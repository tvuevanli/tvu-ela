#!/usr/bin/env python3
"""ela promote plan, offline: a plan written into the pending record (local file only), its one-line form, the three
re-checks as ✓/·/✗ lines from fixture mails and a fixture git, --check on the plan already there, and close clearing it."""
import json, os, sys, tempfile, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ("promote", "testlist", "brief"):
    sys.path.insert(0, os.path.join(ROOT, "skills", d))
import promote as P  # noqa: E402
import testlist as TL  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

P.line_cfg = lambda line: {"lanes": {"qa": "qa-cn3", "daily": "daily-wed", "prod": "prod-3"}}
P.R.rmap = lambda key: {"repos": {"mediahub-backend": "web/a", "mediahub-frontend": "web/b", "unified-streaming": "web/c"}}.get(key)
P.scope_slugs = lambda scope: ["mediahub-backend", "mediahub-frontend", "unified-streaming"]
P.repo_path = lambda repo: "/x/" + repo
GIT = {"web/a": {"refs": "  origin/feature/MH-1860\n", "ancestor": 0}, "web/b": {"refs": "  origin/feature/MH-1860\n", "ancestor": 1}, "web/c": {"refs": "", "ancestor": 0}}   # merge-base --is-ancestor: 0 = merged
def fake_git(path, *args, timeout=60):
    g = GIT[path[3:]]
    if args[0] == "branch":
        return 0, g["refs"], ""
    if args[0] == "rev-parse":
        return 0, "abc", ""
    if args[0] == "merge-base":
        return g["ancestor"], "", ""
    return 1, "", "unknown"
P.git = fake_git
MAIL = {"build": "81", "at": "2026-11-04T17:40:00+08:00", "log": [{"keys": ["MH-1860"], "layer": "App", "text": "MediaHub Backend: x — MH-1860"}], "focus": [], "label": "81", "id": "m", "subject": "s"}
TL.release_mails = lambda env, days: {"qa-cn3": {"shown": "QA-AWS3", "mails": [MAIL]}}
TL.report_mails = lambda env, days: {"qa-cn3": []}

with tempfile.TemporaryDirectory() as d:
    pending = os.path.join(d, "pending.json")
    a = types.SimpleNamespace(line="2.1", src="daily", dst="prod", on="2026-11-06", after="QA's report on Thursday's build", carry=["MH-1860"],
                              check=False, pending=pending, json=False, env_file=None)
    P.cmd_plan(a)
    rec = json.load(open(pending))["2.1|daily-wed|prod-3"]
    check("the plan is on the record under the line and lane pair", rec["plan"]["on"] == "2026-11-06" and rec["plan"]["carry"] == ["MH-1860"] and rec["closed"] is False)
    check("the next-train label names the planned day", rec["candidate"]["label"] == "planned Fri 11-06 → prod-3")
    lines = rec["plan_checks"]["lines"]
    check("a branch not merged in one repo blocks (✗) and names the repo", lines[0].startswith("✗ MH-1860: feature/MH-1860 not merged into release2.1 in 1 repo") and "web/b" in lines[0])
    check("the newest QA build naming the key holds (✓)", lines[1] == "✓ QA build 81 names MH-1860")
    check("no QA report yet is a dot", lines[2] == "· no QA report on build 81 yet")
    check("the one-line form carries the day, the condition and the key with its merge state",
          P.plan_line(rec) == "planned Fri 11-06 after QA's report on Thursday's build · carries MH-1860 (feature/MH-1860 not merged into release2.1 in 1 repo as of 11-04)")
    TL.report_mails = lambda env, days: {"qa-cn3": [{"build": "81", "at": "x", "summary": False, "text": "", "subject": ""}]}
    P.cmd_plan(types.SimpleNamespace(line="2.1", src="daily", dst="prod", on=None, after=None, carry=None, check=True, pending=pending, json=False, env_file=None))
    rec = json.load(open(pending))["2.1|daily-wed|prod-3"]
    check("--check keeps the plan and re-runs the checks", rec["plan"]["after"] == "QA's report on Thursday's build" and rec["plan_checks"]["lines"][2] == "✓ QA report on build 81")
    try:
        P.cmd_plan(types.SimpleNamespace(line="2.1", src="daily", dst="prod", on="2026-11-06", after=None, carry=None, check=False, pending=pending, json=False, env_file=None)); code = 0
    except SystemExit as e:
        code = e.code
    check("--on without --after is refused", code == P.EX_USAGE)
    P.pending_path = lambda: pending
    P.cmd_close(types.SimpleNamespace(line="2.1", to="prod-3", json=False))
    rec = json.load(open(pending))["2.1|daily-wed|prod-3"]
    check("close clears the plan", rec["closed"] is True and "plan" not in rec and "plan_checks" not in rec)

# a real repository: origin/feature/MH-1860 ahead of origin/release2.1, then merged
import subprocess
real_git = P.git.__wrapped__ if hasattr(P.git, "__wrapped__") else None
def sh(d, *args):
    return subprocess.run(["git", "-C", d, *args], capture_output=True, text=True, env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"})
with tempfile.TemporaryDirectory() as d:
    sh(d, "init", "-q", "-b", "release2.1"); open(os.path.join(d, "f"), "w").write("1"); sh(d, "add", "f"); sh(d, "commit", "-q", "-m", "base")
    sh(d, "update-ref", "refs/remotes/origin/release2.1", "HEAD")
    sh(d, "checkout", "-q", "-b", "feature/MH-1860"); open(os.path.join(d, "f"), "w").write("2"); sh(d, "commit", "-q", "-am", "MH-1860")
    sh(d, "update-ref", "refs/remotes/origin/feature/MH-1860", "HEAD")
    P.git = lambda path, *args, timeout=60: (lambda r: (r.returncode, r.stdout, r.stderr))(sh(path, *args))
    P.repo_path = lambda repo: d
    states = P.key_branch_state("MH-1860", "2.1", {"mediahub-frontend": "web/x"})
    check("a real checkout: the feature branch is found and is not an ancestor of release2.1", states == [("web/x", "not merged", ["origin/feature/MH-1860"])])
    sh(d, "update-ref", "refs/remotes/origin/release2.1", "HEAD")
    states = P.key_branch_state("MH-1860", "2.1", {"mediahub-frontend": "web/x"})
    check("once release2.1 contains it the branch is merged", states == [("web/x", "merged", ["origin/feature/MH-1860"])])
    check("a key with no branch", P.key_branch_state("MH-9999", "2.1", {"mediahub-frontend": "web/x"}) == [("web/x", "no branch", [])])

if failures:
    print(f"promote plan: {len(failures)} check(s) failed"); sys.exit(1)
print("promote plan: all offline checks passed")
