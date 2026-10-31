#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""F21 checks — station identity constants and the in-page identity line.

History: the first F21 version put a frequency band on the landing page;
revised the same day (user feedback) into the current form — everything lives
in the generated page's green block: h2 carries MeshCore + MeshCom identity
from constants, and a "MeshCore Neighbors" h3 heads the table like the other
sections. Suite consolidated accordingly.

Run:  python3 test-f21.py [engine-path] [index-html-path]
Defaults: ./mesh-neighbors.py  ./index.html

Covers:
  t1  CONFIG carries MESHCORE_FREQ/MESHCOM_NAME/MESHCOM_FREQ, old FREQ gone
  t2  HTML_TEMPLATE renders the full identity h2 (MeshCore first, then MeshCom,
      quotes escaped) and the "MeshCore Neighbors" h3 sits before {table}
  t3  index.html carries NO frequency band (same-day interim, rolled back),
      landing page otherwise intact (iframe + banner + fit script)
"""
import importlib.util
import sys
from datetime import datetime, timezone

ENGINE = sys.argv[1] if len(sys.argv) > 1 else "./mesh-neighbors.py"
INDEX = sys.argv[2] if len(sys.argv) > 2 else "./index.html"

checks = 0
failures = 0
def check(name, cond, info=""):
    global checks, failures
    checks += 1
    if not cond:
        failures += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{info}]"))

spec = importlib.util.spec_from_file_location("engine", ENGINE)
eng = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eng)

check("t1 MESHCORE_FREQ constant", eng.MESHCORE_FREQ == "869.618 MHz", repr(getattr(eng, "MESHCORE_FREQ", None)))
check("t1 MESHCOM_NAME constant", eng.MESHCOM_NAME == 'DK0MAV-12 "Digipeater Peine"', repr(getattr(eng, "MESHCOM_NAME", None)))
check("t1 MESHCOM_FREQ constant", eng.MESHCOM_FREQ == "433.175 MHz", repr(getattr(eng, "MESHCOM_FREQ", None)))
check("t1 old FREQ constant gone", not hasattr(eng, "FREQ"))

page = eng.HTML_TEMPLATE.format(
    iso=datetime(2026, 10, 31, 18, 0, 0, tzinfo=timezone.utc).isoformat(timespec="seconds"),
    started_meta="", sublines="", node=eng.NODE_NAME, freq=eng.MESHCORE_FREQ,
    meshcom_name=eng.htmllib.escape(eng.MESHCOM_NAME), meshcom_freq=eng.MESHCOM_FREQ,
    table="<TABLEMARK/>", extra_sections="", src_port="ttyUSB0")
want_h2 = ("DK0MAV mc&sup2;-Peine-Node &mdash; MeshCore: Amateurfunk Peine FTZ, 869.618 MHz"
           " &nbsp;|&nbsp; MeshCom: DK0MAV-12 &quot;Digipeater Peine&quot;, 433.175 MHz")
check("t2 h2 shows full MeshCore + MeshCom identity", want_h2 in page, page[:400])
check("t2 MeshCore listed before MeshCom",
      -1 < page.find(eng.MESHCORE_FREQ) < page.find(eng.MESHCOM_FREQ))
check("t2 'MeshCore Neighbors' h3 heads the table",
      "<h3>MeshCore Neighbors</h3>" in page and page.find("<h3>MeshCore Neighbors</h3>") < page.find("<TABLEMARK/>"), page[:400])

idx = open(INDEX, encoding="utf-8").read()
check("t3 index.html has no frequency band (rolled-back interim)",
      eng.MESHCORE_FREQ not in idx and eng.MESHCOM_FREQ not in idx)
check("t3 landing page intact (iframe + banner + fit script)",
      'id="neighborsFrame"' in idx and "neighborsFrame" in idx and r"/____/_/|_|" in idx)

print(f"\n{checks} checks, {failures} failures")
sys.exit(1 if failures else 0)
