#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""F19 checks — "Storage" section between "USB device watchdog" and "Clock & NTP".

Run:  python3 test-f19.py [engine-path]     (default: ./mesh-neighbors.py)

Covers:
  t1  storage_info on a synthetic /sys/block + /proc/mounts tree: all physical
      disks (sd*, mmcblk0 boot card, nvme) with virtual zram/loop excluded; total
      size from the sysfs size file; df-style used/avail/pct summed over all mounted
      partitions of a disk (multi-mount sdb + p-partition mmcblk0); mount attribution
  t2  unmounted disk -> None stats; vanished mount point (statvfs OSError) ->
      None stats but mount still listed; missing block dir -> []
  t3  render_storage_html: data-sort byte values, human strings, "-" cells for
      unmounted disks, empty-state div
  t4  scan_usb_devices regression on a synthetic /sys tree: watchdog Details now
      carries only the bare block device name (size/mount text removed)
  t5  full-page write_html with real storage_info() output + watchdog rows from
      scan_usb_devices(): five sections in F19 order, watchdog cell <td>sda</td>,
      storage rows carry df stats and mount points
"""
import importlib.util
import os
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "mesh-neighbors.py")

spec = importlib.util.spec_from_file_location("mn", ENGINE)
mn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mn)          # module level is constants + defs only (no I/O)
mn.names = {}                        # main() normally loads mesh-node-names.json; "-" fallback in tests

NOW = datetime(2026, 10, 26, 13, 30, 0, tzinfo=timezone.utc)   # fixed "page generated" time
MiB = 1024 ** 2
GiB = 1024 ** 3

PASS = []


def check(name, cond, detail=""):
    if not cond:
        print(f"FAIL {name} {detail}")
        sys.exit(1)
    PASS.append(name)
    print(f"ok   {name}")


# ---------------------------------------------------------------- fixtures
class FakeStatvfs:
    """df semantics: used = (blocks - bfree) * frsize, avail = bavail * frsize."""

    def __init__(self, used_bytes, avail_bytes):
        self.f_frsize = 4096
        self.f_bavail = avail_bytes // 4096
        self.f_bfree = self.f_bavail + 1            # reserved blocks; keeps bavail <= bfree
        self.f_blocks = self.f_bfree + used_bytes // 4096


FAKE_VFS = {
    "/var/log/piupsmonitor-logs": FakeStatvfs(1 * GiB, 2 * GiB),   # sda1
    "/mnt/kioxia": FakeStatvfs(5 * GiB, 5 * GiB),                  # sdb2
    "/media/vfat": FakeStatvfs(1 * GiB, 3 * GiB),                  # sdb1
    "/boot/firmware": FakeStatvfs(32 * MiB, 1536 * MiB),           # mmcblk0p1 (vfat)
    "/": FakeStatvfs(2 * GiB, 4 * GiB),                            # mmcblk0p2 (rootfs)
}

MMC_USED = 2 * GiB + 32 * MiB            # rootfs + boot partition, summed per disk
MMC_AVAIL = 4 * GiB + 1536 * MiB


def fake_statvfs(mp):
    if mp not in FAKE_VFS:
        raise OSError("mount point vanished mid-run")
    return FAKE_VFS[mp]


def build_tree(td):
    """Synthetic /sys tree: two USB sticks (sda on 1-1.2, sdb+sdc on 1-1.3),
    an unmounted stick (sdc), a vanished-mount disk (sdd), plus mmcblk0/loop0."""
    usb = os.path.join(td, "usb", "devices")
    sysdev = os.path.join(td, "sys", "devices", "usb1", "1-1")
    blk = os.path.join(td, "block")
    for name in ("1-1.2", "1-1.3"):
        os.makedirs(os.path.join(sysdev, name))

    def attr(usbname, vid, pid, product):
        dd = os.path.join(usb, usbname)
        os.makedirs(dd)
        for k, v in (("idVendor", vid), ("idProduct", pid), ("product", product),
                     ("serial", ""), ("bDeviceClass", "00")):
            with open(os.path.join(dd, k), "w") as f:
                f.write(v + "\n")

    attr("1-1.2", "0781", "5567", "Disk 2.0")
    attr("1-1.3", "0954", "102c", "TransMemory")

    for dev, usbname in (("sda", "1-1.2"), ("sdb", "1-1.3"), ("sdc", "1-1.3")):
        dd = os.path.join(blk, dev)
        os.makedirs(dd)
        os.symlink(os.path.join(sysdev, usbname), os.path.join(dd, "device"))

    def size(dev, sectors):
        with open(os.path.join(blk, dev, "size"), "w") as f:
            f.write(f"{sectors}\n")

    os.makedirs(os.path.join(blk, "sdd"))     # no USB parent: storage_info still lists it
    size("sda", 8388608)      # 4.0 GiB
    size("sdb", 29360128)     # 14.0 GiB
    size("sdc", 1048576)      # 512 MiB, unmounted
    size("sdd", 2097152)      # 1.0 GiB, mount point vanished

    os.makedirs(os.path.join(blk, "mmcblk0"))     # boot SD card: now included (F19 revision)
    size("mmcblk0", 15728640)                     # 7.5 GiB
    os.makedirs(os.path.join(blk, "nvme0n1"))     # other physical disk type: included
    size("nvme0n1", 4194304)                      # 2.0 GiB, unmounted
    os.makedirs(os.path.join(blk, "zram0"))       # virtual (RAM-backed): excluded
    size("zram0", 2097152)
    os.makedirs(os.path.join(blk, "loop0"))       # virtual: must be excluded

    mounts = os.path.join(td, "mounts")
    with open(mounts, "w") as f:
        f.write("/dev/root / ext4 rw,relatime 0 0\n"
                "/dev/sda1 /var/log/piupsmonitor-logs ext4 rw 0 0\n"
                "/dev/sdb2 /mnt/kioxia ext4 rw 0 0\n"
                "/dev/sdb1 /media/vfat vfat rw 0 0\n"
                "/dev/mmcblk0p1 /boot/firmware vfat rw 0 0\n"
                "/dev/mmcblk0p2 / ext4 rw 0 0\n"
                "/dev/sdd1 /gone ext4 rw 0 0\n")
    return usb, blk, mounts


# ---------------------------------------------------------------- t1/t2 collector
td = tempfile.mkdtemp(prefix="f19-tree-")          # must outlive the with-block: t4 reuses it
usb_dir, block_dir, mounts_file = build_tree(td)

orig_statvfs = mn.os.statvfs
mn.os.statvfs = fake_statvfs
try:
    disks = mn.storage_info(block_dir=block_dir, mounts_file=mounts_file)
finally:
    mn.os.statvfs = orig_statvfs

by_dev = {d["device"]: d for d in disks}
check("t1 all physical disks (zram0/loop0 excluded)",
      [d["device"] for d in disks] == ["mmcblk0", "nvme0n1", "sda", "sdb", "sdc", "sdd"],
      str([d["device"] for d in disks]))

mmc = by_dev["mmcblk0"]
check("t1 mmcblk0 total (boot SD card included)", mmc["total_bytes"] == int(7.5 * GiB), repr(mmc))
check("t1 mmcblk0 used summed over p-partitions", mmc["used_bytes"] == MMC_USED, repr(mmc))
check("t1 mmcblk0 available summed", mmc["avail_bytes"] == MMC_AVAIL, repr(mmc))
check("t1 mmcblk0 pct = used/(used+avail)",
      abs(mmc["pct"] - MMC_USED / (MMC_USED + MMC_AVAIL) * 100.0) < 1e-9, repr(mmc))
check("t1 mmcblk0 p-partitions attributed (sorted)",
      mmc["mounts"] == ["/", "/boot/firmware"], repr(mmc))

nvme = by_dev["nvme0n1"]
check("t1 nvme disk included; unmounted -> None stats",
      nvme["total_bytes"] == 2 * GiB and nvme["used_bytes"] is None and nvme["mounts"] == [],
      repr(nvme))

sda = by_dev["sda"]
check("t1 sda total from sysfs size file", sda["total_bytes"] == 4 * GiB, repr(sda))
check("t1 sda used (df semantics)", sda["used_bytes"] == 1 * GiB, repr(sda))
check("t1 sda available", sda["avail_bytes"] == 2 * GiB, repr(sda))
check("t1 sda pct = used/(used+avail)", abs(sda["pct"] - 100.0 / 3.0) < 1e-9, repr(sda))
check("t1 sda mounts", sda["mounts"] == ["/var/log/piupsmonitor-logs"], repr(sda))

sdb = by_dev["sdb"]
check("t1 sdb total", sdb["total_bytes"] == 14 * GiB, repr(sdb))
check("t1 sdb used summed over both partitions", sdb["used_bytes"] == 6 * GiB, repr(sdb))
check("t1 sdb avail summed over both partitions", sdb["avail_bytes"] == 8 * GiB, repr(sdb))
check("t1 sdb pct = 6/14", abs(sdb["pct"] - 600.0 / 14.0) < 1e-9, repr(sdb))
check("t1 sdb both partitions attributed (sorted)",
      sdb["mounts"] == ["/media/vfat", "/mnt/kioxia"], repr(sdb))

sdc = by_dev["sdc"]
check("t2 unmounted disk: total known, usage None",
      sdc["total_bytes"] == 512 * 1024 ** 2 and sdc["used_bytes"] is None
      and sdc["avail_bytes"] is None and sdc["pct"] is None, repr(sdc))
check("t2 unmounted disk: no mounts", sdc["mounts"] == [], repr(sdc))

sdd = by_dev["sdd"]
check("t2 vanished mount point: stats None but mount listed",
      sdd["used_bytes"] is None and sdd["pct"] is None and sdd["mounts"] == ["/gone"],
      repr(sdd))

check("t2 missing block dir -> []", mn.storage_info(block_dir=os.path.join(td, "nope")) == [])


# ---------------------------------------------------------------- t3 renderer
html = mn.render_storage_html(disks)
check("t3 sda total cell (data-sort bytes + human)",
      '<td class="num" data-sort="4294967296">4.0 GiB</td>' in html, html[:400])
check("t3 sda used/avail cells",
      'data-sort="1073741824">1.0 GiB' in html and 'data-sort="2147483648">2.0 GiB' in html)
check("t3 sda pct cell", 'data-sort="33.3">33.3 %</td>' in html)
check("t3 sdb summed cells",
      'data-sort="15032385536">14.0 GiB' in html and 'data-sort="6442450944">6.0 GiB' in html
      and 'data-sort="8589934592">8.0 GiB' in html and 'data-sort="42.9">42.9 %</td>' in html)
check("t3 sdb mount list", "/media/vfat, /mnt/kioxia" in html)
check("t3 mmcblk0 row (p-partition mounts listed)",
      f'data-sort="{int(7.5 * GiB)}">7.5 GiB' in html and f'data-sort="{MMC_USED}"' in html
      and "/, /boot/firmware" in html)
i_sdc = html.find("<td>sdc</td>")
row_sdc = html[i_sdc:html.find("</tr>", i_sdc)] if i_sdc != -1 else ""
check("t3 unmounted row: '-' usage cells + em-dash mounts",
      '<td>-</td><td>-</td><td>-</td><td>&mdash;</td>' in row_sdc, row_sdc)
check("t3 empty state", mn.render_storage_html([]) == '<div class="none">no physical storage detected</div>')


# ---------------------------------------------------------------- t4 watchdog details regression
devs = mn.scan_usb_devices(usb_dir=usb_dir, tty_glob=os.path.join(td, "nonexistent", "ttyUSB*"),
                           block_dir=block_dir)
check("t4 two USB devices found", len(devs) == 2, str(sorted(devs)))
row_sda_key = [k for k in devs if k.endswith(":1-1.2")]
row_13_key = [k for k in devs if k.endswith(":1-1.3")]
check("t4 keys carry port path", len(row_sda_key) == 1 and len(row_13_key) == 1, str(sorted(devs)))
d12 = devs[row_sda_key[0]]
d13 = devs[row_13_key[0]]
check("t4 sda row: bare block name only (no size/mount text)", d12["details"] == ["sda"], repr(d12))
check("t4 1-1.3 row: bare names for both disks", d13["details"] == ["sdb", "sdc"], repr(d13))
check("t4 type still 'USB storage'", d12["type"] == "USB storage" and d13["type"] == "USB storage")


# ---------------------------------------------------------------- t5 full page
def fake_read_sysfile(uptime_text):
    orig = mn.read_sysfile

    def patched(path):
        if path == "/proc/uptime":
            return uptime_text
        return orig(path)

    return patched


ORIG_READ_SYSFILE = mn.read_sysfile
USB_INFOS = [
    {"port": "/dev/ttyUSB0", "role": "meshcore",
     "product": "CP2102 USB to UART Bridge Controller", "usb_path": "1-1.2",
     "details": "Amateurfunk Peine FTZ · v1.17.1-d929643"},
]
NTP = {"tz": "Europe/Berlin (CET, +0100)", "ntp": "active", "synced": "yes"}
UPS = {
    "status": {"primary": 1, "secondary": 0, "low": 0, "charging": 0, "full": 0, "button": 0},
    "volts": {"U_Bat": 4154, "I_Rasp": 802, "U_USB": 5064, "U_USV": 439, "U_Ext": 12815},
    "ts": {f: (NOW, u) for f, u in (("U_Bat", "mV"), ("I_Rasp", "mA"), ("U_USB", "mV"),
                                    ("U_USV", "mV"), ("U_Ext", "mV"))},
    "latest_ts": NOW, "stale_s": 0,
}
NODES_EVER = {"73C1F5D1": {"last": "2026-10-26 09:26:18 UTC", "best_db": 14.0,
                           "worst_db": 11.5, "sightings": 23028}}
ROWS = [("73C1F5D1", 0, 12)]

wd_now = NOW.strftime("%Y-%m-%d %H:%M:%S UTC")
WD_DEVICES = {k: {**info, "status": "ONLINE", "since": wd_now, "last_seen": wd_now}
              for k, info in devs.items()}

out = os.path.join(tempfile.mkdtemp(prefix="f19-"), "neighbors.html")
mn.read_sysfile = fake_read_sysfile("90061 180122")
old_out = mn.HTML_OUT
mn.HTML_OUT = out
try:
    mn.write_html(rows=ROWS, now_utc=NOW, nodes_ever=NODES_EVER, usb_infos=USB_INFOS,
                  ntp=NTP, ups=UPS, wd_devices=WD_DEVICES, storages=disks)
    with open(out, encoding="utf-8") as f:
        page = f.read()
finally:
    mn.read_sysfile = ORIG_READ_SYSFILE
    mn.HTML_OUT = old_out

order = [page.find(h) for h in ("<h3>USB serial devices</h3>", "<h3>USB device watchdog</h3>",
                                "<h3>Storage</h3>", "<h3>Clock &amp; NTP</h3>",
                                "<h3>PiUPS+ / Power</h3>")]
check("t5 all five sections present", all(i != -1 for i in order), str(order))
check("t5 F19 section order (Storage between watchdog and clock)",
      order == sorted(order) and len(set(order)) == 5, str(order))

i_wd = page.find("<h3>USB device watchdog</h3>")
i_st = page.find("<h3>Storage</h3>")
wd_section = page[i_wd:i_st]
check("t5 watchdog details cell is the bare name", "<td>sda</td>" in wd_section, wd_section[:600])
check("t5 watchdog section no longer carries size/mount text",
      "GiB" not in wd_section and "mounted at" not in wd_section)

st_section = page[i_st:page.find("<h3>Clock &amp; NTP</h3>")]
check("t5 storage rows carry df stats + mount point",
      'data-sort="4294967296">4.0 GiB' in st_section
      and "/var/log/piupsmonitor-logs" in st_section)
check("t5 boot SD card row present on the page", "<td>mmcblk0</td>" in st_section)

print(f"\n{len(PASS)} checks passed")
