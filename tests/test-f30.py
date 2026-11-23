#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""F30 regression suite — 8-step Unicode signal stairs in the live SNR cell.

  t1  BAR_CHARS = U+2581..U+2588 (eight ascending glyphs)
  t2  default scale −20..+8: level mapping at every band boundary (0..8)
  t3  box-config bar_min/bar_max move the scale
  t4  bogus bar_min/bar_max shapes fall back to defaults
  t5  live cell renders colored prefix + dim rest + keeps data-sort; no-live
      row keeps plain "-" (no stairs)
  t6  best/worst columns untouched (no stairs there)

Run:  python3 test-f30.py [engine-path]
Defaults resolve for both the repo root and the flat staging layout.
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))


def _find(name):
    for cand in (os.path.join(HERE, name), os.path.join(os.path.dirname(HERE), name)):
        if os.path.isfile(cand):
            return cand
    raise SystemExit(f"{name} not found next to this suite")


ENGINE = sys.argv[1] if len(sys.argv) > 1 else _find("mesh-neighbors.py")
PASS = []


def check(name, cond, info=""):
    if cond:
        PASS.append(name)
        print(f"PASS {name}")
    else:
        print(f"FAIL {name} {info}")
        sys.exit(1)


def load_with(cfg_text=None, alias="mn30"):
    td = tempfile.mkdtemp(prefix="f30-")
    eng = os.path.join(td, "mesh-neighbors.py")
    shutil.copy(ENGINE, eng)
    if cfg_text is not None:
        with open(os.path.join(td, "box-config.json"), "w", encoding="utf-8") as f:
            f.write(cfg_text)
    spec = importlib.util.spec_from_file_location(alias, eng)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mn = load_with()
mn.names = {"AABB0011": "StairNode"}

# ------------------------------------------------------------------- t1 glyphs
check("t1 BAR_CHARS is U+2581..U+2588",
      mn.BAR_CHARS == "".join(chr(0x2581 + i) for i in range(8)) and len(mn.BAR_CHARS) == 8,
      repr(mn.BAR_CHARS))

# ------------------------------------------------------------------- t2 levels
check("t2 default scale -20..+8", mn.BAR_MIN == -20.0 and mn.BAR_MAX == 8.0)
SPEC = [(-21.0, 0), (-20.5, 0), (-20.0, 1), (-16.1, 1), (-16.0, 2),
        (-12.0, 3), (-8.0, 4), (-7.5, 4), (-4.0, 5), (-2.1, 5),
        (0.0, 6), (3.9, 6), (4.0, 7), (7.9, 7), (8.0, 8), (42.0, 8)]
bad = [(db, mn.snr_level(db), want) for db, want in SPEC if mn.snr_level(db) != want]
check("t2 every band boundary maps per spec (levels 0..8)", not bad, str(bad))

# ------------------------------------------------------------------- t3 overlay
ov = load_with(json.dumps({"bar_min": -30, "bar_max": 2}))
check("t3 bar_min/bar_max overlay moves scale",
      ov.BAR_MIN == -30.0 and ov.BAR_MAX == 2.0
      and ov.snr_level(-31) == 0 and ov.snr_level(-29) == 1
      and ov.snr_level(1) == 7 and ov.snr_level(2) == 8 and ov.snr_level(99) == 8,
      str([ov.snr_level(x) for x in (-31, -29, 1, 2, 99)]))

# ------------------------------------------------------------------- t4 bogus
bog = load_with(json.dumps({"bar_min": "-20", "bar_max": [8]}), "mn30bog")
check("t4 bogus bar_min/bar_max fall back to defaults",
      bog.BAR_MIN == -20.0 and bog.BAR_MAX == 8.0)

# ------------------------------------------------------------------- t5 cell
NOW = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)
STATE = {"AABB0011": {"last": "2026-11-23 12:00:00 UTC", "best_db": 5.0, "worst_db": -25.0,
                      "sightings": 4},
         "CCDD0022": {"last": "2026-11-22 12:00:00 UTC", "best_db": 2.0, "worst_db": -9.0,
                      "sightings": 2}}
table = mn.build_merged_table([("AABB0011", 0, 16)], STATE, NOW)  # snr 16/4 = +4 -> 7 steps
check("t5 live cell: colored prefix + dim rest + data-sort kept",
      '<span class="sig"><span style="color:#7f7">▁▂▃▄▅▆▇</span>'
      '<span class="sig-off">█</span></span> +4.00</td>' in table
      and 'data-sort="4.00"' in table, table[table.find("AABB0011"):][:340])
check("t5 no-live row keeps plain '-' (no stairs)",
      '<td class="num">-</td>' in table)

# ------------------------------------------------------------------- t6 untouched
i = table.find("AABB0011")
seg = table[i:i + 700]
check("t6 best/worst cells carry no stairs",
      'style="color:#7f7" data-sort="5.00">+5.00' in seg
      and 'style="color:#f95" data-sort="-25.00">-25.00' in seg
      and seg.count('class="sig"') == 1, seg[:460])

print(f"\n{len(PASS)} checks passed")
