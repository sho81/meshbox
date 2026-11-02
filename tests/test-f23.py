# SPDX-License-Identifier: MIT
#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""F23 checks — log() output is sanitized to printable ASCII.

Run:  python3 test-f23.py [engine-path]
Defaults: ./mesh-neighbors.py

The cron log must stay pure printable ASCII: a single NUL or control byte
makes grep/less treat the whole multi-megabyte log as binary and hides all
matches. The engine's log() therefore sanitizes its message through
_sanitize(); normal messages must pass through byte-for-byte unchanged.

Covers:
  t1  _sanitize exists and log() wraps its message in it
  t2  NUL / control chars / DEL become "?", printable ASCII untouched
  t3  embedded newlines cannot forge extra log lines
  t4  normal ok-style message passes through unchanged
  t5  log() end-to-end: captured stdout line is single, clean, well-formed
"""
import io
import re
import sys
import types

ENGINE = sys.argv[1] if len(sys.argv) > 1 else "mesh-neighbors.py"
src = open(ENGINE, encoding="utf-8").read()

failures = 0
def check(name, ok):
    global failures
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failures += 1

# --- t1: static shape -------------------------------------------------------
check("t1 _sanitize defined and used inside log()",
      re.search(r"def _sanitize\(msg\):", src) is not None
      and re.search(r"def log\(msg\):\n(?:.*\n)*?.*_sanitize\(msg\)", src) is not None)

# --- load engine as module --------------------------------------------------
mod = types.ModuleType("engine")
mod.__file__ = ENGINE
exec(compile(src, ENGINE, "exec"), mod.__dict__)
s = mod._sanitize

# --- t2: sanitization semantics ----------------------------------------------
check("t2 NUL/ctrl/DEL -> '?', printable ASCII untouched",
      s("a\x00b") == "a?b"
      and s("\x1b[31mred\x07") == "?[31mred?"
      and s("del\x7f") == "del?"
      and s("ok: ttyUSB0=meshcore; U_Bat=4142 mV (100 %)") == "ok: ttyUSB0=meshcore; U_Bat=4142 mV (100 %)")

# --- t3: no forged lines ------------------------------------------------------
check("t3 embedded newline cannot forge log lines",
      "\n" not in s("line1\n[2026-11-02 00:00:00 UTC] fake")
      and s("a\r\nb") == "a??b")

# --- t4: pass-through ---------------------------------------------------------
msg = ("ok: ttyUSB0=meshcore, ttyUSB1=meshcom; 1 raw entries -> 1 unique node(s); "
       "wrote /var/www/html/neighbors.html; piups 0 s old U_Bat=4142 mV I_Rasp=715 mA")
check("t4 normal ok-message passes through unchanged", s(msg) == msg)

# --- t5: end-to-end through log() ---------------------------------------------
buf = io.StringIO()
old = sys.stdout
sys.stdout = buf
try:
    mod.log("warning: junk\x00\x1b[0m on port\x1b")
finally:
    sys.stdout = old
out = buf.getvalue()
body_ok = (out.count("\n") == 1
           and re.match(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC\] ", out) is not None
           and all(0x20 <= ord(c) <= 0x7e for c in out.rstrip("\n"))
           and "junk?" in out and "on port?" in out)
check("t5 log() writes one clean, well-formed line", body_ok)

print(f"5 checks, {failures} failures")
sys.exit(1 if failures else 0)
