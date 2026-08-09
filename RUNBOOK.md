# ostg 标准操作手册

从生成到 SFT 数据的每一步标准指令。全部在 **WSL** 上执行(Mac 只改代码);
设计与阈值的"为什么"看 [README.md](README.md),这里只记"怎么跑"。

约定(下文所有命令假设已设):

```bash
TG=/mnt/d/research/os-simple-taskgen-v8      # 执行仓库,branch v8
OW=/mnt/d/research/OSWorld
P=$OW/.venv/bin/python
R=$OW/results_generated/qwen36-27b-bf16-local
cd $TG
```

流水线全景:

    gen(可分片) -> ship(re-emit+gates) -> [cull] -> merge -> control(3路) -> rollout -> traj_html -> 分析/SFT抽取

---

## 0 同步代码 Mac → WSL

Mac 端 scratchpad 仓库提交后:

```bash
git bundle create /tmp/ostg.bundle <上次同步的commit>..v8
cat /tmp/ostg.bundle | ssh osworld-windows 'wsl -e bash -lc "cat > /tmp/ostg.bundle && cd /mnt/d/research/os-simple-taskgen-v8/ostg && git fetch -q /tmp/ostg.bundle v8 && git merge --ff-only -q FETCH_HEAD && git log --oneline -1"'
```

## 1 生成 gen

默认不开 thinking(省 5 倍钱、躲 504);`--thinking` 只在想要 d4/d5 更深探针时用。
两分片并行(同 seed 得到不相交的坐标切分,错开写不同目录):

```bash
for i in 0 1; do
  setsid nohup env PYTHONPATH=. $P -m ostg.gen --n 5 --batches 20 --seed <S> --stream \
    --shard $i/2 --out out/runs/<set>-s$i/specs.jsonl \
    --avoid-corpus /mnt/d/research/cua-gym/tasks.jsonl \
    > logs/<set>-s$i.log 2>&1 &
done
```

批间丢失由 `--refill`(默认 2)自动补抽。跑完看日志尾部的收官统计。

## 2 验收 ship

```bash
PYTHONPATH=. $P -m ostg.ship out/runs/<set>-s0 out/runs/<set>-s1 \
  --ref cua-gym=/mnt/d/research/cua-gym/tasks.jsonl \
  --ref osworld-361=$OW/evaluation_examples/examples
```

re-emit 用当前 emitter 重编译全部 task JSON(旧集自动吃到新修复),然后过
HARD/REVIEW 门(见 README)。**删重复**:把该行从 `specs.jsonl` 挪到同目录
`specs_culled.jsonl`,重跑 ship 即可(每对留先生成的那条)。

## 3 合并 merge

目录规则:**一次启动 = 一个目录**(并行分片各写各的,避免两进程同写一个
jsonl 把行写花);**一个任务集 = 可能由多次启动拼成**(分片、中断续跑)。
而 runner 只吃一个 `--test_config_base_dir` + 一个 manifest,control 分片也
需要统一有序的 manifest,所以拼装是标准动作:

```bash
PYTHONPATH=. $P -m ostg.merge out/runs/<set>-s0 out/runs/<set>-s1 --out out/runs/<set>-all
```

id 撞车直接报错退出;源目录不动。cull 之后要重新 merge。

## 4 control 负例检查(rollout 前必跑)

抓三类 OSWorld 静默吞掉的故障:setup 退出码非 0、probe 崩溃(任务会无声退出
分母)、probe 白给 PASS(SFT 毒药)。三路并行,N 条每路 ceil(N/3):

```bash
L=69   # ceil(206/3)
for i in 0 1 2; do
  setsid nohup env PYTHONPATH=.:$OW $P -m ostg.control \
    --tasks out/runs/<set>-all --path_to_vm $OW/docker_vm_data/Ubuntu.qcow2 \
    --start $((i*L)) --limit $L --report out/runs/<set>-all/control_report_$i.jsonl \
    > logs/control-<set>-$i.log 2>&1 &
done
```

约 4 分钟/条/路。BAD 处理同 cull:挪出 specs → ship → 重新 merge。
**不要和 rollout 混跑**(见 §7 内存)。

## 4.5 正向验收:gold 注入 + audit 审计(v8.4 起)

control 只证明"没干活得 0 分";这两道补反方向。四道检查按**盲区**分工,
每道抓其余三道结构上看不见的病(右列 = 自己抓不了、由谁兜底):

| 检查 | 抓什么 | 抓不了什么(兜底者) |
|---|---|---|
| control 负例 | 白给分、坏 setup | 一切正向病(下面三个)|
| gold 注入 | 永远判不过的判分器:懒写盘时序、路径/常量错 | 金标世界信念错(audit)|
| audit 审计 | 指令⊄判分覆盖;金标里错误的世界断言 | 要真实执行才暴露的(rollout)|
| rollout | 以上全部漏掉的 | ——最贵,最终裁判 |

**audit 是 LLM 审计**:每条任务一次调用,审计员读指令+判分器源码,给出
covered / partial(指令要求判分器不查)/ overreach(判分器查指令没要求的),
外加 world_assumptions(判分器常量里对活网/外部世界的信念,审计员用自己的
世界知识核对)。**审计员必须换模型**(出题 opus-5 → 审计 opus-4-6)。

```bash
# ① LLM 覆盖审计(纯 API,不占 VM,report-only)
PYTHONPATH=. $P -m ostg.audit out/runs/<set>-s0/specs.jsonl [...] \
  --out out/runs/audit-<set>.jsonl --model claude-opus-4-6 --stream

# ② 金标脚本生成(纯 API;答案钥匙要算准,用强模型)
PYTHONPATH=. $P -m ostg.gold out/runs/<set>-s0/specs.jsonl [...] \
  --out out/runs/gold-<set>.jsonl --model claude-opus-5 --stream

# ③ 金标注入(VM,control 的镜像模式:注入后判分必须 1.0)
PYTHONPATH=.:$OW $P -m ostg.control --tasks out/runs/<set>-all \
  --path_to_vm $OW/docker_vm_data/Ubuntu.qcow2 --gold out/runs/gold-<set>.jsonl
```

读结果:
- `audit-*.jsonl` 里 verdict != covered 或 world_assumptions 非空的 → 人工过一遍,
  处置三选一:删任务 / 改探针金标 / 改指令(砍掉判分器不看的承诺);
- `gold_report.jsonl` 里 ok=false 的分两种:`gold_rc != 0` = 钥匙脚本自己烂(重生成),
  `gold_rc == 0` 且 score 0 = **判分器永假,真病**(看 probe_out 定位);
- 已知校准案例:chrome 懒写盘(gold 可抓)、panama 双要求(audit 可抓)、
  itinerary 活网金标(audit world_assumptions 可抓)。

## 5 rollout 标准指令

前置:隧道自检(HTTP 200 + 模型 id 即通):

```bash
cd $OW && set -a && . ./.env && set +a && curl -s -w '\nHTTP %{http_code}\n' \
  -H "Authorization: Bearer $OPENAI_API_KEY" http://127.0.0.1:18001/v1/models
```

标准参数(与官方 361 campaign 同口径,除了 sleep 1 与 max_steps 100):

```bash
cd $OW && setsid nohup .venv/bin/python scripts/python/run_multienv_qwen.py \
  --provider_name docker --path_to_vm $OW/docker_vm_data/Ubuntu.qcow2 --headless \
  --observation_type screenshot --action_space pyautogui \
  --model qwen36-27b-bf16-local --base_url http://127.0.0.1:18001/v1 \
  --temperature 0.6 --top_p 0.95 --max_tokens 81920 \
  --max_steps 100 --sleep_after_execution 1 --num_envs 3 --simple_path \
  --screen_width 1920 --screen_height 1080 \
  --test_config_base_dir $TG/out/runs/<set>-all \
  --test_all_meta_path $TG/out/runs/<set>-all/manifest.json \
  --result_dir $R/<set>-ms100-$(date +%Y%m%d) \
  > $TG/logs/rollout-<set>.log 2>&1 &
```

**补跑 = 用同一 `--result_dir` 重启同一条命令**:有 result.txt 的自动跳过,
没有的重跑(截图 500 之类的中途夭折就这么救)。

## 6 HTML 轨迹查看器

上游 OSWorld 没有这功能;跑完(或跑到一半)随时生成/刷新:

```bash
PYTHONPATH=. $P -m ostg.traj_html $R/<run目录名> --tasks out/runs/<set>-all
```

浏览:Windows 上直接开 `D:\research\OSWorld\results_generated\...\<run>\index.html`。
每任务一页:每步的模型原始输出、pyautogui 动作、执行后截图。增量安全,可反复跑。

## 7 健康检查与并发红线

```bash
ss -ltn | grep 18001                        # 隧道还在吗
docker ps --format "{{.Names}}" | wc -l     # 现有 VM 数
free -g                                     # 可用内存
grep -c "Failed to get screenshot" logs/rollout-<set>.log   # 500 计数,涨了=内存紧
```

内存红线(实测,总内存 19G):

| 组合 | 结论 |
|---|---|
| rollout ×3 VM(独占) | 安全档,标准配置 |
| rollout ×2 + control ×1 | **会出截图 500,任务无声夭折**(2026-08-09 实测)|
| control ×3(独占) | 安全 |

截图 500 的症状:runner 日志 `Failed to get screenshot. Status code: 500` 后跟
`TypeError: a bytes-like object is required` ——该任务没有 result.txt,按 §5 补跑。
