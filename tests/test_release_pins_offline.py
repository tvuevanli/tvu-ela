#!/usr/bin/env python3
"""The release pins, offline: the file renders and reads back, one entry per line."""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "release"))
import release as R  # noqa: E402

lines = {"2.1": {"official": "MediaHub 2.1.15", "id": "1564267921390329856", "set": "2026-10-27", "by": "owner"},
         "2.0": {"official": "MediaHub 2.0 rc11", "id": "1", "set": "2026-10-20", "by": "owner"}}
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "releases.yaml")
    open(p, "w").write(R.render_pins(lines))
    ok = R.read_pins(p) == lines and R.read_pins(os.path.join(d, "none.yaml")) == {}
print(("ok   " if ok else "FAIL ") + "the pins file round-trips, and a missing file is no pin")
sys.exit(0 if ok else 1)
