"""Tillicum checkpoint -> verified Klone model -> one Slurm serving job.

Run on the source host with an existing Klone SSH master. No login loop, GPU
generation probe, automatic resubmission, or eval launch. See EVAL_AUTOMATION.md.
Python 3.6+ and rsync; the same file is streamed to Klone for remote operations.
"""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(str(temp), str(path))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def shell(args):
    return ' '.join(shlex.quote(str(a)) for a in args)


def command(args, timeout=30, **kwargs):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True, timeout=timeout, **kwargs)
    require(result.returncode == 0, '{} failed: {}'.format(args[0], result.stderr[-1600:]))
    return result.stdout.strip()


def validate(config):
    for key in ('model_id', 'arm'):
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+@~-]*', config[key]), 'Unsafe ' + key)
    for key in ('checkpoint', 'assets', 'destination_root', 'container', 'tool_root', 'key_file', 'bind_root', 'ssh_socket'):
        value = config[key]
        require(Path(value).is_absolute() and '..' not in Path(value).parts
                and not any(c.isspace() or c == '\0' for c in value), 'Invalid path: ' + key)
    require(re.fullmatch(r'[A-Za-z0-9_.@-]+', config['ssh_host']) and not config['ssh_host'].startswith('-'), 'Invalid SSH host')
    require(config['expected_step'] > 0, 'Pin an explicit checkpoint step')
    serving = config['serving']
    replicas = serving.get('replicas', 1)
    require(type(replicas) is int and 1 <= replicas <= 8, 'Invalid replica count')
    require(1024 <= serving['port'] <= 65536 - replicas, 'Invalid port range')
    for key in ('tensor_parallel', 'max_model_len', 'max_num_seqs', 'image_limit', 'max_num_batched_tokens'):
        require(isinstance(serving[key], int) and serving[key] > 0, 'Invalid ' + key)
    require(0 < serving['gpu_memory_utilization'] < 1, 'Invalid GPU memory fraction')
    require(isinstance(config['capture'], (dict, bool)), 'capture must be an object or false')
    require(config['capture'] is not True, 'Use a capture object or false')
    allowed = {'account', 'partition', 'qos', 'gres', 'cpus-per-task', 'mem', 'time', 'constraint'}
    require(set(config['slurm']) <= allowed, 'Unsupported Slurm option')
    require({'account', 'partition', 'gres', 'mem', 'time'} <= set(config['slurm']), 'Missing Slurm resources')
    require(re.fullmatch(r'gpu(?::[A-Za-z0-9_-]+)?:' + str(serving['tensor_parallel']), config['slurm']['gres']),
            'Slurm GPU count must equal tensor_parallel')
    for key, value in config['slurm'].items():
        require(re.fullmatch(r'[A-Za-z0-9_.:+-]+', str(value)), 'Invalid Slurm ' + key)
    root = Path(config['bind_root'])
    for key in ('destination_root', 'container', 'tool_root', 'key_file'):
        require(root in Path(config[key]).parents, key + ' must be inside bind_root')
    return config


def checkpoint_files(config):
    """Select inference files only; never ship optimizer/RNG/DeepSpeed state."""
    source, assets = Path(config['checkpoint']), Path(config['assets'])
    require(read(source / 'trainer_state.json')['global_step'] == config['expected_step'], 'Checkpoint step mismatch')
    index = source / 'model.safetensors.index.json'
    declared = read(index)['weight_map'] if index.exists() else None
    shards = sorted(set(declared.values())) if declared else ['model.safetensors']
    tensors = {}
    files = {}
    for name in shards:
        require(re.fullmatch(r'[A-Za-z0-9_.-]+\.safetensors', name), 'Unsafe shard filename')
        path = source / name
        with path.open('rb') as stream:
            size = struct.unpack('<Q', stream.read(8))[0]
            require(0 < size < 100_000_000, 'Invalid safetensors header')
            header = json.loads(stream.read(size))
        end = 0
        for key, value in header.items():
            if key == '__metadata__':
                continue
            require(key not in tensors, 'Duplicate tensor ' + key)
            begin, stop = value['data_offsets']
            require(0 <= begin <= stop, 'Invalid tensor offsets')
            end = max(end, stop)
            tensors[key] = name
        require(path.stat().st_size == 8 + size + end, 'Incomplete shard: ' + name)
        files[name] = path
    require(declared is None or tensors == declared, 'Shard index and tensor keys differ')
    require(any('.visual.' in k for k in tensors), 'Expected a complete multimodal checkpoint, not text-only/LoRA weights')
    for name in ('config.json', 'trainer_state.json'):
        require((source / name).is_file(), 'Missing checkpoint ' + name)
        files[name] = source / name
    if index.exists():
        files[index.name] = index
    for name in ('args.json', 'INIT_MANIFEST.json'):
        if (source / name).is_file():
            files[name] = source / name
    # Explicit fallback only for inference assets; weights/config never fall back.
    for name in ('tokenizer.json', 'tokenizer_config.json', 'preprocessor_config.json',
                 'chat_template.jinja', 'processor_config.json', 'video_preprocessor_config.json',
                 'generation_config.json', 'special_tokens_map.json', 'added_tokens.json', 'vocab.json', 'merges.txt'):
        path = source / name if (source / name).is_file() else assets / name
        if path.is_file():
            files[name] = path
    require(all(n in files for n in ('tokenizer.json', 'tokenizer_config.json', 'preprocessor_config.json')), 'Missing tokenizer/image processor')
    tokenizer = read(files['tokenizer_config.json'])
    require('chat_template.jinja' in files or tokenizer.get('chat_template'), 'Missing chat template')
    return files


def bundle(config):
    files = checkpoint_files(config)
    manifest = {name: dict(bytes=p.stat().st_size, sha256=sha(p), source=str(p)) for name, p in files.items()}
    return files, dict(config=config, files=manifest)


def paths(config):
    base = Path(config['destination_root']) / config['model_id']
    return base, base / 'model'


def serving_script(config, replica=0):
    base, model = paths(config)
    s = config['serving']
    lines = ['#!/bin/bash']
    suffix = '-r' + str(replica + 1) if s.get('replicas', 1) > 1 else ''
    directives = dict(config['slurm'], nodes=1, ntasks=1,
                      **{'job-name': config['model_id'] + suffix, 'output': str(base / 'serve-%j.log')})
    lines += ['#SBATCH --{}={}'.format(k, v) for k, v in directives.items()]
    lines += ['set -euo pipefail',
              'test -r ' + shlex.quote(config['key_file']),
              'export VLLM_API_KEY="$(cat ' + shlex.quote(config['key_file']) + ')"',
              'test -n "$VLLM_API_KEY"',
              'export HF_HUB_OFFLINE=1',
              'export XDG_CACHE_HOME="${SLURM_TMPDIR:-/tmp}/cua-serve-${SLURM_JOB_ID}/cache"',
              'export APPTAINER_CACHEDIR="${SLURM_TMPDIR:-/tmp}/cua-serve-${SLURM_JOB_ID}/apptainer"',
              'mkdir -p "$XDG_CACHE_HOME" "$APPTAINER_CACHEDIR"',
              # FlashInfer defaults to HOME, not XDG; HOME may link to a full GPFS cache.
              'export FLASHINFER_WORKSPACE_BASE="$XDG_CACHE_HOME/flashinfer"',
              'export TRITON_CACHE_DIR="$XDG_CACHE_HOME/triton"',
              'export APPTAINERENV_FLASHINFER_WORKSPACE_BASE="$FLASHINFER_WORKSPACE_BASE"',
              'export APPTAINERENV_TRITON_CACHE_DIR="$TRITON_CACHE_DIR"']
    args = ['apptainer', 'exec', '--nv', '--bind', config['bind_root'] + ':' + config['bind_root'],
            config['container'], 'python3', '-m', 'vllm.entrypoints.openai.api_server',
            '--model', str(model), '--served-model-name', config['model_id'], '--dtype', 'bfloat16',
            '--host', '0.0.0.0', '--port', s['port'] + replica, '--tensor-parallel-size', s['tensor_parallel'],
            '--max-model-len', s['max_model_len'], '--max-num-seqs', s['max_num_seqs'],
            '--max-num-batched-tokens', s['max_num_batched_tokens'],
            '--gpu-memory-utilization', s['gpu_memory_utilization'], '--kv-cache-dtype', 'auto',
            '--reasoning-parser', 'qwen3', '--limit-mm-per-prompt', json.dumps({'image': s['image_limit']}),
            '--mm-processor-kwargs', json.dumps(s['mm_processor_kwargs']),
            '--override-generation-config', json.dumps(s['generation_config'])]
    if config['capture'] is not False:
        root = config['tool_root']
        lines += ['export CUA_VLLM_CAPTURE_CONFIG=' + shlex.quote(str(base / 'capture.json')),
                  'export PYTHONPATH=' + shlex.quote(root + '/sft/scripts/serve/visual_capture:' + root)]
        args += ['--enforce-eager', '--attention-backend', 'FLASH_ATTN', '--no-async-scheduling',
                 '--no-enable-prefix-caching', '--mm-processor-cache-gb', '0']
    lines += ['exec ' + shell(args)]
    return '\n'.join(lines) + '\n'


def remote(config, operation, payload=None):
    command(['ssh', '-S', config['ssh_socket'], '-O', 'check', config['ssh_host']])
    ssh = ['ssh', '-S', config['ssh_socket'], '-o', 'ControlMaster=no', '-o', 'BatchMode=yes',
           '-o', 'ConnectionAttempts=1', '-o', 'ConnectTimeout=10']
    request = base64.b64encode(json.dumps(dict(config=config, payload=payload)).encode()).decode()
    output = command(ssh + [config['ssh_host'], shell(['python3', '-', '_remote', operation, request])],
                     timeout=7200 if operation == 'publish' else 60, input=Path(__file__).read_text())
    return json.loads(output)


def remote_operation(config, operation, payload):
    base, model = paths(config)
    if operation == 'status':
        return service_status(config)
    base.mkdir(parents=True, exist_ok=True)
    with (base / '.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        binding = base / 'deployment.json'
        if binding.exists():
            require(read(binding) == payload, 'Model ID is already bound to other files/config; use a new deployment ID')
        else:
            write(binding, payload)
        if operation == 'init':
            (base / 'upload').mkdir(exist_ok=True)
            return dict(published=model.is_dir(), destination=str(base / 'upload'))
        require(operation == 'publish', 'Unknown remote operation')
        job = base / 'job.json'
        if job.exists():
            record = read(job)
            require(record.get('job_id') or record.get('services'), 'Previous sbatch outcome uncertain; inspect Slurm before any new submission')
            return record
        stage = model if model.is_dir() else base / 'upload'
        expected = payload['files']
        require({p.name for p in stage.iterdir()} == set(expected), 'Unexpected/missing files in staged model')
        for name, record in expected.items():
            path = stage / name
            require(path.stat().st_size == record['bytes'] and sha(path) == record['sha256'], 'Transfer checksum mismatch: ' + name)
        require(Path(config['container']).is_file(), 'Missing serving container')
        key = Path(config['key_file'])
        require(key.is_file() and key.stat().st_mode & 0o777 in (0o400, 0o600), 'Key file must have mode 400/600')
        if config['capture'] is not False:
            tool = Path(config['tool_root'])
            required = ['sft/scripts/serve/visual_capture/sitecustomize.py', 'sft/analysis/vllm_capture.py', 'sft/analysis/attention_store.py']
            require(all((tool / n).is_file() for n in required), 'Deploy existing CUA capture modules first')
            write(base / 'capture-code.json', {n: sha(tool / n) for n in required})
            capture = dict(config['capture'], directory=str(base / 'capture-spool'))
            write(base / 'capture.json', capture)
        if stage != model:
            os.rename(str(stage), str(model))
        replicas = config['serving'].get('replicas', 1)
        services = []
        for i in range(replicas):
            script = base / ('serve.sbatch' if replicas == 1 else 'serve-r{}.sbatch'.format(i + 1))
            receipt = job if replicas == 1 else base / 'job-r{}.json'.format(i + 1)
            script.write_text(serving_script(config, i))
            services.append(submit_once(config, script, receipt))
        if replicas == 1:
            return services[0]
        record = dict(model_id=config['model_id'], checkpoint=str(model), state='submitted', services=services)
        write(job, record)
        return record


def submit_once(config, script, receipt):
    if receipt.exists():
        saved = read(receipt)
        require(saved.get('job_id'), 'Previous sbatch outcome uncertain; inspect Slurm before any new submission')
        return saved
    # One receipt per independent job; a lost reply must never duplicate a GPU allocation.
    write(receipt, dict(state='submission_started', model_id=config['model_id']))
    reply = command(['sbatch', '--parsable', str(script)])
    job_id = reply.split(';')[0]
    require(job_id.isdigit(), 'Unexpected sbatch response; inspect Slurm')
    record = dict(job_id=job_id, checkpoint=str(paths(config)[1]), model_id=config['model_id'], state='submitted')
    write(receipt, record)
    return record


def serve_held(config):
    """Run replicas as one Slurm step in an already owned single-node allocation."""
    job = str(config['allocation_job'])
    require(re.fullmatch(r'[0-9]+', job), 'Invalid allocation job ID')
    require(config['serving']['tensor_parallel'] == 1, 'Held replicas require TP1')
    base, model = paths(config)
    require(model.is_dir(), 'Publish/verify the checkpoint before serving it')
    folder = base / ('allocation-' + job)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / '.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = folder / 'launch.json'
        if receipt.exists():
            saved = read(receipt)
            require(saved['config'] == config, 'Allocation serving config changed')
            return saved  # Never duplicate a possibly successful step submission.
        detail = command(['scontrol', 'show', 'job', '-o', job])
        require('JobState=RUNNING' in detail and 'NumNodes=1 ' in detail, 'Allocation must be running on one node')
        require(re.search(r'UserId=[^ ]+\(' + str(os.getuid()) + r'\)', detail), 'Allocation is not owned by this user')
        replicas = config['serving'].get('replicas', 1)
        cpus = int(config['slurm'].get('cpus-per-task', 1))
        require(int(re.search(r'NumCPUs=(\d+)', detail).group(1)) >= cpus * replicas, 'Insufficient allocated CPUs')
        tres = re.search(r'AllocTRES=([^ ]+)', detail).group(1)
        gpu = re.search(r'(?:^|,)gres/gpu=(\d+)(?:,|$)', tres)
        require(gpu and int(gpu.group(1)) >= replicas, 'Insufficient allocated GPUs')
        require(Path(config['key_file']).stat().st_mode & 0o777 in (0o400, 0o600), 'Key file must be private')
        require((base / 'capture.json').is_file() or config['capture'] is False, 'Missing capture configuration')
        for i in range(replicas):
            (folder / ('serve-r{}.sh'.format(i))).write_text(serving_script(config, i))
        launcher = folder / 'replicas.py'
        launcher.write_text('''import json,os,subprocess
from pathlib import Path
folder=Path(__file__).parent
config=json.loads((folder/'launch.json').read_text())['config']
count=config['serving'].get('replicas',1)
rows=subprocess.check_output(['nvidia-smi','--query-gpu=uuid,memory.used','--format=csv,noheader,nounits'],universal_newlines=True).splitlines()
devices=[r.split(',')[0].strip() for r in rows]
assert len(devices)==count and all(int(r.split(',')[1])<512 for r in rows),'Allocated GPUs are missing or busy'
children=[];records=[]
for rank,device in enumerate(devices):
 env=dict(os.environ,CUDA_VISIBLE_DEVICES=device,OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
 with (folder/('replica-%d.log'%rank)).open('ab') as log:
  child=subprocess.Popen(['bash',str(folder/('serve-r%d.sh'%rank))],env=env,stdout=log,stderr=log)
 children.append(child);records.append(dict(pid=child.pid,gpu_uuid=device,port=config['serving']['port']+rank,step=os.environ['SLURM_STEP_ID']))
(folder/'replicas.json').write_text(json.dumps(records,indent=2))
codes=[p.wait() for p in children]
raise SystemExit(1 if any(codes) else 0)
''')
        parts = config['slurm']['gres'].split(':')
        gpu_spec = (parts[1] + ':' if len(parts) == 3 else '') + str(replicas)
        args = ['srun', '--jobid=' + job, '--overlap', '--exact', '--nodes=1', '--ntasks=1',
                '--cpus-per-task=' + str(cpus * replicas), '--gpus-per-node=' + gpu_spec,
                '--gpu-bind=none', 'python3', str(launcher)]
        record = dict(state='submission_started', config=config, command=args, allocation_job=job)
        write(receipt, record)
        with (folder / 'launcher.log').open('ab') as log:
            child = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        record.update(state='starting', launcher_pid=child.pid)
        write(receipt, record)
        return record


def service_status(config):
    base, model = paths(config)
    require(read(base / 'deployment.json')['config'] == config, 'Config differs from saved deployment')
    job = read(base / 'job.json')
    if job.get('services'):
        services = []
        for i, record in enumerate(job['services']):
            try:
                services.append(probe_service(config, record, record.get('port',config['serving']['port'] + i)))
            except (OSError, ValueError) as exc:
                services.append(dict(record, ready=False, error=str(exc)))
        result = dict(job, services=services, ready=all(s['ready'] for s in services))
        if result['ready']:
            result['eval_model'] = dict(services[0]['eval_model'],
                max_parallel_requests=sum(s.get('max_num_seqs',config['serving']['max_num_seqs']) for s in services))
        return result
    return probe_service(config, job, config['serving']['port'])


def probe_service(config, job, port):
    base, model = paths(config)
    require(job.get('job_id'), 'Submission outcome uncertain; inspect Slurm')
    info = command(['scontrol', 'show', 'job', '-o', job['job_id']])
    fields = dict(re.findall(r'(\w+)=([^ ]+)', info))
    result = dict(job, state=fields.get('JobState'), node=fields.get('NodeList'), port=port, ready=False)
    if result['state'] != 'RUNNING':
        return result
    nodes = command(['scontrol', 'show', 'hostnames', result['node']]).splitlines()
    require(len(nodes) == 1, 'Expected one serving node')
    result['node'] = nodes[0]
    url = 'http://{}:{}'.format(nodes[0], result['port'])
    headers = {'Authorization': 'Bearer ' + Path(config['key_file']).read_text().strip()}
    try:
        with urlopen(Request(url + '/v1/models', headers=headers), timeout=10) as response:
            models = json.load(response)['data']
        served = next((m for m in models if m.get('id') == config['model_id']), None)
        require(served and served.get('root') == str(model), 'Serving checkpoint/model ID mismatch')
        require(served.get('max_model_len', 0) >= config['serving']['max_model_len'], 'Serving context mismatch')
        if config['capture'] is not False:
            def capture_ready():
                try:
                    urlopen(Request(url + '/v1/cua-attention/' + '0' * 64 + '.rank0.attn', headers=headers, method='OPTIONS'), timeout=10).close()
                except HTTPError as exc:
                    return exc.code == 405 and 'GET' in exc.headers.get('Allow', '')
                return False
            if not capture_ready():
                # The existing collector registers its route on first chat entry.
                # An unregistered model is rejected before GPU generation, but
                # still enters that wrapper. Never probe using the real model.
                name = config['model_id'] + '--unregistered-readiness-probe'
                require(all(m.get('id') != name for m in models), 'Readiness probe name is registered')
                data = json.dumps(dict(model=name, messages=[dict(role='user', content='Initialize capture route')], max_tokens=1)).encode()
                try:
                    urlopen(Request(url + '/v1/chat/completions', data=data,
                                    headers=dict(headers, **{'Content-Type': 'application/json'})), timeout=10).close()
                    raise ValueError('Expected the unregistered probe model to be rejected')
                except HTTPError as exc:
                    require(exc.code == 404, 'Unexpected capture route initialization response')
                require(capture_ready(), 'Attention collector is not ready')
        result.update(ready=True, endpoint=url + '/v1', served_model=served)
        # Existing eval registry owns Windows tunnel paths; do not guess them.
        result['eval_model'] = dict(arm=config['arm'], checkpoint=str(model), endpoint=config['model_id'],
                                   precision='BF16', min_context=config['serving']['max_model_len'],
                                   max_parallel_requests=job.get('max_num_seqs',config['serving']['max_num_seqs']))
    except (OSError, ValueError) as exc:
        result['error'] = str(exc)
    return result


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '_remote':
        request = json.loads(base64.b64decode(sys.argv[3]))
        print(json.dumps(remote_operation(validate(request['config']), sys.argv[2], request['payload'])))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['plan', 'prepare', 'status', 'serve-held'])
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args()
    config = validate(read(args.config))
    if args.operation == 'serve-held':
        print(json.dumps(serve_held(config), indent=2))
        return
    if args.operation == 'status':
        print(json.dumps(remote(config, 'status'), indent=2))
        return
    # Source-host lock shared by login nodes, held through transfer and submission.
    with args.config.with_suffix('.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        files, manifest = bundle(config)
        if args.operation == 'plan':
            print(json.dumps(dict(manifest=manifest, serving_scripts=[serving_script(config, i)
                             for i in range(config['serving'].get('replicas', 1))]), indent=2))
            return
        state = remote(config, 'init', manifest)
        if not state['published']:
            ssh = shell(['ssh', '-S', config['ssh_socket'], '-o', 'ControlMaster=no', '-o', 'BatchMode=yes',
                         '-o', 'ConnectionAttempts=1', '-o', 'ConnectTimeout=10'])
            for directory in sorted(set(p.parent for p in files.values())):
                names = '\n'.join(n for n, p in files.items() if p.parent == directory) + '\n'
                command(['rsync', '-rtL', '--partial', '--checksum', '--protect-args', '--timeout=120',
                         '--files-from=-', '-e', ssh, str(directory) + '/',
                         config['ssh_host'] + ':' + state['destination'] + '/'], timeout=7200, input=names)
        # Catch checkpoints modified while they were being transferred.
        for name, path in files.items():
            require(sha(path) == manifest['files'][name]['sha256'], 'Source changed during transfer: ' + name)
        print(json.dumps(remote(config, 'publish', manifest), indent=2))


if __name__ == '__main__':
    main()
