#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Service regression suite — the two companion daemons (F13, F16).

  t1  F13 check_epoch: type/unit/plausibility validation table
  t2  F13 HTTP GET / health endpoint on a loopback port
  t3  F13 POST /settime: valid epoch -> 200 with applied_epoch/delta_s,
          with clock_settime mocked (NEVER touches the real system clock)
  t4  F13 POST /settime: junk body -> 400, implausible epoch -> 400,
          unknown path -> 404
  t5  F16 relay handle_line: status bits first-sighting + change-delta only
  t6  F16 relay handle_line: readings only on threshold excursions (>= 10)
  t7  F16 relay tick(): snapshot of latest readings, no duplicate of an
          already-pending excursion line
  t8  F16 relay flush(): chronological order, file append, queue cleared;
          flush failure keeps pending lines
  t9  F16 relay trim_if_needed(): over-cap live log keeps NEWEST bytes
  t10 F31 POST /keymap-update: first click spawns the helper (stub), re-click
          while running -> 409, after exit -> 429 cooldown + SKIPPED status
          file (no network: stub script instead of the real helper)

Run:  python3 test-services.py [time-sync-path] [relay-path]
Defaults resolve for both the repo root and the flat staging layout.
"""
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

def _find(name):
    for cand in (os.path.join(HERE, name), os.path.join(os.path.dirname(HERE), name)):
        if os.path.isfile(cand):
            return cand
    raise SystemExit(f"{name} not found next to this suite")

TS_PATH = sys.argv[1] if len(sys.argv) > 1 else _find("mesh-time-sync.py")
RL_PATH = sys.argv[2] if len(sys.argv) > 2 else _find("piups-log-relay.py")

def load(path, modname):
    spec = importlib.util.spec_from_file_location(modname, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

ts = load(TS_PATH, "mts")
rl = load(RL_PATH, "plr")

failures = 0
def check(name, ok):
    global failures
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failures += 1

# --- t1 check_epoch -----------------------------------------------------------
now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
now_s = int(now.timestamp())
cases = [
    (now_s, True),                    # right now: fine
    (now_s - 60, True),               # a minute adrift: fine
    (True, False),                    # bool is not an int here
    ("1762000000", False),            # wrong type
    (1762000000000, False),           # milliseconds -> out of absolute range
    (10 ** 7, False),                 # pre-1973
    (now_s + 6 * 366 * 86400, False),  # more than 5 years ahead
]
check("t1 check_epoch validation table",
      all(ts.check_epoch(v, now)[0] is want for v, want in cases))

# --- t2..t4 HTTP service with mocked clock_settime ------------------------------
calls = []
class _FakeStructure:                    # base for apply_clock's inner Timespec
    def __init__(self, *a): calls.append(a)
class _FakeLib:
    def clock_settime(self, clk, tsref): return 0
class _FakeCTypes:
    Structure = _FakeStructure
    c_long = int
    util = type("u", (), {"find_library": staticmethod(lambda n: "libc")})()
    @staticmethod
    def CDLL(*a, **k): return _FakeLib()
    @staticmethod
    def get_errno(): return 1
    @staticmethod
    def byref(x): return x
# apply_clock does `import ctypes` + `import ctypes.util` -> binds via sys.modules,
# so swap both (a plain non-package stand-in would break the dotted import).
_real_ctypes = sys.modules.get("ctypes")
_real_ctypes_util = sys.modules.get("ctypes.util")
sys.modules["ctypes"] = _FakeCTypes
sys.modules["ctypes.util"] = _FakeCTypes.util

srv = ts.ThreadingHTTPServer(("127.0.0.1", 0), ts.Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"

def req(path, data=None):
    r = urllib.request.Request(base + path, data=data)
    if data:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

st, body = req("/")
check("t2 GET / health", st == 200 and body["ok"] and "now_utc" in body)

_exp = int(datetime.now(timezone.utc).timestamp()) - 60
st, body = req("/settime", json.dumps({"epoch": _exp}).encode())
check("t3 POST /settime accepted (mocked settime)",
      st == 200 and body["ok"] and body["applied_epoch"] == _exp
      and abs(body["delta_s"] + 60) <= 2 and len(calls) == 1)

st1, b1 = req("/settime", b"not json")
st2, b2 = req("/settime", json.dumps({"epoch": 999}).encode())
st3, b3 = req("/nope", b"{}")
check("t4 POST /settime junk -> 400, implausible -> 400, unknown path -> 404",
      st1 == 400 and st2 == 400 and st3 == 404
      and not b2["ok"] and "range" in b2["error"])

# --- t10 F31 POST /keymap-update: spawn, single-flight, cooldown --------------
KD = tempfile.mkdtemp(prefix="f31-svc-")
stub = os.path.join(KD, "keymap-stub.py")
with open(stub, "w") as f:
    f.write("#!/usr/bin/python3\n"
            "import argparse, json, os, time\n"
            "p = argparse.ArgumentParser()\n"
            "p.add_argument('--state-dir', required=True)\n"
            "p.add_argument('--status-only')\n"
            "p.add_argument('--detail', default='')\n"
            "a = p.parse_args()\n"
            "if a.status_only:\n"
            "    json.dump({'last_run': time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime()),\n"
            "               'result': a.status_only, 'detail': a.detail},\n"
            "              open(os.path.join(a.state_dir, 'keymap-status.json'), 'w'))\n"
            "else:\n"
            "    time.sleep(2)   # stay 'running' long enough for the single-flight check\n"
            "    open(os.path.join(a.state_dir, 'stub-ran'), 'w').write('x')\n")
ts.STATE_DIR = KD
ts.KEYMAP_SCRIPT = stub
ts.KEYMAP_STAMP = os.path.join(KD, ".keymap-last")
st, body = req("/keymap-update", b"{}")
check("t10a F31 keymap first click starts run",
      st == 200 and body.get("ok") and body.get("started"))
st2, body2 = req("/keymap-update", b"{}")        # stub still asleep -> single-flight
check("t10b F31 re-click while running -> 409",
      st2 == 409 and body2.get("skipped")
      and body2.get("reason") == "update already running")
ts.KEYMAP_RUN["proc"].wait(timeout=15)           # stub done -> cooldown now guards
st3, body3 = req("/keymap-update", b"{}")
check("t10c F31 click inside cooldown -> 429 skipped",
      st3 == 429 and body3.get("skipped") and "min" in body3.get("reason", ""))
check("t10d F31 run spawned the helper",
      os.path.isfile(os.path.join(KD, "stub-ran")))
try:
    with open(os.path.join(KD, "keymap-status.json")) as f:
        sj = json.load(f)
except OSError:
    sj = {}
check("t10e F31 refusal logged to keymap-status.json (SKIPPED + reason)",
      sj.get("result") == "SKIPPED" and "ago" in sj.get("detail", ""))
srv.shutdown()
for name, real in (("ctypes", _real_ctypes), ("ctypes.util", _real_ctypes_util)):
    if real is not None:
        sys.modules[name] = real
    else:
        sys.modules.pop(name, None)

# --- t5/t6 relay handle_line ----------------------------------------------------
L = lambda ts_s, field, val, unit="": f"{ts_s} [DEBUG] {field}: {val}{(' ' + unit) if unit else ''}"
r = rl.Relay(out_log=os.devnull)
r.handle_line(L("2026-11-02 12:00:00", "Primary Power Supply", 0))
r.handle_line(L("2026-11-02 12:00:01", "Primary Power Supply", 0))
r.handle_line(L("2026-11-02 12:00:02", "Primary Power Supply", 1))
first3 = list(r.pending)
check("t5 relay status: first sighting + change only",
      first3 == [L("2026-11-02 12:00:00", "Primary Power Supply", 0),
                 L("2026-11-02 12:00:02", "Primary Power Supply", 1)])

r2 = rl.Relay(out_log=os.devnull)
r2.handle_line(L("2026-11-02 12:00:00", "U_Bat", 4100, "mV"))   # first sighting
r2.handle_line(L("2026-11-02 12:00:01", "U_Bat", 4105, "mV"))   # delta 5  -> silent
r2.handle_line(L("2026-11-02 12:00:02", "U_Bat", 4090, "mV"))   # delta 15 -> excursion
check("t6 relay readings: threshold-gated excursions",
      r2.pending == [L("2026-11-02 12:00:00", "U_Bat", 4100, "mV"),
                     L("2026-11-02 12:00:02", "U_Bat", 4090, "mV")]
      and r2.latest_reading["U_Bat"][1] == 4090)

# --- t7 relay tick ----------------------------------------------------------------
r2.tick()
check("t7 relay tick: snapshot latest, excursion already pending not duplicated",
      r2.pending[-1] == L("2026-11-02 12:00:02", "U_Bat", 4090, "mV")
      and len(r2.pending) == 2)
r2.handle_line(L("2026-11-02 12:00:09", "U_Bat", 4092, "mV"))   # quiet drift, latest updated
r2.tick()
check("t7b relay tick: quiet drift still snapshotted",
      r2.pending[-1] == L("2026-11-02 12:00:09", "U_Bat", 4092, "mV"))

# --- t8 relay flush ----------------------------------------------------------------
r3 = rl.Relay(out_log=None)
with tempfile.TemporaryDirectory() as d:
    r3.out_log = os.path.join(d, "out.log")
    r3.handle_line(L("2026-11-02 12:00:05", "U_Bat", 1, "mV"))
    r3.handle_line(L("2026-11-02 12:00:01", "U_Ext", 2, "mV"))   # out-of-order arrival
    n = r3.flush()
    written = open(r3.out_log).read().splitlines()
    ok = n == 2 and written == [L("2026-11-02 12:00:01", "U_Ext", 2, "mV"),
                                L("2026-11-02 12:00:05", "U_Bat", 1, "mV")] and r3.pending == []
    r3.out_log = os.path.join(d, "nope", "missing", "out.log")   # unwritable path
    r3.handle_line(L("2026-11-02 12:00:06", "U_Bat", 50, "mV"))  # big excursion -> queued
    n2 = r3.flush()
    ok = ok and n2 == 0 and len(r3.pending) == 1
check("t8 relay flush: chronological + cleared; failure keeps pending", ok)

# --- t9 relay trim_if_needed --------------------------------------------------------
r4 = rl.Relay(max_bytes=200, keep_bytes=100)
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "live.log")
    filler = "".join(f"line{i:04d} padding\n" for i in range(40))   # > 200 bytes
    open(path, "w").write(filler)
    with open(path, "r+b") as f:
        r4.trim_if_needed(f)
    kept = open(path).read()
    check("t9 relay trim: keeps newest bytes within cap",
          len(kept) <= 100 and kept == filler[-len(kept):] and len(kept) > 0)

print(f"services: {failures} failures")
sys.exit(1 if failures else 0)
