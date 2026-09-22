"""Launch a pinned native evaluation with raw capture and the existing page worker."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import urllib.request


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text())
    root = Path(profile["harness_root"]).resolve()
    tool = Path(__file__).resolve().parents[3]
    result = Path(profile["result_dir"]).resolve()
    inspection_path = Path(profile["inspection_config"]).resolve()
    inspection = json.loads(inspection_path.read_text())
    protocol = json.loads(Path(profile["protocol_file"]).read_text())
    manifest = json.loads(Path(profile["task_manifest"]).read_text())
    tasks = [(domain, task) for domain, ids in manifest.items() for task in ids]
    assert tasks and len(tasks) == len(set(tasks)), "Empty or duplicate task panel"
    assert not result.exists(), "Use a new result directory; preserve previous attempts"
    assert result.is_relative_to(Path(inspection["results_root"]).resolve())
    assert inspection["collection"] in ("eval", "test") and inspection["capture"]["enabled"]
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    assert commit == profile["commit"], "Unexpected benchmark commit"
    assert not subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True).strip()
    key = Path(profile["key_file"]).read_text().strip()
    with urllib.request.urlopen(urllib.request.Request(profile["base_url"].removesuffix("/v1") + "/openapi.json",
            headers={"Authorization": "Bearer " + key}), timeout=30) as response:
        assert len(response.read()) > 200000, "Large model response check failed"
    python = str(root / ".venv/bin/python")
    env = dict(os.environ, OPENAI_API_KEY=key, CUA_INSPECTION_CONFIG=str(inspection_path),
               PYTHONPATH=":".join(map(str, [tool / "sft/scripts/eval/capture_runtime", tool, root, root / "scripts/python"])),
               OSWORLD_EVAL_MODEL_BASE_URL="https://api.anthropic.com",
               OSWORLD_USER_SIM_BASE_URL="https://api.anthropic.com",
               OSWORLD_OPENAI_TIMEOUT=str(profile.get("model_timeout_seconds", 1800)))
    subprocess.run([python, "-c", "import lib_run_single; assert getattr(lib_run_single.run_single_example, '_cua_capture_wrapped', False)"],
                   cwd=root, env=env, check=True)
    sys.path.insert(0, str(root / "local_eval"))
    from process_identity import identity
    # Check for another campaign before allocating VMs. Do not stop unknown work.
    processes = []
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            processes.append((int(proc.name), (proc / "cmdline").read_bytes().decode().split("\0")))
        except (OSError, UnicodeError):
            pass
    assert not any(any(x.endswith(("run_multienv_qwen_internal_agent.py", "local_eval/entry.py")) for x in cmd)
                   for _, cmd in processes), "An evaluation runner is already active"
    command = [python, "-u", str(root / "scripts/python/run_multienv_qwen_internal_agent.py")]
    for name, value in protocol.items():
        if isinstance(value, bool):
            if value:
                command.append("--" + name)
        else:
            command.extend(["--" + name, str(value)])
    command += ["--base_url", profile["base_url"], "--api_key_env", "OPENAI_API_KEY",
                "--num_envs", str(profile["num_envs"]), "--test_config_base_dir", str(root / "evaluation_examples"),
                "--test_all_meta_path", profile["task_manifest"], "--result_dir", str(result)]
    result.mkdir(parents=True)
    def save(name, value):
        (result / name).write_text(json.dumps(value, indent=2) + "\n")
    def start(command, name):
        with (result / (name + ".log")).open("ab") as log:
            child = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        return identity(child.pid)
    hashes = {str(p.relative_to(tool)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (tool / "sft").rglob("*") if p.is_file() and p.suffix in (".py", ".html")}
    save("inspection.json", inspection)
    save("version.json", {"benchmark_commit": commit, "protocol": protocol, "source_hashes": hashes,
                          "classification": inspection["collection"], **profile.get("provenance", {})})
    save("MODEL_BOUNDARY.json", profile["model_boundary"])
    metadata = dict(commit=commit, profile=profile, protocol=protocol, task_manifest=manifest,
                    command=command, source_hashes=hashes)
    worker = next((pid for pid, cmd in processes if "process-pending" in cmd and str(inspection_path) in cmd), None)
    metadata["postprocessor"] = identity(worker) if worker else start(
        [python, "-u", str(tool / "sft/scripts/eval/after_task.py"), "process-pending", "--config", str(inspection_path), "--watch"], "postprocess")
    with socket.socket() as connection:
        busy = connection.connect_ex(("127.0.0.1", profile["viewer_port"])) == 0
    if not busy:
        metadata["viewer"] = start([python, "-u", str(tool / "sft/scripts/eval/after_task.py"), "serve",
                                    inspection["output_dir"], "--port", str(profile["viewer_port"])], "viewer")
    metadata["runner"] = start(command, "runner")
    save("launch.json", metadata)
    metadata["monitor"] = start([python, "-u", str(root / "local_eval/monitor.py"), str(result)], "monitor")
    save("launch.json", metadata)
    print(json.dumps({"result_dir": str(result), "tasks": len(tasks), "num_envs": profile["num_envs"],
                      "runner": metadata["runner"], "postprocessor": metadata["postprocessor"]}))


if __name__ == "__main__":
    main()
