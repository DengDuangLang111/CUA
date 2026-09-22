#!/usr/bin/env python3
"""armname.py — 实验臂名与语料名的唯一生成器 / 校验器(`docs/NAMING.md` 的代码锚点)。

臂名语法    <骨干>-<训练法>-<语料>[-<偏离项>…][~e<N>][@<img>f<fold>[.t0][.ms100]…]
语料语法    <来源>[+<来源>…][.<变换>…]        语料段内部不出现 '-',臂名才能无歧义切分

只写与标准配方(STD)不同的部分。拓扑(节点×卡×accum)不进名字:全局 batch 相同即同一模型。
'@' 后面是**推理侧**配置(窗口/采样/步数),属于评测记录不属于权重;默认 @10f1 省略。
'~e<N>' 是中途快照(未退火,见 sft/docs/RESULTS.md §6 的 @eN 口径),终点权重不写。

用法
  armname.py from-sbatch <x.sbatch> [--eval 20f10]   由 sbatch 推导规范臂名(--json 给分解)
  armname.py check       <x.sbatch>                  推导名 vs 声明名(`# ARM:` 行,缺则取 OUT= 末段);不一致 exit 1
  armname.py emit        <x.sbatch>                  打印 ARM= / OUT= / RUN_NAME= / --served-model-name 四行,粘进 sbatch 与 serve
  armname.py alias       <旧臂键>                     历史名 → 规范名(结果目录不改名,看板显示用)
  armname.py corpus      <语料 id | 公式 | 数据目录名>  语料的公式、组成与定义
  armname.py table                                   全部别名对照(供 docs/NAMING.md 对照表)
  armname.py selftest    [sbatch_dir]                 对 sft/scripts/train/*.sbatch 跑回归(期望值 EXPECTED)

新语料/新偏离项:先在下面的注册表加一行再用 —— 未注册的数据目录组合会被拒绝(exit 1),
这就是"以后统一自动生成、不再手打"的机制。
"""
import glob
import json
import os
import re
import sys

# ───────────────────────── 标准配方(省略即代表用它) ─────────────────────────
STD = dict(lr={"full": 3e-6, "lora": 1e-4}, epochs=3, gb=64, wd=0.0, beta2=0.999,
           warmup=0.1, max_length=81920, image_max_token=2048, preserve_thinking=True,
           lora_rank=32, lora_alpha=64)
STD_EVAL = dict(image_max=10, fold_size=1, temperature=1.0, max_steps=50)

# ───────────────────────── 骨干 ─────────────────────────
BACKBONE = {  # --model 末段 → token(token 内不能有 '-')
    "Qwen3.5-4B": "4b", "Qwen3.5-9B": "9b", "Qwen3.8-27B": "27b",
    "Qwen3.6-27B": "27bq36", "Qwen3-VL-4B-Thinking": "vl4b",
    "tmax-9b-cua-init": "tmax9b",
}

# ───────────────────────── 语料:来源 / 变换 / 数据目录 ─────────────────────────
SOURCES = {  # token → 定义(数据目录见 CORPUS_DIRS)
    "r5":   "Bhqs2t-r5 系 v11 rollout:362 轨迹 / 6,474 样本,img10/fold1,think 不截断,末步 100% terminate",
    "v11n": "v11 新批(i10x 重跑):312 轨迹(data/v11new-{500,all})",
    "v16":  "v16 判官准入:554 轨迹(data/v16-{main,pilot})",
    "v16m": "v16 真 multi-app 子集:166 轨迹(data/v16-truemulti,build_truemulti_subset.py)",
    "v16save143": "用户固定选择的143条v16保存证据候选;非独立全项验收结论",
    "v16s": "v16 严格准入:340 轨迹(curate16 --strict)",
    "v11h": "v11-100 池:69 轨迹(旧代 q38-v11100)",
    "b":    "v11-100+500 checker 全 pass:312 轨迹(旧代 q38e3B;窗口未在目录名标注)",
    "bhqs": "双判官+仲裁筛选(旧代 q38-Bhqs)",
    "abs":  "9 题面板时代的 abs-pilot 语料(1,288 样本;与 eval50 不可比)",
}
SRC_ORDER = ["r5", "v11h", "b", "bhqs", "abs", "v11n", "v16", "v16m", "v16s", "v16save143"]

XFORMS = {  # token → 定义
    "tf":    "终止规范化 terminalfix:末步重写并确定性拼上 terminate(success)",
    "ws":    "WebSTAR 步级过滤:每步 0-10 分,>5 留作训练目标",
    "sw":    "SWE-MeM 轨迹内 token 均衡权重(sft/experiments/swe_mem;须 --is_binary_loss_scale false)",
    "tw":    "任务均衡加权 loss_scale=c/N(make-taskw-weights.py;须 --is_binary_loss_scale false)",
    "cap2k": "teacher think 超 2048 token 的训练目标屏蔽(think-cap 2048)",
    "np":    "去 teacher 散文(no prose)",
    "img20": "建语料时每步最多 20 张截图(标准 img10 省略)",
    "img3":  "建语料时每步最多 3 张截图",
    "img1":  "建语料时每步 1 张截图",
    "vl":    "按 Qwen3-VL 格式重建",
    "v":     "切了 5% 验证集",
}
XF_ORDER = ["tf", "ws", "sw", "tw", "cap2k", "np", "img20", "img3", "img1", "vl", "v"]

# Tillicum data/<目录> → (来源集合, 变换集合)。sbatch 里 $B/data/<目录> 全部都要在这里。
CORPUS_DIRS = {
    "r5-v16save143-tf": ({"r5", "v16save143"}, {"tf"}),
    "q38-Bhqs2t-r5nocapimg10-v11100": ({"r5"}, set()),
    "q38-Bhqs2t-r5nocapimg10-v11500": ({"r5"}, set()),
    "v11new-500": ({"v11n"}, set()), "v11new-all": ({"v11n"}, set()),
    "v16-main": ({"v16"}, set()), "v16-pilot": ({"v16"}, set()),
    "v16-truemulti": ({"v16m"}, set()),
    "mixbtf-v11new-500": ({"v11n"}, {"tf"}), "mixbtf-v11new-all": ({"v11n"}, {"tf"}),
    "mixbtf-v16-main": ({"v16"}, {"tf"}), "mixbtf-v16-pilot": ({"v16"}, {"tf"}),
    "mixbtf-taskw-v11new-500": ({"v11n"}, {"tf", "tw"}), "mixbtf-taskw-v11new-all": ({"v11n"}, {"tf", "tw"}),
    "mixbtf-taskw-v16-main": ({"v16"}, {"tf", "tw"}), "mixbtf-taskw-v16-pilot": ({"v16"}, {"tf", "tw"}),
    "mixB-swemem": ({"v11n", "v16"}, {"sw"}),
    "mixa-webstar-v16strict": ({"r5", "v16s"}, {"tf", "ws"}),
    # 旧代(8 月)。q38-Bhqs2t-r5-*:r5 时代的默认建法 = think-cap 2048 + img20(显式的 nocap / img10 变体
    # 才另起目录);kE 与 r5lora 的 sbatch 都用它。q38-Bhqs2t-*(无 r5)是 6,297 行的缺陷旧版(CHECKPOINTS §3.1)。
    "q38-Bhqs2t-r5-v11100": ({"r5"}, {"cap2k", "img20"}), "q38-Bhqs2t-r5-v11500": ({"r5"}, {"cap2k", "img20"}),
    "q38-Bhqs2t-v11100": ({"r5"}, {"cap2k", "img20"}), "q38-Bhqs2t-v11500": ({"r5"}, {"cap2k", "img20"}),
    "q38e3B-v11100": ({"b"}, set()), "q38e3B-v11500": ({"b"}, set()),
    "q38e3B-tc2048-v11100": ({"b"}, {"cap2k"}), "q38e3B-tc2048-v11500": ({"b"}, {"cap2k"}),
    "q38-Bhqs-v11100": ({"bhqs"}, {"cap2k"}), "q38-Bhqs-v11500": ({"bhqs"}, {"cap2k"}),
    "q38-v11100": ({"v11h"}, set()),
}

# 公式 → 短 id(臂名里用短 id;没有短 id 的语料直接用公式)
CORPORA = {
    "r5+v16": "mixa", "v11n+v16": "mixb", "v16": "mixc", "r5+v16m": "mixr5m",
    "v11n+v16.tf": "mixbtf", "v11n+v16.tf.tw": "mixbtf.tw", "v11n+v16.sw": "mixb.sw",
    "r5+v16s.tf.ws": "mixaw",
}
FORMULA_OF = {v: k for k, v in CORPORA.items()}


def corpus_formula(sources, xforms):
    s = "+".join(t for t in SRC_ORDER if t in sources)
    x = "".join("." + t for t in XF_ORDER if t in xforms)
    return s + x


def corpus_from_dirs(dirs):
    """数据目录名集合 → (短 id 或公式, 公式)。未注册的目录 → ValueError。"""
    unknown = sorted(d for d in dirs if d not in CORPUS_DIRS)
    if unknown:
        raise ValueError("未注册的数据目录(先在 armname.py CORPUS_DIRS 登记):" + ", ".join(unknown))
    sources, xforms = set(), set()
    for d in dirs:
        s, x = CORPUS_DIRS[d]
        sources |= s
        xforms |= x
    f = corpus_formula(sources, xforms)
    return CORPORA.get(f, f), f


# ───────────────────────── 格式化 ─────────────────────────
def _num(x):
    """0.1 → '0p1'(点写成 p,沿用 cap1p5 的写法;偏离项里不能有 '.')"""
    return ("%g" % float(x)).replace(".", "p").replace("-", "m")


def fmt_lr(lr):
    m, e = ("%.2e" % float(lr)).split("e")
    m = m.rstrip("0").rstrip(".")
    return "%se%d" % (m.replace(".", "p"), -int(e))


def eval_suffix(image_max=10, fold_size=1, temperature=1.0, max_steps=50, extra=()):
    parts = []
    if (image_max, fold_size) != (STD_EVAL["image_max"], STD_EVAL["fold_size"]):
        parts.append("%df%d" % (image_max, fold_size))
    tags = []
    if float(temperature) == 0.0:
        tags.append("t0")
    if int(max_steps) != STD_EVAL["max_steps"]:
        tags.append("ms%d" % int(max_steps))
    tags += list(extra)
    if not parts and not tags:
        return ""
    return "@" + (parts[0] if parts else "%df%d" % (STD_EVAL["image_max"], STD_EVAL["fold_size"])) + "".join("." + t for t in tags)


# ───────────────────────── 解析 sbatch ─────────────────────────
def _grab(pat, text, default=None, cast=str):
    m = re.search(pat, text, re.M)
    return cast(m.group(1)) if m else default


def parse_sbatch(path):
    raw = open(path, encoding="utf-8").read()
    code = "\n".join(l for l in raw.splitlines() if not l.lstrip().startswith("#"))  # 去掉注释行
    p = {}
    model_arg = _grab(r'''--model\s+("[^"]+"|'[^']+'|\S+)''', code)
    if model_arg is None:
        raise ValueError("%s: 找不到 --model" % path)
    model = os.path.basename(model_arg.strip('"\'').rstrip('/'))
    if model not in BACKBONE:
        raise ValueError("%s: 未注册的骨干 %s(先在 armname.py BACKBONE 登记)" % (path, model))
    p["backbone"] = BACKBONE[model]
    p["method"] = _grab(r"--tuner_type\s+(\w+)", code, "full")
    p["lr"] = _grab(r"--learning_rate\s+(\S+)", code, None, float)
    p["epochs"] = _grab(r"--num_train_epochs\s+(\d+)", code, STD["epochs"], int)
    accum = _grab(r"--gradient_accumulation_steps\s+(\d+)", code, 1, int)
    bs = _grab(r"--per_device_train_batch_size\s+(\d+)", code, 1, int)
    nn = _grab(r"NNODES=(\d+)", code, 1, int)
    npn = _grab(r"NPROC_PER_NODE=(\d+)", code, 1, int)
    p["gb"] = nn * npn * accum * bs
    p["topology"] = "%dx%dxaccum%d" % (nn, npn, accum)
    p["wd"] = _grab(r"--weight_decay\s+(\S+)", code, STD["wd"], float)
    p["beta2"] = _grab(r"--adam_beta2\s+(\S+)", code, STD["beta2"], float)
    p["warmup"] = _grab(r"--warmup_ratio\s+(\S+)", code, STD["warmup"], float)
    p["max_length"] = _grab(r"--max_length\s+(\d+)", code, STD["max_length"], int)
    p["image_max_token"] = _grab(r"IMAGE_MAX_TOKEN_NUM=(\d+)", code, STD["image_max_token"], int)
    p["image_min_token"] = _grab(r"IMAGE_MIN_TOKEN_NUM=(\d+)", code, None, int)
    p["histcomp"] = bool(re.search(r"PYTHONPATH=\S*histcomp", code))
    p["vision_nograd"] = bool(re.search(r"FROZEN_VISION_NO_GRAD=1", code))
    p["preserve_thinking"] = _grab(r"--preserve_thinking\s+(true|false)", code, "true") == "true"
    p["binary_loss_scale"] = _grab(r"--is_binary_loss_scale\s+(true|false)", code, "true") == "true"
    p["lora_rank"] = _grab(r"--lora_rank\s+(\d+)", code, STD["lora_rank"], int)
    p["lora_alpha"] = _grab(r"--lora_alpha\s+(\d+)", code, STD["lora_alpha"], int)
    p["smoke_steps"] = _grab(r"--max_steps\s+(\d+)", code, None, int)
    p["resume"] = bool(re.search(r"--resume_from_checkpoint", code))
    p["out"] = _grab(r"^OUT=\S*/([^/\s]+)\s*$", code)
    p["declared"] = _grab(r"^#\s*ARM:\s*(\S+)", raw)
    dirs = set(re.findall(r"\$B/data/([A-Za-z0-9_.-]+)", code))
    if not dirs:
        raise ValueError("%s: 找不到任何 $B/data/<目录>" % path)
    p["dirs"] = sorted(dirs)
    p["corpus"], p["corpus_formula"] = corpus_from_dirs(dirs)
    return p


def deviations(p):
    d = []
    std_lr = STD["lr"].get(p["method"], STD["lr"]["full"])
    if p["lr"] is not None and abs(p["lr"] - std_lr) > 1e-12:
        d.append("lr" + fmt_lr(p["lr"]))
    if p["epochs"] != STD["epochs"]:
        d.append("ep%d" % p["epochs"])
    if p["gb"] != STD["gb"]:
        d.append("gb%d" % p["gb"])
    if abs(p["wd"] - STD["wd"]) > 1e-12:
        d.append("wd" + _num(p["wd"]))
    if abs(p["beta2"] - STD["beta2"]) > 1e-12:
        d.append("b" + _num(p["beta2"]))
    if abs(p["warmup"] - STD["warmup"]) > 1e-12:
        d.append("wu" + _num(p["warmup"]))
    if p["max_length"] != STD["max_length"]:
        d.append("ml%dk" % (p["max_length"] // 1000))
    if p["image_min_token"]:
        d.append("imgtok%d" % p["image_min_token"])          # max 抬高是 min 的配套,不另记
    elif p["image_max_token"] != STD["image_max_token"]:
        d.append("imgmax%d" % p["image_max_token"])
    if p["histcomp"]:
        d.append("histcomp")
    if p.get("vision_nograd"):
        d.append("vnograd")
    if not p["preserve_thinking"]:
        d.append("nopt")
    if p["method"] == "lora" and (p["lora_rank"], p["lora_alpha"]) != (STD["lora_rank"], STD["lora_alpha"]):
        d.append("r%da%d" % (p["lora_rank"], p["lora_alpha"]))
    return d


def warnings_for(p):
    w = []
    weighted = any(t in p["corpus_formula"] for t in (".sw", ".tw"))
    if weighted and p["binary_loss_scale"]:
        w.append("语料带 per-message 权重(.sw/.tw)但没有 --is_binary_loss_scale false:ms-swift 会静默丢掉权重,等于基线")
    if p["smoke_steps"]:
        w.append("--max_steps %d:这是冒烟,不是臂" % p["smoke_steps"])
    if p["resume"]:
        w.append("续跑脚本:名字与原臂相同,终点权重的来历见该 sbatch")
    return w


def name_from_sbatch(path, eval_cfg=None):
    p = parse_sbatch(path)
    name = "-".join([p["backbone"], p["method"], p["corpus"]] + deviations(p))
    if p["smoke_steps"]:
        name += "-smoke"
    if eval_cfg:
        name += eval_cfg if eval_cfg.startswith("@") else "@" + eval_cfg
    return name, p


# ───────────────────────── 历史名 → 规范名 ─────────────────────────
# 结果目录/权重目录**不改名**(docs/NAMING.md 规矩);这张表只用于看板显示与文档。
# 旧代 @20f10:那个时代的默认推理窗口是 20/10,现行标准 10/1,所以旧结果必须带 @20f10 才不会被误比。
ALIASES = {
    "tmax9b-r5": "tmax9b-full-r5-ml65k",
    # mix 时代(OUT 目录名 / 看板键)
    "mixA-9b": "9b-full-mixa", "mixa9b": "9b-full-mixa", "mixA-4b": "4b-full-mixa", "mixa4b": "4b-full-mixa",
    "mixB-9b": "9b-full-mixb", "mixb9b": "9b-full-mixb", "mixB-4b": "4b-full-mixb", "mixb4b": "4b-full-mixb",
    "mixC-9b": "9b-full-mixc", "mixc9b": "9b-full-mixc", "mixR5M-9b": "9b-full-mixr5m", "mixr5m9b": "9b-full-mixr5m",
    "mixaw9b": "9b-full-mixaw-ml65k",
    "mixbtf9b": "9b-full-mixbtf", "mixbtf9b-2x4": "9b-full-mixbtf",
    "mixbtf9b-2x4-lr1e6": "9b-full-mixbtf-lr1e6", "mixbtflr1e6": "9b-full-mixbtf-lr1e6",
    "mixbtf9b-2x4-lr1e5": "9b-full-mixbtf-lr1e5", "mixbtf9blr1e5": "9b-full-mixbtf-lr1e5",
    "mixbtf9b-histcomp": "9b-full-mixbtf-histcomp", "histcomp": "9b-full-mixbtf-histcomp",
    "mixbtf9b-taskw": "9b-full-mixbtf.tw", "taskw": "9b-full-mixbtf.tw",
    "mixbtf4b-cap1p5": "4b-full-mixbtf-ml65k-imgtok3072", "cap1p5": "4b-full-mixbtf-ml65k-imgtok3072",
    "mixbtf4b-cap2x": "4b-full-mixbtf-imgtok4096", "cap2x": "4b-full-mixbtf-imgtok4096",
    "mixB-9b-swemem": "9b-full-mixb.sw",
    "mixB-9b-lr1e5-1ep": "9b-full-mixb-lr1e5-ep1-wd0p1-b0p95", "lr1e5": "9b-full-mixb-lr1e5-ep1-wd0p1-b0p95",
    "mixB-9b-lr1e5-b999": "9b-full-mixb-lr1e5-ep1", "lr1e5b999": "9b-full-mixb-lr1e5-ep1",
    "mixB-9b-lr2e5-1ep": "9b-full-mixb-lr2e5-ep1-wd0p1-b0p95", "lr2e5": "9b-full-mixb-lr2e5-ep1-wd0p1-b0p95",
    "mixB-9b-lr2e5-gb128": "9b-full-mixb-lr2e5-ep1-gb128-wd0p1-b0p95", "lr2e5gb128": "9b-full-mixb-lr2e5-ep1-gb128-wd0p1-b0p95",
    "mixb9bw20": "9b-full-mixb@20f10", "mixb9bw20f1": "9b-full-mixb@20f1",
    "mixb9b-aws": "9b-full-mixb", "mixb4b50b": "4b-full-mixb",      # 评测地点/题集不进模型名,记在结果目录
    # r5 时代(docs/NAMING.md 对照表翻译;语料 cap/img 变换来自 sft/docs/CHECKPOINTS.md §2/§3)
    "nocap": "4b-full-r5.img20@20f10", "nocap50b": "4b-full-r5.img20@20f10", "nocap261": "4b-full-r5.img20@20f10",
    "kE": "4b-full-r5.cap2k.img20@20f10", "kEh3": "4b-full-r5.cap2k.img20@3f1", "kEh1": "4b-full-r5.cap2k.img20@1f1",
    "kD": "4b-full-r5.cap2k.img20-lr1e5@20f10", "kD15": "4b-full-r5.cap2k.img20-lr1e5~e1.5@20f10",
    "a1": "4b-full-r5@20f10", "a1h10": "4b-full-r5", "a2": "9b-full-r5@20f10", "a2261": "9b-full-r5@20f10",
    "a3": "4b-full-r5-hermes@20f10", "a7": "9b-full-r5.v-gb128-hermes~e2@20f10", "a6v": "4b-full-r5.v-lr2e6-ep2",
    "a5v": "4b-full-r5.v-lr2e6-ep5",
    "img3": "4b-full-r5.img3@20f10", "img3h3": "4b-full-r5.img3@3f1", "img1": "4b-full-r5.img1@1f1",
    "nocapnp": "4b-full-r5.np.img20@20f10", "nocapnp2": "4b-full-r5.np.img20~e2@20f10",
    "nocapnp238": "4b-full-r5.np.img20~e2.36@20f10", "np1e6": "4b-full-r5.np.img20-lr1e6@20f10",
    "nocapt0": "4b-full-r5.img20@20f10.t0", "nocapms100": "4b-full-r5.img20@20f10.ms100",
    "r5lora": "4b-lora-r5.cap2k.img20@20f10",   # sbatch DS=q38-Bhqs2t-*(带 cap);docs/NAMING.md 旧表漏写了 cap
    "kG": "4b-lora-r5.np.img20@20f10", "kF": "4b-lora-r5.np.img20-nopt@20f10",
    "base": "4b-base@20f10", "basekeep": "4b-base@20f10", "baseh1": "4b-base@1f1",
    "base50b": "4b-base@20f10", "base261": "4b-base@20f10", "base9b": "9b-base@20f10", "base9b261": "9b-base@20f10",
    "t38": "27b-base@20f10", "t3850b": "27b-base@20f10", "27b": "27b-base@20f10", "qwen36-teacher": "27bq36-base@20f10",
    # B / Bs / Bhqs 时代(sft/docs/CHECKPOINTS.md §2 表;三个臂服务的是 ~e1 快照)
    "bsstock": "4b-full-b.cap2k-lr1e5~e1.02@20f10", "bskeep": "4b-full-b.cap2k-lr1e5~e1.02@20f10",
    "lorastock": "4b-lora-b.cap2k~e1.02@20f10", "lorakeep": "4b-lora-b.cap2k~e1.02@20f10",
    "gb64keep": "4b-full-b-lr1e5~e1.01@20f10", "gb128keep": "4b-full-b-lr1e5-gb128~e2@20f10",
    "gb128ep2keep": "4b-full-b-lr1e5-gb128~e2@20f10", "b1epkeep": "4b-full-b-lr1e5-ep1-gb8@20f10",
    "richrich": "4b-full-v11h-lr1e5-gb8@20f10", "richstock": "4b-full-v11h-lr1e5-gb8@20f10",
    "rich150": "4b-full-v11h-lr1e5-gb8~e1@20f10",
    "leankeep": "4b-full-v11h-lr1e5-gb8-nopt@20f10", "leanstock": "4b-full-v11h-lr1e5-gb8-nopt@20f10",
    "bhqskeep": "4b-full-bhqs.cap2k-lr1e5@20f10",
    # VL 线
    "vlbase": "vl4b-base@20f10", "vlsft": "vl4b-full-r5.vl.img20@20f10", "vl20": "vl4b-full-r5.vl.img20-lr1e5@20f10",
    "gb128": "vl4b-full-r5.vl.img3-lr1e5-gb128@3f1", "vlnocapnp": "vl4b-full-r5.vl.np.img20@20f10",
    # 教师窗口试点(推理侧;'slide' 按标签读作 fold 1,见 UNMAPPED 注)
    "t38i5": "27b-base@5f1", "t38i10": "27b-base@10f1", "t38i20": "27b-base@20f1",
    "t38px480": "27b-base@20f1.tok480", "t38med": "27b-base@20f10.effmed",
    "t38i10med": "27b-base@10f1.effmed", "t38i20med": "27b-base@20f1.effmed", "t38i10px": "27b-base@10f1.tok480",
}
# 没有把握就不映射:这些键要么是 eval50 之前的 9 题面板时代,要么文档里的语料/cap 记载互相矛盾。
UNMAPPED = {
    "qwen35-4b-v1": "9 题面板时代(pre-fix),与 eval50 不可比(CHECKPOINTS §2 明写不列入)",
    "qwen35-4b-pp15": "同上", "qwen35-4b-pilotS3": "同上", "q35-e1": "同上", "q35-e3": "同上", "q35-more": "同上",
    "more3": "同上", "more3np": "同上", "ep5pt": "同上", "ep5np": "同上", "q35-base-topk": "同上",
    "bhqs2keep": "Bhqs-2 rev2:CHECKPOINTS 无权重目录/lr 记载,待用户确认",
    "bhqs2tkeep": "疑即 kD(q38Bhqs2t-gb64);两键是否同权重待确认",
    "bhqs2lrkeep": "Bhqs-2 lr3e-6 displacement probe:疑即 kE,待确认",
    "owrl-4b-sft": "外部模型(OpenWebRL),不按本表命名",
    "t38*": "'slide' 与 'i10' 的 fold 是否为 1 系按看板标签推断,未从 runner 命令行核实",
}


def load_expected(sdir):
    """selftest 期望:文件名 → 规范名(由本文件推导规则手工核过一遍)"""
    return {
        "mixA-4b": "4b-full-mixa", "mixA-9b": "9b-full-mixa",
        "tmax9b-r5": "tmax9b-full-r5-ml65k",
        "mixB-4b": "4b-full-mixb", "mixB-9b": "9b-full-mixb",
        "mixB-9b-lr1e5-1ep": "9b-full-mixb-lr1e5-ep1-wd0p1-b0p95",
        "mixB-9b-lr1e5-b999": "9b-full-mixb-lr1e5-ep1",
        "mixB-9b-lr2e5-1ep": "9b-full-mixb-lr2e5-ep1-wd0p1-b0p95",
        "mixB-9b-lr2e5-gb128": "9b-full-mixb-lr2e5-ep1-gb128-wd0p1-b0p95",
        "mixB-9b-swemem": "9b-full-mixb.sw",
        "mixC-9b": "9b-full-mixc", "mixR5M-9b": "9b-full-mixr5m",
        "mixaw9b": "9b-full-mixaw-ml65k",
        "mixbtf4b-cap1p5": "4b-full-mixbtf-ml65k-imgtok3072",
        "mixbtf4b-cap2x": "4b-full-mixbtf-imgtok4096",
        "mixbtf4b-cap2x-ml65k": "4b-full-mixbtf-ml65k-imgtok4096",
        "mixbtf9b": "9b-full-mixbtf", "mixbtf9b-2x4": "9b-full-mixbtf",
        "mixbtf9b-2x4-lr1e5": "9b-full-mixbtf-lr1e5", "mixbtf9b-2x4-lr1e6": "9b-full-mixbtf-lr1e6",
        "mixbtf9b-histcomp": "9b-full-mixbtf-histcomp", "mixbtf9b-taskw": "9b-full-mixbtf.tw",
        "archive/sft-q38Bhqs2t-lora-g8": "4b-lora-r5.cap2k.img20-ml65k",
    }


# ───────────────────────── CLI ─────────────────────────
def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, args = argv[1], argv[2:]
    if cmd == "from-sbatch":
        ev = None
        if "--eval" in args:
            i = args.index("--eval"); ev = args[i + 1]; args = args[:i] + args[i + 2:]
        want_json = "--json" in args; args = [a for a in args if a != "--json"]
        name, p = name_from_sbatch(args[0], ev)
        if want_json:
            print(json.dumps(dict(name=name, deviations=deviations(p), warnings=warnings_for(p), **p),
                             ensure_ascii=False, indent=1))
        else:
            print(name)
            for w in warnings_for(p):
                print("WARN:", w, file=sys.stderr)
        return 0
    if cmd == "check":
        name, p = name_from_sbatch(args[0])
        declared = p["declared"] or p["out"]
        src = "# ARM:" if p["declared"] else "OUT="
        ok = declared == name
        print("%s  声明(%s)=%s  推导=%s" % ("OK " if ok else "MISMATCH", src, declared, name))
        for w in warnings_for(p):
            print("WARN:", w)
        return 0 if ok else 1
    if cmd == "emit":
        name, p = name_from_sbatch(args[0])
        print("# ARM: %s" % name)
        print("ARM=%s" % name)
        print("OUT=$B/out/$ARM")
        print("RUN_NAME=$ARM-${SLURM_JOB_ID}")
        print("--served-model-name %s-stock" % name)
        return 0
    if cmd == "alias":
        k = args[0]
        if k in ALIASES:
            print(ALIASES[k]); return 0
        if k in UNMAPPED:
            print("UNMAPPED: " + UNMAPPED[k], file=sys.stderr); return 2
        print("unknown key", file=sys.stderr); return 1
    if cmd == "corpus":
        k = args[0]
        if k in CORPUS_DIRS:
            cid, f = corpus_from_dirs({k}); print("目录 %s → 来源 %s 变换 %s → %s" % (k, *CORPUS_DIRS[k], f)); return 0
        f = FORMULA_OF.get(k, k)
        cid = CORPORA.get(f, f)
        srcs = [t for t in SRC_ORDER if t in f.split(".")[0].split("+")]
        xfs = [t for t in f.split(".")[1:]]
        if not srcs:
            print("unknown corpus", file=sys.stderr); return 1
        print("id=%s  公式=%s" % (cid, f))
        for t in srcs: print("  来源 %-5s %s" % (t, SOURCES[t]))
        for t in xfs: print("  变换 %-5s %s" % (t, XFORMS.get(t, "?")))
        dirs = sorted(d for d, (s, x) in CORPUS_DIRS.items() if s <= set(srcs) and x <= set(xfs))
        print("  目录  " + ", ".join(dirs))
        return 0
    if cmd == "table":
        print("| 旧名 | 规范名 |\n|---|---|")
        for k, v in ALIASES.items(): print("| `%s` | `%s` |" % (k, v))
        print("\n未映射:")
        for k, v in UNMAPPED.items(): print("- `%s`:%s" % (k, v))
        return 0
    if cmd == "selftest":
        sdir = args[0] if args else os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "train")
        exp = load_expected(sdir); bad = 0
        for key, want in exp.items():
            path = os.path.join(sdir, key + ".sbatch")
            try:
                got, p = name_from_sbatch(path)
            except Exception as e:
                print("ERR  %-32s %s" % (key, e)); bad += 1; continue
            flag = "ok  " if got == want else "FAIL"
            bad += got != want
            print("%s %-32s %-44s %s" % (flag, key, got, "" if got == want else "expected " + want))
            for w in warnings_for(p): print("      WARN: " + w)
        # 别名表里的 mix 时代键必须与推导一致
        for key, want in exp.items():
            k = os.path.basename(key)
            if k in ALIASES and ALIASES[k] != want:
                print("FAIL alias %s=%s ≠ expected %s" % (k, ALIASES[k], want)); bad += 1
        print("%d failures" % bad)
        return 1 if bad else 0
    print("unknown command", cmd, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
