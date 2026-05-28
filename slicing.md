# ORANSlice: Slicing Architecture

## Overview

ORANSlice implements slicing at two independent layers:

| Layer | Mechanism | Config File |
|-------|-----------|-------------|
| RAN (MAC) | PRB ratio per NSSAI | `rrmPolicy.json` |
| CN Mode 1 | DNN routing in shared SMF/UPF | `docker-compose-legacy.yml` |
| CN Mode 2 | Dedicated SMF+UPF per slice | `docker-compose-slicing-basic-nrf.yaml` |

Both layers operate independently — RAN slicing works with either CN mode.

---

## RAN Slicing

PRB (Physical Resource Block) partitioning at the MAC DL scheduler.

**How it works:**
1. gNB reads `rrmPolicy.json` every ~1280 frames (~13 seconds)
2. Scheduler calls `nr_slice_preprocess()` every slot
3. PRB budget allocated per slice based on `min_ratio`/`max_ratio`/`dedicated_ratio`
4. Each UE's NSSAI (from PDU session) determines which slice budget it draws from

**Policy fields:**
```json
{
  "rrmPolicyRatio": [
    {
      "sst": 1,
      "dedicated_ratio": 5,   // guaranteed minimum PRB %
      "min_ratio": 10,         // scheduler lower bound
      "max_ratio": 100         // scheduler upper bound
    },
    {
      "sst": 1,
      "sd": 2,
      "dedicated_ratio": 5,
      "min_ratio": 10,
      "max_ratio": 100
    }
  ]
}
```

**Key files:**
- `openair2/LAYER2/NR_MAC_gNB/gNB_scheduler_dlsch.c` — `nr_update_slice_policy()`, `nr_slice_preprocess()`
- `openair2/LAYER2/NR_MAC_gNB/nr_mac_gNB.h` — `NR_slice_info_t`, `NR_slice_prb_policy_t`

---

## CN Slicing — Mode 1 (Legacy v1.5.1, Shared SMF/UPF)

Single SMF and single UPF handle all slices. Isolation at DNN/IP pool level only.

### Architecture

```
UE1 (SST=1, SD=0xFFFFFF, DNN=oai)  ──┐
                                        ├── gNB ── AMF ── SMF ── UPF (oai-spgwu-tiny)
UE2 (SST=1, SD=0x000002, DNN=oai2) ──┘
```

### PDU Session Flow

```
UE1 registers → AMF sees NSSAI(SST=1, SD=0xFFFFFF) → routes to SMF
SMF creates PDU session → assigns IP from 12.1.1.0/24 → DNN=oai
UPF gets PFCP rule: GTP tunnel → tun0(12.1.1.1) → eth0

UE2 registers → AMF sees NSSAI(SST=1, SD=0x000002) → same SMF
SMF creates PDU session → assigns IP from 12.1.2.0/24 → DNN=oai2
UPF gets PFCP rule: GTP tunnel → tun0(12.1.2.1) → eth0
```

One SMF holds **both** PDU sessions. One UPF processes **both** data paths.

### Slice Identity

| Slice | SST | SD | DNN | UE IP Range | UPF tun0 IP |
|-------|-----|----|-----|-------------|-------------|
| Slice 1 | 1 | 0xFFFFFF (default) | `oai` | 12.1.1.x | 12.1.1.1 |
| Slice 2 | 1 | 0x000002 | `oai2` | 12.1.2.x | 12.1.2.1 |

### Setup Notes

- `restart_cn.sh` adds `12.1.2.1/24` to UPF `tun0` (not in docker-compose config)
- `restart_cn.sh` adds iptables masquerade for `12.1.2.0/24` (Slice 2 internet access)
- Slice 1 masquerade is configured automatically by oai-spgwu-tiny at startup

---

## CN Slicing — Mode 2 (Develop v2.0.1+, Dedicated NF per Slice)

Each slice gets its own SMF and UPF container. True data-plane isolation.

### Architecture

```
UE1 (SST=1, SD=0xFFFFFF) ──┐
                              ├── gNB ── AMF ── NSSF ──── SMF-slice1 ── UPF-slice1 ── Internet
UE2 (SST=1, SD=0x000002) ──┘                    └─────── SMF-slice2 ── UPF-slice2 ── Internet
```

### PDU Session Flow

```
UE1 registers → AMF queries NSSF → NSSF returns SMF-slice1
SMF-slice1 creates PDU session → assigns IP from 12.1.1.0/24 → DNN=oai
UPF-slice1 gets PFCP rule: GTP tunnel → tun0 → eth0

UE2 registers → AMF queries NSSF → NSSF returns SMF-slice2
SMF-slice2 creates PDU session → assigns IP from 12.1.2.0/24 → DNN=oai2
UPF-slice2 gets PFCP rule: GTP tunnel → tun0 → eth0
```

Each SMF holds **only its slice's** PDU sessions. UPF-slice1 never sees UE2 packets.

### Container IPs

| Container | IP | Role |
|-----------|----|------|
| oai-amf | 192.168.70.132 | Shared — all UEs register here |
| oai-nssf | 192.168.70.138 | Shared — routes AMF to correct SMF |
| oai-smf-slice1 | 192.168.70.139 | Slice 1 session management |
| oai-smf-slice2 | 192.168.70.140 | Slice 2 session management |
| oai-upf-slice1 | 192.168.70.142 | Slice 1 user plane |
| oai-upf-slice2 | 192.168.70.143 | Slice 2 user plane |

### Shared vs Per-Slice Components

| CN Component | Mode 1 | Mode 2 |
|--------------|--------|--------|
| AMF | Shared | Shared |
| NSSF | Not present | Shared |
| AUSF / UDM / UDR | Shared | Shared |
| SMF | Shared (1 instance) | Per-slice (2 instances) |
| UPF | Shared (1 instance) | Per-slice (2 instances) |

---

## PDU Session Comparison

| Aspect | Mode 1 | Mode 2 |
|--------|--------|--------|
| Sessions stored in | 1 SMF (both slices) | SMF-slice1 or SMF-slice2 |
| PFCP rules in | 1 UPF (both tunnels) | UPF-slice1 or UPF-slice2 |
| N4 interface | 1 SMF↔UPF pair | per-slice SMF↔UPF pair |
| SMF failure impact | both sessions drop | only that slice drops |
| UPF failure impact | both slices lose data | only that slice loses data |
| IP pool enforcement | DNN-based in shared UPF | UPF only knows its own subnet |
| Complexity | Low | High |

---

## End-to-End Slicing (Both Layers Together)

```
rrmPolicy.json          CN Mode 2
      ↓                      ↓
MAC PRB budget         Dedicated SMF/UPF
per NSSAI              per NSSAI
      ↓                      ↓
Slice 1 gets X% PRBs + own SMF-slice1 + UPF-slice1
Slice 2 gets Y% PRBs + own SMF-slice2 + UPF-slice2
```

Full isolation: RAN radio resources partitioned + CN data paths separated.
This is the full ORANSlice system as described in ACM MobiCom '24.
