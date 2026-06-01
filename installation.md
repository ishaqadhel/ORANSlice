# ORANSlice — Installation Guide

One-time setup for a fresh Ubuntu 22.04 VM. Do this once; then use `how-to-run.md` to operate the system.

---

## System Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| OS | Ubuntu 22.04 LTS (64-bit) | — |
| RAM | 8 GB | 16 GB |
| CPU | 4 cores | 8+ cores |
| Disk | 30 GB free | 50 GB |
| Network | Internet access | — |

> If using VirtualBox/VMware: allocate 4+ cores, 8+ GB RAM, enable Nested Virtualization.

---

## Step 0 — Clone the Repository

```bash
cd ~
git clone https://github.com/wineslab/ORANSlice.git
cd ORANSlice
```

---

## Step 1 — Install Docker

```bash
# Remove old versions
sudo apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

# Prerequisites
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release

# GPG key + repo
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Run without sudo
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker run hello-world
```

---

## Step 2 — Create the Docker Network

The gNB and CN use a dedicated bridge (`demo-oai`). Create it once:

```bash
docker network create \
  --driver=bridge \
  --subnet=192.168.70.128/26 \
  --opt "com.docker.network.bridge.name"="demo-oai" \
  demo-oai-public-net
```

Verify:
```bash
docker network ls | grep demo-oai
ip addr show demo-oai | grep inet   # should show 192.168.70.129
```

---

## Step 3 — Pull Core Network Docker Images

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

---

## Step 4 — Install OAI RAN Build Dependencies

### 4.1 protobuf-c (required for E2 Agent)

```bash
sudo apt-get install -y \
  build-essential g++ clang pkg-config \
  autoconf automake libtool make curl git \
  protobuf-compiler libprotoc-dev

git clone https://github.com/protobuf-c/protobuf-c
cd protobuf-c
./autogen.sh && ./configure && make
sudo make install && sudo ldconfig
cd ~
```

### 4.2 UHD (USRP driver — required even for RFSim)

```bash
sudo apt-get install -y libuhd-dev uhd-host
```

### 4.3 OAI dependency installer

```bash
cd ~/ORANSlice/oai_ran/cmake_targets/
./build_oai -I
```

> Takes 5–15 minutes. Say `Y` to confirmations.

---

## Step 5 — Build OAI gNB and nrUE

```bash
cd ~/ORANSlice/oai_ran/cmake_targets/
./build_oai -w USRP --ninja --gNB --nrUE
```

> Takes 20–60 minutes. Successful when you see `BUILD SHOULD BE SUCCESSFUL`.

Verify:
```bash
ls ~/ORANSlice/oai_ran/cmake_targets/ran_build/build/nr-softmodem
ls ~/ORANSlice/oai_ran/cmake_targets/ran_build/build/nr-uesoftmodem
```

---

## Step 6 — Configure the gNB Config

The `SliceConf` path in the gNB config must match your deployment path (default is `/root/ORANSlice`; adjust if cloned elsewhere).

```bash
ORAN_PATH="$HOME/ORANSlice"
CONFIG_FILE="$ORAN_PATH/oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF/ORANSlice.gnb.sa.band78.fr1.106PRB.usrpx310.conf"

sed -i "s|SliceConf = \".*\"|SliceConf = \"$ORAN_PATH/rrmPolicy.json\"|" "$CONFIG_FILE"
grep "SliceConf" "$CONFIG_FILE"
```

Also verify the network interface config matches your `demo-oai` IP:
```bash
ip addr show demo-oai | grep "inet "
# If not 192.168.70.129, update GNB_IPV4_ADDRESS_FOR_NG_AMF in the config file
```

---

## Step 7 — Set Up the CLI

```bash
cd ~/ORANSlice/tools/cli
sudo apt-get install -y python3.10-venv   # if not already present
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
chmod +x oranslice
```

---

## Installation Complete

You now have:
- Docker + CN images ready
- `demo-oai-public-net` network created
- OAI gNB + nrUE binaries built
- gNB config pointing to `rrmPolicy.json`
- CLI venv ready

Proceed to **`how-to-run.md`** to start the system.
