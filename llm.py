"""The Anthropic-API client every ostg stage shares: env loading, one
retrying call, and forced-tool extraction. Split out of taskgen/gen.py so
the SFT side does not import the generation pipeline to reach the model.
"""
import json
import os
import socket
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


def _protocol(cfg):
    """'auto' routes claude* to the Anthropic endpoint, everything else
    (qwen*, gpt*, ...) to the OpenAI one -- matching the gateway's own
    supported_endpoint_types."""
    p = (cfg.get("protocol") or "auto").lower()
    if p != "auto":
        return p
    return "anthropic" if cfg["model"].lower().startswith("claude") else "openai"


def _to_openai_messages(messages, system_blocks):
    def text_of(content):
        if isinstance(content, str):
            return content
        return "\n".join(p.get("text", "") for p in content
                         if isinstance(p, dict) and p.get("type") == "text")
    out = []
    sys_text = text_of(system_blocks) if isinstance(system_blocks, list) else str(system_blocks)
    if sys_text.strip():
        out.append({"role": "system", "content": sys_text})
    for m in messages:
        out.append({"role": m["role"], "content": text_of(m.get("content", ""))})
    return out


def _from_openai_response(data):
    msg = (data.get("choices") or [{}])[0].get("message", {})
    finish = (data.get("choices") or [{}])[0].get("finish_reason")
    content = []
    rc = msg.get("reasoning_content") or msg.get("reasoning")
    if rc:
        content.append({"type": "thinking", "thinking": rc})
    if msg.get("content"):
        content.append({"type": "text", "text": msg["content"]})
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            continue
        content.append({"type": "tool_use", "name": fn.get("name"), "input": args})
    usage = data.get("usage") or {}
    return {"content": content,
            "stop_reason": {"tool_calls": "tool_use", "stop": "end_turn"}.get(finish, finish),
            "usage": {"input_tokens": usage.get("prompt_tokens"),
                      "output_tokens": usage.get("completion_tokens")}}


def _call_openai(messages, system_blocks, cfg, timeout=900, tool=None):
    """OpenAI-protocol twin of call(), response translated back to the
    Anthropic shape. Default regime for non-claude models mirrors the
    anthropic branch: thinking OFF + forced tool_choice (verified against the
    gateway: thinking mode rejects forced calls on qwen and anthropic alike);
    cfg['thinking'] flips to thinking + auto, guarded by the retry loop."""
    payload = {
        "model": cfg["model"],
        "max_tokens": cfg["max_tokens"],
        "messages": _to_openai_messages(messages, system_blocks),
        "tools": [{"type": "function",
                   "function": {"name": tool["name"],
                                "description": tool.get("description", ""),
                                "parameters": tool["input_schema"]}}],
        "tool_choice": ("auto" if cfg.get("thinking")
                        else {"type": "function", "function": {"name": tool["name"]}}),
        "enable_thinking": bool(cfg.get("thinking")),
    }
    if cfg.get("temperature") is not None:
        payload["temperature"] = cfg["temperature"]
    if cfg.get("stream"):
        payload["stream"] = True
    req = urllib.request.Request(
        cfg["base"] + "/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json",
                 "authorization": "Bearer " + cfg["key"]},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if payload.get("stream"):
                return _from_openai_response(_assemble_openai(r))
            return _from_openai_response(json.loads(r.read().decode("utf-8", "replace")))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:600]
        err = RuntimeError("HTTP %d: %s" % (e.code, body))
        err.transient = e.code == 429 or 500 <= e.code < 600
        raise err from None
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        err = RuntimeError("network: %s" % e)
        err.transient = True
        raise err from None


def _assemble_openai(response):
    msg = {"content": "", "reasoning_content": "", "tool_calls": {}}
    finish = None
    usage = {}
    for raw in response:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:") or line[5:].strip() == "[DONE]":
            continue
        try:
            ev = json.loads(line[5:].strip())
        except ValueError:
            continue
        if ev.get("usage"):
            usage = ev["usage"]
        for ch in ev.get("choices") or []:
            if ch.get("finish_reason"):
                finish = ch["finish_reason"]
            d = ch.get("delta") or {}
            if d.get("content"):
                msg["content"] += d["content"]
            if d.get("reasoning_content"):
                msg["reasoning_content"] += d["reasoning_content"]
            for tc in d.get("tool_calls") or []:
                slot = msg["tool_calls"].setdefault(tc.get("index", 0),
                        {"function": {"name": "", "arguments": ""}})
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["function"]["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["function"]["arguments"] += fn["arguments"]
    return {"choices": [{"message": {
                "content": msg["content"] or None,
                "reasoning_content": msg["reasoning_content"] or None,
                "tool_calls": [msg["tool_calls"][i] for i in sorted(msg["tool_calls"])] or None},
             "finish_reason": finish}],
            "usage": usage}


def call(messages, system_blocks, cfg, timeout=900, tool=None):
    if _protocol(cfg) == "openai":
        return _call_openai(messages, system_blocks, cfg, timeout=timeout, tool=tool)
    # anthropic path below, unchanged
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
    # temperature only when the caller pins it (judges want 0); never combine
    # with thinking -- the API demands temperature 1 there, so we just omit it.
    if cfg.get("temperature") is not None and not cfg.get("thinking"):
        payload["temperature"] = cfg["temperature"]
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
