# gpufree.awk -- scontrol show node | awk -v parts=gpu-h200 -f gpufree.awk
# 只用 POSIX awk 语法(2 参数 match + RSTART/RLENGTH),gawk/mawk/BSD awk 都能跑。
# 三个必须做的事:①故障节点的空卡另计,不算可用 ②过滤分区 ③跳过非 GPU 节点。
function gpunum(s,   p, t) {
  p = index(s, "gres/gpu=")            # CfgTRES 里同时有 gres/gpu=8 和
  if (p == 0) return 0                 # gres/gpu:h200=8;取前者,因为冒号!=等号
  t = substr(s, p + 9)
  if (match(t, /^[0-9]+/)) return substr(t, 1, RLENGTH) + 0
  return 0
}
# 分区精确匹配:节点的 Partitions 可能是逗号分隔的多个,parts 也是。
# 不能用 index() 子串匹配 —— "gpu-h200" 是 "gpu-h200-mig" 的子串,
# 查 mig 会把整卡节点一起捞进来(真机上实测踩到)。两边都加逗号哨兵。
function inparts(nodeparts,   i, n, arr) {
  if (parts == "") return 1
  n = split(nodeparts, arr, ",")
  for (i = 1; i <= n; i++)
    if (index("," parts ",", "," arr[i] ",")) return 1
  return 0
}
function flush(   free, bad) {
  if (node == "" || gpu_total == 0) return
  if (!inparts(part)) return
  free = gpu_total - gpu_alloc
  bad = (state ~ /DOWN|DRAIN|MAINT|FAIL|INVAL|RESERV/)
  tot_all += gpu_total; alloc_all += gpu_alloc
  if (bad) dead_all += free; else free_all += free
  if (free > 0)
    printf "  %-8s GPU %d/%d 空  CPU %d 空  %-14s%s\n", node, free, gpu_total,
           cputot-cpualloc, state, (bad ? "  <-- 不可用,别按这个数提作业" : (state ~ /PLANNED/ ? "  (已被调度器预定给排队作业)" : ""))
}
/^NodeName=/ { flush(); node=$1; sub("NodeName=","",node)
               cpualloc=0; cputot=0; gpu_total=0; gpu_alloc=0; state=""; part="" }
{ for(i=1;i<=NF;i++){
    if($i ~ /^CPUAlloc=/)   { split($i,a,"="); cpualloc=a[2] }
    if($i ~ /^CPUTot=/)     { split($i,a,"="); cputot=a[2] }
    if($i ~ /^State=/)      { split($i,a,"="); state=a[2] }
    if($i ~ /^Partitions=/) { split($i,a,"="); part=a[2] }
    if($i ~ /^CfgTRES=/)    { gpu_total = gpunum($i) }
    if($i ~ /^AllocTRES=/)  { gpu_alloc = gpunum($i) }
} }
END { flush()
      printf "\n  合计: 总 %d  已用 %d  可用 %d  不可用 %d(故障/维护)\n",
             tot_all, alloc_all, free_all, dead_all }
