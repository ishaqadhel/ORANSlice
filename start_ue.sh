#!/bin/bash
# Start a single nrUE inside a network namespace, waiting for PDU session before returning.
# Usage: ./start_ue.sh <ns_index> <conf_file> [log_file]
#
#   ns_index  : integer (1-9), namespace ue<N> is created if missing
#   conf_file : full path to nrUE conf file
#   log_file  : optional log path (default: /tmp/ue<N>.log)
#
# RFSim server address is derived automatically: 10.(200+N).1.100

set -e

REPO="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS="$REPO/oai_ran/tools/scripts/multi-ue.sh"
BUILD="$REPO/oai_ran/cmake_targets/ran_build/build"

NS_INDEX="${1:?Usage: $0 <ns_index> <conf_file> [log_file]}"
CONF_FILE="${2:?Usage: $0 <ns_index> <conf_file> [log_file]}"
LOG_FILE="${3:-/tmp/ue${NS_INDEX}.log}"

NS_NAME="ue${NS_INDEX}"
RFSIM_ADDR="10.$((200 + NS_INDEX)).1.100"

if ! ip netns list | grep -qw "$NS_NAME"; then
    echo "[start_ue] creating namespace $NS_NAME"
    bash "$SCRIPTS" "-c${NS_INDEX}"
fi

if ip netns exec "$NS_NAME" ip addr show oaitun_ue1 2>/dev/null | grep -q "inet "; then
    echo "[start_ue] $NS_NAME already has oaitun_ue1 up — UE running"
    exit 0
fi

echo "[start_ue] starting UE in $NS_NAME → $RFSIM_ADDR  conf: $(basename "$CONF_FILE")"
nohup ip netns exec "$NS_NAME" "$BUILD/nr-uesoftmodem" \
    -r 106 --numerology 1 --band 78 -C 3619200000 --sa \
    -O "$CONF_FILE" --rfsim --rfsimulator.serveraddr "$RFSIM_ADDR" \
    > "$LOG_FILE" 2>&1 &
UE_PID=$!
echo "[start_ue] UE PID $UE_PID — waiting for PDU session (oaitun_ue1)..."

TIMEOUT=120
ELAPSED=0
while ! ip netns exec "$NS_NAME" ip addr show oaitun_ue1 2>/dev/null | grep -q "inet "; do
    sleep 5
    ELAPSED=$((ELAPSED + 5))
    if [ $ELAPSED -ge $TIMEOUT ]; then
        echo "[start_ue] ERROR: oaitun_ue1 not up after ${TIMEOUT}s — check $LOG_FILE"
        exit 1
    fi
    if ! kill -0 $UE_PID 2>/dev/null; then
        echo "[start_ue] ERROR: UE process exited early — check $LOG_FILE"
        exit 1
    fi
done

IP=$(ip netns exec "$NS_NAME" ip addr show oaitun_ue1 | grep "inet " | awk '{print $2}')
echo "[start_ue] $NS_NAME connected — oaitun_ue1 $IP  log: $LOG_FILE"
