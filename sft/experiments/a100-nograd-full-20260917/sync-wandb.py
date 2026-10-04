"""Mirror existing Swift scalar logs to W&B without touching the trainer."""
import fcntl
import json
import os
from pathlib import Path
import re
import time

import wandb

ROOT = Path('/gscratch/krishna/jy050706/out/9b-full-r5+v16save143.tf-ml65k-vnograd/train20260917-klone1x4')
LOG = ROOT / 'v0-20260917-125722/logging.jsonl'
STATE = ROOT / 'wandb-sync'
STATE.mkdir(exist_ok=True)
lock = (STATE / 'sync.lock').open('w')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
config = json.loads((ROOT / 'DEPLOYMENT.json').read_text())
run = wandb.init(
    project=os.environ.get('WANDB_PROJECT', 'cua-sft'),
    entity=os.environ.get('WANDB_ENTITY') or None,
    id='klone-40253867-30-vnograd', resume='allow', mode='online',
    name=config['arm'] + '-klone1x4-40253867',
    dir=str(STATE), config=config,
    tags=['vnograd', 'terminal-fix', 'r5-v16save143', 'log-mirror'],
    notes='Live mirror of Swift logging.jsonl. Training started 2026-09-17 12:56 PT. Historical steps backfilled; W&B timestamps are upload times. No checkpoint or image upload. System metrics disabled because this is a separate log reader.',
    settings=wandb.Settings(x_disable_stats=True, disable_git=True, console='off'),
)
run.define_metric('train/global_step')
run.define_metric('train/*', step_metric='train/global_step')
last_step = run.step - 1


def receipt(status):
    data = dict(url=run.url, run_id=run.id, project=run.project, entity=run.entity,
                last_synced_step=last_step, status=status, pid=os.getpid(),
                updated_at=time.time(), source=str(LOG))
    tmp = STATE / 'receipt.tmp'
    tmp.write_text(json.dumps(data, indent=2) + '\n')
    tmp.replace(STATE / 'receipt.json')


receipt('running')
print('WANDB_RUN_URL=' + run.url, flush=True)
while True:
    if LOG.exists():
        for line in LOG.read_text().splitlines(keepends=True):
            if not line.endswith('\n'):
                break  # Writer may still be appending this JSON object.
            row = json.loads(line)
            step = int(row['global_step/max_steps'].split('/')[0])
            if step <= last_step:
                continue
            values = {'train/' + key: value for key, value in row.items()
                      if isinstance(value, (int, float))}
            values['train/global_step'] = step
            elapsed = re.findall(r'(\d+)([dhms])', row.get('elapsed_time', ''))
            if elapsed:
                values['train/elapsed_seconds'] = sum(int(n) * dict(d=86400, h=3600, m=60, s=1)[unit] for n, unit in elapsed)
            run.log(values, step=step, commit=True)
            last_step = step
            receipt('running')
            print('SYNCED_STEP=' + str(step), flush=True)
    exit_file = ROOT / 'exit_code.txt'
    if exit_file.exists():
        code = int(exit_file.read_text().strip())
        run.summary['training_exit_code'] = code
        run.finish(exit_code=code)
        receipt('finished' if code == 0 else 'training_failed')
        break
    time.sleep(30)
