#!/usr/bin/python3
# SPDX-License-Identifier: MIT
# SPDX-License-Identifier: MIT
"""mesh-time-sync — manual time sync for raspi-mesh (F13, F24).

A tiny HTTP service bound to loopback only. nginx proxies /settime to it, so
the dashboard's per-row "set from your device" buttons can set clocks from
the visitor's browser clock when NTP is unavailable.

Endpoints:
    GET  /           -> {"ok": true, "now_utc": "..."}          (health check)
    POST /keymap-update  (F31)  -> {"ok": true, "started": true}
                      Runs mesh-keymap.py (full public map.meshcore.io node
                      list -> mesh-keys.json) as a detached subprocess and
                      returns right away. Single-flight + 15 min cooldown (the
                      download is ~19 MB gzipped); refusals answer
                      {"ok": false, "skipped": true, "reason": "..."} and are
                      logged to keymap-status.json for the dashboard label.
    POST /settime    body: {"epoch": <seconds since 1970>}      (sets system time)
                      -> {"ok": true, "applied_epoch": N, "delta_s": D, "now_utc": "..."}
    POST /settime    body: {"epoch": ..., "target": "/dev/ttyUSBx|/dev/ttyACMx"}   (F24)
                      -> {"ok": true, "queued": true, "target": "..."}
                      Writes a one-shot request marker; the dashboard engine
                      (mesh-neighbors.py, cron every minute) applies it to the
                      device under its per-port serial flock — MeshCore
                      "time <epoch>" or MeshCom "--settime" — and verifies the
                      result there. Serial ports are never touched from here.

Validation (defense in depth):
    * absolute range 1e8..4e9  -> catches unit bugs such as milliseconds
                                  (years ~1973 .. ~2096)
    * |epoch - now| <= 5 y     -> sane maximum for a drifted box with no RTC
    * target must be /dev/tty<USB|ACM><digits> (the engine re-validates)

Runs as root (clock_settime needs CAP_SYS_TIME). Stdlib only, so it uses the
system python3 and has no venv dependency. Logs to stderr -> journal:
    journalctl -u mesh-time-sync
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8090

EPOCH_ABS_MIN = 10 ** 8        # ~1973
EPOCH_ABS_MAX = 4 * 10 ** 9    # ~2096
MAX_DELTA_S = 5 * 366 * 86400  # 5 years

# F24: request marker consumed by mesh-neighbors.py (must match its CONFIG).
REQUEST_FILE = "/var/lib/meshcore/settime-request.json"
TARGET_RE = re.compile(r"^/dev/tty(?:USB|ACM)\d+$")

# F31: node key map refresh (see mesh-keymap.py). STATE_DIR is the engine's
# state dir; the helper writes mesh-keys.json + keymap-status.json there.
STATE_DIR = "/var/lib/meshcore"
KEYMAP_SCRIPT = "/usr/local/bin/mesh-keymap.py"
KEYMAP_STAMP = "/var/lib/meshcore/.keymap-last"    # mtime = last accepted run
KEYMAP_MIN_GAP_S = 15 * 60                         # not a click-happy endpoint
KEYMAP_RUN = {"proc": None}                        # single-flight guard
KEYMAP_LOCK = threading.Lock()


def queue_serial_request(target, epoch_s, now_dt):
    """Atomically write the F24 marker so the engine run applies it. Returns path."""
    os.makedirs(os.path.dirname(REQUEST_FILE), exist_ok=True)
    tmp = REQUEST_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"target": target, "epoch": epoch_s,
                   "requested": int(now_dt.timestamp())}, f)
    os.replace(tmp, REQUEST_FILE)
    return REQUEST_FILE


def check_epoch(epoch_s, now_dt):
    """Pure validation of a candidate epoch (seconds). Returns (ok, error|None)."""
    if isinstance(epoch_s, bool) or not isinstance(epoch_s, int):
        return False, "expected an integer number of seconds"
    if not (EPOCH_ABS_MIN < epoch_s < EPOCH_ABS_MAX):
        return False, ("epoch %d outside plausible range (%d..%d); wrong unit?"
                       % (epoch_s, EPOCH_ABS_MIN, EPOCH_ABS_MAX))
    delta = epoch_s - int(now_dt.timestamp())
    if abs(delta) > MAX_DELTA_S:
        return False, ("differs from current system time by %ds (> 5 y)"
                       % delta)
    return True, None


def apply_clock(epoch_s):
    """Set CLOCK_REALTIME via libc. Returns the new UTC datetime."""
    import ctypes
    import ctypes.util
    lib = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)

    class Timespec(ctypes.Structure):
        _fields_ = [("tv_sec", ctypes.c_long), ("tv_nsec", ctypes.c_long)]

    ts = Timespec(epoch_s, 0)
    CLOCK_REALTIME = 0
    if lib.clock_settime(CLOCK_REALTIME, ctypes.byref(ts)) != 0:
        raise OSError(ctypes.get_errno(), "clock_settime failed")
    return datetime.now(timezone.utc)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n"
                         % (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                            fmt % args))

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self._json(200, {"ok": True,
                             "now_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def handle_keymap(self):
        # F31: dashboard "Update node lookup data" button. Refuse while a run
        # is still going, and before KEYMAP_MIN_GAP_S after the last accepted
        # click (the full public map dump is ~19 MB gzipped). Refusals also
        # land in keymap-status.json so the label shows the last ATTEMPT.
        with KEYMAP_LOCK:
            proc = KEYMAP_RUN["proc"]
            if proc is not None and proc.poll() is None:
                return self._json(409, {"ok": False, "skipped": True,
                                        "reason": "update already running"})
            try:
                last = os.path.getmtime(KEYMAP_STAMP)
            except OSError:
                last = 0.0
            gap = time.time() - last
            if gap < KEYMAP_MIN_GAP_S:
                why = ("last run %d s ago (min %d min)"
                       % (int(gap), KEYMAP_MIN_GAP_S // 60))
                sys.stderr.write("keymap: skipped (%s)\n" % why)
                self._keymap_status("SKIPPED", why)
                return self._json(429, {"ok": False, "skipped": True,
                                        "reason": why})
            try:
                open(KEYMAP_STAMP, "a").close()
                KEYMAP_RUN["proc"] = subprocess.Popen(
                    [sys.executable, KEYMAP_SCRIPT, "--state-dir", STATE_DIR])
            except OSError as e:
                return self._json(500, {"ok": False,
                                        "error": "keymap spawn failed: %s" % e})
        sys.stderr.write("keymap: update started (%s)\n" % KEYMAP_SCRIPT)
        self._json(200, {"ok": True, "started": True})

    def _keymap_status(self, result, detail):
        try:
            subprocess.run([sys.executable, KEYMAP_SCRIPT, "--state-dir", STATE_DIR,
                            "--status-only", result, "--detail", detail],
                           timeout=10)
        except (OSError, subprocess.SubprocessError) as e:
            sys.stderr.write("keymap: status write failed: %s\n" % e)

    def do_POST(self):
        if self.path == "/keymap-update":
            return self.handle_keymap()
        if self.path != "/settime":
            return self._json(404, {"ok": False, "error": "not found"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length).decode() or "{}")
            epoch = data["epoch"]
            if isinstance(epoch, float) and epoch.is_integer():
                epoch = int(epoch)
            target = data.get("target") or ""
        except (ValueError, KeyError, TypeError):
            return self._json(400, {"ok": False,
                                    "error": 'expected JSON body {"epoch": <seconds>}'})
        now = datetime.now(timezone.utc)
        ok, err = check_epoch(epoch, now)
        if not ok:
            return self._json(400, {"ok": False, "error": err})
        if target:
            if not TARGET_RE.fullmatch(target):
                return self._json(400, {"ok": False,
                                        "error": "target must be /dev/ttyUSB|ttyACM<digits> or empty"})
            try:
                queue_serial_request(target, epoch, now)
            except OSError as e:
                return self._json(500, {"ok": False, "error": f"queue write failed: {e}"})
            sys.stderr.write("queued manual sync for %s (epoch %d) -> %s\n"
                             % (target, epoch, REQUEST_FILE))
            return self._json(200, {"ok": True, "queued": True, "target": target,
                                    "applied_epoch": epoch})
        old_s = int(now.timestamp())
        try:
            new_dt = apply_clock(epoch)
        except OSError as e:
            return self._json(500, {"ok": False, "error": str(e)})
        delta = epoch - old_s
        sys.stderr.write("applied epoch %d (delta %+ds), now reads %s\n"
                         % (epoch, delta, new_dt.strftime("%Y-%m-%d %H:%M:%S UTC")))
        self._json(200, {"ok": True, "applied_epoch": epoch, "delta_s": delta,
                         "now_utc": new_dt.isoformat(timespec="seconds")})


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
