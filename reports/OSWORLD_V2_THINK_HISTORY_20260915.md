# OSWorld-V2 think 历史实测与 OSWorld-Verified 对齐

## 结论

当前 workstation agent 开启 `enable_thinking=True, preserve_thinking=True` 后，连续 3 步真实 Teacher 调用均产生非空 think 和正确可解析的下一步动作。
服务端 `/v1/chat/completions/render` 的 token IDs 经 `/detokenize` 还原后，第 2 步包含第 1 步完整 think，第 3 步包含前两步完整 think。

在固定相同 system prompt、instruction、截图、原始 assistant 回复，且关闭 Verified 图像年龄压缩的条件下，实际 OSWorld-Verified `history.py` 的消息构造结果与三份 V2 实际请求 **3/3 完全相同**。
这证明两者的完整 think 历史保存/回放方式可以对齐；不代表整个 benchmark、全部 system prompt 或动作执行协议都相同。

## 测试对象和范围

- 服务：Klone `g3104`，作业 `40172229`，Qwen3.8-27B BF16、TP2、2×L40S，vLLM 0.25.1，131072 上下文。
- agent：workstation `/home/yanji/research/OSWorld-V2-0808/mm_agents/qwen_internal_agent.py`，已完成用户指定的三个官方行为恢复；SHA-256 `8198beea2eb41bb2a49356e3328dc02b5b47d4661481cc320b95ca2d1a2b588d`。
- 临时测试参数：`enable_thinking=True`、`preserve_thinking=True`、`history_n=100`、`image_max=10`、`fold_size=1`、temperature 1.0、top-p 0.95、max_tokens 81920。
- 3 张 1920×1080 受控截图：START → CONFIRM → 完成提示；调用真实 agent.predict 和真实 Teacher。检查生成的点击坐标是否落在按钮范围，最后一步是否返回 DONE。
- **没有执行 VM 动作，也不是完整 OSWorld 任务成功率测试。** 正式 runner 的 thinking 参数没有被改动。

## 三步真实调用

### 上一轮正式 run 的实际状态（后续追查）

`results_v2/qwen38-27b-v2-20260905/pyautogui/screenshot/qwen38-27b/args.json` 的两个开关均为 False：`enable_thinking=False`、`preserve_thinking=False`。
对 39 个已出分任务的 39 份 `traj.jsonl` 检查：7,748 条带字符串 response 的日志记录中，非空 think 块为 0，仅空 think 块的记录为 4；顶层非空 reasoning/reasoning_content 字段为 0，JSON 坏行 0。这里是日志记录数，未去重，不能当作独立模型调用/步数。
因此上一轮没有开启 thinking，也没有发现实际返回的非空 think 历史。
用户随后决定正式配置继续保持 `preserve_thinking=False`；这不等于关闭完整回复历史回放，也不自动开启新 thinking。正式 enable_thinking 仍保持原值，独立三步测试的 True 不写回正式配置。

| 步 | 本步 think 字符数 | 服务端最终输入的历史 think | 输入 token 数 | 解析动作 | 预期动作检查 |
|---|---:|---|---:|---|---|
| 1 | 254 | 无历史 | 3420 | `pyautogui.click(960, 649)` | 点击 START，通过 |
| 2 | 281 | 第 1 步完整 think，1/1 | 5603 | `pyautogui.click(960, 649)` | 点击 CONFIRM，通过 |
| 3 | 307 | 第 1、2 步完整 think，2/2 | 7787 | `DONE` | 完成，通过 |

每步用完整返回文本解析得到的动作，与只解析 `</think>` 后正文得到的动作相同；本次三步未发生 think 文本被误当额外工具动作的现象。
“能看到”在这里指完整内容出现在模型 token 输入中，不证明模型每次都正确利用历史，也不证明开启后 benchmark 分数一定提高。

## preserve_thinking=False 的真实对照

固定第 3 步同一份请求，仅将 `preserve_thinking=True` 改成 False；`enable_thinking` 保持 True：

- 两个历史 think 仍全部保留。
- 最终渲染文本逐字节相同。
- token ID 序列完全相同，均为 7787 tokens。

原因有两层：当前 client 将完整 think 写进历史 `assistant.content`，模板没有主动删除这段 content；当前消息结构又把后续截图包在 `<tool_response>` 中，属于同一用户任务内的连续工具回合。
实际模型 `/gscratch/cse/jy050706/sft/models/Qwen3.8-27B/chat_template.jinja` 第 88–99 行确定 `last_query_index`，第 116 行的保留条件为：

```jinja
preserve_thinking is undefined or preserve_thinking is true or loop.index0 > ns.last_query_index
```

因此此处不能用单独开关 preserve_thinking 来构造“有/无历史 think”消融。若将来需要无历史对照，必须改变实际历史内容并重新核验最终 tokens；本次没有做这种修改。

渲染还显示每个历史 assistant 轮可出现“模板的空 think 块 + content 内真实 think 块”两块。历史内容没有丢失，三步真实调用输出正常；这是当前模板/消息表示的实测形式，不应描述为只有一个规范化 reasoning 字段。

## 截图折叠与 history_n 边界

以下为真实 agent 消息构造和真实服务端 token 渲染检查，但历史使用唯一的合成标记，没有额外跑 102 次模型推理：

| 当前步数 | 保留截图 | 历史标记 | 结果 |
|---|---:|---:|---|
| 12 | 10 | 前 11 步 | 11/11 全部在最终输入中；22397 prompt tokens |
| 102 | 10 | 前 101 步 | 仅第 1 步移出，余下 100/100 保留；27741 prompt tokens |

当前 `start_step = max(1, total_steps - history_n)`。所以 `history_n=100,max_steps=100` 不会因历史条数限制移除该 episode 的早期 think；`image_max=10` 限制的是图片，不是完整文本。
长任务仍受 131K 模型上下文及输出预算限制；本次没有完成真实 100 步长轨迹测试。

## 与实际 OSWorld-Verified 的代码对照

源文件：旧 WSL `/mnt/d/research/OSWorld/mm_agents/qwen/history.py`，本次 SHA-256 `46a0fb8552a1bcca0c62cff14e3f46fbc63f2f8a6b98729972909e0b4b0edbca`。
读取了实际 `main.py` 和 `client.py`：

- `client.py` 将 `reasoning_content` 或 `reasoning` 与 content 合并为带 think 块的完整回复。
- `main.py` 先将完整回复追加到 `self.responses`，再单独解析动作；`self.actions` 不代替完整回复历史。
- `history.py` 从 `responses` 回放 assistant 历史，`ensure_empty_think_prefix` 与 V2 `_normalize_think` 的核心行为相同。
- 两者都有 `history_n=100` 的文本窗口，以及独立的 image_max/fold_size 截图窗口。
- Verified 对非 DashScope 的 thinking=True 请求同样发送 chat_template_kwargs；它另外支持 `OSTG_REASONING_EFFORT`。V2 本次依赖模型模板默认值，服务端渲染实查默认为 xhigh；不能把所有历史 Verified 实验的 reasoning_effort 都假定为相同。

使用从实际 Verified 源文件提取的原函数，固定前述相同输入重建 V2 第 1、2、3 步 messages，三份完整消息列表逐项一致。
比较的是 history builder 这一层；Verified 的可选 HISTCOMP 图片年龄压缩在此对照中关闭。

## 原始证据

workstation 目录：`/home/yanji/research/OSWorld-V2-0808/resume-20260915/think-history-probe/`。

- `step-1/2/3.request.json`：真实 agent 请求（包含受控图片，不包含 API key）。
- `step-1/2/3.response.txt`：真实第三方模型的返回。
- `step-*.preserve.token_ids.json` / `.rendered.txt`：服务端最终输入。
- `step-3.no-preserve.*`：关闭保留开关的渲染对照。
- `structural-12.*` / `structural-102.*`：截图与文本窗口边界检查。
- `summary.json`、`verified-history-comparison.json`：机器可读结果。
- 独立测试脚本：workstation `/tmp/osworld-v2-think-history-probe-20260915.py` 与 `/tmp/osworld-v2-compare-verified-history-20260915.py`。

测试只创建独立实例和审计文件，没有修改 agent/runner 源码、旧结果或正式评测开关。
