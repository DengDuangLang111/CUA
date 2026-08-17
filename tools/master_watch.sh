#!/bin/bash
# master_watch.sh -- notice when the Tillicum ControlMaster dies, and stop the
# eval chain from burning VM time against a dead endpoint.
#
# 2026-08-17: the master died after 18h (not the 48h ControlPersist -- a
# network blip past ServerAliveCountMax=3 killed it), every tunnel went with
# it, and the Bs eval kept running against an endpoint returning HTTP 000.
# Nothing noticed until a human looked. Re-establishing needs Duo, so this
# cannot self-heal; what it CAN do is fail loudly and stop the waste.
#
#   bash tools/master_watch.sh          (runs until stopped)
set -u
CM=$HOME/.ssh/cm/qwen36-tillicum-login
CTL=/mnt/d/research/osworld-verified-control
LOG=$CTL/logs/master_watch.log
SLEEP=${SLEEP:-120}
SSHT="ssh -n -S $CM -o ControlMaster=no -o BatchMode=yes jy050706@tillicum-login02.hyak.uw.edu"
down=0
echo "[$(date '+%F %T')] master_watch up" >> $LOG
while true; do
  if $SSHT true 2>/dev/null; then
    if [ $down = 1 ]; then
      echo "[$(date '+%F %T')] MASTER BACK -- eval drivers may be restarted" >> $LOG
      down=0
    fi
  else
    if [ $down = 0 ]; then
      down=1
      echo "[$(date '+%F %T')] MASTER DOWN -- needs a human + Duo:" >> $LOG
      echo "   rm -f $CM && ssh -M -S $CM -o ControlPersist=yes \\" >> $LOG
      echo "     -o ServerAliveInterval=60 -o ServerAliveCountMax=30 -o TCPKeepAlive=yes \\" >> $LOG
      echo "     -fN jy050706@tillicum-login02.hyak.uw.edu" >> $LOG
      # Stop runners: with the endpoint gone every step is a timeout, and the
      # VMs are the scarcest resource in the whole pipeline.
      pkill -f run_multienv_qwen 2>/dev/null && \
        echo "[$(date '+%F %T')] eval runners stopped to save VM time" >> $LOG
    fi
  fi
  sleep $SLEEP
done
