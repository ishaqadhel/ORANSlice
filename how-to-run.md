# ORANSlice — How to Run

> **Prerequisites:** Installation complete (see `installation.md`). All commands from `~/ORANSlice/` unless noted.

---

## Quick Reference

```bash
# 1. Start CN (~2-3 min)
sudo ./oai_cn/oai-cn5g-legacy/restart_cn.sh

# 2. Start gNB
sudo ./start_ran.sh

# 3. Manage UEs via CLI (create + run)
sudo ./tools/cli/oranslice

# 4. Verify
ip netns exec ue1 ping -I oaitun_ue1 -c 3 192.168.70.135

# 5. Stop
sudo ./stop_ran.sh
sudo ./oai_cn/oai-cn5g-legacy/stop_cn.sh
```

---

## 1. Start the Core Network

```bash
cd ~/ORANSlice/oai_cn/oai-cn5g-legacy/
sudo ./restart_cn.sh
```

Script waits for:
1. All containers up
2. `oai-spgwu-tiny` healthy (UPF)
3. MySQL subscriber data populated (UDR auth ready)

Takes ~2–3 minutes. Ends with:
```
[restart_cn] Core Network ready.
```

> **DB persistence:** Subscriber data lives in the `oai_db_data` Docker volume — survives restarts.
> Reset to factory: `docker compose -f docker-compose-legacy.yml down -v`

Verify all containers are `Up`:
```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

Expected containers: `mysql`, `oai-nrf`, `oai-udr`, `oai-udm`, `oai-ausf`, `oai-amf`, `oai-smf`, `oai-spgwu-tiny`, `oai-ext-dn`

---

## 2. Start the gNB

```bash
cd ~/ORANSlice
sudo ./start_ran.sh
```

Logs go to `/tmp/gnb.log`. After ~20s, verify AMF association:
```bash
grep "NGAP_REGISTER_GNB_CNF" /tmp/gnb.log
# Expected: [GNB_APP]   [gNB 0] Received NGAP_REGISTER_GNB_CNF: associated AMF 1
```

Live monitor:
```bash
tail -f /tmp/gnb.log | grep -E 'AMF|NGAP|ERROR'
```

---

## 3. Start UEs

> **Critical:** Start UEs one at a time. OAI RFSim crashes when multiple UEs connect simultaneously. The CLI handles this automatically.

### Via CLI (recommended)

```bash
cd ~/ORANSlice
sudo ./tools/cli/oranslice
```

**First time setup:**
```
UE Management → Delete Orphan UEs        # remove DB entries with no conf file
UE Management → Create UE               # IMSI, slice, auto-assigns IP + namespace
UE Management → Run UE                  # starts nr-uesoftmodem, waits for PDU session
```

Repeat "Create UE" + "Run UE" for each additional UE. The CLI starts them sequentially — wait for each to connect before running the next.

Each UE gets a tunnel interface `oaitun_ue1` in its namespace:
- **Slice 1** UE: `12.1.1.x`
- **Slice 2** UE: `12.1.2.x`

**Namespace-to-RFSim address mapping:**

| Namespace | RFSim addr | Notes |
|-----------|------------|-------|
| ue1 | 10.201.1.100 | first created UE |
| ue2 | 10.202.1.100 | second created UE |
| ueN | 10.(200+N).1.100 | auto-assigned by CLI |

### Via script (scripted/automated usage)

```bash
cd ~/ORANSlice
CONFDIR="oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF"

sudo ./run_ues.sh \
  "1:$CONFDIR/nrUE_001010000010779.conf" \
  "2:$CONFDIR/nrUE_001010000010781.conf"
```

`run_ues.sh` calls `start_ue.sh` for each pair sequentially, waiting for PDU session before starting the next.

---

## 4. Verify Connectivity

### Check tunnel IPs

```bash
ip netns exec ue1 ip addr show oaitun_ue1 | grep inet   # 12.1.1.x
ip netns exec ue2 ip addr show oaitun_ue1 | grep inet   # 12.1.2.x
```

### Ping CN (oai-ext-dn at 192.168.70.135)

```bash
ip netns exec ue1 ping -I oaitun_ue1 -c 4 192.168.70.135
ip netns exec ue2 ping -I oaitun_ue1 -c 4 192.168.70.135
```

### Ping internet

```bash
ip netns exec ue1 ping -I oaitun_ue1 -c 4 8.8.8.8
ip netns exec ue2 ping -I oaitun_ue1 -c 4 8.8.8.8
```

### iperf3 throughput test

```bash
# Server (in oai-ext-dn)
docker exec -it oai-ext-dn iperf3 -s &
docker exec -it oai-ext-dn iperf3 -s -p 5202 &

# Slice 1 client (UE1 IP from above, e.g. 12.1.1.2)
ip netns exec ue1 iperf3 -c 192.168.70.135 -B 12.1.1.2 -t 30

# Slice 2 client (UE2 IP from above, e.g. 12.1.2.2)
ip netns exec ue2 iperf3 -c 192.168.70.135 -B 12.1.2.2 -t 30 -p 5202
```

---

## 5. UE Management (CLI)

The CLI is the single tool for managing UEs end-to-end — DB entries, conf files, namespaces, and running processes.

### Launch

```bash
sudo ~/ORANSlice/tools/cli/oranslice
```

### UE Management menu actions

| Action | What it does |
|--------|-------------|
| List UEs | Table with SST, SD, DNN, IP, conf file status, assigned namespace |
| Create UE | Wizard → assigns IP + namespace automatically → writes conf + DB entry |
| Run UE | Select a single UE or **"Run All"** to start all sequentially — waits for each PDU session (up to 120s each) |
| Stop UE | Kills `nr-uesoftmodem` process for selected UE |
| Delete UE | Removes DB entries, conf file, and namespace |
| Delete Orphan UEs | Bulk-removes DB entries that have no conf file |

### Full workflow (new UE)

```
1. UE Management → Create UE
      IMSI: 001010000010782   (15 digits, not already in DB)
      Key/OPC: use defaults
      Slice: Slice 1 or Slice 2
      → auto-assigns static IP, creates namespace ueN, writes conf

2. UE Management → Run UE
      Select IMSI → CLI starts UE, waits for oaitun_ue1 to come up
      → output shows IP and log path when connected

3. Verify (in a separate terminal):
      ip netns exec ueN ip addr show oaitun_ue1 | grep inet
      ip netns exec ueN ping -I oaitun_ue1 -c 4 192.168.70.135
```

### Delete a UE

```
UE Management → Delete UE → select IMSI → confirm
```

Removes DB entry, conf file, and namespace in one step. Stop the UE process first if running:
```
UE Management → Stop UE → select IMSI
```

---

## 6. RAN Slice Policy

Edit `rrmPolicy.json` to change PRB allocation between slices:

```bash
nano ~/ORANSlice/rrmPolicy.json
```

```json
{
  "rrmPolicyRatio": [
    { "sst": 1,           "dedicated_ratio": 5, "min_ratio": 80, "max_ratio": 100 },
    { "sst": 1, "sd": 2,  "dedicated_ratio": 5, "min_ratio": 10, "max_ratio": 20  }
  ]
}
```

> Dynamic reload (gNB re-reads every ~13s) requires `doc/rrmPolicyJson.patch` applied + OAI rebuild. Without the patch, policy is read at startup only.

See `slicing.md` for field definitions and architecture.

---

## 7. Stop Everything

```bash
cd ~/ORANSlice

# Kills UEs + gNB, deletes all ueN namespaces, cleans veth interfaces
sudo ./stop_ran.sh

# Stops CN containers (preserves oai_db_data volume)
sudo ./oai_cn/oai-cn5g-legacy/stop_cn.sh
```

---

## 8. Restart (Full Cycle)

```bash
cd ~/ORANSlice

# 1. CN (waits ~2-3 min until UDR is ready)
sudo ./oai_cn/oai-cn5g-legacy/restart_cn.sh

# 2. gNB
sudo ./start_ran.sh

# 3. Wait for AMF association
sleep 25

# 4. UEs — via CLI
sudo ./tools/cli/oranslice
# UE Management → Run UE → Run All
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Container stuck "Exited" | `docker logs <name> --tail 30`; run `restart_cn.sh` again |
| gNB "No route to AMF" | CN not ready yet — wait and retry `start_ran.sh` |
| UE no IP on `oaitun_ue1` | Check `docker logs oai-amf` for auth failure; CLI → UE Management → Stop UE → Run UE |
| UE stuck `5GMM-REG-INITIATED` | UDR not ready at auth time — `restart_cn.sh` now prevents this; stop and re-run UE via CLI |
| UE crash on start | Started multiple UEs in parallel — use CLI "Run All" which starts sequentially |
| 3rd+ UE hangs at radio sync | Restart gNB fresh, then CLI → Run UE → Run All |
| CLI UEs gone after restart | Shouldn't happen (named volume); if wiped with `-v`, re-create via CLI |
| ping fails through tunnel | `docker exec oai-spgwu-tiny ip route` — check UE subnet route exists |

---

## Appendix: Single UE Test

Minimal smoke test with one UE:

```bash
cd ~/ORANSlice

sudo ./oai_cn/oai-cn5g-legacy/restart_cn.sh
sudo ./start_ran.sh
sleep 25

# Create + run via CLI
sudo ./tools/cli/oranslice
# UE Management → Create UE  (Slice 1, use defaults)
# UE Management → Run UE     (select the new IMSI)

# Verify (in another terminal)
ip netns exec ue1 ping -I oaitun_ue1 -c 4 192.168.70.135
ip netns exec ue1 ping -I oaitun_ue1 -c 4 8.8.8.8
```

Expected UE log (`/tmp/ue1.log`):
```
[NAS]   Received PDU Session Establishment Accept
[NR_RRC]   State = NR_RRC_CONNECTED
```
