#!/usr/bin/env bash
# ela SessionStart hook, run as several commands (hooks.json), each printing one part of the session's context:
#   session-start.sh            context/evan.md · pointers to the rest of the site file · the knowledge root · which
#                               mapped repo/area the cwd is in · the desk's pending line
#   session-start.sh prefs I/K  part I of K of the working preferences, the first section of
#                               ~/.claude/ela/working-with-evan.md, split at top-level bullets; K parts together are
#                               the section whole
# Claude Code injects a hook command's output only up to CAP characters (measured on 2.1.332, 2026-11-25: 10,000
# injected, 10,001 saved to a file with a 2KB preview; characters, not bytes; each command has its own cap). Past it
# the session sees the first 2KB, which is how the preferences stopped reaching every session once the single output
# grew to ~20,700 characters. Hence one command per part, and each output measures itself: from WARN up a warning
# goes on its first line, inside the preview, naming the overrun.
# The one write is a start line in the session registry (<runtime>/sessions.jsonl, sessions.py hook-start), made by the
# default part only; no repo, no live system, never a commit.
set -u
ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
SITE="$HOME/.claude/ela/site.json"
PREFS="$HOME/.claude/ela/working-with-evan.md"
CWD="${CLAUDE_PROJECT_DIR:-$PWD}"
CAP=10000
WARN=9000
MODE="${1:-context}"

# Print stdin; from WARN characters on, a warning comes first so it survives a persisted output's 2KB preview.
emit() {
  python3 -c '
import sys
cap, warn, what = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
t = sys.stdin.read().rstrip()
if not t:
    sys.exit(0)
n = len(t)
if n >= warn:
    state = "OVER the cap: Claude Code shows this session only its first 2KB" if n > cap else "near the cap"
    head = (f"ela: WARNING this SessionStart output ({what}) is {n:,} characters, {state} of {cap:,} per hook command; "
            f"shorten its source or split it into another part in hooks/hooks.json. Until then Read the source in full.")
    t = head + "\n\n" + t
sys.stdout.write(t + "\n")
' "$CAP" "$WARN" "$1"
}

if [ "$MODE" = "prefs" ]; then
  [ "${ELA_GUEST:-}" = "1" ] && exit 0          # the owner's preferences are his, not a guest's
  [ -f "$PREFS" ] || exit 0
  python3 - "$PREFS" "${2:-1/1}" "$((WARN - 500))" <<'PY' | emit "working preferences part ${2:-1/1}"
import re, sys
path, part, budget = sys.argv[1], sys.argv[2], int(sys.argv[3])
i, k = (int(x) for x in part.split("/"))
lines = open(path, encoding="utf-8").read().splitlines(keepends=True)
# The first `## ` section is the preferences; later sections are pointed at by the default part, not injected.
ends = [n for n, l in enumerate(lines) if l.startswith("## ")]
stop = ends[1] if len(ends) > 1 else len(lines)
section = lines[:stop]
# Blocks: a top-level bullet with its continuation lines; a block over the budget is split line by line.
blocks, cur = [], []
for n, l in enumerate(section):
    if cur and (l.startswith("- ") or l.startswith("#")):
        blocks.append(cur); cur = []
    cur.append((n + 1, l))
if cur:
    blocks.append(cur)
units = []
for b in blocks:
    if sum(len(l) for _, l in b) <= budget:
        units.append(b)
    else:
        units.extend([x] for x in b)
parts, cur, size = [], [], 0
for u in units:
    s = sum(len(l) for _, l in u)
    if cur and size + s > budget:
        parts.append(cur); cur, size = [], 0
    cur.extend(u); size += s
if cur:
    parts.append(cur)
home = "~/.claude/ela/working-with-evan.md"
if len(parts) > k and i == k:
    total = sum(len(l) for l in section)
    print(f"ela: WARNING the working preferences ({total:,} characters) need {len(parts)} parts and hooks/hooks.json "
          f"injects {k}; lines {parts[k][0][0]}-{parts[-1][-1][0]} of {home} did not reach this session. "
          f"Read them now, before replying; then add a `prefs` part to hooks.json.\n")
if i > len(parts):
    sys.exit(0)
p = parts[i - 1]
print(f"(ela: {home}, working preferences part {i} of {min(k, len(parts))}, lines {p[0][0]}-{p[-1][0]})")
sys.stdout.write("".join(l for _, l in p))
PY
  exit 0
fi

[ -t 0 ] || printf '%s' "$(cat)" | python3 "$ROOT/skills/sessions/sessions.py" hook-start >/dev/null 2>&1 || true

# A guest session (ela-runner's answer to a colleague on the owner's whitelist, ELA_GUEST=1) gets no owner context:
# who he is, his preferences and the knowledge root's location are his, not the asker's.
if [ "${ELA_GUEST:-}" = "1" ]; then
  echo "ela guest session: answering a colleague of the owner, read-only, from ela's product verbs, the code and the published knowledge."
  exit 0
fi

{
cat "$ROOT/context/evan.md" 2>/dev/null

# The site file's later sections (his day, …) are pointed at, not injected: a session reads them when they matter.
[ -f "$PREFS" ] && python3 - "$PREFS" <<'PY' 2>/dev/null
import sys
lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
heads = [(n + 1, l[3:].strip()) for n, l in enumerate(lines) if l.startswith("## ")]
if heads[1:]:
    print("\n## Read when it matters (not injected)")
for n, title in heads[1:]:
    print(f"- \"{title}\": `~/.claude/ela/working-with-evan.md` from line {n}.")
PY

[ -f "$SITE" ] || { echo; echo "ela: site file missing — run /ela:setup"; exit 0; }

python3 - "$SITE" "$CWD" <<'PY' 2>/dev/null || true
import json, os, re, sys
site, cwd = sys.argv[1], sys.argv[2]
try:
    s = json.load(open(site))
except Exception:
    sys.exit(0)
records = s.get("elak") or s.get("records", "")   # `records` accepted until /ela:setup renames the key
print()
print(f"## Knowledge base: {records}")
if s.get("site") == "remote":
    print("This is a REMOTE site: <records> is a read-only published subset (elak-published). Never write a plan, ledger entry or decision "
          "draft under it — hand drafts to Helm's store or Jira. Code checkouts, GitLab, Confluence, Jenkins and GM are not reachable here; "
          "say 'office only' instead of retrying. (elak `blueprint/decisions/2026-10-22-the-remote-host-retires-everything-runs-on-the-owners-box.md`)")
# The blueprint is a Read away; a hook injects where things are, not what they say. Injecting the
# status and the decision list here fed every session the day's narrative and made it context, so it stopped.
# Which checkout is the cwd in? From the survey cache; a hook must not survey (git across every checkout
# takes longer than the hook's timeout) — it says when the cache is stale and lets `ela survey` refresh it.
cache = os.path.expanduser("~/.claude/ela/map/host.json")
stale = False
try:
    import time
    stale = not os.path.isfile(cache) or time.time() - os.path.getmtime(cache) > 86400
    repos = json.load(open(cache)).get("repos", [])
except Exception:
    repos = []
if stale:
    print("Survey cache missing or older than a day — run `ela survey` to refresh it.")
best = None
for r in repos:
    p = r.get("path", "")
    if p and (cwd == p or cwd.startswith(p.rstrip("/") + "/")):
        if best is None or len(p) > len(best["path"]):
            best = r
code_root = s.get("code") or os.path.join(s.get("projects", ""), "code")
work_root = s.get("work") or os.path.join(s.get("projects", ""), ".ela", "work")
if best:
    where = "code/ (read-only — changes go to a work/ worktree)" if best["path"].startswith(code_root + "/") else ("work/ (a task worktree)" if best["path"].startswith(work_root + "/") else "Evan's own")
    print(f"cwd {cwd} is in repo '{best['name']}' — governance {best.get('governance','?')}, branch {best.get('branch','?')}, {where}. Rules are bound to the location: follow that repo's own files.")
elif cwd.startswith(code_root + "/"):
    print(f"cwd {cwd} is under code/ but not a surveyed checkout — run map.py survey.")
else:
    print(f"cwd {cwd} is not inside any surveyed checkout. Only ela's own rules apply here.")
PY

# The desk: an owner session started in the projects root (not a runner job) hears the improvements ela should carry
# out next (ADR 0023), one line from the store, a local read; any failure prints nothing.
if [ -z "${ELA_RUNNER_JOB:-}" ]; then
  PROJ="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("projects") or "")' "$SITE" 2>/dev/null || true)"
  if [ -n "$PROJ" ] && [ "${CWD%/}" = "${PROJ%/}" ]; then
    LINE="$(timeout 5 python3 "$ROOT/skills/improve/improve.py" pending 2>/dev/null || true)"
    [ -n "$LINE" ] && { echo; echo "$LINE"; }
  fi
fi
} | emit "session context"
exit 0
