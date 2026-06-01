#!/bin/bash
# Start OAI gNB in background (RFSim mode).
# Usage: ./start_ran.sh [logfile]  (default: /tmp/gnb.log)

REPO="$(cd "$(dirname "$0")" && pwd)"
BUILD="$REPO/oai_ran/cmake_targets/ran_build/build"
CONF="$REPO/oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF/ORANSlice.gnb.sa.band78.fr1.106PRB.usrpx310.conf"
LOG="${1:-/tmp/gnb.log}"

if pgrep -x nr-softmodem > /dev/null; then
    echo "[start_ran] nr-softmodem already running (PID $(pgrep -x nr-softmodem))"
    exit 0
fi

echo "[start_ran] starting gNB → log: $LOG"
nohup "$BUILD/nr-softmodem" -O "$CONF" --sa --rfsim > "$LOG" 2>&1 &
GNB_PID=$!
echo "[start_ran] gNB PID: $GNB_PID"
echo "[start_ran] wait ~20s for AMF association, then run UEs"
echo "[start_ran] monitor: tail -f $LOG | grep -E 'AMF|RRC|NGAP|ERROR'"
