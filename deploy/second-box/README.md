# Second box: one engine, config-only re-brand (F27)

The same `mesh-neighbors.py` serves several boxes. Everything box-specific
lives in files **next to the script**, none of it in git:

| File | Purpose |
| --- | --- |
| `box-config.json` | page title, station header, the four identity strings, serial family (`ports_glob`), output dir. See `box-config.example.json` — keys are optional, absent = first box's defaults |
| `mesh-node-names.json` | node id -> display name map (start from `deploy/mesh-node-names.example.json`) |

## Checklist for a new box

1. Install `mesh-neighbors.py` + `box-config.json` + `mesh-node-names.json`
   in `/usr/local/bin/`, cron one line (system python3 is enough when
   pyserial is packaged):
   `* * * * * /usr/bin/python3 /usr/local/bin/mesh-neighbors.py >>/var/log/mesh-neighbors.log 2>&1`
2. CDC-ACM adapters (ESP32/CH340 boards): set `"ports_glob": "/dev/ttyACM*"` —
   the USB tables/watchdog and the F24 time-sync targets follow automatically.
3. Serve the page from its own dir (`"www_dir"`, e.g. `/var/www/mesh`) so an
   existing web app keeps the document root. lighttpd example:
   `lighttpd-mesh-dashboard.conf` (alias + `/settime` proxy for optional manual
   clock setting; needs `lighty-enable-mod proxy`).
4. Optional: `deploy/mesh-time-sync.service` + the `/settime` proxy enable the
   browser-driven "set this clock" buttons (loopback service on 8090).
5. The embedding `index.html` is per-box (title/header/ASCII art = branding).
   The ASCII art block is optional — omit the `<pre>` block when there is none.

Identity/branding strings (callsigns, station names, QRGs) stay on the box;
this repo only carries the mechanism and these placeholders.
