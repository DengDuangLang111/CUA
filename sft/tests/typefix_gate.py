#!/usr/bin/env python3
"""Acceptance gates for fix B (multi-line `type` no-split, OSTG_TYPE_NO_SPLIT).

Run BEFORE landing the diff. Builds a patched copy of mm_agents/ in a work dir,
imports the live parser and the patched parser side by side, and replays every
real recorded model response (traj.jsonl "response" fields) through both.

Gate A (regression, env unset)   : patched output must be byte-identical to the
                                   live parser on every response. Real inputs,
                                   never synthetic: the keepthink acceptance
                                   test passed on synthetic inputs while the
                                   branch it tested was unreachable in prod.
Gate B (equivalence, env set to 1): canonicalize both command lists into key
                                   event streams (typewrite -> one event per
                                   char with '\n' == 'enter'; press("enter")
                                   -> 'enter'; any other command verbatim).
                                   Streams must be equal -- proving the
                                   collapsed form sends the exact key sequence
                                   the split form sends (pyautogui maps '\n'
                                   to Return, _pyautogui_x11.py:282).

Usage: typefix_gate.py <osworld_root> <results_root> [workdir]
Exit 0 only if both gates pass; mismatch details go to stdout.
"""
import ast
import importlib
import json
import logging
import os
import shutil
import sys

OLD_BLOCK = r'''        elif action == "type":
            text = "" if params.get("text") is None else str(params.get("text", ""))
            normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
            if "\n" not in normalized_text:
                pyautogui_code.append(f"pyautogui.typewrite({py_string(normalized_text)})")
            else:
                chunks = normalized_text.split("\n")
                for idx, chunk in enumerate(chunks):
                    if chunk:
                        pyautogui_code.append(f"pyautogui.typewrite({py_string(chunk)})")
                    if idx < len(chunks) - 1:
                        pyautogui_code.append(f"pyautogui.press({py_string('enter')})")
'''

NEW_BLOCK = r'''        elif action == "type":
            text = "" if params.get("text") is None else str(params.get("text", ""))
            normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
            if "\n" not in normalized_text or os.environ.get("OSTG_TYPE_NO_SPLIT") == "1":
                # pyautogui maps '\n' to Return (_pyautogui_x11.py:282): one
                # typewrite sends the key sequence the per-line split sends,
                # and parse_base_response has always shipped multi-line text
                # this way. One guest command instead of up to 2*lines
                # execute+screenshot round-trips (the "command storm").
                if "\n" in normalized_text:
                    logger.info("multi-line type: %d lines -> 1 command (OSTG_TYPE_NO_SPLIT=1)",
                                normalized_text.count("\n") + 1)
                pyautogui_code.append(f"pyautogui.typewrite({py_string(normalized_text)})")
            else:
                chunks = normalized_text.split("\n")
                n_before = len(pyautogui_code)
                for idx, chunk in enumerate(chunks):
                    if chunk:
                        pyautogui_code.append(f"pyautogui.typewrite({py_string(chunk)})")
                    if idx < len(chunks) - 1:
                        pyautogui_code.append(f"pyautogui.press({py_string('enter')})")
                logger.warning("multi-line type: %d lines -> %d guest commands (upstream split; "
                               "set OSTG_TYPE_NO_SPLIT=1 to collapse)",
                               len(chunks), len(pyautogui_code) - n_before)
'''


def build_patched_tree(osworld_root, workdir):
    src = os.path.join(osworld_root, "mm_agents")
    dst = os.path.join(workdir, "mm_agents")
    if os.path.exists(workdir):
        shutil.rmtree(workdir)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
    target = os.path.join(dst, "qwen", "actions.py")
    with open(target, encoding="utf-8") as fh:
        content = fh.read()
    n = content.count(OLD_BLOCK)
    if n != 1:
        sys.exit("FATAL: expected exactly 1 occurrence of the type branch in %s, found %d. "
                 "actions.py has changed since this gate was written -- re-derive OLD_BLOCK "
                 "from the live file before trusting any result." % (target, n))
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(content.replace(OLD_BLOCK, NEW_BLOCK))
    return dst


def load_parser(root):
    for name in [m for m in sys.modules if m == "mm_agents" or m.startswith("mm_agents.")]:
        del sys.modules[name]
    sys.path.insert(0, root)
    try:
        mod = importlib.import_module("mm_agents.qwen.actions")
    finally:
        sys.path.pop(0)
    return mod


# Mirrors the production call site (mm_agents/qwen/main.py:298): the runner
# passes coordinate_type="relative" (QwenAgent default), the 1920x1080 screen,
# and the smart-resized dims. Values only need to be identical on both sides
# and realistic enough to exercise the coordinate path.
PARSE_KW = dict(coordinate_type="relative",
                original_width=1920, original_height=1080,
                processed_width=1932, processed_height=1092)


def call(parse, response):
    import inspect
    params = inspect.signature(parse).parameters
    kw = {k: v for k, v in PARSE_KW.items() if k in params}
    missing = [k for k, p in params.items()
               if p.default is inspect.Parameter.empty
               and p.kind is inspect.Parameter.KEYWORD_ONLY and k not in kw]
    if missing:
        sys.exit("FATAL: parse_internal_response has required params this gate "
                 "does not know how to fill: %r -- update PARSE_KW." % missing)
    try:
        return ("ok",) + tuple(parse(response, **kw))
    except Exception as exc:  # equal-exception on both sides is still a pass
        return ("err", repr(exc))


def canon(commands):
    out = []
    for cmd in commands:
        if cmd.startswith("pyautogui.typewrite(") and cmd.endswith(")"):
            arg = ast.literal_eval(cmd[len("pyautogui.typewrite("):-1])
            out.extend(("key", "enter" if ch == "\n" else ch) for ch in arg)
        elif cmd == 'pyautogui.press("enter")':
            out.append(("key", "enter"))
        else:
            out.append(("cmd", cmd))
    return out


def main():
    osworld_root = os.path.abspath(sys.argv[1])
    results_root = os.path.abspath(sys.argv[2])
    workdir = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else "/tmp/typefix_work"

    logging.disable(logging.CRITICAL)
    os.environ.pop("OSTG_TYPE_NO_SPLIT", None)
    os.environ.pop("OSTG_PARAM_DIALECT", None)

    patched_root = os.path.dirname(build_patched_tree(osworld_root, workdir))
    old_mod = load_parser(osworld_root)
    old_parse = old_mod.parse_internal_response
    new_mod = load_parser(patched_root)
    new_parse = new_mod.parse_internal_response
    assert new_mod.__file__.startswith(patched_root), new_mod.__file__
    assert "OSTG_TYPE_NO_SPLIT" in open(new_mod.__file__, encoding="utf-8").read()
    assert old_parse is not new_parse

    seen = set()
    n_files = n_lines = n_bad = n_unique = 0
    a_bad = b_bad = 0
    n_multiline = 0
    max_saved = 0
    total_saved = 0
    fail_examples = []

    for dirpath, _dirnames, filenames in os.walk(results_root):
        if "traj.jsonl" not in filenames:
            continue
        n_files += 1
        path = os.path.join(dirpath, "traj.jsonl")
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                n_lines += 1
                try:
                    resp = json.loads(line).get("response")
                except Exception:
                    n_bad += 1
                    continue
                if not isinstance(resp, str):
                    continue
                h = hash(resp)
                if h in seen:
                    continue
                seen.add(h)
                n_unique += 1

                os.environ.pop("OSTG_TYPE_NO_SPLIT", None)
                a_old = call(old_parse, resp)
                a_new = call(new_parse, resp)
                if a_old != a_new:
                    a_bad += 1
                    if len(fail_examples) < 5:
                        fail_examples.append(("A", path, a_old, a_new, resp[-2000:]))

                os.environ["OSTG_TYPE_NO_SPLIT"] = "1"
                b_new = call(new_parse, resp)
                ok = False
                if a_old[0] == "err":
                    ok = (b_new == a_old)
                elif b_new[0] == "err":
                    ok = False
                else:
                    ok = (a_old[1] == b_new[1]
                          and canon(a_old[2]) == canon(b_new[2]))
                    if ok and len(b_new[2]) < len(a_old[2]):
                        n_multiline += 1
                        saved = len(a_old[2]) - len(b_new[2])
                        total_saved += saved
                        max_saved = max(max_saved, saved)
                if not ok:
                    b_bad += 1
                    if len(fail_examples) < 5:
                        fail_examples.append(("B", path, a_old, b_new, resp[-2000:]))

    print("scanned: %d traj.jsonl, %d steps (%d bad json), %d unique responses"
          % (n_files, n_lines, n_bad, n_unique))
    print("GATE A (env unset, must be byte-identical): %s -- %d mismatches"
          % ("PASS" if a_bad == 0 else "FAIL", a_bad))
    print("GATE B (env=1, key-stream equivalence)   : %s -- %d mismatches"
          % ("PASS" if b_bad == 0 else "FAIL", b_bad))
    print("multi-line type responses collapsed: %d (guest commands saved: %d total, max %d in one step)"
          % (n_multiline, total_saved, max_saved))
    for tag, path, lhs, rhs, tail in fail_examples:
        print("---- %s MISMATCH in %s\n  old/newA: %r\n  new/B  : %r\n  resp tail: %r"
              % (tag, path, lhs, rhs, tail))
    sys.exit(0 if a_bad == 0 and b_bad == 0 else 1)


if __name__ == "__main__":
    main()
