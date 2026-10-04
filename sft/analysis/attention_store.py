"""Lossless, seekable float32 attention rows; JSON stores offsets, not tensors."""
from array import array
import hashlib
from pathlib import Path
import sys
import zlib


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def append_row(path, values):
    try:
        view = memoryview(values)
    except TypeError:
        view = None
    if view is not None and view.ndim == 1 and view.format == 'f' and sys.byteorder == 'little':
        raw = view.tobytes()
    else:
        values = array('f', values)
        if sys.byteorder != 'little':
            values.byteswap()
        raw = values.tobytes()
    compressed = zlib.compress(raw, level=1)
    with Path(path).open('ab') as stream:
        offset = stream.tell()
        stream.write(compressed)
    return dict(offset=offset, length=len(compressed), codec='zlib-float32-le',
                chunk_sha256=hashlib.sha256(compressed).hexdigest())


def read_row(row, root):
    if 'weights' in row:
        return row['weights']
    ref = row['weights_ref']
    root = Path(root).resolve()
    path = (root / ref['path']).resolve()
    if not path.is_relative_to(root) or ref['codec'] != 'zlib-float32-le':
        raise ValueError('Invalid attention artifact path/codec')
    offset, length = ref['offset'], ref['length']
    if type(offset) is not int or type(length) is not int or offset < 0 or length <= 0:
        raise ValueError('Invalid attention byte range')
    with path.open('rb') as stream:
        stream.seek(offset)
        compressed = stream.read(length)
    if len(compressed) != length or hashlib.sha256(compressed).hexdigest() != ref['chunk_sha256']:
        raise ValueError('Attention chunk is missing or corrupt')
    decoder = zlib.decompressobj()
    count = row.get('stored_key_count', row['key_count'])
    if type(count) is not int or not 0 <= count <= row['key_count']:
        raise ValueError('Invalid stored attention count')
    raw = decoder.decompress(compressed, count * 4 + 1)
    if len(raw) != count * 4 or not decoder.eof or decoder.unused_data:
        raise ValueError('Attention shape differs from recorded key_count')
    values = array('f')
    values.frombytes(raw)
    if sys.byteorder != 'little':
        values.byteswap()
    return values
