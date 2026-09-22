"""Receipt-driven producer cleanup over existing SSH; never glob-delete a spool.

The producer CLI uses only stdlib (including Python 3.6 on Klone). It removes
acknowledged .attn files; small JSONL metadata and cleanup receipts are retained.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, sort_keys=True); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def cleanup_spool(spool, request, apply=False, min_age=60):
    import fcntl
    spool = Path(spool).resolve(strict=True)
    if request.get('version') != 1 or not re.fullmatch(r'[a-f0-9]{64}', request.get('receipt_id', '')):
        raise ValueError('Invalid cleanup receipt identity')
    artifacts = request.get('artifacts')
    if not isinstance(artifacts, list) or not 0 < len(artifacts) <= 256:
        raise ValueError('Cleanup needs a bounded explicit artifact list')
    names = set()
    for a in artifacts:
        if (not re.fullmatch(r'[a-f0-9]{64}\.rank[0-9]+\.attn', a.get('name', ''))
                or not re.fullmatch(r'[a-f0-9]{64}', a.get('sha256', ''))
                or type(a.get('bytes')) is not int or a['bytes'] <= 0 or a['name'] in names):
            raise ValueError('Invalid or duplicate producer artifact')
        names.add(a['name'])
    signature = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    folder = spool / '.cleanup-receipts'; folder.mkdir(exist_ok=True)
    receipt_path = folder / (request['receipt_id'] + '.json')
    with (folder / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        prior = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
        if prior and prior['request_sha256'] != signature:
            raise ValueError('Cleanup receipt ID cannot be rebound')
        verified = []
        for a in artifacts:
            path = spool / a['name']
            if path.is_symlink(): raise ValueError('Refusing producer symlink')
            if not path.exists():
                if not prior: raise ValueError('Producer artifact missing without a verified cleanup receipt')
                continue  # Recover a crash after unlink and before the final receipt.
            st = path.stat()
            if time.time() - st.st_mtime < min_age:
                return {'status': 'deferred', 'reason': 'Producer file is too recent'}
            if st.st_size != a['bytes'] or sha256(path) != a['sha256']:
                raise ValueError('Producer artifact differs from the verified consumer copy')
            after = path.stat()
            if (st.st_ino, st.st_size, st.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                raise ValueError('Producer artifact changed during verification')
            verified.append((path, after))
        result = {'status': 'verified', 'request_sha256': signature, 'receipt_id': request['receipt_id'],
                  'artifacts': artifacts, 'bytes': sum(a['bytes'] for a in artifacts),
                  'metadata_policy': 'Producer JSONL metadata retained', 'time': time.time()}
        if not apply: return {**result, 'status': 'dry_run'}
        # Persist verified intent before unlink so a process crash is recoverable.
        save(receipt_path, result)
        for path, st in verified:
            now = path.lstat()
            if path.is_symlink() or (now.st_ino, now.st_size, now.st_mtime_ns) != (st.st_ino, st.st_size, st.st_mtime_ns):
                raise ValueError('Producer artifact changed before removal')
            path.unlink()
        result['status'] = 'deleted'; save(receipt_path, result)
        return result


def sweep(config):
    """Clean one acknowledged task per call; an SSH/auth failure stops this sweep."""
    from sft.analysis.attention_download import locked
    from sft.analysis.retention import finish_cleanup
    from sft.analysis.visual_signals import read_json, write_json
    setting = config.get('producer_cleanup', {})
    if not setting.get('enabled') or config.get('raw_retention') != 'delete-after-export':
        return {'status': 'disabled'}
    command = setting.get('command')
    if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
        raise ValueError('Producer cleanup needs a configured argument-list command')
    output = Path(config['output_dir']).resolve(); root = Path(config['results_root']).resolve()
    signature = hashlib.sha256(json.dumps(setting, sort_keys=True).encode()).hexdigest()
    blocked_path = output / '.producer-cleanup-blocked.json'
    blocked = read_json(blocked_path, {})
    if blocked.get('configuration') == signature:
        return {'status': 'blocked', 'error': blocked['error']}
    with locked(output / '.producer-cleanup.lock') as acquired:
        if not acquired: return {'status': 'busy'}
        for path in sorted((output / 'retention').glob('*.json')):
            ack_path = output / 'producer-cleanup' / path.name
            if read_json(ack_path, {}).get('status') == 'deleted': continue
            receipt = read_json(path); task = Path(receipt['task']).resolve()
            if not task.is_relative_to(root) or receipt.get('policy') != 'delete-after-export' or receipt.get('status') != 'deleted': continue
            owner_config = {}
            # Honor an explicit keep switch in the task's own run, not only this worker's run.
            for parent in task.parents:
                if parent == root: break
                if (parent / 'inspection.json').exists():
                    owner_config = read_json(parent / 'inspection.json', {}); break
            if owner_config.get('raw_retention') == 'keep': continue
            bundle = read_json(output / 'tasks' / path.name, {})
            if not bundle.get('runs') or bundle['runs'][0].get('checkpoint') != setting.get('checkpoint'): continue
            try:
                jobs = [read_json(p) for p in (task / 'capture/downloads').glob('*.json')]
                if not jobs or any(j.get('status') != 'complete' for j in jobs): continue
                artifacts = []
                by_name = {Path(j['url']).name: j for j in jobs}
                for name, info in receipt['sources'].items():
                    original = Path(name)
                    if original.parent != task / 'capture/attention' or original.suffix != '.attn': continue
                    j = by_name.get(original.name)
                    if not j or j['sha256'] != info['sha256'] or j['bytes'] != info['size']:
                        raise ValueError('Download receipt does not match retained artifact identity')
                    artifacts.append(dict(name=original.name, sha256=info['sha256'], bytes=info['size']))
                if not artifacts: continue
                # A replay/import may share a producer blob with another local task.
                # Such a consumer must have its own completed archive before release.
                wanted = {a['name'] for a in artifacts}
                shared_pending = False
                for link in root.glob('*/attempts/*/attempt-*/*/*/capture/downloads/*.json'):
                    if link.stem not in wanted or link.parent.parent.parent == task: continue
                    peer = link.parent.parent.parent
                    source = read_json(link)
                    ready = False
                    for candidate in (output / 'retention').glob('*.json'):
                        value = read_json(candidate)
                        if value.get('task') == str(peer) and value.get('status') == 'deleted':
                            finish_cleanup(peer, output, candidate.stem); ready = True; break
                    if source.get('status') != 'complete' or not ready:
                        shared_pending = True; break
                if shared_pending: continue
                # Recheck the actual retained artifact bytes and task fingerprint before producer deletion.
                finish_cleanup(task, output, path.stem)
                identity = {'task': str(task), 'artifacts': artifacts, 'exported': receipt['artifacts']}
                request = {'version': 1, 'receipt_id': hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
                           'artifacts': artifacts}
                response = subprocess.run(command, input=json.dumps(request), text=True, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE, timeout=setting.get('timeout_seconds', 300))
                if response.returncode:
                    raise RuntimeError('Producer cleanup failed once: ' + response.stderr[-1200:])
                result = json.loads(response.stdout)
                if result.get('receipt_id') not in (None, request['receipt_id']):
                    raise ValueError('Producer acknowledged a different receipt')
                if result.get('status') == 'deleted':
                    write_json(ack_path, {**result, 'task': str(task), 'configuration': signature})
                return result
            except Exception as exc:
                write_json(blocked_path, {'configuration': signature, 'error': str(exc), 'task': str(task), 'time': time.time()})
                return {'status': 'blocked', 'error': str(exc)}
    return {'status': 'idle'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spool', required=True, type=Path)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--min-age-seconds', type=float, default=60)
    a = p.parse_args()
    if a.min_age_seconds < 0: p.error('min age must not be negative')
    import sys
    print(json.dumps(cleanup_spool(a.spool, json.load(sys.stdin), a.apply, a.min_age_seconds)))


if __name__ == '__main__': main()
