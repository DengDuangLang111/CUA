"""Durable attention transfers, consumed by the existing post-processing worker.

Only a private key-file path is saved. One lock bounds transfers per host queue;
interrupted partial files resume and are published only after size/SHA checks.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
from types import SimpleNamespace

from .visual_signals import read_json, write_json


class DownloadPending(RuntimeError):
    pass


@contextmanager
def locked(path, wait=False):
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        yield True


def bind_paths(task, backend):
    task = Path(task)
    folder = task / 'capture/attention'
    folder.mkdir(parents=True, exist_ok=True)
    for name, info in backend['attention_blobs'].items():
        if (not re.fullmatch(r'[0-9a-f]{64}\.rank[0-9]+\.attn', name)
                or not re.fullmatch(r'[0-9a-f]{64}', info['sha256'])
                or type(info['bytes']) is not int or info['bytes'] <= 0):
            raise ValueError('Invalid attention artifact identity')
        info['path'] = (folder / name).relative_to(task).as_posix()
    for row in backend.get('attention', []):
        if 'weights_ref' in row:
            ref = row['weights_ref']
            info = backend['attention_blobs'][ref['blob']]
            ref.update(path=info['path'], sha256=info['sha256'])


@contextmanager
def url_stream(method, url, headers, timeout, follow_redirects=False):
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    if follow_redirects:
        raise ValueError('Attention downloads must not forward credentials through redirects')
    with build_opener(NoRedirect).open(Request(url, headers=headers, method=method), timeout=timeout) as response:
        yield SimpleNamespace(status_code=response.status, headers=response.headers,
                              raise_for_status=lambda: None,
                              iter_bytes=lambda size: iter(lambda: response.read(size), b''))


def fetch_blob(stream_request, url, headers, path, info, min_free_bytes=0, stop=None):
    """No full blob in RAM; retry network failures with a verified Range resume."""
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    started = time.perf_counter()
    for attempt in range(3):
        try:
            if stop is not None and stop.is_set():
                raise InterruptedError('Transfer stopped at a resumable boundary')
            if path.exists():
                sha = hashlib.sha256()
                with path.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        sha.update(chunk)
                if path.stat().st_size != info['bytes'] or sha.hexdigest() != info['sha256']:
                    raise ValueError('Existing attention artifact checksum/size mismatch')
                temporary.unlink(missing_ok=True)
                return dict(bytes=info['bytes'], seconds=time.perf_counter() - started, attempts=0)
            size = temporary.stat().st_size if temporary.exists() else 0
            if size > info['bytes']:
                raise ValueError('Attention file exceeds declared size')
            sha = hashlib.sha256()
            if size:
                with temporary.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        sha.update(chunk)
            if size < info['bytes']:
                if shutil.disk_usage(path.parent).free < info['bytes'] - size + min_free_bytes:
                    raise OSError('Insufficient disk space for attention download and reserve')
                request_headers = dict(headers)
                if size:
                    request_headers['Range'] = f'bytes={size}-'
                with stream_request('GET', url, headers=request_headers, timeout=600, follow_redirects=False) as response:
                    response.raise_for_status()
                    status = getattr(response, 'status_code', 200)
                    if size and status == 206:
                        match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('content-range', ''))
                        if not match or int(match[1]) != size or int(match[3]) != info['bytes']:
                            raise ValueError('Invalid attention Range response')
                    elif status == 200:
                        size, sha = 0, hashlib.sha256()
                    else:
                        raise ValueError('Unexpected attention download response')
                    with temporary.open('ab' if size else 'wb') as stream:
                        for chunk in response.iter_bytes(1024 * 1024):
                            if stop is not None and stop.is_set():
                                raise InterruptedError('Transfer stopped at a resumable boundary')
                            size += len(chunk)
                            if size > info['bytes']:
                                raise ValueError('Attention response exceeds declared size')
                            sha.update(chunk)
                            stream.write(chunk)
                        stream.flush()
                        os.fsync(stream.fileno())
            if size != info['bytes']:
                raise OSError('Incomplete attention download; partial file retained for resume')
            if sha.hexdigest() != info['sha256']:
                raise ValueError('Attention artifact checksum mismatch')
            temporary.replace(path)
            return dict(bytes=size, seconds=time.perf_counter() - started, attempts=attempt + 1)
        except Exception as exc:
            if isinstance(exc, InterruptedError):
                raise
            if isinstance(exc, ValueError):
                temporary.unlink(missing_ok=True)
                # A mismatched final file is never treated as a valid capture.
                path.unlink(missing_ok=True)
            if attempt == 2:
                raise
            time.sleep(2)


def enqueue(task, backend, base_url, config):
    task = Path(task).resolve()
    queue = Path(config['download_queue']).resolve()
    key_file = Path(config['key_file']).expanduser().resolve()
    if not key_file.is_file():
        raise ValueError('Background attention download needs an existing private key file')
    parsed = urlsplit(base_url)
    if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Invalid attention endpoint')
    bind_paths(task, backend)
    for name, info in backend['attention_blobs'].items():
        job_path = task / 'capture/downloads' / (name + '.json')
        job_path.parent.mkdir(parents=True, exist_ok=True)
        identity = dict(url=base_url.rstrip('/') + '/cua-attention/' + name,
                        key_file=str(key_file), bytes=info['bytes'], sha256=info['sha256'],
                        min_free_bytes=int(config.get('download_min_free_gib', 1) * 1024**3))
        existing = read_json(job_path)
        if existing is not None:
            if any(existing.get(k) != v for k, v in identity.items()):
                raise ValueError('Attention download identity changed')
            if existing.get('status') == 'complete':
                continue
        else:
            write_json(job_path, dict(identity, status='pending', queued_at=time.time()))
        marker = queue / (hashlib.sha256(str(job_path).encode()).hexdigest() + '.json')
        write_json(marker, dict(job=str(job_path)))


def task_ready(task):
    jobs = [read_json(p) for p in (Path(task) / 'capture/downloads').glob('*.json')]
    failed = [j for j in jobs if j['status'] == 'failed']
    if failed:
        raise RuntimeError('Attention download failed: ' + str(failed[0].get('error')))
    pending = sum(j['status'] != 'complete' for j in jobs)
    if pending:
        raise DownloadPending(f'{pending} attention files still downloading; raw data retained on model server')


def queue_jobs(queue, results_root):
    if not queue:
        return []
    jobs = []
    for marker in Path(queue).glob('*.json'):
        link = read_json(marker)
        if link is None:  # Another worker completed it after the directory listing.
            continue
        path = Path(link['job']).resolve()
        if not path.is_relative_to(Path(results_root).resolve()) or path.parent.name != 'downloads' or path.parent.parent.name != 'capture':
            raise ValueError('Download queue points outside captured tasks')
        jobs.append((marker, path, read_json(path)))
    return sorted(jobs, key=lambda row: row[2]['queued_at'])


def has_pending(queue, results_root):
    return any(j['status'] in ('pending', 'downloading') for _, _, j in queue_jobs(queue, results_root))


def retry_failed(queue, results_root):
    for _, path, job in queue_jobs(queue, results_root):
        if job['status'] == 'failed':
            job.update(status='pending', retried_at=time.time())
            write_json(path, job)


def download_one(queue, results_root, slot=0, stop=None):
    if not queue:
        return False
    if type(slot) is not int or not 0 <= slot < 4:
        raise ValueError('Download slot must be between 0 and 3')
    slot_lock = '.worker.lock' if slot == 0 else f'.worker-{slot}.lock'
    with locked(Path(queue) / slot_lock) as acquired:
        if not acquired:
            return False
        for marker, path, job in queue_jobs(queue, results_root):
            with locked(path.with_suffix('.download.lock')) as claimed:
                if not claimed:
                    continue
                job = read_json(path)
                if job['status'] == 'complete':
                    marker.unlink(missing_ok=True)
                    continue
                if job['status'] == 'failed':
                    continue
                target = path.parent.parent / 'attention' / path.stem
                with locked(Path(queue) / '.claims.lock', wait=True):
                    reserved = 0
                    for _, peer_path, peer in queue_jobs(queue, results_root):
                        if peer_path == path or peer['status'] != 'downloading': continue
                        peer_target = peer_path.parent.parent / 'attention' / peer_path.stem
                        if peer_target.exists(): continue
                        partial = peer_target.with_suffix('.tmp')
                        try: present = partial.stat().st_size
                        except FileNotFoundError: present = 0
                        reserved += max(0, peer['bytes'] - present)
                    job.update(status='downloading', started_at=time.time(), worker_slot=slot)
                    write_json(path, job)
                try:
                    headers = {'Authorization': 'Bearer ' + Path(job['key_file']).read_text().strip()}
                    timing = fetch_blob(url_stream, job['url'], headers, target, job, job['min_free_bytes'] + reserved, stop=stop)
                    job.update(status='complete', completed_at=time.time(), transfer=timing)
                    job.pop('error', None)
                except InterruptedError:
                    job.update(status='pending', interrupted_at=time.time())
                except Exception as exc:
                    job.update(status='failed', error=f'{type(exc).__name__}: {exc}', failed_at=time.time())
                write_json(path, job)
                if job['status'] == 'complete':
                    marker.unlink(missing_ok=True)
                return True
    return False
