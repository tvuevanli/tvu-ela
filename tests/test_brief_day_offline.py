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
  qa_test_hours: 24
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
at = lambda h, m: datetime.datetime(2026, 10, 28, h, m)  # noqa: E731
check("the lanes page says whether it was read before or after the QA deploy",
      B.deploy_note(at(13, 0), wed) == "*Read at 13:00, before today's QA-AWS3 deploy (~17:00)*"
      and B.deploy_note(at(17, 30), wed) == "*Read at 17:30, after today's QA-AWS3 deploy (~17:00)*")
check("no line on a day off", B.deploy_note(at(13, 0), fri) is None)
tz = datetime.timezone(datetime.timedelta(hours=8))
check("a build's report is due the next working day's evening; Thursday's skips the Friday holiday and the weekend",
      B.report_due(datetime.datetime(2026, 10, 27, 17, 58, tzinfo=tz), doc) == datetime.date(2026, 10, 28)
      and B.report_due(datetime.datetime(2026, 10, 29, 17, 30, tzinfo=tz), doc) == datetime.date(2026, 11, 2))
rel = lambda n, at, *vs: {"subject": f"[Release Mediahub QA-AWS3] For 2.1 Release build {n}", "date": at,  # noqa: E731
                          "moves": [{"to": v} for v in vs]}
rep = lambda at, subj, *vs: {"subject": subj, "at": at, "pass": 60, "fail": 2, "verdict": "partial", "new_keys": ["MH-9"],  # noqa: E731
                             "tested": [{"version": f"v{v} build1"} for v in vs]}
docs = [{"releases": [rel(77, "Tue, 27 Oct 2026 02:58:31 -0700", "2.1.35", "2.2.122")], "qa": []},
        {"releases": [rel(78, "Wed, 28 Oct 2026 03:23:26 -0700", "2.1.36", "2.2.123")],
         "qa": [rep("2026-10-28T18:43:47+08:00", "Daily Test Report … build 75 on 10-28", "2.1.35", "2.2.122")]}]
bs = B.qa_builds(docs, doc)
check("a report goes to the build whose versions it ran on, whatever its subject says",
      [(b["build"], bool(b["report"])) for b in bs] == [("77", True), ("78", False)] and bs[0]["report"]["keys"] == ["MH-9"])
with tempfile.TemporaryDirectory() as t:
    import json
    os.makedirs(os.path.join(t, "runner"))
    for d, x in zip(("2026-10-28", "2026-10-29"), docs):
        json.dump(x, open(os.path.join(t, "runner", f"{d}-changes.json"), "w"))
    c = B.qa_cycle(datetime.date(2026, 10, 29), runtime=t, doc=doc)
    check("on the morning of D the verdict build is the one reported, the build sent the evening before is under test",
          c["verdict_build"]["build"] == "77" and c["under_test_build"]["build"] == "78" and c["under_test_build"]["due"] == "2026-10-29")
    check("the lanes page's QA-cycle lines", B.qa_cycle_lines(c, datetime.date(2026, 10, 29)) == [
        "- sent 10-27 17:58 · build 77 · QA report 10-28 18:43: 60 pass, 2 fail (MH-9) · verdict partial",
        "- sent 10-28 18:23 · build 78 · under test · report due this evening"])
    c = B.qa_cycle(datetime.date(2026, 10, 28), runtime=t, doc=doc)
    check("a report after the morning is not yet known", c["verdict_build"] is None and c["under_test_build"]["build"] == "77")
    docs[1]["qa"] = []
    json.dump(docs[1], open(os.path.join(t, "runner", "2026-10-29-changes.json"), "w"))
    c = B.qa_cycle(datetime.date(2026, 10, 29) + datetime.timedelta(days=4), runtime=t, doc=doc)
    check("a build whose evening passed with no report is not received; the lanes line says so",
          c["report_missing_build"]["build"] == "78" and c["under_test_build"] is None
          and B.qa_cycle_lines(c, datetime.date(2026, 11, 2), days=7)[0].endswith("report not received (due 10-28 evening)"))
body = "\n- Sprint: day 3 of 10\n- Releases: prod-3 runs 2.1.15\n- Ask: MH-3829 the URL?\nela: drop Sprint\nela: MH-3829 first\n\n> [!note]- copy\n"
out, unread = B.apply_meeting_guidance(body, [g.group(0) for g in B.MEETING_GUIDE_RX.finditer(body)] + ["ela: celebrate"])
check("his ela: lines drop and reorder a meeting's bullets and never go out themselves",
      out == "- Ask: MH-3829 the URL?\n- Releases: prod-3 runs 2.1.15" and unread == ["celebrate"])
check("the Slack form: bold, links and wiki links as Slack writes them",
      B.slack_form("**Ask** [thread](https://x.y/p1) [[lanes|the lanes]]") == "*Ask* <https://x.y/p1|thread> the lanes")
page = "# B\n\n## Scrum with the PM at 10:00\n\n- a\n\n## FYI\n\n- b\n"
check("a meeting's section is read from its heading to the next", B.meeting_section(page, "Scrum with the PM at 10:00").strip() == "- a")
sys.exit(1 if failures else 0)
