# PLAN-20260818 — datagenv12 首波:补格式类任务(fmt-w1)

> 状态:进行中。分支 `datagenv12`(WSL worktree `/mnt/d/research/ostg-datagenv12/ostg`,
> 基于 v11.1@a1707aa9)。所有 prompt / ship 层改动先给 diff 批准再落。

## 一句话

语料 544 道任务里格式类只有 **1 道(0.2%)**,而 OSWorld-Verified 全量 15.2%、
eval-50 18%;该类并集解开率 3/9,其余类 32/41。本波:解锁判据 → 生成 50 道
格式题 → 教师 rollout → 成功轨迹作为**独立数据集 DS3** 并入训练 → 与 r5 做
单变量对照。

## 依据(全部经独立复算,两套分类法同向)

| 量 | 值 |
|---|---|
| 语料格式类占比 | 1/544 = 0.2%(关键词法;另一套 8 类普查 2.2%,align/font/transparent 零计数一致) |
| OSWorld-Verified 全量 | 56/369 = 15.2% —— 缺口是总体性质,非 eval-50 采样偶然 |
| eval-50 | 9/50 = 18% |
| 并集解开(14 跑) | 格式 3/9,其余 32/41;**基座单臂 2/9 —— 全部 SFT 臂合计只比基座多 1 道** |
| 机械成因 | grade 词汇表(probe/table/browser)表达不了呈现属性 + `<role>` 规定"判不了就别写" → 下笔前丢弃;换生成器无效(Qwen v11q2 同分布),加量无效 |
| 形态启发(n=10,弱) | 单对象单属性会,同属性多对象不会 |

## 目标 / 非目标

- 目标:打通"缺失类补进语料"的通路;验收看**产量与行为**。
- 非目标:eval-50 总分提升 —— 天花板 +5 道(并集口径)仍低于 MDE80≈8 道,
  **总分只记录,不作判定**。

## 五条硬约束

1. **DS3 独立**(`q38-fmt-w1`),不动 r5;训练用 `--dataset DS1 DS2 DS3` 挂载;
   build 与 r5 同参(terminalfix、`--think-cap 2048`、`--whole-traj-filter`、
   `--freeze-date "Monday, August 17, 2026"`)—— 补类是唯一变量。
   (cap 已知有反效果 §5.10,但本波不同时改两件事;去 cap 留给下一轮单独测。)
2. **grade=pptx 走规则式**(ref + method + value,宿主 python-pptx 读 XML 属性),
   照 `grade=table` 模式;**不做 gold-file 机器**。
3. **产量闸(教师通过率即探针)**:>50% 开训(~30 条轨迹 ≈ 语料 7.7%);
   30–50% 加量到 100+ 道再训;**<15% 停** —— 结论记为"教师能力瓶颈",本波止损。
4. **新 checker 审计**:抽 10 条通过轨迹,LibreOffice→PDF 渲染人工核终态
   (不得用同一 checker 自证);census / verify / corpusaudit 全跑。
   历史依据:本项目已出过 4 个 checker bug,全靠数字离谱才被发现。
5. **防污染**:生成题与 eval-50 的 9 道、官方 56 道格式题查重;官方题只可作
   教师能力参照,**绝不入语料**。

## 设计要求

- ≥ 半数为**同一属性、多个对象**(如三张幻灯片三种对齐);
- 应用配比向 impress / calc-chart / gimp 倾斜(bench 的格式题所在);
- prompt 改动:`<grades>` 加 pptx(规则式)、rule 6 翻转(给 `--convert-to
  odp:impress8` 配方并允许预置 deck)、intent 轴加 `restyle`。

## 步骤与闸

| # | 事 | 闸 | 状态 |
|---|---|---|---|
| 0 | 分支 + worktree | — | ✅ |
| 1 | prompt + taxonomy + gen/accept | 用户已批 | ✅ 落地,分支提交 `c05113a2` |
| 2 | 宿主检查器 `check_pptx_props` / `check_image_props` | 单测 + 已知反例 | ✅ 真 pptx/PNG 单测 6/6 过(正例 1.0;错值 / 越界 shape / 丢文件全部守错 0.0) |
| 3 | 生成 50 道 | 查重闸 + 人审 5 道抽样 | |
| 4 | 教师 rollout | 需 Tillicum 恢复(08-19 09:00)+ VM(与 kC/kE/kD1/kG 争,用户定序) | |
| 5 | checker 审计 | 硬约束 4 | |
| 6 | build DS3 | 与 r5 同参;census/verify/corpusaudit | |
| 7 | 训练 | 240310 的 LoRA 孪生,唯一变量 = +DS3 | |
| 8 | 评测 | stock · pick_ckpt endpoint · INCOMPLETE 闸 | |

## 验收指标

- 教师通过率(闸 3 的读数本身就是探针结论);
- DS3 成功轨迹数 / 样本数 / 语料占比;
- 训后行为面板:eval-50 那 9 道格式题上的行为(是否出现"改属性→确认→保存"链)、
  显式 terminate 率不回退、think 尾部不恶化;
- eval-50 总分:**只记录**。

## 落地纪要(2026-08-18)

- 改动比预案又小了一圈:**闸零改动** —— 现有"禁裸 `--convert-to odp/pptx`"正则
  (`gen.py:615`)本来就放行带冒号的限定滤镜,`pptx:"Impress MS PowerPoint 2007
  XML"` 直接通过;prebuild / accept / control / rollout 四层零改动维持。
- 检查器落在 OSWorld fork `generated_tasks.py`(第 19、20 个自定义 metric,
  沿既有惯例),`metrics/__init__.py` 注册;**惰性 import**,缺库不拖垮整个
  evaluator。宿主 venv 实测已带 python-pptx 与 PIL。
- 尚未做:prebuild 容器里冒烟 `odp → pptx` 滤镜串(生成前的第一件事);
  restyle 波次的抽签限制(gen 只抽 restyle 格)。

## 风险

| 风险 | 接住它的闸 |
|---|---|
| 教师做不了格式题 | 闸 3 直接停,损失仅 prompt 工作(可复用) |
| 新 checker 判错把坏轨迹放进语料 | 闸 5(异路径人工核) |
| 生成题撞基准 | 闸 3 查重 |
| 与残余 eval 抢 VM | 步骤 4 前用户定序 |
