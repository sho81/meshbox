# deploy/ — wiring files & multi-box operation

One engine file (`mesh-neighbors.py`) serves any number of boxes. Every box
is just an instance: the first box needs no extra files at all (its values
are the engine defaults), each further box is created **by config only** —
no fork, no per-box directory in this repo. Everything box-specific lives in
files **next to the script on the box**, none of it in git:

| File (on the box, next to the engine) | Purpose |
| --- | --- |
| `box-config.json` | page title, station header, the four identity strings, serial family (`ports_glob`), output dir, SNR-stairs scale (`bar_min`/`bar_max`, defaults −20/+8 dB), and optional `node_names` (key prefix -> display name, merged over the name file below). See `box-config.example.json` — every key optional, absent = engine defaults |
| `mesh-node-names.json` | node id -> display name map (shape: `mesh-node-names.example.json`); optional when all names live in `box-config.json` |

## Checklist for a new box

1. Install `mesh-neighbors.py` + `box-config.json` + `mesh-node-names.json`
   in `/usr/local/bin/`, cron one line (system python3 is enough when
   pyserial is packaged):
   `* * * * * /usr/bin/python3 /usr/local/bin/mesh-neighbors.py >>/var/log/mesh-neighbors.log 2>&1`
2. CDC-ACM adapters (ESP32/CH340 boards): set `"ports_glob": "/dev/ttyACM*"` —
   the USB tables/watchdog and the F24 time-sync targets follow automatically.
3. Serve the page from its own dir (`"www_dir"`, e.g. `/var/www/mesh`) so an
   existing web app keeps the document root. Web examples in this folder:
   `nginx-sites-enabled-default.conf` (nginx) and
   `lighttpd-mesh-dashboard.conf` (lighttpd: alias + `/settime` proxy,
   needs `lighty-enable-mod proxy`).
4. Optional: `mesh-time-sync.service` + the `/settime` proxy enable the
   browser-driven "set this clock" buttons (loopback service on 8090).
5. The embedding `index.html` is per-box (title/header/ASCII art = branding).
   The ASCII art block is optional — omit the `<pre>` block when there is none.

Identity/branding strings (callsigns, station names, QRGs) stay on the box;
this repo only carries the mechanism and these placeholders.

## Name resolution + privacy

The nodes table shows a display name per node — the **first 8 hex digits of
the node's public key** are the lookup key. Two box-local sources, both
optional, merged at render time (F29: box-config wins):

1. `mesh-node-names.json` next to the engine — a flat JSON object,
   `{ "<KEY8>": "<Display Name>" }` (shape: `mesh-node-names.example.json`)
2. `node_names` object inside `box-config.json` — same shape, overrides
   entries of the file

Where names come from: the official MeshCore internet map publishes every
uploaded node advert. Browsing: <https://map.meshcore.io/> (search accepts a
key prefix; the node popup shows name + full key). Machine readable:

```
GET https://map.meshcore.io/api/v1/nodes
```

A JSON array (~75k entries); relevant fields: `public_key` (hex string —
prefix-match the first 8 digits, case-insensitive), `adv_name` (advertised
name), `type` (0 client, 1 repeater, 2 room server, 3 sensor). Example —
resolve a handful of prefixes seen in your dashboard:

```bash
curl -s https://map.meshcore.io/api/v1/nodes | python3 - <<'PY'
import json, sys
want = {"AABBCCDD", "11223344"}          # your key prefixes, upper case
for n in json.load(sys.stdin):
    if n["public_key"][:8].upper() in want:
        print(n["public_key"][:8].upper(), "->", repr(n.get("adv_name")))
PY
```

Caveats: advertised names may contain emoji; nodes can rename or re-key
(same site, new prefix); plenty of private nodes are never uploaded, so
their names stay your own manual entries.

**Privacy rule: a filled-in name map is personal data** (callsigns, site
names). It lives on the box only — never commit it; this repo ships nothing
but placeholder examples.
