#!/usr/bin/env python3
"""sessions hook-stop: the zellij pane title carries the last reply's closing mark — ⏳ while the session waits, 🦀 when
it is out, nothing otherwise — renamed by pane id only when it changes; silent outside zellij.
Offline: a stub zellij serving a pane list and logging its calls."""
import json, os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "sessions", "sessions.py")
HOOK = os.path.join(ROOT, "hooks", "pane-mark.sh")
fail = 0


def check(ok, what):
    global fail
    print(("ok   " if ok else "FAIL ") + what)
    fail |= not ok


with tempfile.TemporaryDirectory() as tmp:
    stubs, zlog, panes = os.path.join(tmp, "bin"), os.path.join(tmp, "zellij.log"), os.path.join(tmp, "panes.json")
    os.makedirs(stubs)
    open(os.path.join(stubs, "zellij"), "w").write(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{zlog}"\n'
                                                   f'case "$*" in *list-panes*) cat "{panes}";; esac\nexit 0\n')
    os.chmod(os.path.join(stubs, "zellij"), 0o755)

    def run(title, stdin, pane="7", zellij="0", argv=None):
        json.dump([{"id": 7, "is_plugin": True, "title": "plugin"}, {"id": 7, "title": title}, {"id": 8, "title": "other"}],
                  open(panes, "w"))
        if os.path.exists(zlog):
            os.remove(zlog)
        e = dict(os.environ, HOME=tmp, ELA_TEST="1", PATH=stubs + os.pathsep + os.environ["PATH"])
        for k, v in (("ZELLIJ_PANE_ID", pane), ("ZELLIJ", zellij)):
            if v is None:
                e.pop(k, None)
            else:
                e[k] = v
        p = subprocess.run(argv or [sys.executable, SCRIPT, "hook-stop"], input=json.dumps(stdin), capture_output=True,
                           text=True, env=e)
        calls = open(zlog).read().splitlines() if os.path.exists(zlog) else []
        return p, [c for c in calls if "rename-pane" in c]

    pending = "Started the build.\n\n⏳ ela pending · the build's result · ~15 min"
    out = "Done.\n\n— ela out 🦀"
    p, r = run("worker-a", {"last_assistant_message": pending})
    check(p.returncode == 0 and r == ["action rename-pane --pane-id terminal_7 ⏳ worker-a"], f"a pending reply marks ⏳: {r}")
    p, r = run("⏳ worker-a", {"last_assistant_message": out})
    check(r == ["action rename-pane --pane-id terminal_7 🦀 worker-a"], f"out replaces ⏳ with 🦀: {r}")
    p, r = run("🦀 worker-a", {"last_assistant_message": "A question?\n\n⚖️ Needs your decision\n- apply next"})
    check(r == ["action rename-pane --pane-id terminal_7 worker-a"], f"any other closing line clears the mark: {r}")
    p, r = run("⏳ worker-a", {"last_assistant_message": pending})
    check(p.returncode == 0 and r == [], "an unchanged mark is not renamed again")
    p, r = run("worker-a", {"last_assistant_message": "⏳ ela pending is how a reply closes.\nNothing runs."})
    check(r == [], "the marker inside the text, not on the last line, marks nothing")

    tr = os.path.join(tmp, "t.jsonl")
    lines = [{"type": "assistant", "message": {"content": [{"type": "text", "text": pending}]}},
             {"type": "assistant", "isSidechain": True, "message": {"content": [{"type": "text", "text": out}]}},
             {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]}}, {"type": "user"}]
    open(tr, "w").write("".join(json.dumps(x) + "\n" for x in lines))
    p, r = run("worker-b", {"transcript_path": tr})
    check(r == ["action rename-pane --pane-id terminal_7 ⏳ worker-b"],
          f"without last_assistant_message the transcript's last main-line text decides: {r}")

    p, r = run("worker-a", {"last_assistant_message": pending}, pane=None)
    check(p.returncode == 0 and r == [] and not os.path.exists(zlog), "outside zellij (no pane id): zellij is never called")
    p, r = run("worker-a", {"last_assistant_message": pending}, zellij=None)
    check(p.returncode == 0 and not os.path.exists(zlog), "no $ZELLIJ: zellij is never called")
    p, r = run("", {"last_assistant_message": pending})
    check(r == [], "a pane with no title is left alone")
    p, r = run("worker-a", {"last_assistant_message": pending}, argv=["bash", HOOK])
    check(p.returncode == 0 and p.stdout == "" and r == ["action rename-pane --pane-id terminal_7 ⏳ worker-a"],
          f"the hook script runs it, prints nothing and exits 0: {r}")
    p, r = run("worker-a", {"last_assistant_message": pending}, pane=None, argv=["bash", HOOK])
    check(p.returncode == 0 and p.stdout == "" and not os.path.exists(zlog), "the hook script outside zellij exits 0 at once")

sys.exit(fail)
