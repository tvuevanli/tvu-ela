#!/usr/bin/env python3
"""QA today and Dev today as posted, against the reference shapes approved on 2026-10-30
(<reports>/runner/actions/2026-10-30/slack-v2.md): versions in a code block, one line a row, P1/P2 and the dev
groups as headers, age as "7d", "No ticket" for a row without one, "⚠ no steps", no chat words as a row; the vault's
form as Markdown tables."""
import datetime, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "testlist"))
import testlist as TL  # noqa: E402

TL._ROSTER = {}                                             # names as they come; the roster is the site's
FIX = os.path.join(ROOT, "tests", "fixtures", "testlist-slack")
failures = []
def check(name, cond, got=None):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)
        if got is not None:
            print(got)

U = TL.JIRA_URL
def row(key, title, prio, why, age, steps="Open the page and look.", also=(), rid=None):
    return {"id": rid or key, "ticket": key, "url": U + key if key else None, "also": list(also), "title": title, "priority": prio,
            "how_to_verify": steps, "auto": False, "ela_saw": None, "reason": "carried", "why": why, "age": age}

AT = datetime.datetime(2026, 10, 30, 8, 30).astimezone()
out = {"shown": "QA-AWS3", "lane_label": "79", "kind": "qa"}
plan = {"more": 61, "versions": [("mediahub-backend", "2.1.37"), ("mediahub-frontend", "2.2.124"), ("UR Caller", "2.1.79"),
                                 ("unified-media-frontend", "3.0.39"), ("unified-media-backend", "1.0.286"),
                                 ("media bundle", "mh2.1@qa-q28")],
        "rows": [row("MH-3756", "[NDTV] NDTV audio-only profile in multi-profile HLS", "P1", "customer incident (NDTV)", 7, "steps unknown"),
                 row("MH-3771", "[App] HTML source input via MQTT proxy", "P1", "re-test: failed on 2.1.36", 7, also=["MH-3772"]),
                 row("WF-476", "Multiviewer category in MM Observe", "P1", "Jira High, 2 builds old", 7),
                 row("MH-3808", "Auth gaps on groupAttr (login + group owner)", "P1", "Jira High, the train leaves within a working day", 3),
                 row("MH-3820", "Preview Quality admin switch", "P1", "Jira High, 2 builds old", 2),
                 row("MH-3802", "ISSP as MPEG-TS on SRT/UDP source", "P2", "the rest, 2 builds old", 3),
                 row(None, "Scheduler extension updates the destination end time", "P2", "the rest, 2 builds old", 7, rid="nt-0a1b2c3d"),
                 row(None, "Backend nightly fixes (orderItem, bindDestinations)", "P2", "the rest, 2 builds old", 7, "", rid="nt-1a1b2c3d"),
                 row(None, "Drive signed requests use POST", "P2", "the rest, 2 builds old", 3, rid="nt-2a1b2c3d"),
                 row(None, "webemulator wp response envelope", "P2", "the rest, 2 builds old", 3, "steps unknown", rid="nt-3a1b2c3d"),
                 {"id": "https://x.slack.com/archives/C1/p1", "ticket": None, "url": "https://x.slack.com/archives/C1/p1", "also": [],
                  "title": "", "priority": "—", "how_to_verify": "", "auto": False, "chat": True, "reason": "ask from Ann to Bo in #qa"}]}
qa = TL.today_text(out, plan, AT)
want = open(os.path.join(FIX, "qa-today.txt"), encoding="utf-8").read().rstrip("\n")
check("QA today is the reference text, line for line", qa == want,
      "\n".join(f"{'  ' if a == b else '≠ '}{a!r}\n  {b!r}" for a, b in zip(qa.split("\n"), want.split("\n"))))
check("no nt- id, no (was …), no ⇒ in Slack", "nt-" not in qa and "(was" not in qa and "⇒" not in qa)
check("an ask with no ticket is no row", "ask from" not in qa and "slack.com" not in qa)
tab = TL.today_table(out, plan)
check("the vault form is Markdown tables", "| service | version |" in tab and "| # | P | ticket | title | why | age | steps |" in tab
      and "| 7 | P2 | no ticket | Scheduler extension updates the destination end time | — | 7d | yes |" in tab, tab)
check("the vault form names a chat ask by its thread, not its words", "[chat ask](https://x.slack.com/archives/C1/p1)" in tab, tab)

def drow(key, who, title, reason, **more):
    return {"id": key, "ticket": key if key and key.startswith("MH-") else None, "url": U + key if key else key, "who": who,
            "title": title, "reason": reason, **more}

dplan = {"more": 28, "rows": [
    drow("MH-3569", "Wilson Wang", "Fox YouTube source not following live", "overdue since 2026-09-08", age=52),
    drow("MH-3510", "Wilson Wang", "[App] Call HTML module API instead of UR docker", "overdue since 2026-09-16", age=44),
    drow("MH-3166", "Andy Zhao", "Operation log default range 30 days", "blocked"),
    drow("MH-3650", "Andy Zhao", "Rule 2 (stop unused inputs) takeover", "on hold"),
    drow("nt-9a9b9c9d", "—", "Mediahub Backend: bindDestination takes @RequestBody", "build 79 change with no ticket", build="79"),
    drow("nt-8a9b9c9d", "—", "UR Caller: null guard on the task", "build 79 change with no ticket", build="79"),
    drow("https://x.slack.com/archives/C1/p2", "Bo", "", "ask from Ann in #prj_dev_mediahub", chat=True),
    drow("MH-3779", "Etan Yang", "TVU → Jira callback on schedule changes", "moved In Progress → Review")]}
dev = TL.dev_text("2.1", dplan, AT)
want = open(os.path.join(FIX, "dev-today.txt"), encoding="utf-8").read().rstrip("\n")
check("Dev today is the reference text, line for line", dev == want,
      "\n".join(f"{'  ' if a == b else '≠ '}{a!r}\n  {b!r}" for a, b in zip(dev.split("\n"), want.split("\n"))))
check("Dev today: no nt- id, no 'overdue since', no chat words", "nt-" not in dev and "overdue since" not in dev and "ask from" not in dev)
dtab = TL.dev_table(dplan)
check("the dev vault form is a Markdown table", dtab.startswith("| group | developer | ticket | title | age · why |")
      and "| Overdue | Wilson Wang | [MH-3569](" in dtab and "| 52d |" in dtab, dtab)
sys.exit(1 if failures else 0)
