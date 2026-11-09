#!/usr/bin/env python3
"""promote ship check, offline: a release version past the source lane's build lists the commits between with their
tickets, a QA verdict counts only on a build that carries the ship build, and the service is named as the owner names it."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "promote"))
import shipcheck as SC  # noqa: E402
import promote as P  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

SLUGS = {"unified-streaming", "mediahub-backend"}
check("UR Caller resolves to its slug", SC.resolve("UR Caller", SLUGS) == "unified-streaming")
check("the Jenkins job name resolves", SC.resolve("ur-caller", SLUGS) == "unified-streaming")
check("a legacy alias resolves", SC.resolve("ur-streaming", SLUGS, {"ur-streaming": "unified-streaming"}) == "unified-streaming")
check("an unknown name is None", SC.resolve("audio mixer", SLUGS) is None)

target = P.parse_version("2.1.87+377")
def at_least(text):
    return SC.carries(text, target, P.parse_version, lambda x, y: P.cmp_versions("unified-streaming", x, y))

# SNAPSHOT of 2026-11-09 ~16:00: daily-wed then ran UR Caller 2.1.85; it moved to 2.1.87 at about 17:30. The fixture
# keeps the morning's state to test the logic; it is not a statement about the lane today.
commits = [{"sha": "a1", "subject": "MH-3961 WebRenderer with the switcher's selector", "keys": ["MH-3961"]},
           {"sha": "a2", "subject": "MH-3966 reconcile passes userId", "keys": ["MH-3966"]},
           {"sha": "a3", "subject": "MH-3966 review", "keys": ["MH-3966"]},
           {"sha": "a4", "subject": "bump", "keys": []}]
qa = {"MH-3961": [{"area": "qa", "who": "QA", "when": "2026-11-08", "verdict": "pass", "env_lane": "qa-cn3",
                   "env_versions": {"unified-streaming": "v2.1.85 build375"}}],
      "MH-3966": [{"area": "qa", "who": "QA", "when": "2026-11-10", "verdict": "partial", "env_lane": "qa-cn3",
                   "env_versions": {"unified-streaming": "2.1.87"}}]}
g = SC.gap("unified-streaming", {"version": "2.1.85", "build": 375, "sha": "x"}, {"version": "2.1.87", "build": 377, "sha": "y"}, commits, qa, at_least)
check("every commit between is counted", g["commits"] == 4)
check("a pass on 2.1.85 does not cover a 2.1.87 commit", "MH-3961" in g["uncovered"])
check("a verdict on 2.1.87 written without its build covers", "MH-3966" not in g["uncovered"])
g["source"]["read_at"] = "2026-11-09T08:00:00Z"
w = SC.words(g, "daily-wed")
check("the words name the service as the owner does, with the read time", w.startswith("UR Caller ships 2.1.87 (build 377) but daily-wed runs 2.1.85 (build 375, read 2026-11-09T08:00:00Z)"))
check("a ticket with two commits reads ×2", "MH-3966 ×2" in w)
check("the uncovered ticket says where QA was seen", "MH-3961 — no QA on a build that carries it (QA seen only on v2.1.85 build375)" in w)
check("an unticketed commit is listed", "1 commit(s) with no ticket: a4 bump" in w)
NOW = "2026-11-09T10:00:00Z"
check("a fresh read with no later build is judged", SC.stale("2026-11-09T08:00:00Z", ["2026-11-09 15:30"], 4, NOW) is None)   # 15:30 +08 = 07:30Z
check("a read older than the limit is not judged", "h old" in (SC.stale("2026-11-09T05:00:00Z", [], 4, NOW) or ""))
check("a newer build finished after the read is not judged", "after the read" in (SC.stale("2026-11-09T08:00:00Z", ["2026-11-09 17:20"], 4, NOW) or ""))
check("a read with no time is not judged", SC.stale(None, [], 4, NOW) == "the read has no time")
print("promote ship: " + ("all offline checks passed" if not failures else f"{len(failures)} failed"))
sys.exit(1 if failures else 0)
