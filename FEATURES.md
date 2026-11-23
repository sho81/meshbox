# Feature history (F1–F32)

F-numbers are stable internal change IDs. They appear in engine comments
(e.g. "F16 moves the live log to tmpfs") and in test file names
(`test-f18.py`, `test-f19.py`, `test-f21.py` — each suite regression-covers
its feature plus the earlier ones). The pre-F18 base is covered by
`test-core.py` (F1/F4/F7/F8/F11/F12) and `test-services.py` (F13/F16);
F2/F5/F14/F15/F17 have no suite of their own (config/process or behaviors
already implied by the render checks). Dates are deploy dates on the DK0MAV
mc²-Peine-Node box.

## F1–F2 · Baseline engine — before 2026-10-10

First `mesh-neighbors.py`: probe the MeshCore repeater over its serial
console every minute and publish the neighbor page. Pre-dates this feature
log; the engine backup chain starts at `.bak-20261010-f2`.

## F3 · Sortable neighbor table — 2026-10-10

Key-prefix column first, node name second; sortable table headers, third
click restores device order.

## F4 · All-nodes-ever history — 2026-10-10

State file `/var/lib/meshcore/nodes-ever.json`: first/last seen, sightings,
best/worst SNR per node. Grows every run, survives reboots.

## F5 · Mirror discipline (process, no engine change) — 2026-10-10

Deployed files are mirrored to an operator workspace (this repo is the
published, scrubbed copy); the box stays authoritative. Kept in the list so
the F-sequence stays complete.

## F6 · USB port table from OS + serial — 2026-10-10

Every `/dev/ttyUSB*` probed and classified (MeshCore repeater vs. MeshCom)
using OS enumeration plus one serial command per port, shown with a role
column.

## F7 · Port-swap robustness — 2026-10-10

Persisted port→role mapping (`ports.json`): an unresponsive port falls back
to its saved role and is flagged stale, so a USB cable/adapter swap never
breaks the page.

## F8 · Clock auto-sync + NTP status — 2026-10-10

The repeater's clock is corrected over serial when it lags the Pi by more
than `CLOCK_SYNC_LAG_S` (120 s); an NTP status row reports the Pi's own sync
state.

## F9 · Merged nodes table + layout — 2026-10-10

One merged table — every node ever heard enriched with the live run: key
prefix, name, last seen (d/h/m), live SNR, best/worst SNR, sightings; the
separate "all nodes ever heard" table was dropped. Clock & NTP lists both
ports. Landing page widened, ASCII banner on one line.

## F10 · Pre-sorted tables, HTML-only output — 2026-10-10

All tables load pre-sorted with visible sort indicators (faint ↕ inactive,
bright ▲/▼ active). The old `meshcore.txt` companion output was removed —
the HTML page is the only published output.

## F11 · PiUPS+ / Power section — 2026-10-10

UPS status line (primary/secondary power, battery state + raw bits, button)
and a sortable table of the five traced readings (`U_Bat`, `I_Rasp`,
`U_USB`, `U_USV`, `U_Ext`) with unit conversion and per-field last-update
times. Parsed by tailing the piupsmonitor daemon's debug log — zero extra
I²C traffic. Red "daemon down?" marker when the data is older than 90 s
(`PIUPS_STALE_S`).

## F12 · USB device watchdog — 2026-10-11

ONLINE/OFFLINE state machine for every tracked peripheral (serial bridges,
storage sticks): status, humanized status age, last confirmed. Identity key
is `vendor:product[:serial]:port path`; pure `/sys` enumeration, state
survives reboots (`usb-state.json`). Catches a stick that silently vanished.

## F13 · Clock & NTP everywhere + emergency time sync — 2026-10-11

Section always rendered; the Pi's system clock is the first row and the
reference for all deltas. A "set system time from your device" button POSTs
the visitor's browser clock to `/settime`, which nginx proxies to a loopback
service (`mesh-time-sync.py`, ch. in README) that sets `CLOCK_REALTIME` —
an emergency path for cold boots without NTP. Unauthenticated by design:
keep it on a trusted segment. (Superseded by F24: the button became a
per-row "set from your device", now covering the serial devices too.)

## F14 · Section order — 2026-10-11

The power section moved to the last section of the page (neighbors →
USB serial devices → watchdog → Clock & NTP → PiUPS+ / Power).

## F15 · UPS debug log off the SD card — 2026-10-11

The daemon's full debug log (~1 GB/day of writes) moved to a dedicated
ext4 USB stick mounted by UUID, so flash wear hits a cheap disposable stick
instead of the boot card.

## F16 · Log write traffic cut ≈98 % — 2026-10-11

The live debug log now lives on tmpfs (`/run/piupsmonitor/live.log`); a
small relay service (`piups-log-relay.py`) appends a verbatim, compact
subset (status changes + a reading snapshot every 5 s, plus excursions) to
the stick — ~100–150 B/s instead of ~13.5 KB/s. The engine reads the RAM
log, so page values are ≤ ~1 s old and the stick file is the forensic copy.

## F17 · Full date in power update cells — 2026-10-26

Per-field "Last update (UTC)" cells render `YYYY-MM-DD HH:MM:SS` instead of
time-only; sorting (by epoch) and tooltips unchanged.

## F18 · "Started" uptime line — 2026-10-26

Above "Updated": `Started <boot time UTC> (<uptime> ago)`, boot time derived
from `/proc/uptime` (fallback `/proc/stat btime`), omitted rather than wrong
when unreadable. The JS humanizer gained a days tier (`14 d 2 h`).
Regression suite: `test-f18.py` (19 checks, incl. current section order).

## F19 · Storage section — 2026-10-26

Every persistent physical storage disk — USB/SCSI sticks (`sd*`), the boot
SD card (`mmcblk*`), `hd*`/NVMe if present; virtual devices (`zram`, `loop`)
excluded. Columns: device, total size (sysfs), used, available, %, mount
points; usage uses df semantics summed over all partitions of a disk
(handles both `sdb1` and `mmcblk0p1` naming). The watchdog's Details column
was slimmed to the bare block name so watchdog rows map 1:1 onto storage
rows. Section sits between the watchdog and Clock & NTP. Regression suite:
`test-f19.py` (40 checks, synthetic `/sys` tree).

## F20 · CONFIG block — 2026-10-31 (refactor, no behavior change)

All operator-tunable constants gathered into one clearly marked CONFIG block
right after the imports: station identity, serial probe, output paths,
state dir (renamed `NODES_EVER_DIR` → `STATE_DIR`), clock-sync threshold,
power-log tunables (new `PIUPS_STALE_S` replaces a magic 90).

## F21 · Station identity line — 2026-10-31

Config constants `MESHCORE_FREQ`, `MESHCOM_NAME`, `MESHCOM_FREQ`; the
generated page's header now shows the full station identity (MeshCore
repeater name + 869.618 MHz, MeshCom unit name + 433.175 MHz), and a
"MeshCore Neighbors" section heading precedes the table like all other
sections. Regression suite: `test-f21.py` (9 checks).

## F22 · Atomic page publish — 2026-11-02

`neighbors.html` is no longer written in place: the engine writes a sibling
`neighbors.html.tmp` and `os.replace()`s it into position (same pattern as
the state files), so a browser refreshing mid-write can never catch a
half-written page. The tmp file inherits the target's mode. This needs
directory write access, so on the box `/var/www/html` is group-writable
(`root:www-data 2775`, setgid) and the engine user is in `www-data`.
Regression suite: `test-f22.py` (5 checks).

## F23 · Log sanitizing — 2026-11-02

The engine's `log()` passes every message through `_sanitize()`: only
printable ASCII reaches the cron log (control chars, NUL and DEL become
`?`; embedded newlines cannot forge extra log lines). This keeps
grep/less/operational queries working on the whole log file — two
historical NUL holes (reboot artifacts, not serial data) had made the
7.8 MB log "binary" for grep; they were scrubbed once at deploy time.
The log now also rotates monthly (`deploy/logrotate-d-mesh-neighbors`:
rotate 6, compress, copytruncate). Regression suite: `test-f23.py`
(5 checks).

## F24 · Manual per-row time sync — 2026-11-06

The F13 "emergency time sync" became **manual time sync**, and the single
button under the Clock & NTP table was cloned into every row. The table grew
a dedicated fifth column "Manual sync" (buttons aligned in one vertical
line; the local-time row shows `—` there). Its flat black/green
"set from your device" buttons (`.tbtn`) send the browser's epoch plus that
row's target to `/settime`.

- Pi row: unchanged path — `clock_settime` right away.
- `/dev/ttyUSB*` rows: the service writes a one-shot marker
  (`/var/lib/meshcore/settime-request.json`, atomic tmp+rename) and answers
  `{"queued": true}`. The engine's next cron run consumes it: it re-probes
  the port anyway, so the role decision (MeshCore 869 MHz vs MeshCom
  433 MHz) uses the fresh live classification with the persisted `ports.json`
  fallback (F7) — robust against USB renumbering. Under the normal per-port
  flock it sends `time <epoch>` (MeshCore) or `--settime yyyy.mm.dd hh:mm:ss`
  in device-local time (MeshCom, UTC + UTC-OFF), then re-reads the clock
  ("clock" / "--pos") and shows "manual sync verified (Δ …)" in that row.
- New last row "local device time (this browser)": the visitor's own clock,
  live to the second via the ticker script — the source every button sends,
  so it has no button itself.
- The Pi system row is pinned to the top of the table at every sort order
  (`data-pin` handling in `SORT_JS`).
- A measured Δ of exactly 0 renders as `0s` (ports with no readable clock
  still show `—`).

The automatic lag sync (F8, MeshCore lag > `CLOCK_SYNC_LAG_S`) is unchanged;
a manual request just suppresses it for that one run. Regression suite:
`test-f24.py` (17 checks).

## F25 · Temperatures table — 2026-11-06

Sensor survey on the box first: the Pi 3 B+ has exactly **one** physical thermal
sensor — the SoC thermal zone (`/sys/class/thermal/thermal_zone0`, mirrored as
hwmon `cpu_thermal`). `vcgencmd measure_temp` and every `-m cpu|core|gpu|soc|pmu`
variant read that same sensor through the GPU mailbox (measured identical on the
box), `rpi_volt` is a voltage hwmon, and there are no 1-wire devices, no
`/sys/class/power_supply` entries and no temperature in the PiUPS+ data. So the
new **Temperatures** section shows a single row.

- Table `Source | Now | Abs min (UTC) | Abs max (UTC)`, everything in °C,
  sortable like all others; the min/max cells carry the recorded date+time
  under the number (`data-sort` keeps the columns numeric).
- Positioned after Clock & NTP, before PiUPS+ / Power (operator's choice).
- Reader: kernel thermal sysfs (millidegrees) first, `vcgencmd measure_temp`
  as fallback when no zone is readable; sane range −50…150 °C only.
- Absolute min/max are **permanent across reboots**, sampled every cron
  minute and stored in `/var/lib/meshcore/temps-ever.json` (same pattern as
  the nodes-ever / usb-state files); the file is rewritten only when an
  extreme actually changes, and deleting it resets the history.
- Future hardware with more zones gets its own rows automatically
  (`cpu-thermal` → "SoC", `gpu-thermal` → "GPU"; unknown zone types keep
  their kernel name).

Regression suite: `test-f25.py` (19 checks).

## F26 · Network interfaces table — 2026-11-21

"How do I connect to this box right now?" — a live snapshot of every
interface (operator's spec: one row per interface, IPv4 + IPv6, positioned
after the USB watchdog and before Storage).

- Source is iproute2 JSON (`ip -j addr show` + `ip -j route show`, one
  read each per run — same subprocess style as the timedatectl/vcgencmd
  reads). Two iproute2 JSON dialects are handled: MAC under `mac` or
  `address`, default route as `dst "default"` or omitted/null, protocol
  key `proto` or `protocol`, lease seconds under `valid_lft` or
  `valid_life_time` (iproute2 6.15 on the box omits them in plain JSON —
  then dynamic addresses just show `dynamic`).
- `lo` is dropped; any other interface (AP mode, tunnels, future add-ons)
  appears automatically. State comes from the `UP`/`LOWER_UP` flags
  (`UP` / `up, no carrier` / `DOWN`).
- Table `Interface | State | MAC | IPv4 | IPv6`; extra addresses stack
  inside a cell. IPv6 gets scope labels: **global** (2001::-style),
  **ULA** (fd/fc), **link** (fe80::). Dynamic addresses show their lease
  remainder ("lease 42 m 06 s") when the JSON carries one — the box's
  public IPv6 rotates every ~40 min, so this table is where you read the
  current one.
- The interface holding the default route (lowest metric) is tagged in
  its name cell; the footer shows the default gateway + source address
  and the grouped static routes — the Hamnet referrals get a
  `(Hamnet)` tag: `44.0.0.0/9, 44.128.0.0/10 via 192.168.3.1 dev eth0`.
- No state file by design: interface *history* is the USB watchdog's
  (F12) job; this section answers the question for right now.
- The cron ok-line grew a `net eth0=UP/192.168.3.10 wlan0=UP/…` tag.

Regression suite: `test-f26.py` (18 checks, both iproute2 dialects).

## F27 · Per-box overlay config — second-box rollout — 2026-11-23

The engine moved to the second station by config only — same code file, no
fork. `box-config.json` next to the script (same placement pattern as
`mesh-node-names.json`) optionally overrides: page `<title>`, the `<h2>`
station prefix, the four identity strings (MeshCore node name + QRG, MeshCom
unit name + QRG), `ports_glob` (e.g. `/dev/ttyACM*` for ESP32/CH340 CDC-ACM
adapters) and `www_dir`. Every key is optional and absent means the original
box's values — so the first deployment needs no file at all and its rendered
page stays byte-identical.

- The sysfs tty glob used by the USB tables/watchdog follows the configured
  serial family automatically (`ttyACM*` ports → `ttyACM*` in `/sys/class/tty`).
- F24's manual time-sync target validation (engine AND service) now accepts
  `ttyACM` ports next to `ttyUSB`.
- Config files are inserted verbatim into `<title>`/`<h2>` — authors keep
  them HTML-safe. Broken JSON or wrong shapes are ignored with a warning.
- Identity/branding values are deployment-private: they live on each box;
  the repo ships only placeholder examples in `deploy/` (see `deploy/README.md`).

Regression suite: `test-f27.py` (11 checks: defaults preserved, full/partial
overlay, broken config, ttyACM targets both sides, rendered page overlay).

## F28 · Nodes table opens sorted by "Last seen" — 2026-11-23

The merged nodes table's initial sort (what you see before any click) is now
**Last seen ascending = freshest first**, matching the order the engine
already writes the rows in server-side. The little ▲ indicator sits on that
column from the start; click behavior is unchanged (asc → desc → device
order, and "device order" now *is* freshest-first too). Every other table
keeps its first-column initial sort.

Regression suite: `test-f28.py` (3 checks).

## F29 · Manual node names inside the box config — 2026-11-23

Manual key-prefix → display-name resolution (until then only
`mesh-node-names.json` next to the script) is now also an **optional part of
`box-config.json`**: a `node_names` object maps 8-hex key prefixes to names.
The two maps are merged at load time, config entries winning over file
entries; either one alone works. Keys are normalized upper-case, malformed
shapes are ignored. Useful because many node names are public data (e.g.
from map.meshcore.io) while your local overrides stay on the box.

Regression suite: `test-f29.py` (8 checks: defaults, config-only, merge
precedence, key normalization, broken shapes, no F27 regression).

## F30 · Signal stairs in the live SNR column — 2026-11-23

Every live SNR reading now carries an 8-step **signal staircase** next to
the dB number: the full set of Unicode block glyphs `▁▂▃▄▅▆▇█`
(U+2581–U+2588) stands ascending in the cell; steps reached by the signal
are colored (same green/yellow/red bands as before), the remaining steps
are dim gray. Scale: −20 dB (roughly the SF12 decode floor) to +8 dB
(saturated link), 7 equal 4 dB steps, so full stairs at ≥ +8 dB and no
lit step below −20. The scale is box-overridable via optional
`bar_min`/`bar_max` numbers in `box-config.json`. The dB number, the
sort values and the Best/Worst history columns are untouched; rows
without a live value still show a plain "-".

Regression suite: `test-f30.py` (8 checks: glyph set, level mapping at
every boundary, overlay scale, bogus shapes, cell markup, untouched
best/worst).

## F31 · Node names deep-link to map.meshcore.io — 2026-11-23

Node names are links to the official MeshCore map
(`https://map.meshcore.io/?public_key=<full key>`, new tab) — but only for
nodes whose FULL 64-hex public key is known locally. The dashboard engine
only sees 8-hex key prefixes, and the map's API has no prefix query (its
frontend opens popups for full keys only), so a local key map
`/var/lib/meshcore/mesh-keys.json` (prefix → full key) does the join.
Nodes never published on the map keep their names as plain text — their
identifiers are never invented or sent anywhere.

`mesh-keymap.py` (new companion script) refreshes that map: it streams the
map's public node list (no partial query exists, so it is the full list —
~19 MB gzipped), keeps only prefixes seen in nodes-ever.json and writes
`mesh-keys.json` plus `keymap-status.json` (last run: OK / SKIPPED / FAIL +
detail incl. transfer and file size). Triggers: the dashboard button
"⟳ Update node lookup data" (confirm dialog warns about the 19 MB; the
time-sync service gained a `POST /keymap-update` route with single-flight
and a 15-minute cooldown — refusals also land in the status file) or a
manual `mesh-keymap.py` run. Below the neighbors table the page shows
"Last node lookup: <UTC> — OK (73815 nodes scanned, 8 keys stored,
19.1 MB transfer, file 0.6 KB)". Optional box-config key `node_link_url`
customizes the link template (""/false = links off).

Regression suite: `test-f31.py` (17 checks: key-map loading/normalization,
link templates incl. overlay off/custom, name-cell markup with escaping,
lookup-label states, table integration, helper status-only CLI, streaming
gzip parse against a local fixture). `test-services.py` t10 covers the
route: spawn, 409 single-flight, 429 cooldown, SKIPPED status write.

## F32 · MeshCom Neighbors table — 2026-11-23

A second neighbors table for the MeshCom (433 cm) side, right below the
MeshCore one: Station · Last heard · live SNR (stairs) · Best/Worst SNR ·
Sightings, sortable, newest first, `GW` badge for stations that answered
as gateway. Source is the MeshCom console command `--mheard` (firmware
4.40a answers `[MH] call=... snr=... age=... gw=Y` key=value lines; older
firmware yields an empty table instead of failing). The device only keeps
a 12 h window and forgets on reboot, so the engine mirrors its own
all-stations-ever state in `meshcom-nodes-ever.json` (first/last heard,
sighting count without double-counting the same heard event, best/worst
SNR) — same pattern as nodes-ever.json on the MeshCore side. The live SNR
column comes from this run's reply; stations older than that show "-".
Note: `--mheard` lists directly RF-heard stations only — mesh-relayed
traffic does not appear.

Regression suite: `test-f32.py` (18 checks: --mheard parsing incl. units
and garbage, ever-state merge/dedup/gw stickiness, table markup and
ordering, section gating, sort init). `test-f21.py`/`test-f28.py` adapted
to the new template slot and sort init.
