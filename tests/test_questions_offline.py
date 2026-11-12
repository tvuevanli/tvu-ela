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
sec = lambda raw, section=None, parent=None, kind="meeting", where="meetings/x.md": {"raw": raw, "section": section, "parent": parent,
                                                                                  "kind": kind, "where": where}
check("a subject from the section, with the section's key or else the question's one ticket",
      Q.subject_of(sec("UR: the retry order. Who? · UR lead", "5. TVU Region 3.0 — [MH-3819](https://j/browse/MH-3819)")) == "TVU Region 3.0 (MH-3819)"
      and Q.subject_of(sec("What must be on CN ([MH-3752](https://j/browse/MH-3752))? · CN lead", "2. 超赛 11/21 — CN vs COM")) == "超赛 11/21, CN vs COM (MH-3752)")
check("a subject from the bullet it hangs from, from its own words before a colon, from its ticket",
      Q.subject_of(sec("Who upgrades the account pool to Premium? · PM lead", "7. Waiting on Evan — threads", "**YouTube source** ([ads](https://s))")) == "YouTube source"
      and Q.subject_of(sec("This week's deploy: what goes to Prod 3? · QA lead", "If time allows")) == "This week's deploy"
      and Q.subject_of(sec("[MH-2564](https://j/browse/MH-2564) async graph submissions: when?", "If time allows")) == "MH-2564"
      and Q.subject_of(sec("Who takes it?", kind="project", where="projects/p.md"), {"MH-3984": "projects/p.md"},
                       {"projects/p.md": "MH-3984 · Destination CSC"}) == "Destination CSC (MH-3984)")
r_ = {"raw": "x", "text": "MH-2564 — async graph submissions: when?", "lead": ["MH-2564"], "subject": "MH-2564", "thing": {}, "who": "UR lead"}
check("a line is its subject and the question, the subject not said twice, its ticket linked, never cut",
      Q.line(r_, "https://j") == "[MH-2564](https://j/browse/MH-2564): Async graph submissions: when?"
      and not Q.unworded(r_) and Q.unworded(dict(r_, text="MH-2564 — " + "word " * 30 + "?")))
check("his words for a line: one sentence of at most 25 words, no ellipsis; they stand while the note words it the same",
      Q.set_words({"questions": {"q": r_}}, "q", "MH-2564", "When does async graph submission start …?") == "an ellipsis: write it whole"
      and Q.set_words({"questions": {"q": r_}}, "q", "MH-2564", "word " * 26 + "?").startswith("one whole sentence")
      and Q.set_words({"questions": {"q": r_}}, "q", "Async graph submissions (MH-2564)", "Which sprint takes it, and who builds it?") is None
      and Q.line(r_) == "Async graph submissions (MH-2564): Which sprint takes it, and who builds it?"
      and Q.line(dict(r_, raw="reworded")) == "MH-2564: Async graph submissions: when?")

st = {"questions": {"q-aaaaaa": {"status": "open"}, "q-bbbbbb": {"status": "open"}}}
got, used = Q.by_word(st, "> [!note]- Raised once, by who answers (2)\n> **PM lead**\n> - [x] A: B? · raised today ^q-aaaaaa\n"
                          "> - [ ] C: D? · raised today ^q-bbbbbb\n> ela: drop\n", datetime.date(2026, 11, 12))
check("his tick and `ela:` line inside the folded part count as on the page",
      st["questions"]["q-aaaaaa"]["status"] == "closed" and st["questions"]["q-bbbbbb"]["status"] == "dropped")

check("a note's meeting is its file name less its date, matched to the book's key either way",
      Q.audience("meetings/2026-11-12-sync-eng-qa.md", ["sync-eng-qa-ux"]) == "sync-eng-qa-ux"
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
    hand = os.path.join(vault, "meetings", "2026-11-12-sync-eng-qa.md")
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
    csc = next(r for r in qs.values() if r["thing"].get("ref", "").startswith("projects/"))
    check("a project's question no box names goes to the person its project's ticket is on, else asks who takes it",
          csc.get("holder") is None and Q.answerer(csc)[0] == "Not named" and Q.line(csc).endswith("Who takes orchestration and the destination UI?")
          and Q.line(dict(csc, text="Retire the poll?")).endswith(": Who takes it? Retire the poll?")
          and Q.answerer(dict(csc, holder="CSC lead"))[0] == "CSC lead" and "0 meetings" not in Q.page(state, now.date()))

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
    part1 = text.split("## Carried", 1)[1].split("> [!note]-", 1)[0]
    check("the standing page: Carried first, each line its subject and question, who answers, how long it has waited",
          line.startswith("- [ ] CN vs COM ([MH-3752](https://j/browse/MH-3752)): What must be on CN for 11/21")
          and "· **CN release lead** with UR lead · waiting 31 days · 2 meetings" in line and line in part1
          and 0 < part1.count("- [ ] ") <= Q.CARRIED_MAX and "…" not in text)
    built = sorted(f for f in os.listdir(os.path.join(vault, "meetings")) if f.startswith("2026-12"))
    note = open(os.path.join(vault, "meetings", built[0])).read() if built else ""
    page_ids = re.findall(r"\^(q-[0-9a-f]{6})", part1)
    note_ids = re.findall(r"\^(q-[0-9a-f]{6})", note.split("## Carried", 1)[1].split("\n## ", 1)[0]) if "## Carried" in note else []
    check("the built meeting note's Carried is the page's part one: same lines, same order",
          note_ids and note_ids == [i for i in page_ids if i in note_ids]
          and all(l in part1 for l in note.split("## Carried", 1)[1].split("\n## ", 1)[0].splitlines() if l.startswith("- [ ]")))
    tl = Q.today_line(state, later.date(), ("sync", datetime.date(2026, 12, 15)), "https://j")
    check("today's one line: how many, the longest waiting and its days, the next sync, the page linked",
          tl.startswith("- [[meetings/open-questions|") and re.search(r"longest waiting: \[MH-\d+\]\(https://j/browse/MH-\d+\), 31 days", tl) and tl.endswith("next sync Tue"))

    # his word on the page: a tick closes, `ela: drop` drops, other words close with those words
    deploy = next(r for r in state["questions"].values() if "deploy" in r["text"])
    overlay = next(r for r in state["questions"].values() if "Overlay" in r["text"])
    dl = next(l for l in text.splitlines() if deploy["id"] in l)
    disk = text.replace(dl, dl.replace("- [ ] ", "- [x] ", 1)).replace(
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
          len(r["meetings"]) == 4 and ask and ask["box"] == "drop" and ask["text"].endswith("carried through 4 meetings.")
          and [(o["letter"], o["does"]) for o in ask["options"]] == [("A", None), ("B", "drop")] and "CN release lead" in ask["options"][0]["text"]
          and r["draft"]["via"] == "Jira comment on MH-3752" and r["draft"]["command"].startswith("ela jira comment MH-3752 --from-file ")
          and os.path.isfile(r["draft"]["file"]) and "— The" in open(r["draft"]["file"]).read())
    check("the ask is the same one until three more meetings pass", ask["id"].endswith(":1"))
    act = {"rule": "question", "question": cn["id"], "day": later.date().isoformat(), "n": 7, "tier": 3, "text": "send it"}
    ask2 = next(a for a in V.question_asks(state, later.date(), [act]) if cn["id"] in a["id"])
    check("once the runner drafts it as an action, the question's ask carries its apply box and the action is not a second ask",
          ask2["box"] == "apply 7" and ask2["ns"] == [7] and V.ask_candidates(later.date(), [act], []) == [])
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
    open(os.path.join(vault, "meetings", "2026-11-12-sync-eng-qa.md"), "w").write(HAND)
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
    hand = os.path.join(vault, "meetings", "2026-11-12-sync-eng-qa.md")
    open(hand, "w").write(HAND + "- [ ] Who decides the overlay switch? · The Owner, app lead\n")
    tz = datetime.datetime.now().astimezone().tzinfo
    book = [{"key": "sync-eng-qa-ux", "name": "Team sync", "weekdays": ["Tue", "Thu"], "time": "", "enabled": False}]
    morning = datetime.datetime(2026, 11, 12, 10, 0, tzinfo=tz)
    V.questions_pass(vault, reports, facts, morning, book, "https://j")
    check("on the day of his own note, nothing is built over it", sorted(os.listdir(os.path.join(vault, "meetings"))) == ["2026-11-12-sync-eng-qa.md"])
    evening = datetime.datetime(2026, 11, 12, 19, 0, tzinfo=tz)
    V.questions_pass(vault, reports, facts, evening, book, "https://j")
    built = os.path.join(vault, "meetings", "2026-11-17-sync-eng-qa-ux.md")
    text = open(built).read()
    heads = re.findall(r"^## (.+)$", text, re.M)
    check("after it, the next one is built: dated, by ela, Where things stand, a focus topic with its state, then what waits on him, then the rest",
          'date: "2026-11-17"' in text and 'by: "ela"' in text and heads[0] == "Where things stand" and heads[1].startswith("1. CN upgrade — [MH-3752]")
          and "In Progress · carried by CN release lead" in text and heads[-2:] == ["Waiting on you", "Raised once"]
          and re.search(r"^- \[ \] .*· 1 meeting \^q-[0-9a-f]{6}$", text, re.M) and open(hand).read().endswith("app lead\n"))
    open(built, "a").write("\nmy own line\n")
    V.questions_pass(vault, reports, facts, evening + datetime.timedelta(hours=1), book, "https://j")
    check("a built note he edited is his: not rebuilt", open(built).read().endswith("my own line\n"))

# Where things stand on a built note: the lanes' newest builds (the generator's facts block, missing on 11-11's copy)
B = [{"line": "2.1", "lane": "qa-cn3", "lane_name": "QA-AWS3", "build": "91", "date": "2026-11-11", "name": "2026-11-11-build-91-to-qa-aws3"},
     {"line": "2.1", "lane": "qa-cn3", "lane_name": "QA-AWS3", "build": "90", "date": "2026-11-10", "name": "2026-11-10-build-90-to-qa-aws3"},
     {"line": "2.1", "lane": "prod-3", "lane_name": "prod-3", "build": "88", "date": "2026-10-01", "name": "2026-10-01-build-88-to-prod-3"}]
check("Where things stand: each lane's newest build in two weeks, linked; an older one is left out",
      V.stand_lines(B, datetime.date(2026, 11, 12)) == ["QA-AWS3 runs 2.1 build 91, taken 11-11 ([[releases/2.1/2026-11-11-build-91-to-qa-aws3|release note]])"])
with tempfile.TemporaryDirectory() as t:
    vault, reports, facts = (os.path.join(t, x) for x in ("vault", "reports", "facts"))
    os.makedirs(os.path.join(vault, "meetings")); os.makedirs(os.path.join(facts, "jira", "issues")); os.makedirs(os.path.join(reports, "releases", "2.1"))
    json.dump({"line": "2.1", "lane": "qa-cn3", "lane_name": "QA-AWS3", "build": "91", "date": "2026-11-11", "at": "2026-11-11T18:00:00+08:00",
               "source": "s", "services": [{"service": "UR Caller", "from": "1", "to": "2", "for": "x", "keys": []}], "notes": ""},
              open(os.path.join(reports, "releases", "2.1", "2026-11-11-build-91-to-qa-aws3.json"), "w"))
    tz = datetime.datetime.now().astimezone().tzinfo
    book = [{"key": "scrum-pm", "name": "Scrum with the PM", "weekdays": ["Fri"], "time": "10:00"}]
    V.questions_pass(vault, reports, facts, datetime.datetime(2026, 11, 12, 19, 0, tzinfo=tz), book, "https://j")
    built = open(os.path.join(vault, "meetings", "2026-11-13-scrum-pm.md")).read()
    check("a built meeting note opens with Where things stand, from the build records",
          re.findall(r"^## (.+)$", built, re.M)[:1] == ["Where things stand"] and "- QA-AWS3 runs 2.1 build 91, taken 11-11" in built)
    V.questions_pass(vault, reports, facts, datetime.datetime(2026, 11, 13, 19, 0, tzinfo=tz), book, "https://j")
    check("after the meeting, the closed note keeps its Where things stand",
          "## Where things stand" in open(os.path.join(vault, "meetings", "2026-11-13-scrum-pm.md")).read())

# waiting since the earliest evidence, not the day ela first read the question
with tempfile.TemporaryDirectory() as t:
    vault, reports, facts = (os.path.join(t, x) for x in ("vault", "reports", "facts"))
    for d in ("meetings", "reference/days/2026", "archive"):
        os.makedirs(os.path.join(vault, d))
    os.makedirs(os.path.join(facts, "jira", "issues")); os.makedirs(os.path.join(reports, "ela"))
    json.dump({"issues": [{"fields": {"assignee": {"displayName": "The Owner"}}}]}, open(os.path.join(facts, "jira", "owner.json"), "w"))
    def issue(key, updated, comments=()):
        json.dump({"key": key, "fields": {"status": {"name": "In Progress"}, "assignee": {"displayName": "CN release lead"},
                   "created": "2026-10-01T10:00:00.000+0800", "updated": updated}, "comments": list(comments)},
                  open(os.path.join(facts, "jira", "issues", f"{key}.json"), "w"))
    issue("MH-3752", "2026-10-28T19:10:29.308-0700", [{"author": {"displayName": "The Owner"}, "created": "2026-10-27T01:25:03.154-0700"}])
    issue("MH-2564", "2026-11-10T09:00:00.000+0800", [{"author": {"displayName": "The Owner"}, "created": "2026-11-10T09:00:30.000+0800"},
                                                      {"author": {"displayName": "UR lead"}, "created": "2026-11-03T09:00:00.000+0800"}])
    issue("MH-3975", "2026-11-11T09:00:00.000+0800")
    open(os.path.join(vault, "meetings", "2026-11-12-sync-eng-qa.md"), "w").write(HAND + f"- [ ] [MH-3975]({J}MH-3975) — who re-tests 1.0.25? · PM lead\n")
    json.dump({"keys:MH-3975": {"first": "2026-11-05", "text": "MH-3975: ask the PM lead", "dropped": "2026-11-10"}},
              open(os.path.join(reports, "ela", "asks.json"), "w"))
    for i, d in enumerate(("2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12")):
        open(os.path.join(vault, "reference", "days", "2026", f"{d}-brief.md"), "w").write(
            f"## Needs you\n\n> ### 4. [MH-3909]({J}MH-3909): the deploy waits\n> [MH-3909]({J}MH-3909) · {i + 1}{'st' if i == 0 else 'th'} morning\n")
    open(os.path.join(vault, "archive", "meetings-scrum-pm-2026-11.md"), "w").write(
        f'---\ntype: "meeting"\ndate: "2026-11-06"\n---\n# Scrum\n\n## To raise\n\n- [ ] [MH-3909]({J}MH-3909) — deploy day? · PM lead · since 11-02\n')
    tz = datetime.datetime.now().astimezone().tzinfo
    now = datetime.datetime(2026, 11, 12, 10, 0, tzinfo=tz)
    state, _ = V.questions_pass(vault, reports, facts, now, [], "https://j")
    by = {r["lead"][0]: r for r in state["questions"].values() if len(r["lead"]) == 1}
    check("a silent ticket: waiting reaches back to its last movement by someone else, not to his own comment",
          by["MH-3752"]["waiting"]["since"] == "2026-10-28" and by["MH-3752"]["waiting"]["why"] == "Jira silent since 2026-10-28")
    check("an update his own comment made is not movement: the last word by someone else counts",
          by["MH-2564"]["waiting"]["since"] == "2026-11-03")
    check("his ask on the ticket, dropped since, dates it", by["MH-3975"]["waiting"]["since"] == "2026-11-05")
    check("an archived meeting list dates it before the morning pages do",
          by["MH-3909"]["waiting"]["since"] == "2026-11-02" and "archive/" in by["MH-3909"]["waiting"]["why"])
    check("the page and today's line count the days it has waited",
          "waiting 15 days · 1 meeting" in Q.page(state, now.date())
          and re.search(r"longest waiting: MH-3752, 15 days", Q.today_line(state, now.date())))
    ev = V.question_evidence(vault, reports, lambda k: None)
    check("a morning page's own count reaches back over the pages", ("2026-11-09", "on the morning page since 2026-11-09") in ev("MH-3909"))

PAGE = ("## Needs you\n\n> ### 1. MH-1: short\n> MH-1 · 2nd morning\n> ### 2. MH-2: also short\n> MH-2 · 3rd morning\n"
        "### 3. MH-3: one line\n### 4. MH-4: no blank line before it\nMH-4 · 4th morning")
check("items of two lines or less: each heading is read, none swallowed by the item before it",
      [(Q.keys_in(h)[0], n) for h, n in V.morning_items(PAGE)] == [("MH-1", 2), ("MH-2", 3), ("MH-4", 4)])
check("an item without its own count does not borrow the next item's", all(not h.startswith("3.") and "MH-3" not in h for h, _ in V.morning_items(PAGE)))

sys.exit(1 if failures else 0)
