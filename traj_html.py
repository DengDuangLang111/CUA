"""HTML view of a rollout result dir: index + one page per task.

    python -m ostg.traj_html RESULT_DIR --tasks out/runs/v8big-all

Reads <domain>/<id>/{traj.jsonl,result.txt,step_*.png}; writes viewer.html
beside each trajectory and index.html at the root. No dependencies, no
server: open index.html in a browser, images load from the task dirs.
"""
import argparse
import glob
import html
import json
import os

PAGE = ("<!doctype html><meta charset=utf-8><title>%s</title><style>"
        "body{font:14px/1.5 sans-serif;margin:2em auto;max-width:1100px;padding:0 1em}"
        "img{max-width:100%%;border:1px solid #ccc}"
        "pre{white-space:pre-wrap;background:#f6f6f6;padding:.6em;overflow-x:auto}"
        ".step{margin:1.5em 0;border-top:2px solid #333;padding-top:.5em}"
        ".pass{color:#00701a;font-weight:bold}.fail{color:#b00020;font-weight:bold}"
        "table{border-collapse:collapse}td,th{border:1px solid #999;padding:.3em .6em;text-align:left}"
        "</style>")


def score_of(td):
    f = os.path.join(td, "result.txt")
    if not os.path.isfile(f):
        return None
    try:
        return float(open(f).read().strip())
    except ValueError:
        return None


def task_page(td, meta):
    steps = [json.loads(l) for l in open(os.path.join(td, "traj.jsonl"), encoding="utf-8")
             if l.strip()]
    score = score_of(td)
    cls = "pass" if score == 1.0 else "fail"
    title = meta.get("slug") or os.path.basename(td)
    out = [PAGE % html.escape(title),
           "<h2>%s <span class=%s>score %s</span></h2>" % (html.escape(title), cls, score),
           "<p><b>%s</b></p>" % html.escape(meta.get("instruction", ""))]
    for s in steps:
        out.append("<div class=step><h3>step %s</h3>" % s.get("step_num"))
        out.append("<pre>%s</pre>" % html.escape((s.get("response") or "").strip()))
        out.append("<p><code>%s</code></p>" % html.escape(str(s.get("action"))))
        png = s.get("screenshot_file")
        if png and os.path.isfile(os.path.join(td, png)):
            out.append('<p><img loading=lazy src="%s"></p>' % png)
        out.append("</div>")
    open(os.path.join(td, "viewer.html"), "w", encoding="utf-8").write("\n".join(out))
    return score, len(steps)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("result_dir")
    ap.add_argument("--tasks", default=None, help="run dir with examples/, for slug + instruction")
    a = ap.parse_args()
    meta = {}
    if a.tasks:
        for f in glob.glob(os.path.join(a.tasks, "examples", "*", "*.json")):
            j = json.load(open(f, encoding="utf-8"))
            meta[j["id"]] = {"slug": (j.get("ostg") or {}).get("slug", j["id"]),
                             "instruction": j.get("instruction", "")}
    rows = []
    for tj in sorted(glob.glob(os.path.join(a.result_dir, "*", "*", "traj.jsonl"))):
        td = os.path.dirname(tj)
        m = meta.get(os.path.basename(td), {})
        score, n = task_page(td, m)
        rows.append((os.path.basename(os.path.dirname(td)),
                     m.get("slug", os.path.basename(td)), score, n,
                     os.path.relpath(os.path.join(td, "viewer.html"), a.result_dir)))
    done = [r for r in rows if r[2] is not None]
    passed = sum(1 for r in rows if r[2] == 1.0)
    idx = [PAGE % "rollout index",
           "<h2>%s</h2>" % html.escape(os.path.basename(os.path.normpath(a.result_dir))),
           "<p>%d trajectories, %d scored, %d passed</p>" % (len(rows), len(done), passed),
           "<table><tr><th>domain<th>task<th>score<th>steps"]
    for dom, slug, score, n, rel in rows:
        cls = "pass" if score == 1.0 else "fail"
        idx.append('<tr><td>%s<td><a href="%s">%s</a><td class=%s>%s<td>%d'
                   % (dom, rel, html.escape(slug), cls, score, n))
    idx.append("</table>")
    open(os.path.join(a.result_dir, "index.html"), "w", encoding="utf-8").write("\n".join(idx))
    print("index.html + %d viewer.html -> %s" % (len(rows), a.result_dir))


if __name__ == "__main__":
    main()
