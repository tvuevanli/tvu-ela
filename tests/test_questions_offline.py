#!/usr/bin/env python3
"""Open team questions, offline (ADR 0016): read from a hand-written meeting note, an older note in the verb's form and
a project page; merged by ticket and meaning; closed by the ticket's outcome, by his tick and by his `ela:` line, never
by age; the standing page and today's line; the ask after three meetings, with its draft."""
import datetime, json, os, re, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
sys.path.insert(0, os.path.join(ROOT, "skills", "brief"))
import questions as Q  # noqa: E402
import vault as V  # noqa: E402

failures = 0


def check(name, cond):
    global failures
    print(("ok   " if cond else "FAIL ") + name)
    failures += 0 if cond else 1


J = "https://j/browse/"
OLD = f"""---
title: "Team sync · Wed 2026-11-11"
type: "meeting"
date: "2026-11-11"
source: "vault"
---

# Team sync · Wed 2026-11-11

## To raise

- [ ] [MH-3752]({J}MH-3752) — CN Prod2 to backend 2.1.42 / frontend 2.2.128: target date? · CN release lead, UR lead
- [ ] [MH-2564]({J}MH-2564) — async graph submissions, which fixes three open bugs: when? · the owner, UR lead
- [ ] [MH-3975]({J}MH-3975) — 80 Mbps SRT ingress drops (due 11-12): who verifies tvu_live_transmit 1.0.25? · PM lead
- [ ] This week's deploy — what goes in, who cuts the build, which day to Prod 3? · QA lead, PM lead

## Ruled

### 2026-11-11

- [MH-3752]({J}MH-3752) — CN Prod2 to backend 2.1.42 / frontend 2.2.128: target date? · CN release lead, UR lead · no change: raised again next meeting
"""
HAND = f"""---
title: "Team sync · Thu 2026-11-12"
type: "meeting"
date: "2026-11-12"
source: "vault"
---

# Team sync · Thu 2026-11-12

## 2. CN vs COM

- [ ] What must be on CN for 11/21, and what is the date to bring CN Prod2 to 2.1.42+ ([MH-3752]({J}MH-3752))? · CN release lead, UR lead
- [ ] Is Graphics Overlay in scope for CN by 11/21, or COM only? · the team

## 3. Amazon POC — [FB-10757]({J}FB-10757)

- [ ] Who re-tests 80 Mbps on 1.0.25, and when? · PM lead, field engineer
- [x] Rule [MH-3847]({J}MH-3847) Q1: lift the cap to 70 for 1080p too? · PM lead

## If time allows

- [ ] This week's deploy: build 91 is on QA. What goes to Prod 3, and on which day? [MH-3909]({J}MH-3909) is still In Progress. · QA lead, PM lead
- [ ] [MH-2564]({J}MH-2564) async graph submissions (Backlog), which would fix [MH-3954]({J}MH-3954), [MH-3934]({J}MH-3934) and [MH-2277]({J}MH-2277): when? · the owner, UR lead
- [ ] Owners for [MH-3976]({J}MH-3976), [MH-3959]({J}MH-3959) (billing), [MH-3584]({J}MH-3584) · PM lead
"""
PROJECT = """---
title: "MH-3984 · Destination CSC"
type: "project"
---
# MH-3984 · Destination CSC

## Open questions

- [ ] Who takes orchestration and the destination UI? · ela proposes: the orchestration lead
- [x] Answered already?
"""

check("lead keys: a list that opens the line needs every key; a line about one ticket is that ticket",
      Q.lead_keys("Owners for MH-1, MH-2 (billing), MH-3 and MH-4 / MH-5? · PM lead") == ["MH-1", "MH-2", "MH-3", "MH-4", "MH-5"]
      and Q.lead_keys("MH-2564 async, which would fix MH-3954, MH-3934 and MH-2277: when?") == ["MH-2564"])
check("who is what follows the last ` · `; a proposal is neither question nor who",
      Q.split_who("Who takes it? · ela proposes: the lead") == ("Who takes it?", None)
      and Q.split_who("Date for the deployment · release lead") == ("Date for the deployment", "release lead"))
check("a note's meeting is its file name less its date, matched to the book's key either way",
      Q.audience("meetings/20261112-sync-eng-qa.md", ["sync-eng-qa-ux"]) == "sync-eng-qa-ux"
      and Q.audience("meetings/2026-11-17-sync-eng-qa-ux.md", ["sync-eng-qa-ux"]) == "sync-eng-qa-ux")

with tempfile.TemporaryDirectory() as t:
    vault, reports, facts = (os.path.join(t, x) for x in ("vault", "reports", "facts"))
    for d in ("meetings", "projects"):
        os.makedirs(os.path.join(vault, d))
    os.makedirs(os.path.join(facts, "jira", "issues")); os.makedirs(os.path.join(reports, "ela"))
    def issue(key, status="Backlog", who=None, comments=()):
        json.dump({"key": key, "fields": {"status": {"name": status}, "assignee": {"displayName": who} if who else None,
                   "created": "2026-10-01T10:00:00.000+0800"}, "comments": list(comments)},
                  open(os.path.join(facts, "jira", "issues", f"{key}.json"), "w"))
    for k in ("MH-3752", "MH-2564", "MH-3975", "MH-3909", "MH-3847", "MH-3976", "MH-3959", "MH-3584", "MH-3984"):
        issue(k, "In Progress" if k == "MH-3752" else "Backlog", "CN release lead" if k == "MH-3752" else None)
    json.dump({"issues": [{"fields": {"assignee": {"displayName": "The Owner"}}}]}, open(os.path.join(facts, "jira", "owner.json"), "w"))
    seed = os.path.join(t, "sync-eng-qa-ux.md")
    open(seed, "w").write(OLD)
    hand = os.path.join(vault, "meetings", "20261112-sync-eng-qa.md")
    open(hand, "w").write(HAND)
    open(os.path.join(vault, "projects", "mh-3984-destination-csc.md"), "w").write(PROJECT)
    tz = datetime.datetime.now().astimezone().tzinfo
    now = datetime.datetime(2026, 11, 12, 10, 0, tzinfo=tz)
    os.utime(hand, (now.timestamp() - 600, now.timestamp() - 600))
    book = [{"key": "sync-eng-qa-ux", "name": "Team sync", "weekdays": ["Tue", "Thu"], "time": "", "enabled": False}]
    state, done = V.questions_pass(vault, reports, facts, now, book, "https://j", seeds=[seed])
    qs = state["questions"]
    by = {r["lead"][0] if r["lead"] else Q.subject(r["text"]): r for r in qs.values()}
    cn = by.get("MH-3752")
    check("the same question across the two notes is one record: by ticket, by numbers, by subject",
          sum(1 for r in qs.values() if "MH-3752" in r["keys"]) == 1 and sum(1 for r in qs.values() if "MH-2564" in r["keys"]) == 1
          and sum(1 for r in qs.values() if "80" in r["text"] or "MH-3975" in r["keys"]) == 1
          and sum(1 for r in qs.values() if "deploy" in r["text"]) == 1)
    check("a record keeps when it was first raised and every meeting that listed it",
          cn and cn["first"]["date"] == "2026-11-11" and cn["meetings"] == ["2026-11-11", "2026-11-12"] and cn["status"] == "open")
    check("two boxes of one note are never merged; a box ticked before ela saw it is not kept; a project's box is a question",
          len([r for r in qs.values() if r["status"] == "open"]) == 7 and not any("1080p" in r["text"] for r in qs.values())
          and any(r["thing"].get("ref", "").startswith("projects/") for r in qs.values()))
    check("the hand-written note is read, never written", open(hand).read() == HAND)

    issue("MH-2564", "Backlog", "UR lead")                 # the world answers: the ticket got an assignee
    state, done = V.questions_pass(vault, reports, facts, now + datetime.timedelta(hours=1), book, "https://j")
    r = next(r for r in state["questions"].values() if "MH-2564" in r["keys"])
    check("its ticket assigned: the question closes by itself, the outcome written on it",
          r["status"] == "closed" and r["outcome"] == "assigned to UR lead" and r["by"] == "world")
    issue("MH-3976", "Backlog", "app lead")
    state, _ = V.questions_pass(vault, reports, facts, now + datetime.timedelta(hours=2), book, "https://j")
    owners = next(r for r in state["questions"].values() if "MH-3976" in r["keys"])
    check("a list question stays open until every ticket on it has an outcome", owners["status"] == "open")
    issue("MH-3752", "In Progress", "CN release lead", comments=[{"author": {"displayName": "The Owner"}, "created": "2026-11-12T12:00:00.000+0800"}])
    state, _ = V.questions_pass(vault, reports, facts, now + datetime.timedelta(hours=3), book, "https://j")
    check("his own comment does not answer it", state["questions"][cn["id"]]["status"] == "open")

    later = now + datetime.timedelta(days=30)
    state, _ = V.questions_pass(vault, reports, facts, later, book, "https://j")
    check("a month without an answer: still open, never dropped by age",
          state["questions"][cn["id"]]["status"] == "open" and not os.path.exists(os.path.join(vault, "reference", "dropped.md")))

    text = Q.page(state, later.date(), "https://j")
    line = next(l for l in text.splitlines() if cn["id"] in l)
    check("the standing page: one line a question, its answerer first, its ticket, since when, how many meetings",
          line.startswith("- [ ] **CN release lead** with UR lead · ") and "[MH-3752](https://j/browse/MH-3752)" in line
          and "since 11-11 (31 days)" in line and "listed at 2 meetings" in line and len(text.splitlines()) <= Q.PAGE_LINES + 4)
    tl = Q.today_line(state, later.date(), ("sync", datetime.date(2026, 12, 15)), "https://j")
    check("today's one line: how many, the oldest and its age, the next sync, the page linked",
          tl.startswith("- [[meetings/open-questions|") and re.search(r"oldest: \[MH-\d+\]\(https://j/browse/MH-\d+\), 31 days", tl) and tl.endswith("next sync Tue"))

    # his word on the page: a tick closes, `ela: drop` drops, other words close with those words
    deploy = next(r for r in state["questions"].values() if "deploy" in r["text"])
    overlay = next(r for r in state["questions"].values() if "Overlay" in r["text"])
    disk = text.replace(f"- [ ] **QA lead**", "- [x] **QA lead**").replace(
        next(l for l in text.splitlines() if overlay["id"] in l), next(l for l in text.splitlines() if overlay["id"] in l) + "\n  ela: drop")
    open(os.path.join(vault, Q.QUESTIONS_PAGE), "w").write(disk)
    state, done = V.questions_pass(vault, reports, facts, later, book, "https://j")
    check("his tick on the page closes it; `ela: drop` under it drops it, and the line is consumed",
          state["questions"][deploy["id"]]["status"] == "closed" and state["questions"][overlay["id"]]["status"] == "dropped"
          and done["consumed"] == ["ela: drop"])

    # three meetings without an outcome: one ask on today.md, a draft under his name, not again until three more
    for d in ("2026-11-17", "2026-11-19"):
        open(os.path.join(vault, "meetings", f"{d}-sync-eng-qa-ux.md"), "w").write(
            f'---\ntitle: "Team sync · {d}"\ntype: "meeting"\ndate: "{d}"\nby: "ela"\nsource: "vault"\n---\n\n# Team sync · {d}\n\n'
            f"## Carried\n\n- [ ] What must be on CN for 11/21? · CN release lead ^{cn['id']}\n")
    state, _ = V.questions_pass(vault, reports, facts, later, book, "https://j")
    r = state["questions"][cn["id"]]
    asks = V.question_asks(state, later.date())
    ask = next((a for a in asks if cn["id"] in a["id"]), None)
    check("listed at three meetings: one ask, `drop` its box, the drafted message waiting as a Jira comment",
          len(r["meetings"]) == 4 and ask and ask["box"] == "drop" and "carried through 4 meetings: send CN release lead the drafted message, or drop it" in ask["text"]
          and r["draft"]["via"] == "Jira comment on MH-3752" and r["draft"]["command"].startswith("ela jira comment MH-3752 --from-file ")
          and os.path.isfile(r["draft"]["file"]) and "— The" in open(r["draft"]["file"]).read())
    check("the ask is the same one until three more meetings pass", ask["id"].endswith(":1"))
    open(os.path.join(vault, "today.md"), "w").write(f"- [x] drop — x → [[{Q.QUESTIONS_PAGE[:-3]}#^{cn['id']}|its section]]\n")
    state, _ = V.questions_pass(vault, reports, facts, later, book, "https://j")
    check("`drop` ticked on today.md drops the question", state["questions"][cn["id"]]["status"] == "dropped")

    # a project page's box he ticks or removes: answered on its page
    open(os.path.join(vault, "projects", "mh-3984-destination-csc.md"), "w").write(PROJECT.replace("- [ ] Who takes", "- [x] Who takes"))
    state, _ = V.questions_pass(vault, reports, facts, later, book, "https://j")
    check("a project's question ticked on its page closes",
          all(r["status"] != "open" for r in state["questions"].values() if r["thing"].get("ref", "").startswith("projects/")))

# the older note seeded after the vault's own were read: the first raising moves back, the newest wording stays
with tempfile.TemporaryDirectory() as t:
    vault, reports, facts = (os.path.join(t, x) for x in ("vault", "reports", "facts"))
    os.makedirs(os.path.join(vault, "meetings")); os.makedirs(os.path.join(facts, "jira", "issues")); os.makedirs(os.path.join(reports, "ela"))
    open(os.path.join(vault, "meetings", "20261112-sync-eng-qa.md"), "w").write(HAND)
    seed = os.path.join(t, "sync-eng-qa-ux.md")
    open(seed, "w").write(OLD)
    tz = datetime.datetime.now().astimezone().tzinfo
    now = datetime.datetime(2026, 11, 12, 10, 0, tzinfo=tz)
    V.questions_pass(vault, reports, facts, now, [], "")
    state, done = V.questions_pass(vault, reports, facts, now, [], "", seeds=[seed])
    cn = [r for r in state["questions"].values() if "MH-3752" in r["keys"]]
    check("a seed read after the vault: one record, first raised 11-11, worded as the newest note words it",
          len(cn) == 1 and cn[0]["first"]["date"] == "2026-11-11" and cn[0]["text"].startswith("What must be on CN")
          and cn[0]["meetings"] == ["2026-11-11", "2026-11-12"])

# the next meeting's note, built from the records: not over his note for the day; his edit makes it his
with tempfile.TemporaryDirectory() as t:
    vault, reports, facts = (os.path.join(t, x) for x in ("vault", "reports", "facts"))
    os.makedirs(os.path.join(vault, "meetings")); os.makedirs(os.path.join(facts, "jira", "issues")); os.makedirs(os.path.join(reports, "ela"))
    json.dump({"key": "MH-3752", "fields": {"summary": "CN upgrade", "status": {"name": "In Progress"}, "assignee": {"displayName": "CN release lead"},
               "updated": "2026-11-13T10:00:00.000+0800", "duedate": "2026-11-16"}}, open(os.path.join(facts, "jira", "issues", "MH-3752.json"), "w"))
    json.dump({"issues": [{"fields": {"assignee": {"displayName": "The Owner"}}}]}, open(os.path.join(facts, "jira", "owner.json"), "w"))
    hand = os.path.join(vault, "meetings", "20261112-sync-eng-qa.md")
    open(hand, "w").write(HAND + "- [ ] Who decides the overlay switch? · The Owner, app lead\n")
    tz = datetime.datetime.now().astimezone().tzinfo
    book = [{"key": "sync-eng-qa-ux", "name": "Team sync", "weekdays": ["Tue", "Thu"], "time": "", "enabled": False}]
    morning = datetime.datetime(2026, 11, 12, 10, 0, tzinfo=tz)
    V.questions_pass(vault, reports, facts, morning, book, "https://j")
    check("on the day of his own note, nothing is built over it", sorted(os.listdir(os.path.join(vault, "meetings"))) == ["20261112-sync-eng-qa.md"])
    evening = datetime.datetime(2026, 11, 12, 19, 0, tzinfo=tz)
    V.questions_pass(vault, reports, facts, evening, book, "https://j")
    built = os.path.join(vault, "meetings", "2026-11-17-sync-eng-qa-ux.md")
    text = open(built).read()
    heads = re.findall(r"^## (.+)$", text, re.M)
    check("after it, the next one is built: dated, by ela, a focus topic with where it stands, then what waits on him, then Carried",
          'date: "2026-11-17"' in text and 'by: "ela"' in text and heads[0].startswith("1. CN upgrade — [MH-3752]")
          and "In Progress · carried by CN release lead" in text and heads[-2:] == ["Waiting on you", "Carried"]
          and re.search(r"^- \[ \] .*listed at 1 meeting \^q-[0-9a-f]{6}$", text, re.M) and open(hand).read().endswith("app lead\n"))
    open(built, "a").write("\nmy own line\n")
    V.questions_pass(vault, reports, facts, evening + datetime.timedelta(hours=1), book, "https://j")
    check("a built note he edited is his: not rebuilt", open(built).read().endswith("my own line\n"))

sys.exit(1 if failures else 0)
