#!/bin/bash
# Stop the OAI Core Network.
# DB data (including CLI-created UEs) is preserved in the oai_db_data volume.
# To wipe the DB and reset to factory SQL, run:  docker compose -f docker-compose-legacy.yml down -v
cd "$(dirname "$0")"
echo "[stop_cn] stopping Core Network..."
docker compose -f docker-compose-legacy.yml down
echo "[stop_cn] done.  DB preserved in oai_db_data volume."
echo "[stop_cn] To reset DB: docker compose -f docker-compose-legacy.yml down -v"
