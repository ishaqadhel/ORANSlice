#!/bin/bash
# Stop all ORANSlice RAN components and clean up namespaces/interfaces

SCRIPTS="$(cd "$(dirname "$0")" && pwd)/oai_ran/tools/scripts/multi-ue.sh"

echo "[stop_ran] Killing nr-uesoftmodem..."
sudo pkill -f nr-uesoftmodem 2>/dev/null || true
sleep 1

echo "[stop_ran] Killing nr-softmodem..."
sudo pkill -f nr-softmodem 2>/dev/null || true
sleep 1

echo "[stop_ran] Deleting all ueN namespaces..."
existing_ns=$(ip netns list 2>/dev/null | awk '{print $1}' | grep -E '^ue[0-9]+$' || true)

if [ -z "$existing_ns" ]; then
    echo "[stop_ran]   No ueN namespaces found."
else
    for ns in $existing_ns; do
        n="${ns#ue}"
        if [ -f "$SCRIPTS" ]; then
            sudo "$SCRIPTS" "-d${n}" 2>/dev/null || sudo ip netns del "$ns" 2>/dev/null || true
        else
            sudo ip netns del "$ns" 2>/dev/null || true
        fi
        echo "[stop_ran]   Deleted namespace $ns"
    done
fi

echo "[stop_ran] Cleaning stale v-ueN veth interfaces..."
for iface in $(ip link show 2>/dev/null | grep -oP 'v-ue\d+' || true); do
    sudo ip link delete "$iface" 2>/dev/null || true
    echo "[stop_ran]   Deleted $iface"
done

echo "[stop_ran] Done. Run 'ip a' to verify interfaces are clean."
