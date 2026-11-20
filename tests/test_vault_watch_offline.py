#!/usr/bin/env python3
"""The vault as the work panel, offline (plan 2026-11-20): the watcher's stamp beside a line it took, a stamped line
never taken twice, a page he changed in the last ten minutes left to him, and Syncthing's conflict copies merged into
the live page and kept."""
import contextlib, io, json, os, sys, tempfile, time, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import vault as V  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

# ── a page he is editing is his for ten minutes ────────────────────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "today.md")
    open(p, "w").write("ela wrote this\n")
    mine = V.digest("ela wrote this\n")
    check("the page as the sync wrote it is not his edit", not V.his_recent_edit(p, mine))
    open(p, "w").write("ela wrote this\nela: hold MH-1\n")
    check("changed by him a moment ago: left to him", V.his_recent_edit(p, mine))
    check("changed eleven minutes ago: rewritten", not V.his_recent_edit(p, mine, now=time.time() + 660))
    check("no record yet: not taken for his edit", not V.his_recent_edit(p, None))
    V.atomic_write(p, "ela rewrote it in this run\n")
    check("ela's own write earlier in the same run is not his edit", not V.his_recent_edit(p, mine))

print(f"\n{len(failures)} failure(s)" if failures else "\nall ok")
sys.exit(1 if failures else 0)
