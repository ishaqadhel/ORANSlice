# ORANSlice — How to Run

> **Prerequisites:** Installation complete (see `installation.md`). All commands from `~/ORANSlice/` unless noted.

---

## Quick Reference

```bash
# Start
sudo ./oai_cn/oai-cn5g-legacy/restart_cn.sh   # ~2-3 min
sudo ./start_ran.sh                             # wait ~20s for AMF
sudo ./run_ues.sh "1:oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF/nrUE_slice1.conf" \
                  "2:oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF/nrUE_slice2.conf"

# Verify
ip netns exec ue1 ping -I oaitun_ue1 -c 3 192.168.70.135
ip netns exec ue2 ping -I oaitun_ue1 -c 3 8.8.8.8

# Stop
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

> **Critical:** Start UEs one at a time. OAI RFSim crashes when multiple UEs connect simultaneously. `run_ues.sh` handles this automatically — it waits for each UE's PDU session before starting the next.

```bash
cd ~/ORANSlice
CONFDIR="oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF"

sudo ./run_ues.sh \
  "1:$CONFDIR/nrUE_slice1.conf" \
  "2:$CONFDIR/nrUE_slice2.conf"
```

Expected output:
```
[start_ue] creating namespace ue1
[start_ue] UE PID 12345 — waiting for PDU session (oaitun_ue1)...
[start_ue] ue1 connected — oaitun_ue1 12.1.1.2/24  log: /tmp/ue1.log
[start_ue] creating namespace ue2
[start_ue] UE PID 12367 — waiting for PDU session (oaitun_ue1)...
[start_ue] ue2 connected — oaitun_ue1 12.1.2.2/24  log: /tmp/ue2.log
[run_ues] all UEs connected.
```

Each UE gets a tunnel interface `oaitun_ue1` in its namespace:
- **ue1** (Slice 1): `12.1.1.x`
- **ue2** (Slice 2): `12.1.2.x`

**Namespace-to-RFSim address mapping:**

| Namespace | veth host IP | UE conf |
|-----------|-------------|---------|
| ue1 | 10.201.1.100 | nrUE_slice1.conf |
| ue2 | 10.202.1.100 | nrUE_slice2.conf |
| ue3 | 10.203.1.100 | any |
| ueN | 10.(200+N).1.100 | any |

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

The CLI manages subscriber DB entries, UE conf files, and namespaces interactively.

### Launch

```bash
cd ~/ORANSlice/tools/cli
sudo ./oranslice
```

Menu options:
- **UE Management** — list, create, delete subscribers
- **Namespace Management** — list, create, delete namespaces
- **Slice Management** — view/update `rrmPolicy.json`, restart CN
- **System Status** — health check + connectivity test

### Add a new UE (end-to-end)

**Step 1 — Create subscriber in DB + generate conf file via CLI:**

```
UE Management → Create UE
  IMSI: 001010000010779   (15 digits, must not already exist in DB)
  Key/OPC: use defaults
  Slice: Slice 1  (SST=1, SD=0xFFFFFF, DNN=oai)  or  Slice 2
  Confirm
```

CLI creates:
- DB entry in `AuthenticationSubscription` + `SessionManagementSubscriptionData`
- `oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF/nrUE_<IMSI>.conf`

**Step 2 — Start the UE:**

```bash
cd ~/ORANSlice
CONFDIR="oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF"

# Single new UE (pick next available namespace index, e.g. 3)
sudo ./start_ue.sh 3 "$CONFDIR/nrUE_001010000010779.conf"

# Or add multiple at once (sequentially)
sudo ./run_ues.sh \
  "3:$CONFDIR/nrUE_001010000010779.conf" \
  "4:$CONFDIR/nrUE_001010000010780.conf"
```

**Step 3 — Verify:**

```bash
ip netns exec ue3 ip addr show oaitun_ue1 | grep inet
ip netns exec ue3 ping -I oaitun_ue1 -c 4 192.168.70.135
ip netns exec ue3 ping -I oaitun_ue1 -c 4 8.8.8.8
```

### Delete a UE

```
CLI → UE Management → Delete UE → select IMSI → confirm
```

Removes DB entries and conf file. Stop and delete the namespace separately:
```bash
sudo bash oai_ran/tools/scripts/multi-ue.sh -d3   # remove namespace ue3
```

### IMSI range

Pre-provisioned in `oai_db.sql`: `001010000010776` (Slice 1) and `001010000010777` (Slice 2) plus extras (`10768–10778`, `12245–12256`).

For CLI-created UEs use any 15-digit IMSI not already in the DB (e.g. `001010000010779` onwards).

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

# 4. UEs (sequential)
CONFDIR="oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF"
sudo ./run_ues.sh \
  "1:$CONFDIR/nrUE_slice1.conf" \
  "2:$CONFDIR/nrUE_slice2.conf"
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Container stuck "Exited" | `docker logs <name> --tail 30`; run `restart_cn.sh` again |
| gNB "No route to AMF" | CN not ready yet — wait and retry `start_ran.sh` |
| UE no IP on `oaitun_ue1` | Check `docker logs oai-amf` for auth failure; restart UE with `start_ue.sh` |
| UE stuck `5GMM-REG-INITIATED` | UDR not ready at auth time — `restart_cn.sh` now prevents this; restart UE |
| UE crash on start | Started multiple UEs in parallel — always use `run_ues.sh` |
| 3rd+ UE hangs at radio sync | Restart gNB fresh, connect all UEs from scratch via `run_ues.sh` |
| CLI UEs gone after restart | Shouldn't happen (named volume); if wiped with `-v`, re-create via CLI |
| ping fails through tunnel | `docker exec oai-spgwu-tiny ip route` — check UE subnet route exists |

---

## Appendix: Single UE Test

Minimal smoke test with one UE (no slice2, no namespace setup needed):

```bash
cd ~/ORANSlice

sudo ./oai_cn/oai-cn5g-legacy/restart_cn.sh
sudo ./start_ran.sh
sleep 25

sudo ./start_ue.sh 1 oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF/nrUE_slice1.conf

ip netns exec ue1 ping -I oaitun_ue1 -c 4 192.168.70.135
ip netns exec ue1 ping -I oaitun_ue1 -c 4 8.8.8.8
```

Expected UE log (`/tmp/ue1.log`):
```
[NAS]   Received PDU Session Establishment Accept
[NR_RRC]   State = NR_RRC_CONNECTED
```
