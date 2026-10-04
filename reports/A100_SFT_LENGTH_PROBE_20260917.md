# 4×A100 80GB：505 条 SFT 数据的长度与显存短测

本轮由用户授权在已有 Klone 单节点占位 `40253867 / g3087` 内短测普通 Qwen3.5-9B；没有启动正式三轮训练，也没有修改 Tillicum 排队作业或其固定语料。

后续状态：用户同日进一步授权后，12:56 PT已在同一占位启动独立全量no_grad训练；以下内容保留短测当时的范围与结论。全量启动证据见[实验账本](../docs/EXPERIMENTS.md)及[启动验证](a100-nograd-full-20260917/launch_validation.json)。

## 数据与长度

复用 `r5-v16save143-tf`，505 轨迹、10,142 样本，数据 SHA256 `3d2881f2514e51b24314530d9478721081561de1f12f5433bfb678e728eca1dd`。10,157 张图片全部为 1920×1088；在 IMAGE_MAX_TOKEN_NUM=2048 下每图实际 2,040 tokens。全部数据已经传到 Klone，并对全部图片执行 PIL verify。

长度用实际 tokenizer/chat template 计算，再加入精确图像 token 展开；16 个样本（含数据边界、最长样本）与实际 Swift `template.encode` 的 input_ids 长度完全一致。中位24,170，P90 32,177，P95 35,197，P99 43,146，最大58,441 tokens。

| max_length | 超长行 | 占全部样本 | 会丢失末步的轨迹 | 若整条排除超长任务，保留轨迹/样本 |
|---|---:|---:|---:|---:|
| 16,384 | 7,170 | 70.70% | 480 | 25 / 125 |
| 24,576 | 4,730 | 46.64% | 370 | 135 / 1,272 |
| 32,768 | 914 | 9.01% | 81 | 424 / 7,291 |
| 49,152 | 28 | 0.28% | 3 | 502 / 10,008 |
| 65,536 | 0 | 0% | 0 | 505 / 10,142 |
| 81,920 | 0 | 0% | 0 | 505 / 10,142 |

调低上限不会缩小原本就低于上限的输入；若按默认超长丢弃处理，末步监督会消失。48K超长的三条均来自旧r5：acd3db2e、19a5b6dd、128c9ca6。上表的丢弃是长度审计结果，本轮没有实际改掉正式语料。

## 短测设置和已观察结果

四张 A100 80GB PCIe，同节点，16 CPU/384GiB主机内存。基座从 Klone 的普通 `Qwen3.5-9B` 复制到节点本地盘。bf16、ZeRO-2 optimizer CPU offload、batch1、accum16、global batch64、lr3e-6、last_round、preserve_thinking、SDPA（cuDNN backend禁用）、视觉塔/aligner参数冻结；每次最多2个optimizer steps，计划保存完整checkpoint。每个case有独立目录和40分钟执行上限。

| case | 压力样本 | 改动 | 结果 |
|---|---|---|---|
| cap48k_zero2 | ≤49,152 中最长64行，43,949–49,135 tokens | 原训练执行方式 | 第一步视觉编码OOM；约79GiB，额外申请360MiB失败，0/2 steps |
| cap32k_zero2 | 32,290–32,762 tokens，9或10张图；选取当时媒体已完整到达的最长64行 | 仅降低上限/压力样本长度 | 第一步视觉编码OOM；约79GiB，申请180/360MiB失败，0/2 steps |
| cap64k_frozen_nograd | 全数据最长64行，45,536–58,441 tokens | 仅对完全冻结的视觉塔显式no_grad | **2/2 steps完成，exit=0，完整checkpoint文件集写齐，语言权重更新已核对** |

64K最终结果：两步训练及保存耗时1,330.7105秒（22分11秒，不含此前模型加载），exit=0。第1步704.3055秒，第2步训练后累计1,273.4394秒，第二步增量约569.13秒；保存收尾另约57秒。两步loss均为0.6717397，grad_norm4.5031476/4.5029793，token_acc0.79185244；该两步短计划首步是warmup，第二步后cosine LR降为0，不应用此两点loss判断收敛。

Swift最终max_memory_reserved **63.65625GiB**；nvidia-smi每5秒采样峰值 **68,531MiB（66.92GiB）**，包含不同口径的占用，无再次OOM。最坏64行平均49,428 tokens，而全语料平均21,586；压力测试吞吐不能直接当作全语料平均速度。

检查点 `.../cap64k_frozen_nograd/train/v0-20260917-064332/checkpoint-2`：trainer global_step=2，4个模型分片、4个ZeRO optimizer分片、4个RNG文件及scheduler齐全，总146,017,668,974 bytes（约136GiB）。抽查3个语言模型矩阵切片，共36,864个值，其中2,527个确实发生变化，max_abs_delta均3.814697e-6，证明并非只执行forward或只保存未更新权重。基座775个tensor key比训练模型760个多15个未实例化的`mtp.*`辅助头，验证器仅允许这一已观察差异；主模型key无新增或其他缺失。checkpoint恢复运行未测试。

Slurm step `40253867.14` 为COMPLETED、耗时24分41秒（含启动加载），MaxRSS 351,830,432 KiB，约335.53GiB，因此本次384GiB主机内存分配也属于已测配置的重要条件。结束后四张GPU均回到0MiB/0%利用率，7天占位40253867继续RUNNING。

## no_grad 的范围

视觉塔原本就被冻结，不更新其参数。隔离补丁在每次视觉forward前断言全部视觉参数 requires_grad=False，然后只在该forward内使用 `torch.no_grad()`；图片数量、分辨率、特征维度、语言模型训练参数不变。它避免为这个冻结模块保留梯度图，不等于把图像删除或把语言模型冻结。日志记录输入requires_grad=False、进入该段时全局grad_enabled=True。

本轮没有把此补丁部署到正式训练环境；它仅由短测case的环境开关启用。已经验证两个optimizer steps、非零梯度、实际语言权重变化及完整checkpoint文件集；未验证checkpoint恢复和全语料训练。短测的epoch1/2只指64行压力子集的两遍，不是505条全量数据的epoch，更不能声称效果或所有样本均已验证。

## no_grad影响：官方文档核查（同日补充）

用户进一步要求搜索no_grad影响。PyTorch官方[autograd说明](https://docs.pytorch.org/docs/2.14/notes/autograd.html)说明，no-grad计算的输出可以继续用于后续grad-mode训练；`no_grad`与`eval`独立。对固定视觉特征 z=V(x;theta_v)、只训练后续LLM参数theta_l而言，只要z数值保持一致且没有需要穿过V的上游梯度，移除V的反向图在数学上不改变LLM梯度。但此条件不能由“LLM权重发生更新”单独证明。

需要收紧此前机制解释：**标准autograd中，若普通运算的所有输入（含权重）均requires_grad=False，该运算本来就不会记入反向图**。本次参数冻结断言通过、入口图像输入也为False，却观察到显著内存差异，其具体来源尚未定位；内部hook、checkpoint或grad-mode相关实现只能作为待查假设，不能宣称已查明。

不适合包进no_grad的情况：视觉塔内有需要训练的LoRA/adapter/projector，或视觉塔之前有可训练模块、需要把梯度传回它；需要图像输入梯度的任务也不适合。Hugging Face官方[enable_input_require_grads](https://huggingface.co/docs/transformers/main_classes/model#transformers.PreTrainedModel.enable_input_require_grads)说明其用途正包括模型主体冻结时的adapter训练；因此不能把所有输入梯度hook都当成多余。

正式采用前未完成的关键验证是同权重、同batch、同随机状态、同train/eval/autocast设置的A/B：比较视觉特征、loss、各训练参数梯度及一步更新；区分未预期断梯度与浮点容差内差异。本轮证据仍定位为“能运行、能更新、能保存”，不升级为数值或训练效果等价结论。搜索到的在线稳定文档为PyTorch2.14，本轮实际运行版本为2.13；API一般语义参考官方文档，具体框架路径仍需以已安装版本审计。

## 产物

- [长度统计](a100-length-probe-20260917/length_summary.json)、[逐行长度与任务溯源](a100-length-probe-20260917/row_lengths.jsonl)、[整轨迹保留量](a100-length-probe-20260917/whole_trajectory_retention.json)、[媒体校验](a100-length-probe-20260917/media_validation.json)。
- [三组实测汇总](a100-length-probe-20260917/smoke_summary.json)、[checkpoint与语言权重变化核查](a100-length-probe-20260917/checkpoint_verification.json)。
- [实验脚本](../sft/experiments/a100-length-probe-20260917/smoke.sh)、[隔离补丁](../sft/experiments/a100-length-probe-20260917/sitecustomize.py)、[检查点验证脚本](../sft/experiments/a100-length-probe-20260917/verify_checkpoint.py)。
- Klone `/gscratch/cse/jy050706/sft/experiments/a100-length-probe-20260917/results/` 保存独立case日志、GPU采样、退出码和训练输出。
