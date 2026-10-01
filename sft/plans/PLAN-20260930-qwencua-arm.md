# Qwen-CUA-397B 当动作级 reward model(ARM),按 action-reward-models 仓库做法蒸馏回 9B

2026-09-30 草案,**待用户逐项核对(§7),未部署、未下载、未改代码**。
背景与原仓库数字:`docs/READING.md`「动作级 reward model」节;构思:`docs/IDEAS.md` 末节。

## 1 用哪个模型(已核实)

| | Qwen-CUA | Qwen-CUA-Max |
|---|---|---|
| 规模 | 397B 总参数 / 每 token 激活 17B,MoE 512 专家 top-10 | >1T(仅 README 提到) |
| 开源 | **是**,HF `xlangai/Qwen-CUA`,Apache-2.0,非 gated | **否**,HF 全站搜不到 |
| 权重 | BF16,107 个文件,**806.8 GB** | — |
| 报告分数 | OSWorld-Verified 86.2 | 87.6 |

架构 `Qwen3_5MoeForConditionalGeneration`;60 层,每 4 层一层全注意力(其余线性注意力),
2 个 KV 头 → KV cache 很小(全注意力 15 层 × 2 头 × 256 维 × K/V × 2 字节 ≈ 30 KB/token)。
视觉 patch 16、合并 2 → 1920×1088 截图 2040 token,与我们 9B 相同。
动作格式:`computer_use` XML,坐标 0..999 归一化网格(我们的 harness 是 `relative`,**是否同一网格
待用真实 payload 核对**)。官方采样参数 temp 0.6 / top_p 0.95 / top_k 20,默认开思考。

## 2 部署(Tillicum H200,141 GB/卡)

**4 卡放不下 BF16**:4×141 = 564 GB < 807 GB 权重。两条路:

| | A:4 卡 + 自转 FP8 | B:8 卡 BF16 |
|---|---|---|
| 权重 | ~403 GB(FP8 E4M3,128×128 分块) | 807 GB 原样 |
| 显存余量 | ~160 GB 给激活/KV/视觉(KV 很小,够) | 官方推荐配置 |
| 额外步骤 | 转换 + 转换器验证 | 无 |
| 24h 费用(按 $0.90/卡时) | ~$86 | ~$173 |
| 排队 | 4 卡容易 | 要整 8 卡节点,难;fairshare 消耗翻倍 |
| 数值 | 与原权重有量化误差 | 原样 |

**A 的依据**:Qwen 官方发布了同架构 `Qwen/Qwen3.5-397B-A17B-FP8`,其 BF16 版参数总数
403,397,920,304 与 Qwen-CUA **逐位相同**。量化配置可照抄:`quant_method fp8`、activation dynamic、
`weight_block_size [128,128]`、官方 `modules_to_not_convert` 清单(lm_head、embed、线性注意力
conv1d/in_proj_a/in_proj_b、MoE gate、shared_expert_gate…)。逐分片 CPU 转换,不需整模型进内存。
~~转换器验证 / 离线转换~~ **已被 §8 取代**:vLLM 0.25.1 支持加载时在线做同格式分块 FP8
(`fp8_per_block`),不再自写转换器;原先"在线量化会 OOM"的判断对这版不成立。

**两条路共用的前置检查(需 Duo 登录后做)**:
1. 现有 vLLM(0.25.1)是否注册了 `Qwen3_5MoeForConditionalGeneration`;没有就单独建 nightly 环境。
2. `/gpfs/scrubbed/jy050706/models/` 剩余空间与配额:A 需要 ~1.21 TB(BF16 + FP8,转完可删 BF16),B 需要 0.81 TB。
   scrubbed 长期不访问会被清理。
3. 下载速度:先下 10 GB 实测再估总时长。
4. H200 空闲情况(`sinfo`)与 `video` 账户 fairshare。

**时间顺序**:24 小时的 GPU 占位要等权重就绪、候选采样就绪后再开始,否则 GPU 空占。
作业名用含糊名(memory 规矩),例如 `srv-h4`。

## 3 流程(逐阶段对应仓库 A–E,采用仓库里成功的那一版)

仓库成功版(`build_distill_selections.py`):**每个候选单独打分 0–1 → 最佳分 < 0.7 则丢掉该状态 →
平局取多数票(同 `action_str` 出现最多)→ 离线**;对照 = 同状态随机选一个候选。
失败版(在线、训练出的 4B 选择器、无门槛)−4.2pp,不采用。

| 阶段 | 仓库 | 我们 |
|---|---|---|
| 状态 | gold SFT 轨迹的状态 | r5 语料 6,474 个样本(每个样本的输入就是一个状态,prompt 逐字节可复原);先抽 200 做试点 |
| A 候选 | 当前 actor 每状态采 5 个,temp 1.0 / top_p 1.0 | 9B 学生每状态 n=5,同一请求共享前缀;候选 = 思考+动作原文 |
| 预检 | `onpolicy_precheck.py`:选中≠多数票的比例 <10% 停,>25% 值得 | 原样;"同一动作"判据见 §7-Q6 |
| B 打分 | GPT-5.5 逐候选打分(PRM prompt:任务 + 当前截图 + 最近 5 步动作及思考 + 单个候选及其思考 → `{"score": 0–1}`) | **Qwen-CUA 替代 GPT-5.5**;prompt 照仓库,只做最小替换(web→desktop、去 URL、坐标网格说明),替换清单与 sha256 入档 |
| C 构建 | `build_onpolicy_sft.py`;可选 `--only-changed` | 原样 |
| D 训练 | actor 续训:LoRA all-linear r16,lr 1e-4,1 epoch,视觉塔不训,prompt 不算 loss | 见 §7-Q9 |
| E 评测 | 贪心 n=1,无判官;三臂:基线 / 选中 / 随机候选 | 我们的标准 Verified100 协议;三臂同协议 |

## 4 量级估算(低置信度,试点后重估)

- 全量:6,474 状态 × 5 = 32,370 个 9B 候选 + 32,370 次 Qwen-CUA 打分。
- 打分输入 ≈ 1 张图 2040 token + 历史与候选文本约 2–4k token;不开思考时输出只有一个 JSON。
  5 个候选共享前缀(截图+历史),前缀缓存若对线性注意力生效,预填充约 1 次/状态。
- 24h 窗口对打分量足够(不开思考的情况);开思考时输出量随思考长度放大,试点实测再定。
- 9B 候选采样不能和 Qwen-CUA 共用这 4 卡,需要另一份 GPU(见 §7-Q4)。

## 5 风险

1. **同家族偏好**:Qwen-CUA 与学生都是 Qwen3.5 系,可能偏好"像 Qwen 的"动作;GPT-6 暂无 API,
   没有独立第二判官。缓解:对照臂(随机候选)仍能判定"选择是否有用"。
2. **门槛 0.7 是给 GPT-5.5 分数定的**。WebSTAR 时换判官保留率差 19pp,所以要先看 Qwen-CUA
   在试点里的分数分布再定。
3. **单步看不见后果**(保存格式、快捷键是否生效),末步 DONE/FAIL 尤甚(§7-Q8)。
4. **崩溃信号**照仓库失败版监控:终止率、撞步数上限率、重复动作率、wait/screenshot/scroll 占比。
5. FP8 量化误差(仅 A 路)。

## 6 已完成 / 未完成

- 已核实:HF 模型存在与大小、架构、官方部署参数、官方 FP8 格式、仓库成功版的打分与选择规则、PRM prompt 原文。
- 未完成:Tillicum 侧任何检查(需要 Duo)、下载、转换、部署、任何代码。

## 7 用户核对结果(2026-09-30 晚)

| # | 项 | 定 |
|---|---|---|
| 1 | 部署 | **A:4×H200 + FP8**;下载 `xlangai/Qwen-CUA` 已批准 |
| 2 | 学生 | 纯 r5 9B = a2 = `sft/out/img10-9b/v0-20260822-024940/checkpoint-306`(默认,用户未改) |
| 3 | 采候选 | Tillicum 另开 1×H200(默认) |
| 4 | 采样 | **同 Verified100 eval**:temp 1.0 / top_p 0.95 / max_tokens 81920 / enable_thinking + preserve_thinking;其余取 checkpoint generation_config(eval server 同法) |
| 5–8 | 逻辑 | **用户令"不改上游逻辑、能复用就复用、最小改动"**:多数票按 action_str 完全相等(不分桶);不排除末步;候选 thought 不截断;0.7 门槛与平局规则照上游 |
| 6 | Qwen-CUA 思考 | **开** |
| 9 | 训练 | 待定(照仓库 = actor 上 LoRA 续训) |
| — | 流程 | **每段代码改动先给用户看 diff 审查,审过再提交/运行** |

## 8 执行记录

**2026-09-30 21:38 起(Tillicum,经 Mac `tillicum2` ControlMaster,用户过 Duo)**

- **存储**:scrubbed 用户配额 98.2T/100T,只剩 ~1.8T;krishna/video projects 均 >90%。
- **登录节点限额**:每用户 cgroup 内存 3.2 GiB、CPU 0.8 核。首次下载(hf_xet、8 并发)
  在 9.7 GB 处被 OOM 杀(`memory.events` oom_kill),日志无报错。改 `HF_HUB_DISABLE_XET=1`、
  4 并发重启:RSS ~240 MB,~200 MB/s,21:47 起,预计 ~22:55 完成。脚本/日志:
  `/gpfs/scrubbed/jy050706/models/qwencua-download.{py,log}`,目标 `models/Qwen-CUA-bf16/`。
- **FP8 实现改为在线量化,不写转换器**:Tillicum 现用 vLLM 0.25.1(`qwen-serve/.venv`)已注册
  `Qwen3_5MoeForConditionalGeneration`,且支持 `--quantization fp8_per_block`(加载时逐层量化为
  128×128 分块 FP8,权重先放 meta 设备,不会先按 BF16 占满显存 —— §2 里"在线量化会 OOM"的
  说法对这版不成立,已更正)。BF16 保留的模块用 `--quantization-config '{"ignore": [...]}'`
  以 `re:` 正则按 vLLM 内部模块名给出(vLLM 把 in_proj_a/b 合并成 in_proj_ba):router gate、
  shared_expert_gate、linear_attn.conv1d、in_proj_(a|b|ba)、visual.*、lm_head。
  `cua/check_quant.py` 加载后逐层列出量化方法,与官方清单不符即失败退出。磁盘上只存 BF16 807 GB。
- **H200 空闲**(21:4x):g021 空 8、g022 空 6、g008 空 5、g010 空 4;名下无作业。
- **代码仓库**:Mac `/Users/knight/uw/computeragent/cua-arm`(本地 git,不推远端)。
  提交 `aa828b4` = 上游 `piotr-teterwak/action-reward-models@4d6dfff` 原样拷贝;CUA 适配全在 `cua/`。
  复用上游:`selection_prompt.build_catts_vision_prompt_v2` + `scalar_server._split_user/_to_prm_format`
  (PRM prompt,同 `build_reward_data.py` 的构造法)、`onpolicy_precheck.py`、
  `build_distill_selections.py`、`build_onpolicy_sft.py` 原样调用。
  自写(上游没有对应或协议不同):`states.py`(swift 行→状态)、`sample_candidates.py`(上游采样器走
  SGLang `/generate`、top_p 写死 0.9,与 eval 协议不符)、`score_candidates.py`(调用上游 prompt 函数 +
  4 处文字替换)、`to_swift.py`、`random_selections.py`(distill_rand 对照)、`check_quant.py`、
  两个 sbatch(`srv-h4` 4×H200 24h 端口 8030;`gen-h1` 1×H200)。
- **干跑**(只渲染不调模型):r5 第 5 行状态 + 教师动作作候选,上游函数生成的 PRM prompt
  结构正确,4 处替换各命中 1 次。
- **用户审 diff 批准四段**(22:0x 前):cua-arm 提交 `20f78a4` 状态 / `5063a47` 阶段 A /
  `ec44e2e` 阶段 B / `823c0e4` 阶段 C;用户令"不改上游逻辑"后撤回三处自加改动(点击分桶、
  排末步、think 截断),serve 上下文改 262144。
- **逻辑自测** `cua/selftest.py`(`db5acf8`,修 workdir `192d0e2`),Tillicum 登录节点真语料:
  ① 6,474 个教师目标全部可解析、题面与图片占位一致;② 20 个 prompt 构造成功、4 处替换命中;
  ③ 阶段 C 全链(上游 build_distill_selections → onpolicy_precheck → build_onpolicy_sft → to_swift
  + random_selections)用已知答案的合成分数:20 状态留 10(门槛以下与 -1 分各 5 个被丢)、
  5 个偏离多数票,输出行除目标外与语料逐字节一致。产物 `arm/runs/selftest-20260930-2159/`。
- **部署**:Tillicum `/gpfs/scrubbed/jy050706/arm/cua-arm`(git clone 自 bundle,md5 两端一致)。
  heredoc 内第二个 ssh 漏 `-n` 吃掉后续命令一次(CLAUDE.md 已记的坑),已逐步补做。
- **试点状态**:`arm/runs/pilot200-20260930/states.jsonl`,n=200 seed 0;语料 sha256 `6c8b38e6…`
  与 CHECKPOINTS 登记一致;分布 vs_code 51 / os 35 / calc 33 / chrome 25 / writer 19 / impress 14 /
  vlc 8 / thunderbird 8 / gimp 7。
- **阶段 A 试点**:Slurm **338834** `gen-h1`,g008,1×H200,8h 上限(估 $7.20),21:5x 起。
  **启动日志暴露 top_k=0 → 已 scancel(运行 2:42,未写出任何候选)**。原因:采样器只取
  checkpoint 的 generation_config(img10-9b 的只有 eos,无 top_k),而 eval 服务由
  `prepare_model.py` 传 `--override-generation-config`
  `{temperature 1.0, top_p 0.95, top_k 20, min_p 0, presence_penalty 0, repetition_penalty 1.0,
  max_new_tokens 81920}`(cua-eval 三份部署记录一致)。用户批准修复 → cua-arm `ecc0d6f`,
  重投 **338835** `gen-h1`(g008)。
  教训:"同 eval"要对 eval 服务的实际启动参数核,不能只对 registry 的 protocol 字段。
- **下载**:22:00 时 145 GB,~135 MB/s,预计 ~23:20 完成;完成后提交 `srv-h4`。

<!-- REPO NAV -->
[Repository map](../../README.md)
<!-- /REPO NAV -->
