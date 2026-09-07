#!/usr/bin/env bash
# ela SessionStart hook. Prints context for the session: context/evan.md · the working preferences · the knowledge root ·
# which mapped repo/area the cwd is in. It writes nothing: no repo, no live system.
set -u
ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
SITE="$HOME/.claude/ela/site.json"
CWD="${CLAUDE_PROJECT_DIR:-$PWD}"

cat "$ROOT/context/evan.md" 2>/dev/null
# working preferences live in the site dir (never committed), beside site.json and .env
cat "$HOME/.claude/ela/working-with-evan.md" 2>/dev/null


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
          "say 'office only' instead of retrying. (decision 2026-09-03-ela-second-site-on-the-remote)")
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
exit 0
