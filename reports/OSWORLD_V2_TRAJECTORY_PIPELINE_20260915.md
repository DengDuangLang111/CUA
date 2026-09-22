# OSWorld-V2 自动轨迹页面与 visual-signal 状态

## 结论

**V2 已启用与 Verified 同一套自动轨迹页面程序；真实模型内部 visual-signal 采集尚未接入 V2。**
截图、动作、think/response、执行图和已有判分证据可以自动整理。attention、logprobs、真实每图 token 映射等只有在原始信号确实记录时才能显示，不能从页面模板的存在推断已采集。

## 实际部署核验

Verified 部署：旧 WSL `/home/daniel_yan/cua-trajectory-tool-20260915`。

V2 部署：两台共享 fork 的 `local_eval/trajectory/`；Git commit `d552441917f302fab410a1991cc705d7bf585d14`。

本次逐文件比较确认下列5个核心文件字节一致：

- `sft/scripts/eval/after_task.py`
- `sft/analysis/visual_signals.py`
- `sft/analysis/trajectory_viewer.py`
- `sft/analysis/trajectory_viewer.html`
- `sft/analysis/trajectory_index.html`

V2 的 `local_eval/entry.py` 在内存中包装官方 `lib_run_single.run_single_example`，使用已有 `after_task.wrap_task`。额外处理只用于导出 V2 task class 的元数据和源码出处，不改变模型、动作或 evaluator 的结果。

## 当前能自动生成的内容

| 内容 | 状态 |
|---|---|
| 每题结束后的独立HTML、原始JSON、共享Index | 已启用 |
| 完整执行时间线、动作/状态图、重复动作和循环 | 已启用 |
| 原始前后截图、点击/拖动坐标标注 | 已启用；缺失截图保留不可用状态 |
| 原始think、完整response、工具/动作记录 | 已启用 |
| 已记录reward/done/score与判分代码出处 | 已启用；未保存的实际evaluator输入不会伪造 |
| 正常完成与异常中断的已有轨迹 | 支持；SIGKILL来不及回调的页可从保存记录补建 |
| attention、logprobs、真实每图vision-token映射 | V2当前未记录，不能显示为已采集 |

不是每一步都重建整站：回调在每题函数返回或抛异常后执行，只更新该题与索引。原始截图仍在各自机器，页面引用这些文件，不搬入GitHub。

## 实际产物证据

检查时 workstation 已有6个任务页面、439个step记录；另一台已有3个任务页面、203个step记录。检查的642个step记录全部为 `signal_status=unavailable`，非空signals为0。
这些是已经产生的页面记录；页面数量包含中断任务，不能当作已完成/成功任务数。

workstation 的007因强制结束清理进程来不及执行回调，已用相同 `render_v2 → render_task` 路径从原始轨迹补建；没有重跑模型或改变得分。

此前两台首个已完成页面和原始PNG都经过真实viewer HTTP handler验证：004和006的HTML/PNG均返回200。

## 输出路径

- workstation：`/home/yanji/cua-v2-shared-trajectories-20260915/`
- 另一台：`/home/daniel_yan/cua-v2-shared-trajectories-20260915/`

其中有 `index.html`、`index.json`、`manifest.json`、每题HTML，以及 `tasks/` 下的原始导出JSON。
131K旧批次与262K恢复批次按不同run路径区分，不会因为模型名称相同就合成一条轨迹。

## 如果需要真实模型内部信号

展示器目前消费 `<task>/visual_signals.jsonl`，它本身不向vLLM提取attention或logprobs。
要启用这部分，需要在推理侧记录可验证的request/response身份、原始模型输入图片与token位置映射，以及实际attention行或概率数据，再交给已有展示器。
未记录这些原始数据时，无法从截图或已生成文本可靠补算attention，也不能用估计值替代真实概率或token映射。

本次未修改推理内核或增设信号采集；262K恢复后继续使用已经启用的页面回调。

## 为什么当前没有 detect 到信号：逐段核查

1. **请求端没有请求这些信号**：`mm_agents/qwen_internal_agent.py:306` 构造的payload只有messages、采样参数和thinking模板开关，没有logprobs/attention采集设置。
2. **客户端只返回文本**：`mm_agents/qwen35vl_agent.py:644` 调用SDK后只取content与reasoning字段并返回合并字符串，没有把response ID、usage/logprobs或其他元数据写到信号文件。
3. **轨迹缺少匹配身份字段**：实际JSONL记录只有step_num、action_timestamp、action、response、reward、done、info、screenshot_file。request_id、request_sha256、response_sha256和checkpoint都没有记录。本次实查该run的`visual_signals.jsonl`文件数为0。
4. **展示器按预期报 unavailable**：`local_eval/trajectory/sft/analysis/visual_signals.py:218` 读取每题的`visual_signals.jsonl`；不存在时，第265–267行保留`signal_status=unavailable`及`No recorded visual signals for this decision.`。如果有文件但ID/hash/图片对不上，会在第302–330行进入unverified，而不是当前情况。

因此当前是**生产/采集端没有接入**，不是已有信号被页面漏检。仅接上after_task页面回调，无法自动产生模型内部数据。
