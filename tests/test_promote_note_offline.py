#!/usr/bin/env python3
"""promote note, offline: the lint's rules on a note and its Slack text, and the claims split between the two checkers."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "promote"))
import note as N  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

J = "https://tvunetworks.atlassian.net/browse/"
good = f"---\ntitle: x\n---\n# t\n\nUR Caller 2.1.87 carries [MH-3961]({J}MH-3961); DB on `vpc02.mx-service`; mixer 2.0.108.23.\n\n## Checked\n- done\n"
check("a clean note is clean", N.lint_note(good) == [])
bad = f"---\ntitle: x\n---\n# t\n\n```\nMH-1 in a fence\n```\nmx 2.1.87 and FE; MH-3966 is new; host " + ".".join(["10", "0", "0", "1"]) + "\n"
f = N.lint_note(bad)
check("a short name is flagged", any("'mx'" in x for x in f) and any("'FE'" in x for x in f))
check("a bare key is flagged with the file's line", any(x.startswith("line 9: MH-3966") for x in f))
check("a key inside a code fence is not flagged", not any("MH-1 " in x for x in f))
check("a key inside a link target is not flagged twice", len([x for x in N.lint_note(f"[MH-2]({J}MH-2)\n## Checked\n") if "MH-2" in x]) == 0)
check("no Checked section is flagged", any("Checked" in x for x in f))
check("a private address is flagged, a version is not", any("address" in x for x in f) and not any("address" in x for x in N.lint_note(good)))
check("a two-part Slack text with plain keys is clean", N.lint_slack("Generic MXL arrives.\n---\nDeploy UR Caller 2.1.87; DDL for MH-3891\n") == [])
s = N.lint_slack(f"MH-3961 ships <{J}MH-3961|MH-3961> and [MH-1]({J}MH-1)\n")
check("one part, ticket ids in part 1, Slack and Markdown links are each flagged", len(s) == 4)
r = {"from": "daily-wed", "to": "prod-3", "line": "2.1",
     "lanes": {"services": [{"service": "unified-streaming", "from_lane": "daily-wed", "to_lane": "prod-3", "from": {"version": "v2.1.85", "source": "live"}, "to": {"version": "v2.1.78", "source": "live"}}]},
     "evidence": {"keys": {"MH-3872": {"verdict": "pass", "splits": [{"key": "MH-3880", "verdict": "fail", "status": "Open"}]}}},
     "placement": {"MH-3579": {"placement": "on-target"}}}
c = N.claims(r)
check("versions go to the system checker, named in full", [x["claim"][:28] for x in c if x["kind"] == "lane_version"] == ["UR Caller on daily-wed is v2", "UR Caller on prod-3 is v2.1."])
check("verdicts, splits and placement go to the Jira checker", {x["kind"] for x in c if x["checker"] == "jira"} == {"qa_verdict", "split", "placement"})
check("every claim names the read that settles it", all(x["settle"] for x in c))
print("promote note: " + ("all offline checks passed" if not failures else f"{len(failures)} failed"))
sys.exit(1 if failures else 0)
