#!/usr/bin/env python3
"""The board watch's second reading offline (vault plan ela/2026-11-26-plan-sweep-judges-every-field, first slice 3): a
ruling ask whose option A is only the watch's own writes, and a low act, wait as review-pending, off ela/watch.md and the
DM; one about a close, a lowered priority or labels goes straight to the owner. A case settles only with a source from
the closed list; a settled low act stays held (first slice 4); a failure or timeout releases the case marked not read
twice. Writes go to a stub runner; nothing reaches Jira or Slack."""
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
NOW = datetime.datetime(2026, 11, 26, 10, 30, tzinfo=TZ)
DEV = {"accountId": "acc-dev", "displayName": "Dev One", "accountType": "atlassian"}
ok_runner = lambda cmd, apply: (0, "ok")   # noqa: E731


def issue(facts, key):
    json.dump({"key": key, "fields": {"summary": f"Ticket {key}", "status": {"name": "Review", "statusCategory": {"key": "indeterminate"}},
                                      "assignee": DEV, "priority": {"name": "High"}, "duedate": None, "labels": [],
                                      "resolution": None, "updated": "2026-11-26T09:00:00.000+0800", "description": None},
               "comments": [{"id": "9", "author": DEV, "body": "Merged in 2.2.170.", "created": "2026-11-26T09:00:00.000+0800"}]},
              open(os.path.join(facts, "jira", "issues", f"{key}.json"), "w"))


def ask(key, writes, letter_a="move it"):
    return {"key": key, "verdict": "ask", "kind": "ruling", "confidence": "medium", "why": "the build is not confirmed",
            "question": f"What about {key}?", "options": [{"letter": "A", "text": letter_a, "writes": writes,
                                                           "comment": "Moved to Review: the fix is merged in 2.2.170."},
                                                          {"letter": "B", "text": "leave it"}]}


with tempfile.TemporaryDirectory() as t:
    facts, reports = os.path.join(t, "facts"), os.path.join(t, "reports")
    os.makedirs(os.path.join(facts, "jira", "issues")); os.makedirs(os.path.join(reports, "ela", "watch"))
    keys = ("MH-1", "MH-2", "MH-3", "MH-4", "MH-5", "MH-6")
    for k in keys:
        issue(facts, k)
    scanned = {"triggered": [{"key": k, "priority": "High", "triggers": [{"kind": "changed", "says": "x"}]} for k in keys], "replies": []}
    dec = {"decisions": [
        ask("MH-1", [{"verb": "transition", "to": "Review"}]),
        ask("MH-2", [{"verb": "transition", "to": "Done"}], "close it"),
        ask("MH-3", [{"verb": "priority", "to": "Low"}], "lower it"),
        ask("MH-4", [], "a release-scope call"),
        {"key": "MH-5", "verdict": "act", "confidence": "low", "doubt": "the merge may not be in the bundle", "why": "merged",
         "writes": [{"verb": "transition", "to": "Review"}], "comment": "Moved to Review: the fix is merged in 2.2.170."},
        ask("MH-6", [{"verb": "assign", "assignee": "acc-dev"}])]}
    r = W.decide(dec, scanned, facts, reports, NOW, apply=True, runner=ok_runner)
    pend = sorted(x["key"] for x in W.pending_review(reports, NOW))
    check("a ruling ask within the watch's verbs and a low act wait for the second reading", pend == ["MH-1", "MH-5", "MH-6"])
    seen = sorted(x["key"] for x in W.open_topics(reports, NOW))
    check("a close, a lowered priority and an ask with no watch write go straight to the owner", seen == ["MH-2", "MH-3", "MH-4"])
    check("ela/watch.md and the DM leave the pending cases out",
          "MH-1" not in W.page(reports, NOW.date(), now=NOW) and all(k not in json.dumps(W.dm_plan(W.load_topics(reports), NOW.date(), now=NOW)) for k in pend))
    doc = W.review_prompt(reports, facts, NOW)
    check("the reader's prompt lists each pending case with the closed source list",
          [c["key"] for c in doc["cases"]] == pend and doc["sources"] == list(W.SOURCES) and "Agreeing with the decider" in W.review_text(doc))

    entries = {"cases": [
        {"topic": "watch:MH-1", "settles": True, "letter": "A", "source": {"kind": "build-record", "ref": "Jenkins mh-web #170"}, "why": "the build carries the merge"},
        {"topic": "watch:MH-5", "settles": True, "letter": "A", "source": {"kind": "reporter-comment", "ref": "MH-5 comment 9"}},
        {"topic": "watch:MH-6", "settles": True, "letter": "A", "source": {"kind": "the decider agreed", "ref": "x"}}]}
    dry = W.review_settle(entries, reports, NOW, apply=False)
    check("dry run: nothing changes", len(W.pending_review(reports, NOW)) == 3 and [x["key"] for x in dry["settled"]] == ["MH-1"])
    got = W.review_settle(entries, reports, NOW, apply=True)
    tp = W.load_topics(reports)["topics"]
    check("a case with a first-hand source is settled and closed by the second reading",
          [x["key"] for x in got["settled"]] == ["MH-1"] and tp["watch:MH-1"]["closed"]["by"] == "second reading"
          and tp["watch:MH-1"]["closed"]["letter"] == "A")
    check("a source outside the closed list does not settle: the case reaches the owner, read twice, not settled",
          [x["key"] for x in got["unsettled"]] == ["MH-6"] and "MH-6" in {x["key"] for x in W.open_topics(reports, NOW)}
          and "Read twice, not settled" in W.page(reports, NOW.date(), now=NOW))
    check("a settled low act stays held for the owner, its source shown",
          [x["key"] for x in got["held"]] == ["MH-5"] and not tp["watch:MH-5"].get("closed")
          and "on reporter-comment MH-5 comment 9" in W.page(reports, NOW.date(), now=NOW))
    check("the settled ask's writes go out at the next decide, as his letter's would",
          any(x["topic"] == "watch:MH-1" and x.get("state") == "dry run" for x in W.decide({"decisions": []}, {"triggered": []}, facts, reports,
                                                                                           NOW + datetime.timedelta(days=1), apply=False, runner=ok_runner)["answered"]))
    check("a settled case is not counted as an answer of his", W.outcomes(reports)["wrong"] == 0)
    check("the rereads are kept for the measure",
          sorted((x["key"], x["outcome"]) for x in W.read_jsonl(W.decided_path(reports)) if x["verdict"] == "reread")
          == [("MH-1", "settled"), ("MH-5", "held"), ("MH-6", "unsettled")])
    ws = W.measure(facts, reports, {}, NOW.date(), weeks=1)
    check("an ask settled on the second reading counts as settled by ela", ws[0]["changed"]["settled_on_review"] == 1)

    # failure: release; timeout: shown anyway
    W.decide({"decisions": [ask("MH-1", [{"verb": "due", "date": "2026-12-01"}])]}, scanned, facts, reports,
             NOW + datetime.timedelta(days=1), apply=True, runner=ok_runner)
    later = NOW + datetime.timedelta(days=1)
    check("a new case waits again", [x["key"] for x in W.pending_review(reports, later)] == ["MH-1"])
    check("past REVIEW_WAIT_H a pending case is shown, not read twice",
          "MH-1" in {x["key"] for x in W.open_topics(reports, later + datetime.timedelta(hours=W.REVIEW_WAIT_H + 1))})
    check("release hands every pending case to the owner marked not read twice",
          W.review_release(reports, later, apply=True) == ["watch:MH-1"] and not W.pending_review(reports, later)
          and "Not read twice" in W.page(reports, later.date(), now=later))
    check("an entry for a case not pending is refused",
          W.review_settle({"cases": [{"topic": "watch:MH-2", "settles": True}]}, reports, later)["refused"][0]["topic"] == "watch:MH-2")

print(f"\n{len(fails)} failed" if fails else "\nall ok")
sys.exit(1 if fails else 0)
