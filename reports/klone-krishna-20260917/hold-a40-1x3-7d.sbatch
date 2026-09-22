#!/bin/bash
#SBATCH --job-name=hold-a40-1x3-7d
#SBATCH --account=gpu-a40-krishna
#SBATCH --partition=gpu-a40
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:a40:3
#SBATCH --cpus-per-task=6
#SBATCH --mem=192G
#SBATCH --time=7-00:00:00
#SBATCH --output=/gscratch/cse/jy050706/reservations/a40-1x3-20260917/hold_%j.out
set -euo pipefail
echo "job=$SLURM_JOB_ID node=$SLURM_JOB_NODELIST nodes=$SLURM_JOB_NUM_NODES gpu_ids=${CUDA_VISIBLE_DEVICES:-}"
[[ "$SLURM_JOB_NUM_NODES" == 1 ]] || exit 1
nvidia-smi --query-gpu=index,name,uuid,memory.total --format=csv
sleep 604800
