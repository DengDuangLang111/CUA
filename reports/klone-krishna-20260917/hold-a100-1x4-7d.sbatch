#!/bin/bash
#SBATCH --job-name=hold-a100-1x4-7d
#SBATCH --account=gpu-a100-krishna
#SBATCH --partition=gpu-a100
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:a100:4
#SBATCH --cpus-per-task=16
#SBATCH --mem=384G
#SBATCH --time=7-00:00:00
#SBATCH --output=/gscratch/cse/jy050706/reservations/a100-1x4-20260917/hold_%j.out
set -euo pipefail
echo "job=$SLURM_JOB_ID node=$SLURM_JOB_NODELIST nodes=$SLURM_JOB_NUM_NODES gpu_ids=${CUDA_VISIBLE_DEVICES:-}"
[[ "$SLURM_JOB_NUM_NODES" == 1 ]] || exit 1
nvidia-smi --query-gpu=index,name,uuid,memory.total --format=csv
sleep 604800
