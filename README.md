# ostg — 最小 OSWorld 任务生成器

自由生成 → 全部实跑 → 事后筛。质量控制在 filter 和两个构建期对照里，不在生成端。

对 OSWorld **零改动**：没有自定义 metric，没有 import shim，没有 `.pth`，没有 gold 文件。
判分走官方 command-probe 那条路 —— `exact_match(vm_command_line 的 stdout, rule)`。

> 包名是 `ostg` 而不是 `taskgen`：OSWorld 的 venv 里装着 `taskgen_shim.pth`，
> 它在 site 初始化期就 `import taskgen.evaluators.shim`，把 `taskgen` 这个名字钉给
> `/mnt/d/research/osworld-taskgen`，同名包会被永久遮蔽。

---

## 1. 一个任务是四样东西

```
instruction   用户想要什么
setup_py      写初始文件            在 host 跑
solve_py      把初始文件变成完成态    在 host 跑 —— 见证者，不是答案
probe_py      检查机器，打印 PASS/FAIL   在 VM 里跑 —— 这才是答案
```

三个程序里 `P(...)` 都是**用户主目录**。`P("Desktop/sales.xlsx")` 在 host 上指向
构建树、在 VM 里指向 `/home/user/Desktop/sales.xlsx`。**同一套路径词汇**是两个
对照能成立的前提。

> 早期版本让 `setup_py` 写扁平目录、再按 basename 映射成 guest 布局。
> 目录型素材、嵌套输出、`.config/Code/User/settings.json` 这类目标全部映射不上，
> 正对照 6 个里挂 4 个。改成 guest 镜像后 8/8 通过。

## 2. 两个构建期对照

```
负对照   probe(seed)    必须 FAIL    抓「空闲 agent 也能满分」的探针
正对照   probe(solved)  必须 PASS    抓「探针和解法互相不同意」
```

**都不会丢弃任务**，结果写进 task JSON 的 `taskgen.controls`，由 filter 事后按
对照状态切分产出率 —— 于是"对照失败是否真的预测死任务"是实测出来的，不是假设的。

这两个不是防御性代码：它们用**真判分器**跑两次，秒级。
它们守的是 `score == 1.0` 这个筛子结构上盲的两类：
坏任务混在难任务里、松判分器放行错答案。

`solve_py` 也不是 gold。gold 是答案，`solve_py` 是**第二种独立的"完成"表达**；
两者不一致说明任务本身没说清。这比任何一方单独存在都更有信息量。

## 3. 探针

探针体被包进 `try/except`，任何异常都变成 stdout 上干净的 `FAIL`。
不包的话探针一崩就什么都不打印，`get_vm_command_line` 交给 metric 一个空串，
判 0 —— 对空闲 agent 是对的，但和「正确的 agent 撞上探针 bug」无法区分。
包了之后，**在 solved 上崩掉的探针会被正对照抓住**，而不是藏起来。

VM 里有 stdlib、PIL、lxml、requests、Xlib、pyatspi、ffmpeg、wmctrl、LibreOffice，
**没有 openpyxl / python-docx / python-pptx**。所以 OOXML 由 `tghelp.py` 用
`zipfile` + `xml.etree` 解，随每个任务上传到 `/tmp/tghelp.py`。

```python
read_xlsx(p) -> {sheet: [[cell]]}    read_docx(p) -> [paragraph]
read_pptx(p) -> [[shape_text]]       norm(v)   num(v)
```

`read_xlsx` 把每行补齐到最宽行。openpyxl 对 `None` 单元格根本不写 `<c>` 元素，
行尾空格会被丢掉、行变不等长，探针里一个 `r[4]` 就 IndexError —— 又一个会伪装成
「模型没做对」的假 0。

活的 GUI 状态也可判：a11y 全树在 `http://127.0.0.1:5000/accessibility`，
Chrome 标签在 `http://127.0.0.1:1337/json`，窗口用 `wmctrl -lx`。
这是 361 个官方任务里 8 个「只有 GUI 里才有的状态」全部被推翻的依据。

## 4. 抽样

`data/osworld361_labels.json` —— 361 个官方任务全部按 artifact / operation /
source / modality / app_count 打了标，并标了可生成性与阻塞原因。

**度量按 `artifact × source`，转向按 `artifact × source × operation`。**
40 个样本盲标重标的逐轴不一致率：

```
artifact    10.0%   ✅ 唯一既过关又有独立信号
app_count   12.5%（app_count=0 ⇔ infeasible 的约定已知后降到 2.5%）
source      13.9%（排除 refuse）
modality    15.0%   ⚠️ 过关但冗余：60 个 result_getter 值里 59 个唯一映射到一个 modality
operation   27.5%   ❌ derive/rewrite/set_value 语义嵌套，作为度量结构性坏掉
```

这张表否掉的是 `operation` 当**度量**的资格——两个标注员对一个已完成任务该叫什么
会吵起来，所以拿它报覆盖率没意义。但它当**转向**照样有效：`remove_element` 和
`set_value` 会让模型写出不一样的任务，跟标注员事后吵不吵无关。
所以 `AXES`（报覆盖率）和 `STEER`（喂模型）是两份清单，
加上 `operation` 让可达格子从 37 变成 80。批内去重仍停在 `(artifact, source)`，
不放宽——那条防的是模式塌缩，跟覆盖面无关。详见 [SAMPLING.md](SAMPLING.md)。

主应用**由 artifact 的实际域分布决定**，不独立轮转 —— 独立轮转会产出
`raster_image + libreoffice_calc` 这种无意义组合。这也是不把 `domain` 做成独立
抽样轴的原因（那样能到 107 格，但要重新打开这个口子）。

同一格反复抽会得到同一句 brief，所以 `gen` 会把该格**已生成的 slug** 一并发过去
要求避开。纯自对弈，不碰官方内容——361 既是参考库也是评测集，
借坐标不借内容那条线见 [SAMPLING.md](SAMPLING.md)。

覆盖不到的（**101/361，28%**，结构性）：`needs_live_web` 56、`refusal_not_observable` 27、
`needs_network_install` 9、`needs_gui_only_state` 8、`subjective_judgement` 1。
`refuse` 尤其做不了：`desktop_env.py:469` 读的是 `action_history[-1] == 'FAIL'`，
**判分信号在 agent 的输出通道里，VM 内任何程序都看不见。**

## 5. 跑

```bash
python -m ostg.gen   --n 8 --seed 11 --out out/specs.jsonl
python -m ostg.emit  out/specs.jsonl --build out/build --out out/tasks --batch v1
python -m ostg.check out/tasks                      # 需在 checkout 根、用 OSWorld 的 python
python -m ostg.filter --results R1 --results R2 --taskroot out/tasks --out out/sft.jsonl
```

`out/tasks/manifest.json` 就是 runner 的 `--test_all_meta_path`。

**先跑一轮分诊**：每个任务先只跑 1 次，只给至少成功过一次的续投。
一次都没成的要么坏要么太难，两种都不值得续投；这同时量出坏任务比例。

实测依据：官方 312 个结果里成功轨迹中位 **10 步**、只有 4% 用到 50 步上限，
而失败平均 35.2 步、34% 撞上限，**失败消耗了全部步数的 72%**。
所以 max_steps 定 50–60，不要 100。

## 6. filter

只留 `score == 1.0`。同一任务多次成功时，取**没有绕过 GUI 迹象的里最短的那条**。
单纯取最短是错的 —— 最短的往往是用一行 shell 做完全部工作的那条，
而那正是 GUI agent 不该学的行为。

多样性配比应当按**轨迹特征**做，不按 spec 标签做：三个轴全是模型自报、无人验证。

## 7. 已知做不到的

1. **`score == 1.0` 不代表判分器是紧的。** 探针是模型写的，常见失败不是作弊，
   是检查了任务的**代理量**而非任务本身。负对照抓不到这个 —— 它只证明探针不是恒 PASS。
   这是 LLM judge 唯一真正该上的地方：读指令 + 探针源码，问「不做这个任务能不能让它打印 PASS」。纯文本，几百 token。
2. **探针跑在 agent 控制的机器上。** agent 可以去写探针读的那个文件。
   官方 `vm_command_line` 任务同样如此，没有便宜的防法。
3. **指令泄漏答案没有任何东西拦。** 泄漏的任务 agent 轻松通过，而那条轨迹会被**留下**。
4. **三个轴都是自报的。** 你的"多样"是标签上的多样。
