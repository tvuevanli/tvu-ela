#!/usr/bin/env bash
# ela SessionEnd hook — snapshot the knowledge base. Never touches the ela repo. Also run by SessionStart as a catch-up.
# Policy (blueprint decision 2026-09-02-knowledge-commits-are-snapshots): whenever a turn ends with the
# knowledge base dirty at session end (or a catch-up at the next start), one commit with a generated message,
# pushed; nothing per file, nothing on a timer.
# Evan accepted many small snapshots over a curated history for the knowledge base.
set -u
SITE="$HOME/.claude/ela/site.json"
[ -f "$SITE" ] || exit 0
REC=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('records',''))" "$SITE" 2>/dev/null)
[ -n "$REC" ] && [ -d "$REC/.git" ] || exit 0
cd "$REC" || exit 0
if [ -n "$(git status --porcelain)" ]; then
  dirs=$(git status --porcelain | awk '{print $2}' | cut -d/ -f1 | sort -u | tr '\n' ' ' | sed 's/ $//')
  n=$(git status --porcelain | wc -l | tr -d ' ')
  git add -A
  git commit -q -m "snapshot $(date +%F\ %H:%M) — ${n} file(s): ${dirs}" 2>/dev/null
fi
# push whatever is ahead of the remote — also commits left unpushed when an earlier hook was cut short
if [ -n "$(git log --oneline @{u}..HEAD 2>/dev/null)" ]; then
  git push -q origin HEAD 2>/dev/null
fi
exit 0
