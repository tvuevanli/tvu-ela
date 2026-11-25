#!/usr/bin/env python3
"""release:must cleared at the deploy that ships the ticket, offline (vault releases/release-naming.md rule 6): shipped
is a plain official bundle carrying the ticket and the prod lane carrying its fix; the clears are one dry-run batch of
the release-must-clear class, applied only on his A; a clear lands on the ticket's history line in next.json; and the
Friday summary in Slack mrkdwn. Nothing here reads a source or writes to Jira or Slack."""
import datetime, os, re, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "release"))
sys.path.insert(0, os.path.join(ROOT, "skills", "dry"))
import nextrel as N  # noqa: E402
import dry as D  # noqa: E402

TZ = datetime.timezone(datetime.timedelta(hours=8))
NOW = datetime.datetime(2026, 11, 30, 17, 40, tzinfo=TZ)            # the Monday of the 2.2.0 deploy
CFG = {"lanes": {"qa": "qa-cn3", "daily": "daily-wed", "prod": "prod-3"}, "bundle_line": "mh2.1@", "ships_as": ["2.2"], "ships_as_since": "2026-11-30"}
BASE = {"name": "MediaHub 2.1.19", "id": "1", "created": "2026-11-17 16:45", "rule": "the newest plain official bundle before the release"}
REL = {"name": "MediaHub 2.2.0", "id": "3", "created": "2026-11-30 10:00", "rule": ""}
CAND = {"name": "mh2.1@daily-wed-s2-d57", "id": "2", "created": "2026-11-20 10:03", "rule": "prefix"}
URL = "https://tvunetworks.atlassian.net/browse/"
TICKETS = {"tickets": [{"key": k, "exists": True, "summary": f"ticket {k}", "status": "Done", "url": URL + k, "services_in_delta": []}
                       for k in ("MH-1", "MH-2", "MH-5")]}
PROD = {"arrived": "2.1.49", "since": "2026-11-30", "verdict": None}
TRAIN = {"lanes": [], "rows": [{"key": "MH-1", "position": "prod", "cells": {"prod-3": PROD}},          # in 2.2.0, on prod-3
                               {"key": "MH-2", "position": "daily", "cells": {"daily-wed": PROD}},     # in 2.2.0, not on prod-3
                               {"key": "MH-3", "position": "prod", "cells": {"prod-3": PROD}},         # on prod-3, not in 2.2.0
                               {"key": "MH-4", "position": "prod", "cells": {"prod-3": PROD}}]}        # cleared already
MUST = [{"key": k, "summary": f"ticket {k}", "status": "Done", "type": "Bug"} for k in ("MH-1", "MH-2", "MH-3", "MH-4")]
CLEARED = [{"at": "2026-11-30T11:00:00+08:00", "class": "release-must-clear", "verdict": "applied", "target": "MH-4",
            "batch": "2026-11-30-release-must-clear-mh-2.1", "act": "2026-11-30-release-must-clear-mh-2.1#2"},
           {"at": "2026-11-29T11:00:00+08:00", "class": "release-must-clear", "verdict": "applied", "target": "MH-9",
            "batch": "2026-11-29-release-must-clear-mh-2.1"},
           {"at": "2026-10-01T11:00:00+08:00", "class": "release-must-clear", "verdict": "applied", "target": "MH-8"},
           {"at": "2026-11-30T11:00:00+08:00", "class": "release-reconcile", "verdict": "applied", "target": "MH-7"}]
PREV = {"must": [{"key": "MH-9", "url": URL + "MH-9", "summary": "shipped in 2.2.0 and cleared yesterday", "status": "Done",
                  "history": [{"at": "2026-11-20T09:00:00+08:00", "event": "labelled"}]}]}


def inp(**kw):
    d = {"line": "2.1", "cfg": CFG, "base": BASE, "candidate": CAND, "candidate_source": "newest", "released": True,
         "released_bundle": REL, "tickets": TICKETS, "report": {}, "train": TRAIN, "must_rows": MUST,
         "must_since": {"MH-1": "2026-11-25T09:00:00.000+0800"}, "indev_rows": [], "sources": {}, "gaps": [],
         "previous": PREV, "clear_batches": [], "clear_records": CLEARED}
    d.update(kw)
    return d


fails = []


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        fails.append(what)


# ── shipped ────────────────────────────────────────────────────────────────────────────────────────────────────────
doc = N.build(inp(), NOW)
must = {m["key"]: m for m in doc["must"]}
check(must["MH-1"]["shipped"] == {"bundle": "MediaHub 2.2.0", "lane": "prod-3", "arrived": "2.1.49", "since": "2026-11-30"},
      "released: in the official bundle's content and on prod-3 by the train is shipped, in that bundle")
check(must["MH-2"]["shipped"] is None, "in the bundle but its fix not yet on the prod lane: not shipped")
check(must["MH-3"]["shipped"] is None, "on the prod lane but not in the released bundle's content: not shipped by this release")
planned = N.build(inp(released=False, released_bundle=None, clear_records=[]), NOW)
pm = {m["key"]: m for m in planned["must"]}
check(pm["MH-3"]["shipped"] == dict(must["MH-1"]["shipped"], bundle="MediaHub 2.1.19") and pm["MH-1"]["shipped"] is None,
      "planned: on the prod lane and not on the candidate shipped in the base; the candidate's content never ships")
check(doc["counts"]["must"] == 3 and doc["counts"]["must_shipped"] == 1 and doc["counts"]["must_cleared"] == 2,
      "counts: must still owed, shipped of them, cleared")
check(doc["schema"] == 3 and "3 tickets must ship (1 shipped, the label's clear waiting on your A)," in doc["head"]["lede"]
      and doc["head"]["lede"].count(".") == 1, "schema 3; the lede names the shipped must tickets, still one sentence")

# ── the batch: one per line, a label removal each, only his A applies it ─────────────────────────────────────────
w = N.clear_writes(doc)
check([x["target"] for x in w] == ["MH-1"] and w[0]["command"] == "ela jira label MH-1 --remove release:must"
      and "MediaHub 2.2.0 is on prod-3" in w[0]["why"], "the writes: one label removal per shipped ticket, with why")
rx = re.compile(D.CLASSES["release-must-clear"]["command"])
check(all(rx.match(x["command"]) for x in w) and not rx.match("ela jira label MH-1 --remove release:mh-2.1")
      and not rx.match("ela jira label MH-1 --add release:must"), "the class admits the removal of release:must and nothing else")
check(D.CLASSES["release-must-clear"]["ladder"] == (3,) and D.reversible("release-must-clear")[0],
      "the class never climbs past his confirm, and its reverse atom exists")
check(D.class_of_action({"command": "ela jira label MH-1 --remove release:must"}) == "release-must-clear"
      and D.class_of_action({"command": "ela jira label MH-1 --add release:mh-2.0"}) == "release-reconcile",
      "a past write is attributed to the clear class only when it is the clear")
with tempfile.TemporaryDirectory() as reports:
    bid = N.propose_clears(doc, reports, NOW.date())
    b = D.load_batch(reports, bid)
    check(bid == "2026-11-30-release-must-clear-mh-2.1" and b["state"] == "open" and len(b["writes"]) == 1,
          "propose: one open batch for the line, asked on today.md")
    ask = next(a for a in D.asks(reports, NOW.date(), ask_state={}) if a["id"] == f"dry:{bid}")
    check(ask["options"][0]["does"] == f"ela dry answer dry:{bid} A --apply" and "1 label clear ready" in ask["question"],
          "the ask: A applies the batch, B drops it")
    check(N.propose_clears(doc, reports, NOW.date()) == bid and len(D.batches(reports)) == 1, "a later pass carries the same batch, never a second")
    ran = []
    D.answer(reports, f"dry:{bid}", "A", apply=False, runner=lambda c, ap: (ran.append((c, ap)), (0, "DRY RUN"))[1])
    check(ran == [("ela jira label MH-1 --remove release:must", False)] and D.load_batch(reports, bid)["state"] == "open",
          "a dry answer runs the write without --apply and leaves the batch open")
    D.answer(reports, f"dry:{bid}", "A", apply=True, runner=lambda c, ap: (0, "MH-1: labels -release:must"), now=NOW)
    rec = [r for r in D.record(reports) if r.get("class") == "release-must-clear"]
    check(D.load_batch(reports, bid)["state"] == "applied" and rec and rec[-1]["target"] == "MH-1",
          "his A with --apply: applied, the clear on the record")
    after = N.build(inp(clear_records=rec, previous=doc), NOW)
    cl = {m["key"]: m for m in after["must_cleared"]}
    check("MH-1" in cl and "MH-1" not in {m["key"] for m in after["must"]}
          and [h["event"] for h in cl["MH-1"]["history"]] == ["labelled", "shipped", "cleared"],
          "the next file: the ticket moves to must_cleared, its history line labelled → shipped → cleared")
    nothing = N.build(inp(must_rows=[m for m in MUST if m["key"] != "MH-1"], clear_records=rec, previous=after), NOW)
    check(N.propose_clears(nothing, reports, (NOW + datetime.timedelta(days=1)).date()) is None,
          "nothing left to clear: no batch")

# ── the history line ─────────────────────────────────────────────────────────────────────────────────────────────
cl = {m["key"]: m for m in doc["must_cleared"]}
check(set(cl) == {"MH-4", "MH-9"}, "cleared within 14 days: still labelled in a stale store (MH-4) or carried from the last file (MH-9); older ones and other classes not")
check(cl["MH-9"]["summary"] == "shipped in 2.2.0 and cleared yesterday" and [h["event"] for h in cl["MH-9"]["history"]] == ["labelled", "cleared"]
      and cl["MH-9"]["history"][-1] == {"at": "2026-11-29T11:00:00+08:00", "event": "cleared", "batch": "2026-11-29-release-must-clear-mh-2.1", "by": "the owner's approve"},
      "a carried ticket keeps its row and history, the clear appended with its batch")
check([h["event"] for h in must["MH-1"]["history"]] == ["labelled", "shipped"] and must["MH-1"]["history"][0]["at"] == "2026-11-25T09:00:00+08:00",
      "a must ticket's history: labelled (ISO), then shipped")
prop = N.build(inp(clear_records=[], clear_batches=[{"id": "b1", "class": "release-must-clear", "state": "open", "made": "2026-11-30T08:05:00+08:00",
                                                     "writes": [{"n": 1, "target": "MH-1", "command": "x"}]}]), NOW)
check([h["event"] for h in prop["must"][0]["history"]][-1] == "clear proposed" and prop["must"][0]["history"][-1]["batch"] == "b1",
      "an open batch shows as clear proposed on the history line")
again = N.build(inp(must_since={"MH-4": "2026-11-30T12:00:00.000+0800"}), NOW)
check("MH-4" in {m["key"] for m in again["must"]} and "MH-4" not in {m["key"] for m in again["must_cleared"]},
      "labelled again after the clear: owed again")

# ── the Friday summary ───────────────────────────────────────────────────────────────────────────────────────────
fri = N.build(inp(released=False, released_bundle=None, clear_records=[], report={"evidence": {"keys": {
    "MH-1": {"verdict": "fail", "source": "jira"}, "MH-2": {"verdict": "pass", "source": "mail"}}}}),
    datetime.datetime(2026, 11, 27, 17, 35, tzinfo=TZ))
fri["on_candidate"].append({"key": "MH-6", "url": URL + "MH-6", "summary": "a <tag> & more", "assignee": "Dev", "qa": None})
text = N.slack_summary(fri, datetime.datetime(2026, 11, 27, 17, 36, tzinfo=TZ))
check(text.startswith("_Dry run, to you only") and "*MediaHub 2.2.0* → prod-3 (UR/J2N Prod 3), planned for Monday 30 Nov" in text,
      "the summary opens as a dry run to him, then the release, its lane and date")
check("*QA fail (1)*\n• <" + URL + "MH-1|MH-1> ticket MH-1" in text and "*No QA verdict (2)*" in text
      and "<" + URL + "MH-6|MH-6> a &lt;tag&gt; &amp; more · Dev" in text,
      "fail and no-verdict tickets listed as Slack links, text escaped")
check("*Must, not on the candidate: hold or defer (" in text and "• must 4, " in text and "on the candidate 3: QA fail 1 · no QA verdict 2" in text,
      "the key figures and the must tickets the candidate lacks")
check(not re.search(r"\*\*|^#|\[[^\]]+\]\(|^---|^\s+[-*] ", text, re.M), "Slack mrkdwn: no Markdown bold, heading, link, rule or nested list")
print("release must clear: all offline checks passed" if not fails else f"release must clear: {len(fails)} failed")
sys.exit(1 if fails else 0)
