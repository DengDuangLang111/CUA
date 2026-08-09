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

## Pipeline

    gen  ->  ship  ->  rollout

    # 1. generate: specs + runnable task JSON in one pass. --thinking buys
    #    deeper probes on hard cells; --shard I/N runs N processes over
    #    disjoint coordinates; --refill re-draws when a batch is lost.
    python -m ostg.gen --n 5 --batches 40 --seed S --stream \
      --out out/runs/<set>/specs.jsonl \
      --avoid-corpus /mnt/d/research/cua-gym/tasks.jsonl

    # 2. ship: everything between generation and rollout, one command,
    #    stops at the first failing stage.
    python -m ostg.ship out/runs/<set> [more sets ...] \
      --ref cua-gym=/mnt/d/research/cua-gym/tasks.jsonl \
      --ref osworld=/mnt/d/research/OSWorld/evaluation_examples/examples \
      --path_to_vm /mnt/d/research/OSWorld/docker_vm_data/Ubuntu.qcow2

    # 3. rollout: point the runner at the shipped set
    ... run_multienv_qwen.py --test_config_base_dir out/runs/<set> \
        --test_all_meta_path out/runs/<set>/manifest.json

ship runs three stages and is safe to re-run any time:

    re-emit   examples/ + manifest.json rebuilt from specs.jsonl with the
              CURRENT emitter and gate -- emit fixes and gate tightenings
              reach sets generated before them; rejected specs are dropped
              with the reason printed
    accept    the six gates below; any hard failure blocks the ship
    control   only with --path_to_vm: one fresh VM per task, setup exit code
              checked (OSWorld never does) and an idle agent must score 0

## The accept gates

Six gates, three duplicate detectors with disjoint blind spots. Standalone:

    python -m ostg.accept out/runs/<set>/specs.jsonl [more specs.jsonl ...] \
      --ref cua-gym=... --ref osworld=...

    1  instruction jaccard, all pairs     none >= 0.4. Real duplicates measure
                                          0.5-0.65; same-theme-different-task
                                          measures <= 0.30.
    1b instruction tf-idf cosine, pairs   none >= 0.5; the 0.35-0.5 band goes
                                          to hand review. Re-dressed duplicates
                                          top out at ~0.34-0.44 here (measured:
                                          the vlc pair, the listings pair), so
                                          the text layer flags them and the
                                          signature layer convicts them.
    2  grader signatures, all pairs       what the probe READS -- identifier
                                          word pieces, constants dropped.
                                          >= 0.30 (the measured knee) goes to
                                          hand review, not auto-fail: it
                                          catches re-dressed duplicates whose
                                          nouns all changed (a confirmed pair
                                          scored jaccard 0.29, signature 1.00)
                                          but is coarse on table specs.
    3  tf-idf cosine vs cua-gym           none >= 0.5. Sharper than jaccard:
                                          idf downweights boilerplate, so
                                          shared DISCRIMINATIVE words score.
    4  tf-idf cosine vs osworld-361      none >= 0.5 -- the train-on-test gate.
    5  axis balance                       intents even; difficulty quota drift
                                          under 10%.

External corpora get the text detectors only: signatures were measured (old
sig.py) not to transfer across grader styles.

## Files

    taxonomy.py             intent x domain x difficulty (ambiguity defined,
                            not yet crossed in); cells() draws briefs
    gen.py                  cells -> Claude -> specs.jsonl + task JSON
    ship.py                 re-emit + accept + control, one command, no logic
    control.py              the VM negative checks, on the real evaluation path
    accept.py               the six gates, over finished spec sets
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
