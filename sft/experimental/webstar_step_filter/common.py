"""Shared identity, provenance, and source-index helpers."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
ACTION_RE = re.compile(
    r"<parameter=action>\s*([a-z_]+)\s*</parameter>", re.IGNORECASE)


@dataclass(frozen=True, order=True)
class StepKey:
    source_build: str
    run: str
    domain: str
    task_id: str
    step: int

    @classmethod
    def from_dict(cls, row):
        return cls(
            str(row["source_build"]), str(row["run"]),
            str(row["domain"]), str(row["task_id"]), int(row["step"]))

    def as_dict(self):
        return {
            "source_build": self.source_build,
            "run": self.run,
            "domain": self.domain,
            "task_id": self.task_id,
            "step": self.step,
        }

    def text(self):
        return "/".join((self.source_build, self.run, self.domain,
                         self.task_id, str(self.step)))


@dataclass
class SourceRow:
    key: StepKey
    source_dir: Path
    sample: dict


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_text(text):
    return sha256_bytes(str(text).encode("utf-8"))


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_named_paths(values, flag_name):
    out = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError(f"{flag_name} expects NAME=PATH, got {value!r}")
        name, path = value.split("=", 1)
        name, path = name.strip(), Path(path).expanduser()
        if not name or name in out:
            raise ValueError(f"invalid or duplicate {flag_name} name: {name!r}")
        out[name] = path
    return out


def iter_jsonl(path):
    with Path(path).open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_no}: invalid JSON") from exc


def key_for_sample(source_build, sample):
    meta = sample.get("meta") or {}
    missing = [name for name in ("run", "domain", "task_id", "step")
               if meta.get(name) is None]
    if missing:
        raise ValueError(f"sample missing meta fields {missing}: {meta}")
    return StepKey(source_build, str(meta["run"]), str(meta["domain"]),
                   str(meta["task_id"]), int(meta["step"]))


def load_source_rows(source_dirs):
    """Index every neutral source row by collision-proof step identity."""
    index, reports = {}, {}
    for name, source_dir in source_dirs.items():
        path = Path(source_dir) / "samples.jsonl"
        if not path.is_file():
            raise FileNotFoundError(f"missing source samples: {path}")
        count = 0
        for sample in iter_jsonl(path):
            key = key_for_sample(name, sample)
            if key in index:
                raise ValueError(f"duplicate source step key: {key.text()}")
            index[key] = SourceRow(key, Path(source_dir), sample)
            count += 1
        reports[name] = {
            "path": str(path.resolve()),
            "rows": count,
            "sha256": sha256_file(path),
        }
    return index, reports


def target_action_text(response):
    """Remove teacher thought; the paper's judge evaluates the action only."""
    stripped = THINK_RE.sub("", response or "").strip()
    return stripped or "[No explicit proposed action text]"


def action_names(response):
    return [x.lower() for x in ACTION_RE.findall(response or "")]


def action_signature(response):
    names = action_names(response)
    return "+".join(names) if names else "no_action_tag"


def think_est_tokens(response):
    m = re.search(r"<think>(.*?)</think>", response or "",
                  re.DOTALL | re.IGNORECASE)
    return int(len(m.group(1)) / 3.5) if m else 0


def is_terminal_sample(sample):
    meta = sample.get("meta") or {}
    return int(meta.get("step") or 0) == int(meta.get("n_steps") or -1)


def has_explicit_done(response):
    # A prose sentence such as "task done" is not an executed stop signal.
    return bool({"terminate", "done"} & set(action_names(response)))


def stable_rank(key, seed):
    raw = f"{seed}|{key.text()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
