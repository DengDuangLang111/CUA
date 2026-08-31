#!/bin/bash
# gpus.sh [tillicum|klone|all] -- 一眼看完集群 GPU 现状。
#
# 用法:
#   CUA/tools/gpus.sh            两个集群都查(默认)
#   CUA/tools/gpus.sh tillicum   只查 Tillicum
#   CUA/tools/gpus.sh klone      只查 Klone
#
# 首次会走 Duo;ssh config 里 tillicum1/hyak 都开了 ControlMaster +
# ControlPersist 86400,所以之后 24 小时内再查不用再验证。
#
# 为什么把远端逻辑写成 heredoc 喂给 `ssh host bash -s`:项目铁律"外层单引号、
# 内层双引号、不嵌第三层",一嵌套就会被 Windows/GBK 那条链路啃成乱码。
# heredoc 只有一层引号,且远端脚本原样传过去,不受本地 shell 二次展开影响。
set -u
WHICH="${1:-all}"

remote_slurm() {   # $1 = 集群显示名, $2 = 分区(逗号分隔)
  cat <<REMOTE
PARTS=$2
CLUSTER=$1
REMOTE
  cat <<'REMOTE'
echo "════════ $CLUSTER ════════"
python3 - "$PARTS" <<'PY'
import subprocess, sys, re, collections
parts = sys.argv[1].split(",")
me = subprocess.run(["whoami"], capture_output=True, text=True).stdout.strip()

# 节点 -> (分区集合, gpu 型号, 总数, 已分配, 状态)
raw = subprocess.run(["scontrol","show","node","-o"], capture_output=True, text=True).stdout
nodes = {}
for line in raw.splitlines():
    if not line.strip(): continue
    g = dict(re.findall(r"(\w+)=([^\s]+)", line))
    name = g.get("NodeName")
    cfg  = g.get("CfgTRES","");  alloc = g.get("AllocTRES","")
    m = re.search(r"gres/gpu=(\d+)", cfg)
    if not m: continue
    tot = int(m.group(1))
    m2 = re.search(r"gres/gpu=(\d+)", alloc)
    used = int(m2.group(1)) if m2 else 0
    typ = ""
    mt = re.search(r"gres/gpu:([a-z0-9_]+)=", cfg)
    if mt: typ = mt.group(1)
    nodes[name] = dict(part=g.get("Partitions",""), typ=typ, tot=tot,
                       used=used, state=g.get("State",""))

for p in parts:
    sel = {n:v for n,v in nodes.items() if p in v["part"].split(",")}
    if not sel:
        print(f"  [{p}] 无此分区"); continue
    tot=sum(v["tot"] for v in sel.values())
    used=sum(v["used"] for v in sel.values())
    # 不可用 = 节点处于 DOWN/DRAIN/MAINT,它的空卡是假空
    dead=sum(v["tot"]-v["used"] for v in sel.values()
             if any(k in v["state"] for k in ("DOWN","DRAIN","MAINT","FAIL")))
    free=tot-used-dead
    print(f"  [{p}]  总 {tot}  已用 {used}  \033[1m可用 {free}\033[0m  不可用 {dead}(节点故障/维护)")
    # 有空卡的节点
    rows=[]
    for n,v in sorted(sel.items()):
        f=v["tot"]-v["used"]
        if f>0:
            bad=any(k in v["state"] for k in ("DOWN","DRAIN","MAINT","FAIL"))
            rows.append(f"    {n} 空{f}/{v['tot']} {v['typ']} {v['state']}" + ("  ← 不可用" if bad else ""))
    print("\n".join(rows) if rows else "    (没有任何节点有空卡)")

# 我的作业
q = subprocess.run(["squeue","-u",me,"-h","-o","%i|%j|%t|%M|%L|%D|%b|%R"],
                   capture_output=True, text=True).stdout.strip()
print(f"\n  我的作业({me}):")
if not q:
    print("    (无)")
else:
    run=[l for l in q.splitlines() if l.split("|")[2]=="R"]
    pend=[l for l in q.splitlines() if l.split("|")[2]!="R"]
    ngpu=0
    for l in run:
        i,j,t,m,left,d,b,r = l.split("|")
        g=re.search(r"gpu:?[a-z0-9_]*:?(\d+)", b or "")
        n=int(g.group(1)) if g else 0
        ngpu += n*int(d) if ":" in (b or "") else n
        print(f"    {i:>9} {j:<12} R  已跑 {m:>11}  余 {left:>11}  {d}节点  {b}  {r}")
    for l in pend:
        i,j,t,m,left,d,b,r = l.split("|")
        print(f"    {i:>9} {j:<12} {t}  排队  墙钟 {left:>11}  {d}节点  {b}  ← {r}")
    print(f"    小计:运行 {len(run)} 个 / 排队 {len(pend)} 个")
PY
REMOTE
}

if [ "$WHICH" = "all" ] || [ "$WHICH" = "tillicum" ]; then
  remote_slurm Tillicum gpu-h200 | ssh -o ConnectTimeout=25 tillicum1 bash -s 2>&1 \
    || echo "  ✗ Tillicum 连不上(先跑一次 ssh tillicum1 过 Duo)"
fi
if [ "$WHICH" = "all" ] || [ "$WHICH" = "klone" ]; then
  remote_slurm Klone gpu-a100,gpu-l40s,gpu-a40,gpu-h200 | ssh -o ConnectTimeout=25 hyak bash -s 2>&1 \
    || echo "  ✗ Klone 连不上(先跑一次 ssh hyak 过 Duo)"
fi
