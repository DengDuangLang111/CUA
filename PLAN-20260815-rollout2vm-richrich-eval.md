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

- [x] A1 run38.sh 链 + runner 终止,容器清零(17:05)
- [x] A2 run38b.sh 从 **291/444** 断点续跑,`num_envs 2` 验证(17:11)
- [x] B1 keepthink 模板上 Tillicum,md5 一致(863e28c4…)
- [x] B2 serve job **232766** RUNNING @g008(vLLM 起,chat_template 加载确认)
- [x] B3 隧道 18011 起(ControlMaster 复用,无 Duo);**render 对照验证 keepthink 生效**
      (同对话带/不带历史 think 渲染 38 vs 30 tokens,差值恰为 think 块)
- [x] B4 eval runner 起跑 17:21(pass 1 at 0/50,`--preserve_thinking` + `num_envs 1` 验证)
- [x] C 两路监控挂上(DONE|FATAL 过滤);现状块已更新
- [x] D2 **再平衡(2026-08-15 19:45,用户决定)**:eval 提速为主 —— rollout 降到
      **1 VM**(run38c.sh,同 result_dir 续跑),rich/rich eval 升到 **2 VM**
      (同脚本改 `--num_envs 2`,断点续跑自 13/50)。预计 eval ~4 分钟/题,
      剩余 ~35 题 ≈ 2.5h;rollout 剩 ~145 题 @1VM 会拖到数天 —— 预期是 eval
      矩阵(base 等臂)接着占这 2 VM,矩阵跑完再还给 rollout。
- [ ] D 完成:eval 50/50 落地,读数入账;rollout 收尾后本文归档

执行备注:run38.sh 的 stop_runner 会 `docker rm -f` 全部容器,run38b/run_eval 的
清理改为按 result_dir 模式 pkill + 共存时跳过 docker 清理;发现 5 个历史积累的
eval38 隧道副本(pkill -f 匹配不到 env 变量)+ 1 条 18001 死隧道(evalfp8)。
**已清理(2026-08-15 用户批准)**:杀 5 留 2 —— 18020/18011 各留实际持有端口的
那个实例,清后双端点复检 200/200。根治(run38 系脚本改 pidfile 式去重)是程序
修改,留待下次 campaign 启动前提 diff。

## 预算

- rollout 剩余 ~183 题 @2VM:预计 +8–12 h 于原计划
- rich/rich eval:50 题 @1VM ≈ 6–8 h;serve 1×H200 短 job
