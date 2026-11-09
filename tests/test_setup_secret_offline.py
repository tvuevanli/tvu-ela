#!/usr/bin/env python3
"""`ela secret NAME` reaches setup.py's own terminal check: bin/ela passes `--env-file <path>` to every capability
outside a short list, and setup.py accepts it as a top-level option and writes to that file. Without a terminal the
script exits 2 with its terminal message, never an argparse error. Every other capability bin/ela passes the option
to accepts it too. Nothing is written; no value is entered."""
import os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "setup"))
import setup as S  # noqa: E402 — the module under test

failures = []


def check(ok, label):
    print(("ok   " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


def run(argv):
    return subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)


r = run([sys.executable, os.path.join(ROOT, "skills", "setup", "setup.py"), "--env-file", os.devnull, "secret", "FOO_BAR"])
check(r.returncode == 2 and "run this in a terminal" in r.stderr and "invalid choice" not in r.stderr,
      "setup.py --env-file PATH secret NAME, no terminal: exit 2 with the terminal message")
if os.path.isfile(os.path.expanduser("~/.claude/ela/site.json")):
    r = run([os.path.join(ROOT, "bin", "ela"), "secret", "FOO_BAR"])
    check(r.returncode == 2 and "run this in a terminal" in r.stderr and "invalid choice" not in r.stderr,
          "bin/ela secret NAME, no terminal: exit 2 with the terminal message, not an argparse error")
check(S.env_path("/x/given.env") == "/x/given.env", "the env file bin/ela passes is the one written")

# bin/ela's run(): every capability but these gets --env-file; each must accept it
NO_ENV = {"map", "reports", "publish", "stream", "runtime", "sessions"}
for cap in sorted(os.listdir(os.path.join(ROOT, "skills"))):
    script = os.path.join(ROOT, "skills", cap, f"{cap}.py")
    if cap in NO_ENV or not os.path.isfile(script):
        continue
    r = run([sys.executable, script, "--env-file", os.devnull, "--help"])
    check(r.returncode == 0, f"{cap} accepts the --env-file bin/ela passes")

sys.exit(1 if failures else 0)
