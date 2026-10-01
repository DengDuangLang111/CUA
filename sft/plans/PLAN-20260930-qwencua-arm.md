# Qwen-CUA-397B 当动作级 reward model(ARM),按 action-reward-models 仓库做法蒸馏回 9B

> **选择器已改为 GPT-6.1-sol(§10),Qwen-CUA 弃用。** 目标:10-01 10:00 前看到 a2 + ARM-LoRA 在 eval50 的结果。

## 0 实时进度(每次检查更新)

| 时间 | eval50 B 臂(a2 每步 5 选 1,GPT-6.1-sol high,20/10) | r5 提纯(PRM 打分) | ARM-LoRA 训练 |
|---|---|---|---|
| 10-01 06:25 | — | — | **339127(全量 ARM 臂)06:06 CUDA OOM 失败于 635/782 步**(rank1 申请 26.6 GiB,剩 22 GiB;疑为最长样本之一,r5 第 1366–1370 行同一轨迹,文本 3.6–3.9 万 token + 10 图,未超 max_length 65536)。checkpoint-500/600 已存(每 100 步存档的改动起了作用)。处置(不改训练逻辑):debug QOS 作业 **339232** 合并 checkpoint-600 → `serving/9b-full-r5-armg61--train20261001--s600`,全量链改参数化(cua-arm),workstation/Windows 启动脚本改等 s600;结果目录不变,内放 NOTE_snapshot_s600 注明是 77% 进度快照。续训方案待用户定:A 跳过 OOM 那一批续训;B 序列并行续训(等价但复杂);C 降 max_length(截断长样本);D 只用 s600 |
| 10-01 06:05 | — | **only-changed eval100(98/100 计分,2 道崩溃题在 workstation wsR 补跑中):59/98(60.2%)vs 基线 62/98(63.3%),−3 题**;+10/−13,符号检验 p=0.68。**不可完成 13 道:8 vs 4(+4);能做的 85 道:51 vs 58(−7,符号检验 6 vs 13,p=0.17)**;能做题上报 failure 2 次。按应用(题数/oc/基线):calc 14/8/10、chrome 6/5/4、gimp 8/5/3、impress 15/9/10、multi_apps 24/13/16、os 8/4/5、thunderbird 5/4/4、vlc 5/4/2、vs_code 7/3/4、writer 6/4/4。成功题平均步数 13.7 vs 15.5。结论:只用"有改动"的 1,191 状态训练,能做的题变差,收益全来自不可完成题的结束标签校准。计分规则:移到 wsW 的 8 题用 wsW 结果、Windows 重复作废;崩溃题(harness_error.json)不计,由补跑结果替代 | Windows oc runner 06:02 由 stop_win_oc.sh 停,容器 0;Windows 的 oc 补跑等待已撤(改在 wsR 跑) |
| 10-01 05:25 | — | oc:workstation 组 wsA/wsB1 全完(wsA 两道崩溃题 04:37 自动补跑成功),wsB2 10/11、wsB3 7/8;Windows 慢(长 multi_apps 题,04:26→05:21 仅 13→15 题)且 05:18 第三次崩溃(writer/8472fece 取截图空)。**Windows 队列尾 8 题移到 workstation 新组 wsW(5 VM,05:2x 起)**,Windows 只做自己在跑的 3 题+留下的 3 题,完成后 stop_win_oc.sh 停 runner;预登记:移走的题用 wsW 结果,Windows 重复作废。补跑脚本升级 v2(`rerun_crashed2.sh`,cua-arm 4e5684e):只用崩溃题生成临时题集重跑(v1 会连同被移走的未完成题一起重跑);全部旧等待进程已替换。全量链加固(b9e3dc6):Klone 换副本改 setsid 独立运行,并核 5 个端点均就绪,20 min 不就绪写 FAILED;监控新增链进程存活检查。训练 05:21 在 529/782,预计 07:16 训完;07:20/07:30/07:40 三个检测点已排 |
| 10-01 03:55 | **B 臂 eval50 完成:40/50(80.0%)vs 基线 35/50(70.0%,按得分>0.5;RESULTS 记 34/50=68.0%,差一题待按其口径核)**,+6/−1(只 B 对:thunderbird 7b1e1ff9、vlc 5ac2891a、impress 5d901039/05dd4c1d、gimp 2a729ded/62f7fd55[不可完成];只基线对:calc 04d9aeaf,该步 5 候选全为 terminate),配对符号检验 p=0.125;成功题平均 12.3 步 vs 14.5 | oc eval100 30 题:22 vs 19(+5/−2,p=0.45);不可完成 6 道 5 vs 1,能做的 24 道 17 vs 18。训练数据 terminate(failure)=0(r5/全量/oc 均无);oc 1,191 个改动:51% 同类动作改参数,~16% 观望(screenshot/wait/mouse_move)→实操,5% →terminate(success)。基线在不可完成题上常在思考里判断"做不到"却调用 terminate(success);oc 改为 terminate(failure)(未直接训练,机理待查) | 03:52 第二次基础设施崩溃:wsA calc/42e0a640 取截图返回空,记 0+harness_error.json,由 rerun_crashed.sh 在 wsA 结束后重跑 |
| 10-01 03:45 | B 49/50(B 40 vs 基线 35)| oc eval100 19 题:15 vs 基线 11(+4/−0)| **监控报警 03:40**:Windows oc 组 libreoffice_calc/0cecd4f3 虚拟机启动超时,harness 按约定写 0 分 + harness_error.json(基础设施故障,非模型判定)。基线 a2 eval100 与 B 臂均 0 例,为口径一致必须重跑。新增 `rerun_crashed.sh`(cua-arm):每组 runner 结束后把带 harness_error.json 的题目录移到 `_crashed/<轮次>/`,用同一启动器/模型/URL/select_n 只重跑这些题,最多 2 轮;已挂在 oc 的 wsA/wsB1/wsB2/win 与全量的 ws/win。evalcheck 改为按 `--result_dir` 判断 runner 存活、计崩溃题数;监控以新基准重启。wsB 拆为 wsB1(18 题,03:33 起,3 VM)与 wsB2(19 题,容器≤3 时 4 VM) |
| 10-01 03:12 | B 完成 44/50(B 39 vs 基线 34,+6/−1;ws2b 03:01 由 stop_ws2b.sh 停,其重复跑的 510f64c8/6f56bf42 按预登记作废)| — | **oc eval100 已开跑**:wsA 03:01 起,03:08 完成 4/33;win、wsB 待 B 收尾自动起。**全量臂夜间自动链**(cua-arm 4c274cc):Tillicum `full_chain.sh` 等 339127 出 `Completed 9b-full-r5-armg61 merged=`(publish_to_klone 已改精确匹配 d8d6d81)→ 传 Klone 核 sha256(不过即停)→ Klone `swap_to_model.sh` 停 A40×3/A100×2 上 a2 副本、补 3 个 tokenizer/processor 文件、起全量副本 8051–8055 → workstation `full_launch_ws.sh`起代理 18071/18030,等 oc 的 ws 组全结束后 7 VM 跑 70 题;Windows `full_launch_win.sh` 等 oc win 结束且 18030 可用后 3 VM 跑 30 题;结果 `results_generated/arm-full-eval100-20261001/{ws,win}`。**监控** Mac `mon.sh`(5 min,Tillicum 10 min):harness Traceback/a2 调用失败/代理非 200/训练错误数上升、runner 退出但题未完、容器超限、可用内存<3G、链路 FAILED 即退出唤醒;oc 100 题完成、全量 eval 开跑为里程碑 |
| 10-01 02:50 | B 完成 40/50,余 10 题在跑 | — | **339130 02:37 训完并合并**(checkpoint-149);02:42 传 Klone `serving/9b-full-r5-armg61oc--train20261001--s149/model`,13 文件 sha256 全同。与 a2 比:chat template/tokenizer/预处理/生成配置全同,760 个张量名同;config.json 仅少训练残留 `use_cache: false`;merged 缺 merges.txt/vocab.json/video_preprocessor_config.json,已从 a2 目录拷入(同一基座,非权重)。L40S GPU4–7 的 a2 副本停掉(步骤 9–12),改起 oc 副本 8046–8049;B 代理池缩为 A40×3+A100×2。oc eval100 分批启动:wsA(33 题,3 VM,ws 空出 3 台即起)、wsB(37 题,4 VM,B 的 ws 组全结束后)、win(30 题,3 VM,win/win2 结束后 18032 改指 oc 池);workstation 用代理 18061;结果 `results_generated/arm-oc-eval100-20261001/{wsA,wsB,win}` |
| 10-01 02:38 | 完成 36/50,同 36 题 B 32 vs 基线 28(+5/−1;唯一 −1 题 04d9aeaf 该步 5 候选全是 terminate,非选择器问题)。**尾部重分配**:ws2b 剩余队列拆出 → ws2c(a462a795、7aeae0e2、7c4cc09e,ws 3 VM)、ws2d(510f64c8,ws 1 VM)、win2(6f56bf42,Windows 1 VM);ws2b 只做 5d901039/70bca0cc/48d05431,完成后由 stop_ws2b.sh 停进程与其 2 容器。**预登记规则**:被移走的题一律用新组结果,ws2b 若重复跑则作废。VM:ws 7、Windows 3 | — | 339130 将训完 |
| 10-01 02:15 | B 臂只跑 eval50(用户定);**only-changed 臂改用 eval100**(a2 基线 eval50-a2-20260823 实为 eval100 61/100,可逐题配对)。eval 配置核对:①runner 参数与基线 args.json 只差 model/base_url/路径(enable_proxy、num_envs 等一致);②OSTG_ARM_SELECT=0 走原 call_llm,与基线代码路径相同;③与基线树相比 mm_agents/qwen 仅 main.py(该钩子)与 images.py(主树 09-05 才加 min_pixels 环境变量,不影响 1920×1080)不同;④eval100 题集与 100 个任务 JSON 两机与基线树 md5 全同;⑤切分 armsel_eval100_ws(70)/_win(30),两机 md5 同 | publish_to_klone.sh(cua-arm 8f64a44)等 oc 合并后传 Klone 并逐文件核 sha256 | 339130 ~02:35 训完 |
| 10-01 01:57 | **加速**:Klone 新起 6 个 a2 副本(A100×2 @40897923 端口 8034–35;L40S GPU4–7 @39608331 8036–39,同 serve_actor_held.sh 基线参数),workstation 用 `cua-arm/cua/rr_proxy.py`(b865bac,按最少在途请求分发、每条记日志)接管 18031/18033(池:A40×2+A100×2+L40S×2)与 18032(Windows 经 workstation 转发;池:A40+L40S×2),共 9 卡 10 VM;切换后 2 分钟 17 次请求全 200、0 失败,单请求 16–25 s(此前每步 2–4 min)。ws2b 01:52 用空出的 2 台 VM 启动(原等 ws1 的脚本已停) | — | 339127 / 339130 在跑 |
| 10-01 01:35 | 完成 18/50,同 18 题 **B 17/18 vs 基线 14/18**,翻转 +3/−0(gimp/62f7fd55、gimp/2a729ded、impress/05dd4c1d);0 退回、0 Traceback。ws2b(10 题)改为 ws1 结束后用其 4 个 VM 槽、接 Klone a2 副本 18033 自动启动(workstation 脚本 ws2b_after_ws1.sh) | **全部 6,474 状态打完**、0 失败;0.7 门槛保留 6,253(96.6%),选中≠a2 最常动作 19.0%;数据 swift_arm.jsonl sha256 0f41c8e5…;only-changed 子集 1,191 行 swift_arm_oc.jsonl sha256 9cef5cad… | 339006 因 8h 上限风险取消;**339127**(全量,ARM 臂 9b-full-r5-armg61,每 100 步存,~08:17 完)+ **339130**(only-changed 臂 9b-full-r5-armg61oc,149 步)均在跑;代码 265812b |
| 10-01 00:57 | 完成 15/50,同 15 题 B 14/15 vs 基线 13/15(翻转仍只 gimp/62f7fd55);0 退回、0 Traceback。ws1 两道 multi_apps 第 0 步排队等 a2(18031:跑 5–7、等 6–8,20 s 只出 172 token,预填充瓶颈),非卡死 | **第一批 4,992/4,992 完成、0 失败**;第二批等采样 338873 结束后自动起(已改为并发 192、chunk 96) | 339006 运行中,等数据 |
| 10-01 00:47 | 完成 14/50(ws1 10、win 4、ws2a 0),8 在跑;选择 205 次、0 退回、0 Traceback;同 14 题 B 13/14 vs 基线 12/14,翻转 +1/−0(仍是 gimp/62f7fd55);ws2b(10 题)待 OSWorld2 腾出 VM 再起 | 第一批 3,392/4,992(并发 192 后 ~200 状态/min,~00:55 完);已用 67.6M 输入 / 1.53M 输出 token;采样 338872–4 仍在跑(338871 已完) | **339006 已在 g012 运行**(00:34 起),正在等 `swift_arm.jsonl.ready`(最长 240 min) |
| 10-01 00:33 | 完成 11/50、8 在跑;选择 152 次、0 退回;同 11 题 B 10/11 vs 基线 9/11(均分 .909 vs .818),翻转 +1/−0。a2 副本 18031 排队 9(A40 预填充瓶颈:20 图 ~40k token×5 候选、无 prefix cache;KV 仅 10–20%),每 VM ~1–1.5 min/步,预计 ~02:30 完;不重启服务以保持与基线同参 | 第一批 928/4,992(~93 状态/min,~01:17 完);采样每片剩 ~300–450(~01:00 完) | 339006 排队,Slurm 估 01:29 开始 |
| 10-01 00:35 | 在跑(上次 8/50) | 第一批约 1,000/4,992、0 失败;采样 ~01:00 完后自动起第二批(scored.part2) | 4 卡 interactive 作业因 QOS(cpu≤16、gpu≤2)永不启动 → 改 2×H200、累积 4(全局 batch 8 不变)、加 LoRA 合并 → **339006** 排队;随机对照臂后补 |
| 10-01 00:27 | 完成 8/50(ws1+win+ws2a),8 题在跑;选择 127 次、0 退回;已完成 8 题 B 8/8 vs 基线 7/8,翻转 +1/−0(gimp/62f7fd55 不可完成题,B 正确 FAIL) | 候选采样剩 ~35%(~01:00 完);第一批 4,992 状态打分中 320 完成、0 失败、平均分 0.94(偏高,0.7 门槛可能挡不住多少) | 338949(interactive 2×H200,ARM 臂)排队中;随机对照臂后补 |

**打分 prompt 溯源(00:30–00:35,用户要求查分支/历史)**:用的是上游 `build_catts_vision_prompt_v2`(单候选)+
`scalar_server._to_prm_format` + `templates/prm2_templates.json`(= Piotr 训 `reward_bt_prm2_ep2` 的格式)+ 4 处 CUA 替换。
**产生 GPT-5.5 PRM 分数的脚本/prompt 在任何可访问处都没有**:GitHub 只有 main;12 个 commit 中 selection_prompt.py 仅在
首个 commit `a377862` 出现且 PRM 模式自始即"repro build 已删";HF 数据集 `code/` 与两个 .pyc 同为删减版;HF
`distillation_data/` 是 rollout 记录;Klone 上 dan29 克隆无分支、piotrt 只有 OpenWebRL 代码。原件在作者 BU SCC 生产树
(`/projectnb/ivc-ml/piotrt/browser_agents/browser-environment`)。HF `selections_distill_a.jsonl`(蒸馏成功版实际用的选择):
39,160 条保留,top_score p10 0.8 / 中位 0.95,0.7 档仅 1.5%;按连续编号的空缺估计 0.7 门槛约丢 8% 状态(保留 ~92%)
→ GPT-5.5 同样打高分,我们平均 0.94 属同一现象,预计保留率也在九成左右。

**API 缓存与 token 量(00:45 实测)**:记录里原本没存 `cached_tokens`,另抽 20 个状态重打 100 次实测:现做法(每状态 5 个候选同时发)缓存命中 **4.0%**;先发 1 个、回来后再同时发 4 个 → **22.1%**。已打 3,392 状态 = 16,960 次调用,平均输入 3,988 / 输出 90 token。全量 6,474 状态 × 5 ≈ 32,370 次 → **输入 ~129M、输出 ~2.9M token,~$280**;eval50 选择 ~700–1,000 次 → 输入 ~3–6M,~$10–20。合计 ~$290–300。
选择调用另测 8 次:平均输入 **9,147**(最大 23,590,5 个候选的思考都在 prompt 里)、输出 58 token。**截至 00:51 实际已用 ≈ $187**:打分 21,280 次(输入 84.3M、输出 1.90M,≈$181)+ eval 选择 222 次(≈2.0M 输入,≈$4)+ 测试 ~110 次(≈$1)。这把 key 无 `api.usage.read` 权限,余额接口只能浏览器登录查,**总额度看不到**。
**依次发送实测(00:55,各 10 状态)**:同一状态 5 个候选逐个发(前一个返回再发下一个)命中 **48.7%**;再加 `prompt_cache_key` 46.5%(无帮助)。第 2–5 次调用里一半完全没命中(请求被分到别的服务器),命中的那一半几乎整条 prompt 都命中。第二批 1,482 状态按此方式预计省 ~$20–25(~$64 → ~$40);改动 = `score_candidates.py --sequential`(cua-arm `c10614e`,已批)。
**生产实测(01:06,第二批前 2,880 次调用)命中仅 1.9%,没省到钱**:小测试 10 状态低速时 48.7%,192 状态同时跑就失效。推测(未验证):所有 prompt 开头的系统提示完全相同,OpenAI 按开头路由,高并发下同一开头溢出到多台机器,缓存分散;`prompt_cache_key`=state_id 可能解决,但低速测试无法区分,需高并发实测。第二批 ~6 分钟即完,本次不再改。
**"5 候选动作全同"不是采样 bug(01:35 核查)**:全 6,474 状态中 2,656(41.0%)动作全同,其中 2,621 个 5 段输出文字各不相同(采样生效,只是动作收敛),仅 35 个逐字相同;按动作类型 key 70%、terminate 61%、left_click 32%、type 28%;a2 在未见过的 eval 题上(B 臂实时 338 次选择)全同 26.9%,r5 训练过的状态更高属预期。
**改动量**:选中≠a2 最常动作 19.0%,上游判据 <10% 没得学、>25% 值得做;GPT-5.5 正式版此数无法从 HF 数据算出。
**更正**:上游 README 的"泛化负结果"指在线流式变体(−4.2pp,学会来回滚动不提交);我们用的离线 PRM 打分 + 0.7 门槛版本上游结果是 +8.7pp(对照随机候选 SFT +7.2pp,p≈0.001),推理时 best-of-5 选择为 +7.2pp,即蒸馏把选择收益基本全折进单次采样——故 B 臂的提升幅度近似是 ARM-LoRA 的上限参考。
**这一步实际在做什么(4,736 状态实测,动作字符串精确比较)**:r5 原标注动作不打分、不进新数据;r5 只提供状态。5 候选完全相同 40.3%;r5 原动作在 5 候选中 77.1%;丢弃(最高分<0.7)3.7%;保留里选中=a2 最常出的动作 78.0%、=r5 原动作 59.0%、两者都不是 15.4%。即主要是把目标换成 a2 自己写的、判官选中的回答,过滤只占小头;上游 `--only-changed`(只留选中≠a2 最常出的状态)未开。上游 README 也写明状态取自 gold 轨迹、非 DAgger。

运行位置:B 臂结果 workstation `~/research/OSWorld-armsel/results_generated/armsel-eval50-gpt61sol-high-20261001/{ws1,ws2a,ws2b}`、
Windows `/mnt/d/research/OSWorld-armsel/results_generated/.../win`;打分 Tillicum `arm/runs/r5-prm-gpt61-20261001/scored.jsonl`;
训练输出 Tillicum `sft/out/9b-full-r5-armg61/`,日志 `arm/logs/trn_339006.out`。


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
- **试点采样完成**(338835,22:03–22:19,16.5 min 含 ~3 min 加载 → **4.05 s/状态/H200**):
  首批 64 状态 320 候选 0 不可解析、格式全对、全部正常结束(无截断),生成长度中位 140 / p90 555 /
  最长 3545 token;72% 状态的 5 个候选不全相同(按 action_str 全等,点击 1 像素差也算不同)。

**2026-09-30 22:2x 用户定全量:8 张卡、r5+v16、立即采样**

- 语料 `sft/data/r5-v16save143-tf/train_swift_abs.jsonl`:10,142 行(r5 6,474 + v16 3,668,v16 多应用
  1,128),sha256 `3d2881f2…` 与其 manifest 一致;selftest 三项在该语料上通过
  (`arm/runs/selftest-r5v16-2220`)。a2 未在 v16 上训过;ARM 只用 v16 的状态,不用其教师目标。
- `sample_actor.sbatch` 改为 `CORPUS=${CORPUS:-<r5 默认>}`(cua-arm `ded5293`,一行参数化、默认不变;
  因用户令"立即开始"先提交后报 diff 复核)。
- 全量状态 `arm/runs/full-r5v16-20260930/states.jsonl`(10,142),按字节均分 4 片
  s00 2,719 / s01 2,692 / s02 2,506 / s03 2,225;Slurm **338853–338856** `gen-h1` 各 1×H200
  (g008×2、g010×2),输出 `candidates.s0{0..3}.jsonl`。
- 排程(8 卡):采样 4 卡 → 下载完成后 Qwen-CUA 4 卡(srv-h4),先打试点 200 状态给用户看分布,
  再流式打全量;采样结束后空出的 4 卡起第二个 Qwen-CUA 副本分担打分;两臂(ARM / 随机)各 4 卡并行 LoRA。
  估算(低置信度):采样 ~3–3.5h,打分 1.5–3.5h(未实测),训练 2–3.5h → SFT 完 ~明早 05–08 点;
  训练 sbatch 尚未写,写好先给用户审 diff 与参数表。

**22:5x 用户改选择器为 selection ARM(仿 David An),并改为先只做 r5**

- selection:cua-arm `67e8ee6`(`select_candidates.py` 移植上游 run_selector_offline.py + `report_selection.py`)、
  `809e6df`(服务名 `qwen-cua-qwen3.5-397b` 使上游按前沿模型处理:普通 prompt、temperature 0、无强制 JSON;
  Qwen-CUA 模板默认开思考;selftest 覆盖 selection prompt)。无 0.7 门槛(selection 无分数)。
- r5 在语料中连续(行 0–6,473),v16 在后(6,474–10,141)。原 4 片(338853–6,31 min)取消:已完成
  s00 384 / s01 384 / s02 320(均 r5)/ s03 320(v16),无截断行;采样代码 ded5293→809e6df 无差异。
  剩余 r5 5,386 状态重切 4 片(`states.r5rest.s0{0..3}`)→ **338871–338874**;1,088 + 5,386 = 6,474 核对无漏无重。
- **严谨性**:与上游同构 —— Piotr 的选择数据(HF `PTeterwak/action-reward-models-data`
  `openwebrl_actor/selection_sft`)取自 OpenWebRL 公开 SFT 轨迹的 3,085 个状态(`states_full.jsonl`,带 `demo_action`),
  训练集 39,155 例 / 2,557 个不同截图;David 的 8,731 = 每状态取 3 组(`_3ps`)。即上游的状态也来自 actor 自己的
  SFT 数据,r5 对 a2 正是同样关系;v16 是我们额外加的。

## 9 仿 David An 的 CUA 版流程(2026-09-30 23:0x 用户定)

David(Klone `dan29`)的做法:先在推理时让强模型从 actor 的 5 个候选里挑(GPT-6/GPT-5.5 当 selection ARM),
再把挑选能力蒸馏成 actor 自己 checkpoint 上的 LoRA 选择器;他尚未把选中动作 SFT 回 actor。CUA 版:

| 步 | 内容 | 状态 |
|---|---|---|
| ① | a2 在 r5 6,474 状态上每状态采 5 个候选(离线,不执行) | 338871–4 在跑,~00:55 完 |
| ② | Qwen-CUA 4×H200 FP8 | 下载 ~23:20 完后提交 srv-h4 |
| ③ | 试点 200 状态 selection 报告 | 服务起后 |
| ④ | **推理时检验 eval50**:a2 每步采 5 + Qwen-CUA 挑,对比 a2 单次 | 代码已提交,待部署 |
| ⑤ | 全量标签(Qwen-CUA 给 r5 状态选) | 可与 ④ 并行 |
| ⑥⑦ | 在 a2 上 LoRA 训选择器、离线一致率 + 在线 eval50 | ④ 有提升再做 |

**④ 的实现**(用户审 diff 批准):
- cua-arm `91c7167`:`build_inputs` 供离线标注与在线 `select_live` 共用(同 prompt/打乱/上游调用);
  离线 prompt 前后 30 状态哈希一致(`6d404e3a…`)。
- OSWorld worktree(workstation `/home/yanji/research/OSWorld-armsel`,分支 `armsel-select`):
  `b7dce12` = 主 eval 工作区快照(3df1ef4 + 17 个未提交魔改 + 8 个未跟踪文件 + .env + cache 322M;26 文件哈希逐一
  一致,registry 钉的 3 个哈希一致);`a8b2448` = `mm_agents/qwen/main.py` 加 `_respond`:`OSTG_ARM_SELECT=N`
  时同一 payload 并发采 N 个,`select_live` 挑,仅选中者进历史并执行,`ARM_SELECT` 日志记 5 个动作/展示顺序/选择器回复;
  不设开关 = 原代码路径。主工作区未动(main.py 仍 `e3aba4b1`,status 25 行)。运行用主工作区 venv 的 python。
- 题集:`verified_eval50_nonproxy.json`(10 个应用分层,eval50 ∪ eval50b = eval100),非"前 50 题"。
- **基线口径**:a2 现有 Verified 结果全是 20/10(`eval50-a2-20260823`,100 题,旧 Windows);a2 从未按 10/1 跑过
  Verified。B 臂若按 10/1 跑会混入窗口差(同权重 20/10 比 10/1 低约 8pp,RESULTS §5.34)。用户称"A 已有、只跑 B",
  已提示两个选项(B 用 20/10 对齐现有基线 / B 与 A 都按 10/1),**待用户定**。
- 连通:Tillicum `~/.ssh/cm/klone` 与 workstation `~/.ssh/cm/klone-login` 均落 klone-login01 → 在该登录节点回环端口
  中转(Tillicum 登录节点 ssh -L 到计算节点 127.0.0.1,再 -R 到 klone-login01;workstation -L 取回);服务均需 API key。
- a2 服务 `cua/serve_actor.sbatch`(待审 diff):eval 部署档案同参(bf16/TP1/262144/图 10/像素/override generation
  config),仅 max_num_seqs 3→32、max_num_batched_tokens 2048→8192(无注意力采集;只影响吞吐)。

**23:0x–23:15 用户定:B 用 20/10 对齐现有 a2 基线;a2 可部署在 Klone**

- a2 基线 = `eval50-a2-20260823`(dashboard 存 args.json / MODEL_BOUNDARY.json):image_max 20 / fold 10、temp 1.0、
  top_p 0.95、max_tokens 81920、history_n 100、max_steps 50、sleep 3、thinking + preserve_thinking、relative、3 env、
  enable_proxy true(nonproxy 题集无影响)、env `OSTG_NO_RECORD=1 OSTG_TYPE_NO_SPLIT=1`;服务(Tillicum 253817
  `serve4bbo_253817.out`)非默认参数:max_model_len 262144、kv fp8、image limit 20、qwen3 reasoning parser、
  override generation config = temp 1.0/top_p 0.95/top_k 20/min_p 0/无惩罚/81920。
- Tillicum 版 `serve_actor.sbatch` 未提交即删除(图 10 张在 20/10 下会报错),改 `cua/serve_actor_held.sh`:Klone 占位作业里
  照 `serve-teacher-held.sh` 模式起 a2,vLLM 参数逐项 = 基线服务。Klone 上的 a2(`sft/serving/9b-full-r5--train20260822--s306/model`)
  与 Tillicum checkpoint-306 索引及第 4 分片 sha256 一致。拟用空闲占位 **40897922(A40×1,g3074,6 CPU)**;
  40897918/919/920 是 OSWorld2 teacher 迁移用,不动。
- `run_eval.py` 默认要求服务端注意力采集器(EVAL_AUTOMATION:capture:false 不关 eval 侧采集),开采集会改服务参数且
  B 臂 5× 候选采集量 → **B 臂改为直接调原生 runner**(基线当年也是直接跑):`cua/run_armsel_eval.sh`,参数逐项抄基线
  args.json + env + `OSTG_ARM_*`;已生成的 armsel registry 删除。像素:harness 默认 max_pixels 13,107,200 = 现 registry 值,
  照基线不设。题集 `verified_eval50_nonproxy.json`(sha256 `a8877065…`);worktree main.py `72b740ac…`。
- Qwen-CUA 下载完成(23:11,5,292 s):107 文件大小与 HF 逐一一致、索引 94 分片齐;残留 8 个 `.incomplete`(首轮 OOM)待清。
  **srv-h4 = Slurm 338887,PENDING(Resources)**:当时无单节点 4 张空 H200(最多 3 张);账户 QOS 仅 normal/interactive/debug,
  无 urgent。采样 338871–4 约 4.4 s/状态,预计 ~00:35 完。
- workstation 内存:总 54G、可用 35G,OSWorld2 三台 VM 实占 3.3–6.8G;B 臂 3 台 VM(默认 4G)可共存。

**23:15–23:25 执行**
- 用户批准两脚本 → cua-arm `1c91332`,Tillicum / Klone(`/gscratch/cse/jy050706/arm/cua-arm`)/ workstation 三处同步(bundle md5 一致)。
- a2 起于 Klone 占位 40897922(g3074,step 40897922.0,端口 8031),日志 `/gscratch/cse/jy050706/arm/logs/srv_actor_40897922_8031.log`;
  引擎配置 kv fp8、prefix caching 关、CUDA Graph FULL_AND_PIECEWISE(与旧基线服务一致)。
- 用户问能否把 Qwen-CUA 放在"已有的 4 张 H200"上:那是 4 个 1 卡采样作业,分在 g006/g008×2/g010 三个节点,
  张量并行要求同节点,不行。Klone:FP8 403G 需单节点显存 ≳480G → L40S/A40(8×48G=384G)放不下;ckpt 分区
  8×A100(g3080–87)与 8×H200(g3125–32)当时均几乎满(各仅 1 节点空 1 卡);krishna A100 额度 6、cse 4,凑不出 8 张。
  Tillicum srv-h4 Slurm 估计 23:35 开始 → 保持 Tillicum。
- Qwen-CUA API key 复制到 workstation `~/.config/cua-v2/tillicum_vllm_key`(600,md5 前缀两端一致);
  删除首轮下载残留 8 个 `.incomplete`(9.1G)。
- **a2 就绪 23:21**:A40 KV 1,273,270 token(262k 上下文并发 4.86×)。workstation 转发 127.0.0.1:18031 → g3074:8031
  (klone-login 主连接),`/v1/models` 正常,开思考的短请求正常结束。
- ⚠ vLLM 把 `--api-key` 明文写进启动日志("non-default args");已对该日志 chmod 600。`serve-teacher-held.sh` 同样用
  `--api-key`,其日志有同样问题(未改动他人日志);Qwen-CUA 的 sbatch 用 `VLLM_API_KEY` 环境变量,不入日志。
- 冒烟题集 `evaluation_examples/armsel_smoke1.json`(worktree 未跟踪文件):os/13584542(终端 132x43 重启保持)。
- 后续 SFT 显卡:选择器 SFT(单截图,约 5–15k token,9B LoRA)用 Klone 已占的 A40/A100 即可,估 1–2h;
  actor 蒸馏(10–20 图、≤58k token)需单节点 4×H200,每臂 2–3.5h。

**23:30–23:50 用户定:跳过离线试点,直接 eval50 B 臂,10 VM = workstation 7 + Windows 3;并与 OSWorld2 会话协调**
- OSWorld2 会话(b601be)回复:22:00 起已停止派题;Windows 全空(21G);workstation 剩 3 台 VM(057/059/060)
  15–60 min 内跑完,建议先上 3–4 台,其结束后再加满;不能碰清单(~/cua-v2-pilot-20260915、OSWorld-V2-shared、
  监视器 PID 299972、klone-login 上 8150–8154 转发、39608331、40897918/919/920)均不碰。Windows 无 Klone master,
  经 workstation 中转,需 WSL 运行时路由 MSS900。
- **srv-h4 338887 失败**:`check_quant.py` 经 `llm.apply_model(survey)` 把 `__main__.survey` 发往 vLLM 进程,PicklingError;
  修为模块导入调用(cua-arm `506fd8e`)→ 重投 **338913**,PENDING(Priority),Slurm 估 01:48 开始;g011 的卡已被他人占用。
  Klone 无法承接:所有自有占位的单节点显存 ≤384G(L40S×8),FP8 需 ≳480G;8×A100/8×H200 可抢占节点满且非自有配额。
- a2 副本:8031(40897922)、8032 / 8033(40897921 两张不同卡;`f4de639` 起改为取第一张空闲卡,首次两步被分到同卡已
  scancel 40897921.1)。workstation 转发 18031/18032/18033 → g3074:8031/8032/8033。
- Windows:用户批准后加 `ip route replace 100.72.191.125/32 via 172.20.128.1 dev eth0 advmss 900`(运行时,WSL 重启即失);
  workstation 分支 `armsel-select` 以 bundle 传入 Windows 主仓库,worktree `/mnt/d/research/OSWorld-armsel` = a8b2448
  (两机同 commit;两机主工作区差异 python.py / provider.py / images.py 已逐行核对,对本 eval 无影响);复制 .env 与
  cache(1.3G);cua-arm `8b9c989`;两个 key(600,md5 前缀与 workstation 一致);隧道 Windows → workstation(机器 ID 一致)
  转发 18032、18030;Windows 经中转访问 a2 r2 正常。
- 题目切分(round-robin by i%10,按题集顺序):`armsel_eval50_ws1.json` 20 题 / `_win` 15 / `_ws2` 15,并集 = 50;两机 md5 一致。
  runner 计划:ws1 4 VM → 18031;win 3 VM → 18032;ws2 3 VM(OSWorld2 腾空后)→ 18033。

## 10 选择器改为 GPT-6.1-sol(2026-09-30 23:5x 用户定;Qwen-CUA 弃用)

- 用户给两个 OpenAI key(均有效、174 个模型,含 gpt-6-astra/luna/sol、gpt-6.1-sol、gpt-5.5;无 Qwen)。用第二个
  (非 Prior),存两机 `~/.config/cua-v2/openai_key`(600)。Qwen-CUA 作业 338913 已 scancel;FP8 说明(官方仅 BF16,
  我们是 vLLM 加载时按官方 FP8 格式在线量化)留档备查。David 用的是 `gpt-6-astra`、effort medium、Responses API、自写 prompt。
- **关键发现**:上游 `catts_vision_select_v2` 只把含 `gpt-5`/o 系列的模型名当推理模型;`gpt-6.1-sol` 走普通路径带
  `max_tokens` → OpenAI 400 → 上游 **静默退回第一个展示的候选(即随机)**。修:`selection_prompt.py` 的模型名判断加
  `"gpt-6"`,并加 `ARBITER_REASONING_EFFORT`(cua-arm `ea609ed`,已登记 PROVENANCE.md)。`run_armsel_eval.sh` 选择器
  url/model/key/effort 走环境变量,结果目录写 `SELECTOR`(`475b838`)。
- 实测(试点状态,gpt-6.1-sol):effort 只支持 low/medium/high/xhigh(无 max);思考 token default/medium 0–27、
  high 46–59、xhigh 76–133;每次 3–6 s;输入 3.8–7.2k、输出 ≤150 token。上游完整路径 high/xhigh 均 `ok=True`。
- **配置**:gpt-6.1-sol、Chat Completions、effort **high**、`max_completion_tokens=2048`、无 temperature/无 JSON schema
  (上游推理模型路径),prompt = ARM canonical(Piotr selection prompt)+ 4 处 CUA 文字替换。用户定"ARM 版 + CUA 最小改动";
  David 的 `ours` prompt(含 URL、页面观察文本、工具反馈)为网页设计,不用。与 David 推理循环的差异:候选全相同时
  仍调用(他跳过)、不剔除不可解析候选(他剔除;试点 0/1000)。
- **开跑 23:58**:workstation `results_generated/armsel-eval50-gpt61sol-high-20261001/ws1`(4 VM,a2 18031,20 题);
  Windows `/mnt/d/research/OSWorld-armsel/results_generated/armsel-eval50-gpt61sol-high-20261001/win`(3 VM,a2 18032,15 题)。
  两边记录 cua-arm `475b838`、OSWorld `a8b2448`。ws2(15 题,3 VM,a2 18033)待 OSWorld2 的 workstation VM 腾空后启动。
- 00:00 首步核查(workstation 4 VM):ARM_SELECT 均 `ok: true`、每步 5 候选、展示位置→原编号映射正确;执行的 pyautogui
  坐标与选中候选一致(484,82 → click(930,88));首步即出现选少数派动作。Windows 3 VM 已起。
- **a2 基线 eval50**(dashboard `traj/qwen35-9b-sft/eval50-a2-20260823/<domain>/<task>/result.txt`,= dashboard
  "seen50" 切片):满分 34/50 = 68.0%,均分 69.81%;chrome 3/3、writer 3/3、multi_apps 9/12、os 3/4、calc 5/7、
  thunderbird 2/3、vlc 2/3、impress 3/7、gimp 2/4、vs_code 2/4。单次运行(temp 1.0),对比用逐题配对 + 符号检验。

## 11 与 Piotr 成功版("option A")完整做法的差异(2026-10-01 对照 HF 数据 + cua-arm 代码)

相同:状态取自 actor 自己的 SFT 训练集;actor 自采 5 个、只生成不执行;强 API 模型逐候选打 0–1 分,上游 PRM prompt;
最佳 <0.7 丢状态、平局取 actor 多数票(action_str 全等);离线一轮;LoRA r16/α32/dropout 0.05/all-linear、视觉塔不训、
lr 1e-4、1 epoch、全局 batch 8、只对目标回合算 loss;不排除末步。

| 项 | Piotr 成功版 | 我们 | 影响判断 |
|---|---|---|---|
| actor / 任务 | MolmoWeb-4B,网页 | a2 = Qwen3.5-9B r5 SFT,桌面 | 桌面单步后果更难看见 |
| 判官 | GPT-5.5 | GPT-6.1-sol effort high + 4 处 CUA 文字替换 | 两者都给高分(上游丢 ~8%,我们丢 3.4%) |
| 状态数(过门槛后) | 39,160 | 6,253 | 我们约 1/6 |
| 候选采样 | temp 1.0 / top_p 1.0 | temp 1.0 / top_p 0.95 / top_k 20,开思考(= eval 协议) | 我们多样性更低;41% 状态 5 个动作全同 |
| 训练形式 | 单截图 + 文本历史 | 多图历史(img10)、max_length 65,536、preserve_thinking,目标含思考 | 目标更长 |
| only-changed 臂 | 有此开关,成功版是否开未写明 | 全量臂 + only-changed 臂(1,191 行)都在训 | 我们多一个臂 |
| **随机候选对照** | **有**(distill_rand,+7.2pp 的因果依据) | **未投**(`random_selections.py` 已写) | 缺它就无法归因 |
| 评测 | 贪心 n=1,多次运行,配对 n≈190–240 | eval50,temp 1.0,单次 | +8.7pp ≈ 4 题,50 题单次测不出显著 |

<!-- REPO NAV -->
[Repository map](../../README.md)
<!-- /REPO NAV -->
