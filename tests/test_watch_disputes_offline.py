#!/usr/bin/env python3
"""The watch's dispute detector offline (decision 2026-11-24: a reply disputing ela's signed comment is a correction).
Stub tickets in a temp fact store: an agreeing reply, a disputing reply and an ambiguous one (a dispute). Every write
goes to a stub runner and the class's state is a temp file, so nothing reaches Jira or Slack."""
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
SIGN = "\n\n" + W.J.signature("Dana Owner")
DEV = {"accountId": "acc-dev", "displayName": "Dev One", "accountType": "atlassian"}
QA = {"accountId": "acc-qa", "displayName": "Qa One", "accountType": "atlassian"}


def ts(d):
    return d.strftime("%Y-%m-%dT%H:%M:%S.000+0800")


def issue(facts, key, cs):
    json.dump({"key": key, "fields": {"summary": f"Ticket {key}", "status": {"name": "Review", "statusCategory": {"key": "indeterminate"}},
                                      "assignee": DEV, "priority": {"name": "Medium"}, "duedate": None, "labels": [],
                                      "resolution": None, "updated": ts(NOW - datetime.timedelta(hours=1)), "description": None},
               "comments": cs, "updated": ts(NOW - datetime.timedelta(hours=1))},
              open(os.path.join(facts, "jira", "issues", f"{key}.json"), "w"))


ran = []
runner = lambda cmd, apply: (ran.append((cmd, apply)) or (0, "ok"))   # noqa: E731

with tempfile.TemporaryDirectory() as t:
    facts, reports = os.path.join(t, "facts"), os.path.join(t, "reports")
    os.makedirs(os.path.join(facts, "jira", "issues")); os.makedirs(os.path.join(reports, "ela"))
    acted = NOW - datetime.timedelta(days=1)
    # yesterday's board-watch acts on three tickets, as `ela dry act` records them
    for k in ("MH-21", "MH-22", "MH-23"):
        D.append(reports, {"at": acted.isoformat(timespec="seconds"), "class": "board-watch", "verdict": "applied", "as_drafted": True,
                           "target": k, "command": f"ela jira transition {k} --to Review --note-file x", "batch": f"2026-11-23-board-watch-{k}",
                           "act": f"2026-11-23-board-watch-{k}#1", "source": "tier1"})
    ela_c = lambda cid: {"id": cid, "author": {"accountId": "acc-owner", "displayName": "Dana Owner"},   # noqa: E731
                         "body": "Moved to Review: the fix is in build 2.1.40." + SIGN, "created": ts(acted + datetime.timedelta(minutes=1))}
    reply = lambda cid, who, text: {"id": cid, "author": who, "body": text, "created": ts(acted + datetime.timedelta(hours=3))}  # noqa: E731
    issue(facts, "MH-21", [ela_c("100"), reply("101", DEV, "Thanks, agreed, QA can take it from here.")])
    issue(facts, "MH-22", [ela_c("200"), reply("201", QA, "This is wrong: 2.1.40 does not carry the fix, it is still In Progress.")])
    issue(facts, "MH-23", [ela_c("300"), reply("301", DEV, "Hmm, maybe.")])
    issue(facts, "MH-24", [{"id": "400", "author": DEV, "body": "No ela comment here, just a note.", "created": ts(acted)}])

    got = W.scan(facts, reports, NOW, holds={"holds": {}, "read": {}}, lines=[], owner=OWNER, write=True, base="https://j")
    reps = {x["key"]: x for x in got["replies"]}
    check("each reply after ela's signed comment is listed for judgment; a ticket without one is not",
          sorted(reps) == ["MH-21", "MH-22", "MH-23"])
    check("a reply carries its link and the act ela's comment carried",
          reps["MH-22"]["link"] == "https://j/browse/MH-22?focusedCommentId=201" and reps["MH-22"]["act"] == "2026-11-23-board-watch-MH-22#1"
          and reps["MH-22"]["class"] == "board-watch")
    check("the prompt asks the session to mark them, unsure counting as a dispute",
          "Replies to ela's signed comments" in W.prompt_text(got, W.prompt_rows(got, facts), "x.json") and "unsure" in W.prompt_text(got, [], "x"))

    marks = {"decisions": [], "replies": [{"key": "MH-21", "reply": "101", "disputes": False},
                                          {"key": "MH-22", "reply": "201", "disputes": True},
                                          {"key": "MH-23", "reply": "301", "disputes": "unsure"}]}
    st0 = D.load_state(reports)["board-watch"]["tier"]
    r = W.decide(marks, got, facts, reports, NOW, apply=False, runner=runner)
    check("dry run: agreement and disputes told, nothing recorded or demoted",
          [x["key"] for x in r["agreed"]] == ["MH-21"] and sorted(x["key"] for x in r["disputes"]) == ["MH-22", "MH-23"]
          and not [x for x in D.record(reports) if x.get("verdict") == "corrected"] and D.load_state(reports)["board-watch"]["tier"] == st0
          and W.open_topics(reports) == [])

    r = W.decide(marks, got, facts, reports, NOW, apply=True, runner=runner)
    corr = [x for x in D.record(reports) if x.get("verdict") == "corrected"]
    check("the agreeing reply is no correction", "MH-21" not in {x["key"] for x in r["disputes"]}
          and not any("MH-21" in (x.get("target") or "") for x in corr))
    check("the disputing reply is recorded through dry as corrected, with the act id and the reply's link",
          any(x["target"] == "2026-11-23-board-watch-MH-22#1" and "https://j/browse/MH-22?focusedCommentId=201" in x["note"]
              and x["class"] == "board-watch" for x in corr))
    check("the ambiguous reply counts as a dispute", any(x["target"] == "2026-11-23-board-watch-MH-23#1" for x in corr))
    check("a dispute returns board-watch to confirm (the demotion path)", D.load_state(reports)["board-watch"]["tier"] == 3)
    a = W.asks(reports, NOW.date())
    qs = {x["id"]: x["question"] for x in a}
    check("each dispute is an ask on today.md naming the ticket and the reply",
          len(a) == 2 and "MH-22" in qs.get("watch:MH-22:reply-201", "") and "focusedCommentId=201" in qs["watch:MH-22:reply-201"]
          and "MH-23" in qs.get("watch:MH-23:reply-301", ""))
    check("no Jira write was made by judging replies", ran == [])

    again = W.scan(facts, reports, NOW, holds={"holds": {}, "read": {}}, lines=[], owner=OWNER, base="https://j")
    check("a judged reply is not listed again", again["replies"] == [])
    n = len(corr)
    W.decide(marks, got, facts, reports, NOW, apply=True, runner=runner)
    check("a reply is recorded once", len([x for x in D.record(reports) if x.get("verdict") == "corrected"]) == n)

    # no re-comment on a disputed ticket for 7 days
    day3 = NOW + datetime.timedelta(days=3)
    got3 = {"triggered": [{"key": "MH-22", "summary": "x"}, {"key": "MH-21", "summary": "y"}], "replies": []}
    act = lambda k: {"key": k, "verdict": "act", "confidence": "high", "writes": [], "comment": f"A nudge on {k}: what is the next step?"}  # noqa: E731
    r = W.decide({"decisions": [act("MH-22"), act("MH-21")]}, got3, facts, reports, day3, apply=False, runner=runner)
    check("within 7 days a disputed ticket gets no comment; an undisputed one does",
          [x["key"] for x in r["refused"]] == ["MH-22"] and "until 2026-12-01" in r["refused"][0]["why"]
          and [x["key"] for x in r["acts"]] == ["MH-21"])
    day8 = NOW + datetime.timedelta(days=7)
    r = W.decide({"decisions": [act("MH-22")]}, {"triggered": [{"key": "MH-22"}], "replies": []}, facts, reports, day8,
                 apply=False, runner=runner)
    check("after 7 days the ticket may be commented on again", r["refused"] == [] and [x["key"] for x in r["acts"]] == ["MH-22"])
    s4 = W.scan(facts, reports, NOW + datetime.timedelta(days=6), holds={"holds": {}, "read": {}}, lines=[], owner=OWNER, base="https://j")
    row = next((x for x in s4["triggered"] if x["key"] == "MH-22"), None)
    check("the scan tells the session a disputed ticket is quiet", row is not None and row["quiet_until"] == "2026-12-01"
          and "no comment until 2026-12-01" in W.prompt_text(s4, [dict(row, comments=[])], "x"))
    check("a mark for a reply the scan did not list is refused",
          W.decide({"replies": [{"key": "MH-24", "reply": "400", "disputes": True}]}, {"triggered": [], "replies": []}, facts, reports,
                   NOW, apply=False)["refused_replies"][0]["key"] == "MH-24")

print(f"\n{len(fails)} failed" if fails else "\nall ok")
sys.exit(1 if fails else 0)
