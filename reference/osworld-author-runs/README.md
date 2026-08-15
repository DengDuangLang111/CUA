# Configs from the OSWorld authors' own published runs

Pulled 2026-08-14 from `huggingface.co/datasets/xlangai/ubuntu_osworld_verified_trajs`
(the authors' trajectory release: 15+ model variants, 1000+ episodes, 500 GB).
Fetched by HTTP range request against the zip central directory — no archive was
downloaded in full. Tool: `sft/tools/zpeek.py`.

These are **not** reconstructions. Each file is the verbatim `args.json` the
runner wrote at the start of a real run whose trajectories are in that archive.

| file | archive | benchmark | notes |
|---|---|---|---|
| `mano-qwen25vl-verified361.args.json` | dataset root | Verified 361 (`test_nogdrive.json`) | the `mano` agent, `qwen25vl` infer mode |
| `qwen37plus-verified361-100steps.args.json` | `qwen37-plus_100steps_0524.zip` | Verified 361 | **the directly comparable one** |
| `qwen36-think-v2-300steps.args.json` | `qwen36-cua-think_300steps_0510.zip` | OSWorld-V2 (102) | `SFT_qwen36_plus_think` |
| `qwen36-nothink-v2-300steps.args.json` | `qwen36-cua-nothink_300steps_0510.zip` | OSWorld-V2 (102) | `SFT_qwen36_plus_fd11-ep3` |
| `qwen35-rl-tools_def.json` | `qwen35_osworld_eval_traj.zip` | Verified, RL pipeline | the literal tool schema sent to the model |

Scores computed from each archive's own `summary/results.json`:

- **qwen3.7-plus, Verified 361, 100 steps: mean 0.6899, exact-1.0 66.6% (n=374).**
- qwen3.6-think, OSWorld-V2 102, 300 steps: mean 0.2984, exact-1.0 6.3% (n=95).
