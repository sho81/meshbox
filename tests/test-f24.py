#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""F24 regression suite — manual per-row time sync (rename of the F13 emergency sync).

  t1  load_manual_sync_request: valid marker -> dict, file consumed
  t2  stale marker (> SETTIME_MAX_AGE_S) -> None, file still removed
  t3  malformed markers (bad target, bad epoch, broken json) -> None + removed
  t4  no marker at all -> None
  t5  probe_port MeshCore + manual: "time <epoch>" sent, clock re-read verifies,
      automatic lag sync skipped this run
  t6  probe_port MeshCore + manual that misses: manual.ok False, status reports it
  t7  probe_port MeshCom + manual: "--settime yyyy.mm.dd hh:mm:ss" in device-local
      time (UTC + UTC-OFF), --pos re-read verifies
  t8  manual request for a DIFFERENT port leaves this probe untouched (auto-sync
      behaves exactly as before)
  t9  clock_status_text manual branches
  t10 render_clock_section: pinned Pi row first, local device time row last
      without button, per-port buttons carry data-target
  t11 Δ == 0 renders "0s"
  t12 write_html end-to-end: .tbtn CSS + delegated handler present, old single
      button (__synchTime / btn-synctime) gone, local-clock span live in ticker
  t13 service POST /settime with target -> queued marker written atomically
  t14 service rejects a bogus target with 400

Run:  python3 test-f24.py [engine-path] [time-sync-path]
Defaults resolve for both the repo root and the flat staging layout.
"""
import importlib.util
import json
import os
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))

def _find(name):
    for cand in (os.path.join(HERE, name), os.path.join(os.path.dirname(HERE), name)):
        if os.path.isfile(cand):
            return cand
    raise SystemExit(f"{name} not found next to this suite")

ENGINE = sys.argv[1] if len(sys.argv) > 1 else _find("mesh-neighbors.py")
TS_PATH = sys.argv[2] if len(sys.argv) > 2 else _find("mesh-time-sync.py")

def load(path, modname):
    spec = importlib.util.spec_from_file_location(modname, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

mn = load(ENGINE, "mn")
ts = load(TS_PATH, "mts")

mn.names = {}                          # main() normally loads the name map; "-" fallback

UTC = timezone.utc
NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=UTC)
MANUAL_EPOCH = int(datetime(2026, 10, 26, 11, 59, 30, tzinfo=UTC).timestamp())

failures = 0
def check(name, ok):
    global failures
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failures += 1


# --- t1..t4 marker consumption -------------------------------------------------
tmpdir = tempfile.mkdtemp(prefix="f24-")
mn.SETTIME_REQUEST = os.path.join(tmpdir, "settime-request.json")
locks = tempfile.mkdtemp(prefix="f24-locks-")
mn.lock_file_for = lambda port: os.path.join(locks, "meshcore-" + os.path.basename(port) + ".lock")

def put_marker(obj):
    with open(mn.SETTIME_REQUEST, "w", encoding="utf-8") as f:
        json.dump(obj, f)

put_marker({"target": "/dev/ttyUSB0", "epoch": MANUAL_EPOCH,
            "requested": int(NOW.timestamp())})
# age guard uses real wall clock — pretend "requested" is fresh:
put_marker({"target": "/dev/ttyUSB0", "epoch": MANUAL_EPOCH,
            "requested": int(datetime.now(UTC).timestamp())})
got = mn.load_manual_sync_request()
check("t1 valid marker consumed once",
      got == {"target": "/dev/ttyUSB0", "epoch": MANUAL_EPOCH}
      and not os.path.exists(mn.SETTIME_REQUEST))

put_marker({"target": "/dev/ttyUSB0", "epoch": MANUAL_EPOCH,
            "requested": int(datetime.now(UTC).timestamp()) - (mn.SETTIME_MAX_AGE_S + 60)})
check("t2 stale marker dropped (file removed)",
      mn.load_manual_sync_request() is None and not os.path.exists(mn.SETTIME_REQUEST))

for bad in ({"target": "/dev/sda", "epoch": MANUAL_EPOCH, "requested": 0},
            {"target": "/dev/ttyUSB0", "epoch": 123, "requested": 0},
            {"target": "/dev/ttyUSB0", "epoch": MANUAL_EPOCH, "requested": -10 ** 9}):
    put_marker(bad)
    if mn.load_manual_sync_request() is not None or os.path.exists(mn.SETTIME_REQUEST):
        break
else:
    bad = None
with open(mn.SETTIME_REQUEST, "w") as f:
    f.write("{not json")
check("t3 malformed markers dropped + consumed",
      bad is None and mn.load_manual_sync_request() is None
      and not os.path.exists(mn.SETTIME_REQUEST))
check("t4 absent marker -> None", mn.load_manual_sync_request() is None)


# --- fake serial harness ---------------------------------------------------------
class FakeSerial:
    """Queue of per-command replies (list = successive answers, else repeat)."""
    def __init__(self, replies):
        self.replies = {k: list(v) if isinstance(v, list) else [v]
                        for k, v in replies.items()}
        self.sent = []
        self._out = b""

    @property
    def in_waiting(self):
        return len(self._out)

    def read(self, n=-1):
        data = self._out if n in (-1, None) else self._out[:n]
        self._out = self._out[len(data):]
        return data

    def reset_input_buffer(self):
        self._out = b""

    def write(self, bts):
        cmd = bts.decode(errors="replace").strip()
        if not cmd:
            return
        self.sent.append(cmd)
        q = self.replies.get(cmd)
        if q:
            self._out = (q.pop(0) if len(q) > 1 else q[0]).encode()

    def close(self):
        pass


def probe(replies, port="/dev/ttyUSB0", manual=None):
    fs = FakeSerial(replies)
    mod = SimpleNamespace(Serial=lambda *a, **k: fs)
    res = mn.probe_port(port, mod, NOW, manual=manual)
    return fs, res


MC_REPLIES = {
    "neighbors": "All neighbors (1):\r\n  AABB0011:20:-160",
    "get name": "  ->  DK0MAV",
    "ver": "MeshCore v1.4.0 (Build: 4711)",
    "clock": ["  -> 05:00 - 26/10/2026 UTC", "  -> 11:59 - 26/10/2026 UTC"],
}

# --- t5 MeshCore manual applied + verified ----------------------------------------
fs, res = probe(MC_REPLIES, manual={"target": "/dev/ttyUSB0", "epoch": MANUAL_EPOCH})
c = res.get("clock") or {}
check("t5 MeshCore manual: time <epoch> + verify re-read, auto-sync skipped",
      f"time {MANUAL_EPOCH}" in fs.sent
      and f"time {int(NOW.timestamp())}" not in fs.sent          # no auto-sync this run
      and c.get("manual", {}).get("ok") is True
      and c.get("manual", {}).get("verify_delta_s") == -30
      and c.get("synced") is False)

# --- t6 MeshCore manual misses -----------------------------------------------------
fs, res = probe({**MC_REPLIES,
                 "clock": ["  -> 05:00 - 26/10/2026 UTC", "  -> 05:00 - 26/10/2026 UTC"]},
                manual={"target": "/dev/ttyUSB0", "epoch": MANUAL_EPOCH})
c = res["clock"]
check("t6 MeshCore manual miss: not verified, status says so",
      c["manual"]["ok"] is False and abs(c["manual"]["verify_delta_s"]) > 90
      and "still" in mn.clock_status_text(c, "meshcore"))

# --- t7 MeshCom manual in device-local time ----------------------------------------
MESHCOM_REPLIES = {
    "neighbors": "ERROR: command not found",
    "--info": ("MeshCom 1.2.0 (build: abcdef)\r\nCall: <DH1234>\r\n"
               "...NAME: TestUnit\r\n...TIME 12345 ms\r\nUTC-OFF 2"),
    "--pos": ["...DATE: 2026.10.26 07:00:00", "...DATE: 2026.10.26 13:59:30"],
}
fs, res = probe(MESHCOM_REPLIES, manual={"target": "/dev/ttyUSB0", "epoch": MANUAL_EPOCH})
c = res.get("clock") or {}
check("t7 MeshCom manual: --settime local (UTC+2), --pos re-read verifies",
      "--settime 2026.10.26 13:59:30" in fs.sent
      and c.get("manual", {}).get("ok") is True
      and c.get("manual", {}).get("verify_delta_s") == 0
      and c.get("device") == "2026-10-26 11:59:30 UTC"
      and c.get("lag_s") == 30)

# --- t8 request aimed at another port: probe unchanged -----------------------------
fs, res = probe(MC_REPLIES, port="/dev/ttyUSB0",
                manual={"target": "/dev/ttyUSB1", "epoch": MANUAL_EPOCH})
c = res["clock"]
check("t8 foreign target: auto-sync exactly as before, no manual",
      f"time {int(NOW.timestamp())}" in fs.sent
      and f"time {MANUAL_EPOCH}" not in fs.sent
      and c.get("synced") is True and "manual" not in c)

# --- t9 status text branches --------------------------------------------------------
check("t9 clock_status_text manual branches",
      "verified" in mn.clock_status_text(
          {"lag_s": 0, "synced": False, "manual": {"verify_delta_s": -30, "ok": True}},
          "meshcore")
      and "no verification reply" in mn.clock_status_text(
          {"lag_s": 0, "synced": False, "manual": {"verify_delta_s": None, "ok": False}},
          "meshcom"))

# --- t10/t11 rendering ---------------------------------------------------------------
infos = [
    {"port": "/dev/ttyUSB0", "role": "meshcore", "ok": True, "details": "-",
     "product": "MeshCore bridge", "vid_pid": "1a86:7523", "usb_path": "1-1.2",
     "clock": {"device": "2026-10-26 12:00 UTC", "lag_s": 0, "synced": False}},
    {"port": "/dev/ttyUSB1", "role": "meshcom", "ok": True, "details": "-",
     "product": "CP210x", "vid_pid": "10ac:d61c", "usb_path": "1-1.3",
     "clock": {"device": "2026-10-26 12:10:00 UTC", "lag_s": -600, "synced": False,
               "manual": {"verify_delta_s": 0, "ok": True}}},
]
ntp = {"tz": "CET", "ntp": "active", "synced": "yes"}
sec = mn.render_clock_section(infos, ntp, NOW)
i_pi = sec.find('data-pin="top"')
i_usb0 = sec.find("<td>/dev/ttyUSB0</td>")
i_usb1 = sec.find("<td>/dev/ttyUSB1</td>")
i_local = sec.find("local device time (this browser)")
check("t10 pinned Pi row first, device rows, local row last",
      0 <= i_pi < i_usb0 < i_usb1 < i_local)
local_row = sec[sec.find('<tr data-order="99"'):sec.find("</tr>", sec.find('<tr data-order="99"'))]
check("t10b local row has live span, no button",
      'id="local-clock"' in local_row and "<button" not in local_row)
check("t10c per-device buttons carry data-target",
      'data-target="/dev/ttyUSB0"' in sec and 'data-target="/dev/ttyUSB1"' in sec
      and 'data-target=""' in sec)                                 # Pi row = system
clock_rows = re.findall(r'<tr[^>]*data-order="[^"]*"[^>]*>(.*?)</tr>', sec, re.S)
check("t10d dedicated 'Manual sync' column: 5 cells per row, button in the last",
      "<th>Manual sync</th>" in sec and len(clock_rows) == 4
      and all(r.count("<td") == 5 for r in clock_rows)
      and all(('<button' in r.rsplit("<td", 1)[-1]) == (i < 3)
              for i, r in enumerate(clock_rows)))                  # local row has none
check("t11 delta 0 renders '0s'", '<td class="num" data-sort="0">0s</td>' in sec)

# --- t12 end-to-end page -------------------------------------------------------------
out = os.path.join(tmpdir, "neighbors.html")
old_out, old_sysfile = mn.HTML_OUT, mn.read_sysfile
mn.HTML_OUT = out
try:
    mn.write_html(rows=[("AABB0011", 20, -160)], now_utc=NOW, nodes_ever=None,
                  usb_infos=infos, src_port="/dev/ttyUSB0", ntp=ntp)
    page = open(out, encoding="utf-8").read()
finally:
    mn.HTML_OUT, mn.read_sysfile = old_out, old_sysfile
check("t12 page: .tbtn CSS + handler + local-clock live, old button gone",
      ".tbtn {" in page and "tbl-clock" in page and 'id="local-clock"' in page
      and "getElementById('local-clock')" in page
      and "__synchTime" not in page and "btn-synctime" not in page
      and "data-pin" in page)

# --- t13/t14 service target path -------------------------------------------------------
ts.REQUEST_FILE = os.path.join(tmpdir, "sub", "settime-request.json")
srv = ts.ThreadingHTTPServer(("127.0.0.1", 0), ts.Handler)
port_n = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port_n}"

def req(path, data=None):
    r = urllib.request.Request(base + path, data=data)
    if data:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

epoch_now = int(datetime.now(UTC).timestamp())
st, body = req("/settime", json.dumps({"epoch": epoch_now,
                                       "target": "/dev/ttyUSB0"}).encode())
marker = json.load(open(ts.REQUEST_FILE, encoding="utf-8"))
check("t13 serial target queued atomically (no clock_settime touched)",
      st == 200 and body.get("queued") is True and body.get("target") == "/dev/ttyUSB0"
      and marker["target"] == "/dev/ttyUSB0" and marker["epoch"] == epoch_now
      and "requested" in marker and not os.path.exists(ts.REQUEST_FILE + ".tmp"))

st2, body2 = req("/settime", json.dumps({"epoch": epoch_now,
                                         "target": "/dev/sda"}).encode())
check("t14 bogus target -> 400", st2 == 400 and not body2["ok"] and "ttyUSB" in body2["error"])
srv.shutdown()

print(f"f24: {failures} failures")
sys.exit(1 if failures else 0)
