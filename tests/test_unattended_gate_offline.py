#!/usr/bin/env python3
"""bin/ela refuses, under ELA_NO_APPLY, every flag that writes, joins or skips a confirm, and session land|close,
for every verb; outside it the same arguments pass (plan 2026-11-26-review-autonomy-adversarial, item 4)."""
import importlib.machinery, importlib.util, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
loader = importlib.machinery.SourceFileLoader("ela_bin", os.path.join(ROOT, "bin", "ela"))
spec = importlib.util.spec_from_loader("ela_bin", loader)
ela = importlib.util.module_from_spec(spec); loader.exec_module(ela)

fails = []
def check(name, cond):
    if not cond:
        fails.append(name)

os.environ.pop("ELA_NO_APPLY", None); os.environ.pop("ELA_GUEST", None)
check("owner: --apply passes", ela.unattended("jira", ["comment", "MH-1", "--apply"]) is None)
check("owner: session land passes", ela.unattended("sessions", ["land", "x"]) is None)

os.environ["ELA_NO_APPLY"] = "1"
for cap, args in [("jira", ["comment", "MH-1", "--apply"]), ("slack", ["post", "C1", "hi", "--yes"]),
                  ("meeting", ["--join"]), ("vault", ["answer", "--apply=1"]), ("anything", ["x", "--apply"])]:
    check(f"refused: {cap} {args}", ela.unattended(cap, args) is not None)
check("refused: session land", ela.unattended("sessions", ["land", "x"]) is not None)
check("refused: session close", ela.unattended("sessions", ["close", "x"]) is not None)
check("dry run passes", ela.unattended("jira", ["comment", "MH-1", "text"]) is None)
check("session list passes", ela.unattended("sessions", ["list"]) is None)
check("session reap dry passes", ela.unattended("sessions", ["reap"]) is None)
check("session reap --apply refused", ela.unattended("sessions", ["reap", "--apply"]) is not None)
check("a text after -- is data", ela.unattended("slack", ["post", "C1", "--", "--apply"]) is None)
check("a longer flag is not --apply", ela.unattended("x", ["--applying"]) is None)
check("abbreviation still refused", ela.abbreviated(["--app"]) is not None)

# the gate runs before any capability: run() exits with the refusal and never reaches exec
try:
    ela.run("jira", ["comment", "MH-1", "--apply"], "/nonexistent")
    fails.append("run() did not refuse")
except SystemExit as e:
    check("run() refuses with the reason", "ELA_NO_APPLY" in str(e.code))

if fails:
    print("unattended gate: FAIL\n  " + "\n  ".join(fails)); sys.exit(1)
print("unattended gate: ok")
