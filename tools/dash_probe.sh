#!/bin/bash
# dash_probe.sh — one-command end-to-end health check for the dashboard.
# Run from the Mac. Every layer that has ever silently failed gets a line:
#   origin head | data on origin vs branch-CDN | served shell | traj sample
#   | WSL daemons. Exit code 0 always; read the table, not $?.
SITE=${SITE:-https://cua-dashboard-theta.vercel.app}
REPO=DengDuangLang111/CUA
API=https://api.github.com/repos/$REPO

echo "== origin head"
HEAD=$(curl -sf --max-time 10 $API/commits/main \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['sha'],d['commit']['committer']['date'])" 2>/dev/null)
SHA=${HEAD%% *}
echo "   ${HEAD:-API UNREACHABLE}"

echo "== data freshness (updated field)"
for f in status.json sft.json; do
  P=$(curl -sf --max-time 10 "https://raw.githubusercontent.com/$REPO/$SHA/dashboard/$f" 2>/dev/null \
      | python3 -c "import json,sys;print(json.load(sys.stdin).get('updated'))" 2>/dev/null)
  B=$(curl -sf --max-time 10 "https://raw.githubusercontent.com/$REPO/main/dashboard/$f" 2>/dev/null \
      | python3 -c "import json,sys;print(json.load(sys.stdin).get('updated'))" 2>/dev/null)
  FLAG=""; [ -n "$P" ] && [ "$P" != "$B" ] && FLAG="   <-- branch CDN is stale (page is sha-pinned, unaffected)"
  echo "   $f  sha-pinned: ${P:-?}   branch-cdn: ${B:-?}$FLAG"
done

echo "== served shell"
LIVE_STAMP=$(curl -sf --max-time 10 "$SITE/" | grep -oE 'SHELL_STAMP = "[a-z0-9-]+"' | head -1)
REPO_STAMP=$(curl -sf --max-time 10 "https://raw.githubusercontent.com/$REPO/$SHA/dashboard/index.html" \
  | grep -oE 'SHELL_STAMP = "[a-z0-9-]+"' | head -1)
echo "   live: ${LIVE_STAMP:-?}   repo: ${REPO_STAMP:-?}"
[ -n "$LIVE_STAMP" ] && [ "$LIVE_STAMP" != "$REPO_STAMP" ] && \
  echo "   <-- SHELL OUT OF DATE: a deploy is due (coalesced push? next push self-heals via ignoreCommand)"

echo "== traj sample"
curl -s -o /dev/null --max-time 10 \
  -w "   eval50-richrich index: HTTP %{http_code}\n" \
  "$SITE/traj/qwen35-4b-sft/eval50-richrich-20260815/index.html"

echo "== WSL daemons"
ssh -o ConnectTimeout=8 osworld-windows 'wsl -e bash -lc "echo \"   status_daemon: $(pgrep -cf dash_status_daemon) sft_daemon: $(pgrep -cf sft_dash_daemon)\""' 2>/dev/null \
  || echo "   ssh unreachable"
