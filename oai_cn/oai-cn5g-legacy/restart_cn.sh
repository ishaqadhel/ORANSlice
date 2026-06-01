#!/bin/bash
# Restart the OAI Core Network.
# DB data is persisted in the oai_db_data named volume across restarts.
# To wipe DB and reload from oai_db.sql: docker compose -f docker-compose-legacy.yml down -v
set -e
cd "$(dirname "$0")"

docker compose -f docker-compose-legacy.yml down
docker compose -f docker-compose-legacy.yml up -d

# Wait for UPF (spgwu-tiny) — has a built-in health check
echo "[restart_cn] waiting for oai-spgwu-tiny to be healthy..."
for i in $(seq 1 60); do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' oai-spgwu-tiny 2>/dev/null || echo "missing")
    if [ "$STATUS" = "healthy" ]; then
        echo "[restart_cn] oai-spgwu-tiny healthy after ${i}0s"
        break
    fi
    if [ $i -eq 60 ]; then
        echo "[restart_cn] WARNING: oai-spgwu-tiny not healthy after 600s, proceeding anyway"
    fi
    sleep 10
done

# Wait for UDR to be able to serve subscriber queries (auth depends on this)
echo "[restart_cn] waiting for UDR to serve subscriber data..."
for i in $(seq 1 30); do
    COUNT=$(docker exec mysql mysql -utest -ptest oai_db -sN \
        -e "SELECT COUNT(*) FROM AuthenticationSubscription" 2>/dev/null || echo "0")
    if [ "$COUNT" -gt "0" ] 2>/dev/null; then
        echo "[restart_cn] UDR DB ready: ${COUNT} subscribers after ${i}0s"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "[restart_cn] WARNING: DB not populated after 300s"
    fi
    sleep 10
done

# Extra buffer for UDR HTTP service to be ready after DB is up
sleep 5

docker exec oai-spgwu-tiny ip addr add 12.1.2.1/24 dev tun0 2>/dev/null || echo "[restart_cn] 12.1.2.1/24 already set on tun0"
echo "[restart_cn] 12.1.2.1/24 configured on tun0"

docker exec oai-spgwu-tiny iptables -t nat -A POSTROUTING -s 12.1.2.0/24 -o eth0 -j MASQUERADE 2>/dev/null || true
echo "[restart_cn] masquerade rule configured for 12.1.2.0/24"

echo "[restart_cn] Core Network ready."
