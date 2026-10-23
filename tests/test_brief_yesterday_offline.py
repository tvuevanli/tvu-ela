#!/usr/bin/env python3
"""The yesterday join, offline: which strings count as ticket keys."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "brief"))
import brief as B  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

check("a key in a subject", B.keys_in("fix(copier): MH-3568 drop the stale PID") == ["MH-3568"])
check("a key in a branch name", B.keys_in("feature/MH-3800-issp") == ["MH-3800"])
check("codecs and standards are not keys", B.keys_in("UTF-8 ISO-8601 H-264 AAC-2 X-1 MP-4 AWS-3 QA-2") == [])
check("keys are unique and sorted", B.keys_in("WF-476 MH-1 MH-1") == ["MH-1", "WF-476"])
check("a bare number is not a key", B.keys_in("build 172, #365") == [])
sys.exit(1 if failures else 0)
