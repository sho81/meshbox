#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""piups-log-relay — compact the piupsmonitor debug log onto the USB stick (F16).

The piupsmonitor daemon writes its full-rate debug log to a tmpfs file
(LIVE_LOG, ~13 KB/s at LogLevel=debug) so neither the boot SD card nor the
USB forensics stick wears from every I2C read. This relay tails that file and
appends a compact subset — verbatim lines with original timestamps, no
synthesised content — to OUT_LOG on the USB stick:

  * status bits (and any unknown DEBUG field): emitted on first sighting and
    whenever the value differs from the last emitted one for that field, so
    state transitions and blips are recorded exactly once;
  * readings U_Bat/I_Rasp/U_USB/U_USV/U_Ext: a full snapshot block (the most
    recent line per field) is emitted every FLUSH_INTERVAL seconds, which
    guarantees persisted values + timestamps at <=5 s cadence for forensics;
    additionally any reading line between snapshots whose value moved by >=
    the configured threshold (10 mV / 10 mA) from the last emitted value is
    queued immediately.

LIVE_LOG is self-trimmed: once it exceeds MAX_BYTES it is truncated in place,
keeping only the newest KEEP_BYTES — safe because the daemon writes O_APPEND
and both consumers tolerate one partial head line. Every appended line kept
the order of its timestamp prefix (stable sort within each batch), so OUT_LOG
remains a chronological true subset of the daemon stream and tail parsers
(mesh-neighbors.py) work unchanged on it.

Env overrides (testing / field tuning): PIUPS_RELAY_FLUSH (s), PIUPS_RELAY_MAX
(bytes), PIUPS_RELAY_KEEP (bytes).
"""
import os
import re
import signal
import sys
import time

LIVE_LOG = "/run/piupsmonitor/live.log"
OUT_LOG = "/var/log/piupsmonitor-logs/piupsmonitor.log"
FLUSH_INTERVAL = float(os.environ.get("PIUPS_RELAY_FLUSH", "5"))
MAX_BYTES = int(float(os.environ.get("PIUPS_RELAY_MAX", str(64 * 1024 * 1024))))
KEEP_BYTES = int(float(os.environ.get("PIUPS_RELAY_KEEP", str(32 * 1024 * 1024))))

# field -> delta threshold. Reading fields are snapshot + excursion logged;
# every other (status) field is pure change-delta.
READING_THRESHOLDS = {"U_Bat": 10, "I_Rasp": 10, "U_USB": 10, "U_USV": 10, "U_Ext": 10}

LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[DEBUG\] (.+?): (-?\d+)(?: (mV|mA))?$"
)


def log(msg):
    print(f"[piups-log-relay] {msg}", file=sys.stderr, flush=True)


class Relay:
    def __init__(self, live_log=LIVE_LOG, out_log=OUT_LOG,
                 flush_interval=FLUSH_INTERVAL, max_bytes=MAX_BYTES, keep_bytes=KEEP_BYTES):
        self.live_log = live_log
        self.out_log = out_log
        self.flush_interval = flush_interval
        self.max_bytes = max_bytes
        self.keep_bytes = keep_bytes
        self.last_status = {}       # field -> last emitted value (delta fields)
        self.last_reading_val = {}  # field -> last emitted reading value
        self.latest_reading = {}    # field -> (line, int value), newest seen
        self.pending = []           # verbatim lines queued for the next flush
        self.stop = False

    def handle_line(self, line):
        m = LINE_RE.match(line)
        if not m:
            return
        field, val = m.group(2), int(m.group(3))
        if field in READING_THRESHOLDS:
            self.latest_reading[field] = (line, val)
            prev = self.last_reading_val.get(field)
            if prev is None or abs(val - prev) >= READING_THRESHOLDS[field]:
                self.pending.append(line)
                self.last_reading_val[field] = val
        else:  # status bits / unknown fields: first sighting + every change
            if self.last_status.get(field) != val:
                self.pending.append(line)
                self.last_status[field] = val

    def tick(self):
        """Periodic snapshot: the current value of every reading field.

        Unconditional in steady state (the daemon stamps a fresh line for each
        field every second, so "latest" always carries a current timestamp and
        the <=flush_interval cadence guarantee holds). Only skipped when the
        very same line was already queued this cycle as an excursion — avoids
        one duplicate per flush at most.
        """
        for field, (line, val) in list(self.latest_reading.items()):
            if line not in self.pending:
                self.pending.append(line)
            self.last_reading_val[field] = val

    def flush(self):
        if not self.pending:
            return 0
        if len(self.pending) > 4096:  # persistent OUT failure guard
            log(f"pending queue exceeded {len(self.pending)} lines; dropping oldest")
            self.pending = self.pending[-1024:]
        lines = sorted(self.pending, key=lambda l: l[:19])  # chronological, stable
        try:
            with open(self.out_log, "a", encoding="utf-8") as f:
                for line in lines:
                    f.write(line + "\n")
        except OSError as e:
            log(f"flush to {self.out_log} failed ({e}); keeping {len(self.pending)} pending lines")
            return 0
        n = len(lines)
        self.pending = []
        return n

    def trim_if_needed(self, f):
        size = os.fstat(f.fileno()).st_size
        if size > self.max_bytes:
            keep = min(self.keep_bytes, size)
            # Keep the NEWEST bytes: a plain truncate() only cuts the tail, so
            # grab the last KEEP bytes and rewrite them in place. The file is
            # briefly small during the rewrite (same transient class as the
            # logrotate copytruncate window); the daemon's O_APPEND writes can
            # at most lose one line inside that ~ms window.
            f.seek(size - keep)
            tail = f.read()
            f.seek(0)
            f.truncate()
            f.write(tail)
            log(f"live log trimmed {size // 1024} KiB -> {len(tail) // 1024} KiB "
                f"(keeping last {self.keep_bytes // (1024 * 1024)} MiB)")

    def run(self):
        f = None
        while not self.stop:
            try:
                f = open(self.live_log, "r+b")  # r+b: trim rewrites the live file in place
                break
            except FileNotFoundError:
                time.sleep(1.0)
        if f is None:
            return 0  # stopped while waiting for the live log to appear
        f.seek(0, os.SEEK_END)  # resume from now; first-sighting emissions re-establish state within seconds
        log(f"tailing {self.live_log} -> {self.out_log} "
            f"(flush every {self.flush_interval:g}s, live cap {self.max_bytes // 1024} KiB, "
            f"keep {self.keep_bytes // 1024} KiB)")
        buf = b""
        since_trim_check = 0
        next_flush = time.monotonic() + self.flush_interval
        while not self.stop:
            chunk = f.read(1 << 16)
            if chunk:
                buf += chunk
                end = buf.find(b"\n")
                while end >= 0:
                    raw, buf = buf[:end], buf[end + 1:]
                    self.handle_line(raw.decode("utf-8", "replace").rstrip("\r"))
                    end = buf.find(b"\n")
                since_trim_check += len(chunk)
                if since_trim_check >= (1 << 20):  # trim check at most once per MiB consumed
                    self.trim_if_needed(f)
                    since_trim_check = 0
            else:
                time.sleep(0.5)
            now = time.monotonic()
            if now >= next_flush:
                self.tick()
                self.flush()
                next_flush = now + self.flush_interval
        f.close()
        self.tick()
        self.flush()  # best-effort final snapshot on shutdown
        return 0


def main():
    relay = Relay()

    def _stop(signum, frame):
        relay.stop = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log(f"started (flush {FLUSH_INTERVAL:g}s; live cap {MAX_BYTES // 1024} KiB / "
        f"keep {KEEP_BYTES // 1024} KiB)")
    return relay.run()


if __name__ == "__main__":
    sys.exit(main())
