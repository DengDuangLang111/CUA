# PLAN 2026-08-15 — rollout 降 2 VM,腾 1 VM 跑 rich/rich eval

> **活跃计划文档**:任务全部跑完后归档进 `outdated/`。批准:用户 2026-08-15
> ("可以…执行任务")。进度勾选随执行更新;读数入 `EXPERIMENTS.md` /
> `sft/TRAINING.md`,本文只管计划与执行状态。

## 目标

1. v11-500 教师 rollout 从 3 VM 降到 2 VM 继续(重启法,同 result_dir 断点续跑)。
2. 腾出的 1 VM 立刻开始 **rich/rich** eval(rich checkpoint-450 + keepthink 模板
   + `--preserve_thinking`),50 题 verified-eval-50 non-proxy。

## 依据(已验证)

- `run_multienv_qwen.py:367 get_unfinished()`:resume 跳过有 `result.txt` 的任务,
  删除无 result 的半成品并重跑 → 重启不丢已完成的 261 题,代价 ≤3 个在飞 episode 重跑。
- 内存:基线 1.0 + 双 runner 1.3 + 3×4.61 = 16.2 GB < 19.5 GiB 可用(§OPS.md 5)。
- 顺序偏离知情:原批准顺序 base-stock 先;rich/rich 先跑,分数在 base 落地前只是绝对值。
- 默认项:checkpoint-450(3 epoch 终点);150/300 留作 epoch 对照。

## 步骤与状态

- [ ] A1 温和终止 rollout runner,等容器退净
- [ ] A2 原命令改 `--num_envs 2` 同 result_dir 重启,确认跳过已完成、2 容器在跑
- [ ] B1 keepthink 模板推上 Tillicum
- [ ] B2 4B serve sbatch(rich/checkpoint-450,`--chat-template` keepthink,新端口)提交并 RUNNING
- [ ] B3 WSL 新隧道 18011(复用 ControlMaster,无 Duo)
- [ ] B4 eval runner 起跑:1 env,50 题,`--preserve_thinking`,参数按 TRAINING.md 协议
- [ ] C 两路监控挂上(过滤器覆盖失败态);EXPERIMENTS / TRAINING 现状块更新
- [ ] D 完成:eval 50/50 落地,读数入账;rollout 收尾后本文归档

## 预算

- rollout 剩余 ~183 题 @2VM:预计 +8–12 h 于原计划
- rich/rich eval:50 题 @1VM ≈ 6–8 h;serve 1×H200 短 job
