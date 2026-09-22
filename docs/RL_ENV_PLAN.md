# CUA RL 环境：源码副本、缺失项与进度

更新：2026-09-22，America/Los_Angeles。

## 2026-09-22：第二轮(iter2)准备完成，远端执行等待用户批准

本节只记录准备与核查；**π1 未发布、未采样、未训练**。远端写操作(Klone 共享盘写入、起服务、VM 采样)被 Claude Code 权限分类器按"修改共享资源"拦下，按规矩停下等用户批准，没有绕过。

**现场核查(15:20–15:45 PT)**：9/18 15:42 之后 workstation、Klone、Mac 均无新 RL 产物。allocation 40253896(g3108，8×L40S)有效期 2026-09-18 06:02 → **2026-09-25 06:02 PT**；node-local 的 step1 DeepSpeed checkpoint(119G，含 optimizer 状态)随之消失，g3108 `/tmp` 仍有 2.7T 空闲。π0 服务(step .6，GPU6，端口 8082)仍在，4 天无请求。g3108 各卡：0/1/2/4 为用户的 molmospaces 数据生成(step .47，overlap 持有全部 8 卡与 16 CPU)，5 状态异常(nvidia-smi 显示 [N/A])，6 为 π0，**3 与 7 空闲**。本作业内存上限 512GiB、当前 29.6GiB；节点 `free` 显示的 374G 已用主要属于他人作业 40434900(660G)，不占本作业额度。workstation 空闲(无 VM、无评测进程)，到 Klone 的 SSH master 在线。

**主 benchmark**：用户 09-22 确认 **OSWorld-Verified**(官方 361 题)；设计文档已同步。

**版本管理(09-22 起)**：
- `cua-rl-local/` 建为本地 git 仓库(无远端)。基线 `bb11eca` = 09-18 探针代码与证据；probe.py/verify.py/run.sh 与 Klone 实际运行副本 SHA256 一致(probe `16df8722…`)。上游 checkout 的 commit 与所用损失函数文件(OpenWebRL `9da6dc1` `slime/utils/ppo_utils.py`，`42a60d08…`)记在 `SOURCES.json`。凭据、虚拟环境、wheel、上游源码、下载数据不入库。
- 今天的代码在 `iter2` 分支：`eedb206` 发布与服务包装 → `6483aff` 原样复制 09-18 脚本 → `547c09b` 改动提案(**未运行**)。验证通过再合回 main。
- CUA 仓库此前自 09-14 目录整理起累积 500+ 文件未提交，已作快照提交 `04ea21395f`(分支 `reorg-20260909`，未推送)。

**π1 发布方案(脚本已写好，未执行)**：模型 ID `9b-full-r5-grpoprobe--train20260918--s1`，arm `9b-full-r5-grpoprobe`(临时登记见 `CUA/docs/NAMING.md`)。逐文件比对 update1/model 与 π0 服务目录：
- 权重索引、tokenizer.json、chat_template.jinja、generation_config 逐字节一致；
- config.json 只差 π0 多一行 `use_cache:false`；tokenizer_config 只差加载开关 `local_files_only`；
- processor_config 的图像尺寸上下限被 probe 在保存前改写(推理时由 `--mm-processor-kwargs` 覆盖)；
- update1 缺 preprocessor_config、video_preprocessor_config、vocab、merges 四个文件。

因此 **π1 只换权重**：4 个分片与索引硬链接自 update1(共享盘 /mmfs1 已用 99%、余 260G，硬链接不占新空间)，其余 12 个推理文件逐字节复制自 π0 服务目录，用现有 `prepare_model.checkpoint_files()` 校验。采集代码三文件 SHA 与 π0 部署时一致。registry：`cua-eval/registry.cuagym-p2-grpoprobe-s1.json`，与 09-18 P2 版本只差模型条目和端口(8183→g3108:8083)。

**Slurm GPU 分配(实测，debug)**：在 40253896 中申请 1 卡的 overlap step，两次测试都被分到正在服务的 GPU6，现成的 `prepare_model serve-held` 会因"GPU 忙"断言拒绝启动(安全失败，但起不来)。办法沿用 09-18 训练：step 申请 8 卡可见，由 `serve_on_gpu.sh` 显式绑定已验证空闲的 UUID；vLLM 命令仍由 `prepare_model.serving_script()` 生成，参数与 π0 完全一致。同时发现 09-18 `run.sh` 的空闲闸门(<1024MiB)会放行 molmospaces 占 719MiB 的 GPU0，新版收紧为 <512MiB 且无计算进程。

**恢复训练的内存核算**：update1 是从零建 optimizer；resume 时 `torch.load` 约 107GB optimizer 状态，叠加已分配的 CPU Adam 状态(约 143GB)，峰值估计约 250GB，故训练 step 申请 `--mem=320G`(update1 为 192G)。超限只会杀掉训练 step 本身。

**待批准的远端操作(按顺序)**，均使用已持有的 allocation 和 workstation，不申请新 GPU：
1. R1 在 Klone 发布 π1(`iter2-20260922/publish_pi1.py`)。
2. R2 在 g3108 GPU3 启动 π1 服务(8083；workstation 本地 8183)。
3. R3 四轮采样(`run_rounds.sh`；与 09-18 P2 同协议：同 4 题、30 步、T0.8、单 VM 串行、collection=test、原始记录保留；约 70 分钟)。
4. R4 汇总并导出有差异的组，传到 Klone。
5. R5 在 GPU7 上从 step1 恢复并更新一步(global_step 1→2)。
6. R6 校验(权重变化、视觉冻结、重新加载 forward)。

训练参数表与代码 diff 见 `cua-rl-local` 的 `547c09b`。

## 2026-09-18：GRPO单步更新、落盘及独立重载已验证

本次完成的是**一次真实optimizer update的资格测试**，不是持续online RL或效果实验。使用原普通r5-9B SFT初始化，独立HF/DeepSpeed后端，复用未修改的OpenWebRL clipped policy loss；未声称跑通原生OpenWebRL/Megatron整套调度。

| 检查 | 最终结果 |
|---|---|
| 导出并核对输入 | 3个完整group、12条轨迹、127次决策；全部prompt token及图像网格匹配 |
| 实际训练batch | Writer一个完整group，reward为0/1/1/1，4条轨迹、33次决策，每轨迹等权 |
| 更新设置 | 语言全参、视觉冻结；lr5e-7，clip0.2，temperature0.8，ZeRO2 CPU optimizer offload，单L40S |
| old-policy路径 | 训练侧重算，上游use_rollout_logprobs=False语义；33次更新前old/new logprob最大差0 |
| backward / update | 33/33通过；global_step=1，梯度范数4.551735，进程exit0 |
| 训练部分耗时 / 显存 | 595.1秒，不含初始化与保存；peak reserved42.789GiB |
| 落盘模型 | 4个safetensors分片，760个tensor，18,839,793,446 bytes含配置/验证元数据 |
| 独立语言权重核对 | 抽查36,864值，593值改变；最大差9.536743e-7 |
| 冻结视觉核对 | 333个visual tensor全部与原SFT逐元素完全相同 |
| 独立重新加载 | 新进程加载新checkpoint，真实截图forward通过，382个输出token logprob全部有限；exit0 |

- 推理权重：Klone `/gscratch/cse/jy050706/sft/experiments/cua-rl-probe-20260918/update1/model`。原始SFT权重及其GPU6服务保留。
- 完整DeepSpeed checkpoint：g3108 `/tmp/jy050706-cua-rl-probe-20260918/update1-resume/step1`。这是节点临时盘；只验证了文件和optimizer分片存在，**尚未执行resume，也未持久化到长期存储**。
- 同一份采样记录可供资格测试，但跨vLLM/HF数值差异和sampling/importance-weight口径仍未完全验收。训练侧重算使本次update的分母自洽，不代表它消除了跨后端误差。不能据单步结果宣称RL效果提升。
- 本轮没有运行新权重的VM rollout、自动权重同步或第二轮更新。下一步先把独立新checkpoint接入已有serving/eval入口并跑小组VM验证，再测试checkpoint恢复与第二轮采样/更新；正式任务池、holdout及长期存储仍待落实。

证据：[单步训练报告](../../cua-rl-local/train-probe-20260918/results/update1-report.json)、[独立权重与重载验证](../../cua-rl-local/train-probe-20260918/results/update1-verification.json)、[概率口径核对](../../cua-rl-local/train-probe-20260918/probability-contract.json)、[最终资源状态](../../cua-rl-local/train-probe-20260918/results/final-resources.json)。

### 本轮接入与排错记录

- 用户授权继续最小训练闭环。原OpenWebRL Qwen3.5 bridge及其链接launcher存在语言模型路径，不能未经验证直接当作截图多模态训练。先复用已有 `sft-train.sif` 的HF Qwen3.5完整多模态实现和DeepSpeed，以未改的OpenWebRL clipped policy loss做隔离资格检查；不是宣称OpenWebRL在线训练已集成。
- 已实时确认A100四卡正在其他训练，不使用；L40S占位40253896有空闲卡，原SFT服务step6保留。容器版本实查：torch2.13.0+cu130、transformers5.15.0、deepspeed0.19.5、trl0.29.1，sglang未安装。
- 已导出3个有奖励方差的完整group：12条轨迹、127次决策、125张唯一图片，最大总长度27,609。使用精确capture请求、图像SHA、输入输出token IDs、rollout logprob、loss mask、trajectory turn count和原奖励。没有把缺失记录补成0或丢弃同组失败轨迹。
- 本地独立脚本：`cua-rl-local/train-probe-20260918/`。远端独立目录：`/gscratch/cse/jy050706/sft/experiments/cua-rl-probe-20260918/`。先运行preflight1：全部输入重建匹配，再做同checkpoint logprob检查；不满足门槛则不允许optimizer step。该阶段后来通过训练侧old-policy重算完成一次更新，最终结果见本节顶部。
- preflight实际结果：127次prompt token与图像网格全部匹配；修复了本地拼接response后mm_token_type_ids未补齐的错误。原始vLLM与HF整段forward的两条logprob检查平均绝对差0.02709/0.01159、最大0.81962/0.22776；原始rollout-logprob直接使用路径未通过预设门槛，未放宽阈值。
- 全部183次决策、39,083个API logprob与采集器的temperature前raw logprob逐项相同（最大差0）；采样temperature0.8、top_p0.95。上游 `slime/backends/megatron_utils/loss.py` 的get_responses会除temperature，因此不能将这些raw值直接作为该路径的old logprob。
- 最小替代路径采用上游已支持的 `use_rollout_logprobs=False` 语义：在同一训练后端、同一temperature0.8下重算old policy，并在每次backward前验证未更新策略的比值约为1。保留原rollout logprob用于差异诊断，不宣称已经解决跨后端或采样分布差异。独立update1只使用Writer的完整四轨迹group、33次决策；语言全参、视觉冻结、lr5e-7、clip0.2、每轨迹等权，一次optimizer step。
- GPU使用：Slurm单卡overlap首次选中了正在serve的GPU6，被内存门槛拒绝；后续在同一个已有八卡allocation内显式只绑定空闲GPU0 UUID `GPU-4a7aa295-575f-7902-743b-1d6d2db6b8c1`，未停原GPU6服务。共享盘实查仅余约183GiB，完整optimizer checkpoint写入节点本地 `/tmp/jy050706-cua-rl-probe-20260918/`（非长期持久存储）；独立HF权重才写共享盘。训练入口限制40分钟。


## 2026-09-18：四任务 × 四轮真实采样已完成（未做训练）

最终完成 **16/16条有效模型轨迹**，冻结普通r5-9B checkpoint-306。完整成功8条、部分完成2条、0分6条；这是四个工程测试任务的重复采样，不是OSWorld benchmark成绩。

| 应用 | 第1轮 | 第2轮 | 第3轮 | 第4轮 | 组内奖励差异 |
|---|---:|---:|---:|---:|---|
| Calc | 0 | 0 | 0 | 0 | 无，advantage全0 |
| Writer | 0 | 1 | 1 | 1 | 有 |
| Impress | 1 | 1 | 1 | 0 | 有 |
| VS Code | 1 | 0.4 | 1 | 0.4 | 有 |

- 3/4组、12条轨迹具有非零组内奖励方差，可用于训练链路验收。Binary与Partial都只有这三组有效：Writer/Impress的advantage完全相同；VS Code两档分数经标准化后最大差约1e-6，仅来自epsilon。这批数据不能检验部分分是否优于二值奖励。
- 16次初始评分均为0；16次原grader均正常退出，未把初始化/服务异常算成模型0分。VS Code两条0.4均为删除了第14行的内容、保留空行，文件仍20行；未完整删除该行。Calc四条的磁盘文件缩放仍100/100；Impress最后一条磁盘顺序仍为初始顺序，未事后补操作或修分。
- 共183次模型决策、202条动作记录（一次回复可以包含多个动作）、39,083个输出token，其中24,243个reasoning token。每次token IDs与logprob数量一致，capture_errors为空；16页全部验证passed，183次信号决策已验证，388张图像解码通过。这不等于训练prompt/mask已经验收。
- 第四轮中本地轮询出现一次STATUS_FAILED并退出；重新查询确认远端controller独立完成该轮，未重复启动或重跑。最终全部controller结束、运行Docker容器数0。释放可回收文件缓存后WSL available为54,606 MiB；未重启WSL或停止其他服务。 随后Windows vmmemWSL working set为4,193,746,944 bytes（约3.91 GiB）；原单L40S模型服务8182健康检查HTTP200，保留供下一步使用，未做新GPU申请。
- 五个原始源码checkout、workstation共享harness及本轮独立worktree均git status clean。私有任务适配文件被harness任务数据规则忽略；未修改原task/setup/grader、共享VM镜像或模型权重。
- **下一步只验收一次GRPO更新**：从这三组构造逐决策训练样本，核对原prompt/image/token映射、生成token的loss mask与old logprob；接入现有训练后端，先做forward/loss/gradient检查，再做一次optimizer step并保存独立checkpoint，验证权重同步后用同协议小规模回测。当前未构建训练batch、未backward、未更新权重，SFT基线保留。Binary/Partial比较需另收更多reward档位或binary全失败但partial有差异的组。

证据：[奖励与优势](../../cua-rl-local/artifacts/p2-grouped-20260918/summary.json)、[原始评分与采集验收](../../cua-rl-local/artifacts/p2-grouped-20260918/final-audit.json)、[运行状态](../../cua-rl-local/artifacts/p2-grouped-20260918/final-statuses.json)、[16页索引](../../cua-rl-local/artifacts/p2-grouped-20260918/viewer-entries.json)、[内存清理](../../cua-rl-local/artifacts/p2-grouped-20260918/memory-cleanup.json)。页面已进入[统一查看器test集合](http://127.0.0.1:8793/index.html?collection=test)。

### 本次执行与依赖修复记录

用户再次要求推进下一步，现已执行，不只停留在计划。对公开数据做只读 grader 初筛，排除发现的自动保存副作用，再选出以下四题；保留原始 instruction/setup/reward，不改分、不自动补保存。

| 应用 / task id | 任务 | 有限 fixture 检查：初始 / 错误 / 部分 / 完成 |
|---|---|---|
| Calc `693b3046…` | Sheet1缩放85%、Sheet2缩放110% | 0 / 0 / 0.5 / 1 |
| Writer `f02c7f7f…` | 只将第二段设为双倍行距 | 0 / 0 / 0.6 / 1 |
| Impress `2ecc76ab…` | 将第5张幻灯片移到第2位 | 0 / 0 / 0.4 / 1 |
| VS Code `d46f3728…` | 删除 script.sh 的第14行 | 0 / 0.4 / 0.4 / 1 |

这是有限的典型正负例验收，不保证对所有投机解免疫。VS Code 的错误删除可能获得部分分，不能把非零分数当完整成功。每条真实 rollout 初始化时仍检查原 grader 的分数必须为0。

- 当前模型仍为同一普通 r5-9B checkpoint-306，固定BF16服务；未更新模型权重、未增加GPU实例，workstation单VM串行采样。
- 四轮各包含这四题，共16条；使用统一 `run_eval.py plan/doctor/run/status`，collection=test、原始记录保留。自动顺序推进已冻结的四份plan，出现环境/服务错误则停止后续轮次；正常0分不会触发补救重跑。
- 每条最多30步，temperature0.8、top_p0.95、输出4096、context65536、10图/fold1，与上一轮一致。没有显式API seed，不称作四个预先指定随机种子的复现实验。
- 独立 worktree/bundles：`/home/yanji/research/cua-rl-local/p2-grouped-20260918/`；原始脚本哈希及上传一致性已记录。
- VM guest Python3.10缺 openpyxl/docx/pptx，通过任务进程专用的纯Python wheels路径补齐（另含et_xmlfile、typing_extensions、xlsxwriter）；复用guest已有lxml/Pillow。共享VM镜像、上游harness和主机Python环境未改。
- 首次执行：Calc第一条完成、score=0；Writer在模型调用前因python-docx默认模板不能从wheel zip路径打开而初始化失败；已停止该次controller及其拥有的进程/VM，保留失败证据，不计为模型0分。Impress未形成有效模型样本。
- 修复只涉及私有依赖目录：在一次性VM中解压同样的六个wheel，再通过进程级PYTHONPATH加载。原任务、grader、模型和共享镜像未改。Writer/Impress均已在真实VM上重新验证setup成功、初始reward=0；初始桌面渲染需要短暂等待，5秒后截图正常，沿用native runner现有的就绪等待。
- 修复后的独立worktree为 `p2-grouped-fixeddeps-20260918`。第一轮只补Writer/Impress/VSCode三题，保留已完成的Calc0分；其余三轮仍各四题，共计划16条有效模型轨迹。新的冻结plan及原失败plan都保留；未启动的旧plan不再使用。
- 修复后16条有效采样已全部完成，原失败记录保留。
- 按原始task id跨轮分组，未将不同题混作一个GRPO组，最终结果见本节顶部。

证据：[冻结plan及重复轮次映射](../../cua-rl-local/artifacts/p2-grouped-20260918/plans.json)、[reward检查](../../cua-rl-local/artifacts/p2-grouped-20260918/reward-checks.json)、[原部署哈希](../../cua-rl-local/artifacts/p2-grouped-20260918/deployment.json)、[依赖修复后的哈希](../../cua-rl-local/artifacts/p2-grouped-20260918/fixed-deployment.json)、[VM初始化复核](../../cua-rl-local/artifacts/p2-grouped-20260918/fixed-dependency-qualification.txt)。

## 下一阶段前的 reward 审查：发现一个已复现的假阳性

对已准备的四个任务只做源码审查和本地负例测试，没有启动新 VM、模型采样或训练，也没有修改原 evaluator。

| 任务 | 本次发现 | 证据等级 / 处理 |
|---|---|---|
| Calc / E2 自定义验证 | evaluator 用 `'E2' in sqref_str`；只给 E20 添加验证、E2 无任何验证，也会返回 1.0。另有未明确写入 instruction 的错误提示文字要求 | **负例已复现**，先隔离出首轮训练候选；原 rollout 的0分保持不变 |
| Writer / 四边页边框 | 只检查 `doc.sections[0]`；距离检查只看 `space`，未检查相对页面/正文的 `offsetFrom` | 静态风险，需多 section / 不同偏移基准的负例测试，暂不判验收通过 |
| Impress / 矩形 callout | 原 reward 执行入口会自行 `Ctrl+S`；形状检查仅要求 `AUTO_SHAPE`，没有核实矩形具体类型 | 已确认评分有保存副作用，形状边界为静态风险；不与无自动保存的任务混成同一个未说明的协议 |
| VS Code / Python 项目设置 | 解释器只接受 `${workspaceFolder}/.venv/bin/python` 字面值，另强制 unittest=false；JSONC 正则剥注释可能误处理字符串里的 `//` | 静态风险，先检查有效等价配置与初始化提供的信息，不当作已完全合格 |

Calc 负例证据：[calc-negative-control.json](../../cua-rl-local/artifacts/reward-audit-20260918/calc-negative-control.json)。正确 E2 和错误 E20 两个 fixture 都被原函数打成1.0；使用 openpyxl 的真实区域包含判断确认 E20 不覆盖 E2。

此前 P0 的 0/0.7/1 验证证明了评分链路能运作，**没有证明 reward 对错误解不会给高分**。这个新发现使 Calc 暂不具备训练准入资格，但不否定已完成的真实模型/VM接口验收。

下一步保持小预算：先换筛并验收4个评分边界明确的任务，每个4条独立 rollout，共16条；只有采样组有有效奖励差异，才进行一次 GRPO update。每条从干净状态开始，固定同一9B checkpoint；不人工补操作、不事后修分。候选任务应通过初始态、正确态、典型错误态三类检查，且明确 grader 是否会自动保存/修改状态。此处是下一步计划，尚未启动16条采样。

## 2026-09-18：普通 r5-9B 的真实 Calc rollout 已完成，原始得分 0

- 用户要求“下一步”。已通过现有 `tillicum2` SSH master 找到原始普通 r5 checkpoint：`/gpfs/scrubbed/jy050706/sft/out/img10-9b/v0-20260822-024940/checkpoint-306`，`global_step=306`、epoch=3、full SFT，源模型 Qwen3.5-9B，数据为两份 r5nocapimg10 语料，视觉塔/aligner 冻结。不是 histcomp、TMAX 或其他 mixB 版本。
- 使用现有 `prepare_model.py plan` 验证分片/index/完整视觉权重，传输并逐文件校验 17 个推理文件，共 18,849,985,312 bytes；不传 optimizer/RNG。发布到 Klone `/gscratch/cse/jy050706/sft/serving/9b-full-r5--train20260822--s306/model`。
- 用原有 `prepare_model.py serve-held` 在已拥有且空闲的 `40253896` allocation 中启动 **1 张 L40S**，节点 g3108、step `40253896.6`、GPU `GPU-f0492b40-1501-0682-cb93-02957e80e98f`、端口8082；没有新建长期 GPU allocation，也没有停止其他服务。workstation 本地新转发8182。
- 服务 BF16、context65,536、单并发、image limit10；按已有采集工具保存输出与视觉信号。SFT 工具名 `computer_use` 和相对坐标约定已核对。
- 独立 worktree：`/home/yanji/research/cua-rl-local/p1-calc-20260918/harness`，commit d552441。新增一个被任务数据规则忽略的 BaseTask adapter；原始任务、setup、reward 与共享 harness 均未修改。task adapter 仅初始化和评分，无脚本解法。
- 统一入口已执行 `run_eval.py plan → doctor → run`，collection=`test`、raw_retention=`keep`，workstation1 slot；doctor 全部通过，包括精确 checkpoint/model ID 与大响应连接检查。
- Run：`9b-full-r5--train20260822--s306--cuagym-p1--cuagym-calc-p1-n1--20260918T194352Z-97a467585548`。最多30步，temperature0.8/top_p0.95，max output4096，image10/fold1，thinking/preserve_thinking 开启。
- **最终结果：1/1 任务完成，native exit=0，原始 reward=0.0；模型9次决策（8次GUI操作＋DONE），没有超时或执行异常。controller 已完成、该任务VM已清理，未做 RL 参数更新。**
- 截图确认第7步在 E2 的 Custom 验证框输入 `=E2>D2`，第8步点 OK，第9步模型宣称成功并 terminate。轨迹没有保存动作；原 evaluator 读取磁盘文件后，三个组件均报告未发现验证规则。证据最支持漏保存，但没有事后补保存来重打分，不能把这一推断写成已做反事实验证。
- 采集9/9决策，输出 token IDs/logprob 共1,059项、每轮数量相等，其中 reasoning342 tokens；capture_errors 为空。页面验证 passed：9 decisions、9 actions、18 decoded images、9 verified signal decisions，无 errors/warnings。
- 页面已进入现有统一 viewer 的 **test** 集合：[真实轨迹](http://127.0.0.1:8793/sources/workstation-eval/task-fb53c63253de4eac9c958a95688ed944.html#episode=0)。
- **reward 数据审计待办**：原评分第三项额外检查非空错误提示文字，而 instruction 未明确要求该文字；先作为一致性疑点，不改本轮原始成绩、不直接把该任务标为训练资格全部通过。
- 已验证的是固定9B SFT的真实 rollout与记录链路。仍缺一组同任务多轨迹的奖励差异、OpenWebRL训练样本/mask构建、backward与权重同步；不是GRPO训练已跑通。
- 收尾：workstation 已无运行 Docker VM；清理本次文件缓存后 WSL 可用约53.2 GiB。只保留 `40253896.6` 的1张L40S独立模型服务供后续继续，其他服务和allocation未改。

本地证据：[最终报告](../../cua-rl-local/artifacts/p1-calc-20260918/rollout-report.json)、[第7步公式截图](../../cua-rl-local/artifacts/p1-calc-20260918/step07-formula.png)、[冻结 plan](../../cua-eval/runs/9b-full-r5--train20260822--s306--cuagym-p1--cuagym-calc-p1-n1--20260918T194352Z-97a467585548/plan.json)、[模型发布清单](../../cua-rl-local/artifacts/p1-calc-20260918/model-publication-plan.json)、[任务部署哈希](../../cua-rl-local/artifacts/p1-calc-20260918/task-deployment.txt)。

**实验设计入口**：[RL_EXPERIMENT_DESIGN.md](RL_EXPERIMENT_DESIGN.md)。用户已确认初始模型为现有 Qwen3.5-9B CUA SFT；设计包含冻结 SFT、Binary-GRPO、Partial-GRPO 三个对照。主 benchmark 仍待选择，默认提案为 Verified 361(09-22 更正：用户已确认 OSWorld-Verified)。这里只记录环境事实和准备历史，实验参数与预算以设计文件为准。正式 RL 实验未启动，上游代码未修改；最新 P0 执行结果见下方。

## 2026-09-18：workstation 上的 Calc P0 环境测试已通过

用户授权“试一试”，随后明确使用 workstation，并要求顺便清理其运存。Windows 的既有评测未改动。

- 实际运行主机：workstation / `jyworkstation`，SSH 路由复用现有 registry；启动前 0 个 Docker VM、约 54 GiB 可用内存。仅使用一个并发 VM；重置前后顺序创建两个实例。
- 复用 `/home/yanji/research/OSWorld-V2-shared`，commit `d552441917f302fab410a1991cc705d7bf585d14`、原 `.venv` Python 3.12.3；上游 checkout 前后保持 clean。
- VM 文件使用现有 `.env` 指定的 `.../releases/v2026.06.24/osworld-v2-ubuntu-x86-v2026.06.24-official-fonts.qcow2`。本次未重算整盘哈希，不据文件名推断完整 benchmark release 匹配；这是 CUA-Gym 环境资格测试，不是正式 OSWorld benchmark 成绩。
- 任务：Calc `0029e9c3-6038-55fd-aee3-9eb4186d4d63`，E2 自定义验证 `=E2>D2`。
- 首次尝试 `p0-calc-20260918T090555Z` 暴露 **guest `python3` 缺 openpyxl**。这与 WSL 客户端已安装 openpyxl 是两回事；该实例失败后已停止，失败报告保留。
- 第二次 `p0-calc-20260918T090935Z` 携带固定 `openpyxl 3.1.5` / `et_xmlfile 2.0.0` 纯 Python wheels，通过仅测试命令的 `PYTHONPATH` 使用；没有改 VM 基础镜像、共享 Python 环境或原始任务代码。
- 新增代码仅为独立 `cua-rl-local/p0_calc_vm.py` 和 `p0_calc_guest.py`，远端部署在独立 run 目录；全部上传文件 SHA256 已对照一致。

| 实际检查 | 结果 |
|---|---:|
| 原始 initial_setup 在真实 VM 执行 | 成功 |
| 初始 reward | 0.0 |
| 经 OSWorld 执行真实 GUI 键盘动作 | 成功，截图确认选中 E2 |
| 脚本构造部分完成状态，运行原 reward.py | 0.7 |
| 脚本构造完整完成状态，运行原 reward.py | 1.0 |
| 环境重置、重新运行原 setup 后评分 | 0.0 |
| 本轮两个 VM 实例清理 | 全部停止，最终运行容器数 0 |
| 总运行时间 | 约 67.3 秒，含两次 VM 启动/初始化与清理 |

**范围：P0 的环境/评分/重置部分通过，1/4 个已准备应用完成实机检查。未调用 9B 模型，未进行 agent 自主解题，也未做 backward、权重同步或 GRPO 更新。** 满分来自明确标记的 scripted fixture，不是模型成功率；这次 67 秒也不能用来估计真实长轨迹的训练吞吐。

证据：[完整报告](../../cua-rl-local/artifacts/p0-calc-20260918T090935Z/report.json)、[GUI 动作后截图](../../cua-rl-local/artifacts/p0-calc-20260918T090935Z/02-after-gui-action.png)、[运行日志](../../cua-rl-local/artifacts/p0-calc-20260918T090935Z/run.log)、[首次缺包失败](../../cua-rl-local/artifacts/p0-calc-20260918T090555Z/report.json)。

### 同次 workstation 运存清理

初始 Windows `vmmemWSL` working set 为 44,274,368,512 bytes（约 41.23 GiB）。WSL 内约 39.4 GiB 是文件缓存，进程/内核实际使用约 1.9 GiB。经用户授权执行 `sync` 后释放可回收缓存，没有重启 WSL、没有杀服务或改内存上限；首次核对 Windows working set 降至约 2.73 GiB。P0 结束后再次释放测试产生的缓存，最终数值记录于[清理回执](../../cua-rl-local/artifacts/workstation-memory-cleanup-20260918.json)。Windows working set 的回落可能滞后于 WSL free-memory 统计。

下一步是冻结普通 Qwen3.5-9B CUA SFT 的精确 checkpoint，并接一条真实模型 rollout。目前 registry 中的 9B 服务是 histcomp / TMAX 版本，本轮未默默替换初始化模型。

## 最新纠正：复用现有 Windows / WSL OSWorld，适配 RL rollout

### 数据规模核对（2026-09-18）

本地 `datasets/tasks.parquet` 共 10,910 行、10,910 个唯一 task id，与当前 Hugging Face dataset card 的公开规模一致。按原始 platform 标签：desktop 8,029；web 1,075；cross_app 430；缺失标签 1,376。缺失标签的任务不擅自归入 desktop 或 cross_app。

明确标为 desktop 的分布：Calc 2,576、Writer 2,093、Impress 1,402、VS Code 1,178、PDF 679、VLC 71、GIMP 30。前四类合计 7,249。公开表的 327 个原始 `app_type` 值包含跨应用组合、泛化标签和命名变体，不能称作 327 个独立软件。

项目官网描述整体覆盖 110 environments（16 desktop + 94 web）和约 3.2 万任务，与本地公开任务表的统计口径不同。当前训练准备按已下载文件计数，不按整体宣传规模假定数据已齐。

算法关系：CUA-Gym 提供 task/setup/reward；Arijit 使用 verl/GiGPO；OpenWebRL 使用 slime 的训练/rollout 栈。桌面 RL 的共同闭环是相同 task 初始状态下采样多条轨迹 → 原 evaluator 给分 → 计算相对优势 → 用模型输出 token 的 logprob 和 mask 反向传播 → 同步新 policy 权重。GiGPO 另用 anchor observation 组织步骤级比较；这不意味着数据集提供逐步正确动作。

**Zixian fork 的进一步核对**：远端 HEAD 与本地 `9da6dc1` 一致。主 4B 脚本是 GRPO，默认从 OpenWebRL-4B-SFT 开始，读 2,102 个 WebGym prompts，每 task 5 条 rollout，按 turn 拆训练样本；终局 judge 分数传播至各 turn，并过滤组内 reward 无差异的组。实际 reward 分支为成功 1 / 失败 0 / 特定格式失败 -1，不能按函数旧注释理解成任意 format/judge 加权和。

该 fork 另有 `openwebrl/docs/ARM_SUMMARY.md`，记录 Zixian 的 ARM 候选选择、离线 SFT/DPO、在线 turn-level advantage bonus 实验。在线 ARM 部分在 outcome advantage 上为有有效标签的 turn 加 `0.5 * (selected_executed_action - 0.2)`；与推理时选择最好 action 执行是两种用法。文档报告推理时选择收益最明显，在线 RL 尚未显示可靠增益。本 checkout 只找到这份总结，未找到对应 ARM Python/launcher 实现或它引用的详细结果文件，因此此部分属于作者文档证据，未独立复现实验。桌面适配计划仍先复用 outcome-only GRPO，不自动加入 ARM 研究分支。

来源：[CUA-Gym 项目](https://github.com/xlang-ai/CUA-Gym)、[公开数据说明](https://huggingface.co/datasets/xlangai/CUA-Gym/blob/main/README.md)、本地 parquet 实际计数与两个训练仓库源码。

用户指出已经在 Windows 主机上跑 OSWorld。本次经 SSH **只读实时核对**：

- Windows SSH 别名 `osworld-windows`，WSL 发行版 `Ubuntu-24.04`（另有 docker-desktop）。
- WSL 架构 `x86_64`，存在 `/dev/kvm`。
- `/home/daniel_yan/research/OSWorld-V2-shared` HEAD 为 `d552441917f302fab410a1991cc705d7bf585d14`，Git 状态干净。
- 检查瞬间有 3 个 `happysixd/osworld-docker` 容器运行；这只证明容器存在，不等于某条 rollout 成功或训练已经可用。
- 本地同 commit 的 `OSWorld-V2-personal/local_eval/README.md` 说明该共享环境基于官方 `v2026.08.08`，保留部分 Qwen/VM/runner 适配。未重新校验完整 VM 哈希、全部 gated assets 或模型服务。
- 未启动、停止、重置或修改任何远端容器/实验。另一个 agent 的现有运行不属于本轮 RL worker。

**因此此前“先选一个 VM 主机”对已有项目不准确，应改为：复用既有 Windows/WSL 桌面基础设施，在独立 RL checkout 和结果目录中增加环境服务接口。Mac 上新建的 Python 环境只是准备工具，不替代 WSL 的已验证运行环境。**

刚下载的 `c261cb5` 仅用于对照 Arijit 的代码。后续 RL 环境优先沿用已有 WSL 的 `d552441` / v2026.08.08 基线，不把旧 pin 覆盖到正在运行的共享 checkout。

### 建议适配方案（本轮只设计，未实施）

```text
GPU 训练主机：OpenWebRL / slime + 可训练 policy 的 rollout engine
        │ 截图、动作、任务分数；每组 rollout 固定 policy 权重版本
        ▼
Windows → WSL Ubuntu：独立 OSWorld RL worker / 环境服务
        ▼
既有 Docker/KVM 桌面 VM：reset → screenshot → PyAutoGUI action → evaluate
```

新增的薄层职责：

1. **WSL 环境服务**：封装已有 `DesktopEnv` 的 reset / step / evaluate / close；复用原任务 loader、镜像和环境依赖。为 RL 单独分配 VM、端口、锁和输出目录，不接管正在运行的评测容器。
2. **OpenWebRL rollout adapter**：复用自定义 generate hook；截图进入多模态 prompt，policy 输出转换成既有 PyAutoGUI action，反馈写回下一轮；输出 trainer 所需的 tokens、图像输入、response length、loss mask、rollout logprobs、reward、policy version。
3. **配置**：task pool、endpoint、history / screenshot / coordinate conventions、max steps、同 task 的样本数。原有 browser adapter 和正式 evaluator 不改。

预计最小新增面是独立环境服务、一个 desktop generate/reward 模块和一份配置；先跑 1 个 VM，不先部署另一套 Orchard cluster。

### 任务与 reward

- CUA 是能力/动作范式；OSWorld DesktopEnv 是执行环境；OSWorld benchmark 与 CUA-Gym desktop 是不同任务来源。CUA-Gym desktop 可以在 OSWorld 桌面 VM 中跑，并非 web-only。
- 若目标是提升 OSWorld 泛化，建议用 CUA-Gym desktop / 自有桌面任务训练，OSWorld 留作 held-out 评测。若明确研究 benchmark 内 RL，则单独划分训练和评测任务，不能用训练过的任务声称泛化提升。
- OSWorld 自带 `step()` 在此版本通常返回 `reward=0`；任务得分来自最终 `evaluate()`，不能直接把 step 的占位 0 当训练 reward。
- CUA-Gym tuple 则由原 `reward.py` 返回任务分数；保留 raw score / evaluator error，不直接复用作者 `won >= 0.5` 的成功标签替代官方成功标准。
- 先采用终局 reward；不默认每一步调用可能有 postconfig 或状态修改的 evaluator。
- VM / 网络 / 初始化故障单独标记基础设施错误；不能都混成“任务失败得 0”。

### 从评测走到 RL 的验收顺序

1. 用独立 RL VM 跑一个桌面任务，验证 reset、截图、动作、原 evaluator、清理和重新初始化。
2. 同一 task 从相同初始状态采样 4 条轨迹（起步配置），可用单 VM 串行完成；同组期间不更新 policy，不能让下一条继承前一条的桌面状态。
3. 检查每条轨迹的图像/坐标、实际输入 token、生成 token logprob、mask、终止状态与终局 reward。固定 teacher/API 轨迹不能直接冒充当前 trainable policy 的 on-policy rollout。
4. 接 OpenWebRL 做 1 次小规模参数更新；验证有限 loss/梯度、有效样本数与 rollout engine 同步了新权重，再扩到小任务集。
5. 如果同组 reward 全 0，先排查任务难度、初始化、解析和 evaluator，保证有组内任务奖励差异，再加并发。

Orchard 放在扩容阶段：保持上述环境协议，由 Orchard 管理 worker 生命周期。OSWorld 的完整桌面 VM 还需要考虑 Linux/x86、KVM/device 权限、磁盘/快照与节点资源，不能把已有 browser pod 镜像当成完整桌面 VM。

## 上一轮已完成的本地最小准备（不替代上述 WSL 运行环境）

用户最新要求：只补必要缺项，为 RL 做准备；随后明确自己的重点是 CUA / OSWorld 桌面任务。已停止推进 web mock 路线，本轮只增加独立 Python 环境、OSWorld 固定版本源码、桌面任务资料和外围准备/检查脚本。

五个源码 checkout 的 `git status --short` 均为空；未应用 Arijit 的 OSWorld patch，也没有继续修改 OpenWebRL 或 Orchard。当前没有运行中的本轮 VM / mock / 训练服务。

### 本轮实际补齐

| 项目 | 结果 |
|---|---|
| OSWorld 源码 | `sources/OSWorld-V2/`，固定 `c261cb57a699bd18db128787ca4e71b749141762`，与 Arijit 的 setup pin 一致 |
| Python | 新建 `.venv-osworld/`，Python `3.12.14`，与原先 browser `.venv/` 分离 |
| 必要准备依赖 | numpy、pandas、PyArrow、zstandard、huggingface-hub、requests、websockets、Pillow、PyYAML、openpyxl；完整版本见 `requirements-osworld-prep.lock.txt` |
| 桌面任务 | 从已有 CUA-Gym 下载件提取 Calc / Writer / Impress / VS Code 各一个 smoke 任务，共 12 份原始文件；未执行 Linux setup，未决定正式训练/评测划分 |
| 任务清单 | `datasets/desktop-pilot/tasks.jsonl`、文件 SHA256 和 369 个旧版 OSWorld JSON 示例 inventory；不冒充 OSWorld-Verified 361 |
| 原版导入 | OSWorld `PythonController`、`BaseTask`、Arijit `CuaGymDesktopWorker` 通过；没有创建 DesktopEnv 或连接 VM |
| reward 检查 | 原始 Calc `verify_task` 对合成 fixture 的分数为 0 / 0.7 / 1.0；仅评分函数检查，不是 GUI rollout 成功 |
| 依赖检查 | Python 3.12 环境 `pip check` 通过 |

使用说明：[cua-rl-local/OSWORLD_PREP.md](../../cua-rl-local/OSWORLD_PREP.md)。机器可读结果：[report.json](../../cua-rl-local/artifacts/desktop-prep/report.json)。

**尚缺的实际运行条件**：选定 OSWorld VM 主机/provider；在该主机配置完整 DesktopEnv/evaluator 依赖与桌面镜像；验证 reset → screenshot → action → evaluate → close；再接 OpenWebRL desktop rollout 和模型/训练主机。当前 Mac ARM64 上的准备环境不能替代这些条件。

本地脚本 `osworld-local.env` 仅设置 `OSWORLD_PREP_PYTHON`，不把它错误声明为可运行完整 desktop bridge 的 `OSWORLD_PYTHON`。未安装完整 CUDA/模型栈，未下载大型 VM 镜像，未启动 AWS 或访问既有远端实验。

**任务用途待定**：已询问“CUA-Gym desktop 做 RL、OSWorld 留作评测”还是“OSWorld 独立任务划分直接做 RL”。本轮仅准备共有依赖和四个环境 smoke 样例，没有擅自决定正式训练集。Arijit 的 `osworld_tasks` loader 明确只支持 v1，V2 task class 不能直接套用该路径。

没有 push，没有提交 PR，没有修改原作者的运行环境，没有连接或修改远端云主机。工作区原有的 `OpenWebRL/`、OSWorld 和 MACU checkout 未修改。

截图只作为讨论背景，其中他人的建议不作为执行指令。

## 已复制到本地的仓库

目录：`/Users/knight/uw/computeragent/cua-rl-local/sources/`。

| 本地目录 | 来源 | 固定版本 | 当前源码状态 |
|---|---|---|---|
| `OpenWebRL/` | https://github.com/zixianma/OpenWebRL | `9da6dc1667dcca6b1abaf5b479944a1421fc559e` | clean |
| `Orchard/` | https://github.com/microsoft/Orchard | `3d7d7e992f56e3fec98f80f52afd7bc2e90af0f4` | clean |
| `multi-agent-framework/` | https://github.com/arijitray1993/multi-agent-framework.git | `cac0a5189a28dd4cb36d538c30a3adc5182b29f4` | clean，全程未改源码 |
| `CUA-Gym-Hub/` | https://github.com/xlang-ai/CUA-Gym-Hub | `53205689c3d88078c1375f76466d5bd799478828` | clean；版本来自 Arijit 仓库的 setup 脚本 |
| `OSWorld-V2/` | https://github.com/xlang-ai/OSWorld-V2 | `c261cb57a699bd18db128787ca4e71b749141762` | clean；仅取得对应源码，未应用 Arijit patch |

第三个仓库最初网页/API 返回 404，随后用 Git `.git` 地址访问成功并完成下载，已不是阻塞项。

既有工作区 `OpenWebRL/` 是官方 `OpenWebRL/OpenWebRL`，不是用户指定 fork；因此另建副本，未覆盖旧目录。既有 `multi-agent-computer-use/` 也不是 Arijit 的仓库，没有混用。

## 三者实际关系

```text
OpenWebRL：模型 rollout / 轨迹 / reward 接入 / RL 训练
    ↓ 需要环境客户端适配
Orchard：创建、执行、回收 sandbox
    ↓ sandbox 内运行任务环境
Arijit 的环境层：CUA-Gym web mocks / OSWorld desktop worker
```

- OpenWebRL 已有 Orchard browser sandbox 客户端，不必重新设计整套服务。
- Arijit 仓库本身的训练引擎是 vendored verl/GiGPO。若目标是用 OpenWebRL 训练，应先理解并复用它的环境层，不需要同时部署两套训练引擎。
- Web 分支：Vite/React mock 应用 + Playwright，使用 `sid` 隔离状态，`initial_setup.py` 初始化，`reward.py` 评分。
- Desktop 分支：当前 `worker_bridge.py` 的 `DesktopSession._boot()` 显式写了 `provider_name="aws"`。它不是现成的纯本地桌面环境；直接运行会涉及 AWS。尚未执行该分支。
- 当前本机是 macOS ARM64；完整 OpenWebRL CUDA 训练需要另一类硬件，浏览器环境可单独在本地运行。

## 上一阶段只读检查结果（历史记录，当前状态以上方桌面准备结果为准）

**结论：独立 CUA-Gym web worker 的基础依赖已基本齐备；缺的是解包一个真实任务、配置本地路径与完成运行验证。将它接到 Orchard / OpenWebRL，以及在 Mac 上运行 desktop，是后续不同层面的工作。不能把这些全部归为“缺 Python 包”。**

### A. 单独运行 Arijit 的 web 环境

已通过的检查：

- `.venv`：Python `3.11.1`，Playwright `1.58.0`，requests `2.34.2`，PyArrow `25.0.1`，zstandard `0.25.0`，Pillow `12.3.0`；`pip check` 未发现已安装包的依赖冲突。
- Playwright ARM64 Chromium / headless shell 已在 `browsers/`，不需要重新下载。
- 当前 shell 的 Node `v24.12.0`、npm `11.6.2` 可用；这是本次 shell 检查值，不代表上轮所有安装过程都用了该 Node 版本。
- Instagram、HubSpot、Google Docs、Google Calendar、Notion 五个 app 的直接 npm 依赖均存在，版本与恢复后的原版 lockfile 一致。此检查没有声称完整依赖树、应用构建或启动已通过。
- 原版 `web_worker.py` 可按文件加载成功，未修改源码、未实例化 worker、未启动浏览器。其顶层依赖无需 torch / verl。
- 已下载索引有 **10,910** 行，其中 **1,075** 行为 web。四个主要 mock 对应 **282** 个任务：Instagram 79、HubSpot 77、Google Docs 76、Google Calendar 50。
- 流式读取压缩包，核实这 282 个任务引用的 **846 / 846** 份 task/setup/reward 文件均存在；仅在内存读取，未解包或执行。
- 这批 Python setup/reward 文件均能由 Python AST 解析；静态非标准库 import 只有 `requests` 和 `urllib3`，当前环境均已安装。静态 import 检查不覆盖动态 import、外部程序或脚本运行语义。

还缺 / 尚未做：

1. **任务落盘与 task dict**：压缩包尚未解包；worker 所需的 `setup_files`、`reward_local`、`instruction`、`app_type` 等字段尚未组成可运行的本地任务。
2. **本地路径与配置**：Hub 在并列的 `sources/CUA-Gym-Hub`，而 Arijit launcher 默认寻找仓库内 `datasets/third_party/CUA-Gym-Hub`；需用本地配置明确 Hub 路径、Python、浏览器目录和 mock URL。路径不同不等于需再 clone 一次。
3. **实际运行验证**：原版 worker 的 reset → screenshot → action → reward → close 未执行；sid 隔离和 reward 是否正常也未验证。上一轮 OpenWebRL 的简单按钮测试不能替代它。
4. **若坚持用原数据 loader**：`datasets/loaders/cua_gym.py` 需要 `pandas`、`huggingface_hub`，本 venv 未安装；它调用的 `zstd` CLI 当前可用。若只是验证一个已下载的任务，已有 PyArrow / zstandard 可读取资料，不必为此先装完整训练栈。
5. **若使用 vector manager**：`manager.py` 需要 numpy，目前未安装；完整训练入口还会引入更多依赖。这不阻塞独立 web worker 的基础导入。

所选本地 mock + 脚本动作 + programmatic reward 的初始验证，不需要模型 API key、CUDA GPU 或 Browserbase 账号。若使用真实模型自主操作，再配置 policy endpoint；若使用 live-web judge 分支，再配置 judge。

### B. Orchard 本地 sandbox

已具备 SDK、Docker/Colima/kubectl 工具和一个已停止的独立本地 cluster；SDK 导入成功。尚缺可用的 orchestrator 服务和完整 sandbox 验收，本轮没有重新启动 cluster 查询实时对象。

- **部署配置尚未定案**：上游 orchestrator YAML 默认 3 replicas，每个请求 4 CPU / 16 GiB，Redis 另请求 4 CPU / 16 GiB；合计请求 16 CPU / 64 GiB，超过现有本地 VM 的 4 CPU / 6 GiB。需要本地配置覆盖 replicas / resources，不需要因此修改 Python 业务源码。
- **Redis 有两条原生路径**：多副本部署 Redis；单副本可使用源码已有的 `USE_REDIS=false` 内存存储选项。该选择尚未运行验证。
- **镜像分发缺方案**：原版 injector 使用 `Always` 拉取策略，需要可达 registry。此前改成 `IfNotPresent` 只是我选择“本地预载镜像”方案的适配，并不是运行 Orchard 必须修改的源码；保留原版、配置 registry 也是可选路径。两者都未继续执行。
- **环境镜像未完成**：已有本地旧镜像含过临时改动，不能视为 clean checkout 的正式构建产物；目标 CUA-Gym worker + mock 如何放入 sandbox 尚未打包。
- **网络与生命周期未验证**：未来需检查 pod 到 mock 的实际地址、创建/执行/删除、状态隔离。Mac 上的 `127.0.0.1` 不能直接当作 pod 内同一个服务地址。

### C. OpenWebRL 接入：重新核对之前的改动是否必要

1. **SDK import 可以先不改源码**。本次用当前 `.venv` 加临时 `PYTHONPATH=<Orchard>/orchard_env/orchard_env`，成功执行原有的 `from client.sandbox_client import AsyncSandboxClient, AsyncSandboxInstance`。因此“必须改 import”不成立；先用启动配置即可解决这一层路径问题。只验证了导入，尚未证明整个 sandbox 调用链兼容。
2. **browser Dockerfile 确有漏文件的静态证据**：`web_env.py:11` 导入 `openwebrl.feedback_utils`，Dockerfile 的 COPY 列表未包含它。在按该清单生成的独立镜像中会缺此模块。尚未构建原版镜像来复现；以后真正采用该镜像路线时，再讨论最小补文件方案。
3. **原版包入口的依赖未齐**：本次直接 import 原版 `openwebrl.docker.env_server`，首先报缺 `transformers`。包 `__init__.py` 会引入训练/rollout 模块；当前 venv 还缺 torch、Ray、SGLang、OmegaConf、loguru 等。不能认为只装 transformers 就一定能启动，也不建议为检查 web worker 一次装完 CUDA 训练依赖。
4. **CUA-Gym 接入尚未实现**：在 OpenWebRL 环境目录和 Orchard Python 代码中未找到 CUA-Gym adapter；在 Arijit 的 CUA-Gym env package 中未找到 Orchard 客户端接入。当前需要明确 task 初始化、action 格式、观测、programmatic reward 和 close 如何连接；这是集成工作，不是 pip 安装能补齐的部分。

### D. Desktop 与完整训练

- 当前新目录未下载 Arijit 所固定的 `OSWorld-V2` / `CUA-Gym` 源码，也没有可运行的本地 desktop VM。工作区其他 OSWorld checkout 不能未经版本核对直接代入。
- 原版 desktop bridge 的 `provider_name="aws"` 写在源码里，纯本地部署还缺本地 provider 方案及 VM 架构兼容检查。没有连接 AWS，也未检查或索取云凭据。
- 本地 `.venv` 未安装完整 RL 栈，未配置训练模型权重或 Megatron-LM；Arijit 示例配置中的 `hf_id` 仍指向作者的 `/projectnb/...` 路径，不能在本机直接使用。
- Mac ARM64 不提供 NVIDIA CUDA 训练环境。以后要训练，需要选定 Linux/NVIDIA GPU 机器并独立配置；当前不操作远端主机。

### 最小建议顺序（本次未执行）

先只选 **一个 CUA-Gym web task**：从现有压缩包取出三份文件，给原版 worker 配好 mock URL / 浏览器路径，使用脚本动作验证 reset、截图、reward 和清理。基础依赖已具备，预期无需先改三个仓库源码。通过后再决定 Orchard 打包与 OpenWebRL 接口适配。

本次检查结束：四个源码 checkout 仍 clean；`18100`、`8092`、`8123–8126` 端口均关闭；只更新本 MD，没有安装或启动服务。

数据文件 SHA256（用于识别本次检查的下载件，不代表与发布方校验清单比对）：

- `tasks.parquet`：`334393102f2fd5013c94014999c7db523c65a8bc534827c7bb3f6c3ab82498af`
- `cua_gym_tasks_v1.tar.zst`：`2198e335a8670297cad10405e58b06f3ee7acd8cceaf2d572a5c005e3736f79e`

## 上一轮部署前的初步清单（历史记录，以本次检查结果为准）

以下是检查清单，均不代表已经批准继续修改或部署。

| 部分 | 已确认要求 / 问题 | 最小下一步 | 当前状态 |
|---|---|---|---|
| OpenWebRL browser | Python、Playwright Chromium、FastAPI 等 | 看能否用原版独立入口启动，避免加载训练依赖 | 只在派生精简 runtime 验证通过；原版完整包入口会导入 transformers |
| OpenWebRL sandbox client | 当前导入 `client.sandbox_client`，但引用的 `openwebrl/sandbox/` 不在该版本中 | 确认作者对应 SDK 来源和版本；再决定是否需 import 适配 | 尚未连接验证；临时修改已恢复 |
| OpenWebRL browser Dockerfile | `web_env.py` 需要 `openwebrl.feedback_utils`，COPY 列表未包含该模块 | 原版构建时先确认实际错误；若需补文件只做这一项 | 临时 COPY / Playwright 固定已恢复；构建已停止 |
| Orchard | Python >=3.11、Kubernetes、sandbox agent image；多副本默认 Redis | 先决定是否需要本轮部署 K8s，或只检查 SDK | SDK 已安装，集群已暂停；未部署 orchestrator 服务 |
| Orchard 本地镜像 | init container 使用 `image_pull_policy="Always"` | 先比较原版 registry 路径与本地载入镜像方案 | 本地 IfNotPresent 修改已恢复 |
| CUA-Gym web | Node/npm、指定 mock 应用、Playwright、task tuple | 先选一个 app / 一个 task 验证原版 worker 和 reward | 依赖下载完成，服务已停；真实任务 worker/reward 未验证 |
| CUA-Gym desktop | OSWorld 环境与 VM；当前 worker 固定 AWS | 明确是否要本地 desktop，再检查 provider 与 VM 架构 | 未安装桌面 VM，未调用 AWS |
| 完整 RL | Linux/NVIDIA CUDA、模型权重、Megatron/SGLang 或 verl/vLLM | 后续另列训练环境计划 | 未安装、未启动训练 |

不直接执行上游 `set_up.sh` 或整个 Conda 环境导出：前者包含 Linux CUDA 安装和系统路径链接；Arijit 的环境导出也包含 Linux/CUDA 包。需要先按本轮要运行的组件辨别依赖。

## 本轮已经做过的操作（保留审计）

用户曾授权本地部署后，助手推进到以下步骤；用户指出修改过多后已暂停。这里如实记录，不能理解为“只是 clone，什么都没装”。

### 已安装 / 下载，暂未卸载

- Homebrew 安装：Colima `0.10.3`、Lima `2.2.0`、Docker CLI `29.8.0`、kubectl `1.37.0`。这些工具位于 `/opt/homebrew/`。
- 创建本地 Colima profile `cua-rl`：4 CPU、6 GiB 内存、40 GiB 虚拟数据盘，K3s `v1.35.0+k3s1`。运行数据位于 `~/.colima/`，目前已停止。
- 本地 cluster 中创建过 `orchestrator` namespace、service account、RBAC、API-key secret，并给该本地节点加了 sandbox label。没有部署 orchestrator Deployment，也没有创建云资源。
- 独立 Python venv：`cua-rl-local/.venv/`，安装了 browser runtime、Orchard SDK 和数据读取依赖。
- 独立 Playwright 浏览器目录：`cua-rl-local/browsers/`。
- 安装了五个 mock 的 npm 依赖：Instagram、HubSpot、Google Docs、Google Calendar（上游 hybrid launcher 的四个 app），以及供上游 probe 使用的 Notion。`node_modules` 保留；npm 改写的五份 tracked `package-lock.json` 已恢复原版。
- 下载了 CUA-Gym `tasks.parquet` 和约 49 MiB 的 `cua_gym_tasks_v1.tar.zst`，位于 `cua-rl-local/datasets/`。未执行任务 setup 或 reward。
- 本地 Docker 中构建过 orchestrator 和 agent-injector 镜像；browser 镜像构建被停止。旧镜像可能包含已恢复的临时补丁，不能当作当前 clean 源码的构建结果继续使用。

### 已验证，但范围有限

精简 browser runtime 的本地测试通过：

- `/health` 可用。
- `/reset` 返回 1280 × 1000 PNG。
- `/step` 执行真实鼠标点击，测试页按钮从 `Click me` 变成 `CLICKED`。
- `done` 返回 terminated。
- `/exit` 释放浏览器环境。
- 再次 reset 得到干净的初始按钮状态。

证据：`cua-rl-local/artifacts/browser-smoke.json`、`browser-before.png`、`browser-after.png`。

该测试使用了本地 `browser-runtime/`，按上游 Dockerfile 的文件布局复制必要模块并补入 feedback_utils；它不是原版完整 OpenWebRL 包或 Orchard 集成测试，更不是 CUA-Gym 真实任务成功率。

### 已停止 / 已恢复

- 浏览器 server（原地址 `127.0.0.1:18100`）已停止。
- 五个 mock 服务（原端口 `8123–8126`、`8092`）已停止。
- 本轮 browser Docker build 已停止。
- `cua-rl` 虚拟机 / Kubernetes 已停止。
- OpenWebRL 的两个改动文件、Orchard 的一个改动文件已恢复 HEAD。
- CUA-Gym-Hub 的五份 npm lockfile 已恢复 HEAD。
- 四个 checkout 均再次检查为 clean；Arijit 源码从未修改。

撤回前的 diff 留在 `cua-rl-local/artifacts/*-reverted-changes.patch`，仅用于知道改过什么，未重新应用。

## 后续顺序

1. **已完成**：三个指定仓库下载到独立本地目录，固定版本，恢复原样。
2. **下一步仅检查**：确定先跑 web 还是 desktop；逐项列出缺少的依赖、配置、资产和入口。
3. **待讨论**：如果原版无法运行，解释具体报错、最小修改和替代方案；一次只处理一个问题。
4. **待继续授权**：按选定范围恢复部署并验证一个环境的 reset → action → reward → close。
5. **尚未开始**：OpenWebRL 环境适配、模型 rollout、CUDA 训练。

`cua-rl-local/` 中已有启动脚本、`k8s-local.yaml` 和精简 runtime 都是本轮留下的本地草稿；当前不自动执行，不代表方案已经定下。

## 主要源码依据

- `sources/OpenWebRL/openwebrl/env/sandbox_env.py`：SDK 导入与 sandbox 生命周期。
- `sources/OpenWebRL/openwebrl/docker/Dockerfile.browser`：浏览器环境独立打包方式。
- `sources/OpenWebRL/openwebrl/docker/env_server.py`：reset / step / exit / health。
- `sources/Orchard/orchard_env/pyproject.toml`、`docs/deployment.md`：Python 与部署依赖。
- `sources/Orchard/orchard_env/orchard_env/orchestrator/k8s_client.py`：镜像 pull policy。
- `sources/multi-agent-framework/scripts/setup_third_party.sh`：第三方仓库 pins。
- `sources/multi-agent-framework/third_party/molmoweb-rl/agent_system/environments/env_package/cuagym/web_worker.py`：web reset、action、reward。
- 同目录 `worker_bridge.py`：AWS DesktopEnv。
- `sources/multi-agent-framework/launchers/cuagym_gigpo_hybrid.sh`：四个 mock app。
- `sources/CUA-Gym-Hub/README.md`：mock API 与 sid 隔离。

以上路径均相对于 `/Users/knight/uw/computeragent/cua-rl-local/`。
