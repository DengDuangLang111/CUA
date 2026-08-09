"""Prompt and schema for the single-JSON generator (v6).

Mirrors ostg.prompt's interface -- system_prompt(), user_prompt(),
tool_definition() -- so gen.py can switch between them with one flag. The
difference is what a task IS:

    ostg.prompt          instruction + setup_py + solve_py + probe_py, built on
                         the host, uploaded as files, two build-time controls
    ostg.prompt_single   instruction + setup + probe, both run inside the VM,
                         the task JSON self-contained

Everything about coordinates, avoid lists and retrieval is shared: this module
reuses ostg.prompt for those, because they are about what to ask for and are
identical either way.
"""
from __future__ import annotations

import json
from pathlib import Path

from ostg import prompt as P
from ostg import taxonomy as T

PROMPTS = Path(__file__).resolve().parent / "prompts"
_S = P._sections("single_json.txt")
SYSTEM, USER_HEAD = _S["SYSTEM"], _S["USER"]

SCHEMA = {
    "type": "object",
    "required": ["specs"],
    "properties": {
        "specs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["slug", "instruction", "apps", "setup", "probe"],
                "properties": {
                    "slug": {"type": "string",
                             "description": "unique, lowercase, under 40 characters"},
                    "instruction": {
                        "type": "string",
                        "description": "what the user wants, in their voice. Complete on its "
                                       "own, and it never states the answer the probe checks."},
                    "apps": {"type": "array",
                             "items": {"type": "string", "enum": list(P.APPS)},
                             "description": "applications the agent must use, PRIMARY FIRST"},
                    "setup": {
                        "type": "string",
                        "description": "ONE shell command, run inside the VM as the desktop "
                                       "user before the agent starts. It creates every file and "
                                       "directory the task begins from. Office files are made by "
                                       "writing CSV and calling soffice --headless --convert-to, "
                                       "because the VM has LibreOffice but not openpyxl."},
                    "probe": {
                        "type": "string",
                        "description": "a python3 program, run inside the VM after the agent "
                                       "stops. It inspects the machine and prints exactly PASS "
                                       "or exactly FAIL. Write it as real lines of Python: it is "
                                       "used verbatim, so a newline is a newline."},
                    "open_path": {
                        "type": "string",
                        "description": "optional absolute path opened in its application before "
                                       "the agent starts, e.g. /home/user/Desktop/sales.xlsx"},
                    "probe_reads": {
                        "type": "string",
                        "description": "the file or setting the probe reads and the value it "
                                       "compares against, in one line. Naming it forces the "
                                       "check to exist before the scenario is written."},
                },
            },
        }
    },
}


def system_prompt():
    return SYSTEM + ("\n<output>\nThe examples show the shape. Emit your tasks "
                     "through the tool.\n</output>\n")


def user_prompt(n, cells, priors=None, external=None, per_app=12, seed=0,
                own=None, own_per_app=8):
    """Coordinates and avoid lists, on top of the [USER] block.

    The coordinate lines and both avoid lists are built by ostg.prompt: they say
    what to ask for, which does not change with how the task is packaged. Only
    the framing around them differs.
    """
    body = P.user_prompt(n, cells, priors, external, per_app, seed, own, own_per_app)
    # Drop ostg.prompt's own TASK header -- this generator has its own contract
    # and two descriptions of the output would compete.
    marker = "\nPer-spec targets, in order:\n"
    tail = body[body.index(marker):] if marker in body else body
    return USER_HEAD.format(n=n) + tail


def tool_definition(name="emit_task_specs"):
    return {"name": name,
            "description": "Emit the finished task specs.",
            "input_schema": SCHEMA}
