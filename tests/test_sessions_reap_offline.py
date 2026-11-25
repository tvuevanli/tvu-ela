#!/usr/bin/env python3
"""sessions reap: each live session's state from git and its transcript; --apply lands a ready worker and closes the
finished idle ones, never the desk, a busy, dirty, waiting or brief-less one. open on ela refuses with no first message.
Offline: a fake registry and transcripts, `sleep` processes standing in for Claude, a stub zellij, local git repos."""
import datetime, json, os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "sessions", "sessions.py")
G = dict(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
fail = 0


def check(ok, what):
    global fail
    print(("ok   " if ok else "FAIL ") + what)
    fail |= not ok


def git(d, *args):
    return subprocess.run(["git", "-C", d, *args], capture_output=True, text=True, env=dict(os.environ, **G))


with tempfile.TemporaryDirectory() as tmp:
    home, stubs = os.path.join(tmp, "home"), os.path.join(tmp, "bin")
    os.makedirs(stubs)
    os.makedirs(os.path.join(home, ".claude", "ela"))
    zlog = os.path.join(tmp, "zellij.log")
    open(os.path.join(stubs, "zellij"), "w").write(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{zlog}"\nexit 0\n')
    os.chmod(os.path.join(stubs, "zellij"), 0o755)
    projects, work, rt = os.path.join(tmp, "projects"), os.path.join(tmp, "work"), os.path.join(tmp, "rt")
    json.dump({"projects": projects, "runtime": rt, "work": work}, open(os.path.join(home, ".claude", "ela", "site.json"), "w"))

    def run(args):
        e = dict(os.environ, HOME=home, ELA_TEST="1", PATH=stubs + os.pathsep + os.environ["PATH"], **G)
        for k in ("ZELLIJ", "ZELLIJ_SESSION_NAME", "ZELLIJ_PANE_ID", "CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID"):
            e.pop(k, None)
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=e)

    # the shared checkout with an origin, and worker worktrees in the states reap tells apart
    origin, ela = os.path.join(tmp, "origin.git"), os.path.join(projects, "ela")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    subprocess.run(["git", "clone", "-q", origin, ela], check=True, capture_output=True)
    git(ela, "checkout", "-q", "-b", "main")
    os.makedirs(os.path.join(ela, "tests"))
    open(os.path.join(ela, "tests", "run.sh"), "w").write("#!/usr/bin/env bash\nexit 0\n")
    for f in ("a.txt", "b.txt"):
        open(os.path.join(ela, f), "w").write(f + "\n")
    git(ela, "add", "."); git(ela, "commit", "-qm", "base"); git(ela, "push", "-q", "origin", "main")

    def worktree(n, commit=None, dirty=None):
        wt = os.path.join(work, n, "ela")
        git(ela, "worktree", "add", "-q", "-b", f"evan/{n}", wt, "main")
        if commit:
            open(os.path.join(wt, commit), "w").write(n + "\n"); git(wt, "add", commit); git(wt, "commit", "-qm", n)
        if dirty:
            open(os.path.join(wt, dirty), "w").write("half\n")
        return wt
    worktree("tl", commit="c.txt")                 # to-land, says it is ready: landed, then closed
    worktree("tr", commit="b.txt")                 # to-land, ready, but the checkout's b.txt is dirty: refused, kept
    open(os.path.join(ela, "b.txt"), "w").write("someone else's edit\n")
    worktree("dt", dirty="d.txt")                  # dirty
    worktree("fr")                                 # opened, nothing committed yet: not landed
    worktree("ld", commit="e.txt")            # its commit reached main another way: landed
    git(ela, "merge", "-q", "--ff-only", "evan/ld")
    worktree("pl", commit="pl.txt")           # landed, but its last reply still waits: pending, never closed
    git(ela, "merge", "-q", "--ff-only", "evan/pl")
    worktree("pt", commit="pt.txt")           # to-land, ready, and waiting: landed, not closed
    base_sha = git(ela, "rev-parse", "--short", "main").stdout.strip()
    # landed, then the worktree and branch removed as `session land` leaves them; the only reply still asks for a task
    worktree("lb", commit="lb.txt")
    lb_sha = git(ela, "rev-parse", "--short", "evan/lb").stdout.strip()
    git(ela, "merge", "-q", "--ff-only", lb_sha)            # lb reached main with no `merge evan/lb` in the reflog
    worktree("la", commit="la.txt")
    git(ela, "merge", "-q", "--ff-only", "evan/la")         # the reflog records `merge evan/la`
    for n in ("la", "lb"):
        git(ela, "worktree", "remove", os.path.join(work, n, "ela")); git(ela, "branch", "-q", "-D", f"evan/{n}")

    old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=30)).isoformat()
    new = datetime.datetime.now(datetime.timezone.utc).isoformat()
    proj = os.path.join(home, ".claude", "projects", "-p")
    os.makedirs(proj)
    procs, reg = {}, []

    def user(text, ts=old):
        return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": text}}

    def reply(text, ts=old, stop="end_turn"):
        return {"type": "assistant", "timestamp": ts, "message": {"role": "assistant", "stop_reason": stop,
                                                                 "content": [{"type": "text", "text": text}]}}

    def session(sid, name, cwd, lines, at=old):
        p = subprocess.Popen(["sleep", "300"])
        procs[sid] = p
        reg.append({"event": "start", "id": sid, "at": at, "name": name, "cwd": cwd, "pid": p.pid, "pane": None,
                    "job": "midday" if sid == "s-job" else None})
        if lines is not None:
            open(os.path.join(proj, sid + ".jsonl"), "w").write("".join(json.dumps(x) + "\n" for x in lines))
    W = lambda n: os.path.join(work, n, "ela")   # noqa: E731
    session("s-tl", "tl", W("tl"), [user("do it"), reply("Committed. Ready to land: `ela session land tl`.")])
    session("s-tr", "tr", W("tr"), [user("do it"), reply("Committed; run `ela session land tr`.")])
    session("s-dt", "dt", W("dt"), [user("do it"), reply("Done.\n\n— ela out 🦀")])
    session("s-fr", "fr", W("fr"), [user("do it"), reply("Reading the code first.")])
    session("s-ld", "ld", W("ld"), [user("do it"), reply("Landed by the desk.")])
    session("s-gone", "gone", W("gone"), [user("do it"), reply("All done.")])
    asks = "No task came with this session. What would you like me to do?"
    session("s-la", "la", W("la"), [user("brief"), reply(f"Branch clean at {base_sha}. {asks}")])
    session("s-lb", "lb", W("lb"), [user("brief"), reply(f"Committed {lb_sha}; the desk landed it. {asks}")])
    session("s-lc", "lc", W("lc"), [user("brief"), reply(f"Branch clean at {base_sha}. {asks}")], at=new)
    session("s-nb", "nb", "/x", [])
    session("s-ask", "ask", "/x", [user("hi"), reply("No task came with this session. What would you like me to do?")])
    session("s-sig", "sig", "/x", [user("look"), reply("The answer.\n\n— ela out 🦀")])
    session("s-sig-new", "signew", "/x", [user("look"), reply("The answer.\n\n— ela out 🦀", ts=new)])
    session("s-wait", "wait", "/x", [user("look"), reply("Two ways.\n\n**Shall I take A?**")])
    wait = "\n\n⏳ ela pending · the desk's reply · after the land"
    session("s-pend", "pend", "/x", [user("look"), reply("Asked the peer." + wait)])
    session("s-pl", "pl", W("pl"), [user("do it"), reply("Landed." + wait)])
    session("s-pt", "pt", W("pt"), [user("do it"), reply("Committed. Ready to land: `ela session land pt`." + wait)])
    session("s-dec", "dec", "/x", [user("look"), reply("Built both.\n\n**⚖️ Needs your decision**\n- the label: say `apply next`")])
    session("s-busy", "busy", "/x", [user("look"), reply("Working on it.", stop="tool_use")])
    session("s-desk", "desk", projects, [user("hello"), reply("Fine.\n\n— ela out 🦀")])
    session("s-root", None, projects, [user("hello"), reply("Fine.\n\n— ela out 🦀")])
    session("s-ela", "ela", "/x", [user("hello"), reply("Fine.\n\n— ela out 🦀")])
    session("s-hand", None, "/x", [user("hello"), reply("Fine.\n\n— ela out 🦀")])
    session("s-job", "runner-x", "/x", [user("pass"), reply("Done.\n\n— ela out 🦀")])
    os.makedirs(rt)
    open(os.path.join(rt, "sessions.jsonl"), "w").write("".join(json.dumps(x) + "\n" for x in reg))

    p = run(["reap", "--json"])
    rows = {r["id"]: r for r in json.loads(p.stdout)} if p.returncode == 0 else {}
    st = {k: v["state"] for k, v in rows.items()}
    check(p.returncode == 0 and len(rows) == len(procs), "reap: one row per live session")
    check(st.get("s-tl") == "to-land" and rows["s-tl"]["ready"] and st.get("s-tr") == "to-land",
          "a branch with commits beyond main and a clean worktree is to-land; ready when the reply says so")
    check(st.get("s-dt") == "dirty", "an uncommitted change is dirty, whatever the reply says")
    check(st.get("s-fr") == "busy", "a worktree whose branch never had a commit is not landed")
    check(st.get("s-ld") == "landed" and st.get("s-gone") == "landed",
          "landed: the branch has nothing beyond main after commits of its own, or the worktree is gone")
    check(st.get("s-nb") == "no-brief" and st.get("s-ask") == "no-brief", "no-brief: no typed message, or the only reply asks for a task")
    check(st.get("s-la") == "landed" and "merge evan/la" in rows["s-la"]["reason"],
          "worktree and branch gone, main's reflog records merge evan/<N>: landed, though the only reply asks for a task")
    check(st.get("s-lb") == "landed" and lb_sha in rows["s-lb"]["reason"],
          "worktree and branch gone, a reply names a commit main gained after the session started: landed")
    check(st.get("s-lc") == "no-brief",
          "worktree gone, no land record, the reply names only the base main already had: still no-brief")
    check(st.get("s-sig") == "signed-off" and st.get("s-sig-new") == "signed-off", "signed-off: the last line is the sign-off")
    check(st.get("s-wait") == "waiting-owner" and rows["s-wait"]["question"] == "**Shall I take A?**",
          "waiting-owner carries the question line")
    check(st.get("s-pend") == "pending" and rows["s-pend"]["reason"].startswith("⏳ ela pending · the desk's reply")
          and st.get("s-pl") == "pending" and st.get("s-pt") == "to-land" and rows["s-pt"]["pending"],
          "a last line `⏳ ela pending · …` is pending, even when its commit already reached main")
    check(st.get("s-dec") == "waiting-owner" and rows["s-dec"]["question"] == "⚖️ Needs your decision",
          "an open ⚖️ Needs your decision is waiting-owner, though no line ends with a question mark")
    check(st.get("s-busy") == "busy" and st.get("s-desk") == "desk" and st.get("s-root") == "desk",
          "a turn under way is busy; the desk by name or by the projects root is never reaped")
    check(st.get("s-ela") == "desk" and st.get("s-job") == "runner", "the desk named ela is the desk; a runner job's session is its own")
    check(rows["s-tl"]["age"] in (29, 30, 31) and rows["s-sig-new"]["age"] == 0, "age: minutes since the last reply")
    p = run(["reap"])
    check(p.returncode == 0 and any(x.split()[:2] == ["wait", "waiting-owner"] for x in p.stdout.splitlines()),
          "without --json: one line per session, name and state first")
    check(not any(p.poll() is not None for p in procs.values()), "reap without --apply ends nothing")

    p = run(["reap", "--apply", "--json"])
    rows = {r["id"]: r for r in json.loads(p.stdout)} if p.returncode == 0 else {}
    ended = {sid for sid, pr in procs.items() if (pr.wait(timeout=5) if sid in {"s-tl", "s-ld", "s-gone", "s-la", "s-lb", "s-sig"} else pr.poll()) is not None}
    check(ended == {"s-tl", "s-ld", "s-gone", "s-la", "s-lb", "s-sig"}, f"--apply closes the landed and the idle signed-off sessions only: {sorted(ended)}")
    check(rows.get("s-tl", {}).get("action") == "landed, closed" and git(origin, "rev-parse", "main").stdout == git(ela, "rev-parse", "main").stdout
          and os.path.exists(os.path.join(ela, "c.txt")) and not os.path.isdir(W("tl")),
          "a ready to-land worker is landed (main fast-forwarded, pushed, worktree removed), then closed")
    check(rows.get("s-tr", {}).get("action", "").startswith("land refused: dirty in the shared checkout") and procs["s-tr"].poll() is None,
          "a refused land is reported and the session stays open")
    check("under 10m" in (rows.get("s-sig-new", {}).get("action") or ""), "a signed-off session idle under 10 minutes is kept")
    check(procs["s-dt"].poll() is None, "a dirty worktree is never closed, even signed off")
    check(all(procs[k].poll() is None for k in ("s-pend", "s-pl", "s-pt", "s-dec")),
          "pending and an open decision are never closed")
    check(rows.get("s-pt", {}).get("action") == "landed" and os.path.exists(os.path.join(ela, "pt.txt")),
          "a ready to-land that waits is landed, and its session kept")
    check(st.get("s-hand") == "signed-off" and rows["s-hand"]["action"] == "started by hand: closes on the owner's word"
          and procs["s-hand"].poll() is None, "a signed-off session started by hand is reported, not closed")
    lines = open(os.path.join(rt, "sessions.jsonl")).read().splitlines()
    check(sum('"closed by desk"' in x for x in lines) == 6, "each close writes an end line, closed by desk")
    p = run(["reap", "--last"])
    left = p.stdout.splitlines()
    check(p.returncode == 0 and any(x.startswith("tr: to-land — land refused") for x in left) and any(x.startswith("wait: waiting-owner — ") for x in left)
          and not any(x.startswith(("tl:", "sig:", "desk:", "ela:", "runner-x:")) for x in left), "--last: one line per session the pass left open, the desk not among them")
    check(not os.path.exists(zlog), "no pane was named, so zellij was never called")

    # a pane zellij holds after its session ended (the worker exited, or was closed from outside zellij) is swept
    panes = [{"id": 9, "title": "🦀 held", "exited": True}, {"id": 10, "title": "live", "exited": False},
             {"id": 11, "title": "renamed", "exited": True}, {"id": 12, "is_plugin": True, "title": "held", "exited": True}]
    json.dump(panes, open(os.path.join(tmp, "panes.json"), "w"))
    open(os.path.join(stubs, "zellij"), "w").write(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{zlog}"\n'
                                                   f'case "$*" in *list-panes*) cat "{tmp}/panes.json";; esac\nexit 0\n')
    t0 = "2026-11-25T10:00:00+08:00"
    with open(os.path.join(rt, "sessions.jsonl"), "a") as f:
        for sid, name, pane in (("s-held", "held", "9"), ("s-live", "live", "10"), ("s-other", "other", "11")):
            f.write(json.dumps({"event": "start", "id": sid, "at": t0, "name": name, "cwd": "/x", "pid": 1, "pane": pane, "zellij": "z"}) + "\n")
            f.write(json.dumps({"event": "end", "id": sid, "at": t0, "reason": "other"}) + "\n")
    p = run(["reap", "--apply"])
    calls = open(zlog).read().splitlines() if os.path.exists(zlog) else []
    closes = [c for c in calls if "close-pane" in c]
    check(p.returncode == 0 and "--session z action list-panes --json" in calls
          and closes == ["--session z action close-pane --pane-id terminal_9"] and "held" in p.stderr,
          f"--apply closes the exited pane of an ended session by its id and name, nothing else: {closes}")

    e = dict(os.environ, HOME=home, ELA_TEST="1", PATH=os.path.join(tmp, "none") + os.pathsep + "/usr/bin:/bin")
    p = subprocess.run([sys.executable, SCRIPT, "reap", "--apply"], capture_output=True, text=True, env=e)
    check(p.returncode == 2 and "ELA_TEST=1" in p.stderr, "under ELA_TEST --apply with no stub zellij refuses")

    # open on ela with no first message is refused; --no-brief opens it on purpose
    p = run(["open", "ela", "--dry-run", "--tab", "--name", "w9"])
    check(p.returncode == 2 and "--brief FILE or the quoted brief" in p.stderr, "open on ela with no brief is refused")
    p = run(["open", "ela", "--dry-run", "--tab", "--name", "w9", "--no-brief"])
    check(p.returncode == 0 and "worktree add -b evan/w9" in p.stdout, "--no-brief opens it on purpose")
    p = run(["open", "ela", "--dry-run", "--tab", "--name", "w9", "--brief", "/b/x.md"])
    check(p.returncode == 0, "--brief FILE is a first message")
    for pr in procs.values():
        if pr.poll() is None:
            pr.kill()
            pr.wait()
sys.exit(fail)
