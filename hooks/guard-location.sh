#!/usr/bin/env bash
# ela PreToolUse guard — rules are bound to a location; a write lands only where its rules are loaded.
# Reads the tool call from stdin (JSON: tool_name, tool_input.file_path) and the site from ~/.claude/ela/site.json.
# Exit 2 blocks the call and tells the session why; exit 0 lets it through. Never blocks reads.
#
# Blocks:
#   1. any Edit/Write under <published>            — a generated directory; the source is elak, regenerate instead
#   2. any Edit/Write under <projects>/ela or /helm — unless the session's project dir IS that repo
#                                                     (their CLAUDE.md and agents load only there; delegate via /ela:task)
#   3. on a remote site, any Edit/Write under <elak> — the published subset is read-only there;
#                                                        drafts go to Helm's store or Jira (decision 2026-09-03-ela-second-site-on-the-remote)
#   4. any Edit/Write under <elak> outside blueprint/ knowledge/ map/ — elak holds what ela knows, and
#                                                        a log of what happened is not knowledge
#                                                        (decision 2026-09-07-elak-is-elas-knowledge)
#   5. any Edit/Write into a tracked .md/.yaml of elak/ela/helm whose new text quotes a person's own
#      words — a tracked file carries the rule and names the origin, never the utterance
#      (decisions 2026-09-03-tracked-files-carry-the-rule-not-the-argument,
#       2026-09-03-records-name-the-origin-not-the-utterance). Rules 1-4 are about place; this one is
#      about content, and it is the reason the hook reads the text and not only the path.
set -u
SITE="$HOME/.claude/ela/site.json"
[ -f "$SITE" ] || exit 0
INPUT="$(cat)"
python3 - "$SITE" "${CLAUDE_PROJECT_DIR:-$PWD}" "$INPUT" <<'PY'
import json, os, re, sys
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
elak = site.get("elak") or site.get("records")      # `records` accepted until /ela:setup renames the key
if under(target, published):
    block(f"{target} is under the published directory ({published}) — generated, never edited. Change the source in elak and publish again.")
if site.get("site") == "remote" and under(target, elak):
    block(f"this is a remote site: <elak> ({elak}) is a read-only published subset. A plan or decision draft written here is lost on the next publish — hand it to Helm's store or Jira.")
projects = site.get("projects") or ""
for repo in ("ela", "helm"):
    root = os.path.join(projects, repo) if projects else ""
    if under(target, root) and not under(project_dir, root):
        block(f"{target} is inside {root}, but this session's project is {project_dir}. That repo's rules (CLAUDE.md, agents) load only in a session started there — start one in {root}, or delegate with /ela:task.")

# 4 — elak holds what ela knows, in three directories. Anything else is a diary.
if under(target, elak):
    rel = os.path.relpath(target, os.path.realpath(os.path.expanduser(elak)))
    top = rel.split(os.sep)[0]
    if top not in ("blueprint", "knowledge", "map", ".git", ".gitignore", "README.md"):
        block(f"{target} is under <elak> but outside blueprint/ knowledge/ map/.\n"
              f"  elak holds what ela knows (decision 2026-09-07-elak-is-elas-knowledge). Two questions:\n"
              f"    1. Does ela know this? about itself -> blueprint/ · about the world -> map/ if a script\n"
              f"       derives it, knowledge/ if it is a reading.\n"
              f"    2. Or did it merely happen? Then it is not knowledge: cite the source (a Slack permalink,\n"
              f"       a ticket key, a commit) and keep no file. Raw material goes to <runtime>.")

# 5 — a tracked file names the origin, never the utterance.
UTTERANCE_CUE = re.compile(r"(?i)\b(source|owner_source|says?|said|asked|wrote|words|quote[sd]?)\b|他说|她说|原话")
CJK_QUOTE = re.compile(r"[\"“「』]([^\"”」』\n]*[一-鿿][^\"”」』\n]*)[\"”」』]")
new_text = (call.get("tool_input") or {}).get("content") or (call.get("tool_input") or {}).get("new_string") or ""
tracked_roots = [r for r in (elak, os.path.join(projects, "ela"), os.path.join(projects, "helm")) if r]
if new_text and target.endswith((".md", ".yaml", ".yml")) and any(under(target, r) for r in tracked_roots):
    for line in new_text.splitlines():
        if line.lstrip().startswith(("description:", "#", "//", "*", "-", "|")) and "source" not in line.lower():
            continue                                  # trigger vocabulary and bullet prose carry terms, not quotations
        for m in CJK_QUOTE.finditer(line):
            run = m.group(1)
            cjk = len(re.findall(r"[一-鿿]", run))
            if cjk >= 12 or (UTTERANCE_CUE.search(line) and cjk >= 2):
                block(f"this write quotes what someone said: {m.group(0)[:60]}\n"
                      f"  A tracked file carries the rule and names the ORIGIN, not the utterance\n"
                      f"  (2026-09-03-tracked-files-carry-the-rule-not-the-argument,\n"
                      f"   2026-09-03-records-name-the-origin-not-the-utterance).\n"
                      f"  Write what is now true and cite where it was decided or observed — a permalink,\n"
                      f"  a ticket key, a date and a role. Never the sentence a person typed.")
sys.exit(0)
PY
