# OSWorld-Verified harness snapshot + a2 baseline run metadata

Pulled 2026-10-03 from the Windows WSL host; md5 checked against the originals.

| File | Source | md5 |
|---|---|---|
| `osworld-verified-a8b2448.patch` | `git format-patch --stdout 091f5ef..a8b2448` in `/mnt/d/research/OSWorld-armsel` (branch `armsel-select`) | `5ca34ca6093371493147933455dc851e` |
| `a2-eval50-a2-20260823.args.json` | `/mnt/d/research/OSWorld/results_generated/qwen35-9b-sft/eval50-a2-20260823/args.json` | `882976d0961b412080599a912a55dbca` |
| `a2-eval50-a2-20260823.MODEL_BOUNDARY.json` | same dir, `MODEL_BOUNDARY.json` | `b89c4e25d55f442552bcb049f7a4f3cb` |

## Rebuild the runtime

```bash
git clone https://github.com/xlang-ai/OSWorld && cd OSWorld
git checkout 091f5ef1
git am <CUA>/reference/osworld-verified-harness/osworld-verified-a8b2448.patch
git rev-parse HEAD^{tree}   # must print 74b0610489fd73259a444040b98a81cbfe8fd1fc
```

The tree hash was checked on 2026-10-03: applying the patch to a clean `091f5ef1` gives the same tree as `a8b2448` on the WSL host. `git am` warns about trailing whitespace on 6 lines; that is expected.

The patch has 4 commits on top of upstream `091f5ef`:

- `b80d825`, `3df1ef4`: AWS provider tagging and a VM cleanup script (not used by docker runs).
- `b7dce12`: snapshot of the main Verified eval working tree (17 modified + 8 untracked files: qwen agent changes, `generated_tasks.py` evaluator, eval panels). `.env` and caches are not included.
- `a8b2448`: `OSTG_ARM_SELECT` hook in `mm_agents/qwen/main.py`. Unset or `0` keeps the original single `call_llm` path.

## What the two JSON files are

- `args.json`: written by OSWorld's own runner (`scripts/python/run_multienv_qwen.py`, `vars(args)` dump) into the result dir. Contains no secrets (`api_key` null, `client_password` empty).
- `MODEL_BOUNDARY.json`: not part of OSWorld. Our CUA eval launchers write it into the result dir before the run starts. It records the weights vLLM reported actually loading (`/v1/models` `root`), precision, effective sampling including server-side defaults the client never sends (`top_k 20`), harness env flags and the task panel.

## Known caveat

`b7dce12` was taken from the workstation's main eval tree. The Windows main tree (`/mnt/d/research/OSWorld`) matches it in 22 of 25 files. The 3 that differ:

- `desktop_env/controllers/python.py`: snapshot decodes screenshots with PIL to reject corrupt frames; Windows checks magic bytes only.
- `desktop_env/providers/docker/provider.py`: snapshot reads VM RAM and CPU from env vars, with the same 4G/4 defaults.
- `mm_agents/qwen/images.py`: Windows adds an `OSTG_MIN_PIXELS` env var (added 2026-09-05, after the a2 run).

The a2 baseline ran on the Windows tree on 2026-08-23. Its exact `python.py` at that time was not recorded.
