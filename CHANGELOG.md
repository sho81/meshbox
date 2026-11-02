# Changelog

Deploy log by date. Feature-by-feature documentation lives in
[FEATURES.md](FEATURES.md); the F-numbers there are the same IDs you find in
engine comments and test file names.

## 2026-11-02

- F22: atomic publish of `neighbors.html` (tmp + `os.replace`); new `tests/test-f22.py`

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
