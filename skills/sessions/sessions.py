#!/usr/bin/env python3
"""ela sessions — find an earlier Claude Code session on this machine by what it was about.

  sessions find <word> [<word>…] [--since YYYY-MM-DD] [--limit 20] [--json]

Reads the local transcripts under ~/.claude/projects/*/*.jsonl; nothing remote, nothing written.
A session matches when every word (case-insensitive) appears in its first prompt or its final answer.
The current session ($CLAUDE_SESSION_ID) and subagent transcripts are skipped.

Printed per hit, newest first: the date · the project directory · the first prompt (140 chars) · the final
answer (240 chars) · the paths the session read (Read tool calls, at most 12, relative to <projects> or <code>).
--json adds the transcript path.

Not printed: tool results of any kind, any other prompt or answer. Every printed string passes publish.redact
(addresses become <ip> / <tailnet>) and any run of 32+ token-shaped characters becomes <token>.

Exit codes: 0 hits · 2 usage · 3 nothing found.
"""
import argparse, glob, json, os, re, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "publish"))
from publish import redact   # one rule for addresses, defined once (publish.py)

SITE = os.path.expanduser("~/.claude/ela/site.json")
TRANSCRIPTS = os.path.expanduser("~/.claude/projects")
TOKEN = re.compile(r"[A-Za-z0-9_-]{32,}")
MAX_PATHS = 12


def roots():
    try:
        s = json.load(open(SITE))
    except Exception:
        return None, None
    projects = s.get("projects")
    code = s.get("code") or (os.path.join(projects, "code") if projects else None)
    return projects, code


def clean(text):
    return TOKEN.sub("<token>", redact(text or ""))


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


def main():
    ap = argparse.ArgumentParser(prog="sessions", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find", help="sessions whose first prompt or final answer carries every word")
    f.add_argument("words", nargs="+")
    f.add_argument("--since", help="YYYY-MM-DD: only sessions started on or after this date")
    f.add_argument("--limit", type=int, default=20)
    f.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.since and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.since):
        ap.error("--since takes YYYY-MM-DD")
    sys.exit(cmd_find(a))


if __name__ == "__main__":
    main()
