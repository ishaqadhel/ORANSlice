# How to Run ORANSlice on a Single Ubuntu VM

This guide walks you through setting up a complete 5G network slicing system using ORANSlice on a **single Ubuntu 22.04 VM** — no special hardware needed. You will run:

- **OAI Core Network (CN)** — the "brain" of the 5G network, runs in Docker
- **OAI gNB** — the 5G base station (gNodeB), runs natively in software simulation mode
- **OAI nrUE** — the 5G User Equipment / phone emulator, runs natively

> **What is RFSim?** Instead of needing actual radio hardware (expensive USRP devices), we use "RFSim" (Radio Frequency Simulator) — a software mode where the gNB and UE communicate over a loopback socket (127.0.0.1). This is perfect for learning and development.

---

## Table of Contents

1. [Concepts for Beginners](#1-concepts-for-beginners)
2. [System Requirements](#2-system-requirements)
3. [Step 0: Clone the Repository](#step-0-clone-the-repository)
4. [Step 1: Install Docker](#step-1-install-docker)
5. [Step 2: Set Up the OAI Core Network](#step-2-set-up-the-oai-core-network)
6. [Step 3: Install Build Dependencies for OAI RAN](#step-3-install-build-dependencies-for-oai-ran)
7. [Step 4: Build OAI gNB and nrUE](#step-4-build-oai-gnb-and-nrue)
8. [Step 5: Configure the gNB Config File](#step-5-configure-the-gnb-config-file)
9. [Step 6: Run the gNB](#step-6-run-the-gnb)
10. [Step 7: Run Multiple UEs Using Network Namespaces](#step-7-run-multiple-ues-using-network-namespaces)
11. [Step 8: Verify Both UEs Connectivity](#step-8-verify-both-ues-connectivity)
12. [Step 9: Network Slicing with ORANSlice](#step-9-network-slicing-with-oranslice)
13. [Step 10: Core Network Slicing (Advanced)](#step-10-core-network-slicing-advanced)
14. [Step 11: UE Management with the CLI](#step-11-ue-management-with-the-cli)
15. [Step 12: Stop and Restart Everything](#step-12-stop-and-restart-everything)
16. [Appendix A: Single UE Test](#appendix-a-single-ue-test)

---

## 1. Concepts for Beginners

Before running anything, here is a quick glossary of terms you will encounter:

| Term | Meaning |
|------|---------|
| **gNB** | gNodeB — the 5G base station (like a cell tower) |
| **nrUE** | NR User Equipment — a simulated 5G phone |
| **AMF** | Access and Mobility Management Function — handles UE registration |
| **SMF** | Session Management Function — manages data sessions |
| **UPF** | User Plane Function — routes user data traffic |
| **IMSI** | Subscriber identity (like a SIM card number) |
| **PLMN** | Public Land Mobile Network — identified by MCC+MNC (e.g., MCC=001, MNC=01) |
| **NSSAI** | Network Slice Selection Assistance Information — identifies a slice |
| **SST** | Slice/Service Type — part of NSSAI (e.g., 1 = eMBB) |
| **SD** | Slice Differentiator — part of NSSAI to distinguish slices with same SST |
| **DNN** | Data Network Name — like an APN in 4G (e.g., "oai", "oai2") |
| **RFSim** | Radio Frequency Simulator — software radio (no hardware needed) |
| **PDU Session** | A data connection from UE to the internet through the core |

**In this setup:**
- **Slice 1**: SST=1, SD=0xFFFFFF (default), DNN=`oai`, UE IP range: 12.1.1.x
- **Slice 2**: SST=1, SD=0x000002, DNN=`oai2`, UE IP range: 12.1.2.x

---

## 2. System Requirements

- **OS**: Ubuntu 22.04 LTS (64-bit)
- **RAM**: Minimum 8 GB (16 GB recommended)
- **CPU**: 4+ cores (more cores = better performance)
- **Disk**: At least 30 GB free (OAI RAN source + build is large)
- **Network**: Internet access for pulling Docker images and packages

> **Tip:** If you are using a VM in VirtualBox or VMware, make sure to allocate at least 4 CPU cores and 8 GB RAM. Enable "Nested Virtualization" if available.

---

## Step 0: Clone the Repository

Open a terminal and clone ORANSlice to your home directory:

```bash
cd ~
git clone https://github.com/wineslab/ORANSlice.git
cd ORANSlice
```

You should see these folders:
- `oai_cn/` — Core Network config and Docker compose files
- `oai_ran/` — RAN source code (gNB + nrUE)
- `doc/` — Documentation and patch files

---

## Step 1: Install Docker

The OAI Core Network runs entirely in Docker containers.

### 1.1 Install Docker Engine

```bash
# Remove any old Docker versions
sudo apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

# Install prerequisites
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release

# Add Docker's official GPG key
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Add Docker repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

### 1.2 Allow Running Docker Without sudo

```bash
sudo usermod -aG docker $USER
newgrp docker
```

> **Note:** The `newgrp docker` command applies the group change in the current shell. You may need to log out and log back in for it to fully take effect in all terminals.

### 1.3 Verify Docker Works

```bash
docker run hello-world
```

You should see: `Hello from Docker!`

---

## Step 2: Set Up the OAI Core Network

The Core Network (CN) consists of several Docker containers. We use the **legacy v1.5.1** configuration which is the simplest option.

### 2.1 Create the Docker Network

The gNB and CN communicate over a dedicated Docker bridge network named `demo-oai`. Create it first:

```bash
docker network create \
  --driver=bridge \
  --subnet=192.168.70.128/26 \
  --opt "com.docker.network.bridge.name"="demo-oai" \
  demo-oai-public-net
```

Verify the network was created:
```bash
docker network ls | grep demo-oai
```

### 2.2 Pull the Required Docker Images

Pull all OAI CN images upfront (this takes a few minutes depending on your internet speed):

```bash
docker pull oaisoftwarealliance/oai-amf:v1.5.1
docker pull oaisoftwarealliance/oai-smf:v1.5.1
docker pull oaisoftwarealliance/oai-nrf:v1.5.1
docker pull oaisoftwarealliance/oai-spgwu-tiny:v1.5.1
docker pull oaisoftwarealliance/oai-udr:v1.5.1
docker pull oaisoftwarealliance/oai-udm:v1.5.1
docker pull oaisoftwarealliance/oai-ausf:v1.5.1
docker pull oaisoftwarealliance/trf-gen-cn5g:latest
docker pull mysql:8.0
```

### 2.3 Start the Core Network

```bash
cd ~/ORANSlice/oai_cn/oai-cn5g-legacy/
./restart_cn.sh
```

What `restart_cn.sh` does internally:
1. Stops any running CN containers
2. Starts all containers (mysql, oai-nrf, oai-udr, oai-udm, oai-ausf, oai-amf, oai-smf, oai-spgwu-tiny, oai-ext-dn)
3. Waits for `oai-spgwu-tiny` to be healthy (health check loop)
4. Waits for MySQL to have subscriber data populated (UDR readiness check)
5. Adds a secondary IP address (`12.1.2.1/24`) to the UPF container for Slice 2
6. Adds masquerade rule for Slice 2 traffic

> **Important:** `restart_cn.sh` takes ~2–3 minutes because it waits for the database to be fully initialized before declaring the CN ready. Do not start the gNB until the script prints `[restart_cn] Core Network ready.`

> **DB persistence:** Subscriber data (including CLI-created UEs) is stored in a named Docker volume (`oai_db_data`) that survives restarts. To reset the database to the factory SQL: `docker compose -f docker-compose-legacy.yml down -v`

### 2.4 Verify the Core Network Is Running

```bash
docker ps -a
```

You should see all these containers with status `Up`:

```
CONTAINER ID  IMAGE                                    STATUS   NAMES
...           oaisoftwarealliance/trf-gen-cn5g:latest  Up       oai-ext-dn
...           oaisoftwarealliance/oai-spgwu-tiny:v1.5.1 Up     oai-spgwu-tiny
...           oaisoftwarealliance/oai-smf:v1.5.1       Up       oai-smf
...           oaisoftwarealliance/oai-amf:v1.5.1       Up       oai-amf
...           oaisoftwarealliance/oai-ausf:v1.5.1      Up       oai-ausf
...           oaisoftwarealliance/oai-udm:v1.5.1       Up       oai-udm
...           oaisoftwarealliance/oai-udr:v1.5.1       Up       oai-udr
...           oaisoftwarealliance/oai-nrf:v1.5.1       Up       oai-nrf
...           mysql:8.0                                 Up       mysql
```

> **If any container shows "Exited":** Wait 30 seconds and run `docker ps -a` again — some containers take time to become healthy. If a container keeps restarting, check its logs with `docker logs <container-name>`.

### 2.5 Check AMF Is Ready

The AMF is the most important CN function. Verify it started correctly:

```bash
docker logs oai-amf 2>&1 | grep -i "registered\|ready\|started" | tail -5
```

You should see messages indicating it registered with the NRF and is ready.

### 2.6 Verify the CN Network Interface Exists

Since the gNB will use the `demo-oai` bridge interface, verify it exists on your host:

```bash
ip addr show demo-oai
```

You should see an interface with IP in the `192.168.70.128/26` subnet. Note the host IP (typically `192.168.70.129` or the first available address).

---

## Step 3: Install Build Dependencies for OAI RAN

Install all software needed to compile OAI gNB and nrUE.

### 3.1 Install protobuf-c (Required for E2 Agent)

```bash
sudo apt-get update
sudo apt-get install -y protobuf-compiler libprotoc-dev autoconf automake libtool

sudo apt install -y autoconf automake libtool make gcc g++ pkg-config

sudo apt install -y build-essential g++ clang

sudo apt install -y \
  build-essential \
  pkg-config \
  autoconf \
  automake \
  libtool \
  curl \
  git

git clone https://github.com/protobuf-c/protobuf-c
cd protobuf-c
./autogen.sh
./configure
make
sudo make install
sudo ldconfig
cd ~
```

### 3.2 Install UHD (USRP Hardware Driver) — Required Even for RFSim

Even though we use software simulation, the build system requires UHD headers:

```bash
sudo apt-get install -y libuhd-dev uhd-host
```

### 3.3 Run OAI's Dependency Installer

OAI provides an automated dependency script:

```bash
cd ~/ORANSlice/oai_ran/cmake_targets/
./build_oai -I
```

> **This step takes 5–15 minutes.** It installs all required libraries (libsctp, libssl, libcurl, cmake, etc.). Say `Y` if it asks for confirmation.

---

## Step 4: Build OAI gNB and nrUE

### 4.1 Build Both gNB and nrUE

From the `cmake_targets` directory, build both binaries:

```bash
cd ~/ORANSlice/oai_ran/cmake_targets/
./build_oai -w USRP --ninja --gNB --nrUE
```

- `-w USRP` — includes USRP drivers AND enables RFSim support
- `--ninja` — faster build using Ninja instead of Make
- `--gNB` — build the gNodeB binary
- `--nrUE` — build the NR UE binary

> **This step takes 20–60 minutes** depending on your CPU. The build compiles millions of lines of C code.

You will know the build succeeded when you see:
```
BUILD SHOULD BE SUCCESSFUL
```

### 4.2 Verify the Binaries Exist

```bash
ls -la ~/ORANSlice/oai_ran/cmake_targets/ran_build/build/nr-softmodem
ls -la ~/ORANSlice/oai_ran/cmake_targets/ran_build/build/nr-uesoftmodem
```

Both files should exist and have non-zero size.

---

## Step 5: Configure the gNB Config File

### 5.1 Create the Slicing Policy File

Create `rrmPolicy.json` at the repo root:

```bash
cat > ~/ORANSlice/rrmPolicy.json << 'EOF'
{
	"rrmPolicyRatio" :
	[
		{
			"sst":1,
			"dedicated_ratio":5,
			"min_ratio":10,
			"max_ratio":100
		},
		{
			"sst":1,
			"sd":1,
			"dedicated_ratio":5,
			"min_ratio":10,
			"max_ratio":100
		},
		{
			"sst":1,
			"sd":2,
			"dedicated_ratio":5,
			"min_ratio":10,
			"max_ratio":100
		}
	]
}
EOF
```

> **Note:** Optionally apply `doc/rrmPolicyJson.patch` to enable dynamic policy reloading (requires rebuilding OAI). For basic testing, the file above is sufficient.

### 5.2 Update the Path in the gNB Config

The gNB config file's `SliceConf` must point to the correct path. Update it:

```bash
ORAN_PATH="$HOME/ORANSlice"
CONFIG_FILE="$ORAN_PATH/oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF/ORANSlice.gnb.sa.band78.fr1.106PRB.usrpx310.conf"

# Update the SliceConf path
sed -i "s|SliceConf = \".*\"|SliceConf = \"$ORAN_PATH/rrmPolicy.json\"|" "$CONFIG_FILE"

# Verify the change
grep "SliceConf" "$CONFIG_FILE"
```

Expected output:
```
SliceConf = "/home/YOUR_USERNAME/ORANSlice/rrmPolicy.json";
```

### 5.3 Understand the Network Interface Setup

The gNB config specifies:
```
GNB_INTERFACE_NAME_FOR_NG_AMF = "demo-oai";
GNB_IPV4_ADDRESS_FOR_NG_AMF   = "192.168.70.129/24";
```

This means the gNB will communicate with the AMF (at `192.168.70.132`) through the `demo-oai` Docker bridge interface. This works because:
- The `demo-oai` bridge was created in Step 2.1
- The AMF container is on `192.168.70.132` in this bridge network
- The host machine gets IP `192.168.70.129` on this bridge (the gNB uses this)

Verify your host machine has the correct IP on `demo-oai`:
```bash
ip addr show demo-oai | grep "inet "
```

If the IP shown is not `192.168.70.129`, update the `GNB_IPV4_ADDRESS_FOR_NG_AMF` value in the config file accordingly.

---

## Step 6: Run the gNB

Use the provided script to start the gNB in the background:

```bash
cd ~/ORANSlice
sudo ./start_ran.sh
```

This launches the gNB with output to `/tmp/gnb.log`.

**Wait ~20 seconds**, then verify the gNB associated with the AMF:
```bash
grep "NGAP_REGISTER_GNB_CNF" /tmp/gnb.log
```

Expected output:
```
[GNB_APP]   [gNB 0] Received NGAP_REGISTER_GNB_CNF: associated AMF 1
```

Monitor live: `tail -f /tmp/gnb.log | grep -E 'AMF|RRC|NGAP|ERROR'`

> **If you see "Connection refused" or NGAP errors:** The CN may not be fully ready. Wait 30 more seconds and restart the gNB.

---

## Step 7: Run Multiple UEs Using Network Namespaces

For the slicing demo, you need **two UEs running simultaneously**. OAI nrUE only allows one UE per machine by default (they all try to use `oaitun_ue1`). To run **multiple UEs at the same time**, we use **network namespaces**.

### 7.1 What Are Network Namespaces?

**Network namespaces** are a **Linux kernel feature** that provides isolation of network resources. Think of it as a **virtual bubble** of network resources:

- Each namespace has its own: network interfaces, IP addresses, routing tables, firewall rules, ports
- Processes running inside a namespace can only see/modify resources in that namespace
- This is the same technology that Docker uses internally to isolate containers

**Without namespaces (the problem):**
```
Host machine
└── oaitun_ue1 (only ONE exists, IP either 12.1.1.x OR 12.1.2.x)

Both UEs try to bind to the same oaitun_ue1 — the second UE overwrites the first's IP.
```

**With namespaces (the solution):**
```
Host machine
├── namespace ue1
│   └── oaitun_ue1 → IP 12.1.1.2 (Slice 1)
│
└── namespace ue2
    └── oaitun_ue1 → IP 12.1.2.2 (Slice 2)
```

Each namespace has its **own isolated `oaitun_ue1`** with a different IP — no conflict.

**Key commands:**
```bash
ip netns list              # list all namespaces
ip netns exec ue1 <cmd>    # run command inside namespace ue1
```

**The gNB** runs on the host network (not in any namespace) and communicates with both UEs via their different RFsim server addresses (`10.201.1.100` vs `10.202.1.100`).

> **Note:** This step is required for running 2 UEs simultaneously. If you only need to test a single UE first, see [Appendix A: Single UE Test](#appendix-a-single-ue-test) at the bottom of this guide.

### 7.2 Critical: Start UEs Sequentially (One at a Time)

> **Important:** OAI RFSim has a known instability when multiple UEs connect simultaneously. Always start UEs one at a time, waiting for each to receive a PDU session (get an IP on `oaitun_ue1`) before starting the next one.

Use the provided `run_ues.sh` script which handles this automatically:

```bash
cd ~/ORANSlice
CONFDIR="oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF"

sudo ./run_ues.sh \
  "1:$CONFDIR/nrUE_slice1.conf" \
  "2:$CONFDIR/nrUE_slice2.conf"
```

The script creates namespaces, starts each UE, and waits for its PDU session before starting the next. Expected output:

```
[start_ue] creating namespace ue1
[start_ue] starting UE in ue1 → 10.201.1.100  conf: nrUE_slice1.conf
[start_ue] UE PID 12345 — waiting for PDU session (oaitun_ue1)...
[start_ue] ue1 connected — oaitun_ue1 12.1.1.2/24  log: /tmp/ue1.log
[start_ue] creating namespace ue2
[start_ue] starting UE in ue2 → 10.202.1.100  conf: nrUE_slice2.conf
[start_ue] UE PID 12367 — waiting for PDU session (oaitun_ue1)...
[start_ue] ue2 connected — oaitun_ue1 12.1.2.2/24  log: /tmp/ue2.log
[run_ues] all UEs connected.
```

### 7.3 Manual UE Launch (alternative to run_ues.sh)

If you prefer manual control, create each namespace and start each UE individually, waiting between them:

**Create namespace ue1 and start UE Slice 1:**

```bash
sudo bash oai_ran/tools/scripts/multi-ue.sh -c1
sudo ./start_ue.sh 1 oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF/nrUE_slice1.conf
```

Wait for `[start_ue] ue1 connected`, then:

**Create namespace ue2 and start UE Slice 2:**

```bash
sudo ./start_ue.sh 2 oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF/nrUE_slice2.conf
```

---

## Step 8: Verify Both UEs Connectivity

After both UEs connect, check the gNB logs — you should see both UEs registered with their respective slices:

```
Active slices for UE 563b = [ 1 ]   # Slice 1 UE
Active slices for UE e13d = [ 2 ]   # Slice 2 UE
```

### 8.1 Verify Each UE's IP Address

```bash
# Check UE1 (Slice 1 — should be 12.1.1.x)
ip netns exec ue1 ip addr show oaitun_ue1 | grep inet

# Check UE2 (Slice 2 — should be 12.1.2.x)
ip netns exec ue2 ip addr show oaitun_ue1 | grep inet
```

### 8.2 Test Connectivity Per Slice

```bash
# Test Slice 1 UE — ping oai-ext-dn (CN side)
ip netns exec ue1 ping -I oaitun_ue1 -c 5 192.168.70.135

# Test Slice 2 UE — ping oai-ext-dn (CN side)
ip netns exec ue2 ping -I oaitun_ue1 -c 5 192.168.70.135

# Test internet connectivity from both UEs
ip netns exec ue1 ping -I oaitun_ue1 -c 5 8.8.8.8
ip netns exec ue2 ping -I oaitun_ue1 -c 5 8.8.8.8
```

### 8.3 iperf3 Throughput Test

**Start the iperf3 server in oai-ext-dn (Terminal 4):**
```bash
docker exec -it oai-ext-dn iperf3 -s
```

**Run iperf3 for Slice 1:**
```bash
ip netns exec ue1 iperf3 -c 192.168.70.135 -B 12.1.1.x -t 60 -i 5
```

**Run iperf3 for Slice 2 (second server instance needed):**
```bash
docker exec -it oai-ext-dn iperf3 -s -p 5202 &
ip netns exec ue2 iperf3 -c 192.168.70.135 -B 12.1.2.x -t 60 -i 5 -p 5202
```

---

## Step 9: Network Slicing with ORANSlice

ORANSlice controls **RAN slicing** by dividing radio resources (Physical Resource Blocks) among slices. The slicing policy is defined in `rrmPolicy.json`.

### 9.1 Understand the Slicing Policy File

```bash
cat ~/ORANSlice/rrmPolicy.json
```

Output:
```json
{
  "rrmPolicyRatio": [
    {
      "sst": 1,
      "dedicated_ratio": 5,
      "min_ratio": 10,
      "max_ratio": 100
    },
    {
      "sst": 1,
      "sd": 1,
      "dedicated_ratio": 5,
      "min_ratio": 10,
      "max_ratio": 100
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

**Fields explained:**
- `sst` — Slice Service Type
- `sd` — Slice Differentiator (omitted = default/0xFFFFFF)
- `dedicated_ratio` — minimum guaranteed PRB ratio (%) for this slice
- `min_ratio` — minimum PRB ratio the scheduler can assign
- `max_ratio` — maximum PRB ratio the scheduler can assign

> **Note:** Dynamic policy reloading (gNB reads this file every ~13s) requires applying `doc/rrmPolicyJson.patch` and rebuilding OAI. Without the patch, the policy is read at startup only.

### 9.2 Test Slice Prioritization

**Scenario: Give Slice 1 priority over Slice 2**

Make sure both UEs are connected and running iperf3 traffic simultaneously. Then edit `rrmPolicy.json`:

```bash
nano ~/ORANSlice/rrmPolicy.json
```

Change the ratios so Slice 1 (sd=0xFFFFFF, omitted) gets 80% and Slice 2 (sd=2) gets 20%:

```json
{
  "rrmPolicyRatio": [
    {
      "sst": 1,
      "dedicated_ratio": 5,
      "min_ratio": 80,
      "max_ratio": 100
    },
    {
      "sst": 1,
      "sd": 1,
      "dedicated_ratio": 5,
      "min_ratio": 10,
      "max_ratio": 20
    },
    {
      "sst": 1,
      "sd": 2,
      "dedicated_ratio": 5,
      "min_ratio": 10,
      "max_ratio": 20
    }
  ]
}
```

Save and exit. Wait about 15 seconds for the gNB to pick up the change (no restart needed, requires patch).

### 9.3 Measure the Throughput Difference

**Terminal for Slice 1 iperf3 client:**
```bash
ip netns exec ue1 iperf3 -c 192.168.70.135 -B 12.1.1.11 -t 60 -i 5
```

**Terminal for Slice 2 iperf3 client (simultaneously):**
```bash
ip netns exec ue2 iperf3 -c 192.168.70.135 -B 12.1.2.11 -t 60 -i 5 -p 5202
```

> For the second iperf3 test, start a second server on a different port inside oai-ext-dn:
> ```bash
> docker exec -it oai-ext-dn iperf3 -s -p 5202
> ```

**Observe:** With 80%/20% ratio split, Slice 1 should achieve ~4x higher throughput than Slice 2.

**Now reverse: Give Slice 2 priority:**

Edit `rrmPolicy.json` again and swap the ratios — set Slice 1's `max_ratio` to 20 and Slice 2's `min_ratio` to 80. After ~15 seconds, observe throughput switch.

### 9.4 Verify Slicing Is Active in gNB Logs

In the gNB terminal (Terminal 1), look for slice policy update messages:

```
[MAC]   Slice policy updated from rrmPolicy.json
```

or check the MAC scheduler logs to see resource block allocations.

---

## Step 10: Core Network Slicing (Advanced)

### Understanding the ORANSlice End-to-End Framework

The diagram below (from `doc/ORANSlice_Framework.png`) shows what "end-to-end" means in ORANSlice:

```
┌─────────────────────┐        ┌────────────────────────────────────────┐
│     Near-RT RIC     │        │           Core Network                 │
│  ┌──────────────┐   │        │  ┌─── Control Plane (CP) ───────────┐  │
│  │ DB │RIC Svc  │   │        │  │   AMF    NSSF    AUSF            │  │
│  │    xApp SDK  │   │        │  └──────────────────────────────────┘  │
│  │      xApp    │   │        │  ┌─── User Plane (UP) ─────────────┐  │
└──┤              ├───┘   E2   │  │  SMF 1 ── UPF 1 (Slice 1)      │  │
   └──────────────┘ ◄──────┐  │  │  SMF 2 ── UPF 2 (Slice 2)      │──► Internet
                            │  │  └──────────────────────────────────┘  │
   ┌── DU ──────┐  ┌── CU ─┤  └────────────────────────────────────────┘
   │ ┌─────────┐│  │  RLC  │
   │ │Slice 1  ││  │RRC/PDCP│
   │ │ freq/   ││  │SDAP/  │
   │ │  time   ││  │PDCP   │
   │ │Slice 2  ││  └───────┘
   │ └─────────┘│
   │  PHY  MAC  │
   └────────────┘
   RU 🗼   UE1  UE2
```

The key architectural insight from the framework is: **slicing happens at two independent layers simultaneously**:

1. **RAN layer (DU/MAC)** — the gNB splits radio resources (PRBs) between slices in the time-frequency grid. Controlled by the Near-RT RIC via E2 interface.
2. **Core Network layer** — each slice has its own SMF + UPF pair. The control plane (AMF/NSSF/AUSF) is shared but slice-aware.

---

### What Each CN Component Does for Slicing

The ORANSlice CN adjustments are **purely configuration-based** — no CN source code is modified. Here is exactly what was changed for each NF:

#### AMF — Access and Mobility Management Function
**Role in slicing:** Receives UE registration requests, reads the UE's requested NSSAI (SST+SD), and routes it to the correct SMF via the NSSF.

**What was adjusted:**
- PLMN configured to match the gNB: `MCC=001, MNC=01, TAC=0x0001`
- Two NSSAI entries registered:
  - Slice 1: `SST=1, SD=0xFFFFFF` (default slice)
  - Slice 2: `SST=1, SD=0x000002`
- `enable_smf_selection = yes` — AMF uses NSSF/NRF to dynamically discover which SMF serves which NSSAI, instead of a static SMF list
- Authentication algorithms aligned: `NIA0, NIA1, NIA2` / `NEA0, NEA1, NEA2`

**What was NOT changed:** AMF is fully shared across slices. All UEs go through the same AMF regardless of which slice they belong to.

---

#### NSSF — Network Slice Selection Function
**Role in slicing:** When AMF receives a UE's NSSAI request, it queries the NSSF: *"which NRF should I talk to in order to find the right SMF for this slice?"* The NSSF returns a pointer to the correct NRF instance (which then leads to the correct SMF).

**What was adjusted:**
- Present **only in the develop-branch mode** (Mode 2). The legacy v1.5.1 setup does not have NSSF — the AMF resolves SMF directly via a static config.
- Configured with slice-to-NRF mapping:
  - `SST=1` (Slice 1) → `oai-nrf-slice12` → `oai-smf-slice1`
  - `SST=1, SD=000002` (Slice 2) → `oai-nrf-slice12` → `oai-smf-slice2`
- This enables **dynamic slice selection**: adding a new slice only requires updating NSSF config, not AMF config.

---

#### AUSF — Authentication Server Function
**Role in slicing:** Authenticates the UE using 5G-AKA (5G Authentication and Key Agreement). Verifies the UE's IMSI, key, and OPc against the UDM/UDR database.

**What was adjusted:** Almost nothing. AUSF is slice-unaware — authentication is independent of which slice the UE will use. The only change was aligning the PLMN (`MCC=001/MNC=01`).

**Why it is in the framework diagram:** AUSF must complete before the UE can request a PDU session for any slice. It is part of the end-to-end flow even though it has no slice-specific logic.

---

#### SMF 1 / SMF 2 — Session Management Functions (one per slice)
**Role in slicing:** Manages the entire lifecycle of a UE's PDU session — IP address assignment, QoS policy, and N4/PFCP session setup with its paired UPF.

**What was adjusted (per SMF instance):**

| Parameter | SMF 1 (Slice 1) | SMF 2 (Slice 2) |
|-----------|-----------------|-----------------|
| NSSAI served | `SST=1, SD=0xFFFFFF` | `SST=1, SD=0x000002` |
| DNN served | `oai` | `oai2` |
| UE IP pool | `12.1.1.0/24` | `12.1.2.0/24` |
| Paired UPF | `oai-upf-slice1` | `oai-upf-slice2` |
| Session AMBR | 100 Mbps UL / 400 Mbps DL | 100 Mbps UL / 400 Mbps DL |
| 5QI | 5 (eMBB / video) | 9 (best-effort) |

Each SMF only knows about its own slice's DNN and IP pool. If a UE requests `DNN=oai2` but is routed to SMF 1, SMF 1 will reject the session — this is the enforcement boundary.

---

#### UPF 1 / UPF 2 — User Plane Functions (one per slice)
**Role in slicing:** Routes all actual user data (internet traffic) for UEs in its slice. Receives GTP-U tunneled packets from the gNB (N3 interface), applies QoS rules from the SMF (N4/PFCP), and forwards to the internet (N6 interface).

**What was adjusted (per UPF instance):**

| Parameter | UPF 1 (Slice 1) | UPF 2 (Slice 2) |
|-----------|-----------------|-----------------|
| NSSAI served | `SST=1, SD=0xFFFFFF` | `SST=1, SD=0x000002` |
| DNN served | `oai` | `oai2` |
| UE subnet | `12.1.1.0/24` | `12.1.2.0/24` |
| Container IP | `192.168.70.142` | `192.168.70.143` |

Because each UPF only holds PFCP sessions for its own slice's UEs, traffic from Slice 2 UEs can never accidentally traverse UPF 1. This is the **data-plane isolation** boundary.

---

### Summary: Which Components Are Shared vs. Per-Slice

```
┌──────────────────────┬───────────────────────────────────────────────┐
│   CN Component       │  Shared or Per-Slice?                         │
├──────────────────────┼───────────────────────────────────────────────┤
│ AMF                  │ SHARED — all UEs register here                │
│ NSSF                 │ SHARED — routes to correct SMF, slice-aware   │
│ AUSF                 │ SHARED — authentication is slice-independent  │
│ UDM / UDR            │ SHARED — subscriber database                  │
│ NRF                  │ SHARED — NF registry (one per slice group)    │
│ SMF                  │ PER-SLICE — one SMF per slice                 │
│ UPF                  │ PER-SLICE — one UPF per slice                 │
└──────────────────────┴───────────────────────────────────────────────┘
```

The design principle is: **control plane signalling is centralized** (one AMF for all UEs is more efficient), while **user plane processing is isolated** (separate SMF/UPF per slice prevents cross-slice interference in data forwarding and QoS enforcement).

Everything in Steps 1–10 already uses **Core Network slicing** — but in its simplest form. This step explains the difference between the two CN slicing modes and shows you how to upgrade to true, dedicated-NF-per-slice CN slicing.

### 10.1 Understand the Two Modes of CN Slicing

The term "CN slicing" can mean two different things, and ORANSlice supports both:

**Mode 1 — Session-level CN slicing (what you already have)**

```
UE1 (Slice 1, DNN=oai)  ──┐
                            ├── gNB ── AMF ── SMF ── UPF ── Internet
UE2 (Slice 2, DNN=oai2) ──┘              (one of each)
```

- A **single SMF and single UPF** handle both slices
- Slices are separated at the **session level** only: each UE gets a different DNN (`oai` vs `oai2`) and a different IP pool (`12.1.1.x` vs `12.1.2.x`)
- The AMF selects the correct DNN based on the UE's NSSAI, but the actual session functions (SMF/UPF) are shared
- This is what the legacy v1.5.1 setup (Steps 1–10) provides
- **Limitation**: a bug or overload in the shared SMF/UPF affects all slices simultaneously

**Mode 2 — Dedicated NF per slice (true CN slicing)**

```
UE1 (Slice 1) ──┐
                  ├── gNB ── AMF ─── NSSF ─── SMF-slice1 ── UPF-slice1 ── Internet
UE2 (Slice 2) ──┘                     └────── SMF-slice2 ── UPF-slice2 ── Internet
```

- Each slice gets its **own SMF and UPF** Docker containers
- An **NSSF** (Network Slice Selection Function) helps the AMF pick the right SMF for each UE's requested slice
- A failure or configuration change in SMF-slice2 does **not** affect Slice 1 at all
- This uses OAI CN develop branch (v2.0.1+) with the `dev_oai5gcn.patch` from this repository

| What is isolated | Mode 1 (Legacy) | Mode 2 (Develop) |
|-----------------|-----------------|------------------|
| IP address pool | Yes (different DNN) | Yes (different UPF) |
| QoS policy | Partly (per-DNN) | Yes (per-SMF) |
| Session management | No (shared SMF) | Yes (dedicated SMF) |
| User plane routing | No (shared UPF) | Yes (dedicated UPF) |
| Fault isolation | No | Yes |

> **Which mode should you use?** For learning and basic testing, Mode 1 is sufficient. Use Mode 2 if you need to study how CN functions are separated per slice, or to match the full end-to-end ORANSlice architecture from the paper.

---

### 10.2 Set Up Mode 2: Dedicated SMF + UPF Per Slice

**Prerequisites:** You still need everything from Steps 1–4 (Docker, OAI RAN built, gNB/UE configured). You will only **replace the Core Network** — the gNB and nrUE commands do not change.

#### 10.2.1 Stop the Legacy CN

If the legacy CN is running, stop it first:

```bash
cd ~/ORANSlice/oai_cn/oai-cn5g-legacy/
./stop_cn.sh
```

#### 10.2.2 Clone the OAI CN Develop Repository

The `dev_oai5gcn.patch` applies to the upstream `oai-cn5g-fed` repo at tag `v2.0.1`:

```bash
cd ~
git clone https://gitlab.eurecom.fr/oai/cn5g/oai-cn5g-fed.git
cd oai-cn5g-fed
git checkout v2.0.1
```

#### 10.2.3 Apply the ORANSlice Patch

```bash
git apply ~/ORANSlice/oai_cn/dev_oai5gcn.patch
```

What the patch changes:
- PLMN from MCC=208/MNC=95 → **MCC=001/MNC=01** (matches the gNB and UE configs)
- Slice 2 SD from `000001` → **`000002`** (matches `nrUE_slice2.conf`)
- DNN for Slice 2 from `oai.ipv4` → **`oai2`** (matches `nrUE_slice2.conf`)
- Slice 1 IP pool: **`12.1.1.0/24`** (SMF1 + UPF1)
- Slice 2 IP pool: **`12.1.2.0/24`** (SMF2 + UPF2)
- Removes the original 3rd slice (VPP-based UPF)
- Pins all container images to `:develop` tag
- Adds UE subscriber data for IMSIs `001010000010776` (Slice 1) and `001010000010777` (Slice 2)

#### 10.2.4 Pull the Develop Branch Docker Images

```bash
docker pull oaisoftwarealliance/oai-amf:develop
docker pull oaisoftwarealliance/oai-smf:develop
docker pull oaisoftwarealliance/oai-upf:develop
docker pull oaisoftwarealliance/oai-nrf:develop
docker pull oaisoftwarealliance/oai-udr:develop
docker pull oaisoftwarealliance/oai-udm:develop
docker pull oaisoftwarealliance/oai-ausf:develop
docker pull oaisoftwarealliance/oai-nssf:develop
docker pull oaisoftwarealliance/trf-gen-cn5g:latest
docker pull mysql:8.0
```

> **Note:** The `:develop` tag is a rolling release. Images pulled at different times may behave differently. If you encounter issues, check the OAI CN release notes.

#### 10.2.5 Start the Per-Slice CN

```bash
cd ~/oai-cn5g-fed/docker-compose/
docker compose -f docker-compose-slicing-basic-nrf.yaml up -d
```

#### 10.2.6 Verify All Containers Are Running

```bash
docker ps -a
```

You should see these containers (all `Up`):

```
NAMES
oai-ext-dn
oai-upf-slice2    (192.168.70.143) ← dedicated UPF for Slice 2
oai-upf-slice1    (192.168.70.142) ← dedicated UPF for Slice 1
oai-smf-slice2    (192.168.70.140) ← dedicated SMF for Slice 2
oai-smf-slice1    (192.168.70.139) ← dedicated SMF for Slice 1
oai-amf           (192.168.70.132) ← same IP as before, gNB config unchanged
oai-ausf          (192.168.70.130)
oai-udm           (192.168.70.134)
oai-udr           (192.168.70.133)
oai-nrf-slice12   (192.168.70.136)
oai-nssf          (192.168.70.138) ← new: Network Slice Selection Function
mysql             (192.168.70.131)
```

> **Important:** The AMF IP remains `192.168.70.132` — the same as in the legacy setup. **No changes are needed** to the gNB config file (`ORANSlice.gnb.sa.band78.fr1.106PRB.usrpx310.conf`).

#### 10.2.7 Wait for the CN to Be Ready

The NSSF and NRF need time to register all NFs. Wait about 60 seconds, then check:

```bash
# Check AMF registered with NRF
docker logs oai-amf 2>&1 | grep -i "registered\|nrf" | tail -5

# Check SMF slice 1 is up
docker logs oai-smf-slice1 2>&1 | grep -i "started\|upf\|registered" | tail -5

# Check SMF slice 2 is up
docker logs oai-smf-slice2 2>&1 | grep -i "started\|upf\|registered" | tail -5
```

---

### 10.3 Run the System with the Per-Slice CN

The gNB and nrUE commands are **identical** to Steps 6–9. Run them in the same way.

---

### 10.4 Verify Per-Slice CN Isolation

This is the key step that proves true CN slicing is working.

#### Check which SMF handled each UE's session

After both UEs connect, look at SMF logs to confirm each slice went through its own SMF:

```bash
# Slice 1 UE (IMSI 001010000010776) should appear ONLY in SMF slice 1
docker logs oai-smf-slice1 2>&1 | grep -i "session\|pdu\|ue\|imsi" | tail -10

# Slice 2 UE (IMSI 001010000010777) should appear ONLY in SMF slice 2
docker logs oai-smf-slice2 2>&1 | grep -i "session\|pdu\|ue\|imsi" | tail -10
```

#### Check which UPF handles each slice's traffic

```bash
# UPF for Slice 1 should have a tun interface for 12.1.1.x
docker exec oai-upf-slice1 ip addr show | grep "12.1.1"

# UPF for Slice 2 should have a tun interface for 12.1.2.x
docker exec oai-upf-slice2 ip addr show | grep "12.1.2"
```

#### Ping test — same as before

```bash
# Slice 1 UE — traffic goes through UPF-slice1
ip netns exec ue1 ping -I oaitun_ue1 -c 5 192.168.70.135

# Slice 2 UE — traffic goes through UPF-slice2
ip netns exec ue2 ping -I oaitun_ue1 -c 5 192.168.70.135
```

#### Prove fault isolation

Stop SMF-slice2 and verify Slice 1 is completely unaffected:

```bash
# Stop the SMF for Slice 2
docker stop oai-smf-slice2

# Slice 1 UE should still ping successfully
ip netns exec ue1 ping -I oaitun_ue1 -c 5 192.168.70.135

# Slice 2 UE will lose connectivity (expected)
ip netns exec ue2 ping -I oaitun_ue1 -c 5 192.168.70.135

# Restart SMF-slice2
docker start oai-smf-slice2
```

This demonstrates that Slice 1's SMF and UPF are completely independent — a failure in the Slice 2 control plane does not affect Slice 1.

---

### 10.5 Stopping the Develop Branch CN

```bash
cd ~/oai-cn5g-fed/docker-compose/
docker compose -f docker-compose-slicing-basic-nrf.yaml down
```

---

### 10.6 Combine CN Slicing + RAN Slicing

The most complete ORANSlice demonstration combines both layers:
- **CN layer**: Dedicated SMF+UPF per slice (Mode 2 from this step)
- **RAN layer**: PRB ratio control via `rrmPolicy.json` (Step 10)

Run both simultaneously:
1. Start the per-slice CN (Step 10.2.5)
2. Apply the RAN slicing patch if not already done (Step 5.1)
3. Start the gNB and both UEs (Steps 6–7)
4. Connect both UEs, then change `rrmPolicy.json` to shift PRB allocation (Step 9.2)
5. Run iperf3 on both UEs simultaneously and observe both CN-level isolation (separate UPF logs) and RAN-level throughput differentiation

This is the full end-to-end ORANSlice system as described in the MobiCom '24 paper.

---

## Step 11: UE Management with the CLI

The `tools/cli/oranslice` CLI manages UE subscriptions, network namespaces, and RAN slice policies.

### 11.1 Set Up the CLI

```bash
cd ~/ORANSlice/tools/cli
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
chmod +x oranslice
```

> **Requires root.** The CLI handles `sudo` internally via the `oranslice` wrapper.

### 11.2 Launch the CLI

```bash
cd ~/ORANSlice/tools/cli
./oranslice
```

The CLI has an interactive menu:
- **UE Management** — list, create, delete subscriber entries + generate conf files
- **Namespace Management** — list, create, delete network namespaces
- **Slice Management** — view/update RAN slice policy, restart CN
- **System Status** — health check for all components + connectivity test

### 11.3 Adding New UEs via CLI

Use the CLI to provision a new UE. In the menu, select:
1. `UE Management` → `Create UE`
2. Enter IMSI (15 digits, e.g. `001010000010779`)
3. Use default key/OPC (matches pre-provisioned values)
4. Assign to Slice 1 or Slice 2
5. Confirm — CLI inserts DB entry and generates `nrUE_<IMSI>.conf`

After creating the UE, start it with:
```bash
cd ~/ORANSlice
# start_ue.sh <namespace_index> <conf_file>
sudo ./start_ue.sh 3 oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF/nrUE_001010000010779.conf
```

Or use `run_ues.sh` to start multiple at once (sequentially):
```bash
CONFDIR="oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF"
sudo ./run_ues.sh \
  "3:$CONFDIR/nrUE_001010000010779.conf" \
  "4:$CONFDIR/nrUE_001010000010780.conf" \
  "5:$CONFDIR/nrUE_001010000010781.conf"
```

> **DB persistence:** CLI-created UEs are stored in the `oai_db_data` named Docker volume and survive CN restarts. To reset the DB to factory state: `docker compose -f docker-compose-legacy.yml down -v`

### 11.4 Verifying New UEs

After a CLI-created UE connects, test it exactly like the built-in UEs:

```bash
# Check tunnel (replace 3 with namespace index)
ip netns exec ue3 ip addr show oaitun_ue1 | grep inet

# Ping tests
ip netns exec ue3 ping -I oaitun_ue1 -c 4 192.168.70.135  # CN
ip netns exec ue3 ping -I oaitun_ue1 -c 4 8.8.8.8          # Internet
```

---

## Step 12: Stop and Restart Everything

### 12.1 Stop All Components

```bash
cd ~/ORANSlice

# 1. Stop all UEs, gNB, and delete all namespaces
sudo ./stop_ran.sh

# 2. Stop the Core Network
sudo ./oai_cn/oai-cn5g-legacy/stop_cn.sh
```

`stop_ran.sh` handles:
- Kills `nr-uesoftmodem` (all UE processes)
- Kills `nr-softmodem` (gNB process)
- Deletes all `ueN` namespaces (calls `multi-ue.sh -d<N>` for each)
- Cleans up stale veth interfaces

`stop_cn.sh` handles:
- Runs `docker compose down` (removes containers, preserves `oai_db_data` volume)

### 12.2 Restart

```bash
cd ~/ORANSlice

# 1. Start the Core Network (waits for UDR to be ready before returning)
sudo ./oai_cn/oai-cn5g-legacy/restart_cn.sh

# 2. Start the gNB
sudo ./start_ran.sh

# Wait ~20s for gNB to associate with AMF, then start UEs
sleep 20

# 3. Start UEs (sequentially, waits for each PDU session)
CONFDIR="oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF"
sudo ./run_ues.sh \
  "1:$CONFDIR/nrUE_slice1.conf" \
  "2:$CONFDIR/nrUE_slice2.conf"
```

### 12.3 Verify After Restart

```bash
# Both UEs should have tunnel IPs
ip netns exec ue1 ip addr show oaitun_ue1 | grep inet   # 12.1.1.x
ip netns exec ue2 ip addr show oaitun_ue1 | grep inet   # 12.1.2.x

# Ping tests
ip netns exec ue1 ping -I oaitun_ue1 -c 4 192.168.70.135
ip netns exec ue2 ping -I oaitun_ue1 -c 4 8.8.8.8
```

---

## Troubleshooting

### Core Network container keeps restarting

```bash
docker logs <container-name> --tail 50
```

Common causes:
- MySQL is not ready yet (UDR tries to connect too early) — `restart_cn.sh` waits for this automatically; if it still fails, run `./restart_cn.sh` again
- The `demo-oai-public-net` network does not exist — re-run the `docker network create` command from Step 2.1

### gNB fails with "NGAP: No route to host" or connection refused

1. Verify the CN is running: `docker ps -a | grep -v Exited`
2. Verify the AMF IP is reachable: `ping -c 3 192.168.70.132`
3. Verify the `demo-oai` interface exists and has the correct IP: `ip addr show demo-oai`
4. Verify the gNB config has the correct interface name and IP:
   ```bash
   grep -A5 "NETWORK_INTERFACES" ~/ORANSlice/oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF/ORANSlice.gnb.sa.band78.fr1.106PRB.usrpx310.conf
   ```

### nrUE connects but no IP address on oaitun_ue1

The PDU session (data connection) was not established. Check:
1. The UE's DNN (`oai` for slice 1, `oai2` for slice 2) matches what is configured in the SMF
2. The UE's IMSI is in the database — check `docker logs oai-amf`
3. The SMF logs: `docker logs oai-smf | tail -30`

### UE crashes after PDU session request (race condition)

OAI RFSim can crash if multiple UEs connect simultaneously. Use `run_ues.sh` or `start_ue.sh` which wait for each UE's PDU session before starting the next one. Never launch multiple UEs in parallel.

### UE stuck in 5GMM-REG-INITIATED after CN restart

The UDR may not have been ready when authentication was attempted. Restart the UE process:
```bash
pkill -f "nr-uesoftmodem.*<conf_filename>"
sleep 3
sudo ./start_ue.sh <ns_index> <conf_file>
```

`restart_cn.sh` now waits for the database to be populated before returning, which prevents this in normal use.

### ping fails through oaitun_ue1

1. Verify the UE has an IP: `ip netns exec ueN ip addr show oaitun_ue1`
2. Verify routing: `ip netns exec ueN ip route | grep oaitun`
3. Check if the UPF has the route for the UE subnet: `docker exec oai-spgwu-tiny ip route`
4. Try adding a route manually if missing: `ip netns exec ueN sudo ip route add 12.1.1.0/24 dev oaitun_ue1`

### Build fails during `build_oai`

1. Run the dependency installer again: `./build_oai -I`
2. Check for disk space: `df -h`
3. Check for missing packages:
   ```bash
   sudo apt-get install -y build-essential cmake libsctp-dev libssl-dev libcurl4-openssl-dev
   ```

### rrmPolicy.json changes are not applied

1. Verify the file exists: `ls ~/ORANSlice/rrmPolicy.json`
2. Verify `SliceConf` in the gNB config points to the correct path: `grep SliceConf <gNB_conf_file>`
3. Dynamic reloading requires applying `doc/rrmPolicyJson.patch` and rebuilding OAI. Without the patch, the policy is read at startup only.

### CLI-created UEs lost after CN restart

With the named `oai_db_data` volume, CLI UEs now survive CN restarts. If you wiped the volume (`docker compose down -v`), you need to re-create the UEs via the CLI. The base UEs (10776, 10777 etc.) are always restored from `oai_db.sql` on fresh starts.

### Stopping Everything

To stop the entire system cleanly:

```bash
cd ~/ORANSlice
sudo ./stop_ran.sh
sudo ./oai_cn/oai-cn5g-legacy/stop_cn.sh
```

---

## Summary: Terminal Layout

When everything is running, you should have these terminal windows open:

| Terminal | Running | Command |
|----------|---------|---------|
| Terminal 1 | OAI gNB | `sudo ./start_ran.sh` (background) |
| Terminal 2 | nrUE Slice 1 (namespace ue1) | `sudo ./run_ues.sh "1:...nrUE_slice1.conf"` |
| Terminal 3 | nrUE Slice 2 (namespace ue2) | started by `run_ues.sh` above |
| Terminal 4 | iperf3 server (in Docker) | `docker exec -it oai-ext-dn iperf3 -s` |

The Core Network runs in the background via Docker.

---

## Appendix A: Single UE Test

If you only want to test a single UE (Slice 1) without setting up namespaces:

### Run the gNB

```bash
cd ~/ORANSlice
sudo ./start_ran.sh
sleep 20  # wait for AMF association
```

### Run the nrUE

```bash
sudo ./start_ue.sh 1 oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF/nrUE_slice1.conf
```

### Verify UE Connectivity

```bash
ip netns exec ue1 ip addr show oaitun_ue1    # Should show IP in 12.1.1.x range
ip netns exec ue1 ping -I oaitun_ue1 -c 5 192.168.70.135    # Test CN connectivity
ip netns exec ue1 ping -I oaitun_ue1 -c 5 8.8.8.8           # Test internet
```

### What to Look For

A successful connection shows in `/tmp/ue1.log`:
```
[NAS]   Received PDU Session Establishment Accept
[NR_RRC]   State = NR_RRC_CONNECTED
```

And in the gNB terminal:
```
[NGAP]   Initial UE Message received
[NR_RRC]   UE 0 Registration Accepted
```

---

## Next Steps

Once your basic slicing setup is working, you can explore the full ORANSlice framework:

- **E2Sim + xApp**: Automate slicing control via the O-RAN Near-RT RIC (see [README.md](README.md) for links)
- **OSC Near-RT RIC**: Deploy the O-RAN Software Community RIC for production-like testing
- **OAI Develop Branch CN**: Upgrade to dedicated SMF+UPF per slice for true CN isolation — see [Step 10](#step-10-core-network-slicing-advanced) above
- **Multiple UEs**: Run more UEs by using the CLI to create them and `run_ues.sh` to launch them. Each new UE needs a unique IMSI in the database (CLI handles this automatically).
