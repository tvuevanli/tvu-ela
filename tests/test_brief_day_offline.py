#!/usr/bin/env python3
"""brief day, offline: the owner's day read from a meetings file, holidays and the meetings of a weekday."""
import datetime, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "brief"))
import brief as B  # noqa: E402

failures = 0


def check(name, cond):
    global failures
    print(("ok   " if cond else "FAIL ") + name)
    failures += 0 if cond else 1


YAML = """day:
  at_desk: "09:00"
  dm_hours: ["08:30", "19:00"]
  qa_deploy: "17:00"
holidays: ["2026-10-30"]

meetings:
  - name: "Scrum with the PM"
    key: scrum-pm
    weekdays: [Mon, Wed, Fri]
    time: "10:00"
    audience: product
    enabled: true
  - name: "Engineering + QA + UX sync"
    key: sync-eng-qa-ux
    weekdays: [Tue, Thu]
    time: ""
    audience: [engineering, qa, ux]
    enabled: true
  - name: "Design review"
    key: design
    weekdays: [Wed]
    time: "09:30"
    audience: ux
    enabled: true
  - name: "Old sync"
    key: old
    weekdays: [Wed]
    time: "15:00"
    audience: qa
    enabled: false
"""
with tempfile.TemporaryDirectory() as t:
    path = os.path.join(t, "meetings.yaml")
    open(path, "w").write(YAML)
    doc = B.owner_day(path)
check("the day block, its DM window a list", doc["day"]["dm_hours"] == ["08:30", "19:00"] and doc["day"]["qa_deploy"] == "17:00")
wed = B.day_plan(datetime.date(2026, 10, 28), doc)
check("a weekday's enabled meetings with a time, in time order, each with its section heading",
      [m["section"] for m in wed["meetings"]] == ["Design review at 09:30", "Scrum with the PM at 10:00"])
check("a meeting with no time renders nothing", B.day_plan(datetime.date(2026, 10, 29), doc)["meetings"] == [])
fri = B.day_plan(datetime.date(2026, 10, 30), doc)
check("a holiday is not a working day and has no meetings", not fri["working_day"] and fri["holiday"] and fri["meetings"] == [])
check("a missing file is an empty day, never an error", B.owner_day(os.path.join(ROOT, "no-such.yaml"))["meetings"] == [])
sys.exit(1 if failures else 0)
