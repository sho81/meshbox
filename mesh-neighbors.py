#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
mesh-neighbors.py - fetch MeshCore repeater neighbor list over serial, publish to web.

Runs on the DK0MAV mc2-Peine-Node raspi, normally invoked every minute
by cron through /usr/local/bin/meshcli-neighbors.sh. Must run with the python of
/opt/venvs/meshcore-venv (pyserial is provided by it).

Probe: every run ALL /dev/ttyUSB* ports are probed under per-port flocks
(/var/lock/meshcore-ttyUSBN.lock) so an interactive session on one port never blocks the
other. Each port is woken with a bare CR, then answered to "neighbors":
 - reply contains neighbor lines or "-none-"  -> role = MeshCore repeater
   (see MeshCore firmware, examples/simple_repeater/MyMesh.cpp::formatNeighborsReply:
    {pubkey-prefix}:{secs_ago}:{snr*4}; at most 8 entries, newest first; duplicates are
    possible in the raw list, so we keep only the newest observation per node)
   The repeater is additionally queried with "get name" and "ver" for its details.
 - otherwise the port is answered to "--info"; a parseable MeshCom info block
   ("MeshCom x.y (build: ...)" + Call/NAME/TIME lines) -> role = MeshCom.

Clock: each MeshCore port is also queried with "clock" (reply "HH:MM - DD/M/YYYY UTC",
minute precision). When the device lags the Pi by more than CLOCK_SYNC_LAG_S it gets
"time <epoch>" and is marked auto-synced on the page; a device running ahead only gets
a hint, because the MeshCore console accepts forward moves only. Each MeshCom port is
queried with "--pos" (reply "...DATE: YYYY.MM.DD HH:MM:SS LT"), converted to UTC using
its configured "UTC-OFF" from --info and shown as a delta; that unit keeps its own RTC
via NTP, so the Pi only reports it. System NTP state comes from timedatectl.
F24 adds manual per-row sync: a Clock & NTP row button POSTs the visitor's epoch to
mesh-time-sync.py, which writes a one-shot marker (settime-request.json) that the next
run consumes — "time <epoch>" on MeshCore (verified by an immediate "clock" re-read) or
"--settime yyyy.mm.dd hh:mm:ss" in device-local time on MeshCom (verified by a "--pos"
re-read); the outcome shows in that row's status cell.

The neighbor table is one merged list of every node ever heard (state in nodes-ever.json):
this run's rows add the live SNR, older rows show their last-seen age plus best/worst
SNR and sightings. It is sourced from whichever port classified as MeshCore, so a USB
port swap between the two Heltec units is absorbed automatically (the persisted mapping
and stale handling live in ports.json, see /var/lib/meshcore).

Outputs (written directly; files must exist with write permission for user db4sjp):
    /var/www/html/neighbors.html   HTML page embedded into index.html:
        merged neighbor table, PiUPS+ power section (electrical values + status),
        USB serial device table, clock/NTP status.

The PiUPS+ section (F11) does not touch the I2C bus at all: it parses the tail of
the piupsmonitor debug log (LogLevel=debug). F15 moved that log off the SD card;
F16 moves the LIVE log to tmpfs (/run/piupsmonitor/live.log) so ~800 MB/day of full
debug stays in RAM — zero flash reads, values <= ~1 s old. A compact forensic copy is
persisted on the USB stick at /var/log/piupsmonitor-logs/piupsmonitor.log by the
piups-log-relay service (status bits on change, full reading snapshot every 5 s), so
power-loss post-mortems still have a <=5 s cadence. The daemon logs the six status flags
on every I2C read and the five electrical readings (U_Bat, I_Rasp, U_USB, U_USV, U_Ext)
once per second; we take the newest value + timestamp per field from a 64 KB tail of
the live log.
"""

import fcntl
import glob
import html as htmllib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

# ============================================================================
# CONFIG — the only part of this file an operator normally edits.
# Node identity, paths and probe/timing tunables live here, everything below
# is mechanics. Keep derived paths (os.path.join) as they are so a single
# change to WWW_DIR or STATE_DIR moves every file at once.
# ============================================================================

# Station identity shown in the header line of the generated page: the MeshCore
# repeater's name + own uplink frequency, and the MeshCom unit's name + 70 cm
# frequency (reference only — the probe itself uses neither MeshCom value).
NODE_NAME = "Amateurfunk Peine FTZ"
MESHCORE_FREQ = "869.618 MHz"
MESHCOM_NAME = 'DK0MAV-12 "Digipeater Peine"'
MESHCOM_FREQ = "433.175 MHz"

# Serial probe: which ports to look at, console baud, and the quiet period that
# marks a reply complete (replies arrive in one burst, we read until the line
# has been silent this long).
PORTS_GLOB = "/dev/ttyUSB*"
BAUD = 115200
QUIET_MS = 500

# Output: the generated page (index.html embeds it) and the per-port lock files
# that keep the cron probe and an interactive meshcli console apart.
WWW_DIR = "/var/www/html"
HTML_OUT = os.path.join(WWW_DIR, "neighbors.html")


def lock_file_for(port):
    return f"/var/lock/meshcore-{os.path.basename(port)}.lock"

# State + name map: the all-nodes-ever history, the persisted port->role mapping
# (survives USB port swaps) and the USB watchdog state machine all live in
# STATE_DIR; mesh-node-names.json sits next to this script (start from
# deploy/mesh-node-names.example.json in the meshbox repo).
NAMES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mesh-node-names.json")
STATE_DIR = "/var/lib/meshcore"
NODES_EVER_FILE = os.path.join(STATE_DIR, "nodes-ever.json")
PORTS_FILE = os.path.join(STATE_DIR, "ports.json")
USB_STATE_FILE = os.path.join(STATE_DIR, "usb-state.json")

# Time sync: a MeshCore device clock lagging the Pi by more than this gets
# "time <epoch>" pushed to it (forward moves only — the console refuses them).
CLOCK_SYNC_LAG_S = 120

# F24: manual per-row time sync. mesh-time-sync.py writes a one-shot request
# marker here when a Clock & NTP row button targets a serial device; this engine
# consumes it during the next cron run (probe applies it under the per-port
# flock and verifies immediately). Requests older than this are dropped.
SETTIME_REQUEST = os.path.join(STATE_DIR, "settime-request.json")
SETTIME_MAX_AGE_S = 900

# PiUPS+ power section: the debug log to tail (live log on tmpfs since F16, see
# note further down) and how many bytes of its tail to parse (~5 s at the
# daemon's debug rate). Data older than PIUPS_STALE_S renders as a red
# "daemon down?" warning.
PIUPS_LOG = "/run/piupsmonitor/live.log"
PIUPS_TAIL_BYTES = 65536
PIUPS_STALE_S = 90

LINE_RE = re.compile(r"\b([0-9A-Fa-f]{8}):(\d{1,10}):(-?\d+)\b")


def _sanitize(msg):
    # F23: keep the log pure printable ASCII — any control char (NUL holes,
    # serial fragments echoed into warnings) would make grep/less treat the
    # whole log file as binary. Each offending char becomes a "?".
    return "".join(c if 0x20 <= ord(c) <= 0x7e else "?" for c in str(msg))


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {_sanitize(msg)}", flush=True)


def humanize_secs(s):
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} m {s % 60:02d} s"
    if s < 86400:
        return f"{s // 3600} h {(s % 3600) // 60:02d} m"
    return f"{s // 86400} d {(s % 86400) // 3600:02d} h"


def load_names():
    try:
        with open(NAMES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {str(k).upper(): str(v) for k, v in data.items()}
    except (OSError, ValueError) as e:
        log(f"warning: no valid name map at {NAMES_FILE} ({e})")
        return {}


def load_nodes_ever():
    try:
        with open(NODES_EVER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k).upper(): v for k, v in data.items()}
    except (OSError, ValueError) as e:
        log(f"warning: no valid nodes-ever state at {NODES_EVER_FILE} ({e})")
    return {}


def update_nodes_ever(rows, now_utc):
    """Merge this run's deduplicated rows into the all-nodes-ever state file."""
    state = load_nodes_ever()
    for key, age, snr in rows:
        db = round(snr / 4, 2)
        seen_iso = datetime.fromtimestamp(now_utc.timestamp() - age, timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC")
        e = state.get(key)
        if e is None:
            state[key] = {"first": seen_iso, "last": seen_iso, "sightings": 1,
                          "best_db": db, "worst_db": db}
        else:
            # fixed-width UTC strings compare chronologically as plain text
            e["last"] = max(e.get("last", ""), seen_iso)
            e["sightings"] = int(e.get("sightings", 0)) + 1
            e["best_db"] = round(max(float(e.get("best_db", db)), db), 2)
            e["worst_db"] = round(min(float(e.get("worst_db", db)), db), 2)
    try:
        with open(NODES_EVER_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
            f.write("\n")
    except OSError as e:
        log(f"warning: could not write {NODES_EVER_FILE}: {e}")
    return state


def ensure_state_dir():
    if not os.path.isdir(STATE_DIR):
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
        except OSError as e:
            log(f"warning: cannot create {STATE_DIR}: {e} (nodes-ever history stays empty)")


def read_sysfile(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def boot_time_utc(now_utc, uptime_file="/proc/uptime", stat_file="/proc/stat"):
    """System boot time as an aware UTC datetime (F18 "Started" line).

    Derived from the wall clock minus /proc/uptime seconds, so it carries exactly
    the same pre-NTP cold-boot skew as every other timestamp on this page (no RTC
    on this Pi); NTP corrects both within ~40 s of boot. Falls back to /proc/stat
    btime; None when neither is readable (the Started line is then omitted)."""
    text = read_sysfile(uptime_file)
    try:
        up_s = float(text.split()[0])
    except (ValueError, IndexError):
        pass
    else:
        return now_utc - timedelta(seconds=up_s)
    for line in read_sysfile(stat_file).splitlines():
        if line.startswith("btime "):
            try:
                return datetime.fromtimestamp(int(line.split()[1]), tz=timezone.utc)
            except (ValueError, IndexError, OSError):
                break
    return None


USB_PATH_SEG_RE = re.compile(r"^\d+-[\d.-]+$")


def usb_os_info(port):
    """OS-level USB identity of a tty device from /sys (no serial traffic)."""
    info = {"product": "-", "vid_pid": "-", "usb_path": "-"}
    link = os.path.realpath(os.path.join("/sys/class/tty", os.path.basename(port)))
    for part in reversed(link.split("/")):
        if USB_PATH_SEG_RE.match(part):          # e.g. 1-1.2 (bus-port chain)
            info["usb_path"] = part
            break
    d = link
    for _ in range(6):                           # walk up to the USB device dir
        if os.path.isfile(os.path.join(d, "idVendor")):
            vid, pid = read_sysfile(os.path.join(d, "idVendor")), read_sysfile(os.path.join(d, "idProduct"))
            prod = read_sysfile(os.path.join(d, "product"))
            if vid and pid:
                info["vid_pid"] = f"{vid}:{pid}"
            if prod:
                info["product"] = prod
            break
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return info


def parse_neighbor_entries(text):
    entries = []
    for m in LINE_RE.finditer(text):
        key, age, snr = m.group(1).upper(), int(m.group(2)), int(m.group(3))
        entries.append((key, age, snr))
    return entries


def read_response(ser, timeout_s=4.0):
    """Read until QUIET_MS of silence or total timeout; return decoded text."""
    buf = b""
    start = time.monotonic()
    last_change = start
    while True:
        now = time.monotonic()
        if (now - start) * 1000 > timeout_s * 1000:
            break
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
            last_change = now
        elif buf and (now - last_change) * 1000 >= QUIET_MS:
            break                        # response complete (quiet for QUIET_MS)
        else:
            time.sleep(0.05)
    return buf.decode("utf-8", errors="replace")


def send_cmd(ser, cmd, timeout_s=4.0):
    """Send one CLI command and return its raw reply text."""
    ser.reset_input_buffer()
    ser.write(cmd.encode("ascii") + b"\r")
    return read_response(ser, timeout_s)


CORE_VER_RE = re.compile(r"(v[\d][\w.\-]*)\s*\(Build:\s*([^)\r\n]+)")
MESHCOM_INFO_RE = re.compile(r"MeshCom\s+([\w.]+)\s*\(build:\s*([^)]+)")
MESHCOM_CALL_RE = re.compile(r"Call:\s*<([^>]*)>")
MESHCOM_NAME_RE = re.compile(r"\.\.\.NAME:\s*([^\r\n]+)")
MESHCOM_UPTIME_RE = re.compile(r"\.\.\.TIME\s+(\d+)\s+ms")
MESHCOM_DATE_RE = re.compile(
    r"\.\.\.DATE:\s*(\d{4})\.(\d{2})\.(\d{2})\s+(\d{1,2}):(\d{2}):(\d{2})")
MESHCOM_UTCOFF_RE = re.compile(r"UTC-OFF\s+([+-]?\d+(?:\.\d+)?)")

# MeshCore "clock" reply, e.g. "  -> 11:48 - 15/5/2024 UTC" (minute precision)
CLOCK_RE = re.compile(r"->\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2})/(\d{1,2})/(\d{4})\s+UTC")


def parse_clock_reply(raw):
    """Parse a MeshCore 'clock' reply into an aware UTC datetime (seconds = 0)."""
    m = CLOCK_RE.search(raw)
    if not m:
        return None
    h, mi, d, mo, y = (int(g) for g in m.groups())
    try:
        return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)
    except ValueError:
        return None


def system_ntp_status():
    """System clock/NTP state from timedatectl, for the page's Clock & NTP section."""
    info = {"tz": "-", "ntp": "-", "synced": "-"}
    try:
        out = subprocess.run(["timedatectl"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return info
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("Time zone:"):
            info["tz"] = s.split(":", 1)[1].strip()
        elif s.startswith("NTP service:"):
            info["ntp"] = s.split(":", 1)[1].strip()
        # older systemd prints "Time synchronized:", newer ones "System clock synchronized:"
        elif s.startswith("System clock synchronized:") or s.startswith("Time synchronized:"):
            info["synced"] = s.split(":", 1)[1].strip()
    return info


def probe_port(port, serial_mod, now_utc=None, manual=None):
    """One per-port probe: classify role + collect details + neighbor entries.

    manual: optional F24 request {"target": port, "epoch": int} to push this
    visitor's clock to this device (applied only when target == port).
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    res = dict(usb_os_info(port))
    res.update({"port": port, "role": "unknown", "ok": False, "rows": [], "details": "-"})

    lock_fd = os.open(lock_file_for(port), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        res["details"] = "- (busy)"
        return res

    ser = None
    try:
        ser = serial_mod.Serial(port, BAUD, timeout=0.2)
        time.sleep(0.4)                      # let the serial line settle
        ser.reset_input_buffer()
        ser.write(b"\r\n")                   # wake the console
        time.sleep(0.6)

        raw_nb = send_cmd(ser, "neighbors", 5.0)
        entries = parse_neighbor_entries(raw_nb)
        if entries or "-none-" in raw_nb:    # MeshCore repeater answered
            res["role"] = "meshcore"
            res["ok"] = True
            res["rows"] = entries
            bits = []
            mname = re.search(r"\->\s*>\s*([^\r\n]+)", send_cmd(ser, "get name"))
            if mname:
                bits.append(mname.group(1).strip())
            mver = CORE_VER_RE.search(send_cmd(ser, "ver"))
            if mver:
                bits.append(f"{mver.group(1)} (Build: {mver.group(2)})")
            res["details"] = htmllib.escape(" \u00b7 ".join(bits)) if bits else "-"

            # F8: device clock check. Reply has minute precision, so the delta is
            # approximate (+/- 60 s). A lag beyond CLOCK_SYNC_LAG_S gets fixed by
            # sending "time <epoch>"; a device running ahead only gets a hint on the
            # page (the MeshCore console accepts forward moves only).
            dev_dt = parse_clock_reply(send_cmd(ser, "clock"))
            want_epoch = manual["epoch"] if manual and manual["target"] == port else None
            if want_epoch is not None:
                # F24 manual sync: push the visitor's epoch, then re-read the clock
                # to verify. The automatic lag sync is skipped this run — the
                # requested time may deliberately differ from the Pi's.
                send_cmd(ser, f"time {want_epoch}")
                dev_dt = parse_clock_reply(send_cmd(ser, "clock")) or dev_dt
            if dev_dt is not None:
                lag_s = int((now_utc - dev_dt).total_seconds())
                synced = False
                if want_epoch is None and lag_s > CLOCK_SYNC_LAG_S:
                    send_cmd(ser, f"time {int(now_utc.timestamp())}")
                    synced = True
                res["clock"] = {"device": dev_dt.strftime("%Y-%m-%d %H:%M UTC"),
                                "lag_s": lag_s, "synced": synced}
                if want_epoch is not None:
                    vd = int(dev_dt.timestamp()) - want_epoch
                    res["clock"]["manual"] = {"verify_delta_s": vd, "ok": abs(vd) <= 90}
            elif want_epoch is not None:
                log(f"manual sync on {port}: sent, but no clock reply to verify")
        else:                                # not a repeater -> try MeshCom info block
            raw_info = send_cmd(ser, "--info", 5.0)
            mi = MESHCOM_INFO_RE.search(raw_info)
            if mi:
                res["role"] = "meshcom"
                res["ok"] = True
                bits = [f"MeshCom {mi.group(1)} (build: {mi.group(2)})"]
                ident = []
                mc, mn = MESHCOM_CALL_RE.search(raw_info), MESHCOM_NAME_RE.search(raw_info)
                if mc and mc.group(1).strip():
                    ident.append(mc.group(1).strip())
                if mn and mn.group(1).strip():
                    ident.append(f"\u201c{mn.group(1).strip()}\u201d")
                if ident:
                    bits.append(" ".join(ident))
                mu = MESHCOM_UPTIME_RE.search(raw_info)
                if mu:
                    bits.append(f"up {humanize_secs(int(mu.group(1)) // 1000)}")
                res["details"] = htmllib.escape(" \u00b7 ".join(bits))

                # Device clock: --pos reports local time, subtract the configured
                # offset to get UTC. The unit self-syncs its RTC via NTP, so we only
                # report a delta (F24 adds the manual per-row set button).
                off = MESHCOM_UTCOFF_RE.search(raw_info)
                md = MESHCOM_DATE_RE.search(send_cmd(ser, "--pos", 5.0))
                want_epoch = manual["epoch"] if manual and manual["target"] == port else None
                if off and md:
                    y, mo, d, hh, mi_, ss = (int(g) for g in md.groups())
                    try:
                        dev_utc = (datetime(y, mo, d, hh, mi_, ss)
                                   - timedelta(hours=float(off.group(1)))).replace(
                                       tzinfo=timezone.utc)
                    except ValueError:
                        dev_utc = None
                    if dev_utc is not None:
                        res["clock"] = {"device": dev_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
                                        "lag_s": int((now_utc - dev_utc).total_seconds()),
                                        "synced": False}
                        if want_epoch is not None:
                            # F24 manual sync. The MeshCom CLI wants LOCAL time
                            # (local = UTC + UTC-OFF, same convention --pos shows).
                            loc = (datetime.fromtimestamp(want_epoch, timezone.utc)
                                   + timedelta(hours=float(off.group(1))))
                            send_cmd(ser, f"--settime {loc:%Y.%m.%d %H:%M:%S}")
                            md2 = MESHCOM_DATE_RE.search(send_cmd(ser, "--pos", 5.0))
                            set_utc = None
                            if md2:
                                try:
                                    set_utc = (datetime(*(int(g) for g in md2.groups()))
                                               - timedelta(hours=float(off.group(1)))
                                               ).replace(tzinfo=timezone.utc)
                                except ValueError:
                                    set_utc = None
                            vd = (int(set_utc.timestamp()) - want_epoch
                                  if set_utc is not None else None)
                            res["clock"]["manual"] = {"verify_delta_s": vd,
                                                      "ok": vd is not None and abs(vd) <= 10}
                            if set_utc is not None:
                                res["clock"]["device"] = set_utc.strftime(
                                    "%Y-%m-%d %H:%M:%S UTC")
                                res["clock"]["lag_s"] = int(
                                    (now_utc - set_utc).total_seconds())
                    elif want_epoch is not None:
                        log(f"manual sync on {port}: cannot read --pos clock, "
                            "--settime skipped")
            else:
                res["details"] = "- (unrecognized reply)"
    except Exception as e:                   # USB glitch / device vanished mid-probe
        if res["role"] == "unknown":
            res["details"] = htmllib.escape(f"probe error: {e}")
    finally:
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    return res


ROLE_LABEL = {"meshcore": "MeshCore repeater", "meshcom": "MeshCom"}


def render_usb_html(infos):
    trs = []
    for i, p in enumerate(infos):
        role = ROLE_LABEL.get(p["role"], "?")
        if p.get("stale"):
            role += " (stale)"
        trs.append(
            f'<tr data-order="{i}">'
            f'<td>{p["port"]}</td>'
            f'<td>{htmllib.escape(p["product"])}</td>'
            f'<td>{htmllib.escape(p["usb_path"])}</td>'
            f'<td data-sort="{ROLE_LABEL.get(p["role"], "?")}">{role}</td>'
            f'<td>{p["details"]}</td></tr>')
    return ('<table class="sortable" id="tbl-usb"><thead><tr>'
            '<th>Port</th><th>USB device</th><th>USB path</th><th>System</th>'
            f'<th>Details</th></tr></thead><tbody>{"".join(trs)}</tbody></table>')


def load_ports_state():
    try:
        with open(PORTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("ports"), dict):
            return data
    except (OSError, ValueError) as e:
        log(f"warning: no valid port state at {PORTS_FILE} ({e})")
    return {"updated": "", "ports": {}}


def save_ports_state(state):
    try:
        with open(PORTS_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
            f.write("\n")
    except OSError as e:
        log(f"warning: could not write {PORTS_FILE}: {e}")


def apply_port_persistence(infos, now_utc):
    """Merge live classification with the persisted role mapping (ports.json).

    - a port that answered is classified from its live reply; a differing saved
      role counts as a detected USB swap and is logged + overwritten.
    - an unresponsive port falls back to its saved role and gets flagged stale.
    """
    prev = load_ports_state()
    prev_ports = prev.get("ports", {})
    now_iso = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    new_ports = {}
    for p in infos:
        port, base = p["port"], os.path.basename(p["port"])
        saved = prev_ports.get(port) or {}
        if p["role"] != "unknown":
            if saved.get("role") and saved["role"] != p["role"]:
                log(f"port role changed on {base}: was {saved['role']}, now {p['role']} (swap?)")
            new_ports[port] = {"role": p["role"], "usb_path": p["usb_path"]}
        elif saved.get("role") in ("meshcore", "meshcom"):
            p["role"] = saved["role"]
            p["ok"] = False
            p["stale"] = True
            p["details"] += f' &mdash; stale (last confirmed {prev.get("updated") or "?"})'
            new_ports[port] = {"role": saved["role"], "usb_path": saved.get("usb_path", "-")}
        else:
            p["stale"] = False
    state = {"updated": now_iso, "ports": new_ports}
    save_ports_state(state)
    return state


def load_manual_sync_request():
    """F24: consume the one-shot manual time-sync marker written by mesh-time-sync.py.

    Returns {"target": "/dev/ttyUSBx", "epoch": int} or None. The marker file is
    always deleted here (processed, stale or malformed — never retried forever);
    shape/range checks mirror the service side as defense in depth.
    """
    try:
        with open(SETTIME_REQUEST, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log(f"warning: unreadable manual-sync request at {SETTIME_REQUEST}: {e}")
        try:
            os.remove(SETTIME_REQUEST)
        except OSError:
            pass
        return None
    try:
        os.remove(SETTIME_REQUEST)
    except OSError as e:
        log(f"warning: could not remove {SETTIME_REQUEST}: {e}")
    target, epoch = data.get("target"), data.get("epoch")
    if (not isinstance(target, str) or not re.fullmatch(r"/dev/ttyUSB\d+", target)
            or not isinstance(epoch, int) or isinstance(epoch, bool)
            or not (10 ** 8 < epoch < 4 * 10 ** 9)):
        log(f"manual-sync request discarded: bad shape {str(data)[:120]}")
        return None
    age = int(time.time()) - int(data.get("requested") or 0)
    if age > SETTIME_MAX_AGE_S or age < -60:
        log(f"manual-sync request for {target} discarded: {age} s old")
        return None
    log(f"manual time sync requested for {target} (epoch {epoch}, age {age} s)")
    return {"target": target, "epoch": epoch}


def clock_status_text(c, role):
    m = c.get("manual")
    if m:
        vd = m.get("verify_delta_s")
        if vd is None:
            return "manual sync sent \u2014 no verification reply, check the next update"
        if m.get("ok"):
            return f"manual sync verified (\u0394 to requested time {vd:+d} s)"
        return (f"manual sync sent, device still {humanize_secs(abs(vd))} off the "
                "requested time")
    if c["synced"]:
        return f"auto-synced this run (was {humanize_secs(c['lag_s'])} behind)"
    if c["lag_s"] < 0:
        return (f"running ahead by {humanize_secs(-c['lag_s'])}; Pi should win, "
                "check the device manually")
    if role == "meshcom" and c["lag_s"] > CLOCK_SYNC_LAG_S:
        # MeshCom keeps its own RTC via NTP; we do not overwrite it automatically.
        return (f"{humanize_secs(c['lag_s'])} behind; self-syncs via NTP, use the "
                "button to set it from your device if this persists")
    return "ok"


# F24: one manual-sync button per Clock & NTP row (render_clock_section emits the
# .tbtn buttons); this delegated handler POSTs browser epoch + row target.
MANUAL_SYNC_JS = """
<script>
(function () {
    var tbl = document.getElementById('tbl-clock');
    if (!tbl) return;
    tbl.addEventListener('click', function (ev) {
        var btn = ev.target.closest ? ev.target.closest('button.tbtn') : null;
        if (!btn) return;
        var res = btn.parentNode.querySelector('.tresult');
        var epoch = Math.floor(Date.now() / 1000);   // seconds — timezone-agnostic by definition
        var target = btn.getAttribute('data-target') || '';
        var what = target || 'raspi-mesh system time';
        if (!confirm('Set ' + what + ' to\\n' + new Date(epoch * 1000).toUTCString()
                     + '\\n\\nUses THIS device\\'s clock (manual sync; NTP stays preferred).')) return;
        res.textContent = 'sending\\u2026';
        var body = {epoch: epoch};
        if (target) body.target = target;
        fetch('/settime', {method: 'POST', headers: {'Content-Type': 'application/json'},
                           body: JSON.stringify(body)})
          .then(function (r) { return r.json(); })
          .then(function (d) {
              if (!d.ok) { res.textContent = 'error: ' + (d.error || 'unknown'); return; }
              res.textContent = d.queued
                  ? 'queued \\u2014 runs with the next update (\\u2248 1 min)'
                  : 'ok \\u2014 Pi now reads ' + d.now_utc;
          })
          .catch(function (e) { res.textContent = 'error: ' + e; });
    });
})();
</script>"""


def render_clock_section(infos, ntp, now_utc):
    """All clocks in one sortable table (F24).

    Row order: the Pi system clock (pinned to the top at every sort), then one
    row per device clock, then the visitor's own "local device time" last. Every
    settable row carries its own manual-sync button; the local row has none —
    its clock IS the source every button sends.
    """
    synced = str(ntp.get("synced", "-")).lower()
    ntp_svc = str(ntp.get("ntp", "-")).lower()
    if synced == "yes":
        pi_status = '<span style="color:#7f7">NTP synchronized</span>'
    elif ntp_svc == "active":
        pi_status = ('<span style="color:#fd5" '
                     'title="NTP service runs but the clock is not locked yet">'
                     'not yet synchronized (NTP active)</span>')
    else:
        pi_status = '<span style="color:#f95">NTP service not active</span>'

    def set_btn(target, title):
        return (f'<button type="button" class="tbtn" data-target="{target}" '
                f'title="{title}">set from your device</button>'
                '<span class="tresult"></span>')

    now_txt = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    trs = []
    # F13/F24: dedicated system-clock row, pinned first at every sort order.
    pi_title = ("Set the raspi-mesh system clock to THIS device's current time "
                "(UTC). Fallback for when NTP is unavailable.")
    trs.append(
        '<tr data-order="0" data-pin="top">'
        "<td>raspi-mesh (system)</td>"
        f'<td data-sort="{now_txt}">{now_txt}</td>'
        '<td class="num" title="reference clock (all &Delta; measured against this)">&mdash;</td>'
        f"<td>{pi_status}</td>"
        f"<td>{set_btn('', pi_title)}</td></tr>")
    for i, p in enumerate(x for x in infos or [] if x.get("clock")):
        c = p["clock"]
        if c["lag_s"] == 0:
            delta = "0s"
        else:
            sign = "+" if c["lag_s"] > 0 else "-"
            delta = f"{sign}{humanize_secs(abs(c['lag_s']))}"
        role_lbl = ROLE_LABEL.get(p["role"], p["role"])
        port_title = (f'Set {p["port"]} ({role_lbl}) to THIS device&#39;s current '
                      "time (UTC). Runs with the next update; the verification "
                      "result shows here.")
        trs.append(
            f'<tr data-order="{i + 1}">'
            f"<td>{p['port']}</td>"
            f'<td data-sort="{c["device"]}">{c["device"]}</td>'
            f'<td class="num" data-sort="{c["lag_s"]}">{delta}</td>'
            f"<td>{htmllib.escape(clock_status_text(c, p['role']))}</td>"
            f"<td>{set_btn(p['port'], port_title)}</td></tr>")
    # F24: the visitor's own clock — source of every manual sync, hence no button;
    # the ticker script keeps it live to the second.
    trs.append(
        '<tr data-order="99">'
        "<td>local device time (this browser)</td>"
        f'<td data-sort="{now_txt}"><span id="local-clock">{now_txt}</span></td>'
        '<td class="num" title="this clock is what the buttons send">&mdash;</td>'
        "<td>reference for the manual sync column</td>"
        "<td>&mdash;</td></tr>")
    table = ('<table class="sortable" id="tbl-clock"><thead><tr>'
             '<th>Port</th><th>Device time (UTC)</th><th class="num">&Delta; vs Pi</th>'
             '<th>Status</th><th>Manual sync</th>'
             f'</tr></thead><tbody>{"".join(trs)}</tbody></table>')
    line = (f"system: time zone {htmllib.escape(ntp.get('tz', '-'))} &middot; "
            f"NTP service: {htmllib.escape(ntp.get('ntp', '-'))} &middot; "
            f"time synchronized: {htmllib.escape(ntp.get('synced', '-'))}")
    return (table + MANUAL_SYNC_JS
            + f'\n<p style="font-size:11px;color:#575">{line}</p>')


# ---------------------------------------------------------------------------
# PiUPS+ / Power section (F11)
#
# Data source is the piupsmonitor daemon's own log, not the I2C bus, so this adds
# zero bus traffic on top of the daemon's ~30-45 reads/s. Log line formats
# (vendor dehapama/piupsmonitor-raspberrypi, LogLevel=debug):
#   2026-10-10 18:50:39 [DEBUG] Primary Power Supply: 1     <- per I2C status read
#   2026-10-10 18:50:39 [DEBUG] U_Bat: 4209 mV              <- once per second
# Timestamps are local wall time without a zone; the box has no RTC, so they are
# converted to UTC with the system's current offset (values used here are seconds
# old, so a DST-boundary error would be at most one year in the making).
# (PIUPS_LOG / PIUPS_TAIL_BYTES / PIUPS_STALE_S moved up to CONFIG.)
# F15 moved the log to the USB stick (ext4, mount /var/log/piupsmonitor-logs); F16 moves
# the LIVE log to tmpfs (/run/piupsmonitor/live.log) so ~800 MB/day of full debug stays in
# RAM. piups-log-relay persists a compact subset to the USB stick for forensics (status on
# change, reading snapshot every 5 s); this engine reads the live log — fresher values and
# no flash reads at all.

PIUPS_STATUS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[\w+\] "
    r"(Primary Power Supply|Secondary Power Supply|Battery Low|"
    r"Button Pressed|Battery Charge|Battery Full): ([01])$")
PIUPS_VOLT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[DEBUG\] "
    r"(U_Bat|I_Rasp|U_USB|U_USV|U_Ext): (-?\d+) (mV|mA)$")

PIUPS_STATUS_KEYS = {
    "Primary Power Supply": "primary",
    "Secondary Power Supply": "secondary",
    "Battery Low": "low",
    "Battery Charge": "charging",
    "Battery Full": "full",
    "Button Pressed": "button",
}

# Daemon's own print order; meanings as established during the 2026-10-10 post-mortem.
PIUPS_VOLT_ORDER = ["U_Bat", "I_Rasp", "U_USB", "U_USV", "U_Ext"]
PIUPS_VOLT_TOOLTIPS = {
    "U_Bat": "battery pack voltage",
    "I_Rasp": "Raspberry Pi current draw",
    "U_USB": "USB rail (name as logged by the daemon)",
    "U_USV": "UPS sense line, looks like a current-sense shunt",
    "U_Ext": "external DC feed into the module (~13 V, not USB 5 V)",
}


def _piups_ts_utc(ts_str, gmtoff_s):
    """Zone-less piupsmonitor timestamp -> aware UTC (None if malformed)."""
    try:
        naive = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    local = naive.replace(tzinfo=timezone(timedelta(seconds=gmtoff_s)))
    return local.astimezone(timezone.utc)


def read_piups(now_utc):
    """Latest value + timestamp for every field the piupsmonitor debug log traces.

    Returns a dict with per-field status bits (0/1), raw voltage/current values,
    per-field timestamps and how old the newest value is ("stale_s"), or None when
    no matching lines are found at all (file missing, daemon below LogLevel=debug,
    or log just rotated away). A 64 KB tail covers ~5 s of debug output, i.e. at
    least five complete voltage blocks and many status sets.
    """
    try:
        size = os.path.getsize(PIUPS_LOG)
    except OSError:
        return None
    with open(PIUPS_LOG, "rb") as f:
        if size > PIUPS_TAIL_BYTES:
            f.seek(-PIUPS_TAIL_BYTES, os.SEEK_END)
        data = f.read()
    lines = data.decode("utf-8", errors="replace").splitlines()
    if len(lines) and size > PIUPS_TAIL_BYTES:
        lines = lines[1:]                 # first line may be cut at the seek point

    gmtoff_s = int(time.localtime().tm_gmtoff)
    status, volts, ts_fields = {}, {}, {}
    latest = None

    def bump(t):
        nonlocal latest
        if t is not None and (latest is None or t > latest):
            latest = t

    for line in lines:
        m = PIUPS_STATUS_RE.match(line)
        if m:
            t = _piups_ts_utc(m.group(1), gmtoff_s)
            key = PIUPS_STATUS_KEYS[m.group(2)]
            status[key] = int(m.group(3))     # file is append-only: last line wins
            ts_fields[key] = t
            bump(t)
            continue
        m = PIUPS_VOLT_RE.match(line)
        if m:
            t = _piups_ts_utc(m.group(1), gmtoff_s)
            volts[m.group(2)] = int(m.group(3))
            ts_fields[m.group(2)] = (t, m.group(4))
            bump(t)

    if not status and not volts:
        return None
    stale_s = max(0, int((now_utc - latest).total_seconds())) if latest else None
    return {"status": status, "volts": volts, "ts": ts_fields,
            "latest_ts": latest, "stale_s": stale_s}


def render_piups_section(ups):
    """Status line + electrical-values table for the PiUPS+ / Power section."""
    st = ups["status"]

    def on_off(key, warn_when_off=True):
        if st.get(key):
            return '<span style="color:#7f7">ON</span>'
        color = "#f95" if warn_when_off else "#575"
        return f'<span style="color:{color}">OFF</span>'

    bat_word, bat_color = ("&mdash;", "#575")
    for word, color, bit in (("FULL", "#7f7", "full"),
                             ("CHARGING", "#fd5", "charging"),
                             ("LOW", "#f95", "low")):
        if st.get(bit):
            bat_word, bat_color = word, color
            break
    bits = (f'low={st.get("low", "?")} charge={st.get("charging", "?")} '
            f'full={st.get("full", "?")}')
    btn = ('<span style="color:#fd5">PRESSED</span>' if st.get("button")
           else '<span style="color:#575">&mdash;</span>')

    stale_s = ups["stale_s"]
    latest_iso = (ups["latest_ts"].strftime("%Y-%m-%d %H:%M:%S UTC")
                  if ups.get("latest_ts") else "?")
    if stale_s is not None and stale_s > PIUPS_STALE_S:
        age = (f'<span style="color:#f95" title="{htmllib.escape(latest_iso)}">'
               f'stale &mdash; data {humanize_secs(stale_s)} old, daemon down?</span>')
    else:
        age = (f'<span style="color:#575" title="{htmllib.escape(latest_iso)}">'
               f'data {humanize_secs(0 if stale_s is None else stale_s)} old</span>')

    status_line = (f'Primary power: {on_off("primary")} &middot; '
                   f'Secondary: {on_off("secondary", warn_when_off=False)} &middot; '
                   f'Battery: <span style="color:{bat_color}">{bat_word}</span> '
                   f'<span style="color:#575">({bits})</span> &middot; '
                   f'Button: {btn} &nbsp;&middot;&nbsp; {age}')

    trs = []
    for i, field in enumerate(PIUPS_VOLT_ORDER):
        if field not in ups["volts"]:
            trs.append(f'<tr data-order="{i}"><td class="key">{field}</td>'
                       '<td class="num">-</td><td>-</td></tr>')
            continue
        value = ups["volts"][field]
        t, unit = ups["ts"].get(field, (None, ""))
        extra = f' <span style="color:#575">({value / 1000:.3f} V)</span>' if unit == "mV" else ""
        shown = t.strftime("%Y-%m-%d %H:%M:%S") if t else "-"
        title = t.strftime("%Y-%m-%d %H:%M:%S UTC") if t else "no timestamp parsed"
        trs.append(
            f'<tr data-order="{i}">'
            f'<td class="key" data-sort="{field}" '
            f'title="{htmllib.escape(PIUPS_VOLT_TOOLTIPS[field])}">{field}</td>'
            f'<td class="num" data-sort="{value}">{value} {unit}{extra}</td>'
            f'<td title="{title}" data-sort="{int(t.timestamp()) if t else 0}">{shown}</td></tr>')

    table = ('<table class="sortable" id="tbl-piups"><thead><tr>'
             '<th>Reading</th><th class="num">Value</th>'
             f'<th>Last update (UTC)</th></tr></thead><tbody>{"".join(trs)}</tbody></table>')

    note = ('source: /run/piupsmonitor/live.log (LogLevel=debug in RAM &mdash; status flags per I&sup2;C '
            'read, voltages once per second) &middot; forensic copy on the USB stick at 5&nbsp;s cadence '
            '(/var/log/piupsmonitor-logs) &middot; U_Ext is the ~13 V DC feed into the module, not USB '
            '5&nbsp;V; U_USV looks like a current-sense shunt')
    return (f'<p style="margin:0 0 6px;font-size:12px">{status_line}</p>\n'
            + table
            + f'\n<p style="font-size:11px;color:#575;margin:4px 0 0">{note}</p>')


# ---------------------------------------------------------------------------
# USB device watchdog (F12)
#
# Physical presence tracking for every "meaningful" USB peripheral - the CP210x
# UART bridges and the storage stick(s). Source of truth is /sys/bus/usb/devices
# (no serial traffic, no kernel or udev changes). Every cron minute the current
# devices are enumerated; per-device state (ONLINE/OFFLINE + transition time +
# last confirmed observation) persists in usb-state.json across runs and reboots.
# A plug/unplug therefore flips status within one cron minute even when nothing
# else on the page changes - which is exactly what an unattended box needs: a
# permanently attached stick that is missing after a reboot shows up OFFLINE at
# once. Display only for now; no commands fire on transitions (later step).

_USB_DEV_NAME_RE = re.compile(r"^\d+-\d+(\.\d+)*$")


def _read_sys(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def _usb_dir_of(resolved):
    """Name of the nearest USB device directory (e.g. "1-1.2") above a resolved sysfs path."""
    p = resolved.rstrip("/")
    for _ in range(40):
        name = os.path.basename(p)
        if _USB_DEV_NAME_RE.match(name):
            return name
        parent = os.path.dirname(p)
        if not parent or parent == p:
            break
        p = parent
    return None


def _tty_to_usb(tty_glob="/sys/class/tty/ttyUSB*"):
    """Map USB device dir name -> sorted list of the tty names it provides.

    Resolves through /sys/class/tty (kernel-guaranteed symlinks into the device
    tree), not /dev: on this kernel devtmpfs creates plain character nodes in
    /dev, so realpath("/dev/ttyUSB0") would just return itself.
    """
    mapping = {}
    for dev in glob.glob(tty_glob):
        try:
            resolved = os.path.realpath(dev)
        except OSError:
            continue
        usb_name = _usb_dir_of(resolved)
        if usb_name:
            mapping.setdefault(usb_name, []).append(os.path.basename(dev))
    return {k: sorted(v) for k, v in mapping.items()}


def _block_to_usb(block_dir="/sys/block"):
    """Map USB device dir name -> sorted list of block devices (sd*) it owns."""
    mapping = {}
    try:
        entries = os.listdir(block_dir)
    except OSError:
        return mapping
    for b in sorted(entries):
        if not b.startswith("sd"):
            continue                      # mmcblk/zram are internal or virtual
        target = os.path.join(block_dir, b, "device")
        try:
            resolved = os.path.realpath(target)
        except OSError:
            continue
        usb_name = _usb_dir_of(resolved)
        if usb_name:
            mapping.setdefault(usb_name, []).append(b)
    return {k: sorted(v) for k, v in mapping.items()}


def mount_points_for(devname, mounts_text):
    """Mount points of /dev/<devname> or any of its partitions (from /proc/mounts text)."""
    pts = set()
    for line in mounts_text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        base = os.path.basename(parts[0])
        rest = base[len(devname):] if base.startswith(devname) else ""
        # partitions are named <dev>1, <dev>2 (sd/hd) or <dev>p1, <dev>p2 (mmcblk/nvme)
        if base == devname or rest.isdigit() or (rest[:1] == "p" and rest[1:].isdigit()):
            pts.add(parts[1])
    return sorted(pts)


def _human_bytes(n):
    v = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if v < 1024 or unit == "GiB":
            break
        v /= 1024
    return f"{int(v)} {unit}" if unit == "B" else f"{v:.1f} {unit}"


# Persistent physical storage as exposed in /sys/block: USB/SCSI sticks (sd*),
# legacy IDE (hd*), SD cards/eMMC incl. the boot card (mmcblk*), NVMe. Virtual or
# mapped devices (zram, loop, ram, dm-*, nbd) do not match and stay out of the table.
PHYSICAL_DISK_RE = re.compile(r"^(?:sd[a-z]+|hd[a-z]+|mmcblk\d+|nvme\d+n\d+)$")


def storage_info(block_dir="/sys/block", mounts_file="/proc/mounts"):
    """All persistent physical storage disks with total size and df-style usage (F19).

    Total size comes from /sys/block/<dev>/size (512-byte sectors). Used/Available
    are summed over all mounted partitions of the disk via os.statvfs on each mount
    point, using df semantics: used = (blocks - bfree) * frsize, avail = bavail *
    frsize, pct = used / (used + avail) * 100. A disk without any readable mount
    gets None stats (rendered as "-")."""
    mounts_text = _read_sys(mounts_file)
    disks = []
    try:
        entries = sorted(os.listdir(block_dir))
    except OSError:
        return disks
    for dev in entries:
        if not PHYSICAL_DISK_RE.match(dev):
            continue                      # zram/loop/ram/dm-* etc. are virtual or mapped
        size_raw = _read_sys(os.path.join(block_dir, dev, "size"))
        total_bytes = int(size_raw) * 512 if size_raw.isdigit() else None
        mounts = mount_points_for(dev, mounts_text)
        used = avail = 0
        ok = False
        for mp in mounts:
            try:
                st = os.statvfs(mp)
            except OSError:
                continue                  # vanished mid-run; the other mounts still count
            used += (st.f_blocks - st.f_bfree) * st.f_frsize
            avail += st.f_bavail * st.f_frsize
            ok = True
        disk = {"device": dev, "total_bytes": total_bytes, "mounts": mounts,
                "used_bytes": None, "avail_bytes": None, "pct": None}
        if ok:
            disk["used_bytes"] = used
            disk["avail_bytes"] = avail
            denom = used + avail
            if denom:
                disk["pct"] = used / denom * 100.0
        disks.append(disk)
    return disks


def scan_usb_devices(usb_dir="/sys/bus/usb/devices", tty_glob="/sys/class/tty/ttyUSB*",
                     block_dir="/sys/block"):
    """Enumerate the USB peripherals worth watching for presence.

    Skipped: root hubs (names like "usb1"), class-9 hub devices, and unnamed
    infrastructure (no product string AND no serial - e.g. the SoC-internal
    0424:7800 device on a Raspberry Pi). The identity key always includes the
    port path because both CP210x bridges share iSerial "0001"; replugging into
    another port is reported as OFFLINE + new ONLINE, which is the wanted signal.

    Returns {key: info} - one observation snapshot of /sys right now (F19 moved
    the storage size/mount details out of here into storage_info()).
    """
    ttys = _tty_to_usb(tty_glob)
    blocks = _block_to_usb(block_dir)

    devices = {}
    try:
        names = sorted(os.listdir(usb_dir))
    except OSError:
        return devices
    for name in names:
        if not _USB_DEV_NAME_RE.match(name):
            continue                      # root hubs (usb1, usb2) etc.
        d = os.path.join(usb_dir, name)
        vid = _read_sys(os.path.join(d, "idVendor"))
        pid = _read_sys(os.path.join(d, "idProduct"))
        if not vid or not pid:
            continue                      # mid-enumeration / vanishing device
        product = _read_sys(os.path.join(d, "product"))
        serial = _read_sys(os.path.join(d, "serial"))
        dev_class = _read_sys(os.path.join(d, "bDeviceClass")).lower()
        if dev_class == "09":
            continue                      # hub: a vanished hub takes its children with it
        tts = ttys.get(name, [])
        blks = blocks.get(name, [])
        if not product and not serial and not tts and not blks:
            continue                      # unnamed infrastructure (e.g. 0424:7800)

        # F19: size + mount info moved to the dedicated Storage section; keep only the
        # bare block device name here so watchdog rows still map 1:1 onto storage rows.
        details = list(tts) + blks

        kinds = []
        if tts:
            kinds.append("UART bridge")
        if blks:
            kinds.append("USB storage")
        key = f"{vid}:{pid}" + (f":{serial}" if serial else "") + f":{name}"
        devices[key] = {
            "label": product or f"{vid}:{pid}",
            "key": key,
            "type": "+".join(kinds) if kinds else "other",
            "port_path": name,
            "serial": serial or "-",
            "details": details,
        }
    return devices


def _parse_iso_utc(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def merge_usb_state(current, prev_devices, now_utc):
    """Presence state machine.

    Present now -> ONLINE; keeps the original "since" if already ONLINE, else
    since = now (first observation or return after OFFLINE). Previously known
    but absent this run -> OFFLINE with since = transition time; its last_seen
    stays at the moment it was last confirmed present.
    """
    out = {}
    now_iso = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    for key, info in current.items():
        prev = (prev_devices or {}).get(key) or {}
        since = prev.get("since") if prev.get("status") == "ONLINE" and prev.get("since") else now_iso
        out[key] = dict(info)
        out[key]["status"] = "ONLINE"
        out[key]["since"] = since
        out[key]["last_seen"] = now_iso
    for key, prev in (prev_devices or {}).items():
        if key not in current:
            d = dict(prev)
            d["status"] = "OFFLINE"
            d["since"] = now_iso
            out[key] = d                  # last_seen unchanged on purpose
    return out


def load_usb_state(path=USB_STATE_FILE):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        dev = data.get("devices", {})
        return dev if isinstance(dev, dict) else {}
    except (OSError, ValueError):
        return {}


def save_usb_state(devices, now_utc, path=USB_STATE_FILE):
    state = {"updated": now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"), "devices": devices}
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1)
        os.replace(tmp, path)              # atomic: readers never see a partial file
    except OSError as e:
        log(f"warning: could not write {path}: {e}")


def usb_watchdog(now_utc):
    """One cron-minute pass: enumerate, merge with persisted state, persist."""
    current = scan_usb_devices()
    devices = merge_usb_state(current, load_usb_state(), now_utc)
    save_usb_state(devices, now_utc)
    return devices


def render_usb_watchdog_html(devices, now_utc):
    """Presence table: Device | Type | Details | Status | Since | Last confirmed."""
    if not devices:
        return '<div class="none">no USB peripherals tracked yet</div>'

    def time_cell(iso_str):
        raw = htmllib.escape(str(iso_str or "-"))
        dt = _parse_iso_utc(str(iso_str or ""))
        if dt is None:
            return f'<td title="{raw}">{raw}</td>'
        secs = max(0, int((now_utc - dt).total_seconds()))
        return (f'<td data-sort="{int(dt.timestamp())}" title="{raw}">'
                f'{humanize_secs(secs)} ago</td>')

    trs = []
    for i, key in enumerate(sorted(devices)):
        info = devices[key]
        status = str(info.get("status", "?"))
        if status == "ONLINE":
            status_html = '<span style="color:#7f7">ONLINE</span>'
        else:
            status_html = (f'<span style="color:#f55" '
                           f'title="{htmllib.escape(str(info.get("since", "")))}">{status}</span>')
        details = htmllib.escape("; ".join(info.get("details") or []) or "-")
        trs.append(
            f'<tr data-order="{i}">'
            f'<td title="{htmllib.escape(key)}">{htmllib.escape(str(info.get("label", key)))}</td>'
            f"<td>{info.get('type', 'other')}</td>"
            f"<td>{details}</td>"
            f"<td>{status_html}</td>"
            + time_cell(info.get("since"))
            + time_cell(info.get("last_seen"))
            + "</tr>")

    return ('<table class="sortable" id="tbl-usb-wd"><thead><tr>'
            '<th>Device</th><th>Type</th><th>Details</th><th>Status</th>'
            "<th>Since (status age)</th><th>Last confirmed (UTC)</th>"
            f'</tr></thead><tbody>{"".join(trs)}</tbody></table>'
            + '\n<p style="font-size:11px;color:#575;margin:4px 0 0">'
            'identity = vendor:product[:serial]:port path &middot; replugging into another port '
            'shows up as OFFLINE + new ONLINE &middot; state persists across reboots in '
            '/var/lib/meshcore/usb-state.json &middot; display only, no commands fired yet</p>')


def render_storage_html(storages):
    """Storage table (F19): Device | Total size | Used | Available | Used % | Mounted at.

    Byte cells carry data-sort = raw bytes so the shared sort JS orders them
    numerically; a disk without any readable mount renders "-" in the usage cells."""
    if not storages:
        return '<div class="none">no physical storage detected</div>'

    def bytes_cell(value):
        if value is None:
            return "<td>-</td>"
        return f'<td class="num" data-sort="{value}">{_human_bytes(value)}</td>'

    trs = []
    for i, d in enumerate(storages):
        pct = (f'<td class="num" data-sort="{d["pct"]:.1f}">{d["pct"]:.1f} %</td>'
               if d["pct"] is not None else "<td>-</td>")
        mounts = ", ".join(htmllib.escape(m) for m in d["mounts"]) or "&mdash;"
        trs.append(
            f'<tr data-order="{i}">'
            f"<td>{d['device']}</td>"
            + bytes_cell(d["total_bytes"])
            + bytes_cell(d["used_bytes"])
            + bytes_cell(d["avail_bytes"])
            + pct
            + f"<td>{mounts}</td></tr>")

    return ('<table class="sortable" id="tbl-storage"><thead><tr>'
            "<th>Device</th>"
            '<th class="num">Total size</th><th class="num">Used</th>'
            '<th class="num">Available</th><th class="num">Used %</th>'
            f"<th>Mounted at</th></tr></thead><tbody>{''.join(trs)}</tbody></table>")


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>DK0MAV MeshCore Neighbors</title>
<meta http-equiv="refresh" content="58">   <!-- auto-reload just before each cron minute -->
<meta name="updated" content="{iso}">
{started_meta}
<style>
    body {{ background:#111; color:#0f0; font-family:'Courier New',monospace; margin:0; padding:16px 20px; }}
    h2 {{ margin:0 0 4px; font-size:15px; text-align:center; font-weight:normal; }}
    .sub {{ text-align:center; font-size:12px; color:#7a7; margin-bottom:14px; }}
    table {{ width:100%; border-collapse:collapse; font-size:15px; }}
    th, td {{ padding:6px 14px; border-bottom:1px solid #233; text-align:left; }}
    thead th {{ color:#9f9; background:#152415; border-bottom:2px solid #0f0; }}
    td.num, th.num {{ text-align:right; }}
    .key {{ letter-spacing:2px; }}
    tr:hover {{ background:#182a18; }}
    .none {{ padding:16px 0; text-align:center; color:#7a7; font-size:14px; }}
    footer {{ margin-top:12px; font-size:11px; color:#575; text-align:center; }}
    h3 {{ color:#9f9; font-size:14px; font-weight:normal; margin:20px 0 6px; border-bottom:1px solid #233; padding-bottom:3px; }}
    table.sortable thead th {{ cursor:pointer; user-select:none; }}
    table.sortable thead th:hover {{ background:#1c331c; }}
    .sortarrow {{ display:inline-block; min-width:8px; margin-left:4px; color:#3d5c3d; font-size:11px; }}
    th[data-mode] .sortarrow {{ color:#7f7; }}
    .tbtn {{ background:#000; color:#7f7; border:1px solid #7f7; border-radius:3px;
             font-family:'Courier New',monospace; font-size:11px; padding:2px 8px; cursor:pointer; }}
    .tbtn:hover {{ background:#7f7; color:#000; }}
    .tresult {{ color:#575; font-size:11px; margin-left:6px; }}
</style>
</head>
<body>
<h2>DK0MAV mc&sup2;-Peine-Node &mdash; MeshCore: {node}, {freq} &nbsp;|&nbsp; MeshCom: {meshcom_name}, {meshcom_freq}</h2>
{sublines}
<h3>MeshCore Neighbors</h3>
{table}
{extra_sections}
<footer>every node ever heard, merged with this run&apos;s live SNR &middot; source: repeater CLI
<code>neighbors</code> over {src_port} &middot; updated every minute by cron</footer>
<script>
(function () {{
    var t0 = new Date(document.querySelector('meta[name=updated]').content);
    var ms = document.querySelector('meta[name=started]');
    var t1 = ms ? new Date(ms.content) : null;   // F18: system boot time (absent if unreadable)
    function tick() {{
        var s = Math.max(0, Math.floor((Date.now() - t0.getTime()) / 1000));
        document.getElementById('upd').textContent =
            t0.toISOString().replace('T', ' ').slice(0, 19) + " UTC (" + human(s) + " ago)";
        if (t1 && !isNaN(t1.getTime())) {{
            var u = Math.max(0, Math.floor((Date.now() - t1.getTime()) / 1000));
            document.getElementById('started').textContent =
                t1.toISOString().replace('T', ' ').slice(0, 19) + " UTC (" + human(u) + " ago)";
        }}
        var lc = document.getElementById('local-clock');   // F24: viewer's own clock, live
        if (lc) lc.textContent = new Date().toISOString().replace('T', ' ').slice(0, 19) + " UTC";
    }}
    function human(s) {{
        if (s < 60) return s + " s";
        if (s < 3600) return Math.floor(s / 60) + " m " + (s % 60) + " s";
        if (s < 86400) return Math.floor(s / 3600) + " h " + Math.floor((s % 3600) / 60) + " m";
        return Math.floor(s / 86400) + " d " + Math.floor((s % 86400) / 3600) + " h";
    }}
    tick(); setInterval(tick, 1000);
}})();
</script>
<script>
/*__SORTJS__*/
</script>
</body>
</html>
"""


# Client-side table sorting (injected verbatim; no .format placeholders inside).
# Every sortable header shows an indicator from the start: faint up/down cross on all
# columns (they are clickable), bright arrow on the active column with its direction.
# Tables load pre-sorted by their first column (asc); a click cycles asc -> desc -> device order.
SORT_JS = """(function () {
    'use strict';
    document.querySelectorAll('table.sortable').forEach(function (t) {
        var ths = t.tHead.rows[0].cells;
        function activate(th, idx, next) {
            for (var j = 0; j < ths.length; j++) {
                ths[j].removeAttribute('data-mode');
                ths[j].querySelector('.sortarrow').textContent = '\\u2195';
            }
            var all = Array.prototype.slice.call(t.tBodies[0].rows);
            // F24: rows with data-pin stay on top for every sort direction.
            var pinned = all.filter(function (r) { return r.getAttribute('data-pin'); });
            var rows = all.filter(function (r) { return !r.getAttribute('data-pin'); });
            if (next) {
                th.setAttribute('data-mode', next);
                th.querySelector('.sortarrow').textContent = next === 'asc' ? '\\u25b2' : '\\u25bc';
                var dir = next === 'asc' ? 1 : -1;
                rows.sort(function (a, b) {
                    var ca = a.cells[idx], cb = b.cells[idx];
                    if (!ca || !cb) return 0;
                    var va = ca.getAttribute('data-sort');
                    var vb = cb.getAttribute('data-sort');
                    if (va === null) va = ca.textContent.trim();
                    if (vb === null) vb = cb.textContent.trim();
                    var na = parseFloat(va), nb = parseFloat(vb);
                    if (!isNaN(na) && !isNaN(nb)) return (na - nb) * dir;
                    return va < vb ? -dir : (va > vb ? dir : 0);
                });
            } else {
                rows.sort(function (a, b) {
                    return parseInt(a.getAttribute('data-order'), 10)
                         - parseInt(b.getAttribute('data-order'), 10);
                });
            }
            var tbody = t.tBodies[0];
            pinned.concat(rows).forEach(function (r) { tbody.appendChild(r); });
        }
        for (var i = 0; i < ths.length; i++) (function (th, idx) {
            var arrow = document.createElement('span');
            arrow.className = 'sortarrow';
            th.appendChild(arrow);
            th.title = 'click to sort - again to reverse, third click restores device order';
            th.onclick = function () {
                var mode = th.getAttribute('data-mode') || '';
                activate(th, idx, (mode === '') ? 'asc' : (mode === 'asc' ? 'desc' : ''));
            };
        })(ths[i], i);
        if (ths.length) activate(ths[0], 0, 'asc');   // initial state: first column asc
    });
})();"""


def build_merged_table(rows, state, now_utc):
    """One sortable table for every node ever heard; this run's rows add the live SNR.

    The nodes-ever state (kept fresh by update_nodes_ever before this is called)
    supplies last-seen / best / worst / sightings; a row that did not appear in this
    run's reply shows its stored age and "-" for the live SNR column. Newest first.
    """
    fresh_db = {key: round(snr / 4, 2) for key, _age, snr in rows}
    items = []
    for key, e in (state or {}).items():
        try:
            last_ts = datetime.strptime(e["last"], "%Y-%m-%d %H:%M:%S UTC").replace(
                tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue                              # malformed state entry -> skip row
        items.append((key, e, last_ts))
    items.sort(key=lambda t: (t[2], t[0]), reverse=True)
    if not items:
        return '<div class="none">no nodes recorded yet (-none-)</div>'
    trs = []
    for i, (key, e, last_ts) in enumerate(items):
        name_e = htmllib.escape(names.get(key, "-"))
        age = max(0, int(now_utc.timestamp() - last_ts.timestamp()))
        seen_iso = last_ts.strftime("%Y-%m-%d %H:%M:%S UTC")
        best = float(e.get("best_db", 0.0))
        worst = float(e.get("worst_db", 0.0))
        sights = int(e.get("sightings", 0))
        db = fresh_db.get(key)
        if db is not None:
            color = "#7f7" if db >= -6 else ("#fd5" if db >= -18 else "#f95")
            snr_cell = (f'<td class="num" style="color:{color}" '
                        f'data-sort="{db:.2f}">{db:+.2f}</td>')
        else:                                     # not heard this run -> no live value
            snr_cell = '<td class="num">-</td>'
        trs.append(
            f'<tr data-order="{i}">'
            f'<td class="key" data-sort="{key}">{key}</td>'
            f'<td data-sort="{name_e.lower()}">{name_e}</td>'
            f'<td class="num" title="{seen_iso}" data-sort="{age}">{humanize_secs(age)}</td>'
            f'{snr_cell}'
            f'<td class="num" style="color:#7f7" data-sort="{best:.2f}">{best:+.2f}</td>'
            f'<td class="num" style="color:#f95" data-sort="{worst:.2f}">{worst:+.2f}</td>'
            f'<td class="num" data-sort="{sights}">{sights}</td></tr>')
    return ('<table class="sortable" id="tbl-nodes"><thead><tr>'
            '<th>Key prefix</th><th>Node</th>'
            '<th class="num">Last seen</th><th class="num">SNR (dB)</th>'
            '<th class="num">Best SNR (dB)</th><th class="num">Worst SNR (dB)</th>'
            f'<th class="num">Sightings</th></tr></thead><tbody>{"".join(trs)}</tbody></table>')


def write_html(rows, now_utc, nodes_ever=None, usb_infos=None, src_port="-", ntp=None,
               ups=None, wd_devices=None, storages=None):
    if nodes_ever is not None:
        table = build_merged_table(rows, nodes_ever, now_utc)
    else:
        table = '<div class="none">no neighbors yet (-none-)</div>'

    sections = []
    if usb_infos is not None:
        sections.append("<h3>USB serial devices</h3>\n" + render_usb_html(usb_infos))
    # F12: presence watchdog right after the serial table - same hardware, different question.
    if wd_devices is not None:
        sections.append("<h3>USB device watchdog</h3>\n"
                        + render_usb_watchdog_html(wd_devices, now_utc))
    # F19: physical storage (sd*) with size/usage/mounts — between watchdog and clock.
    if storages is not None:
        sections.append("<h3>Storage</h3>\n" + render_storage_html(storages))
    # F13: always shown — the Pi system row and the manual time-sync buttons must be
    # visible even when no device clock is present (that is often exactly when NTP is down).
    if ntp is not None:
        sections.append("<h3>Clock &amp; NTP</h3>\n"
                        + render_clock_section(usb_infos, ntp, now_utc))
    # F14: readings last — user's choice (2026-10-11): the PiUPS+ / Power section moved from
    # first among the extras to the end of the page.
    if ups is not None:
        sections.append("<h3>PiUPS+ / Power</h3>\n" + render_piups_section(ups))
    extra = "\n".join(sections)

    # F18: "Started" uptime line above the Updated line — system boot time from
    # /proc/uptime (wall-clock derived; see boot_time_utc). Omitted entirely when
    # unreadable, so a wrong timestamp never shows.
    started = boot_time_utc(now_utc)
    if started is not None:
        started_meta = f'<meta name="started" content="{started.isoformat(timespec="seconds")}">'
        sublines = ('<div class="sub">Started <span id="started"></span></div>\n'
                    '<div class="sub">Updated <span id="upd"></span></div>')
    else:
        started_meta = ""
        sublines = '<div class="sub">Updated <span id="upd"></span></div>'

    page = HTML_TEMPLATE.format(
        iso=now_utc.isoformat(timespec="seconds"),
        started_meta=started_meta, sublines=sublines,
        node=NODE_NAME, freq=MESHCORE_FREQ,
        meshcom_name=htmllib.escape(MESHCOM_NAME), meshcom_freq=MESHCOM_FREQ,
        table=table, extra_sections=extra, src_port=src_port)
    page = page.replace("/*__SORTJS__*/", SORT_JS)
    # F22: atomic publish — write a sibling .tmp then os.replace() so a browser
    # refreshing mid-write never sees a half-written page (same pattern as the
    # state files). Keep the mode of the existing target (installed 666 so the
    # engine user can replace it and nginx can still read it).
    tmp = HTML_OUT + ".tmp"
    try:
        mode = os.stat(HTML_OUT).st_mode & 0o777
    except OSError:
        mode = 0o644
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(page)
    os.chmod(tmp, mode)
    os.replace(tmp, HTML_OUT)


def main():
    global names
    # Per-port flocks (inside probe_port) keep us from fighting interactive
    # meshcli / esptool sessions on a single port; the other port still runs.

    names = load_names()
    import serial as pyserial            # from meshcore-venv

    ports = sorted(glob.glob(PORTS_GLOB))
    if not ports:
        log("ERROR: no /dev/ttyUSB* devices present")
        return 1

    now_utc = datetime.now(timezone.utc)
    # F24: pick up (and consume) a queued manual time-sync request from the
    # dashboard service before probing, so the matching port probe applies it
    # under the normal per-port flock and verifies it in the same run.
    manual = load_manual_sync_request()
    infos = [probe_port(p, pyserial, now_utc, manual=manual) for p in ports]
    ensure_state_dir()

    # F7: merge live classification with the persisted mapping (ports.json).
    # Unresponsive ports fall back to their saved role and get flagged stale;
    # a differing live role is logged as a USB-swap event. Core selection below
    # therefore also sees roles restored from state, so a hung console on the
    # repeater port degrades gracefully (stale flag + empty table) instead of
    # "no MeshCore port identified".
    apply_port_persistence(infos, now_utc)
    ntp = system_ntp_status()
    ups = read_piups(now_utc)
    # F12: USB presence watchdog (bridges + sticks); state survives reboots.
    wd_devices = usb_watchdog(now_utc)
    # F19: physical storage overview (sd* disks, df-style usage per disk).
    storages = storage_info()

    cores = [p for p in infos if p["role"] == "meshcore"]
    if len(cores) > 1:
        log(f"warning: {len(cores)} ports answered as MeshCore: "
            f"{[c['port'] for c in cores]} (using the first)")
    core = cores[0] if cores else None

    entries = list(core["rows"]) if core is not None else []
    src_port = core["port"] if core is not None else "-"
    if core is None:
        log("ERROR: no MeshCore port identified this run (see USB table on the page)")

    # Deduplicate: keep the newest observation (lowest secs_ago) per node.
    best = {}
    for key, age, snr in entries:
        if key not in best or age < best[key][0]:
            best[key] = (age, snr)
    rows = sorted(((k, a, s) for k, (a, s) in best.items()), key=lambda r: r[1])

    nodes_ever = update_nodes_ever(rows, now_utc)
    write_html(rows, now_utc, nodes_ever, usb_infos=infos, src_port=src_port, ntp=ntp,
               ups=ups, wd_devices=wd_devices, storages=storages)
    def _role_tag(p):
        return p["role"] + ("(stale)" if p.get("stale") else "")
    roles = ", ".join(f"{os.path.basename(p['port'])}={_role_tag(p)}" for p in infos)
    if ups is not None:
        ubat, icas = ups["volts"].get("U_Bat"), ups["volts"].get("I_Rasp")
        piups_tag = f"piups {ups['stale_s']} s old"
        if ubat is not None and icas is not None:
            piups_tag += f" U_Bat={ubat} mV I_Rasp={icas} mA"
    else:
        piups_tag = "piups no data (log missing or below LogLevel=debug)"
    wd_offline = [str(d.get("label", "?")) for d in wd_devices.values()
                  if d.get("status") == "OFFLINE"]
    wd_tag = f"usb-wd {len(wd_devices) - len(wd_offline)}/{len(wd_devices)} online"
    if wd_offline:
        wd_tag += " (offline: " + ", ".join(sorted(set(wd_offline))) + ")"
    log(f"ok: {roles}; {len(entries)} raw entries -> {len(rows)} unique node(s); "
        f"{len(nodes_ever)} node(s) in all-nodes-ever state; wrote {HTML_OUT}; "
        f"{piups_tag}; {wd_tag}")
    return 0 if core is not None else 1


if __name__ == "__main__":
    sys.exit(main())
