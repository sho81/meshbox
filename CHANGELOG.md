# Changelog

Deploy log by date. Feature-by-feature documentation lives in
[FEATURES.md](FEATURES.md); the F-numbers there are the same IDs you find in
engine comments and test file names.

## 2026-11-23

- F27: **per-box overlay config** — optional `box-config.json` next to the
  engine overrides title, station identity strings, `ports_glob` (ttyACM
  serial family works end-to-end now, incl. F24 settime targets) and
  `www_dir`; defaults unchanged, so the first box needs no file and its
  page stays byte-identical. `deploy/README.md` documents a config-only
  re-brand deployment; new `tests/test-f27.py`
- F28: **nodes table initial sort = Last seen** (freshest first, indicator
  arrow included); other tables keep their initial sort; new `tests/test-f28.py`
- F29: **node_names inside box-config.json** — manual key-prefix → name map
  merged over mesh-node-names.json (config wins; file optional); new
  `tests/test-f29.py`. Name-resolution how-to (public map.meshcore.io API)
  documented in `deploy/README.md`; example name map switched to
  fictitious key prefixes (privacy)
- F30: **signal stairs** — 8-step Unicode staircase (▁..█) visualizes each
  live SNR (scale −20..+8 dB, per-box `bar_min`/`bar_max`), dB number and
  Best/Worst columns untouched; new `tests/test-f30.py`
- F31: **map.meshcore.io deep links** — node names link to the official map
  when the full public key is known locally (`mesh-keys.json`, prefix→key);
  `mesh-keymap.py` refreshes it from the public map list (~19 MB gzipped,
  streamed), dashboard button + `/keymap-update` service route (single-flight,
  15 min cooldown) + "Last node lookup" status label; optional `node_link_url`;
  new `tests/test-f31.py`

## 2026-11-21

- F26: **Network interfaces section** — one row per interface (lo omitted):
  state, MAC, all IPv4/IPv6 addresses with scope labels and lease hints,
  default-route tag + gateway footer, Hamnet static routes as footer line;
  sourced from `ip -j addr show`/`ip -j route show` (two iproute2 JSON
  dialects handled); new `tests/test-f26.py`

## 2026-11-06

- F24: manual time sync redesign — "set from your device" button in every
  Clock & NTP row (flat black/green `.tbtn`); serial targets queue a marker
  that the engine applies+verifies on the next run (`time <epoch>` on
  MeshCore, `--settime` in device-local time on MeshCom); new "local device
  time" row; Pi row pinned first at every sort; Δ 0 renders `0s`;
  new `tests/test-f24.py`
- F25: **Temperatures section** — one row per thermal source (single SoC
  sensor on the Pi 3 B+), current reading + permanent absolute min/max with
  date+time (UTC) in `temps-ever.json`; sysfs-first with `vcgencmd`
  fallback; new `tests/test-f25.py`

## 2026-11-02

- F22: atomic publish of `neighbors.html` (tmp + `os.replace`); new `tests/test-f22.py`
- F23: `log()` sanitizing (printable ASCII only) + monthly log rotation
  (`deploy/logrotate-d-mesh-neighbors`); new `tests/test-f23.py`
- Tests: `test-core.py` backfills regression coverage for the pre-F18 features
  (F1/F4/F7/F8/F11/F12), `test-services.py` covers the companion daemons
  (F13/F16); GitHub Actions runs all 7 suites on every push

## 2026-10-31

- F20: CONFIG block (refactor, no behavior change)
- F21: station identity line + "MeshCore Neighbors" heading; new `tests/test-f21.py`

## 2026-10-26

- F17: full date in the power table's update cells
- F18: "Started" uptime line; `tests/test-f18.py`
- F19: Storage section (all persistent disks); `tests/test-f19.py`

## 2026-10-11

- F12: USB device watchdog
- F13: Clock & NTP always shown + emergency `/settime` time sync
- F14: section order (power last)
- F15: UPS debug log moved to a USB stick
- F16: tmpfs live log + `piups-log-relay` (≈98 % less stick writes)

## 2026-10-10 — initial dashboard (F1–F11)

- Baseline engine, sortable neighbor table, all-nodes-ever history, port
  role classification + swap robustness, clock auto-sync, merged nodes
  table, pre-sorted tables, PiUPS+ / Power section
