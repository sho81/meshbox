# SPDX-License-Identifier: MIT
#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""F22 checks — atomic publish of neighbors.html (tmp + os.replace).

Run:  python3 test-f22.py [engine-path]
Defaults: ./mesh-neighbors.py

The engine must never write HTML_OUT directly: a reader (nginx/browser
refresh) could catch a half-written page. Instead it writes HTML_OUT+".tmp"
and os.replace()s it into place, preserving the target's file mode so the
installed 666 neighbors.html stays replaceable by the engine user and
readable by nginx.

Covers:
  t1  write_html body uses the tmp + os.replace pattern, no direct
      open(HTML_OUT, "w") left
  t2  mode of an existing target is carried over to the tmp file (666 case)
  t3  write_html actually publishes: content lands in HTML_OUT, no stale
      .tmp remains, and the published file keeps the pre-existing mode
  t4  fresh install case: missing HTML_OUT still publishes with mode 644
  t5  state-file writers already atomic (save_usb_state keeps os.replace)
"""
import os
import re
import sys
import tempfile
import types

ENGINE = sys.argv[1] if len(sys.argv) > 1 else "mesh-neighbors.py"
src = open(ENGINE, encoding="utf-8").read()

failures = 0
def check(name, ok):
    global failures
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failures += 1

# --- t1: static pattern check on the write_html body -----------------------
m = re.search(r"def write_html\(.*?\n(?=\ndef )", src, re.S)
body = m.group(0) if m else ""
check("t1 write_html uses tmp + os.replace, no direct open(HTML_OUT, 'w')",
      'os.replace(tmp, HTML_OUT)' in body
      and 'HTML_OUT + ".tmp"' in body
      and not re.search(r'open\(\s*HTML_OUT\s*,\s*["\']w', body))

# --- load the engine as a module (pyserial-free path only used below) ------
mod = types.ModuleType("engine")
mod.__file__ = ENGINE
exec(compile(src, ENGINE, "exec"), mod.__dict__)

# --- t2/t3/t4: functional publish against a temp HTML_OUT -------------------
import datetime

def sample_rows():
    # engine row shape: (key, age, raw_snr); raw snr is /4 for display
    return [("ABCDEF01", 0, -168)]

def nodes_ever_state():
    return {"ABCDEF01": {"last": "2026-11-02 12:00:00 UTC",
                         "best_db": -42.0, "worst_db": -55.0, "sightings": 3}}

with tempfile.TemporaryDirectory() as d:
    target = os.path.join(d, "neighbors.html")
    mod.HTML_OUT = target
    mod.names = {}

    # t2+t3: pre-existing 666 target (as installed on the box)
    open(target, "w").write("placeholder")
    os.chmod(target, 0o666)
    now = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=datetime.timezone.utc)
    mod.write_html(sample_rows(), now, nodes_ever=nodes_ever_state())
    pub = open(target, encoding="utf-8").read()
    check("t2 pre-existing mode 666 carried over through the tmp file",
          os.stat(target).st_mode & 0o777 == 0o666)
    check("t3 content published atomically, no stale .tmp left",
          "ABCDEF01" in pub and "Updated" in pub
          and not os.path.exists(target + ".tmp")
          and "placeholder" not in pub)

    # t4: fresh install — target absent
    os.remove(target)
    mod.write_html(sample_rows(), now, nodes_ever=nodes_ever_state())
    check("t4 fresh install (no target) publishes with mode 644",
          os.path.exists(target) and os.stat(target).st_mode & 0o777 == 0o644)

# --- t5: state writers stay atomic ------------------------------------------
check("t5 save_usb_state keeps tmp + os.replace",
      re.search(r"def save_usb_state\(.*?os\.replace\(tmp, path\)", src, re.S) is not None)

print(f"{5} checks, {failures} failures")
sys.exit(1 if failures else 0)
