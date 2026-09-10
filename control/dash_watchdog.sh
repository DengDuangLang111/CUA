#!/bin/bash
# 每 5 分钟由 cron 调用:两个 dashboard daemon 谁不在就拉起谁。
# 幂等 —— daemon 都在时零动作、不写日志,所以 dash_watchdog.log 里有行
# 就等于「真的救过一次」,它本身就是故障记录。
#
# 存在的理由(2026-08-28):两个 daemon 都是 while true + set +e,不会自己退出,
# 但没有任何东西保证它们活着。status daemon 死于 08-24 16:15、无人察觉 4 天;
# sft daemon 死于 08-27 19:22 的 WSL 重启。前者不是重启导致的,所以只做
# 开机自启不够,必须周期性检查。
#
# 真源在 CTL:/mnt/d/research/osworld-verified-control/dash_watchdog.sh
# 本文件是 git 存档镜像(规矩见 DASHBOARD.md §134:只改 CTL,单向同步过来)。
CTL=/mnt/d/research/osworld-verified-control
H=/home/daniel_yan
LOG=$H/dash_watchdog.log

check() {   # $1=daemon 脚本名  $2=该 daemon 的日志
  pgrep -f "$CTL/$1" >/dev/null && return
  setsid nohup "$CTL/$1" >> "$2" 2>&1 < /dev/null &
  echo "[$(date '+%F %T')] restarted $1" >> "$LOG"
}

check dash_status_daemon.sh "$H/dash_status.log"
check sft_dash_daemon.sh    "$H/dash_sft.log"
