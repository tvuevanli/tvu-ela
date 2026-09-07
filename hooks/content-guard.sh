#!/usr/bin/env bash
# ela content guard — a git hook for the repositories other people may read (ela, helm, elak).
#
#   content-guard.sh pre-commit          scans the staged additions
#   content-guard.sh commit-msg <file>   scans the commit message
#
# What it refuses, and why:
#   credentials and addresses   a token, a private key, an IPv4 address, a tailnet or LAN host name,
#                               an ssh user@host — none of these belongs in a shared tree, and a
#                               pushed commit cannot be taken back
#   a person's utterance        a quoted sentence in CJK, "X said/asked/wrote", "in his own words":
#                               a tracked file states the rule and cites the origin (ticket, link,
#                               date + role), never the sentence someone typed
#   session narrative (.md)     "this session", "today we", "we decided", a `source:` line that
#                               cites a conversation: documentation describes what is in force,
#                               not how a conversation arrived at it
#
# Exit 1 blocks with a file:line list. Set ELA_GUARD_SKIP=1 on the command to bypass once, deliberately.
set -u
[ -n "${ELA_GUARD_SKIP:-}" ] && exit 0
mode="${1:-pre-commit}"
python3 - "$mode" "${2:-}" <<'PY'
import re, subprocess, sys
mode, msgfile = sys.argv[1], sys.argv[2]

def octets_ok(m):
    return all(0 <= int(o) <= 255 for o in m.group(0).split("."))
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
VERSION_LINE = re.compile(r"(?i)version|build|image|tag|release|\bv\d")

ANY_FILE = [
    (re.compile(r"xox[abpe]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"afxp_[A-Za-z0-9]{16,}"), "Apifox token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?key|token)\s*[:=]\s*['\"]?[A-Za-z0-9+/=_\-]{12,}"), "credential assignment"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{24,}"), "bearer token"),
    (re.compile(r"\b[a-z0-9-]+\.[a-z0-9-]+\.ts\.net\b"), "tailnet host name"),
    (re.compile(r"\bssh://[^\s'\"]+|\bssh\s+(?:-\S+\s+)*[A-Za-z0-9._-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]+"), "ssh user@host"),
]
UTTERANCE = [
    (re.compile(r"[\"“「『]([^\"”」』\n]{0,80}[一-鿿][^\"”」』\n]{0,80})[\"”」』]"), "a quoted CJK sentence"),
    (re.compile(r"(?i)\b(?:he|she|evan|the owner)\s+(?:said|says|wrote|told (?:me|us)|put it|phrased it)\b"), "a person's words as source"),
    (re.compile(r"(?i)\bin (?:his|her|their|evan's) (?:own )?words\b|原话|他说|她说"), "a person's words as source"),
]
NARRATIVE_MD = [
    (re.compile(r"(?i)\b(?:this|that|the same|the current) session\b"), "session narrative"),
    (re.compile(r"(?i)\b(?:today|yesterday|this morning|this afternoon) (?:we|i|ela|evan)\b"), "session narrative"),
    (re.compile(r"(?i)^\s*source:.*\b(?:(?:design|plan|working|ela|claude) session|conversation|chat with|discussion with)\b"), "a source line that cites a conversation"),
    (re.compile(r"(?i)\b(?:we|i) (?:decided|agreed|realised|realized|found out|went back and forth)\b"), "session narrative"),
]
TEXT_EXT = (".md", ".yaml", ".yml", ".json", ".py", ".sh", ".txt", ".toml", ".ini", ".cfg", ".env.example", ".html", ".js", ".ts")

def cjk_count(s): return len(re.findall(r"[一-鿿]", s))

def scan_line(path, line, is_md):
    hits = []
    for rx, why in ANY_FILE:
        if rx.search(line): hits.append(why)
    m = IPV4.search(line)
    if m and octets_ok(m) and not VERSION_LINE.search(line) and not m.group(0).startswith(("127.", "0.0.0.0", "255.")):
        hits.append("IPv4 address")
    for rx, why in UTTERANCE:
        m = rx.search(line)
        if m:
            if why.startswith("a quoted") and cjk_count(m.group(1)) < 8:
                continue
            hits.append(why)
    if is_md:
        for rx, why in NARRATIVE_MD:
            if rx.search(line): hits.append(why)
    return hits

problems = []
if mode == "commit-msg":
    text = open(msgfile, encoding="utf-8", errors="replace").read()
    for n, line in enumerate(text.splitlines(), 1):
        if line.startswith("#"): continue
        for why in scan_line("commit message", line, True):
            problems.append(f"  commit message:{n}: {why}: {line.strip()[:70]}")
else:
    files = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=AM"], capture_output=True, text=True).stdout.split()
    for f in files:
        if not f.endswith(TEXT_EXT) or f.endswith("hooks/content-guard.sh"): continue   # its own patterns would match
        diff = subprocess.run(["git", "diff", "--cached", "-U0", "--", f], capture_output=True, text=True).stdout
        n = 0
        for raw in diff.splitlines():
            if raw.startswith("@@"):
                m = re.search(r"\+(\d+)", raw); n = int(m.group(1)) - 1 if m else n; continue
            if raw.startswith("+") and not raw.startswith("+++"):
                n += 1
                for why in scan_line(f, raw[1:], f.endswith(".md")):
                    problems.append(f"  {f}:{n}: {why}: {raw[1:].strip()[:70]}")
if problems:
    print("ela content guard: this commit is refused — the tree is read by others.", file=sys.stderr)
    print("\n".join(problems[:40]), file=sys.stderr)
    print("  Fix: state the rule and cite the origin (ticket key, link, date + role); move addresses and\n"
          "  credentials to the site directory. ELA_GUARD_SKIP=1 bypasses once, on purpose.", file=sys.stderr)
    sys.exit(1)
PY
