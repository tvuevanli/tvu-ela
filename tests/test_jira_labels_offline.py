#!/usr/bin/env python3
"""The label vocabulary gate, offline: what jira.py refuses to add, against a small vocabulary."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "jira"))
import jira as J  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

V = {"closed": {"proto:": {"proto:srt", "proto:hls"}, "flag:": {"flag:closing"}}, "bare": {"Fox": "summary [Fox]", "AA": "retire"}}
check("a listed proto: value passes", J.label_problems(["proto:srt", "flag:closing"], V) == [])
check("an unlisted proto: value is refused, with the values", "proto:hls" in J.label_problems(["proto:sr"], V)[0])
check("release: and pending-svc: follow their registries", J.label_problems(["release:mh-9", "pending-svc:x"], V) == [])
check("no customer: label (the summary bracket carries it)", "bracket" in J.label_problems(["customer:fox"], V)[0])
check("no feat: label (the component carries it)", "component" in J.label_problems(["feat:Audio"], V)[0])
check("a retired bare label is refused, with its replacement", J.label_problems(["Fox"], V) == ["Fox: retired; use summary [Fox]"])
check("an unknown bare label is refused", J.label_problems(["random"], V) == ["random: not in the vocabulary"])
print("jira labels: all offline checks passed" if not failures else f"jira labels: {len(failures)} failed")
sys.exit(1 if failures else 0)
