#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-License-Identifier: MIT
"""Core-engine regression suite — the pre-F18 feature base (F1/F4/F7/F8/F11/F12).

The per-feature suites test-f18+ cover the later features; this suite backfills
regression coverage for the foundational behaviors that predage them, all
hardware-free against synthetic inputs:

  t1  F1  parse_neighbor_entries: key/age/snr capture, upper-cased keys,
          non-matching noise ignored
  t2  F1  parse_clock_reply: "clock" reply -> aware UTC datetime, garbage -> None
  t3  F4  update_nodes_ever: first sighting creates entry, merge keeps
          first, advances last, counts sightings, clamps best/worst (snr/4)
  t4  F4  load_nodes_ever: keys upper-cased, corrupt state file -> {} + warning
  t5  F7  apply_port_persistence: unresponsive port falls back to saved role
          with stale flag + details note
  t6  F7  apply_port_persistence: live role wins over saved (swap logged),
          unknown-without-saved stays unknown
  t7  F7  load_ports_state: corrupt file -> empty shape
  t8  F8  clock_status_text: synced / ahead / MeshCom-behind hint / plain ok
  t9  F11 read_piups: status bits last-wins, readings + units, UTC ts
          conversion via gmtoff, stale_s computed
  t10 F11 read_piups: missing log -> None; no matching lines -> None
  t11 F12 merge_usb_state: ONLINE keeps since, return-after-offline resets it,
          OFFLINE keeps last_seen and stamps transition
  t12 F12 save/load usb state round trip keeps the file atomic (F22 pattern)

Run:  python3 test-core.py [engine-path]      (default: ./mesh-neighbors.py)
"""
import importlib.util
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "mesh-neighbors.py")

spec = importlib.util.spec_from_file_location("mn", ENGINE)
mn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mn)

UTC = timezone.utc
NOW = datetime(2026, 11, 2, 12, 0, 0, tzinfo=UTC)

failures = 0
def check(name, ok):
    global failures
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failures += 1

# --- t1 parse_neighbor_entries ------------------------------------------------
text = ("All neighbors (3):\n"
        "  00ABCDEF:120:-168  DK0MAV\n"
        "  aabb0011:5:-44\n"
        "  AABB0011:9:-40\n"
        "  GG112233:1:-100\n"
        "  12345678:9999999999:0\n"
        "  1234567:9:-5\n")
got = mn.parse_neighbor_entries(text)
check("t1 parse_neighbor_entries: captures hex keys/age/snr, noise ignored",
      got == [("00ABCDEF", 120, -168), ("AABB0011", 5, -44), ("AABB0011", 9, -40),
              ("12345678", 9999999999, 0)])

# --- t2 parse_clock_reply ------------------------------------------------------
check("t2 parse_clock_reply: valid + invalid + no-match",
      mn.parse_clock_reply("  -> 11:48 - 15/5/2024 UTC") == datetime(2024, 5, 15, 11, 48, tzinfo=UTC)
      and mn.parse_clock_reply("  -> 25:99 - 32/13/2024 UTC") is None
      and mn.parse_clock_reply("ERROR: command not found") is None)

# --- t3/t4 nodes-ever (F4) ------------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    statefile = os.path.join(d, "nodes-ever.json")
    mn.NODES_EVER_FILE = statefile
    s1 = mn.update_nodes_ever([("AABB0011", 0, -168)], NOW)
    later = datetime(2026, 11, 2, 13, 0, 0, tzinfo=UTC)
    s2 = mn.update_nodes_ever([("AABB0011", 60, -100), ("AABB0011", 60, -300)], later)
    e = s2["AABB0011"]
    check("t3 update_nodes_ever: first/last/sightings/best/worst merge",
          s1["AABB0011"]["first"] == "2026-11-02 12:00:00 UTC"
          and e["first"] == "2026-11-02 12:00:00 UTC"
          and e["last"] == "2026-11-02 12:59:00 UTC"
          and e["sightings"] == 3
          and e["best_db"] == -25.0 and e["worst_db"] == -75.0
          and json.load(open(statefile))["AABB0011"]["sightings"] == 3)
    with open(statefile, "w") as f:
        f.write("this is not json {{{")
    check("t4 load_nodes_ever: corrupt state -> {} (logged warning)", mn.load_nodes_ever() == {})
    with open(statefile, "w") as f:
        json.dump({"aabb0011": {"first": "x"}}, f)
    check("t4b load_nodes_ever: keys upper-cased", list(mn.load_nodes_ever()) == ["AABB0011"])

# --- t5/t6/t7 port persistence (F7) ---------------------------------------------
with tempfile.TemporaryDirectory() as d:
    portsfile = os.path.join(d, "ports.json")
    mn.PORTS_FILE = portsfile
    base = {"/dev/ttyUSB0": {"role": "meshcore", "usb_path": "1-1.2"},
            "/dev/ttyUSB1": {"role": "meshcom", "usb_path": "1-1.3"}}
    json.dump({"updated": "2026-11-01 10:00:00 UTC", "ports": base}, open(portsfile, "w"))

    p_ok = {"port": "/dev/ttyUSB0", "role": "meshcore", "usb_path": "1-1.2", "ok": True, "stale": False, "details": "x"}
    p_dead = {"port": "/dev/ttyUSB1", "role": "unknown", "usb_path": "-", "ok": True, "stale": False, "details": ""}
    mn.apply_port_persistence([p_ok, p_dead], NOW)
    check("t5 apply_port_persistence: dead port keeps saved role, flagged stale",
          p_dead["role"] == "meshcom" and p_dead["stale"] is True and p_dead["ok"] is False
          and "stale (last confirmed 2026-11-01 10:00:00 UTC)" in p_dead["details"])

    p_swap = {"port": "/dev/ttyUSB0", "role": "meshcom", "usb_path": "1-1.4", "ok": True, "stale": False, "details": ""}
    p_new = {"port": "/dev/ttyUSB9", "role": "unknown", "usb_path": "-", "ok": True, "stale": False, "details": ""}
    mn.apply_port_persistence([p_swap, p_new], NOW)
    saved = json.load(open(portsfile))["ports"]
    check("t6 apply_port_persistence: live role overwrites saved; unknown-without-history untouched",
          saved["/dev/ttyUSB0"]["role"] == "meshcom"
          and "/dev/ttyUSB9" not in saved and p_new["stale"] is False)

    with open(portsfile, "w") as f:
        f.write("garbage")
    st = mn.load_ports_state()
    check("t7 load_ports_state: corrupt -> empty shape", st == {"updated": "", "ports": {}})

# --- t8 clock_status_text (F8) ---------------------------------------------------
check("t8 clock_status_text branches",
      mn.clock_status_text({"synced": True, "lag_s": 300}, "meshcore").startswith("auto-synced this run (was 5 m")
      and "running ahead by 2 m" in mn.clock_status_text({"synced": False, "lag_s": -150}, "meshcore")
      and "self-syncs via NTP" in mn.clock_status_text({"synced": False, "lag_s": 300}, "meshcom")
      and mn.clock_status_text({"synced": False, "lag_s": 300}, "meshcore") == "ok")

# --- t9/t10 read_piups (F11) -------------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    uplog = os.path.join(d, "live.log")
    mn.PIUPS_LOG = uplog
    lines = [
        "2026-11-02 12:59:58 [DEBUG] U_Bat: 4100 mV",
        "2026-11-02 12:59:58 [DEBUG] I_Rasp: 700 mA",
        "2026-11-02 12:59:59 [INFO] Primary Power Supply: 0",
        "2026-11-02 12:59:59 [INFO] Primary Power Supply: 1",
        "2026-11-02 12:59:59 [INFO] Battery Low: 0",
        "2026-11-02 13:00:00 [DEBUG] U_Bat: 4142 mV",
        "2026-11-02 13:00:00 [DEBUG] U_Ext: 12900 mV",
        "2026-11-02 13:00:00 [INFO] something unknown: 7",
    ]
    # read_piups interprets log timestamps with the HOST's gmtoff (time.localtime
    # inside); fixture timestamps are written in host-local time, so compute the
    # expected UTC instants the same way.
    import time as _t
    gmto = _t.localtime().tm_gmtoff
    def loc(ts_str):
        naive = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        from datetime import timedelta as _td
        return naive.replace(tzinfo=timezone(_td(seconds=gmto))).astimezone(UTC)
    open(uplog, "w").write("\n".join(lines) + "\n")
    up = mn.read_piups(loc("2026-11-02 13:00:00"))
    check("t9 read_piups: status last-wins, readings, units, stale_s",
          up is not None
          and up["status"] == {"primary": 1, "low": 0}
          and up["volts"] == {"U_Bat": 4142, "I_Rasp": 700, "U_Ext": 12900}
          and up["ts"]["U_Bat"][0] == loc("2026-11-02 13:00:00") and up["ts"]["U_Bat"][1] == "mV"
          and up["stale_s"] == 0)
    os.remove(uplog)
    check("t10 read_piups: missing file -> None, unmatched content -> None",
          mn.read_piups(NOW) is None and (open(uplog, "w").write("no matches here\n") or mn.read_piups(NOW) is None))

# --- t11/t12 watchdog state (F12) ---------------------------------------------------
cur = {"k1": {"product": "bridge"}, "k2": {"product": "stick"}}
prev = {"k1": {"product": "bridge", "status": "ONLINE", "since": "2026-11-01 08:00:00 UTC", "last_seen": "2026-11-02 11:59:00 UTC"},
        "k2": {"product": "stick", "status": "OFFLINE", "since": "2026-11-02 11:30:00 UTC", "last_seen": "2026-11-02 11:29:00 UTC"},
        "k3": {"product": "gone", "status": "ONLINE", "since": "2026-11-01 08:00:00 UTC", "last_seen": "2026-11-02 11:59:00 UTC"}}
m = mn.merge_usb_state(cur, prev, NOW)
check("t11 merge_usb_state: since-keeping, return, offline transition",
      m["k1"]["since"] == "2026-11-01 08:00:00 UTC"
      and m["k2"]["since"] == "2026-11-02 12:00:00 UTC"          # returned -> new since
      and m["k2"]["status"] == "ONLINE" and m["k2"]["last_seen"] == "2026-11-02 12:00:00 UTC"
      and m["k3"]["status"] == "OFFLINE" and m["k3"]["since"] == "2026-11-02 12:00:00 UTC"
      and m["k3"]["last_seen"] == "2026-11-02 11:59:00 UTC")     # frozen on purpose

with tempfile.TemporaryDirectory() as d:
    statef = os.path.join(d, "usb-state.json")
    mn.save_usb_state(m, NOW, path=statef)
    loaded = mn.load_usb_state(path=statef)
    check("t12 usb-state save/load round trip, no .tmp residue",
          loaded["k1"]["status"] == "ONLINE"
          and not os.path.exists(statef + ".tmp"))

print(f"core: {failures} failures")
sys.exit(1 if failures else 0)
