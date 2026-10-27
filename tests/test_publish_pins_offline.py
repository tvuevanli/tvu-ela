#!/usr/bin/env python3
"""Publishing the release pins, offline: copied into the published tree and recorded in the manifest; no pins, no file."""
import os, sys, tempfile, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "publish"))
import publish as P  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

with tempfile.TemporaryDirectory() as d:
    elak, pub = os.path.join(d, "elak"), os.path.join(d, "pub")
    os.makedirs(os.path.join(elak, "map")); os.makedirs(pub)
    open(os.path.join(elak, "map", "published-machines.md"), "w").write("| source | published file | generated | verified | reader |\n|---|---|---|---|---|\n| — | | | | |\n")
    P.roots = lambda: (elak, pub)
    P.write_published_manifest = lambda r, p: None
    P.DIRTY["on"] = True                     # a plain directory, not a repository: the copying is under test here
    P.cmd_pins(types.SimpleNamespace(json=False))
    check("no pins in elak, nothing published", not os.path.exists(os.path.join(pub, P.PINS_REL)))
    os.makedirs(os.path.join(elak, "blueprint"))
    open(os.path.join(elak, P.PINS_REL), "w").write('lines:\n  "2.1": {"official": "MediaHub 2.1.15", "id": "1", "set": "2026-10-27", "by": "owner"}\n')
    P.cmd_pins(types.SimpleNamespace(json=False))
    check("the pins are copied to the same path in the published tree",
          open(os.path.join(pub, P.PINS_REL)).read() == open(os.path.join(elak, P.PINS_REL)).read())
    check("and recorded in the manifest", "`blueprint/releases.yaml`" in open(os.path.join(elak, "map", "published-machines.md")).read())
sys.exit(1 if failures else 0)
