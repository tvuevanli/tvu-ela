#!/usr/bin/env python3
"""The board watch's measure offline (vault plan ela/2026-11-26-plan-sweep-judges-every-field, first slice 2): decide
--apply keeps each carried decision in decided.jsonl (a none with judged_unneeded); every change is attributed (app, ela
unattended, the owner through ela, the owner in Jira, a person) against writes.jsonl; the weekly share counts a
corrected act and an overturned none as unsettled and the backlog apart; the page is its own and watch.md links it.
Writes go to a stub runner; nothing reaches Jira or Slack."""
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
NOW = datetime.datetime(2026, 11, 25, 10, 30, tzinfo=TZ)     # a Wednesday
OWNER = {"id": "acc-owner", "name": "Dana Owner"}
DEV = {"accountId": "acc-dev", "displayName": "Dev One", "accountType": "atlassian"}
ME = {"accountId": "acc-owner", "displayName": "Dana Owner", "accountType": "atlassian"}
BOT = {"accountId": "acc-bot", "displayName": "Automation for Jira", "accountType": "app"}
SIGN = "\n\n" + W.J.signature("Dana Owner")
ok_runner = lambda cmd, apply: (0, "ok")   # noqa: E731


def at(**kw):
    return (NOW + datetime.timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%S.000+0800")


def issue(facts, key, cs=()):
    json.dump({"key": key, "fields": {"summary": f"Ticket {key}", "status": {"name": "Review", "statusCategory": {"key": "indeterminate"}},
                                      "assignee": DEV, "priority": {"name": "Medium"}, "duedate": None, "labels": [],
                                      "resolution": None, "updated": at(hours=-1), "description": None},
               "comments": list(cs), "updated": at(hours=-1)},
              open(os.path.join(facts, "jira", "issues", f"{key}.json"), "w"))


def hist(hid, who, when, field, a, b):
    return {"id": hid, "author": who, "created": when, "items": [{"field": field, "fromString": a, "toString": b}]}


with tempfile.TemporaryDirectory() as t:
    facts, reports = os.path.join(t, "facts"), os.path.join(t, "reports")
    os.makedirs(os.path.join(facts, "jira", "issues")); os.makedirs(os.path.join(reports, "ela", "watch"))
    for k in ("MH-1", "MH-2", "MH-3", "MH-4", "MH-5"):
        issue(facts, k)
    issue(facts, "MH-6", cs=[{"id": "1", "author": ME, "body": "Assigned to its owner." + SIGN, "created": at(minutes=1)},
                             {"id": "2", "author": BOT, "body": "(Copied from MH-9) x", "created": at(minutes=2)},
                             {"id": "3", "author": DEV, "body": "on it", "created": at(minutes=30)}])
    scanned = {"triggered": [{"key": "MH-1", "triggers": [{"kind": "changed", "says": "x"}]},
                             {"key": "MH-2", "triggers": [{"kind": "answered", "says": "x"}]},
                             {"key": "MH-3", "triggers": [{"kind": "changed", "says": "x"}]},
                             {"key": "MH-4", "triggers": [{"kind": "stalled", "says": "x"}]},
                             {"key": "MH-5", "triggers": [{"kind": "changed", "says": "x"}]}], "replies": []}
    dec = {"decisions": [
        {"key": "MH-1", "verdict": "act", "confidence": "high", "why": "w", "comment": "Assigned to the UR owner: the fix is in UR.",
         "writes": [{"verb": "assign", "assignee": "acc-dev"}]},
        {"key": "MH-2", "verdict": "none", "confidence": "high", "why": "nothing waits", "judged_unneeded": ["status", "assignee"]},
        {"key": "MH-3", "verdict": "none", "confidence": "high", "why": "nothing waits", "judged_unneeded": ["priority"]},
        {"key": "MH-4", "verdict": "none", "confidence": "high", "why": "stall is expected"},
        {"key": "MH-5", "verdict": "ask", "kind": "ruling", "confidence": "medium", "why": "w", "question": "Close it?"}]}
    bad = W.decide({"decisions": [dict(dec["decisions"][1], judged_unneeded=["mood"])]}, scanned, facts, reports, NOW, apply=False)
    check("a none's judged_unneeded is a closed list", bad["refused"] and "judged_unneeded" in bad["refused"][0]["why"])
    W.decide(dec, scanned, facts, reports, NOW, apply=False, runner=ok_runner)
    check("a dry run keeps no decision", not os.path.exists(W.decided_path(reports)))
    W.decide(dec, scanned, facts, reports, NOW, apply=True, runner=ok_runner)
    kept = {r["key"]: r for r in W.read_jsonl(W.decided_path(reports))}
    check("decide --apply keeps each carried decision with its verdict, kinds and fields",
          kept["MH-1"]["verdict"] == "act" and kept["MH-1"]["fields"] == ["assignee", "comment"] and kept["MH-1"]["kinds"] == ["changed"]
          and kept["MH-2"]["judged_unneeded"] == ["assignee", "status"] and kept["MH-4"]["judged_unneeded"] is None
          and kept["MH-5"]["verdict"] == "ask")

    # the week's changes: ela's own assign (matched to writes.jsonl), a person overturning MH-2's status, the owner by
    # hand on MH-3, an app's link
    with open(os.path.join(reports, "ela", "writes.jsonl"), "w") as f:
        f.write(json.dumps({"at": (NOW + datetime.timedelta(minutes=1)).isoformat(), "system": "jira", "verb": "assign",
                            "key": "MH-1", "ok": True, "unattended": True}) + "\n")
        f.write(json.dumps({"at": (NOW + datetime.timedelta(minutes=1)).isoformat(), "system": "jira", "verb": "comment",
                            "key": "MH-6", "ok": True, "unattended": False}) + "\n")
    W.write_json(os.path.join(facts, "jira", "changes.json"), [
        {"key": "MH-1", "changelog": {"histories": [hist("h1", ME, at(minutes=1), "assignee", "A", "Dev One")]}},
        {"key": "MH-2", "changelog": {"histories": [hist("h2", DEV, at(hours=5), "status", "Review", "In Progress")]}},
        {"key": "MH-3", "changelog": {"histories": [hist("h3", ME, at(hours=6), "priority", "Medium", "High")]}},
        {"key": "MH-4", "changelog": {"histories": [hist("h4", BOT, at(hours=6), "Link", None, "relates to MH-9")]}}])
    ch = W.attribute(facts, reports, OWNER, NOW - datetime.timedelta(days=1), NOW + datetime.timedelta(days=1))
    who = {(c["key"], c["field"]): c["who"] for c in ch}
    check("ela's own unattended write is attributed to ela", who[("MH-1", "assignee")] == "ela unattended")
    check("a signed comment matched to a session write is the owner through ela",
          [c["who"] for c in ch if c["key"] == "MH-6"] == ["owner through ela", "app", "human"])
    check("the owner's change with no write of ela's is the owner in Jira", who[("MH-3", "priority")] == "owner in Jira")
    check("a colleague's change is human; an app's is app", who[("MH-2", "status")] == "human" and who[("MH-4", "links")] == "app"
          and ("MH-6", "comment") in who and sum(1 for c in ch if c["key"] == "MH-6" and c["who"] == "app") == 1)

    # MH-1's act is corrected (a revert): not settled
    D.append(reports, {"at": (NOW + datetime.timedelta(hours=2)).isoformat(timespec="seconds"), "class": "board-watch",
                       "verdict": "reverted", "how": "revert", "target": "MH-1", "key": "MH-1", "field": "assign",
                       "note": "the lead set it back", "source": "correction"})
    W.fold_corrections(reports, W.load_state(reports))
    ws = W.measure(facts, reports, OWNER, NOW.date(), weeks=2)
    c, b = ws[0]["changed"], ws[0]["backlog"]
    check("the week: an act corrected, a none overturned by a person, a none the owner overrode still settled",
          c["acts"] == 1 and c["corrected"] == 1 and c["nones"] == 2 and c["overturned"] == 1 and c["asks"] == 1
          and c["settled"] == 1 and c["share"] == 0.25)
    check("the backlog is counted apart", b["decided"] == 1 and b["nones"] == 1 and b["nones_unfielded"] == 1 and b["share"] == 1.0)
    check("the week is Monday-first and marked so far; last week is empty", ws[0]["week"] == "2026-11-23" and ws[0]["partial"]
          and ws[1]["changed"]["decided"] == 0 and ws[1]["changed"]["share"] is None)
    check("changes are counted by who", ws[0]["changes"]["human"] >= 2 and ws[0]["changes"]["ela unattended"] == 1
          and ws[0]["changes"]["owner in Jira"] == 1)
    pg = W.measure_page(facts, reports, OWNER, NOW.date())
    check("the page leads with this week's share against last week, the detail folded",
          "**25%** of 4 judged tickets settled without you; last week — of 0." in pg and "> [!note]- Week by week" in pg
          and "> [!note]- Who changed MH tickets" in pg)
    check("ela/watch.md links the measure once", W.page(reports, NOW.date()).count("[[ela/watch-measure|the measure]]") == 1)

    # each pass's prompt is kept beside its scan
    p = W.prompt_keep_path(reports, NOW)
    check("the prompt's keep path is <date>-<HHMM>-prompt.json beside the scan",
          os.path.dirname(p) == os.path.dirname(W.scan_path(reports, "2026-11-25")) and p.endswith("2026-11-25-1030-prompt.json"))

print(f"\n{len(fails)} failed" if fails else "\nall ok")
sys.exit(1 if fails else 0)
