#!/usr/bin/env bash
# ela PreToolUse guard — rules are bound to a location; a write lands only where its rules are loaded.
# Reads the tool call from stdin (JSON: tool_name, tool_input.file_path) and the site from ~/.claude/ela/site.json.
# Exit 2 blocks the call and tells the session why; exit 0 lets it through. Never blocks reads.
#
# Blocks:
#   1. any Edit/Write under <published>            — a generated directory; the source is elak, regenerate instead
#   2. any Edit/Write under <projects>/ela or /helm — unless the session's project dir IS that repo
#                                                     (their CLAUDE.md and agents load only there; delegate via /ela:task)
#   3. on a remote site, any Edit/Write under <records> — the published subset is read-only there;
#                                                          drafts go to Helm's store or Jira (decision 2026-09-03-ela-second-site-on-the-remote)
set -u
SITE="$HOME/.claude/ela/site.json"
[ -f "$SITE" ] || exit 0
INPUT="$(cat)"
python3 - "$SITE" "${CLAUDE_PROJECT_DIR:-$PWD}" "$INPUT" <<'PY'
import json, os, sys
site_path, project_dir, raw = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    call = json.loads(raw)
    site = json.load(open(site_path))
except Exception:
    sys.exit(0)
if call.get("tool_name") not in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
    sys.exit(0)
target = (call.get("tool_input") or {}).get("file_path") or (call.get("tool_input") or {}).get("notebook_path") or ""
if not target:
    sys.exit(0)
target = os.path.realpath(os.path.expanduser(target))
project_dir = os.path.realpath(project_dir)
def under(path, root):
    root = os.path.realpath(os.path.expanduser(root)) if root else None
    return bool(root) and (path == root or path.startswith(root.rstrip("/") + "/"))
def block(msg):
    print(f"ela guard: {msg}", file=sys.stderr); sys.exit(2)

published = site.get("published")
if under(target, published):
    block(f"{target} is under the published directory ({published}) — generated, never edited. Change the source in elak and publish again.")
if site.get("site") == "remote" and under(target, site.get("records")):
    block(f"this is a remote site: <records> ({site.get('records')}) is a read-only published subset. A plan, ledger or decision draft written here is lost on the next publish — hand it to Helm's store or Jira.")
projects = site.get("projects") or ""
for repo in ("ela", "helm"):
    root = os.path.join(projects, repo) if projects else ""
    if under(target, root) and not under(project_dir, root):
        block(f"{target} is inside {root}, but this session's project is {project_dir}. That repo's rules (CLAUDE.md, agents) load only in a session started there — start one in {root}, or delegate with /ela:task.")
sys.exit(0)
PY
