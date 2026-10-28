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
routed_then_own = [{"key": "MH-6", "summary": "routed, then his own comment", "status": "To Do", "assignee": "Dev E",
                    "events": [{"field": "assignee", "to": "Dev E", "by": "Owner", "at": "2026-10-23T09:00:00.000+0000"}],
                    "comments": [{"by": "Owner", "at": "2026-10-24T09:00:00.000+0000", "text": "Context for you: logs attached."}]}]
w6 = B.ticket_waits(routed_then_own, "Owner", set(), set(), now)
check("a ticket he routed and then commented on himself still waits on the assignee",
      len(w6) == 1 and w6[0]["who"] == "Dev E" and w6[0]["threshold"] == 2 and w6[0]["due"])
import tempfile  # noqa: E402
with tempfile.TemporaryDirectory() as t:
    os.makedirs(os.path.join(t, "parked"))
    open(os.path.join(t, "parked", "p.md"), "w").write('---\ntitle: "RVF for v3 Packs"\nstatus: "parked"\nwaits-on: "the Pack team, in its thread"\n'
                                                    'parked: "2026-10-22"\nwake: "a reply there, or FB-7 moving"\n---\n# RVF\n')
    pn = B.parked_notes(t)
check("a parked note is read from its front matter", pn == [{"note": "parked/p.md", "title": "RVF for v3 Packs", "waits_on": "the Pack team, in its thread",
                                                        "parked": "2026-10-22", "wake": "a reply there, or FB-7 moving"}])
quiet = B.parked_row(pn[0], [], {}, "Owner", now)
check("a parked note with no movement is due after three working days, addressed to whom it waits on",
      quiet["kind"] == "parked" and quiet["due"] and quiet["working_days_silent"] == 3 and quiet["who"] == "the Pack team, in its thread"
      and quiet["checked"] == ["FB-7"] and quiet["woke"] == [])
same_day = [{"key": "FB-7", "events": [{"field": "status", "from": "Open", "to": "In Progress", "by": "Dev F", "at": "2026-10-22T15:00:00.000+0000"}], "comments": []}]
check("what happened on the day it was parked does not wake it", B.parked_row(pn[0], same_day, {}, "Owner", now)["woke"] == [])
moved = [{"key": "FB-7", "events": [{"field": "status", "from": "Open", "to": "In Progress", "by": "Dev F", "at": "2026-10-26T09:00:00.000+0000"}], "comments": []}]
r = B.parked_row(pn[0], moved, {}, "Owner", now)
check("a status change on the wake's ticket wakes it, and a woken note is not a nudge", len(r["woke"]) == 1 and r["woke"][0]["ref"] == "FB-7" and not r["due"])
own = [{"key": "FB-7", "events": [], "comments": [{"by": "Owner", "at": "2026-10-27T09:00:00.000+0000", "text": "Any news?"},
                                                  {"by": "Automation for Jira", "at": "2026-10-27T10:00:00.000+0000", "text": "x"}]}]
r = B.parked_row(pn[0], own, {}, "Owner", now)
check("his own comment or a machine's does not wake it, and his restarts the count", r["woke"] == [] and r["working_days_silent"] == 1 and not r["due"])
link = "https://team.slack.com/archives/C1/p1761000000000100"
n2 = dict(pn[0], wake=f"a reply on {link}")
th = {link: {"messages": [{"ts": "1761000000.000100", "user": "Owner", "text": "draft"},
                          {"ts": str(now.timestamp() - 3600), "user": "Pack Lead", "text": "We can test Friday"}]}}
r = B.parked_row(n2, [], th, "Owner", now)
check("a reply in the wake's thread wakes it", r["checked"] == [link] and len(r["woke"]) == 1 and r["woke"][0]["source"] == "slack")
check("a bare parked date is that day's end", B.parked_since("2026-10-22").day == 23 and B.parked_since("2026-10-22 15:04").hour == 15)
logged = [{"key": "MH-7", "change": "Dev F: Can you decide the code?", "reading": "unsure: comment from Dev F, a question", "sure": False,
           "addressed_to_owner": True, "by": "Dev F", "pass_at": "2026-10-28T06:30:00+08:00", "prod_or_customer": True},
          {"key": "MH-7", "change": "status: Review → In Progress by QA", "reading": "unsure: moved back from Review to In Progress", "sure": False,
           "addressed_to_owner": False, "pass_at": "2026-10-28T06:30:00+08:00"},
          {"key": "MH-8", "change": "assignee: a → b → c", "reading": "unsure: reassigned 3 times in a day", "sure": False,
           "addressed_to_owner": False, "pass_at": "2026-10-28T06:30:00+08:00"},
          {"key": "MH-9", "change": "x", "reading": "sure 7: to QA in Review", "sure": True, "addressed_to_owner": False, "pass_at": "2026-10-28T06:30:00+08:00"},
          {"key": "MH-10", "change": "y", "reading": "unsure: z", "sure": False, "addressed_to_owner": False, "pass_at": "2026-10-20T06:30:00+08:00"}]
ti = {i["key"]: i for i in B.tracked_items(logged, now - datetime.timedelta(hours=24))}
check("one tracked item per ticket; addressed to him is C with who said what", ti["MH-7"]["class"] == "C" and ti["MH-7"]["first_line"] == "Dev F: Can you decide the code?"
      and ti["MH-7"]["rows"] == 2 and ti["MH-7"]["prod_or_customer"])
check("otherwise D, saying what ela could not place", ti["MH-8"]["class"] == "D" and ti["MH-8"]["first_line"] == "ela could not place: reassigned 3 times in a day")
check("sure rows and rows outside the window are not items", "MH-9" not in ti and "MH-10" not in ti)
pg = lambda *hs: "# B\n\n## Needs you\n\n" + "".join(f"### {i}. {h}\n\nfacts\n\n" for i, h in enumerate(hs, 1)) + "## FYI\n\n### not an item\n"  # noqa: E731
cr = B.carried([pg("MH-1: a", "Nobody owns X"), pg("MH-1: a, again", "Nobody owns X", "MH-9: b"), pg("MH-2: c"),
                pg("MH-1: a", "Nobody owns X", "MH-2: c, still")])
check("an item's mornings count back while it stays under Needs you, by key or by heading",
      cr == {"MH-1": 1, "nobody owns x": 1, "MH-2": 2})
cr = B.carried([pg("MH-1: a"), pg("MH-1: b"), pg("MH-1: c")])
check("the third morning is counted", cr == {"MH-1": 3})
pk = lambda *its: "## Needs you\n\n" + "".join(f"### {i}. {h}\n{f}\n- x\n\n" for i, (h, f) in enumerate(its, 1))  # noqa: E731
cr = B.carried([pk(("Device APIs, a week without lanes", "MH-4 · MH-5 · High")),
                pk(("Device APIs: the wrong team", "MH-5 · MH-6 · High"), ("Nobody owns X", "no ticket"))])
check("a retitled item sharing a key with its facts line is the same item; a keyless one goes by heading",
      cr == {"MH-5": 2, "nobody owns x": 1})
sys.exit(1 if failures else 0)
