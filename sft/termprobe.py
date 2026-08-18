"""Does sampling temperature decide whether the teacher stops explicitly?

    python -m ostg.sft.termprobe --corpus OUT_DIR [--corpus OUT_DIR ...] \
        --endpoint http://127.0.0.1:18020/v1 --model qwen38-27b-local \
        --temps 0.6,1.0 --n 60 --harness /path/to/OSWorld --out probe.jsonl

Why: on the SAME 100 generated tasks, Qwen3.6 ended 96% of trajectories with
an explicit `terminate` and Qwen3.8 ended 13% that way -- the rest as bare
prose the harness scores as DONE. That looked like a teacher-version effect,
but the two campaigns also ran at different sampling temperatures (0.6 vs
1.0), so the comparison cannot separate the two. This replays ONE fixed set of
contexts -- the exact rendered context each trajectory's final step was
produced from -- against ONE model at several temperatures. Model, tasks,
template and prompt are held constant; temperature is the only thing that
moves.

Read the result as: how much of the missing stop signal is a decoding setting
we can change for free, and how much is the model.

The contexts come from a BUILT corpus because build already renders them with
the agent's own message assembly; nothing is re-derived here. Use a corpus
whose terminal step is the trajectory's original ending (not one rewritten by
terminalfix) -- the rewrite changes the target, not the context, but an
untruncated arm keeps the mapping obvious.
"""
import argparse
import base64
import json
import sys
import threading
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def load_terminal_samples(dirs):
    """The final step of every trajectory: (key, sample, build_dir)."""
    latest = {}
    for d in dirs:
        p = Path(d) / "samples.jsonl"
        if not p.is_file():
            continue
        for line in p.open(encoding="utf-8"):
            if not line.strip():
                continue
            s = json.loads(line)
            m = s.get("meta") or {}
            key = (m.get("domain"), m.get("task_id"))
            step = m.get("step") or 0
            if step >= latest.get(key, (0, None, None))[0]:
                latest[key] = (step, s, str(d))
    return [(k, v[1], v[2]) for k, v in sorted(latest.items())]


def to_wire(sample, build_dir):
    """The sample's rendered context as an OpenAI-style message list."""
    out = []
    for msg in sample.get("messages", []):
        c = msg.get("content")
        if not isinstance(c, list):
            out.append({"role": msg["role"], "content": str(c)})
            continue
        parts = []
        for part in c:
            if part.get("type") == "image":
                p = part["path"]
                full = p if Path(p).is_absolute() else str(Path(build_dir) / p)
                b64 = base64.b64encode(Path(full).read_bytes()).decode()
                parts.append({"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + b64}})
            else:
                parts.append({"type": "text", "text": part.get("text", "")})
        out.append({"role": msg["role"], "content": parts})
    return out


def sample_once(endpoint, model, key, msgs, temp, top_p, top_k, kwargs,
                max_tokens=2048, timeout=300):
    body = {"model": model, "messages": msgs, "max_tokens": max_tokens,
            "temperature": temp, "top_p": top_p}
    if top_k:
        body["top_k"] = top_k
    if kwargs:
        body["chat_template_kwargs"] = kwargs
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        msg = json.load(r)["choices"][0]["message"]
    # With thinking enabled vLLM can return content=null and put everything in
    # reasoning_content. Treating that as an empty string silently scores the
    # sample as "prose", and len(None) crashes the summary.
    return msg.get("content") or msg.get("reasoning_content") or ""


def classify(response, parse):
    """What the harness would do with this reply."""
    actions = [str(p.get("action")) for p in parse(response or "")
               if p.get("action")]
    if not actions:
        return "prose->DONE"
    if "terminate" in actions:
        return "terminate"
    if "call_user" in actions:
        return "call_user"
    return "real-action"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", action="append", required=True)
    ap.add_argument("--endpoint", default="http://127.0.0.1:18020/v1")
    ap.add_argument("--model", default="qwen38-27b-local")
    ap.add_argument("--key", default=None)
    ap.add_argument("--harness", default=None)
    ap.add_argument("--temps", default="0.6,1.0")
    ap.add_argument("--top-p", type=float, default=0.95)
    ap.add_argument("--top-k", type=int, default=20)
    ap.add_argument("--n", type=int, default=60,
                    help="trajectories to replay (deterministic prefix, so "
                         "every temperature sees the identical set)")
    ap.add_argument("--repeats", type=int, default=1,
                    help="samples per (context, temperature)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)

    import os
    key = a.key or os.environ.get("OPENAI_API_KEY") or "EMPTY"
    if a.harness:
        sys.path.insert(0, a.harness)
    from mm_agents.qwen.parser import iter_tool_call_params

    temps = [float(x) for x in a.temps.split(",") if x.strip()]
    contexts = load_terminal_samples(a.corpus)[:a.n]
    print("replaying %d terminal contexts at %s" % (len(contexts), temps))

    done = set()
    if a.out.exists():
        for line in a.out.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["domain"], r["task_id"], r["temp"], r["rep"]))

    jobs = [(k, s, d, t, i) for (k, s, d) in contexts for t in temps
            for i in range(a.repeats)
            if (k[0], k[1], t, i) not in done]
    out_f = a.out.open("a", encoding="utf-8")
    lock = threading.Lock()
    tally = defaultdict(Counter)
    n = [0]

    def run(job):
        (domain, task_id), sample, build_dir, temp, rep = job
        meta = sample.get("meta") or {}
        try:
            msgs = to_wire(sample, build_dir)
            reply = sample_once(a.endpoint, a.model, key, msgs, temp,
                                a.top_p, a.top_k,
                                meta.get("chat_template_kwargs"))
            kind = classify(reply, iter_tool_call_params)
            err = None
        except Exception as e:                               # noqa: BLE001
            reply, kind, err = "", "error", "%s: %s" % (type(e).__name__,
                                                        str(e)[:120])
        row = {"domain": domain, "task_id": task_id, "temp": temp,
               "rep": rep, "kind": kind, "chars": len(reply),
               "reply_tail": reply[-400:], "error": err}
        with lock:
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            out_f.flush()
            tally[temp][kind] += 1
            n[0] += 1
            if n[0] % 10 == 0:
                print("  %d/%d" % (n[0], len(jobs)))

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(run, jobs))
    out_f.close()

    print("\n%-6s %s" % ("temp", "ending distribution"))
    for t in temps:
        c = tally[t]
        tot = sum(c.values()) or 1
        print("%-6s %s" % (t, "  ".join(
            "%s %d (%.0f%%)" % (k, v, 100.0 * v / tot)
            for k, v in c.most_common())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
