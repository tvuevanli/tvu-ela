#!/usr/bin/env python3
"""The links index offline: edges from fixtures (a ticket's links and named keys, the thread behind its Slack link and
the keys that thread names, a deploy post, a build record, the train's lanes, a vault note, a question, ela's writes
with and without their session), an update that re-reads only what changed, a write attributed only when one action
matches; then the budget on today's real facts when they are on disk (read-only, the store in a temp directory)."""
import json, os, shutil, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="ela-links-")
REAL_RUNTIME = None
try:
    REAL_RUNTIME = json.load(open(os.path.expanduser("~/.claude/ela/site.json"))).get("runtime")
except (OSError, ValueError):
    pass
os.environ["ELA_FACTS_RUNTIME"] = os.path.join(TMP, "rt")
os.environ["ELA_LINKS_REPORTS"] = os.path.join(TMP, "reports")
os.environ["ELA_LINKS_VAULT"] = os.path.join(TMP, "vault")
os.environ["ELA_LINKS_STORE"] = os.path.join(TMP, "links.db")
sys.path.insert(0, os.path.join(ROOT, "skills", "links"))
sys.path.insert(0, os.path.join(ROOT, "skills", "jira"))
import links as L  # noqa: E402
import jira as J  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

def put(path, obj):
    path = os.path.join(TMP, path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False))

def adf(text):
    return {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}

BASE = "https://example.atlassian.net"
PL = "https://example.slack.com/archives/C06553EE44X/p1793673172789319"
put("rt/facts/jira/projects.json", {"projects": [{"key": "MH"}, {"key": "UR"}, {"key": "WR3"}, {"key": "SCTE"}, {"key": "ST"}]})
put("rt/facts/jira/issues/MH-3870.json", {"key": "MH-3870", "url": f"{BASE}/browse/MH-3870", "fields": {
    "summary": "Generic MXL processes not released", "status": {"name": "Backlog"}, "updated": "2026-11-02T19:40:32.024-0800",
    "created": "2026-11-02T18:44:06.456-0800", "reporter": {"displayName": "QA lead"},
    "issuelinks": [{"type": {"outward": "relates to", "inward": "relates to"},
                    "outwardIssue": {"key": "UR-542", "fields": {"summary": "MeshAdapter pair released late", "status": {"name": "Backlog"}}}}],
    "description": adf(f"Seen in qa2. Source: {PL}")},
    "comments": [{"id": "287579", "created": "2026-11-02T19:00:00.000-0800", "author": {"displayName": "Automation"},
                  "body": adf("(Copied from UR-542) see also UTF-8 and H-264; SCTE-35 on SRT, ST-2110 later, SCTE-7 is a ticket")}]})
put("rt/facts/jira/issues/MH-3735.json", {"key": "MH-3735", "url": f"{BASE}/browse/MH-3735", "fields": {
    "summary": "Close HTTP ports", "status": {"name": "Backlog"}, "updated": "2026-11-11T19:40:32.024-0800",
    "issuelinks": [{"type": {"outward": "contains", "inward": "is contained in"}, "outwardIssue": {"key": "MH-3990", "fields": {"summary": "Blackframe over MQTT"}}}],
    "description": adf("Parent for the HTTP to MQTT move")},
    "comments": [{"id": "291655", "created": "2026-11-12T00:10:00.000-0800", "author": {"displayName": "Owner"},
                  "body": adf("Modules: MH-3990, MH-3983, WR3-89 and MH-0123")}]})
put("rt/facts/jira/issues/MH-3990.json", {"key": "MH-3990", "url": f"{BASE}/browse/MH-3990", "fields": {
    "summary": "Blackframe over MQTT", "status": {"name": "Backlog"}, "updated": "2026-11-11T19:40:32.024-0800",
    "issuelinks": [{"type": {"outward": "contains", "inward": "is contained in"}, "inwardIssue": {"key": "MH-3735", "fields": {"summary": "Close HTTP ports"}}}]}})
put("rt/facts/jira/changes.json", [])
put("rt/facts/slack/channels.json", {"channels": [{"id": "C06553EE44X", "name": "prj_dev_mediahub"}]})
put("rt/facts/slack/C06553EE44X.json", {"messages": {
        "1793673172.789319": {"ts": "1793673172.789319", "text": "generic mxl source process 释放问题\nmore", "reply_count": 4},
        "1793700000.000001": {"ts": "1793700000.000001", "text": "lunch?"},
        "1793900000.000002": {"ts": "1793900000.000002", "text": "alert digest: MH-3870 MH-11 MH-12 MH-13 MH-14 MH-15 UR-545"}},
    "replies": {"1793673172.789319": {"messages": [
        {"ts": "1793673172.789319", "text": "generic mxl source process 释放问题"},
        {"ts": "1793673851.771959", "text": "已创建 Jira ticket：<https://example.atlassian.net/browse/MH-3870|MH-3870>"},
        {"ts": "1793700003.165599", "text": "相关JIRA:<https://example.atlassian.net/browse/UR-545|UR-545>"},
        {"ts": "1793710000.000000", "text": '*结论*：分析很长\n……这里没有 pin 到已部署版本的源码'},
        {"ts": "1793779572.654389", "text": "部署了"}]}}})
put("rt/facts/mail/messages/m1.json", {"id": "m1", "thread": "t1", "subject": "Daily Test Report build 79",
                                       "body": "MH-3870 still open", "internal_date": "1793704027"})
put("reports/releases/2.1/2026-11-11-build-91-to-qa-aws3.json", {"line": "2.1", "lane": "qa-cn3", "lane_name": "QA-AWS3",
    "build": "91", "date": "2026-11-11", "services": [{"service": "UR Caller", "from": "2.1.90", "to": "2.1.91", "keys": ["MH-3990"]}]})
put("reports/releases/2.1/2026-11-11-build-91-to-qa-aws3.reconcile.json", {"build": "91", "services": [{"keys": ["MH-1"]}]})
put("reports/train/2.1.json", {"rows": [{"key": "MH-3768", "also": ["SCTE-35"], "cells": {
    "prod-3": {"arrived": "2.1.87", "since": "2026-11-09", "verdict": "untested"}}}]})
put("vault/projects/mh-3735/mh-3735.md", "# MH-3735 HTTP to MQTT\n\nwatches MH-3735 and MH-3990\n")
put("vault/reference/days/2026-11-12-brief.md", "# a day page\nMH-3735\n")
put("reports/ela/questions.json", {"questions": {"q-1": {"text": "Who takes MH-3990?", "keys": ["MH-3990"], "lead": [],
                                                         "status": "open", "first": {"date": "2026-11-10", "where": "meetings/sync.md"}}}})
writes = [
    {"at": "2026-11-12T13:41:39+08:00", "system": "jira", "verb": "fixed-in", "key": "MH-3768", "ok": True, "unattended": False},
    {"at": "2026-11-12T13:40:01+08:00", "system": "jira", "verb": "comment", "key": "MH-2406", "ok": True, "unattended": False},
    {"at": "2026-11-12T15:00:00+08:00", "system": "jira", "verb": "link", "key": "MH-3735", "keys": ["MH-3983"], "ok": True,
     "session": "projects-05", "job": None, "action": "dry:b1#1", "word": "answer dry:b1 A"},
    {"at": "2026-11-12T15:01:00+08:00", "system": "slack", "verb": "post", "key": None, "permalink": PL + "?thread_ts=1793673172.789319&cid=C06553EE44X",
     "ok": True, "session": "desk", "word": "the owner in the session"},
    {"at": "2026-11-12T13:57:45+08:00", "system": "jira", "verb": "link", "key": None, "ok": True},
]
put("reports/ela/writes.jsonl", "\n".join(json.dumps(w) for w in writes) + "\n")
put("reports/runner/2026-11-12-actions.json", [
    {"n": 2, "command": "ela jira comment MH-2406 --text \"x\"", "applied": "2026-11-12T13:39:59+0800", "by": "tick"},
    {"n": 3, "command": "ela jira comment MH-9 --text \"y\""}])

# ── the build ────────────────────────────────────────────────────────────────────────────────────────
res = L.update(full=True)
check("a rebuild reads every origin", {"jira", "mail", "builds", "lanes", "questions", "writes", "vault", "slack/C06553EE44X"} <= set(res["read"]))
db = L.connect(os.environ["ELA_LINKS_STORE"])

v = L.lookup_key(db, "MH-3870")
check("MH-3870: UR-542 linked, read as relates to", [(l["other"], l["reads"]) for l in v["linked"]] == [("UR-542", "relates to")])
th = {t["id"]: t for t in v["threads"]}
tid = "slack:C06553EE44X/1793673172.789319"
check("MH-3870: the thread behind its Slack link, linked from its description", tid in th and th[tid]["via"].startswith("linked from the ticket's description"))
check("the thread names UR-545 among its keys", "UR-545" in th[tid]["names"])
check("the thread carries a first line, a channel and a reply count", th[tid]["first"] == "generic mxl source process 释放问题"
      and th[tid]["channel"] == "prj_dev_mediahub" and th[tid]["replies"] == 4)
check("the deploy post is found; a word deep in an analysis is not one", [d["label"] for d in th[tid]["deploys"]] == ["部署了"])
named = {n["key"]: n for n in v["named_with"]}
check("UR-545 is named with it, with where", "UR-545" in named and named["UR-545"]["where"][0]["where"].startswith("thread #prj_dev_mediahub"))
check("UR-542 is named with it and marked linked, listed first", v["named_with"][0]["key"] == "UR-542" and v["named_with"][0]["linked"])
check("a key outside the Jira projects is not a key (UTF-8, H-264)", not any(k in named for k in ("UTF-8", "H-264")))
check("a standard's name is not a key though its prefix is a project (SCTE-35, ST-2110); the project's own ticket is",
      not any(k in named for k in ("SCTE-35", "ST-2110")) and "SCTE-7" in named)
check("a train row's also naming a standard is not indexed as a ticket",
      not db.execute("SELECT 1 FROM edges WHERE src = 'SCTE-35' OR dst = 'SCTE-35'").fetchone())
check("Keys.find: the deny list is names, not prefixes", L.Keys(os.path.join(TMP, "rt", "facts")).find("SCTE-35 SCTE-7 AC-3 SMPTE-2110") == ["SCTE-7"])
check("a digest (more than five keys) is a weak edge: its tickets come after the strong ones, flagged weak",
      [n["key"] for n in v["named_with"] if n["weak"]] == ["MH-11", "MH-12", "MH-13", "MH-14", "MH-15"]
      and not any(n["weak"] for n in v["named_with"][:2]) and v["named_with"][-1]["weak"])
check("a ticket named both in a digest and in a small thread stays strong, its strong source first",
      not named["UR-545"]["weak"] and not named["UR-545"]["where"][0]["weak"] and any(w["weak"] for w in named["UR-545"]["where"]))
txt = L.render_key(v, {})
sec = txt.split("\nnamed with it\n")[1].split("\n\n")[0]
check("rendered: the weak ones fold into one line with the count and the source, no line a ticket",
      "MH-11 ·" not in sec and sec.count("also listed together in 1 digest (5 tickets): thread #prj_dev_mediahub") == 1
      and "p1793900000000002" in sec and sec.index("UR-545") < sec.index("also listed"))
check("--json keeps every edge, each with its weak flag", all("weak" in w for n in v["named_with"] for w in n["where"])
      and len(v["named_with"]) == len(named))
check("the mail that names it", [e["mail"]["label"] for e in v["mails"]] == ["Daily Test Report build 79"])
check("a lone message that names no key is not indexed", not db.execute("SELECT 1 FROM nodes WHERE id = 'slack:C06553EE44X/1793700000.000001'").fetchone())

v = L.lookup_key(db, "MH-3735")
check("MH-3735: the module tickets its comment names", {"MH-3990", "MH-3983", "WR3-89"} <= {n["key"] for n in v["named_with"]})
check("MH-3735: a key with a leading zero is not a key", "MH-123" not in {n["key"] for n in v["named_with"]})
check("MH-3735: a link seen from both ends is one line, in its own words",
      [(l["other"], l["reads"]) for l in v["linked"]] == [("MH-3990", "contains")])
check("MH-3735: the project page holds it; a day page does not count", [e["src"] for e in v["notes"]] == ["vault:projects/mh-3735/mh-3735.md"])
w = [e["write"] for e in v["writes"]]
check("a write with its session recorded: who and on whose word", len(w) == 1 and L.who_words(w[0]) ==
      "by session projects-05, action dry:b1#1 on answer dry:b1 A")
check("a link write lists both keys", L.lookup_key(db, "MH-3983")["writes"][0]["write"]["label"] == "jira link")

v = L.lookup_key(db, "MH-3990")
check("MH-3990: seen from the child, the parent reads is contained in", ("MH-3735", "is contained in") in [(l["other"], l["reads"]) for l in v["linked"]])
check("MH-3990: the build that carries it, service and version step", [e["note"] for e in v["builds"]] == ["UR Caller 2.1.90→2.1.91"])
check("the reconcile record is not a build record", len(v["builds"]) == 1)
check("MH-3990: the open question naming it", [e["note"]["label"] for e in v["notes"] if e["kind"] == "question"] == ["Who takes MH-3990?"])

v = L.lookup_key(db, "MH-3768")
check("MH-3768: the lane its fix reached, from the train's evidence", [(e["lane"], e["at"]) for e in v["lanes"]] == [("prod-3", "2026-11-09")])
w = v["writes"][0]["write"]
check("MH-3768: a write before the change, no action matching: unknown, said so", w["how"] == "unknown" and "unknown" in L.who_words(w))
w = L.lookup_key(db, "MH-2406")["writes"][0]["write"]
check("MH-2406: a write one applied action matches is attributed to it", w["action"] == "2026-11-12-actions.json#2" and w["word"] == "tick (runner)")

t = L.lookup_thread(db, "C06553EE44X", "1793779572.654389", "1793673172.789319")
check("a reply's permalink finds its thread: the keys, the ticket that links it, ela's post",
      [x["key"] for x in t["keys"]] == ["MH-3870", "UR-545"] and [e["src"] for e in t["tickets"]] == ["MH-3870"] and len(t["writes"]) == 1)
b = L.lookup_build(db, "qa-cn3/91")
check("a build by lane/number: the tickets it carries", b and [e["dst"] for e in b["keys"]] == ["MH-3990"])
check("the rendered key page says the index's age and makes no causal claim",
      "index built" in L.render_key(L.lookup_key(db, "MH-3870"), L.index_age(db)) and "is not \"fixed by\"" in L.render_key(L.lookup_key(db, "MH-3870"), L.index_age(db)))
db.close()

# ── incremental ──────────────────────────────────────────────────────────────────────────────────────
res = L.update()
check("an update with nothing changed re-reads nothing", res["read"] == [])
time.sleep(1.1)
put("rt/facts/mail/messages/m2.json", {"id": "m2", "subject": "Release note", "body": "MH-3735 shipped", "internal_date": "1793804027000"})
res = L.update()
check("a new mail re-reads the mail origin alone", res["read"] == ["mail"])
db = L.connect(os.environ["ELA_LINKS_STORE"])
check("the new mail is linked, its millisecond date read", [(e["mail"]["label"], e["at"][:10]) for e in L.lookup_key(db, "MH-3735")["mails"]] == [("Release note", "2026-11-04")])
db.close()
os.remove(os.path.join(TMP, "rt/facts/slack/C06553EE44X.json"))
res = L.update()
db = L.connect(os.environ["ELA_LINKS_STORE"])
check("a channel file that is gone takes its edges with it", "slack/C06553EE44X" in res["removed"] and not L.lookup_key(db, "MH-3870")["threads"][0]["indexed"])
db.close()

# ── the write log's new fields ───────────────────────────────────────────────────────────────────────
env = {k: os.environ.pop(k) for k in ("ELA_SESSION_NAME", "CLAUDE_CODE_SESSION_ID", "ELA_RUNNER_JOB", "ELA_ACTION", "ELA_WORD", "ELA_NO_APPLY") if k in os.environ}
os.environ.update(ELA_SESSION_NAME="links-index", ELA_ACTION="2026-11-12-actions.json#4", ELA_WORD="apply 4 (Slack)")
check("a write records the session, the action and the word", J.write_who() == {"session": "links-index", "job": None,
      "action": "2026-11-12-actions.json#4", "word": "apply 4 (Slack)"})
for k in ("ELA_SESSION_NAME", "ELA_ACTION", "ELA_WORD"):
    os.environ.pop(k)
os.environ["CLAUDE_CODE_SESSION_ID"] = "4c4d6919-1aea-43d6-88b8-0e990cf42c7a"
check("an unnamed session is its Claude id; its word is the owner's in it", J.write_who() == {"session": "claude:4c4d6919", "job": None,
      "action": None, "word": "the owner in the session"})
os.environ.pop("CLAUDE_CODE_SESSION_ID")
check("nothing set: every field null, never guessed", J.write_who() == {"session": None, "job": None, "action": None, "word": None})
os.environ.update(env)

# ── the budget, on today's real facts (read-only; the store in the temp directory) ────────────────────
if REAL_RUNTIME and os.path.isdir(os.path.join(os.path.expanduser(REAL_RUNTIME), "facts", "jira")):
    for k in ("ELA_LINKS_REPORTS", "ELA_LINKS_VAULT"):
        os.environ.pop(k)
    os.environ["ELA_FACTS_RUNTIME"] = os.path.expanduser(REAL_RUNTIME)
    os.environ["ELA_LINKS_STORE"] = os.path.join(TMP, "real.db")
    t0 = time.time()
    res = L.update(full=True)
    secs = time.time() - t0
    check(f"budget: the full rebuild on today's facts under two minutes ({secs:.1f}s)", secs < 120)
    check(f"budget: the store under 20 MB ({res['bytes'] / 1e6:.1f} MB)", res["bytes"] < 20e6)
else:
    print("skip the budget: no fact store on this machine")

shutil.rmtree(TMP, ignore_errors=True)
if failures:
    print(f"links: {len(failures)} failed"); sys.exit(1)
print("links: all offline checks passed")
