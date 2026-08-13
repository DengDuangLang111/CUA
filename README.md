# ostg v9

LLM-generated OSWorld tasks, one self-contained JSON each. Every task is drawn
at a coordinate in the product intent x domain x difficulty x ambiguity (1300
cells), with a voice register derived per cell -- the cell dictates what kind
of task gets written and how its instruction may speak. Three grades, all
judged by stock OSWorld machinery; the cell dictates the grade:

    probe    (default) setup + a python3 probe in the VM printing PASS/FAIL;
             vm_command_line + check_include_exclude
    table    spreadsheet cells: the .xlsx is pulled out and check_cell rules
             run on the host (openpyxl); vm_file + compare_table, no gold file
    browser  browser_tab cells: where Chrome ended up;
             active_url_from_accessTree + is_expected_url_pattern_match

Nothing is built on the host and nothing is uploaded; the task JSON is the
whole task.

The v9 axes (see EXPERIMENTS.md section 2 for the measurements):

    ambiguity  1 explicit (10%): full paths, enumerated requirements
               2 functional (30%): objects named by what they are, no paths
               3 deictic (30%): the target is already open (open_path);
                 "this sheet" -- browser tasks use start_url as the referent
               4 outcome (30%): end state only, operations inferred
    voice      terse 30% / polite 25% / persona 45%

    Graders stay exact at every level: the probe pins full paths regardless of
    how vaguely the instruction points. Gates enforce mechanically: a path or
    filename in an ambiguity>=2 instruction rejects the spec; deictic without
    open_path rejects it. Rules 12-13 (prompt): every countable promise is
    checked in full or not made; browser url_patterns must encode the work.

## Pipeline

    gen  ->  ship  ->  rollout

    # 1. generate: specs + runnable task JSON in one pass. --thinking buys
    #    deeper probes on hard cells; --shard I/N runs N processes over
    #    disjoint coordinates; --refill re-draws when a batch is lost;
    #    --start-batch resumes after a crash with seeds aligned.
    #    RUN FROM THE VERSIONED WORKTREE as cwd: python -m puts the working
    #    directory ahead of PYTHONPATH, and a stale ostg/ there wins.
    python -m ostg.taskgen.gen --n 5 --batches 40 --seed S --stream \
      --out out/runs/<set>/specs.jsonl \
      --avoid-corpus /mnt/d/research/cua-gym/tasks.jsonl

    # 2. ship: everything between generation and rollout, one command,
    #    stops at the first failing stage.
    python -m ostg.taskgen.ship out/runs/<set> [more sets ...] \
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
    accept    the gates below; any hard failure blocks the ship
    control   only with --path_to_vm: one fresh VM per task, on the real
              evaluation path. Catches three failure classes OSWorld leaves
              SILENT, each before rollout minutes are spent:
              - setup rc != 0 (OSWorld never checks exit codes): the agent
                meets a desktop without the promised files, scores 0, and it
                reads as a model failure
              - probe crash: evaluator exception means no result.txt -- the
                task quietly leaves the denominator
              - probe passing on the untouched desktop: a do-nothing
                trajectory would be graded success; for SFT data that is the
                worst poison. An idle agent must score 0.
              Real yield: 2/20 caught in the first opus-5 set (setup \n
              escaping -- since also blocked statically by the compile gate).

To cull a duplicate after the fact: move its line from specs.jsonl to
specs_culled.jsonl in the same run dir and re-run ship.

## The accept gates

Numbers match the tool's output labels. HARD gates block the ship; REVIEW
gates print worklists. Standalone:

    python -m ostg.taskgen.accept out/runs/<set>/specs.jsonl [more specs.jsonl ...] \
      --ref cua-gym=... --ref osworld=...

    1  HARD    instruction jaccard, all    none >= 0.4. Real duplicates measure
               pairs                       0.5-0.65; same-theme-different-task
                                           measures <= 0.30.
    1b HARD    instruction tf-idf cosine,  none >= 0.5; the 0.35-0.5 band goes
               all pairs                   to hand review. Re-dressed duplicates
                                           top out at ~0.34-0.44 here (measured:
                                           the vlc pair, the listings pair), so
                                           the text layer flags them and the
                                           signature layer convicts them.
    2  REVIEW  grader signatures, all      what the probe READS -- identifier
               pairs                       word pieces, constants dropped.
                                           >= 0.30 (the measured knee) goes to
                                           hand review, not auto-fail: it
                                           catches re-dressed duplicates whose
                                           nouns all changed (a confirmed pair
                                           scored jaccard 0.29, signature 1.00)
                                           but is coarse on table specs.
    3  HARD    tf-idf cosine vs EACH       none >= 0.5, one line per --ref.
               --ref corpus                cua-gym = the co-trained benchmark;
                                           osworld-361 = train-on-test. Sharper
                                           than jaccard: idf downweights
                                           boilerplate, so shared
                                           DISCRIMINATIVE words score.
    4  REVIEW  axis balance                intents even; difficulty quota drift
                                           under 10% or CHECK.
    5  REVIEW  corpus concentration        what pairwise checks cannot see: a
                                           monoculture. Entities reused across
                                           >= 3 tasks (sentence-initial capitals
                                           excluded), distinct-bigram ratio,
                                           setup-template share.

External corpora get the text detectors only: signatures were measured (old
sig.py) not to transfer across grader styles.

## Files

    taxonomy.py             intent x domain x difficulty x ambiguity, voice
                            derived per cell; cells() draws briefs
    gen.py                  cells -> Claude -> specs.jsonl + task JSON
    ship.py                 re-emit + accept + control, one command, no logic
    control.py              the VM negative checks, on the real evaluation path
    accept.py               the gates, over finished spec sets
    merge.py                several run dirs -> one rollout set (one manifest)
    audit.py                LLM coverage audit: instruction vs grader, both ways
    gold.py                 gold script per spec, for control --gold injection
    traj_html.py            static HTML trajectory viewer over a result dir
    prompts/single_json.txt the whole prompt (SYSTEM + USER head)
    RUNBOOK.md              the standard commands, end to end

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
