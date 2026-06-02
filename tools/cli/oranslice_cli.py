#!/usr/bin/env python3
"""ORANSlice CLI — Interactive management tool for UEs and slices."""

# =============================================================================
# SECTION 1: Imports + Configuration constants
# =============================================================================

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import mysql.connector
import questionary
import yaml
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

console = Console()

REPO_ROOT       = Path.home() / "ORANSlice"
UE_CONF_DIR     = REPO_ROOT / "oai_ran/targets/PROJECTS/GENERIC-NR-5GC/CONF"
GNB_CONF_FILE   = UE_CONF_DIR / "ORANSlice.gnb.sa.band78.fr1.106PRB.usrpx310.conf"
RRM_POLICY_FILE = REPO_ROOT / "rrmPolicy.json"
MULTI_UE_SCRIPT = REPO_ROOT / "oai_ran/tools/scripts/multi-ue.sh"
CN_COMPOSE_FILE = REPO_ROOT / "oai_cn/oai-cn5g-legacy/docker-compose-legacy.yml"
CN_DIR          = REPO_ROOT / "oai_cn/oai-cn5g-legacy"

DB_HOST = "192.168.70.131"
DB_PORT = 3306
DB_USER = "test"
DB_PASS = "test"
DB_NAME = "oai_db"

DEFAULT_KEY = "fec86ba6eb707ed08905757b1bb44b8f"
DEFAULT_OPC = "C42449363BBAD02B66D16BC975D77CC1"
PLMN_ID     = "00101"
MAX_NS      = 9  # multi-ue.sh hard limit; increase if script is extended
NS_MAP_FILE = REPO_ROOT / "tools/cli/ue_ns_map.json"

SLICE_CONFIG = {
    "slice1": {"dnn": "oai",  "sst": 1, "sd": None, "subnet": "12.1.1", "sd_hex": "0xFFFFFF"},
    "slice2": {"dnn": "oai2", "sst": 1, "sd": 2,    "subnet": "12.1.2", "sd_hex": "0x000002"},
}

# =============================================================================
# SECTION 2: DB connection manager
# =============================================================================

@contextmanager
def get_db():
    conn = None
    try:
        conn = mysql.connector.connect(
            host=DB_HOST, port=DB_PORT,
            user=DB_USER, password=DB_PASS, database=DB_NAME,
            connect_timeout=5,
        )
        yield conn
    except mysql.connector.errors.InterfaceError as e:
        raise RuntimeError(
            f"Cannot reach MySQL at {DB_HOST}:{DB_PORT}. "
            f"Is the CN running?  docker ps | grep mysql\n{e}"
        )
    finally:
        if conn and conn.is_connected():
            conn.close()


# =============================================================================
# SECTION 3: UE operations
# =============================================================================

def list_ues() -> list:
    sql = """
        SELECT
            a.ueid              AS imsi,
            a.encPermanentKey   AS key_hex,
            a.encOpcKey         AS opc_hex,
            s.singleNssai       AS nssai_json,
            s.dnnConfigurations AS dnn_json
        FROM AuthenticationSubscription a
        LEFT JOIN SessionManagementSubscriptionData s
            ON a.ueid = s.ueid AND s.servingPlmnid = %s
        ORDER BY a.ueid
    """
    with get_db() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, (PLMN_ID,))
        return cur.fetchall()


def _next_free_ip(subnet_prefix: str) -> str:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT dnnConfigurations FROM SessionManagementSubscriptionData")
        used = set()
        for (dnn_json,) in cur.fetchall():
            data = json.loads(dnn_json or "{}")
            for dnn_conf in data.values():
                for addr in dnn_conf.get("staticIpAddress", []):
                    ip = addr.get("ipv4Addr", "")
                    if ip.startswith(subnet_prefix + "."):
                        used.add(ip)
    for i in range(2, 255):
        candidate = f"{subnet_prefix}.{i}"
        if candidate not in used:
            return candidate
    raise RuntimeError(f"No free IPs in {subnet_prefix}.0/24")


def _build_dnn_conf(dnn: str, static_ip: str) -> str:
    return json.dumps({
        dnn: {
            "pduSessionTypes": {"defaultSessionType": "IPV4"},
            "sscModes": {"defaultSscMode": "SSC_MODE_1"},
            "5gQosProfile": {
                "5qi": 6,
                "arp": {
                    "priorityLevel": 1,
                    "preemptCap": "NOT_PREEMPT",
                    "preemptVuln": "NOT_PREEMPTABLE",
                },
                "priorityLevel": 1,
            },
            "sessionAmbr": {"uplink": "1000Mbps", "downlink": "1000Mbps"},
            "staticIpAddress": [{"ipv4Addr": static_ip}],
        }
    })


def _write_ue_conf(imsi: str, key: str, opc: str, dnn: str, sst: int, sd) -> Path:
    sd_line = f"\nnssai_sd=0x{sd:x};" if sd is not None else ""
    content = (
        f'uicc0 = {{\n'
        f'imsi = "{imsi}";\n'
        f'key = "{key}";\n'
        f'opc= "{opc}";\n'
        f'dnn= "{dnn}";\n'
        f'nssai_sst={sst};{sd_line}\n'
        f'}}\n'
    )
    path = UE_CONF_DIR / f"nrUE_{imsi}.conf"
    path.write_text(content)
    return path


def create_ue(imsi: str, key: str, opc: str, sst: int, sd, dnn: str, static_ip: str) -> tuple:
    """Create UE in DB, write conf file, and create network namespace atomically.

    Returns (conf_path, ns_index).
    """
    insert_auth = """
        INSERT INTO AuthenticationSubscription
            (ueid, authenticationMethod, encPermanentKey, protectionParameterId,
             sequenceNumber, authenticationManagementField, algorithmId, encOpcKey, supi)
        VALUES (%s, '5G_AKA', %s, %s,
            '{"sqn":"000000000000","sqnScheme":"NON_TIME_BASED","lastIndexes":{"ausf":0}}',
            '8000', 'milenage', %s, %s)
    """
    insert_smsd = """
        INSERT INTO SessionManagementSubscriptionData
            (ueid, servingPlmnid, singleNssai, dnnConfigurations)
        VALUES (%s, %s, %s, %s)
    """
    nssai_json = json.dumps({"sst": sst, "sd": str(sd) if sd is not None else "0"})
    dnn_json = _build_dnn_conf(dnn, static_ip)

    ns_index = _next_free_ns_index()
    create_namespace(ns_index)

    conf_path = None
    try:
        with get_db() as conn:
            cur = conn.cursor()
            try:
                cur.execute(insert_auth, (imsi, key, key, opc, imsi))
                cur.execute(insert_smsd, (imsi, PLMN_ID, nssai_json, dnn_json))
                conn.commit()
            except mysql.connector.IntegrityError:
                conn.rollback()
                raise ValueError(f"UE with IMSI {imsi} already exists in DB")
            except Exception:
                conn.rollback()
                raise

        conf_path = _write_ue_conf(imsi, key, opc, dnn, sst, sd)
    except Exception:
        delete_namespace(ns_index)
        raise

    ns_map = _load_ns_map()
    ns_map[imsi] = ns_index
    _save_ns_map(ns_map)

    return conf_path, ns_index


def delete_ue(imsi: str) -> None:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM AuthenticationSubscription WHERE ueid = %s", (imsi,))
        deleted_auth = cur.rowcount
        cur.execute("DELETE FROM SessionManagementSubscriptionData WHERE ueid = %s", (imsi,))
        if deleted_auth == 0:
            conn.rollback()
            raise ValueError(f"IMSI {imsi} not found in DB")
        conn.commit()

    conf_path = UE_CONF_DIR / f"nrUE_{imsi}.conf"
    if conf_path.exists():
        conf_path.unlink()

    ns_map = _load_ns_map()
    ns_index = ns_map.pop(imsi, None)
    if ns_index is not None:
        try:
            delete_namespace(ns_index)
        except (ValueError, RuntimeError):
            pass
        _save_ns_map(ns_map)


# =============================================================================
# SECTION 4: Namespace operations
# =============================================================================

def list_namespaces() -> list:
    result = subprocess.run(["ip", "netns", "list"], capture_output=True, text=True)
    return [line.split()[0] for line in result.stdout.splitlines() if line.strip()]


def _load_ns_map() -> dict:
    if NS_MAP_FILE.exists():
        return json.loads(NS_MAP_FILE.read_text())
    return {}


def _save_ns_map(m: dict) -> None:
    NS_MAP_FILE.write_text(json.dumps(m, indent=2))


def _next_free_ns_index() -> int:
    mapped = set(_load_ns_map().values())
    live = {int(ns[2:]) for ns in list_namespaces() if ns.startswith("ue") and ns[2:].isdigit()}
    used = mapped | live
    for n in range(1, MAX_NS + 1):
        if n not in used:
            return n
    raise RuntimeError(f"All {MAX_NS} namespace slots are in use")


def create_namespace(n: int) -> None:
    if n < 1 or n > MAX_NS:
        raise ValueError(f"Namespace index must be 1–{MAX_NS} (multi-ue.sh limit)")
    if not MULTI_UE_SCRIPT.exists():
        raise FileNotFoundError(
            f"multi-ue.sh not found at {MULTI_UE_SCRIPT}.\n"
            "Clone OAI full repo and copy: cp oai_full/tools/scripts/multi-ue.sh "
            f"{MULTI_UE_SCRIPT}"
        )
    if f"ue{n}" in list_namespaces():
        raise ValueError(f"Namespace ue{n} already exists")
    result = subprocess.run(
        ["bash", str(MULTI_UE_SCRIPT), f"-c{n}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"multi-ue.sh -c{n} failed:\n{result.stderr}")


def delete_namespace(n: int) -> None:
    if not MULTI_UE_SCRIPT.exists():
        raise FileNotFoundError(f"multi-ue.sh not found at {MULTI_UE_SCRIPT}")
    if f"ue{n}" not in list_namespaces():
        raise ValueError(f"Namespace ue{n} does not exist")
    result = subprocess.run(
        ["bash", str(MULTI_UE_SCRIPT), f"-d{n}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"multi-ue.sh -d{n} failed:\n{result.stderr}")


# =============================================================================
# SECTION 5: RAN slice operations (rrmPolicy.json)
# =============================================================================

def _load_rrm() -> dict:
    if not RRM_POLICY_FILE.exists():
        raise FileNotFoundError(
            f"{RRM_POLICY_FILE} not found.\n"
            "Apply the patch first:  git apply doc/rrmPolicyJson.patch"
        )
    return json.loads(RRM_POLICY_FILE.read_text())


def _save_rrm(data: dict) -> None:
    RRM_POLICY_FILE.write_text(json.dumps(data, indent="\t"))


def _validate_ratios(dedicated: int, min_r: int, max_r: int) -> None:
    if not all(0 <= v <= 100 for v in (dedicated, min_r, max_r)):
        raise ValueError("All ratios must be 0–100")
    if min_r > max_r:
        raise ValueError("min_ratio cannot exceed max_ratio")


def list_ran_slices() -> list:
    if not RRM_POLICY_FILE.exists():
        return []
    return _load_rrm().get("rrmPolicyRatio", [])


def create_ran_slice(sst: int, sd, dedicated_ratio: int, min_ratio: int, max_ratio: int) -> None:
    _validate_ratios(dedicated_ratio, min_ratio, max_ratio)
    data = _load_rrm()
    for entry in data["rrmPolicyRatio"]:
        if entry["sst"] == sst and entry.get("sd") == sd:
            raise ValueError(f"RAN slice SST={sst} SD={sd} already exists")
    new_entry = {"sst": sst, "dedicated_ratio": dedicated_ratio,
                 "min_ratio": min_ratio, "max_ratio": max_ratio}
    if sd is not None:
        new_entry["sd"] = sd
    data["rrmPolicyRatio"].append(new_entry)
    _save_rrm(data)


def update_ran_slice(sst: int, sd, dedicated_ratio: int, min_ratio: int, max_ratio: int) -> None:
    _validate_ratios(dedicated_ratio, min_ratio, max_ratio)
    data = _load_rrm()
    for entry in data["rrmPolicyRatio"]:
        if entry["sst"] == sst and entry.get("sd") == sd:
            entry["dedicated_ratio"] = dedicated_ratio
            entry["min_ratio"] = min_ratio
            entry["max_ratio"] = max_ratio
            _save_rrm(data)
            return
    raise ValueError(f"RAN slice SST={sst} SD={sd} not found")


def delete_ran_slice(sst: int, sd) -> None:
    data = _load_rrm()
    original_len = len(data["rrmPolicyRatio"])
    data["rrmPolicyRatio"] = [
        e for e in data["rrmPolicyRatio"]
        if not (e["sst"] == sst and e.get("sd") == sd)
    ]
    if len(data["rrmPolicyRatio"]) == original_len:
        raise ValueError(f"RAN slice SST={sst} SD={sd} not found")
    _save_rrm(data)


# =============================================================================
# SECTION 6: CN slice operations (legacy read-only + restart)
# =============================================================================

def list_cn_slices() -> list:
    if not CN_COMPOSE_FILE.exists():
        return []
    data = yaml.safe_load(CN_COMPOSE_FILE.read_text())
    smf_env_raw = data.get("services", {}).get("oai-smf", {}).get("environment", [])
    smf_env = {}
    for item in smf_env_raw:
        if isinstance(item, str) and "=" in item:
            k, v = item.split("=", 1)
            smf_env[k.strip()] = v.strip()
        elif isinstance(item, dict):
            smf_env.update(item)

    slices = []
    i = 0
    while f"DNN_NI{i}" in smf_env:
        slices.append({
            "index": i,
            "dnn": smf_env[f"DNN_NI{i}"],
            "sst": smf_env.get(f"NSSAI_SST{i}", "?"),
            "sd": smf_env.get(f"NSSAI_SD{i}", "default"),
            "ip_range": smf_env.get(f"DNN_RANGE{i}", "?"),
            "ambr_ul": smf_env.get(f"SESSION_AMBR_UL{i}", "?"),
            "ambr_dl": smf_env.get(f"SESSION_AMBR_DL{i}", "?"),
        })
        i += 1
    return slices


def restart_cn() -> None:
    script = CN_DIR / "restart_cn.sh"
    if not script.exists():
        raise FileNotFoundError(f"restart_cn.sh not found at {script}")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Restarting Core Network (this takes 30–60s)...", total=None)
        result = subprocess.run(
            ["bash", str(script)],
            cwd=str(CN_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )
    if result.returncode != 0:
        raise RuntimeError(f"restart_cn.sh failed:\n{result.stderr}")


# =============================================================================
# SECTION 7: Status and health checks
# =============================================================================

def system_status() -> dict:
    status = {}

    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM AuthenticationSubscription")
            count = cur.fetchone()[0]
        status["mysql"] = ("up", f"{count} UEs in DB")
    except Exception as e:
        status["mysql"] = ("down", str(e)[:80])

    result = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"],
        capture_output=True, text=True,
    )
    containers = {}
    for line in result.stdout.splitlines():
        if "\t" in line:
            name, state = line.split("\t", 1)
            containers[name.strip()] = state.strip()
    status["containers"] = containers

    status["namespaces"] = list_namespaces()

    try:
        slices = list_ran_slices()
        if slices:
            status["rrm_policy"] = ("ok", f"{len(slices)} RAN slices configured")
        else:
            status["rrm_policy"] = ("missing", "Apply: git apply doc/rrmPolicyJson.patch")
    except FileNotFoundError:
        status["rrm_policy"] = ("missing", "Apply: git apply doc/rrmPolicyJson.patch")

    return status


def ping_ue(ns_name: str, target_ip: str = "192.168.70.135", count: int = 4) -> str:
    result = subprocess.run(
        ["ip", "netns", "exec", ns_name,
         "ping", "-I", "oaitun_ue1", "-c", str(count), target_ip],
        capture_output=True, text=True, timeout=20,
    )
    return (result.stdout + result.stderr).strip()


# =============================================================================
# SECTION 8: Rich display helpers
# =============================================================================

def _sd_label(entry: dict) -> str:
    sd = entry.get("sd")
    if sd is None:
        return "default (0xFFFFFF)"
    return f"0x{sd:x}" if isinstance(sd, int) else str(sd)


def print_ue_table(ues: list) -> None:
    table = Table(title="UE Subscribers", show_lines=True)
    table.add_column("IMSI", style="cyan")
    table.add_column("SST", justify="center")
    table.add_column("SD", justify="center")
    table.add_column("DNN")
    table.add_column("Static IP")
    table.add_column("Conf File", justify="center")
    table.add_column("Namespace", justify="center")

    ns_map = _load_ns_map()
    live_ns = set(list_namespaces())

    for ue in ues:
        nssai = json.loads(ue["nssai_json"]) if ue.get("nssai_json") else {}
        dnn_data = json.loads(ue["dnn_json"]) if ue.get("dnn_json") else {}
        dnn_name = list(dnn_data.keys())[0] if dnn_data else "?"
        dnn_conf = dnn_data.get(dnn_name, {})
        static_ips = dnn_conf.get("staticIpAddress", [])
        ip_str = static_ips[0]["ipv4Addr"] if static_ips else "dynamic"
        conf_exists = (UE_CONF_DIR / f"nrUE_{ue['imsi']}.conf").exists()

        ns_index = ns_map.get(ue["imsi"])
        ns_name = f"ue{ns_index}" if ns_index is not None else None
        if ns_name and ns_name in live_ns:
            ns_cell = f"[green]{ns_name}[/]"
        elif ns_name:
            ns_cell = f"[yellow]{ns_name}?[/]"
        else:
            ns_cell = "[dim]-[/]"

        table.add_row(
            ue["imsi"],
            str(nssai.get("sst", "?")),
            str(nssai.get("sd", "?")),
            dnn_name,
            ip_str,
            "[green]yes[/]" if conf_exists else "[red]no[/]",
            ns_cell,
        )
    console.print(table)


def print_ran_slice_table(slices: list) -> None:
    table = Table(title="RAN Slice Policy (rrmPolicy.json)", show_lines=True)
    table.add_column("SST", justify="center")
    table.add_column("SD", justify="center")
    table.add_column("dedicated_ratio", justify="right")
    table.add_column("min_ratio", justify="right")
    table.add_column("max_ratio", justify="right")

    for entry in slices:
        table.add_row(
            str(entry.get("sst", "?")),
            _sd_label(entry),
            str(entry.get("dedicated_ratio", "?")),
            str(entry.get("min_ratio", "?")),
            str(entry.get("max_ratio", "?")),
        )
    console.print(table)


def print_cn_slice_table(slices: list) -> None:
    table = Table(title="CN Slice Config (docker-compose legacy)", show_lines=True)
    table.add_column("#", justify="center")
    table.add_column("DNN")
    table.add_column("SST", justify="center")
    table.add_column("SD", justify="center")
    table.add_column("IP Range")
    table.add_column("AMBR UL")
    table.add_column("AMBR DL")

    for s in slices:
        table.add_row(
            str(s["index"]),
            s["dnn"],
            str(s["sst"]),
            str(s["sd"]),
            s["ip_range"],
            s["ambr_ul"],
            s["ambr_dl"],
        )
    console.print(table)


def print_ns_table(namespaces: list) -> None:
    table = Table(title="Active Network Namespaces", show_lines=True)
    table.add_column("Name", style="cyan")
    table.add_column("RFSim Addr")
    table.add_column("Enter Command")

    for ns in namespaces:
        if ns.startswith("ue") and ns[2:].isdigit():
            n = int(ns[2:])
            rfsim = f"10.{200 + n}.1.100"
            cmd = f"sudo bash {MULTI_UE_SCRIPT} -o{n}"
        else:
            rfsim = "?"
            cmd = "?"
        table.add_row(ns, rfsim, cmd)
    console.print(table)


def print_system_status(status: dict) -> None:
    lines = []

    mysql_state, mysql_msg = status["mysql"]
    color = "green" if mysql_state == "up" else "red"
    lines.append(f"[{color}]MySQL:[/] {mysql_msg}")

    lines.append("")
    lines.append("[bold]Docker Containers:[/]")
    cn_containers = [
        "mysql", "oai-nrf", "oai-amf", "oai-smf", "oai-spgwu-tiny",
        "oai-udr", "oai-udm", "oai-ausf", "oai-ext-dn",
    ]
    containers = status.get("containers", {})
    for name in cn_containers:
        if name in containers:
            state = containers[name]
            ok = state.lower().startswith("up")
            color = "green" if ok else "red"
            lines.append(f"  [{color}]{name}:[/] {state}")
        else:
            lines.append(f"  [dim]{name}: not running[/]")

    lines.append("")
    ns_list = status.get("namespaces", [])
    lines.append(f"[bold]Network Namespaces:[/] {', '.join(ns_list) if ns_list else 'none'}")

    rrm_state, rrm_msg = status["rrm_policy"]
    color = "green" if rrm_state == "ok" else "yellow"
    lines.append(f"[{color}]RAN Policy:[/] {rrm_msg}")

    console.print(Panel("\n".join(lines), title="System Status", border_style="cyan"))


def _handle_error(e: Exception) -> None:
    rprint(f"[red]Error:[/] {e}")


# =============================================================================
# SECTION 9: Interactive wizard functions
# =============================================================================

def _wizard_create_ue() -> None:
    try:
        imsi = questionary.text(
            "IMSI (15 digits, e.g. 001010000010780):",
            validate=lambda v: (len(v) == 15 and v.isdigit()) or "Must be exactly 15 digits",
        ).ask()
        if imsi is None:
            return

        use_defaults = questionary.confirm(
            f"Use default key/OPC (key={DEFAULT_KEY[:8]}...)?",
            default=True,
        ).ask()
        if use_defaults is None:
            return

        if use_defaults:
            key, opc = DEFAULT_KEY, DEFAULT_OPC
        else:
            key = questionary.text(
                "Key (32 hex chars):",
                validate=lambda v: (
                    len(v) == 32 and all(c in "0123456789abcdefABCDEF" for c in v)
                ) or "Must be 32 hex characters",
            ).ask()
            if key is None:
                return
            opc = questionary.text(
                "OPC (32 hex chars):",
                validate=lambda v: (
                    len(v) == 32 and all(c in "0123456789abcdefABCDEF" for c in v)
                ) or "Must be 32 hex characters",
            ).ask()
            if opc is None:
                return

        slice_choice = questionary.select(
            "Assign to slice:",
            choices=[
                "Slice 1  (SST=1, SD=0xFFFFFF, DNN=oai,  subnet 12.1.1.x)",
                "Slice 2  (SST=1, SD=0x000002, DNN=oai2, subnet 12.1.2.x)",
            ],
        ).ask()
        if slice_choice is None:
            return

        if "Slice 1" in slice_choice:
            cfg = SLICE_CONFIG["slice1"]
        else:
            cfg = SLICE_CONFIG["slice2"]

        sst = cfg["sst"]
        sd = cfg["sd"]
        dnn = cfg["dnn"]
        subnet = cfg["subnet"]

        rprint(f"[dim]Finding next free IP in {subnet}.0/24...[/]")
        try:
            static_ip = _next_free_ip(subnet)
        except RuntimeError as e:
            _handle_error(e)
            return

        console.print(Panel(
            f"IMSI:      {imsi}\n"
            f"DNN:       {dnn}\n"
            f"SST:       {sst},  SD: {cfg['sd_hex']}\n"
            f"Static IP: {static_ip}\n"
            f"Key:       {key[:8]}...\n"
            f"OPC:       {opc[:8]}...\n"
            f"Namespace: auto-assigned",
            title="New UE Summary",
        ))

        confirm = questionary.confirm("Create this UE?", default=True).ask()
        if not confirm:
            rprint("[yellow]Cancelled.[/]")
            return

        conf_path, ns_index = create_ue(imsi, key, opc, sst, sd, dnn, static_ip)
        rfsim = f"10.{200 + ns_index}.1.100"
        rprint(f"[green]Created UE {imsi}[/]  IP: {static_ip}  namespace: ue{ns_index}  conf: {conf_path}")
        rprint(f"[dim]Enter namespace: sudo bash {MULTI_UE_SCRIPT} -o{ns_index}  |  rfsim addr: {rfsim}[/]")

    except (ValueError, RuntimeError) as e:
        _handle_error(e)
    except KeyboardInterrupt:
        rprint("[yellow]Cancelled.[/]")


def _wizard_delete_ue() -> None:
    try:
        ues = list_ues()
    except RuntimeError as e:
        _handle_error(e)
        return

    if not ues:
        rprint("[yellow]No UEs in database.[/]")
        return

    choices = [u["imsi"] for u in ues] + ["Cancel"]
    imsi = questionary.select("Select UE to delete:", choices=choices).ask()
    if imsi is None or imsi == "Cancel":
        return

    ns_map = _load_ns_map()
    ns_index = ns_map.get(imsi)
    ns_note = f", namespace ue{ns_index}," if ns_index is not None else ""
    confirmed = questionary.confirm(
        f"Delete UE {imsi}? This removes DB entries{ns_note} and conf file.",
        default=False,
    ).ask()
    if not confirmed:
        rprint("[yellow]Cancelled.[/]")
        return

    try:
        delete_ue(imsi)
        ns_msg = f"  namespace ue{ns_index} removed" if ns_index is not None else ""
        rprint(f"[green]Deleted UE {imsi}[/]{ns_msg}")
    except (ValueError, RuntimeError) as e:
        _handle_error(e)


def _wizard_create_namespace() -> None:
    try:
        existing = list_namespaces()
        rprint(f"[dim]Existing namespaces: {existing if existing else 'none'}[/]")

        choices = [str(n) for n in range(1, MAX_NS + 1)] + ["Cancel"]
        choice = questionary.select(
            "Create namespace for UE index:",
            choices=choices,
        ).ask()
        if choice is None or choice == "Cancel":
            return

        n = int(choice)
        create_namespace(n)
        rprint(f"[green]Created namespace ue{n}[/]")
        rfsim = f"10.{200 + n}.1.100"
        console.print(Panel(
            f"Enter namespace:  sudo bash {MULTI_UE_SCRIPT} -o{n}\n\n"
            f"Then run UE with:  --rfsimulator.serveraddr {rfsim}",
            title=f"Namespace ue{n} ready",
            border_style="green",
        ))
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        _handle_error(e)
    except KeyboardInterrupt:
        rprint("[yellow]Cancelled.[/]")


def _wizard_delete_namespace() -> None:
    try:
        existing = list_namespaces()
        if not existing:
            rprint("[yellow]No active namespaces.[/]")
            return

        choices = existing + ["Cancel"]
        ns = questionary.select("Select namespace to delete:", choices=choices).ask()
        if ns is None or ns == "Cancel":
            return

        confirmed = questionary.confirm(
            f"Delete namespace {ns}? Any UE running inside will lose connectivity.",
            default=False,
        ).ask()
        if not confirmed:
            rprint("[yellow]Cancelled.[/]")
            return

        suffix = ns[2:] if ns.startswith("ue") else ""
        n = int(suffix) if suffix.isdigit() else None
        if n is None:
            rprint(f"[red]Cannot parse namespace index from '{ns}'[/]")
            return

        delete_namespace(n)
        rprint(f"[green]Deleted namespace {ns}[/]")
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        _handle_error(e)
    except KeyboardInterrupt:
        rprint("[yellow]Cancelled.[/]")


def _wizard_create_ran_slice() -> None:
    try:
        sst_str = questionary.text(
            "SST (Slice Service Type, integer, e.g. 1):",
            validate=lambda v: v.isdigit() or "Must be integer",
        ).ask()
        if sst_str is None:
            return
        sst = int(sst_str)

        sd_str = questionary.text(
            "SD (Slice Differentiator, hex without 0x, or 'none' for default):",
            default="none",
        ).ask()
        if sd_str is None:
            return
        sd = None if sd_str.strip().lower() == "none" else int(sd_str.strip(), 16)

        ded_str = questionary.text("dedicated_ratio (0–100):", default="5").ask()
        min_str = questionary.text("min_ratio (0–100):", default="10").ask()
        max_str = questionary.text("max_ratio (0–100):", default="100").ask()
        if None in (ded_str, min_str, max_str):
            return

        create_ran_slice(sst, sd, int(ded_str), int(min_str), int(max_str))
        rprint(f"[green]Created RAN slice SST={sst} SD={sd}[/]  (gNB picks up in ~13s)")
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        _handle_error(e)
    except KeyboardInterrupt:
        rprint("[yellow]Cancelled.[/]")


def _wizard_update_ran_slice() -> None:
    try:
        slices = list_ran_slices()
        if not slices:
            rprint("[yellow]No RAN slices configured (or rrmPolicy.json missing).[/]")
            return

        def _slice_label(e: dict) -> str:
            return f"SST={e['sst']} SD={_sd_label(e)}  ded={e.get('dedicated_ratio')} min={e.get('min_ratio')} max={e.get('max_ratio')}"

        choices = [_slice_label(e) for e in slices] + ["Cancel"]
        chosen = questionary.select("Select RAN slice to update:", choices=choices).ask()
        if chosen is None or chosen == "Cancel":
            return

        idx = choices.index(chosen)
        entry = slices[idx]
        sst = entry["sst"]
        sd = entry.get("sd")

        ded_str = questionary.text(
            "dedicated_ratio:", default=str(entry.get("dedicated_ratio", 5))
        ).ask()
        min_str = questionary.text(
            "min_ratio:", default=str(entry.get("min_ratio", 10))
        ).ask()
        max_str = questionary.text(
            "max_ratio:", default=str(entry.get("max_ratio", 100))
        ).ask()
        if None in (ded_str, min_str, max_str):
            return

        update_ran_slice(sst, sd, int(ded_str), int(min_str), int(max_str))
        rprint(f"[green]Updated RAN slice SST={sst} SD={sd}[/]  (gNB picks up in ~13s)")
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        _handle_error(e)
    except KeyboardInterrupt:
        rprint("[yellow]Cancelled.[/]")


def _wizard_delete_ran_slice() -> None:
    try:
        slices = list_ran_slices()
        if not slices:
            rprint("[yellow]No RAN slices configured.[/]")
            return

        def _slice_label(e: dict) -> str:
            return f"SST={e['sst']} SD={_sd_label(e)}"

        choices = [_slice_label(e) for e in slices] + ["Cancel"]
        chosen = questionary.select("Select RAN slice to delete:", choices=choices).ask()
        if chosen is None or chosen == "Cancel":
            return

        idx = choices.index(chosen)
        entry = slices[idx]
        sst = entry["sst"]
        sd = entry.get("sd")

        confirmed = questionary.confirm(
            f"Delete RAN slice SST={sst} SD={_sd_label(entry)}?",
            default=False,
        ).ask()
        if not confirmed:
            rprint("[yellow]Cancelled.[/]")
            return

        delete_ran_slice(sst, sd)
        rprint(f"[green]Deleted RAN slice SST={sst} SD={sd}[/]")
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        _handle_error(e)
    except KeyboardInterrupt:
        rprint("[yellow]Cancelled.[/]")


def _wizard_restart_cn() -> None:
    try:
        confirmed = questionary.confirm(
            "Restart Core Network? All UE connections will drop and reconnect.",
            default=False,
        ).ask()
        if not confirmed:
            rprint("[yellow]Cancelled.[/]")
            return
        restart_cn()
        rprint("[green]Core Network restarted successfully.[/]")
    except (RuntimeError, FileNotFoundError) as e:
        _handle_error(e)
    except KeyboardInterrupt:
        rprint("[yellow]Cancelled.[/]")


def _wizard_ping_ue() -> None:
    try:
        ns_list = list_namespaces()
        if not ns_list:
            rprint("[yellow]No active namespaces. Create one first.[/]")
            return

        choices = ns_list + ["Cancel"]
        ns = questionary.select("Select namespace to ping from:", choices=choices).ask()
        if ns is None or ns == "Cancel":
            return

        target = questionary.text(
            "Target IP:", default="192.168.70.135"
        ).ask()
        if target is None:
            return

        rprint(f"[dim]Pinging {target} from namespace {ns}...[/]")
        output = ping_ue(ns, target)
        console.print(Panel(output, title=f"Ping from {ns} → {target}"))
    except (ValueError, RuntimeError) as e:
        _handle_error(e)
    except subprocess.TimeoutExpired:
        rprint("[red]Ping timed out after 20 seconds.[/]")
    except KeyboardInterrupt:
        rprint("[yellow]Cancelled.[/]")


# =============================================================================
# SECTION 10: Menu definitions + main()
# =============================================================================

def ue_menu() -> None:
    while True:
        try:
            choice = questionary.select(
                "UE Management",
                choices=["List UEs", "Create UE", "Delete UE", "Back"],
            ).ask()
        except KeyboardInterrupt:
            return

        if choice is None or choice == "Back":
            return
        elif choice == "List UEs":
            try:
                ues = list_ues()
                if not ues:
                    rprint("[yellow]No UEs found in database.[/]")
                else:
                    print_ue_table(ues)
            except RuntimeError as e:
                _handle_error(e)
        elif choice == "Create UE":
            _wizard_create_ue()
        elif choice == "Delete UE":
            _wizard_delete_ue()


def namespace_menu() -> None:
    while True:
        try:
            choice = questionary.select(
                "Namespace Management",
                choices=["List Namespaces", "Create Namespace", "Delete Namespace", "Back"],
            ).ask()
        except KeyboardInterrupt:
            return

        if choice is None or choice == "Back":
            return
        elif choice == "List Namespaces":
            ns_list = list_namespaces()
            if not ns_list:
                rprint("[yellow]No active namespaces.[/]")
            else:
                print_ns_table(ns_list)
        elif choice == "Create Namespace":
            _wizard_create_namespace()
        elif choice == "Delete Namespace":
            _wizard_delete_namespace()


def slice_menu() -> None:
    while True:
        try:
            choice = questionary.select(
                "Slice Management",
                choices=[
                    "List Slices (RAN + CN)",
                    "Create RAN Slice",
                    "Update RAN Slice Policy",
                    "Delete RAN Slice",
                    "Restart CN",
                    "Back",
                ],
            ).ask()
        except KeyboardInterrupt:
            return

        if choice is None or choice == "Back":
            return
        elif choice == "List Slices (RAN + CN)":
            ran = list_ran_slices()
            if ran:
                print_ran_slice_table(ran)
            else:
                rprint("[yellow]No RAN slices (rrmPolicy.json missing or empty).[/]")
            try:
                cn = list_cn_slices()
                if cn:
                    print_cn_slice_table(cn)
                else:
                    rprint("[yellow]CN compose file not found.[/]")
            except Exception as e:
                _handle_error(e)
        elif choice == "Create RAN Slice":
            _wizard_create_ran_slice()
        elif choice == "Update RAN Slice Policy":
            _wizard_update_ran_slice()
        elif choice == "Delete RAN Slice":
            _wizard_delete_ran_slice()
        elif choice == "Restart CN":
            _wizard_restart_cn()


def status_menu() -> None:
    while True:
        try:
            choice = questionary.select(
                "System Status",
                choices=["Full System Status", "Ping UE Connectivity Test", "Back"],
            ).ask()
        except KeyboardInterrupt:
            return

        if choice is None or choice == "Back":
            return
        elif choice == "Full System Status":
            status = system_status()
            print_system_status(status)
        elif choice == "Ping UE Connectivity Test":
            _wizard_ping_ue()


def main_menu() -> None:
    while True:
        try:
            choice = questionary.select(
                "ORANSlice CLI — Main Menu",
                choices=[
                    "UE Management",
                    "Namespace Management",
                    "Slice Management",
                    "System Status",
                    "Exit",
                ],
            ).ask()
        except KeyboardInterrupt:
            break

        if choice is None or choice == "Exit":
            break
        elif choice == "UE Management":
            ue_menu()
        elif choice == "Namespace Management":
            namespace_menu()
        elif choice == "Slice Management":
            slice_menu()
        elif choice == "System Status":
            status_menu()


def main() -> None:
    if os.geteuid() != 0:
        rprint("[red]Error:[/] This tool requires root privileges.")
        rprint("Run via:  sudo ./oranslice")
        rprint("Or:       sudo python3 oranslice_cli.py")
        sys.exit(1)

    console.print(Panel(
        "[bold cyan]ORANSlice CLI[/] — 5G Network Slicing Management\n"
        "[dim]OAI RFSim · Legacy CN v1.5.1 · ACM MobiCom '24[/]",
        border_style="cyan",
    ))
    main_menu()
    rprint("[dim]Goodbye.[/]")


if __name__ == "__main__":
    main()
