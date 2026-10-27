#!/usr/bin/env python3
"""ticket refresh, offline: each change read against the closed list, and the page updated in place."""
import datetime, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "ticket"))
import ticket as T  # noqa: E402

failures = 0


def check(name, cond):
    global failures
    print(("ok   " if cond else "FAIL ") + name)
    failures += 0 if cond else 1


ctx = {"key": "MH-1", "me": "Owner Name", "qa": {"qa person"}, "devs": {"dev one"}, "assignee": "Dev One", "status": "In Progress",
       "awaited": {"robin"}, "commit_keys": {"MH-1"}, "qa_pass": None, "fixed_in": None,
       "reporter": "", "ledger": {"builds": [], "lanes": set()}}
ev = lambda field, frm, to, by: {"type": "event", "field": field, "from": frm, "to": to, "by": by}  # noqa: E731
cm = lambda by, text: {"type": "comment", "by": by, "text": text}  # noqa: E731
R = lambda c, **kw: T.read_change(c, dict(ctx, **kw))  # noqa: E731

check("1: Review on a branch naming the key", R(ev("status", "In Progress", "Review", "Dev One"))[1:3] == ("sure 1: Review on a branch naming the key", True))
check("Review with no commit is unsure", not R(ev("status", "In Progress", "Review", "Dev One"), commit_keys=set())[2])
check("2: QA's version and verdict", R(cm("QA Person", "Retested on 2.2.121: pass"))[1:3] == ("sure 2: QA pass on 2.2.121", True))
check("a QA fail is still sure 2, read as fail", R(cm("QA Person", "Failed on 2.2.121, still the old code"))[1] == "sure 2: QA fail on 2.2.121")
check("3: Fixed In the carrying build", R(ev("Fixed In", None, "mediahub-frontend@2.2.121", "Helm Lookout"), fixed_in="same")[2])
check("Fixed In not matched is unsure", not R(ev("Fixed In", None, "x@1.0.0", "Dev One"), fixed_in="differs")[2])
check("4: an answer from whom the page waits on", R(cm("Robin Lead", "Yes, the same notice for both."))[1:3] == ("sure 4: answer from Robin Lead", True))
check("5: Done after a QA pass", R(ev("status", "Review", "Done", "QA Person"), qa_pass="2.2.121")[1] == "sure 5: Done after QA pass on 2.2.121")
check("6: progress from the assignee on In Progress", R(cm("Dev One", "Working on the field rename now."))[1:3] == ("sure 6: progress from Dev One", True))
check("a progress note with a question is unsure", not R(cm("Dev One", "Which code should the pool shortage use?"))[2])
check("a reopen is unsure", R(ev("status", "Done", "Reopened", "QA Person"))[1] == "unsure: moved back from Done to Reopened")
check("a status jump no rule covers is unsure", not R(ev("status", "To Do", "Done", "Dev One"))[2])
check("a new linked ticket is unsure", R(ev("Link", None, "MH-9", "Dev One"))[1] == "unsure: new linked ticket MH-9")
r = R(ev("assignee", "Dev One", "Owner Name", "QA Person"))
check("an assignment to the owner is addressed to him", r[3] and not r[2])
r = R(cm("Someone Else", "@Owner can you decide this?"))
check("a comment naming the owner is addressed to him", r[3] and not r[2])
check("his own change is a row, never an item", R(cm("Owner Name", "Asked the team."))[1:4] == ("yours", True, False))
check("a machine's label edit is no row", R(ev("labels", "", "release:mh-2.1", "Helm Lookout")) is None)
check("a field that moves with a status is no row", R(ev("resolution", None, "Done", "Dev One")) is None)
check("7: to QA in Review", R(dict(ev("assignee", "Dev One", "QA Person", "Dev One"), status_at="Review"))[1:3] == ("sure 7: to QA in Review", True))
check("7: to a developer in In Progress", R(dict(ev("assignee", "", "Dev One", "QA Person"), status_at="In Progress"))[2])
check("7: back to the reporter on Done", R(dict(ev("assignee", "QA Person", "Reporter Two", "QA Person"), status_at="Done"), reporter="Reporter Two")[2])
check("an assignment the status does not explain is unsure", not R(dict(ev("assignee", "", "QA Person", "Dev One"), status_at="Backlog"))[2])
led = {"builds": [{"service": "mediahub-backend", "version": "2.1.76", "build": 280, "lanes": ["qa-cn3"]}], "lanes": {"qa-cn3"}}
check("8: a developer names a version the ledger confirms", R(cm("Dev One", "Fixed in 2.1.76, deployed to QA."), ledger=led)[1:3]
      == ("sure 8: 2.1.76 carries the fix, ledger agrees", True))
check("8: or its build number", R(cm("Dev One", "It is in build 280 now"), ledger=led)[2])
check("a version the ledger does not hold is unsure", R(cm("Dev One", "Fixed in 2.1.77."), ledger=led)[1]
      == "unsure: Dev One names 2.1.77, a version not in the ledger")
check("a fix on QA while the ticket is Backlog disagrees", T.lane_mismatch({"qa-cn3"}, "Backlog") == "fix on QA-AWS3, ticket Backlog")
check("a fix on prod while In Progress disagrees", T.lane_mismatch({"prod-3"}, "In Progress") == "fix on prod-3, ticket In Progress")
check("a fix on QA while In Progress agrees", T.lane_mismatch({"qa-cn3"}, "In Progress") is None)
check("7: a To Do ticket routed to a developer", R(dict(ev("assignee", "", "Dev One", "Owner Two"), status_at="To Do"))[2])
check("a developer reporting a failure is neither progress nor evidence", R(cm("Dev One", "Still fails on 2.1.76."), ledger=led)[1:3]
      == ("unsure: a developer reports it still fails", False))
check("the furthest lane decides: QA and prod, In Progress", T.lane_mismatch({"qa-cn3", "prod-3"}, "In Progress") == "fix on prod-3, ticket In Progress")
check("on prod while Review with no QA verdict", T.lane_mismatch({"prod-3"}, "Review") == "fix on prod-3, ticket Review with no QA verdict"
      and T.lane_mismatch({"prod-3"}, "Review", True) is None)
check("a comment row is its first sentence", T.first_sentence("Done on QA. Next I look at prod.") == "Done on QA."
      and T.first_sentence("word " * 80).endswith(" …"))
check("the page names whom it waits on", T.awaited("**Real status.** Waiting on Robin's ruling.\n\n## Next\n\n- **Then Summer**: x\n") == {"robin"})

page = ("# MH-1: t — x\n\n**Real status.** Jira says Review, assigned to yulong. In fact it cannot work.\n\n## Timeline\n\n"
        "| date | what happened | source |\n|---|---|---|\n| 04-09 | filed | MH-1 |\n\n**Why it happened.** y\n\n## Next\n\n- z\n")
now = datetime.datetime(2026, 10, 28, 9, 0).astimezone()
rows = [{"date": "10-27", "change": "Robin: same | notice", "source": "comment", "reading": "sure 4: answer from Robin", "sure": True},
        {"date": "10-27", "change": "status: Review → In Progress", "source": "changelog", "reading": "unsure: moved back", "sure": False}]
out = T.update_page(page, rows, "Jira says In Progress, assigned to Summer.", now, now)
check("the page gains seen-until in its front matter", out.startswith('---\nseen-until: "2026-10-28T09:00:00'))
check("an older table gains the reading column, its rows an empty cell", "| date | what happened | source | reading |" in out
      and "|---|---|---|---|" in out and "| 04-09 | filed | MH-1 |  |" in out)
check("each change is a row under the old ones, pipes escaped", "| 10-27 | Robin: same \\| notice | comment | sure 4: answer from Robin |" in out
      and out.index("04-09") < out.index("10-27"))
check("Real status: the Jira facts replaced, the judgement kept, the refresh noted",
      "**Real status.** Jira says In Progress, assigned to Summer. In fact it cannot work. *(refreshed 10-28 09:00: 2 changes, 1 unsure)*" in out)
check("the rest of the page stays as written", "**Why it happened.** y\n\n## Next\n\n- z\n" in out)
again = T.update_page(out, [], "Jira says In Progress, assigned to Summer.", now, now)
check("a second refresh replaces its note and its watermark, never stacks them", again.count("refreshed") == 1 and again.count("seen-until") == 1)
check("a prod or customer ticket is flagged", T.prod_or_customer("FB-1", {}) and T.prod_or_customer("MH-1", {"labels": ["prod-3"]})
      and not T.prod_or_customer("MH-1", {"labels": ["release:mh-2.1"], "summary": "UX"}))
check("routed means he set the assignee to someone else", T.routed_keys([{"key": "MH-1", "events": [ev("assignee", "", "Dev One", "Owner Name")]},
                                                                      {"key": "MH-2", "events": [ev("assignee", "", "Owner Name", "Owner Name")]}], "Owner Name") == {"MH-1"})
sys.exit(1 if failures else 0)
