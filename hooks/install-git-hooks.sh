#!/usr/bin/env bash
# Install content-guard.sh as pre-commit and commit-msg in the repositories other people may read.
# Local to this machine (.git/hooks is not tracked); re-run after cloning. Usage: install-git-hooks.sh [repo...]
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SITE="$HOME/.claude/ela/site.json"
if [ $# -gt 0 ]; then repos=("$@"); else
  P=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['projects'])" "$SITE")
  E=$(python3 -c "import json,sys;s=json.load(open(sys.argv[1]));print(s.get('elak') or s.get('records'))" "$SITE")
  repos=("$P/ela" "$P/helm" "$E")
fi
for r in "${repos[@]}"; do
  [ -d "$r/.git" ] || { echo "skip $r (no .git)"; continue; }
  printf '#!/usr/bin/env bash\nexec "%s/hooks/content-guard.sh" pre-commit\n' "$ROOT" > "$r/.git/hooks/pre-commit"
  printf '#!/usr/bin/env bash\nexec "%s/hooks/content-guard.sh" commit-msg "$1"\n' "$ROOT" > "$r/.git/hooks/commit-msg"
  chmod +x "$r/.git/hooks/pre-commit" "$r/.git/hooks/commit-msg"
  echo "installed in $r"
done
