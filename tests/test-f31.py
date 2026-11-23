#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""F31 regression suite — map.meshcore.io deep links on node names + lookup label.

  t1  load_key_map: {} without file, normalization (upper prefix / lower key)
  t2  node_link_url: default map URL, overlay "" = off, custom {key} template
  t3  render_name_cell: linked (target/rel/arrow) only when the full key is
          known; plain cell otherwise; data-sort unchanged
  t4  keymap_bar_html: no-status hint, OK / FAIL / SKIPPED labels + detail,
          JS marker present
  t5  build_merged_table integration: one linked row, one plain row,
          SNR/best/worst cells untouched
  t6  helper CLI: --status-only writes keymap-status.json (SKIPPED path)

Run:  python3 test-f31.py [engine-path]
Defaults resolve for both the repo root and the flat staging layout.
"""
import importlib.util
import json
import os
import shutil
import subprocess
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
HELPER = _find("mesh-keymap.py")
PASS = []


def check(name, cond, info=""):
    if cond:
        PASS.append(name)
        print(f"PASS {name}")
    else:
        print(f"FAIL {name} {info}")
        sys.exit(1)


def load_with(cfg_text=None, alias="mn31"):
    td = tempfile.mkdtemp(prefix="f31-")
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

# ------------------------------------------------------------- t1 key map load
check("t1a no key map file -> {}", mn.load_key_map("/nonexistent/mesh-keys.json") == {})
td1 = tempfile.mkdtemp(prefix="f31-keys-")
kpath = os.path.join(td1, "mesh-keys.json")
with open(kpath, "w") as f:
    json.dump({"aabb0011": "0100DEADBEEF" + "0" * 52}, f)
km = mn.load_key_map(kpath)
check("t1b normalization upper prefix / lower key",
      km == {"AABB0011": "0100deadbeef" + "0" * 52}, str(km))

# ------------------------------------------------------------- t2 link template
FULL = "0100" + "ab" * 30
check("t2a default map URL",
      mn.node_link_url("AABB0011", FULL) == "https://map.meshcore.io/?public_key=" + FULL)
off = load_with(json.dumps({"node_link_url": ""}), "mn31off")
check("t2b overlay \"\" turns links off", off.node_link_url("AABB0011", FULL) == "")
cust = load_with(json.dumps({"node_link_url": "https://example.org/n?k={key}"}), "mn31cust")
check("t2c custom {key} template",
      cust.node_link_url("AABB0011", FULL) == "https://example.org/n?k=" + FULL)

# ------------------------------------------------------------- t3 name cell
mn.names = {"AABB0011": "Good Node", "CCDD0022": "No Key Node"}
mn.KEY_MAP = {"AABB0011": FULL}
cell = mn.render_name_cell("AABB0011", "Good Node")
check("t3a linked cell: url + new tab + noopener + arrow + data-sort",
      '<td data-sort="good node">'
      '<a href="https://map.meshcore.io/?public_key=' + FULL + '" target="_blank" '
      'rel="noopener" title="Show node on map.meshcore.io">'
      'Good Node<span class="ext">\u2197</span></a></td>' == cell, cell)
cell2 = mn.render_name_cell("CCDD0022", "No Key Node")
check("t3b no full key -> plain cell",
      cell2 == '<td data-sort="no key node">No Key Node</td>', cell2)
cell3 = mn.render_name_cell("AABB0011", "A&amp;B &lt;x&gt;")
check("t3c escaping kept inside link",
      ">A&amp;B &lt;x&gt;<span" in cell3 and "public_key=" + FULL in cell3, cell3)

# ------------------------------------------------------------- t4 lookup label
mn.KEYMAP_STATUS_FILE = os.path.join(td1, "keymap-status.json")
bar = mn.keymap_bar_html()
check("t4a no status file -> hint + button + JS marker",
      "no node lookup data yet" in bar and 'id="keymap-btn"' in bar
      and "/*__KEYMAPJS__*/" in bar, bar)


def bar_for(result, detail="d"):
    with open(mn.KEYMAP_STATUS_FILE, "w") as f:
        json.dump({"last_run": "2026-11-23 17:00 UTC", "result": result,
                   "detail": detail}, f)
    return mn.keymap_bar_html()


check("t4b OK label green + detail",
      'Last node lookup: 2026-11-23 17:00 UTC &mdash; <span style="color:#7f7">OK'
      in bar_for("OK", "12 keys stored"))
check("t4c FAIL label red",
      '<span style="color:#f95">FAIL' in bar_for("FAIL", "timeout"))
check("t4d SKIPPED label dim",
      '<span style="color:#9a9">SKIPPED' in bar_for("SKIPPED", "min 15 min"))

# ------------------------------------------------------------- t5 integration
NOW = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)
STATE = {"AABB0011": {"last": "2026-11-23 12:00:00 UTC", "best_db": 5.0,
                      "worst_db": -25.0, "sightings": 4},
         "CCDD0022": {"last": "2026-11-22 12:00:00 UTC", "best_db": 2.0,
                      "worst_db": -9.0, "sightings": 2}}
table = mn.build_merged_table([("AABB0011", 0, 16)], STATE, NOW)  # snr 16/4 = +4
check("t5a linked + plain rows in table",
      "?public_key=" + FULL in table
      and '<td data-sort="no key node">No Key Node</td>' in table)
check("t5b SNR cell untouched by links",
      'class="sig"' in table and 'data-sort="4.00"' in table
      and 'data-sort="5.00"' in table)

# ------------------------------------------------------------- t6 helper CLI
td2 = tempfile.mkdtemp(prefix="f31-cli-")
r = subprocess.run([sys.executable, HELPER, "--state-dir", td2,
                    "--status-only", "SKIPPED", "--detail", "last run 3 s ago"],
                   capture_output=True, text=True, timeout=30)
check("t6 helper --status-only writes status", r.returncode == 0
      and json.load(open(os.path.join(td2, "keymap-status.json")))["result"] == "SKIPPED",
      r.stderr)

# ------------------------------------------- t7 helper fetch: local gzip fixture
import gzip as _gzip
import http.server
import threading

spec = importlib.util.spec_from_file_location("mkm", HELPER)
mkm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mkm)

K1 = "0100" + "11" * 30
K2 = "0200" + "22" * 30
K3 = "0300" + "33" * 30          # NOT in nodes-ever -> must be skipped
FIXTURE = json.dumps([
    {"public_key": K1, "adv_name": "One"},
    {"public_key": K2, "adv_name": "Two {curly} \"quoted\""},   # brace/quote torture
    {"public_key": K3, "adv_name": "Three"},
]).encode()


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = _gzip.compress(FIXTURE)
        self.send_response(200)
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(("127.0.0.1", 0), _H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
td3 = tempfile.mkdtemp(prefix="f31-fetch-")
with open(os.path.join(td3, "nodes-ever.json"), "w") as f:
    json.dump({K1[:8]: {"last": "x"}, "aabb9999": {"last": "y"}}, f)
mkm.MAP_URL = f"http://127.0.0.1:{port}/api/v1/nodes"
hits, scanned, xfer = mkm.fetch_matches(td3)
srv.shutdown()
check("t7a streaming parse: 3 scanned, only wanted prefixes hit",
      scanned == 3 and set(hits) == {K1[:8]} and hits[K1[:8]] == K1.lower(),
      str((scanned, hits)))
merged = mkm.merge_existing(td3, hits)             # no old file -> hits as-is
mkm.write_json_atomic(os.path.join(td3, "mesh-keys.json"), merged)
check("t7b written key map round-trips",
      json.load(open(os.path.join(td3, "mesh-keys.json"))) == {K1[:8]: K1.lower()})
print(f"\n{len(PASS)} checks passed")
