#!/usr/bin/env python3
"""The sprint reading, offline: a temporary vault with one active and one closed sprint note, and a runtime
holding part of a week's yesterday files."""
import atexit, datetime, os, shutil, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "brief"))
import brief as B  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

ACTIVE = """---
title: "Sprint 2"
type: "sprint"
date: "2026-11-09"
status: "active"
start: "2026-11-09"
end: "2026-11-20"
---
# Sprint 2

## Sprint goals

| # | goal | ticket | where it stands (2026-11-09) | done when, by 20 Nov |
|---|---|---|---|---|
| G1 | **Generic MXL** carries `integration.type` | [MH-3768](https://example/browse/MH-3768) | UDS already sends it (RRS-421) | merge request submitted |

## Committed

| # | item | done when |
|---|---|---|
| 1 | [MH-3794](https://example/browse/MH-3794) / [MH-3795](https://example/browse/MH-3795) device APIs | broken into lanes |
| 2 | [MH-2406](https://example/browse/MH-2406) shipped, but cannot work ([[2026-10-26-deep-mh-2406\\|the reading]]) | the frontend change in QA |

## Stretch

| # | item | done when |
|---|---|---|
| 9 | MH-1 | never read |
"""
CLOSED = ACTIVE.replace('status: "active"', 'status: "done"').replace('date: "2026-11-09"', 'date: "2026-12-01"')

vault, runtime = tempfile.mkdtemp(prefix="ela-vault-"), tempfile.mkdtemp(prefix="ela-runtime-")
atexit.register(shutil.rmtree, vault, True); atexit.register(shutil.rmtree, runtime, True)
os.makedirs(os.path.join(vault, "sprints")); os.makedirs(os.path.join(runtime, "runner"))
open(os.path.join(vault, "sprints", "2026-S02.md"), "w").write(ACTIVE)
open(os.path.join(vault, "sprints", "2026-S03.md"), "w").write(CLOSED)
for day in ("2026-11-09", "2026-11-11", "2026-11-13"):
    open(os.path.join(runtime, "runner", f"{day}-yesterday.json"), "w").write("{}")

d = datetime.date.fromisoformat
r = B.read_sprint(vault, runtime, d("2026-11-11"))
s = r["active"]
check("the active sprint is found, a closed one with a later date is not", s and s["title"] == "Sprint 2")
check("Wednesday of the first week is day 3 of 10", (s["day"], s["days"], s["days_left"]) == (3, 10, 7))
check("a weekend counts as the Friday before", B.read_sprint(vault, runtime, d("2026-11-15"))["active"]["day"] == 5)
check("after the end the day stops at the last one", B.read_sprint(vault, runtime, d("2026-11-25"))["active"]["day"] == 10)
items = s["items"]
check("goals and committed items, not stretch", [(i["section"], i["id"]) for i in items] == [("goal", "G1"), ("committed", "1"), ("committed", "2")])
check("a goal's keys come from its ticket column, not its status", items[0]["keys"] == ["MH-3768"])
check("a committed row names every key it carries", items[1]["keys"] == ["MH-3794", "MH-3795"])
check("links and bold are read as plain words", items[0]["item"] == "Generic MXL carries integration.type" and "the reading" in items[2]["item"])
check("each item keeps its done-when", items[2]["done_when"] == "the frontend change in QA")
check("a midweek day is not Friday", r["friday"] is False)
f = B.read_sprint(vault, runtime, d("2026-11-13"))
check("on Friday the week's yesterday files are listed", f["friday"] and [os.path.basename(p) for p in f["week_yesterday_files"]]
      == ["2026-11-09-yesterday.json", "2026-11-11-yesterday.json", "2026-11-13-yesterday.json"])
check("no active sprint is said, not an error", B.read_sprint(runtime, runtime, d("2026-11-11")) == {"active": None})

print("brief sprint: all offline checks passed" if not failures else f"brief sprint: {len(failures)} check(s) failed")
sys.exit(1 if failures else 0)
