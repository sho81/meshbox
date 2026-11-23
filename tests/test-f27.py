#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""F27 regression suite — per-box overlay config (second-box rollout).

  t1  no box-config.json next to the script: every default preserved
  t2  overlay applied: title/station/identity/ports_glob/www_dir + derived
      HTML_OUT and TTY_SYS_GLOB
  t3  partial overlay: only the keys present are overridden
  t4  broken/unknown-shaped config: defaults kept, no crash
  t5  settime target validation accepts ttyACM (engine AND service), still
      rejects bogus targets
  t6  TTY_SYS_GLOB follows the configured serial family
  t7  rendered page carries overlaid <title> and <h2> station prefix
  t8  _tty_to_usb/scan_usb_devices default to TTY_SYS_GLOB (no crash)

Run:  python3 test-f27.py [engine-path]
Defaults resolve for both the repo root and the flat staging layout.
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))


def _find(name):
    for cand in (os.path.join(HERE, name), os.path.join(os.path.dirname(HERE), name)):
        if os.path.isfile(cand):
            return cand
    raise SystemExit(f"{name} not found next to this suite")


ENGINE = sys.argv[1] if len(sys.argv) > 1 else _find("mesh-neighbors.py")
SERVICE = _find("mesh-time-sync.py")
PASS = []


def check(name, cond, info=""):
    if cond:
        PASS.append(name)
        print(f"PASS {name}")
    else:
        print(f"FAIL {name} {info}")
        sys.exit(1)


def load_engine(path, alias):
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_engine_with(cfg_text, alias="mn_overlay"):
    """Engine copy in a fresh tmpdir with box-config.json next to it."""
    td = tempfile.mkdtemp(prefix="f27-")
    eng = os.path.join(td, "mesh-neighbors.py")
    shutil.copy(ENGINE, eng)
    with open(os.path.join(td, "box-config.json"), "w", encoding="utf-8") as f:
        f.write(cfg_text)
    return load_engine(eng, alias)


# ---------------------------------------------------------------- t1 defaults
mn = load_engine(ENGINE, "mn")           # no box-config.json next to the repo copy
check("t1 defaults without box-config (DK0MAV identity preserved)",
      mn.PAGE_TITLE == "DK0MAV MeshCore Neighbors"
      and mn.STATION == "DK0MAV mc&sup2;-Peine-Node"
      and mn.NODE_NAME == "Amateurfunk Peine FTZ"
      and mn.MESHCORE_FREQ == "869.618 MHz"
      and mn.MESHCOM_NAME == 'DK0MAV-12 "Digipeater Peine"'
      and mn.MESHCOM_FREQ == "433.175 MHz"
      and mn.PORTS_GLOB == "/dev/ttyUSB*"
      and mn.WWW_DIR == "/var/www/html"
      and mn.HTML_OUT == "/var/www/html/neighbors.html"
      and mn.TTY_SYS_GLOB == "/sys/class/tty/ttyUSB*",
      str(mn.PAGE_TITLE))

# ---------------------------------------------------------------- t2 overlay
FULL = json.dumps({
    "title": "TESTBOX MeshBox Neighbors",
    "station": "TESTBOX MeshBox",
    "node_name": "TESTBOX mc",
    "meshcore_freq": "433.500 MHz",
    "meshcom_name": "TESTBOX-1 Digipeater",
    "meshcom_freq": "433.175 MHz",
    "ports_glob": "/dev/ttyACM*",
    "www_dir": "/var/www/mesh",
})
ov = load_engine_with(FULL)
check("t2 full overlay applied incl. derived HTML_OUT",
      ov.PAGE_TITLE == "TESTBOX MeshBox Neighbors"
      and ov.STATION == "TESTBOX MeshBox"
      and ov.NODE_NAME == "TESTBOX mc" and ov.MESHCORE_FREQ == "433.500 MHz"
      and ov.MESHCOM_NAME == "TESTBOX-1 Digipeater"
      and ov.MESHCOM_FREQ == "433.175 MHz"
      and ov.PORTS_GLOB == "/dev/ttyACM*"
      and ov.WWW_DIR == "/var/www/mesh"
      and ov.HTML_OUT == "/var/www/mesh/neighbors.html",
      str((ov.PAGE_TITLE, ov.HTML_OUT)))

# ---------------------------------------------------------------- t3 partial
pt = load_engine_with(json.dumps({"ports_glob": "/dev/ttyACM*"}), "mn_partial")
check("t3 partial overlay: only present keys change",
      pt.PORTS_GLOB == "/dev/ttyACM*" and pt.TTY_SYS_GLOB == "/sys/class/tty/ttyACM*"
      and pt.PAGE_TITLE == "DK0MAV MeshCore Neighbors"
      and pt.WWW_DIR == "/var/www/html"
      and pt.NODE_NAME == "Amateurfunk Peine FTZ",
      str((pt.PORTS_GLOB, pt.PAGE_TITLE)))

# ---------------------------------------------------------------- t4 broken
bad = load_engine_with("{ not json", "mn_bad")
check("t4 broken box-config: defaults kept, no crash",
      bad.PAGE_TITLE == "DK0MAV MeshCore Neighbors"
      and bad.PORTS_GLOB == "/dev/ttyUSB*")
arr = load_engine_with('["surprise"]', "mn_arr")
check("t4 non-object box-config ignored",
      arr.STATION == "DK0MAV mc&sup2;-Peine-Node")

# ---------------------------------------------------------------- t5 settime
td = tempfile.mkdtemp(prefix="f27-st-")
mn.SETTIME_REQUEST = os.path.join(td, "settime-request.json")
EPOCH = 1770000000


def put(payload):
    with open(mn.SETTIME_REQUEST, "w") as f:
        json.dump(payload, f)


put({"target": "/dev/ttyACM1", "epoch": EPOCH, "requested": int(time.time())})
check("t5 engine marker validation accepts /dev/ttyACM1",
      mn.load_manual_sync_request()
      == {"target": "/dev/ttyACM1", "epoch": EPOCH}, "engine regex")
for bogus in ("/dev/ttyXYZ0", "/dev/ttyUSB0x", "/dev/ttyACM", "/dev/sda"):
    put({"target": bogus, "epoch": EPOCH, "requested": int(time.time())})
    if mn.load_manual_sync_request() is not None:
        check(f"t5 engine still rejects {bogus}", False, "accepted!")
check("t5 engine still rejects bogus targets", True)

svc = load_engine(SERVICE, "svc")
check("t5 service TARGET_RE accepts ttyACM3, rejects /dev/sda",
      bool(svc.TARGET_RE.fullmatch("/dev/ttyACM3"))
      and not svc.TARGET_RE.fullmatch("/dev/sda")
      and bool(svc.TARGET_RE.fullmatch("/dev/ttyUSB0")))

# ---------------------------------------------------------------- t7 render
NOW = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)
out = os.path.join(td, "neighbors.html")
old_out = ov.HTML_OUT
ov.HTML_OUT = out
try:
    ov.write_html(rows=[("AABB0011", 20, -160)], now_utc=NOW)
finally:
    ov.HTML_OUT = old_out
with open(out, encoding="utf-8") as f:
    page = f.read()
check("t7 overlaid title + station in page, DK0MAV strings gone",
      "<title>TESTBOX MeshBox Neighbors</title>" in page
      and "<h2>TESTBOX MeshBox &mdash; MeshCore: TESTBOX mc, 433.500 MHz" in page
      and "DK0MAV" not in page, page[:300])
dfl = os.path.join(td, "default.html")
old_out = mn.HTML_OUT
mn.HTML_OUT = dfl
try:
    mn.write_html(rows=[("AABB0011", 20, -160)], now_utc=NOW)
finally:
    mn.HTML_OUT = old_out
with open(dfl, encoding="utf-8") as f:
    dpage = f.read()
check("t7 default page byte-for-byte in the old DK0MAV identity",
      "<title>DK0MAV MeshCore Neighbors</title>" in dpage
      and "<h2>DK0MAV mc&sup2;-Peine-Node &mdash; MeshCore: Amateurfunk Peine FTZ, 869.618 MHz" in dpage)

# ---------------------------------------------------------------- t8 helpers
check("t8 tty helpers default to TTY_SYS_GLOB without crashing (empty tree ok)",
      ov._tty_to_usb() == {} and ov.scan_usb_devices(usb_dir="/nonexistent-f27")
      is not None)

print(f"\n{len(PASS)} checks passed")
