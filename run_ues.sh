#!/bin/bash
# Launch multiple UEs sequentially (one per namespace), waiting for each PDU session
# before starting the next. This avoids the OAI RFSim race condition that causes
# crashes when multiple UEs connect simultaneously.
#
# Usage: ./run_ues.sh <ns1:conf1> [<ns2:conf2> ...]
#
# Examples:
#   ./run_ues.sh 1:oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF/nrUE_slice1.conf
#   ./run_ues.sh 1:nrUE_slice1.conf 2:nrUE_slice2.conf
#   ./run_ues.sh 3:nrUE_001010000010779.conf 4:nrUE_001010000010780.conf
#
# Conf file can be basename (searched in CONF_DIR) or full path.

REPO="$(cd "$(dirname "$0")" && pwd)"
CONF_DIR="$REPO/oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF"

if [ $# -eq 0 ]; then
    echo "Usage: $0 <ns_index>:<conf_file> [<ns_index>:<conf_file> ...]"
    exit 1
fi

for ARG in "$@"; do
    NS_INDEX="${ARG%%:*}"
    CONF="${ARG#*:}"

    # Resolve conf to full path
    if [ ! -f "$CONF" ]; then
        CONF="$CONF_DIR/$CONF"
    fi
    if [ ! -f "$CONF" ]; then
        echo "[run_ues] ERROR: conf file not found: $CONF"
        exit 1
    fi

    bash "$REPO/start_ue.sh" "$NS_INDEX" "$CONF" || exit 1
done

echo "[run_ues] all UEs connected."
