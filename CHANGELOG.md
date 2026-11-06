# Changelog

Deploy log by date. Feature-by-feature documentation lives in
[FEATURES.md](FEATURES.md); the F-numbers there are the same IDs you find in
engine comments and test file names.

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
