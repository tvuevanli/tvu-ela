#!/usr/bin/env python3
"""QA's verdict from Jira (promote's qajira.py), offline. Comment shapes from the 2026-11-09 daily-wed → prod-3
promotion, where report mails alone missed seven build-85 verdicts and partial passes were shown as passes."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "promote"))
import qajira as Q  # noqa: E402

C, cur = {}, None
for ln in open(os.path.join(ROOT, "tests", "fixtures", "qajira", "comments.txt"), encoding="utf-8"):
    if ln.startswith("=== "):
        cur = ln[4:].strip(); C[cur] = ""
    elif cur:
        C[cur] += ln

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

p = Q.parse(C["partial-with-env"], "MH-3909")
check("⚠ 3 Pass + 1 Fail is partial, with its counts", p["verdict"] == "partial" and p["counts"]["pass"] == 3 and p["counts"]["fail"] == 1)
check("its environment is qa-cn3 at UR Caller 2.1.85", p["env"]["lane"] == "qa-cn3" and p["env"]["versions"]["unified-streaming"].startswith("v2.1.85"))
check("the test day is read", p["tested_on"] == "2026-11-09")
check("已修复 ✅ 2 Pass is a pass", Q.parse(C["pass"])["verdict"] == "pass")
p = Q.parse(C["pass-with-note"])
check("a pass whose 说明 line names what is still open is ⚠ partial", p["verdict"] == "partial" and p["open_points"])
p = Q.parse(C["pending"])
check("a 待确认 count is an open point", p["verdict"] == "partial" and p["open_points"][0].startswith("1 case"))
p = Q.parse(C["accepted"])
check("保持现状 is accepted, not a fix", p["verdict"] == "accepted")
p = Q.parse(C["split"], "MH-3163")
check("split keys in a split line are followed", p["verdict"] == "partial" and p["splits"] == ["MH-3738", "MH-3739", "MH-3740"])
p = Q.parse(C["words"])
check("QA words with a fixed and a broken half are partial", p and p["verdict"] == "partial")
check("a plain remark is no verdict", Q.parse(C["remark"]) is None)
check("❌ 未修复 is a fail", Q.parse(C["fail"])["verdict"] == "fail")

QA = {"erin zhang"}
def comment(who, text, when):
    return {"author": {"displayName": who}, "created": when, "body": text, "id": when}
issue = {"key": "MH-3951", "fields": {"status": {"name": "Review"}, "issuelinks": []},
         "comments": [comment("Automation", C["copy"], "2026-11-06T10:00")]}
check("a non-QA author's copy is not QA's verdict", Q.verdict_of(issue, QA)["verdict"] == "none")
issue = {"key": "MH-3951", "fields": {"status": {"name": "Review"}, "issuelinks": []},
         "comments": [comment("Erin Zhang", C["copy"], "2026-11-06T10:00")]}
check("a QA comment headed by another key is that ticket's report, not this one's", Q.verdict_of(issue, QA)["verdict"] == "none")
issue = {"key": "MH-3911", "fields": {"status": {"name": "Done"}, "issuelinks": [
            {"type": {"name": "Cloners"}, "outwardIssue": {"key": "MH-3999", "fields": {"status": {"name": "Open"}}}}]},
         "comments": [comment("Erin Zhang", C["fail"], "2026-11-01T10:00"),
                      comment("Erin Zhang", C["pass"], "2026-11-08T10:00")]}
v = Q.verdict_of(issue, QA)
check("the latest QA comment decides; the earlier one is history", v["verdict"] == "pass" and len(v["history"]) == 1)
check("a Cloners link is a split to follow", v["links"][0]["split"])

if failures:
    print(f"qajira: {len(failures)} failure(s)"); sys.exit(1)
print("qajira: all offline checks passed")
