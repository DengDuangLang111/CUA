#!/usr/bin/env python3
"""内嵌 fixture 的真实类型审计。

为什么需要它:2026-08-30 在 v16 上抓到 —— 任务 JSON 里 base64 内嵌的办公文件
是合法 ZIP、setup 退出码是 0、首帧截图也不是空桌面,但 ODF zip 内部的
`mimetype` 条目写的是 `...opendocument.text`,而文件名叫 `.odp`。
LibreOffice 认内部类型不认扩展名,于是"改幻灯片"的任务在 VM 里打开的是
Writer 中的一段纯文本 —— 任务从定义上无解,而已有的两道闸全部放行。

  setup rc == 0      只证明文件写出来了
  首帧非空桌面        只证明有窗口起来了
  test -s            只证明文件非空
  本检查             证明它是不是那个类型

用法:
    python3 fixture_type_audit.py <任务集目录> [<任务集目录> ...]
    # 任务集目录 = 含 examples/<domain>/<id>.json 与 manifest.json 的那一层

退出码 0=全部合格,1=发现不符(便于挂进流水线闸)。
"""
import base64, collections, glob, io, json, os, re, sys, zipfile

ODF = {
    "odp": "application/vnd.oasis.opendocument.presentation",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odg": "application/vnd.oasis.opendocument.graphics",
}
OOXML = {
    "xlsx": "xl/workbook.xml",
    "docx": "word/document.xml",
    "pptx": "ppt/presentation.xml",
}
# 2026-08-30 教训:最初只认 `base64 -d ... > '<path>'` 这一种形态,漏掉了
# 用 soffice --convert-to / --outdir 产出、或先写临时名再 mv 的写法,少数了约 三分之一。
# 现在改成:在同一条 execute 命令里,取"最后出现的办公扩展名路径"作为产物,
# 与该命令里的全部 base64 片段配对。宁可多扫,不要漏。
OFFICE_EXT = "odp|odt|ods|odg|xlsx|docx|pptx"
RE_PATH = re.compile(r"['\"]([^'\"]*\.(?:%s))['\"]" % OFFICE_EXT, re.I)
RE_B64 = re.compile(r"['\"]([A-Za-z0-9+/=]{200,})['\"]")


def pair_blobs_to_paths(cmd):
    """把一条 execute 命令拆成 (产物路径, 该产物的 base64 字节) 的序列。

    生成器写出来的形态是可重复的段落:
        rm -f TMP && printf %s 'BLOB' >> TMP [&& printf %s 'BLOB' >> TMP ...]
              && base64 -d TMP > 'PATH'
    一条命令里可以有多个这样的段落(既写 .txt 也写 .odp)。

    2026-08-30 的三次返工都源于没按段落配对:
      1. 只认 `base64 -d ... > 'path'` 一种形态  -> 漏报约三分之一
      2. 放宽成"取最后一个办公路径"           -> 把源文件当成产物,误报"打不开 zip"
      3. 把命令里全部 blob 拼在一起           -> 多产物命令拼出垃圾,再次误报
    现在按 `base64 -d ... > 'PATH'` 的出现位置切段,每段只吃它前面那批 blob。
    """
    out = []
    last = 0
    for m in re.finditer(r"base64\s+-d\s+[^>]*>\s*['\"]([^'\"]+)['\"]", cmd):
        seg = cmd[last:m.start()]
        blobs = RE_B64.findall(seg)
        out.append((m.group(1), "".join(blobs)))
        last = m.end()
    return out


def audit_set(root):
    rows, counts = [], collections.Counter()
    for f in sorted(glob.glob(os.path.join(root, "examples", "*", "*.json"))):
        j = json.load(open(f, encoding="utf-8"))
        dom = os.path.basename(os.path.dirname(f))
        tid = j.get("id", os.path.basename(f)[:-5])
        slug = j.get("ostg", {}).get("slug", "?")
        for c in j.get("config", []):
            if c.get("type") != "execute":
                continue
            cmd = c.get("parameters", {}).get("command")
            s = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            # 有转换步骤时 blob 是"源"不是"产物",静态判不了,交给运行期
            converts = bool(re.search(r"\bsoffice\b|\blibreoffice\b|--convert-to", s))
            for path, b64 in pair_blobs_to_paths(s):
                ext = path.rsplit(".", 1)[-1].lower()
                if ext not in ODF and ext not in OOXML:
                    continue
                if converts:
                    counts["%s:含转换步骤,静态无法判定" % ext] += 1
                    continue
                rec = {"domain": dom, "id": tid, "slug": slug,
                       "path": path, "ext": ext}
                if not b64:
                    rec["verdict"] = "该段无 base64"
                else:
                    try:
                        raw = base64.b64decode(b64 + "=" * (-len(b64) % 4))
                        z = zipfile.ZipFile(io.BytesIO(raw))
                        names = z.namelist()
                    except Exception as e:
                        rec["verdict"] = "打不开 zip: %s" % e
                    else:
                        if ext in ODF:
                            actual = (z.read("mimetype").decode()
                                      if "mimetype" in names else "(无 mimetype)")
                            rec["actual"] = actual
                            rec["expected"] = ODF[ext]
                            rec["verdict"] = "OK" if actual == ODF[ext] else "类型不符"
                        else:
                            need = OOXML[ext]
                            rec["expected"] = need
                            rec["actual"] = ",".join(names[:4])
                            rec["verdict"] = "OK" if need in names else "缺必需成员"
                counts["%s:%s" % (ext, rec["verdict"])] += 1
                rows.append(rec)
    return rows, counts


def main(argv):
    bad_total = 0
    out = {}
    for root in argv:
        rows, counts = audit_set(root)
        name = os.path.basename(root.rstrip("/"))
        bad = [r for r in rows if r["verdict"] != "OK"]
        bad_total += len(bad)
        out[name] = bad
        print("=== %s ===" % name)
        print("  内嵌办公文件 %d 个" % len(rows))
        for k, v in sorted(counts.items()):
            print("   %-32s %4d" % (k, v))
        print("  ⚠ 不合格 %d 个" % len(bad))
        for r in bad[:25]:
            print("     %-14s %-38s %-26s %s"
                  % (r["domain"], r["slug"][:38], os.path.basename(r["path"]),
                     r.get("actual", r["verdict"])))
        if len(bad) > 25:
            print("     ... 其余 %d 条见 JSON 输出" % (len(bad) - 25))
        print()
    dest = os.environ.get("FIXTURE_AUDIT_OUT")
    if dest:
        json.dump(out, open(dest, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("缺陷清单已写入", dest)
    return 1 if bad_total else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
