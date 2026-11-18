#!/usr/bin/env python3
"""ela sessions — open a worker session, list the sessions on this machine, find an earlier one by what it was about.

  sessions open <alias|path> [--name N] [--tab | --pane] [--brief FILE] [--permission-mode M] [--dry-run] ["brief"]
  sessions close <name> [--dry-run]
  sessions list [--limit 30] [--json]
  sessions usage [--since 7d|48h|YYYY-MM-DD] [--by kind|name|day|cwd] [--top 10] [--json]
  sessions find <word> [<word>…] [--since YYYY-MM-DD] [--limit 20] [--json]
  sessions hook-start | hook-end      the plugin's SessionStart / SessionEnd hooks; hook JSON on stdin

open: a Claude session where the target's rules live, by default a stacked pane in the tab named `workers` (made
when missing; one pane expanded, the others title bars), the pane titled with the session's name; --tab opens a tab
of its own, --pane a pane beside the current one (a topic session beside the desk). The target is a site root by
alias (ela, runner, elak, helm, reports, published), `code/<ref>` resolved by map.py where, or a directory.
--brief FILE makes the first message a pointer to that file. The default name is the alias. It refuses a name a
live session holds (started, not ended, its process alive). Outside zellij it refuses. --dry-run prints the layout
and the commands. Focus returns to the tab named `desk` when there is one.

close: ends a live session by name: TERM to its Claude process, then its pane (`zellij action close-pane
--pane-id`), and an end line "closed by desk" in the registry. The desk runs it after the worker's closing line.

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

Not printed: tool results of any kind, any other prompt or answer. Every printed string passes publish.redact
(addresses become <ip> / <tailnet>) and any run of 32+ token-shaped characters becomes <token>.

Exit codes: 0 ok · 2 usage · 3 nothing found / unknown target · 5 zellij failed.
"""
import argparse, datetime, glob, json, os, re, shlex, subprocess, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "publish"))
from publish import redact   # one rule for addresses, defined once (publish.py)

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
    return TOKEN.sub(lambda m: m.group(1) or "<token>", redact(text or ""))


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


def _tokens_of(path, tools, skills):
    """Sum one transcript file's assistant usage, each API message once: Claude Code writes one line per content
    block, every line carrying the whole message's usage under the same message id. → (tokens, models, turns,
    cwd, first timestamp, last timestamp)."""
    seen, tokens, models, cwd, first, last = set(), dict.fromkeys(TOKENS, 0), set(), None, None, None
    for line in open(path, encoding="utf-8", errors="replace"):
        if '"assistant"' not in line and cwd is not None:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        cwd = cwd or d.get("cwd")
        if d.get("type") != "assistant":
            continue
        ts = d.get("timestamp")
        if isinstance(ts, str):
            first, last = first or ts, ts
        msg = d.get("message") if isinstance(d.get("message"), dict) else {}
        for b in msg.get("content") if isinstance(msg.get("content"), list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                name = b.get("name") or "?"
                tools[name] = tools.get(name, 0) + 1
                if name == "Skill":
                    sk = (b.get("input") or {}).get("skill") or "?"
                    skills[sk] = skills.get(sk, 0) + 1
        u, mid = msg.get("usage"), msg.get("id")
        if not isinstance(u, dict) or (mid and mid in seen):
            continue
        seen.add(mid)
        if msg.get("model"):
            models.add(msg["model"])
        tokens["input"] += u.get("input_tokens") or 0
        tokens["output"] += u.get("output_tokens") or 0
        tokens["cache_read"] += u.get("cache_read_input_tokens") or 0
        tokens["cache_write"] += u.get("cache_creation_input_tokens") or 0
    return tokens, models, len(seen), cwd, first, last


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
    """One session's usage: tokens summed over its own transcript and its subagents' (<id>/subagents/*.jsonl),
    the tools and skills it called, its cost when Claude Code recorded one. None when the file cannot be read."""
    tools, skills = {}, {}
    try:
        tokens, models, turns, cwd, first, last = _tokens_of(transcript, tools, skills)
        cs = _cost_state(transcript)
    except OSError:
        return None
    sub = 0
    for p in sorted(glob.glob(os.path.join(transcript[:-len(".jsonl")], "subagents", "*.jsonl"))):
        try:
            t, m, n, _, _, _ = _tokens_of(p, tools, skills)
        except OSError:
            continue
        sub += 1
        models |= m
        turns += n
        for k in TOKENS:
            tokens[k] += t[k]
    cost = cs.get("totalCostUSD") if cs else None
    return {"tokens": tokens, "cost_usd": round(cost, 4) if isinstance(cost, (int, float)) else None,
            "turns": turns, "subagents": sub, "models": sorted(models), "tools": tools, "skills": skills,
            "cwd": cwd, "first": first, "last": last}


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


def cmd_open(a):
    cwd, name = target_dir(a.target)
    if not cwd:
        print(f"session open: {name}", file=sys.stderr)
        return 3
    name = a.name or name
    held = live(name)
    if held and not a.dry_run:
        print(f"session open: {name} is still open (pane {held.get('pane') or '?'}); close it with `ela session close {name}` "
              "or pick another name", file=sys.stderr)
        return 2
    first = " ".join(x for x in ((f"Read {os.path.abspath(a.brief_file)} and follow it." if a.brief_file else ""), a.brief) if x)
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


def cmd_close(a):
    r = live(a.name)
    if not r:
        print(f"session close: no live session named {a.name}", file=sys.stderr)
        return 3
    steps = [f"TERM {r['pid']}"] + ([f"zellij action close-pane --pane-id {r['pane']}"] if r.get("pane") else [])
    if a.dry_run:
        print("\n".join(steps))
        return 0
    try:
        os.kill(int(r["pid"]), 15)
    except (OSError, ValueError) as e:
        print(f"session close: {e}", file=sys.stderr)
    if r.get("pane") and os.environ.get("ZELLIJ_SESSION_NAME"):
        subprocess.run(["zellij", "action", "close-pane", "--pane-id", str(r["pane"])], capture_output=True, text=True)
    append({"event": "end", "id": r["id"], "at": now(), "reason": "closed by desk"})
    print(f"closed {a.name}: " + "; ".join(steps))
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
            msg = d.get("message") if isinstance(d, dict) and isinstance(d.get("message"), dict) else {}
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
    u = usage_of(d["transcript_path"]) if d.get("transcript_path") else None
    append({"event": "end", "id": d["session_id"], "at": now(), "reason": d.get("reason"),
            "purpose": one_line80(prompt) if prompt else None,
            "usage": {k: u[k] for k in ("tokens", "cost_usd", "turns", "subagents", "models", "tools", "skills")} if u else None})
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
    """Every session active since `since`: from its transcript when Claude Code still keeps it, else from the usage
    its end line stored (transcripts are cleaned up after a month; the registry is not)."""
    known = {r["id"]: r for r in sessions(unstarted=True)}
    rows, done, cut = [], set(), since.timestamp()
    for path in glob.glob(os.path.join(TRANSCRIPTS, "*", "*.jsonl")):
        try:
            if os.path.getmtime(path) < cut:
                continue
        except OSError:
            continue
        sid = os.path.basename(path)[:-len(".jsonl")]
        u = usage_of(path)
        if not u or not u["turns"] or not _when(u["last"]) or _when(u["last"]) < since:
            continue
        r = known.get(sid) or {}
        rows.append(dict(u, id=sid, name=r.get("name"), job=r.get("job"),
                         purpose=r.get("purpose") or one_line80(first_prompt(path) or "") or None, kind=kind_of(r.get("name"), u["cwd"] or r.get("cwd"))))
        done.add(sid)
    for sid, r in known.items():
        u, at = r.get("usage"), _when(r.get("ended"))
        if sid in done or not u or not at or at < since:
            continue
        rows.append(dict(u, id=sid, name=r.get("name"), job=r.get("job"), purpose=r.get("purpose"), cwd=r.get("cwd"),
                         first=r.get("started"), last=r.get("ended"), kind=kind_of(r.get("name"), r.get("cwd"))))
    return sorted(rows, key=lambda r: r.get("last") or "", reverse=True)


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
           "cwd": lambda r: shown_path(r.get("cwd") or "", projects, code)}[a.by]
    groups = {}
    for r in rows:
        g = groups.setdefault(key(r), {"sessions": 0, "priced": 0, "cost_usd": 0.0, "turns": 0,
                                       "tokens": dict.fromkeys(TOKENS, 0), "tools": {}, "skills": {}})
        g["sessions"] += 1
        g["turns"] += r.get("turns") or 0
        if isinstance(r.get("cost_usd"), (int, float)):
            g["priced"] += 1
            g["cost_usd"] += r["cost_usd"]
        for k in TOKENS:
            g["tokens"][k] += (r.get("tokens") or {}).get(k) or 0
        for f in ("tools", "skills"):
            for n, c in (r.get(f) or {}).items():
                g[f][n] = g[f].get(n, 0) + c
    if a.json:
        print(json.dumps({"since": since.isoformat(timespec="seconds"), "by": a.by, "groups": groups,
                          "sessions": [{k: (clean(v) if k == "purpose" and v else v) for k, v in r.items()}
                                       for r in rows]}, ensure_ascii=False, indent=1))
        return 0
    if not rows:
        print(f"no session since {since:%Y-%m-%d %H:%M}", file=sys.stderr)
        return 3
    cost = sum(g["cost_usd"] for g in groups.values())
    priced = sum(g["priced"] for g in groups.values())
    tok = {k: sum(g["tokens"][k] for g in groups.values()) for k in TOKENS}
    print(f"since {since:%Y-%m-%d %H:%M}: {len(rows)} sessions · ${cost:,.2f} where Claude Code recorded a cost "
          f"({priced} of {len(rows)}) · cache read {human(tok['cache_read'])} · cache write {human(tok['cache_write'])}"
          f" · input {human(tok['input'])} · output {human(tok['output'])}")
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
    o.add_argument("--dry-run", action="store_true", help="print the layout and the command; open nothing")
    c = sub.add_parser("close", help="end a live session by name: its Claude process, then its pane")
    c.add_argument("name")
    c.add_argument("--dry-run", action="store_true")
    l = sub.add_parser("list", help="the sessions the hooks recorded, newest first")
    l.add_argument("--limit", type=int, default=30)
    l.add_argument("--json", action="store_true")
    u = sub.add_parser("usage", help="what the sessions cost, grouped: tokens, cost, tools and skills from the transcripts")
    u.add_argument("--since", default="7d", help="7d, 48h or YYYY-MM-DD (default 7d)")
    u.add_argument("--by", choices=("kind", "name", "day", "cwd"), default="kind")
    u.add_argument("--top", type=int, default=10, help="how many of the costliest sessions to list")
    u.add_argument("--json", action="store_true")
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
    sys.exit({"find": cmd_find, "open": cmd_open, "close": cmd_close, "list": cmd_list, "usage": cmd_usage,
              "hook-start": cmd_hook_start, "hook-end": cmd_hook_end}[a.cmd](a))


if __name__ == "__main__":
    main()
