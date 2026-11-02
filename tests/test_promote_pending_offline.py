#!/usr/bin/env python3
"""The pending promotions, offline: a report opens one record per line and lane pair, a second refreshes it and keeps
the owner's open choices, another line's report leaves it alone, an unreadable source lane never blanks a filled
candidate, the old single-record file migrates on read, and close picks one record."""
import json, os, sys, tempfile, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "promote"))
import promote as P  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

def res(at, fe="v2.2.121 build176", line="2.1", frm="daily-wed", to="prod-3", read=True):
    row = lambda s, v: {"service": s, "from": ({"version": v, "parsed": P.parse_version(v)} if read else None), "unreadable": [] if read else ["prod"]}
    return {"line": line, "from": frm, "to": to, "generated_at": at, "counts": {"findings": {"stop": 1, "high": 2}},
            "lanes": {"services": [row("mediahub-frontend", fe), row("mediahub-backend", "v2.1.34 build265")],
                      "hosts_read": {P.lane_host(frm): read, P.lane_host(to): True}}}

with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "promote", "pending.json")
    r1 = P.record_pending(res("2026-10-27T09:00"), "/r/one.json", path)
    check("a report opens the pending promotion with the source lane's versions",
          r1["opened"] == "2026-10-27T09:00" and r1["candidate"]["versions"]["mediahub-backend"] == {"version": "2.1.34+265"} and not r1["closed"])
    doc = json.load(open(path))
    check("the file is keyed by line and lane pair", list(doc) == ["2.1|daily-wed|prod-3"])
    doc["2.1|daily-wed|prod-3"]["candidate"]["versions"]["mediahub-frontend"] = {"awaiting": "owner", "options": ["2.2.118", "2.2.118 patch with MH-3821"], "why": "QA failed 2.2.121"}
    doc["2.1|daily-wed|prod-3"]["candidate"]["label"] = "Wednesday (build 78) → prod-3"
    doc["2.1|daily-wed|prod-3"]["open_items"] = ["MH-3808 QA FAIL 10-30"]
    json.dump(doc, open(path, "w"))
    r2 = P.record_pending(res("2026-10-28T09:00"), "/r/two.json", path)
    check("a second report refreshes it and keeps a choice still awaiting the owner",
          r2["opened"] == "2026-10-27T09:00" and r2["refreshed"] == "2026-10-28T09:00" and r2["report"] == "/r/two.json"
          and r2["candidate"]["versions"]["mediahub-frontend"].get("awaiting") == "owner")
    check("and the fields the report does not produce: the label and the open items",
          r2["candidate"]["label"] == "Wednesday (build 78) → prod-3" and r2["open_items"] == ["MH-3808 QA FAIL 10-30"])
    r3 = P.record_pending(res("2026-10-29T09:00", line="2.0", frm="qa-cn2", to="prod-8", read=False), "/r/three.json", path)
    doc = json.load(open(path))
    check("another line's report opens its own record and leaves the first one as it was",
          set(doc) == {"2.1|daily-wed|prod-3", "2.0|qa-cn2|prod-8"} and doc["2.1|daily-wed|prod-3"]["refreshed"] == "2026-10-28T09:00"
          and doc["2.1|daily-wed|prod-3"]["candidate"]["versions"]["mediahub-backend"] == {"version": "2.1.34+265"})
    check("a first report whose source lane was not read opens an empty candidate marked stale",
          r3["candidate"]["versions"] == {} and r3["candidate"]["stale"] == "2026-10-29T09:00 source unreadable")
    doc["2.0|qa-cn2|prod-8"]["candidate"]["versions"] = {"mediahub-backend": {"version": "2.0.11+268"}}
    json.dump(doc, open(path, "w"))
    r4 = P.record_pending(res("2026-10-30T09:00", line="2.0", frm="qa-cn2", to="prod-8", read=False), "/r/four.json", path)
    check("an unreadable source never overwrites a filled candidate: the versions stand, marked stale",
          r4["candidate"]["versions"] == {"mediahub-backend": {"version": "2.0.11+268"}} and r4["candidate"]["stale"] == "2026-10-30T09:00 source unreadable"
          and r4["refreshed"] == "2026-10-30T09:00")
    r5 = P.record_pending(res("2026-10-31T09:00", line="2.0", frm="qa-cn2", to="prod-8", fe="v2.2.72.18 build166"), "/r/five.json", path)
    check("a readable source refreshes the versions and clears the mark",
          r5["candidate"]["versions"]["mediahub-frontend"] == {"version": "2.2.72.18+166"} and "stale" not in r5["candidate"])
    # close: two open → refuse without a selection; --line picks one; the other stays open
    P.pending_path = lambda: path
    rc = []
    real_exit = sys.exit
    sys.exit = lambda c=0: rc.append(c) or (_ for _ in ()).throw(SystemExit(c))
    try:
        try:
            P.cmd_close(types.SimpleNamespace(line=None, to=None, json=False))
        except SystemExit:
            pass
        check("close with two open records and no selection refuses (exit 2)", rc == [P.EX_USAGE])
        P.cmd_close(types.SimpleNamespace(line="2.0", to=None, json=False))
        doc = json.load(open(path))
        check("close --line closes that record only",
              doc["2.0|qa-cn2|prod-8"]["closed"] and not doc["2.1|daily-wed|prod-3"]["closed"])
        P.cmd_close(types.SimpleNamespace(line=None, to=None, json=False))
        doc = json.load(open(path))
        check("with one open record close needs no selection", doc["2.1|daily-wed|prod-3"]["closed"])
    finally:
        sys.exit = real_exit
    r6 = P.record_pending(res("2026-11-01T09:00"), "/r/six.json", path)
    check("a report after a close opens anew, dropping the closed record's extras",
          r6["opened"] == "2026-11-01T09:00" and "open_items" not in r6 and r6["candidate"]["label"] == "next train → prod-3")
    # migration: the single-record shape the file had before
    old = {"line": "2.1", "from": "daily-wed", "to": "prod-3", "opened": "o", "refreshed": "o", "report": "/r/old.json", "closed": False,
           "candidate": {"label": "next train → prod-3", "versions": {"mediahub-backend": {"version": "2.1.34+265"}}}, "counts": {}}
    json.dump(old, open(path, "w"))
    check("the old single-record file reads as one keyed record", P.load_pending(path) == {"2.1|daily-wed|prod-3": old})
    r7 = P.record_pending(res("2026-11-02T09:00", line="2.1", read=False), "/r/seven.json", path)
    doc = json.load(open(path))
    check("and the first write migrates it, an unreadable source keeping its versions",
          list(doc) == ["2.1|daily-wed|prod-3"] and r7["opened"] == "o" and r7["candidate"]["versions"] == {"mediahub-backend": {"version": "2.1.34+265"}}
          and r7["candidate"]["stale"].endswith("source unreadable"))
sys.exit(1 if failures else 0)
