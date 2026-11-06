# Feature history (F1–F24)

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
`test-f24.py` (16 checks).
