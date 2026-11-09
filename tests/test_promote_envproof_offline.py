#!/usr/bin/env python3
"""The environment proof as a gate (promote's envproof.py), offline: a QA comment's 验证环境 block on qa-cn3 proves
qa-cn3; against daily-wed it is same-build when every version it lists equals daily-wed's and other-lane when one
differs; a text with no ENV is unproven; a graph whose creator logged as prod3 is prod-3, not the lane claimed.
Fixtures from the 2026-11-09 daily-wed → prod-3 promotion."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "promote"))
import envproof as E  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

BLOCK = """验证环境（完整版本块，2026/11/9 实测）：
TVU MediaHub (ENV: aws-cn3-env)Beta
Frontend: v2.2.128 build185 2026-11-06 09:42:46
Backend: v2.1.42 build274 2026-11-06 09:40:16
Unified Resources Caller (ENV: AWSCN3)Beta
Backend: v2.1.85 build375 2026-11-06 09:40:08"""
p = E.panel(BLOCK)
check("the block names qa-cn3", p and p["lane"] == "qa-cn3")
check("its versions are read per service", p and p["versions"].get("unified-streaming", "").startswith("v2.1.85"))
check("on its own lane it is proven", E.judge("qa-cn3", p)["verdict"] == "proven")
WED85 = {"mediahub-backend": "v2.1.42 build274", "unified-streaming": "v2.1.85 build375", "mediahub-frontend": "v2.2.128 build185"}
j = E.judge("daily-wed", p, WED85)
check("daily-wed at the same versions: same-build, counts, named as qa-cn3", j["verdict"] == "same-build" and j["counts"] and j["lane"] == "qa-cn3")
WED86 = dict(WED85, **{"unified-streaming": "v2.1.86 build376"})
j = E.judge("daily-wed", p, WED86)
check("daily-wed one build ahead: other-lane, does not count", j["verdict"] == "other-lane" and not j["counts"] and "2.1.86" in j["why"])
check("no ENV in the text: unproven", E.judge("daily-wed", E.panel("tested on Wed, works"))["verdict"] == "unproven")
g = {"lane": "prod-3", "graph": "01M6ZM88V9DK398282VRYD152G", "creator": "ur-caller[prod3]", "versions": {}}
j = E.judge("daily-wed", g)
check("a graph created by prod-3's UR Caller is not a Wed test", j["verdict"] == "other-lane" and not j["counts"])
check("a graph with no creator line is unproven", E.judge("daily-wed", {"lane": None, "why": "no UR Caller line"})["verdict"] == "unproven")

if failures:
    print(f"envproof: {len(failures)} failure(s)"); sys.exit(1)
print("envproof: all offline checks passed")
