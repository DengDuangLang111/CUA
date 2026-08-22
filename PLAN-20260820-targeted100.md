> **后续**:2026-08-22 起新增三条缺口(跨应用组合类型 / 负例 / 验证集规矩),
> 见 `PLAN-20260822-datagen-v13.md`。本文的动作缺口配额仍然有效,两份并进。

# PLAN-20260820-targeted100 — 定向补 ~100 条成功轨迹(纯追加)

## 一句话

按 `应用 × 动作 × 产出` 三层缺口定向生成候选任务,teacher 通过率校正配额,
最终**追加约 100 条 checker 验证通过的成功轨迹**到现有 362 条上(462 条),
超参全冻结重训,验证"覆盖补齐"这一个变量值多少分。

## 用户已拍板的决定(2026-08-20)

- **纯追加,不降采样**:现有 362 条一条不动,VS Code/OS 超配就超配(要压到
  OSWorld 比例总数得 1195 条,数学上做不到,接受)。
- **FAIL 类(infeasible)不做**——太麻烦。假报成功的病只治"自检"这一半。
- 候选不够的格子用 **Opus 5 生成**(datagenv12 分支,不动 main)。
- 超参全冻结:4B 全量 / lr 3e-6 / gb64 / 3ep / 20 图 / 带散文 / no-cap。
- **候选池只用 v11 及以后**(2026-08-20 补令):数据标准 = r5 标准基础上修改;
  v11 前时代(v8/v9/v10)一律不做候选。池从 1405 缩到 **647**。
- **本轮训练加 eval loss 节点**(2026-08-20):`ostg.sft.build --val-ratio 0.05`
  (按任务/slug 切,前缀不泄漏;该旗 08-13 abs-pilot3 实战验证过,
  1288+178 行走完全链)→ swift `--val_dataset` + `--eval_strategy steps
  --eval_steps 34`(与 save_steps 对齐,每个 checkpoint 配一个 eval loss 点)。
  零新代码。代价:约 5% 任务(~18/462)不进训练,训练集 ~444;sbatch diff
  训练提交前给用户过目。
- 曝光 +28%(6474→约 8262 行,累积 lr 4.5e-4→约 5.8e-4,正好越过实测峰顶)
  接受;**另评一个 ~2.35ep 的 checkpoint** 把"曝光变多"和"覆盖变好"拆开
  (checkpoint 本来每 34 步存一个,零训练成本,只多一次 eval)。

## 事实基础(tools/taxonomy_tag.py,2026-08-20 首跑)

- 语料产出形态:file_or_text 81% / spreadsheet 15% / browser_state 4%——只有
  3 家族;OSWorld 12 个家族(presentation 11%、config_state 10%、document 9%、
  image 8%、infeasible 7%…)。
- **候选池 1405 条**(taskgen 历代产物去重、除训练),但横跨 18 个时代
  (v8~v11),且产出分布与语料同偏(file_or_text 83%)——池只能按动作补,
  补不了 checker 形态。checker 形态对 SFT 教学影响待议(模型看不到 checker)。
- **v1 表被反驳审计否决(08-20)**,v2 重写后重算。审计要点:纯伪影格
  (vlc/formula_compute 100% 是 "computer" 误命中)、"池可补"多格是假的
  (vs_code/theme 的池 13 条全是 "template" 伪命中)、多标签按格加总超配
  13-23%、27% 需求(101 条 untagged:网页导航/跨应用搬运/单元格编辑)
  完全不在表上、infeasible 混占动作格。v2 修法:负向上下文正则、补 4 类
  词表(web_navigation/data_transfer/cell_edit/git_ops)、infeasible 剥离
  (27 条,gimp 占 9)、旗标改覆盖率阈值(教得少也亮)、需求按任务去重。
- **v2 缺口需求(v11 池 647 条,按任务去重 119 条)**:
  multi 38 · impress 25 · calc 18 · writer 12 · vlc 12 · os 4 · chrome 3 ·
  vs_code 3 · gimp 2 · thunderbird 2。
  **需生成格**(v11 池 0 条):calc/pivot 5、calc/chart 4、impress/theme_bg 7、
  writer/char_format 6、chrome/sort_filter 3、multi/{install 6、downloads 6、
  extensions 5、theme_bg 4、git 2、playback 2}、vs_code/install 3、
  vlc/export 2。**池可补大格**:impress/char_format(16 题,池仅 1)、
  multi/export_convert(17 题教 1,池 16)、calc/sheet_ops(13 题教 1,池 1)、
  writer/para_page_layout(8 题教 1,池 3)、thunderbird/sort_filter(池 11)。
- **池核选结果(08-20,`tools/pool_vet.py`,68 候选逐条过三闸)**:
  真可用约 **25-30 条** —— multi/export_convert ~10-12(题材对口,checker 验
  产物)、os/terminal 4(checker 直接验终端使用,最干净)、vlc ~6(配置类,
  有 sed 旁路风险)、gimp/color_tone 2、impress 2-3、multi 杂项 3、calc
  sheet_ops 1、writer 1。判废的典型:calc/char_format 池 1 条实为数值检查、
  impress/para_layout 4 条里 2 条是网格 XML 配置、writer 3 条里 2 条是
  "header" 伪命中、multi/web_navigation 6 条里 5 条是 price/order 伪命中。
- **逆向选择发现(影响配额算术)**:池里有 rollout 历史的 10 条,9 条全挂
  (TB 过滤类 0/5,invoice-chaser 0/2)——因为**当年 teacher 做成的任务都进
  了训练集,留在池里的"有历史"任务全是失败者**。所以:①这 10 条的通过率
  不能外推到整个池;②58 条无历史任务要先查是被 cull 掉的还是没被抽中出货
  的(前者有质量问题);③TB 过滤格 teacher 0/5,按 p̂<15% 规则先修再说。
- **选池任务的三道人工闸**(审计固化):①逐条过全文,不信格子计数;
  ②GUI 格必须核 checker 强制 GUI 产物(include_exclude 型 checker 会放过
  纯终端解法,筛出的"成功轨迹"可能全程不演示目标 GUI 动作);③配额按
  任务 ID 去重分配。
- 打标器是关键词多标签,精度未审计,已知有误标;**配额定稿前必须过
  反驳审计**(进行中)。

## 流程(闸门照旧,新增两道)

1. taxonomy_tag 定缺口(✅ 已固化)→ 反驳 agent 攻击表(进行中)
2. 候选池筛缺口格任务(优先 v10/v11 时代;老时代需验格式兼容)
3. 通过率:先挖存量 teacher rollout 记录估 p̂,零数据格才跑 8-10 题 pilot
4. 配额:N_gen = ceil(target / max(p̂,0.15) × 1.15),p̂=(s+1)/(n+2);
   p̂<15% 的格先修任务/checker,不无限生成
5. 池不够的格用 Opus 5 生成(datagenv12 worktree,代码先入 git 再跑)
6. 轨迹筛选:五道闸照用 + 新增语义近重复过滤 + 缺口 set-cover 打分
   (一条轨迹同时填几个格优先)
7. 追加构建 DS4 语料(stage+swap+snapshot,不碰在训数据)
8. 训练(参数冻结)→ dev100(已烧的 100)选型 → 新面板一次性报告
   (从剩余 213 非代理题冻结,**建议只冻 80,留 133 缓冲**——最后一块干净面板)

## 补丁设计(2026-08-20 晚,通读 taskgen 代码后;池线已按用户令关闭)

**读码结论:补丁比预想小得多,fmt-w1 已把地基打好。**

已有可直接复用(零新代码):
- **生成模型就是 Claude**:`llm.py` 按模型名自动走 anthropic 协议,
  `gen --model claude-opus-5` 即可;PPAPI 网关。**前提:PPAPI key 可用
  (fmt-w1 上次就卡在这)**。
- 定向机制:`--apps`(应用过滤)+ `--intents`(v12 新增)+ shards/waves +
  `--spent-from`(补差额)+ 自家/公共 avoid 清单 + repair-before-reject。
- v12 fmt-w1 已交付:`intent=restyle`("一个属性跨多个对象")、
  `grade=pptx`(宿主 python-pptx 判 shape/slide 属性 —— **正中 impress
  char_format 16 题 + theme_bg 7 题**)、`grade=image`(PIL 判 mode/尺寸,
  RGBA 证透明 —— 正中 gimp 透明/变换)、prebuild 容器造 deck。

需新增(小补丁,和 fmt-w1 动同三个文件 gen/taxonomy/prompts):
1. **`--focus FILE`**:每 wave 一份技能清单注入 user prompt(与 own/ext
   avoid 块同构),把缺口 cell 写成"每条 spec 必须落在这些操作里+配额"。
   这是动作级(pivot/chart/layers/install)定向的唯一新机制。
2. **prompt <grades> 加两份 probe 配方(不加新 grade)**:pivot/chart 用
   .ods 目标 + VM 内 zipfile/ElementTree 解析 content.xml(data-pilot-table
   / chart Object 的存在与属性;明示别用 xlsx,DataPilot 转存有损);
   writer 格式类用 odt/docx XML 解析(v11 池任务已有成熟先例)。
3. **taxonomy 一行**:restyle 的 INTENT_ARTIFACTS 加 text_document
   (writer char_format 是 restyle 语义,host=writer,grade=probe)。
4. 风险标注:install 类依赖 VM 网络与 sudo(可行但要 control 验证);
   gimp/layers 无 stdlib xcf 解析,主用 image-grade 代理(RGBA/尺寸),
   指令层要求 GUI 图层操作,配额小(3)。

**配额(300 条,2026-08-20 用户升量:"这些任务不是很好成功",按 119 条
去重缺口比例 ×2.52)**:
multi **96**(export_convert 42 · install 15 · downloads 15 · extensions 12 ·
git 6 · playback 6)· impress **63**(char_format 40 · theme_bg 18 ·
para_layout 5)· calc **45**(sheet_ops 22 · pivot 12 · chart 11)·
writer **30**(para_page_layout 19 · char_format 11)· vlc **30** ·
os **10** · chrome **8** · vs_code **8**(install)· gimp **5** · tb **5**。
PPAPI 确认可用(08-20)。--focus 补丁已打在 datagenv12 工作区(未提交,
diff 待用户批;dry-run 验证 focus 块落入 prompt)。

**流程**:gen(gap-w1,4 shards)→ ship(prebuild/accept/scan)→ control →
teacher rollout → 通过率复盘(<15% 的 cell 修任务不加量)→ 五道闸 build
(`--val-ratio 0.05`)→ 追加成 DS4。**写代码前 diff 给用户过目。**

## 评测策略更新(2026-08-22)与 ship 警告

- **freeze-100 令**:此后所有臂只跑冻结 100(已见 50 + 留出 50);261 类臂
  (base9b261、t38261)从链上摘除,以后再说。今天下午起四个 img10 训练臂
  (a1 4B / a2 9B / a3 hermes / a5v 5ep带验证集)出 checkpoint,各带
  epoch 边界可评点。
- **⚠️ ship 带验证集语料必须用 `ship_val.sh`**(或等 ship_dataset.sh 合并
  支持):现行 `ship_dataset.sh` 的 tar 清单写死 train 文件名,
  `val_swift.jsonl` 会**静默留在本地不上传**——正是本轮 eval loss 设计
  (`--val-ratio 0.05`)会踩中的坑,同事已踩过并补了脚本。
- 顺带一条可入报告的硬结论(同事核实):nocapnp ckpt-204(2ep 未退火)与
  ckpt-303(3ep 退火完)在已见 50 上逐位同分 27.90/50 —— 第三个 epoch +
  完整余弦退火净收益精确为 0(口径:仅已见 50)。

## 仓库版本状态(2026-08-20 整理)

- ostg:main == v11.1(a1707aa9,同步✓);datagenv12 工作区干净(c84145a6);
  v11.1 树有两个他人脏文件(sft/corpusaudit.py 改动、sft/tools/
  ship_dataset.sh 未跟踪),归属另一会话,不动。
- CUA:全部落 main 并已推送;本计划文档为 targeted-200 campaign 唯一定都点。

## 应用配额草案(已被上节 200 条配额取代,存档)

multi 20-25 · Calc ~20(chart/pivot/sheet_ops 为主)· Impress ~15(char_format
16|0 是最大单格)· GIMP ~10(layers/color_tone)· Writer ~10(char_format 6|0、
para_page_layout 8|1)· Chrome ~10 · Thunderbird ~5。
自检轨迹升采样(存量 66 条已定位)依赖 manifest 复制,与纯追加方案不合,
**暂缓**;如要做,以"新生成任务自带显式验证步"的形式并入生成规格。

## 开放问题

- 老时代(v8/v9)候选能否直接进当前 rollout 流水线(格式兼容性)——反驳
  agent 正在查;
- (untagged) 黑洞:chrome 23 条、multi 24 条 OSWorld 任务没进任何动作格,
  配额会系统性漏掉——等审计结论补词表。
