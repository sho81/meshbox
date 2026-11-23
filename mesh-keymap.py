#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""mesh-keymap — refresh the F31 node key map from the public MeshCore map.

The dashboard (mesh-neighbors.py) only ever sees each neighbor's 8-hex
public_key prefix; map.meshcore.io opens a node deep link only for the FULL
64-hex public key. This helper downloads the map's public node list and
stores, for every prefix we have ever heard (nodes-ever.json), the full key
in <state-dir>/mesh-keys.json. Nodes that were never published on the map
get no entry and therefore no link — nothing is invented or leaked here.

The API has no partial query: prefix params are ignored server-side and
/nodes/<prefix> is a 400, so the full list is the minimum work. It is served
gzipped (~19 MB transfer; ~57 MB raw) — that is why the dashboard button
carries a confirm warning and the service enforces a 15 min cooldown. The
reply is streamed and parsed object-by-object (raw_decode), so peak memory
stays low even on a 1 GB Pi; only matching keys are kept.

After every run it writes <state-dir>/keymap-status.json:
    {"last_run": "YYYY-MM-DD HH:MM UTC", "result": "OK|SKIPPED|FAIL",
     "detail": "1234 nodes scanned, 20 keys stored, 18.2 MB transfer",
     "file_bytes": 1394}
which the dashboard renders as "Last node lookup: ... — OK (...)".

Usage:
    mesh-keymap.py [--state-dir DIR]            # do a lookup run
    mesh-keymap.py --status-only RESULT [--detail TEXT]   # just log a status
Stdlib only. Run manually, or from the time-sync service via the dashboard
button (see mesh-time-sync.py /keymap-update).
"""
import argparse
import gzip
import json
import os
import sys
import time
import urllib.request

MAP_URL = "https://map.meshcore.io/api/v1/nodes"
DEFAULT_STATE_DIR = "/var/lib/meshcore"
KEYS_FILE = "mesh-keys.json"
STATUS_FILE = "keymap-status.json"
NODES_EVER_FILE = "nodes-ever.json"
UA = "meshbox-keymap/1.0 (+local dashboard key refresh)"


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S UTC ") + msg)


def write_json_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def write_status(state_dir, result, detail, started, file_bytes=None):
    st = {"last_run": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(started)),
          "result": result, "detail": detail}
    if file_bytes is not None:
        st["file_bytes"] = file_bytes
    try:
        write_json_atomic(os.path.join(state_dir, STATUS_FILE), st)
    except OSError as e:
        log(f"status write failed: {e}")


def wanted_prefixes(state_dir):
    """8-hex prefixes seen so far (upper); empty set without usable state."""
    try:
        with open(os.path.join(state_dir, NODES_EVER_FILE), "r",
                  encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k).upper()[:8] for k in data}
    except (OSError, ValueError) as e:
        log(f"warning: cannot read nodes-ever state: {e}")
    return set()


def iter_objects(stream, decoder):
    """Yield the objects of one JSON array, incrementally (bounded memory).

    stream yields decompressed bytes; raw_decode handles nested objects and
    braces inside strings, incomplete objects just buffer more input.
    """
    buf = b""
    while True:
        start = buf.find(b"{")
        if start != -1:
            try:
                obj, end = decoder.raw_decode(buf[start:].decode("utf-8", "replace"))
            except ValueError:
                pass                            # incomplete object: buffer more
            else:
                yield obj
                buf = buf[start + end:]
                continue
        chunk = stream.read(65536)
        if not chunk:
            return
        if start != -1:
            buf = buf[start:]                   # drop the separator/whitespace junk
        buf += chunk


def fetch_matches(state_dir):
    """Stream the public node list; return (hits dict, scanned, xfer_bytes)."""
    want = wanted_prefixes(state_dir)
    req = urllib.request.Request(MAP_URL, headers={
        "Accept-Encoding": "gzip", "User-Agent": UA})
    hits, scanned, xfer = {}, 0, 0
    decoder = json.JSONDecoder()
    with urllib.request.urlopen(req, timeout=60) as resp:
        xfer = int(resp.headers.get("Content-Length") or 0)
        raw = resp
        if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
            raw = gzip.GzipFile(fileobj=resp)
        for node in iter_objects(raw, decoder):
            scanned += 1
            pk = node.get("public_key") if isinstance(node, dict) else None
            if isinstance(pk, str) and len(pk) == 64:
                pref = pk[:8].upper()
                if not want or pref in want:
                    hits[pref] = pk.lower()
    return hits, scanned, xfer


def merge_existing(state_dir, new_hits):
    path = os.path.join(state_dir, KEYS_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            old = json.load(f)
        if isinstance(old, dict):
            merged = {str(k).upper(): str(v).lower() for k, v in old.items()}
            merged.update(new_hits)
            return merged
    except (OSError, ValueError):
        pass
    return dict(new_hits)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    ap.add_argument("--status-only", metavar="RESULT",
                    help="only write keymap-status.json (RESULT: OK/SKIPPED/FAIL)")
    ap.add_argument("--detail", default="")
    args = ap.parse_args()
    started = time.time()
    os.makedirs(args.state_dir, exist_ok=True)

    if args.status_only:
        write_status(args.state_dir, args.status_only.upper(),
                     args.detail or "no detail", started)
        return 0

    try:
        hits, scanned, xfer = fetch_matches(args.state_dir)
        merged = merge_existing(args.state_dir, hits)
        out = os.path.join(args.state_dir, KEYS_FILE)
        write_json_atomic(out, merged)
        size = os.path.getsize(out)
        detail = (f"{scanned} nodes scanned, {len(merged)} keys stored, "
                  f"{xfer / 1e6:.1f} MB transfer, file {size / 1024:.1f} KB")
        write_status(args.state_dir, "OK", detail, started, file_bytes=size)
        log("OK: " + detail)
        return 0
    except Exception as e:                       # noqa: BLE001 - report, never crash silently
        detail = f"{type(e).__name__}: {e}"
        write_status(args.state_dir, "FAIL", detail, started)
        log("FAIL: " + detail)
        return 1


if __name__ == "__main__":
    sys.exit(main())
