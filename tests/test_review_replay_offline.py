#!/usr/bin/env python3
"""review replay, offline: each way a day's word can turn out wrong, read against later changes and lane reads."""
import datetime, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "review"))
import review as RV  # noqa: E402

failures = 0


def check(name, cond):
    global failures
    print(("ok   " if cond else "FAIL ") + name)
    failures += 0 if cond else 1


ev = lambda at, frm, to, by="Dev One": {"at": at, "field": "status", "from": frm, "to": to, "by": by}  # noqa: E731
cm = lambda at, by, text: {"at": at, "by": by, "text": text}  # noqa: E731
sure = [{"key": "MH-1", "reading": "sure 1: Review on a branch naming the key", "at": "2026-10-27T10:00:00.000+0800"},
        {"key": "MH-2", "reading": "sure 2: QA pass on 2.2.121", "at": "2026-10-27T10:00:00.000+0800"},
        {"key": "MH-3", "reading": "sure 5: Done after QA pass", "at": "2026-10-27T10:00:00.000+0800"}]
issues = {"MH-1": {"events": [ev("2026-10-27T15:00:00.000+0800", "Review", "In Progress")], "comments": []},
          "MH-2": {"events": [], "comments": [cm("2026-10-27T16:00:00.000+0800", "QA Person", "Failed on 2.2.122, the old code")]},
          "MH-3": {"events": [ev("2026-10-27T09:00:00.000+0800", "Done", "Reopened")], "comments": []}}
rows = RV.contradicted(sure, issues, {"qa person"})
check("a status moved back after a sure reading contradicts it", any(r["key"] == "MH-1" and "Review → In Progress" in r["now"] for r in rows))
check("a QA fail after a sure reading contradicts it", any(r["key"] == "MH-2" and "QA fail" in r["now"] for r in rows))
check("a change before the reading does not", not any(r["key"] == "MH-3" for r in rows))

page = """## The lanes this morning

| | prod-3 | QA-AWS3 |
|---|---|---|
| mediahub-backend | 2.1.32+263 ○ | ▲ 2.1.35+266 (was 2.1.34+265) ○ |
| UR Caller (unified-streaming) | 2.1.74+364 ○ | ▲ 2.1.77+367 (was 2.1.76+366) ○ |
| mediahub-frontend | 2.2.116+171 ○ | ▲ 2.2.122+177 (was 2.2.121+176) ○ |
"""
check("the ▲ cells are read with their lane and slug", RV.called_moves(page) == [
    ("QA-AWS3", "mediahub-backend", "2.1.35+266"), ("QA-AWS3", "unified-streaming", "2.1.77+367"), ("QA-AWS3", "mediahub-frontend", "2.2.122+177")])
snap = {"date": "2026-10-28", "rows": [{"lane": "qa-cn3", "service": "mediahub-backend", "version": "v2.1.34 build265 2026-10-26"},
                                       {"lane": "qa-cn3", "service": "unified-streaming", "version": "v2.1.78 build368 2026-10-28"},
                                       {"lane": "qa-cn3", "service": "mediahub-frontend", "version": "v2.2.122 build177 2026-10-27"}]}
m = RV.miscalled(page, snap)
check("an older version on the next read is a miscall; a newer one or the same is not",
      [r["said"] for r in m] == ["QA-AWS3 mediahub-backend moved to 2.1.35+266"])

me = "Owner Name"
acts = [{"n": 1, "text": "MH-4: ask Robin for the ruling", "drafted": "2026-10-27T09:55:00+0800"},
        {"n": 2, "text": "MH-5: ask Summer for the field names", "drafted": "2026-10-27T09:55:00+0800"}]
iss = {"MH-4": {"events": [], "comments": [cm("2026-10-26T10:00:00.000+0800", me, "Robin, which code?"),
                                           cm("2026-10-26T18:00:00.000+0800", "Robin Wu", "Use 0x81004009.")]},
       "MH-5": {"events": [], "comments": [cm("2026-10-26T10:00:00.000+0800", "Summer Chen", "Which names?"),
                                           cm("2026-10-26T12:00:00.000+0800", me, "Summer, the table is here.")]}}
n = RV.answered_nudges(acts, iss, me)
check("a nudge for someone whose answer came after the owner's last word is flagged; one still owed is not",
      [r["key"] for r in n] == ["MH-4"])

applied = [{"n": 1, "text": "MH-6: post the status", "applied": "2026-10-27T10:00:00+0800"},
           {"n": 2, "text": "MH-7: post the status", "applied": "2026-10-27T10:00:00+0800"},
           {"n": 3, "text": "MH-8: post the status", "applied": "2026-10-28T10:00:00+0800"}]
iss = {"MH-6": {"events": [], "comments": [cm("2026-10-27T10:00:05.000+0800", me, "Status: …"),
                                           cm("2026-10-27T11:00:00.000+0800", "Helm Lookout", "Fixed In set")]},
       "MH-7": {"events": [ev("2026-10-28T11:00:00.000+0800", "In Progress", "Review")], "comments": []},
       "MH-8": {"events": [], "comments": []}}
now = datetime.datetime(2026, 10, 29, 9, 0).astimezone(datetime.timezone(datetime.timedelta(hours=8)))
a = RV.applied_no_change(applied, iss, me, now)
check("an applied action answered only by the owner and Helm for a working day is flagged; a moved one and an open "
      "window are not", [r["key"] for r in a] == ["MH-6"])
check("Friday's window runs to Monday", RV.next_workday_end(datetime.datetime(2026, 10, 30, 10, 0)).date() == datetime.date(2026, 11, 2))
check("the summary line", RV.summary("2026-10-27", {"sure_contradicted": 0, "version_miscalled": 1, "nudge_answered": 0, "applied_no_change": 2})
      == "replay of 10-27: 0 sure readings contradicted, 1 version miscalled, 0 nudges already answered, 2 applied actions with no change")
sys.exit(1 if failures else 0)
