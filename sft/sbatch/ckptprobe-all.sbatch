#!/bin/bash
#SBATCH --job-name=ckptprobe
#SBATCH --account=video
#SBATCH --partition=gpu-h200
#SBATCH --qos=interactive
#SBATCH --nodes=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --output=/gpfs/scrubbed/jy050706/sft/ckptprobe_%j.out

# Measured parameter displacement for every arm, against the pre-SFT base.
# Why a batch job and not the login node: this streams ~264 GB off GPFS and
# does fp32 math over 4B params x 32 checkpoints -- real compute, which the
# login node is not for (a first attempt there was cgroup-killed, and it
# would have been a policy violation anyway). It asks for 1 GPU only because
# gpu-h200 has no CPU-only path; the probe itself never touches the device.
#
# What it settles: the eval curve has been read on an "lr x steps" axis, but
# Adam is scale-invariant, so neither gradient clipping nor cumulative LR
# gives the true ||theta_SFT - theta_base||. This measures it -- and the gap
# between measured net displacement and the cumulative-LR proxy is exactly
# how much the updates cancel each other out.
umask 077
set -x
B=/gpfs/scrubbed/jy050706/sft
BASE=$B/models/Qwen3.5-4B
cd $B && source venv/bin/activate
mkdir -p $B/probe
for arm in q38e3B-gb64o q38Bs-gb64 q38Bhqs-gb64 q38e3B-gb128 q38e1B q38e3B q38e3-rich q38e3-lean; do
  for v in $B/out/$arm/v*/; do
    ls $v | grep -q '^checkpoint-' || continue
    echo ">>> probing $arm ($v)"
    python ckptprobe.py "$v" --base "$BASE" --json "$B/probe/${arm}.json" || echo "FAILED $arm"
  done
done
echo "=== probe files ==="
ls -la $B/probe/
echo CKPTPROBE_ALL_DONE
