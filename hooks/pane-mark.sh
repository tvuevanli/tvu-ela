#!/usr/bin/env bash
# ela Stop hook — the zellij pane title carries the last reply's closing mark: ⏳ while the session waits
# (`⏳ ela pending · …`), 🦀 when it is out (`— ela out 🦀`), nothing otherwise (sessions.py hook-stop).
# Silent outside zellij; never blocks the stop, never prints a decision.
set -u
[ -n "${ZELLIJ_PANE_ID:-}" ] || exit 0
ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
[ -t 0 ] || printf '%s' "$(cat)" | python3 "$ROOT/skills/sessions/sessions.py" hook-stop >/dev/null 2>&1 || true
exit 0
