#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""F28 regression suite — merged nodes table opens sorted by "Last seen".

  t1  build_merged_table: rows newest-heard first (data-order follows that)
  t2  SORT_JS: nodes table initial column = Last seen (asc = freshest),
      other tables keep first column; the branch ships inside the page
  t3  header/column layout unchanged (Last seen is column index 2)

Run:  python3 test-f28.py [engine-path]
Defaults resolve for both the repo root and the flat staging layout.
"""
import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))


def _find(name):
    for cand in (os.path.join(HERE, name), os.path.join(os.path.dirname(HERE), name)):
        if os.path.isfile(cand):
            return cand
    raise SystemExit(f"{name} not found next to this suite")


ENGINE = sys.argv[1] if len(sys.argv) > 1 else _find("mesh-neighbors.py")
spec = importlib.util.spec_from_file_location("mn", ENGINE)
mn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mn)
mn.names = {}
PASS = []


def check(name, cond, info=""):
    if cond:
        PASS.append(name)
        print(f"PASS {name}")
    else:
        print(f"FAIL {name} {info}")
        sys.exit(1)


NOW = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)
FMT = "%Y-%m-%d %H:%M:%S UTC"
STATE = {  # deliberately inserted oldest-first: sort must reorder to freshest
    "AAAA0001": {"last": (NOW - timedelta(days=30)).strftime(FMT),
                 "best_db": 100, "worst_db": 20, "sightings": 3},
    "BBBB0002": {"last": (NOW - timedelta(minutes=5)).strftime(FMT),
                 "best_db": 120, "worst_db": 40, "sightings": 9},
    "CCCC0003": {"last": (NOW - timedelta(hours=6)).strftime(FMT),
                 "best_db": 80, "worst_db": 10, "sightings": 5},
}
table = mn.build_merged_table([("BBBB0002", 1, 12)], STATE, NOW)

first = table[table.find('<tr data-order="0">'):table.find('</tr>', table.find('<tr data-order="0">'))]
last = table[table.find('<tr data-order="2">'):table.find('</tr>', table.find('<tr data-order="2">'))]
check("t1 order is freshest-first: BBBB0002 fresh, AAAA0001 oldest",
      "BBBB0002" in first and "AAAA0001" in last, first[:120])
check("t2 SORT_JS picks Last seen (idx 2) for tbl-nodes, col 0 elsewhere",
      "t.id === 'tbl-nodes' && ths.length > 2" in mn.SORT_JS
      and "var init = (t.id === 'tbl-nodes' && ths.length > 2) ? 2 : 0;" in mn.SORT_JS
      and "activate(ths[init], init, 'asc');" in mn.SORT_JS, mn.SORT_JS[-300:])
check("t3 Last seen stays column index 2 of the nodes table",
      table.find(">Last seen<") > table.find(">Node<")
      and table.find(">SNR (dB)<") > table.find(">Last seen<"))

print(f"\n{len(PASS)} checks passed")
