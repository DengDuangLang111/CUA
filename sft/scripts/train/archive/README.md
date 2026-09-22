# sft/scripts/train/archive/ —— 历史 sbatch(2026-09-09 归档,64 个)

sbatch 是每个臂的**配置真源**(`sft/docs/CHECKPOINTS.md` 口径:目录名以 sbatch 里的 `DS=` 为准),
所以只归档、**不删**。留在 `sft/scripts/train/` 主目录的是 21 个 `mix*` 训练 sbatch(mix 时代的
每个训练臂各一份)+ `pick_ckpt.sh`。

| 组 | 数量 | 说明 |
|---|---|---|
| `sft-q38*` `sft-vl*` | 24 | 8 月旧代训练(B/Bs/Bhqs/Bhqs2t/rich/lean/VL 线);臂名对照见 `docs/NAMING.md` 对照表与 `sft/docs/CHECKPOINTS.md` §2。含 `sft-vl20pic-gb128-resume`(也是下面 resume 组的一员,两组重叠 1 个,故总数 64 不是 65) |
| `serve-chain-*` | 29 | 旧 eval 链的 serve 端;被 `sft/scripts/eval/chain_eval.sh` + Klone READY 流程取代 |
| `*-smoke` | 3 | 投全程前的 3 步冒烟(cap2x-sp2 / histcomp / taskw) |
| `*-resume` | 5 | 崩溃续跑(记录了从哪个 checkpoint、加了什么补丁续的 —— 是终点权重的来历,别删) |
| 探针/合并 | 4 | `ckptprobe-all` `probe-z3a16` `merge-lora-bs` `serve-klone-a100-mixb4b` |

<!-- REPO NAV -->
[Repository map](../../../../README.md)
<!-- /REPO NAV -->
