#!/usr/bin/env python3
"""The stage queue offline: the stage a lane list reaches, the action each ticket shape owes, the Epic roll-up."""
import datetime, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "stage"))
import stage as S  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

TODAY = datetime.date(2026, 10, 21)
ROSTER = {"people": [{"name": "Product Person", "area": "product"}, {"name": "Dev Person", "area": "ui"}]}
S.P.person_area = lambda roster, name: next((p["area"] for p in roster["people"] if p["name"] == name), None)

def rec(**kw):
    base = {"key": "MH-1", "summary": "s", "status": "Backlog", "issuetype": "Task", "lanes": [], "commits": [], "draft": [],
            "declared": {}, "evidence": None, "current": "", "assignee": "Dev Person", "gaps": []}
    base.update(kw); return base

old = [{"sha": "a", "date": "2026-04-30", "author": "dev"}]
check("prod outranks daily and qa", S.stage_of([{"lane": "qa-cn3"}, {"lane": "daily-tue"}, {"lane": "prod-3"}]) == "prod")
check("stage is the lane name's kind", S.stage_of([{"lane": "stage"}]) == "daily" and S.stage_of([]) == "none")
r = S.row_of(rec(status="Review", lanes=[{"lane": "prod-3"}], commits=old, draft=["x@1"]), ROSTER, 30, TODAY)
check("an open ticket whose fix sat on prod for the threshold owes a close", r["action"] == "close" and r["fix_age_days"] == 174)
r = S.row_of(rec(status="Review", lanes=[{"lane": "prod-3"}], commits=old, draft=["x@1"], evidence={"verdict": "fail"}), ROSTER, 30, TODAY)
check("a QA refutation blocks the close", r["action"] != "close")
r = S.row_of(rec(status="Review", assignee="Product Person", lanes=[{"lane": "prod-3"}], commits=old, draft=["x@1"]), ROSTER, 30, TODAY)
check("Review assigned to product is the sign-off gate, never nagged", r["action"] == "awaiting-product")
r = S.row_of(rec(status="In Progress", lanes=[{"lane": "qa-cn3"}], commits=[{"sha": "a", "date": "2026-10-20", "author": "dev"}], draft=["x@1"]), ROSTER, 30, TODAY)
check("a fix on a QA lane with the ticket before Review owes Fixed In and the transition", r["action"] == "reached-qa" and "transition" in r["dry_run"])
r = S.row_of(rec(status="Review", current="x@1.0.0+5", lanes=[{"lane": "daily-tue"}], commits=old, draft=["x@1"]), ROSTER, 30, TODAY)
check("a fix on daily with QA silent asks QA", r["action"] == "awaiting-qa")
r = S.row_of(rec(status="Review", declared={"declared": [{"value": "x@1"}]}), ROSTER, 30, TODAY)
check("a declared build no lane carries is declared-only", r["action"] == "declared-only")
r = S.row_of(rec(status="In Progress"), ROSTER, 30, TODAY)
check("In Progress with no commit asks where the change is", r["action"] == "no-fix")
r = S.row_of(rec(status="Backlog"), ROSTER, 30, TODAY)
check("Backlog with no fix owes nothing", r["action"] == "none")
r = S.row_of(rec(status="Done", lanes=[{"lane": "prod-3"}], commits=old), ROSTER, 30, TODAY)
check("a terminal ticket is done", r["action"] == "done")
r = S.row_of(rec(assignee="Dev Person", commits=[{"sha": "a", "date": "2026-04-01", "author": "someone else"}], status="In Progress", lanes=[{"lane": "prod-3"}], draft=["x@1"]), ROSTER, 30, TODAY)
check("the implementer is shown beside the assignee, not flagged", r["implementers"] == ["someone else"] and r["action"] == "close")

rows = [S.row_of(rec(key="MH-10", issuetype="Epic", status="Review"), ROSTER, 30, TODAY),
        S.row_of(rec(key="MH-11", parent="MH-10", status="Review", lanes=[{"lane": "prod-3"}], commits=old, draft=["x@1"]), ROSTER, 30, TODAY),
        S.row_of(rec(key="MH-12", parent="MH-10", status="Done"), ROSTER, 30, TODAY)]
S.roll_up_epics(rows)
check("an Epic whose children are all closed or closable owes a close", rows[0]["action"] == "close" and "1 close" in rows[0]["why"])
rows.append(S.row_of(rec(key="MH-13", parent="MH-10", status="Backlog"), ROSTER, 30, TODAY)); S.roll_up_epics(rows)
check("an Epic with an open child is the feature's head, owing nothing itself", rows[0]["action"] == "epic")

print("stage: all offline checks passed" if not failures else f"stage: {len(failures)} check(s) failed")
sys.exit(1 if failures else 0)
