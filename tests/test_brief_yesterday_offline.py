#!/usr/bin/env python3
"""The yesterday join, offline: which strings count as ticket keys."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "brief"))
import brief as B  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

check("a key in a subject", B.keys_in("fix(copier): MH-3568 drop the stale PID") == ["MH-3568"])
check("a key in a branch name", B.keys_in("feature/MH-3800-issp") == ["MH-3800"])
check("codecs and standards are not keys", B.keys_in("UTF-8 ISO-8601 H-264 AAC-2 X-1 MP-4 AWS-3 QA-2") == [])
check("keys are unique and sorted", B.keys_in("WF-476 MH-1 MH-1") == ["MH-1", "WF-476"])
check("a bare number is not a key", B.keys_in("build 172, #365") == [])

import datetime  # noqa: E402
now = datetime.datetime(2026, 10, 28, 10, 0, tzinfo=datetime.timezone.utc)   # a Wednesday
issues = [
    {"key": "MH-1", "summary": "routed", "status": "To Do", "assignee": "Dev A", "comments": [],
     "events": [{"field": "assignee", "to": "Dev A", "by": "Owner", "at": "2026-10-23T09:00:00.000+0000"}]},
    {"key": "MH-2", "summary": "answered", "status": "In Progress", "assignee": "Dev B", "comments": [],
     "events": [{"field": "assignee", "to": "Dev B", "by": "Owner", "at": "2026-10-23T09:00:00.000+0000"},
                {"field": "status", "to": "In Progress", "by": "Dev B", "at": "2026-10-24T09:00:00.000+0000"}]},
    {"key": "MH-3", "summary": "asked", "status": "Review", "assignee": "QA C", "events": [],
     "comments": [{"by": "Owner", "at": "2026-10-27T09:00:00.000+0000", "text": "Can you retest on 2.1.34?"},
                  {"by": "Helm Lookout", "at": "2026-10-27T10:00:00.000+0000", "text": "Fixed In set"}]},
    {"key": "MH-4", "summary": "committed", "status": "To Do", "assignee": "Dev D", "comments": [],
     "events": [{"field": "assignee", "to": "Dev D", "by": "Owner", "at": "2026-10-23T09:00:00.000+0000"}]},
]
w = {r["ref"]: r for r in B.ticket_waits(issues, "Owner", set(), {"MH-4"}, now)}
check("a ticket he routed with no move by its assignee waits, counted in working days, due at two",
      "MH-1" in w and w["MH-1"]["working_days_silent"] == 3 and w["MH-1"]["threshold"] == 2 and w["MH-1"]["due"])
check("a status change or a commit by the assignee is an answer", "MH-2" not in w and "MH-4" not in w)
check("his ask as the last human comment waits; Helm's edit after it is not an answer",
      "MH-3" in w and w["MH-3"]["working_days_silent"] == 1 and not w["MH-3"]["due"])
self_assigned = [{"key": "MH-5", "summary": "mine", "status": "Review", "assignee": "Owner", "comments": [],
                  "events": [{"field": "assignee", "to": "Owner", "by": "Owner", "at": "2026-10-23T09:00:00.000+0000"}]}]
check("a ticket he assigned to himself waits on nobody", B.ticket_waits(self_assigned, "Owner", set(), set(), now) == [])
sys.exit(1 if failures else 0)
