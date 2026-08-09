# ostg v8

LLM-generated OSWorld tasks, one self-contained JSON each. Three grades, all
judged by stock OSWorld machinery; the taxonomy cell dictates the grade:

    probe    (default) setup + a python3 probe in the VM printing PASS/FAIL;
             vm_command_line + check_include_exclude
    table    spreadsheet cells: the .xlsx is pulled out and check_cell rules
             run on the host (openpyxl); vm_file + compare_table, no gold file
    browser  browser_tab cells: where Chrome ended up;
             active_url_from_accessTree + is_expected_url_pattern_match

Nothing is built on the host and nothing is uploaded; the task JSON is the
whole task.

## Run

    # generate specs AND runnable tasks (examples/ + manifest.json) in one pass
    python -m ostg.gen --n 5 --batches 4 --seed 424242 --thinking --stream \
      --out out/runs/v8/specs.jsonl \
      --avoid-corpus /mnt/d/research/cua-gym/tasks.jsonl

    # pre-rollout controls: setup exit code + idle agent must score 0
    # (OSWorld venv; boots one fresh VM per task)
    python -m ostg.control --tasks out/runs/v8 \
      --path_to_vm /mnt/d/research/OSWorld/docker_vm_data/Ubuntu.qcow2

    # rollouts: point the runner at the emitted directory
    ... run_multienv_qwen.py \
      --test_config_base_dir out/runs/v8 \
      --test_all_meta_path out/runs/v8/manifest.json

## Files

    taxonomy.py             intent x domain x difficulty (ambiguity defined,
                            not yet crossed in); cells() draws briefs
    gen.py                  cells -> Claude -> specs.jsonl + task JSON
    control.py              the two checks above, on the real evaluation path
    prompts/single_json.txt the whole prompt (SYSTEM + USER head)

## OSWorld facts the emitter is built on

Verified against the OSWorld source, commit 091f5ef1:

- the expected getter reads `rules` -- plural (`getters/misc.py:92`)
- `vm_command_line` returns raw stdout, so PASS arrives as `"PASS\n"`;
  `check_include_exclude` tolerates that and guards None, which also makes the
  evaluator unable to throw (an evaluator exception means NO result.txt and the
  task silently leaves the denominator)
- the VM's `/execute` endpoint kills commands at 120 s; `shell:true` is /bin/sh
- setup exit codes are never checked, and `until: {returncode: 0}` retries a
  permanently failing command forever -- hence no `until`, and control.py
- an agent whose last action is FAIL scores 0 without the probe running
