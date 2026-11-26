#!/usr/bin/env python3
"""Tracked tickets offline (vault plan ela/2026-11-26-plan-sweep-judges-every-field, brief: the owner tracks tickets for a
release instead of ruling now): `track` and `untrack` in a temp store; a tracked ticket is due a decision on a change
by a person (a field from the changelog, a comment, a link), never on ela's, the owner's or an app's; legacy does not
hide it; --until ends it. Nothing reaches Jira or Slack."""
import datetime, json, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "watch"))
import watch as W  # noqa: E402

fails = []


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


TZ = W.TZ
NOW = datetime.datetime(2026, 11, 26, 9, 0, tzinfo=TZ)
OWNER = {"id": "acc-owner", "name": "Dana Owner"}
DEV = {"accountId": "acc-dev", "displayName": "Dev One", "accountType": "atlassian"}
ME = {"accountId": "acc-owner", "displayName": "Dana Owner", "accountType": "atlassian"}
BOT = {"accountId": "acc-bot", "displayName": "Automation for Jira", "accountType": "app"}
SIGN = "\n\n" + W.J.signature("Dana Owner")


def at(**kw):
    return (NOW + datetime.timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%S.000+0800")


def issue(facts, key, cs=(), updated=None):
    json.dump({"key": key, "fields": {"summary": f"Ticket {key}", "status": {"name": "Review", "statusCategory": {"key": "indeterminate"}},
                                      "assignee": DEV, "priority": {"name": "Medium"}, "duedate": None, "labels": [],
                                      "resolution": None, "updated": updated or at(hours=-1), "description": None},
               "comments": list(cs), "updated": updated or at(hours=-1)},
              open(os.path.join(facts, "jira", "issues", f"{key}.json"), "w"))


def hist(who, when, field, a, b):
    return {"id": when, "author": who, "created": when, "items": [{"field": field, "fromString": a, "toString": b}]}


H = {"holds": {}, "read": {}}
with tempfile.TemporaryDirectory() as t:
    facts, reports = os.path.join(t, "facts"), os.path.join(t, "reports")
    os.makedirs(os.path.join(facts, "jira", "issues")); os.makedirs(os.path.join(reports, "ela"))
    old = (NOW - datetime.timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%S.000+0800")
    issue(facts, "MH-1", updated=old)                                     # legacy, but tracked
    issue(facts, "MH-2", cs=[{"id": "1", "author": DEV, "body": "Merged to release 2.2.", "created": at(hours=2)}])
    issue(facts, "MH-3", cs=[{"id": "1", "author": ME, "body": "my own note", "created": at(hours=2)},
                             {"id": "2", "author": ME, "body": "Assigned to its owner." + SIGN, "created": at(hours=2)},
                             {"id": "3", "author": BOT, "body": "(Copied from MH-9) x", "created": at(hours=2)}])
    issue(facts, "MH-4", cs=[{"id": "1", "author": DEV, "body": "A change nobody tracks.", "created": at(hours=2)}])
    W.write_json(os.path.join(facts, "jira", "changes.json"), [
        {"key": "MH-1", "changelog": {"histories": [hist(DEV, at(hours=1), "status", "In Progress", "Review"),
                                                    hist(DEV, at(hours=-5), "assignee", "A", "B")]}},
        {"key": "MH-3", "changelog": {"histories": [hist(ME, at(hours=1), "priority", "Medium", "High"),
                                                    hist(BOT, at(hours=1), "Link", None, "relates to MH-9")]}}])

    got = W.track(reports, ["mh-1", "MH-2", "MH-3"], NOW, why="2.2.0 scope", until="2026-12-31")
    check("track keeps each key with its reason, its first day and its until",
          [r["key"] for r in got] == ["MH-1", "MH-2", "MH-3"] and got[0]["why"] == "2.2.0 scope" and got[0]["until"] == "2026-12-31"
          and sorted(W.tracking(reports, "2026-11-26")) == ["MH-1", "MH-2", "MH-3"])
    try:
        W.track(reports, ["nonsense"], NOW); bad = False
    except ValueError:
        bad = True
    check("a word that is not a key is refused", bad)

    later = NOW + datetime.timedelta(hours=3)
    s = W.scan(facts, reports, later, holds=H, lines=[], owner=OWNER, base="https://j")
    rows = {r["key"]: r for r in s["triggered"]}
    check("a status change by a person on a tracked ticket makes it due, legacy or not",
          "MH-1" in rows and any(x["kind"] == "tracked" and "Dev One changed status: In Progress → Review" in x["says"]
                                 for x in rows["MH-1"]["triggers"]))
    check("a change before tracking began does not count", "assignee" not in json.dumps(rows["MH-1"]["triggers"]))
    check("a colleague's comment on a tracked ticket makes it due, its reason on the row",
          any(x["kind"] == "tracked" and "Merged to release 2.2." in x["says"] for x in rows["MH-2"]["triggers"])
          and rows["MH-2"]["tracked"] == {"why": "2.2.0 scope", "until": "2026-12-31"})
    check("the owner's own changes, ela's signed comments and an app's are not a tracked change",
          not any(x["kind"] == "tracked" for x in (rows.get("MH-3") or {}).get("triggers") or []))
    check("an untracked ticket with a comment is not due by tracking", not any(x["kind"] == "tracked" for x in (rows.get("MH-4") or {}).get("triggers") or []))
    check("tracked tickets come first in the pass", [r["key"] for r in s["triggered"]][:2] == ["MH-1", "MH-2"])
    check("the prompt names the reason it is tracked",
          "tracked on the owner's word: 2.2.0 scope" in W.prompt_text(s, [dict(rows["MH-2"], comments=[])], "x"))

    st = W.load_state(reports)
    st["tickets"].setdefault("MH-2", {})["decided"] = (NOW + datetime.timedelta(hours=2, minutes=30)).isoformat()
    W.write_json(W.state_path(reports), st)
    s = W.scan(facts, reports, later, holds=H, lines=[], owner=OWNER, base="https://j")
    check("a change already decided does not trigger again",
          not any(x["kind"] == "tracked" for r in s["triggered"] if r["key"] == "MH-2" for x in r["triggers"]))

    check("untrack ends it and keeps the row", W.untrack(reports, ["MH-2"], NOW) == ["MH-2"]
          and "MH-2" not in W.tracking(reports, "2026-11-26") and W.load_tracked(reports)["tickets"]["MH-2"]["ended"])
    check("after --until it is no longer tracked", "MH-1" not in W.tracking(reports, "2027-01-01"))
    check("tracked is a kind a precedent may be filed under", "tracked" in W.KINDS)

print(f"\n{len(fails)} failed" if fails else "\nall ok")
sys.exit(1 if fails else 0)
