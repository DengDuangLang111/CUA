"""HTML view of a rollout result dir: index + a step player per task.

    python -m ostg.traj_html RESULT_DIR --tasks out/runs/v8big-all

Reads <domain>/<id>/{traj.jsonl,result.txt,step_*.png}; writes viewer.html
beside each trajectory and index.html at the root. Self-contained: inline
CSS/JS, no dependencies, works over file:// or any static server.
"""
import argparse
import glob
import html
import json
import os

CSS = """
*{box-sizing:border-box}
body{font:15px/1.55 -apple-system,'Segoe UI',Roboto,sans-serif;margin:0;
     background:#f4f5f7;color:#1c1e21}
.wrap{max-width:1150px;margin:0 auto;padding:1.2em 1em 4em}
h2{margin:.3em 0 .2em}
a{color:#1a63c9;text-decoration:none} a:hover{text-decoration:underline}
.badge{display:inline-block;padding:.1em .6em;border-radius:1em;font-size:.8em;
       font-weight:600;color:#fff;vertical-align:middle}
.pass{background:#1e8e3e}.fail{background:#c5221f}.none{background:#9aa0a6}
.instr{background:#fff;border-left:4px solid #1a63c9;padding:.7em 1em;
       border-radius:0 8px 8px 0;box-shadow:0 1px 2px rgba(0,0,0,.08)}
.meta{margin:.5em 0;font-size:.9em;color:#5f6368}
.nav{position:sticky;top:0;z-index:5;background:#fff;border-radius:10px;
     box-shadow:0 2px 8px rgba(0,0,0,.12);padding:.55em .9em;margin:.8em 0;
     display:flex;align-items:center;gap:.7em;flex-wrap:wrap}
.nav button{font:inherit;padding:.35em 1em;border:1px solid #dadce0;
     border-radius:8px;background:#fff;cursor:pointer}
.nav button:hover{background:#f1f3f4}
.nav input[type=range]{flex:1;min-width:120px}
#pos{font-weight:600;min-width:5.5em;text-align:center}
.frame{background:#fff;border-radius:10px;box-shadow:0 1px 3px rgba(0,0,0,.1);
       padding:1em 1.2em;margin:.8em 0}
.frame h3{margin:.1em 0 .5em}
.frame h3 small{color:#5f6368;font-weight:400}
.blk{border:1px solid #e3e6ea;border-left-width:4px;border-radius:8px;
     padding:.55em .9em .6em;margin:.55em 0;white-space:pre-wrap;
     font-size:.92em;background:#fbfcfd}
.blk .tag{display:block;font-size:.7em;font-weight:700;letter-spacing:.08em;
     margin:0 0 .35em;font-family:-apple-system,'Segoe UI',sans-serif}
.b-think{border-left-color:#8a94a6}.b-think .tag{color:#8a94a6}
.b-act{border-left-color:#1a73e8}.b-act .tag{color:#1a73e8}
.b-tool{border-left-color:#b0b6bf;font-family:ui-monospace,Menlo,Consolas,monospace;
        font-size:.85em}.b-tool .tag{color:#9aa0a6}
.b-exec{border-left-color:#1e8e3e;font-family:ui-monospace,Menlo,Consolas,monospace;
        font-size:.88em}.b-exec .tag{color:#1e8e3e}
.resp{background:#f8f9fa;border:1px solid #eceff1;border-radius:8px;
      padding:.6em .9em;white-space:pre-wrap;overflow-x:auto;font-size:.9em;
      font-family:ui-monospace,Menlo,Consolas,monospace}
img.shot{max-width:100%;border:1px solid #dadce0;border-radius:8px;margin-top:.5em}
table{border-collapse:collapse;width:100%;background:#fff;border-radius:10px;
      overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.1)}
th,td{padding:.5em .8em;text-align:left;border-bottom:1px solid #eceff1}
th{background:#f8f9fa;position:sticky;top:0}
tr:hover td{background:#f8fbff}
details{margin:.5em 0}
summary{cursor:pointer;color:#5f6368}
.chips{display:flex;gap:.6em;margin:.6em 0;flex-wrap:wrap}
.chip{background:#fff;border-radius:2em;padding:.3em 1em;
      box-shadow:0 1px 2px rgba(0,0,0,.08);font-size:.9em}
"""

JS = """
const frames=[...document.querySelectorAll('.frame')];
let cur=0, all=false;
const pos=document.getElementById('pos'), rng=document.getElementById('rng');
function show(i){
  cur=Math.max(0,Math.min(frames.length-1,i));
  frames.forEach((f,k)=>f.style.display=(all||k===cur)?'':'none');
  pos.textContent=(cur+1)+' / '+frames.length; rng.value=cur;
  if(!all) window.scrollTo({top:0});
}
document.getElementById('prev').onclick=()=>show(cur-1);
document.getElementById('next').onclick=()=>show(cur+1);
rng.oninput=e=>show(+e.target.value);
document.getElementById('all').onclick=e=>{all=!all;
  e.target.textContent=all?'single step':'show all';show(cur);};
document.addEventListener('keydown',e=>{
  if(e.key==='ArrowLeft')show(cur-1);
  if(e.key==='ArrowRight')show(cur+1);});
show(0);
"""


def page(title, body):
    return ("<!doctype html><meta charset=utf-8><title>%s</title>"
            "<style>%s</style><div class=wrap>%s</div>"
            % (html.escape(title), CSS, body))


def badge(score):
    if score == 1.0:
        return '<span class="badge pass">PASS 1.0</span>'
    if score is None:
        return '<span class="badge none">no score</span>'
    return '<span class="badge fail">FAIL %g</span>' % score


def score_of(td):
    f = os.path.join(td, "result.txt")
    if not os.path.isfile(f):
        return None
    try:
        return float(open(f).read().strip())
    except ValueError:
        return None


def split_response(r):
    """(think, action_desc, tool_xml): reasoning verbatim, the natural-language
    action line, and the raw tool_call block."""
    think = ""
    rest = r
    if "</think>" in r:
        think = r.split("</think>")[0].replace("<think>", "").strip()
        rest = r.split("</think>", 1)[1]
    rest = rest.strip()
    if "<tool_call>" in rest:
        desc, xml = rest.split("<tool_call>", 1)
        desc = desc.replace("Action:", "", 1).strip()
        return think, desc, "<tool_call>" + xml
    return think, rest, ""


def task_page(td, meta):
    steps = []
    for l in open(os.path.join(td, "traj.jsonl"), encoding="utf-8"):
        if l.strip():
            try:
                steps.append(json.loads(l))
            except ValueError:   # torn line while the runner is mid-write
                pass
    score = score_of(td)
    title = meta.get("slug") or os.path.basename(td)

    total = {}
    for s in steps:
        total[s.get("step_num")] = total.get(s.get("step_num"), 0) + 1
    seen, prev, prev_n = {}, None, None

    frames = []
    for s in steps:
        n = s.get("step_num")
        seen[n] = seen.get(n, 0) + 1
        label = str(n) if total[n] == 1 else "%s.%d" % (n, seen[n])
        t = str(s.get("action_timestamp", ""))
        clock = "%s:%s:%s" % (t[9:11], t[11:13], t[13:15]) if "@" in t and len(t) >= 15 else ""
        resp = (s.get("response") or "").strip()
        parts = ["<div class=frame><h3>step %s <small>%s</small></h3>" % (label, clock)]
        # Same call = same step_num; identical text from a DIFFERENT call (a
        # degenerate loop) still renders in full, so loops stay visible.
        if not (resp == prev and n == prev_n):
            think, desc, xml = split_response(resp)
            if think:
                parts.append('<div class="blk b-think"><span class=tag>THINKING'
                             '</span>%s</div>' % html.escape(think))
            if desc:
                parts.append('<div class="blk b-act"><span class=tag>ACTION'
                             '</span>%s</div>' % html.escape(desc))
            if xml:
                parts.append('<div class="blk b-tool"><span class=tag>TOOL CALL'
                             '</span>%s</div>' % html.escape(xml))
        else:
            parts.append("<p class=meta>same model call as the previous action</p>")
        prev, prev_n = resp, n
        parts.append('<div class="blk b-exec"><span class=tag>EXECUTED (pyautogui in VM)'
                     '</span>%s</div>' % html.escape(str(s.get("action"))))
        png = s.get("screenshot_file")
        if png and os.path.isfile(os.path.join(td, png)):
            parts.append('<img class=shot loading=lazy src="%s">' % png)
        parts.append("</div>")
        frames.append("".join(parts))

    o = meta.get("ostg") or {}
    chips = []
    for lab, val in (("grade", o.get("grade")), ("intent", o.get("intent")),
                     ("domain", o.get("domain")),
                     ("difficulty", "d%s" % o.get("difficulty") if o.get("difficulty") else None),
                     ("ambiguity", "a%s" % o.get("ambiguity") if o.get("ambiguity") else None),
                     ("voice", o.get("voice")),
                     ("apps", " + ".join(meta.get("apps") or []) or None),
                     ("batch", o.get("batch"))):
        if val:
            chips.append('<span class=chip><b style="color:#5f6368;font-weight:600">'
                         '%s</b>&nbsp;%s</span>' % (lab, html.escape(str(val))))
    head = ["<h2>%s %s</h2>" % (html.escape(title), badge(score)),
            ('<div class=chips style="margin:.2em 0 .6em">%s</div>' % "".join(chips))
            if chips else "",
            '<div class=instr>%s</div>' % html.escape(meta.get("instruction", ""))]
    links = ['<a href="index.html" onclick="history.back();return false">&larr; back</a>']
    if os.path.isfile(os.path.join(td, "recording.mp4")):
        links.append('<a href="recording.mp4">recording.mp4</a>')
    head.append('<p class=meta>%s</p>' % " &nbsp;|&nbsp; ".join(links))
    if meta.get("task"):
        head.append("<details><summary>task config + evaluator</summary>"
                    "<div class=resp>%s</div></details>"
                    % html.escape(json.dumps(meta["task"], indent=1, ensure_ascii=False)))
    nav = ('<div class=nav><button id=prev>&#9664; prev</button>'
           '<span id=pos></span><button id=next>next &#9654;</button>'
           '<input type=range id=rng min=0 max=%d value=0>'
           '<button id=all>show all</button></div>' % max(len(frames) - 1, 0))
    body = "".join(head) + nav + "".join(frames) + "<script>%s</script>" % JS
    open(os.path.join(td, "viewer.html"), "w", encoding="utf-8").write(page(title, body))
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
                             "instruction": j.get("instruction", ""),
                             "ostg": j.get("ostg") or {},
                             "apps": j.get("related_apps") or [],
                             "task": {"config": j.get("config"),
                                      "evaluator": j.get("evaluator")}}
    rows = []
    for tj in sorted(glob.glob(os.path.join(a.result_dir, "*", "*", "traj.jsonl"))):
        td = os.path.dirname(tj)
        m = meta.get(os.path.basename(td), {})
        score, n = task_page(td, m)
        o = m.get("ostg") or {}
        rows.append((os.path.basename(os.path.dirname(td)),
                     m.get("slug", os.path.basename(td)), score, n,
                     os.path.relpath(os.path.join(td, "viewer.html"), a.result_dir),
                     o.get("grade", ""), o.get("difficulty", ""), o.get("intent", "")))
    rows.sort(key=lambda r: (-(r[2] == 1.0), r[0], r[1]))
    done = [r for r in rows if r[2] is not None]
    passed = sum(1 for r in rows if r[2] == 1.0)
    idx = ["<h2>%s</h2>" % html.escape(os.path.basename(os.path.normpath(a.result_dir))),
           '<div class=chips><span class=chip>%d trajectories</span>'
           '<span class=chip>%d scored</span>'
           '<span class="chip" style="color:#1e8e3e;font-weight:600">%d passed</span></div>'
           % (len(rows), len(done), passed),
           "<table><tr><th>domain<th>task<th>grade<th>diff<th>intent<th>score<th>steps"]
    for dom, slug, score, n, rel, grade, diff, intent in rows:
        idx.append('<tr><td>%s<td><a href="%s">%s</a><td>%s<td>%s<td>%s<td>%s<td>%d'
                   % (dom, rel, html.escape(slug), grade,
                      ("d%s" % diff) if diff != "" else "", intent, badge(score), n))
    idx.append("</table>")
    open(os.path.join(a.result_dir, "index.html"), "w", encoding="utf-8").write(
        page("rollout index", "".join(idx)))
    print("index.html + %d viewer.html -> %s" % (len(rows), a.result_dir))


if __name__ == "__main__":
    main()
