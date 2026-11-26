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
        {"key": "MH-1", "verdict": "act", "confidence": "high", "why": "the UI owner holds review", "writes": [{"verb": "assign", "assignee": "acc-ui"}],
         "comment": "Assigned to the UI owner: the change under review is in the player."},
        {"key": "MH-2", "verdict": "act", "confidence": "high", "writes": [{"verb": "transition", "to": "Done"}], "comment": "Closing: merged."},
        {"key": "MH-3", "verdict": "act", "confidence": "high", "writes": [{"verb": "label", "to": "x"}], "comment": "x"},
        {"key": "MH-7", "verdict": "act", "confidence": "high", "writes": [{"verb": "due", "date": "2026-12-01"}], "comment": ""},
        {"key": "MH-12", "verdict": "act", "confidence": "high", "writes": [], "comment": "The fix is on daily; QA can test it there.\n\n\u4fee\u590d\u5df2\u5728 daily \u4e0a\uff0cQA \u53ef\u4ee5\u5728\u90a3\u91cc\u6d4b\u8bd5\u3002"},
        {"key": "MH-6", "verdict": "act", "confidence": "high", "writes": [], "comment": "Dev One's performance on this is poor."},
        {"key": "MH-11", "verdict": "ask", "question": "Reopened by QA: send it back to Dev One, or hold for the 2.2 line?",
         "options": [{"letter": "A", "text": "back to Dev One", "writes": [{"verb": "assign", "assignee": "acc-dev"}],
                      "comment": "Back to Dev One: QA reopened it on daily."}, {"letter": "B", "text": "hold it"}]},
        {"key": "MH-9", "verdict": "none", "confidence": "high", "why": "it moves on the line's train"},
        {"key": "MH-77", "verdict": "act", "confidence": "high", "writes": [], "comment": "x"},
    ]}
    r = W.decide(decisions, got2, facts, reports, later, apply=False, runner=runner)
    why = {x["key"]: x["why"] for x in r["refused"]}
    check("a terminal status is refused: the owner's word", "terminal" in why.get("MH-2", ""))
    check("a verb outside the watch's own is refused", "not a write ela makes" in why.get("MH-3", ""))
    check("a set without its comment is refused", "comment" in why.get("MH-7", ""))
    check("a Chinese paragraph in the comment is refused: English, one language", "one language" in why.get("MH-12", ""))
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
    D.roster_names = lambda: {"acc-ui": "Uma Interface"}
    line, rows = D.did(reports, "2026-11-24")
    check("did.md lists it, with the undo or the honest gap", line == "ela did: 1 ticket set" and rows[0][0] == "2026-11-24-board-watch-MH-1#1"
          and "MH-1" in rows[0][1] and rows[0][2] == "no reverse atom: undo it on the ticket")
    check("did.md names the write in plain words, the assignee by name, and the comment it posted",
          rows[0][1] == "MH-1: assigned to Uma Interface; its comment: \"Assigned to the UI owner: the change under review "
                        "is in the player.\" — why: the UI owner holds review")
    sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
    import vault as V  # noqa: E402
    check("each key on did.md is a link; the act id is left as it is",
          "- 2026-11-24-board-watch-MH-1#1. [MH-1](https://j/browse/MH-1): assigned to Uma Interface"
          in V.dry_pages(reports, reports, datetime.date(2026, 11, 24), record=False, jira_base="https://j")["ela/dry/did.md"])
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
    r = W.decide({"decisions": [{"key": "MH-1", "verdict": "act", "confidence": "high", "writes": [], "comment": "Another."}]},
                 dict(got2), facts, reports, later, apply=True, runner=runner)
    check("one set per ticket a day: a second is refused", "one set of writes a day" in r["refused"][0]["why"] and ran == [])

    issue(facts, "MH-14", "Said before", who=DEV, cs=[comment("1", ME, "Can you share the build?" + SIGN, ago(hours=3))])
    rec = {"said": []}
    check("never a repeated comment: the same words ela already wrote there",
          "already said" in (W.check_act("MH-14", {"writes": [], "comment": "Can you share  the build?"},
                                         W.read_json(os.path.join(facts, "jira", "issues", "MH-14.json"), {}), rec, "2026-11-24") or ""))

    iss14 = W.read_json(os.path.join(facts, "jira", "issues", "MH-14.json"), {})
    lk = {"writes": [{"verb": "link", "other": "MH-15", "type": "relates to"}], "comment": "Linked the twin ticket."}
    _, ltext, lw = W.act_writes("MH-14", lk, reports)
    check("a set of links alone needs no comment and posts none; its command carries no note and the class admits it",
          W.check_act("MH-14", dict(lk, comment=""), iss14, {"said": []}, "2026-11-24") is None and ltext == ""
          and "carries no comment" in (W.check_act("MH-14", lk, iss14, {"said": []}, "2026-11-24") or "")
          and "--note-file" not in lw[0]["command"] and not [w for w in lw if "jira comment" in w["command"]]
          and __import__("re").match(D.CLASSES["board-watch"]["command"], lw[0]["command"]))
    mixed = {"writes": [{"verb": "link", "other": "MH-15", "type": "relates to"}, {"verb": "due", "date": "2026-12-01"}],
             "comment": "Due date set from the release plan."}
    _, mtext, mw = W.act_writes("MH-14", mixed, reports)
    check("a link beside a field change: the field change goes first with the note, the link after with none",
          mtext and mw[0]["command"].startswith("ela jira due") and "--note-file" in mw[0]["command"]
          and mw[1]["command"].startswith("ela jira link") and "--note-file" not in mw[1]["command"]
          and W.check_act("MH-14", dict(mixed, comment=""), iss14, {"said": []}, "2026-11-24") is not None)

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

# ── the reminder reads as written for a person (the owner's ruling, 2026-11-26): the key is the link, no bare URL,
#    a long title cut at a word with "…", Slack's control characters escaped, mrkdwn clean ────────────────────────────
sys.path.insert(0, os.path.join(ROOT, "skills", "slack"))
import slack as S  # noqa: E402
tp = {"roots": {}, "topics": {}}
W.put_topic(tp, "MH-1997", {"question": "MH-1997: who takes it?"}, "2026-11-26",
            "[Prod9 1.1.1] Unable to create X source after the user switches the account <and> the source drops out again")
plan = W.dm_plan(tp, datetime.date(2026, 11, 26), "https://j")
txt = plan[0]["text"] if plan else ""
first, bullet = (txt.split("\n") + ["", ""])[:2]
check("watch reminder: a short first line saying what it is; the key is its link; no bare URL; cut at a word",
      first.startswith("*Board watch:* 1 new topic") and bullet.startswith("• <https://j/browse/MH-1997|MH-1997> [Prod9")
      and "https://j/browse/MH-1997>" not in txt.replace("|MH-1997>", "") and bullet.endswith("…")
      and bullet[:-1].split()[-1] in ("the", "drops", "source", "&lt;and&gt;", "account", "switches", "user")
      and "&lt;and&gt;" in bullet and S.mrkdwn_check(txt) == [])
check("watch reminder without a Jira base: the key alone, never a broken link",
      W.dm_plan(tp, datetime.date(2026, 11, 26), "")[0]["text"].split("\n")[1].startswith("• MH-1997 [Prod9"))

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
    check("dry run: one reminder naming the new topics, the vault page and the CLI verb; nothing stored",
          [x["kind"] for x in r["sent"]] == ["reminder"] and len(posts) == 1 and not posts[0][1]
          and "ela/watch" in r["sent"][0]["text"] and "ela watch answer" in r["sent"][0]["text"]
          and "MH-31" in r["sent"][0]["text"] and "https://j/browse/MH-32" in r["sent"][0]["text"]
          and W.load_topics(reports)["roots"] == {})
    posts.clear()
    r = W.dm(reports, day1, apply=True, post=post, base="https://j")
    tp = W.load_topics(reports)
    check("applied (a stub): one message to his DM, no thread per topic; the store marks the topics reminded",
          len(posts) == 1 and posts[0][0][:3] == ["post", "--dm", "me"] and tp["roots"]["2026-11-24"].endswith("/p1")
          and all(tp["topics"][k]["thread"] for k in ("watch:MH-31", "watch:MH-32")))
    posts.clear()
    check("a second pass the same day sends nothing", W.dm(reports, day1, apply=True, post=post)["sent"] == [] and posts == [])
    W.answer(reports, "watch:MH-32", "B", day1)
    day2 = day1 + datetime.timedelta(days=1)
    check("the next day with nothing new: no reminder (the open one lives on the vault page, not repeated in Slack)",
          W.dm(reports, day2, apply=True, post=post)["sent"] == [] and posts == [])
    tp = W.load_topics(reports)
    W.put_topic(tp, "MH-33", {"question": "MH-33: who takes it?"}, "2026-11-25", "summary MH-33")
    W.write_json(W.topics_path(reports), tp)
    r = W.dm(reports, day2, apply=True, post=post, base="")
    check("a new topic: one reminder naming only it, counting every open one",
          len(r["sent"]) == 1 and r["sent"][0]["topics"] == ["watch:MH-33"] and "1 new topic for your answer · 2 waiting in all" in r["sent"][0]["text"])
    posts.clear()
    check("and once a day only", W.dm(reports, day2, apply=True, post=post)["sent"] == [])
    fail = lambda argv, apply: (1, None, "slack down")   # noqa: E731
    W.put_topic(tp := W.load_topics(reports), "MH-34", {"question": "MH-34?"}, "2026-11-26", "")
    W.write_json(W.topics_path(reports), tp)
    r = W.dm(reports, day2 + datetime.timedelta(days=1), apply=True, post=fail)
    check("a failed post is reported and the topic stays unreminded for the next pass",
          len(r["failed"]) == 1 and r["sent"] == [] and not W.load_topics(reports)["topics"]["watch:MH-34"]["thread"])
    pg = W.page(reports, day2.date(), "https://j")
    check("the vault page lists every open topic with each letter's CLI line; a settled one is not there",
          "### [MH-31](https://j/browse/MH-31)" in pg and "`ela watch answer watch:MH-31 " in pg and "MH-32" not in pg
          and "4 topics" not in pg and "3 topics wait" in pg)

    sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
    import vault as V  # noqa: E402
    check("today.md carries one line for the board watch whatever the ask cap shows, the page behind it",
          (V.watch_line(reports) or "").startswith("- [[ela/watch|The board watch]]: 3 topics wait")
          and list(V.watch_page(reports, day2.date(), "https://j")) == ["ela/watch.md"])
    got = V.watch_asks(reports, day2.date())
    check("today.md shows each open topic as an ask, dated from its first day, its letters answered by ela watch answer",
          {x["id"] for x in got} == {"watch:MH-31", "watch:MH-33", "watch:MH-34"}
          and next(x for x in got if x["id"] == "watch:MH-31")["first"] == "2026-11-24"
          and V.sync_handles("ela watch answer watch:MH-31 A"))
    state = {"watch:MH-31": {}}
    check("a tick on today.md records the letter through the watch", V.settle_one(reports, state, "watch:MH-31", "A",
                                                                                  "ela watch answer watch:MH-31 A", day2.date())
          and W.load_topics(reports)["topics"]["watch:MH-31"]["closed"]["letter"] == "A")


# confidence: every act and none carries it, below high with its doubt; did.md and watch.md list the least sure first
with tempfile.TemporaryDirectory() as reports:
    os.makedirs(os.path.join(reports, "ela", "dry"), exist_ok=True)
    day = datetime.date(2026, 11, 25)
    scanned = {"triggered": [{"key": k} for k in ("MH-40", "MH-41", "MH-42", "MH-43")]}
    r = W.decide({"decisions": [
        {"key": "MH-40", "verdict": "act", "writes": [], "comment": "A nudge."},
        {"key": "MH-41", "verdict": "none", "why": "moving", "confidence": "low"},
        {"key": "MH-42", "verdict": "none", "why": "moving", "confidence": "sure"},
        {"key": "MH-43", "verdict": "ask", "question": "Which owner?", "options": [{"letter": "A", "text": "UI"}]}]},
        scanned, reports, reports, datetime.datetime(2026, 11, 25, 9, tzinfo=TZ))
    check("the session's prompt asks for the confidence, since an older installed skill may not",
          '"confidence": high | medium | low' in W.prompt_text({"date": "2026-11-25"}, [], "f.json"))
    why = {x["key"]: x["why"] for x in r["refused"]}
    check("an act or a none without its confidence is refused; below high without a doubt is refused; an ask needs none",
          "confidence" in why.get("MH-40", "") and "doubt" in why.get("MH-41", "") and "confidence" in why.get("MH-42", "")
          and [x["key"] for x in r["asks"]] == ["MH-43"])

    note = os.path.join(reports, "note.txt")
    open(note, "w").write("Assigned to the UI owner: the `player` trace ends there. The rest is detail nobody needs here, "
                          "repeated at length so that the comment runs well past the length a did.md row can carry whole, "
                          "and then some more words, and more again, until it is plainly too long.\n")
    at = lambda h: f"2026-11-25T{h:02d}:00:00+08:00"   # noqa: E731
    D.append(reports, {"at": at(9), "class": "board-watch", "verdict": "applied", "target": "MH-50", "source": "tier1",
                       "command": f"ela jira assign MH-50 --assignee acc-ui --note-file {note}", "why": "UI holds it, see MH-49",
                       "batch": "2026-11-25-board-watch-MH-50", "act": "2026-11-25-board-watch-MH-50#1", "confidence": "high"})
    D.append(reports, {"at": at(9), "class": "board-watch", "verdict": "applied", "target": "MH-50", "source": "tier1",
                       "command": f"ela jira transition MH-50 --to Review --note-file {note}", "why": "UI holds it, see MH-49",
                       "batch": "2026-11-25-board-watch-MH-50", "act": "2026-11-25-board-watch-MH-50#2", "confidence": "high"})
    D.append(reports, {"at": at(10), "class": "board-watch", "verdict": "applied", "target": "MH-51", "source": "tier1",
                       "command": "ela jira due MH-51 --date 2026-12-01 --note-file /nonexistent", "why": "stalled",
                       "batch": "2026-11-25-board-watch-MH-51", "act": "2026-11-25-board-watch-MH-51#1"})   # before confidence: low
    D.append(reports, {"at": at(11), "class": "link-named", "verdict": "applied", "target": "MH-61", "source": "tier1",
                       "command": "ela jira link MH-60 MH-61 --type contains", "why": "x (Open) · named by description",
                       "batch": "2026-11-25-link-named-MH-60", "act": "2026-11-25-link-named-MH-60#1"})
    D.roster_names = lambda: {"acc-ui": "Uma Interface"}
    _, rows = D.did(reports, day.isoformat())
    text = {n: t for n, t, _, _ in rows}
    check("did.md rows: low first, then medium, then high",
          [lv for *_, lv in rows] == ["low", "medium", "high", "high"] and rows[0][0] == "2026-11-25-board-watch-MH-51#1")
    check("a board-watch row names its write in plain words, the assignee by name, and the comment's first sentence once a set",
          text["2026-11-25-board-watch-MH-50#1"].startswith("MH-50: assigned to Uma Interface; its comment: \"Assigned to the "
                                                             "UI owner: the 'player' trace ends there.\" — why: UI holds it")
          and text["2026-11-25-board-watch-MH-50#2"] == "MH-50: moved to Review — why: UI holds it, see MH-49")
    check("a row below high opens with its level and its doubt",
          text["2026-11-25-board-watch-MH-51#1"].startswith("**Low**: no doubt was recorded. MH-51: due date set to 2026-12-01")
          and text["2026-11-25-link-named-MH-60#1"].startswith("**Medium**: "))
    sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
    import vault as V  # noqa: E402
    pg = V.dry_pages(reports, reports, day, record=False, jira_base="https://j")["ela/dry/did.md"]
    check("did.md: the rows below high under Review first, every key a link, the act id and undo word left as they were",
          pg.index("## Review first") < pg.index("MH-51") < pg.index("MH-60") < pg.index("## The rest") < pg.index("MH-50#1")
          and "[MH-49](https://j/browse/MH-49)" in pg and "- 2026-11-25-board-watch-MH-50#1. [MH-50](https://j/browse/MH-50): " in pg
          and {i for i, m, _ in D.did_marks(pg.replace("on the ticket`", "on the ticket` ok"))}
          == {"2026-11-25-board-watch-MH-50#1", "2026-11-25-board-watch-MH-50#2", "2026-11-25-board-watch-MH-51#1",
              "2026-11-25-link-named-MH-60#1"})

    st = W.load_state(reports)
    st["tickets"].update({"MH-70": {"verdict": "none", "decided": at(9), "why": "the train carries it", "confidence": "high"},
                          "MH-71": {"verdict": "none", "decided": at(9), "why": "answered in Slack", "confidence": "medium",
                                    "doubt": "the Slack answer may not cover QA"},
                          "MH-72": {"verdict": "none", "decided": at(9)},
                          "MH-73": {"verdict": "none", "decided": "2026-11-24T09:00:00+08:00", "why": "yesterday"}})
    W.write_json(W.state_path(reports), st)
    W.write_json(os.path.join(reports, "ela", "watch", "2026-11-25-decisions.json"),
                 {"decisions": [{"key": "MH-72", "verdict": "none", "why": "filed before confidence"}]})
    pg = W.page(reports, day, "https://j")
    tail = pg[pg.index("## Judged nothing due today"):]
    check("watch.md closes with today's nones, least sure first, each linked with its level and doubt; no CLI line",
          tail.index("MH-72") < tail.index("MH-71") < tail.index("MH-70") and "MH-73" not in tail and "ela watch answer" not in tail
          and "- [MH-72](https://j/browse/MH-72): **Low**: no doubt was recorded — filed before confidence" in tail
          and "**Medium**: the Slack answer may not cover QA — answered in Slack" in tail
          and "- [MH-70](https://j/browse/MH-70): the train carries it" in tail)
    check("the page is written for its nones even when no topic waits", list(V.watch_page(reports, day, "https://j")) == ["ela/watch.md"])

# a low-confidence act writes nothing: it is held as the owner's topic, A its writes as decided, listed first on watch.md
with tempfile.TemporaryDirectory() as t:
    facts, reports = os.path.join(t, "facts"), os.path.join(t, "reports")
    os.makedirs(os.path.join(facts, "jira", "issues")); os.makedirs(os.path.join(reports, "ela"))
    issue(facts, "MH-80", "Nobody on it", status="Review", who=None)
    issue(facts, "MH-81", "Asked plainly", who=DEV)
    scanned = {"triggered": [{"key": "MH-80", "summary": "Nobody on it"}, {"key": "MH-81", "summary": "Asked plainly"}]}
    low = {"key": "MH-80", "verdict": "act", "confidence": "low", "doubt": "two areas could own the player trace",
           "why": "the trace ends in the player", "writes": [{"verb": "assign", "assignee": "acc-ui"}],
           "comment": "Assigned to the UI owner: the trace in the last comment ends in the player."}
    ask = {"key": "MH-81", "verdict": "ask", "question": "Keep it for 2.2?", "options": [{"letter": "A", "text": "keep"}]}
    ran = []
    runner = lambda cmd, apply: (ran.append((cmd, apply)) or (0, "ok"))   # noqa: E731
    D.roster_names = lambda: {"acc-ui": "Uma Interface"}
    when = datetime.datetime(2026, 11, 26, 9, tzinfo=TZ)
    for apply in (False, True):
        r = W.decide({"decisions": [ask, low]}, scanned, facts, reports, when, apply=apply, runner=runner)
    check("a low act: no write, dry or applied, and no batch; it is held as one topic",
          ran == [] and not D.batches(reports) and r["acts"] == [] and [x["key"] for x in r["held"]] == ["MH-80"]
          and not [x for x in D.record(reports) if x.get("target") == "MH-80"])
    tp = W.load_topics(reports)["topics"]["watch:MH-80"]
    check("its option A carries the writes and the comment exactly as decided; B leaves it; the doubt is kept",
          tp["options"][0]["writes"] == low["writes"] and tp["options"][0]["comment"] == low["comment"]
          and "assign to Uma Interface" in tp["options"][0]["text"] and tp["options"][1]["writes"] == []
          and tp["unsure"]["doubt"] == low["doubt"] and "the trace ends in the player" in tp["question"])
    st = W.load_state(reports)["tickets"]["MH-80"]
    check("the ticket's record says ask, so it does not trigger again tomorrow", st["verdict"] == "ask" and st["pending"] == [])
    bad = W.decide({"decisions": [dict(low, writes=[{"verb": "transition", "to": "Done"}])]}, scanned, facts, reports, when)
    check("a low act still passes the gates first: a terminal status is refused, not held",
          bad["held"] == [] and "terminal" in bad["refused"][0]["why"])
    pg = W.page(reports, when.date(), "https://j")
    check("watch.md: the held topic first under Confirm first, with its doubt line, above the ordinary asks",
          pg.index("## Confirm first: ela was not sure") < pg.index("[MH-80]") < pg.index("**Doubt**: two areas could own")
          < pg.index("## Asks") < pg.index("[MH-81]"))
    check("the asks list it first, its doubt in the text", [x["id"] for x in W.asks(reports, when.date())] == ["watch:MH-80", "watch:MH-81"]
          and "Doubt: two areas could own" in W.asks(reports, when.date())[0]["question"])
    W.answer(reports, "watch:MH-80", "A", when)
    r = W.decide({"decisions": []}, {"triggered": []}, facts, reports, when + datetime.timedelta(days=1), apply=True, runner=runner)
    check("his A carries the writes at the next pass, recorded high: his word, not a row to review first",
          ran and ran[0][0].startswith("ela jira assign MH-80 --assignee acc-ui --note-file ")
          and [x.get("confidence") for x in D.record(reports) if x.get("target") == "MH-80"] == ["high"])

print("watch: all offline checks passed" if not fails else f"watch: {len(fails)} failed")
sys.exit(1 if fails else 0)
