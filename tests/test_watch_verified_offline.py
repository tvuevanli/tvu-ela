#!/usr/bin/env python3
"""A verified close offline (vault plan ela/2026-11-26-plan-sweep-judges-every-field, first slice 5; the owner's word of
2026-11-26, a verified pass closes the ticket): the gate is a stored run of the ticket, its env.json proven on the named
lane and its cases passing by /ela:verify's own verdict; it goes out as `ela jira close --terminal` through `ela dry`'s
class verified-close, its proof the signed comment. Every write goes to a stub runner; nothing reaches Jira or Slack."""
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


NOW = datetime.datetime(2026, 11, 26, 10, 30, tzinfo=W.TZ)
DEV = {"accountId": "acc-dev", "displayName": "Dev One", "accountType": "atlassian"}
ran = []
runner = lambda cmd, apply: (ran.append((cmd, apply)) or (0, "ok"))   # noqa: E731
PROOF = "Verified on prod-3 (build 2.2.170) as the test account: the SRT listener reports Sending to both clients. Closing."


def run_dir(runtime, name, lane="prod-3", verdict="proven", results=("pass",)):
    d = os.path.join(runtime, "browser", "runs", name)
    os.makedirs(d, exist_ok=True)
    json.dump({"lane": lane, "verdict": verdict}, open(os.path.join(d, "env.json"), "w"))
    json.dump({"result": [{"id": str(i), "result": r} for i, r in enumerate(results)]}, open(os.path.join(d, "cases.json"), "w"))
    return d


with tempfile.TemporaryDirectory() as t:
    runtime = os.path.join(t, "runtime")
    facts, reports = os.path.join(runtime, "facts"), os.path.join(t, "reports")
    os.makedirs(os.path.join(facts, "jira", "issues")); os.makedirs(os.path.join(reports, "ela"))
    json.dump({"issues": [{"fields": {"assignee": {"accountId": "acc-owner", "displayName": "Dana Owner"}}}]},
              open(os.path.join(facts, "jira", "owner.json"), "w"))
    for k in ("MH-1", "MH-2", "MH-3", "MH-4", "MH-5"):
        json.dump({"key": k, "fields": {"summary": f"Ticket {k}", "status": {"name": "Review"}, "assignee": DEV,
                                        "priority": {"name": "Medium"}, "resolution": None, "description": None}, "comments": []},
                  open(os.path.join(facts, "jira", "issues", f"{k}.json"), "w"))
    good = run_dir(runtime, "MH-1-2026-11-26")
    run_dir(runtime, "MH-2-2026-11-26", verdict="unproven")
    run_dir(runtime, "MH-3-2026-11-26", results=("pass", "fail"))
    run_dir(runtime, "MH-4-2026-11-26", lane="prod-8")
    other = run_dir(runtime, "MH-9-2026-11-26")
    scanned = {"triggered": [{"key": k, "triggers": [{"kind": "stalled", "says": "x"}]} for k in ("MH-1", "MH-2", "MH-3", "MH-4", "MH-5")],
               "replies": []}

    def vc(key, run, lane="prod-3", conf="high", comment=PROOF, extra=()):
        return {"key": key, "verdict": "act", "confidence": conf, "why": "verified", "comment": comment,
                "writes": [{"verb": "verified-close", "run": run, "lane": lane}] + list(extra)}
    r = W.decide({"decisions": [vc("MH-1", good), vc("MH-2", os.path.join(runtime, "browser", "runs", "MH-2-2026-11-26")),
                                vc("MH-3", os.path.join(runtime, "browser", "runs", "MH-3-2026-11-26")),
                                vc("MH-4", os.path.join(runtime, "browser", "runs", "MH-4-2026-11-26")),
                                vc("MH-5", other)]}, scanned, facts, reports, NOW, apply=False, runner=runner)
    why = {x["key"]: x["why"] for x in r["refused"]}
    check("a proven, passing run on the named lane closes the ticket", [x["key"] for x in r["acts"]] == ["MH-1"])
    check("an unproven lane is refused", "not proven" in why.get("MH-2", ""))
    check("a failing case is refused: a fail reopens instead", "fail" in why.get("MH-3", ""))
    check("a run proven on another lane is refused", "prod-8" in why.get("MH-4", ""))
    check("another ticket's run is refused", "names its run" in why.get("MH-5", ""))
    cmd = r["acts"][0]["writes"][0]
    check("the close is `ela jira close --terminal`, its proof the signed note",
          cmd.startswith("ela jira close MH-1 --terminal --to Done --from-file ") and cmd.endswith("--no-mention")
          and W.J.is_signed(r["acts"][0]["comment"]) and "Dana Owner" in r["acts"][0]["comment"])
    check("it runs through ela dry's class verified-close, tier 1 by the owner's word",
          r["acts"][0]["batch"].endswith("-verified-close-MH-1") and D.load_state(reports)["verified-close"]["tier"] == 1
          and "verified-close" in D.TIER1_BY_DECISION)
    r = W.decide({"decisions": [dict(vc("MH-1", good, conf="medium"), doubt="one case was flaky"), vc("MH-1", good, comment="Closing.")]}, scanned, facts, reports, NOW,
                 apply=False, runner=runner)
    check("below high confidence, or a comment without the lane, it is refused",
          len(r["refused"]) == 2 and "confidence high" in r["refused"][0]["why"] and "proof" in r["refused"][1]["why"])
    r = W.decide({"decisions": [vc("MH-1", good, extra=[{"verb": "priority", "to": "High"}])]}, scanned, facts, reports, NOW,
                 apply=False, runner=runner)
    check("a verified close is its set's only write", "only write" in r["refused"][0]["why"])
    check("a close is still never a board-watch write", W.check_act("MH-1", {"confidence": "high", "comment": "x",
          "writes": [{"verb": "transition", "to": "Done"}]}, {}, {}, "2026-11-26") is not None)
    W.decide({"decisions": [vc("MH-1", good)]}, scanned, facts, reports, NOW, apply=True, runner=runner)
    check("applied, one close was written through the runner", [c for c, a in ran if a] and all("close MH-1" in c for c, a in ran if a))

print(f"\n{len(fails)} failed" if fails else "\nall ok")
sys.exit(1 if fails else 0)
