#!/bin/bash
#SBATCH --job-name=hold-l40s-1x8-7d
#SBATCH --account=gpu-l40s-krishna
#SBATCH --partition=gpu-l40s
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:l40s:8
#SBATCH --cpus-per-task=16
#SBATCH --mem=512G
#SBATCH --time=7-00:00:00
#SBATCH --output=/gscratch/cse/jy050706/reservations/l40s-1x8-20260917/hold_%j.out
set -euo pipefail
echo "job=$SLURM_JOB_ID node=$SLURM_JOB_NODELIST nodes=$SLURM_JOB_NUM_NODES gpu_ids=${CUDA_VISIBLE_DEVICES:-}"
[[ "$SLURM_JOB_NUM_NODES" == 1 ]] || exit 1
nvidia-smi --query-gpu=index,name,uuid,memory.total --format=csv
sleep 604800
