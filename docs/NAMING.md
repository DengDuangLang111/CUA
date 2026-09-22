# 实验臂与语料命名标准

> 2026-08-23 立;2026-09-09 扩展并接上生成器。起因:`kE` / `a1h10` / `img3h3` / `nocap` 这类名字
> 只有当事人看得懂;08-25 定下第一版规范后一周内又出现 `mixbtf9b-2x4-lr1e6` / `cap1p5` / `taskw`
> 一轮手打名(`cap1p5` 曾被误读成 think-cap)。名字的职责是**让人一眼看出这个臂和基准差在哪**。
> **09-09 起名字由 `sft/armname.py` 从 sbatch 推导,不再手打**;本文件只写语法与规矩,
> 注册表(语料目录、变换、别名)的唯一真源是那个脚本。

## 评测运行标识（2026-09-16）

保留下面的canonical arm语法。标准评测脚本另用**模型ID→固定checkpoint**的注册表，以及自动生成的**唯一eval run ID**：`<model-id>--<benchmark>--<panel>-n<count>--<UTC>-<random>`。模型ID不能改绑其他checkpoint；同一配方的不同训练产物可使用不同模型ID，并用`arm`字段指向同一canonical arm。Benchmark、题数与机器分配保存在带SHA校验的plan.json，不靠拆文件名猜。命令、注册表填写和两机示例见 [EVAL_AUTOMATION.md](../sft/docs/EVAL_AUTOMATION.md)。

## 1 臂名格式

```
<骨干>-<训练法>-<语料>[-<偏离项>…][~e<N>][@<img>f<fold>[.t0][.ms100]…]
```

- **只写与标准配方不同的部分。** 完全按标准配方训练的臂,名字里没有偏离项 ——
  名字越长,说明这个臂动的东西越多、越不适合做单变量对比。
- **拓扑不进名字。** 2×4×accum8 与 4×2×accum8 都是全局 batch 64,是同一个模型
  (`mixbtf9b` 与 `mixbtf9b-2x4` 的规范名相同)。
- **`@` 后面是推理侧配置**(窗口、采样、步数),是评测记录的属性,不是权重的属性;
  同一份权重换推理配置 = 同前缀、只差 `@` 后缀。默认 `@10f1` 省略。
- **`~e<N>` 是中途快照**(未退火,见 `sft/docs/RESULTS.md` §6 的 @eN 口径),终点权重不写。
- 评测地点(WSL/AWS)、题集(eval100/heldout50/REST261)**不进名字**,记在结果目录与
  `MODEL_BOUNDARY.json`。

### 标准配方(省略即代表用它)

Qwen3.5 全参微调 · lr 3e-6(LoRA 1e-4)· 3 epoch · global batch 64 · warmup 0.1 ·
weight decay 0 · β₂ 0.999 · 余弦退火到 0 · max_length 81920 · IMAGE_MAX_TOKEN_NUM 2048 ·
preserve_thinking 开 · 梯度重计算开 · 语料建时 img10 / fold 1

TMAX骨干登记为 `tmax9b`（模型目录 `tmax-9b-cua-init`）：TMAX语言权重加原Qwen3.5-9B视觉组件，来源见专门实验计划。其r5训练沿用旧a2的65536长度，规范名为 `tmax9b-full-r5-ml65k`。

RL 工程探针（2026-09-22 临时登记，正式 B/C 臂命名另定）：在 SFT 规范臂名后加 `-grpoprobe`，如 `9b-full-r5-grpoprobe`；模型 ID 的 `--train<日期>` 是该步 GRPO 更新的日期，`--s<N>` 是累计 GRPO optimizer 步数（例：`9b-full-r5-grpoprobe--train20260918--s1`）。设计与进度见顶层 `CUA_RL_EXPERIMENT_DESIGN.md` / `CUA_RL_ENV_PLAN.md`。

### 标准推理配置(省略即代表用它)

`image_max 10 / fold_size 1` · temperature 1.0 · top_p 0.95 · max_steps 50 · max_tokens 81920

**2026-09 起标准是 10/1**(8 月是 20/10)。旧结果一律带 `@20f10`,否则会和新结果误比:
同权重 10/1 → 20/10 实测 −8pp(`sft/docs/RESULTS.md` §5.31/§5.34)。

## 2 各段的取值

| 段 | 取值 | 说明 |
|---|---|---|
| **骨干** | `4b` `9b` `27b` `27bq36` `vl4b` `tmax9b` | Qwen3.5-4B / 9B / 教师 Qwen3.8-27B / Qwen3.6-27B / Qwen3-VL-4B-Thinking |
| **训练法** | `full` `lora` `base` | 全参 / LoRA / 未训练 |
| **语料** | 短 id 或公式 | 见 §3 |
| **偏离项** | 下表 | 与标准配方不同的地方,可多个,顺序固定 |
| **快照** | `~e1.5` | 中途 checkpoint 的 epoch |
| **推理后缀** | `@20f10` `@3f1.t0` … | 见下表 |

### 偏离项(顺序固定:lr → ep → gb → wd → b → wu → ml → imgtok/imgmax → histcomp → nopt → r/a)

| token | 含义 | 标准(省略时) |
|---|---|---|
| `lr<v>` | 学习率;`lr1e5` = 1e-5,`lr1p5e5` = 1.5e-5 | full 3e-6,lora 1e-4 |
| `ep<N>` | epoch 数 | 3 |
| `gb<N>` | 全局 batch = 节点 × 卡 × accum × per-device bs | 64 |
| `wd<v>` | weight decay;`wd0p1` = 0.1(小数点写 p,沿用 `cap1p5` 的写法) | 0.0 |
| `b<v>` | adam β₂;`b0p95` = 0.95 | 0.999 |
| `wu<v>` | warmup ratio | 0.1 |
| `ml<N>k` | max_length;`ml65k` = 65536 | 81920 |
| `imgtok<N>` | `IMAGE_MIN_TOKEN_NUM=N`:每图强制上采样到 ≥N token(配套抬高的 MAX 不另记) | 未设 |
| `imgmax<N>` | 只改 `IMAGE_MAX_TOKEN_NUM` 时 | 2048 |
| `histcomp` | 渐变历史分辨率(`PYTHONPATH=histcomp`) | 关 |
| `vnograd` | 仅对完全冻结的视觉塔显式no_grad；不关闭语言模型梯度 | 关 |
| `nopt` | `preserve_thinking false` | 开 |
| `hermes` | 动作 token 的 loss 权重 ×2(旧代,a3/a7) | 关 |
| `r<N>a<M>` | LoRA rank / alpha | 32 / 64 |
| `smoke` | 带 `--max_steps` 的冒烟脚本,不是臂 | — |

### 推理后缀

| token | 含义 | 标准(省略时) |
|---|---|---|
| `@<img>f<fold>` | `--image_max <img> --fold_size <fold>` | `@10f1` |
| `.t0` | 贪心解码 | temperature 1.0 |
| `.ms100` | max_steps 100 | 50 |
| `.tok480` `.effmed` | 教师试点:图 480 token / 思考力度 medium | — |

## 3 语料命名

```
<来源>[+<来源>…][.<变换>…]
```

语料段里**不出现 `-`**(用 `+` 连来源、`.` 接变换),臂名才能无歧义地切成 骨干-训练法-语料-偏离项。
常用组合登记一个**短 id**(`mixb`),臂名里用短 id;没有短 id 的语料直接写公式(`r5.cap2k.img20`)。
公式本身就是对比提示:`v11n+v16` 与 `v11n+v16.tf` 一眼看出只差终止规范化。

### 来源

| token | 定义 | Tillicum `data/` 目录 |
|---|---|---|
| `r5` | Bhqs2t-r5 系 v11 rollout:362 轨迹 / 6,474 样本,img10/fold1,think 不截断,末步 100% terminate | `q38-Bhqs2t-r5nocapimg10-{v11100,v11500}` |
| `v11n` | v11 新批(i10x 重跑):312 轨迹 | `v11new-{500,all}` |
| `v16` | v16 判官准入:554 轨迹 | `v16-{main,pilot}` |
| `v16m` | v16 真 multi-app 子集:166 轨迹 | `v16-truemulti` |
| `v16s` | v16 严格准入:340 轨迹(`curate16 --strict`) | 在 `mixa-webstar-v16strict` 内 |
| `v11h` | v11-100 池:69 轨迹(旧代) | `q38-v11100` |
| `b` | v11-100+500 checker 全 pass:312 轨迹(旧代) | `q38e3B-{v11100,v11500}` |
| `bhqs` | 双判官+仲裁筛选(旧代) | `q38-Bhqs-{v11100,v11500}` |
| `abs` | 9 题面板时代 abs-pilot 语料(与 eval50 不可比) | — |

### 变换

| token | 定义 |
|---|---|
| `tf` | 终止规范化 terminalfix:末步重写并确定性拼上 terminate(success) |
| `ws` | WebSTAR 步级过滤:每步 0-10 分,>5 留作训练目标 |
| `sw` | SWE-MeM 轨迹内 token 均衡权重(须 `--is_binary_loss_scale false`,否则权重被静默丢弃) |
| `tw` | 任务均衡加权 loss_scale = c/N(同上) |
| `cap2k` | teacher think 超 2048 token 的训练目标屏蔽(think-cap 2048) |
| `np` | 去 teacher 散文(no prose) |
| `img20` `img3` `img1` | 建语料时每步截图上限(标准 img10 省略) |
| `vl` | 按 Qwen3-VL 格式重建 |
| `v` | 切了 5% 验证集 |

### 短 id

| 短 id | 公式 | 组成 |
|---|---|---|
| `mixa` | `r5+v16` | r5 + v16 判官准入 554 |
| `mixb` | `v11n+v16` | v11 新批 312 + v16 554 = 866 轨迹 |
| `mixc` | `v16` | 只有 v16 |
| `mixr5m` | `r5+v16m` | r5 + v16 真 multi 166 |
| `mixbtf` | `v11n+v16.tf` | mixb 同 866 轨迹,只补终止规范化 |
| `mixbtf.tw` | `v11n+v16.tf.tw` | mixbtf + 任务均衡加权 |
| `mixb.sw` | `v11n+v16.sw` | mixb + SWE-MeM 权重 |
| `mixaw` | `r5+v16s.tf.ws` | r5 + v16 strict 340,两半都过 WebSTAR |

**规矩:新语料先在 `sft/armname.py` 的 `CORPUS_DIRS`(目录 → 来源/变换)与 `CORPORA`(公式 → 短 id)
登记,再投训。** 未登记的数据目录组合会被生成器拒绝(exit 1)—— 这就是"不再手打"的机制。

## 4 对照表(历史名 → 规范名)

**历史结果目录与权重目录不改名**(它们是存档),看板与文档经别名显示规范名。
下表由 `python3 sft/armname.py table` 生成,改别名请改脚本再重新生成,不要手改这里。

<!-- BEGIN armname.py table -->
| 旧名 | 规范名 |
|---|---|
| `tmax9b-r5` | `tmax9b-full-r5-ml65k` |
| `mixA-9b` | `9b-full-mixa` |
| `mixa9b` | `9b-full-mixa` |
| `mixA-4b` | `4b-full-mixa` |
| `mixa4b` | `4b-full-mixa` |
| `mixB-9b` | `9b-full-mixb` |
| `mixb9b` | `9b-full-mixb` |
| `mixB-4b` | `4b-full-mixb` |
| `mixb4b` | `4b-full-mixb` |
| `mixC-9b` | `9b-full-mixc` |
| `mixc9b` | `9b-full-mixc` |
| `mixR5M-9b` | `9b-full-mixr5m` |
| `mixr5m9b` | `9b-full-mixr5m` |
| `mixaw9b` | `9b-full-mixaw-ml65k` |
| `mixbtf9b` | `9b-full-mixbtf` |
| `mixbtf9b-2x4` | `9b-full-mixbtf` |
| `mixbtf9b-2x4-lr1e6` | `9b-full-mixbtf-lr1e6` |
| `mixbtflr1e6` | `9b-full-mixbtf-lr1e6` |
| `mixbtf9b-2x4-lr1e5` | `9b-full-mixbtf-lr1e5` |
| `mixbtf9blr1e5` | `9b-full-mixbtf-lr1e5` |
| `mixbtf9b-histcomp` | `9b-full-mixbtf-histcomp` |
| `histcomp` | `9b-full-mixbtf-histcomp` |
| `mixbtf9b-taskw` | `9b-full-mixbtf.tw` |
| `taskw` | `9b-full-mixbtf.tw` |
| `mixbtf4b-cap1p5` | `4b-full-mixbtf-ml65k-imgtok3072` |
| `cap1p5` | `4b-full-mixbtf-ml65k-imgtok3072` |
| `mixbtf4b-cap2x` | `4b-full-mixbtf-imgtok4096` |
| `cap2x` | `4b-full-mixbtf-imgtok4096` |
| `mixB-9b-swemem` | `9b-full-mixb.sw` |
| `mixB-9b-lr1e5-1ep` | `9b-full-mixb-lr1e5-ep1-wd0p1-b0p95` |
| `lr1e5` | `9b-full-mixb-lr1e5-ep1-wd0p1-b0p95` |
| `mixB-9b-lr1e5-b999` | `9b-full-mixb-lr1e5-ep1` |
| `lr1e5b999` | `9b-full-mixb-lr1e5-ep1` |
| `mixB-9b-lr2e5-1ep` | `9b-full-mixb-lr2e5-ep1-wd0p1-b0p95` |
| `lr2e5` | `9b-full-mixb-lr2e5-ep1-wd0p1-b0p95` |
| `mixB-9b-lr2e5-gb128` | `9b-full-mixb-lr2e5-ep1-gb128-wd0p1-b0p95` |
| `lr2e5gb128` | `9b-full-mixb-lr2e5-ep1-gb128-wd0p1-b0p95` |
| `mixb9bw20` | `9b-full-mixb@20f10` |
| `mixb9bw20f1` | `9b-full-mixb@20f1` |
| `mixb9b-aws` | `9b-full-mixb` |
| `mixb4b50b` | `4b-full-mixb` |
| `nocap` | `4b-full-r5.img20@20f10` |
| `nocap50b` | `4b-full-r5.img20@20f10` |
| `nocap261` | `4b-full-r5.img20@20f10` |
| `kE` | `4b-full-r5.cap2k.img20@20f10` |
| `kEh3` | `4b-full-r5.cap2k.img20@3f1` |
| `kEh1` | `4b-full-r5.cap2k.img20@1f1` |
| `kD` | `4b-full-r5.cap2k.img20-lr1e5@20f10` |
| `kD15` | `4b-full-r5.cap2k.img20-lr1e5~e1.5@20f10` |
| `a1` | `4b-full-r5@20f10` |
| `a1h10` | `4b-full-r5` |
| `a2` | `9b-full-r5@20f10` |
| `a2261` | `9b-full-r5@20f10` |
| `a3` | `4b-full-r5-hermes@20f10` |
| `a7` | `9b-full-r5.v-gb128-hermes~e2@20f10` |
| `a6v` | `4b-full-r5.v-lr2e6-ep2` |
| `a5v` | `4b-full-r5.v-lr2e6-ep5` |
| `img3` | `4b-full-r5.img3@20f10` |
| `img3h3` | `4b-full-r5.img3@3f1` |
| `img1` | `4b-full-r5.img1@1f1` |
| `nocapnp` | `4b-full-r5.np.img20@20f10` |
| `nocapnp2` | `4b-full-r5.np.img20~e2@20f10` |
| `nocapnp238` | `4b-full-r5.np.img20~e2.36@20f10` |
| `np1e6` | `4b-full-r5.np.img20-lr1e6@20f10` |
| `nocapt0` | `4b-full-r5.img20@20f10.t0` |
| `nocapms100` | `4b-full-r5.img20@20f10.ms100` |
| `r5lora` | `4b-lora-r5.cap2k.img20@20f10` |
| `kG` | `4b-lora-r5.np.img20@20f10` |
| `kF` | `4b-lora-r5.np.img20-nopt@20f10` |
| `base` | `4b-base@20f10` |
| `basekeep` | `4b-base@20f10` |
| `baseh1` | `4b-base@1f1` |
| `base50b` | `4b-base@20f10` |
| `base261` | `4b-base@20f10` |
| `base9b` | `9b-base@20f10` |
| `base9b261` | `9b-base@20f10` |
| `t38` | `27b-base@20f10` |
| `t3850b` | `27b-base@20f10` |
| `27b` | `27b-base@20f10` |
| `qwen36-teacher` | `27bq36-base@20f10` |
| `bsstock` | `4b-full-b.cap2k-lr1e5~e1.02@20f10` |
| `bskeep` | `4b-full-b.cap2k-lr1e5~e1.02@20f10` |
| `lorastock` | `4b-lora-b.cap2k~e1.02@20f10` |
| `lorakeep` | `4b-lora-b.cap2k~e1.02@20f10` |
| `gb64keep` | `4b-full-b-lr1e5~e1.01@20f10` |
| `gb128keep` | `4b-full-b-lr1e5-gb128~e2@20f10` |
| `gb128ep2keep` | `4b-full-b-lr1e5-gb128~e2@20f10` |
| `b1epkeep` | `4b-full-b-lr1e5-ep1-gb8@20f10` |
| `richrich` | `4b-full-v11h-lr1e5-gb8@20f10` |
| `richstock` | `4b-full-v11h-lr1e5-gb8@20f10` |
| `rich150` | `4b-full-v11h-lr1e5-gb8~e1@20f10` |
| `leankeep` | `4b-full-v11h-lr1e5-gb8-nopt@20f10` |
| `leanstock` | `4b-full-v11h-lr1e5-gb8-nopt@20f10` |
| `bhqskeep` | `4b-full-bhqs.cap2k-lr1e5@20f10` |
| `vlbase` | `vl4b-base@20f10` |
| `vlsft` | `vl4b-full-r5.vl.img20@20f10` |
| `vl20` | `vl4b-full-r5.vl.img20-lr1e5@20f10` |
| `gb128` | `vl4b-full-r5.vl.img3-lr1e5-gb128@3f1` |
| `vlnocapnp` | `vl4b-full-r5.vl.np.img20@20f10` |
| `t38i5` | `27b-base@5f1` |
| `t38i10` | `27b-base@10f1` |
| `t38i20` | `27b-base@20f1` |
| `t38px480` | `27b-base@20f1.tok480` |
| `t38med` | `27b-base@20f10.effmed` |
| `t38i10med` | `27b-base@10f1.effmed` |
| `t38i20med` | `27b-base@20f1.effmed` |
| `t38i10px` | `27b-base@10f1.tok480` |
<!-- END armname.py table -->

## 5 怎么用

**看到两个名字,把不同的段圈出来 —— 那就是这次比较的变量。**

```
9b-full-mixb           vs  9b-full-mixbtf                     只差语料变换 .tf     ✓ 干净
9b-full-mixbtf         vs  9b-full-mixbtf-lr1e6               只差 lr              ✓ 干净
9b-full-mixb           vs  9b-full-mixb@20f10                 只差推理窗口(同一份权重)✓ 干净
4b-full-mixb           vs  9b-full-mixb                       只差骨干             ✓ 干净
9b-full-mixb-lr1e5-ep1 vs  9b-full-mixb-lr1e5-ep1-wd0p1-b0p95 只差优化器           ✓ 干净
9b-full-mixb           vs  9b-full-mixb-lr2e5-ep1-wd0p1-b0p95 差四项               ✗ 不能归因到任何单项
4b-full-r5.img20@20f10 vs  9b-full-mixb                       骨干/语料/窗口全不同 ✗ 别比
```

最后两行正是这个命名法的价值:**名字自己就在警告你别做那个比较。** 09-05 之前叫
`lr2e5` 的臂,名字里看不出它同时还动了 weight decay 与 β₂;`cap1p5` 看不出它还把
max_length 砍到了 65536。

## 6 规矩

1. **新臂一律用生成器**:`python3 sft/armname.py emit <x.sbatch>` 给出 `# ARM:` / `OUT=` /
   `RUN_NAME=` / `--served-model-name` 四行,粘进 sbatch 与 serve 脚本;看板键、结果目录
   `eval50-<臂>-<日期>`、`MODEL_BOUNDARY.json` 都用同一个名字。
2. **sbatch 预检加一行 `python3 sft/armname.py check $0`**:声明名 ≠ 推导名就拒绝投训。
3. **偏离项由生成器写全** —— 少写一个,就等于对读者隐瞒了一个变量;人不再手写。
4. **同一份权重的不同推理配置共享前缀、只差 `@` 后缀。**
5. **语料建出来时就登记**(§3 规矩),不要事后翻译。
6. **Slurm `--job-name` 不在本规范内**:squeue 全集群可见,作业名故意模糊(`vt-b9h`),别改。
7. **历史目录不改名**;对照表(§4)只服务显示与文档。

## 7 已知矛盾与未映射(2026-09-09 整编时查出,待用户裁定)

- **`r5lora` 的 cap**:旧表写 `4b-lora-img20`(无 cap),但它的 sbatch(`sft/scripts/train/archive/sft-q38Bhqs2t-lora-g8.sbatch`)
  与 kE 用同一份 `q38-Bhqs2t-r5-*`,而 kE 在旧表里是 `img20cap` —— 两者不可能一个带 cap 一个不带。
  以 sbatch 为准,对照表里 r5lora 已改为带 `cap2k`。`kG`/`kF` 沿用旧表(无 cap),未从 sbatch 复核。
- **教师窗口试点**(`t38i10` 等):看板标签里的 "slide" 按 fold 1 读,未从 runner 命令行核实。
- **`bhqs2keep` / `bhqs2tkeep` / `bhqs2lrkeep`**:CHECKPOINTS 无独立权重目录记载,疑与 kD/kE 同权重,未映射。
- **9 题面板时代**(`qwen35-4b-v1`、`q35-e1/e3/more`、`ep5*`、`more3*`):与 eval50 不可比,不映射。
- **旧代语料的建图窗口**:`b` / `v11h` / `bhqs` 的目录名不带窗口标注,公式里未写 `.img20`(推断为 20,未逐一核对)。

<!-- REPO NAV -->
[Repository map](../README.md)
<!-- /REPO NAV -->
