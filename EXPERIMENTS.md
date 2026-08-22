# Synthetic task generation for OSWorld — design, experiments, results

## 现状(2026-08-18,过时即改;历史快照看 git log)

- **两大口径更正(08-18,详 `sft/RESULTS.md` §5.2 / §5.7)**:
  ① **keepthink 与 stock 两个评测模板逐字节等价** —— harness 把推理内联进
  `content`,keepthink 的分支永不触发;所有 `·keepthink` / `·stock` 臂吃到的是
  同一个 prompt。rich 28.0 vs 30.0 与 lean 23.8 vs 25.8 因此是**同配置重复**,
  给出配对噪声 sd≈2.8 题(5–6pp),**MDE80≈15–18pp:eval-50 看不见小于
  ~15pp 的差异**。keepthink 全线退役,以后一律 stock。
  ② **serve 的 checkpoint 挑选器按字典序取到 checkpoint-90**:Bs-LoRA 47.8%、
  Bs-gb64 45.8%、B-gb64o 41.8% 实为 **~1 epoch 权重**的分数;旧结论
  "1ep→3ep=+10 点"作废(两端都是 ~1ep)。已修:`pick_ckpt.sh`
  (endpoint / epoch:N / step:N,选择连判据一起打进日志)。
- **eval-50 最新(缺题按 0,全 50 题;完整表 → RESULTS.md §6)**:
  Bs-LoRA@e1.02 47.8% > Bs-gb64@e1.02 = Bs-LoRA@e3.00 45.8% >
  gb128ep2@e2.00 43.8% > gb64o@e1.01 = **r5-LoRA@e3.00 41.8%** > base 39.8%。
  旧数据里 epoch 与语料共线;新增的 Bs-LoRA e1.02 vs e3.00 配对差 −2.0 点
  (噪声内),**"训过头"在 LoRA 上未获支持**。
- **r5 四臂训毕;末步修复奏效,分数未动**:显式 terminate 6% → **60%(LoRA)/
  74%(全量 kD,跑动中)**,假 done 0/7;代价:失败没有出口,失败题全部磨到
  50 步上限(terminate 被绑定"成功",语料 0 条失败结尾)。机制与硬约束
  (FAIL 在普通题强制 0 分、词表兜底陷阱)→ RESULTS.md §5.8 / §5.9。
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
  58,211 真实响应双闸 0 差异 + 灵敏度对照,→ `sft/FAILURE_ANATOMY.md`)。
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
  **kF 撤下不排**。明细 → `CHECKPOINTS.md` §2.1。插曲:img3 起 serve 撞上
  scrubbed 吃掉 uv Python 标准库的定时炸弹(三次秒死;验尸与修复 → `OPS.md`)。
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
- **8 题从未真正跑过(08-22,同事定案;权威明细 sft/FAILURE_ANATOMY.md §9)**:
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
  (157 题隔离重跑,明细 OPS.md §serve 断档);汇报主口径建议用非 proxy
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
- **散文机制解剖(08-21,`tools/eval_emit_compare.py`,100 题配对)**:
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
  `PLAN-20260820-targeted100.md`;三层打标器 `tools/taxonomy_tag.py` 首跑:
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
- **语料覆盖审计(08-20,`tools/coverage_audit.py`,已固化为流水线检验)**:
  语料只教 **3 种 evaluator**(check_include_exclude 81.7% / compare_table
  14.4% / is_expected_url_pattern_match 3.9%),而基准三个面板各有
  **26 / 21 / 94 种从未出现在语料里**,波及 **78% / 72% / 79%** 的题。
  比例三面板一致 ⇒ **不解释已见-未见落差,但界定了整体天花板**。
  最尖锐的两个零覆盖:**`infeasible`(必须答 FAIL)0 道** —— 与全项目
  假报成功率(冠军未见半 44%、基座 46%)直接对应;**`compare_docx_files`
  0 道** —— 与 writer 域 3/3→0/4 崩塌对应(教师同题 3/4,故非题目不可解)。
  措辞收窄:evaluator 是**任务形态**代理,不等于"没教过该动作"。
  应用分布也偏:语料重仓 files/vscode/terminal,基准重仓 multi_apps/chrome。
- **流程级污染检查落地(08-19 夜,§5.15,tools/flowsim.py 固化为管线命令)**:
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
  其余 32/41。计划、五条硬约束与闸 → `PLAN-20260818-datagenv12-fmt-w1.md`;
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
  一次;后者一次 ssh 探测失败就 pkill 所有 runner。详 `OPS.md`。
- **Bhqs 语料 + 训练(新臂)**:判官+仲裁筛选的 304 轨迹 / 5,367 样本,
  换血 32% 而规模只小 3.9%,**难度反升**;训练 236019 运行中(Bs 精确孪生,
  语料是唯一变量)。赎回三阶段口径 83→56→54,详 `SFT_DATA.md`。
- **数据质检战役(08-17,新)**:盲审判官考试 AUC 跨池稳定(Opus .763/.771,
  Qwen .774);步级审计坐实 cap-2048 断崖(>2k 带弱步 41%,"想完不做"主模式);
  **仲裁 100 池 23 条分歧:10 条 checker 冤案(全过严向,3/3 抽查代码坐实),
  真实 pass 率 ≈80% 非 70%**。问卷拆账:Qwen v2 白改、medium 有害,
  最优 v1+low;**生产问卷定为 v2req**(清单+证据,为成功轨迹分层),
  v1 冻结为校准基线。筛选流水线跑动中:Qwen v2req 批两池 → 500 池仲裁
  (~110 条)→ 三张名单(keep 高质/赎回冤案/剔除假 pass)→ **B-rescue 语料**
  候选。详 → `SFT_DATA.md` 盲审章 + `IDEAS.md` §J。
- **v11-500 教师 rollout:444/444,checker 口径 250 过/56.3%——仲裁修正后
  真实率待 500 池裁决**。B 原料 312 轨迹(arm A 的 4.7 倍)。
- **eval-50 epochs 曲线**:base 38% → ep1 26% → ep3 28% —— 损伤第一个 epoch
  全额安装;训练深度无罪。四行史:rich/rich 28%、leankeep 22%(渲染线闭)。
- **v11q2(qwen3.8-max 生成)已 ship**:459 task JSON,accept 全绿;待办:
  scan review 4 项 + VM control 轮 + **checker 生成端静态检查清单**(仲裁
  病理反哺:禁硬编码未给定细节/round 语义/枚举值核对)。
- 谱系:**v11.1 = main = 标准流水线**;任务源 `os-simple-taskgen-v8/out/runs/`;
  分支史 → `taskgen/GIT_HISTORY.md`。

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
   `sft/TRAINING.md` measures that after an action that changes nothing on
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
| new kernels? | Qwen3.5 needed `flash-linear-attention` + `causal_conv1d`. Budget a build job; ours took three attempts and an hour (`TRAINING.md`) |
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
  new protocol adapter (`taskgen/README.md`). Trial: 4/4 specs, 100%
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
   coordinate** (`taskgen/gen.py:874`): the grid there is 5×13×5×4 = 1300,
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

**Acceptance battery (2026-08-15, `ostg.taskgen.accept`, same refs both corpora,
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
