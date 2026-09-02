#!/usr/bin/env bash
# ela SessionStart hook. Prints context for the session: context/evan.md · latest blueprint decisions + status ·
# which mapped repo/area the cwd is in. Its one write is the knowledge-base catch-up snapshot (session-stop.sh),
# for sessions that ended without their SessionEnd hook. It never touches the ela repo or any live system.
set -u
ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
SITE="$HOME/.claude/ela/site.json"
CWD="${CLAUDE_PROJECT_DIR:-$PWD}"

cat "$ROOT/context/evan.md" 2>/dev/null

# catch-up: a session that ended without its SessionEnd hook leaves the knowledge base dirty — snapshot it first.
# Only on startup|resume: a clear or compaction mid-task must not commit half-written files (ELA_NO_CATCHUP=1).
[ -n "${ELA_NO_CATCHUP:-}" ] || "$ROOT/hooks/session-stop.sh" 2>/dev/null || true

[ -f "$SITE" ] || { echo; echo "ela: site file missing — run /ela:setup"; exit 0; }

python3 - "$SITE" "$CWD" <<'PY' 2>/dev/null || true
import json, os, re, sys
site, cwd = sys.argv[1], sys.argv[2]
try:
    s = json.load(open(site))
except Exception:
    sys.exit(0)
records = s.get("records", "")
bp = os.path.join(records, "blueprint")
print()
print(f"## Knowledge base: {records}")
status = os.path.join(bp, "status.md")
if os.path.isfile(status):
    lines = [l.strip().lstrip("- ") for l in open(status) if l.strip() and not l.startswith("#")]
    print("Status: " + " · ".join(lines[:6]))
dec = os.path.join(bp, "decisions")
if os.path.isdir(dec):
    files = sorted(f for f in os.listdir(dec) if re.match(r"\d{4}-\d{2}-\d{2}-.*\.md$", f))
    if files:
        print("Recent decisions (blueprint/decisions/): " + ", ".join(f[:-3] for f in files[-6:]))

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
work_root = s.get("work") or os.path.join(s.get("projects", ""), "work")
if best:
    where = "code/ (read-only — changes go to a work/ worktree)" if best["path"].startswith(code_root + "/") else ("work/ (a task worktree)" if best["path"].startswith(work_root + "/") else "Evan's own")
    print(f"cwd {cwd} is in repo '{best['name']}' — governance {best.get('governance','?')}, branch {best.get('branch','?')}, {where}. Rules are bound to the location: follow that repo's own files.")
elif cwd.startswith(code_root + "/"):
    print(f"cwd {cwd} is under code/ but not a surveyed checkout — run map.py survey.")
else:
    print(f"cwd {cwd} is not inside any surveyed checkout. Only ela's own rules apply here.")
PY
exit 0
