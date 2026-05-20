# ORANSlice CLI

Interactive management tool for UEs and network slices in ORANSlice (legacy CN v1.5.1, RFSim mode).

## Prerequisites

- Ubuntu 22.04 with ORANSlice deployed (Core Network running in Docker)
- Python 3.8+
- Root access (`sudo`)

## Setup

```bash
cd ~/ORANSlice/tools/cli

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
deactivate
```

## Run

```bash
sudo ~/ORANSlice/tools/cli/oranslice
```

Or directly:

```bash
cd ~/ORANSlice/tools/cli
source .venv/bin/activate
sudo -E python3 oranslice_cli.py
```

> Root is required for namespace operations (`ip netns`).

---

## Features

### UE Management

| Action | Description |
|--------|-------------|
| List UEs | Table of all subscribers from MySQL (`AuthenticationSubscription`) with SST, SD, DNN, static IP, and whether the `.conf` file exists |
| Create UE | Wizard: enter IMSI → choose slice → auto-assigns next free static IP → inserts DB records + writes `nrUE_{imsi}.conf` |
| Delete UE | Select IMSI from list → removes DB entries and `.conf` file |

**Slice options when creating a UE:**

| Slice | SST | SD | DNN | Subnet |
|-------|-----|----|-----|--------|
| Slice 1 | 1 | 0xFFFFFF (default) | `oai` | 12.1.1.x |
| Slice 2 | 1 | 0x000002 | `oai2` | 12.1.2.x |

Static IPs are auto-assigned (scans DB for first free address starting from `.2`).

Default key/OPC match the pre-provisioned UEs in `oai_db.sql`.

---

### Namespace Management

Wraps `oai_ran/tools/scripts/multi-ue.sh`. Supports up to 2 namespaces (`ue1`, `ue2`).

| Action | Description |
|--------|-------------|
| List Namespaces | Shows active namespaces with their RFSim server address and the command to enter them |
| Create Namespace | Runs `multi-ue.sh -c{N}` to set up isolated network stack |
| Delete Namespace | Runs `multi-ue.sh -d{N}` to tear down the namespace |

> To enter a namespace and run a UE inside it, use the command shown in the list output:
> ```bash
> sudo bash ~/ORANSlice/oai_ran/tools/scripts/multi-ue.sh -o1
> ```

RFSim server addresses per namespace:

| Namespace | `--rfsimulator.serveraddr` |
|-----------|--------------------------|
| ue1 | 10.201.1.100 |
| ue2 | 10.202.1.100 |

---

### Slice Management

#### RAN Slices (`rrmPolicy.json`)

The gNB re-reads `rrmPolicy.json` every ~13 seconds automatically — **no restart needed**.

| Action | Description |
|--------|-------------|
| List Slices | Shows both RAN policy (from `rrmPolicy.json`) and CN slices (from docker-compose) |
| Create RAN Slice | Add new entry with SST, SD, and PRB ratios |
| Update RAN Slice Policy | Modify `dedicated_ratio`, `min_ratio`, `max_ratio` for an existing slice |
| Delete RAN Slice | Remove slice entry from policy file |

Policy fields:

| Field | Meaning |
|-------|---------|
| `dedicated_ratio` | Guaranteed PRB % (minimum reserved) |
| `min_ratio` | Scheduler won't assign less than this |
| `max_ratio` | Scheduler won't assign more than this |

> `rrmPolicy.json` requires the patch: `git apply doc/rrmPolicyJson.patch`

#### CN Slices (Legacy v1.5.1)

CN slice configuration is read-only in this tool — slices are fixed at startup via docker-compose environment variables. The only available action is **Restart CN**, which re-runs `restart_cn.sh`:

1. `docker compose down`
2. `docker compose up -d`
3. Adds `12.1.2.1/24` to UPF `tun0` (required for Slice 2 traffic)

---

### System Status

| Check | Source |
|-------|--------|
| MySQL | Connects to `192.168.70.131:3306`, counts UEs |
| Docker containers | `docker ps -a` for all 9 CN containers |
| Network namespaces | `ip netns list` |
| RAN policy | Checks `rrmPolicy.json` exists and counts slices |

**Ping UE test** — runs `ping -I oaitun_ue1` inside a selected namespace toward a target IP (default: `192.168.70.135` / `oai-ext-dn`).

---

## File Locations

| File | Purpose |
|------|---------|
| `oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF/nrUE_{imsi}.conf` | Generated UE config files |
| `rrmPolicy.json` | RAN slice policy (repo root, after patch) |
| `oai_cn/oai-cn5g-legacy/docker-compose-legacy.yml` | CN slice configuration (read-only) |
| `oai_ran/tools/scripts/multi-ue.sh` | Namespace management script |

## MySQL Connection

```
Host:     192.168.70.131 (oai-spgwu container bridge)
Port:     3306
User:     test
Password: test
Database: oai_db
```

Requires the CN (`demo-oai` Docker network) to be running.

## Troubleshooting

**`Cannot reach MySQL`** — Core Network not running. Start it:
```bash
cd ~/ORANSlice/oai_cn/oai-cn5g-legacy/
./restart_cn.sh
```

**`rrmPolicy.json not found`** — Apply the patch:
```bash
cd ~/ORANSlice
git apply doc/rrmPolicyJson.patch
```

**`multi-ue.sh not found`** — Copy from OAI repo:
```bash
cd ~
git clone https://gitlab.eurecom.fr/oai/openairinterface5g.git oai_full
cp oai_full/tools/scripts/multi-ue.sh ~/ORANSlice/oai_ran/tools/scripts/
```

**Namespace index > 2** — `multi-ue.sh` supports only `ue1` and `ue2`. Running more than 2 simultaneous UEs requires modifying the script manually.
