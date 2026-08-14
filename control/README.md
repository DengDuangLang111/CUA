# Control scripts — the machinery behind the dashboard and the rollouts

These run on **WSL** at `/mnt/d/research/osworld-verified-control/`. This
directory is a **versioned copy**, not the execution copy: nothing here runs
from the repo. It exists because DASHBOARD.md and sft/TRAINING.md document these
scripts as load-bearing, and until 2026-08-14 they lived on one WSL disk with no
history at all.

**Editing rule: change the WSL copy, then re-copy here.** Do not edit these and
expect anything to happen. After copying, verify md5 — a bare `for` loop with
nested quotes silently produces empty files over the three-hop
`ssh → wsl → ssh` path (CLAUDE.md §9).

```bash
ssh osworld-windows 'wsl -e bash -s' <<'EOF' | tar xf -
cd /mnt/d/research/osworld-verified-control
tar cf - sft_dash.py sft_dash_daemon.sh run_arm.sh v11_500_fp8.sh final_evals.sh eval_more3_pair.sh
EOF
```

| file | what it is |
|---|---|
| `sft_dash.py` | writes `dashboard/sft.json` and publishes per-arm trajectory viewers. Holds the arm registry: explicit `ARMS`, plus `FAMILY` patterns for `q35-<run>-ep<k>` (mid-schedule snapshot) and `q35-<run>-final` (annealed product). An unknown arm still appears, labelled by directory name |
| `sft_dash_daemon.sh` | 5-minute loop around the above, working in the second clone `cua-dash-sft` so it can never contend with `dash_status_daemon.sh` |
| `run_arm.sh` | one tier-3 arm end to end: wait → cancel stray serve → serve → 9 tasks → tear down. Has the port-collision detector |
| `v11_500_fp8.sh` | switches the teacher serve BF16 → FP8 and supervises the v11-500 rollout across the serve's 12 h wall and node changes |
| `final_evals.sh` | tier-3 for the **final** checkpoint of each training arm. Waits for every `sft-*` job to leave the queue |
| `eval_more3_pair.sh` | the scoped version: pause v11-500 → evaluate two finished arms → resume. Written because `final_evals.sh` would have blocked ~10 h on unrelated jobs still running |

**Not copied here** (they hold or reach credentials, or are pure scratch):
`tunnel_qwen36_auto.sh`, `dash_status_daemon.sh`, the `faststat.sh` / `evalstat.sh`
monitor probes, and anything under `logs/`.

## Two rules these scripts encode, learned the expensive way

- **Kill the supervisor before the runner.** Killing only the runner makes the
  supervisor relaunch it, and then two things fight over the 3 VMs.
- **A bare `pkill` leaks the containers.** Always follow with
  `docker rm -f $(docker ps -aq)` — skipping it once starved the box to 4 GB
  free and made every new VM fail to boot.
