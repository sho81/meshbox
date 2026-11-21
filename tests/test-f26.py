#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""F26 regression suite — Network interfaces section (live iproute2 snapshot).

  t1  network_info: lo dropped, real interfaces kept, states from flags
  t2  MAC from either JSON key (mac / address); missing MAC becomes "-"
  t3  IPv6 scope labels: global / ULA / link
  t4  dynamic flags + lease seconds (valid_lft "forever" -> None)
  t5  default route + per-interface badge (box shape: dst "default",
      "protocol" key); t5b newer shape (dst null, "proto") + lowest metric
  t6  static non-default routes grouped, Hamnet (44/8) tagged
  t7  failure modes: ip missing / garbage output -> {}
  t8  render: table shell, 5 cells per row, default-route badge
  t9  address cells: prefix, scope + lease small text
  t10 footer: default route line + grouped static route line
  t11 empty/broken snapshot -> placeholder
  t12 full page: seven sections, Network between watchdog and Storage

Run:  python3 test-f26.py [engine-path]
Defaults resolve for both the repo root and the flat staging layout.
"""
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

def _find(name):
    for cand in (os.path.join(HERE, name), os.path.join(os.path.dirname(HERE), name)):
        if os.path.isfile(cand):
            return cand
    raise SystemExit(f"{name} not found next to this suite")

ENGINE = sys.argv[1] if len(sys.argv) > 1 else _find("mesh-neighbors.py")

spec = importlib.util.spec_from_file_location("mn", ENGINE)
mn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mn)          # module level is constants + defs only (no I/O)
mn.names = {}

NOW = datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone.utc)

PASS = []


def check(name, cond, info=""):
    if cond:
        PASS.append(name)
        print(f"PASS {name}")
    else:
        print(f"FAIL {name} {info}")
        sys.exit(1)


td = tempfile.mkdtemp(prefix="f26-")

# synthetic iproute2 JSON shaped like the real box (lo/eth0/wlan0 + dummy0)
ADDR = [
    {"ifname": "lo", "index": 1, "flags": ["LOOPBACK", "UP", "LOWER_UP"],
     "addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8,
                    "scope": "host"},
                   {"family": "inet6", "local": "::1", "prefixlen": 128,
                    "scope": "host", "valid_lft": "forever"}]},
    {"ifname": "eth0", "index": 2, "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"],
     "mac": "b8:27:eb:ea:61:d8",
     "addr_info": [{"family": "inet", "local": "192.168.3.10", "prefixlen": 24,
                    "scope": "global", "valid_life_time": 4294967295},
                   {"family": "inet6", "local": "fe80::456f:2821:749c:bded",
                    "prefixlen": 64, "scope": "link", "valid_lft": "forever"}]},
    {"ifname": "wlan0", "index": 3, "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"],
     "address": "b8:27:eb:bf:34:8d",
     "addr_info": [
         {"family": "inet", "local": "192.168.2.195", "prefixlen": 24,
          "dynamic": True, "scope": "global", "valid_lft": 694542},
         {"family": "inet6", "local": "2a00:6020:4a83:2200:b025:2cad:f94f:c4ba",
          "prefixlen": 64, "dynamic": True, "scope": "global", "valid_lft": 2526},
         {"family": "inet6", "local": "fd3a:c821:db70:1711:883a:6161:a126:2e44",
          "prefixlen": 64, "dynamic": True, "scope": "global", "valid_life_time": 6911},
         {"family": "inet6", "local": "fe80::cd1f:4fb0:88ab:996b",
          "prefixlen": 64, "dynamic": True, "scope": "link"}]},
    {"ifname": "dummy0", "index": 4, "flags": ["BROADCAST", "MULTICAST", "UP"],
     "addr_info": []},
]
ROUTES = [
    {"dst": "default", "gateway": "192.168.2.1", "dev": "wlan0", "protocol": "dhcp",
     "prefsrc": "192.168.2.195", "metric": 600},
    {"dst": "44.0.0.0/9", "gateway": "192.168.3.1", "dev": "eth0", "protocol": "static",
     "metric": 100},
    {"dst": "44.128.0.0/10", "gateway": "192.168.3.1", "dev": "eth0", "protocol": "static",
     "metric": 100},
    {"dst": "192.168.2.0/24", "dev": "wlan0", "proto": "kernel", "scope": "link",
     "src": "192.168.2.195", "metric": 600},
]

addr_p, route_p = os.path.join(td, "addr.json"), os.path.join(td, "route.json")
with open(addr_p, "w") as f:
    json.dump(ADDR, f)
with open(route_p, "w") as f:
    json.dump(ROUTES, f)
ip = os.path.join(td, "ip")
with open(ip, "w") as f:
    f.write(f'#!/bin/sh\nif [ "$2 $3" = "addr show" ]; then cat {addr_p}; '
            f'else cat {route_p}; fi\n')
os.chmod(ip, 0o755)

nets = mn.network_info(ip_cmd=ip)
by_name = {d["iface"]: d for d in nets["ifaces"]}

# ---------------------------------------------------------------- t1..t6 parse
check("t1 lo dropped; eth0/wlan0/dummy0 kept, states from UP/LOWER_UP flags",
      list(by_name) == ["eth0", "wlan0", "dummy0"]
      and by_name["eth0"]["state"] == "UP" and by_name["dummy0"]["state"] == "up, no carrier",
      str(list(by_name)))
check("t2 MAC from 'mac' or 'address' key; interface without MAC shows '-'",
      by_name["eth0"]["mac"] == "b8:27:eb:ea:61:d8"
      and by_name["wlan0"]["mac"] == "b8:27:eb:bf:34:8d"
      and by_name["dummy0"]["mac"] == "-",
      str({k: v["mac"] for k, v in by_name.items()}))
check("t3 IPv6 scopes: global / ULA / link on wlan0, link on eth0",
      [e["scope"] for e in by_name["wlan0"]["v6"]] == ["global", "ULA", "link"]
      and [e["scope"] for e in by_name["eth0"]["v6"]] == ["link"],
      str([e["scope"] for e in by_name["wlan0"]["v6"]]))
check("t4 dynamic flag + leases from valid_lft AND valid_life_time keys",
      by_name["wlan0"]["v4"][0]["dynamic"] and by_name["wlan0"]["v4"][0]["lease_s"] == 694542
      and by_name["wlan0"]["v6"][0]["lease_s"] == 2526
      and by_name["wlan0"]["v6"][1]["lease_s"] == 6911
      and by_name["eth0"]["v4"][0]["lease_s"] == 4294967295
      and not by_name["eth0"]["v4"][0]["dynamic"]
      and by_name["wlan0"]["v6"][2]["dynamic"] and by_name["wlan0"]["v6"][2]["lease_s"] is None,
      str(by_name["wlan0"]))
check("t5 default route (dst 'default') on wlan0 + badge flag only there",
      nets["default"]["gateway"] == "192.168.2.1"
      and by_name["wlan0"]["default"] and not by_name["eth0"]["default"],
      json.dumps(nets["default"]))
check("t6 statics grouped by gw+dev, 44/8 tagged (Hamnet)",
      nets["statics"] == ["44.0.0.0/9, 44.128.0.0/10 via 192.168.3.1 dev eth0 (Hamnet)"],
      str(nets["statics"]))

# newer iproute2 shape: dst null/absent for default, "proto" key, two defaults
ROUTES2 = [
    {"dst": None, "gateway": "10.0.0.1", "dev": "eth1", "proto": "dhcp", "metric": 100},
    {"dst": "default", "gateway": "192.168.2.1", "dev": "wlan0", "proto": "dhcp",
     "metric": 600},
    {"dst": "44.0.0.0/9", "gateway": "192.168.3.1", "dev": "eth0", "proto": "static"},
]
with open(route_p, "w") as f:
    json.dump(ROUTES2, f)
nets2 = mn.network_info(ip_cmd=ip)
check("t5b newer iproute2 shape accepted; lowest-metric default wins; proto key works",
      nets2["default"]["gateway"] == "10.0.0.1"
      and nets2["statics"] == ["44.0.0.0/9 via 192.168.3.1 dev eth0 (Hamnet)"],
      json.dumps(nets2["default"]) + str(nets2["statics"]))
with open(route_p, "w") as f:
    json.dump(ROUTES, f)

# ---------------------------------------------------------------- t7 failures
check("t7 ip missing -> {} (no exception)", mn.network_info(ip_cmd=os.path.join(td, "nope")) == {})
bad = os.path.join(td, "ip-bad")
with open(bad, "w") as f:
    f.write("#!/bin/sh\necho 'not json'\n")
os.chmod(bad, 0o755)
check("t7 garbage ip output -> {}", mn.network_info(ip_cmd=bad) == {})

# ---------------------------------------------------------------- t8..t11 render
html = mn.render_network_html(nets)
check("t8 table shell + 5 cells per row over 3 rows",
      'id="tbl-net"' in html and html.count("<tr data-order=") == 3
      and all(r.count("<td") == 5 for r in
              [html[html.find(f'data-order="{i}"'):html.find('</tr>', html.find(f'data-order="{i}"'))]
               for i in range(3)]), html)
check("t8 default-route badge only on wlan0 name cell",
      html.count("(default route)") == 1 and "(default route)</span></td>" in html
      and '<td data-sort="wlan0">' in html, html)
check("t9 address cells: prefix + scope/lease small text ('dynamic' fallback label)",
      "192.168.2.195/24" in html and "(lease 8 d 00 h)" in html
      and "(global lease 42 m 06 s)" in html and "(ULA lease 1 h 55 m)" in html
      and "(link)" in html and "(link dynamic)" in html
      and "192.168.3.10/24<" in html, html)
check("t10 dummy0 rows empty -> em-dash cells", "<td>&mdash;</td><td>&mdash;</td>" in html, html)
check("t10 footer: default route + grouped statics",
      "default route via wlan0: gateway 192.168.2.1, source 192.168.2.195" in html
      and "44.0.0.0/9, 44.128.0.0/10 via 192.168.3.1 dev eth0 (Hamnet)" in html, html)
check("t11 empty snapshot -> placeholder",
      mn.render_network_html({}) == '<div class="none">no network info (iproute2 unreadable?)</div>'
      and mn.render_network_html({"ifaces": []}) == '<div class="none">no network info (iproute2 unreadable?)</div>')

# ---------------------------------------------------------------- t12 full page
NTP = {"tz": "Europe/Berlin (CET, +0100)", "ntp": "active", "synced": "yes"}
UPS = {
    "status": {"primary": 1, "secondary": 0, "low": 0, "charging": 0, "full": 0, "button": 0},
    "volts": {"U_Bat": 4154, "I_Rasp": 802, "U_USB": 5064, "U_USV": 439, "U_Ext": 12815},
    "ts": {f: (NOW, u) for f, u in (("U_Bat", "mV"), ("I_Rasp", "mA"), ("U_USB", "mV"),
                                    ("U_USV", "mV"), ("U_Ext", "mV"))},
    "latest_ts": NOW, "stale_s": 0,
}
WD = {"10c4:ea60:1-1.2": {"label": "CP2102", "key": "10c4:ea60:1-1.2",
                          "type": "UART bridge", "port_path": "1-1.2", "serial": "-",
                          "details": ["/dev/ttyUSB0"], "status": "ONLINE",
                          "since": "2026-11-05 20:00:00 UTC",
                          "last_seen": NOW.strftime("%Y-%m-%d %H:%M:%S UTC")}}
STORAGE = [{"device": "sda", "total_bytes": 4294967296, "used_bytes": 1073741824,
            "avail_bytes": 2147483648, "pct": 100.0 / 3.0,
            "mounts": ["/var/log/piupsmonitor-logs"]}]

out = os.path.join(td, "neighbors.html")
old_out, old_sysfile = mn.HTML_OUT, mn.read_sysfile
mn.HTML_OUT = out
mn.read_sysfile = lambda p: "90061 180122" if p == "/proc/uptime" else old_sysfile(p)
try:
    mn.write_html(rows=[("AABB0011", 20, -160)], now_utc=NOW, nodes_ever=None,
                  usb_infos=[{"port": "/dev/ttyUSB0", "role": "meshcore", "ok": True,
                              "product": "CP2102 USB to UART Bridge Controller",
                              "vid_pid": "10c4:ea60", "usb_path": "1-1.2",
                              "details": "-"}],
                  ntp=NTP, ups=UPS, wd_devices=WD, storages=STORAGE,
                  temps=[{"source": "SoC", "c": 41.9}],
                  temps_ever={"SoC": {"min": 8.2, "min_at": "2026-11-06 04:12 UTC",
                                      "max": 62.0, "max_at": "2026-10-31 14:03 UTC"}},
                  nets=nets)
finally:
    mn.HTML_OUT, mn.read_sysfile = old_out, old_sysfile
with open(out, encoding="utf-8") as f:
    page = f.read()
order = [page.find(h) for h in ("<h3>USB serial devices</h3>", "<h3>USB device watchdog</h3>",
                                "<h3>Network interfaces</h3>", "<h3>Storage</h3>",
                                "<h3>Clock &amp; NTP</h3>", "<h3>Temperatures</h3>",
                                "<h3>PiUPS+ / Power</h3>")]
check("t12 all seven sections present", all(i != -1 for i in order), str(order))
check("t12 section order: Network between watchdog and Storage",
      order == sorted(order) and len(set(order)) == 7, str(order))
i_net, i_st = page.find("<h3>Network interfaces</h3>"), page.find("<h3>Storage</h3>")
check("t12 live rows rendered inside the section",
      "192.168.2.195/24" in page[i_net:i_st], page[i_net:i_net + 200])

print(f"\n{len(PASS)} checks passed")
