#!/usr/bin/env python3
"""publish reads elak's last commit, offline: a throwaway git repo stands in for elak."""
import os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "publish"))
import publish as P  # noqa: E402

failures = 0


def check(name, cond):
    global failures
    print(("ok   " if cond else "FAIL ") + name)
    failures += 0 if cond else 1


with tempfile.TemporaryDirectory() as rec:
    g = lambda *a: subprocess.run(["git", "-C", rec, *a], check=True, capture_output=True)  # noqa: E731
    g("init", "-q"); g("config", "user.email", "t@example.invalid"); g("config", "user.name", "t")
    os.makedirs(os.path.join(rec, "map"))
    open(os.path.join(rec, "map", "a.yaml"), "w").write("committed: 1\n")
    g("add", "map/a.yaml"); g("commit", "-q", "-m", "one")
    open(os.path.join(rec, "map", "a.yaml"), "w").write("committed: 1\nhalf: edited\n")
    open(os.path.join(rec, "map", "b.yaml"), "w").write("new: 1\n")
    snap = P.source_root(rec)
    check("the source is the last commit, not the tree", open(os.path.join(snap, "map", "a.yaml")).read() == "committed: 1\n"
          and not os.path.exists(os.path.join(snap, "map", "b.yaml")))
    try:
        P.require_committed(rec, ["map/a.yaml", "map/b.yaml"]); stopped = False
    except SystemExit as e:
        stopped = e.code == P.EX_USAGE
    check("an edited or untracked source stops the publication", stopped)
    P.require_committed(rec, ["map/missing-is-fine.yaml"])
    check("a clean source passes", True)
    check("the published-on date is the source's commit date", len(P.source_date(rec, "map/a.yaml")) == 10)
    P.DIRTY["on"] = True
    check("--dirty reads the working tree", P.source_root(rec) == rec)
    P.require_committed(rec, ["map/a.yaml"])
    check("and lets an edited source through", True)
sys.exit(1 if failures else 0)
