#!/usr/bin/env python3
"""sessions: the hooks' registry lines merge into one row per session; open writes a layout and refuses outside zellij;
open on ela or ela-runner starts the worker in a worktree; land fast-forwards main only when it is safe."""
import json, os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "sessions", "sessions.py")
fail = 0


STUB = '#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\nexit 0\n'   # records its argv, one line per call, and does nothing


def run(args, stdin="", stub=True, **env):
    """The script in a child whose zellij and claude are stubs first on PATH, never the owner's: no ZELLIJ* variable is
    inherited (a test run from a zellij pane would otherwise reach the real session); a test sets one explicitly."""
    e = dict(os.environ, HOME=home, ELA_TEST="1")
    for k in ("ZELLIJ", "ZELLIJ_SESSION_NAME", "ZELLIJ_PANE_ID", "ELA_SESSION_NAME", "ELA_SESSION_PURPOSE"):
        e.pop(k, None)
    e.update(env)
    if stub:
        e["PATH"] = stubs + os.pathsep + env.get("PATH", os.environ["PATH"])
    return subprocess.run([sys.executable, SCRIPT, *args], input=stdin, capture_output=True, text=True, env=e)


def claudes():
    """Claude processes on this machine started with one of the test's session names (`claude --name N`)."""
    found = set()
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            argv = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
        except OSError:
            continue
        words = [x.decode(errors="replace") for x in argv]
        if any(os.path.basename(w) == "claude" for w in words[:2]) and any(
                words[i] == "--name" and words[i + 1] in NAMES for i in range(len(words) - 1)):
            found.add(pid)
    return found


NAMES = {"desk", "busy", "runner-dev", "topic-x", "runner", "look", "w1", "w2"}


def check(ok, what):
    global fail
    print(("ok   " if ok else "FAIL ") + what)
    fail |= not ok


with tempfile.TemporaryDirectory() as tmp:
    home = os.path.join(tmp, "home")
    stubs = os.path.join(tmp, "bin")
    os.makedirs(stubs)
    for exe in ("zellij", "claude"):
        open(os.path.join(stubs, exe), "w").write(STUB.format(log=os.path.join(tmp, exe + ".log")))
        os.chmod(os.path.join(stubs, exe), 0o755)
    before = claudes()
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

    p = run(["open", "runner", "--in-place", "--dry-run", "--tab", "--name", "runner-dev", 'read "the brief"'])
    check(p.returncode == 0 and 'cwd="' + os.path.join(tmp, "projects", "ela-runner") + '"' in p.stdout
          and '"read \\"the brief\\""' in p.stdout and "new-tab --name runner-dev" in p.stdout, "open --tab --dry-run: the layout at the alias, the brief quoted")
    p = run(["open", "runner", "--in-place", "--dry-run", "--name", "runner-dev", "x"])
    check("new-tab --name workers" in p.stdout and "pane stacked=true" in p.stdout and 'name="runner-dev"' in p.stdout,
          "by default a stacked pane in a new workers tab, titled with the session's name")
    p = run(["open", "runner", "--in-place", "--pane", "--dry-run", "--brief", "/b/brief.md", "--name", "topic-x"])
    check("Read /b/brief.md and follow it." in p.stdout, "--brief FILE: the first message points to the file")
    run(["hook-start"], json.dumps({"session_id": "c", "source": "startup", "cwd": "/z"}), ELA_SESSION_NAME="busy", ZELLIJ_PANE_ID="7")
    p = run(["open", "runner", "--in-place", "--name", "busy", "x"])
    check(p.returncode == 2 and "busy is still open (pane 7)" in p.stderr, "a name a live session holds is refused")
    p = run(["close", "busy", "--dry-run"])
    check(p.returncode == 0 and "close-pane --pane-id 7" in p.stdout, "close names the process and the pane it ends")
    check(run(["close", "nobody"]).returncode == 3, "closing a name no live session holds exits 3")
    p = run(["open", "runner", "--in-place", "--pane", "--dry-run", "x"])
    check("zellij run --name runner" in p.stdout, "--pane goes through zellij run")
    p = run(["open", "runner", "--in-place", "x"])
    check(p.returncode == 2 and "not inside zellij" in p.stderr and not os.path.isdir(os.path.join(tmp, "rt", "sessions")), "outside zellij it refuses and writes nothing")
    check(run(["open", "nowhere", "x"]).returncode == 3, "an unknown target exits 3")
    # ela and ela-runner: the worker starts in a worktree; land brings it into main only when it is safe
    G = dict(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    def git(d, *args):
        return subprocess.run(["git", "-C", d, *args], capture_output=True, text=True, env=dict(os.environ, **G))
    projects, work = os.path.join(tmp, "projects"), os.path.join(tmp, "work")
    origin, ela = os.path.join(tmp, "origin.git"), os.path.join(projects, "ela")
    json.dump({"projects": projects, "runtime": os.path.join(tmp, "rt"), "work": work},
              open(os.path.join(home, ".claude", "ela", "site.json"), "w"))
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    subprocess.run(["git", "clone", "-q", origin, ela], check=True, capture_output=True)
    git(ela, "checkout", "-q", "-b", "main")
    os.makedirs(os.path.join(ela, "tests"))
    open(os.path.join(ela, "tests", "run.sh"), "w").write("#!/usr/bin/env bash\ntest ! -e FAIL\n")
    open(os.path.join(ela, "a.txt"), "w").write("a\n")
    open(os.path.join(ela, "b.txt"), "w").write("b\n")
    git(ela, "add", "."); git(ela, "commit", "-qm", "base"); git(ela, "push", "-q", "origin", "main")
    p = run(["open", "ela", "--dry-run", "x"])
    check(p.returncode == 2 and "only in a worktree" in p.stderr, "open ela without --name is refused: a worktree needs a name")
    p = run(["open", ela, "--dry-run", "--tab", "--name", "w1", "x"])
    wt = os.path.join(work, "w1", "ela")
    check(p.returncode == 0 and f"worktree add -b evan/w1 {wt} main" in p.stdout and f'cwd="{wt}"' in p.stdout
          and "ela session land w1" in p.stdout and not os.path.isdir(wt),
          "open on the ela checkout by path: a worktree on evan/N from main, the worker there; dry run creates nothing")
    p = run(["open", "ela", "--in-place", "--dry-run", "--tab", "--name", "look", "x"])
    check(f'cwd="{ela}"' in p.stdout and "worktree add" not in p.stdout, "--in-place opens the shared checkout")
    p = run(["open", "ela", "--tab", "--name", "w1", "x"], ZELLIJ_SESSION_NAME="t")
    check(p.returncode == 0 and git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "evan/w1",
          "open creates the worktree on evan/N before starting the worker")
    p = run(["open", "ela", "--dry-run", "--tab", "--name", "w1", "x"])
    check(p.returncode == 0 and "worktree add" not in p.stdout, "an existing worktree on the branch is reused")

    def land(*args):
        return run(["land", "w1", *args], **G)
    check(land().returncode == 4 and "nothing that" in land().stderr, "land with no commit on the branch refuses")
    open(os.path.join(wt, "a.txt"), "w").write("a2\n")
    p = land()
    check(p.returncode == 4 and "uncommitted changes in the worktree: a.txt" in p.stderr, "uncommitted work in the worktree refuses")
    git(wt, "commit", "-qam", "change a")
    open(os.path.join(ela, "a.txt"), "w").write("half-written\n")
    p = land()
    check(p.returncode == 4 and "dirty in the shared checkout and touched by the change: a.txt" in p.stderr
          and git(ela, "rev-parse", "main").stdout == git(ela, "rev-parse", "origin/main").stdout,
          "a dirty file in the shared checkout that the change touches refuses; main stays")
    git(ela, "checkout", "-q", "a.txt")
    open(os.path.join(ela, "b.txt"), "w").write("someone else's edit\n")
    open(os.path.join(wt, "FAIL"), "w").write("x"); git(wt, "add", "FAIL"); git(wt, "commit", "-qm", "break the tests")
    p = land()
    check(p.returncode == 4 and "tests/run.sh failed" in p.stderr and os.path.isdir(wt)
          and git(ela, "rev-parse", "main").stdout == git(ela, "rev-parse", "origin/main").stdout, "failing tests refuse; main stays")
    git(wt, "rm", "-q", "FAIL"); git(wt, "commit", "-qm", "mend the tests")
    # someone else lands first: origin moves ahead; the branch is rebased on it
    other = os.path.join(tmp, "other")
    subprocess.run(["git", "clone", "-q", origin, other], check=True, capture_output=True)
    open(os.path.join(other, "c.txt"), "w").write("c\n"); git(other, "add", "c.txt"); git(other, "commit", "-qm", "c"); git(other, "push", "-q", "origin", "main")
    p = land("--dry-run")
    check(p.returncode == 0 and "rebase evan/w1 on origin/main" in p.stdout and os.path.isdir(wt), "--dry-run prints the steps, moves nothing")
    p = land()
    check(p.returncode == 0 and "landed w1" in p.stdout, "land: rebased, tested, fast-forwarded, pushed")
    check(open(os.path.join(ela, "a.txt")).read() == "a2\n" and os.path.exists(os.path.join(ela, "c.txt"))
          and open(os.path.join(ela, "b.txt")).read() == "someone else's edit\n",
          "main carries the change and origin's commit; an unrelated dirty file is left alone")
    check(git(origin, "rev-parse", "main").stdout == git(ela, "rev-parse", "main").stdout, "main is pushed")
    check(not os.path.exists(os.path.join(work, "w1")) and git(ela, "rev-parse", "--verify", "--quiet", "evan/w1").returncode != 0,
          "the worktree and the branch are removed")
    check(run(["land", "w1"], **G).returncode == 3, "land with no worktree exits 3")
    # usage: each API message counted once, subagents added, the cost from cost-state, the kind from where it ran
    import datetime
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    proj = os.path.join(home, ".claude", "projects", "-p")
    os.makedirs(os.path.join(proj, "s1", "subagents"))
    def amsg(mid, inp, out, rd, wr, blocks):
        return {"type": "assistant", "timestamp": stamp, "cwd": "/w/.ela-guest/2026-11-18-x",
                "message": {"id": mid, "model": "m1", "content": blocks,
                            "usage": {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": rd,
                                      "cache_creation_input_tokens": wr}}}
    lines = [{"type": "user", "cwd": "/w/.ela-guest/2026-11-18-x", "message": {"content": "what runs on prod"}},
             amsg("m-a", 1, 10, 100, 5, [{"type": "text", "text": "x"}]),
             amsg("m-a", 1, 10, 100, 5, [{"type": "tool_use", "name": "Skill", "input": {"skill": "ela:graph"}}]),
             amsg("m-b", 2, 20, 200, 0, [{"type": "tool_use", "name": "Bash", "input": {}}]),
             {"type": "cost-state", "totalCostUSD": 1.25}]
    open(os.path.join(proj, "s1.jsonl"), "w").write("".join(json.dumps(l) + "\n" for l in lines))
    open(os.path.join(proj, "s1", "subagents", "agent-1.jsonl"), "w").write(json.dumps(amsg("m-c", 3, 30, 300, 7, [])) + "\n")
    p = run(["usage", "--since", "1d", "--json"])
    rows = {r["id"]: r for r in json.loads(p.stdout)["sessions"]} if p.returncode == 0 else {}
    s1 = rows.get("s1") or {}
    check(s1.get("tokens") == {"input": 6, "output": 60, "cache_read": 600, "cache_write": 12} and s1.get("turns") == 3,
          "usage counts each message id once and adds the subagent's transcript")
    check(s1.get("cost_usd") == 1.25 and s1.get("kind") == "guest" and s1.get("skills") == {"ela:graph": 1}
          and s1.get("tools") == {"Skill": 1, "Bash": 1}, "the cost from cost-state, the kind from the cwd, tools and skills counted")
    check(s1.get("purpose") == "what runs on prod", "a session the registry does not know takes its first prompt as purpose")
    run(["hook-end"], json.dumps({"session_id": "s1", "reason": "exit", "transcript_path": os.path.join(proj, "s1.jsonl")}))
    end = json.loads(open(os.path.join(tmp, "rt", "sessions.jsonl")).read().splitlines()[-1])
    check((end.get("usage") or {}).get("tokens", {}).get("cache_read") == 600, "the end line stores the session's usage")
    os.remove(os.path.join(proj, "s1.jsonl"))
    rows = {r["id"]: r for r in json.loads(run(["usage", "--since", "1d", "--json"]).stdout)["sessions"]}
    check((rows.get("s1") or {}).get("cost_usd") == 1.25, "with the transcript cleaned up, the stored usage stands in")
    check(run(["usage", "--since", "soon"]).returncode == 2, "a --since that is no window exits 2")
    # a continued session is counted once, through its successor; a prompt is redacted whole before it is cut
    tok = "Q" * 40
    prev = [{"type": "user", "cwd": "/w", "message": {"content": "x" * 60 + " the key: " + tok}},
            amsg("m-p", 1, 1, 10, 0, []), {"type": "continued-in", "continuedInSessionId": "s3"}, [1, 2]]
    succ = [{"type": "user", "cwd": "/w", "message": {"content": "go on"}}, amsg("m-p", 1, 1, 10, 0, []),
            amsg("m-q", 1, 1, 10, 0, []), {"type": "cost-state", "totalCostUSD": 2.0,
                                            "modelUsage": {"m1": {"costUSD": 2.0}}}]
    open(os.path.join(proj, "s2.jsonl"), "w").write("".join(json.dumps(l) + "\n" for l in prev))
    open(os.path.join(proj, "s3.jsonl"), "w").write("".join(json.dumps(l) + "\n" for l in succ))
    p = run(["usage", "--since", "1d", "--json"])
    out = json.loads(p.stdout)
    rows = {r["id"]: r for r in out["sessions"]}
    check("s2" not in rows and rows.get("s3", {}).get("turns") == 2 and rows["s3"].get("cost_by_model") == {"m1": 2.0},
          "a session continued in another is dropped; the successor carries its messages and cost")
    run(["hook-end"], json.dumps({"session_id": "s2", "reason": "exit", "transcript_path": os.path.join(proj, "s2.jsonl")}))
    end = json.loads(open(os.path.join(tmp, "rt", "sessions.jsonl")).read().splitlines()[-1])
    check(end.get("purpose") and "QQQQQQQQ" not in end["purpose"], "the stored purpose is redacted before it is cut")
    check(run(["usage", "--since", "1d", "--by", "model"]).returncode == 0 and "m1" in run(["usage", "--since", "1d", "--by", "model"]).stdout,
          "--by model groups by the message's model")
    # here: the session a command runs in, from the registry's live row for the process above it; the name is the
    # transcript's last custom-title line (what /rename writes), else the registry's
    U1, U2 = "11111111-2222-4333-8444-555555555555", "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    run(["hook-start"], json.dumps({"session_id": U1, "source": "startup", "cwd": "/h"}), ELA_SESSION_NAME="topic-x")
    p = run(["here", "--json"])
    here = json.loads(p.stdout) if p.returncode == 0 else {}
    check(here == {"id": U1, "name": "topic-x", "transcript": None},
          "here: the last session this process started, among several live rows; no transcript, the registry's name")
    t1 = os.path.join(proj, U1 + ".jsonl")
    open(t1, "w").write("".join(json.dumps(l) + "\n" for l in (
        {"type": "user", "message": {"content": 'say "custom-title" twice'}},
        {"type": "custom-title", "customTitle": "first-name", "sessionId": U1},
        ["custom-title"],
        {"type": "custom-title", "customTitle": "topic-10-bit\n", "sessionId": U1})) + '{"type":"custom-title", cut\n')
    here = json.loads(run(["here", "--json"]).stdout)
    check(here == {"id": U1, "name": "topic-10-bit", "transcript": t1},
          "here: the name is the transcript's last custom-title line, one line; a line that is not one is passed over")
    check(run(["here"]).stdout == f"{U1}\ttopic-10-bit\n", "here without --json: the id, a tab, the name")
    # no live row: the session id of the environment; none at all exits 3 (in process: the test owns the process above)
    sys.path.insert(0, os.path.dirname(SCRIPT))
    import sessions as S
    S.SITE, S.TRANSCRIPTS, S.claude_pid = os.path.join(home, ".claude", "ela", "site.json"), os.path.join(home, ".claude", "projects"), os.getpid
    kept = {k: os.environ.pop(k, None) for k in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID")}
    open(os.path.join(proj, U2 + ".jsonl"), "w").write(json.dumps({"type": "custom-title", "customTitle": "desk-2"}) + "\n")
    check(S.current() is None and S.cmd_here(type("A", (), {"json": False})()) == 3, "here outside a Claude session finds none and exits 3")
    os.environ["CLAUDE_SESSION_ID"] = "not-an-id"
    check(S.current() is None, "a session id that is no UUID is not taken")
    os.environ["CLAUDE_SESSION_ID"] = U2
    check(S.current() == {"id": U2, "name": "desk-2", "transcript": os.path.join(proj, U2 + ".jsonl")},
          "with no live row, the environment's session id; its name from its transcript")
    open(os.path.join(tmp, "rt", "sessions.jsonl"), "a").write(
        json.dumps({"event": "start", "id": U1, "at": "2026-11-19T10:00:00+08:00", "pid": os.getpid()}) + "\n"
        + json.dumps({"event": "end", "id": U1, "at": "2026-11-19T11:00:00+08:00"}) + "\n")
    check(S.current()["id"] == U2, "a row that has ended is not this session, whatever its process id")
    for k, v in kept.items():
        os.environ.pop(k, None)
        if v is not None:
            os.environ[k] = v
    # nothing reached the owner's zellij or started a Claude: every zellij call is the stub's, and claude never ran
    seen = open(os.path.join(tmp, "zellij.log")).read().splitlines() if os.path.exists(os.path.join(tmp, "zellij.log")) else []
    check(len(seen) == 2 and seen[0] == "action query-tab-names" and seen[1].startswith("action new-tab --name w1 --cwd " + wt),
          "the stub zellij saw every call the test made: the tab query and the one tab the real open made")
    check(not os.path.exists(os.path.join(tmp, "claude.log")), "the stub claude never ran: the stub zellij starts nothing")
    check(not (claudes() - before), "no process named claude with one of the test's session names was started")
sys.exit(fail)
