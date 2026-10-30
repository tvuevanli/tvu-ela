#!/usr/bin/env python3
"""Tiers, offline: each action's tier against the closed rules and its form on the page; a revert and a contradicting
reply count as corrections; three on one rule in seven days demote it."""
import datetime, json, os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "brief"))
sys.path.insert(0, os.path.join(ROOT, "skills", "review"))
import brief as B  # noqa: E402
import review as RV  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

THREAD = "https://tvunetworks.slack.com/archives/C0C16LK4KT9/p1793180233748809"
acts = [{"n": 1, "tier": 1, "rule": "fact-comment", "evidence": "QA's fail on build 77, comment 10-28", "command": "ela jira comment MH-1 --from-file f"},
        {"n": 2, "tier": 2, "rule": "train-hold", "evidence": "build 77 report 10-28: MH-3820 untested",
         "command": f"ela slack post {THREAD} --file f --team-thread", "channel": "mediahub-qa-release"},
        {"n": 3, "tier": 3, "command": "ela jira close MH-3 --from-file f"},
        {"n": 4, "command": "ela jira comment MH-4 --from-file f"}]
page = ("### 1. MH-1\nfacts\n- **Do:**\n- done 1 — the QA fail recorded on MH-1 · evidence: comment 10-28\n"
        "- [ ] don't 2 — at 10:00 unless you tick: hold the train on build 77\n- [ ] apply 3 — close MH-3\n- [ ] apply 4 — comment MH-4\n")
verdict = {"build": "77"}
check("tiers as written pass, and no tier reads as tier 3", B.tier_check(page, acts, {}, verdict) == [])
check("lint takes a done line and a don't box as Do lines", [x for x in RV.lint(page, acts) if "Do line" in x or "box" in x] == [])
bad = [dict(acts[0], command="ela jira close MH-1 --from-file f"), dict(acts[1], tier=1), dict(acts[2], tier=2, rule="thread-reply")]
f = B.tier_check(page, bad, {}, verdict)
check("a close is never what fact-comment admits", any("action 1: its command is not" in x for x in f))
check("a tier-1 rule is not a tier-2 one, and the page form must match", any("action 2: tier 1 needs" in x for x in f) and any("action 2: tier 1, but the page writes it as tier 2" in x for x in f))
check("a tier-2 reply needs --team-thread", any("action 3: its command is not" in x for x in f))
f = B.tier_check(page, [dict(acts[0], evidence=""), dict(acts[1], evidence="build 78 under test")] + acts[2:], {}, verdict)
check("tier 1 and 2 carry evidence; a train action names the verdict build and its report",
      any("action 1: a tier-1 action carries its evidence" in x for x in f) and any("action 2: a train action's evidence" in x for x in f))
check("a demoted rule's actions are tier 3", any("rule fact-comment is demoted" in x for x in B.tier_check(page, acts, {"fact-comment": "3 in 7 days"}, verdict)))
check("an applied tier-3 action said in words needs no box", B.tier_check("", [dict(acts[2], applied="2026-10-29T09:00:00+08:00")], {}) == [])
check("a done line with no action is caught", any("action 9: on the page" in x for x in B.tier_check("- done 9 — x\n", [], {})))

me, now = "Evan Li", datetime.datetime(2026, 10, 30, 20, 0).astimezone()
at = "2026-10-29T10:00:00+0800"
applied = [{"n": 1, "tier": 1, "rule": "label", "command": "ela jira label MH-7 --add proto:srt", "text": "label", "applied": at},
           {"n": 2, "tier": 1, "rule": "assign-by-rule", "command": "ela jira assign MH-8 --assignee x", "text": "assign", "applied": at},
           {"n": 3, "tier": 1, "rule": "fact-comment", "command": "ela jira comment MH-9 --from-file f", "text": "comment", "applied": at},
           {"n": 4, "tier": 3, "rule": None, "command": "ela jira label MH-10 --add a", "text": "t3", "applied": at}]
iss = {"MH-7": {"events": [{"at": "2026-10-29T12:00:00+0800", "by": "A Dev", "field": "labels", "from": "proto:srt ui", "to": "ui"}]},
       "MH-8": {"events": [{"at": "2026-10-29T11:00:00+0800", "by": me, "field": "assignee", "from": "x", "to": "y"}]},
       "MH-9": {"comments": [{"at": "2026-10-29T15:00:00+0800", "by": "A Dev", "text": "that is not what QA saw"}]},
       "MH-10": {"events": [{"at": "2026-10-29T12:00:00+0800", "by": "A Dev", "field": "labels", "from": "a", "to": ""}]}}
r = RV.reverts(applied, iss, me, now)
check("a label taken off by a colleague is a correction; the owner's own change and a tier-3 action are not",
      [(x["key"], x["rule"]) for x in r] == [("MH-7", "label")])
gaps = []
rep = RV.replies(applied, iss, me, [], gaps)
check("a colleague's comment after a tier-1 comment goes to the reader to judge", [(x["key"], x["action"]) for x in rep] == [("MH-9", 3)])

with tempfile.TemporaryDirectory() as t:
    os.makedirs(os.path.join(t, "review"))
    for i, d in enumerate(("2026-10-27", "2026-10-28")):
        json.dump({"rows": [{"kind": "correction", "rule": "label", "key": f"MH-{i}"}]}, open(os.path.join(t, "review", f"{d}-replay.json"), "w"))
    json.dump({"rows": [{"kind": "correction", "rule": "label", "key": "MH-old"}]}, open(os.path.join(t, "review", "2026-10-01-replay.json"), "w"))
    check("two corrections in the window do not demote", not RV.update_tiers(t, "2026-10-29")["rules"]["label"]["demoted"])
    json.dump({"rows": [{"kind": "reply", "action": 3, "rule": "fact-comment", "key": "MH-9", "now": "A Dev: no"}]},
              open(os.path.join(t, "review", "2026-10-29-replay.json"), "w"))
    judge = RV.to_judge(t, "2026-10-29")
    reader = "| 1. x | tickable | y |\n- **Read first:** a\n- **Skipped:** b\n- **Missing:** c\n"
    check("a reply the reader has not judged fails the check", any("action 3: a reply after it is not judged" in x for x in RV.reader_check("", reader, judge)))
    reader += "\n## Corrections\n\n| action 3 | contradicts | QA saw the old build |\n"
    check("judged, it passes", not any("action 3" in x for x in RV.reader_check("", reader, judge)))
    fnd = RV.reader_findings("", reader, judge)
    check("a contradicting reply is a correction on its rule", any(x["kind"] == "correction" and x["rule"] == "fact-comment" for x in fnd))
    json.dump([{"kind": "correction", "how": "reply", "rule": "label", "key": "MH-3"}], open(os.path.join(t, "review", "2026-10-29-reader.json"), "w"))
    out = RV.update_tiers(t, "2026-10-29")
    check("three on one rule in seven days demote it, and the morning reads it", out["rules"]["label"]["demoted"]
          and B.demoted_rules(t) == {"label": out["rules"]["label"]["why"]})
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import vault as V  # noqa: E402
with tempfile.TemporaryDirectory() as t:
    p = os.path.join(t, "a.json")
    json.dump([{"n": 1, "applied": "2026-10-29T08:31:00+0800"}, {"n": 2, "vetoed": "2026-10-29T09:12:00+0800"},
               {"n": 3, "applied": "2026-10-29T10:00:05+0800"}, {"n": 4, "failed": {"error": "jira 403"}}], open(p, "w"))
    out = V.action_states("- done 1 — a\n- [x] don't 2 — at 10:00 unless you tick: b\n- [ ] don't 3 — at 10:00 unless you tick: c\n- done 4 — d", p)
    check("the vault shows what the runner did: done, held by his tick, sent, not done",
          out == "- done 1 — a · done 08:31\n- [x] don't 2 — at 10:00 unless you tick: b · held, you ticked 09:12\n"
                 "- [ ] don't 3 — at 10:00 unless you tick: c · sent 10:00\n- done 4 — d · not done: jira 403")
mt = [{"n": 5, "tier": 2, "rule": "meeting", "send_at": "14:00", "evidence": "the scrum's list",
       "command": f"ela slack post {THREAD} --text-file f --team-thread"}]
p14 = "- [ ] don't 5 — at 14:00 unless you tick: the scrum's list\n"
check("a tier-2 post at its send time passes", B.tier_check(p14, mt) == [])
check("a page time that disagrees with the action's send_at fails",
      any("goes at 10:00" in f for f in B.tier_check(p14.replace("14:00", "10:00"), mt)))
check("the 19:00 test-list post is retired", any("rule test-list is retired" in f for f in B.tier_check(
      "- [ ] don't 5 — at 19:00 unless you tick: x\n", [dict(mt[0], rule="test-list", send_at="19:00")])))
dp = [{"n": 6, "tier": 2, "rule": "dev-today", "evidence": "the 2.1 dev list", "command": "ela slack post #prj_dev_mediahub --file f --team-day-post"}]
check("dev-today is parked: a draft fails, its absence passes", any("parked" in f for f in B.tier_check("- [ ] don't 6 — at 10:00 unless you tick: Dev today\n", dp))
      and B.tier_check("## Dev today\n\nNo post today.\n", []) == [])
qa = [{"n": 9, "tier": 3, "send_box": True, "rule": "qa-today", "command": "ela slack post #mediahub-qa-release --file f --team-day-post"}]
psb = "## QA today\n\n- [ ] send 9 — QA today on qa-cn3 (your ela: lines applied first) · unticked: stays as apply 9\n"
check("the runner's send-box draft of QA today passes, ticked or not", B.tier_check(psb, qa) == [] and B.tier_check(psb.replace("[ ]", "[x]"), qa) == [])
check("QA today drafted at tier 2 fails", any("send-box action is tier 3" in f for f in B.tier_check(
      "- [ ] don't 9 — at 09:30 unless you tick: QA today\n", [dict(qa[0], tier=2, send_box=False)])))
check("a send-box action without its send box fails", any("is written" in f for f in B.tier_check("- [ ] apply 9 — QA today\n", qa)))
check("a send box with no action fails", any("not in the actions file" in f for f in B.tier_check(psb, [])))
check("thread-reply may not make a top-level post",
      any("not what rule" in f for f in B.tier_check("- [ ] don't 6 — at 10:00 unless you tick: x\n", [dict(dp[0], rule="thread-reply")])))
pr = [{"n": 7, "tier": 1, "rule": "priority-by-rule", "evidence": "customer bracket", "command": "ela jira priority MH-1 --to High --why x"}]
check("priority-by-rule stays tier 3 until promoted", any("until the owner promotes it" in f for f in B.tier_check("- done 7 — x\n", pr)))
check("as tier 3 it passes", B.tier_check("- [ ] apply 7 — raise MH-1 to High\n", [dict(pr[0], tier=3)]) == [])
sys.exit(1 if failures else 0)
