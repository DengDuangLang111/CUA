#!/bin/bash
# Classify the VM containers on one VM host; with --remove, delete the orphans (with their volumes) and the
# dangling anonymous volumes. Run on the host: ssh <route> bash -s [-- --remove] < list_orphans.sh
#
# A bridge's VM: QEMU started with the bridge's QMP socket (ARGUMENTS=-qmp unix:/tmp/qmp.sock); the eval
# harness's VMs (same image and disk) have no such argument and are never touched.
# In use: named in a live bridge's record /tmp/cuagym-vm-<pid> (bridges from 708a732 on), or, for bridges that
# keep no record, created after the oldest live bridge started.
# Orphan: exited or dead; or running with no live bridge at all; or older than every live bridge and unrecorded.
set -u
REMOVE=${1:-}
now=$(date +%s)
bridges=$(for p in $(pgrep -f worker_bridge.py); do ps -o args= -p "$p" | grep -q "worker_bridge.py" && echo "$p"; done)
recorded=$(for p in $bridges; do cat "/tmp/cuagym-vm-$p" 2>/dev/null; echo; done | sort -u)
oldest=$(for p in $bridges; do stat -c %Y "/proc/$p"; done | sort -n | head -1)
echo "live bridges: $(echo $bridges | wc -w); recorded containers: $(echo $recorded | wc -w);" \
     "oldest bridge started: ${oldest:+$(date -d @$oldest +%H:%M:%S)}"
echo "eval runners: $(ps -eo args | grep -c '[r]un_multienv')"
orphans=()
for c in $(docker ps -aq); do
    read -r name status created image <<<"$(docker inspect -f '{{.Name}} {{.State.Status}} {{.Created}} {{.Config.Image}}' "$c")"
    name=${name#/}; t=$(date -d "$created" +%s); age=$(( (now - t) / 60 ))
    if ! docker inspect -f '{{range .Config.Env}}{{.}}{{"\n"}}{{end}}' "$c" | grep -q '^ARGUMENTS=-qmp unix:/tmp/qmp.sock'; then
        echo "keep    $name ($image, $status, ${age} min): not a bridge VM"; continue
    fi
    full=$(docker inspect -f '{{.Id}}' "$c")
    if grep -qx "$full" <<<"$recorded"; then why=""
    elif [ "$status" != running ]; then why="$status"
    elif [ -z "$bridges" ]; then why="running, no live bridge"
    elif [ "$t" -lt "$oldest" ]; then why="running, older than every live bridge, unrecorded"
    else why=""; fi
    if [ -n "$why" ]; then echo "ORPHAN  $name (${age} min): $why"; orphans+=("$name")
    else echo "keep    $name ($status, ${age} min): in use or booting"; fi
done
echo "orphans: ${#orphans[@]}; dangling volumes: $(docker volume ls -qf dangling=true | wc -l)"
if [ "$REMOVE" = --remove ]; then
    [ ${#orphans[@]} -gt 0 ] && docker rm -f -v "${orphans[@]}" > /dev/null && echo "removed ${#orphans[@]} containers"
    docker volume prune -f | tail -1
    echo "now: $(docker ps -q | wc -l) running containers; $(free -g | awk '/Mem/ {print $7}') GiB available; swap used $(free -g | awk '/Swap/ {print $3}') GiB"
fi
