#!/bin/bash
# run_eval50_stock.sh <arm> -- run one eval-50 arm on the OSWorld-Verified
# DEFAULT (stock) chat template.
#
# 2026-08-18: all evaluation moved to the stock template. Not because stock
# won a comparison -- because there was never a comparison to win. This
# agent never sends a reasoning_content field; client.py:46-51 merges the
# reasoning INLINE into the assistant content string, and history.py:90-94
# prepends an empty <think></think> when there is none. The keepthink patch
# gates on `{% if reasoning_content %}`, which is therefore never true, so
# the two templates render byte-identically. --preserve_thinking is inert for
# the same reason (neither template references it). Every arm from here on
# differs from every other arm only in its weights.
#
# basestock is kept in the table but is NOT chained: base/keepthink already
# ran (39.81%) and, the axis being degenerate, base/stock would be the same
# configuration a second time. Run it only as a deliberate noise estimate.
#
# The arm waits for its predecessor to release the 3 VMs, brings up its own
# serve, then runs. It does NOT gate on a DONE marker in a log: markers have
# fired early before (a watchdog killed a run at 0/50 and the driver still
# printed DONE), and a marker cannot tell a finished run from a killed one.
#
# It gates on PROCESSES, and on two of them, because either alone is
# ambiguous. The predecessor's DRIVER exists from launch until its arm is
# finished; the predecessor's RUNNER exists only while tasks are executing.
# Waiting on the runner alone reads "hasn't started yet" as "already done" --
# which is exactly what happened on the first launch of this script: all three
# arms were started at once, and the two later ones sailed straight through
# their gate and submitted serves that then sat idle. Waiting on the driver
# alone misses a predecessor that was started by hand without a driver (the
# lean/stock rerun). Wait while EITHER is alive.
#
# Canonical location: WSL /mnt/d/research/osworld-verified-control/
set -u
ARM="${1:?usage: run_eval50_stock.sh <arm>}"
XARGS=""   # per-arm extra runner flags (e.g. "--image_max 3 --fold_size 1")
METAF="verified_eval50_nonproxy.json"  # per-arm task set. The default is the
           # frozen 50 every arm has been scored on. Arms ending in "50b" use
           # verified_eval50b_nonproxy.json instead: the OTHER half of the
           # frozen 100, held out since 2026-08-15, never run by any model and
           # never looked at by any decision -- the pre-registered out-of-
           # sample paper. Same scoring convention either way: sum over the
           # task set, missing = 0, divide by 50.
DIALECT="" # per-arm tool-call dialect; "json" for models TRAINED on the json
           # corpus serialization (all VL SFT arms). Gates BOTH the system
           # prompt and the parser (prompts.py / actions.py). vlbase stays XML.

#         serve sbatch          slurm job   port  served-model-name    result group     waits for
case "$ARM" in
  basestock) SB=4b-base-stock; JOB=eval4bbo;  RP=8023; MN=q35-4b-stock;     GRP=qwen35-4b-base; PREV=leanstock; PJOB=eval4bls  ;;
  lorastock) SB=4b-lora-stock; JOB=eval4blos; RP=8024; MN=q38Bs-lora-stock; GRP=qwen35-4b-sft;  PREV=leanstock; PJOB=eval4bls  ;;
  r5lora)    SB=4b-r5-lora-stock; JOB=eval4br5l; RP=8027; MN=q38Bhqs2t-lora-stock; GRP=qwen35-4b-sft; PREV=lorastock; PJOB=eval4blos ;;
  bsstock)   SB=4b-bs-stock;   JOB=eval4bbss; RP=8025; MN=q38Bs-gb64-stock; GRP=qwen35-4b-sft;  PREV=lorastock; PJOB=eval4blos ;;
  # ---- post-recovery chain, all under OSTG_TYPE_NO_SPLIT=1 (set by launcher) ----
  # port 8030 deliberately skipped: local 18030 was the Klone kD tunnel port,
  # and a stale forward there would silently score one arm against another model.
  kE)   SB=4b-lr3e6-stock;  JOB=eval4blr3; RP=8028; MN=q38Bhqs2t-lr3e6-stock;  GRP=qwen35-4b-sft; PREV=bsstock; PJOB=eval4bbss ;;
  kD15) SB=4b-gb64e15-stock; JOB=eval4bd15; RP=8029; MN=q38Bhqs2t-gb64e15-stock; GRP=qwen35-4b-sft; PREV=kE;   PJOB=eval4blr3 ;;
  # vlbase: stock Qwen3-VL-4B-Thinking, the reference for all VL SFT arms.
  # No training dependency -- runs the moment t38 releases the VMs.
  vlbase) SB=vl-base-stock; JOB=eval4bvlb; RP=8034; MN=q3vl-4b-base-stock; GRP=qwen3vl-4b-base; PREV=t38;  PJOB=eval38 ;;
  # gb128: VL x vl3pic at global-batch 128 (3-image trained -> 3-image eval)
  gb128) SB=vl3gb128-stock; JOB=eval4bg28; RP=8037; MN=vl3pic-gb128-stock; GRP=qwen3vl-4b-sft; PREV=vlsft; PJOB=eval4bvls; XARGS="--image_max 3 --fold_size 1"; DIALECT=json ;;
  nocap) SB=4b-nocap-stock; JOB=eval4bnc; RP=8033; MN=q38Bhqs2t-lr3e6nocap-stock; GRP=qwen35-4b-sft; PREV=kEh3; PJOB=eval4blr3 ;;
  kG)   SB=4b-loranp-stock; JOB=eval4bnp;  RP=8031; MN=q38Bhqs2t-loranp-stock; GRP=qwen35-4b-sft; PREV=gb128;  PJOB=eval4bg28 ;;
  # VL tail (user 08-19): vl20 gated on its training. vl3b/vl20g were PULLED
  # by user order 08-19 late (eval is the bottleneck; the VL-backbone-negative
  # conclusion already stands on vlsft 44.00 vs kE 57.81) -- both trainings
  # are COMPLETE on disk (vl3pic-base ckpt-300, vl20pic-gb128 ckpt-150),
  # kept UNEVALUATED for a later slot; rows removable from git history.
  vl20)  SB=vl20-stock;  JOB=eval4bv20; RP=8038; MN=vl20pic-lr1e5-stock; GRP=qwen3vl-4b-sft; PREV=kG;    PJOB=eval4bnp; DIALECT=json ;;
  # kEh1: kE weights at a ONE-image eval window -- completes the eval-window
  # curve 20/3/1. fold_size MUST be 1 (fold 10 alternates into total blindness).
  kEh1)  SB=4b-lr3e6-stock; JOB=eval4blr3; RP=8028; MN=q38Bhqs2t-lr3e6-stock; GRP=qwen35-4b-sft; PREV=vl20; PJOB=eval4bv20; XARGS="--image_max 1 --fold_size 1" ;;
  # 1-image floor for the untrained 3.5 backbone (user 08-19, the 1pic-vs-3pic
  # training-window decision): basestock weights, eval window 1.
  # fold_size MUST be 1 (fold 10 alternates into total blindness, see kEh1).
  # vlbaseh1 (the VL twin) was PULLED in the user's VL eval-shed 08-19 late.
  baseh1)   SB=4b-base-stock; JOB=eval4bbo;  RP=8023; MN=q35-4b-stock;       GRP=qwen35-4b-base;  PREV=kEh1;   PJOB=eval4blr3; XARGS="--image_max 1 --fold_size 1" ;;
  # nocapt0: the champion weights rerun GREEDY (user 08-19: temp0 topk-1 topp1).
  # Runner has no --top_k flag and the request never carried top_k (the 20 in the
  # sampling block is vLLM adopting the model generation_config) -- moot anyway:
  # at temperature 0 vLLM decodes greedy and ignores top_k/top_p entirely.
  # argparse last-wins lets XARGS override the protocol -- checked, no dedup.
  nocapt0) SB=4b-nocap-stock; JOB=eval4bnc; RP=8033; MN=q38Bhqs2t-lr3e6nocap-stock; GRP=qwen35-4b-sft; PREV=baseh1; PJOB=eval4bbo; XARGS="--temperature 0.0 --top_p 1.0" ;;
  # ---- the fresh furnaces (2026-08-19 late), ordered by user priority.
  # Each is gated on its training in tillicum_chain.sh. nocapnp reads against
  # nocap 59.81 (prose axis at full FT); img1 at its MATCHED 1-image window
  # (fold MUST be 1).
  # nocaplean was CANCELLED at 27/306 (real-payload rendering proved eval
  # history keeps ALL think, so preserve_thinking=false trains the worst-
  # direction skew). vl20nc was PULLED with vl3b/vl20g in the user's VL
  # eval-shed (its training 249500 continues; weights keep-unevaluated;
  # serve-chain-vl20nocap-stock.sbatch stays on disk for a later slot).
  # nocapnp2: the 2-epoch checkpoint rescued from the run that died at 73%.
  # Weights exist, so it fills the window while the 3ep rerun queues. Its
  # serve pins the v0 directory (the rerun writes v1 with its own ckpt-204).
  # Two variables vs nocap 59.81 (prose AND epochs) -- reads "did it break",
  # not "by how much".
  nocapnp2)  SB=4b-nocapnp2-stock;  JOB=eval4bnn2; RP=8048; MN=q38Bhqs2t-nocapnp-e2-stock; GRP=qwen35-4b-sft; PREV=vlnocapnp; PJOB=eval4bvnp ;;
  # nocapnp: PULLED from the chain 2026-08-20 by user order after its training
  # failed three times. Attempt 1 (249538, 4x2xaccum8) died at 73% on a cuDNN
  # attention-workspace allocation; attempts 2 and 3 (249689, 16 ranks) died at
  # step 245/303 after exactly 2h45m with cudaErrorContained "Invalid access of
  # peer GPU memory over nvlink" -- the same step and the same nodes g[014,021]
  # as np1e6's first attempt. The row is kept so the arm can be re-queued once
  # a run finishes: it needs an endpoint at epoch >= 2.99, and today the best
  # on disk is v1 checkpoint-238 @ 2.36. If retried, exclude g021 (all three
  # jobs that touched it failed) and probably g014.
  # nocapnp: back on the chain 2026-08-20 after the fourth training attempt
  # finally reached 3 epochs (v2 checkpoint-303, lr annealed to 0, token_acc
  # 0.9027 against the champion's 0.8938). Runs the FULL 100 by user order.
  # pick_ckpt spans v0/v1/v2 by epoch, so it resolves to the 3.00 endpoint and
  # cannot pick up either of the two dead attempts' partial checkpoints.
  nocapnp)   SB=4b-nocapnp-stock;   JOB=eval4bnnp; RP=8041; MN=q38Bhqs2t-nocapnp-stock;   GRP=qwen35-4b-sft; PREV=np1e6; PJOB=eval4bnp1; METAF="verified_eval100_nonproxy.json" ;;
  img1)      SB=4b-img1-stock;      JOB=eval4bim1; RP=8043; MN=q38Bhqs2t-img1-stock;      GRP=qwen35-4b-sft; PREV=nocapt0;   PJOB=eval4bnc;  XARGS="--image_max 1 --fold_size 1" ;;
  # vlnocapnp: VL x (nocap + no-prose) at lr3e-6 -- the VL line re-enters with
  # the no-prose recipe (user 08-19 night, appended after img1). Reads against
  # vlsft 44.00 (cap+prose joint change). Gated on training 249567.
  vlnocapnp) SB=vlnocapnp-stock;     JOB=eval4bvnp; RP=8045; MN=vlnocapnp-lr3e6-stock;     GRP=qwen3vl-4b-sft; PREV=img1;      PJOB=eval4bim1; DIALECT=json ;;
  # LR left flank (user 08-19 night, revised): a single arm at lr 1e-6, 3ep
  # (cumulative dose 1.5e-4 vs the champion's 4.5e-4 -- a 3x cut, the first
  # sample ever taken left of the peak). The 2e-6 and 1e-6x5ep variants were
  # withdrawn: the 2e-6 pilot's loss curve sat 2.0% from 3e-6 at matched
  # epochs, far inside eval-50's 5-6pp noise floor, i.e. underpowered.
  # ---- eval100 final (user order 2026-08-20): the champion and the untrained
  # base on the HELD-OUT half of the frozen 100. This is the pre-registered
  # out-of-sample test: those 50 tasks were frozen 2026-08-15 and have never
  # been run by any model, so no selection pressure has touched them. Both
  # arms reuse their existing serves and weights -- no training needed.
  # Reading: the primary comparison is champion vs base ON THESE 50, paired by
  # task. Expect the margin to shrink versus the seen 50 (59.81 - 39.81 = 20pp);
  # a margin that survives here is the one that generalises.
  nocap50b)  SB=4b-nocap-stock;      JOB=eval4bnc;  RP=8033; MN=q38Bhqs2t-lr3e6nocap-stock; GRP=qwen35-4b-sft;  PREV=nocapnp2; PJOB=eval4bnn2; METAF="verified_eval50b_nonproxy.json" ;;  # 08-20: moved AHEAD of nocapnp -- its weights already exist while nocapnp was still training, and the eval VMs were idling behind that training gate
  base50b)   SB=4b-base-stock;       JOB=eval4bbo;  RP=8023; MN=q35-4b-stock;               GRP=qwen35-4b-base; PREV=nocap50b; PJOB=eval4bnc;  METAF="verified_eval50b_nonproxy.json" ;;  # 08-20 user order: immediately after nocap50b, so the eval100 paired comparison completes back to back instead of straddling another arm
  # t3850b: the 27B teacher on the held-out half, completing the eval100 final
  # as the three-way (champion / base / teacher) pre-registered on the seen
  # half. Same serve as t38 (1 GPU, TP1), same sampling protocol.
  t3850b)    SB=38-i;                JOB=eval38;    RP=8000; MN=qwen38-27b-local;           GRP=qwen38-27b-local; PREV=base50b; PJOB=eval4bbo; METAF="verified_eval50b_nonproxy.json" ;;
  # np1e6 runs the FULL 100 in one pass (user order 08-20) rather than the seen
  # half: it is the first arm whose weights postdate the eval100 decision, so
  # there is no reason to score it on the selection panel alone. ~4h, not ~2h.
  np1e6)     SB=4b-np1e6-stock;      JOB=eval4bnp1; RP=8047; MN=q38Bhqs2t-np1e6-stock;     GRP=qwen35-4b-sft;  PREV=t3850b;    PJOB=eval38; METAF="verified_eval100_nonproxy.json" ;;
  # nocapnp238: the furthest checkpoint the no-prose full-FT run ever reached
  # (v1 checkpoint-238, epoch 2.356, anneal 87% complete) over the FULL 100.
  # It is the closest available stand-in for the 3-epoch endpoint while the
  # resume queues, and it stays useful afterwards as the 2.36-vs-3.00 pair.
  # Serve pins the exact v1 path; the resume writes v2 into the same dir.
  nocapnp238) SB=4b-nocapnp238-stock; JOB=eval4bn238; RP=8049; MN=q38Bhqs2t-nocapnp-e238-stock; GRP=qwen35-4b-sft; PREV=np1e6; PJOB=eval4bnp1; METAF="verified_eval100_nonproxy.json" ;;  # tail: scancel eval4bn238 after
  # vlsft: Qwen3-VL-4B-Thinking x r5vl corpus, lr3e-6 3ep (chain gates on training done)
  vlsft) SB=vl-r5vl-stock; JOB=eval4bvls; RP=8035; MN=q3vl-r5vl-lr3e6-stock; GRP=qwen3vl-4b-sft; PREV=nocap; PJOB=eval4bnc; DIALECT=json ;;  # rerun right after nocap; first attempt burned on the XML/json dialect mismatch
  # img3: kE's exact recipe with the training screenshot window 20->3; STANDARD 20-image
  # eval protocol by user order (the deliberate train/eval-skew cell of the 2x2)
  img3)  SB=4b-img3-stock; JOB=eval4bim3; RP=8036; MN=q38Bhqs2t-img3-stock; GRP=qwen35-4b-sft; PREV=vlbase; PJOB=eval4bvlb ;;
  # the other two cells of the history-window 2x2 (user 2026-08-19): same weights,
  # eval-side window 3. img3h3 reuses img3's live serve (same JOB); kEh3 resubmits kE's.
  img3h3) SB=4b-img3-stock; JOB=eval4bim3; RP=8036; MN=q38Bhqs2t-img3-stock; GRP=qwen35-4b-sft; PREV=vlsft; PJOB=eval4bvls; XARGS="--image_max 3 --fold_size 1" ;;
  kEh3)  SB=4b-lr3e6-stock; JOB=eval4blr3; RP=8028; MN=q38Bhqs2t-lr3e6-stock; GRP=qwen35-4b-sft; PREV=img3h3; PJOB=eval4bim3; XARGS="--image_max 3 --fold_size 1" ;;
  kF)   SB=4b-loralean-stock; JOB=eval4bll; RP=8032; MN=q38Bhqs2t-loralean-stock; GRP=qwen35-4b-sft; PREV=kEh3; PJOB=eval4blr3 ;;
  # teacher ceiling: Qwen3.8-27B on the SAME frozen 50, same sampling protocol
  # (t=1.0 top_p .95 max_tokens 81920), no-split semantics like every k-era arm.
  t38)  SB=38-i;       JOB=eval38;   RP=8000; MN=qwen38-27b-local; GRP=qwen38-27b-local; PREV=kD15; PJOB=eval4bd15 ;;
  *) echo "unknown arm: $ARM" >&2; exit 2 ;;
esac

CTL=/mnt/d/research/osworld-verified-control
LOG=$CTL/logs/eval50_$ARM.log
exec >>$LOG 2>&1
cd /mnt/d/research/OSWorld; set -a; . ./.env; set +a
SSHT="ssh -n -S $HOME/.ssh/cm/qwen36-tillicum-login -o ControlMaster=no -o BatchMode=yes jy050706@tillicum-login02.hyak.uw.edu"
PORT=$((RP + 10000))
C=/mnt/d/research/OSWorld/evaluation_examples
META=$C/$METAF
RES=/mnt/d/research/OSWorld/results_generated

# Reuse an existing result dir for this arm so a restart resumes instead of
# starting a second copy under a new date.
R=$(ls -dt $RES/$GRP/eval50-$ARM-* 2>/dev/null | head -1)
[ -n "$R" ] || R=$RES/$GRP/eval50-$ARM-$(date +%Y%m%d)
mkdir -p "$R"
TAG=$(basename "$R")
echo "[$(date '+%F %T')] === $ARM -> $R"

up(){ [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $OPENAI_API_KEY" http://127.0.0.1:$PORT/v1/models)" = "200" ]; }

# Wait for the endpoint, re-submitting the serve if its Slurm job has gone.
#
# A fixed 1-2h wait was enough for a serve that only ever died by crashing.
# It is not enough for a cluster maintenance reservation: August18_Maintenance
# holds all 24 GPU nodes for a full 24 hours, so a serve that expires at 08:33
# cannot be replaced until 09:00 the NEXT day. With the old wait the driver
# would FATAL a couple of hours in and the whole chain would silently stop.
# Per-task results are already on disk, so surviving the gap means the run
# resumes by itself instead of needing a human at 09:00 on a Tuesday.
wait_up(){                       # $1 = how many minutes to keep trying
  local mins=${1:-90} i
  for i in $(seq 1 $((mins * 2))); do
    up && return 0
    if [ $((i % 20)) -eq 0 ]; then   # every 10 min, make sure a serve exists
      if [ -z "$($SSHT "squeue -u jy050706 -h -n $JOB -o %i" 2>/dev/null | tr -dc 0-9)" ]; then
        echo "[$(date '+%F %T')] no $JOB in the queue -- resubmitting"
        $SSHT "sbatch --parsable /gpfs/scrubbed/jy050706/qwen-serve/serve-chain-$SB.sbatch" >/dev/null 2>&1
      fi
    fi
    sleep 30
  done
  up
}
scored(){ find "$1" -name result.txt 2>/dev/null | wc -l; }

stop_eval(){
  pkill -f "run_multienv_qwen.*$TAG" 2>/dev/null
  for i in $(seq 1 30); do pgrep -f "run_multienv_qwen.*$TAG" >/dev/null || break; sleep 2; done
  pkill -9 -f "run_multienv_qwen.*$TAG" 2>/dev/null
}

# ---- wait for the predecessor to let go of the VMs ----
busy(){ pgrep -f "run_eval50_stock.sh $PREV" >/dev/null ||
        pgrep -f "run_multienv_qwen.*eval50-$PREV" >/dev/null; }
for i in $(seq 1 960); do busy || break; sleep 30; done
busy && { echo "[$(date '+%F %T')] FATAL: $PREV still busy after 8h"; exit 1; }
PR=$(ls -dt $RES/*/eval50-$PREV-* 2>/dev/null | head -1)
echo "[$(date '+%F %T')] $PREV released the VMs at $(scored "${PR:-/nonexistent}")/50"
sleep 20

# ---- serve ----
# Release the predecessor's serve first. The interactive QOS allows 2 jobs;
# leaving a finished arm's serve up means this arm's serve pends behind it,
# and an idle vLLM burns an H200 doing nothing.
$SSHT "scancel -n $PJOB -u jy050706" 2>/dev/null
sleep 5
HAVE=$($SSHT "squeue -u jy050706 -h -n $JOB -o %i" 2>/dev/null | tr -dc 0-9)
if [ -z "$HAVE" ]; then
  JID=$($SSHT "sbatch --parsable /gpfs/scrubbed/jy050706/qwen-serve/serve-chain-$SB.sbatch" 2>/dev/null | tr -dc 0-9)
  echo "[$(date '+%F %T')] submitted serve $JID ($SB)"
else
  echo "[$(date '+%F %T')] reusing live serve $HAVE ($JOB)"
fi
JOB=$JOB LPORT=$PORT RPORT=$RP setsid nohup $CTL/tunnel_qwen36_auto.sh > $HOME/tunnel_$JOB.log 2>&1 < /dev/null &
# 2026-08-20: initial wait raised 90 min -> 12 h. A 90-minute patience was
# sized for a serve that only ever waited on node health. It is far too short
# when the CLUSTER is saturated: on this night every usable node sat 8/8
# allocated, our own 1-GPU serve pended with a 6-hour Slurm estimate, and the
# driver would have FATALed at 90 minutes. Worse, the chain reads a dead
# driver as "arm finished" and immediately starts the next arm, which submits
# its own serve into the same full cluster -- so one saturated night would
# have marched through every remaining arm in 90-minute increments and
# evaluated nothing. Patience here costs nothing: the arm is idle either way.
wait_up 720 || { echo "[$(date '+%F %T')] FATAL: endpoint $PORT never came up in 12h"; exit 1; }

# Record what the server ACTUALLY loaded, not what any script intended to load.
# vLLM's /v1/models reports `root` = the real weight path. A week of results
# were mislabelled because nothing ever asked this question (see CUA/OPS.md).
ROOT=$(curl -s -H "Authorization: Bearer $OPENAI_API_KEY" http://127.0.0.1:$PORT/v1/models \
       | python3 -c "import json,sys;print(json.load(sys.stdin)['data'][0].get('root',''))")
echo "[$(date '+%F %T')] endpoint UP; vLLM reports root=$ROOT"
python3 - "$R/MODEL_BOUNDARY.json" "$ARM" "$MN" "$ROOT" "${OSTG_TYPE_NO_SPLIT:-0}" "$XARGS" "$DIALECT" "$METAF" <<'PY'
import json, sys
path, arm, served, root, no_split, xargs, dialect, tasks_file = sys.argv[1:9]
json.dump({
    "arm": arm, "served_model_name": served,
    "weights_reported_by_vllm": root,
    "chat_template": "model built-in (OSWorld-Verified default); no --chat-template override",
    "preserve_thinking": "client sends history think (upstream-identical); template decides",
    "precision": "BF16 weights, fp8 kv-cache",
    "sampling": {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0,
                 "presence_penalty": 0.0, "repetition_penalty": 1.0},
    "sampling_note": ("chain protocol values; any --temperature/--top_p in "
                      "runner_extra_args OVERRIDE them (argparse last-wins), "
                      "e.g. nocapt0 runs greedy t=0"),
    "max_steps": 50, "sleep_after_execution": 3, "num_envs": 3,
    "runner_extra_args": xargs or "(none: image_max 20, fold_size 10 defaults)",
    "tool_call_dialect": dialect or "xml (upstream block dialect)",
    "tasks": tasks_file,
    "harness": ("OSTG_NO_RECORD=1 (no guest mp4, screenshots unaffected); "
                "OSTG_TYPE_NO_SPLIT=%s (1 = multi-line type sent as ONE typewrite, "
                "0 = upstream per-line split; semantics change landed 2026-08-18, "
                "arms through kD ran under split)" % no_split),
}, open(path, "w"), indent=1, ensure_ascii=False)
PY

# ---- run ----
T=$(python3 -c "import json;print(sum(len(v) for v in json.load(open('$META')).values()))")
for TRY in 1 2 3 4 5; do
  N=$(scored "$R")
  [ "$N" -ge "$T" ] && { echo "[$(date '+%F %T')] complete $N/$T"; break; }
  # 30h, so a 24h maintenance window is survivable with margin.
  up || { echo "[$(date '+%F %T')] endpoint down at $N/$T, waiting up to 30h"; wait_up 1800; }
  up || { echo "[$(date '+%F %T')] FATAL: endpoint never came back in 30h"; exit 1; }
  echo "[$(date '+%F %T')] pass $TRY at $N/$T"
  # OSTG_NO_RECORD=1: the guest-side mp4s cap near 280-320s regardless of
  # task length and nothing reads them (build.py's mp4 fallback has fired
  # 0 times across 16 builds); on a sick guest end_recording adds 15s of
  # retries to a task that is already failing. Screenshots are unaffected.
  OSWORLD_OPENAI_TIMEOUT=600 OSTG_NO_RECORD=1 OSTG_TYPE_NO_SPLIT=${OSTG_TYPE_NO_SPLIT:-0} OSTG_PARAM_DIALECT=$DIALECT \
  .venv/bin/python scripts/python/run_multienv_qwen.py \
    --provider_name docker --path_to_vm /mnt/d/research/OSWorld/docker_vm_data/Ubuntu.qcow2 \
    --headless --observation_type screenshot --action_space pyautogui \
    --model $MN --base_url http://127.0.0.1:$PORT/v1 \
    --temperature 1.0 --top_p 0.95 --max_tokens 81920 --max_steps 50 \
    --sleep_after_execution 3 --enable_thinking --preserve_thinking --num_envs 3 --simple_path \
    --screen_width 1920 --screen_height 1080 \
    --test_config_base_dir $C --test_all_meta_path $META --result_dir "$R" $XARGS
  stop_eval
done
N=$(scored "$R")
# The histogram below sums to however many tasks finished, so a 47/50 run prints
# something that looks perfectly normal -- that is how gb64keep's 3 missing tasks
# (2.67 points under the 0-filled convention) went unnoticed until someone
# counted result.txt by hand. Name the gap instead.
if [ "$N" -lt "$T" ]; then
  MISS=$(find "$R" -mindepth 2 -maxdepth 2 -type d '!' -exec test -e '{}/result.txt' ';' -print 2>/dev/null | sed "s|$R/||" | tr '\n' ' ')
  echo "[$(date '+%F %T')] INCOMPLETE $N/$T -- crashed: ${MISS:-none} (any remainder never started)"
fi
# awk per file, NOT cat: a result.txt without a trailing newline (the orphan-fix
# used to write bare "0.0") makes cat glue two values into one ("0.0"+"1"->"0.01")
echo "[$(date '+%F %T')] === $ARM RESULT $N/$T: $(find "$R" -name result.txt -exec awk '{print $1; exit}' {} \; 2>/dev/null | sort | uniq -c | tr '\n' ' ')"
