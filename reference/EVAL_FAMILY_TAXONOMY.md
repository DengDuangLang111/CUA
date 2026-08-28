# Evaluator 族归类(117 → 11)—— 统计与配额的唯一口径

> 定稿 2026-08-28。可执行的真相在 `CUA/tools/family_census.py`(前缀规则表
> `PREFIX`,顺序敏感);本文件是它的散文镜像 + 决策依据。改映射先改代码,再改这里。

## 为什么是 evaluator 族,不是动作词表

两次实测(2026-08-28,官方 361 全量 LLM 标注 + 对抗复标):

- 旧关键词标注器 `tools/taxonomy_tag.py`:对 LLM 标注 **precision 0.50 /
  recall 0.46**,24% 任务打不上任何标签。**已废弃**,历史结论凡引用它的数字
  一律视为基于已废弃口径。
- 动作词表本身:两个标注者、同一词表、同一批任务,**分歧 25%**。边界(文字
  编辑归哪个筐、"导航到设置页"算不算改设置)靠定义写不死。

`evaluator.func` 是任务 JSON 里的一个字符串,零判断空间。所以:
**统计、配额、缺口分析一律用 `(domain, family)`;动作词表降级为人读注释,
不进机制、不算比例。**

## 11 族与官方 369 全量分布

`family_census.py` 对官方 `evaluation_examples/examples` 实测:

| family | 判定手段 | 任务数 | 占比 |
|---|---|---|---|
| text_or_shell | 文本/stdout/文件内容比对(check_include_exclude、exact_match、diff…) | 70 | 19.0% |
| table_property | 工作簿属性比对(compare_table 及 CSV 系) | 64 | 17.3% |
| config_state | 配置/偏好读取(check_json_settings、gsettings 系) | 47 | 12.7% |
| deck_property | 幻灯片属性比对(compare_pptx_files 系) | 42 | 11.4% |
| doc_property | 文档属性比对(compare_docx_files 系) | 35 | 9.5% |
| browser_state | 浏览器活态(URL/tab/书签/扩展) | 32 | 8.7% |
| infeasible | 裸 `{"func":"infeasible"}`,FAIL 记 1 | 27 | 7.3% |
| image_property | 图像属性/结构比对(gimp.py 系) | 27 | 7.3% |
| media_state | VLC 配置/播放态/音视频比对 | 16 | 4.3% |
| pdf_property | PDF 比对 | 9 | 2.4% |

(361 跑测面板上的对应计数见 PLAN-20260828-v14g-gold §0。)

## 族 → 生成机制的映射(ostg v14g)

`taskgen/taxonomy.py:FAMILIES` 是权威;摘要:

| family | grade | 宿主 | gold 需求 |
|---|---|---|---|
| text_or_shell / config_state | probe | 任意 / 配置类 | 无 |
| browser_state | browser | chrome | 无 |
| table_property | table_gold | calc | **要**(官方 56 例中 55 例带 gold) |
| deck_property | deck | impress | **要** |
| doc_property | doc | writer | **要** |
| image_property | image | gimp | expected 槽端 **seed 原图**(方向性判定器) |
| media_state(仅 vlcrc 配置子型) | probe | vlc | 无 |
| infeasible | infeasible | — | 无(走 `infeasible_share`,不是族权重) |

**明确不做(wave-2)**:pdf_property(bake 便宜、comparator 校准未做,第一顺位);
media 的 AV 子型(5 例,要音视频道具 + ffmpeg 链)与运行态子型(4 例,评分依赖
活进程)。media 16 例的三分:纯配置 7 / 运行态 4 / AV 5(2026-08-28 实测)。

## 关联

- 生成侧实现与验收:`PLAN-20260828-v14g-gold.md`
- 三方动作普查(注释用途):会话记录 2026-08-28;动作分布表不再维护为口径
