#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""mesh-time-sync — emergency system-clock sync for raspi-mesh (F13).

A tiny HTTP service bound to loopback only. nginx proxies /settime to it, so
the dashboard's "set system time from your device" button can set CLOCK_REALTIME
from the visitor's browser clock when NTP is unavailable.

Endpoints:
    GET  /           -> {"ok": true, "now_utc": "..."}          (health check)
    POST /settime    body: {"epoch": <seconds since 1970>}      (sets system time)
                      -> {"ok": true, "applied_epoch": N, "delta_s": D, "now_utc": "..."}

Validation (defense in depth):
    * absolute range 1e8..4e9  -> catches unit bugs such as milliseconds
                                  (years ~1973 .. ~2096)
    * |epoch - now| <= 5 y     -> sane maximum for a drifted box with no RTC

Runs as root (clock_settime needs CAP_SYS_TIME). Stdlib only, so it uses the
system python3 and has no venv dependency. Logs to stderr -> journal:
    journalctl -u mesh-time-sync
"""
import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8090

EPOCH_ABS_MIN = 10 ** 8        # ~1973
EPOCH_ABS_MAX = 4 * 10 ** 9    # ~2096
MAX_DELTA_S = 5 * 366 * 86400  # 5 years


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

    def do_POST(self):
        if self.path != "/settime":
            return self._json(404, {"ok": False, "error": "not found"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length).decode() or "{}")
            epoch = data["epoch"]
            if isinstance(epoch, float) and epoch.is_integer():
                epoch = int(epoch)
        except (ValueError, KeyError, TypeError):
            return self._json(400, {"ok": False,
                                    "error": 'expected JSON body {"epoch": <seconds>}'})
        now = datetime.now(timezone.utc)
        ok, err = check_epoch(epoch, now)
        if not ok:
            return self._json(400, {"ok": False, "error": err})
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
