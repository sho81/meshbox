#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""F25 regression suite — Temperatures table (SoC sensor + permanent abs min/max).

  t1  read_temps: synthetic thermal zones -> "SoC" row, out-of-range zone dropped
  t2  read_temps vcgencmd fallback (no zones readable -> fake measure_temp script)
  t3  sanity gate: absurd values from either source are rejected
  t4  update_temps_ever cold start: file created with min == max == first sample
  t5  min/max move with samples; an in-between sample rewrites nothing
  t6  history survives a "reboot" (fresh load); corrupt state self-heals
  t7  junk record (non-numeric min/max) is reinitialised from the current sample
  t8  render_temps_html rows: deg C cells with data-sort + UTC timestamps
  t9  sensor gone but history kept: Now cell "-", min/max stay
  t10 empty state renders the "none" placeholder
  t11 full page: six sections, Temperatures between Clock & NTP and PiUPS+ / Power

Run:  python3 test-f25.py [engine-path]
Defaults resolve for both the repo root and the flat staging layout.
"""
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

def _find(name):
    for cand in (os.path.join(HERE, name), os.path.join(os.path.dirname(HERE), name)):
        if os.path.isfile(cand):
            return cand
    raise SystemExit(f"{name} not found next to this suite")

ENGINE = sys.argv[1] if len(sys.argv) > 1 else _find("mesh-neighbors.py")

spec = importlib.util.spec_from_file_location("mn", ENGINE)
mn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mn)          # module level is constants + defs only (no I/O)
mn.names = {}

NOW = datetime(2026, 11, 6, 13, 2, 0, tzinfo=timezone.utc)

PASS = []


def check(name, cond, info=""):
    if cond:
        PASS.append(name)
        print(f"PASS {name}")
    else:
        print(f"FAIL {name} {info}")
        sys.exit(1)


td = tempfile.mkdtemp(prefix="f25-")

# ---------------------------------------------------------------- t1 sysfs zones
zones = os.path.join(td, "thermal")
os.makedirs(zones)


def make_zone(name, ztype, temp):
    z = os.path.join(zones, name)
    os.makedirs(z, exist_ok=True)
    with open(os.path.join(z, "type"), "w") as f:
        f.write(ztype + "\n")
    with open(os.path.join(z, "temp"), "w") as f:
        f.write(str(temp) + "\n")


make_zone("thermal_zone0", "cpu-thermal", 41856)          # -> SoC 41.9
make_zone("thermal_zone1", "cpu-thermal", 999000)         # absurd -> dropped
make_zone("thermal_zone2", "gpu-thermal", 50000)          # future hw -> own "GPU" row
make_zone("thermal_zone4b", "foo-thermal", 30000)         # unknown type -> own name kept
make_zone("thermal_zone3", "", "")                        # unreadable -> skipped
temps = mn.read_temps(thermal_glob=os.path.join(zones, "thermal_zone*"),
                      vcgencmd=os.path.join(td, "no-vcgencmd"))
check("t1 SoC row from cpu-thermal zone, millidegrees -> 1 decimal",
      {"source": "SoC", "c": 41.9} in temps, str(temps))
check("t1 out-of-range + unreadable zones dropped; gpu-thermal mapped, unknown type keeps own name",
      len(temps) == 3 and any(t["source"] == "GPU" for t in temps)
      and any(t["source"] == "foo-thermal" for t in temps), str(temps))

# ---------------------------------------------------------------- t2 vcgencmd fallback
fake = os.path.join(td, "vcgencmd")
with open(fake, "w") as f:
    f.write("#!/bin/sh\necho \"temp=43.9'C\"\n")
os.chmod(fake, 0o755)
temps2 = mn.read_temps(thermal_glob=os.path.join(zones, "none*"), vcgencmd=fake)
check("t2 vcgencmd fallback reads SoC when no zone is readable",
      temps2 == [{"source": "SoC", "c": 43.9}], str(temps2))

# ---------------------------------------------------------------- t3 sanity gate
with open(fake, "w") as f:
    f.write("#!/bin/sh\necho \"temp=999.9'C\"\n")
os.chmod(fake, 0o755)
check("t3 absurd vcgencmd value rejected",
      mn.read_temps(thermal_glob=os.path.join(zones, "none*"), vcgencmd=fake) == [])
make_zone("thermal_zone4", "cpu-thermal", -274000)
check("t3 absurd sysfs value rejected",
      all(t["c"] > -50 for t in mn.read_temps(
          thermal_glob=os.path.join(zones, "thermal_zone4"), vcgencmd=fake))
      and mn.read_temps(thermal_glob=os.path.join(zones, "thermal_zone4"),
                        vcgencmd=fake) == [])

# ---------------------------------------------------------------- t4..t7 state file
state = os.path.join(td, "temps-ever.json")
ever = mn.update_temps_ever([{"source": "SoC", "c": 41.9}], NOW, path=state)
with open(state, encoding="utf-8") as f:
    doc = json.load(f)
check("t4 cold start: file created, min == max == first sample + UTC timestamps",
      doc["sources"]["SoC"] == {"min": 41.9, "min_at": "2026-11-06 13:02 UTC",
                                "max": 41.9, "max_at": "2026-11-06 13:02 UTC"}
      and ever["SoC"]["min"] == 41.9, json.dumps(doc))

morning = datetime(2026, 11, 6, 4, 12, tzinfo=timezone.utc)
mn.update_temps_ever([{"source": "SoC", "c": 8.2}], morning, path=state)
mn.update_temps_ever([{"source": "SoC", "c": 62.0}], NOW, path=state)
before = os.stat(state).st_mtime_ns
ever = mn.update_temps_ever([{"source": "SoC", "c": 30.0}], NOW, path=state)
after = os.stat(state).st_mtime_ns
check("t5 min/max track extremes with their own timestamps",
      ever["SoC"]["min"] == 8.2 and ever["SoC"]["min_at"] == "2026-11-06 04:12 UTC"
      and ever["SoC"]["max"] == 62.0 and ever["SoC"]["max_at"] == "2026-11-06 13:02 UTC",
      json.dumps(ever))
check("t5 in-between sample changes nothing -> file not rewritten", after == before,
      f"{before} vs {after}")

reloaded = mn.load_temps_ever(path=state)
check("t6 history survives reboot (fresh load sees min/max)",
      reloaded["SoC"]["max"] == 62.0 and reloaded["SoC"]["min"] == 8.2, str(reloaded))
with open(state, "w", encoding="utf-8") as f:
    f.write("{not json")
check("t6 corrupt state -> load {} and self-heal on next update",
      mn.load_temps_ever(path=state) == {}
      and mn.update_temps_ever([{"source": "SoC", "c": 20.0}], NOW, path=state)["SoC"]
      == {"min": 20.0, "min_at": "2026-11-06 13:02 UTC", "max": 20.0,
          "max_at": "2026-11-06 13:02 UTC"})
with open(state, "w", encoding="utf-8") as f:
    json.dump({"sources": {"SoC": {"min": "hot", "min_at": "?", "max": "hot", "max_at": "?"}}}, f)
healed = mn.update_temps_ever([{"source": "SoC", "c": 33.3}], NOW, path=state)
check("t7 junk record reinitialised from current sample",
      healed["SoC"]["min"] == 33.3 and healed["SoC"]["max"] == 33.3, str(healed))

# ---------------------------------------------------------------- t8..t10 render
EVER = {"SoC": {"min": 8.2, "min_at": "2026-11-06 04:12 UTC",
                "max": 62.0, "max_at": "2026-10-31 14:03 UTC"}}
html = mn.render_temps_html([{"source": "SoC", "c": 41.9}], EVER)
check("t8 sortable table + 4 cells with numeric data-sort",
      'id="tbl-temps"' in html and html.count("<td") == 4
      and 'data-sort="41.9">41.9 &deg;C' in html and 'data-sort="8.2"' in html
      and 'data-sort="62.0"' in html, html)
check("t8 min/max cells carry the recorded UTC date+time",
      "2026-11-06 04:12 UTC" in html and "2026-10-31 14:03 UTC" in html
      and "<th class=\"num\">Abs min (UTC)</th>" in html, html)
check("t8 footer explains single sensor + permanent min/max reset",
      "temps-ever.json" in html and "delete that file to reset" in html, html)
html9 = mn.render_temps_html([], EVER)
check("t9 sensor gone: Now '-', history rows stay",
      "<td>-</td>" in html9 and 'data-sort="8.2"' in html9, html9)
check("t10 no source at all -> none placeholder",
      mn.render_temps_html([], {}) == '<div class="none">no temperature sensor found</div>')

# ---------------------------------------------------------------- t11 full page
NTP = {"tz": "Europe/Berlin (CET, +0100)", "ntp": "active", "synced": "yes"}
UPS = {
    "status": {"primary": 1, "secondary": 0, "low": 0, "charging": 0, "full": 0, "button": 0},
    "volts": {"U_Bat": 4154, "I_Rasp": 802, "U_USB": 5064, "U_USV": 439, "U_Ext": 12815},
    "ts": {f: (NOW, u) for f, u in (("U_Bat", "mV"), ("I_Rasp", "mA"), ("U_USB", "mV"),
                                    ("U_USV", "mV"), ("U_Ext", "mV"))},
    "latest_ts": NOW, "stale_s": 0,
}
WD = {"10c4:ea60:1-1.2": {"label": "CP2102", "key": "10c4:ea60:1-1.2",
                          "type": "UART bridge", "port_path": "1-1.2", "serial": "-",
                          "details": ["/dev/ttyUSB0"], "status": "ONLINE",
                          "since": "2026-11-05 20:00:00 UTC",
                          "last_seen": NOW.strftime("%Y-%m-%d %H:%M:%S UTC")}}
STORAGE = [{"device": "sda", "total_bytes": 4294967296, "used_bytes": 1073741824,
            "avail_bytes": 2147483648, "pct": 100.0 / 3.0,
            "mounts": ["/var/log/piupsmonitor-logs"]}]

out = os.path.join(td, "neighbors.html")
old_out, old_sysfile = mn.HTML_OUT, mn.read_sysfile
mn.HTML_OUT = out
mn.read_sysfile = lambda p: "90061 180122" if p == "/proc/uptime" else old_sysfile(p)
try:
    mn.write_html(rows=[("AABB0011", 20, -160)], now_utc=NOW, nodes_ever=None,
                  usb_infos=[{"port": "/dev/ttyUSB0", "role": "meshcore", "ok": True,
                              "product": "CP2102 USB to UART Bridge Controller",
                              "vid_pid": "10c4:ea60", "usb_path": "1-1.2",
                              "details": "-"}],
                  ntp=NTP, ups=UPS, wd_devices=WD, storages=STORAGE,
                  temps=[{"source": "SoC", "c": 41.9}], temps_ever=EVER)
finally:
    mn.HTML_OUT, mn.read_sysfile = old_out, old_sysfile
with open(out, encoding="utf-8") as f:
    page = f.read()
order = [page.find(h) for h in ("<h3>USB serial devices</h3>", "<h3>USB device watchdog</h3>",
                                "<h3>Storage</h3>", "<h3>Clock &amp; NTP</h3>",
                                "<h3>Temperatures</h3>", "<h3>PiUPS+ / Power</h3>")]
check("t11 all six sections present", all(i != -1 for i in order), str(order))
check("t11 section order: Temperatures after Clock & NTP, before PiUPS+ / Power",
      order == sorted(order) and len(set(order)) == 6, str(order))
i_tp, i_up = page.find("<h3>Temperatures</h3>"), page.find("<h3>PiUPS+ / Power</h3>")
check("t11 live row rendered inside the section",
      'data-sort="41.9">41.9 &deg;C' in page[i_tp:i_up], page[i_tp:i_tp + 300])

print(f"\n{len(PASS)} checks passed")
