#!/usr/bin/env python3
"""Deploy prerequisites and branch state (promote's prereqs.py), offline: an SQL statement and a backfill call are
items, a negated line is not; a release-todo line carries its list; a commit after the build is unbuilt; an unmerged
ticket branch is dry-run merged against the release branch and against another ticket's branch (2026-11-09: MH-3891's
DDL surfaced only when asked; MH-3961's follow-up conflicted with MH-3966)."""
import os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "promote"))
import prereqs as P  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

DOC = """## 4 deploy
ALTER TABLE t_encoding_profile ADD COLUMN root_group_id varchar(64) NULL;
GET /base/debug/encodingProfile/backfillRootGroupId (backfill, idempotent)
- release todo list:
No DDL, no config key in this change.
"""
items = P.scan(DOC, "doc")
cats = [i["category"] for i in items]
check("an ALTER TABLE statement is a ddl item", "ddl" in cats)
check("a backfill call is a one-off item", "one-off" in cats)
check("a negated line is no item", not any("No DDL" in i["line"] for i in items))
items = P.scan("发版待办" + ": databases\n| env | db |\n|---|---|\n| com | db_a |\n\nother text", "doc")
check("a release-todo line carries the list under it", items and items[0]["category"] == "release-todo" and any("db_a" in d for d in items[0]["detail"]))
check("a key = value line counts only beside a release word", not P.scan("a.b.c = true", "x") and P.scan("before deploy set a.b.c = true", "x"))

# ── a repo: release branch, a build, one commit after it, two ticket branches that conflict with each other ───
d = tempfile.mkdtemp(prefix="ela-prereqs-")
origin, work = os.path.join(d, "origin.git"), os.path.join(d, "work")
def g(*a, cwd=None):
    return subprocess.run(["git", *a], cwd=cwd or work, capture_output=True, text=True, check=True).stdout.strip()
subprocess.run(["git", "init", "-q", "--bare", origin], check=True)
subprocess.run(["git", "clone", "-q", origin, work], check=True, capture_output=True)
g("config", "user.email", "t@example"); g("config", "user.name", "t"); g("checkout", "-q", "-b", "release2.1")
open(os.path.join(work, "a.java"), "w").write("line1\nline2\n"); g("add", "."); g("commit", "-qm", "base")
build = g("rev-parse", "HEAD")
open(os.path.join(work, "b.java"), "w").write("x\n"); g("add", "."); g("commit", "-qm", "fix(MH-3961): selector"); g("push", "-q", "origin", "release2.1")
for br, text in (("feature/MH-3961", "line1 selector\nline2\n"), ("feature/MH-3966", "line1 userId\nline2\n")):
    g("checkout", "-q", "-b", br, "release2.1"); open(os.path.join(work, "a.java"), "w").write(text); g("commit", "-qam", f"fix({br[8:]}): change"); g("push", "-q", "origin", br)
g("fetch", "-q", "origin")
P.repo_path = lambda repo: work
delta = {"services": [{"service": "unified-streaming", "repo": "web/mx-service", "from_build": {"sha": build, "branch": "release2.1", "version": "2.1.85"}}]}
u = P.unbuilt(delta)
check("the commit after the build is unbuilt", len(u[0]["commits"]) == 1 and "MH-3961" in u[0]["commits"][0]["subject"])
b = {x["branch"]: x for x in P.branches(delta, ["MH-3961", "MH-3966"])}
check("both ticket branches are found unmerged", set(b) == {"origin/feature/MH-3961", "origin/feature/MH-3966"})
check("each merges clean into the release branch alone", all(x["against_release"]["clean"] for x in b.values()))
check("they conflict with each other, file named", b["origin/feature/MH-3961"]["with_others"] and "a.java" in b["origin/feature/MH-3961"]["with_others"][0]["conflicts"])

if failures:
    print(f"prereqs: {len(failures)} failure(s)"); sys.exit(1)
print("prereqs: all offline checks passed")
