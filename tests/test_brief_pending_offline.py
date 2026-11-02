#!/usr/bin/env python3
"""The brief's read of the pending promotions, offline: the record for the line it renders, the old single-record
shape migrated, a closed record ignored, a plain candidate file left as it is."""
import json, os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "brief"))
import brief as B  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

rec = lambda line, frm, to, closed=False, refreshed="2026-11-02T01:00Z": {"line": line, "from": frm, "to": to, "closed": closed, "refreshed": refreshed,  # noqa: E731
                                                                          "report": f"/r/{line}.json", "candidate": {"label": f"{line} → {to}", "versions": {}}}
keyed = {"2.1|daily-wed|prod-3": rec("2.1", "daily-wed", "prod-3"), "2.0|qa-cn2|prod-8": rec("2.0", "qa-cn2", "prod-8")}
check("the keyed file gives each line its own record",
      B.pending_for(keyed, "2.1")["to"] == "prod-3" and B.pending_for(keyed, "2.0")["to"] == "prod-8" and B.pending_for(keyed, "1.5") is None)
old = rec("2.1", "daily-wed", "prod-3")
check("the old single-record shape reads as that line's record, and as none for another line",
      B.pending_for(old, "2.1") is old and B.pending_for(old, "2.0") is None)
check("a closed record is not pending", B.pending_for({"k": rec("2.1", "daily-wed", "prod-3", closed=True)}, "2.1") is None)
two = {"a": rec("2.1", "daily-wed", "prod-3", refreshed="2026-11-01T01:00Z"), "b": rec("2.1", "daily-wed", "prod-4", refreshed="2026-11-02T01:00Z")}
check("two open records of one line: the most recently refreshed", B.pending_for(two, "2.1")["to"] == "prod-4")
check("a plain {label, versions} candidate file is not a pending record", B.pending_records({"label": "x", "versions": {"a": "1"}}) == {})
with tempfile.TemporaryDirectory() as d:
    os.makedirs(os.path.join(d, "promote"))
    json.dump(keyed, open(os.path.join(d, "promote", "pending.json"), "w"))
    check("read_pending defaults to the morning's line and takes another by name",
          B.read_pending({"reports": d})["line"] == B.LINE and B.read_pending({"reports": d}, "2.0")["to"] == "prod-8")
    check("no file is no pending promotion", B.read_pending({"reports": os.path.join(d, "none")}) is None)
sys.exit(1 if failures else 0)
