#!/usr/bin/env python3
"""ela sessions — open a worker session, list the sessions on this machine, find an earlier one by what it was about.

  sessions open <alias|path> [--name N] [--tab | --pane] [--brief FILE] [--permission-mode M] [--dry-run] ["brief"]
  sessions close <name> [--dry-run]
  sessions reap [--apply] [--json] | reap --last
  sessions land <name> [--repo ela|runner] [--dry-run]
  sessions list [--limit 30] [--json]
  sessions usage [--since 7d|48h|YYYY-MM-DD] [--by kind|name|day|cwd|model] [--top 10] [--json]
  sessions find <word> [<word>…] [--since YYYY-MM-DD] [--limit 20] [--json]
  sessions here [--json]              this session: its id, its name (/rename) and its transcript
  sessions hook-start | hook-end      the plugin's SessionStart / SessionEnd hooks; hook JSON on stdin

open: a Claude session where the target's rules live, by default a stacked pane in the tab named `workers` (made
when missing; one pane expanded, the others title bars), the pane titled with the session's name; --tab opens a tab
of its own, --pane a pane beside the current one (a topic session beside the desk). The target is a site root by
alias (ela, runner, elak, helm, reports, published), `code/<ref>` resolved by map.py where, or a directory.
--brief FILE makes the first message a pointer to that file. The default name is the alias. It refuses a name a
live session holds (started, not ended, its process alive). Outside zellij it refuses. --dry-run prints the layout
and the commands. Focus returns to the tab named `desk` when there is one.

open on ela or ela-runner (the alias or the checkout's path) does not start the worker in the shared checkout:
every `ela` command, the runner and every session run that checkout, so an unfinished edit there is production.
It needs --name N, adds the worktree <work>/<N>/<repo> on branch evan/<N> from main (reusing the worktree or the
branch when one exists) and starts the worker there; --in-place opens the checkout itself, for a look, not a change.

land: brings a worker's branch evan/<N> into the shared checkout, all or nothing. In order: the worktree has no
uncommitted change; the checkout is on main with no rebase or merge under way; origin is fetched; the branch is
rebased on origin/main (or on main when main is ahead); tests/run.sh passes in the worktree; no dirty or untracked
file in the checkout is one the change touches; then main is fast-forwarded, pushed, and the worktree and the branch
are removed. Any failed step refuses with its reason and leaves main where it was; a failed rebase is aborted.
--dry-run makes the read-only checks and prints the steps. Exit 4 for a refusal, 5 when git fails after main moved.

close: ends a live session by name: TERM to its Claude process, then its pane (`zellij action close-pane
--pane-id`), and an end line "closed by desk" in the registry. The desk runs it after the worker's closing line.

open on ela or ela-runner refuses without a first message (--brief FILE or the quoted brief): a worker opened with
none sits asking what to do. --no-brief opens it so on purpose.

reap: every live session in the registry (not ended, its process alive) gets one state from first-hand facts, in
this order: desk (the session reap runs in, one named ela or desk, or one started in the projects root: never
touched) · runner (a runner job's own session: it ends itself) ·
dirty (an uncommitted change in its worktree <work>/<N>/<repo>) · to-land (evan/<N> has commits beyond main, the
worktree clean) · no-brief (no typed message, or the only reply asks for a task) · landed (the worktree is gone, or
the branch has nothing beyond main after commits of its own, the worktree clean) · signed-off (the last reply's last
line is `— ela out 🦀`) · waiting-owner (the last reply asks a question: its line is shown) · busy (anything else).
One row each: name, state, minutes since the last reply, the reason.
--apply, once each session has been idle 10 minutes: `land` each to-land whose last reply says it is ready (once;
a refusal is reported and the session stays open), then `close` each landed session, and each signed-off one with
nothing to land; a session started by hand (no name from `session open`) is only reported, since it closes on the
owner's word. busy, dirty, waiting-owner and no-brief are never closed; `claude --resume <id>` brings back any
closed one. The result goes to <runtime>/sessions/reap.json; --last prints its sessions left open, one line each
(the desk's session start shows them).

Under a test (ELA_TEST=1, exported by tests/run.sh) a live open or close refuses, exit 2, unless the zellij on PATH
lies under the temp directory: a test reaches only a stub, never the owner's zellij or a real Claude session.

here: the session a command runs in, so a note it writes can say where it came from (`ela note stamp`). The id
is the registry's live row for the Claude process above the command, else that process's `--resume`/`--session-id`
argument, else $CLAUDE_CODE_SESSION_ID or $CLAUDE_SESSION_ID; the name is the transcript's last /rename, else the registry's. Exit 3 when no
session is found (a command run outside Claude).

list: the registry <runtime>/sessions.jsonl, newest first: name · cwd · started · ended · purpose. The
hooks append to it (a start line on startup or resume, an end line at SessionEnd); nothing else writes it,
and nothing in it is committed anywhere (ADR 0001).

usage: what the sessions on this machine cost, from Claude Code's own transcripts (~/.claude/projects): tokens
summed per API message (each message once, the subagents' transcripts included), the cost from the transcript's
cost-state line when Claude Code wrote one, the tools and skills called. A session counts when its last message
is inside the window, all of it. Grouped by kind: an unattended runner pass by the name the runner gave it (`runner-…`), a
Slack guest session `guest`, a named session `worker`, any other `interactive`; --by name keeps every name.
When Claude Code has cleaned a transcript up, the usage its end line stored in the registry stands in.

find: reads the local transcripts under ~/.claude/projects/*/*.jsonl; nothing remote, nothing written.
A session matches when every word (case-insensitive) appears in its first prompt or its final answer.
The current session ($CLAUDE_SESSION_ID) and subagent transcripts are skipped.

Printed per hit, newest first: the date · the project directory · the first prompt (140 chars) · the final
answer (240 chars) · the paths the session read (Read tool calls, at most 12, relative to <projects> or <code>).
--json adds the transcript path.

Not printed: tool results of any kind, any other prompt or answer. Every printed string passes configserver.redact (credentials), then publish.redact
(addresses become <ip> / <tailnet>) and any run of 32+ token-shaped characters becomes <token>.

Exit codes: 0 ok · 2 usage · 3 nothing found / unknown target · 4 land refused · 5 zellij or git failed.
"""
import argparse, datetime, glob, json, os, re, shlex, shutil, subprocess, sys, tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "publish"))
from publish import redact   # one rule for addresses, defined once (publish.py)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "configserver"))
from redact import scrub as cut_credentials   # one rule for embedded credentials (configserver/redact.py)

SITE = os.path.expanduser("~/.claude/ela/site.json")
TRANSCRIPTS = os.path.expanduser("~/.claude/projects")
TOKEN = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?![A-Za-z0-9_-])"
                   r"|[A-Za-z0-9_-]{32,}")   # a UUID (a transcript's own name) is matched first and kept
MAX_PATHS = 12


def roots():
    try:
        s = json.load(open(SITE))
    except Exception:
        return None, None
    projects = s.get("projects")
    code = s.get("code") or (os.path.join(projects, "code") if projects else None)
    return projects, code


def site():
    try:
        return json.load(open(SITE))
    except Exception:
        return {}


def runtime_root():
    s = site()
    return s.get("runtime") or (os.path.join(s["projects"], ".ela") if s.get("projects") else None)


def registry():
    r = runtime_root()
    return os.path.join(r, "sessions.jsonl") if r else None


def clean(text):
    """Credentials cut first (a stream key's rule needs the URL's host whole), then addresses, then any long run."""
    return TOKEN.sub(lambda m: m.group(1) or "<token>", redact(cut_credentials(text or "")))


def shown_path(p, projects, code):
    for name, root in (("<code>", code), ("<projects>", projects)):   # <code> first: it usually sits inside <projects>
        if root and (p == root or p.startswith(root.rstrip("/") + "/")):
            return name + p[len(root.rstrip("/")):]
    return p


def read_session(path, projects, code):
    """First plain-string user prompt, the last assistant line's text, earliest timestamp, paths read."""
    first, final, earliest, paths = None, None, None, []
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        ts = d.get("timestamp")
        if isinstance(ts, str) and (earliest is None or ts < earliest):
            earliest = ts
        kind = d.get("type")
        msg = d.get("message") if isinstance(d.get("message"), dict) else {}
        content = msg.get("content")
        if kind == "user" and first is None and isinstance(content, str):
            if d.get("isSidechain") is True:
                return None                                  # a subagent transcript
            first = content
        elif kind == "assistant" and isinstance(content, list):
            final = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Read":
                    fp = (b.get("input") or {}).get("file_path")
                    if isinstance(fp, str):
                        rel = shown_path(fp, projects, code)
                        if rel not in paths and len(paths) < MAX_PATHS:
                            paths.append(rel)
    if first is None:
        return None
    return {"first": first, "final": final or "", "started": earliest or "", "paths": paths}


def one_line(text, n):
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


# ── usage: what a session cost, read from its transcript ───────────────────────────────────────

TOKENS = ("input", "output", "cache_read", "cache_write")
USAGE_KEPT = ("tokens", "by_model", "cost_by_model", "cost_usd", "turns", "subagents", "models", "tools", "skills", "last", "continued_in")


def _tokens_of(path, tools, skills, seen):
    """Read one transcript file's assistant messages into `seen` (message id → usage, shared by a session's files:
    Claude Code writes one line per content block, each carrying the whole message's usage, and a subagent's file may
    repeat a message of its parent; the largest usage of an id is kept, since a later line may carry the final count).
    → (models, cwd, first timestamp, last timestamp, the session this one continued in, or None)."""
    models, cwd, first, last, cont = set(), None, None, None, None
    for line in open(path, encoding="utf-8", errors="replace"):
        if cwd is not None and '"assistant"' not in line and '"continued-in"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        if cwd is None and isinstance(d.get("cwd"), str):
            cwd = d["cwd"]
        if d.get("type") == "continued-in" and isinstance(d.get("continuedInSessionId"), str):
            cont = d["continuedInSessionId"]
        if d.get("type") != "assistant":
            continue
        ts = d.get("timestamp")
        if isinstance(ts, str):
            first, last = first or ts, ts
        msg = d.get("message") if isinstance(d.get("message"), dict) else {}
        for b in msg.get("content") if isinstance(msg.get("content"), list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                name = str(b.get("name") or "?")
                tools[name] = tools.get(name, 0) + 1
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                if name == "Skill":
                    sk = str(inp.get("skill") or "?")
                    skills[sk] = skills.get(sk, 0) + 1
        u, mid = msg.get("usage"), msg.get("id")
        if not isinstance(u, dict):
            continue
        n = lambda k: u.get(k) if isinstance(u.get(k), (int, float)) else 0
        t = {"input": n("input_tokens"), "output": n("output_tokens"), "cache_read": n("cache_read_input_tokens"),
             "cache_write": n("cache_creation_input_tokens"), "model": msg.get("model") if isinstance(msg.get("model"), str) else None}
        key = mid if isinstance(mid, str) and mid else f"{path}:{len(seen)}"
        old = seen.get(key)
        if old is None or sum(t[k] for k in TOKENS) > sum(old[k] for k in TOKENS):
            seen[key] = t
        if t["model"]:
            models.add(t["model"])
    return models, cwd, first, last, cont


def _cost_state(path):
    """The last cost-state line Claude Code wrote into the transcript (its own running total, subagents and
    background models included), or None. Only the cost is taken from it; the tokens are counted from the messages."""
    found = None
    for line in open(path, encoding="utf-8", errors="replace"):
        if '"cost-state"' in line:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("type") == "cost-state":
                found = d
    return found


def usage_of(transcript):
    """One session's usage: tokens summed over its own transcript and its subagents' (<id>/subagents/*.jsonl), each
    message once, the tools and skills it called, its cost when Claude Code recorded one, the session it continued
    in. None when the file cannot be read."""
    tools, skills, seen = {}, {}, {}
    try:
        models, cwd, first, last, cont = _tokens_of(transcript, tools, skills, seen)
        cs = _cost_state(transcript)
    except OSError:
        return None
    sub = 0
    for p in sorted(glob.glob(os.path.join(transcript[:-len(".jsonl")], "subagents", "*.jsonl"))):
        try:
            m, _, _, _, _ = _tokens_of(p, tools, skills, seen)
        except OSError:
            continue
        sub += 1
        models |= m
    tokens = {k: sum(t[k] for t in seen.values()) for k in TOKENS}
    by_model = {}
    for t in seen.values():
        b = by_model.setdefault(t["model"] or "?", dict.fromkeys(TOKENS, 0))
        for k in TOKENS:
            b[k] += t[k]
    cost = cs.get("totalCostUSD") if cs else None
    mu = cs.get("modelUsage") if cs and isinstance(cs.get("modelUsage"), dict) else {}
    cost_by_model = {m: round(v["costUSD"], 4) for m, v in mu.items() if isinstance(v, dict) and isinstance(v.get("costUSD"), (int, float))}
    return {"tokens": tokens, "by_model": by_model, "cost_by_model": cost_by_model, "cost_usd": round(cost, 4) if isinstance(cost, (int, float)) else None,
            "turns": len(seen), "subagents": sub, "models": sorted(models), "tools": tools, "skills": skills,
            "cwd": cwd, "first": first, "last": last, "continued_in": cont}


def cmd_find(a):
    projects, code = roots()
    words = [w.lower() for w in a.words]
    current = os.environ.get("CLAUDE_SESSION_ID")
    hits = []
    for path in glob.glob(os.path.join(TRANSCRIPTS, "*", "*.jsonl")):
        name = os.path.basename(path)
        if current and current in (name, name[:-len(".jsonl")]):
            continue
        s = read_session(path, projects, code)
        if not s:
            continue
        if a.since and s["started"][:10] < a.since:
            continue
        hay = (s["first"] + "\n" + s["final"]).lower()
        if all(w in hay for w in words):
            s["project"] = os.path.basename(os.path.dirname(path))
            s["transcript"] = path
            hits.append(s)
    hits.sort(key=lambda h: h["started"], reverse=True)
    hits = hits[:a.limit]
    if not hits:
        print("no session matches " + " ".join(clean(w) for w in a.words), file=sys.stderr)
        return 3
    if a.json:
        print(json.dumps([{"date": h["started"][:10], "started": clean(h["started"]), "project": clean(h["project"]),
                           "first_prompt": clean(one_line(h["first"], 140)), "final_answer": clean(one_line(h["final"], 240)),
                           "paths": [clean(p) for p in h["paths"]], "transcript": clean(shown_path(h["transcript"], projects, code))}
                          for h in hits], ensure_ascii=False, indent=2))
        return 0
    for h in hits:
        print(f"{h['started'][:10]} · {clean(h['project'])}")
        print(f"  asked:    {clean(one_line(h['first'], 140))}")
        print(f"  answered: {clean(one_line(h['final'], 240))}")
        for p in h["paths"]:
            print(f"  read      {clean(p)}")
        print()
    return 0


# ── open ────────────────────────────────────────────────────────────────────────────────────────

ALIASES = {"ela": "ela", "runner": "ela-runner", "helm": "helm"}    # under <projects>
ROOT_ALIASES = ("elak", "reports", "published")                     # their own site.json keys


def target_dir(ref):
    """(directory, default name) for an alias, code/<ref> or a path; (None, why) when nothing matches."""
    s = site()
    projects = s.get("projects")
    if ref in ALIASES and projects:
        return os.path.join(projects, ALIASES[ref]), ref
    if ref in ROOT_ALIASES and s.get(ref):
        return s[ref], ref
    if ref.startswith("code/"):
        inner = ref[len("code/"):]
        mapper = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "map", "map.py")
        p = subprocess.run(["python3", mapper, "where", inner, "--json"], capture_output=True, text=True, timeout=60)
        try:
            out = json.loads(p.stdout)
        except ValueError:
            return None, (p.stderr.strip() or f"map.py where {inner}: no answer")
        dirs = ([out["dir"]] if isinstance(out, dict) and "dir" in out
                else [r["dir"] for r in out] if isinstance(out, list)
                else [r["dir"] for r in out.get("repos", []) if r.get("dir")])
        dirs = [d for d in dirs if d and os.path.isdir(d)]
        if len(dirs) != 1:
            return None, f"{ref}: {'no checkout on disk' if not dirs else 'several checkouts: ' + ', '.join(dirs)} — clone it or pass the path"
        return dirs[0], os.path.basename(dirs[0].rstrip("/"))
    path = os.path.abspath(os.path.expanduser(ref))
    if os.path.isdir(path):
        return path, os.path.basename(path.rstrip("/"))
    return None, f"{ref}: not an alias ({', '.join(list(ALIASES) + list(ROOT_ALIASES))}), not code/<ref>, not a directory"


GUARDED = ("ela", "ela-runner")   # checkouts under <projects> that every ela command runs: changed only in a worktree
BASE = "main"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def guarded(cwd):
    """The repository name when cwd is the shared ela or ela-runner checkout, else None."""
    projects = site().get("projects")
    for repo in GUARDED:
        if projects and os.path.realpath(cwd) == os.path.realpath(os.path.join(projects, repo)):
            return repo
    return None


def work_root():
    s = site()
    return s.get("work") or (os.path.join(runtime_root(), "work") if runtime_root() else None)


def git(d, *args):
    return subprocess.run(["git", "-C", d, *args], capture_output=True, text=True)


def worktree_plan(checkout, wt, branch):
    """(git argv to run or None when the worktree is there, None) or (None, why it cannot be used)."""
    if os.path.isdir(wt):
        head = git(wt, "rev-parse", "--abbrev-ref", "HEAD")
        if head.returncode != 0 or head.stdout.strip() != branch:
            return None, f"{wt} exists but is not a worktree on {branch} — pick another name"
        return None, None
    if git(checkout, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0:
        return ["git", "-C", checkout, "worktree", "add", wt, branch], None
    return ["git", "-C", checkout, "worktree", "add", "-b", branch, wt, BASE], None


def kdl(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t") + '"'


def one_line80(text):
    return one_line(text or "", 80)


WORKERS, DESK = "workers", "desk"


def zellij_out(*args):
    p = subprocess.run(["zellij", *args], capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else None


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def live(name):
    """The live session holding a name: started, not ended, its process alive; None when there is none."""
    return next((r for r in sessions() if r["name"] == name and not r["ended"] and r.get("pid") and alive(r["pid"])), None)


def test_refusal():
    """open on ela or ela-runner refuses without a first message (--brief FILE or the quoted brief): a worker opened with
none sits asking what to do. --no-brief opens it so on purpose.

reap: every live session in the registry (not ended, its process alive) gets one state from first-hand facts, in
this order: desk (the session reap runs in, one named ela or desk, or one started in the projects root: never
touched) · runner (a runner job's own session: it ends itself) ·
dirty (an uncommitted change in its worktree <work>/<N>/<repo>) · to-land (evan/<N> has commits beyond main, the
worktree clean) · no-brief (no typed message, or the only reply asks for a task) · landed (the worktree is gone, or
the branch has nothing beyond main after commits of its own, the worktree clean) · signed-off (the last reply's last
line is `— ela out 🦀`) · waiting-owner (the last reply asks a question: its line is shown) · busy (anything else).
One row each: name, state, minutes since the last reply, the reason.
--apply, once each session has been idle 10 minutes: `land` each to-land whose last reply says it is ready (once;
a refusal is reported and the session stays open), then `close` each landed session, and each signed-off one with
nothing to land; a session started by hand (no name from `session open`) is only reported, since it closes on the
owner's word. busy, dirty, waiting-owner and no-brief are never closed; `claude --resume <id>` brings back any
closed one. The result goes to <runtime>/sessions/reap.json; --last prints its sessions left open, one line each
(the desk's session start shows them).

Under a test (ELA_TEST=1, which tests/run.sh exports), the reason a live open or close must not run: the zellij
    on PATH is not a stub under the temp directory, so it would reach the owner's real session; None when it may."""
    if os.environ.get("ELA_TEST") != "1":
        return None
    z, tmp = shutil.which("zellij"), os.path.realpath(tempfile.gettempdir())
    if z and os.path.commonpath([os.path.realpath(z), tmp]) == tmp:
        return None
    return (f"ELA_TEST=1 and the zellij on PATH ({z or 'none'}) is not a stub under {tmp}: a test never reaches "
            "the real zellij or starts a Claude session")


def cmd_open(a):
    why = None if a.dry_run else test_refusal()   # first: a live open under test touches neither git nor zellij
    if why:
        print(f"session open: {why}", file=sys.stderr)
        return 2
    cwd, name = target_dir(a.target)
    if not cwd:
        print(f"session open: {name}", file=sys.stderr)
        return 3
    if guarded(cwd) and not (a.brief or a.brief_file or a.no_brief):
        print(f"session open: a worker on {guarded(cwd)} starts with its task — pass --brief FILE or the quoted brief "
              "(--no-brief to open it without one, on purpose)", file=sys.stderr)
        return 2
    repo = None if a.in_place else guarded(cwd)
    prep, note = None, ""
    if repo:
        if not a.name or not NAME.fullmatch(a.name):
            print(f"session open: {repo} is changed only in a worktree — pass --name N (letters, digits, . _ -) for "
                  f"<work>/N/{repo} on branch evan/N, or --in-place to open the shared checkout for a look", file=sys.stderr)
            return 2
        if not work_root():
            print("session open: no work root in site.json — run /ela:setup", file=sys.stderr)
            return 2
        checkout, branch = cwd, f"evan/{a.name}"
        cwd = os.path.join(work_root(), a.name, repo)
        prep, why = worktree_plan(checkout, cwd, branch)
        if why:
            print(f"session open: {why}", file=sys.stderr)
            return 2
        note = (f"You work in the worktree {cwd} on branch {branch}, never in the shared checkout {checkout}; commit here, "
                f"and the desk lands it with `ela session land {a.name}`.")
    name = a.name or name
    held = live(name)
    if held and not a.dry_run:
        print(f"session open: {name} is still open (pane {held.get('pane') or '?'}); close it with `ela session close {name}` "
              "or pick another name", file=sys.stderr)
        return 2
    first = " ".join(x for x in ((f"Read {os.path.abspath(a.brief_file)} and follow it." if a.brief_file else ""), a.brief, note) if x)
    argv = ["env", f"ELA_SESSION_NAME={name}", f"ELA_SESSION_PURPOSE={one_line80(a.brief or (a.brief_file and os.path.basename(a.brief_file)) or '')}",
            "claude", "--name", name]
    if a.permission_mode:
        argv += ["--permission-mode", a.permission_mode]
    if first:
        argv.append(first)
    pane = (f"pane command={kdl(argv[0])} cwd={kdl(cwd)} name={kdl(name)} focus=true {{\n"
            f"        args {' '.join(kdl(x) for x in argv[1:])}\n    }}")
    tabs = (zellij_out("action", "query-tab-names") or "").split() if os.environ.get("ZELLIJ_SESSION_NAME") else []
    mode = "pane" if a.pane else "tab" if a.tab else "workers"
    chrome = lambda inner: ("layout {\n"   # noqa: E731 — zellij's default tab: tab bar, the panes, status bar
                            '    pane size=1 borderless=true { plugin location="zellij:tab-bar"; }\n'
                            f"    {inner}\n"
                            '    pane size=2 borderless=true { plugin location="zellij:status-bar"; }\n'
                            "}\n")
    if mode == "pane":
        layout = f"layout {{\n    {pane}\n}}\n"
        runs = [["zellij", "run", "--name", name, "--cwd", cwd, "--", *argv]]
    elif mode == "tab":
        layout = chrome(pane)
        runs = [["zellij", "action", "new-tab", "--name", name, "--cwd", cwd, "--layout", "<layout>"]]
    elif WORKERS in tabs:
        layout = ""
        runs = [["zellij", "action", "go-to-tab-name", WORKERS], ["zellij", "run", "--stacked", "--name", name, "--cwd", cwd, "--", *argv]]
    else:
        layout = chrome(f"pane stacked=true {{\n        {pane}\n    }}")
        runs = [["zellij", "action", "new-tab", "--name", WORKERS, "--cwd", cwd, "--layout", "<layout>"]]
    if mode == "workers" and DESK in tabs:
        runs.append(["zellij", "action", "go-to-tab-name", DESK])
    if a.dry_run:
        if prep:
            print(" ".join(shlex.quote(x) for x in prep))
        print(layout or "(the workers tab exists: no layout)")
        for run in runs:
            print(" ".join(shlex.quote(x) for x in run))
        return 0
    if not os.environ.get("ZELLIJ_SESSION_NAME"):
        print("session open: not inside zellij — start zellij first (`zellij attach -c ela`), then run this from a pane", file=sys.stderr)
        return 2
    root = runtime_root()
    if not root:
        print("session open: no runtime root in site.json — run /ela:setup", file=sys.stderr)
        return 2
    if prep:
        os.makedirs(os.path.dirname(cwd), exist_ok=True)
        p = subprocess.run(prep, capture_output=True, text=True)
        if p.returncode != 0:
            print(f"session open: git worktree add failed: {p.stderr.strip() or p.returncode}", file=sys.stderr)
            return 5
        print(f"worktree {shown_path(cwd, *roots())} on {branch}")
    d = os.path.join(root, "sessions")
    os.makedirs(d, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(d, f"{stamp}-{re.sub(r'[^A-Za-z0-9_.-]+', '-', name)}.kdl")
    with open(path, "w") as f:
        f.write(layout)
    for run in runs:
        p = subprocess.run([path if x == "<layout>" else x for x in run], capture_output=True, text=True)
        if p.returncode != 0:
            print(f"session open: zellij failed: {p.stderr.strip() or p.returncode}", file=sys.stderr)
            return 5
    where = {"pane": "a pane beside this one", "tab": "its own tab", "workers": f"a stacked pane in the {WORKERS} tab"}[mode]
    print(f"opened {name} in {where} at {shown_path(cwd, *roots())}  (layout {path})")
    if not trusted(cwd):
        print("the folder is new to Claude Code: the session waits in its tab for your trust answer, and is recorded after it")
    return 0


# ── land ────────────────────────────────────────────────────────────────────────────────────────

def dirty(d):
    """Paths with uncommitted or untracked changes in a checkout (both sides of a rename)."""
    out = git(d, "status", "--porcelain", "-z", "--untracked-files=all").stdout
    paths, items, i = set(), out.split("\0"), 0
    while i < len(items):
        it = items[i]
        if len(it) > 3:
            paths.add(it[3:])
            if it[0] in "RC":            # a rename's source follows as its own item
                i += 1
                if i < len(items) and items[i]:
                    paths.add(items[i])
        i += 1
    return paths


def touched(d, *ranges):
    files = set()
    for r in ranges:
        files |= {x for x in git(d, "diff", "--name-only", r).stdout.splitlines() if x}
    return files


def cmd_land(a):
    def refuse(why, code=4):
        print(f"session land {a.name}: refused — {why}", file=sys.stderr)
        return code
    if not NAME.fullmatch(a.name):
        return refuse("a name is letters, digits, . _ -", 2)
    projects, work = site().get("projects"), work_root()
    if not projects or not work:
        return refuse("no projects or work root in site.json — run /ela:setup", 2)
    repos = [ALIASES.get(a.repo, a.repo)] if a.repo else list(GUARDED)
    repos = [r for r in repos if r in GUARDED and os.path.isdir(os.path.join(work, a.name, r))]
    if len(repos) != 1:
        where = os.path.join(shown_path(work, *roots()), a.name)
        return refuse(f"no worktree of ela or ela-runner under {where}" if not repos
                      else f"worktrees of {' and '.join(repos)} under {where} — pass --repo", 3)
    repo = repos[0]
    wt, checkout, branch = os.path.join(work, a.name, repo), os.path.join(projects, repo), f"evan/{a.name}"
    if git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() != branch:
        return refuse(f"{wt} is not on {branch}")
    if dirty(wt):
        return refuse("uncommitted changes in the worktree: " + ", ".join(sorted(dirty(wt))) + " — commit or drop them first")
    if git(checkout, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() != BASE:
        return refuse(f"the shared checkout {checkout} is not on {BASE}")
    for marker in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD"):
        if os.path.exists(os.path.join(checkout, git(checkout, "rev-parse", "--git-path", marker).stdout.strip())):
            return refuse(f"a {marker.lower().replace('_', ' ')} is under way in the shared checkout")
    if not os.path.isfile(os.path.join(wt, "tests", "run.sh")):
        return refuse(f"no tests/run.sh in {wt}")
    f = git(checkout, "fetch", "--quiet", "origin", BASE)
    if f.returncode != 0:
        return refuse(f"fetch origin failed: {f.stderr.strip()}")
    upstream = f"origin/{BASE}"
    if git(checkout, "merge-base", "--is-ancestor", BASE, upstream).returncode == 0:
        base = upstream
    elif git(checkout, "merge-base", "--is-ancestor", upstream, BASE).returncode == 0:
        base = BASE
    else:
        return refuse(f"{BASE} and {upstream} have diverged — settle the shared checkout first")
    if git(checkout, "rev-list", "--count", f"{base}..{branch}").stdout.strip() == "0":
        return refuse(f"{branch} has nothing that {base} lacks — remove the worktree with `git worktree remove {wt}`")
    def overlap():
        return sorted(dirty(checkout) & touched(checkout, f"{BASE}...{branch}", *([f"{BASE}..{base}"] if base != BASE else [])))
    both = overlap()
    if both:
        return refuse("dirty in the shared checkout and touched by the change: " + ", ".join(both)
                      + " — whoever holds them commits or stashes first")
    steps = [f"rebase {branch} on {base}", "tests/run.sh in the worktree", f"fast-forward {BASE} in {checkout}",
             f"push origin {BASE}", f"remove the worktree {wt} and {branch}"]
    if a.dry_run:
        print("\n".join(steps))
        return 0
    r = git(wt, "rebase", base)
    if r.returncode != 0:
        git(wt, "rebase", "--abort")
        return refuse(f"rebase on {base} failed and was aborted: {(r.stdout + r.stderr).strip()[-600:]}")
    t = subprocess.run(["bash", "tests/run.sh"], cwd=wt, capture_output=True, text=True)
    if t.returncode != 0:
        tail = "\n".join((t.stdout + t.stderr).strip().splitlines()[-20:])
        return refuse(f"tests/run.sh failed in the worktree:\n{tail}")
    both = overlap()   # again: the checkout may have changed while the tests ran
    if both:
        return refuse("dirty in the shared checkout and touched by the change: " + ", ".join(both))
    m = git(checkout, "merge", "--ff-only", branch)
    if m.returncode != 0:
        return refuse(f"fast-forward failed: {m.stderr.strip()}")
    p = git(checkout, "push", "--quiet", "origin", BASE)
    if p.returncode != 0:
        print(f"session land {a.name}: {BASE} moved to {branch} but the push failed: {p.stderr.strip()} — push by hand; "
              "the worktree is kept", file=sys.stderr)
        return 5
    head = git(checkout, "rev-parse", "--short", "HEAD").stdout.strip()
    rm = git(checkout, "worktree", "remove", wt)
    git(checkout, "branch", "-d", branch)
    try:
        os.rmdir(os.path.dirname(wt))
    except OSError:
        pass
    print(f"landed {a.name}: {repo} {BASE} at {head}, pushed"
          + ("; worktree removed" if rm.returncode == 0 else f"; worktree not removed: {rm.stderr.strip()}"))
    return 0 if rm.returncode == 0 else 5


def claude_pid():
    """The Claude process this hook runs under: the nearest ancestor whose command is claude (or its node), else the
    hook's parent."""
    pid = os.getppid()
    for _ in range(6):
        try:
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace")
            if re.search(r"(^|/)claude(\s|$)|claude-code|@anthropic-ai/claude", cmd):
                return pid
            pid = int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return os.getppid()


UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def transcript_of(sid):
    hits = glob.glob(os.path.join(TRANSCRIPTS, "*", f"{sid}.jsonl"))
    return max(hits, key=os.path.getmtime) if hits else None


def title_of(transcript):
    """The session's name as /rename last set it (Claude Code's `custom-title` line), or None."""
    name = None
    try:
        for line in open(transcript, encoding="utf-8", errors="replace"):
            if '"custom-title"' in line:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get("type") == "custom-title" and isinstance(d.get("customTitle"), str):
                    name = " ".join(d["customTitle"].split()) or name      # one line: it becomes a note's property
    except (OSError, TypeError):
        pass
    return name


def current():
    """{id, name, transcript} for the session this command runs in, or None."""
    pid, sid, row, last = claude_pid(), None, None, None
    try:                                             # the registry is append-only: the last start this process wrote is
        for line in open(registry() or "", encoding="utf-8"):   # its session (a /resume inside it, a reused process id)
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("event") == "start" and e.get("pid") == pid:
                last = e.get("id")
    except OSError:
        pass
    for r in sessions(unstarted=True):
        if last and r.get("id") == last and r.get("pid") == pid and not r.get("ended"):
            sid, row = r["id"], r
    if not sid:
        try:
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
            for i, x in enumerate(cmd[:-1]):
                if x in (b"--resume", b"-r", b"--session-id") and UUID.fullmatch(cmd[i + 1].decode(errors="replace")):
                    sid = cmd[i + 1].decode()
        except OSError:
            pass
    if not sid:
        sid = next((v for v in (os.environ.get(k) or "" for k in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID")) if UUID.fullmatch(v)), None)
    if not sid:
        return None
    tr = transcript_of(sid)
    if not row:
        row = next((r for r in sessions(unstarted=True) if r.get("id") == sid), {})
    return {"id": sid, "name": title_of(tr) or row.get("name"), "transcript": tr}


def cmd_here(a):
    c = current()
    if not c:
        print("session here: not inside a Claude session", file=sys.stderr)
        return 3
    print(json.dumps(c, ensure_ascii=False) if a.json else f"{c['id']}\t{c['name'] or '-'}")
    return 0


def close_row(r):
    """End one live session: TERM to its Claude process, then its pane, and an end line "closed by desk". → the steps."""
    steps = [f"TERM {r['pid']}"] + ([f"zellij action close-pane --pane-id {r['pane']}"] if r.get("pane") else [])
    try:
        os.kill(int(r["pid"]), 15)
    except (OSError, ValueError) as e:
        print(f"session close: {e}", file=sys.stderr)
    if r.get("pane") and os.environ.get("ZELLIJ_SESSION_NAME"):
        subprocess.run(["zellij", "action", "close-pane", "--pane-id", str(r["pane"])], capture_output=True, text=True)
    append({"event": "end", "id": r["id"], "at": now(), "reason": "closed by desk"})
    return steps


def cmd_close(a):
    r = live(a.name)
    if not r:
        print(f"session close: no live session named {a.name}", file=sys.stderr)
        return 3
    steps = [f"TERM {r['pid']}"] + ([f"zellij action close-pane --pane-id {r['pane']}"] if r.get("pane") else [])
    if a.dry_run:
        print("\n".join(steps))
        return 0
    why = test_refusal()
    if why:
        print(f"session close: {why}", file=sys.stderr)
        return 2
    print(f"closed {a.name}: " + "; ".join(close_row(r)))
    return 0


# ── reap: which live sessions are done; on --apply the ready ones landed and the finished ones closed ──────────

SIGN_OFF = "— ela out 🦀"
IDLE_MIN = 10                                    # minutes a session sits idle before reap closes it
ASKS_TASK = re.compile(r"what (would you like|should i|do you want|can i)|how can i help|what('s| is) the task|no (brief|task)"
                       r'|需要我(做|帮)|我该做什么|要我做什么|有什么(任务|需要)', re.I)   # the same ask in Chinese
READY = re.compile(r'ready to land|ready for (the )?land|session land \S+|可以 ?land|待 ?land', re.I)


def _when_any(ts):
    try:
        t = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return t if t.tzinfo else t.astimezone()
    except ValueError:
        return None


def _prompt_text(content):
    """A user line's typed words, or None for a tool result, a command echo or an insert of the harness."""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        text = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    else:
        return None
    text = text.strip()
    if not text or text.startswith(("<command-", "<local-command", "<system-reminder", "<task-notification")):
        return None
    return text


def read_turns(transcript):
    """What reap needs of a transcript: the typed prompts, the assistant's text replies (text, time), whether the
    last turn ended (the last assistant message stopped at end_turn and nothing came after it), the last line's time.
    None when it cannot be read."""
    prompts, replies, ended, last = 0, [], False, None
    try:
        f = open(transcript, encoding="utf-8", errors="replace")
    except (OSError, TypeError):
        return None
    with f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict) or d.get("isSidechain") is True:
                continue
            ts = _when_any(d["timestamp"]) if isinstance(d.get("timestamp"), str) else None
            msg = d.get("message") if isinstance(d.get("message"), dict) else {}
            if d.get("type") == "user" and not d.get("isMeta"):
                last = ts or last
                if _prompt_text(msg.get("content")) is not None:
                    prompts += 1
                ended = False                              # a prompt or a tool result: the turn goes on
            elif d.get("type") == "assistant":
                last = ts or last
                content = msg.get("content") if isinstance(msg.get("content"), list) else []
                text = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text").strip()
                if text:
                    replies.append((text, ts))
                ended = msg.get("stop_reason") == "end_turn"
    return {"prompts": prompts, "replies": replies, "ended": ended, "last": last}


def question_of(text):
    """The reply's last line that asks something, or None."""
    for line in reversed([x.strip() for x in (text or "").splitlines() if x.strip()]):
        if line.rstrip("*_` ").endswith(("?", "？")):
            return line
    return None


def worker_of(cwd):
    """(name, repo) when cwd is a worker's worktree <work>/<N>/<repo> of ela or ela-runner, else None."""
    w = work_root()
    if not w or not cwd:
        return None
    rel = os.path.relpath(os.path.realpath(cwd), os.path.realpath(w))
    parts = rel.split(os.sep)
    if len(parts) >= 2 and parts[0] not in (".", "..") and parts[1] in GUARDED and NAME.fullmatch(parts[0]):
        return parts[0], parts[1]
    return None


def worktree_state(n, repo):
    """(state, reason) of a worker's branch evan/<n> and its worktree, from git: dirty, to-land, landed; None when
    the branch never carried a commit of its own (a worker that has not committed yet has landed nothing)."""
    wt, checkout, branch = os.path.join(work_root(), n, repo), os.path.join(site().get("projects") or "", repo), f"evan/{n}"
    if not os.path.isdir(wt):
        return "landed", f"the worktree {n}/{repo} is gone"
    d = sorted(dirty(wt))
    if d:
        return "dirty", "uncommitted: " + ", ".join(d[:4]) + (f" and {len(d) - 4} more" if len(d) > 4 else "")
    ahead = git(checkout, "rev-list", "--count", f"{BASE}..{branch}")
    if ahead.returncode != 0:
        return "landed", f"no branch {branch}"
    if ahead.stdout.strip() != "0":
        return "to-land", f"{branch} has {ahead.stdout.strip()} commit(s) beyond {BASE}, the worktree clean"
    log = git(checkout, "reflog", "show", "--format=%gs", branch).stdout.splitlines()
    if any(x.startswith(("commit", "rebase", "cherry-pick", "merge", "reset")) for x in log):
        return "landed", f"{branch} has nothing beyond {BASE} and the worktree is clean"
    return None, f"{branch} has no commit yet"


def is_desk(r, mine):
    """The sessions reap never closes: the one it runs in, and the desk (named ela or desk, or started in the projects
    root)."""
    projects = site().get("projects")
    return (r["id"] in mine or r.get("name") in ("ela", DESK)
            or bool(projects and r.get("cwd") and os.path.realpath(r["cwd"]) == os.path.realpath(projects)))


def judge(r, now_, mine):
    """One live session's state from first-hand facts: its worktree and branch in git, then its transcript."""
    tr = transcript_of(r["id"])
    t = read_turns(tr) if tr else None
    text, when = (t["replies"][-1] if t and t["replies"] else ("", None))
    idle_at = (t or {}).get("last") or _when_any(r.get("started") or "")
    row = {"id": r["id"], "name": r.get("name") or "-", "cwd": shown_path(r.get("cwd") or "", *roots()),
           "age": round((now_ - when).total_seconds() / 60) if when else None,
           "idle": round((now_ - idle_at).total_seconds() / 60) if idle_at else None,
           "question": None, "ready": bool(READY.search(text)), "worker": None, "branch": None, "action": None}

    def done(state, reason):
        row.update(state=state, reason=reason)
        return row
    if is_desk(r, mine):
        return done("desk", "the desk: never reaped")
    if r.get("job"):
        return done("runner", f"a runner job ({r['job']}): it ends itself")
    w = worker_of(r.get("cwd"))
    state, why = worktree_state(*w) if w else (None, None)
    if w:
        row["worker"], row["branch"] = w[0], state
        if state in ("dirty", "to-land"):
            return done(state, why)
    if t is None:
        return done("busy", "no transcript yet")
    if t["prompts"] == 0 or (len(t["replies"]) == 1 and t["ended"] and ASKS_TASK.search(text)):
        return done("no-brief", "no first message" if t["prompts"] == 0 else "the only reply asks for a task")
    if state == "landed":
        return done("landed", why)
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if t["ended"] and lines and lines[-1] == SIGN_OFF:
        return done("signed-off", "the last reply signs off" + (f"; {why}" if w else ""))
    q = question_of(text) if t["ended"] else None
    if q:
        row["question"] = one_line(clean(q), 160)
        return done("waiting-owner", row["question"])
    if not t["ended"]:
        return done("busy", "a turn under way")
    return done("busy", "the last reply asks nothing and does not sign off" + (f"; {why}" if w else ""))


def reap_file():
    root = runtime_root()
    return os.path.join(root, "sessions", "reap.json") if root else None


def cmd_reap(a):
    if a.last:
        try:
            got = json.load(open(reap_file() or "", encoding="utf-8"))
        except (OSError, ValueError):
            return 3
        for line in got.get("kept") or []:
            print(line)
        return 0
    why = test_refusal() if a.apply else None
    if why:
        print(f"session reap: {why}", file=sys.stderr)
        return 2
    now_, c = datetime.datetime.now().astimezone(), current()
    live_rows = [r for r in sessions() if not r["ended"] and r.get("pid") and alive(r["pid"])]
    by_id = {r["id"]: r for r in live_rows}
    rows = [judge(r, now_, {c["id"]} if c else set()) for r in live_rows]
    if a.apply:                                  # a session still at work in the last IDLE_MIN minutes is left alone
        for row in rows:
            if row["state"] == "to-land" and row["ready"] and (row["idle"] or 0) >= IDLE_MIN:
                p = subprocess.run([sys.executable, os.path.realpath(__file__), "land", row["worker"]], capture_output=True, text=True)
                if p.returncode == 0:
                    row.update(state="landed", branch="landed", action="landed",
                               reason=(p.stdout.strip().splitlines() or ["landed"])[-1])
                else:
                    err = (p.stderr or p.stdout).strip().replace(f"session land {row['worker']}: refused — ", "")
                    row["action"] = "land refused: " + one_line(err, 200)
                    continue
            closable = row["state"] == "landed" or (row["state"] == "signed-off" and row["branch"] in (None, "landed"))
            if not closable:
                continue
            if row["name"] == "-":                     # started by hand, not by `session open`: closes on the owner's word
                row["action"] = "started by hand: closes on the owner's word"
                continue
            if (row["idle"] or 0) >= IDLE_MIN:
                close_row(by_id[row["id"]])
                row["action"] = "landed, closed" if row["action"] == "landed" else "closed"
            else:
                row["action"] = f"idle {row['idle']}m, under {IDLE_MIN}m: kept"
        kept = [f"{r['name']}: {r['state']} — {r['action'] or r['reason']}" for r in rows
                if r["state"] not in ("desk", "runner") and "closed" not in (r["action"] or "")]
        path = reap_file()
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"at": now(), "rows": rows, "kept": kept}, f, ensure_ascii=False, indent=1)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    if not rows:
        print("no live session")
    for r in rows:
        age = f"{r['age']}m" if r["age"] is not None else "-"
        print(f"{r['name'][:24]:<24} {r['state']:<13} {age:>6}  {r['reason']}" + (f"  [{r['action']}]" if r["action"] else ""))
    return 0


def trusted(cwd):
    """Whether Claude Code's trust prompt was accepted for cwd or a folder above it (~/.claude.json); True when unreadable,
    so the hint is never a guess."""
    try:
        projects = json.load(open(os.path.expanduser("~/.claude.json"))).get("projects") or {}
    except (OSError, ValueError):
        return True
    d = cwd.rstrip("/")
    while d:
        if (projects.get(d) or {}).get("hasTrustDialogAccepted"):
            return True
        d = os.path.dirname(d) if d != "/" else ""
    return False


# ── the registry ───────────────────────────────────────────────────────────────────────────────

def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def append(row):
    path = registry()
    if not path:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def hook_input():
    try:
        d = json.loads(sys.stdin.read() or "{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def first_prompt(transcript):
    """The first plain-string user prompt of a transcript, or None."""
    try:
        for line in open(transcript, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            msg = d.get("message") if isinstance(d.get("message"), dict) else {}
            if d.get("type") == "user" and isinstance(msg.get("content"), str):
                return msg["content"]
    except OSError:
        pass
    return None


def cmd_hook_start(a):
    d = hook_input()
    if d.get("source") not in ("startup", "resume") or not d.get("session_id"):
        return 0                                     # clear and compact are the same session
    append({"event": "start", "id": d["session_id"], "at": now(),
            "name": os.environ.get("ELA_SESSION_NAME") or None,
            "cwd": d.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd(),
            "purpose": os.environ.get("ELA_SESSION_PURPOSE") or None,
            "job": os.environ.get("ELA_RUNNER_JOB") or None,
            "pid": claude_pid(), "pane": os.environ.get("ZELLIJ_PANE_ID") or None})
    return 0


def cmd_hook_end(a):
    d = hook_input()
    if not d.get("session_id"):
        return 0
    prompt = first_prompt(d.get("transcript_path") or "")
    try:                                     # the end line is written whatever the transcript holds
        u = usage_of(d["transcript_path"]) if isinstance(d.get("transcript_path"), str) else None
    except Exception:
        u = None
    append({"event": "end", "id": d["session_id"], "at": now(), "reason": d.get("reason"),
            "purpose": one_line80(clean(prompt)) if prompt else None,          # redacted whole, then cut
            "usage": {k: u.get(k) for k in USAGE_KEPT} if u else None})
    return 0


def sessions(unstarted=False):
    """One record per session id: the first start, the last end (cleared by a later resume), the purpose. A session
    whose start line is missing (started before the registry, or by a hook that failed) only with `unstarted`."""
    path = registry()
    rows = {}
    try:
        lines = open(path, encoding="utf-8").readlines() if path else []
    except OSError:
        lines = []
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        r = rows.setdefault(e.get("id"), {"id": e.get("id"), "name": None, "cwd": None, "started": None, "ended": None, "purpose": None,
                                          "pid": None, "pane": None, "job": None, "usage": None})
        if e.get("event") == "start":
            r["started"] = r["started"] or e.get("at")
            r["ended"] = None
            r["pid"], r["pane"] = e.get("pid") or r["pid"], e.get("pane") or r["pane"]   # a resume is a new process
            r["name"] = r["name"] or e.get("name")
            r["cwd"] = r["cwd"] or e.get("cwd")
            r["job"] = r["job"] or e.get("job")
        elif e.get("event") == "end":
            r["ended"] = e.get("at")
            r["usage"] = e.get("usage") or r["usage"]      # each end sums the whole transcript: the last one holds
        r["purpose"] = r["purpose"] or e.get("purpose")
    return sorted((r for r in rows.values() if r["started"] or (unstarted and r["ended"])),
                  key=lambda r: r["started"] or r["ended"], reverse=True)


def cmd_list(a):
    projects, code = roots()
    rows = sessions()[:a.limit]
    if a.json:
        print(json.dumps([dict(r, cwd=shown_path(r["cwd"] or "", projects, code)) for r in rows], ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("no session recorded yet", file=sys.stderr)
        return 3
    for r in rows:
        ended = r["ended"][5:16].replace("T", " ") if r["ended"] else "open"
        print(f"{(r['name'] or '-'):<14} {r['started'][5:16].replace('T', ' ')} → {ended:<11} "
              f"{shown_path(r['cwd'] or '', projects, code):<34} {clean(r['purpose'] or '')}")
    return 0


def since_of(text):
    """`7d`, `48h` or `YYYY-MM-DD` → an aware datetime, or None when the text is none of them."""
    m = re.fullmatch(r"(\d+)([dh])", text or "")
    if m:
        n = int(m.group(1))
        return datetime.datetime.now().astimezone() - datetime.timedelta(days=n if m.group(2) == "d" else 0,
                                                                          hours=n if m.group(2) == "h" else 0)
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%d").astimezone()
    except (TypeError, ValueError):
        return None


def kind_of(name, cwd):
    """What a session was, for grouping: the name the runner or `session open` gave it; else a guest session, a
    runner pass, or an interactive one, from where it ran."""
    c = (cwd or "").replace("\\", "/")
    if "/.ela-guest" in c:
        return "guest"
    if "/runner/sessions/" in c:                      # <runtime>/runner/sessions/<stamp>: an unattended runner pass
        return name or "runner"
    return "worker" if name else "interactive"


def _when(ts):
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
    except (AttributeError, ValueError):
        return None


def usage_rows(since):
    """Every session whose last message is inside the window: from its transcript while Claude Code still keeps it,
    else from the usage its end line stored (transcripts are cleaned up after a month; the registry is not). A session
    continued in another (a `continued-in` line) is dropped when its successor is counted: the successor's transcript
    carries the earlier messages and its cost total includes them."""
    known = {r["id"]: r for r in sessions(unstarted=True)}
    rows, seen_ids, cut = {}, set(), since.timestamp()
    for path in glob.glob(os.path.join(TRANSCRIPTS, "*", "*.jsonl")):
        sid = os.path.basename(path)[:-len(".jsonl")]
        seen_ids.add(sid)                                   # on disk: its stored copy never stands in
        try:
            if os.path.getmtime(path) < cut:
                continue
            u = usage_of(path)
        except Exception:
            continue
        if not u or not u["turns"] or not _when(u["last"]) or _when(u["last"]) < since:
            continue
        r = known.get(sid) or {}
        purpose = r.get("purpose") or one_line80(clean(first_prompt(path) or "")) or None
        rows[sid] = dict(u, id=sid, name=r.get("name"), job=r.get("job"), purpose=purpose,
                         kind=kind_of(r.get("name"), u["cwd"] or r.get("cwd")))
    for sid, r in known.items():
        u = r.get("usage")
        at = _when((u or {}).get("last") or r.get("ended"))
        if sid in seen_ids or not isinstance(u, dict) or not at or at < since:
            continue
        rows[sid] = dict(u, id=sid, name=r.get("name"), job=r.get("job"), purpose=r.get("purpose"), cwd=r.get("cwd"),
                         first=r.get("started"), last=u.get("last") or r.get("ended"), kind=kind_of(r.get("name"), r.get("cwd")))
    for sid in [k for k, v in rows.items() if v.get("continued_in") in rows]:
        if isinstance(rows[rows[sid]["continued_in"]].get("cost_usd"), (int, float)):   # a successor still open has
            del rows[sid]                                                               # no total yet: keep this one
    return sorted(rows.values(), key=lambda r: r.get("last") or "", reverse=True)


def human(n):
    for unit, size in (("G", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= size:
            return f"{n / size:.1f}{unit}"
    return str(int(n))


def cmd_usage(a):
    since = since_of(a.since)
    if not since:
        print("--since takes 7d, 48h or YYYY-MM-DD", file=sys.stderr)
        return 2
    rows = usage_rows(since)
    projects, code = roots()
    key = {"kind": lambda r: r["kind"], "name": lambda r: r.get("name") or "-",
           "day": lambda r: (r.get("last") and _when(r["last"]).strftime("%Y-%m-%d")) or "?",
           "cwd": lambda r: shown_path(r.get("cwd") or "", projects, code), "model": None}[a.by]

    def parts(r):
        """(group, cost, tokens, turns, tools, skills) for each group a row falls in: one, or with --by model one per
        model (the cost from Claude Code's per-model total, the tokens from the messages; turns and tools stay whole)."""
        if a.by != "model":
            return [(key(r), r.get("cost_usd"), r.get("tokens") or {}, r.get("turns") or 0, r.get("tools") or {}, r.get("skills") or {})]
        bm, cm = r.get("by_model") or {}, r.get("cost_by_model") or {}
        return [(m, cm.get(m), bm.get(m) or {}, 0, {}, {}) for m in sorted(set(bm) | set(cm))]

    groups = {}
    for r in rows:
        for name, cost, toks, turns, tools, skills in parts(r):
            g = groups.setdefault(name, {"sessions": 0, "priced": 0, "cost_usd": 0.0, "turns": 0,
                                         "tokens": dict.fromkeys(TOKENS, 0), "tools": {}, "skills": {}})
            g["sessions"] += 1
            g["turns"] += turns
            if isinstance(cost, (int, float)):
                g["priced"] += 1
                g["cost_usd"] += cost
            for k in TOKENS:
                g["tokens"][k] += toks.get(k) or 0
            for f, src in (("tools", tools), ("skills", skills)):
                for n, c in src.items():
                    g[f][n] = g[f].get(n, 0) + c
    # what ela costs to run (the runner's passes, guest sessions) apart from the owner's own sessions, building included
    operating = lambda r: r["kind"] == "guest" or r["kind"].startswith("runner")
    split = {"operating": round(sum(r.get("cost_usd") or 0 for r in rows if operating(r)), 2),
             "own": round(sum(r.get("cost_usd") or 0 for r in rows if not operating(r)), 2)}
    if a.json:
        print(json.dumps({"since": since.isoformat(timespec="seconds"), "by": a.by, "groups": groups, "split": split,
                          "sessions": [{k: (clean(v) if k == "purpose" and v else shown_path(v, projects, code) if k == "cwd" and v else v)
                                        for k, v in r.items()}
                                       for r in rows]}, ensure_ascii=False, indent=1))
        return 0
    if not rows:
        print(f"no session since {since:%Y-%m-%d %H:%M}", file=sys.stderr)
        return 3
    cost = sum(r.get("cost_usd") or 0 for r in rows)
    priced = sum(1 for r in rows if isinstance(r.get("cost_usd"), (int, float)))
    tok = {k: sum((r.get("tokens") or {}).get(k) or 0 for r in rows) for k in TOKENS}
    print(f"since {since:%Y-%m-%d %H:%M}: {len(rows)} sessions · ${cost:,.2f} where Claude Code recorded a cost "
          f"({priced} of {len(rows)}) · cache read {human(tok['cache_read'])} · cache write {human(tok['cache_write'])}"
          f" · input {human(tok['input'])} · output {human(tok['output'])}")
    print(f"running ela (runner passes, guest sessions) ${split['operating']:,.2f} · the owner's own sessions "
          f"${split['own']:,.2f}. Costs are Claude Code's API-priced figures, not an invoice; a session still open "
          "shows the cost of its last exit or none, and counts whole on the day of its last message.")
    print(f"\n{'by ' + a.by:<26} {'sessions':>8} {'cost $':>9} {'cache rd':>9} {'cache wr':>9} {'output':>8} {'turns':>6}  top tools")
    for name, g in sorted(groups.items(), key=lambda kv: (-kv[1]["cost_usd"], -kv[1]["tokens"]["cache_read"])):
        top = ", ".join(f"{n} {c}" for n, c in sorted(g["tools"].items(), key=lambda kv: -kv[1])[:4])
        print(f"{clean(name)[:26]:<26} {g['sessions']:>8} {g['cost_usd']:>9,.2f} {human(g['tokens']['cache_read']):>9} "
              f"{human(g['tokens']['cache_write']):>9} {human(g['tokens']['output']):>8} {g['turns']:>6}  {top}")
    skills = {}
    for g in groups.values():
        for n, c in g["skills"].items():
            skills[n] = skills.get(n, 0) + c
    if skills:
        print("\nskills loaded: " + ", ".join(f"{n} {c}" for n, c in sorted(skills.items(), key=lambda kv: -kv[1])[:12]))
    print(f"\nthe costliest {min(a.top, len(rows))}:")
    for r in sorted(rows, key=lambda r: (-(r.get("cost_usd") or 0), -(r.get("tokens") or {}).get("cache_read", 0)))[:a.top]:
        c = f"${r['cost_usd']:,.2f}" if isinstance(r.get("cost_usd"), (int, float)) else "$?"
        when = _when(r.get("last")) if r.get("last") else None
        print(f"  {when.strftime('%m-%d %H:%M') if when else '?':<11} {c:>8}  {r['kind'][:16]:<16} {r.get('turns') or 0:>4} turns  "
              f"{one_line(clean(r.get('purpose') or ''), 90)}")
    return 0


def main():
    ap = argparse.ArgumentParser(prog="sessions", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("open", help="a Claude session at a target, in its own zellij tab or pane")
    o.add_argument("target", help="ela|runner|elak|helm|reports|published, code/<ref>, or a directory")
    o.add_argument("brief", nargs="?", default="")
    o.add_argument("--name")
    o.add_argument("--pane", action="store_true", help="a pane beside this one (a topic session beside the desk)")
    o.add_argument("--tab", action="store_true", help="a tab of its own instead of a stacked pane in the workers tab")
    o.add_argument("--brief", dest="brief_file", metavar="FILE", help="a brief file: the first message points to it")
    o.add_argument("--permission-mode")
    o.add_argument("--in-place", action="store_true", help="ela or ela-runner: the shared checkout itself, not a worktree")
    o.add_argument("--no-brief", action="store_true", help="ela or ela-runner: open with no first message, on purpose")
    o.add_argument("--dry-run", action="store_true", help="print the layout and the command; open nothing")
    g = sub.add_parser("land", help="rebase evan/N on main, test, fast-forward main, push, remove the worktree")
    g.add_argument("name")
    g.add_argument("--repo", choices=("ela", "runner", "ela-runner"))
    g.add_argument("--dry-run", action="store_true", help="the read-only checks and the steps; nothing moves")
    r = sub.add_parser("reap", help="each live session's state (landed, to-land, dirty, no-brief, signed-off, busy, waiting-owner)")
    r.add_argument("--apply", action="store_true", help="land the ready to-land sessions, close the finished idle ones")
    r.add_argument("--last", action="store_true", help="the sessions the last --apply left open, one line each")
    r.add_argument("--json", action="store_true")
    c = sub.add_parser("close", help="end a live session by name: its Claude process, then its pane")
    c.add_argument("name")
    c.add_argument("--dry-run", action="store_true")
    l = sub.add_parser("list", help="the sessions the hooks recorded, newest first")
    l.add_argument("--limit", type=int, default=30)
    l.add_argument("--json", action="store_true")
    u = sub.add_parser("usage", help="what the sessions cost, grouped: tokens, cost, tools and skills from the transcripts")
    u.add_argument("--since", default="7d", help="7d, 48h or YYYY-MM-DD (default 7d)")
    u.add_argument("--by", choices=("kind", "name", "day", "cwd", "model"), default="kind")
    u.add_argument("--top", type=int, default=10, help="how many of the costliest sessions to list")
    u.add_argument("--json", action="store_true")
    h = sub.add_parser("here", help="this session: its id, its name (/rename) and its transcript")
    h.add_argument("--json", action="store_true")
    sub.add_parser("hook-start", help="SessionStart: append a start line (hook JSON on stdin)")
    sub.add_parser("hook-end", help="SessionEnd: append an end line (hook JSON on stdin)")
    f = sub.add_parser("find", help="sessions whose first prompt or final answer carries every word")
    f.add_argument("words", nargs="+")
    f.add_argument("--since", help="YYYY-MM-DD: only sessions started on or after this date")
    f.add_argument("--limit", type=int, default=20)
    f.add_argument("--json", action="store_true")
    a, extra = ap.parse_known_args()
    if a.cmd == "open" and extra and not a.brief and not any(x.startswith("-") for x in extra):
        a.brief = " ".join(extra)                    # the brief after an option: open runner --pane "brief"
    elif extra:
        ap.error("unrecognized arguments: " + " ".join(extra))
    if a.cmd == "find" and a.since and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.since):
        ap.error("--since takes YYYY-MM-DD")
    sys.exit({"find": cmd_find, "open": cmd_open, "close": cmd_close, "land": cmd_land, "reap": cmd_reap, "list": cmd_list, "here": cmd_here, "usage": cmd_usage,
              "hook-start": cmd_hook_start, "hook-end": cmd_hook_end}[a.cmd](a))


if __name__ == "__main__":
    main()
