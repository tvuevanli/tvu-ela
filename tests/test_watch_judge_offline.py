#!/usr/bin/env python3
"""A ticket that reaches the owner arrives judged, offline (plan ela/2026-11-26-plan-tickets-reach-you-judged): the judge
queue in the scan, the judgment's own clock, `decide --judge`, a closed topic kept, a hollow option refused, and the
replay of MH-4065 as of 2026-11-26: today.md's Team yesterday line carries the verdict and the link to its home, not the
listing. The fact store, the reports and the vault are files in a temp dir; nothing reaches Jira or Slack."""
import datetime, json, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "watch"))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import watch as W  # noqa: E402
import vault as V  # noqa: E402

fails = []


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


TZ = W.TZ
NOW = datetime.datetime(2026, 11, 26, 13, 30, tzinfo=TZ)
OWNER = {"id": "acc-owner", "name": "Dana Owner"}
ME = {"accountId": "acc-owner", "displayName": "Dana Owner", "accountType": "atlassian"}
DEV = {"accountId": "acc-dev", "displayName": "Dev One", "accountType": "atlassian"}
QA = {"accountId": "acc-qa", "displayName": "Qa One", "accountType": "atlassian"}


def at(now, **kw):
    return (now - datetime.timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%S.000+0800")


def issue(facts, key, summary, status="Review", who=ME, prio="High", updated=None, cs=()):
    json.dump({"key": key, "fields": {"summary": summary, "status": {"name": status, "statusCategory": {"key": "indeterminate"}},
                                      "assignee": who, "priority": {"name": prio}, "duedate": None, "labels": ["release:mh-2.1"],
                                      "resolution": None, "updated": updated or at(NOW, hours=20), "description": "the admin page"},
               "comments": list(cs), "updated": updated or at(NOW, hours=20)},
              open(os.path.join(facts, "jira", "issues", f"{key}.json"), "w"))


def scan(facts, reports, now):
    return W.scan(facts, reports, now, holds={"holds": {}, "read": {}}, lines=["2.1"], owner=OWNER, write=True, base="")


with tempfile.TemporaryDirectory() as t:
    facts, reports, vault = (os.path.join(t, x) for x in ("facts", "reports", "vault"))
    os.makedirs(os.path.join(facts, "jira", "issues")); os.makedirs(os.path.join(reports, "ela"))
    os.makedirs(os.path.join(vault, "projects", "eip-pool"))
    qa = {"id": "1", "author": QA, "body": "QA review on QA-AWS3: 14 of 18 cases pass; TC18 fails.", "created": at(NOW, hours=20)}
    issue(facts, "MH-4065", "MediaHub Admin: manage the self-managed EIP pool", cs=[qa])
    issue(facts, "MH-2", "A developer's review", who=DEV)
    issue(facts, "MH-3", "Yours, in progress", status="In Progress")
    issue(facts, "MH-4", "Yours, highest", prio="Highest")
    # as on 2026-11-26: the quick pass decided MH-4065 at 10:33, after its last move; the judging has its own clock
    st = W.load_state(reports)
    st["tickets"]["MH-4065"] = {"first": "2026-11-24", "decided": at(NOW, hours=3), "verdict": "ask", "judged": ["r1"]}
    W.write_json(W.state_path(reports), st)

    got = scan(facts, reports, NOW)
    q = [r["key"] for r in got["judge"]]
    check("the judge queue: his tickets in Review, never judged, Highest first; not a developer's, not his In Progress",
          q == ["MH-4", "MH-4065"] and got["judge"][1]["why"] == "in Review with you, never judged")
    check("the quick pass's decision does not count as a judgment", "MH-4065" in q)

    # the topic the quick pass asked at 10:33, answered A at 13:39 with no writes behind its words
    topics = W.load_topics(reports)
    W.put_topic(topics, "MH-4065", {"question": "Hand it back to QA, or keep it?", "kind": "ruling",
                                    "options": [{"letter": "A", "text": "hand it to QA to retest TC18"}, {"letter": "B", "text": "keep it"}]},
                "2026-11-26", "EIP pool admin")
    W.write_json(W.topics_path(reports), topics)
    W.answer(reports, "watch:MH-4065", "A", NOW)
    topics = W.load_topics(reports)
    W.put_topic(topics, "MH-4065", {"question": "A new question", "kind": "ruling", "options": [{"letter": "A", "text": "x"}]},
                "2026-11-27", "EIP pool admin")
    tp = topics["topics"]["watch:MH-4065"]
    check("a new ask on a closed topic keeps the closed one, his letter with it, in history",
          tp["closed"] is None and tp["history"][0]["closed"]["letter"] == "A"
          and [x.get("closed", {}) and x["closed"].get("letter") for x in W.topics_on(reports, "MH-4065")] == ["A"])
    W.write_json(W.topics_path(reports), {"topics": {}, "roots": {}})

    # the judging session's decision file, checked against the judge queue
    hollow = {"decisions": [{"key": "MH-4065", "verdict": "ask", "kind": "ruling", "confidence": "medium", "why": "QA has a fail",
                             "question": "Back to QA?", "options": [{"letter": "A", "text": "assign to Qa One to retest TC18"},
                                                                    {"letter": "B", "text": "you keep it"}]}]}
    r = W.decide(hollow, got, facts, reports, NOW, apply=False, judge="MH-4065")
    check("an option that names a write it does not carry is refused", r["refused"] and "carries no writes" in r["refused"][0]["why"])
    r = W.decide({"decisions": [{"key": "MH-2", "verdict": "none", "why": "x", "confidence": "high"}]}, got, facts, reports, NOW,
                 judge="MH-2")
    check("decide --judge refuses a ticket that is not in the judge queue", r["refused"][0]["why"] == "not due judging in today's scan")
    topics = W.load_topics(reports)
    W.put_topic(topics, "MH-4065", {"question": "Open quick ask", "kind": "ruling", "options": [{"letter": "A", "text": "keep it"}]},
                "2026-11-26", "EIP pool admin")
    W.write_json(W.topics_path(reports), topics)
    none = {"decisions": [{"key": "MH-4065", "verdict": "none", "why": "QA retests TC18; nothing to write", "confidence": "high"}]}
    r = W.decide(none, got, facts, reports, NOW, apply=True, judge="MH-4065")
    tp = W.load_topics(reports)["topics"]["watch:MH-4065"]
    check("a judge's none closes the open topic as superseded, kept, counted apart",
          r["none"] and (tp["closed"] or {}).get("superseded_by", "").endswith("-judge-MH-4065.json")
          and W.outcomes(reports)["superseded"] == 1 and W.outcomes(reports)["open"] == 0 and not W.open_topics(reports))

    try:
        W.judged(reports, facts, "MH-4065", NOW, verdict="x" * 200)
        long_ok = False
    except ValueError:
        long_ok = True
    check("a verdict is one line of at most 160 characters", long_ok)
    verdict = "QA retests TC18 on Admin v1.0.43 (your A, 11-26); the reassignment waits for your confirm"
    j = W.judged(reports, facts, "MH-4065", NOW, verdict=verdict)
    rec = W.load_state(reports)["tickets"]["MH-4065"]
    check("the record: its own clock, the status at the time, the reply ids it judged left alone, a line in judgments.jsonl",
          rec["judgment"]["verdict"] == verdict and rec["judgment"]["status"] == "Review" and rec["judged"] == ["r1"]
          and os.path.isfile(os.path.join(reports, "ela", "watch", "judgments.jsonl")) and j["key"] == "MH-4065")
    W.judged(reports, facts, "MH-4", NOW, failed=True)
    W.judged(reports, facts, "MH-4", NOW, failed=True)
    got = scan(facts, reports, NOW + datetime.timedelta(minutes=5))
    check("judged: not due again; a pick that failed twice goes to the back",
          "MH-4065" not in [r["key"] for r in got["judge"]] and got["judge"][-1]["key"] == "MH-4" and got["judge"][-1]["fails"] == 2)

    later = NOW + datetime.timedelta(days=4)
    own = {"id": "2", "author": ME, "body": "Can you retest TC18?", "created": at(later, hours=2)}
    issue(facts, "MH-4065", "MediaHub Admin: manage the self-managed EIP pool", cs=[qa, own], updated=at(later, hours=2))
    check("his own comment does not bring a judgment back", "MH-4065" not in [r["key"] for r in scan(facts, reports, later)["judge"]])
    qa2 = {"id": "3", "author": QA, "body": "Retest on v1.0.43: TC18 passed.", "created": at(later, hours=1)}
    issue(facts, "MH-4065", "MediaHub Admin: manage the self-managed EIP pool", cs=[qa, own, qa2], updated=at(later, hours=1))
    got = scan(facts, reports, later)
    check("a QA verdict from someone else after three days brings it back",
          next((r["why"] for r in got["judge"] if r["key"] == "MH-4065"), "") == "Qa One gave a QA verdict since its judgment")
    issue(facts, "MH-4065", "MediaHub Admin: manage the self-managed EIP pool", status="Reopened", cs=[qa], updated=at(NOW, minutes=-10))
    W.judged(reports, facts, "MH-4", NOW, verdict="keep it")
    check("a ticket that left Review, and was not handed over, leaves the queue",
          "MH-4065" not in [r["key"] for r in scan(facts, reports, NOW + datetime.timedelta(minutes=20))["judge"]])
    issue(facts, "MH-4065", "MediaHub Admin: manage the self-managed EIP pool", cs=[qa])

    # the replay: the home is the project page that lists the ticket's own key; a linked key does not count
    open(os.path.join(vault, "projects", "eip-pool", "eip-pool.md"), "w").write(
        '---\ntitle: "EIP pool · MediaHub-managed static IPs on Akamai"\ntype: "project"\nkeys: ["MH-4052", "MH-4065"]\n---\n# EIP pool\n')
    check("home: the page listing the ticket's own key; a ticket it only links to is not at home there",
          W.home_link(vault, "MH-4065") == ("projects/eip-pool/eip-pool", "EIP pool") and W.home_link(vault, "UR-564") is None)
    first = "MH-4065 (Review, yours): EIP pool admin page reviewed in QA"
    line, whole = V.judged_for_you(first, reports, vault)
    check("replay: the Team yesterday line carries the verdict and the link, not the listing",
          whole and line == f"MH-4065 (Review, yours): {verdict} → [[projects/eip-pool/eip-pool|EIP pool]]"
          and "reviewed in QA" not in line)
    check("a line that is not about one of his tickets is left as it was",
          V.judged_for_you("MH-2 (Review, Dev One's): x", reports, vault) == ("MH-2 (Review, Dev One's): x", False))
    wl = V.watch_line(reports, NOW.date())
    check("today.md's watch line counts his judged tickets and links the list", "2 of your tickets judged" in wl
          and f"#{W.JUDGED_HEAD}|" in wl)
    pg = W.page(reports, NOW.date(), "https://jira.example", vault)
    check("ela/watch.md lists each judged ticket with its verdict and home",
          f"## {W.JUDGED_HEAD}" in pg and verdict in pg and "[[projects/eip-pool/eip-pool|EIP pool]]" in pg)

print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
