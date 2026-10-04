#!/bin/bash
set -euo pipefail
set +x
umask 077
set -a
source /gscratch/cse/jy050706/wandb.env
set +a
export APPTAINERENV_WANDB_API_KEY="$WANDB_API_KEY"
export APPTAINERENV_WANDB_PROJECT="${WANDB_PROJECT:-cua-sft}"
if [[ -n "${WANDB_ENTITY:-}" ]]; then export APPTAINERENV_WANDB_ENTITY="$WANDB_ENTITY"; fi
exec apptainer exec --no-mount /var/run/slurm,/var/spool/slurmd \
    --bind /gscratch/cse/jy050706:/gscratch/cse/jy050706 \
    --bind /gscratch/krishna/jy050706:/gscratch/krishna/jy050706 \
    /gscratch/cse/jy050706/sif/sft-train.sif /opt/venv/bin/python \
    /gscratch/cse/jy050706/sft/experiments/a100-nograd-full-20260917/sync-wandb.py
