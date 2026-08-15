# ostg 仓库全史(2026-08-15 勘察)

`.git` 位于 `ostg/` 子目录(各父目录为普通目录),一个仓库、14 分支、6 个 worktree。
**拓扑是一条直线** —— 分支名是"时代标记",各自停在自己时代的末尾,无任何真实分岔:

```
v3-taxonomy → check → v5 → v6-single-json → v8/v8.1/v8.2 → v8.4 ─(+11)→ main ─→ v9 → v10 → v11 ──(+183)──→ v11.1
 08-08 15:19   19:15  21:01     21:06         08-08~09      08-09 05:42  08-09 07:35  08:18 18:32 19:03      08-15 03:58
     4笔        18     19         20            28~43           53           64        66   72    74           257
```

## 各时代干了什么

| 分支(时代) | tip 时间 | 累计笔数 | 本时代的贡献 |
|---|---|---|---|
| v3-taxonomy | 08-08 15:19 | 4 | taxonomy 初版;确立 CUA-Gym 为污染约束 |
| check | 08-08 19:15 | 18 | V3 对官方 Calc 任务实测校准 |
| v5 | 08-08 21:01 | 19 | 难度 = 应用数 × 需求数 |
| v6-single-json | 08-08 21:06 | 20 | 单 JSON 自包含任务 + prompt 重写 |
| v8/.1/.2 | 08-08~09 | 28–43 | setup/probe 必填(约束解码)、判分前 flush 文档、分片并行 |
| v8.4 | 08-09 05:42 | 53 | 双向审计闭环 |
| **main** | **08-09 07:35** | **64** | v8.4 + 11 笔:**ambiguity 进坐标积(10/30/30/30)+ voice 语域混合**、`--start-batch`、stringified-specs 解析、文档全面英译(tip) |
| v9 | 08-09 08:18 | 66 | control 补 deictic 盲区;preserve-thinking 内存爬坡记录 |
| v10 | 08-09 18:32 | 72 | **user-to-agent 指令转向**;`--spent-from` 配额账本(on keep);难度阶梯严格单调 |
| v11 | 08-09 19:03 | 74 | 修复管线(reject→廉价重写→再门控);extract 鲁棒化 |
| **v11.1** | **08-15 03:58** | **257** | **+183 笔 = 此后一切**:v11/v11-500 语料与 controls、traj_html、SFT 管线(build/traj/verify/filters)、dashboard、协议适配器(08-15) |

## worktree 地图(哪个目录跑哪个时代)

```
os-simple-taskgen      → v6-single-json     ostg-v10  → v10
os-simple-taskgen-v8   → v8.4  ← 08-15 误用于 v11q-325 的那次
ostg-v9 → v9           ostg-v11 → v11       ostg-v11.1 → v11.1  ← 生产血统
```

## main 是哪个 & merge 评估

**main = 08-09 07:35 的一个直线中间点**(英译文档收尾),此后没有任何独有提交 ——
`main..v11.1` = 193 笔,`v11.1..main` = **0 笔**。

**结论:v11.1 → main 是纯 fast-forward,无任何冲突可能,无任何"main 上别的改动"需要
结合(main 没有别的改动)。** 操作一条命令:

```
git -C /mnt/d/research/os-simple-taskgen-v8/ostg branch -f main v11.1
```

(main 未被任何 worktree checkout,移动引用零影响;各时代分支保留原位作历史标记,
将来可转 tag。)风险:无。收益:main 语义恢复为"最新生产血统",消灭今天这类
worktree 误用的温床。

**已执行 2026-08-15**:main `9317793d`(08-09) → `a361e753`(08-15, =v11.1 tip)。
六个 worktree 逐一核验原样;磁盘零文件变化;时代分支全部保留。
