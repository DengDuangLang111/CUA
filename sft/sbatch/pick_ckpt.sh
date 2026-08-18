#!/bin/bash
# pick_ckpt.sh <run-dir-glob> [policy] -- resolve a training run to one checkpoint.
#
#   policy  endpoint   (default) the largest step
#           epoch:N    the checkpoint whose recorded epoch is closest to N
#           step:N     exactly checkpoint-N
#
# Prints the checkpoint path on stdout and nothing else, so callers can do
#   MODEL=$(pick_ckpt.sh "$B/out/<run>/v*") || exit 1
# and writes a one-line audit record to stderr, which in a Slurm job lands in
# the job's .out file:
#   [pick_ckpt] <run> policy=endpoint -> checkpoint-264 epoch=3.00 (9 available)
#
# Why this exists: the previous one-liner was
#   ls -d <glob>/checkpoint-* | sort -t- -k2 -n | tail -1
# `-t-` splits the whole absolute path on '-', so field 2 was a non-numeric
# fragment like "gb64/v0"; -n scored every line 0, GNU sort fell back to
# comparing whole lines as text, and checkpoint-90 sorted after checkpoint-264.
# Three arms were served ~1-epoch weights for a week without anyone noticing,
# because nothing in the pipeline ever printed which step it had chosen.
#
# Step counts differ per run (264, 267, 135, 708 for the same 3 epochs), so
# nothing here is a constant: the epoch comes from each checkpoint's own
# trainer_state.json.
set -uo pipefail
GLOB="${1:?usage: pick_ckpt.sh <run-dir-glob> [endpoint|epoch:N|step:N]}"
POLICY="${2:-endpoint}"

mapfile -t CKPTS < <(ls -d $GLOB/checkpoint-* 2>/dev/null)
[ "${#CKPTS[@]}" -gt 0 ] || { echo "[pick_ckpt] FATAL: no checkpoint under $GLOB" >&2; exit 1; }

CHOSEN=$(python3 - "$POLICY" "${CKPTS[@]}" <<'PY'
import json, os, sys
policy, paths = sys.argv[1], sys.argv[2:]
rows = []
for p in paths:
    try:
        step = int(p.rsplit("checkpoint-", 1)[1])
    except (IndexError, ValueError):
        continue
    epoch = None
    try:
        with open(os.path.join(p, "trainer_state.json")) as f:
            epoch = float(json.load(f)["epoch"])
    except Exception:                                        # noqa: BLE001
        pass
    rows.append((step, epoch, p))
if not rows:
    sys.exit("no parsable checkpoint")
rows.sort()

if policy == "endpoint":
    pick = rows[-1]
elif policy.startswith("epoch:"):
    want = float(policy.split(":", 1)[1])
    known = [r for r in rows if r[1] is not None]
    if not known:
        sys.exit("epoch policy needs trainer_state.json; none readable")
    pick = min(known, key=lambda r: abs(r[1] - want))
elif policy.startswith("step:"):
    want = int(policy.split(":", 1)[1])
    hit = [r for r in rows if r[0] == want]
    if not hit:
        sys.exit("no checkpoint-%d among %s" % (want, [r[0] for r in rows]))
    pick = hit[0]
else:
    sys.exit("unknown policy %r" % policy)

step, epoch, path = pick
print("%s\t%d\t%s\t%d" % (path, step, "%.2f" % epoch if epoch is not None else "?", len(rows)))
PY
) || { echo "[pick_ckpt] FATAL: $GLOB policy=$POLICY: selection failed" >&2; exit 1; }

IFS=$'\t' read -r PATH_OUT STEP EPOCH N <<<"$CHOSEN"
echo "[pick_ckpt] $(basename "$(dirname "$PATH_OUT")") policy=$POLICY -> checkpoint-$STEP epoch=$EPOCH ($N available)" >&2
echo "$PATH_OUT"
