# 术语表 — 本项目所有标准说法(2026-08-30 立,防语义漂移)

> 规矩:①对话与文档一律用"标准词"列的说法;②新概念先入此表再使用;
> ③代码/命令列是锚点,词义有歧义时以锚点为准。别名列是**禁用词**(历史黑话)。

## 流水线六步(顺序固定)

| 标准词 | 一句话 | 代码锚点 | 禁用别名 |
|---|---|---|---|
| 生成 | LLM 按抽中的格子一次产出"题面+初始化+判据+做答案脚本" | taskgen/gen.py | gen |
| 门闸 | 生成后的静态格式检查,不合格丢弃重抽 | gen.py `gate()` | gate |
| 烤箱 | 构建容器里真跑一遍:做出种子和答案文件并存档 | taskgen/bake.py | bake、B类烤箱 |
| 虚拟机验证 | 在真 VM 里做负向检验+注入检验(合并为一次开机,08-30 起) | taskgen/control | control、闸 |
| 查重对撞 | 文本查重 + 与官方/CUA-Gym 撞题检查,命中即删 | taskgen/accept | accept |
| 合并 | 多批任务并成一个总池目录 | taskgen/merge | merge |

## 检验体系

| 标准词 | 一句话 | 代码锚点 | 禁用别名 |
|---|---|---|---|
| 探针 | 每题现写的检查程序,在 VM 里跑,打印 PASS/FAIL | spec 的 probe 字段 | probe |
| 答案文件 | 生成时先做出来的正确成品,判分时逐字节比对 | files/<slug>/gold/ | gold |
| 判据 | 官方判分函数+它的参数(查什么、期望什么) | evaluator.func | func、判分器 |
| 复合判据 | 一道题挂多个判据(主产物+副产物各查各的) | evaluator.func 列表 | multi-func |
| 副产物 | 题面要求的第二产出(台账/日志),难题必须连它一起判 | — | side-artifact |
| 单轴合同(级) | 级=应用数(官方词表 9 词,os 家族整体算 1 个),1/2/3 均分;组合由抽签发牌、门闸照牌验收;含 os 比例 d2 59%(官方)/d3 50%(用户压缩,常数在 draw_combo);os 要计数必须干实活,搬运不算(2026-08-30 用户裁定) | gen16.py draw_combo+gate | 判据数=难度(旧)、os不计数(旧) |
| 意图族 | 任务性质轴,19 族(用户全谱裁剪,交易/远控/监控/远程协作弃);族名+动词串进输入行,示例永不进提示词;创意制作限 impress/gimp/writer | gen16.INTENTS+draw_intent | intent、目的 |
| os 工种 | os 主应用三分:设置 45/终端 45/文件管理 10(照官方 24 道) | gen16.draw_oskind | os-trade |
| 预打开数 | warm=K:开局已打开的应用数,0..GUI 应用数均匀,指代型(a3)≥1;K<应用数即逼中途开应用 | gen16.draw_warm+open_paths | warm start(旧布尔) |
| 装箱16 | v16 装箱一条命令:合并查重→撞题(官方+CUA-Gym,3-gram)→prebuild→容器冒烟(setup 实跑 rc==0)→官方格式任务 JSON | taskgen/emit16.py | emit、ship16 |
| 定点自检 | 烤箱出炉检查:种子必须判0分、答案必须判满分 | bake.py `_FP` | fixed point |
| 负向检验 | VM 里不做题就判分,必须0分(防白送分) | control | negative |
| 注入检验 | 把答案文件塞进 VM 再判分,必须满分(防判据永不可满足) | control --gold | tier1、Tier-1 |
| 往返容差 | 答案文件经 VM 的 LibreOffice 重存后仍须满分 | gold.py tier2 | tier2、Tier-2 |
| 审计 | LLM 判官读题面+判据,答固定问题(可开思考) | taskgen/audit.py | audit |
| 体检 | 每批任务的多样性/可验证性自动报告 | taskgen/divcheck.py | divcheck |
| 修补 | 门闸拒收后只重写题面措辞的廉价返工(全上下文+只改措辞) | gen.py repair_instruction | repair |

## 判据质量三律(08-30 定)

| 标准词 | 内容 |
|---|---|
| 对称条款 | 判据只可要求题面明文说过的性质;歧义作用于措辞,不作用于要求集合 |
| 内容不查格式 | 题面没钉死格式的,判据查内容元素(含),禁比对整行结构 |
| 固有文书律 | 副产物必须是该职业场景真实存在的文书,不许发明无人保存的记录 |

## 统计与口径

| 标准词 | 一句话 | 禁用别名 |
|---|---|---|
| 评分家族 | 任务的统计主轴,按判据类型归 11 族 | family、族 |
| 格子/抽签 | 配方按 难度×歧义×口吻×应用×家族 抽坐标 | 坐标、cell |
| 判据口径通过率 | "完成了被判分部分"的比率——不等于完成题面全部要求 | — |
| 载荷对撞 | (判据,查什么,期望值)三元组与官方逐条比,防换皮抄题 | collision |
| 操作指纹 | 做答案脚本用到的操作集合,聚类后看动作多样性 | fingerprint |
| 旅程 | 题面要求的完整做事过程(尤指跨应用部分) | journey |
| 计数应用 | 数难度用的八个文档/图形应用(表格/文档/幻灯片/浏览器/图像/邮件/播放器/代码编辑器) | GUI apps |
| 环境设施 | 终端/文件管理器/系统设置——随便用,不计入应用数 | 辅助应用、cheap apps |
| 示例跟签 | 抽中哪种规则/判据,提示词就配那种的官方真例 | example-follows-draw |

## 轨迹判分(rollout 侧;细节 JUDGING.md)

| 标准词 | 一句话 | 代码锚点 | 禁用别名 |
|---|---|---|---|
| 盲评判官 | 看不到程序评分的轨迹打分员(0-10),只提名不定罪 | sft/trajaudit.py | judge、trajaudit |
| 仲裁 | 分歧轨迹的定罪环节:亮判据代码,Opus5+思考 | sft/arb.py | arb |
| 强判官 | v16 唯一裁判:规则闸拦掉后每条一次调用,给二元判定+要求清单。生产证据袋=末尾8帧+全动作(不给思考/不给自述,2×2 实测四格纯度无差异)+磁盘转录 | sft/strongjudge.py | strong judge、llm judge |
| 严格准入 | 轨迹级准入的收紧口径:判官 success 且每条要求 done=yes 之上,再要求全部要求有截图为证(无 inferred/cannot_tell/crit_fail/evidence 违规,derived≥10);v16 全池 1374 → 340 | curate16.py `--strict` | strict-340、证据闸 |
| 步级过滤 | 对已准入轨迹的每一步打 0-10 分,>5 留作训练目标,≤5 不算 loss 但仍留在后续步上下文;末步不直接删 | webstar_step_filter grade_steps / decide_steps / filter_copy | WebSTAR、step filter、stepaudit(另一工具,教师看前后帧打元数据,不删) |
| 终止规范化 | 教师重写每条轨迹的末步理由并确定性拼上 terminate(success);没做时末步是纯散文,harness 贴的 DONE 不是模型动作 | terminalfix.py + build `--terminal-rewrite`;验收 verify `--require-terminate` | terminal-rewrite、补 done |
| 规则闸 | 判官前的零成本确定性拦截:自报 FAIL/空轨迹直接记败,不花判官钱(承 OpenWebRL) | strongjudge.py 门 | protocol gate |
| 双判官 | **已废(08-31)**:2×2+3臂对照证明错放是系统性盲区不是手抖,四种证据配置在同一批硬负样本上一起栽,冗余无效、只翻倍成本 | — | double judge |
| 哑判据 | v16 可行题的占位判据(恒 0),程序分作废、判官唯一裁判;infeasible 题仍挂真 `infeasible` 判据白捡信号 | emit16.py ZERO_EVAL | dummy evaluator |
| 完成度/证据度 | 要求项拆成两个独立字段:`done`(yes/partial/no/cannot_tell,做到了吗)与 `evidence`(seen/inferred,看见的还是推断的);旧的六值枚举把两者混在一起,`mostly_satisfied` 实为"按了保存但没拍到确认" | strongjudge REQ_PROPS16 | status、satisfied 六值(旧) |
| 磁盘证据 | rollout 判分前把 VM 里 /home/user 最终状态转录成文字给判官(`OSTG_FINAL_STATE=1`);治"像素里看不见"的那类错放 | final_state.py + J2 | J2、final_state |

## 防臃肿立法(08-30 用户批准)

**每件进流水线的新东西,提案必须写明它替代或删除了什么。** 净增机器需专门论证。
