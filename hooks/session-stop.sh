#!/usr/bin/env bash
# ela SessionEnd hook — report, never commit.
# elak is written only on Evan's word and committed by hand (or by ela after his confirm), so a dirty
# knowledge tree at session end is shown, not snapshotted. Nothing here runs git add, commit or push.
set -u
SITE="$HOME/.claude/ela/site.json"
[ -f "$SITE" ] || exit 0
ELAK=$(python3 -c "import json,sys;s=json.load(open(sys.argv[1]));print(s.get('elak') or s.get('records',''))" "$SITE" 2>/dev/null)
[ -n "$ELAK" ] && [ -d "$ELAK/.git" ] || exit 0
cd "$ELAK" || exit 0
dirty=$(git status --porcelain | wc -l | tr -d ' ')
ahead=$(git log --oneline @{u}..HEAD 2>/dev/null | wc -l | tr -d ' ')
if [ "$dirty" != "0" ] || [ "$ahead" != "0" ]; then
  echo "ela: elak has ${dirty} uncommitted file(s) and ${ahead} unpushed commit(s) — review with 'git -C $ELAK status' and commit by hand." >&2
fi
exit 0
