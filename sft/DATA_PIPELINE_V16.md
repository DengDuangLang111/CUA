# v16 数据管线:判官制下从轨迹到训练数据

> **这份是 v16(判官制)的管线。** v11/v14 那份在 `DATA_PIPELINE.md`,
> 它写的是 **checker + 判官 + 仲裁**三方体系;v16 没有程序判据,
> 三方变一方,管线因此少了两层、多了一条新口径。
> **v11 那份仍然有效的部分**(图片 key 带 task_id、静默失效九例、
> 工具故障伪装成对象故障、扫多轮语料的两个坑)不重复,按需回查。

---

## 0 v16 与 v11 的结构差异

```
v11:  rollout → traj → trajaudit(判官) → arb(仲裁 checker vs 判官)
                                          → curate(五张名单)→ terminalfix
                                          → build → verify → corpusaudit
                                          → to_swift → ship → preflight

v16:  rollout → traj → strongjudge(判官,边跑边判)→ curate16(一张名单)
                                          → build → verify → corpusaudit
                                          → to_swift → ship → preflight
                     ↑ 少了 arb 和 terminalfix,原因见 §2、§3
```

| 层 | v11 | v16 | 说明 |
|---|---|---|---|
| ① rollout | 同 | 同 | v16 的 `result.txt` **恒为 0**(哑判据),不是故障 |
| ② `traj.py` | 同 | 同 | 一步一样本,未改 |
| ③ 判官 | `trajaudit` | `strongjudge` + `tools_judge_loop.sh` | **边跑边判**,见 §1 |
| ④ 仲裁 `arb` | 需要 | **不适用** | 没有 checker 就没有分歧可裁,见 §2 |
| ⑤ 筛选 | `curate`(五张名单) | **`curate16`**(一张 admitted) | 口径全新,见 §4 |
| ⑥ `terminalfix` | 必需 | **可跳过** | 病根消失了,见 §3 |
| ⑦-⑪ build/verify/corpusaudit/to_swift/preflight | 同 | 同 | 未改 |

---

## 1 判官边跑边判(这一轮新增,省了一整段墙钟)

rollout 吃 GPU + EC2,判官吃 Claude API,**两边资源完全不重叠**。
串行是 `rollout + judge`,流水线是 `max(rollout, judge)`。

实测(v16 这轮):判官 **11.5 条/分钟**(6 路并发,单条 31 秒),
rollout 峰值 7-8 条/分钟 —— **判官始终在等 rollout**,所以省下的是判官那一整段
(1386 条约 2 小时)。

**正确性支点**:`result.txt` 是安全的完成信号。
`lib_run_single.py` 里 `traj.jsonl` 先 append(86-97 行),`result.txt` 最后写(117 行);
实测 107 条:result.txt 晚于 traj.jsonl 100 条、同秒 7 条、**早于 0 条**,
晚于最后一张截图 105/105。**目录里出现 `result.txt` = 轨迹和截图已完整落盘。**

**最小实现,不要做队列系统**:判官本就支持断点续跑,所以

```
每 N 分钟扫结果树,挑出同时满足四条的去判:
  ① 有 result.txt   ② traj.jsonl 非空
  ③ 不在已判台账    ④ 不在缺陷清单
```

幂等 + 定时重跑 = 流水线。`tools_judge_loop.sh` 就是这个,6 分钟一轮。

**中断安全**:rollout 断线时在飞任务会留下"有 traj 没 result.txt"的半截目录,
条件①天然把它们挡住;恢复后 runner 也按 result.txt 判断重跑,不会漏。
**这条流水线不需要为中断做任何特殊处理。**

---

## 2 为什么没有仲裁层

v11 的 `arb` 裁的是「checker 判定 vs 判官判定」的分歧,`curate` 的原则是
**判官提名、仲裁定罪** —— 只有证据能封杀。

v16 的可行任务挂的是恒返回 0 的哑判据(`check_include_exclude` + 永不命中的 rule),
**没有 checker 信号**,分歧不存在,仲裁失去输入。

**代价要说清楚**:v16 是**判官单签**,没有第二个独立信号交叉验证。
v11 体系里判官错了还有 checker 兜;现在没有。
缓解手段是判官侧的配置对照实验(2×2:全帧 vs 末 8 帧 × 给不给 agent 自述),
以及 J2 的磁盘证据 —— 但那是提高单个判官的准确率,不是引入第二个信号。

---

## 3 为什么可以跳过 terminalfix(实测,不是省事)

**terminalfix 存在的原因**(`build.py` 注释记的实测):v11 语料里
**72% 的轨迹靠"不调工具"结束**,harness 把它算作 DONE ——
拿这种语料训练,4B 学生的显式终止能力从 **eval-50 上 100% 掉到 0%**。

**v16 收录轨迹的结尾形态(577 条实测)**:

| 结尾 | 条数 | 占比 |
|---|---:|---:|
| **显式 DONE 动作** | **552** | **95.7%** |
| 末步是普通动作(隐式结束) | 22 | 3.8% |
| 以 WAIT 结尾 | 3 | 0.5% |

**隐式结束从 72% 降到 4.3%,病根基本消失。** 两个原因:
① 教师带 `--enable_thinking --preserve_thinking`,本就倾向显式宣告;
② **收录规则要求每条 requirement 都 done** —— "跑到一半没声了"的轨迹进不来。

**处置**:跳过 terminalfix,用 `build.py --exclude` 加一条硬过滤代替:

```
排除末步非显式 DONE/FAIL 的     25 条(4.3%)
排除撞 50 步上限的              29 条(5.0%)
```

最多损失约 9%,换掉一整层(判官重写结尾 + md5 画面硬门)。
**保留 terminalfix 的唯一理由是救回那 25 条,不值得为此维护一层。**

⚠ **这个结论绑在"结尾形态"这个实测上,不是永久豁免。**
换教师、换采样配置、换 max_steps 之后,**必须重量一次隐式结束占比**;
超过 10% 就把 terminalfix 加回来。

---

## 4 收录口径(`curate16`,2026-08-31 用户裁定)

```
python3 -B -m ostg.sft.curate16 judge-*.jsonl --tasks SET [SET ...] \
    [--defects v16_fixture_defects.json] [--out admitted.jsonl]
```

**规则:`j_verdict == success` 且每一条 requirement 都已完成。**

- `done=yes`(v16 schema)或 `satisfied`/`mostly_satisfied`(老 schema)——
  **两套 schema 并存,必须都读**。
  (我第一次只读 `done` 漏掉老 schema,收录率算成 29.4%,真值 40.3%。)
- **`critical` 故意忽略**:判官给的布尔,提示词里无定义,87% 的条目都被标 critical,
  而一条题面明写的要求曾被标成非 critical 溜过去。
- **证据质量(seen/inferred)故意不纳入**:收录集里 `inferred` 占 16.5%
  (全体 22%),强求 `seen` 会把收录率从 49.7% 砍到 29.5% ——
  **那不是纯度,是惩罚判官看不见的东西**。J2 的磁盘转录才是把 `inferred`
  变成 `seen` 的手段,**它上线之后再收紧,不是现在**。

**实测收录率(判官跑到 1430 条时)**:576 条 = 40.3%,分域:

```
os 86.2% · vs_code 71.8% · calc 63.5% · gimp 61.3% · vlc 45.5%
writer 45.3% · chrome 39.0% · multi_apps 35.8% · impress 35.5% · thunderbird 16.2%
```

`--defects` 传缺陷清单,把 fixture 坏掉的任务排除(v16 这轮剩 7 条修不好)。

---

## 5 接口对齐(实操时最容易卡的地方)

- `curate16` 出 **`admitted.jsonl`**(一行一条 `domain`/`task_id`);
  `build.py` 用 **`--include`** 吃它 —— 参数名不同,别找 `--admitted`。
- `build.py --terminal-rewrite` **不传即为跳过 terminalfix**,不需要改代码。
- `build.py` 的渲染参数必须与 rollout 一致:`--image-max` / 折叠设置来自
  `mm_agents.qwen` 的同一份代码,**样本结构不会漂**,但 CLI 侧的
  `--tail-run` / `--think-cap` 要按臂对齐。

---

## 6 v11 那份里仍然有效、不要重新踩的

- **图片 key 必须带 `task_id`** —— 这是结构保证,让两条轨迹不可能写进同一目录;
  有了它就不需要逐像素复核(那是用最贵的方式学到零信息)。
- **静默失效九例**:数字只是悄悄变小,不报错。断言要放在丢弃点上。
- **工具故障会伪装成对象故障**:一天撞四次的那些。
- **推文件必对 md5**;数据生成代码先入 git 再跑,日志记 code hash。
- `verify` 只看语料自己,`corpusaudit` 要回头读原始轨迹 —— 两者不可互相替代,
  后者定位在 **build 之后、ship 之前跑一次**。
