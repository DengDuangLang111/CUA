"""Standalone, deterministic trajectory viewer. No report-app or model dependency."""
import ast
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
from .visual_signals import attention_overviews, write_json


def action_graph(frames, mode="action"):
    if mode not in {"action", "state", "steps"}:
        raise ValueError("Unknown graph grouping")
    nodes, edges, by_key, by_edge, route, occurrences = [], [], {}, {}, [], []
    for si, frame in enumerate(frames):
        for ai, action in enumerate(frame["actions"]):
            occurrence = len(occurrences)
            command = action["action"]
            command = command if isinstance(command, str) else json.dumps(command, ensure_ascii=False, sort_keys=True)
            app = action.get("app")
            app = app if isinstance(app, str) else json.dumps(app, ensure_ascii=False, sort_keys=True) if app is not None else ""
            try:
                normalized = ast.dump(ast.parse(command), include_attributes=False)
            except (SyntaxError, ValueError):
                normalized = command
            if mode == "action":
                key = (app, normalized)
            elif mode == "state" and action.get("before_sha256"):
                key = (app, action["before_sha256"])
            else:
                key = ("occurrence", occurrence)
            if key not in by_key:
                by_key[key] = len(nodes)
                nodes.append(dict(id=len(nodes), label=command, app=app, occurrences=[]))
            node = by_key[key]
            nodes[node]["occurrences"].append(occurrence)
            route.append(node)
            occurrences.append(dict(step_order=si, action_index=ai, step_num=frame["step"], row_number=action["row_number"]))
            if occurrence:
                pair = (route[-2], node)
                if pair not in by_edge:
                    by_edge[pair] = len(edges)
                    edges.append(dict(source=pair[0], target=pair[1], occurrences=[]))
                edges[by_edge[pair]]["occurrences"].append([occurrence - 1, occurrence])
    return dict(nodes=nodes, edges=edges, route=route, occurrences=occurrences)


def json_script(value):
    # Raw predictions are untrusted text, including literal </script> sequences.
    return json.dumps(value, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace("&", "\\u0026")


def task_html(bundle, json_path, output_dir=None):
    episodes = []
    exported = []
    for index,row in enumerate(bundle['trace_steps']):
        frame=dict(row)
        if row.get('signals'):
            signal=dict(row['signals'])
            if 'attention_overviews' not in signal:signal['attention_overviews']=attention_overviews(signal)
            if output_dir is not None and any('weights_ref' in r for r in signal.get('attention',[])):
                relative='signals/'+Path(json_path).stem+'-'+str(index)+'.json'
                write_json(Path(output_dir)/relative,signal)
                frame.update(signals=None,signals_url=relative)
            else:frame['signals']=signal
        exported.append(frame)
    for trace in bundle["trace_catalog"]:
        frames = [row for row in exported if row['trace_id']==trace['id']]
        episodes.append(dict(trace=trace, frames=frames, graphs=bundle["graphs"][trace["id"]]))
    payload = dict(run=bundle["runs"][0], episodes=episodes, json_path=json_path,
                   validation=bundle.get("validation"))
    template = Path(__file__).with_name("trajectory_viewer.html").read_text(encoding="utf-8")
    return template.replace("/*__TRAJECTORY_DATA__*/", json_script(payload), 1)


def add_graphs(bundle):
    bundle["graphs"] = {}
    for trace in bundle["trace_catalog"]:
        frames = [row for row in bundle["trace_steps"] if row["trace_id"] == trace["id"]]
        bundle["graphs"][trace["id"]] = {mode: action_graph(frames, mode) for mode in ("action", "state", "steps")}
    return bundle


def index_group_id(item, run):
    """Combine host shards only for the same named, registered eval campaign."""
    name = Path(item.get('run') or run.get('path') or '').name
    boundary = run.get('model_boundary') or {}
    if not boundary.get('model_id') or not re.fullmatch(r'.+--\d{8}T\d{6}Z-[a-f0-9]{12}', name):
        return item['run_id']
    args = run.get('args') or json.loads(item.get('protocol') or '{}')
    local = {'base_url', 'result_dir', 'test_all_meta_path', 'test_config_base_dir',
             'path_to_vm', 'num_envs', 'log_level'}
    identity = [name, item.get('collection', 'eval'), boundary,
                run.get('checkpoint') or item.get('checkpoint'),
                {k: v for k, v in args.items() if k not in local}]
    return 'campaign:' + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]


def index_html(index):
    from sft.armname import BACKBONE, SOURCES
    backbone_names = {token: name for name, token in BACKBONE.items()}
    groups = {}
    labels = {s['id']: s['label'] for s in index.get('sources', [])}
    for item in index["trajectories"]:
        run = index.get("runs", {}).get(item["run_id"], {})
        group_id = index_group_id(item, run)
        source = labels.get(item.get('catalog_source'), item.get('source', ''))
        if group_id not in groups:
            model = run.get("canonical_name") or item.get("canonical_name") or item.get("model") or "模型未记录"
            parts = model.split("@")[0].split("~")[0].split("-")
            method = parts[1] if len(parts) > 1 else ""
            formula = run.get("corpus_formula") or ("未做本项目 SFT" if method == "base" else "未记录")
            boundary = run.get("model_boundary") or {}
            groups[group_id] = dict(
                id=group_id, member_run_ids=[], sources=[], collection=item.get("collection", "eval"), model=model, alias=run.get("legacy_name") or "",
                name=Path(item.get("run", "")).name, source=item.get("source", ""),
                backbone=backbone_names.get(parts[0], "未记录"),
                method={"full": "全参 SFT", "lora": "LoRA SFT", "base": "原始权重 · 未做本项目 SFT"}.get(method, "未记录"),
                dataset=formula, dataset_label={"r5": "v11 旧数据（r5）", "v16": "v16 判官准入（仅 v16）"}.get(formula, formula),
                dataset_description="本项目未进行 SFT；上游训练数据未记录。" if method == "base" else "；".join(SOURCES.get(t, t) for t in formula.split(".")[0].split("+")),
                args=run.get("args") or json.loads(item.get("protocol") or "{}"),
                precision=boundary.get("precision") or "未记录", train_recipe=boundary.get("train_recipe") or "未记录",
                checkpoint=run.get("checkpoint") or item.get("checkpoint") or "未记录", entries=[])
        group = groups[group_id]
        if item['run_id'] not in group['member_run_ids']:
            group['member_run_ids'].append(item['run_id'])
        if source not in group['sources']:
            group['sources'].append(source)
        group['source'] = ' / '.join(group['sources'])
        entry = {key: item.get(key) for key in (
            "run_id", "task_path", "task_id", "instruction", "domain", "related_apps",
            "evaluator_functions", "episode", "actionCount", "score", "html")}
        entry['source'] = source
        group['entries'].append(entry)
    payload = sorted(groups.values(), key=lambda group: (group["name"], group["id"]))
    template = Path(__file__).with_name("trajectory_index.html").read_text(encoding="utf-8")
    return template.replace("/*__INDEX_DATA__*/", json_script(payload), 1).replace(
        "/*__CATALOG_DATA__*/", json_script({"sources": index.get("sources", []), "revision": index.get("revision")}), 1)


class ViewerHandler(SimpleHTTPRequestHandler):
    def send_head(self):
        path = unquote(urlsplit(self.path).path)
        if path.startswith("/assets/"):
            try:
                manifest = json.loads((self.server.output / "manifest.json").read_text())
                original = manifest["assets"].get(path[len("/assets/"):])
                self.selected_file = Path(original).resolve() if original else None
                if self.selected_file and not self.selected_file.is_relative_to(Path(manifest["root"]).resolve()):
                    self.selected_file = None
            except (OSError, ValueError, KeyError, TypeError):
                self.selected_file = None
        elif path in ("/", "/index.html", "/index.json") or re.fullmatch(r"/(?:task-[a-f0-9]{32}\.html|(?:tasks|validation)/[a-f0-9]{32}\.json|signals/[a-f0-9]{32}-[0-9]+(?:-raw)?\.json|heatmaps/[a-f0-9]{32}-[0-9]+\.heat|archives/[a-f0-9]{32}\.jsonl\.gz)", path):
            self.selected_file = (self.server.output / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
            if not self.selected_file.is_relative_to(self.server.output):
                self.selected_file = None
        else:
            self.selected_file = None
        self.compressed_json = False
        if self.selected_file is not None and path.startswith('/signals/') and not self.selected_file.is_file():
            compressed = self.selected_file.with_suffix(self.selected_file.suffix + '.gz')
            if compressed.is_file():
                self.selected_file = compressed
                self.compressed_json = True
        if self.selected_file is None or not self.selected_file.is_file():
            self.send_error(404)
            return None
        self.remaining=None
        if self.headers.get('Range') and self.selected_file.suffix in ('.attn','.heat','.gz') and not self.compressed_json:
            match=re.fullmatch(r'bytes=(\d+)-(\d+)',self.headers['Range'])
            size=self.selected_file.stat().st_size
            if not match or not 0<=int(match[1])<=int(match[2])<size:
                self.send_error(416);return None
            start,end=map(int,match.groups());self.remaining=end-start+1
            self.send_response(206)
            self.send_header('Content-Type','application/octet-stream')
            self.send_header('Content-Length',str(self.remaining))
            self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.send_header('Accept-Ranges','bytes')
            self.end_headers()
            stream=self.selected_file.open('rb');stream.seek(start);return stream
        return super().send_head()

    def end_headers(self):
        if getattr(self, 'compressed_json', False):
            self.send_header('Content-Encoding', 'gzip')
        super().end_headers()

    def guess_type(self, path):
        return 'application/json' if getattr(self, 'compressed_json', False) else super().guess_type(path)

    def copyfile(self, source, outputfile):
        if self.remaining is None:return super().copyfile(source,outputfile)
        while self.remaining:
            chunk=source.read(min(self.remaining,1024*1024))
            if not chunk:break
            outputfile.write(chunk);self.remaining-=len(chunk)

    def translate_path(self, path):
        return str(self.selected_file)

    def list_directory(self, path):
        self.send_error(403)


def viewer_server(output, port=8793):
    import fcntl
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".index.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        index_path = output / "index.json"
        if not index_path.exists():
            write_json(index_path, {"schema_version": 3, "trajectories": [], "runs": {}})
        if not (output / "index.html").exists():
            index = json.loads(index_path.read_text())
            temporary = output / "index.html.tmp"
            temporary.write_text(index_html(index), encoding="utf-8")
            temporary.replace(output / "index.html")
    server = ThreadingHTTPServer(("127.0.0.1", port), ViewerHandler)
    server.output = output
    return server
