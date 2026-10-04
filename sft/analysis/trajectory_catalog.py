"""One live catalog over loopback viewers. Only index metadata is cached locally."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import subprocess
import threading
import time
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

from .trajectory_viewer import index_html, index_group_id, json_script
from .visual_signals import read_json, write_json


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def upstream(url, headers=None, timeout=30):
    return build_opener(NoRedirect).open(Request(url, headers=headers or {}), timeout=timeout)


class Catalog:
    def __init__(self, config):
        self.config = Path(config).resolve()
        self.cache = self.config.parent / (self.config.stem + "-cache")
        self.lock = threading.Lock()
        self.expires = 0
        self.tunnels = {}

    def reconnect(self, source):
        """Keep only explicitly configured, loopback SSH forwards alive."""
        ssh = source.get("ssh")
        if not ssh:
            return
        process, started = self.tunnels.get(source["id"], (None, 0))
        if (process and process.poll() is None) or time.monotonic() - started < 30:
            return
        port = urlsplit(source["url"]).port
        command = ["ssh", "-NT", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                   "-o", "ExitOnForwardFailure=yes", "-o", "ControlPath=none",
                   "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3",
                   "-o", "StrictHostKeyChecking=yes", "-p", str(ssh.get("port", 22)),
                   "-L", f"127.0.0.1:{port}:127.0.0.1:{int(ssh['remote_port'])}"]
        if ssh.get("known_hosts"):
            command += ["-o", "UserKnownHostsFile=" + ssh["known_hosts"]]
        # The host is operator configuration, never a value from an eval result.
        if not re.fullmatch(r"[A-Za-z0-9_.@-]+", ssh["host"]) or ssh["host"].startswith("-"):
            raise ValueError("Invalid SSH host")
        process = subprocess.Popen(command + [ssh["host"]], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.tunnels[source["id"]] = (process, time.monotonic())

    def read_source(self, source):
        path = self.cache / (source["id"] + ".json")
        status = {k: source[k] for k in ("id", "label", "collection")}
        try:
            with upstream(source["url"] + "/index.json", timeout=3) as response:
                raw = response.read(32 * 1024 * 1024 + 1)
            if len(raw) > 32 * 1024 * 1024:
                raise ValueError("Index exceeds 32 MiB")
            index = json.loads(raw)
            if not isinstance(index.get("trajectories"), list) or not isinstance(index.get("runs", {}), dict):
                raise ValueError("Invalid source index")
            write_json(path, {"index": index, "fetched_at": time.time()})
            status.update(online=True, cached=False)
        except (OSError, ValueError, TypeError) as exc:
            self.reconnect(source)
            saved = read_json(path, {})
            index = saved.get("index", {"trajectories": [], "runs": {}})
            status.update(online=False, cached=bool(saved), fetched_at=saved.get("fetched_at"), error=str(exc))
        return source, index, status

    def snapshot(self):
        with self.lock:
            if time.monotonic() < self.expires:
                return self.index
            config = read_json(self.config)
            sources = config["sources"]
            seen = set()
            for s in sources:
                url = urlsplit(s["url"])
                if (not re.fullmatch(r"[a-z0-9-]+", s["id"]) or s["id"] in seen
                        or s["collection"] not in {"eval", "test"}
                        or url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port
                        or url.username or url.password or url.path or url.query or url.fragment):
                    raise ValueError("Sources need unique IDs, eval/test and loopback HTTP viewer URLs")
                seen.add(s["id"])
            merged = dict(schema_version=3, trajectories=[], runs={}, sources=[])
            with ThreadPoolExecutor(max_workers=max(1, min(8, len(sources)))) as pool:
                for source, index, status in pool.map(self.read_source, sources):
                    prefix = "/sources/" + source["id"] + "/"
                    for row in index["trajectories"]:
                        item = dict(row)
                        item["run_id"] = source["id"] + ":" + row["run_id"]
                        item["collection"] = row.get("collection", source["collection"])
                        if item["collection"] not in {"eval", "test"}:
                            raise ValueError("Invalid recorded collection")
                        item["catalog_source"] = source["id"]
                        for key in ("html", "json"):
                            if row.get(key):
                                item[key] = prefix + row[key].lstrip("/")
                        merged["trajectories"].append(item)
                    merged["runs"].update({source["id"] + ":" + k: v for k, v in index.get("runs", {}).items()})
                    merged["sources"].append(status)
            merged["revision"] = hashlib.sha256(json.dumps(merged, sort_keys=True).encode()).hexdigest()
            self.sources = {s["id"]: s for s in sources}
            self.legacy_source = config.get("legacy_source")
            self.index = merged
            self.expires = time.monotonic() + 10
            return merged


def current_task_page(raw, source, index):
    """Use the shared template with the existing export; never rewrite raw evidence."""
    match = re.search(r'<script[^>]*\bid="trajectory-data"[^>]*>(.*?)</script>', raw, re.S)
    if match:
        payload = json.loads(match[1])
    else:
        match = re.search(r"\bconst DATA\s*=\s*", raw)
        if not match:
            raise ValueError("Task page has no supported data payload")
        payload, _ = json.JSONDecoder().raw_decode(raw[match.end():])
    payload["run"]["id"] = source["id"] + ":" + payload["run"]["id"]
    collections = {r["collection"] for r in index["trajectories"] if r["run_id"] == payload["run"]["id"]}
    collection = next(iter(collections)) if len(collections) == 1 else source["collection"]
    payload["catalog"] = {"prefix": "/sources/" + source["id"], "collection": collection}
    current = next((r for r in index['trajectories'] if r['run_id'] == payload['run']['id']), None)
    if current:
        group = index_group_id(current, index['runs'].get(current['run_id'], {}))
        payload['catalog']['run_ids'] = sorted({r['run_id'] for r in index['trajectories']
            if index_group_id(r, index['runs'].get(r['run_id'], {})) == group})
    template = Path(__file__).with_name("trajectory_viewer.html").read_text(encoding="utf-8")
    return template.replace("/*__TRAJECTORY_DATA__*/", json_script(payload), 1).encode()


class CatalogHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            self.serve()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.send_error(502, "Source unavailable", explain=str(exc))

    def reply(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def serve(self):
        path = urlsplit(self.path).path
        index = self.server.catalog.snapshot()
        if path in ("/", "/index.html", "/index.json"):
            if path.endswith(".json"):
                return self.reply(json.dumps(index, ensure_ascii=False).encode(), "application/json")
            return self.reply(index_html(index).encode(), "text/html; charset=utf-8")
        if re.fullmatch(r"/task-[a-f0-9]{32}\.html", path):
            targets = {r["html"].split("#")[0] for r in index["trajectories"] if r["html"].split("#")[0].endswith(path)}
            fallback = self.server.catalog.legacy_source
            target = next(iter(targets)) if len(targets) == 1 else (
                "/sources/" + fallback + path if not targets and fallback in self.server.catalog.sources else None)
            if target:
                self.send_response(302)
                self.send_header("Location", target)
                self.end_headers()
                return
        match = re.fullmatch(r"/sources/([a-z0-9-]+)/(.+)", path)
        if not match or match[1] not in self.server.catalog.sources:
            return self.send_error(404)
        source, relative = self.server.catalog.sources[match[1]], match[2]
        decoded = unquote(relative)
        if any(p in {"..", "."} for p in decoded.split("/")) or "\\" in decoded:
            return self.send_error(404)
        if relative == "index.html":
            self.send_response(302)
            self.send_header("Location", "/index.html?collection=" + source["collection"])
            self.end_headers()
            return
        if relative == "index.json":
            return self.reply(json.dumps(index, ensure_ascii=False).encode(), "application/json")
        task = bool(re.fullmatch(r"task-[a-f0-9]{32}\.html", relative))
        if not (task or relative.startswith("assets/") or re.fullmatch(
                r"(?:tasks|validation)/[a-f0-9]{32}\.json|signals/[a-f0-9]{32}-[0-9]+(?:-raw)?\.json|heatmaps/[a-f0-9]{32}-[0-9]+\.heat|archives/[a-f0-9]{32}\.jsonl\.gz", relative)):
            return self.send_error(404)
        headers = {"Range": self.headers["Range"]} if self.headers.get("Range") else {}
        try:
            response = upstream(source["url"] + "/" + relative, headers, timeout=60)
        except HTTPError as exc:
            return self.send_error(exc.code)
        with response:
            if task:
                return self.reply(current_task_page(response.read().decode(), source, index), "text/html; charset=utf-8")
            self.send_response(response.status)
            for header in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "Last-Modified", "Content-Encoding"):
                if response.headers.get(header):
                    self.send_header(header, response.headers[header])
            self.end_headers()
            while chunk := response.read(1024 * 1024):
                self.wfile.write(chunk)


def catalog_server(config, port=8793):
    class Server(ThreadingHTTPServer):
        def server_close(self):
            super().server_close()
            for process, _ in self.catalog.tunnels.values():
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
    server = Server(("127.0.0.1", port), CatalogHandler)
    server.catalog = Catalog(config)
    return server
