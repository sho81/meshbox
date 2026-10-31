# Changelog

## 2026-10-31 — initial public release

Feature history of the DK0MAV mc2-Peine-Node box (developed incrementally, F1–F19):

- Neighbor table over the MeshCore serial console: merged all-nodes-ever list
  (key prefix, name, last seen, live/best/worst SNR, sightings), persistent
  history across reboots, sortable pre-sorted tables with live-ticking timestamps.
- Serial port discovery and role classification (MeshCore repeater vs. MeshCom),
  robust against USB port swaps (persisted mapping, stale flags, per-port flocks).
- USB device watchdog: ONLINE/OFFLINE state machine for tracked peripherals,
  pure `/sys` enumeration, survives reboots.
- Storage section: all persistent physical disks (`sd*`, `mmcblk*`, `hd*`, NVMe)
  with df-style total/used/available/% and mount points, per-disk partition summing.
- Clock & NTP: repeater clock auto-sync over serial when lagging, MeshCom RTC
  reporting, Pi NTP state, browser `/settime` emergency clock button.
- PiUPS+ power section parsed from the daemon's debug log tail (zero extra I²C
  traffic); live log on tmpfs with a compact forensic copy relayed to a USB stick
  (~98 % write traffic cut); uptime line ("Started … ago") above the updated stamp.
