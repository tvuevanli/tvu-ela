#!/usr/bin/env python3
"""The board watch offline (decision 2026-11-24): the scan's triggers, skips and order; the gates on the session's
decisions; the tier-1 set through `ela dry` and its record in did.md; the owner's topics. The fact store and the reports
are files in a temp dir; every write goes to a stub runner, so nothing reaches Jira or Slack."""
import datetime, json, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "watch"))
sys.path.insert(0, os.path.join(ROOT, "skills", "dry"))
import watch as W  # noqa: E402
import dry as D  # noqa: E402

fails = []


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


TZ = W.TZ
NOW = datetime.datetime(2026, 11, 24, 9, 0, tzinfo=TZ)
OWNER = {"id": "acc-owner", "name": "Dana Owner"}
ZH = "".join(chr(c) for c in (0x64ad, 0x653e, 0x5668, 0x5207, 0x6362, 0x540e, 0x9ed1, 0x5c4f, 0xff0c, 0x91cd, 0x542f, 0x6062, 0x590d))
SIGN = "\n\n" + W.J.signature("Dana Owner")


def ago(**kw):
    return (NOW - datetime.timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%S.000+0800")


def person(aid, name):
    return {"accountId": aid, "displayName": name, "accountType": "atlassian"}


def comment(cid, who, text, when):
    return {"id": cid, "author": who, "body": text, "created": when}


def issue(facts, key, summary, status="In Progress", who=None, prio="Medium", updated=None, cs=(), labels=(), desc=None):
    json.dump({"key": key, "fields": {"summary": summary, "status": {"name": status, "statusCategory": {"key": "indeterminate"}},
                                      "assignee": who, "priority": {"name": prio}, "duedate": None, "labels": list(labels),
                                      "resolution": None, "updated": updated or ago(hours=1), "description": desc},
               "comments": list(cs), "updated": updated or ago(hours=1)},
              open(os.path.join(facts, "jira", "issues", f"{key}.json"), "w"))


DEV = person("acc-dev", "Dev One")
QA = person("acc-qa", "Qa One")
ME = person("acc-owner", "Dana Owner")
BOT = {"accountId": "acc-bot", "displayName": "Automation for Jira", "accountType": "app"}

with tempfile.TemporaryDirectory() as t:
    facts, reports = os.path.join(t, "facts"), os.path.join(t, "reports")
    os.makedirs(os.path.join(facts, "jira", "issues")); os.makedirs(os.path.join(reports, "ela"))
    issue(facts, "MH-1", "Nobody on it", status="Review", who=None)
    issue(facts, "MH-2", "Fixed but still in progress", who=DEV, cs=[comment("1", DEV, "Fixed and merged into release2.1.", ago(hours=5))])
    issue(facts, "MH-3", "A question waits", who=DEV, cs=[comment("1", QA, "Which build carries the fix?", ago(hours=60))])
    issue(facts, "MH-4", "A link is not a question", who=DEV, cs=[comment("1", QA, "see https://x.slack.com/archives/C1/p1?thread_ts=1", ago(hours=60))])
    issue(facts, "MH-5", "A bot copy is not a question", who=DEV, cs=[comment("1", BOT, "(Copied from MH-9) Anyone?", ago(hours=60))])
    issue(facts, "MH-6", "The owner's own", who=ME, prio="Low")
    issue(facts, "MH-7", "Stalled in progress", who=DEV, updated=ago(days=3))
    issue(facts, "MH-8", "Legacy", status="Backlog", who=None, updated=ago(days=90))
    issue(facts, "MH-9", "Legacy but on the line", status="In Progress", who=DEV, updated=ago(days=90), labels=["release:mh-2.1"])
    issue(facts, "MH-10", "Held", status="Review", who=None)
    issue(facts, "MH-11", "Quiet and fine", who=DEV)
    issue(facts, "MH-12", "\u7a33\u5b9a " + ZH, who=ME, desc=ZH)
    json.dump({"key": "MH-13", "fields": {"summary": "Done", "status": {"name": "Done", "statusCategory": {"key": "done"}}}},
              open(os.path.join(facts, "jira", "issues", "MH-13.json"), "w"))
    holds = {"holds": {"MH-10": {"id": "MH-10", "subject": "MH-10", "keys": ["MH-10"], "words": [], "since": "2026-11-20"}}, "read": {}}

    got = W.scan(facts, reports, NOW, holds=holds, lines=["2.1"], owner=OWNER, write=True)
    by = {r["key"]: {x["kind"] for x in r["triggers"]} for r in got["triggered"]}
    check("Done is not tracked; legacy (90 days quiet, off the lines) is left alone; on the current line it is not legacy",
          "MH-13" not in by and got["skipped"]["legacy"] == 1 and "MH-8" not in by and "stalled" in by.get("MH-9", set()))
    check("a held ticket is left alone", got["skipped"]["held"] == ["MH-10"] and "MH-10" not in by)
    check("unassigned in review", by.get("MH-1") == {"unassigned"})
    check("behind: its assignee wrote it is fixed while it is in progress", "behind" in by.get("MH-2", set()))
    check("unanswered past the wait; a URL's ? and a bot's copy are not questions",
          "unanswered" in by.get("MH-3", set()) and "MH-4" not in by and "MH-5" not in by)
    check("the owner's ticket is owner-held; a stall past its threshold", "owner-held" in by.get("MH-6", set()) and "stalled" in by.get("MH-7", set()))
    check("a quiet ticket with nothing due is not triggered", "MH-11" not in by)
    check("the owner's tickets first, whatever their priority", [r["key"] for r in got["triggered"]][:2] == ["MH-12", "MH-6"] or
          [r["key"] for r in got["triggered"]][:2] == ["MH-6", "MH-12"])
    check("a Chinese ticket is marked so for the comment's language", next(r for r in got["triggered"] if r["key"] == "MH-12")["chinese"])
    check("the pass and its scan are stored", os.path.exists(W.scan_path(reports, "2026-11-24")) and W.load_state(reports)["tickets"]["MH-1"]["snap"])

    # a change since the last pass that calls for a response: pending until a decision takes it
    issue(facts, "MH-11", "Quiet and fine", status="Reopened", who=DEV)
    issue(facts, "MH-6", "The owner's own", who=ME, prio="Low", cs=[comment("9", QA, "Dana, can we ship this on Friday?", ago(minutes=30))])
    later = NOW + datetime.timedelta(hours=2)
    got2 = W.scan(facts, reports, later, holds=holds, lines=["2.1"], owner=OWNER, write=True)
    by2 = {r["key"]: [x for x in r["triggers"]] for r in got2["triggered"]}
    check("reopened since the last pass: a change trigger", any(x["kind"] == "changed" and "Reopened" in x["says"] for x in by2.get("MH-11", [])))
    check("a new question on the owner's ticket: a change trigger at once", any(x["kind"] == "changed" and "asked" in x["says"] for x in by2.get("MH-6", [])))
    check("the change waits as pending in the store", W.load_state(reports)["tickets"]["MH-11"]["pending"])

    # the session's decisions, checked and carried through a stub runner
    ran = []
    runner = lambda cmd, apply: (ran.append((cmd, apply)) or (0, "ok"))   # noqa: E731
    decisions = {"decisions": [
        {"key": "MH-1", "verdict": "act", "why": "the UI owner holds review", "writes": [{"verb": "assign", "assignee": "acc-ui"}],
         "comment": "Assigned to the UI owner: the change under review is in the player."},
        {"key": "MH-2", "verdict": "act", "writes": [{"verb": "transition", "to": "Done"}], "comment": "Closing: merged."},
        {"key": "MH-3", "verdict": "act", "writes": [{"verb": "label", "to": "x"}], "comment": "x"},
        {"key": "MH-7", "verdict": "act", "writes": [{"verb": "due", "date": "2026-12-01"}], "comment": ""},
        {"key": "MH-12", "verdict": "act", "writes": [], "comment": "The fix is on daily; QA can test it there."},
        {"key": "MH-6", "verdict": "act", "writes": [], "comment": "Dev One's performance on this is poor."},
        {"key": "MH-11", "verdict": "ask", "question": "Reopened by QA: send it back to Dev One, or hold for the 2.2 line?",
         "options": [{"letter": "A", "text": "back to Dev One", "writes": [{"verb": "assign", "assignee": "acc-dev"}],
                      "comment": "Back to Dev One: QA reopened it on daily."}, {"letter": "B", "text": "hold it"}]},
        {"key": "MH-9", "verdict": "none", "why": "it moves on the line's train"},
        {"key": "MH-77", "verdict": "act", "writes": [], "comment": "x"},
    ]}
    r = W.decide(decisions, got2, facts, reports, later, apply=False, runner=runner)
    why = {x["key"]: x["why"] for x in r["refused"]}
    check("a terminal status is refused: the owner's word", "terminal" in why.get("MH-2", ""))
    check("a verb outside the watch's own is refused", "not a write ela makes" in why.get("MH-3", ""))
    check("a set without its comment is refused", "comment" in why.get("MH-7", ""))
    check("English only on a Chinese ticket is refused", "bilingual" in why.get("MH-12", ""))
    check("a comment about a person is refused: an ask", "about a person" in why.get("MH-6", ""))
    check("a ticket the scan did not find due is refused", "not due" in why.get("MH-77", ""))
    a1 = next(x for x in r["acts"] if x["key"] == "MH-1")
    check("an act's writes: the field change names its comment's file; dry run, nothing stored",
          a1["writes"][0].startswith("ela jira assign MH-1 --assignee acc-ui --note-file ") and a1["state"] == "dry run"
          and ran == [(a1["writes"][0], False)] and not D.batches(reports))
    check("an ask and a none are carried; nothing is stored in a dry run",
          [x["key"] for x in r["asks"]] == ["MH-11"] and [x["key"] for x in r["none"]] == ["MH-9"] and W.open_topics(reports) == [])

    ran.clear()
    r = W.decide(decisions, got2, facts, reports, later, apply=True, runner=runner)
    check("applied: the set runs through ela dry's tier-1 class, the batch kept as applied",
          ran == [(a1["writes"][0], True)] and D.load_batch(reports, "2026-11-24-board-watch-MH-1")["state"] == "applied")
    line, rows = D.did(reports, "2026-11-24")
    check("did.md lists it, with the undo or the honest gap", line == "ela did: 1 ticket set" and rows[0][0] == "2026-11-24-board-watch-MH-1#1"
          and "MH-1" in rows[0][1] and rows[0][2] == "no reverse atom: undo it on the ticket")
    with open(D.acts_path(reports), "a") as f:
        f.write(json.dumps({"act": "2026-11-24-board-watch-MH-1#1", "class": "board-watch", "key": "MH-1", "verb": "assign",
                            "undo": ["ela", "jira", "assign", "MH-1", "--assignee", "none"]}) + "\n")
    check("an act jira.py kept is undone by its act id", D.did(reports, "2026-11-24")[1][0][2] == "ela dry undo 2026-11-24-board-watch-MH-1#1 --apply")
    st = W.load_state(reports)["tickets"]
    check("the decisions are on record: acted today, the pending change taken",
          st["MH-1"]["acted"] == "2026-11-24" and st["MH-11"]["verdict"] == "ask" and st["MH-11"]["pending"] == [] and st["MH-9"]["verdict"] == "none")
    got3 = W.scan(facts, reports, later + datetime.timedelta(minutes=5), holds=holds, lines=["2.1"], owner=OWNER, write=True)
    keys3 = [x["key"] for x in got3["triggered"]]
    check("a ticket written today is left alone; a decided one does not trigger again until it moves",
          "MH-1" in got3["skipped"]["done_today"] and "MH-9" not in keys3 and "MH-11" not in keys3)
    ran.clear()
    r = W.decide({"decisions": [{"key": "MH-1", "verdict": "act", "writes": [], "comment": "Another."}]},
                 dict(got2), facts, reports, later, apply=True, runner=runner)
    check("one set per ticket a day: a second is refused", "one set of writes a day" in r["refused"][0]["why"] and ran == [])

    issue(facts, "MH-14", "Said before", who=DEV, cs=[comment("1", ME, "Can you share the build?" + SIGN, ago(hours=3))])
    rec = {"said": []}
    check("never a repeated comment: the same words ela already wrote there",
          "already said" in (W.check_act("MH-14", {"writes": [], "comment": "Can you share  the build?"},
                                         W.read_json(os.path.join(facts, "jira", "issues", "MH-14.json"), {}), rec, "2026-11-24") or ""))

    # the owner's topics: today.md's asks, his letter, the chosen option carried out at the next pass
    a = W.asks(reports, NOW.date())
    check("an open topic is an ask with its letters, each answered by ela watch answer",
          [x["id"] for x in a] == ["watch:MH-11"] and a[0]["options"][0]["does"] == "ela watch answer watch:MH-11 A" and a[0]["options"][0]["recommended"])
    W.answer(reports, "watch:MH-11", "a", later)
    check("his letter closes the topic", W.open_topics(reports) == [] and W.load_topics(reports)["topics"]["watch:MH-11"]["closed"]["letter"] == "A")
    try:
        W.answer(reports, "watch:MH-11", "Z", later); bad = False
    except ValueError:
        bad = True
    check("a letter the topic does not offer is refused", bad)
    ran.clear()
    nxt = later + datetime.timedelta(days=1)
    r = W.decide({"decisions": []}, {"triggered": []}, facts, reports, nxt, apply=True, runner=runner)
    check("his A carried out at the next pass, signed like any act",
          r["answered"][0]["topic"] == "watch:MH-11" and ran and ran[0][0].startswith("ela jira assign MH-11 --assignee acc-dev --note-file "))
    ran.clear()
    W.decide({"decisions": []}, {"triggered": []}, facts, reports, nxt, apply=True, runner=runner)
    check("and only once", ran == [])

    # the class: its commands, and the demotion rule
    try:
        D.act(reports, "board-watch", "MH-20", [{"target": "MH-20", "command": "ela jira transition MH-20 --to Done", "why": "x"}], NOW.date())
        bad = False
    except ValueError:
        bad = True
    check("the class admits only signed field changes and comments", bad)
    st_ = D.load_state(reports); st_["board-watch"]["tier"] = 3; D.save_state(reports, st_)
    got = D.act(reports, "board-watch", "MH-21", [{"target": "MH-21", "command": "ela jira comment MH-21 --from-file /tmp/x", "why": "w"}],
                NOW.date(), apply=True, runner=runner)
    check("a correction returned the class to confirm: the set is asked as an open batch, not written",
          got["state"] == "open" and D.load_batch(reports, got["batch"])["state"] == "open")

# ── the owner's DM and today.md: one root a day, each topic a reply, an open topic continued in its own thread ───
with tempfile.TemporaryDirectory() as t:
    reports = os.path.join(t, "reports")
    os.makedirs(os.path.join(reports, "ela"))
    topics = W.load_topics(reports)
    for key in ("MH-31", "MH-32"):
        W.put_topic(topics, key, {"question": f"{key}: hand it to the UI owner or keep it?"}, "2026-11-24", f"summary {key}")
    W.write_json(W.topics_path(reports), topics)
    posts = []

    def post(argv, apply):
        posts.append((argv, apply))
        n = len(posts)
        return 0, {"permalink": f"https://x.slack.com/archives/D1/p{n}"} if apply else {"dry_run": True}, ""

    day1 = datetime.datetime(2026, 11, 24, 18, 0, tzinfo=TZ)
    r = W.dm(reports, day1, apply=False, post=post, base="https://j")
    check("dry run: a root, then each topic a reply; nothing stored",
          [x["kind"] for x in r["sent"]] == ["root", "reply", "reply"] and all(not a for _, a in posts)
          and W.load_topics(reports)["roots"] == {})
    posts.clear()
    r = W.dm(reports, day1, apply=True, post=post, base="https://j")
    check("applied (a stub): the root to his DM, each topic a reply in its thread, never top-level per topic",
          posts[0][0][:3] == ["post", "--dm", "me"] and all(a[0][1] == "https://x.slack.com/archives/D1/p1" and "--no-cc" in a[0] for a in posts[1:])
          and len(posts) == 3)
    tp = W.load_topics(reports)
    check("the store keeps the root and each topic's thread", tp["roots"]["2026-11-24"].endswith("/p1")
          and tp["topics"]["watch:MH-31"]["thread"].endswith("/p1") and "https://j/browse/MH-31" in r["sent"][1]["text"])
    posts.clear()
    check("a second pass the same day sends nothing", W.dm(reports, day1, apply=True, post=post)["sent"] == [] and posts == [])
    W.answer(reports, "watch:MH-32", "B", day1)
    tp = W.load_topics(reports)
    W.put_topic(tp, "MH-33", {"question": "MH-33: who takes it?"}, "2026-11-25", "summary MH-33")
    W.write_json(W.topics_path(reports), tp)
    posts.clear()
    day2 = day1 + datetime.timedelta(days=1)
    r = W.dm(reports, day2, apply=True, post=post, base="")
    kinds = {(x["kind"], x["topic"]) for x in r["sent"]}
    check("the next day: a new root for the new topic; the open one continues in its first thread; the settled one is told there",
          kinds == {("root", None), ("reply", "watch:MH-33"), ("again", "watch:MH-31"), ("settled", "watch:MH-32")}
          and next(a for a, _ in posts if "Still" in open(a[-1]).read())[1] == "https://x.slack.com/archives/D1/p1")
    posts.clear()
    check("and once a day only", W.dm(reports, day2, apply=True, post=post)["sent"] == [])
    fail_root = lambda argv, apply: (1, None, "slack down")   # noqa: E731
    W.put_topic(tp := W.load_topics(reports), "MH-34", {"question": "MH-34?"}, "2026-11-26", "")
    W.write_json(W.topics_path(reports), tp)
    r = W.dm(reports, day2 + datetime.timedelta(days=1), apply=True, post=fail_root)
    check("no root, no replies: a failed root stops the pass", len(r["failed"]) == 1 and r["sent"] == [])

    sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
    import vault as V  # noqa: E402
    got = V.watch_asks(reports, day2.date())
    check("today.md shows each open topic as an ask, dated from its first day, its letters answered by ela watch answer",
          {x["id"] for x in got} == {"watch:MH-31", "watch:MH-33", "watch:MH-34"}
          and next(x for x in got if x["id"] == "watch:MH-31")["first"] == "2026-11-24"
          and V.sync_handles("ela watch answer watch:MH-31 A"))
    state = {"watch:MH-31": {}}
    check("a tick on today.md records the letter through the watch", V.settle_one(reports, state, "watch:MH-31", "A",
                                                                                  "ela watch answer watch:MH-31 A", day2.date())
          and W.load_topics(reports)["topics"]["watch:MH-31"]["closed"]["letter"] == "A")

print("watch: all offline checks passed" if not fails else f"watch: {len(fails)} failed")
sys.exit(1 if fails else 0)
