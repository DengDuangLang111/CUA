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
| `dash_status_daemon.sh` | the status/traj publisher loop (commits `dashboard/status.json` and eval50 traj viewers). Holds only the **path** of the deploy key (`~/.ssh/id_ed25519_cua`) — no secret material, so it is safe to version (corrected 2026-09-09; the old 'holds credentials' note below was over-cautious) |
| `dash_watchdog.sh` | supervisor for the two daemons (merged in from `control/` 2026-09-09; see its own header for behaviour) |

**Not copied here** (they hold or reach credentials, or are pure scratch):
`tunnel_qwen36_auto.sh`, the `faststat.sh` / `evalstat.sh`
monitor probes, and anything under `logs/`.

## Two rules these scripts encode, learned the expensive way

- **Kill the supervisor before the runner.** Killing only the runner makes the
  supervisor relaunch it, and then two things fight over the 3 VMs.
- **Restarting the rollout supervisor leaks a tunnel.** `v11_500_fp8.sh` starts
  `tunnel_qwen36_auto.sh` unconditionally, so anything that restarts it — such
  as `eval_more3_pair.sh` resuming the campaign — adds a second tunnel while the
  first is still bound to `:18001`. Observed 2026-08-14: the loser logged
  `cannot listen to port: 18001` every 30 s while the winner kept serving.
  Harmless here, and it self-heals when the old serve's wall expires (the loser
  grabs the freed port and connects to the chained successor), but a supervisor
  restart should kill any existing tunnel for its port first. Diagnose with
  `ss -ltnp | grep 18001` and then check whether that ssh's PPID still exists —
  a dead parent means the working forwarder is an orphan with nothing to restart
  it.
- **A bare `pkill` leaks the containers.** Always follow with
  `docker rm -f $(docker ps -aq)` — skipping it once starved the box to 4 GB
  free and made every new VM fail to boot.

## 2026-09-09 整编:`control/` 并入本目录

`control/`(08-17 提交)是同一批脚本的**第二份镜像**。两份的 `sft_dash.py` 逐字节相同;
两个 daemon 却已分叉 —— `control/` 那份更新:`sft_dash_daemon.sh` 带 08-16 的
"data-first push"(本仓库历史里的自动提交 `sft: refresh (data-first)` 正是它写的,证明它才是
WSL 上在跑的版本),`dash_status_daemon.sh` 带 08-15 用户决定(`eval50-*` 从第 1 题起发布)。
整编取新版并入本目录,删除 `control/`;`dash_watchdog.sh` 只有那边有,一并并入。
**待办**:WSL 09-09 不可达,尚未与 `$CTL` 正本做 md5 复核;可达后按上面的编辑规则重拉一次。
