#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""F29 regression suite — node_names as optional box-config overlay key.

  t1  no box-config: load_names unchanged (file map only)
  t2  node_names only (no mesh-node-names.json): config map works standalone
  t3  merge: config entries override file entries; file-only keys survive
  t4  keys normalized upper-case; non-string values coerced to str
  t5  broken node_names shapes ignored (string / list), file map still works
  t6  F27 overlay keys still work next to node_names (no regression)

Run:  python3 test-f29.py [engine-path]
Defaults resolve for both the repo root and the flat staging layout.
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def _find(name):
    for cand in (os.path.join(HERE, name), os.path.join(os.path.dirname(HERE), name)):
        if os.path.isfile(cand):
            return cand
    raise SystemExit(f"{name} not found next to this suite")


ENGINE = sys.argv[1] if len(sys.argv) > 1 else _find("mesh-neighbors.py")
PASS = []


def check(name, cond, info=""):
    if cond:
        PASS.append(name)
        print(f"PASS {name}")
    else:
        print(f"FAIL {name} {info}")
        sys.exit(1)


def load_with(cfg_text=None, names_text=None, alias="mn29"):
    """Engine copy in a fresh tmpdir; box-config.json / mesh-node-names.json
    placed next to it as requested (None = file absent)."""
    td = tempfile.mkdtemp(prefix="f29-")
    eng = os.path.join(td, "mesh-neighbors.py")
    shutil.copy(ENGINE, eng)
    if cfg_text is not None:
        with open(os.path.join(td, "box-config.json"), "w", encoding="utf-8") as f:
            f.write(cfg_text)
    if names_text is not None:
        with open(os.path.join(td, "mesh-node-names.json"), "w", encoding="utf-8") as f:
            f.write(names_text)
    spec = importlib.util.spec_from_file_location(alias, eng)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ t1 default
m1 = load_with()
check("t1 no box-config/node_names: load_names empty without file", m1.load_names() == {})
m1b = load_with(names_text=json.dumps({"AABB0011": "FileOnly"}))
check("t1 file map alone unchanged", m1b.load_names() == {"AABB0011": "FileOnly"})

# ------------------------------------------------------------------ t2 config
m2 = load_with(cfg_text=json.dumps({"node_names": {"AABB0011": "ConfigOnly"}}))
check("t2 node_names alone (no names file) resolves", m2.load_names() == {"AABB0011": "ConfigOnly"})

# ------------------------------------------------------------------ t3 merge
m3 = load_with(cfg_text=json.dumps({"node_names": {"BBCC2222": "FromConfig", "DDDD4444": "CfgOnly"}}),
               names_text=json.dumps({"AABB0011": "FileOnly", "BBCC2222": "FromFile"}))
check("t3 merge: config wins, file-only keys survive",
      m3.load_names() == {"AABB0011": "FileOnly", "BBCC2222": "FromConfig", "DDDD4444": "CfgOnly"},
      str(m3.load_names()))

# ------------------------------------------------------------------ t4 normalize
m4 = load_with(cfg_text=json.dumps({"node_names": {"aabb0011": "Lower Key", "11223344": "Num"}}))
got = m4.load_names()
check("t4 keys normalized upper-case", got.get("AABB0011") == "Lower Key" and got.get("11223344") == "Num", str(got))

# ------------------------------------------------------------------ t5 broken shapes
m5 = load_with(cfg_text=json.dumps({"node_names": "not-a-dict"}),
               names_text=json.dumps({"AABB0011": "FileOnly"}))
check("t5 node_names string ignored, file map intact", m5.load_names() == {"AABB0011": "FileOnly"})
m5b = load_with(cfg_text=json.dumps({"node_names": ["x", "y"]}),
                names_text="{ broken")
check("t5 node_names list ignored; broken names file tolerated", m5b.load_names() == {})

# ------------------------------------------------------------------ t6 no F27 regression
m6 = load_with(cfg_text=json.dumps({"station": "TESTBOX Box", "ports_glob": "/dev/ttyACM*",
                                    "node_names": {"AABB0011": "N"}}))
check("t6 F27 overlay keys still applied next to node_names",
      m6.STATION == "TESTBOX Box" and m6.PORTS_GLOB == "/dev/ttyACM*"
      and m6.TTY_SYS_GLOB == "/sys/class/tty/ttyACM*" and m6.load_names() == {"AABB0011": "N"})

print(f"\n{len(PASS)} checks passed")
