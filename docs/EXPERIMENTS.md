# Synthetic task generation for OSWorld — design, experiments, results

## OSWorld2 teacher 剩余91题续跑，仅workstation（2026-09-30 00:27 PDT启动）

- **21:52 PT旧Windows重新上线**（WSL刚启动，21G内存，Docker 29.6.1可用、无运行容器）。现场核实此前只凭缓存的分数：003/005/012/016=0（remaining-20260916-windows）、006=0.2222（d552441-windows），均max_steps=100，与缓存一致。
- **21:32 PT迁移A40安排**：用户定迁A40、保持100步、保持4VM×10G（不开新run加VM）。21:05进度33完成/4运行/49排队/5跳过（026/041 GitLab，050/055/056代理；062/075/098预计同样跳过），满分3/33、均分19.76%，近6小时约1题/小时。A40 hold 40897918(g3045)/919(g3043)/920(g3072)各起一个TP2 teacher（同`serve-teacher-held.sh 0`，每卡KV 14.8GiB/1.83×），workstation隧道8152/8153/8154，身份与采集路由已验证；920为热备。workstation上`setsid`运行`switch-to-a40-20261001.py`，于10-01 17:30健康检查后原子写`service-routes.json`（仅改klone-g3114-r1/r2的url，plan_sha256 66a46200…），之后新attempt走A40，在跑题留在L40S跑完。监视器改为workstation脱离会话运行（`watch-osworld2-20260930.sh`，日志同名.log），teacher检查跟随路由端口；Mac每10分钟短连接读日志。Windows 2222入口TCP通但ssh被对端关闭，原因未查，现走`tailscale ssh yanji@jy-eval-wsl`。

- **04:25 PT**：026两次attempt均在setup报`GITLAB_URL and GITLAB_PRIVATE_TOKEN must be set`，标failed后controller继续派题；026/041需自建GitLab（见`reference/OSWORLD_V2_RUNTIME_REQUIREMENTS.md` §8），属环境阻塞、不计0分。用户定：有问题的题直接跳过；步数保持100（核实历次V2 teacher args.json均为max_steps=100，含09-05 nothink轮，无500步）。同日按用户要求hold krishna空闲卡7天：A100×2 40897923（g3081，仅1CPU/20G，不够起27B）、A40×2 40897918/919/920运行、40897921（A40×2）与40897922（A40×1）排队；cse分区MaxWall 1天，未hold。sbatch在`/gscratch/krishna/jy050706/holds/`。
- **03:50 PT进度**：5/91完成、4运行、82排队，failed/interrupted 0。新分数013=1.0（89决策步/144分钟）、015=0.2840（100步/85分钟）、017=0.1429（51步/36分钟）、018=0（100步/132分钟）、020=0.1（69步/132分钟）；本轮满分1/5、均分30.54%。并入此前15题共20题：满分1/20、均分16.02%。已完成题平均约106分钟/题，按4槽位推算剩余约37–45小时，与39608331剩余约41.8小时持平，能否跑完不确定（仅5个样本，长题偏后完成）。WSL used32G/available22G，两teacher各running2/waiting0，故障监视器无告警。

- 用户授权：只在workstation跑，已评分15题不重跑，036/037仍阻塞；使用空闲占位作业 **39608331（dxg_w41，g3114，8×L40S，到期10-01 21:39）** 中的4张卡；每VM 10GB。`hold-l40s-7d`（40340981）自09-19起因krishna组GRES额度PENDING，未使用。GPU4–7留给原项目。
- Teacher：27B BF16权重52GB放不下单张L40S（46GB），故2个TP2副本：r1=GPU0/1:8150（step 39608331.2）、r2=GPU2/3:8151（step .5）。vLLM参数与09-16 `serve-teacher-signals-full.sbatch`逐行一致，仅端口不同；启动器`/gscratch/cse/jy050706/cua-v2-pilot-20260915/serve-teacher-held.sh`（md5 80217bbc…）。每卡KV 14.71GiB/476,202 tokens，1.82×262K（09-16为14.85GiB/1.83×）。采集改写`/gscratch/scrubbed/jy050706/cua-v2-signals-held-39608331-r{0,1}`，因cse组配额98%满（旧teacher signals 170GB/4982文件保留未动）。采集路由按prepare_model既有方式用未注册模型404探针初始化，不生成token。
- Klone主机内存：单副本anon 8.1GiB、权重文件页缓存52.6GiB（两副本共享）；两副本运行后cgroup 75/128GiB，anon 20GiB。09-16 teacher的Slurm MaxRSS 73.3GiB主要是文件页。
- Workstation：OSWorld-V2-shared新分支`qwen38-v2-vmram` commit `ce0c4fd`（仅本地未push），provider.py的`RAM_SIZE`读`OSWORLD_VM_RAM_SIZE`，默认4G不变；registry设10G、slots 6→4、teacher各capacity2（备份`registry.json.bak-20260930-pre-g3114`）。4容器实测RAM_SIZE=10G/CPU_CORES=4；启动4分钟后WSL used 23G/available 31G，负载6.3/20线程。
- Run：`27b-base--osworld2--remaining-ws4vm10g-n91--20260930T072726Z-8b8df9cf247c`，panel `cua-eval/osworld2-remaining-20260930.json`（91题），plan→doctor（无错误）→run，controller PID263679。首批013/015→r1、017/018→r2；首步attention条目数=输出token（398/398、722/722、253/253、75/75），L63/H0，2040视觉token/图，capture_errors空。协议未变（thinking、preserve=False、10图/fold1、100步）。
- 预计：按上一轮每步2.5–3.2分钟与多数题跑满100步，91题/4VM粗估46–90小时，大概率超过39608331剩余约45小时，届时需迁移teacher；低置信度。

## OSWorld2 teacher（Qwen3.8-27B）eval进度核对（2026-09-29 23:58 PDT，只读）

- 仍停在2026-09-16 20:21的用户暂停，之后没有续跑。Workstation实查：无eval进程、无运行容器；最后活动是09-22的cuagym评测。旧Windows在Tailscale上离线约1天，Windows分片按Mac catalog缓存（09-19 21:28同步，晚于暂停）及`reports/OSWORLD_V2_REMAINING_20260916.json`计，今日未能现场复核。
- 当前协议（shared commit d552441、thinking=True/preserve=False、10图/fold1、100步）：**108题中15题有最终分数，2题代理阻塞（036/037），91题无分数**（workstation分片70、Windows分片21）。
- 已评分：001=0.4444、004=0.1111、006=0.2222（Windows，仅报告记录）、014=0.90，其余002/003/005/007/008/009/010/011/012/016/019均为0。满分0/15，含部分分均分11.19%；001/002/004/006来自131K上下文服务，其余为262K全token采集，来源差异保留。
- 91题中8题有中断轨迹，无分数：workstation r2的013（28步）、015（92）、017（45）、018（99）、021（36）、022（43）；Windows的020、024。其余未启动。r2在6VM下13:17–20:21约7小时仅完成2题（014、019）。
- 按记录teacher采集服务40207395已于2026-09-22到期；续跑须重新部署teacher并核对身份，本次未查Klone现状。09-05不开thinking的旧轮次（39/108）协议不同，不与本轮合算。

## 9B r5＋v16save143 no_grad 完训并启动 Verified100（2026-09-19）

- **20:05 PT，90题同题比较及追加核查**：新51/90满分（56.67%）、均分58.4508%；旧同题59/90（65.56%）、均分67.6678%。严格满分翻转为12退步/4改善，净少8题；13退步/5改善指任意分数升降，其中含0.997988→0及0→0.702663，不能都称为满分翻转。新增实证：VSCode缩进题最终文件仅第2行缺少应有4空格，模型却报告全部完成；DOC转PDF任务模型报告12份，但评测cache归档实际9份有效PDF、gold12份，且命令历史正则也失败；Conda评分只检查bashrc中的conda initialize标记，未独立确认替代做法的功能正确性。数据manifest显示v16占3668/10142样本行（36.17%，非loss权重），terminalfix为append129/rewrite11/already3；这些是数据审计线索，未证明造成退步。训练从原始Qwen3.5-9B开始，不是旧r5 checkpoint续训；同为3epoch，477vs306更新不能单凭步数判定过拟合。保留本轮所有原始分数和配置。[90题核查证据](../reports/r5-v16save143-eval100-20260919/regression-diagnosis-90tasks.json)。

- **17:45 PT“是否卡住”检查**：17:41时已评分仍38，Workstation/Windows分别约21/17分钟无新任务结束，但多数活跃轨迹最近动作仍更新，检查时两题处于48/50轮，最慢Impress一轮等待约339秒。4路服务约93秒合计新增9417输出tokens、完成11次模型请求，waiting均0，GPU即时利用率35–37%；17:44已评分增至39。17:45目录确认39题，38份完整信号passed、1份processing，无failed。未发现整轮死锁或出图堵住计分；未重启/终止任务。正在生成token不保证单条长回复不会耗时很久，需与“整题完成数”区分。[运行核查](../reports/r5-v16save143-eval100-20260919/stall-check-20260919-1745.json)。

- **17:33 PT，38题下降核查**：22/38满分57.89%，均分60.2711%；旧同题25/38=65.79%、均分68.1659%，3胜6负，净少3题。相较20题新增18题，仅8满分＋1部分分＋9零分，旧同18题12满分，新增5退步/1改善。6个旧对新错均为Office：Calc3、Impress2、Writer1。逐文件核实包括：工具名computer而非computer_use导致空解析→DONE首步退出；字体FF4000≠FF8000；去bullet但未对齐段落缩进；PAGE字段插在正文且无footer；50步后仅保留1个而非2个pivot。另1个冻结题为**评测假阴性**：实际与gold的freeze边界均frozen/2列/1行且表格数据相同，仅滚动视口C17 vs C2不同；当前metric仍比较freeze_panes，单独重放freeze0、sheet_data1。保留原分数/协议，未修改正在跑的评测。10,142监督目标检出11,824个函数标签均为computer_use，但该检查不等于全量数据质量认证。[38题核查证据](../reports/r5-v16save143-eval100-20260919/regression-diagnosis-38tasks.json)。

- **16:51 PT，20道已完成同题的step对比**：模型决策步数按native traj相同step_num/response合并多动作、仅最后episode，含WAIT/DONE/FAIL、不含初始截图；40条新旧traj均单episode、步号连续。旧324/20=16.20，新315/20=15.75（−0.45步/−2.78%）；两边都满分12题10.75→10.83，两边都0分5题27.40→30.40。平均底层动作记录19.55→20.15，不能把它与决策步数混用。部分总均值下降来自仍失败的Chrome任务50→13步；新模型尚未显示对共同成功任务的显著步数节省。旧20/fold10与新10/fold1及服务执行差异仍需披露，完成子集也不代表全部100题。[逐题计数及口径](../reports/r5-v16save143-eval100-20260919/average-steps-20tasks.json)。

- **16:46 PT速度快照**：启动约36分钟、19题已有最终分数，累计31.7题/小时；近30分钟16题=32题/小时，近15分钟7题=28题/小时。Workstation16/67、Windows3/33；导出已完成14＋3题，WS另2题待处理、最长约69秒；WS只有1个在途下载，Windows全部下载完成。当前没有大规模出图/下载积压。固定host分片下Windows剩30题，按其启动以来/近15分钟吞吐约需3.8–5.7小时，故整轮剩余暂估4–6小时、低置信度，不能把总吞吐线性外推的2.6小时当完成承诺；题型和并发分配不同，尚未隔离各自影响。[速度快照](../reports/r5-v16save143-eval100-20260919/speed-20260919-1646.json)。

- **16:40 PT快照**：15/100已评分，11/15满分=73.33%，均分73.33%；Workstation13完成/6运行、Windows2完成/3运行，合计76待跑、运行异常0。旧纯r5在相同15题10/15=66.67%，逐题2胜1负、净多1题。此对照旧r5推理20/fold10、新10/fold1且服务执行栈不同，又是已完成的早期子集，不能据此归因v16数据或no_grad收益。[进度与逐题对照](../reports/r5-v16save143-eval100-20260919/progress-20260919-1640.json)。

- 用户点名W&B训练 `9b-full-r5+v16save143.tf-ml65k-vnograd-klone1x4-40253867`。已查实际退出码0、epoch3、global_step477/max_steps477、最后保存日志和4个完整权重分片；训练结束时间日志14:26:51。最终权重为`/gscratch/krishna/jy050706/out/9b-full-r5+v16save143.tf-ml65k-vnograd/train20260917-klone1x4/v0-20260917-125722/checkpoint-477`，不使用159或318。
- 标准prepare_model校验17份推理文件并发布到`/gscratch/cse/jy050706/sft/serving/9b-full-r5+v16save143.tf-ml65k-vnograd--train20260917--s477/model`。复用刚空闲的40253867/g3087/4×A10080GB，在step33启动四路8084–8087服务；未改动其它模型服务/分配。
- 原Verified100相同任务SHA `8e7d2b5c91275d4b9620306a527f09910605542ca1a1378e1a6ab0ae66b1af91`；全分辨率img10/fold1，thinking及preserve_thinking=true，temperature1/top_p0.95，max_tokens81920/max_steps50；明确OSTG_HISTCOMP=0。两端默认min/max像素已冻结，实际预处理1920×1088/2040 tokens且输出PNG SHA一致；两端images.py仅可选min_pixels传参存在差异，此输入配置下实测一致，未覆盖benchmark源文件。
- Workstation67题/6VM，8084–8086各2路；Windows33题/3VM，8087负责3路。四服务均ready，标准plan→doctor→run成功；Workstation controller147853、Windows98349，已实查6＋3个任务运行，初始无failed/blocked/interrupted。两端native进程实际HISTCOMP=0；真实回复抽查192/192、191/191、394/394输出位置attention齐全，历史图各2040tokens。全部输出token的L31/H0/image_keys采集、异步下载、整条轨迹与热力图、校验后清理沿用现有管道；仅同步已注册的命名模块用于新语料描述。
- Run：`9b-full-r5+v16save143.tf-ml65k-vnograd--train20260917--s477--verified--verified100-n100--20260919T230610Z-60aae87eeeb7`。Registry：`cua-eval/registry.r5-v16save143-s477.json`。[完成/部署/配置证据](../reports/r5-v16save143-eval100-20260919/request.json)。此次评测是r5＋v16save143的505轨迹/10,142样本模型；同日另行合并的Tillicum数据是纯r5的362轨迹/6,474样本，二者不得混淆。


## Histcomp-9B 原前50题重评（2026-09-18，50/50已完成）

- **最终结果（9月18日12:33 PT核实）**：50/50均有最终分数，27/50满分=54.00%，含部分分均分55.8061%。旧同样50题29/50=58.00%，均分59.8061%；两项都低4.00个百分点。逐题5胜7负、38相同，净少2题；Chrome3→5、GIMP4→2、Calc10→9、Impress10→9、Writer2→2。运行状态completed，基础设施failed/blocked/interrupted均0；结束时间为2026-09-18 02:47:39 PDT。以下14/17题分析保留为历史中途快照，不代表最终结果。[最终逐题得分](../reports/histcomp-first50-20260917/final-scores.json)。


- **后续17题快照（2026-09-17 23:42 PT）**：旧同题9/17=52.94%，新7/17=41.18%，2胜4负，净少2题；Chrome3/6→5/6、GIMP4/8→2/8、Calc2/3→0/3。相较14题新增3个0分，其中GIMP三角形居中和Calc销售图表两题旧版也0，两次都用完50模型步；新增退步为Calc `04d9aeaf…`（旧1→新0）。直接读取保存xlsx及golden的Sheet2，2015–2019公式/数值基本对应，但新结果额外插入2014空变动行，违反要求并导致整表内容不匹配。此前两个infeasible终止状态错误及利润公式错误仍在。该差距不能再以14题“只差1题”的快照描述；也尚不能归因于压缩、采集或单纯随机性。[17题逐题证据](../reports/histcomp-first50-20260917/regression-diagnosis-17tasks.json)。

- **运行中同题核对（2026-09-17，冻结14个已完成任务）**：旧8/14→新7/14（57.14%→50.00%），2胜3负、净少1题。Chrome3/6→5/6；GIMP4/7→2/7；Calc1/1→0/1。不能直接拿这个未完成子集和旧100题60%相比。
- 三个退步任务已逐条核对：GIMP SVG(`62f7fd55…`)和Blue主题(`fbb548ca…`)均识别不可完成，但新输出terminate(success)/DONE，旧为failure/FAIL；原生infeasible evaluator要求最后FAIL。Calc(`035f41ba…`)使用空E列计算Gross Profit，J2为-20000而标准55000，Sheet2标题也未正确保留。现有证据指向终止状态/表格依赖与核验错误，不能据此把历史压缩或视觉grounding认定为总体下降原因。
- 同checkpoint870、同10/fold1阶梯、同temperature1/top_p0.95/top_k20，但旧stock为CUDA Graph/async scheduling，新capture服务为eager/同步调度；尚无固定请求capture开关对照，未分离随机路径与服务执行差异。此诊断未改评测、评分或正在跑的任务。[逐题证据与配置差异](../reports/histcomp-first50-20260917/regression-diagnosis.json)。

- 用户要求重跑当时的 history compression eval，仅前50题。模型沿用 `9b-full-mixbtf-histcomp` / 旧 `histcomp-stock`，Klone 现存 `mixbtf9b-histcomp-e870`，trainer_state=870；14份权重/推理文件完整性、SHA与发布文件已验证。以硬链接发布独立目录，未重复复制模型内容或修改源文件。
- 原 `verified_eval100_nonproxy.json` 的固定顺序前50题，非随机抽样；6 Chrome＋8 GIMP＋15 Calc＋15 Impress＋6 Writer。旧同题结果29/50满分、均分59.8061%。原100题数据不覆盖。
- 参数：image_max10/fold1、history_n100、thinking=true、preserve_thinking=true、temperature1/top_p0.95、max_tokens81920、max_steps50。`OSTG_HISTCOMP=1` 明确写入冻结plan；推理代码两份SHA已纳入预检。1920×1088输入实测age0–1→2040、age2–4→1008、age5–7→510、age8+→252视觉tokens；稳定10图9138 tokens。
- Windows上一轮TMAX20/fold10已33/33 completed、无native任务、下载队列为空；确认三路服务running/waiting均0后，仅停止 `40253895.4` 服务step，保留整个40253895分配。新 `40253895.5` 在g3051三张A40各一个histcomp副本、端口8074–8076，对应Windows8124–8126，3VM每卡一路。Workstation上的TMAX及A100训练未动。
- 三服务模型/上下文/attention接口ready，标准`run_eval.py plan → doctor → run`成功；Windows controller PID50058已启动，3个task均running；native进程实际`OSTG_HISTCOMP=1`。已收到真实回复与attention（抽查136/136、133/133、139/139、76/76输出位置），第4步真实回复已核实4图token为1008/1008/2040/2040、attention175/175输出位置齐全，压缩历史图的采集实际生效。attention仍采全部输出tokens、L31/H0、全部image patches（image_keys），沿用当前异步下载/热力图/清理管道、collection=eval，结果进入8793原正式目录。源码版本/服务精度与旧运行分开记录，不把此次重跑称为旧内核逐位复现。
- Registry：`cua-eval/registry.histcomp9b-s870.json`。Run：`9b-full-mixbtf-histcomp--train20260904--s870--verified--verified100-first50-histcomp-repeat-n50--20260918T050744Z-0dea75a9ec3e`。冻结plan和原运行参数、旧同题分数、压缩实测、服务启动回执见[本轮证据](../reports/histcomp-first50-20260917/request.json)。TMAX的旧A40端点现在已退役，后续若恢复TMAX Windows评测须先重新部署并核对身份，不要直接用旧registry启动。


## 轨迹后处理五项优化已上线（2026-09-17 18:56 PT）

- 已实现：JSON 缓冲流式写入、NumPy 精确热力图量化、Klone 回执清理、有限导出/下载并发、逐决策断点恢复。Workstation 2 个导出进程/2 个下载线程，Windows 1/2；`keep`、清理开关、worker 数量、恢复开关保留。
- 两台 WSL 在当前任务导出完成后切换后处理 worker；eval controller 的 PID/start-time 身份保持，native rollout、VM、服务和冻结 plan 未重启/改参数。当前 20/fold10 继续执行，旧 10/fold1 得分保留。
- 本地 pipeline 55 项与 eval 10 项测试通过；两台 WSL 各 55 项中 54 通过、1 项 Node 浏览器检查跳过（Mac 已通过）。真实 attention heatpack 字节一致；24 行完整写入中位数 WS 0.3031→0.0849 秒、Windows 0.1917→0.0565 秒，不等于整轮 eval 加速倍数。
- 上线后两机均有新任务完整导出、校验通过并生成断点回执。浏览器实看 Windows 新任务 `a462a795…` 的真实截图、整体和逐 token 热力图、share/entropy 正常。
- Klone `.attn` 按已验证的本地归档、下载清单和生产端 SHA/大小核验后清理；18:56 Klone 复查已完成 36 份清理回执、约 53.36 GiB，对应二进制文件均已不存在；后台仍继续。生产端 JSONL 元数据、未知归属、未完成或验证失败的数据保留。旧 worker 的有意 SIGTERM 若留在 `export-error.json`，对照部署回执和后续成功导出识别，不是 eval 被停。
- [验证与部署收据](../reports/pipeline-optimization-20260917/deployment-validation.json)、[配置/恢复案例](../sft/docs/TRAJECTORY_PIPELINE.md#bounded-postprocessing)、[标准 eval 入口](../sft/docs/EVAL_AUTOMATION.md#postprocessing-settings-for-the-next-evaluation)。TMAX 六 GPU 两份 registry 已加入后处理配置；冻结 plan 不追溯更改。恢复旧 plan 后检查其 inspection 中的 producer 配置；旧 plan 未包含新字段时仍默认关闭生产端清理。


## TMAX-9B Verified100 20/fold10 已启动（2026-09-17 14:20 PT）

- 前序10/fold1保留99道评分及1道用户手动中断的Writer题；没有补0、重跑该题或覆盖旧成绩。Writer已导出44次决策、125动作、120张解码图片，校验通过；登记的attention下载全部完成。Windows一条原生Error末行造成的历史页面校验警告仍保留，不伪装修复。
- 新run：`tmax9b-full-r5-ml65k--train20260915--s306--verified--verified100-20f10-after-75ef6328f5ea-n100--20260917T211419Z-72fc6de52532`。标准`plan → doctor → run → status`完成，两端预检ready；启动后已核对Workstation6个、Windows3个native任务运行，controller均alive，尚无新最终分数。
- 同一checkpoint-306、同一Verified100完整任务清单；selected tasks SHA256 `8e7d2b5c91275d4b9620306a527f09910605542ca1a1378e1a6ab0ae66b1af91`。相对前序只改`image_max:10→20`、`fold_size:1→10`，其余protocol字段逐项相等。
- Workstation67题/6VM，3×L40S各2路；Windows33题/3VM，3×A40各1路。复用现有六路image_keys采集服务，未重复提交GPU作业。输出继续进入8793正式目录；训练/其它模型服务未更改。
- 启动时记录的GPU剩余时间：三路L40S约17小时，A40分配约6天。调度状态仍须现查，不把本快照当后续存活保证。
- 本地冻结计划和启动/预检回执：`cua-eval/runs/tmax9b-full-r5-ml65k--train20260915--s306--verified--verified100-20f10-after-75ef6328f5ea-n100--20260917T211419Z-72fc6de52532/`；队列`queued-tmax-20f10.json`已标记launched，避免重复启动。

## 505条 terminal-fix：冻结视觉 no_grad 全量训练已启动（2026-09-17 13:02 PT）

- **13:42 PT W&B已接入**：用户要求同步；独立CPU日志读取进程每30秒读取Swift `logging.jsonl`，历史补传至step5，线上summary已核对step5/loss0.74171185与源文件一致，训练未重启。[W&B run](https://wandb.ai/yanjiayuan/cua-sft/runs/klone-40253867-30-vnograd)，项目`yanjiayuan/cua-sft`，固定run ID支持续传，横轴`train/global_step`，上传时间不等于原始训练时间。同步loss/各应用loss、grad_norm、learning_rate、token_acc、epoch和日志已有内存/耗时指标；不上传图片/权重，禁用日志进程自身system metrics。训练写出exit_code后同步最终记录并结束run。同步进程在klone-login03，13:42 PID1783321；实际状态需现查。代码`9bdb5239cf`，[服务器校验](../reports/a100-nograd-full-20260917/wandb_validation.json)，[同步脚本](../sft/experiments/a100-nograd-full-20260917/sync-wandb.py)。

- 用户在确认 no_grad 影响后明确授权：判断当前 CUA 是否需要视觉梯度，不需要则启动独立 No Grad 版本。当前配方冻结视觉塔和 aligner，截图输入无需梯度，语言模型训练动作输出；因此只对完整冻结视觉 forward 使用 no_grad。每次前向断言视觉参数全部冻结且输入 requires_grad=False；语言侧约8,953.8033M参数保持可训练。未证明数值或eval效果等价，单列实验臂。
- **`9b-full-r5+v16save143.tf-ml65k-vnograd`**：普通 Qwen3.5-9B 基座重新开始；旧r5 362条＋v16保存证据候选143条，terminal-fix，合计505条/10,142行。候选不重新标为独立验证100% instruction完成。max_length65,536，实际最大58,441，无样本或末步因长度丢弃；3 epochs/477 optimizer steps，4×batch1×accum16=global64，lr3e-6，bf16、ZeRO2 CPU offload、原图2040 tokens/图，SDPA，save_steps159，保留3份checkpoint。
- 复用既有 **40253867 / g3087 / 同节点4×A100 80GB / 384GiB主机内存**，当前训练step **40253867.30**，12:56:37 PT后台启动。13:02 PT preflight通过、四rank视觉no_grad标记齐全、单层torchrun正确、训练条0/477，第一步尚未写出指标。两次此前启动失败分别为Slurm变量和Swift重复torchrun，已修复；失败日志保留，未从失败尝试或短测checkpoint续训。
- 输出：`/gscratch/krishna/jy050706/out/9b-full-r5+v16save143.tf-ml65k-vnograd/train20260917-klone1x4/v0-20260917-125722`，父目录含train.log、gpu.csv、部署与数据清单。完整训练仍进行中；未启动eval，Tillicum保留作业未更改。代码隔离分支`train/r5-v16save143-20260917`，commit`302b308a6446705250b571138b125628daa82d96`。
- [启动脚本](../sft/experiments/a100-nograd-full-20260917/train-held.sh)、[视觉补丁](../sft/experiments/a100-nograd-full-20260917/sitecustomize.py)、[配置/校验SHA](../sft/experiments/a100-nograd-full-20260917/deployment.json)、[启动验证](../reports/a100-nograd-full-20260917/launch_validation.json)。此前[长度压力短测](../reports/A100_SFT_LENGTH_PROBE_20260917.md)已完成两步及完整保存，不等于本次全量已完成。
- 13:06 PT交接状态：step30仍RUNNING，四rank no_grad已触发，第一optimizer step仍在计算（0/477，尚无loss条目），未退出；最新每卡显存约45.6–60.1GiB。此时只能确认实际开始训练及前向，不能说全量第一步或checkpoint已完成。[实时快照](../reports/a100-nograd-full-20260917/status_1306.json)、[实际训练args](../reports/a100-nograd-full-20260917/args.json)。

## 10/fold1尾部请求超时记录（2026-09-17 11:45 PT）

- 当前97/100有最终分数：Workstation66/67、Windows31/33，控制进程仍在运行。
- Workstation最后一题Writer `8472fece-c7dd-4241-8d65-9b3cd1a0b568`停留在第45步；runner.log明确记录10:50:40与11:20:41两次`Retrying request to /chat/completions`，间隔约30分钟，与现有1800秒API超时一致。不是单纯目录没刷新。
- 对应8106服务metadata正常，模型ID正确，running1/waiting0；未发现该服务离线。只做了只读核对，没有暂停/重启或改本轮参数，20/fold10继续等待前序完成与导出收尾。

## 固定GPU槽位＋共享待做队列已启用（2026-09-17 09:00 PT）

- 实测Windows r2已完成自己的11题后空闲，而其他两路还有13题未开始；Workstation也出现r2的22题已完成、两槽空闲。不是模型服务故障，是按题预绑GPU造成尾部不均。
- 新controller改为每台host一个共享待做FIFO，每张GPU的VM并发仍固定L40S2/A401。只调度未开始题；运行中的任务保持原服务和PID，已评分文件hash保持。原host67/33面板、冻结plan和模型/评测参数未改，实际teacher以execution/task-state为准，旧plan.task_teachers只作历史计划。
- 本地及两WSL各14项调度/路由测试通过。刷新后现场确认Workstation2+2+2任务、Windows1+1+1任务在跑，所有六张卡都有分配。新controller PID83083/21792，精确状态仍需现查。
- 代码入口`run_eval.dispatch_tasks`，操作记录`<run>/dispatch.json`与`dispatch-handoff.json`。下一轮20/fold10沿用此调度方式与六路优化服务，不额外提交GPU。

## 六卡新版采集已上线并续跑（2026-09-17 08:08 PT）

- 当前同一10/fold1、Verified100、checkpoint306继续；原冻结plan未改。Workstation6VM→3张L40S各2路；Windows3VM→3张A40各1路。新L40S作业40254676/g3100:8054、40254568/g3100:8055、40254723/g3124:8056；A40复用用户的40253895 allocation，在g3051的step4启动8064–8066三个独立副本，不额外提交A40占卡job。节点/端口须再现查。
- 六路均通过真实带图采集与PNG验证，collector SHA `432324bf706d630b9e51f59b3b01b0dbba0ff61a2b4552cf2d278468b902a713`；使用全部输出token、L31/H0、所有image patches，存储范围image_keys。原始full-context softmax保留，不是图片内重归一化；文本逐位置权重不存，保留full/non-image mass与entropy摘要。
- 去列表往返、复用log-softmax、collect移出API事件循环已随服务启用。新任务继续异步下载；原先长期运行的native进程保留其加载时的下载代码，服务端已升级，任务完成后自然使用新client。
- 两个controller已接管原native PID，未重复启动正在做的题。切换在已保存的模型回复处SIGSTOP/SIGCONT，保留VM与内存状态；维护门禁全部解除，已确认无遗留暂停PID。切换前已完成成绩校验保持不变。新controller PID为Workstation79407、Windows15102（易变，现查）。
- 当前运行registry指向`cua-eval/registry.tmax9b-s306-6gpu.json`；下一轮`registry.tmax9b-s306-6gpu-20f10.json`。`six-gpu-transition.json`已标complete；排队任务升级门禁已ready，后续复用六路服务，不能按旧三卡说明重复换版/占卡。
- 原始验证/回执：[SIX_GPU_IMAGE_CAPTURE_20260917.validation.json](../reports/SIX_GPU_IMAGE_CAPTURE_20260917.validation.json)；操作与复用：[EVAL_AUTOMATION](../sft/docs/EVAL_AUTOMATION.md#reuse-a-held-allocation-and-preserve-active-tasks)；范围与格式：[TRAJECTORY_PIPELINE](../sft/docs/TRAJECTORY_PIPELINE.md#image-key-storage-same-visual-values-less-transport2026-09-17)。

## 505条语料：Klone 4×A100长度短测通过隔离优化配置（2026-09-17 07:07 PT）

- 用户授权测试已占住的同节点4×A100能否训练普通9B，并询问降低max_length的效果。使用40253867/g3087现有占位，没有新申请GPU或启动正式三轮训练；未更改Tillicum的298926作业/数据。
- 505条/10,142行实际最长58,441 tokens；64K不丢样本。48K默认超长排除会丢28行及3条轨迹末步；32K会丢914行及81条末步，故不能把降低上限视作无代价优化。
- 原ZeRO2-offload、10图/2040视觉tokens在48K及32K压力样本均0/2步、视觉阶段OOM。仅对完全冻结视觉塔显式no_grad的64K隔离版本，完成全数据最长64行的2个optimizer steps及完整checkpoint保存，exit0；训练及保存22分11秒，reserved峰值63.66GiB，nvidia-smi采样66.92GiB。语言模型3个矩阵切片共2,527个值变化，4份optimizer/RNG和scheduler齐全。
- 此结果支持这4卡可运行该隔离优化配方的短测，不等于505条全量三轮已通过或效果保持不变。压力样本均长45,536–58,441 tokens，不应用其吞吐直接估算全语料速度；尚未验证checkpoint恢复。短测权重约136GiB，存于`/gscratch/cse/jy050706/sft/experiments/a100-length-probe-20260917/results/cap64k_frozen_nograd/train/v0-20260917-064332/checkpoint-2`。
- [完整报告](../reports/A100_SFT_LENGTH_PROBE_20260917.md)、[实测汇总](../reports/a100-length-probe-20260917/smoke_summary.json)、[checkpoint核查](../reports/a100-length-probe-20260917/checkpoint_verification.json)。独立实验分支脚本/补丁已版本化；不是修改共享容器内的库文件。

## 旧eval更快的硬件与服务差异核实（2026-09-17）

- 旧r5/a2 `eval50-a2-20260823`实际为100题、3VM；Tillicum `sacct`确认对应job **253817 / eval4ba2 / g010 / 1×H200**，03:24:44–07:12:03。旧日志`serve4bbo_253817.out`确认checkpoint-306、vLLM0.25.1、`enforce_eager=False`、CUDA Graph FULL_AND_PIECEWISE、FP8 KV。当前是3×L40S、9VM、eager、BF16 KV、逐输出token的完整采集。**不能将其描述为相同服务单纯加了VM。**
- 同样已完成的30题：旧487次模型决策、当前492次；原生traj首至末动作时间按题求和，70.04分钟→443.38分钟（6.33倍）。这是并行任务耗时之和，不是整轮墙钟；不含首步模型响应/启动，且新旧模型、历史图片策略和诊断不同，不能把6.33倍全归因某一项。
- 旧实际`enable_prefix_caching=False`，所以**不能把prefix cache关闭作为本次相对旧a2的新增减速原因**。20/fold10与10/fold1含义已查WSL history.py；不将fold10说成图像缩小10倍。
- 解释与边界：9VM相对3VM最多提供3倍任务并发，无法自动抵消单题服务成本的大幅增长。异步下载与三项小优化有用，但没有证据保证能恢复旧eval时长；硬件与capture开关需要同模型同协议对照后才能分配各自开销。当前不改采集范围、不额外占GPU。
- 逐题耗时与Slurm/日志证据：[TMAX_VS_R5_SPEED_20260917.json](../reports/TMAX_VS_R5_SPEED_20260917.json)。

## TMAX Verified100 当前进度与下一轮升级门禁（2026-09-17 06:35 PT）

- **本轮10/fold1继续**：Workstation25/67、Windows5/33，总计30/100；6+3个VM正常执行，抽查当前9题request_errors均为0。近30分钟5题、近60分钟7题。尚有5道旧同步任务；新任务按已部署异步下载运行。此刻两机后台下载收据均已完成，没有pending/failed积压。
- **粗估剩余8–12小时，低置信度**，即9月17日约14:30–18:30 PT；不含下一轮服务换版/Slurm排队。单纯按最近合计7–10题/小时算是7–10小时，额外余量考虑Windows分片偏慢、长thinking与后处理收尾。未完成任务不均匀，若Windows持续旧速度会超出范围；不把7步局部加速直接当整轮加速。原始统计见[进度快照](../reports/TMAX_VERIFIED100_PROGRESS_20260917.json)。
- **用户授权下一轮启用三项服务端优化**。队列`cua-eval/queued-tmax-20f10.json`已增加`serving_upgrade.required=true`和候选/基线SHA、隔离tool路径、回执路径。现有heartbeat `tmax-9b-20f10`已更新，不再直接复用旧服务启动20/10。
- 顺序：前序67+33全部最终评分＋两controller completed退出＋后处理排空→只对空闲的3路TMAX服务做隔离tool换版并登记新Slurm作业→逐路preflight和短采集验证→标准plan/doctor/run启动同一Verified100的20/fold10。3单GPU、6+3VM、其他评测设置保持；不覆盖27B等服务共用的tool、不打断本轮、不重复提交、不重算旧成绩。
- **调度性质**：沿用Mac/Codex每10分钟的heartbeat，需要宿主可用；不是Slurm原生依赖。服务换版可能需重新排GPU或加载；阶段/作业ID持久保存，失败先报告，不反复登录或静默跳过升级。具体流程见[EVAL_AUTOMATION](../sft/docs/EVAL_AUTOMATION.md#required-serving-upgrade-before-the-queued-2010-run-authorized-2026-09-17)。

## 服务端采集优化候选：仅隔离测试，未上线（2026-09-17 06:26 PT）

- 两个实现文件的最小改动：float32 buffer取代Python列表往返、复用log-softmax、collect移出API事件循环；采集范围/数值/文件格式保持。
- Klone同vLLM镜像11项测试全通过；本地27通过、5无Torch跳过。真实3行attention的重编码SHA与原始块一致。三路服务/两个controller未替换或重启。
- 局部GPU→CPU转换+压缩写盘耗时约少18–20%，每token entropy/top-k少0.076ms；59.5MB文件整理时事件循环最长停顿中位数44.8→2.7ms。**不是整轮eval加速测量；没有新模型forward A/B。**
- 源码、命令和局限：[管道文档](../sft/docs/TRAJECTORY_PIPELINE.md#服务端三项最小改动的隔离测试2026-09-17)；[完整验证数据](../reports/CAPTURE_SERVER_OPTIMIZATION_20260917.validation.json)。

## Klone krishna：追加L40S单节点8卡与A40三卡，均7天（2026-09-17 06:15 PT）

- 用户要求L40S 8卡必须同节点、7天，并占位A40 3卡、7天。已提交 **40253896（gpu-l40s-krishna，nodes=1，gpu:l40s:8，16CPU/512G）** 与 **40253895（gpu-a40-krishna，nodes=1，gpu:a40:3，6CPU/192G）**，均normal QoS、TimeLimit=7-00:00:00，仅占位sleep。两者脚本语法、部署SHA256和Slurm test-only通过；实际作业号不等于test-only返回值。
- **A40 40253895 已于06:15:11 PT启动，节点g3051，3张同节点NVIDIA A40**；日志确认3张设备，EndTime 2026-09-24 06:15:11 PT。
- **L40S 40253896 截至06:15:45 PT为PENDING，未分配节点**；正式队列当时预计2026-09-17 06:21:37 PT开始，预测可能变化，不等于已经拿到卡。此前组内42/42 GPU额度已满，未为本次请求手动停止其他运行任务。
- 原A100占位 **40253867 / g3087 / 4卡**继续RUNNING，到期2026-09-24 06:10:48 PT。用户原有两个dxg待排作业和现有模型服务均未改动。
- 文件分别在 `/gscratch/cse/jy050706/reservations/l40s-1x8-20260917/` 和 `.../a40-1x3-20260917/`；[三组状态与硬件日志](../reports/klone-krishna-20260917/l40s_a40_submissions.json)、[L40S脚本](../reports/klone-krishna-20260917/hold-l40s-1x8-7d.sbatch)、[A40脚本](../reports/klone-krishna-20260917/hold-a40-1x3-7d.sbatch)。

## Klone krishna：单节点4×A100占位7天已运行（2026-09-17 06:12 PT）

- 用户明确要求查krishna空闲GPU，并申请4张A100、7天、必须同一节点。已提交 **40253867**，account `gpu-a100-krishna`、partition `gpu-a100`、QOS normal、`nodes=1`、`gres=gpu:a100:4`，配套16 CPU/384G主机内存。单节点是硬约束，不会拆到多个节点。
- 实际06:10:48 PT启动于 **g3087**，截至06:11:38 PT为RUNNING；EndTime **2026-09-24 06:10:48 PT**。作业日志确认CUDA_VISIBLE_DEVICES=0,1,2,3，四张均为 **NVIDIA A100 80GB PCIe / 81920 MiB**。当前执行占位sleep，没有启动训练或推理。
- 脚本/日志目录 `/gscratch/cse/jy050706/reservations/a100-1x4-20260917/`。实际作业号不是test-only的40253859。通过Tillicum login02已有`klone.sock`连接，落在klone-login03。未手动操作其他已运行的模型或作业。
- 06:12 group额度快照：A100总6/已用4（含此次4卡占位）、A40总24/已用21、L40S总42/已用42。配额不等于物理空闲，其他用户/账号也可能占用同一分区节点。06:11物理空闲（排除维护/保留/故障节点）：A100 0、A40 69（其中有空闲CPU的节点上50）、L40S 28、L40 27（有CPU19）、H200 11；这些数量不保证在某账户下立即启动。
- [申请脚本](../reports/klone-krishna-20260917/hold-a100-1x4-7d.sbatch)、[运行状态及硬件日志](../reports/klone-krishna-20260917/after.json)、[各类型物理空闲快照](../reports/klone-krishna-20260917/physical_free_summary.json)、[启动后组用量](../reports/klone-krishna-20260917/group_usage_after.json)。

## TMAX Verified100：attention 后台下载（2026-09-17 05:59 PT 部署）

- 当前 `...20260917T111039Z-75ef6328f5ea` 继续 **10/fold1**，Workstation6VM＋Windows3VM；controller PID 69181 / 4605保持，模型服务器/VM没有重启，冻结plan未改。切换前后原始分数不重算。
- 两机部署 recorder/downloader/after_task/run_eval，并原子更新该run的inspection capture为`background`；**新的native task进程启用，已在运行的task继续旧配置**。新计划默认后台下载；20/f10仍按已有后续队列等待，未提前启动。
- Klone先保存文件→回复动作→WSL写下载清单并执行→已有后处理进程的下载线程续传/SHA校验→文件齐后渲染→校验通过才按原保留开关清理。每host最多一个后台下载；保留全部已选output-token attention，Klone spool不删。
- **06:05 PT 真实衔接确认**：新任务`68a25bd4-59c7-4f4d-975e-da0c8509c848`第1步记录background；06:05:35动作开始，06:05:53才完成33.8MB attention下载与SHA校验（19.41s），任务未等文件。旧Windows已部署并通过真实文件续传，当前旧native task仍在继续，到新task边界才启用。
- 去掉recorder未使用的全历史request内存列表。异步只消除动作前的文件传输阻塞，不消除服务端推理/采集和VM操作时间，未声称固定倍数加速。
- 本地及两机隔离目录各29项测试通过；两个真实模型文件隔离续传SHA一致，原件未改。部署前后SHA/备份、测试/真实文件证据见[验证报告](../reports/ATTENTION_ASYNC_DOWNLOAD_20260917.validation.json)。
- 使用、故障恢复与回退案例统一放在[轨迹管道文档](../sft/docs/TRAJECTORY_PIPELINE.md#attention-后台下载与正在运行的任务衔接2026-09-17)，新eval入口见[EVAL_AUTOMATION](../sft/docs/EVAL_AUTOMATION.md)。

## 普通 Qwen3.5-9B：r5 + v16保存证据候选143，terminal-fix，两种拓扑（2026-09-17）

- **用户最新决定：只保留2×8**。已执行 `scancel 298925 298931 298930`，取消2×4、2×2、1×4；2×8 **298926** 保留在urgent队列。以下四拓扑记录为历史提交信息，不应重新提交已取消的三组。数据与脚本保留。

- **05:26 PT 用户追加 1×4 和 2×2**：已分别正式提交 **298930（1节点×4 H200）**、**298931（2节点×2 H200）**，均urgent、accum16、global batch64，其余模型/数据/训练参数沿用本节。先前298925/298926保留。新增两组分别32 CPU/800G总主机内存；1×4集中于1节点，2×2每节点16 CPU/400G，时限均24h。
- 05:26:38 PT四组均PENDING/Priority。正式队列当时给出的预计启动：298930为09-18 18:22 PT，298931为09-19 02:23 PT；前两组N/A。预测会变动，不能把test-only估计当实际作业状态。新脚本已通过命名/语法、数据preflight与Slurm test-only，代码提交`cba9d0c629`；新增部署记录`deployment-4gpu.json`，未覆盖前两组部署说明。输出分别`$B/out/9b-full-r5+v16save143.tf/train20260917-1x4`与`.../train20260917-2x2`；日志`$B/save143tf_1x4_298930.out`和`$B/save143tf_2x2_298931.out`。详见[四作业快照](../reports/r5-v16save143-tf-20260917/four_job_snapshot.json)。

- 用户固定选择旧 r5 362 条 + 本会话 v16 143 条候选，并明确追加 terminal-fix；之后要求同时排 2×4 和 2×8 两个 urgent 作业，每个最多两个节点。没有将候选重新命名为已独立验证全部 instruction 的数据。
- 语料从 Tillicum 已有 `q38-Bhqs2t-r5nocapimg10-v11{100,500}` 和 `mixbtf-v16-{main,pilot}` 提取，完全排除 v11new。v16复用相同143个ID的现有terminalfix产物：append129、rewrite11、already-terminate3；所选任务没有截短。r5保持原版。
- 固定数据目录 `/gpfs/scrubbed/jy050706/sft/data/r5-v16save143-tf`：505轨迹、10,142行（r5 6,474 / v16 3,668，63.83% / 36.17%）；其中 v16 multi-app 37 条/1,128行。505条最后训练响应均为显式 terminate(success)。79,043图片引用、10,157独立图片全部通过PIL完整性检查，训练行与图像占位符数量一致。
- 规范臂名 `9b-full-r5+v16save143.tf`，由登记后的armname生成/检查。两组都从 `/gpfs/scrubbed/jy050706/sft/models/Qwen3.5-9B` 开始，**不是TMAX、不是旧SFT checkpoint续训**。full SFT（沿用默认冻结视觉塔/aligner），lr3e-6、3ep、global batch64、max_length81920、img10/fold1、preserve_thinking、ZeRO2 optimizer offload、SDPA且禁用cuDNN backend。159步/epoch，总477步；保存159/318/477。
- **Slurm 298925：2节点×4 H200，urgent，accum8**；**Slurm 298926：2节点×8 H200，urgent，accum4**。均为video账户/gpu-h200、24h时限、排除已标fail的g018。05:19 PT正式提交；05:21 PT两者PENDING/Priority，尚未开训，StartTime=Unknown。Slurm当前状态以实时查询为准，不把test-only返回的298923/298924当真实作业。
- 内存每节点800G/1600G；为满足内存对应CPU约束，排队作业原位调整为CPU总数64/128，TresPerTask cpu32/64，未更换作业号或GPU数量。Slurm内部显示的CPUs/Task仍为内存推导的27/54；step读取SLURM_CPUS_PER_TASK，整体分配CPU充足。
- 输出分别为 `$B/out/9b-full-r5+v16save143.tf/train20260917-2x4` 和 `.../train20260917-2x8`；日志 `$B/save143tf_2x4_298925.out` / `$B/save143tf_2x8_298926.out`。两份作业分别保存，不覆盖或恢复其他模型。
- 实验代码独立分支 `train/r5-v16save143-20260917`，worktree `/private/tmp/cua-r5-v16save143-20260917`，首次提交 `91f21a1420`，CPU修正 `339fd13d1e`。部署 `$B/deploy/r5-v16save143-tf-20260917`，所有部署文件SHA256核对一致；保留Slurm提交时的原始spooled脚本与资源更新记录。
- 本地可复核：[实验代码与固定名单](../sft/experiments/r5-v16save143-tf-20260917/selection.json)、[2×4脚本](../sft/experiments/r5-v16save143-tf-20260917/train-2x4.sbatch)、[2×8脚本](../sft/experiments/r5-v16save143-tf-20260917/train-2x8.sbatch)、[语料manifest](../reports/r5-v16save143-tf-20260917/corpus_manifest.json)、[队列快照](../reports/r5-v16save143-tf-20260917/queue_snapshot.json)。数据构建与launch preflight均通过；本次没有启动eval。

## 同轮跨机合并展示；20/10接续评测已排队（2026-09-17）

- 用户要求把当前TMAX run的Windows/workstation两张卡合为一组。已改目录展示层，按同一标准run ID、模型/checkpoint与推理设置合并，任务保留机器来源和原始链接；不同协议不混组。27项catalog/visual-signal测试通过；浏览器已实查一组显示14个已评分任务、11个满分、均分78.57%（当时快照），且从Windows任务可“上一题”切换到workstation任务。
- 当前10/1继续运行。用户另外授权同一新9B在此轮100题完成后，再跑20/fold10的同一Verified100。已保存`cua-eval/queued-tmax-20f10.json`及20/10 registry；当前线程自动检查`tmax-9b-20f10`每10分钟确认前序两机完整完成和控制进程退出，再调用标准eval脚本。仍3单GPU副本、6+3VM、相同采集与保留策略；20/10尚未启动。
- 本地catalog服务更新为PID10127，只重启网页目录服务，未重启评测/GPU。显示规则、导航和接续条件已写入TRAJECTORY_PIPELINE与EVAL_AUTOMATION。

## TMAX Verified100：用户最终确认继续10/1，对齐训练（2026-09-17）

- 用户明确指令：“对齐训练”“别改，继续跑”“继续跑10 fold1”。本轮继续原`image_max=10 / fold_size=1`计划；讨论中的20/10没有创建或启动eval，草稿registry已禁用。
- 再次读取Tillicum最终checkpoint的真实args：数据是两份`q38-Bhqs2t-r5nocapimg10-v11{100,500}/train_swift.jsonl`，共6474行；逐行统计最多10张图。训练配方记录为img10/fold1。旧a2的20/fold10属于历史推理设置，不能写成这次训练设置。
- 临时暂停前保存workstation11题、Windows2题，共13个最终得分；原始/已导出记录均保留。用原run `...20260917T111039Z-75ef6328f5ea` 的同一份冻结plan执行`resume`，不会重跑这13题或混入20/10得分。
- 恢复控制进程：workstation69181、Windows4605；仍67/33题分片、6+3VM、3个单GPU9B副本。两机已写USER_RESUME.json，旧暂停标记已归档，推理服务没有重启。以`cua-eval/active-tmax-verified100.json`及实时status为当前入口。

## TMAX Verified100：3个单GPU副本，workstation 6VM + Windows 3VM（2026-09-17）

- 用户最新配置：3个独立9B副本，每副本1张L40S、TP1、最多3路请求；共9VM。三个服务已通过模型身份/context/采集接口检查：40252618/g3100:8054、40252621/g3104:8055、40252622/g3108:8056。第三个作业在Krishna组触及内存配额，原位转到用户已有`gpu-l40s-cse`账户后运行，权重与服务参数不变。
- 唯一权重目录：`/gscratch/cse/jy050706/sft/serving/tmax9b-full-r5-ml65k--train20260915--s306/model`。同一份已校验权重由3个服务读取，没有复制三份。
- 当前run：`tmax9b-full-r5-ml65k--train20260915--s306--verified--verified100-n100--20260917T111039Z-75ef6328f5ea`。标准脚本冻结分配workstation67题/6VM、Windows33题/3VM，不重叠；每GPU固定接2个workstation VM和1个Windows VM。控制进程分别64226、1853；启动后已观察到workstation6个容器，Windows控制进程进入running/3个任务初始化。控制进程启动不代表100题完成。
- 实际入口：Mac `cua-eval/registry.tmax9b-s306-3gpu.json`；plan在`cua-eval/runs/<上述run>/plan.json`；汇总回执`cua-eval/active-tmax-verified100.json`。协议为Verified冻结100、img10/fold1、thinking+preserve、50步、temperature1/top_p0.95。逐题自动轨迹导出，`delete-after-export`；原OSWorld2暂停任务未恢复。
- 用户调整配置前的6VM/TP2 run `...20260917T105121Z-496e93584538`已停止，无最终分数，原始中间记录保留。先前两个TP2服务40252268、40252377已确认取消，不与现在3个副本同时占卡。
- 实跑修复已进入通用准备脚本：FlashInfer默认HOME缓存可能落GPFS，显式改为节点本地FlashInfer/Triton缓存；新collector的artifact路由首次chat入口才注册，就绪检查用未注册模型的404请求激活路由，不生成模型token。新增独立副本参数，12项准备脚本离线测试通过。
- Windows恢复使用已有计划任务`CUA-Docker-Recovery-20260916`启动Docker Desktop，让其独立于SSH会话；Ubuntu用户会话和Docker API已恢复。Windows NTFS venv的CLI导入超过30秒但能正常结束，通用runner把CLI预检上限改为120秒、对应RPC为180秒（仍有界）。两台runner SHA均为`482f5f86652df316784b3de76db586606608ac55dd127afa22203288a8413ca7`，10项eval/routing测试通过。
- 后续实查两机均有真实rollout：workstation6个、Windows3个容器。抽样首步completion token与attention/诊断行数分别189/189、149/149、144/144、161/161、253/253、130/130，capture_errors为空。首批已取得1.0和0两种原始最终分数，不据此推断整批成功率。
- 首题自动导出key`4f9dad31d1eca0bff47878e42c417fb8`：validation passed，2决策/2动作/3张图片；完成验证后按策略清理WSL原始attention，截图与渲染结果保留。通过统一catalog实测HTML/信号JSON/1920×1080截图HTTP200，heatmap Range返回206且PNG签名正确。两机viewer和历史500题viewer均恢复。详细验收见`reports/TMAX_VERIFIED100_LAUNCH_20260917.validation.json`。
- 本轮启动验收末次快照：workstation完成6题、运行6题；Windows完成1题、运行3题，共7/100完成、9题运行。此为当时快照，后续用active plan查询。成功样例`030eeff7-b492-4218-b312-701ec99ee0cc`已自动导出为`task-fe07d75b684119ec97a0cb8950a34a13.html`，原始分数1.0。

## TMAX SFT 9B Verified100：已授权，准备模型服务（2026-09-17）

- 用户要求启动新 SFT 9B 的 OSWorld Verified eval100，按本会话 TMAX r5 step306 主臂准备。原 OSWorld2 teacher 评测仍保持暂停。
- 已实查 workstation 在线、Docker 无运行容器、无 eval 进程，可用内存约53GiB；Verified 固定100题的 manifest/hash、harness commit和受管文件hash一致，VM镜像存在，native CLI检查通过。
- 用户随后明确指定 **workstation 6VM**，相应9B服务准备配置改为6路并发。旧 Windows 在线，但 WSL Docker CLI未就绪，不纳入本轮。
- 用户分别恢复Mac→Tillicum及Tillicum→Klone的SSH master。现查训练297872为COMPLETED/0:0；`v2-20260916-193137/checkpoint-306`的trainer_state为step306/epoch3，权重分片检查通过。准确路径：`/gpfs/scrubbed/jy050706/sft/out/tmax9b-full-r5-ml65k/v2-20260916-193137/checkpoint-306`。
- 用标准`prepare_model.py`准备直传17个推理/元数据文件，共18,849,985,627 bytes；目标为Klone `sft/serving/tmax9b-full-r5-ml65k--train20260915--s306/`。用户改为6VM时尚无job，停止原准备进程、保留已传权重并记录2→6配置变更后恢复标准准备。服务请求2L40S/TP2/24h，全输出token采集，层号由9B模型自身配置解析。
- 独立registry：`/Users/knight/uw/computeragent/cua-eval/registry.tmax9b-s306.json`，在新服务就绪前保持禁用；配置/预检记录在同目录`deployments/tmax9b-full-r5-ml65k--train20260915--s306/`。源端脚本及配置已部署到Tillicum `sft/deploy/verified100-tmax9b-s306-20260917/`并核对hash。当前继续传输校验/服务准备，尚未启动Verified100；后续按真实job/endpoint更新。

## 当前：按用户要求暂停 OSWorld2（2026-09-16 20:21 PDT）

- 用户明确要求“把现在跑的停一下，太慢了”。不要自动续跑。
- Workstation r2 的 runner 58584 及其进程组、monitor 58586、postprocessor 60275 已停止；复查无 eval/monitor 进程，Docker 查询成功且无运行容器。
- 旧 Windows 没有 eval 进程；该标准 run 标签下的两台遗留 VM `e37ed80b29c3`、`26af8d821a2a` 已 stop，未删除容器数据。
- 两个 teacher 8100/g3104 与 8102/g3122 的实时 metrics 均为 running=0、waiting=0。模型服务及其 Slurm 资源暂时保留，未停止其它训练任务。
- 结果与轨迹保留：r2 已完成014=0.90、019=0.00，其余中断记录不伪造最终得分。未切换既有运行的 keep 策略、未清理原始研究数据。
- Workstation r2 目录及两机 remaining-20260916 写入 USER_PAUSE.json；旧 Windows 标准 run 也写入暂停标记。后续只整理脚本，启动评测需要用户新的明确指令。

## 简化脚本已就绪，评测保持暂停（2026-09-16 20:32 PDT）

- 按用户要求采用静态按题分配：`run_eval.py teachers` 列表，plan 中冻结 teacher 分组和并发份额，无共享租约、调度服务或生成探测。两台机器的工具代码已同步，但没有启动新评测。
- 两 teacher 都具备采集能力时，2+6 VM 对应 Windows 1+1、workstation 3+3；100题测试分配50/50。一方不可用时降低并发，不挤满另一方。
- 现查 g3104 普通服务可访问但无采集接口；g3122 采集服务 ready、0 running/0 waiting。当前不能把 g3104 当成具备完整采集能力的服务使用。
- 后续新 plan 默认 delete-after-export，keep 开关保留；旧 plan/配置保留原策略。清理额外覆盖已证实重复的 HTTP response JSON 和网页未引用的 recording.mp4；未动这轮原始数据。
- 全套70项检查，65通过、5平台/依赖跳过。验证记录：`reports/SIMPLE_EVAL_ROUTING_20260916.validation.json`。

## 标准化eval脚本与旧Windows恢复（2026-09-16）

- 已实现 `sft/scripts/eval/run_eval.py`：注册模型ID绑定固定checkpoint；自动唯一run ID；冻结bench/task panel/protocol与SHA；两机按VM配额分片；单task原生进程隔离；最多2次无分数重试；0分视为已完成；status/resume与轨迹pipeline复用。
- 当前部署registry：`/Users/knight/uw/computeragent/cua-eval/registry.json`。模型登记27b-base，bench支持Verified固定100与OSWorld2官方108；任务036/037仍按用户决定阻塞。8题分2/6，100道可运行题分25/75；不静默迁移离线机器的任务。
- Docker远程restart后进程没有保持运行，已通过当前Windows登录用户的单次计划任务 `CUA-Docker-Recovery-20260916` 在桌面Session1启动Docker；Ubuntu socket恢复。任务020/024旧容器的开始时间及端口与旧runner日志逐项匹配后才进行恢复。
- 新脚本已实际启动旧Windows剩余21题，controller PID1523、2VM槽位，首批020/024运行、19题排队；实际024已推进到step5，最新90输出token/90 attention/90 entropy、capture_errors为空。保留旧003/005/012/016四个得分及所有中断轨迹。新run ID：`27b-base--osworld2--remaining-windows-n21--20260916T223649Z-5cd2415b94cb`；计划：`/Users/knight/uw/computeragent/cua-eval/runs/27b-base--osworld2--remaining-windows-n21--20260916T223649Z-5cd2415b94cb/plan.json`。
- Workstation已有6VM的r2批次继续运行，没有为了部署而重启。新的单task隔离适用于新脚本启动的运行；旧r2仍保留旧runner整批异常策略，不能宣称已经热修复。
- 新流程6项测试加既有capture/viewer/catalog检查共42项通过；两个实际bench的commit、panel hash均核对。Verified的workstation CLI参数检查通过；旧Windows在正在跑任务时一次--help导入超过30秒，doctor同时正确报告机器占用，未发起Verified VM评测。真实OSWorld2已通过新脚本启动；尚未宣称21题完成。
- 使用与填写示例见 [EVAL_AUTOMATION.md](../sft/docs/EVAL_AUTOMATION.md)。脚本检查已经注册的模型服务，不自动另申请Slurm模型服务；不循环SSH认证、不全局删除Docker容器。


## Teacher状态核查（2026-09-16 14:41 PDT）

- Workstation r2 runner58584及postprocessor54605仍活跃，6个VM运行；013/014/015/017/018/019约18–38个模型步骤，最新attention/entropy与输出token数量匹配，capture_errors为空，14:40仍有模型HTTP200及实际动作。
- 旧Windows原runner4005和postprocessor4003已不存活；日志14:27:35出现主进程/worker的SIGTERM。WSL Docker socket不存在，docker命令提示WSL integration不可用。Windows侧Docker Desktop进程仍在，WSL boot ID与原记录相同，不能据此断言整机重启或teacher崩溃；终止信号来源未确定。
- 旧Windows本轮003/005/012/016已有最终score（均0）；020/024中断。本次未擅自重启Docker或重开评测，已询问用户是否有环境调整以避免冲突。
- Tillicum已认证socket此次不存在；未循环登录，本次未取得297872的实时训练状态。

## 正式目录展示规则（2026-09-16）

按用户要求，正式目录只展示已有最终分数的任务，0分也保留；未评分任务及空分组隐藏，原始轨迹不删除。浏览器核对OSWorld2仅剩5+3=8题，加历史500题共508题。测试区保留调试记录；后续结果由pipeline自动加入，前后任务导航也遵循相同规则。

## Teacher eval 运行恢复（2026-09-16 13:20 PDT核查）

- 13:22目录检查：Mac各来源转发已断，catalog读取02:26的缓存，导致仅见旧6题。已一次性建立独立SSH `-N` loopback转发（不挂靠短时ControlMaster、不自动循环重连）；HTTP与浏览器核对三组OSWorld2共15条轨迹：pilot6（5评分）、Windows3（3评分）、workstation中断6（0评分）。加历史500条，正式页515个已导出任务；不是515道已完成评测。界面补充“已评分/未评分”和离线缓存最后同步时间。

- Teacher **40207395 / g3122**持续RUNNING，chat/completions和attention文件下载返回200。
- 旧Windows两VM继续运行，本轮003/005/012已有最终score（均0.0）；016、020继续推进，抽查最新输出token/attention/entropy数量对应，capture_errors为空。
- Workstation任务014在04:52连续3次截图HTTP读超时（每次10秒），controller返回None，`lib_run_single.py:948`写截图抛TypeError；04:53原生runner停止整批，清理到05:33。其它5题被连带中断，本批未产出最终score；不是把它们记为0分。VM截图接口超时的底层原因尚未确定。
- 已按原72题清单、原协议和6VM配置重启至新目录 `qwen38-think-i10f1-alltokens-remaining-20260916-workstation-r2`；runner **58584**，复用postprocessor54605。新profile `~/cua-v2-pilot-20260915/remaining-20260916/host-r2.json`。旧run增加INTERRUPTION.json，全部原轨迹保留；未改benchmark评分/截图重试逻辑，未动仍运行的旧Windows。

## TMAX 最后34步续训（2026-09-16 13:14 PDT）

- 作业297496于10:03触及8h时限，Slurm状态TIMEOUT；最后日志284、进度条285/306。没有完整checkpoint-285/306，最近完整保存点为v1的**checkpoint-272**。
- 已检查checkpoint-272的trainer_state、全部safetensors分片边界/索引、四组optimizer/RNG与scheduler。用户授权继续，已提交 **297872**：1节点4H200、800G RAM、32CPU、**3h**，完整恢复到总306步，保留原训练配方。
- 提交后状态PENDING/Priority，预计开训时间暂无。剩34步按上一轮156.7秒/步约89分钟，另加排队、模型/优化器加载和最后保存时间。
- 提交记录：`/gpfs/scrubbed/jy050706/sft/deploy/tmax9b-r5-resume-20260916/finish-job.json`；日志：`tmax9b_r5_297872.out`。旧checkpoint和两轮训练输出均保留。

## 2026-09-16：恢复 teacher eval 与 TMAX SFT（执行中）

- 用户已授权将 OSWorld2 剩余teacher评测继续跑完，覆盖此前暂停范围。两台WSL已重新核对同一shared commit `d552441917f302fab410a1991cc705d7bf585d14`，保持thinking=True、preserve=False、10图/fold1、100步、全输出token L63/H0采集。
- 已保留9道完成结果：001/002/004/006来自早期131K服务，007–011来自262K全token批次；上下文/采集协议差异保留。012截图接口异常，无score，保留原目录后新attempt重跑。036/037代理凭证仍是占位符，单列阻塞，不当0分。
- **02:09已启动**：旧Windows runner4005、postprocessor4003；workstation runner56500，复用后处理54605。实际2+6容器运行，Windows003的298个输出token与298行attention/entropy对应，workstation015为120/120，采集错误为空。两机每题完成后进入固定正式catalog。
- 剩余可运行97题：旧Windows **25题 / 2 VM**，workstation **72题 / 6 VM**，互不重叠；冻结清单见 [JSON](../reports/OSWORLD_V2_REMAINING_20260916.json)。原先8题限制已被本次用户续跑指令更新。
- 旧采集服务40190392仅剩至09-16 17:12；Slurm拒绝原位延长。已提交同配置的长时采集服务 **40207395 / g3122 / 2×L40S / 6天 / port8049**，已加载并切到固定8102入口；首个真实采集核对通过后，旧短时采集服务40190392已释放。原未采集服务40178215未改动。
- TMAX原训练 **296948** 于01:03在step136保存附近发生Slurm主机内存OOM，MaxRSS419361900K触及400G。最近完整checkpoint为102（四组optimizer/RNG、scheduler、四个模型分片均在）。
- 续训 **297496** 已获g017的4张H200，**800G主机内存 / 32CPU / 8h**，恢复checkpoint-102到总306步，保持r5/gb64/lr3e-6/max_length65536；已验证续到**104/306**、lr2.51e-6，原/新训练args关键配方无差异，两份数据SHA匹配。W&B新run为`6k8109qq`。297495因Slurm按RAM自动抬CPU产生环境变量冲突，在训练启动前退出，已修正并保留记录。
- 用户要求不递归/循环登录：使用已认证ControlMaster；目录配置已移除自动SSH重连。旧Windows重启丢失的peer MSS900路由已按既有方案恢复，大HTTP响应0.12秒；没有修改全局防火墙或SSH认证方式。

## TMAX-9B → r5 CUA SFT（2026-09-15，已提交）

- 用户最终配置：**4张H200、最多2节点、无需冒烟直接正式训练**。实际提交1节点×4卡，global batch64=4×1×accum16。
- **Slurm 296948** / Tillicum / account video / gpu-h200 / normal / **8h**；2026-09-15 19:25按用户要求原位缩短时限，作业号和19:18的提交时间保留。调度预测会动态变化。
- 规范臂 `tmax9b-full-r5-ml65k`；r5 6474样本，lr3e-6、3ep、306steps、max_length65536，与读取到的原a2参数对齐。
- 原始TMAX已下载到Tillicum；已装配427个TMAX语言张量 + 333个原始视觉张量 + 15个兼容MTP张量，视觉/merger冻结，MTP不启用。
- 详见[实验计划](../sft/plans/PLAN-20260915-tmax9b-r5-cua-sft.md)；日志 `/gpfs/scrubbed/jy050706/sft/tmax9b_r5_296948.out`，输出 `out/tmax9b-full-r5-ml65k/`。

## OSWorld-V2 全 token 采集：8 题 pilot（2026-09-15，workstation 已启动）

历史记录：当时仅授权先测试 **8题，旧Windows2 VM + workstation6 VM**。**2026-09-16用户已授权继续剩余评测，当前任务范围见顶部恢复记录。**协议沿用 shared commit `d552441917f302fab410a1991cc705d7bf585d14`，teacher Qwen3.8-27B BF16 TP2、thinking=True、preserve=False、image10/fold1、history100、max_steps100、max_tokens81920。

- 独立采集服务：Klone job `40190392` / `g3112` / 2×L40S / 262144 context；此前 `40178215` / `g3104` 保留。
- 全部输出 token 采集 decoder layer63/head0，权重无损 float32 压缩保存，JSON 只存索引；独立 worker 在每题结束后生成原始轨迹、图片、单 token / 整体热力图及评测证据。
- 两机各自 `~/cua-v2-pilot-20260915/` 保存工具、配置、测试记录与结果；loopback SSH port8102 连接采集 teacher。旧 Windows 003/005；workstation 007–012。
- **17:36 后 workstation 已启动 6 VM，007–012**；runner 54604、独立后处理 54605、viewer 54606、monitor 54607。真实预检 768/768 个 thinking token 的 attention/熵与下载校验通过。旧 Windows 自17:30起 Tailscale/SSH 不可达，003/005尚未启动；用户最新要求先运行 workstation。
- 首批结果：011原始score=0.0且采集校验通过；012截图接口超时后异常退出，无最终score，页面明确标记缺失截图/轨迹不完整；其他4题继续运行。私有试跑入口 `http://127.0.0.1:8796/index.html`，Mac通过workstation原生SSH入口连接。详情见 [visual-signal plan](../sft/plans/PLAN-20260914-visual-signal-monitoring.md#all-output-token-storage-and-eight-task-pilot-2026-09-15)。

## OSWorld-V2 共享版本重跑（2026-09-15，当前入口）

> **最新状态（2026-09-15）**：用户要求暂停 OSWorld2，等待另一个 agent 实现采集功能。两台 runner、worker、VM、本地 monitor 均已停止，Codex heartbeat当时设为PAUSED；该暂停随后由2026-09-16用户明确续跑指令更新。4个已完成结果与所有中断轨迹保留，102题待后续恢复，036/037仍代理阻塞。Teacher已扩到262144，作业40178215保留供功能测试。

- **已暂停：workstation原4 VM + 另一台Windows原2 VM**。262K恢复批次尚无新结果；最新结果目录以两机汇总JSON为准。
- **统一代码**：[DengDuangLang111/OSWorld-V2](https://github.com/DengDuangLang111/OSWorld-V2/tree/qwen38-v2)，分支 `qwen38-v2`，固定commit `d552441917f302fab410a1991cc705d7bf585d14`。两台均从GitHub完整clone并初始化server子模块；实际agent SHA256相同。
- **实际目录**：workstation `/home/yanji/research/OSWorld-V2-shared`；另一台 `/home/daniel_yan/research/OSWorld-V2-shared`。本机维护副本为项目同级 `OSWorld-V2-personal/`。不要继续从旧 `OSWorld-V2-0808` 手工副本发新任务。
- **协议**：thinking=True，preserve=False，10图/fold1，history_n100，max_steps100，max_tokens81920，temperature1.0/top_p0.95。只把失败判定、非ASCII、call_user及相应提示词恢复官方，其余已审计适配保留。正式参数与启动器在fork的 `local_eval/`。
- **资源**：Klone `40178215` / `g3104` / 2×L40S / Qwen3.8-27B BF16 TP2；到期2026-09-22 05:01:47 PDT。模型262144上下文；600秒HTTP超时提供长推理余量。
- **环境已核验**：Python3.12.3、全部221个包版本、WSL内核、Docker镜像ID、完整qcow2 SHA256均一致。官方108个任务逐字节匹配；数据、镜像、key、.env、轨迹均未上传GitHub。
- **网络根因/修复**：旧WSL到userspace-Tailscale relay的大响应路径存在MSS相关问题，小health/models会假绿。默认连接读251KB openapi超时；单连接MSS900立即成功。已只添加目标 `100.72.191.125/32 via 172.20.128.1 dev eth0 advmss900`；修后三次普通连接均约0.11秒。重启WSL后路由可能丢失，需重新确认gateway/interface。
- **Monitor（已暂停）**：各结果目录保留launch.json/runner.log/monitor-status.json/monitor-history.jsonl和USER_PAUSE.json；本地主机monitor已停止，Codex heartbeat `osworld-v2-windows` 已设PAUSED。进程身份使用boot ID + start ticks，避免WSL校时造成墙钟启动时间误判。
- **合并结果唯一入口**：[共享版本两机汇总](../reports/OSWORLD_V2_THINK_SHARED_20260915.md) / [JSON](../reports/OSWORLD_V2_THINK_SHARED_20260915.json)。分母保留108，区分完成/待完成/代理阻塞；最终分数尚不可用。每题页面输出在各机 `~/cua-v2-shared-trajectories-20260915/`。09-15首次新任务004完成后，页面与原始PNG均已通过实际viewer HTTP handler验证（200）；后续覆盖继续由monitor检查。
- **审计依据**：[原始harness diff](../reports/OSWORLD_V2_HARNESS_DIFF_20260915.md)、[三项官方行为恢复patch](../reports/OSWORLD_V2_THREE_OFFICIAL_REVERTS_20260915.patch)、[think历史/Verified对齐实测](../reports/OSWORLD_V2_THINK_HISTORY_20260915.md)。不要把“任务一致”或“think历史对齐”写成全部harness原版。

## 现状(2026-09-09,过时即改;历史快照看 git log,上一版现状块见 `git show 85ae979cb6:docs/EXPERIMENTS.md`)

> **训练**:无在训臂。待投 `9b-full-mixb.sw`(mixB-9b-swemem,SWE-MeM 轨迹内均衡权重,sbatch 已入库)。
> `4b-full-mixbtf-imgtok4096`(cap2x)四连 OOM 未成,退档为 `4b-full-mixbtf-ml65k-imgtok3072`(cap1p5,已评)。
> **eval(全部收官,WSL eval100 @10/1)**:mixbtf lr 阶梯 1e-6 / 3e-6 / 1e-5 = 52.0 / **60.0** / 49.0(倒 U);
> taskw 55.0(负);histcomp 60.0 持平且视觉 token −55%(正);cap1p5 50.0 ≈ 4B 原生(无效)。RESULTS §5.35–§5.39,总表 §12。
> **OSWorld-V2 教师 eval**:停在 39/108。根因已定位 —— runner 把教师隧道写进 `OPENAI_BASE_URL`,judge/user-sim 的
> base_url fallback 继承了它,~26 个 LLM 评测任务每 pass 必崩;修复 = `.env` 加 `OSWORLD_EVAL_MODEL_BASE_URL` 与
> `OSWORLD_USER_SIM_BASE_URL`(待批);036/037 代理凭证是占位符(待定)。教师 serve 已过 walltime,续跑要重过 Duo + 重起教师。
> **基础设施**:osworld-windows(WSL)09-09 不可达;WSL→Klone master socket 已失效。
> **整编(分支 `reorg-20260909`)**:命名规范 `docs/NAMING.md` + 生成器 `sft/armname.py`(21 个活 sbatch 回归全过);
> 归档 `outdated/plans` · `sft/scripts/archive` · `sft/scripts/train/archive`;`control/` 合并;RESULTS §5.30–5.34 归位、新增 §12 全臂总表。
> **等用户定**:V2 续跑与否;swemem 投训;分支合并。

- **严格语料线出厂 + 训练臂 mixaw9b(09-01 晚,全链 `outdated/plans/PLAN-20260901-strict-corpus.md` §8-10)**:
  judge 全量 1375 → `curate16 --strict` 340(24.7%;含规则闸复核捞回 5)→ 与 r5 系 v11 362 条合成
  702 轨迹 → **v16 半区补做终止规范化**(末步显式 terminate 3.7% → 100%;首建时漏传
  `--terminal-rewrite`,`verify` 未带 `--require-terminate` 假绿)→ WebSTAR 步级过滤
  (luna 单 pass,13199 步 → **keep 7311 / drop 5893**,55.4%;末步 687/687 全 keep)→
  `mixa-webstar-v16strict` 7311 行,图片 58003 引用 0 未解析 → **Slurm 271889**
  (9B / lr 3e-6 / 3ep / gb64 / save_steps 115 = 三个 epoch 终点)。首投 271875 死于
  `gen_meta` 混合语料 Arrow schema 冲突(DATA_PIPELINE §7b),`pop('gen_meta')` 后重投。
  **读法**:相对 r5 原样,轨迹 +90% 但样本只 +13%(新增量被过滤吃掉),且 r5 半区
  自己也被砍 44% —— **与 a2 不可直接归因**,拆变量要加"只过滤 r5 不加 v16"臂(IDEAS)。
  三条已披露代价:687 个重写末步未经判官;`score>5` 未在本语料标定(opus 比 luna 松 19pp);
  decide_steps 的打分后 sha256 校验按用户令删除。
- **动作普查:v16 成功轨迹 vs v11 成功轨迹(08-30 夜,用户令"看下动作区别")**:
  ⚠**先修一个计数错误(本轮我自己犯的):`traj.jsonl` 一行 = 一个 pyautogui 动作,
  不是一步;步是 `step_num` 字段。** 按行数数会把"50 步打出 142 个动作"报成 142 步,
  更会把同一步多行共享的那段 `response` 重复计入 token(全体 38,812 步里 2,405 步
  是"多行同 response")。**50 步上限一直生效,1284 条轨迹无一超过 50。**
  多动作合并的 harness 魔改在工作:每步平均动作数 v11 1.11 → v16 1.17。
  · **原语分布几乎不变**(click 35% / typewrite 21% / press 17% / hotkey 7%,两代同)
  ——这层本来就不该变,harness 原语层分不出写诗和写代码。**真实差异在工作量**:
  中位模型步数 15 → 23;按应用数拆开 **v11 是 14/15/20 步,v16 是 16/25/33 步**
  ——v11 的 d1→d2 只多 1 步,这是"假难度"在行为侧的直接证据,比通过率证据更硬;
  v16 每加一个应用 +8~9 步。撞 50 步上限:2.4% → 5.6%(d3 档 14%)。
  · 用模型自己的分词器实测(vLLM `/tokenize`,`qwen38-27b-local`):每步输出 token
  中位 144 → 150、think 63 → 68、think 占输出 63.4% → 63.7%——**单步思考习惯完全没变**,
  轨迹变长全部来自步数。整条轨迹输出 token 中位 3,233 → 5,410。
  · "动作与前面某步完全相同"的比率 18.3% → 22.2%,**该口径经用户看片后作废**:
  它把模型试错(点错退回、输入框未聚焦重点一次、等加载连按)算成了空转,
  而这恰是训练该学的恢复能力。作为佐证,动作数最多的 6 条判官分 7/8/8/8/9/9
  (中位 8 = 全体成功轨迹中位),要求项 100% 做到,扣分扣在绕路不在没做完。
  回看页(6 条 227 步全帧)`scratchpad/v16/long6_viewer.html`。
- **判官进度与分数分布(08-30 19:00,rollout 仍在回传)**:回传 1361 / 1386,
  已判去重 1345 条——**success 52.1% / failure 44.2% / unclear 3.7%**,
  按收录规则(通过 且 全部要求项做到)**544 条 = 40.4%**。0-10 分呈**双峰**:
  0-3 分 35.6%(其中 0 分 12.3%,开局即废)、4-6 分仅 13.8%、7-9 分 49.3%、
  10 分 1.5%。中间档空说明判官在做二分判断而非和稀泥,也说明任务边界清楚。

- **语料收录规则定稿 + 判官两处修正(08-31 晚)**:
  ①**收录规则(用户裁定)**:判定 success **且判官列出的每一条要求都做到**
  (`done` ∈ yes/satisfied/mostly_satisfied)。**不看关键性**——`critical` 是又一个
  判官凭语感设的无定义布尔字段(87% 的项都被标关键),且实测有一条题面明写的要求被标成
  非关键放行;旁路它代价 14%(249→215)。**不看证据质量**——22% 的要求项是 `inferred`
  ("按了 Ctrl+S 没拍到确认"),要求 `seen` 会把收录率从 49.7% 砍到 29.5%,那是惩罚
  判官看不见而非提纯,等 J2 上线再收紧。实现 `sft/curate16.py`。
  ②**筛选器时间修正**:修复批沿用原任务 id,按 id 排除缺陷会把修好的任务连旧的一起扔
  (58 条好轨迹);改为按时间——轨迹完成早于任务文件被改写才排除(实测 119 条缺陷任务
  全部跑在修复之后,零误判)。
  ③**最终答复的两种读法**(见 JUDGING §2b):关掉自述导致信息类任务系统性被判"证据不足",
  根因是 2×2 对照的考卷以文件任务为主、看不见"答复即产物"这类。已重判 75 条。
  ④判官返回"有判定无要求清单"改为重试而非接受(此前浪费 25 条)。
  **实测成绩(已判 656 条)**:成功率 54%;难度梯度 d1 64% / d2 55% / d3 32%——每加一个
  应用掉约 15 个百分点,难度轴证明有效。thunderbird 18% 是唯一重灾区(邮件产物在 profile
  里、判官在像素上看不见),J2 靶心之一。修复版 impress 回到 67%,高于全体平均。
- **判官侧三项定稿(08-31)**:①**证据袋最省配置**——2×2 对照(全帧/末8帧 × 给/不给
  agent 自述)四格纯度 74-76%、差异在噪声内,另一组三臂(完整思考/400字/不给)同样无差异,
  故生产取"末尾 8 帧+全动作,不给思考不给自述",图片量降到四分之一。**双判官制因此废止**:
  错放是系统性盲区(四种配置在同一批硬负样本上一起栽),冗余无效只翻倍成本。
  ②**要求项 schema 拆轴**(a259d406):旧六值枚举把"做到没"和"看清没"混在一起,实测 175 个
  `mostly_satisfied` 多为"按了 Ctrl+S 没拍到确认",而"必须全 satisfied"的语料规则会因此
  砍掉 59% 合格轨迹;拆成 `done`(yes/partial/no/cannot_tell)+`evidence`(seen/inferred),
  同考卷复判一致率 94%、错放错杀完全不变(说明只换表示不改判别力)。
  ③**J2 磁盘证据**:基线差集定位产物(见 JUDGING §2c),已实现待下轮 rollout 启用。
- **祖传断言清算(08-31)**:提示词里所有环境事实断言逐条实测(e0556c36)——csv→xlsx/ods、
  txt→odt/docx、pptx→odp 五条全过并写成带日期的清单;此前唯一没测过就写进祈使句的
  `odp:impress8` 造成 165 条假演示稿。**规矩:未验证的断言不许进祈使句和门闸。**
- **v16 语料交付 AWS(08-31)**:生成 1560 → 门闸 −111 → 跨批重名 −36 → 装箱冒烟
  −27 → **交付 1386 条**(先导 `v16-pilot-200` 191 条 + 全量 `v16-main-1` 1195 条,
  零重叠;与官方 369 撞题 0、内部近重复 0)。装箱三方完整性验收通过(manifest 键
  ==目录、悬空 0、未登记 0、id 唯一)。域分布 multi_apps 790 为最大域。
  **装箱链两个误杀已修**(e41e5fff):①构建容器是精简 ubuntu 无 gsettings,而真 VM
  有——18/44 条系统设置类任务差点被误杀,改判"容器无法验证"放行(13 条,待真机复核);
  ②prebuild 遇 0 字节 fixture 会写出坏 setup(`base64 -d` 找不到文件),改用 `: >`
  预建空文件。**open_path 存在性闸**(peer 实测 v14 有 10 条确定性死法:setup 写
  docx 而 open 要 odt / open 指向待产出物 / setup 空转)已加,用经验法(容器跑完
  `test -s`)而非静态正则——静态法在 v16 实测误报 60.6%(setup 先写 csv 再 soffice
  转 xlsx,目标文件名不出现在命令文本里)。
  AWS 侧(peer):4×4GPU Tillicum serve + nginx 反代(least_conn,body 256m/read
  900s/buffering off)+ 48 VM 就绪;VM 不直连模型,harness 集中调用;snapshot 字段
  惰性、无域白名单,multi_apps 开箱即用。
- **v16 生产批次点火(08-31 用户令)**:1560 条,种子 1661/1662(分布已空跑
  锁定:应用参与对齐官方 ±1.5、d2 含 os 58%/d3 51%、warm 38/43/15/4、os 工种
  45/44/10、19 意图族均匀 41-42)。定稿轴:无动作种子(退役,池留 git)、无
  infeasible、os 主应用 6%(三约束联立解,恰=官方纯 os 域 6.5%)、主/副应用
  分配由 gen16 全接管(旧绑定弃用)。装箱链就绪(emit16:合并→撞题(官方+
  CUA-Gym)→prebuild→容器冒烟→官方格式 JSON,83e64d91)。rollout 定 AWS;
  判官双审制;动作多样性终审=rollout 后轨迹动作普查。
- **仲裁终局(08-30 深夜,66 条判官翻案全过堂)**:checker 冤案(过严)46 /
  **判官被骗 16** / 存疑 2 / 调用失败 2 → **真错放率 16/138≈11.6%,落 5-15%
  档,双判官一致才收由数据定案**。判官被骗的模式高度集中:轻信 agent 自述
  (自报的终端 dump/文件名/现编算术)、漏读环境里的 policy.txt、把文本文档当
  演示文稿。46 条冤案=可过对抗辩护后赎回的合格轨迹。我的手工逐条预判 ~23-25
  错放,仲裁 16——方向对、偏严。
- **生成轴大改(08-30 深夜,用户令)**:①意图轴换 **19 族**(用户自制全谱裁剪:
  获取/理解/消费/创建/**创意制作**/转换/沟通起草/审阅批注/组织/规划/分析决策/
  执行流程/办理事务/自动化/维护/排错恢复/安全隐私/自我表达/**照章执行**;
  交易/远控/监控/远程协作四族无法在 VM 落地,弃;族名+动词串进牌面,示例永不
  进 prompt);②**infeasible 轴整个移除**(用户令);③"不可能要求"硬禁令
  (缺硬件+纯音频信息不可用——模型没耳朵);④两条铁律(a1-2 参数写死/只许
  引用 setup 真造的东西);⑤产出要求规则 9 已被 100v100 对照击毙(示例引力
  第三案:13/15 calc 题铸成"锁头+标红"),量产 prompt=自由版;⑥人设轴议而未用。
  规则 9 之死与 19 族设计源自 AUTO PLAY(ICLR26,四大类+环境锚定)与
  AgentSynth(ICLR26,人设+链式拼装)对读,详 docs/READING.md 待补。
- **v16 强判官试验开工(08-30 用户令,分支 datagenv16,承 OpenWebRL 架构)**:
  方向 = 判分从"生成时造判据"移到"跑完之后判录像",生成端解绑以治动作窄化
  (270 条新教师轨迹实测:点击 37.6%+打字 19.2%,右键仅 0.5%,三步套路 92.9%
  重复,前 5 种占 31.7%)。`sft/strongjudge.py` 落码(39260295):规则闸拦自报
  FAIL → Opus5+思考、24 帧标号、末 3 步原文、二元判定+要求清单;首考 = 544 重刷
  里程序判 1 分的轨迹(在跑,146 条起判)。已知底数(sft/docs/JUDGING.md):省钱配置判官
  不够格(排序对率 .77,判败轨迹 63% 被打 8-10),强配置从未考过。**预注册录取
  线:对真败错放 ≤5% 全切判官制;5-15% 双判官一致;>15% 混合。** 倒转生成原型
  (revgen)挂起——判官制若立,其要解决的"题面-判据错配"整类消失。
  **pass 侧考试收官(08-30)**:146 条程序判 1 分轨迹盲判,136 有效判决——
  success 126(92.6%)/failure 6/unclear 4,**引用幻觉全场 0 次**;10 条分歧
  三类:①"值对但没见保存"×4(疑抽帧缝隙错杀,待全帧重判) ②判官抓到 checker
  没查的真毛病×3(残留乱字符/漏条款/漏文件类型) ③待仲裁×3。11 条调用故障
  (8 条请求体超大 400)已修(39deb036:补考+减帧重试)在补。fail 侧 131 条
  接着考,出错放率对录取线。
  **fail 侧考试收官(08-30,137/138)**:判官对程序判败轨迹翻案 65 条(47%)、
  维持 63(含规则闸拦 22 条自报 FAIL)、存疑 7。冤案与错放混杂,待仲裁拆分;
  **过渡决定:v16 新语料默认双判官一致才收**(pass 侧实锤单判官对"保存无证据"
  情形一次判成一次判败的手抖)。
  **v16 量产链开跑(08-30)**:发牌机单次上限 780 = 5意图×13领域×3难度×4歧义
  的格子积走满一遍(实测 cells(5000)=780,65 对×12);1500 条 = 双炉(seed
  1601/1602)同格不同章,跨炉查重在装箱兜底。gen16 量产版(a230ad3f:6 路并发+
  门闸回喂重写一轮+炉内查重+VM库禁令);**emit16 装箱器落码并冒烟通过**
  (8b4e133:合并查重→prebuild 宿主侧 soffice→官方字段任务 JSON;哑判据/真
  infeasible 判据双轨)。prompt 融合 v11 骨架(6d9f666c 系列:四档歧义+deictic
  +防漏招+warm start 回归,warm 升级为预开数量 K 均匀 0..GUI 数,open_paths
  支持裸应用名启动)。教训:/mnt/d 推码必清 __pycache__(stale .pyc 实锤一次)。
  枚举 vs 盖章:格子积只枚举 意图/领域/难度/歧义 四轴;长度(档内随机目标值)、
  腔调、应用、warm、动作种子、副应用是记账式抽签盖章,配额账本管比例。
  **rollout 定 AWS(用户令):装箱+冒烟齐活后交 AWS 20 并发,不占本地 3 VM。**
  **os 计数裁定(08-30 用户拍板)+gen16 落码(902648b5)**:os 家族算 1 个计数
  应用;组合抽签抄官方分布(d2 内 app+os:GUI≈6:4,d3 以 2GUI+os 为主 19:1);
  os 计数必干实活,搬运不算;词表=官方 9 词,main_app/other_apps 对齐官方
  related_apps。生成合同瘦身为【题面+初始化】两件,提示词只给骨架不给内容
  示例。8 条小样在跑。
- **v15 立项开工(08-30,用户批 A+B 全上;计划 `outdated/plans/PLAN-20260830-v15.md`)**:可验证
  空间扩容(官方判据复用 13/118→~39)+ 复合判据(**判据数=难度**:d1-2:1/d3:2/
  d4-5:2-3+跨应用)+ divcheck 常驻尺子。背景:image 族 4 函数塌缩、444 条 d≥3
  旅程不被判分(AWS 实测教师 21/21 照做未判分旅程→存量语料干净,修复面向下一轮)。
  分支 datagenv15;已落:官方 28 函数契约(0f832068)、divcheck 尺子(a7843921,
  验收=机械复现全部人工发现,载荷对撞 0=与官方测试集零暗合)。

- **图窗试点已收官(08-29 午,七臂全 50/50,全表+四轴裁决 → `sft/docs/RESULTS.md` §5.29)**:
  **i10 滑窗是甜点(81.8 vs 锚 69.8,+12pp)**,增益集中在 multi_apps/calc;
  5图 75.8、20滑 73.8(fold 本身≈噪声);**480 分辨率有毒且与少图恶性交互**
  (20图−6pp、10图−16pp,假DONE 27.5%)→ 教师生成侧除名;medium 思考 +10pp
  (但不是"想得少",是铺匀)。**rollout 锁 i10@2040,xhigh/medium 等 H 格
  (i10×medium,在跑)开奖**。旧的试点启动记录如下,存档:
- **图窗试点(08-28 深夜,rollout 前置闸,用户令)**:教师 27B 在冻结 eval-50
  跑三臂 —— `t38i10`(10 图滑窗)/`t38i20`(20 图滑窗,补 t38h20 空目录旧账)/
  `t38px480`(20 图滑窗 + `OSTG_MAX_PIXELS=491520` ≈480 视觉 token/张);锚点 =
  08-19 存档 t38(教师谱系配置 h100/20fold10/ms50/t1.0,**69.8%**)。每对只动
  一轴:锚-i20=fold,i20-i10=张数,i20-px480=分辨率。臂定义
  `sft/scripts/archive/run_eval50_stock.sh`,launcher `tools_pilot_fold.sh` 守着尾扫链自动
  点火,复用在跑的 eval38h20 serve;结果 dashboard eval-50 区实时可看。
  **08-29 深夜追加 E 臂 `t38med`**(用户令):锚点窗口(20fold10 默认)+
  `OSTG_REASONING_EFFORT=medium`(教师谱系全部是模板默认 xhigh)——对锚点
  隔离思考力度;接力器 `tools_pilot_fold2.sh` 排在 D 后,收官标记
  ALL-PILOT2-DONE。**出对照表 → 定 rollout 图窗+思考力度 → 再点 1796 全量。**
- **v14g(08-28)**:datagen 重构 A′–F 落码并实跑。pilot40 全环走通,四道 VM
  闸全绿(bake 36/40、负向 36/36、Tier-1 36/36、Tier-2 36/36),audit 裁定中;
  抓获并修复四个系统性缺陷(注入自杀 / ARG_MAX / **round-trip no-op** / pdf
  gate 误杀)+ 加权抽签的家族饿死(spent_fam 账本 + 可行前沿结论)。wave-2
  生成 1265 条入库 + 375 钉补差在跑(pdf/音视频机制已落,vlc/tbird 足额)。
  教师通过率按坐标实测:d1-3 62%/d4 42%/amb2 最难/跨应用递减,加权 ≈56%。
  执行记录 `outdated/plans/PLAN-20260828-v14g-gold.md` §8.5;口径 `reference/EVAL_FAMILY_TAXONOMY.md`。

- **两大口径更正(08-18,详 `sft/docs/RESULTS.md` §5.2 / §5.7)**:
  ① **keepthink 与 stock 两个评测模板逐字节等价** —— harness 把推理内联进
  `content`,keepthink 的分支永不触发;所有 `·keepthink` / `·stock` 臂吃到的是
  同一个 prompt。rich 28.0 vs 30.0 与 lean 23.8 vs 25.8 因此是**同配置重复**,
  给出配对噪声 sd≈2.8 题(5–6pp),**MDE80≈15–18pp:eval-50 看不见小于
  ~15pp 的差异**。keepthink 全线退役,以后一律 stock。
  ② **serve 的 checkpoint 挑选器按字典序取到 checkpoint-90**:Bs-LoRA 47.8%、
  Bs-gb64 45.8%、B-gb64o 41.8% 实为 **~1 epoch 权重**的分数;旧结论
  "1ep→3ep=+10 点"作废(两端都是 ~1ep)。已修:`pick_ckpt.sh`
  (endpoint / epoch:N / step:N,选择连判据一起打进日志)。
- **eval-50 最新(缺题按 0,全 50 题;完整表 → sft/docs/RESULTS.md §6)**:
  Bs-LoRA@e1.02 47.8% > Bs-gb64@e1.02 = Bs-LoRA@e3.00 45.8% >
  gb128ep2@e2.00 43.8% > gb64o@e1.01 = **r5-LoRA@e3.00 41.8%** > base 39.8%。
  旧数据里 epoch 与语料共线;新增的 Bs-LoRA e1.02 vs e3.00 配对差 −2.0 点
  (噪声内),**"训过头"在 LoRA 上未获支持**。
- **r5 四臂训毕;末步修复奏效,分数未动**:显式 terminate 6% → **60%(LoRA)/
  74%(全量 kD,跑动中)**,假 done 0/7;代价:失败没有出口,失败题全部磨到
  50 步上限(terminate 被绑定"成功",语料 0 条失败结尾)。机制与硬约束
  (FAIL 在普通题强制 0 分、词表兜底陷阱)→ sft/docs/RESULTS.md §5.8 / §5.9。
- **think 变双峰,cap 反效果(§5.10)**:微调后 p50 向教师收敛(419→~120)
  但 max 从 969 炸到 84k/100k;**cap2048 臂失控步 11.0% vs 无 cap 2.8%**
  (配对 t=+3.37,epoch 对齐 1.01/1.02)。重尾承自教师 3.8
  (p99/p50=42.8× vs 基座 1.8×;**3.6 仅 6.0×,其同任务轨迹在盘上从未使用**)。
- **Tillicum 08-18 傍晚提前恢复,eval 链迁回**(Klone 迁移的教训留档:L40S 约
  H200 一半速、GPFS 小文件三次卡死 → 一律节点本地盘、客户端超时 600→1800s)。
  **kD 在 Klone 收官:48/50 计分、0 补齐 49.81% —— 目前最高臂**(超 lorastock
  即 Bs-LoRA e3.00 stock 的 45.81%;basestock 因模板等价结论撤销,从未跑过);缺的 2 题:`5d901039`(impress,卡死)与 `5bc63fb9`(multi_apps,
  即 217 条命令风暴题,旧语义下磨上限,用户裁定放弃)。Klone serve 已撤,账户清空。
- **修法 B 已落地并从 kC 起生效**:`actions.py` 多行 type 在
  `OSTG_TYPE_NO_SPLIT=1` 下一条 typewrite 直发(默认 0=上游拆行;验收
  58,211 真实响应双闸 0 差异 + 灵敏度对照,→ `outdated/reports/SFT_FAILURE_ANATOMY_20260903.md`)。
  **口径边界:kD 及之前=拆行语义,kC 起=合并语义**,每次运行的
  `MODEL_BOUNDARY.json` 记录该 flag。当前链(Tillicum,`tillicum_chain.sh`),
  已出分:**kC=Bs-gb64 真 3ep = 43.81%**(比同跑 e1.02 的 45.8% 低 2pp,噪声内,
  "多训无益"在全量上重现)、**kE=r5 lr3e-6 3ep = 57.81% 全项目新高**(超 base
  18pp,首个越过噪声底线的读数;对 kD 的 +8pp 混着 lr/语义/硬件三变量,归因待
  kD15)。已收官:**kD15=39.81%**(3ep 比 1.5ep 高 10pp,r5 上多训有益)、
  **t38 教师=69.81%**(SFT 关掉 base→teacher 30pp 差距的 60%,剩 12pp 蒸馏
  空间;教师与 kE 双败 12 题=当前范式天花板)。**vlbase 收官 = 33.3%**(VL 基座比 Qwen3.5 基座低 6.5pp,vlsft 对着它读)。
  已收官(08-19):img3=47.81 / img3h3=53.81 / kEh3=57.81 / **nocap=59.81 新冠军**
  / vlsft=44.00(首跑烧于 XML/json 方言错配,修后重跑)/ gb128=37.81(vl3pic
  语料 gb128@1e-5,3 图评;对 vlbase +4.5pp、低 vlsft 6.2pp,语料窗×累积 LR
  双混杂,干净拆解等 vl3b)/ **kG=49.81(24 满分+1 部分分):剥 prose 比
  r5lora 高 8pp,越过噪声底,LoRA 系登顶追平 kD——"prose 是跨步记忆"假设
  证伪,teacher 旁白反是分心源(判读预注册 → RESULTS §5.14)**。
  **vl20 收官 = 45.81**(§5.13 预注册:方向命中幅度扑空,3.3× 累积 LR 只买
  ≤2pp,VL 最好读数仍落后 3.5 系 12-14pp,骨干负收益坐实)。
  当前链:kEh1(起跑)→ baseh1 → nocapt0 → **nocapnp →
  img1(1图匹配窗)→ vlnocapnp(尾,08-19 深夜用户令追加:VL×nocap×去prose
  @lr3e-6,训练 249567 排队中,完训闸接住;对照 vlsft 44.00,cap+prose
  双变量)**,后三臂带完训闸(serve 8041/8043/8045)。**VL 线
  eval 全清(用户令,eval 是瓶颈而 VL 骨干负收益已立住):vl3b/vl20g 训毕
  保留待评;vl20nc 训练也停(66/306,仅 0.6ep,非完整臂);vlbaseh1 撤**。
  用户点名必跑 img1/kEh1/baseh1/nocapt0,nocapnp 原位。预计明晨 ~04:30
  全链收官(撤三臂省 ~3.3h),随后 eval100 决赛。训练:249492 img1 **完训**(EXIT 0,
  1h42m,endpoint=ckpt-300 @ep3.00)、249500 vl20nocap(4×2,同事管,ETA
  贴墙余量 ~40 分)、**249538 nocapnp 跑动中**(249531 preflight 死于相对
  路径,数据修复经双路径交叉验证后重交);~~nocaplean 249536 已撤~~
  (用户令,27/306 零损失:真实 payload 渲染证明 eval 历史 think **全保留
  (27/27)**,preserve_thinking=false 是最坏方向 skew,立项前提反了;
  §5.14/CONTEXT§4 口径修正归 64333 会话);think 权重 0.5 臂论证已结:值得跑
  (think 占 loss 轮 70.8% 字符质量,最大杠杆;channel_loss 不冲突、token
  边界已验),**定序在粗旋钮出分之后(nocaplean 已撤,粗旋钮=nocapnp)**——三者机制
  不同(eval 可见输入/训练输入/训练信号分配),先粗后细省一轮。完训后各接匹配 eval 臂。
  **kF 撤下不排**。明细 → `sft/docs/CHECKPOINTS.md` §2.1。插曲:img3 起 serve 撞上
  scrubbed 吃掉 uv Python 标准库的定时炸弹(三次秒死;验尸与修复 → `docs/OPS.md`)。
- **LR 左翼双探(08-19 深夜,用户令)**:249612 np2e6(累积 3.1e-4)+
  249613 np1e6e5(1e-6×5ep,累积 2.6e-4)——两者剂量几乎同、遍数 3 vs 5,
  恰构成"总剂量 vs 重复次数(阶梯假设)"的配对;同时把 4.5e-4 以左的
  未采样区补上(唯一干净 lr 配对 kD→kE 是 +8pp 指向下方,f(0)=39.81 保证
  峰值存在于 (0,1.5e-3) 内)。1e-6×3ep 原案撤。配方=nocapnp 唯一变 lr/ep,
  逐项已验(4×2/端口公式/81920/独立输出目录)。
- **VL 线正式闭合(08-20,五个数据点全在手)**:vlbase 33.31 → vlsft 44.00
  (r5vl/lr3e-6/带 cap 带散文)→ vl20 **45.81**(lr1e-5,VL 最好读数)→
  gb128 37.81(3 图语料)→ **vlnocapnp 38.00**。最后这个是把 Qwen3.5 侧的
  胜方配方(去 cap + 去散文)搬到 VL:**比 vlsft 低 6pp,即配方不迁移**
  (两变量同动,归因联合)。VL 最好 45.81 vs Qwen3.5 最好 59.81,**差 14pp**;
  且 vlnocapnp 撞上限 20 题(全项目最多)、败题均 53.9 步,是"磨而不得"的形态。
  结论:**换 VL 骨干无收益,配方也不可移植** —— 与 08-19 用户撤空 VL eval 臂
  的决定一致。三份训毕权重(vl3b/vl20g)与 vl20nocap 残件保留待评,不清理。
- **评测窗曲线闭合(08-20,§5.16)**:kEh1=**49.81**、baseh1=**31.81** ——
  同一权重 20→3 图**完全免费**(57.81=57.81),3→1 图对 **SFT 与未训基座
  统一收费 8.00pp**(各丢 4 题,逐位相同)。含义:视觉历史值 8 分且与模型
  强弱无关;SFT 的 18pp 增益正交于视觉窗口;"靠记忆不看屏幕"再添一记反证。
  部署:服务端 3 图窗白捡(省 71% 视觉 token),别贪 1 图。
- **散文轴收官(08-21 晨,nocapnp 100/100)**:去散文全量微调 3ep 终点
  已见半 **55.81** / 未见半 **32.00** / 全 100 **43.90**,对冠军 nocap
  (59.81/38.00/48.91)**全面 −4~−6pp**;且 3ep 终点 == 2ep 中途快照
  (55.81)——按 08-22 实测噪声底应读作**第三个 epoch 的增益不可分辨**
  (不是"证实为零";同事对同类"逐位同分"表述的自纠见 §5.26)。
  **最终结论:散文效应随容量反号 ——
  LoRA +8pp(kG),全量 −5pp**;小容量下散文挤占学习预算,大容量下散文
  是有用上下文。用户裁决:散文保留,nocap 仍是冠军,targeted-300 配方
  冻结(带散文 + no-cap)不变。四次训练尝试(cuDNN 显存 / NVLink×2 /
  坏节点 g018)换来这个负结果,轴彻底关闭。
- **a7 vs a7e3:验证损失能否预测 eval 分数,做成可证伪实验(08-23 预注册)**。
  同一次训练(img10-9bh)的两个 checkpoint 都跑冻结 100:
  **a7 = 98 步(验证损失最低 0.45215)· a7e3 = 147 步(终点 0.45973)**,
  验证侧差 0.0076 = 末四点摆幅(0.0010)的 **7.7 倍**,方向明确。
  **这是本项目第一次能直接检验"验证集选点是否转化为任务成功率"** ——
  ①98 明显更高 → 验证损失可迁移,那 5% 语料的代价值得付;
  ②147 更高或打平 → 验证集的已证用途缩回"只能识别严重过训",
  而项目里两个信号背离已有先例(a6v 停在自己曲线最低点却分数最差)。
  注意 100 题面板 1σ=4.8pp,**若两者差 <5pp 则落入"不可读"支**,
  那本身也是结论:验证损失的这点优势小于评测噪声,不值得为它切 5% 数据。
- **a7 vs a7e3 开奖(09-01 补读)= 落入"不可读"支**:a7e3 一直没进 dashboard 的
  `ARM_PANEL` 注册表,页面按 seen-50 显示 31/50=62%,真值是 **54/100**(eval100,100 题
  齐)。与 a7(95/100,56.8%)配对 95 题:**54 对 54,+0.0pp,翻转 24 题**。验证损失最低点
  (98 步)与终点(147 步)在任务成功率上分不出来 —— 预注册的第③支成立:验证损失的
  这点优势小于评测噪声,不值得为它切 5% 数据。发现途径:sft_dash.py 09-01 加的
  MODEL_BOUNDARY 兜底第一次干跑就把它揪出来了(第四个因缺键被静默腰斩的臂)。
- **a6v 大幅落后(08-23,90/100 时 33.22,对 a1 净 −16 题)—— 不是验证集
  选错了点,是这次训练本身学习量配少了**。累积学习率
  (0.5 × 峰值 lr × 步数):**a6v 1.94e-4 vs a1 4.59e-4 = 42%**
  (lr 2e-6 而非 3e-6、2 epoch 而非 3)。实测曲线在 1.5e-4 处是 47.81、
  峰顶 4.5e-4 是 59.81 —— a6v 正落在左半边。服务权重已核(checkpoint-194,
  正确)。**两条可推广的结论**:
  ①**验证损失只在同一次训练内部有意义** —— 它把 a6v 这条曲线上最好的点
  挑出来了,但无法告诉你"这条曲线整体配低了"。**选 epoch 数和学习率
  必须跨配置比较,验证损失做不到。**
  ②**验证损失与任务成功率在本项目里背离**:前者测"在留出轨迹上预测教师
  下一个 token",后者测"在真实 GUI 里把活干完"。三个印证:nocapnp 训练
  损失掉 19.5% 而 eval 不可分辨;a5v 验证损失从 epoch 2 起上升(看似过训)
  但从未被 eval 证伪;a6v 自身曲线最低点却比多训的臂低 15-19 题。
  **所以"过拟合"的信号在这里不能当停训依据。**
  验证集真正兑现的用途只剩两个:同次训练内排 checkpoint(a7 用上了)、
  发现明显过训(a5v 的 5 epoch)。
  **由此预注册 a7**:它的累积学习率 **2.20e-4,只有 a2(4.59e-4)的 48%**
  —— **预期 a7 < a2(62.90)**;若果真如此,说明 gb128 这条线整体欠训,
  而不是 hermes 或验证集的问题。
- **怎么读跑到一半的 261(08-23,a2261 中途)**:两个陷阱,都会让好臂看着"一般"。
  ① **页面上的 361 百分比按固定分母 361 算**,未评的记 0,所以跑完之前必然偏低
  —— 那是会计口径不是模型表现,看进度读 `scored/total`,看当前水平读 `now`。
  ② **49 道 proxy 题全部落在 261 这片**(100 题面板是 nonproxy 的),而 261 是
  **按域顺序执行**,chrome 恰好是 proxy 重灾区 —— a2261 前 83 题里有 **28 道
  proxy(33.7%)**,是 261 整体密度(18.8%)的 **1.8 倍**,剩余 178 题只剩 21 道
  (11.8%)。**前段分数被系统性压低,后段会松。**
  正确读法是**在已跑完的那些题上做同题配对**(不受难度构成影响):

  | 在 a2261 已跑的 83 题上 | 得分和 | 非 proxy 55 题 | proxy 28 题 |
  |---|---|---|---|
  | **`9b-full-img10`** | **45.00(54.2%)** | **69.1%** | 25.0% |
  | `4b-full-img20`(冠军) | 31.00(37.3%) | 49.1% | 14.3% |
  | `4b-base` | 29.00(34.9%) | 45.5% | — |

  逐题 22 处不同,9B 赢 18 / 冠军赢 4,**净 +14 题**。
  **但不能外推最终 361**:两个难度探针方向相反(对冠军来说已跑段难 13.1pp,
  对基座来说反而易 4.3pp),且 10 个域只跑了 3 个。
- **261 的曲线形状是固定的,由域执行顺序决定,与模型无关(08-23 实测)**。
  两个跑完的臂按完成顺序切 5 段,形状一模一样:

  | 臂 | 第1段 | 第2段 | 第3段 | 第4段 | 第5段 |
  |---|---|---|---|---|---|
  | `4b-base` | 42.3% | 28.8% | 32.7% | **11.1%** | 44.7% |
  | `4b-full-img20` | 42.3% | 42.4% | 46.1% | **30.4%** | **69.6%** |

  域执行顺序与各域难度(`4b-full-img20` 的命中率):

  | 域(执行先后) | 题数 | proxy | base | 冠军 |
  |---|---|---|---|---|
  | chrome | 40 | **70%** | 27.5% | 32.5% |
  | gimp | 18 | 0% | 61.1% | 55.6% |
  | libreoffice_calc | 32 | 0% | 31.2% | 34.4% |
  | libreoffice_impress | 32 | 0% | 31.2% | 62.7% |
  | libreoffice_writer | 16 | 0% | 56.2% | 50.0% |
  | **multi_apps** | **69** | 28% | 11.2% | 31.6% |
  | os | 16 | 0% | 43.8% | 75.0% |
  | thunderbird | 10 | 0% | 60.0% | 60.0% |
  | vlc | 12 | 0% | 30.6% | 65.9% |
  | vs_code | 16 | 12% | 50.0% | 68.8% |

  **开局低(chrome 七成是 proxy)→ 中段锯齿 → multi_apps 连跑 69 题塌陷
  (占全盘 26%)→ 最后 54 题全是 60–75% 的域,猛拉回来。**
  即**滚动均值在全程约 80% 的时间被压着,只在最后 20% 回补** ——
  中途看到掉分是面板结构,不是模型退化。
- **a7 开奖(08-23 17:26)= 55.90/100,预注册方向命中**(已见 61.81、
  留出 50.00)。对 a2(62.90):**逐题 21 处不同,a2 赢 14 / a7 赢 7,净 −7 题**。
  净 −7 明显大于自比基线的净 ±2,不是抖动。
  **但这个比较三重混杂**(gb128 + hermes + 5% 验证集同时动),
  只能读作"这条线整体不如标准配方",**不能归因到其中任何一项** ——
  臂名 `9b-full-img10v-gb128-hermes` 三段偏离项本身就在标注这一点。
  能隔离的那一格是 a7 vs a7e3(同一次训练、同一面板、只差 checkpoint),
  已排在队尾待跑。
- **⚠ 09-01 发现的混杂:a2/a7 是按 20/10 窗口评的,mixa9b/mixb9b 是 10/1**
  (`args.json` 逐一核过:a2/a2261/a7/a7e3 `image_max=20 fold_size=10`;两个 mix 臂
  `image_max=10 fold_size=1`,来自 `chain_eval_rest.sh:149` 写死)。同权重换窗口的现成
  对照 a1(20/10)vs a1h10(10/1),98 题配对 **49.0 vs 42.9 = +6.1pp 归 20/10**
  (multi_apps +2、gimp +3、vlc +2)。而 a2 领先 mixb9b 只有 +2.0pp(99 题配对,
  61.6 vs 59.6,翻转 24%)、领先 mixa9b +6.2pp(97 题)——**都不超过窗口效应本身**。
  "加了 v16 数据反而下降"这个读法在窗口对齐之前不成立。**→ 09-01 20:33 已对齐:mixb9bw20
  (同权重 20/10)= 52.0%,比 10/1 还低 8pp;a2 在同窗口领先 +9.0pp(去 infeasible +12.6pp)。
  窗口不是原因,a2 的领先成立;偏离训练窗口本身要付 6–8pp。RESULTS §5.31。**
- **a2(9B + img10 语料)= 62.90/100 —— 全项目最大的一次跃升,而且远超噪声底**
  (08-23)。已见 **69.81 = 教师的 69.81,但这是平衡翻转不是逐位持平** ——
  集合核验:50 题里 10 题结果不同,5 胜 5 负(08-23 补验;本项目第四次把
  "总分相等"误写成"逐题相同");留出 56.00(教师 68.00)。
  配对(自比基线净 ±2、翻转 24):

  | 对照 | 分差 | 翻转 | 净题数 |
  |---|---|---|---|
  | **vs 4B 冠军 nocap** | **+14.00pp** | 24 | **+14** |
  | **vs 同配方 4B(a1)** | **+14.00pp** | 26 | **+14** |
  | vs 未训 9B(base9b) | +25.00pp | 33 | +25 |
  | vs 教师 27B | −6.00pp | 26 | −6 |

  **净 +14 题对 ±2 的基线是 ~2.9σ —— 这是今天唯一一个稳稳越过噪声的
  模型间差异**(另一个是冠军 vs 基座 +18)。三点值得记:
  ①**换骨干的收益(+14)远大于今天测过的所有配方轴**(散文 −5、hermes +2、
  图窗 0、lr 峰顶两侧 −10~−12),**规模是唯一还在给钱的轴**;
  ②**9B 学生在已见半上追平教师**(69.81 vs 69.81),差距全在留出半
  (56.00 vs 68.00)—— 与 §赢家诅咒分解一致:已见半的分数含选型成分;
  ③**SFT 对 9B 的增益(37.90→62.90,+25)大于对 4B 的增益
  (30.90→48.90,+18)** —— 骨干越强,同一份语料给的越多,没有饱和迹象。
- **已见/留出落差的正式分解(08-23,`sft/analysis/panel_difficulty.py`)**。
  按判分族做 Oaxaca 式分解(成分差 = 换成已见半的题目构成后还剩多少):

  | 臂 | 已见 | 留出 | 总落差 | 成分差 | **同类题上做得更差** |
  |---|---|---|---|---|---|
  | 教师 27B | 69.81 | 67.98 | +1.82 | +1.60 | +0.22 |
  | **冠军 nocap** | 59.79 | 38.00 | **+21.78** | +3.66 | **+18.12** |
  | 基座 4B | 39.83 | 21.98 | +17.85 | +5.81 | +12.04 |
  | 基座 9B | 41.80 | 34.02 | +7.79 | +5.26 | +2.52 |

  **①"留出半更难"只值 2-6pp** —— 成分(表格类 8→14、infeasible 5→8)
  对每个臂都只解释这么多。域构成、指令长度、教师步数几乎完全一样
  (multi_apps 12/12、指令 167/174 字符、教师步数中位 14/15),
  **按教师步数分层完全消不掉落差**,所以"长任务更多"不是原因。
  ②**表格类是真的更难**:教师在留出半的表格上也从 87.5 掉到 50.0
  (−37.5pp)—— 所有臂同吃,这部分与选型无关。
  ③**决定性证据在最大的"其他"族(28 vs 21 题)**:教师 −3.9、基座4B
  +6.9、基座9B +4.4 **三个从未被选型的模型全部持平**,而
  **唯一在已见半上做过选型的冠军 +30.6pp**。同一批题、同样的难度,
  差别只在"这个模型是不是在这半上被挑出来的"——**这是赢家诅咒最干净
  的一次隔离**,比之前的重采样(8.45pp)和教师域配对(8.80pp)都直接。
  **可用的难度代理排序**:教师逐题得分(最好,与被测模型无关)>
  判分族 > 域;**无用的**:教师步数、指令长度、规则数、域构成。
- **推理窗口这条轴:证据自相矛盾,判定不可读并停止投入(08-23)**。
  a1h10(同权重、唯一变量是窗口)= 42.90 vs a1@20 的 48.90。统一到已见 50
  面板后三个测量:**a1(10图训练)@10 vs @20 = −3 题 · img3(3图训练)
  @3 vs @20 = +3 题 · kE(20图训练)@3 vs @20 = 0 题**,翻转次数全是 11-12
  (自比基线量级)。**两个非零测量方向相反且都不显著**(1.25σ p=0.307 /
  0.88σ p=0.549)——若"窗口匹配"是规律,应当同向且同显著。
  **最可能的解释是没有规律,看到的是噪声的花样。**
  a1 两半各 −3 有弱内部一致,但不足以翻转结论。
  **决定:不跑 a1@3** —— 三个都在 1σ 附近的点连不出单调性,只会多一个
  读不出来的数;要测这条轴须上 361 面板(1σ=2.5pp)。
  **我先前"多给图是白送"和"3 张以上是装饰品"两句话都收回**(把 1.25σ
  当结论)。**对 9B 的配置建议因此改为 10 图**:12 图(88% 显存)没有被
  证实的收益,而 10 图(83%)更安全 —— 在两种假设下都稳。
- **a1 开奖(08-22,img10 冠军配方)= 48.90/100,与冠军的浮点和一位不差**
  —— 第四次"相等",这次立刻做了集合核验:**逐题 20 题不同,10 赢 10 输,
  又是平衡翻转**。分半:已见 55.81 vs 59.81(−4)、未见 42.00 vs 38.00(+4),
  连分半都恰好抵消。
  **三个比较放在一起,结论就不需要 σ 了**:

  | 比较 | 逐题翻转 | 净差 |
  |---|---|---|
  | **img10 vs img20**(a1 vs 冠军) | **20/100** | **0** |
  | hermes vs 无(a3 vs a1,干净隔离) | 28/100 | +2 |
  | **同一模型重跑**(冠军 vs 冠军) | **24/100** | −2 |

  **img10 与 img20 的差异(20%)比同一个模型跑两遍的差异(24%)还小** ——
  即**训练图窗从 20 砍到 10 完全测不出代价**,而它省 39% 显存(136.7→89.66 GiB)。
  这是今天最有工程价值的结论。hermes 的干净隔离(a3 vs a1,同语料同窗口)
  是 +2.00pp / 28% 翻转,与自比基线同档,**维持"×2 无可观测效应"的定性**。
  待补:a1h10(同权重、10 图匹配窗口)——若匹配后高于 20 图口径,则 img10
  不只是"不亏"而是"更好"。
- **a3 开奖(08-22,img10 + hermes 动作加权)= 50.90/100**(已见 59.81、
  未见 42.00 vs 冠军 38.00)。**已见半的 59.81 = 59.81 不是"逐位相同"** ——
  逐题查:**12 题结果不同(6 赢 6 输),总分相等是平衡翻转撞出来的**,
  正确说法是"在 6.8pp 噪声底下不可分辨"(同事纠;这是 nocapnp
  27.90=27.90 那个坑的第二次现形,我犯了它今早刚自纠过的错)。**对冠军 +2.00pp,落在预注册的
  第四支:100 题面板 1σ=4.8pp,不可读、不产生结论、不进已证伪清单。**
  逐题 14:12 净 2 题。而且这个比较**三重混杂**(img10 语料 + hermes 加权
  + 20 图评测下的窗口错配),**能隔离 hermes 的干净比较是 a3 vs a1**(同
  语料同窗口),a1 未跑。
  两条预注册预言的结局:①**两道复活题仍为 0 ✓**(它们在 impress/char_format
  零覆盖格,泛化没能拿下;故全 100 与 98 两个口径同向,差 2.04 vs 2.00);
  ②**"hermes 加权推高假报成功"未兑现** —— 34% vs 34%,**但同样是巧合**:
  21 题 vs 21 题里**只有 8 题重合,各有 13 题是对方没有的**,即假报的
  *集合*几乎完全不同、只是*数量*相等。**"两个数相等"在这个项目里已经
  三次都是平衡翻转,不是稳定性** —— 报任何相等都必须逐题核集合;
  收尾结构也几乎相同(DONE 61/62、撞上限 30/28)。行为侧唯一可见的偏移是
  动作/步 1.31 vs 1.26、每步散文 221 vs 145 字符(且出现 22 万字符的极端
  离群),方向与"加权推动作"一致但幅度都在噪声内。
  **最有说服力的表述(不需要 σ)**:a3 与冠军的差异 = **翻转 26/100**、
  净 +2 题;而**冠军与它自己重跑**(同权重、仅改 max_steps)= **翻转
  24/100**、净 −2 题。**换掉 loss_scale 产生的差别,和把同一个模型再跑
  一遍产生的差别一样大。**
- **9B 训练图窗上限实测 = 12 图(08-22)**。三点(同拓扑:4 节点×2 卡=8 rank、
  accum 8、zero2_offload、sdpa、梯度重计算、max_length 65536):
  **10 图 115.8 GiB(82.8%)· 12 图 123.1 GiB(88.1%,2/2 步通过,128 样本
  零丢弃)· 14 图 step 0 即 OOM**(rank7 已分配 137.21/139.79)。
  判定过 OOM 是真因:OOM 行在 NVLink 报错行之前,后者是 rank 猝死的连锁。
  **注意两个 logged 点的斜率(3.65 GiB/图)会低估** —— logged 是步边界的
  max_memory_reserved,而 14 图死在没有任何步边界读数的瞬时分配上;
  **logged 斜率只能当下界,不能当预算**。
  背景账:4B@20 图 136.7 GiB = **97.8%,一直贴着天花板**(这才是当初换
  10 图的原因);9B 同样 10 图比 4B 贵 **26 GiB**(hidden 2560→4096)。
  常规省显存手段已用尽(重计算开、优化器卸 CPU、序列并行经验证净亏)。
  **未用的杠杆:同样 4 节点改每节点 8 卡(8→32 rank),ZeRO-2 梯度分片
  细 4 倍** —— 代价是排队(实测 8 卡最长等 67 分,16 卡 571 分)。
  工具固化 `sft/data/mk_imgwindow_smoke.py --keep N`(折叠 20 图语料造任意
  窗口的最坏样本集;不能筛"恰好 N 图"的样本 —— 那些是走到第 N 步就停的
  短轨迹,会低估,因为峰值由文本主导的长轨迹决定)。
- **kGh 开奖(08-22,LoRA+去散文 @ 留出 50)= 44.00 —— 全部 4B 学生里最高**,
  高于全参冠军 nocap 的 38.00、去散文全参 32.00、未训 9B 34.00。
  **但按实测噪声底 50 题 1σ=6.8pp,+6.00pp 不可读**(逐题配对 7:4,净 3 题)。
  可读的只有 kGh vs 未训 4B 基座 22.00 = **+22pp(>3σ)**。
  **跌幅表(已见→留出)是本轮最值得看的东西**:
  LoRA −5.81 · 全参冠军 −21.81 · 全参去散文 −23.81 · 基座4B −17.81 ·
  基座9B −7.81 · 教师 −1.81。方向一致地暗示"全参记得多、LoRA 保留基座
  泛化",但**差之差的 1σ≈13.6pp(四个测量各 6.8),16pp 差只有 1.2σ,
  同样不可读**;且未训基座自己就有 −17.81 的跌幅,说明两半难度差本身
  就贡献大部分 gap,不能全记在"记忆化"账上。
  **原定要回答的问题没能回答**:配对臂 r5lorah(LoRA+带散文)被撤,
  所以"LoRA 上散文 +8pp 是真是噪"仍然悬着。
  **若要坐实"LoRA 泛化优于全参"这条(它会改写整个 SFT 路线,且 LoRA
  训练成本低一个量级),需要 361 面板(1σ=2.5pp)或同臂多次重掷**,
  50 题上再跑多少次都读不出 6pp。
- **两道复活题的身份 + 双口径预期(08-22,a 系列开跑前锁定)**:
  eval100 里那 2 道从未真跑过的题都在**留出半**、都是
  **libreoffice_impress 格式类**——`a434992a`("把正文字号改 12、
  字体颜色改橙")与 `a669ef01`(第 3 页续行缩进)。**它们正落在覆盖
  审计的最大零覆盖格上**(impress/char_format:OSWorld 16 题、语料 0
  题、v11 池仅 1 条)。冠军/去散文/判决臂在这两题上历史全 0(因从未
  执行)。**预期:a 系列真跑之后大概率仍是 0**,故全 100 与剔除这 2 题
  的 98 两个口径应当几乎相同;**若它们竟得分,那是"零覆盖格也能靠
  泛化拿下"的证据,值得单独记一笔**,而不是 img10 配方的功劳。
  今晨的覆盖审计与今午的复活发现在此收口:同一格子既是语料缺口,
  也是唯一从未被执行的两题。
- **噪声底首次直接实测(08-22,同事从判决臂数据提取,§5.26)**:
  取"两边都 <50 步"的 61 题子集(抬上限物理上碰不到,差异纯采样),
  **翻转率 23.0%** → 1σ:50 题 **6.8pp** / 100 题 **4.8pp** / 361 题
  **2.5pp**。硬规矩:**100 题面板上 <5pp 的臂间差读不出来**,2σ 要
  10pp。追溯定性:nocap vs base +20pp 成立;gb64 vs gb128 −2、
  ms100 −2、nocapnp ep2 vs ep3 ±0 全在噪声内不可读。**a3 预注册补
  第四支(可能是最大概率支):|差|<4.8pp = 不可读,不产生结论,
  不进"已证伪"清单**;要可读只有加大剂量(文献口径 ~25%)或换
  361 面板(1σ 2.5pp)或两者。
- **步数预算判决开奖(08-22 午,nocapms100 100/100)**:唯一变量
  max_steps 50→100,总分 46.90(vs 50 步版 48.91)。**预注册判决量:25 题
  判决池中,真正靠 51-100 步区间转正的只有 2 题(8%)**;另有 2 题 ≤50 步
  重掷成功(运气非预算)、反向丢失 13 题(t=1.0 重掷方差)。32 条 >50 步
  轨迹仅 5 条得分,10 条走满 100 步。**裁决:长任务失败是能力问题不是
  预算问题,"加步数"路线关闭**;v13 语料三缺口维持主线,且 §5.22 的
  师生长度差应读作"长任务=更多出错机会",非"步数不够"。赛前预测:
  我 2-5(中,下沿)、同事 3-8(脱靶)。附带结论:同权重同参重掷在
  50 题半上波动 ±4pp(59.81→55.81),单次对比的噪声底再次实证。
- **a3(hermes 动作加权)判读规则预注册(08-22,出分前锁定)**:同事的
  loss 质量测算 —— tool_call 占 16% token 但只占 **2.2% loss**,hermes ×2
  只把动作信号从 2.2% 挪到 4.3%;文献侧 ActFocus(2605.14558)的最优口径
  是动作占 ~25%(**五倍力度**,且 β 扫描有峰、过头崩),ms-swift 的 ×2
  出处是 2023 demo 论文的未扫描默认值。因此:①a3 明显高 → 方向成立且
  轻剂量就够;②**a3 平 ≠ 方向证伪** —— 剂量不足与方向无效在单点上不可
  分,下一探针应是压 think(α<1)而非 ×N;③a3 低 → 先查假 DONE 率
  (预言:termination 是 tool_call 且语料全 success,加权可能推高假报)。
  顺带三条:hermes 正则依赖 swift 传 re.DOTALL(已实测生效,自写配置者
  的第一雷);我们语料每步 think 268 token 为已发表最长(GUI-Libra 210、
  AGUVIS 85、多家为 0);a3 完训干净(306/306,loss 0.855→0.304)。
- **8 题从未真正跑过(08-22,同事定案;权威明细 outdated/reports/SFT_FAILURE_ANATOMY_20260903.md §9)**:
  魔改 OSWorld 的 metrics/__init__.py 在加自定义 metric 的同一个 diff 里
  删了 9 个上游导出,8/361 题(留出半 2 题、其余 261 中 6 题,multi_apps
  占 5)在**所有历史臂**上 env.reset 即崩、agent 零步、记 0。所有臂同等
  受害 → 臂间差与师生差不受影响,**绝对值全体被低估**:361 上限 −2.2pp
  (nocap 47.00 实为 49.2 的口径)、留出 50 上限 96%(教师 68.00 实为
  72.0 的口径)、multi_apps"最弱域"的 35.3% 部分是记账假象。已修(用户
  批准)、不追溯。**两条落地**:①驱动加发射前静态闸(任务集全部
  evaluator.func 在 runner venv 上 getattr,全 361 冒烟零坏);
  ②**口径差**:nocapms100 的长驻 worker 起于修复前,其 100 题仍含 2 死题
  (与 nocap 同口径,配对干净);a1/a2/a3/a5v 起新进程用修复版 ——
  **a 系列 vs 冠军的 eval100 对比必须双口径报**(全 100 + 剔除 2 复活题
  的 98),否则复活题得分会被误读为配方增益。
- **9B 基座上榜(08-22 晨,eval100)**:已见半 **41.81** / 未见半 **34.00** /
  全 100 **37.90**。三个读数:①未训 9B vs 未训 4B:未见半 **+12pp**
  (34.00 vs 22.00,两半都是干净口径)、已见半只 +2(41.81 vs 39.81,
  4B 那半口径脏)——**规模收益集中在难题**;②未训 9B 的未见半(34.00)
  已逼近 SFT 冠军 4B(38.00)、超过去散文臂(32.00)——**9B 起点几乎追平
  4B 的全部 SFT 增益**;③离教师(68.00)仍差 34pp。若 SFT 对 9B 的增益
  与 4B 同量级(未见半 +16pp),9B 学生可望 ~50,"训 9B @ img10"的
  预期收益有了数(显存侧同事已 smoke:110 GiB,比现行 4B 配方还省)。
  base9b261 已 04:37 自动接棒。
- **361 三段线前两条收官(08-22 凌晨)**:**nocap 冠军 361 全量 47.00%**
  (169.68/361;非 proxy 312 题 **52.14%**、proxy 直连 49 题 14.29%),
  对 base 361 的 31.67%(35.04/10.20)= **SFT 增益全量 +15.3pp、
  非 proxy +17.1pp、proxy 层 +4.1pp**。并集严格 ==test_nogdrive,
  补跑段分桶体检无灌 0(35-67%)。nocap261 中途经历 serve 断档灌 0 事故
  (157 题隔离重跑,明细 docs/OPS.md §serve 断档);汇报主口径建议用非 proxy
  312 题,proxy 49 题单列(直连、59-86% 轨迹含拦截痕迹、SFT 增益被网络
  墙压缩)。9B 基座(base9b 100→base9b261)已接棒在跑。
- **base 361 全量出分(08-21 午,basekeep+base50b+base261 并集,零重叠,
  ==test_nogdrive)**:**31.67%**(114.33/361)。**proxy 分层差距巨大**:
  非 proxy 312 题 **35.04%** vs proxy 直连 49 题 **10.20%** —— "在美国直连
  就行"的假设基本不成立,49 题拖低总分 ~3.4pp(混杂:proxy 题也偏难/偏
  multi_apps,未拆网络失败 vs 能力失败)。按域:multi_apps 15%(93 题,
  最弱、最大)· calc 26% · chrome 30% · impress 32% · writer/vs_code 48% ·
  gimp 54% · thunderbird 67%。基座口径 caveat:basekeep 半无权重存档。
  nocap261 已于 12:02 自动接棒。
- **散文机制解剖(08-21,`sft/analysis/eval_emit_compare.py`,100 题配对)**:
  ①训练期剥除在推理期是**彻底的**——nocapnp 100% 的步零散文(每步均值
  2 字符 vs nocap 145),末步上下文累计散文 61 vs **3810 字符(≈950 token)**;
  ②think 分布不变(p50 535 vs 525)——**丢掉的散文没有被 think 补偿**;
  ③行为侧:动作/步 1.36 vs 1.26(轻度 LoRA 化),假报成功率 39% vs 34%;
  ④配对翻转 14:10 偏向带散文(净 +4 题),两侧翻转题都以长任务为主
  (≥20 步占 10/14 与 8/10)。结论:散文 = **唯一跨步存活的自然语言记忆**
  (历史只留最后一个 think、留全部散文),同时占训练监督信号的 17%
  (语料测量);全量微调下两个通道都是正贡献。单臂 −5pp 在噪声底附近,
  强度来自方向一致性(两半同向 + LoRA 反号 + 2ep 平台)。
- **targeted-100 定向补数据启动(08-20,用户拍板:纯追加不降采样、FAIL 不做、
  超参冻结、池不够用 Opus 5 生成)**:计划与全部决定 →
  `outdated/plans/PLAN-20260820-targeted100.md`;三层打标器 `taskgen/analysis/taxonomy_tag.py` 首跑:
  候选池 1405 条(18 个时代)、产出形态与语料同偏(file_or_text 83%),
  纯需生成格 = calc/chart、gimp/layers、install、speaker_notes;
  缺口表已交反驳 agent 攻击,配额待审计+通过率后定稿。
- **eval100 决赛三方收官(08-20)与赢家诅咒定量 —— 今天最重要的结论**
  (全文待迁入 RESULTS §5.18,当前 RESULTS 有另一会话未提交改动):

  | | 已见 50 | 未见 50 | 跌幅 |
  |---|---|---|---|
  | 教师 27B(选型池=1,零偏差) | 69.81 | **68.00** | **−1.81** |
  | 冠军 nocap | 59.81 | **38.00** | −21.81 |
  | 基座(口径脏,见下) | 39.81 | **22.00** | −17.81 |

  **教师几乎不跌 ⇒ 两半真实难度只差 1.8pp**;冠军跌的 21.8pp 里九成来自
  **选型偏差 + 4B 能力阈值**。选型偏差有两个独立估计且吻合到 0.35pp:
  ①25 臂 split-half 重采样外推 n=50 → **8.45pp**;②教师域配对实测冠军多跌
  **8.80pp**。另:**nocap 只有 27.3% 概率赢得那场选型**——换一批 50 题,
  四次有三次选出别的臂。**由此定规矩:选型面板与报告面板必须分家。**
  未见 50 已在 08-20 用掉,再选型即报废。
  - **未见半是不走运的抽样**:表格类占比 **28%**,而已见 50 与剩余 269 都是
    **16%**(全基准水平)。4B 在表格类上 21% vs 教师 83% —— 能力墙,非覆盖缺口
    (语料表格类 14.4%,与基准 16% 持平)。
  - **基座已见半对照口径脏**(旧模板 + 08-18 前 harness + num_envs 2),故
    "+20pp 收窄到 +16pp"作废,**+16pp 才是干净的 SFT 增益**。
  - **干净面板上学生只关闭了 base→teacher 差距的 35%**(已见半看是 67%),
    即蒸馏空间比原先以为的大一倍。
- **语料覆盖审计(08-20,`taskgen/analysis/coverage_audit.py`,已固化为流水线检验)**:
  语料只教 **3 种 evaluator**(check_include_exclude 81.7% / compare_table
  14.4% / is_expected_url_pattern_match 3.9%),而基准三个面板各有
  **26 / 21 / 94 种从未出现在语料里**,波及 **78% / 72% / 79%** 的题。
  比例三面板一致 ⇒ **不解释已见-未见落差,但界定了整体天花板**。
  最尖锐的两个零覆盖:**`infeasible`(必须答 FAIL)0 道** —— 与全项目
  假报成功率(冠军未见半 44%、基座 46%)直接对应;**`compare_docx_files`
  0 道** —— 与 writer 域 3/3→0/4 崩塌对应(教师同题 3/4,故非题目不可解)。
  措辞收窄:evaluator 是**任务形态**代理,不等于"没教过该动作"。
  应用分布也偏:语料重仓 files/vscode/terminal,基准重仓 multi_apps/chrome。
- **流程级污染检查落地(08-19 夜,§5.15,sft/analysis/flowsim.py 固化为管线命令)**:
  kE 独赢 base 的 9 题流程相似度**反而更低**(0.352 vs 0.539,5/9 与全部训练
  轨迹 0 共享 4-gram),流程撞车最狠的四题 kE 全输——恶性"回放训练流程得分"
  无证据;三锚 base 0.402 / kE 0.505 / teacher 0.530。**对抗审稿已完成,
  结论收窄**(§5.15 收窄版):核心判别量经长度残差化(p≈0.026)与教师倾向
  控制(p≈0.0024)反而更硬,但只能主张"坐标级流程撞车不解释 ≥78% 赢分";
  打字内容记忆(仪器盲区)与屏幕盲性(干预性命题)未检验,2 题(22% 赢分)
  待裁定;"反向证据"句与"机械效应"注记被判死删除。
- **eval100 决赛(用户定,2026-08-19;当前链跑完后执行)**:等全部臂在 eval-50
  出分 → 取 SFT 最高分者(冠军)→ **冠军 + base + teacher 三方跑 eval100**
  (`verified_eval100_nonproxy.json`)。要点:eval50 ⊂ eval100 已验证,**另 50 题
  冻结于 08-15、从未被任何模型跑过/任何决策看过**——天然样本外考卷;跑全 100
  一次同时得到:①未见 50 题上的配对差(答"是否过拟合这 50 题/赢家诅咒"),
  ②已见 50 题的重跑(答"单次运行方差")。判读预注册:主判据=未见 50 题上
  冠军 vs base 逐题配对显著;幅度预期自 eval-50 读数回落。约 3 臂 × 4-9h,
  全程 no-split 口径,base 亦然(顺带闭掉 base 的口径尾巴)。
已出分:kD15(epoch 1.5)= **39.81%**,
  3ep 比 1.5ep 高整 10pp —— r5 全量上「多训有益」,与 Bs 语料方向相反。修法 B 附带红利:单臂 2h(原 4-6h),风暴磨步时间消失;
  serve 端口 8028/8029/8031(8030 让给旧 Klone 隧道位,防串线)。
- **datagenv12 首波启动:补格式类任务 50 道(fmt-w1)**。依据:语料 544 道里
  格式类 **1 道(0.2%)** vs 基准全量 15.2% / eval-50 18%;该类并集解开 3/9,
  其余 32/41。计划、五条硬约束与闸 → `outdated/plans/PLAN-20260818-datagenv12-fmt-w1.md`;
  代码分支 `datagenv12`(worktree `/mnt/d/research/ostg-datagenv12`)。

- **r5 相对旧版(6,297 样本)的四处差异**:① 截尾从 33 条降到 9 条,旧版其中
  13 条砍掉了 109 个真实动作(在教"活没干完就停手");② 图片不再经
  `--image-cache` 继承污染,缓存命中 0、6,489 张全部重编码;③ 末步从"一律合成
  重写"改为三路分流,**307 条保留教师原话**,旧版把 54 条本就正确的 terminate
  也换掉了;④ meta 新增 `terminal_mode` / `rescued` 可溯源。

- **错图根因定论**:手里有唯一的 `task_id`,却用不保证唯一的 `slug` 命名图片目录。
  修法一行(`img_key` 永远带 task_id),两条轨迹在结构上不可能共用目录;
  r5 实测 362 目录 ↔ 362 轨迹一一对应、0 共享。**像素重推导检查因此删除** ——
  每臂 45 分钟重编码 6.2 万张 PNG,去复核一个已由唯一键保证的事实。

- **两个看门狗已删除**(`eval_watchdog` / `master_watch`):前者分不清
  "还没开始"和"卡死",在启动阶段循环杀 runner,导致 LoRA 与 lean-stock 各归零
  一次;后者一次 ssh 探测失败就 pkill 所有 runner。详 `docs/OPS.md`。
- **Bhqs 语料 + 训练(新臂)**:判官+仲裁筛选的 304 轨迹 / 5,367 样本,
  换血 32% 而规模只小 3.9%,**难度反升**;训练 236019 运行中(Bs 精确孪生,
  语料是唯一变量)。赎回三阶段口径 83→56→54,详 `sft/docs/SFT_DATA.md`。
- **数据质检战役(08-17,新)**:盲审判官考试 AUC 跨池稳定(Opus .763/.771,
  Qwen .774);步级审计坐实 cap-2048 断崖(>2k 带弱步 41%,"想完不做"主模式);
  **仲裁 100 池 23 条分歧:10 条 checker 冤案(全过严向,3/3 抽查代码坐实),
  真实 pass 率 ≈80% 非 70%**。问卷拆账:Qwen v2 白改、medium 有害,
  最优 v1+low;**生产问卷定为 v2req**(清单+证据,为成功轨迹分层),
  v1 冻结为校准基线。筛选流水线跑动中:Qwen v2req 批两池 → 500 池仲裁
  (~110 条)→ 三张名单(keep 高质/赎回冤案/剔除假 pass)→ **B-rescue 语料**
  候选。详 → `sft/docs/SFT_DATA.md` 盲审章 + `docs/IDEAS.md` §J。
- **v11-500 教师 rollout:444/444,checker 口径 250 过/56.3%——仲裁修正后
  真实率待 500 池裁决**。B 原料 312 轨迹(arm A 的 4.7 倍)。
- **eval-50 epochs 曲线**:base 38% → ep1 26% → ep3 28% —— 损伤第一个 epoch
  全额安装;训练深度无罪。四行史:rich/rich 28%、leankeep 22%(渲染线闭)。
- **v11q2(qwen3.8-max 生成)已 ship**:459 task JSON,accept 全绿;待办:
  scan review 4 项 + VM control 轮 + **checker 生成端静态检查清单**(仲裁
  病理反哺:禁硬编码未给定细节/round 语义/枚举值核对)。
- 谱系:**v11.1 = main = 标准流水线**;任务源 `os-simple-taskgen-v8/out/runs/`;
  分支史 → `outdated/docs/TASKGEN_GIT_HISTORY_20260815.md`。

Sections 1–4 describe the system design; §5 onward are the experiments that
produced it, newest last, with sample sizes attached so weak evidence can be
told from strong. Code and docs: https://github.com/DengDuangLang111/CUA
(private).

---

## 1. What is running now — v8

A generator writes OSWorld-compatible desktop tasks: a scenario in plain
English, a program that builds the starting files, and a way to decide whether
the agent finished. The output is the JSON OSWorld's runner already consumes,
and the tasks run against a real Ubuntu VM under Docker.

**203 tasks over nine applications:**

| vs_code | calc | os | chrome | impress | writer | thunderbird | vlc | gimp |
|---|---|---|---|---|---|---|---|---|
| 44 | 34 | 32 | 30 | 16 | 16 | 13 | 10 | 8 |

**Three grading routes**, chosen per task rather than one imposed on all:

- **probe** (172 of 206) — a program that reads the finished state and prints
  PASS or FAIL (delivered through OSWorld's `vm_command_line` getter and the
  `check_include_exclude` metric, which tolerates the raw trailing newline). Used when "done" cannot be said in a rule: several files that
  must agree, a value computed from the data, a directory laid out a particular
  way.
- **table** (24) — OSWorld's own spreadsheet comparison (`compare_table`
  judging inline `check_cell` rules on the host; no gold file).
- **browser** (10) — OSWorld's URL matcher (`is_expected_url_pattern_match`
  over the `active_url_from_accessTree` getter).

Preferring the built-in metric where it fits means less generated code, and
grading maintained by the benchmark rather than by us. (Grade counts are
over the 206 generated; the controls below removed three, leaving the 203
that roll.)

**Tasks are self-contained.** The setup runs inside the VM as a shell command,
so the JSON carries everything it needs as text and can be handed to anyone with
an OSWorld checkout. Earlier versions pointed at a build tree on one host
machine and were not portable.

**Controls run before any rollout** (`ostg/control.py`). For each task: boot a
fresh VM, run the setup by hand and check its exit code, then call
`env.evaluate()` on the untouched desktop. An idle agent must score 0.

| set | checked | failed | setup exit ≠ 0 | scored without work |
|---|---|---|---|---|
| v8big-all | 206 | 3 | 3 | 0 |
| v8nt-opus46 | 23 | 0 | 0 | 0 |
| v8nt-opus5 | 20 | 2 | 2 | 0 |

Nothing scored above zero on an untouched desktop. Every failure was a setup
command exiting non-zero — which matters because **OSWorld never checks this**:
`_execute_setup` reads the return code only inside an `until` clause, so a task
whose setup silently failed would run to completion against a desktop that was
never prepared, and score 0 for reasons indistinguishable from a weak agent.

**Rollout ledger** (the v8 main run was stopped 2026-08-09 to hand the VMs
to the v11 chain; every stopped run heals by relaunching with the same
result directory — scored tasks are skipped, unscored ones redo):

| run | status | max steps | thinking | solved |
|---|---|---|---|---|
| v11-all (§3), no-preserve | rolling: 92 tasks (8 removed by controls) | 50 | on, history not preserved | — |
| v8big-all, think-preserve | stopped at 99 / 203 scored | 100 | on, history preserved | 24 (24%) |
| v8nt-opus46 | stopped at 8 / 23 | 50 | off | 4 |
| v8nt-opus5 | stopped at 9 / 20 | 50 | off | 3 |

The two pilots varied the model that *generated* the tasks — Opus 4.6 against
Opus 5 — holding the solving agent fixed. They were superseded by a full-corpus
replication (§10) and stopped to free the VMs; their partial numbers stand but
carry the grader-strictness confound described in §7.

---

## 2. The v9 corpus — ambiguity and voice, activated

Why: measured against the official OSWorld instructions, v8's are twice as
long (median 52 vs 26 words), carry an absolute path 87% of the time (official:
5%), open with a bare imperative 1% of the time (official: 18%), and speak in
one register — a first-person workplace persona. Fine for grading, narrow for
SFT: a model trained only on over-explicit requests never practices resolving
"fix my rota thing". The instruction's explicitness and the grader's precision
are decoupled — a probe can pin an exact path while the instruction says "the
rota spreadsheet on my desktop" — so vagueness costs no grading rigor.

Design:

- **Ambiguity joins the coordinate product** (intent × domain × difficulty ×
  ambiguity, 325 → 1300 cells), four levels with a 10/30/30/30 quota: explicit
  / functional reference / deictic (target pre-opened, "this sheet") /
  outcome-only ("get the numbers right before I resend it").
- **Voice** is derived per cell at 30/25/45: terse / polite / persona.
- **Mechanical gates**: an ambiguity≥2 instruction containing /home/user or a
  filename is rejected; deictic without open_path is rejected (grade=browser is exempt: there the start_url page is the referent).
- **Two prompt rules from the audit findings**: every countable promise is
  checked in full or not made (the partial-verdict feedback), and browser
  targets must have URLs that encode the work (query parameters a form fill
  produces), closing the navigation-only difficulty collapse.
- Same machinery, same seeds; the walk itself is not comparable to v8's (the
  space quadrupled), so cross-version pairing is reference-only.

The corpus completed at **213 specs**. Measured against v8 and the official
instructions:

| | official | v8 | v9 |
|---|---|---|---|
| median words | 26 | 52 | 56 |
| opens Please/Could | 28% | 1% | **26%** |
| first-person persona | 16% | 37% | 21% |
| contains absolute path | 5% | 87% | **12%** |

Ambiguity landed 14/31/25/29 against the 10/30/30/30 quota; every polite task
opens with Please/Could; persona fell from a monoculture to a plurality. The
one partial miss: terse tasks carry the register's tone but not its brevity
(median 47 words vs persona's 63) — the "one or two sentences" instruction is
half-obeyed, and a hard length cap is a one-line rule for the next iteration.

Three generator defects were caught and fixed during the run. One was
operational: a module-resolution mislaunch (Python puts the working
directory ahead of PYTHONPATH, so the old package shadowed the new — run
from the versioned worktree). Two were downstream of the tool schema not
being server-enforced: a spec arriving as a JSON string, and whole spec
arrays arriving as JSON strings — one shard silently discarded 17,000
string fragments before extract learned to parse both shapes back.

Postscript: the instruction review surfaced the findings that became v10
(§3), and v9 was superseded before any VM time was spent. The corpus remains
on disk, gated and mergeable.

## 3. The v10 corpus — instructions become prompts to an agent

v9 was superseded before it spent a minute of VM time. Three findings, all
measured the same day, forced a redesign:

**Finding 1 — the official family pre-opens the workspace.** 85% of
OSWorld-Verified tasks and 82% of OSWorld-V2's 108 task classes launch or
open the relevant application in their setup (multi_apps included at 77%);
only the os domain runs cold. Our self-contained tasks made the agent open
files from a bare desktop — a "first mile" the official family never tests.

**Finding 2 — the first mile was breaking our rollout.** 47% of the v8 run's
failures were byte-identical response loops burned to the step cap, against
1% on the same model over the official corpus. Attribution is two-factor:
the cold start supplies the stall (a double-click that doesn't take), and
preserve_thinking cements it (identical context re-fed, sampling collapses).
Two harness bugs surfaced in the same investigation and were fixed: an empty
model output was parsed as DONE and killed three tasks at step 1 (now WAIT),
and gate rejections were consuming difficulty quota without producing specs,
bleeding d4+d5 to 21% of a 35% target (accounting moved to keep-time).

**Finding 3 — instruction length is mostly voice, and length predicts
failure.** Pass rate falls monotonically with instruction length on BOTH
corpora — official: 58% at ≤15 words to 16% over 60; v8: 33% to 11% — and at
matched lengths the two corpora pass at the same rate, so most of the
45%-vs-22% gap was length mix, not grading. Decomposing v9's lengths at
fixed difficulty: the persona register carries a stable +18-word premium,
deictic tasks are no shorter than explicit ones (so the words are not spent
naming files), and a requirement costs only ~5-8 words. The overage was
scene-setting the prompt itself demanded.

v10 therefore changes the genre: **the instruction is what a user types AT
an agent, not a note to a colleague.** Rule 7 was rewritten positively (state
the goal and its shaping constraints; one load-bearing context clause at
most; no self-introductions, employers, or backstory), length caps scale
with difficulty (150/250/300 characters, gate-enforced), and the voice
registers are now terse 30 / sloppy 10 / polite 25 / contextful 35 — sloppy
being the lowercase fast-typer register real users produce ("need rfc 2616
on screen, official rfc-editor site not a mirror"). Persona is retired.
Deduplication pressure is explicitly forbidden from reintroducing decorative
variety: instructions stay plain even if similarity gates fire more often.

Structurally, v10 also adds the **warm-start axis** (browser and deictic
tasks forced warm, files/terminal forced cold, the free stratum drawn warm
at 65% — landing near the official family's rate, while keeping a deliberate
cold slice as trainable skill) with app-matched pre-launch (open for
LibreOffice documents, launch for chrome/gimp/vscode/vlc/thunderbird), and a
strictly monotone difficulty ladder — d3 becomes two-application, making the
corpus 40% single-app / 60% cross-app by quota.

First specs off the line: median 29 words (v9: 56), gate rejections zero
(the previous prompt's 41 rejections came from rules the model had to be
forced through; positive guidance made compliance the natural writing), all
four registers flowing.

### v11 — repair instead of reject

At scale, v10's economics broke: its top-up run burned 144 gate rejections
to keep 1.9 specs per batch, mostly on three mechanical offenses (a filename
where ambiguity forbids one, an absolute path, an over-cap instruction).
v11 answers with **R + P**, run under the identical command and seed as v10
for a paired comparison:

- **R — the repair pipeline.** A spec failing a *repairable* gate (filename,
  path, length) gets one cheap rewrite call (~200 tokens: rewrite the
  instruction only, preserving the task's meaning) and is re-gated. Setup,
  probe, and coordinates are never touched, so repair cannot alter what the
  grader checks — only how the request is worded.
- **P — inline constraints.** The per-spec character limit moves into the
  spec's own brief line; naming guidance becomes description-first ("the
  rota sheet", not `rota.xlsx`) with a ✓/✗ contrast pair at level 2.

Paired outcome: **v11 kept 7.6 specs per batch against v10's 1.9 (4x)** —
119 specs from the run v10 got 70 from — with 24 repairs used and only 26
hard skips, at equal or better gate metrics (quota drift 1% vs 4%; words
median 31; ≤25 words 34%; cross-app 60%; warm 70%). Repaired instructions
spot-checked clean against their setups: the rewrite does not drift the
task's meaning.

**What the final audit caught — three grader-defect classes the mechanical
gates cannot see.** Before merging, every spec was scanned for coherence
between instruction, setup, and probe. Eight of 119 were culled:

| class | n | example |
|---|---|---|
| near-duplicate pair (similarity gates) | 2 | two "add speaker notes to a deck" tasks, cosine 0.55 |
| rigid output naming | 4 | instruction says "leave a plain text note naming it"; probe demands exactly `missing.txt` — an agent's reasonable name fails |
| missing source data | 1 | instruction cites "my onboarding notes"; setup creates only an empty Desktop |
| dated constant vs. deictic time | 1 | instruction says "this year's viewings"; probe hard-codes `viewings_2025` on a 2026 clock |

The last three classes share a signature: the task *looks* fine, controls
pass (an idle agent still scores 0), and the rollout would report a model
failure that is actually a grader defect. They are precisely the coverage of
the LLM audit (§ positive-direction checks), which this round skipped for
speed — a mechanical scan (probe paths absent from both setup and
instruction; deictic time words against hard-coded years) substituted and is
now part of the ship checklist. The remaining 111 were trimmed to 100 by
largest-remainder allocation over difficulty × ambiguity cells, dropping the
latest-generated members, so the trim cannot skew the quotas (final drift
2%).

One more schema monster joined the §4 list during this run: the model
occasionally returns a spec as one unparseable string rather than an
object; the extractor now returns an empty batch for those instead of
char-skipping through 10,000 fragments.

### The retroactive yardstick — v8, v10, v11 and the official corpus on one scale

The acceptance battery is pure text computation, so v8 was re-measured with
it after the fact (its canonical 192-spec shard files; a first attempt that
globbed in the opus-4.6 corpora and partial regenerations produced fake
duplicate pairs — measure only the canonical set). All three generations
pass the similarity gates; the real movement is in instruction shape:

| metric (threshold) | v8 (192) | v10 (70) | v11 final (100) | official 361 |
|---|---|---|---|---|
| internal jaccard max (<0.4) | 0.30 | 0.27 | 0.35 | — |
| internal tf-idf cosine max (<0.5) | 0.45 | 0.37 | 0.49 | — |
| vs cua-gym max (<0.5) | 0.41 | 0.43 | 0.47 | — |
| vs official-361 max (<0.5) | 0.28 | — | 0.28 | — |
| distinct-bigram ratio | 0.79 | 0.88 | 0.83 | — |
| words, median | 53 | 29 | 31 | 26 |
| ≤25 words | 1% | — | 34% | ~half |
| absolute path in instruction | 87% | — | 8% | 5% |
| bare-imperative opening | 1% | — | 12% | 18% |

v11's similarity maxima sit a little higher than v8/v10 — the user-prompt
genre is shorter and lexically denser, so the corpus packs tighter — but
every value is inside the gates, after the two over-threshold pairs were
culled. The shape rows are the point: v8 read as a colleague's memo (median
53 words, an absolute path 87% of the time); v11 lands at official scale on
all three counts. Given the length-pass law (§3 finding 3), that shift is
expected to show up directly in rollout pass rate. v10's 0.88 bigram ratio
is the best of the three, but it is survivorship — 144 rejections distilled
70 specs; v11 holds 0.83 while keeping 4x as many.

### VM controls on the final 100 — and a second systematic catch

Controls (fresh VM per task: setup exit code, open execution, evaluate on
the untouched desktop) checked all 100 and removed 8:

- **7 impress tasks, one root cause.** Every deck-building setup wrote a
  text outline and converted it through `soffice --headless --convert-to
  odp`. That chain fails on every machine, not just the VM: a `.txt` loads
  into the Writer module, and Writer has no presentation export — verified
  by reproducing the failure in a fresh full-package LibreOffice container.
  The generator had extrapolated a conversion pattern the prompt's own
  examples teach (csv→xlsx, txt→odt — both real filter paths) one format
  too far, to a path that does not exist.
- **1 free-pass** (`course-code-answer-doc`): evaluate returned 1.0 on an
  untouched desktop. The probe's last line was `print('FAIL' if hit else
  'PASS')` — the ternary inverted, so an empty desktop passed and correct
  work would have failed. Exactly the SFT poison controls exist to catch.

**Mid-rollout failure adjudication** (first 26 scored, 13 passed): every
failure classifies — 6 loop-locked + 3 step-cap (model capability; the
tasks are sound), 1 environment flake (Calc did not open; agent reported it
honestly), and 3 "agent claimed done, scored 0" cases that were adjudicated
frame-by-frame from the screenshots:

- *court-portal* — genuine agent error: the note says the browser must NOT
  ask where to save; the agent read the toggle's correct OFF state and
  reasoned itself into switching it ON. A clean negation-comprehension
  failure, correctly scored 0.
- *hr-handbook-bookmark* — **harness wrongful conviction**: the step-1
  screenshot shows a bare New Tab; the `chrome_open_tabs` warm-start never
  delivered the promised page (OSWorld logs such failures without raising),
  and the agent did everything right against what it saw. Requeued.
- *depot-router* — **probe world-belief defect**: the final screenshot
  shows the exact demanded state (download dir set, ask-toggle off), but
  the probe read `prefs.get('prompt_for_download', True)` — Chrome's
  out-of-box state is that the key is absent and the UI is off, so an agent
  who finds the toggle already correct and leaves it alone can never
  materialize the key. Absent-key-default bugs are exactly the audit's
  world_assumptions class (the audit was skipped this round). A corpus-wide
  scan found precisely this one instance (its sibling probe had chosen the
  correct default); patched and requeued.

One preliminary science note: loop-lock persists at 6 of 13 failures under
**no-preserve** — close to v8's preserve-mode share — which weakens the
"preserve cements the loop" half of the §3 attribution. Full-run numbers
will settle it.

**The headless-soffice collision — the biggest mid-run catch.** When the
runner reached the calc domain the pass rate collapsed: 0 of 15, every
failure burning the full 50 steps. Screenshots told the story — Calc's
process alive, the lock file on disk, and no window anywhere: a headless
soffice left over from the setup's `--convert-to` swallows the subsequent
warm-start `open`; the document routes into the headless instance and no
window ever maps. Official calc (32% on the same VM) never trips this
because official setups `download` files rather than convert them. 23
tasks carried the pattern (13 calc, 5 writer, 5 cross-app); the emitter
now inserts `pkill -f soffice.bin; sleep 2` between such setups and their
open, and the 17 already-burned victims were requeued for the heal pass —
including tasks previously misclassified as model CAP-WANDER failures. A
first fix over-reached: the new presentation-conversion gate also killed
two healthy control-passed decks that convert via `odp:impress8` — the
filter-qualified form works; only the bare `--convert-to odp` is
impossible. The gate now distinguishes them.

Corollary for pass-rate reads mid-run: the runner walks domains in order,
so the running average swings with each domain's health — 43% at the
chrome-heavy front, 35% after the poisoned calc block. Judge the corpus on
the final number, per-domain.

**The v11.1 repair** adopts the official corpus's essence for presentation
fixtures — decks are prebuilt real files, never constructed in the VM
(official ships them via cloud `download`; all 47 official impress tasks
do). Ours stay self-contained instead of URL-dependent: the seven decks
were built as .pptx via python-pptx and converted to .odp by a real
LibreOffice in a one-shot container, verified (page counts and text against
the intended outlines), and embedded in each setup as a base64 → file
write. Probes are untouched — they read the same content.xml, now written
by LibreOffice itself. The inverted probe got its one-line flip. Guards so
the class cannot return: a gate rejects any setup converting to a
presentation format, and prompt rule 6 now states the filter boundary
explicitly. The eight repaired tasks await re-control after the current
rollout (controls and rollouts never share the machine), then a top-up into
the same result directory restores the corpus to 100.

The rollout therefore runs 92 tasks. One harness lesson from the handoff:
the runner's manifest keys tasks by uuid while control reports carry slugs —
the first "clean" manifest filtered nothing (100 tasks survived their own
exclusion), and the fix maps slug → uuid through the task JSONs' ostg block.
And a killed runner can hang for tens of minutes in graceful cleanup
(recordings, container teardown) while still matching pgrep — bound the
wait, then SIGKILL and stop containers by hand.

## 4. How a task is specified

Generation does not ask for "a task". It draws a **coordinate** and asks for a
task at that coordinate, so a run walks a product space instead of returning to
whatever the model finds most natural.

**Intent** — what kind of work it is. Five values:

| intent | the agent must |
|---|---|
| `info_seeking` | find something in the environment and report it |
| `transform` | convert or restructure existing content |
| `configure` | put an application into a described state |
| `create` | produce an artifact that did not exist |
| `repair` | fix something already wrong |

**Domain** — the professional setting the scenario is dressed in: finance,
healthcare, education, logistics, human resources, legal, marketing, scientific
research, retail, real estate, travel, manufacturing. This axis exists for
surface variety; it should not affect difficulty, and measurement says it does
not.

**Difficulty** — 1 to 5, defined by *structure*, not by adjectives:

| level | definition |
|---|---|
| 1 | one application, one requirement |
| 2 | one application, two or three requirements that must all hold |
| 3 | one application and four or more requirements including an ordering or tie-breaking rule; or two applications with one to three |
| 4 | two applications and four or more requirements including an ordering rule; or three applications with one to three |
| 5 | three or more applications, four or more requirements, including an ordering or tie-breaking rule |

Levels 4 and 5 exist to find where the model breaks, so a quota keeps them a
minority: 15 / 25 / 25 / 20 / 15 percent.

This definition is itself an experiment result. v3 used a bare requirement count
as its difficulty axis and the rollout showed that count does not predict
success (section 5). Application count was folded in because that is what
actually separates easy from hard.

**Artifact host** — where the answer must end up: spreadsheet, text document,
slide deck, source code, raster image, PDF or archive, filesystem, preference
store, browser tab, terminal output, app data store, desktop session. Each
intent may only end in artifacts that make sense for it, and the host determines
which grading route applies.

**A fourth axis, ambiguity, is defined but not yet crossed in.** The probe
decides alone, so today every instruction must name one unambiguous end state.
Using it means changing the prompt and the grader together.

Generation is sharded: N processes take disjoint slices of the coordinate
product and run at once. The partition is permuted before striding — a raw
stride aligns with the innermost axis and would hand one process a single
difficulty level — and the permutation seed is a constant, so every process
derives the same partition.

---

## 5. How duplication is measured

Generated tasks must not restate what a benchmark already contains, and must not
restate each other. Three detectors, chosen because each is blind to something
the others catch.

**1. Jaccard over instruction tokens.** Set overlap of the vocabulary. Catches
tasks that reuse the same words. Cheap, and insensitive to how common those
words are — "the file" counts as much as "amortisation".

**2. TF-IDF cosine over instructions.** Weights each token by how rare it is
across the corpus, so sharing a distinctive word counts for more than sharing a
common one. This is the primary text detector and the one used against external
corpora. It ranks pairs differently from Jaccard, which is the point: one pair
that scored 0.37 by Jaccard scores 0.52 here.

**3. Grader signature — what the probe reads.** A fingerprint of the paths,
keys and fields a task's grading code touches. This catches re-dressed
duplicates: two tasks whose nouns all changed but which check the same thing in
the same place.

The third is used **only within a generated set, never against external
corpora**, and as a grouping aid rather than a gate. Two reasons, both measured.
OSWorld's tasks have no probes to sign. And signatures were tested for
cross-corpus transfer and failed: the measurement returned 0.097 with the true
match ranked 1254th, because signature vocabulary is a property of who wrote the
grader, not of what the task is about.

Thresholds: Jaccard pairs at or above 0.4 and TF-IDF pairs at or above 0.5 are
flagged inside a set; against an external corpus, 0.5 is the review line.
Signature pairs are grouped at a measured knee of 0.30. Flagged pairs are
reviewed by hand, with the earlier-generated task kept.

### What v8's 211 tasks score

Every detector passes, with no pair reaching its threshold:

| detector | max | p90 | over threshold |
|---|---|---|---|
| within-set jaccard | 0.38 | 0.10 | 0 at ≥ 0.4 |
| within-set TF-IDF | 0.45 | 0.09 | 0 at ≥ 0.5 |
| vs CUA-Gym (10,909 refs) | 0.41 | 0.25 | 0 at ≥ 0.5 |
| vs OSWorld (369 refs) | 0.28 | 0.17 | 0 at ≥ 0.5 |

**CUA-Gym constrains this work; OSWorld does not.** Its p90 is 0.25 against
OSWorld's 0.17, and it has thirty times the tasks over nearly the same
applications. The earlier v3 measurement said the same thing at a smaller scale
(0.13 median against 0.07).

The closest within-set pair shows why two text detectors are worth running:

    iab-tcf-v2-2-spec-page ~ iab-tcf-v2-2-policy-spec-page
    TF-IDF 0.45, jaccard 0.23

They share one rare term. Jaccard barely registers it against everything else in
the two instructions; TF-IDF weights it heavily and surfaces the pair — and it
is a real cluster, with a third member scoring 0.40 against both.

The signature detector flagged 416 pairs at or above 0.30, which is why it is a
grouping aid and not a gate. Its top pairs — `clinic-vitals-days-since-visit`
against `till-returns-reconcile-fix` at 0.67 — are unrelated scenarios whose
probes happen to read a table and compute a difference. That is the detector
behaving as designed: it describes the grading code, not the task.

### Similarity does not predict solvability

Across the 74-task v3 rollout, external similarity was 0.131 among solved tasks
and 0.138 among failures. Pushing tasks away from existing benchmarks costs
nothing in yield.

---

## 6. What each round established

**v2** (29 tasks) — first end-to-end generation. Established that the four-field
contract works at all.

**v3** (185 tasks, 74 rolled out) — the round that produced most of the evidence
in section 5. Also the round whose build-time controls caught **21 tasks whose
grader disagreed with its own reference solution**, fifteen of them from one
cause: the probe reached for a path directly instead of through the helper that
resolves it. That check costs a second on the host against 15–25 minutes of VM
time to find the same defect from a rollout.

**v4** (200 tasks) — a larger draw on the v3 design; generated, never compiled,
superseded.

**v5** (20 tasks, control) — introduced the structural difficulty definition now
in section 2, and moved the prompt out of Python into a file so it could be
diffed.

**v6** (15 tasks, control) — the self-contained-JSON contract: setup moves into
the VM, `solve_py` disappears. Measured against v5 at the same coordinates,
grading code per task fell from 2,260 characters to 820. Instructions fell from
704 to 321, but that belongs to a 300-character budget written into v6's prompt
and not v5's — two variables moved at once and the honest attribution is to the
rule, not the contract.

**v7** — built-in metric dispatch: emit `func`/`result`/`rules` when an OSWorld
metric fits, a probe otherwise. Wired through prompt, schema and emitter; never
generated a batch. v8 carries the idea into production.

**v8** — section 1.

---

## 7. What the 74-task rollout showed

Qwen3.6-27B BF16 on one H200, screenshot observation, pyautogui, 100-step cap,
1920×1080, temperature 0.6. **26 of 74 solved (35%).**

### Application dominates everything else

| application | solved |
|---|---|
| os | 4 / 5 — 80% |
| chrome | 14 / 27 — 52% |
| libreoffice_calc | 4 / 31 — 13% |

A six-fold spread. The same agent scores 78% on official OSWorld Chrome tasks
and 32% on official Calc tasks — ours are about 20 points harder in both, but
the ordering matches, so the gap is task shape rather than one application being
written badly.

### Instruction length predicts success, monotonically

| instruction length | solved |
|---|---|
| under 350 characters | 8 / 16 — 50% |
| 350–600 | 13 / 38 — 34% |
| over 600 | 3 / 17 — 18% |

The mechanism is visible in the trajectories. Long instructions are long because
they inline data — one listed ten clinics with two figures each, twenty numbers
the agent had to type by hand. It succeeded, in 100 steps, repeating the same
action 33 times. The fastest success took 7 steps.

This drove a generator rule: instructions are budgeted at roughly 300
characters, and more than six values must go in a file the agent opens.
Measured effect on generation — inline numbers per instruction fell from a p90
of 13 to 1.

### Requirement count does not predict difficulty

1 → 58%, 2 → 29%, 3 → 32%, 4 → 27%. Not monotonic, and the easiest bucket is
mostly Chrome configuration tasks, so what looks like difficulty is the
application effect in disguise. This is why difficulty was redefined structurally.

### Intent points the same way

`configure` 70% · `create` 38% · `transform` 30% · `info_seeking` 24% ·
`repair` 23%. Configuration tasks end in a settings value and have short action
paths.

### The graders that passed their controls hold up

A Chrome settings probe checks both `Preferences` and `Secure Preferences`,
globs across profile directories, and normalises paths before comparing. A
three-requirement task falls back to a second key name for the password setting,
because Chrome renamed it between versions. These are not naive string
comparisons.

---

## 8. What running it costs

Measured over 74 tasks and 3,566 steps.

| | tasks | median steps | median duration | total |
|---|---|---|---|---|
| solved | 24 | 23 | 4.7 min | 2.6 h |
| failed | 45 | 64 | 16.1 min | 11.8 h |

**82% of machine time goes to tasks that produce no training data.** The 16
tasks that hit the 100-step cap consumed half the total time and yielded one
success between them.

Per-step latency is 14.6 s. The input side dominates: up to 20 screenshots per
request at roughly 1,500–2,500 tokens each, against a measured p90 output of 143
tokens — about 300:1.

Concurrency scales poorly. Going from 2 to 3 simultaneous tasks raised per-step
latency 35% (11.4 s → 15.4 s) and throughput only 11% (10.5 → 11.7 steps/min);
linear scaling would have given 15.8. The model server is the bottleneck, not
the VMs.

Two fixed costs per task come from OSWorld itself: a 60-second wait after setup
before the first observation, added upstream because `reset()` returned a
screenshot of a half-drawn desktop, and 20 seconds before evaluation so the last
action's writes land.

---

## 9. Thinking mode was inert until v8

Every run before v8, **including the official 361-task campaign**, ran without
thinking despite passing `--enable_thinking`. The agent honours that flag only
when the base URL contains "dashscope"; against a local vLLM server it is
silently discarded. Confirmed empirically: zero thinking traces in 7,906 sampled
steps of the official campaign and 3,754 steps of the v3 run.

v8 fixed it, in two independent places. `mm_agents/qwen/main.py` now sends
`chat_template_kwargs` — the form vLLM reads — including `preserve_thinking`,
which keeps reasoning from earlier turns instead of stripping all but the last.
And `client.py` had a second, separate break on the read path: vLLM 0.25
renamed the response field `reasoning_content` to `reasoning`, so even when the
server extracted reasoning, the client read the old name, got None, and
silently discarded it — thinking was generated, paid for, and thrown away in
every prior run. The client now reads both names. Verified: 233 of 233 steps
in the running rollout carry a `<think>` block. Those two files are a new local
modification of the OSWorld checkout and are not yet in its documented list of
local changes.

Related: `max_tokens` was 81920 in every run. That is not a model limit — the
model imposes none and its context is 262,144. Measured p90 output is 143 tokens
and the longest response ever produced was about 2,294. OSWorld's own defaults
are 1500 and 32768.

---

## 10. Why the tasks come from Opus 5 rather than Opus 4.6

Two rounds of evidence, one small and one at scale. The small round (20 vs 23
tasks, §6–7) produced the initial verdict. The 2026-08-09 replication then
regenerated the **entire corpus** with Opus 4.6 under the same seeds — the same
coordinate walk through the cell product, batch for batch, so the generating
model is the only variable. 207 specs came back (Opus 5: 206), at half the
wall-clock (~1.3 h vs ~2.6 h) and half the price.

| | Opus 5 | Opus 4.6 |
|---|---|---|
| hard duplicate pairs (jaccard ≥ .4 / cosine ≥ .5) | 1 + 1 | 3 + 2 (max j = .62) |
| grader-signature pairs ≥ .30 (review band) | 416 | 363 |
| probe size at d5 (avg lines / comparisons) | 39 / 8.8 | 71 / 12.1 |
| worst benchmark proximity (cua-gym / OSWorld-361) | .41 / .28 | .43 / .27 |
| entity reuse ≥ 3 tasks / distinct-bigram ratio | 14 / .79 | 26 / .75 |
| setups written as `python3 -c` | 76% | 61% |

The deciding argument is not any single row; it is the **shape of each model's
characteristic defect**:

- Opus 5's defect is *mechanical*: escaping slips inside setup strings (2 of 20
  in the pilot). A static compile gate now catches the whole class; zero have
  shipped since.
- Opus 4.6's defect is *semantic*: re-dressed duplicates (3 hard pairs at
  scale, the same habit first flagged at n = 43) and, in the pilot, one task
  close enough to a public benchmark to be excluded (0.53 against cua-gym).
  No mechanical gate catches either kind; every instance costs a human or a
  second model to adjudicate.

A defect class that can be gated is strictly cheaper than one that must be
adjudicated. That asymmetry — not the row-by-row scores — is the choice.

Two findings cut against the choice and are recorded rather than hidden. At
scale, Opus 4.6's probes are *longer* and carry *more* comparisons; the pilot's
impression that Opus 5 probes deeper does not survive n = 200 — though length
is not correctness, and the one paired-rollout anecdote (§7's PDF-export pair)
had 4.6 checking file existence where Opus 5 verified file content. And 4.6
generates at half the cost. A bidirectional blind audit — each model reviewing
the other's corpus for instruction–grader divergence — is in flight as of this
writing; if it favours 4.6, this decision should be revisited.

One further result changes what the choice even means: aligned cell for cell,
the two corpora barely overlap (same-cell instruction jaccard median .14, n=45
aligned pairs; cross-corpus nearest-neighbour cosine median .16). The
coordinate dictates intent, app and difficulty; the model supplies the task's
identity. The corpora are **complements, not substitutes** — a merged ~400-task
pool exists if ever wanted, at the price of running the 4.6 half through the
same VM controls.

**The bidirectional audit landed 2026-08-09 and closed the revisit clause.**
Each model blind-reviewed the other's corpus for instruction–grader coverage
(one call per task; the 4.6-as-judge side was calibrated first — it
independently re-found all three defects we had confirmed by hand, including
the example.com gold error). Verdict rates:

| | Opus 5 tasks (4.6 judging) | Opus 4.6 tasks (Opus 5 judging) |
|---|---|---|
| covered | 35% | 15% |
| partial (grader under-checks) | 37% | **82%** |
| overreach (grader over-demands) | 28% | 3% |
| missing items per task | 0.8 | **4.3** |

The judges differ, so judge severity is confounded with corpus quality and the
absolute gap should be discounted. Two things survive the confound. First, the
failure *styles* are opposite: Opus 5's graders err toward overreach (false
FAILs — wasted trajectories), 4.6's toward partial (false PASSes — poisoned
labels), and for SFT harvesting a false PASS is strictly worse than a false
FAIL. Second, the per-grade split: 4.6 went 10/10 partial on browser tasks and
21/23 on table tasks — it keeps writing promises into instructions that the
fixed grader templates cannot check. Both agree with the pilot's PDF-export
anecdote. The decision stands.

**A common judge removed the confound.** Sonnet 4.6 then audited both corpora
under the identical rubric — four audits in total:

| judge → corpus | covered | partial | overreach | missing/task |
|---|---|---|---|---|
| Opus 4.6 → Opus 5 set | 35% | 36% | 27% | 0.8 |
| Opus 5 → 4.6 set | 14% | 81% | 3% | 4.3 |
| Sonnet 4.6 → Opus 5 set | 26% | 70% | 2% | **2.0** |
| Sonnet 4.6 → 4.6 set | 17% | 80% | 1% | **3.1** |

Same judge, same severity: the Opus 5 corpus carries ~35% fewer coverage gaps
(2.0 vs 3.1 missing items per task; covered 26% vs 17%). The direction of the
cross-audit holds; its size does not — the true gap is ~1.5x, not the ~5x the
asymmetric table implied, because Opus 4.6 judges softly (0.8/task on the same
corpus where Sonnet finds 2.0) and Opus 5 judges harshly (4.3 where Sonnet
finds 3.1). Decision unchanged; future audits should use a fixed third-party
judge so rates stay comparable across corpora.

Operationally, Sonnet's stricter pass is the quarantine input for SFT
harvesting: on the v8 corpus it flags 145 tasks partial — 120 of the
under-verifying kind, where a lazy agent could pass — and 11 with fragile
world assumptions. These cross with rollout scores when trajectories are
harvested: passed-but-quarantined gets extra review; failed-on-overreach
becomes the false-FAIL rescue list.

---

## 11. PLANNED — run Qwen3.8-27B over the same 544 tasks

Proposed 2026-08-14. **Not started.** Written down before any work because
step 0 is verification, and because the sequencing matters more than the run.

### What Qwen3.8-27B actually is (read from the model card 2026-08-14, not assumed)

Released 2026-08-14 15:00 UTC. https://huggingface.co/Qwen/Qwen3.8-27B

| | |
|---|---|
| parameters / licence | 27.78 B, Apache 2.0 |
| **modality** | **text + image + video** — usable by this screenshot-driven pipeline |
| context | 262,144 native — matches the `--max-model-len` already in the serve |
| architecture | 64 layers = **48 Gated DeltaNet (linear) + 16 Gated Attention**, a 3:1 ratio — structurally the same shape as Qwen3.5-4B's 24:8 |
| vocab | **248,320 — identical to Qwen3.5-4B** |
| reported OSWorld | **84.3%** |

**Two operational catches, both easy to get wrong by carrying over 3.6's setup:**

1. **The recommended sampling differs.** Thinking mode is
   `temperature=1.0, top_p=0.95, top_k=20, presence_penalty=0.0`. The current
   campaign runs Qwen3.6 at **temperature 0.6**, and we run with
   `--enable_thinking`. Carrying 0.6 over is an unverified deviation from the
   vendor's recommendation — decide deliberately, and record which was used.
2. **No official FP8 is advertised** (218 community quantisations exist). FP8
   bought 1.39–1.51× on Qwen3.6; here it may need a community checkpoint or a
   self-made quantisation, and that needs its own verification.

**Do not read 84.3% as a prediction for our corpus.** Our Qwen3.6 number
(45.2% on OSWorld-Verified) comes from our harness at a 50-step budget over 312
non-proxy tasks; vendor OSWorld figures generally use larger budgets and their
own scaffolding. The two are not the same measurement. It is a strong signal,
not a forecast.

### Why it is worth the ~42 hours

Three separate questions, and the third is the one that would change the SFT
line:

1. **Do these tasks discriminate?** Qwen3.6-27B scores 39% on v11-100 and ~24%
   on v11-500. If a stronger model scores substantially higher, the corpus is
   measuring capability. If it scores the same, the tasks are gated on something
   else — environment flakiness, instruction ambiguity, grader strictness — and
   that is a finding about the generator, not the model.
2. **A better teacher means more and cleaner SFT data.** At 24% the v11-500
   rollout yields ~107 usable trajectories from 444 tasks. A higher pass rate
   raises the corpus without generating a single new task.
3. **Does the failure mechanism change?** This is the important one.
   `outdated/docs/SFT_TRAINING_20260822.md` measures that after an action that changes nothing on
   screen, Qwen3.6 repeats it **85%** of the time — and since only successful
   trajectories become training data, *repetition is the only failure response
   the data can teach*. The student inherits the habit without the accuracy and
   loops. **If a stronger teacher recovers instead of repeating, its
   trajectories would carry the one behaviour the corpus currently cannot
   teach.** Measure this before pass rate.

### Step 0 — verify, before allocating anything

| check | why it can stop the plan |
|---|---|
| does a ~27B variant exist, and is it **vision-language**? | the whole rollout is screenshot-driven; a text-only model is unusable here |
| weights available / licence / gated? | — |
| vLLM version required; does the current serve env support the arch? | Qwen3.5 needed `transformers>=5.9`; a new arch may need newer still |
| new kernels? | Qwen3.5 needed `flash-linear-attention` + `causal_conv1d`. Budget a build job; ours took three attempts and an hour (`outdated/docs/SFT_TRAINING_20260822.md`) |
| official FP8 checkpoint? | FP8 measured **1.39–1.51×** on Qwen3.6 (`logs/fp8_ab.log`); worth having from the start |
| **official sampling recommendation** | Qwen3.5's is temp 0.6 / top_p 0.95 / top_k 20. Do **not** carry that over by assumption |

Disk is not a constraint: `/gpfs/scrubbed` has 523 T free.

### Step 1 — the dialect check, on 5 tasks, before the campaign

The single most likely silent failure. The rollout depends on
`mm_agents/qwen/`'s `build_internal_tools_def` + `parse_internal_response`, and
a different model may emit a different tool-call dialect or hallucinate
undeclared actions. Qwen3.6 hallucinated `answer` and `screenshot`, both of
which fell into the empty-response fallback and became `WAIT` — **an infinite
loop that looked like the model being slow**, and it cost 106 wasted steps
before anyone noticed.

Run 5 tasks and check:
- `grep "unhandled action" runtime.log` — the warning added to `actions.py`
- whether `OSTG_PARAM_DIALECT=inline` is needed (the shim already exists)
- that `terminate` actually appears

### Step 2 — sequencing: do NOT switch mid-corpus

Qwen3.6's v11-500 pass is at 237/444. **Finish it first**, so the 3.6 column is
a complete reference, then run 3.8 as a clean second pass into its own result
dir. Mixing two models inside one result directory repeats the mistake that
`PRECISION_BOUNDARY.json` exists to record, and this time the difference would
be the thing under study rather than a footnote.

Record a `MODEL_BOUNDARY.json` in the new run alongside the args.

### Step 3 — what to measure, and why not just pass rate

Report these *before* the headline number, because they are what survived the
variance problem on the 9-task panel:

| metric | why |
|---|---|
| **dead-end rate** — steps whose screenshot equals the previous one | Qwen3.6: measured on the eval panel; the driver of the student's collapse |
| **repeat-after-dead-end** | Qwen3.6 = 85%. **The number that decides whether a better teacher fixes SFT** |
| **terminate rate** | Qwen3.6 = 85% (v11) / 81% (v11-500) of passing trajectories |
| **state revisitation** | separates looping from working: 0.02 on passed vs 0.56 on failed tasks for one arm |
| steps to solve | shorter demonstrations are better training data |

### Cost and what it blocks

544 tasks (v11 100 + v11-500 444) at the measured **13 tasks/h on 3 VMs ≈ 42 h**,
plus serve GPU hours. It occupies all three VMs for that whole time, so tier-3
evals and any other rollout must be scheduled around it.

### The statistics, done rather than asserted

An earlier draft said "544 tasks makes a few-percent difference meaningful".
That was loose, and pooling the two corpora was wrong — v11 runs at 39% and
v11-500 at 24%, so they are two populations and must be reported separately.

Standard error of a single arm's pass rate, `sqrt(p(1-p)/n)`:

| comparison | n | p | SE | 95% CI |
|---|---:|---:|---:|---|
| the 9-task tier-3 panel | 9 | ~0.25 | **14.4%** | **±2.5 tasks** |
| v11 | 100 | 0.39 | 4.9% | ±9.6% |
| v11-500 | 444 | 0.24 | **2.0%** | **±4.0%** |

The panel's ±2.5 tasks is exactly the 0/1/2 spread measured across three seeds
on 2026-08-14. That is not bad luck, it is what n=9 gives.

**Unpaired** comparison of two models on v11-500: SE of the difference is
`sqrt(2)·2.0% ≈ 2.9%`, so a gap needs to exceed **~5.6 points (≈25 tasks)** to
reach two standard errors. Not "a few percent".

**Paired is the design we actually have** — both models run the identical task
set — so use McNemar on the discordant tasks and the task-difficulty variance
drops out. If 3.6 scores 24% and 3.8 scores substantially higher, the discordant
count will be large and the test decisive. Report the paired result; the
unpaired figure above is the conservative floor.

**What 42 hours buys is n=544 once.** Run-to-run variance is not eliminated by
task count, and repeating a full campaign is expensive — the paired design is
what makes a single pass informative, because both models meet the same tasks.

### One open question it raises

The student is Qwen3.5-4B. Moving the teacher to 3.8 widens the
teacher→student capability gap, and distillation across a wider gap is not
automatically better. If a 3.8-4B exists, whether the student should move too is
a separate decision — and it would invalidate every arm in the current registry
for comparison purposes.

## 11b. Qwen3.8-27B first 40 tasks — it is not the config

Written 2026-08-14 while `v11-100-t1-20260814` was mid-flight (40/100 scored),
because the suspicion was that a mis-set config was depressing results. It was
not. **Paired on the identical 40 task ids** against Qwen3.6's
`v11-all-ms50-think-nopreserve-20260809`:

| | mean | exact 1.0 |
|---|---|---|
| Qwen3.6-27B | 0.3750 | 15 / 40 |
| **Qwen3.8-27B** | **0.7500** | **30 / 40** |

**Better on 15, worse on 0, tied on 25.** Exactly double the mean with zero
regressions. Partial batch, dispatched in manifest order, so the remaining 60
could move it — but a 0-regression split is not what a broken config looks like.

### Category analysis of v11-100 under 3.8: four paradigms (2026-08-15)

**① CORRECTED (user caught the confound): difficulty and app_count are
perfectly confounded by design** — diff 1–2 are all 1-app, 3–4 all 2-app, 5
all 3-app. The monotone pass curve therefore decomposes into two claims:
(a) the app-count ladder works (82→73→31%, a designed effect, validated);
(b) the WITHIN-tier grading carries the label's independent information:
diff1 88% vs diff2 78% (3.6: 50 vs 48) and diff3 75% vs diff4 71% (3.6: 46 vs
33) — all four comparisons directionally right but n≈20 per cell, mostly
within noise except 3.6's 46-vs-33. Paper wording: "a two-level difficulty
design (app-count tiers + within-tier grading) with monotone pass rates on two
teacher generations; within-tier validity pending the 444-task sample."

**② Ambiguity hurts monotonically (90→74→72→57%); voice is flat (67–74%)** —
robust to phrasing style, sensitive to actual under-specification.

**③ 3.8's gains concentrate in precise structured work.** table grading
9→73%, calc 7→60%, configure 24→60%, os 23→69%, vs_code 46→88% — while
browser (60=60), thunderbird (25=25) and gimp (n=3, 100=100) did not move.

**④ Residual weakness portrait: vlc 25% (passing runs grind to median 35
steps), thunderbird 25%, impress 44%, 3-app 31%** — niche media apps plus
cross-app orchestration, not uniform hardness.

**⑤ The 3-app cliff is a bookkeeping failure, not an acting failure.**
Failure-mode dissection: diff 1–4 failures are scattered early stops (0–3
wall-hits per tier); diff-5's 11 failures split 4 horizon-exhausted / 7 early
stops, and **6 of those 7 end in a confident completion claim** (3×
terminate:success, 3× prose "task complete") at steps 16–37 — most of the work
done, one cross-app thread dropped, conjunctive probe says 0. Contributing
mechanics: the early-stop points (23–37 steps) all sit past the image_max=20
folding boundary, so the first app's states have left the visual window; and
the failing runs skip the cross-app re-verification the passing runs perform.
Model-independent (3.6 shows the same cliff shape 33→12%). Corollaries: the
five diff-5 passes are the corpus's most precious demonstrations (the only
ones showing cross-app bookkeeping plus pre-close verification), and
"cliff = bookkeeping" is itself a paper-able observation with a built-in
testbed from the 3-app generator.

SFT corollary: the 69-trajectory corpus skews easy/single-app by construction
(88% of diff-1 tasks contribute vs 31% of diff-5) — the student's demonstrated
distribution is easier than the task distribution; the teacher-regenerates-
failures loop is the standing answer.
### Data quality, side by side (measured at 84/100, 2026-08-14 23:10)

Same 100 tasks, same runner, same 3 envs. Every number from the trajectories
themselves:

| metric | 3.6 v11-100 | **3.8 v11-100** |
|---|---|---|
| perfect (1.0) | 39 / 100 | **57 / 84 so far** |
| steps/task med / p90 | 43 / 50 | **16 / 48** |
| perfect-trajectory steps median | 21 | **15** |
| hit the 50-step wall | 48% | **10%** |
| wall-hitters scored 1.0 (poison) | 6 | **1** |
| WAIT share of steps | 10.3% | **7.3%** |
| · model's own `wait` | 223 | 75 |
| · declared-but-unimplemented → WAIT | 124 | 51 |
| · empty response → WAIT | 9 | **0** (empty → DONE now) |
| steps naming an UNDECLARED action | 106 (3.1%) — all `answer` | **0** |
| tasks ending in ≥5 identical repeats | **29** (worst: 50×) | **0** (worst: 2) |
| think chars med / p90 | 356 / 784 | 260 / **2611** |

Cross-check: the 3.6 columns reproduce the 2026-08-13 WAIT audit exactly
(223 + 106 + 18 + 9), so the classifier agrees with the hand audit.

**What this means for the SFT corpus:**
- **The `answer` hallucination is extinct in 3.8** — zero undeclared-action
  steps against 3.6's 106. Nothing for the hallucination filter to drop.
- **Tail grinding is extinct** — 0 tasks end in ≥5 identical repeats against
  29 (one of which repeated its final action 50 times). `identical_runs` and
  `low_diversity_tail` will fire rarely if at all on this corpus.
- **Poison wall-1.0s down 6×** (6 → 1); the single survivor still needs the
  build-time check.
- **More and shorter demonstrations**: 57 perfects already (vs 39 total) at
  median 15 steps (vs 21) — more tasks demonstrated, less filler per
  demonstration.
- The one regression: the **xhigh thinking tail** (p90 2,611 chars vs 784).
  Whether long deliberation in labels helps or hurts a 4B student is exactly
  the reasoning-effort A/B already queued.

### Throughput: 3.7× the 3.6 campaign, decomposed

Measured at 72/100 (2026-08-14 22:05), both runs 3 envs / ms50:

| | 3.6 v11-100 (sleep 1) | 3.8 v11-100 (sleep 3) |
|---|---|---|
| tasks/hour | 4.9 (20.3 h for 100) | **18.0** |
| steps/task median / mean | 43 / 34.7 | **16 / 20.1** |
| episodes at the 50-step wall | 48% | 7% |
| wall-seconds per step (per env) | 63 | 29 |

Two multiplicative factors: **×1.7 from steps-per-task collapsing** (the DONE
revert ends prose-completions immediately, and the model actually finishes —
48% → 7% wall-hitters), and **×2.2 from per-step wall time** — which is NOT
cleanly attributable to the model: the 3.6 span crossed a night with serve
wall-expiry and tunnel dead time baked in, while 3.8's 4 hours were one clean
evening window. Projection: v11-500 (444 tasks) in ~25 h at this rate.

### Effective sampling of the 3.8 campaign, top_k included

The client (`_build_payload`) sends only `temperature`, `top_p`, `max_tokens` —
grep confirms **no `top_k` anywhere in `mm_agents/qwen/`** — so every parameter
the client omits falls through to the serve's `--override-generation-config`.
Effective sampling therefore is: **temperature 1.0 · top_p 0.95 · top_k 20 ·
min_p 0 · presence 0 · repetition 1.0** — Qwen's published "general thinking"
profile, exactly as recorded in the result dir's `MODEL_BOUNDARY.json`. The
top_k 20 is live, by serve default rather than by client request.

### Where a step's 16 seconds actually go (measured 2026-08-14)

Sources: traj timestamps (n=1,473 inter-step gaps), the live serve's own log,
and a timed streaming request with a real 12-image payload through the tunnel.

Step cycle: **p10 8.8s · median 16.0s · p90 37.3s · mean 22.7s.** Budget for a
median mid-episode step (~12 images ≈ 32k prompt tokens):

| component | measured | median step | p90 step |
|---|---|---:|---:|
| VM side: pyautogui exec + **sleep 3.0** + screenshot fetch + client overhead | cycle − LLM roundtrip | **~8s** | ~8s |
| upload (12 imgs × 319 KB b64 = 3.9 MB; 20 imgs = 6.4 MB) | inside TTFT | ~1s | ~1.5s |
| **prefill — recomputed from zero every step** | TTFT cold 3.94s / warm 2.70s | **~3s** | ~5s |
| decode · thinking (median 260 chars, p90 2,607) | 50.7 tok/s solo, ~30–40 under 3-way load | ~2s | **~17s** |
| decode · visible (median 263 chars, p90 574) | same | ~2s | ~4s |

Server facts from the log: prompt throughput 5–7.6k tok/s (chunked prefill,
8,192-token budget), generation 70–150 tok/s across 3 requests, GPU KV usage
~8%, **MM cache hit 91.4%** (vision features cached) but
**`enable_prefix_caching=False`, prefix hit 0.0%** — every step re-prefills the
entire conversation. vLLM defaults APC on in V1; it auto-disabled here, almost
certainly because Qwen3.8 is a hybrid Gated-DeltaNet architecture (the log's
splitting ops include `qwen_gdn_attention_core`) whose linear-attention state
was not prefix-cacheable in vLLM 0.25.1.

**Levers, ranked by seconds-per-step:**
1. **Thinking tail** (p90 17s): `reasoning_effort medium` instead of the
   template's default xhigh — already queued as the post-campaign A/B; this is
   its speed half.
2. **VM side 8s**, of which sleep 3.0 is deliberate (upstream-documented; the
   authors use 5) — not an error, but the single biggest fixed cost. sleep 1
   would cut ~12% of median cycle at fidelity risk.
3. **Prefill ~3s**: prefix caching would eliminate most of it; check whether a
   newer vLLM supports APC for GDN hybrids before the next campaign.
4. **image_max 20 → 5** halves prefill + upload AND is the quality experiment
   OpenWebRL's 1-image 4B already supports. Speed and science point the same way.
5. num_envs 3 → 4 (+33%) stays blocked by the 22 GB WSL ceiling (§6.5 decision).

### The DONE revert is doing the right thing, for a reason nobody predicted

The `actions.py` fallback was reverted to upstream's `DONE` earlier the same day.
Classifying all 40 finished episodes by their **final** step:

| how the episode ended | n | mean | exact 1.0 | median steps |
|---|---:|---:|---:|---:|
| prose completion, no tool call → **DONE** | 27 | **0.815** | 22 | 15 |
| explicit `terminate` | 7 | 0.857 | 6 | 48 |
| `call_user` (undeclared → DONE) | 3 | 0.667 | 2 | 33 |
| ran out of steps | 2 | 0.000 | 0 | 52 |
| `screenshot` (undeclared → DONE) | 1 | 0.000 | 0 | 58 |

**The single largest ending — 27 of 40 — is the model writing "The task is
complete." in prose and emitting no tool call at all.** Those score 0.815 with 22
perfect, and they finish in a median of 15 steps against `terminate`'s 48. Under
the old WAIT patch every one of them would have looped to the 50-step wall,
burning ~35 wasted steps each with a live VM still able to disturb the final
state. Reverting to DONE converts a silent stall into a clean, correctly-scored
stop.

The cost is the last two rows: 4 episodes ended on an action the internal parser
has no branch for, and 2 of those scored 0. **The authors' own runs show what the
alternative looks like** — sampling 12 qwen3.7-plus trajectories from their
release, `screenshot` appears 4 times and every one is logged as `action: WAIT`
with the episode continuing (3 of the 4 were at step 1, so under DONE those tasks
would have died on their first action). So WAIT is right for `screenshot` and
DONE is right for prose-completion, and the current all-or-nothing fallback
cannot be both.

**The targeted fix, if it is ever worth making:** give `screenshot` its own
branch returning WAIT — it is a declared action in `build_internal_tools_def`
that the parser simply never implemented, so this is filling a hole, not adding
behaviour — and leave the fallback at DONE. That is one `elif`, it changes
nothing about prose-completion, and it removes the only measured way this harness
kills a healthy episode. **Not applied**: the campaign is mid-flight and a
harness change would split the batch. Revisit between campaigns.

## 11c. v11q-500: the same 500 cells, generated by Qwen3.8-Max (launched 2026-08-15)

User hypothesis: a generator from the solver's own family has an implicit
calibration of what the family can do — tasks should land better on the
teacher's ability band. Design: **regenerate the v500 coordinate space with
qwen3.8-max as the only changed variable.**

- Invocation identical to the original v500 run (from its logs): `--n 5
  --batches 29 --shard I/4` × 4 shards, same seed 20260812. **CORRECTED
  twice — final verified story (2026-08-15):** (a) **Lineage verified**:
  `v500-s*` IS v11-500's generation — per-shard spec counts and slug sets
  identical to `v11-500-s*` (443=443) and v11-500-final traces back 441/441,
  so the raw-spec comparison base was right all along. (b) **Taxonomy did NOT
  drift** (earlier speculation wrong): the v500 logs' own domain census
  equals today's 13 domains verbatim, and taxonomy.py's mtime predates both
  runs. (c) The 446-vs-325 budget gap lives in **gen.py itself drifting
  untracked** between Aug 12 and Aug 15: the v500 log opens with a
  "[gen] args:" startup line no surviving gen.py prints, and today's
  spent-set walk is strictly once-per-triple — Opus shards kept 112 specs
  over 81-triple partitions, impossible under today's code. Third
  archaeology failure in one day; **the taskgen repo is now under git**
  (first commit `141916e`, code only, outputs ignored).
- **Route-A forensics complete (2026-08-15), from the surviving Aug-11
  bytecode** (`fossils/ostg-v11.1-pycache/`, commit `f05de82`): the old
  gen.py carried two since-deleted flags, `--spent-from` and `--start-batch`,
  and its walk **sampled triples with replacement per batch** (spent only if
  injected) — 145 draws over an 81-triple shard partition covers ~84%,
  predicting ~272 distinct triples vs 259 observed; the numbers close.
  Today's walk is without-replacement and stops at exhaustion (325). One
  `[gen] args` invocation per shard confirmed — 446 was a single run.
  **The prompt did not drift**: `single_json.txt` mtime 2026-08-09 00:39,
  before both runs, no other copies — Opus and Qwen generated from the
  byte-identical prompt; every output difference is model-side or walk-side.
- **Thinking probe verdict: operationally dead.** 75 minutes with zero specs
  (nothink: 4 minutes for the same volume), likely a gateway stream hang in
  thinking mode on top of genuine slowness; killed. Quality question moot at
  this latency.
- **The lesson, recorded**: code that GENERATES DATA must be under version
  control before it runs, and run logs should print the code identity (a git
  hash), not just args — the v500 log's `[gen] args` line was the only
  surviving fingerprint and it took a day plus a pycache accident to
  reconstruct what one `git log -1` would have answered.
  What holds: **253 shared coarse cells (80% of Qwen's) → stratified, not
  1:1, comparison**. Qwen keep rate ~98% (6 rejects in 331: 3 missing setup,
  2 syntax, 2 dup slugs) — the forced-tool-call regime is highly compliant;
  325-not-500 is cell exhaustion, not quality.;
  `--avoid-corpus` = the CUA-Gym 10,910-instruction dump; own-avoid automatic
  (sibling `out/runs/*/specs.jsonl`, which now includes v11-500 — so v2 is
  disjoint from v1 by construction).
- Generator regime = v11 parity: thinking OFF + forced tool_choice, via the
  new protocol adapter (`outdated/docs/TASKGEN_SNAPSHOT_20260815.md`). Trial: 4/4 specs, 100%
  tool-call compliance, difficulties 2/3/4/5, sane probe (checked by eye).
  ~6.7k tokens per 4-spec batch — full 500 generation estimated single-digit
  dollars.
- Downstream unchanged and still Claude/programmatic (gold, audits, control):
  Qwen writes, Claude audits, programs decide — the generator swap does not
  touch the verification separation.
- **Why 325 exactly, and why simpler — resolved (2026-08-15):** one gen
  invocation walks the core grid (5 intents × 13 domains × 5 difficulties =
  **325 triples**) once, one spec per triple, then stops — Qwen's count is a
  clean single pass (Opus's 446 was ~1.7 passes over the then-259-triple
  grid). The ~10k capacity is multi-pass + fine-axis rotation, realized by
  re-running (auto-avoid makes each pass disjoint). And the simplicity has a
  measured mechanism: **Qwen omits the voice field entirely (0/78 vs Opus
  112/112)** — optional schema fields get dropped by its fill-required-only
  function-calling habit, killing the register axis; deeper, the prompt
  co-evolved with Claude across v6–v11 (each rule patches a Claude failure
  mode), so "same prompt" is Opus's home field — cross-model generator swaps
  cost roughly half a prompt re-tune, itself a finding.
- **First qualitative/quantitative comparison at 325/580 specs (2026-08-15):**
  the generators differ in REGISTER, and it is a confound. Qwen writes
  spec-style: 85% of instructions carry an absolute path (Opus 8%), 86% name
  the file (15%), setups are half the size (med 297 vs 658 chars), and the
  voice axis collapsed (0 sloppy-voice specs vs Opus's 32/32 adherent) —
  systematically easier tasks because discovery work is handed over in the
  instruction. Probes: both structurally correct, but Opus carries tolerance
  machinery in 67% of probes vs Qwen's 37% — prediction: higher control-BAD
  (over-rigid probe) rate for Qwen, which the verification layer will
  quantify. Analysis of the family-alignment hypothesis must therefore
  stratify by difficulty, treat instruction-path-explicitness as a covariate,
  and report probe-rigidity separately; a style guard in the prompt is a
  possible v2, deliberately NOT applied mid-run.
- Readouts when rolled: yield through validation/control, difficulty
  calibration curve, teacher (3.8-27B) pass-rate distribution vs v11-500's,
  and per-cell paired comparison on the shared coordinates.

### 11c-FINAL: the worktree resolution (2026-08-15, supersedes the drift story above)

The user's three challenges were all correct; the final verified picture:

1. **Nothing was ever rewritten untracked. ostg/ was a git repo all along** —
   `.git` lives in the ostg SUBDIRECTORY (the parent dir is plain), with 14
   branches and **six worktrees**: `os-simple-taskgen`(v6),
   `os-simple-taskgen-v8`(v8.4), `ostg-v9/-v10/-v11/-v11.1`. My "unversioned"
   claim, the drift speculation, and the bytecode archaeology were all
   artifacts of checking only the parent directory for git.
2. **v500 was generated from the v10/v11 lineage** (`--spent-from` landed
   `11f2cf47` 08-09 17:59 "quota accounting on keep, not on draw"; the "v10
   standard generation invocation" was documented 39 minutes after v500
   finished). **My v11q ran from the v8.4 worktree** — an older lineage whose
   walk caps at one pass. The 446-vs-325 gap was a WORKTREE MIXUP, mine,
   today.
3. **On the real lineage the quota ledger is a 4-tuple — ambiguity IS a
   coordinate** (`taskgen/generation/gen.py:874`): the grid there is 5×13×5×4 = 1300,
   exactly as the user said. The 325 analysis described the wrong branch's
   taxonomy.
4. Remediation on the right branch (`v11.1`, commits `dc9b35d9`+`a361e753`):
   the protocol adapter now lives in `ostg/llm.py` (auto-routing, non-claude
   default = v11 regime), gen wires `--protocol`, and the sft fixes
   (DECLARED, cv2 fallback, verify gate, filter tests) are committed where
   they belong. The v8.4 working tree is restored pristine.
5. **Thinking verdict revised**: direct probes run 4–6 s with
   `enable_thinking:true`; `thinking_budget` partially binds (1000 trims,
   300 does not). The 75-minute "hang" was confounded by unflushed stdout
   (no `python -u`) — "operationally dead" is retracted; one instrumented
   retry on the v11.1 runway will settle real per-batch latency.
6. **The lesson, corrected**: the failure was not missing version control —
   it was not KNOWING the version control was there (`.git` in a subdir,
   six worktrees) and not knowing which worktree ran what. Fixes: run logs
   now print the git hash (`[gen] args ... code=`), and the check before any
   campaign is `git -C <exec-dir> log -1` — in the directory the code
   actually runs from.

### 11d. v11q2-500: the rerun on the right lineage (launched 2026-08-15)

Aligned line-for-line with the v500/Opus invocation, from the same canonical
runbook section, one knob changed:

| | v500 (Opus) | v11q2 (Qwen) |
|---|---|---|
| code | v10/v11 lineage | **v11.1 (= main), `code=` on the args line** |
| walk | on-keep quota ledger, 4-axis grid (5×13×5×4) | same |
| shape | `--n 5 --batches 29 --shard i/4`, seed 20260812 | same |
| avoid | CUA-Gym 10,910 + sibling corpora | same (v8.4-era 325 parked to `_x/` so it is NOT avoided — comparability) |
| regime | thinking off + forced tool call | same (adapter default) |
| model | claude-opus-5 | **qwen3.8-max** |
| logging | buffered | `python -u` (log-only difference) |

**Completed same day: 488 specs, and the coordinate system cured the register
confound.** Final three-way readout:

| | v500 (Opus, 4-axis) | **v11q2 (Qwen, 4-axis)** | v8.4-era (Qwen, 3-axis) |
|---|---|---|---|
| specs | 446 | **488** | 325 |
| instruction path% | 8% | **5%** | 85% |
| voice filled | 100% | **100%** | 0% |
| ambiguity mix (1/2/3/4) | 43/130/139/134 | **49/147/146/146** | absent |
| probe tolerance | 67% | **34%** | 37% |
| setup median chars | 658 | **321** | 297 |

The ambiguity coordinate (only 10% of cells permit paths; levels 2–4 forbid
filenames by definition) plus the 4-axis briefs/schema made Qwen fill voice
100% and follow the quota exactly — path-explicitness collapsed 85%→5%,
BELOW Opus's 8%. The fill-required-only theory refines to: Qwen complies
perfectly with whatever the brief makes explicit, and improvises nothing.
**What survives the cure is the real model signal**: probe tolerance
engineering (34% vs 67% — the control stage will price this) and setup/world
richness (half of Opus's). Yield actually exceeds Opus (488 vs 446).

**Acceptance battery (2026-08-15, `ostg.taskgen.validation.accept`, same refs both corpora,
both measured pre-cull straight out of generation):**

| gate | v500 (Opus) | v11q2 (Qwen) |
|---|---|---|
| intra jaccard ≥0.4 | max .38, **0 pairs — ok** | max .60, **18 pairs — FAIL** |
| intra tf-idf ≥0.5 | max .49, **0 pairs — ok** | max .76, **28 pairs — FAIL** |
| grader-signature ≥0.30 (review band) | 1,324 | 2,828 (5 pairs at 1.00) |
| vs cua-gym ≥0.5 | max .47, **0 — ok** | max .75, **6 specs — FAIL** |
| vs OSWorld-361 ≥0.5 | max .46, 0 — ok | max .45, 0 — ok |
| slug collisions across shards | 0 | 5 (e.g. `freight-rate-correction` in s0 AND s2) |
| distinct-bigram ratio | .69 | .68 |

So the register cure exposes the **third surviving model delta: semantic
near-duplication**. Opus's 446 pass every gate raw; Qwen re-derives the same
task from different seeds — five cross-shard *identical slugs*, whole
near-clone families (gradebook-weighted-total × 3, clinic-vitals × 2), and six
specs within 0.5 of cua-gym (max 0.75). Phrasing diversity is identical
(bigram ratio .68 vs .69) — the duplication is in task *identity*, not
wording, which is exactly the Opus-4.6 defect shape recorded in §10, and it is
mechanically catchable: the cull (keep earlier member, move line to
`specs_culled.jsonl`, re-run ship) costs ~30–40 specs, landing v11q2 near
Opus's yield. Surviving deltas now number three: probe tolerance (34% vs
67%), setup thickness (321 vs 658), and idea-space entropy (this table).

**Cull executed + shipped (2026-08-15, user-approved).**
`tools/cull_v11q2.py` (wrapper repo, bc37bfd): greedy over the union of both
hard-gate pair lists, later member culled (shard index then line number — the
deterministic proxy for generation order across concurrent shards), plus every
spec ≥0.5 vs cua-gym. **28 culled** (24 near-dups incl. whole clusters — the
chrome-proxy triplet keeps one, the clinic-roster export family lost all four
members once its keeper hit contamination — + 4 contamination) → **460 specs**,
still above Opus's 446. Audit trail in each shard's `specs_culled.jsonl`.
Ship then re-emitted with the current emitter: 1 more spec dropped by the
newer rigid-name gate (`writer-template-margin-sync`) → **459 task JSONs**,
and the full accept battery is green (jaccard 0 ≥.4, cosine 0 ≥.5, cua-gym
max .49, OSWorld max .45). Grader-defect scan flags 4 review items
(2 missing-source, 1 fake-media, 1 the dropped rigid-name) — adjudicate before
rollout. The cull is now a standing pipeline stage on main: `ostg.taskgen.cull`
(ostg 05af9098, RUNBOOK Ship section), verified equivalent to the one-off
script by a zero-cull dry-run over the already-culled set. VM control round still pending (VMs occupied by the v11-500 rollout);
that stage prices the probe-tolerance gap (34% vs 67%).

The v8.4-era 325 is demoted to register-analysis material. Standard-process
consolidation shipped with the launch: the v11.1 RUNBOOK now carries the
500-scale shape, the generator-swap knob and the code-hash line (`190009be`);
`main` fast-forwarded again to include it.

## 12. Open

- **The main rollout is mid-flight** (13 of 203 at this writing); claims about
  thinking's effect on the solve rate, and the preserve/no-preserve A/B, wait
  on it. The v3 run remains paused at 74 of 185.
- **The v5/v6/v7 branches were never merged** and now sit beside a version that
  supersedes them. They should be closed out.
- **`sig.py` should be deleted** — 380 lines, measured not to transfer across
  corpora, a conclusion v8's `accept.py` reached independently and designed
  around. The negative result belongs in prose; the code does not.
- **The 82% spent on failures is unaddressed.** The safe reductions —
  `max_tokens` near the measured p90 rather than 81920, and a stability poll in
  place of the fixed 60-second settle — are identified and not implemented.
- **Voice compliance is unmeasured**: v9 assigns a register per task, but
  whether "terse" actually comes out terse (early sign: tone yes, length no)
  waits on the full-corpus comparison.
- **Browser difficulty labels in v8 overstate**: the grader checks only the
  final URL, so a d5 navigation task is effectively d1. v9's rule 13 addresses
  new tasks; v8's ten browser tasks should be read grade-first.

---

## 13. A note on confidence

Three conclusions here were stated before the evidence supported them and later
contradicted: a loop-count threshold at n=12, a claim that one prompt style never
succeeded at n=15, and a claim that streaming eliminated a gateway timeout after
two clean batches — it reduced them; seven appeared by the fourth. Each was
labelled a small sample at the time and each was still stated too firmly. Sample
sizes are given throughout so the reader can apply their own discount.

<!-- REPO NAV -->
[Repository map](../README.md)
<!-- /REPO NAV -->
