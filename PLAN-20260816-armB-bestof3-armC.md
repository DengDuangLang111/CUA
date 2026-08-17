# PLAN 2026-08-16 — B 臂(量)→ ep1 曲线(深)→ best-of-3 重跑(质)→ C 臂

> **活跃计划文档**:全部任务跑完并入账后归档进 `outdated/`。批准:用户 2026-08-16
> 凌晨("你先写一个接下来的计划md,跑完了这一切任务再归档")。
> 背景:eval-50 头两臂给出 base/keepthink **38%** > rich/rich **28%** ——
> arm A(69 轨迹 ×3ep 全参)对 Verified 迁移为负,损伤集中在语料稀薄域
> (窄化签名)。本计划用三个可测实验拆开 **量 / 深 / 质** 三个嫌疑。

## 0 现有过滤的事实(2026-08-16 核对 sft/traj.py + build.py)

已有(片段级,arm A 用过):撞顶轨迹截 `low_diversity_tail`(≥8 步、≤3 种动作
的尾巴);非撞顶截 `tail_run`(结尾逐字节同动作连段);中途 ≥8 连同动作只保
第一步为训练目标(历史保留)。**没有**(B/C 新增):整条剔除撞顶侥幸 pass;
DONE/terminate 纪律要求。

## 1 流水线(依赖顺序)

```
v11-500 rollout 收尾(3 VM,344/444 起)                        ← 进行中
   ├─→ [GPU] B 数据构建(500+100 成功轨迹,新过滤)→ B 训练 3ep(存 ep 边界)
   └─→ [VM]  ep1 eval(arm A ckpt-150,2 VM,~3.5h)‖ 重跑一(1 VM 起步)
                └─ eval 撤场后 3 VM 全给重跑一/二(各 ~20h)
B-ep1 / B-ep3 eval(各 2-3 VM ~3h)                             ← 量+深的裁决
best-of-3 选择 → C 数据构建 → C 训练 → C eval                  ← 质的裁决
```

## 2 各步细则与判据

- **B 数据构建**:v11-500 + v11-100 全部 score==1.0 轨迹,**新增两条整条级过滤**
  (用户拍板 2026-08-16):①撞 50 步上限的 pass 整条剔除;②从未 emit
  terminate/DONE 的 pass 整条剔除。片段级过滤照旧。构建走 `sft/pipeline.sh`
  一键;count 与剔除清单入 TRAINING.md。
- **B 训练**:同 e3 配方(全参、lr 1e-5、3ep、epoch 边界 checkpoint)。
  **不预设 3ep 为终点** —— ep1 与 ep3 都要 eval。
- **ep1 eval(arm A ckpt-150)**:rich 权重的 1-epoch 点,keepthink + preserve,
  eval-50。判据:若 ep1 显著优于 ep3(28%)、逼近或超过 base(38%),
  "练太深 = 遗忘"实锤,后续训练默认 1-2ep + 考虑 LoRA/低 lr。
- **100 重跑 ×2**:run38 同款(教师 3.8、t1.0、ms50、thinking on),
  result_dir 分别 `v11-100-t1-rerun2-<date>` / `-rerun3-<date>`。
- **best-of-3 选择规则**:每题在三次跑(原跑 + 两重跑)的成功轨迹里选
  **最短的合格轨迹**;合格 = emit 过 terminate 且未撞顶。全部不合格则该题
  弃权(宁缺毋滥)。同长度平手取带显式验证动作者(先记规则,C 构建时实现)。
- **C 数据构建 + 训练 + eval**:best-of-3 语料,epoch 数由 ep1-eval 结论决定。
- **eval 一律**:verified_eval50_nonproxy,keepthink + preserve,同 runner 同参
  (top_k 20 在 serve override)。臂间只比这张表。

## 3 资源与预算

| 项 | 资源 | 估时 |
|---|---|---|
| 500 收尾 | 3 VM | ~20h(进行中)|
| B 构建+训练 | Tillicum GPU | ~1 天(与 VM 无关,500 落地即起)|
| ep1 eval | 2 VM + 1 GPU serve | ~3.5h |
| 重跑 ×2 | 1→3 VM + 教师 serve | ~2 天 |
| B-ep1/ep3 eval | 2-3 VM + GPU serve | 各 ~3h |
| C 构建+训练+eval | GPU + VM | ~1 天 |

## 4 进度勾选

- [x] v11-500 rollout **444/444:250 过/194 败 = 56.3%**(末题三世卡死于
      130s 铡刀,600s 标准化后通关 1.0;终版 census:严格幸存 **312 条/5,674
      步样本** = arm A 的 4.7 倍,整条级毒点 8/320,采用严格版)
- [x] 质量普查固化:`ostg.sft.census`(复用 build 同款 traj 加载器,枚举自
      harness import;pipeline.sh 第 0 步 + 可独立调用)—— B 构建前的对表会
      用它出数(用户规矩:检测走 pipeline,不写一次性脚本)
- [x] B 数据构建 + 到仓(2026-08-16 晚):census 后 build `--whole-traj-filter`,
      剔除整条 8(v11-100 1 条 cap-hit;v11-500 7 条,见 report.json 的
      dropped_whole_traj 名单)→ **312 轨迹 / 5,659 步样本**(1,181 + 4,478),
      `ship_dataset.sh` 双边校验 SHIP OK(q38e3B-v11100、q38e3B-v11500)
- [~] B 训练**已提交:job 235308**(2026-08-16,sbatch 入库 CUA@9cc722d3)。
      3ep 用户拍板;单卡 ~25h 超 24h QOS 墙 → **2×H200 数据并行,accum 8→4,
      全局 batch 保持 8 与 arm A 逐位同配方**,预计 ~14h,墙 20h。
      `--save_strategy epoch` 取精确 ep1/ep2/ep3 checkpoint(供量的裁决 eval)。
      预检两数据集 55,736 图片引用 0 失效,已进 swift 启动。
- [x] ep1(A-ckpt150)eval **完成:13/50 = 26% ≈ ep3 的 28% —— epochs 判据出局,损伤属于语料本身**(详 TRAINING.md);原 [~] 记录保留:
- [~] ep1(A-ckpt150)eval **提前开跑**(2026-08-16 02:36,用户决定:信息价值
      最高,先于 500 收尾执行)—— serve 233719,keepthink+preserve,2 VM;
      rollout 同期降 1 VM(run38e)。落地后回填结论。
      **过程发现(03:00–03:50)**:ckpt-150 行为上处于半迁移态 —— 熟悉局面短平快,
      陌生局面单步思考 2 万 token(但都自愿闭合、出真动作,从未撞 81920);
      client 默认 130s 读超时恰卡在其行为分布中间,长思考被系统性枪毙重抽
      (ep1 开局 4 题就 10 次重试、两题摸到 3/5;对照:ep3 全程 2 次、base 0 次)。
      修:`OSWORLD_OPENAI_TIMEOUT=300`(纯环境变量,放行全部已观测行为并保留
      安全网;对 base/ep3 无追溯影响 —— 它们的步远低于旧闸)。03:50 重启生效,
      已过 2 题保留。"半迁移态的行为退化"本身入账为 epochs 曲线的定性发现。
      **04:25 二次修正(用户方案)**:300s 仍被重尾思考击穿,且发现 openai 客户端
      内层默认重试 ×3 与外层 ×5 相乘(单步最坏 75 分钟,03:59–04:14 的"环境
      挂起"实为一次调用在内层打转)。改 **600s**:81920 生成上限(~510s 含
      prefill)永远先于客户端挂断到达 → 超时与双层重试结构性休眠,慢步全部
      产出真实数据。timeout 只影响哪些生成被丢弃、不改模型策略,臂内混合
      时限已在此註记。
- [ ] 重跑一完成 / [ ] 重跑二完成
- [ ] B-ep1 eval / [ ] B-ep3 eval → 量的裁决入 TRAINING.md
- [ ] best-of-3 选择脚本 + C 构建(选择统计入账)
- [ ] C 训练 + eval → 质的裁决入 TRAINING.md
- [ ] 全部入账后:本文与 PLAN-20260815 一起归档 outdated/
