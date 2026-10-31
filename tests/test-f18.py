#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""F18 checks — "Started <boot time> (... ago)" uptime line above the Updated line.

Run:  python3 test-f18.py [engine-path]     (default: ./mesh-neighbors.py)

Covers:
  t1  boot_time_utc from a synthetic /proc/uptime (exact value + ISO string)
  t2  boot_time_utc fallback to /proc/stat btime when /proc/uptime is unreadable
  t3  boot_time_utc -> None when neither source is readable
  t4  write_html end-to-end with fixed clock: started meta tag, line order
      (Started above Updated), both spans present, updated meta unchanged
  t5  all-sections regression render (F19 section order — Storage between watchdog
      and clock, superseding F14 — + F18 lines coexist)
  t6  node --check of the extracted ticker script
  t7  JS harness: rendered strings for a >24 h uptime (days tier) + Updated line
  t8  JS harness: short uptime (minutes tier) and missing-started-meta guard path
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "mesh-neighbors.py")

spec = importlib.util.spec_from_file_location("mn", ENGINE)
mn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mn)          # module level is constants + defs only (no I/O)
mn.names = {}                        # main() normally loads mesh-node-names.json; "-" fallback in tests

NOW = datetime(2026, 10, 26, 11, 45, 1, tzinfo=timezone.utc)   # fixed "page generated" time
NOW_ISO = NOW.isoformat(timespec="seconds")                    # 2026-10-26T11:45:01+00:00

PASS = []


def check(name, cond, detail=""):
    if not cond:
        print(f"FAIL {name} {detail}")
        sys.exit(1)
    PASS.append(name)
    print(f"ok   {name}")


# ---------------------------------------------------------------- t1-t3 helper
UP_90061 = 90061                                   # 25 h 1 m 1 s of synthetic uptime
BOOT_T1 = NOW - timedelta(seconds=UP_90061)        # -> 2026-10-25T10:44:00+00:00

with tempfile.TemporaryDirectory() as td:
    up_file = os.path.join(td, "uptime")
    with open(up_file, "w") as f:
        f.write(f"{UP_90061} 180122\n")
    got = mn.boot_time_utc(NOW, uptime_file=up_file)
    check("t1 boot from /proc/uptime", got == BOOT_T1, f"got {got!r}")
    check("t1 iso string", got.isoformat(timespec="seconds") == "2026-10-25T10:44:00+00:00",
          got.isoformat(timespec="seconds"))

    stat_file = os.path.join(td, "stat")
    btime_epoch = int((NOW - timedelta(hours=1)).timestamp())
    with open(stat_file, "w") as f:
        f.write(f"cpu  100 0 50 9000 0 0 0 0 0 0\nbtime {btime_epoch}\nintr 42\n")
    got = mn.boot_time_utc(NOW, uptime_file=os.path.join(td, "missing"), stat_file=stat_file)
    check("t2 btime fallback", got == NOW - timedelta(hours=1), f"got {got!r}")

    got = mn.boot_time_utc(NOW, uptime_file=os.path.join(td, "nope"), stat_file=os.path.join(td, "nada"))
    check("t3 both unreadable -> None", got is None, f"got {got!r}")


# ---------------------------------------------------------------- t4-t8 helpers
TICKER_RE = re.compile(r"<script>(.*?)</script>", re.S)


def extract_ticker(page_html):
    # The page carries other <script> blocks too (F13 __synchTime inside the Clock & NTP
    # section, SORT_JS at the end); pick the ticker by its content marker.
    for m in TICKER_RE.finditer(page_html):
        if "meta[name=updated]" in m.group(1) and "setInterval" in m.group(1):
            return m.group(1)
    raise AssertionError("ticker script not found")


# ---------------------------------------------------------------- t4/t5 render
ORIG_READ_SYSFILE = mn.read_sysfile


def fake_read_sysfile(uptime_text):
    def patched(path):
        if path == "/proc/uptime":
            return uptime_text
        return ORIG_READ_SYSFILE(path)

    return patched


USB_INFOS = [
    {"port": "/dev/ttyUSB0", "role": "meshcore",
     "product": "CP2102 USB to UART Bridge Controller", "usb_path": "1-1.2",
     "details": "Amateurfunk Peine FTZ · v1.17.1-d929643"},
    {"port": "/dev/ttyUSB1", "role": "meshcom",
     "product": "CP2102 USB to UART Bridge Controller", "usb_path": "1-1.1.3",
     "details": "MeshCom 4.40a (build: Oct  2 2026)"},
]

WD_DEVICES = {
    "10c4:ea60:0001:1-1.2": {
        "status": "ONLINE", "label": "CP2102 USB to UART Bridge Controller",
        "type": "UART bridge", "details": ["ttyUSB0"],
        "since": "2026-10-11 09:59:38 UTC", "last_seen": NOW.strftime("%Y-%m-%d %H:%M:%S UTC"),
    },
}

NTP = {"tz": "Europe/Berlin (CET, +0100)", "ntp": "active", "synced": "yes"}

UPS = {
    "status": {"primary": 1, "secondary": 0, "low": 0, "charging": 0, "full": 0, "button": 0},
    "volts": {"U_Bat": 4154, "I_Rasp": 802, "U_USB": 5064, "U_USV": 439, "U_Ext": 12815},
    "ts": {f: (NOW, u) for f, u in (("U_Bat", "mV"), ("I_Rasp", "mA"), ("U_USB", "mV"),
                                    ("U_USV", "mV"), ("U_Ext", "mV"))},
    "latest_ts": NOW, "stale_s": 0,
}

NODES_EVER = {"73C1F5D1": {"last": "2026-10-26 09:26:18 UTC", "best_db": 14.0,
                           "worst_db": 11.5, "sightings": 23028}}
ROWS = [("73C1F5D1", 0, 12)]


def render(uptime_text, **kw):
    """write_html with fixed clock + synthetic /proc/uptime; returns (page, out_path)."""
    out = os.path.join(tempfile.mkdtemp(prefix="f18-"), "neighbors.html")
    mn.read_sysfile = fake_read_sysfile(uptime_text)
    old_out = mn.HTML_OUT
    mn.HTML_OUT = out
    try:
        mn.write_html(rows=kw.pop("rows", ROWS), now_utc=NOW, **kw)
        with open(out, encoding="utf-8") as f:
            return f.read(), out
    finally:
        mn.read_sysfile = ORIG_READ_SYSFILE
        mn.HTML_OUT = old_out


page, _ = render(f"{UP_90061} 180122", nodes_ever=NODES_EVER)

check("t4 started meta tag", f'<meta name="started" content="{BOOT_T1.isoformat(timespec="seconds")}">' in page)
check("t4 updated meta unchanged", f'<meta name="updated" content="{NOW_ISO}">' in page)
i_started = page.find('<div class="sub">Started <span id="started"></span></div>')
i_updated = page.find('<div class="sub">Updated <span id="upd"></span></div>')
check("t4 Started line present", i_started != -1)
check("t4 Updated line present", i_updated != -1)
check("t4 Started above Updated", 0 <= i_started < i_updated, f"{i_started} vs {i_updated}")
check("t4 exactly two sub lines", page.count('<div class="sub">') == 2)

# t5: all five sections render in F19 order (F14 superseded by the Storage insertion)
STORAGES = [
    {"device": "sda", "total_bytes": 4294967296, "used_bytes": 1073741824,
     "avail_bytes": 2147483648, "pct": 100.0 / 3.0, "mounts": ["/var/log/piupsmonitor-logs"]},
    {"device": "sdb", "total_bytes": 15032385536, "used_bytes": None, "avail_bytes": None,
     "pct": None, "mounts": []},
]
page5, _ = render(f"{UP_90061} 180122", nodes_ever=NODES_EVER, usb_infos=USB_INFOS,
                  ntp=NTP, ups=UPS, wd_devices=WD_DEVICES, storages=STORAGES)
order = [page5.find(h) for h in ("<h3>USB serial devices</h3>", "<h3>USB device watchdog</h3>",
                                 "<h3>Storage</h3>", "<h3>Clock &amp; NTP</h3>",
                                 "<h3>PiUPS+ / Power</h3>")]
check("t5 all sections present", all(i != -1 for i in order), str(order))
check("t5 F19 section order kept (Storage between watchdog and clock)",
      order == sorted(order) and len(set(order)) == 5, str(order))
i_s = page5.find('<div class="sub">Started')
i_u = page5.find('<div class="sub">Updated')
check("t5 Started above Updated (all sections)", 0 <= i_s < i_u)
# The full page also carries the F13 __synchTime script and SORT_JS — extraction must
# still find the ticker IIFE (regression guard: a naive "first <script>" pick fails here).
ticker_full = extract_ticker(page5)
check("t5 ticker extracted from full page", "meta[name=started]" in ticker_full
      and "__synchTime" not in ticker_full and "sortarrow" not in ticker_full)

# ---------------------------------------------------------------- t6-t8 JS
HARNESS = r"""
const fs = require("fs");
const [,, scriptFile, nowMs, updatedIso, startedIso] = process.argv;
const RealDate = Date;
global.Date = class extends RealDate { static now() { return parseInt(nowMs); } };
const els = {};
global.document = {
    querySelector(sel) {
        if (sel === "meta[name=updated]") return { content: updatedIso };
        if (sel === "meta[name=started]" && startedIso !== "-") return { content: startedIso };
        return null;
    },
    getElementById(id) { return els[id] || (els[id] = {}); }
};
global.setInterval = () => 0;
eval(fs.readFileSync(scriptFile, "utf8"));
console.log(JSON.stringify({
    upd: els.upd ? els.upd.textContent : null,
    started: els.started ? els.started.textContent : null
}));
"""


def run_js(ticker_src, now_ms, updated_iso, started_iso):
    with tempfile.TemporaryDirectory() as td:
        script = os.path.join(td, "ticker.js")
        harness = os.path.join(td, "harness.js")
        with open(script, "w") as f:
            f.write(ticker_src)
        with open(harness, "w") as f:
            f.write(HARNESS)
        out = subprocess.run(["node", harness, script, str(now_ms), updated_iso, started_iso],
                             capture_output=True, text=True, check=True).stdout.strip()
    return json.loads(out)


ticker_src = extract_ticker(page)

with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
    f.write(ticker_src)
    ticker_file = f.name
r = subprocess.run(["node", "--check", ticker_file], capture_output=True, text=True)
check("t6 node --check of extracted ticker script", r.returncode == 0, r.stderr.strip())

now_ms = int(NOW.timestamp()) * 1000 + 3000          # viewer's clock: 3 s after page stamp

# t7: >24 h uptime -> days tier; Updated line unchanged in format
UP_A = 1216980                                       # 14 d 2 h 3 m of synthetic uptime
boot_a = NOW - timedelta(seconds=UP_A)               # -> 2026-10-12T09:42:01+00:00
res = run_js(ticker_src, now_ms, NOW_ISO, boot_a.isoformat(timespec="seconds"))
check("t7 Updated line", res["upd"] == "2026-10-26 11:45:01 UTC (3 s ago)", repr(res))
check("t7 Started days tier",
      res["started"] == f"{boot_a.strftime('%Y-%m-%d %H:%M:%S')} UTC (14 d 2 h ago)", repr(res))

# t8a: short uptime -> minutes tier
UP_B = 307                                           # 5 m 7 s
boot_b = NOW - timedelta(seconds=UP_B)               # -> 2026-10-26T11:39:54+00:00
res = run_js(ticker_src, now_ms, NOW_ISO, boot_b.isoformat(timespec="seconds"))
check("t8 short uptime minutes tier",
      res["started"] == f"{boot_b.strftime('%Y-%m-%d %H:%M:%S')} UTC (5 m 10 s ago)", repr(res))

# t8b: missing started meta -> guard path, Updated still renders
res = run_js(ticker_src, now_ms, NOW_ISO, "-")
check("t8 no started meta -> span untouched", res["started"] is None and
      res["upd"] == "2026-10-26 11:45:01 UTC (3 s ago)", repr(res))

print(f"\n{len(PASS)} checks passed")
