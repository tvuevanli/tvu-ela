#!/usr/bin/env python3
"""ela sessions — open a worker session, list the sessions on this machine, find an earlier one by what it was about.

  sessions open <alias|path> [--name N] [--pane] [--permission-mode M] [--dry-run] ["brief"]
  sessions list [--limit 30] [--json]
  sessions find <word> [<word>…] [--since YYYY-MM-DD] [--limit 20] [--json]
  sessions hook-start | hook-end      the plugin's SessionStart / SessionEnd hooks; hook JSON on stdin

open: a Claude session where the target's rules live, in its own zellij tab (a pane with --pane, for
watching a short worker beside the desk). The target is a site root by alias (ela, runner, elak, helm,
reports, published), `code/<ref>` resolved by map.py where, or a directory. The layout is written under
<runtime>/sessions/ and run with `zellij action new-tab --layout`; a pane goes through `zellij run`. The
default name is the alias. Outside zellij it refuses. --dry-run prints the layout and the command.

list: the registry <runtime>/sessions.jsonl, newest first: name · cwd · started · ended · purpose. The
hooks append to it (a start line on startup or resume, an end line at SessionEnd); nothing else writes it,
and nothing in it is committed anywhere (ADR 0001).

Reads the local transcripts under ~/.claude/projects/*/*.jsonl; nothing remote, nothing written.
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


def cmd_open(a):
    cwd, name = target_dir(a.target)
    if not cwd:
        print(f"session open: {name}", file=sys.stderr)
        return 3
    name = a.name or name
    argv = ["env", f"ELA_SESSION_NAME={name}", f"ELA_SESSION_PURPOSE={one_line80(a.brief)}",
            "claude", "--name", name]
    if a.permission_mode:
        argv += ["--permission-mode", a.permission_mode]
    if a.brief:
        argv.append(a.brief)
    pane = (f"pane command={kdl(argv[0])} cwd={kdl(cwd)} name={kdl(name)} focus=true {{\n"
            f"        args {' '.join(kdl(x) for x in argv[1:])}\n    }}")
    if a.pane:
        layout = f"layout {{\n    {pane}\n}}\n"
    else:   # zellij's default tab: tab bar, the pane, status bar
        layout = ("layout {\n"
                  '    pane size=1 borderless=true { plugin location="zellij:tab-bar"; }\n'
                  f"    {pane}\n"
                  '    pane size=2 borderless=true { plugin location="zellij:status-bar"; }\n'
                  "}\n")
    run = (["zellij", "run", "--name", name, "--cwd", cwd, "--", *argv] if a.pane
           else ["zellij", "action", "new-tab", "--name", name, "--cwd", cwd, "--layout", "<layout>"])
    if a.dry_run:
        print(layout)
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
    run = [path if x == "<layout>" else x for x in run]
    p = subprocess.run(run, capture_output=True, text=True)
    if p.returncode != 0:
        print(f"session open: zellij failed: {p.stderr.strip() or p.returncode}", file=sys.stderr)
        return 5
    print(f"opened {name} in a {'pane' if a.pane else 'tab'} at {shown_path(cwd, *roots())}  (layout {path})")
    if not trusted(cwd):
        print("the folder is new to Claude Code: the session waits in its tab for your trust answer, and is recorded after it")
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
            "purpose": os.environ.get("ELA_SESSION_PURPOSE") or None})
    return 0


def cmd_hook_end(a):
    d = hook_input()
    if not d.get("session_id"):
        return 0
    prompt = first_prompt(d.get("transcript_path") or "")
    append({"event": "end", "id": d["session_id"], "at": now(), "reason": d.get("reason"),
            "purpose": one_line80(prompt) if prompt else None})
    return 0


def sessions():
    """One record per session id: the first start, the last end (cleared by a later resume), the purpose."""
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
        r = rows.setdefault(e.get("id"), {"id": e.get("id"), "name": None, "cwd": None, "started": None, "ended": None, "purpose": None})
        if e.get("event") == "start":
            r["started"] = r["started"] or e.get("at")
            r["ended"] = None
            r["name"] = r["name"] or e.get("name")
            r["cwd"] = r["cwd"] or e.get("cwd")
        elif e.get("event") == "end":
            r["ended"] = e.get("at")
        r["purpose"] = r["purpose"] or e.get("purpose")
    return sorted((r for r in rows.values() if r["started"]), key=lambda r: r["started"], reverse=True)


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


def main():
    ap = argparse.ArgumentParser(prog="sessions", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("open", help="a Claude session at a target, in its own zellij tab or pane")
    o.add_argument("target", help="ela|runner|elak|helm|reports|published, code/<ref>, or a directory")
    o.add_argument("brief", nargs="?", default="")
    o.add_argument("--name")
    o.add_argument("--pane", action="store_true", help="a pane beside this one instead of a tab")
    o.add_argument("--permission-mode")
    o.add_argument("--dry-run", action="store_true", help="print the layout and the command; open nothing")
    l = sub.add_parser("list", help="the sessions the hooks recorded, newest first")
    l.add_argument("--limit", type=int, default=30)
    l.add_argument("--json", action="store_true")
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
    sys.exit({"find": cmd_find, "open": cmd_open, "list": cmd_list,
              "hook-start": cmd_hook_start, "hook-end": cmd_hook_end}[a.cmd](a))


if __name__ == "__main__":
    main()
