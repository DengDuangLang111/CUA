#!/bin/bash
# Live SFT half of the dashboard. Runs alongside dash_status_daemon.sh, which
# owns status.json + traj/v11*. This one owns sft.json + traj/sft/ and works in
# its OWN clone (cua-dash-sft, sparse-checked-out so the 683 MB of rollout
# screenshots the other daemon manages are never even present here). Two working
# trees, disjoint paths: neither can take the other's index.lock, and a raced
# push resolves as an ordinary rebase.
#
#   sft.json          every cycle if it changed (cheap: reads result.txt + traj.jsonl)
#   traj/sft/<arm>/   once per arm -- a tier-3 arm is frozen the moment its 9th
#                     result lands, unlike the live rollout, so there is no churn
REPO=$HOME/cua-dash-sft
CTL=/mnt/d/research/osworld-verified-control
P=/mnt/d/research/OSWorld/.venv/bin/python
BRANCH=main   # Vercel production branch; any other branch only makes Previews
export GIT_SSH_COMMAND="ssh -i ~/.ssh/id_ed25519_cua -o IdentitiesOnly=yes"
cd $REPO || exit 1
set +e
git config user.email "jy050706@uw.edu"; git config user.name "sft-dash-updater"
echo "[$(date '+%F %T')] sft dashboard daemon start"
while true; do
  # Always start the cycle from origin and regenerate: sft.json is derived data,
  # so resetting can never lose anything, and it means this daemon never has a
  # merge conflict to resolve.
  git rebase --abort 2>/dev/null; git merge --abort 2>/dev/null
  git checkout -q -- . 2>/dev/null
  git fetch -q origin $BRANCH 2>/dev/null && git reset -q --hard FETCH_HEAD

  # publish BEFORE status: sft.json records the per-arm traj link by testing for
  # the published index.html, so doing it the other way round would leave a new
  # arm's matrix cells unclickable for a whole cycle.
  # status FIRST (cheap, seconds): matrix freshness must never wait on viewer
  # rendering. publish next; then status AGAIN so a newly published arm's
  # traj links land the same cycle (the original publish-before-status
  # rationale, preserved at the cost of one extra cheap pass).
  $P $CTL/sft_dash.py status
  # PUSH THE DATA NOW (2026-08-16): computing status early is worthless if the
  # commit still waits behind publish -- a slow viewer-render cycle was still
  # holding sft.json hostage for 10+ minutes. Data ships the moment it exists;
  # publish and the link-fixup pass ship at cycle end as before.
  git add dashboard/sft.json
  if git commit -q -m "sft: refresh (data-first)"; then
    git pull --rebase -q origin $BRANCH >/dev/null 2>&1 || git rebase --abort >/dev/null 2>&1
    git push -q origin HEAD:$BRANCH && echo "[$(date '+%F %T')] data pushed"       || { git reset -q --soft HEAD~1; echo "[$(date '+%F %T')] data push raced"; }
  fi
  $P $CTL/sft_dash.py publish
  $P $CTL/sft_dash.py status

  # Stage unconditionally rather than on the exit codes. If a previous cycle
  # committed but lost the push race, the reset above dropped the commit and
  # left those files untracked -- publish will skip them (fingerprint matches)
  # and they would never be committed again.
  git add -A dashboard/traj/sft
  git add dashboard/sft.json
  if git commit -q -m "sft: refresh tier-3 panel"; then
    git pull --rebase -q origin $BRANCH >/dev/null 2>&1 || git rebase --abort >/dev/null 2>&1
    if git push -q origin HEAD:$BRANCH; then
      echo "[$(date '+%F %T')] pushed (arms=$(grep -c '\"key\"' dashboard/sft.json))"
    else
      echo "[$(date '+%F %T')] push raced, next cycle retries"
    fi
  fi
  sleep 75
done
