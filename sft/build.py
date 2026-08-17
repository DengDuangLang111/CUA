"""Build SFT samples from a rollout result directory.

    PYTHONPATH=.:/mnt/d/research/OSWorld python -m ostg.sft.build RESULT_DIR \
        --tasks TASKS_DIR --out OUT_DIR [--limit N] [--tail-run 5] \
        [--initial-fallback mp4]

One sample per step, loss on the final assistant turn only (sft/CONTEXT.md
section 6 says why a packed-conversation format cannot be equivalent). The
context is assembled by the AGENT'S OWN code -- build_messages, the tools
def, the system prompt, the folding state -- imported from mm_agents.qwen,
so the sample structure cannot drift from what the rollout actually sent.
Screenshots are re-encoded with the agent's own process_image, so the pixels
on disk are the pixels the model saw.

Output: OUT_DIR/samples.jsonl  (messages end with the user turn of step k;
                                "response" holds the verbatim target)
        OUT_DIR/images/<slug>/obs_NNN.png
        OUT_DIR/report.json    (what every filter kept and dropped)
"""
import argparse
import base64
import collections
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ostg.sft import traj

SENTINEL = "SFTIMG::"


def load_task_meta(tasks_dir, domain, task_id):
    p = Path(tasks_dir) / "examples" / domain / ("%s.json" % task_id)
    t = json.loads(p.read_text(encoding="utf-8"))
    o = t.get("ostg") or {}
    return t["instruction"], o


def initial_png_from_mp4(task_dir, out_png):
    """Frame 0 of the recording, as an approximation of the initial obs.

    Between _get_obs() and start_recording() nothing touches the VM, so the
    gap is ambient only (a clock tick at worst). Old runs never saved
    initial_state.png; without SOME first image, every sample of the
    trajectory is unbuildable, not just step 1's. Callers must flag the
    approximation in sample meta.
    """
    mp4 = str(Path(task_dir) / "recording.mp4")
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i",
             mp4, "-frames:v", "1", str(out_png)],
            capture_output=True)
        return r.returncode == 0 and Path(out_png).is_file()
    except FileNotFoundError:
        pass
    # No ffmpeg binary. cv2 decodes the frame without any external tool --
    # discovered the hard way 2026-08-15, when a re-run on a WSL box without
    # ffmpeg silently dropped all 39 v11 trajectories (946 steps -> 0 samples).
    try:
        import cv2
        cap = cv2.VideoCapture(mp4)
        ok, frame = cap.read()
        cap.release()
        if ok:
            cv2.imwrite(str(out_png), frame)
            return Path(out_png).is_file()
    except ImportError:
        pass
    if not initial_png_from_mp4.warned:
        print("[build] --initial-fallback mp4 requested but neither ffmpeg "
              "nor cv2 is available; affected trajectories are dropped instead")
        initial_png_from_mp4.warned = True
    return False


initial_png_from_mp4.warned = False


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("result_dir", type=Path)
    ap.add_argument("--tasks", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--osworld", type=Path, default=Path("/mnt/d/research/OSWorld"))
    ap.add_argument("--limit", type=int, default=0, help="max tasks, for smoke runs")
    ap.add_argument("--include", type=Path, default=None,
        help="jsonl of domain/task_id to admit despite a failing checker (curate _rescue)")
    ap.add_argument("--exclude", type=Path, default=None,
        help="jsonl of domain/task_id to drop despite a passing checker (curate _drop / _tier2)")
    ap.add_argument("--whole-traj-filter", action="store_true",
        help="drop cap-hit / DONE-less / illegal-action passing trajectories whole (PLAN-20260816)")
    ap.add_argument("--image-cache", type=Path, default=None,
        help="a prior build dir whose images/ holds identical re-encodes; "
             "referenced images are HARDLINKED from it instead of re-encoded "
             "(deterministic process_image => byte-identical; dirs stay "
             "self-contained -- hardlinked files survive cache deletion)")
    ap.add_argument("--think-cap", type=int, default=0,
        help="drop STEPS whose current-target <think> exceeds N estimated "
             "tokens (chars/3.5); dropped steps stay in later contexts. "
             "Quarantined to think_quarantine.jsonl, never silently lost")
    ap.add_argument("--tail-run", type=int, default=5,
                    help="truncate a trailing run of >= N identical steps")
    ap.add_argument("--initial-fallback", choices=["none", "mp4"], default="none",
                    help="mp4: approximate a missing initial_state.png from "
                         "recording frame 0 (old runs); flagged in meta")
    ap.add_argument("--val-ratio", type=float, default=0.0,
                    help="fraction of TASKS (not samples) held out to "
                         "val_samples.jsonl -- split at slug level so no "
                         "trajectory leaks its prefix into training")
    ap.add_argument("--length-budget", type=int, default=65536,
                    help="token estimate above which a sample is counted as "
                         "at risk of trainer-side truncation")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(args.osworld))
    from mm_agents.qwen.history import build_messages, update_folding_state
    from mm_agents.qwen.images import process_image
    from mm_agents.qwen.main import QwenAgent
    from mm_agents.qwen.prompts import build_instruction_prompt

    # A throwaway agent instance gives us its exact prompt builders. 1920x1088
    # is what smart_resize makes of the campaign's 1920x1080 screens.
    agent = QwenAgent()
    tools_def = agent._build_tools_def(1920, 1088)
    system_prompt = agent._build_system_prompt(tools_def)
    transform = getattr(agent, "_response_transform", lambda t: t)

    out = args.out
    (out / "images").mkdir(parents=True, exist_ok=True)
    rep = {k: 0 for k in ("tasks_seen", "tasks_passed", "steps_total",
                          "samples", "dropped_hallucinated_target",
                          "dropped_tail_steps", "dropped_missing_initial",
                          "tasks_initial_from_mp4", "images_written", "dropped_mid_loop",
                          "recovery_samples", "images_cache_hits",
                          "val_tasks", "val_samples", "over_length_estimate")}
    rep["dropped_whole_traj"] = {}
    rep["dropped_think_cap"] = 0
    quarantine_f = (out / "think_quarantine.jsonl").open("w", encoding="utf-8")
    samples_f = (out / "samples.jsonl").open("w", encoding="utf-8")
    val_f = (out / "val_samples.jsonl").open("w", encoding="utf-8")

    task_dirs = sorted(p for p in args.result_dir.glob("*/*") if p.is_dir())
    run_id = args.result_dir.name
    slug_owner = {}          # slug -> first task_id that claimed it
    rep["slug_collisions"] = 0

    def slugs(path):
        return {(json.loads(l)["domain"], json.loads(l)["task_id"])
                for l in Path(path).read_text().splitlines() if l.strip()}

    # The checker's verdict is the default admission rule; curate lists
    # override it in both directions -- --include admits trajectories the
    # checker failed but arbitration ruled checker_bug_strict (冤案赎回),
    # --exclude drops passes arbitration convicted (or any list you hand it).
    inc = slugs(args.include) if args.include else set()
    exc = slugs(args.exclude) if args.exclude else set()

    def admitted(td):
        k = (td.parent.name, td.name)
        if k in exc:
            return False
        return traj.score(td) == 1.0 or k in inc
    rep["admitted_via_include"] = 0
    rep["excluded_by_list"] = 0
    # A requested split must never come back empty (a hash draw over few
    # tasks can miss everyone): reserve the lexicographically first passing
    # slug as guaranteed val when the draw selects none.
    fallback_val_slug = None
    if args.val_ratio > 0:
        for td in task_dirs:
            if admitted(td):
                _, o = load_task_meta(args.tasks, td.parent.name, td.name)
                s = o.get("slug") or td.name
                if (fallback_val_slug is None or s < fallback_val_slug) and \
                   int(hashlib.md5(s.encode()).hexdigest(), 16) % 1000 \
                   >= args.val_ratio * 1000:
                    fallback_val_slug = s
        drawn = any(
            int(hashlib.md5((load_task_meta(args.tasks, td.parent.name, td.name)[1].get("slug")
                             or td.name).encode()).hexdigest(), 16) % 1000
            < args.val_ratio * 1000
            for td in task_dirs if admitted(td))
        if drawn:
            fallback_val_slug = None
    for td in task_dirs:
        if args.limit and rep["tasks_passed"] >= args.limit:
            break
        rep["tasks_seen"] += 1
        k = (td.parent.name, td.name)
        if not admitted(td):
            rep["excluded_by_list"] += 1 if k in exc else 0
            continue
        rep["admitted_via_include"] += 1 if traj.score(td) != 1.0 else 0
        steps = traj.load_steps(td)
        if not steps:
            continue
        if args.whole_traj_filter:
            why = traj.whole_traj_reject(steps)
            if why:
                rep["dropped_whole_traj"][f"{td.parent.name}/{td.name}"] = why
                continue
        rep["tasks_passed"] += 1
        rep["steps_total"] += len(steps)
        domain, task_id = td.parent.name, td.name
        instruction, ost = load_task_meta(args.tasks, domain, task_id)
        slug = ost.get("slug") or task_id
        # deterministic task-level split: stable across rebuilds, no
        # step-of-same-trajectory leakage between train and val
        is_val = (args.val_ratio > 0 and
                  (slug == fallback_val_slug or
                   int(hashlib.md5(slug.encode()).hexdigest(), 16) % 1000
                   < args.val_ratio * 1000))
        if is_val:
            rep["val_tasks"] += 1

        # v11-500 has 3 slug collisions across 444 tasks (441 unique). With a
        # slug-keyed image dir the second task silently OVERWRITES the first's
        # screenshots, leaving the first trajectory's samples pointing at
        # another task's pixels -- invisible until a hardlink trips over it
        # (2026-08-17). Colliding tasks get a task-id suffix; everyone else
        # keeps the bare slug so --image-cache still hits.
        if slug_owner.setdefault(slug, task_id) == task_id:
            img_key = slug
        else:
            img_key = "%s-%s" % (slug, task_id[:8])
            rep["slug_collisions"] += 1

        # obs_files[i] is what the model saw before step i+1: the initial
        # observation, then each step's LAST screenshot (SFT_DATA.md 1.2/1.3)
        img_dir = out / "images" / img_key
        img_dir.mkdir(parents=True, exist_ok=True)
        initial_from = "initial_state.png"
        init = td / "initial_state.png"
        if not init.is_file() and args.initial_fallback == "mp4":
            init = img_dir / "_frame0_raw.png"
            if initial_png_from_mp4(td, init):
                initial_from = "recording.mp4"
                rep["tasks_initial_from_mp4"] += 1
        if not init.is_file():
            rep["dropped_missing_initial"] += len(steps)
            continue
        obs_files = [init] + [td / s.screenshot for s in steps[:-1]]

        keep = len(steps)
        cap_hit = len(steps) >= 50
        t = traj.low_diversity_tail(steps) if cap_hit else traj.tail_run(steps)
        if t >= (8 if cap_hit else args.tail_run):
            keep = len(steps) - t
            rep["dropped_tail_steps"] += t
        mid_drops = traj.identical_runs(steps[:keep])

        written = {}   # obs index -> relative path, copied on first reference

        def obs_path(i):
            if i not in written:
                rel = "images/%s/obs_%03d.png" % (img_key, i + 1)
                cached = args.image_cache / rel if args.image_cache else None
                if cached and cached.is_file() and cached.stat().st_size > 0:
                    try:
                        os.link(cached, out / rel)
                    except OSError:
                        shutil.copyfile(cached, out / rel)
                    rep["images_cache_hits"] += 1
                else:
                    # the agent's own resize: pixels on disk == pixels it saw
                    b64 = process_image(obs_files[i].read_bytes())
                    (out / rel).write_bytes(base64.b64decode(b64))
                    rep["images_written"] += 1
                written[i] = rel
            return written[i]

        for k in range(1, keep + 1):
            step = steps[k - 1]
            if step.hallucinated:
                rep["dropped_hallucinated_target"] += 1
                continue
            if args.think_cap:
                _est = traj.think_est_tokens(step.response)
                if _est > args.think_cap:
                    rep["dropped_think_cap"] += 1
                    quarantine_f.write(json.dumps({
                        "domain": domain, "task_id": task_id, "step": k,
                        "est_think_tokens": _est,
                        "response": step.response}, ensure_ascii=False) + "\n")
                    continue
            if (k - 1) in mid_drops:
                rep["dropped_mid_loop"] += 1
                continue
            # A surviving target whose context already contains a long run of
            # one action, and which does something else, is the corpus's only
            # demonstration of getting unstuck. Counted because it is scarce
            # and because an earlier filter proposal would have deleted it.
            if k > 1:
                _c = collections.Counter(tuple(s.actions) for s in steps[:k - 1])
                _top, _n = _c.most_common(1)[0]
                if _n >= 8 and tuple(step.actions) != _top:
                    rep["recovery_samples"] += 1
            fold = update_folding_state(k, 0, agent.image_max, agent.fold_size)
            msgs = build_messages(
                system_prompt=system_prompt,
                instruction_prompt=build_instruction_prompt(instruction, "None"),
                screenshots=[SENTINEL + str(i) for i in range(k)],
                responses=[s.response for s in steps[:k - 1]],
                start_step=1, total_steps=k, folded_prefix_k=fold,
                collapse_text=agent.collapse_text,
                response_transform=transform)
            # swap the sentinel data-URLs for image paths, copying lazily so
            # collapsed screenshots are never written at all
            for m in msgs:
                m["content"] = [
                    {"type": "image",
                     "path": obs_path(int(p["image_url"]["url"].split(SENTINEL, 1)[1]))}
                    if p.get("type") == "image_url" else p
                    for p in m["content"]]
            n_imgs = sum(1 for m in msgs for p in m["content"]
                         if p.get("type") == "image")
            n_chars = sum(len(p.get("text", "")) for m in msgs
                          for p in m["content"]) + len(step.response)
            if n_imgs * 2040 + n_chars / 3.5 > args.length_budget:
                rep["over_length_estimate"] += 1
            (val_f if is_val else samples_f).write(json.dumps({
                "messages": msgs,
                "response": step.response,
                "meta": {"run": run_id, "domain": domain, "slug": slug,
                         "task_id": task_id, "step": k, "n_steps": len(steps),
                         "difficulty": ost.get("difficulty"),
                         "ambiguity": ost.get("ambiguity"),
                         "coord": "relative-0-999",
                         "processed_screen": "1920x1088",
                         "initial_from": initial_from,
                         "chat_template_kwargs": {"enable_thinking": True}},
            }, ensure_ascii=False) + "\n")
            rep["val_samples" if is_val else "samples"] += 1

    samples_f.close()
    val_f.close()
    quarantine_f.close()
    (out / "report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
