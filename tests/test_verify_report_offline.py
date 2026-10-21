#!/usr/bin/env python3
"""The verification report rendered from a run directory: verdict from the cases and the gate, every section present."""
import json, os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "verify"))
import verify as V  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

run = tempfile.mkdtemp(); out = tempfile.mkdtemp()
json.dump({"key": "MH-1", "summary": "s", "type": "Task", "status": "Review", "asked": "the end defaults to start + 60 min", "commits": [{"sha": "abcdef12", "subject": "x"}], "later": [{"key": "MH-2", "what": "replaced the control"}]}, open(os.path.join(run, "ticket.json"), "w"))
json.dump([{"id": "T1", "goal": "g1", "source": "description"}, {"id": "T2", "goal": "g2", "source": "commit", "superseded_by": "MH-2"}], open(os.path.join(run, "plan.json"), "w"))
env = {"lane": "prod-3", "verdict": "proven", "panel": "TVU MediaHub (ENV: MediaHubProd3)", "sections": [{"env": "MediaHubProd3", "lane": "prod-3"}],
       "compare": [{"slug": "mediahub-frontend", "panel": "v2.2.111 build162", "map": "v2.2.111 build162", "verdict": "match"}]}
json.dump(env, open(os.path.join(run, "env.json"), "w"))
json.dump({"result": [{"id": "T1", "action": "open", "observed": "17:00", "result": "pass"}, {"id": "T2", "action": "hover", "observed": "gone", "result": "n/a"}]}, open(os.path.join(run, "cases.json"), "w"))
page, verdict = V.render("MH-1", run, out)
check("pass with an n/a is a pass", verdict == "pass")
check("the verdict strip names the lane and the frontend build", "MediaHubProd3" in page and "v2.2.111 build162" in page)
check("every section renders", all(h in page for h in ("Target ticket", "Goals", "Environment proof", "Results")))
check("a superseded goal names its ticket", "superseded by MH-2" in page)
check("the later change is on the ticket table", "MH-2: replaced the control" in page)
check("the page carries no ticket link to itself and a private footer", "not linked from the ticket" in page)
json.dump({"result": [{"id": "T1", "action": "open", "observed": "16:00", "result": "fail"}]}, open(os.path.join(run, "cases.json"), "w"))
check("one failing case fails the verdict", V.render("MH-1", run, out)[1] == "fail")
env["verdict"] = "unproven: no ENV"; json.dump(env, open(os.path.join(run, "env.json"), "w"))
check("an unproven gate discards the results", V.render("MH-1", run, out)[1] == "unproven")
print("verify report: all offline checks passed" if not failures else f"verify report: {len(failures)} check(s) failed")
sys.exit(1 if failures else 0)
