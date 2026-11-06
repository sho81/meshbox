# meshbox — live dashboard for a MeshCore repeater on a Raspberry Pi

Self-contained web dashboard for a [MeshCore](https://github.com/meshcore-dev/MeshCore)
amateur-radio repeater ("meshbox") on a Raspberry Pi: a cron job probes the repeater
over its serial console every minute and publishes a static, auto-refreshing HTML page
with everything you want to know about the box and its RF neighbourhood — one Python
file, only `pyserial`, no database, no JavaScript dependencies.

Built for the **DK0MAV mc²-Peine-Node** (869.618 MHz repeater + MeshCom unit on one
Raspi), but the engine only needs a MeshCore repeater on a serial port and a handful
of paths you can adapt.

## What the page shows

| Section | Content |
|---|---|
| **Neighbors** | merged table of every node ever heard: key prefix, name, last seen (d/h/m), live SNR, best/worst SNR, sightings. All-nodes-ever history survives reboots via a small JSON state file |
| **USB serial devices** | every `/dev/ttyUSB*` probed and classified (MeshCore repeater vs. MeshCom) using OS info + one serial command per port; survives USB port swaps |
| **USB device watchdog** | ONLINE/OFFLINE state machine for every tracked peripheral (serial bridges, storage sticks) driven purely from `/sys` enumeration — catches a stick that silently disappeared, even across reboots |
| **Storage** | every persistent physical disk (`sd*`, `mmcblk*`, `hd*`, NVMe; zram/loop excluded): total size, used, available, %, mount points — df semantics summed per disk |
| **Clock & NTP** | device clocks of the repeater (auto-syncs the repeater when it lags) and the MeshCom GPS/RTC unit, plus the Pi's own NTP state and your browser's clock; a per-row button can manually set any clock (Pi or attached device) from the browser via `/settime` |
| **PiUPS+ / Power** | UPS status bits + five traced electrical readings, parsed from the piupsmonitor daemon's debug log tail — zero extra I²C traffic |

All tables are sortable (third click restores device order) and pre-sorted with visible
sort indicators; timestamps tick live in the browser. The features carry stable internal
change IDs (F1–F21) which also appear in engine comments and test file names — decoded
in [FEATURES.md](FEATURES.md).

## Layout

```
mesh-neighbors.py        the engine: probe -> state -> HTML (run every minute by cron)
mesh-time-sync.py        tiny loopback HTTP service for the /settime emergency clock button
piups-log-relay.py       tails the RAM debug log, writes a compact forensic copy to a USB stick
tools/                   small helper scripts (meshcli console wrappers, apt update, temps)
deploy/                  systemd units, nginx snippet, crontab, tmpfiles, logrotate, fstab,
                         piupsmonitor.conf, node-name map example
web/index.html           the landing page embedding neighbors.html
tests/                   dependency-free test suites (synthetic fixtures, no hardware needed)
requirements.txt         venv top-level pins (meshcore-cli, esptool; engine needs pyserial)
```

## How it works

Every minute cron runs `tools/meshcli-neighbors.sh`, which invokes the engine. The
engine probes **all** `/dev/ttyUSB*` ports under per-port flocks (so an interactive
console on one port never blocks the other), wakes each with a bare CR and classifies:

- answer to `neighbors` → MeshCore repeater. Reply format
  `{pubkey-prefix}:{secs_ago}:{snr*4}`, max 8 entries (see MeshCore firmware,
  `examples/simple_repeater/MyMesh.cpp::formatNeighborsReply`).
- answer to `--info` with a parseable MeshCom block → MeshCom unit.

Plus `clock`/`--pos`/`get name`/`ver` queries, OS-level USB enumeration and a state
machine in `/var/lib/meshcore/*.json` (atomic writes). The rendered page is written to
`/var/www/html/neighbors.html` and embedded into the landing page.

## Setup (short version)

1. Python venv with `meshcore-cli` (provides `meshcli` + `pyserial`): see `requirements.txt`.
2. Adapt the constants near the top of `mesh-neighbors.py` (node name, frequency,
   paths) and drop a `mesh-node-names.json` next to the engine
   (start from `deploy/mesh-node-names.example.json`).
3. Install the pieces from `deploy/`: cron line, systemd units (time-sync service,
   log relay), nginx `location = /settime` proxy, tmpfiles/logrotate for the UPS log.
4. Make sure the output file exists and is writable by the cron user; the engine
   rewrites it in place each run.

### Note on `/settime`

The emergency clock endpoint is bound to `127.0.0.1:8090` and only reachable through
the nginx proxy; it validates the value (epoch seconds, sane range) but is **not
authenticated** — keep it on a trusted LAN/hamnet segment or add auth yourself.

## Tests

The suites in `tests/` run anywhere (pure stdlib, synthetic `/sys` and log fixtures,
no repeater needed; `node` is used for one JS harness). `test-core.py` covers the
foundational behaviors (F1/F4/F7/F8/F11/F12), `test-services.py` the two companion
daemons (F13/F16), the `test-fNN.py` suites their feature plus the earlier ones:

```
python3 tests/test-core.py mesh-neighbors.py
python3 tests/test-services.py mesh-time-sync.py piups-log-relay.py
python3 tests/test-f18.py mesh-neighbors.py
python3 tests/test-f19.py mesh-neighbors.py
python3 tests/test-f21.py mesh-neighbors.py web/index.html
python3 tests/test-f22.py mesh-neighbors.py
python3 tests/test-f23.py mesh-neighbors.py
python3 tests/test-f24.py mesh-neighbors.py mesh-time-sync.py
```

All suites run on every push via GitHub Actions (`.github/workflows/test.yml`).

## License

MIT — see [LICENSE](LICENSE). Protocol behaviour documented after the MeshCore
firmware (MIT, meshcore-dev). This project is unaffiliated; DK0MAV is a licensed
amateur station call sign.
