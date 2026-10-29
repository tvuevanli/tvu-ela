#!/usr/bin/env python3
"""sessions: the hooks' registry lines merge into one row per session; open writes a layout and refuses outside zellij."""
import json, os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "sessions", "sessions.py")
fail = 0


def run(args, stdin="", **env):
    e = dict(os.environ, HOME=home)
    e.pop("ZELLIJ_SESSION_NAME", None)
    e.update(env)
    return subprocess.run(["python3", SCRIPT, *args], input=stdin, capture_output=True, text=True, env=e)


def check(ok, what):
    global fail
    print(("ok   " if ok else "FAIL ") + what)
    fail |= not ok


with tempfile.TemporaryDirectory() as tmp:
    home = os.path.join(tmp, "home")
    os.makedirs(os.path.join(home, ".claude", "ela"))
    os.makedirs(os.path.join(tmp, "projects", "ela-runner"))
    json.dump({"projects": os.path.join(tmp, "projects"), "runtime": os.path.join(tmp, "rt")},
              open(os.path.join(home, ".claude", "ela", "site.json"), "w"))
    transcript = os.path.join(tmp, "t.jsonl")
    open(transcript, "w").write(json.dumps({"type": "user", "message": {"content": "review the helm board"}}) + "\n")

    run(["hook-start"], json.dumps({"session_id": "a", "source": "startup", "cwd": "/x"}), ELA_SESSION_NAME="desk", ELA_SESSION_PURPOSE="brief a")
    run(["hook-start"], json.dumps({"session_id": "a", "source": "compact", "cwd": "/x"}))
    run(["hook-start"], json.dumps({"session_id": "b", "source": "startup", "cwd": "/y"}))
    run(["hook-end"], json.dumps({"session_id": "b", "reason": "exit", "transcript_path": transcript}))
    rows = {r["id"]: r for r in json.loads(run(["list", "--json"]).stdout)}
    lines = open(os.path.join(tmp, "rt", "sessions.jsonl")).read().splitlines()
    check(len(lines) == 3, "a compact start writes no line")
    check(rows["a"]["name"] == "desk" and rows["a"]["purpose"] == "brief a" and rows["a"]["ended"] is None, "an opened session carries its name and purpose, still open")
    check(rows["b"]["ended"] and rows["b"]["purpose"] == "review the helm board", "the end line closes it and takes the purpose from the first prompt")
    run(["hook-start"], json.dumps({"session_id": "b", "source": "resume", "cwd": "/y"}))
    rows = {r["id"]: r for r in json.loads(run(["list", "--json"]).stdout)}
    check(rows["b"]["ended"] is None, "a resume reopens it")

    p = run(["open", "runner", "--dry-run", "--name", "runner-dev", 'read "the brief"'])
    check(p.returncode == 0 and 'cwd="' + os.path.join(tmp, "projects", "ela-runner") + '"' in p.stdout
          and '"read \\"the brief\\""' in p.stdout and "new-tab --name runner-dev" in p.stdout, "open --dry-run: the layout at the alias, the brief quoted")
    p = run(["open", "runner", "--pane", "--dry-run", "x"])
    check("zellij run --name runner" in p.stdout, "--pane goes through zellij run")
    p = run(["open", "runner", "x"])
    check(p.returncode == 2 and "not inside zellij" in p.stderr and not os.path.isdir(os.path.join(tmp, "rt", "sessions")), "outside zellij it refuses and writes nothing")
    check(run(["open", "nowhere", "x"]).returncode == 3, "an unknown target exits 3")
sys.exit(fail)
