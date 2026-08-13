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
import json
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
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i",
         str(Path(task_dir) / "recording.mp4"), "-frames:v", "1", str(out_png)],
        capture_output=True)
    return r.returncode == 0 and Path(out_png).is_file()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("result_dir", type=Path)
    ap.add_argument("--tasks", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--osworld", type=Path, default=Path("/mnt/d/research/OSWorld"))
    ap.add_argument("--limit", type=int, default=0, help="max tasks, for smoke runs")
    ap.add_argument("--tail-run", type=int, default=5,
                    help="truncate a trailing run of >= N identical steps")
    ap.add_argument("--initial-fallback", choices=["none", "mp4"], default="none",
                    help="mp4: approximate a missing initial_state.png from "
                         "recording frame 0 (old runs); flagged in meta")
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
                          "tasks_initial_from_mp4", "images_written")}
    samples_f = (out / "samples.jsonl").open("w", encoding="utf-8")

    task_dirs = sorted(p for p in args.result_dir.glob("*/*") if p.is_dir())
    run_id = args.result_dir.name
    for td in task_dirs:
        if args.limit and rep["tasks_passed"] >= args.limit:
            break
        rep["tasks_seen"] += 1
        if traj.score(td) != 1.0:
            continue
        steps = traj.load_steps(td)
        if not steps:
            continue
        rep["tasks_passed"] += 1
        rep["steps_total"] += len(steps)
        domain, task_id = td.parent.name, td.name
        instruction, ost = load_task_meta(args.tasks, domain, task_id)
        slug = ost.get("slug") or task_id

        # obs_files[i] is what the model saw before step i+1: the initial
        # observation, then each step's LAST screenshot (SFT_DATA.md 1.2/1.3)
        img_dir = out / "images" / slug
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
        t = traj.tail_run(steps)
        if t >= args.tail_run:
            keep = len(steps) - t
            rep["dropped_tail_steps"] += t

        written = {}   # obs index -> relative path, copied on first reference

        def obs_path(i):
            if i not in written:
                rel = "images/%s/obs_%03d.png" % (slug, i + 1)
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
            samples_f.write(json.dumps({
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
            rep["samples"] += 1

    samples_f.close()
    (out / "report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
