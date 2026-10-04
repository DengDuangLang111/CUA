#!/bin/bash
#SBATCH --job-name=eval4b-c2m
#SBATCH --account=video
#SBATCH --partition=gpu-h200
#SBATCH --qos=normal
#SBATCH --nodes=2
#SBATCH --gpus-per-node=4
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=400G
#SBATCH --time=1-00:00:00
#SBATCH --output=/gpfs/scrubbed/jy050706/sft/mixbtf_4bcap2m65_%j.out
# 臂 mixbtf —— mixB 的同一份 866 条轨迹,**只补终止规范化(terminalfix),其余不动**
# 对照 mixb9b:同语料/同配方,唯一变量 = 末步从 88-100% 散文变成 100% 显式 terminate。
# (原 mixB 头注释保留如下)
#
# 语料 = v16 判官准入 554 条 + v11 新批(i10x 重跑) 312 条 = 866 条轨迹
# 图窗 img10 / fold_size 1 —— 这是**建语料时**定死的(build.py --image-max 10
# --fold-size 1),sbatch 里没有对应参数,训练侧本轮改成 IMAGE_MIN_TOKEN_NUM=4096(强制上采样)/ MAX=8192,即 cap x2 实验。
#
# 拓扑 **2 节点 × 4 卡 × accum 8 = 全局 batch 64**(节点上限 2;2x2/accum16 实测 130 s/it 会撞 24h 墙,2x4 与 4x2 每卡负载相同,~70 s/it)。
#   4B @ img10 峰值  89.66 GiB (64.1%)
#   9B @ img10 峰值 115.80 GiB (82.8%)   ← 余 24 GiB
# 曾试过 2 节点 × 8 卡(实测更省显存、墙钟约减半),但它要求两个节点各 8 张全空,
# 集群里同时满足的节点常常只有一个,反而排不上队 —— 2026-08-30 实测排在
# Resources/Priority 上不动。4x2 只要每节点 2 张空即可,秒上。
#
# 两臂的唯一变量是 v11 用哪一批 rollout;v16 那 554 条两臂共用。
# max_length 65536(=原生 4B 基线值,对比更公平;峰值封 65536,cap x2 无 SP 稳装下)。
# 三次 OOM 定案:zero3(all-gather 峰值更糟)/SP=2(关 logits_to_keep,10GiB logits)都帮倒忙;回 zero2_offload,靠 max_length 65536 封峰值。cap x2 下仅 157 条(0.85%)超 65536。
umask 077
set -x
B=/gpfs/scrubbed/jy050706/sft

# ---- 语料(按 ship 时的目录名填;每份都要有 train_swift_abs.jsonl(图片是 /gpfs 绝对路径)) --------------
DS_V16MAIN=$B/data/mixbtf-v16-main
DS_V16PILOT=$B/data/mixbtf-v16-pilot
DS_V11NEW500=$B/data/mixbtf-v11new-500
DS_V11NEWALL=$B/data/mixbtf-v11new-all
# 四个目录只有 train_swift_abs.jsonl;图片路径指回 data/{v16-main,v16-pilot,v11new-500,v11new-all}/images(重建只换末步,图片逐字节相同)
DSLIST="$DS_V16MAIN $DS_V16PILOT $DS_V11NEW500 $DS_V11NEWALL"

# ---- 防撞自检:同一 OUT 里不许混进别的语料训出的产物 -----------------------
OUT=$B/out/mixbtf4b-cap2x-ml65k
for _a in "$OUT"/*/args.json; do
  [ -e "$_a" ] || continue
  grep -q "mixbtf-v11new-500" "$_a" || {
    echo "FATAL: $OUT 里已有别的语料训出的产物: $_a" >&2
    echo "       换 OUT,或把旧产物移走。拒绝启动以免口径混淆。" >&2
    exit 1; }
done
mkdir -p "$OUT" && echo "$DSLIST" > "$OUT/CORPUS.txt"

export PATH="$HOME/.local/bin:$PATH"
cd $B/runcwd && source $B/venv/bin/activate
export CUDA_HOME=$B/cuda13 PATH="$B/cuda13/bin:$PATH"
export LD_LIBRARY_PATH="$B/cuda13/lib64:$B/cuda13/lib:${LD_LIBRARY_PATH:-}"
export NCCL_P2P_DISABLE=1
export PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True'
export PYTHONPATH=$B/nocudnn:${PYTHONPATH:-}   # sitecustomize: enable_cudnn_sdp(False);2x4 拓扑不关会在 ep1.5 崩(272551/272837)
export IMAGE_MIN_TOKEN_NUM=4096   # 强制上采样:1920x1088(2040tok) -> 2752x1536(~4128tok),cap x2 单变量
export IMAGE_MAX_TOKEN_NUM=8192   # 上限抬高,别让 min 强制出来的 4128 又被 max 裁回去

# ---- 预检:每张图逐条 stat,不通过就在烧 GPU 之前退出 -----------------------
# 不验的失败模式是**静默地只拿文本训练**,不报错(DATA_PIPELINE.md 静默失效那节)。
for DS in $DSLIST; do
python - "$DS" <<'PY' || { echo "PREFLIGHT FAILED — aborting"; exit 1; }
import json, os, sys
ds = sys.argv[1]; bad = tot = 0
for line in open(os.path.join(ds, "train_swift_abs.jsonl"), encoding="utf-8"):
    if not line.strip(): continue
    for p in json.loads(line).get("images", []):
        tot += 1
        if not os.path.isabs(p) or not os.path.exists(p):
            bad += 1
            if bad < 4: print("UNRESOLVED:", p)
print(f"preflight {ds}: {tot} image refs, {bad} unresolved")
sys.exit(1 if bad else 0)
PY
done

# ---- 步数算术:save_steps 必须整除 steps/epoch,否则 checkpoint 落不在 -------
# epoch 边界上,save_total_limit 轮转会丢早期点。算完打进日志(TRAINING.md 立规)。
eval "$(python - $DSLIST <<'PY'
import sys
n = 0
for ds in sys.argv[1:]:
    n += sum(1 for line in open(ds + "/train_swift_abs.jsonl", encoding="utf-8") if line.strip())
GB = 64                      # 8 rank x accum 8 (2 节点 x 4 卡)
spe = -(-n // GB)            # steps per epoch, 向上取整
for d in (3, 2, 1):          # 尽量一个 epoch 存 3 次,退而求其次
    if spe % d == 0:
        save = spe // d
        break
print(f"SAMPLES={n}")
print(f"STEPS_PER_EPOCH={spe}")
print(f"SAVE_STEPS={save}")
print(f"TOTAL_STEPS={spe*3}")
PY
)"
echo ">>> 样本 $SAMPLES | steps/epoch $STEPS_PER_EPOCH | save_steps $SAVE_STEPS | 总步 $TOTAL_STEPS"
[ -n "$SAVE_STEPS" ] || { echo "FATAL: 步数算术失败"; exit 1; }

REPORT=none; RUN_NAME=mixbtf4b-cap2x-ml65k-${SLURM_JOB_ID}
if [ -f "$B/wandb.env" ]; then set +x; source "$B/wandb.env"; set -x
  export WANDB_PROJECT="${WANDB_PROJECT:-cua-sft}"; REPORT=wandb; fi
export WANDB_NOTES="mixbtf4b-cap2x: Qwen3.5-4B on mixbtf corpus (mixB 866 traj + terminalfix, 18560 samples), lr 3e-6 gb64 3ep. SINGLE VARIABLE vs native 4B = image resolution: IMAGE_MIN_TOKEN_NUM=4096 forces 1920x1088 upsample to ~4128 tok/img (cap x2, sqrt2 linear), img10 kept. cuDNN SDPA disabled from step0 (2x4). max_length 65536 (= native 4B baseline; caps peak so cap x2 fits without SP/zero3). Only 157/18560 (0.85%) samples exceed 65536 at cap x2."
export B DSLIST REPORT RUN_NAME OUT SAVE_STEPS PYTHONPATH
export MASTER_ADDR=$(scontrol show hostnames "$SLURM_JOB_NODELIST" | head -n1)
export MASTER_PORT=$((20000 + SLURM_JOB_ID % 9000))   # 写死端口在共享节点必撞
export NNODES=2 NPROC_PER_NODE=4
echo ">>> multinode: nodes=$SLURM_JOB_NODELIST master=$MASTER_ADDR port=$MASTER_PORT"
srun --ntasks=2 --ntasks-per-node=1 --kill-on-bad-exit=1 bash -c '
  export NODE_RANK=$SLURM_NODEID
  echo ">>> node $SLURM_NODEID ($(hostname)) launching NPROC=$NPROC_PER_NODE"
  DS_ARGS=""; for d in $DSLIST; do DS_ARGS="$DS_ARGS $d/train_swift_abs.jsonl"; done
  swift sft \
    --model $B/models/Qwen3.5-4B \
    --dataset $DS_ARGS \
    --enable_channel_loss true \
    --tuner_type full --loss_scale last_round --gradient_accumulation_steps 8 \
    --preserve_thinking true \
    --attn_impl sdpa --deepspeed zero2_offload \
    --torch_dtype bfloat16 \
    --num_train_epochs 3 --per_device_train_batch_size 1 \
    --learning_rate 3e-6 --warmup_ratio 0.1 \
    --weight_decay 0.0 --adam_beta2 0.999 \
    --max_length 65536 --gradient_checkpointing true \
    --save_strategy steps --save_steps $SAVE_STEPS --save_total_limit 12 \
    --logging_steps 1 \
    --report_to $REPORT --run_name $RUN_NAME \
    --output_dir $OUT
'
echo "EXIT_mixbtf4bcap2xml65k $?"
