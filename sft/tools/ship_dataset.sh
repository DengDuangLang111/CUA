#!/bin/bash
# ship_dataset.sh — the standing dataset shipper (WSL -> Tillicum).
#
#     bash ostg/sft/tools/ship_dataset.sh OUT_DIR NAME
#
# OUT_DIR: a pipeline output dir holding train_swift.jsonl + images/
# NAME:    the dataset directory name under /gpfs/scrubbed/jy050706/sft/data/
#
# Steps, fixed: absolutize image paths to the Tillicum destination, tar-stream
# images + jsonl over the ControlMaster, then verify line and file counts on
# the far side. HARD FAIL on any mismatch. Born 2026-08-16 (arm B); before
# this the ship was untooled hand-tar (arm A) — pipeline rule applies.
set -e
[ $# -eq 2 ] || { echo "usage: $0 OUT_DIR NAME"; exit 2; }
OUT_DIR=$1; NAME=$2
DEST=/gpfs/scrubbed/jy050706/sft/data/$NAME
SSHT="ssh -n -S $HOME/.ssh/cm/qwen36-tillicum-login -o ControlMaster=no -o BatchMode=yes jy050706@tillicum-login02.hyak.uw.edu"
SSHT_IN="ssh -S $HOME/.ssh/cm/qwen36-tillicum-login -o ControlMaster=no -o BatchMode=yes jy050706@tillicum-login02.hyak.uw.edu"

sed "s|\"images/|\"$DEST/images/|g" "$OUT_DIR/train_swift.jsonl" > "$OUT_DIR/train_swift_abs.jsonl"
LINES=$(wc -l < "$OUT_DIR/train_swift_abs.jsonl")
IMGS=$(find "$OUT_DIR/images" -type f | wc -l)
echo "shipping $NAME: $LINES samples, $IMGS images"

$SSHT "mkdir -p $DEST"
tar -C "$OUT_DIR" -cf - images train_swift_abs.jsonl | $SSHT_IN "tar -C $DEST -xf -"
$SSHT "mv $DEST/train_swift_abs.jsonl $DEST/train_swift.jsonl"

R_LINES=$($SSHT "wc -l < $DEST/train_swift.jsonl")
R_IMGS=$($SSHT "find $DEST/images -type f | wc -l")
echo "remote: $R_LINES samples, $R_IMGS images"
[ "$LINES" = "$R_LINES" ] && [ "$IMGS" = "$R_IMGS" ] || { echo "SHIP FAIL: count mismatch"; exit 1; }
$SSHT "head -1 $DEST/train_swift.jsonl | grep -o '$DEST/images/[^\"]*' | head -1 | xargs -r test -f" \
  && echo "SHIP OK: $DEST ($LINES samples, $IMGS images, spot-check image exists)"
