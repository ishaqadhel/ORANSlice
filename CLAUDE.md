# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repository Is

ORANSlice is an end-to-end 5G network slicing framework for O-RAN, published at ACM MobiCom '24. It extends OAI's 5G protocol stack (OAI 2024.w28 base) with:
1. **RAN slicing** — MAC-layer PRB (Physical Resource Block) partitioning per NSSAI slice
2. **E2SM-CCC-based E2 Agent** — a custom O-RAN Service Model that communicates with an xApp via UDP/protobuf
3. **CN slicing** — two configurations: shared SMF/UPF (legacy v1.5.1) or dedicated SMF+UPF per slice (develop branch v2.0.1+)

## Repository Structure

```
ORANSlice/
├── oai_cn/                        # 5G Core Network (Docker)
│   ├── oai-cn5g-legacy/           # Mode 1: Legacy v1.5.1, shared SMF/UPF
│   │   ├── docker-compose-legacy.yml   # Single SMF + single UPF for both slices
│   │   ├── restart_cn.sh               # Stop/start + add 12.1.2.1/24 to UPF tun0
│   │   ├── conf/config.yaml            # OAI NF configuration
│   │   └── database/oai_db.sql         # Pre-provisioned UE subscriber data
│   ├── dev_oai5gcn.patch          # Mode 2: patch for oai-cn5g-fed v2.0.1 (dedicated NFs)
│   │   # Modifies: basic_nrf_config.yaml, slicing_base/slice1/slice2_config.yaml,
│   │   # docker-compose-basic-nrf.yaml, docker-compose-slicing-basic-nrf.yaml, oai_db2.sql
│   └── oai_slicing_usrpX310.conf  # Alternate gNB config (USRP X310 OTA, not RFSim)
├── oai_ran/                       # OAI RAN source (gNB + nrUE)
│   ├── cmake_targets/             # Build system entry point
│   │   └── build_oai              # Main build script
│   ├── targets/PROJECTS/GENERIC-NR-5GC/CONF/
│   │   ├── ORANSlice.gnb.sa.band78.fr1.106PRB.usrpx310.conf  # Primary gNB config
│   │   ├── nrUE_slice1.conf       # UE for Slice 1 (IMSI ...10776, DNN=oai)
│   │   └── nrUE_slice2.conf       # UE for Slice 2 (IMSI ...10777, DNN=oai2)
│   ├── openair2/
│   │   ├── LAYER2/NR_MAC_gNB/     # RAN slicing core implementation
│   │   │   ├── gNB_scheduler_dlsch.c  # nr_update_slice_policy(), nr_slice_preprocess()
│   │   │   └── nr_mac_gNB.h           # NR_slice_info_t, NR_slice_prb_policy_t, NR_Slices_t
│   │   ├── E2_AGENT/              # E2 Agent communicating with e2sim via UDP
│   │   │   ├── e2_agent_app.c/h   # UDP sockets: IN=6655, OUT=6600
│   │   │   └── oai-oran-protolib/ # Protobuf definitions (ran_messages.proto)
│   │   ├── GNB_APP/gnb_config.c   # Reads SliceConf path into RC.nrmac[0]->SliceConfigFile
│   │   └── RRC/NR/                # NR RRC — propagates NSSAI from UE registration to MAC
│   └── executables/               # nr-softmodem (gNB) and nr-uesoftmodem (UE) entry points
└── doc/
    ├── rrmPolicyJson.patch        # Enables periodic JSON policy reading in the scheduler
    └── ORANSlice_Framework.png
```

## Build Commands (OAI RAN)

All build commands run from `oai_ran/cmake_targets/`.

```bash
# First time only: install all system dependencies
./build_oai -I

# Build gNB and nrUE (software radio / RFSim mode)
./build_oai -w USRP --ninja --gNB --nrUE

# Binaries land at:
# oai_ran/cmake_targets/ran_build/build/nr-softmodem   (gNB)
# oai_ran/cmake_targets/ran_build/build/nr-uesoftmodem (UE)
```

`-w USRP` enables both USRP hardware drivers and the RFSim software radio. There is no separate build flag for RFSim-only; `--rfsim` is a runtime flag.

Rebuild after code changes (no `-I` needed):
```bash
./build_oai -w USRP --ninja --gNB --nrUE
```

## Core Network Commands

```bash
# --- Legacy v1.5.1 (default, simpler) ---
cd oai_cn/oai-cn5g-legacy/
./restart_cn.sh        # stop + start + add 12.1.2.1/24 to UPF tun0 for Slice 2

# --- Develop branch v2.0.1+ (requires applying dev_oai5gcn.patch first) ---
# Single SMF/UPF for all slices (no per-slice CN isolation):
docker compose -f docker-compose/docker-compose-basic-nrf.yaml up -d
# Dedicated SMF+UPF per slice (true CN slicing):
docker compose -f docker-compose/docker-compose-slicing-basic-nrf.yaml up -d

# Check container health (either mode)
docker ps -a

# Tail logs for a specific NF
docker logs oai-amf -f
docker logs oai-smf -f          # legacy
docker logs oai-smf-slice1 -f   # develop slicing mode
docker logs oai-spgwu-tiny -f   # legacy UPF
docker logs oai-upf-slice1 -f   # develop UPF for Slice 1
```

`restart_cn.sh` (legacy) does: stop stack → start stack → `docker exec oai-spgwu-tiny ip addr add 12.1.2.1/24 dev tun0`. The secondary IP is required because oai-spgwu-tiny's `NETWORK_UE_IP` only covers `12.1.1.0/24` (Slice 1); Slice 2 traffic (`12.1.2.x`) needs the extra address on tun0.

## Run Commands

**Prerequisites:** The Docker network `demo-oai-public-net` must exist before starting the CN:
```bash
docker network create \
  --driver=bridge --subnet=192.168.70.128/26 \
  --opt "com.docker.network.bridge.name"="demo-oai" \
  demo-oai-public-net
```

**gNB (RFSim):**
```bash
cd oai_ran/cmake_targets/ran_build/build
sudo ./nr-softmodem \
  -O ../../../targets/PROJECTS/GENERIC-NR-5GC/CONF/ORANSlice.gnb.sa.band78.fr1.106PRB.usrpx310.conf \
  --sa --rfsim
```

**nrUE Slice 1 (RFSim):**
```bash
sudo ./nr-uesoftmodem \
  -r 106 --numerology 1 --band 78 -C 3619200000 --sa \
  -O ../../../targets/PROJECTS/GENERIC-NR-5GC/CONF/nrUE_slice1.conf \
  --rfsim --rfsimulator.serveraddr 127.0.0.1
```

**nrUE Slice 2 (RFSim):** same command but with `nrUE_slice2.conf`.

## Architecture: How CN Slicing Works

The repository provides two distinct CN slicing modes, chosen by which docker-compose file is used.

### Mode 1 — Legacy v1.5.1 (shared SMF/UPF)

```
UE ─── gNB ─── AMF ─── SMF ─── oai-spgwu-tiny (UPF)
                  ↑               ↑
            NSSAI selection   DNN routing
           (SST/SD in AMF)    (oai → 12.1.1.x)
                              (oai2 → 12.1.2.x)
```

- AMF is configured with two `SST_x/SD_x` entries: `SST_0=1/SD_0=0xFFFFFF` and `SST_1=1/SD_1=0x000002`
- A **single SMF** handles both slices, distinguished by DNN (`DNN_NI0=oai`, `DNN_NI1=oai2`)
- A **single UPF** (oai-spgwu-tiny) routes both DNNs; Slice 2 traffic needs the extra `12.1.2.1/24` address added to `tun0` after startup
- CN-level isolation exists at the session/DNN layer only — same SMF and UPF process both slices

### Mode 2 — Develop branch v2.0.1+ with dedicated NFs per slice

Applied via `oai_cn/dev_oai5gcn.patch` to the upstream `oai-cn5g-fed` repo at tag `v2.0.1`.

```
                ┌── oai-smf-slice1 (192.168.70.139) ── oai-upf-slice1 (192.168.70.142)
AMF ── NRF ────┤
                └── oai-smf-slice2 (192.168.70.140) ── oai-upf-slice2 (192.168.70.143)
```

- `docker-compose-slicing-basic-nrf.yaml`: each slice has its **own SMF + UPF** instance
- Also includes **NSSF** (Network Slice Selection Function) for AMF-driven slice selection
- Config files per NF: `slicing_base_config.yaml` (AMF/NSSF), `slicing_slice1_config.yaml` (SMF1+UPF1), `slicing_slice2_config.yaml` (SMF2+UPF2)
- The patch changes: PLMN from MCC208/MNC95 → MCC001/MNC01; SD from `000001`→`000002` for Slice 2; DNN from `oai.ipv4`→`oai2`; removes the original 3rd slice (VPP UPF); pins all images to `:develop` tag
- `docker-compose-basic-nrf.yaml` (also patched): single SMF/UPF but using develop-branch images — a middle option

### CN Slicing Summary

| Feature | Legacy v1.5.1 | Develop: single SMF/UPF | Develop: per-slice SMF/UPF |
|---------|---------------|--------------------------|----------------------------|
| SMF instances | 1 | 1 | 2 (one per slice) |
| UPF instances | 1 | 1 | 2 (one per slice) |
| CN isolation | DNN/session only | DNN/session only | Full NF isolation |
| NSSF | No | No | Yes |
| Complexity | Low | Medium | High |

## Architecture: How RAN Slicing Works

Slicing is implemented in the **MAC DL scheduler** (`openair2/LAYER2/NR_MAC_gNB/`):

1. **Slice registration** — at gNB startup, `gnb_config.c` reads `SliceConf` from the config file into `RC.nrmac[0]->SliceConfigFile`. NSSAI info from each connected UE's PDU session populates `gNB_MAC_INST.SL_info` (a list of `NR_slice_info_t`).

2. **Per-slot scheduling** — `nr_fr1_dlsch_preprocessor()` calls `nr_slice_preprocess()` every slot, which allocates PRB budgets per slice based on `NR_slice_prb_policy_t.{min_ratio, max_ratio, dedicated_ratio}`.

3. **Policy updates** — `nr_update_slice_policy()` reads `rrmPolicy.json`, matches entries by NSSAI (sst+sd), and updates `SL->spolicy`. It is called every 1280 frames (~13 s) when the `rrmPolicyJson.patch` is applied. Without the patch, `nr_update_slice_policy()` is commented out and slicing policy is static.

4. **E2 Agent path** (xApp-driven) — the E2 Agent (`openair2/E2_AGENT/`) runs as a thread alongside the gNB. It exposes the same `NR_slice_prb_policy_t` fields over UDP using protobuf (`ran_messages.proto`). The external e2sim bridges this to OSC Near-RT RIC; the xApp sends `slicing_control_m` messages to update policy dynamically.

## Slice Identity Mapping

| Slice | SST | SD | DNN | UE IP Range | Config File |
|-------|-----|----|-----|-------------|-------------|
| Default | 1 | 0xFFFFFF | `oai` | 12.1.1.x | `nrUE_slice1.conf` |
| Slice 2 | 1 | 0x000002 | `oai2` | 12.1.2.x | `nrUE_slice2.conf` |

Both UEs share the key/OPC (`fec86ba6...` / `C42449363B...`) and differ only in IMSI and DNN.

## Key Configuration Variables

In `ORANSlice.gnb.sa.band78.fr1.106PRB.usrpx310.conf`:
- `amf_ip_address` — must match the AMF container IP (`192.168.70.132`)
- `GNB_INTERFACE_NAME_FOR_NG_AMF` — must be `"demo-oai"` (the Docker bridge)
- `GNB_IPV4_ADDRESS_FOR_NG_AMF` — host's IP on the demo-oai bridge (`192.168.70.129/24`)
- `SliceConf` — **absolute path** to `rrmPolicy.json`; defaults to `/home/wineslab/ORANSlice/rrmPolicy.json` and must be updated to the actual deployment path

## Enabling Slice Policy File Updates

The patch `doc/rrmPolicyJson.patch` must be applied to test slicing without the full xApp/RIC stack:

```bash
cd ORANSlice/
git apply doc/rrmPolicyJson.patch
```

This uncomments the `nr_update_slice_policy()` call in `gNB_scheduler_dlsch.c:1601` and creates `rrmPolicy.json` at the repo root.

## E2 Agent Protocol

The E2 Agent communicates with the external `e2sim` via **UDP**:
- gNB → e2sim: port 6600 (`E2AGENT_OUT_PORT`)
- e2sim → gNB: port 6655 (`E2AGENT_IN_PORT`)

Messages are serialized with protobuf-c using the schema in `oai-oran-protolib/ran_messages.proto`. The `slicing_control_m` message carries `{sst, sd, min_ratio, max_ratio}` and maps directly to `NR_slice_prb_policy_t` fields.

## Dependency: protobuf-c

protobuf-c must be installed from source before building OAI RAN (the system package is too old):
```bash
git clone https://github.com/protobuf-c/protobuf-c
cd protobuf-c && ./autogen.sh && ./configure && make && sudo make install && sudo ldconfig
```
