#!/usr/bin/env python3
"""The pending promotion, offline: a report opens it, a second refreshes it and keeps the owner's open choices,
another line replaces it."""
import json, os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "promote"))
import promote as P  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

def res(at, fe="v2.2.121 build176"):
    row = lambda s, v: {"service": s, "from": {"version": v, "parsed": P.parse_version(v)}}
    return {"line": "2.1", "from": "daily-wed", "to": "prod-3", "generated_at": at, "counts": {"findings": {"stop": 1, "high": 2}},
            "lanes": {"services": [row("mediahub-frontend", fe), row("mediahub-backend", "v2.1.34 build265")]}}

with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "promote", "pending.json")
    r1 = P.record_pending(res("2026-10-27T09:00"), "/r/one.json", path)
    check("a report opens the pending promotion with the source lane's versions",
          r1["opened"] == "2026-10-27T09:00" and r1["candidate"]["versions"]["mediahub-backend"] == {"version": "2.1.34+265"} and not r1["closed"])
    doc = json.load(open(path))
    doc["candidate"]["versions"]["mediahub-frontend"] = {"awaiting": "owner", "options": ["2.2.118", "2.2.118 patch with MH-3821"], "why": "QA failed 2.2.121"}
    json.dump(doc, open(path, "w"))
    r2 = P.record_pending(res("2026-10-28T09:00"), "/r/two.json", path)
    check("a second report refreshes it and keeps a choice still awaiting the owner",
          r2["opened"] == "2026-10-27T09:00" and r2["refreshed"] == "2026-10-28T09:00" and r2["report"] == "/r/two.json"
          and r2["candidate"]["versions"]["mediahub-frontend"].get("awaiting") == "owner")
    other = dict(res("2026-10-29T09:00"), to="prod-4")
    r3 = P.record_pending(other, "/r/three.json", path)
    check("a report for other lanes opens a new one", r3["opened"] == "2026-10-29T09:00" and "awaiting" not in str(r3["candidate"]))
sys.exit(1 if failures else 0)
