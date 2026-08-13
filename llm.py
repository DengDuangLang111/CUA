"""The Anthropic-API client every ostg stage shares: env loading, one
retrying call, and forced-tool extraction. Split out of taskgen/gen.py so
the SFT side does not import the generation pipeline to reach the model.
"""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


def load_env(path=".env"):
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def call(messages, system_blocks, cfg, timeout=900, tool=None):
    tool = tool or tool_definition()
    payload = {
        "model": cfg["model"],
        "max_tokens": cfg["max_tokens"],
        "system": system_blocks,
        "messages": messages,
        "tools": [tool],
        "tool_choice": {"type": "tool", "name": tool["name"]},
    }
    # Thinking and a forced tool choice are mutually exclusive; auto makes the
    # tool call probable rather than guaranteed, hence the retry in the caller.
    if cfg.get("thinking"):
        payload["thinking"] = {"type": "adaptive"}
        payload["tool_choice"] = {"type": "auto"}
    else:
        # Explicit, not omitted: Opus 5 thinks by default, and the forced tool
        # choice above demands thinking off.
        payload["thinking"] = {"type": "disabled"}
    # Streaming is about the gateway: a batch sends nothing for minutes, nginx
    # hits proxy_read_timeout and answers 504 before Anthropic is ever reached.
    # An event stream keeps bytes moving, so the timeout never arms.
    if cfg.get("stream"):
        payload["stream"] = True
    req = urllib.request.Request(
        cfg["base"] + "/v1/messages",
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json",
                 "anthropic-version": "2023-06-01",
                 "x-api-key": cfg["key"]},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if payload.get("stream"):
                return _assemble(r)
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:600]
        err = RuntimeError("HTTP %d: %s" % (e.code, body))
        err.transient = e.code == 429 or 500 <= e.code < 600
        raise err from None
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        # A timeout or a dropped connection must not kill the remaining batches.
        err = RuntimeError("network: %s" % e)
        err.transient = True
        raise err from None


def _assemble(response):
    """Rebuild the non-streaming response shape from an SSE event stream, so
    callers cannot tell the difference. Handles the three block types this
    generator can receive: text, thinking, tool_use (partial_json fragments)."""
    blocks, out = {}, {"content": [], "usage": {}, "stop_reason": None}
    for raw in response:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        try:
            ev = json.loads(line[5:].strip())
        except ValueError:
            continue
        kind = ev.get("type")
        if kind == "message_start":
            out["usage"] = dict(ev.get("message", {}).get("usage") or {})
        elif kind == "content_block_start":
            blocks[ev["index"]] = dict(ev["content_block"])
            blocks[ev["index"]]["_json"] = ""
        elif kind == "content_block_delta":
            b = blocks.setdefault(ev["index"], {"type": "text", "text": "", "_json": ""})
            d = ev.get("delta", {})
            if d.get("type") == "text_delta":
                b["text"] = b.get("text", "") + d.get("text", "")
            elif d.get("type") == "thinking_delta":
                b["thinking"] = b.get("thinking", "") + d.get("thinking", "")
            elif d.get("type") == "input_json_delta":
                b["_json"] += d.get("partial_json", "")
        elif kind == "message_delta":
            out["stop_reason"] = (ev.get("delta") or {}).get("stop_reason")
            out["usage"].update(ev.get("usage") or {})
    for i in sorted(blocks):
        b = blocks[i]
        frag = b.pop("_json", "")
        if b.get("type") == "tool_use":
            try:
                b["input"] = json.loads(frag) if frag else b.get("input") or {}
            except ValueError:
                continue  # truncated tool call: extract() raises, the retry covers it
        out["content"].append(b)
    return out


def extract(resp, name, field="specs"):
    for b in resp.get("content", []):
        if b.get("type") == "tool_use" and b.get("name") == name:
            inp = b.get("input", {})
            out = inp.get(field, []) if field else inp
            # The schema is not server-enforced: the model sometimes returns
            # the array (or an element) as a JSON string. Parse it back.
            if isinstance(out, str):
                try:
                    out = json.loads(out)
                except ValueError:
                    return []   # unparseable string: nothing recoverable
            if isinstance(out, list):
                fixed = []
                for x in out:
                    if isinstance(x, str):
                        try:
                            x = json.loads(x)
                        except ValueError:
                            continue
                    if isinstance(x, dict):
                        fixed.append(x)
                out = fixed
            return out
    raise RuntimeError("no tool_use block (stop_reason=%s)" % resp.get("stop_reason"))


def call_and_extract(messages, system_blocks, cfg, tries=3, tool=None, field="specs"):
    assert tool is not None, "pass an explicit tool definition"
    for attempt in range(1, tries + 1):
        try:
            resp = call(messages, system_blocks, cfg, tool=tool)
        except RuntimeError as e:
            if attempt == tries or not getattr(e, "transient", False):
                raise
            print("  retry %d/%d after %s" % (attempt, tries - 1, str(e)[:60]))
            continue
        thought = sum(1 for b in resp.get("content", []) if b.get("type") == "thinking")
        try:
            specs = extract(resp, name=tool["name"], field=field)
        except RuntimeError as e:
            if attempt == tries:
                raise
            print("  retry %d/%d: %s" % (attempt, tries - 1, e))
            continue
        return specs, resp, thought
    raise AssertionError("unreachable")
