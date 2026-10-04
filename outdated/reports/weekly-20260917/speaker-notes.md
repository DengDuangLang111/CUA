# Visual signals — short speaking notes

## English, about one minute

After finding that we could compress older screenshots without changing the pass count in this run, I wanted to see how attention is distributed across those images.

During evaluation, we save the exact input screenshots and attention from one selected layer and head. For each model decision, we average attention across the output tokens, add up the patch weights within each image, and normalize over all input images. This tells us each image’s share of image attention; it is not its share of the entire text-and-image context.

Here is one real step. The current screenshot gets about 16%, while attention is distributed across several older screenshots. In another example, the current image gets about 81%.

To move beyond examples, I compared 65 tasks at the same step, with the same ten-image budget. The newest history image ranks first, but the oldest retained image ranks third. So attention does not simply decrease with age. Successful and unsuccessful tasks also overlap substantially: more concentrated attention does not automatically mean a better action.

I use these signals alongside screenshots, actual actions, and evaluator results to debug what went wrong.

## 中文讲法

前面发现历史图片压缩以后，通过题数没有下降，所以我进一步想看：模型实际会把注意力分给哪些历史图片。

我们在 eval 时保存真实输入截图和一个指定层、head 的 attention。每一步先把输出 token 的 attention 平均起来，再把同一张图上的 patch 权重加总，得到它在全部图片 attention 中的占比。这个比例不包含文本部分。

这个例子里，当前图只有大约 16%，其余分散到多张历史图；另一个例子里，当前图占到 81%。所以两种分布都存在。

再看同一步、同样十张图的 65 道题：最近的历史图平均最高，但最旧的一张排第三，并不是越旧就越少看。成功和失败任务的分布也有很大重叠，因此 attention 更集中不等于动作更正确。它的价值是配合截图、执行动作和评分结果，一起定位问题。

# Failure-case coverage

Use the page selector or “Failure-mode coverage” to choose cases. The report now contains eight representative case types, with one main image and three questions per case: what it did, why the recorded outcome failed, and what it should have done.

- Grounding / state loss — wrong close target loses the original cursor.
- Incomplete verification — freezes only a row, not both rows and columns.
- Action sequencing — intended Shift-click / subscript formatting is not correctly executed.
- Recovery corruption — repeated replacements leave a malformed paragraph.
- Repetitive action loop — the explanation changes but the old click coordinates repeat.
- Feasibility / terminal status — missing hardware is acknowledged yet success is emitted.
- Planning / step budget — one deliverable is completed, the second is never produced.
- Command / evaluator constraint — a per-file conversion loop fails a specific command-history rule.

This is coverage of evidenced case types, not an exhaustive causal classification of all failures. All 48 non-full-pass trajectories were screened for repeated decision patterns; 14 triggered the heuristic, including 7 with non-WAIT actions. These counts are candidates, not counts of repetition-caused failures. Environment/capture errors are documented separately and are not attributed to visual reasoning without further evidence.
