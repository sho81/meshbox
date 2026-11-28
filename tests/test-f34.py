#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""F34 regression suite — Serial/MAC column in the USB serial devices table.

  t1  USB_MAC_RE accepts colon + plain-hex MAC shapes, rejects chip serials
  t2  native-USB device renders the MAC with the MAC tooltip
  t3  12-hex-no-colon serial is normalized to colon form
  t4  bridge-chip serial renders as-is with the bridge tooltip (never a MAC)
  t5  missing/"-" serial renders a plain dash + explanatory tooltip
  t6  table has the "Serial / MAC" header between "USB device" and "USB path"
  t7  serials are HTML-escaped; row cell count is 6
  t8  F34b: watchdog Details gain "SN <serial>" (NESDR-style stick); serial stays
      in the identity key as before

Run:  python3 test-f34.py [engine-path]
Defaults resolve for both the repo root and the flat staging layout.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _find(name):
    for cand in (os.path.join(HERE, name), os.path.join(os.path.dirname(HERE), name)):
        if os.path.isfile(cand):
            return cand
    raise SystemExit(f"{name} not found next to this suite")


ENGINE = sys.argv[1] if len(sys.argv) > 1 else _find("mesh-neighbors.py")
spec = importlib.util.spec_from_file_location("mn", ENGINE)
mn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mn)

PASS = []


def check(name, cond, info=""):
    if cond:
        PASS.append(name)
    else:
        print(f"FAIL {name} {info}")


# --- t1 regex shapes ---------------------------------------------------------
check("t1 mac regex accepts colon + bare-hex, rejects bridge serials",
      mn.USB_MAC_RE.match("44:1B:F6:69:DC:CC")
      and mn.USB_MAC_RE.match("441bf669dccc")
      and not mn.USB_MAC_RE.match("5971262003")
      and not mn.USB_MAC_RE.match("0001")
      and not mn.USB_MAC_RE.match("44:1B:F6:69:DC"))

# --- t2 native device -> MAC cell --------------------------------------------
cell = mn.serial_cell_html({"serial": "44:1B:F6:69:DC:CC"})
check("t2 native MAC cell + MAC tooltip",
      ">44:1B:F6:69:DC:CC<" in cell and "MAC address (chip MAC" in cell)

# --- t3 bare 12-hex normalized -----------------------------------------------
check("t3 bare hex MAC normalized to colon form",
      ">44:1B:F6:69:DC:CC<" in mn.serial_cell_html({"serial": "441bf669dccc"}))

# --- t4 bridge chip serial ----------------------------------------------------
cell = mn.serial_cell_html({"serial": "5971262003"})
check("t4 bridge serial shown as-is, bridge tooltip, never MAC wording",
      ">5971262003<" in cell and "bridge chip" in cell and "MAC address" not in cell)

# --- t5 no serial string -------------------------------------------------------
cell = mn.serial_cell_html({"product": "x"})
check("t5 missing serial -> dash + tooltip", cell == '<td title="no USB serial string exposed">-</td>')
check("t5b explicit dash serial behaves the same",
      mn.serial_cell_html({"serial": "-"}) == '<td title="no USB serial string exposed">-</td>')

# --- t6/t7 full table ----------------------------------------------------------
table = mn.render_usb_html([
    {"port": "/dev/ttyACM0", "role": "meshcore", "product": "USB JTAG/serial debug unit",
     "usb_path": "1-1.1", "serial": "44:1B:F6:69:DC:CC", "details": "Peine FTZ · v1.18.0"},
    {"port": "/dev/ttyACM1", "role": "meshcom", "product": "USB Single Serial",
     "usb_path": "1-1.2", "details": "MeshCom 4.40a"},
])
check("t6 header order Port|USB device|Serial / MAC|USB path|System|Details",
      table.find("<th>USB device</th>") != -1
      and table.find("<th>USB device</th>") < table.find("<th>Serial / MAC</th>") < table.find("<th>USB path</th>"))
check("t7 one MAC row + one dash row, 6 cells each",
      table.count("<td title=\"MAC address") == 1
      and table.count('<td title="no USB serial string exposed">-</td>') == 1
      and all(r.count("<td") == 6 for r in table.split("<tr ")[1:]))
esc = mn.serial_cell_html({"serial": "aa\"><script"})
check("t7b foreign serials are escaped", "aa&quot;&gt;&lt;script" in esc and "<script" not in esc)

# --- t8 F34b: watchdog Details carry the USB serial string (NESDR-style stick) --
import tempfile
with tempfile.TemporaryDirectory() as td:
    ud = os.path.join(td, "usb")
    os.makedirs(os.path.join(ud, "1-1.3"))
    for k, v in (("idVendor", "0bda"), ("idProduct", "2838"),
                 ("product", "NESDR SMArt v5"), ("serial", "00001090"),
                 ("bDeviceClass", "ff")):
        open(os.path.join(ud, "1-1.3", k), "w").write(v + "\n")
    devs = mn.scan_usb_devices(usb_dir=ud,
                               tty_glob=os.path.join(td, "no", "ttyUSB*"),
                               block_dir=os.path.join(td, "no-block"))
    key = "0bda:2838:00001090:1-1.3"
    check("t8 watchdog details gain 'SN <serial>' (stick without tty/block)",
          list(devs) == [key] and devs[key]["details"] == ["SN 00001090"], repr(devs))
    check("t8b serial stays in the identity key (unchanged) and label intact",
          devs[key]["label"] == "NESDR SMArt v5")

print(f"F34 {len(PASS)} checks passed")
