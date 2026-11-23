#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""F32 regression suite — MeshCom Neighbors table (--mheard + ever-state).

  t1  parse_meshcom_mheard on a real 4.40a reply: header skipped, calls
      upper-cased, age units s/min/h, snr float, gw flag
  t2  garbage/older firmware replies parse to [] (no crash)
  t3  update_meshcom_ever: first run creates entries, exact same heard-event
      does not inflate sightings, newer event updates last/best/worst
  t4  gw=Y is sticky; bogus rows skipped
  t5  build_meshcom_table: newest first, title=seen ISO, live SNR cell has
      stairs + data-sort, stale rows show plain "-", GW badge, escaping
  t6  empty state -> "no MeshCom stations recorded yet"
  t7  write_html: section rendered only when meshcom_ever given; template
      carries the {meshcom_table} slot; SORT_JS inits tbl-meshcom by col 1

Run:  python3 test-f32.py [engine-path]
Defaults resolve for both the repo root and the flat staging layout.
"""
import importlib.util
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


def check(name, cond, info=""):
    if cond:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name} {info}")
        sys.exit(1)


td = tempfile.mkdtemp(prefix="f32-")
eng_path = os.path.join(td, "mesh-neighbors.py")
shutil.copy(ENGINE, eng_path)
spec = importlib.util.spec_from_file_location("mn32", eng_path)
mn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mn)
mn.MESHCOM_EVER_FILE = os.path.join(td, "meshcom-nodes-ever.json")
mn.names = {}

REAL = """
--mheard\r[MH] window=720min rows=2
[MH] call=EXAMPLE-99 2026.11.23 18:32:55 typ=TXT hw=TBEAM_AXP2101 mod=8/8 rssi=-100dBm snr=8dB dist=0.0km ncnt=2 age=2min hm=10dB role=R ex=0 nb=2 gw=N lat=N52.000 lon=E010.000 alt=100m
[MH] call=dk0mav-12 2026.11.23 18:32:50 typ=TXT hw=HELTEC_V3 mod=8/8 rssi=-80dBm snr=-3.5dB dist=4.6km ncnt=2 age=1h hm=5dB role=R ex=0 nb=2 gw=Y lat=N52.311 lon=E010.213 alt=103m
"""

rows = mn.parse_meshcom_mheard(REAL)
check("t1a two rows parsed", len(rows) == 2, repr(rows))
check("t1b upper call + float snr", rows[0]["call"] == "EXAMPLE-99"
      and rows[0]["snr_db"] == 8.0 and rows[0]["gw"] == "N")
check("t1c lower-call upper-cased, h+neg snr", rows[1]["call"] == "DK0MAV-12"
      and rows[1]["snr_db"] == -3.5 and rows[1]["age_s"] == 3600
      and rows[1]["gw"] == "Y")
check("t1d age min unit", rows[0]["age_s"] == 120)
check("t1e seconds unit", mn.parse_meshcom_mheard(
    "[MH] call=X1 snr=1dB age=45s gw=N")[0]["age_s"] == 45)

check("t2a empty/garbage -> []", mn.parse_meshcom_mheard("") == []
      and mn.parse_meshcom_mheard(None) == []
      and mn.parse_meshcom_mheard("Mheard list\r\n--------------\r\nno entries") == [])
check("t2b row without snr skipped", mn.parse_meshcom_mheard(
    "[MH] call=ONLY 2026.11.23 typ=TXT") == [])

NOW = datetime(2026, 11, 23, 19, 0, 0, tzinfo=timezone.utc)
st = mn.update_meshcom_ever(rows, NOW)
check("t3a two stations created", len(st) == 2 and st["DK0MAV-12"]["gw"] == "Y")
check("t3b seen time = now-age", st["EXAMPLE-99"]["last"] == "2026-11-23 18:58:00 UTC",
      st["EXAMPLE-99"])
st2 = mn.update_meshcom_ever(rows, NOW)
check("t3c same events: no sighting inflation",
      st2["EXAMPLE-99"]["sightings"] == 1 and st2["DK0MAV-12"]["sightings"] == 1)
newer = [{"call": "EXAMPLE-99", "age_s": 0, "snr_db": 12.0, "gw": "N"},
         {"call": "DK0MAV-12", "age_s": 60, "snr_db": -9.0, "gw": "N"}]
st3 = mn.update_meshcom_ever(newer, NOW)
e = st3["EXAMPLE-99"]
check("t3d new event updates", e["sightings"] == 2 and e["best_db"] == 12.0
      and e["last"] == "2026-11-23 19:00:00 UTC" and e["first"] == "2026-11-23 18:58:00 UTC")
check("t3e worst deepens, gw stays Y", st3["DK0MAV-12"]["worst_db"] == -9.0
      and st3["DK0MAV-12"]["gw"] == "Y")
check("t3f bogus rows ignored",
      len(mn.update_meshcom_ever([{"call": "", "snr_db": 1},
                                  {"call": "X", "snr_db": "nonsense"}], NOW)) == 2)

html = mn.build_meshcom_table(st3, {"EXAMPLE-99": 12.0}, NOW)
check("t5a newest first", html.index("EXAMPLE-99") < html.index("DK0MAV-12"))
check("t5b title=ISO seen", 'title="2026-11-23 19:00:00 UTC"' in html)
check("t5c live cell has stairs+sort", 'data-sort="12.00"' in html and "\u2587" in html)
check("t5d stale row plain -", html.count('<td class="num">-</td>') == 1)
check("t5e GW badge on dk0mav", '<span class="ext">GW</span>' in html)
check("t5f table id+headers", 'id="tbl-meshcom"' in html and "Last heard" in html)
check("t6 empty state message", "no MeshCom stations recorded yet"
      in mn.build_meshcom_table({}, None, NOW))

page = mn.HTML_TEMPLATE.format(
    iso="x", title="t", station="s", started_meta="", sublines="",
    node="n", freq="f", meshcom_name="m", meshcom_freq="mf",
    table="<table/>", keymap_bar="", meshcom_table="<h3>MeshCom Neighbors</h3>TBL",
    extra_sections="", src_port="p")
check("t7a slot rendered", "<h3>MeshCom Neighbors</h3>TBL" in page)
check("t7b SORT_JS inits tbl-meshcom col 1",
      "tbl-meshcom" in mn.SORT_JS and "? 1 : 0" in mn.SORT_JS)

print(f"\n{len(sys.argv) and 'F32'} all checks passed")
