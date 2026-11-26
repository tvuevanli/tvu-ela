#!/usr/bin/env python3
"""today.md's head and judged facts, offline (vault plan 2026-11-24, steps 1, 2 and 4): a fact alone is not enough.
The head is at most five lines ending in "Start with …"; each fact line is a judgment with a Do and one link, or it is
folded; the verb refuses a line that only repeats its fact; the links row stays at the foot."""
import datetime, os, sys, types
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "vault"))
import vault as V  # noqa: E402
import head as H  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

TUE = datetime.date(2026, 11, 24)
FACT = "QA's verdict build, QA-AWS3 build 100, is partial: 10 pass and 2 fail, both in MH-4048."
JUDGED = ("Build 100 can still move: its 2 failures are MH-4048 (a destination with a saved CSC preset will not start "
          "when destination CSC is switched off), and the switch is on everywhere (mx-service default "
          "csc.destination.enabled=true). Do: move build 100 when the rest is ready; keep the switch on until the "
          "owner's fix lands (they plan to drop the switch).")

def note(path, props, body):
    n = types.SimpleNamespace(path=path, props=props, body=body, title=path, front_lines=[])
    return n

changes = note("reference/days/2026/2026-11-24-changes.md", {"type": "day", "kind": "changes", "date": "2026-11-24"},
               "# What changed\n\n## Releases and versions\n\nThree lanes moved, all mediahub-frontend, and only the QA-AWS3 build came from release2.1.\n\n"
               "## Docker services\n\nProd 3's bundle is now MediaHub 2.1.19 (UR/J2N Prod 9).\n\n## QA\n\n" + FACT + "\n")
brief = note("reference/days/2026/2026-11-24-brief.md", {"type": "day", "kind": "brief", "date": "2026-11-24"},
             "# Morning brief\n\n## Needs you\n\n### 1. Two fixes headed for Prod 3 still have no Fixed In\n\nMH-4047 · x\n"
             "- **Do:**\n- [ ] apply 1 — MH-4047 Fixed In bs_detector 1.0.8\n\n### 2. daily-wed's mediahub-frontend is an untested feature-branch build\n"
             "- **Do:**\n- hold mediahub-frontend at 2.2.132 this week\n\n> [!note]- Also noticed\n> ### 3. Reuters thing\n> - **Do:**\n> - assign it\n")
proj = note("projects/pack-mh-live/pack-mh-live.md", {"type": "project"}, "")
proj.facts = {"key": "pack-mh-live", "days": 13, "deadline": datetime.date(2026, 12, 7), "path": proj.path,
              "step": "Confirm the pack's encoder settings with the media lead", "overdue": False}
notes = [changes, brief, proj]
now = datetime.datetime(2026, 11, 24, 12, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))

# the worked example: the verb accepts the judgment and refuses the bare fact
check("the owner's worked example passes the line check", H.check_line(JUDGED, H.FACT_WORDS, FACT) is None)
check("the bare fact is refused: no Do", "Do:" in (H.check_line(FACT, H.FACT_WORDS, FACT) or ""))
check("a Do on the fact itself is refused: the meaning repeats the fact",
      "repeats" in (H.check_line(FACT + " Do: look at it today.", H.FACT_WORDS, FACT) or ""))
check("two links are refused: one link to the evidence",
      "links" in (H.check_line("Build 100 can still move now. Do: see [a](http://a) and [b](http://b).", H.FACT_WORDS) or ""))
check("a line with no link and no ticket key is refused", "no link" in (H.check_line("The build can still move today. Do: move it.", 80) or ""))
check("a Start line must begin `Start with `", H.check_start("Begin with X.") and H.check_start("Start with moving build 100.") is None)

# with no judgment: ela's own head from the candidates that carry their Do, every fact folded
desk = {"kpi": [{"kind": "route", "key": "MH-4090", "title": "a new ticket", "hours": 6}]}
page = V.today_page(TUE, notes, desk)
head = page.split("## In short", 1)[1].split("## Facts", 1)[0].strip().splitlines()
check("the head sits above Facts", page.index("## In short") < page.index("## Facts"))
check("the head is at most five lines and ends in `Start with …`", 1 < len(head) <= 5 and head[-1].startswith("Start with "))
check("ordered by urgency: the 4-hour routing breach first, then the morning page's items in rank",
      "MH-4090" in head[0] and "Fixed In" in head[1] and "daily-wed" in head[2])
check("the first step is the first line's Do", head[-1] == "Start with route MH-4090 to its owner now.")
check("the morning page's folded items are not head candidates", "Reuters" not in page)
check("each head line carries a Do", all(" Do: " in l for l in head[:-1]))
check("the morning page's box is not part of the Do", "Do: MH-4047 Fixed In bs_detector 1.0.8" in head[1] and "apply 1" not in head[1])
check("a project's step is its own words", "Do: next step: Confirm the pack's encoder settings" in head[3])
check("unjudged facts are folded, none shown bare", "> [!note]- 3 facts not judged yet" in page and "\n- **QA:**" not in page)
check("the inputs are left for the sync to keep", desk["head_inputs"]["date"] == "2026-11-24" and len(desk["head_inputs"]["facts"]) == 3)

# a session's answer, judged by the verb, then rendered
inp = desk["head_inputs"]
qa = next(f["id"] for f in inp["facts"] if f["label"] == "QA")
others = [f["id"] for f in inp["facts"] if f["id"] != qa]
answer = {"head": [{"id": "kpi-route-MH-4090", "line": "MH-4090 has waited 6 hours for an owner, past the routing promise. Do: route it now."},
                   {"id": qa, "line": "Build 100 can still move: both failures are one known MH-4048 case. Do: move it when the rest is ready."},
                   {"id": "nope", "line": "x"}],
          "start": "Start with routing MH-4090.",
          "facts": {qa: JUDGED, others[0]: None, others[1]: "Releases moved."}}
state, refused = H.judge(inp, answer, {})
check("the verb refuses an unknown id and a fact line without a Do, keeps the rest",
      set(refused) == {"nope", others[1]} and state["judged"][qa] == JUDGED and state["judged"][others[0]] is None)
check("the judgment is not stale against its inputs; new inputs make it stale",
      not H.stale(inp, state) and H.stale(dict(inp, sig="other"), state))
page2 = V.today_page(TUE, notes, {"kpi": desk["kpi"], "head": state})
head2 = page2.split("## In short", 1)[1].split("## Facts", 1)[0].strip().splitlines()
check("the stored head replaces ela's own, its Start line last",
      head2 == ["- " + answer["head"][0]["line"], "- " + answer["head"][1]["line"], "Start with routing MH-4090."])
facts2 = page2.split("## Facts", 1)[1].split("## Needs you", 1)[0]
check("the worked example renders as the QA fact's line", f"- **QA:** {JUDGED}" in facts2)
check("the bare fact is not shown outside the fold", FACT not in facts2.split("> [!note]-")[0])
check("the facts without a judgment are folded under one line", "> [!note]- 2 more facts" in facts2)
check("yesterday's judgment is not today's", "Start with route MH-4090" in V.today_page(TUE + datetime.timedelta(days=1), notes, {"kpi": desk["kpi"], "head": state}))
check("the links row stays at the foot", page2.rstrip().splitlines()[-1].startswith("[[manual|manual]] · [[reference/days/2026/2026-11-24-changes|what changed]]")
      and page2.rstrip().splitlines()[-3] == "---")

# the word budget below the head: judged facts fold from the end, never below three
changes4 = note(changes.path, changes.props, changes.body + "\n## Tickets\n\n22 tickets moved.\n")
notes4 = [changes4, brief, proj]
d4 = {"kpi": desk["kpi"]}
V.today_page(TUE, notes4, d4)
inp = d4["head_inputs"]
long = {f["id"]: "This changes what you can ship this week because " + " ".join(["word"] * 40) + ". Do: read MH-1 first."
        for f in inp["facts"]}
many = dict(state, judged=long)
crowded = V.today_page(TUE, notes4, {"kpi": desk["kpi"], "head": many}, [{"id": f"keys:MH-{i}", "text": f"MH-{i}: " + " ".join(["word"] * 17) + ".", "first": "2026-11-24"} for i in (1, 2, 3)])
cf = crowded.split("## Facts", 1)[1].split("## Needs you", 1)[0]
check("over the budget, judged facts fold from the end, three stay", cf.split("> [!note]-")[0].count("\n- **") == 3 and "> [!note]- 1 more fact" in cf)

# the KPI rows from the fact store, read from disk only
import json, tempfile  # noqa: E402
with tempfile.TemporaryDirectory() as rt:
    d = os.path.join(rt, "facts", "jira", "queries"); os.makedirs(d)
    sys.path.insert(0, os.path.join(os.path.dirname(V.HERE), "brief"))
    import brief as B  # noqa: E402
    json.dump({"jql": B.PROJECT + B.Q["triage"], "issues": [
        {"key": "MH-1", "fields": {"summary": "old", "created": "2026-11-24T06:00:00+08:00"}},
        {"key": "MH-2", "fields": {"summary": "new", "created": "2026-11-24T10:30:00+08:00"}}]}, open(os.path.join(d, "a.json"), "w"))
    json.dump({"jql": B.PROJECT + B.Q["yours"], "issues": [
        {"key": "MH-3", "fields": {"summary": "s", "status": {"name": "In Progress"}, "updated": "2026-11-22T12:00:00+08:00"}},
        {"key": "MH-4", "fields": {"summary": "b", "status": {"name": "Blocked"}, "updated": "2026-11-20T12:00:00+08:00"}}]}, open(os.path.join(d, "b.json"), "w"))
    rows = H.kpi_rows(rt, now)
check("KPI: unowned past 4 hours, In Progress on him past 24; a fresh ticket and a Blocked one are not breaches",
      sorted((r["kind"], r["key"], r["hours"]) for r in rows) == [("route", "MH-1", 6), ("update", "MH-3", 48)])

print("today head: all offline checks passed" if not failures else f"today head: {len(failures)} failed")
sys.exit(1 if failures else 0)
