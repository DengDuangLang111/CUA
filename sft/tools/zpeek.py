"""Read a remote zip's central directory over HTTP range requests, and pull
individual members, without downloading the archive. Handles ZIP64."""
import io, json, struct, subprocess, sys, zlib

def rng(url, a, b):
    p = subprocess.run(["curl", "-sSL", "-r", "%d-%d" % (a, b), url],
                       capture_output=True)
    if p.returncode:
        raise SystemExit("curl failed: %s" % p.stderr.decode()[:300])
    return p.stdout

def total(url):
    p = subprocess.run(["curl", "-sSLI", url], capture_output=True, text=True)
    for line in reversed(p.stdout.splitlines()):
        if line.lower().startswith("content-length:"):
            return int(line.split(":")[1])
    raise SystemExit("no content-length")

def central(url, size):
    tail = rng(url, max(0, size - 200000), size - 1)
    base = size - len(tail)
    i = tail.rfind(b"PK\x05\x06")
    if i < 0:
        raise SystemExit("no EOCD")
    n, off = struct.unpack("<I", tail[i+12:i+16])[0], struct.unpack("<I", tail[i+16:i+20])[0]
    cnt = struct.unpack("<H", tail[i+10:i+12])[0]
    j = tail.rfind(b"PK\x06\x06")          # ZIP64 EOCD
    if j >= 0:
        cnt = struct.unpack("<Q", tail[j+32:j+40])[0]
        n   = struct.unpack("<Q", tail[j+40:j+48])[0]
        off = struct.unpack("<Q", tail[j+48:j+56])[0]
    cd = tail[off-base:off-base+n] if off >= base else rng(url, off, off+n-1)
    return cd, cnt

def entries(cd):
    out, p = [], 0
    while p + 46 <= len(cd) and cd[p:p+4] == b"PK\x01\x02":
        meth, csz, usz = struct.unpack("<H", cd[p+10:p+12])[0], \
            struct.unpack("<I", cd[p+20:p+24])[0], struct.unpack("<I", cd[p+24:p+28])[0]
        nl, el, cl = struct.unpack("<HHH", cd[p+28:p+34])
        lo = struct.unpack("<I", cd[p+42:p+46])[0]
        name = cd[p+46:p+46+nl].decode("utf-8", "replace")
        ex, q = cd[p+46+nl:p+46+nl+el], 0
        while q + 4 <= len(ex):                       # ZIP64 extra field
            hid, hsz = struct.unpack("<HH", ex[q:q+4]); d = ex[q+4:q+4+hsz]; k = 0
            if hid == 1:
                if usz == 0xFFFFFFFF: usz = struct.unpack("<Q", d[k:k+8])[0]; k += 8
                if csz == 0xFFFFFFFF: csz = struct.unpack("<Q", d[k:k+8])[0]; k += 8
                if lo  == 0xFFFFFFFF: lo  = struct.unpack("<Q", d[k:k+8])[0]
            q += 4 + hsz
        out.append(dict(name=name, meth=meth, csz=csz, usz=usz, lo=lo))
        p += 46 + nl + el + cl
    return out

def member(url, e):
    hdr = rng(url, e["lo"], e["lo"] + 29)
    nl, el = struct.unpack("<HH", hdr[26:30])
    start = e["lo"] + 30 + nl + el
    raw = rng(url, start, start + e["csz"] - 1)
    return zlib.decompress(raw, -15) if e["meth"] == 8 else raw

if __name__ == "__main__":
    url = sys.argv[1]
    sz = total(url)
    cd, cnt = central(url, sz)
    es = entries(cd)
    print("archive %.1f MB, %d entries (cd says %d)" % (sz/1e6, len(es), cnt))
    json.dump(es, open(sys.argv[2], "w"))
