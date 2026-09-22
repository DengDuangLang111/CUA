"""Opt-in rendered archives. Raw deletion happens only after verified publication.

Heatmaps retain both display scales as 8-bit PNG pixels; numerical image-level
statistics stay exact. This is deliberately not a lossless attention archive.
"""
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import statistics

from .attention_store import file_hash
from .visual_signals import read_json, write_json

POLICIES = ("keep", "delete-after-export")
RENDER_VERSION = "png6-f64-v2"


def write_gzip_json(path, value):
    path = Path(path)
    target = path.with_suffix(path.suffix + ".gz")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as stream:
                with io.TextIOWrapper(stream, encoding="utf-8") as text:
                    json.dump(value, text, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            raw.flush()
            os.fsync(raw.fileno())
        # Validate the compressed JSON before replacing a previous generated file.
        with gzip.open(temporary, "rt", encoding="utf-8") as stream:
            json.load(stream)
        temporary.replace(target)
        path.unlink(missing_ok=True)
    finally:
        temporary.unlink(missing_ok=True)


class HeatmapWriter:
    """One packed PNG file per decision avoids millions of tiny image files."""
    def __init__(self, output, relative):
        self.output, self.relative = Path(output), relative
        self.path = self.output / relative
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.temporary = self.path.with_suffix(".tmp")
        self.stream = self.temporary.open("wb")
        self.rows = []

    def __call__(self, summary, images, values):
        from PIL import Image
        import numpy as np
        flat = np.concatenate([np.asarray(image, dtype=np.float64) for image in values]) if values else np.array([])
        if not flat.size:
            raise ValueError("Cannot render attention without image patches")
        if not np.isfinite(flat).all() or (flat < 0).any():
            raise ValueError("Invalid attention weights")
        maximum = float(flat.max())
        positive = flat[flat > 0]
        pivot = float(np.median(positive)) if positive.size else 1.0
        denominator = math.log1p(maximum / pivot) if maximum else 1.0
        def quantize(logarithmic):
            if not maximum:
                return bytes(flat.size)
            scaled = (np.log1p(flat / pivot) / denominator if logarithmic else flat / maximum) * 255
            rounded = np.rint(scaled)
            # Preserve Python's original rounding at floating-point half boundaries.
            for i in np.flatnonzero(np.abs(scaled - np.floor(scaled) - .5) < 1e-10):
                value = float(flat[i])
                rounded[i] = round((math.log1p(value / pivot) / denominator if logarithmic else value / maximum) * 255)
            return rounded.astype(np.uint8).tobytes()
        linear, logarithmic = quantize(False), quantize(True)
        pixels = linear + logarithmic
        width, height = 256, (len(pixels) + 255) // 256
        pixels += b"\0" * (width * height - len(pixels))
        encoded = io.BytesIO()
        Image.frombytes("L", (width, height), pixels).save(encoded, format="PNG", compress_level=6)
        data = encoded.getvalue()
        # Round-trip check every PNG before accepting it as a raw-data replacement.
        with Image.open(io.BytesIO(data)) as image:
            if image.mode != "L" or image.size != (width, height) or image.tobytes() != pixels:
                raise ValueError("Rendered PNG round-trip failed")
        ref = dict(src=self.relative, offset=self.stream.tell(), length=len(data),
                   sha256=hashlib.sha256(data).hexdigest(), codec="png-u8-linear-log",
                   value_count=len(flat), width=width, height=height)
        self.stream.write(data)
        self.rows.append(ref)
        summary.pop("weights", None)
        summary.pop("weights_ref", None)
        for frame in summary["frames"]:
            frame.pop("weights", None)
        summary.update(render_ref=ref, render_scale=dict(max=maximum, pivot=pivot),
                       precision="rendered 8-bit intensity; exact patch weights not retained")

    def finish(self):
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.stream.close()
        self.temporary.replace(self.path)
        with self.path.open("rb") as stream:
            for ref in self.rows:
                stream.seek(ref["offset"])
                if hashlib.sha256(stream.read(ref["length"])).hexdigest() != ref["sha256"]:
                    raise ValueError("Published heatmap bytes differ from validated PNG")
        return self.path

    def close(self):
        if not self.stream.closed:
            self.stream.close()
        self.temporary.unlink(missing_ok=True)


def task_fingerprint(task):
    return {str(p.relative_to(task)): file_hash(p) for p in
            [task / "traj.jsonl", task / "result.txt", task / "capture/manifest.json", task / "capture/events.jsonl"] if p.is_file()}


def contains_record(saved, original):
    """SDK defaults may add fields; every original response field must survive."""
    if isinstance(original, dict):
        return isinstance(saved, dict) and all(k in saved and contains_record(saved[k], v) for k, v in original.items())
    if isinstance(original, list):
        return isinstance(saved, list) and len(saved) == len(original) and all(contains_record(a,b) for a,b in zip(saved,original))
    return saved == original


class RenderedArchive:
    def __init__(self, task, output, key, resume=True):
        self.task, self.output, self.key = Path(task), Path(output), key
        self.archive = f"archives/{key}.jsonl.gz"
        self.receipt = self.output / "retention" / (key + ".json")
        self.fingerprint = task_fingerprint(self.task)
        self.sources, self.records, self.artifacts = {}, {}, []
        self.writer = None
        self.sequence = 0
        self.expected_rows = self.rendered_rows = 0
        self.resume = resume
        self.current_record = None
        self.restored = None
        self.verified_sources = {}
        source = self.task / "visual_signals.jsonl"
        target = self.output / self.archive
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        text_cache = self.output / "resume" / (key + "-archive.json")
        try:
            cached = read_json(text_cache, {}) if resume else {}
        except (OSError, ValueError):
            cached = {}
        if (cached.get("fingerprint") == self.fingerprint and target.is_file()
                and cached.get("source_sha256") == file_hash(source)
                and cached.get("archive_sha256") == file_hash(target)):
            self.records = {int(k): v for k, v in cached["records"].items()}
            self.sources = cached["sources"]
            self.expected_rows = cached["expected_rows"]
            self.artifacts.append(target)
            return
        original_hash = hashlib.sha256()
        try:
            with source.open("rb") as src, temporary.open("wb") as dst:
                while True:
                    original_offset = src.tell()
                    line = src.readline()
                    if not line:
                        break
                    original_hash.update(line)
                    compressed = gzip.compress(line, compresslevel=6, mtime=0)
                    ref = dict(src=self.archive, offset=dst.tell(), length=len(compressed),
                               codec="gzip-json", sha256=hashlib.sha256(compressed).hexdigest())
                    dst.write(compressed)
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    self.records[original_offset] = ref
                    self.expected_rows += len(record.get("attention", []))
                    for row in record.get("attention", []):
                        if "weights" in row:
                            raise ValueError("Cleanup requires binary attention; inline weights would remain in the text archive")
                        path = (self.task / row["weights_ref"]["path"]).resolve()
                        if not path.is_relative_to((self.task / "capture/attention").resolve()) or path.suffix != ".attn":
                            raise ValueError("Unexpected raw attention path")
                        self.sources[str(path)] = dict(sha256=row["weights_ref"].get("sha256"), size=path.stat().st_size)
                    for attempt in record.get("transport_attempts", []):
                        body = attempt.get("body") or {}
                        name = body.get("path")
                        if not isinstance(name, str):
                            continue
                        response = (self.task / name).resolve()
                        if (response.parent == (self.task / "capture/assets").resolve()
                                and response.name.endswith(".response.json") and response.is_file()
                                and contains_record(record.get("api_response"), read_json(response))):
                            self.sources[str(response)] = dict(sha256=file_hash(response), size=response.stat().st_size)
                    request_id = record.get("request_id")
                    if isinstance(request_id, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", request_id):
                        request = self.task / "capture/requests" / (request_id + ".json")
                        if request.is_file() and read_json(request) == record:
                            self.sources[str(request.resolve())] = dict(sha256=file_hash(request), size=request.stat().st_size)
                dst.flush()
                os.fsync(dst.fileno())
            digest = hashlib.sha256()
            with gzip.open(temporary, "rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.digest() != original_hash.digest():
                raise ValueError("Canonical text archive differs from source JSONL")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        self.sources[str(source.resolve())] = dict(sha256=original_hash.hexdigest(), size=source.stat().st_size)
        self.artifacts.append(target)
        if resume:
            write_json(text_cache, dict(fingerprint=self.fingerprint, source_sha256=original_hash.hexdigest(),
                archive_sha256=file_hash(target), records=self.records, sources=self.sources, expected_rows=self.expected_rows))

    def restore(self, record):
        """Reuse a whole verified decision; incomplete temporary files are never reused."""
        self.current_record = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"),
                                                        allow_nan=False).encode()).hexdigest()
        self.restored = None
        if not self.resume:
            return None
        cache = self.output / "resume" / f"{self.key}-{self.sequence}.json"
        try:
            saved = read_json(cache, {})
            if saved.get("version") != RENDER_VERSION or saved.get("record_sha256") != self.current_record:
                return None
            signal_path = self.output / f"signals/{self.key}-{self.sequence}.json.gz"
            heat_path = self.output / f"heatmaps/{self.key}-{self.sequence}.heat"
            if file_hash(signal_path) != saved["signal_sha256"] or file_hash(heat_path) != saved["heat_sha256"]:
                return None
            # Record identities alone are insufficient if a raw source was modified.
            for row in record.get("attention", []):
                ref = row.get("weights_ref", {})
                path = (self.task / ref.get("path", "")).resolve()
                if not path.is_relative_to((self.task / "capture/attention").resolve()):
                    return None
                stat = path.stat()
                identity = (str(path), stat.st_ino, stat.st_size, stat.st_mtime_ns)
                if identity not in self.verified_sources:
                    self.verified_sources[identity] = file_hash(path)
                if self.verified_sources[identity] != ref.get("sha256"):
                    return None
            stored = read_json(signal_path.with_suffix(""))
            self.restored = heat_path
            return stored["attention"], stored["attention_overviews"]
        except (OSError, ValueError, KeyError, TypeError):
            return None  # Raw data remains available for a complete re-render.

    def begin(self, record):
        self.writer = HeatmapWriter(self.output, f"heatmaps/{self.key}-{self.sequence}.heat")
        return self.writer

    def save(self, frame, relative):
        if self.writer:
            self.artifacts.append(self.writer.finish())
            self.rendered_rows += len(self.writer.rows)
            self.writer = None
        if self.restored:
            self.artifacts.append(self.restored)
            self.rendered_rows += len(frame["signals"]["attention"])
            self.restored = None
        signal = dict(frame["signals"])
        signal["input_token_count"] = len(signal["input_token_ids"]) if isinstance(signal.get("input_token_ids"), list) else None
        signal["raw_fields"] = [k for k in ("api_response", "request", "input_token_ids") if k in signal]
        for key in signal["raw_fields"]:
            signal.pop(key)
        signal.pop("request_file", None)
        signal["transport_attempts"] = [dict(attempt) for attempt in signal.get("transport_attempts", [])]
        for attempt in signal["transport_attempts"]:
            name = (attempt.get("body") or {}).get("path")
            if name and str((self.task / name).resolve()) in self.sources:
                body = attempt.pop("body")
                attempt.update(body_sha256=body.get("sha256"), body_storage="Structured API response retained in the canonical archive")
        signal["raw_details_ref"] = self.records[frame.pop("_signal_offset")]
        signal["raw_retention"] = "rendered-only"
        write_gzip_json(self.output / relative, signal)
        self.artifacts.append((self.output / relative).with_suffix(".json.gz"))
        if self.resume and self.current_record:
            write_json(self.output / "resume" / f"{self.key}-{self.sequence}.json",
                dict(version=RENDER_VERSION, record_sha256=self.current_record,
                     signal_sha256=file_hash((self.output / relative).with_suffix(".json.gz")),
                     heat_sha256=file_hash(self.output / f"heatmaps/{self.key}-{self.sequence}.heat")))
        frame.update(signals=None, signals_url=relative, signal_source=self.archive)
        self.sequence += 1

    def finalize(self, bundle, entries):
        # Incomplete or failed captures never authorize cleanup.
        if bundle["validation"]["status"] != "passed" or not (self.task / "result.txt").is_file():
            return
        result = float((self.task / "result.txt").read_text().strip())
        if not math.isfinite(result) or not 0 <= result <= 1:
            return
        if self.rendered_rows != self.expected_rows:
            raise ValueError("Not every captured attention row has a verified rendered result; retaining raw data")
        if self.fingerprint != task_fingerprint(self.task):
            raise ValueError("Task changed during export; retaining raw data")
        video = self.task / "recording.mp4"
        if video.is_file() and str(video.resolve()) not in bundle["assets"].values():
            self.sources[str(video.resolve())] = dict(sha256=file_hash(video), size=video.stat().st_size)
        for name, info in self.sources.items():
            digest = file_hash(name)
            if info["sha256"] and digest != info["sha256"]:
                raise ValueError("Raw data changed; retaining all source files")
            info["sha256"] = digest
        artifacts = self.artifacts + [self.output / f"tasks/{self.key}.json", self.output / f"task-{self.key}.html",
                                     self.output / f"validation/{self.key}.json"]
        receipt = dict(policy="delete-after-export", status="ready", task=str(self.task.resolve()),
            fingerprint=self.fingerprint, sources=self.sources,
            artifacts={str(p.relative_to(self.output)): file_hash(p) for p in artifacts},
            retained_assets={p: file_hash(p) for p in set(bundle["assets"].values()) if p not in self.sources},
            entries=entries, producer_cache="not managed; this policy only covers this task's local capture artifacts")
        write_json(self.receipt, receipt)
        finish_cleanup(self.task, self.output, self.key)

    def close(self):
        if self.writer:
            self.writer.close()


def finish_cleanup(task, output, key):
    """Verify durable exports first; resumable, narrowly scoped raw deletion."""
    task, output = Path(task).resolve(), Path(output).resolve()
    path = output / "retention" / (key + ".json")
    receipt = read_json(path)
    if not receipt:
        return None
    if receipt["task"] != str(task) or receipt["fingerprint"] != task_fingerprint(task):
        raise ValueError("Task changed after archive; refusing cleanup or stale-page reuse")
    # HTML may be regenerated for UI updates after cleanup; original data artifacts must remain intact.
    for relative, expected in receipt["artifacts"].items():
        artifact = (output / relative).resolve()
        if not artifact.is_relative_to(output):
            raise ValueError("Archive path outside output directory")
        if receipt['status'] == 'deleted' and artifact.suffix == '.html':
            continue
        if file_hash(artifact) != expected:
            raise ValueError("Archive missing or changed; retaining remaining raw data")
    for name, expected in receipt.get("retained_assets", {}).items():
        if file_hash(name) != expected:
            raise ValueError("Retained screenshots or task records changed; refusing cleanup")
    if receipt["status"] != "deleted":
        for name, info in receipt["sources"].items():
            candidate = Path(name)
            if candidate.is_symlink():
                raise ValueError("Refusing symlink cleanup candidate")
            source = candidate.resolve()
            allowed = (source == task / "visual_signals.jsonl" or
                       source.parent == task / "capture/requests" and source.suffix == ".json" or
                       source.parent == task / "capture/assets" and source.name.endswith(".response.json") or
                       source == task / "recording.mp4" or
                       source.is_relative_to(task / "capture/attention") and source.suffix == ".attn")
            if not allowed or source.is_symlink():
                raise ValueError("Cleanup candidate outside the authorized raw paths")
            if source.exists() and file_hash(source) != info["sha256"]:
                raise ValueError("Cleanup candidate changed after publication")
        for name in receipt["sources"]:
            Path(name).unlink(missing_ok=True)
        import fcntl
        with (output / ".index.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            manifest = read_json(output / "manifest.json")
            manifest["assets"] = {k: v for k, v in manifest["assets"].items() if v not in receipt["sources"]}
            write_json(output / "manifest.json", manifest)
        receipt["status"] = "deleted"
        receipt["deleted_bytes"] = sum(v["size"] for v in receipt["sources"].values())
        write_json(path, receipt)
    return receipt["entries"]


def read_archive_record(output, ref):
    path = (Path(output) / ref['src']).resolve()
    if not path.is_relative_to(Path(output).resolve()) or ref['codec'] != 'gzip-json':
        raise ValueError('Invalid canonical record reference')
    if type(ref['offset']) is not int or type(ref['length']) is not int or ref['offset'] < 0 or ref['length'] <= 0:
        raise ValueError('Invalid canonical record byte range')
    with path.open('rb') as stream:
        stream.seek(ref['offset']); data = stream.read(ref['length'])
    if hashlib.sha256(data).hexdigest() != ref['sha256']:
        raise ValueError('Canonical record chunk is missing or corrupt')
    return json.loads(gzip.decompress(data))
