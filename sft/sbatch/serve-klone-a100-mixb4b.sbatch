#!/bin/bash
#SBATCH --job-name=srv-mb4
#SBATCH --account=gpu-a100-krishna
#SBATCH --partition=gpu-a100
#SBATCH --nodes=1
#SBATCH --gpus=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --output=/gscratch/cse/jy050706/srv_mb4_%j.out
#
# 臂 B(4B)eval-50 的 serve —— 一张 A100,Klone。
# 2026-08-31 建。起因:Tillicum H200 分区 22 台全满(只有 drain 掉的 g018 空着),
# eval 拿不到卡;Klone A100 有空档,用户手上已有 4 张。
#
# 权重 = mixB-4b checkpoint-873(epoch 3.0 终点),从 Tillicum 传过来,
#        身份已核对:base=Qwen3.5-4B, 语料=v16-main+v16-pilot+v11new-500+v11new-all,
#        lr 3e-6 / 3ep。传的是 tar(md5 9919fa6d...),不是碎文件。
#
# 相对 serve_l40s.sbatch 的三处 A100 特有改动:
#   1. --kv-cache-dtype fp8 -> auto。A100 是 sm_80,**FP8 需要 sm_89+**
#      (KLONE.md §1)。照抄 L40S/H200 的 fp8 会直接起不来。
#   2. account/partition 走 gpu-a100-krishna。gpu-a100-cse 的 MaxWall 只有
#      1 天且 CPU 额度紧;krishna 无墙钟上限(KLONE.md §1)。
#   3. --cpus-per-task=2。krishna 的 CPU 总额 39,四个占位作业各 8 = 32,
#      申请 8 会 AssocGrpCpuLimit 排不上(KLONE.md §1)。
#
# 全部热数据放节点本地盘,不碰 GPFS —— serve_l40s.sbatch 记录的三次卡死
# (apptainer build / SIF 直接 exec / torch.compile 缓存落 home)都是这一个原因。
set -euo pipefail
BASE=/gscratch/cse/jy050706
MODEL=${MODEL:-$BASE/sft/models/mixB-4b-e873}
NAME=${NAME:-mixB-4b-stock}
PORT=${PORT:-8041}
KEY=$(cat $BASE/.vllm_api_key)

[ -d "$MODEL" ] || { echo "FATAL: 权重目录不存在 $MODEL"; exit 1; }
[ -f "$MODEL/config.json" ] || { echo "FATAL: $MODEL 里没有 config.json"; exit 1; }

LOCAL=${SLURM_TMPDIR:-/tmp}/vllm-$SLURM_JOB_ID
mkdir -p "$LOCAL"
export XDG_CACHE_HOME=$LOCAL/cache
export APPTAINER_CACHEDIR=$LOCAL/apptainer
mkdir -p "$XDG_CACHE_HOME" "$APPTAINER_CACHEDIR"
trap 'rm -rf "$LOCAL"' EXIT

echo ">>> node=$(hostname) job=$SLURM_JOB_ID model=$MODEL name=$NAME port=$PORT"
nvidia-smi --query-gpu=name,memory.total,driver_version,compute_cap --format=csv,noheader
df -h "$LOCAL" | tail -1

echo ">>> 复制 SIF 到节点本地盘(GPFS 只擅长顺序大文件,不擅长容器里的上万个小文件)"
time cp "$BASE/sif/vllm-0.25.1.sif" "$LOCAL/vllm.sif"

apptainer exec --nv \
  --bind "$BASE:$BASE" \
  "$LOCAL/vllm.sif" \
  python3 -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --served-model-name "$NAME" \
    --api-key "$KEY" \
    --host 0.0.0.0 --port "$PORT" \
    --max-model-len 262144 \
    --kv-cache-dtype auto \
    --reasoning-parser qwen3 \
    --gpu-memory-utilization 0.90 \
    --limit-mm-per-prompt '{"image": 20}' \
    --override-generation-config '{"temperature":1.0,"top_p":0.95,"top_k":20,"min_p":0.0,"presence_penalty":0.0,"repetition_penalty":1.0,"max_new_tokens":81920}'
