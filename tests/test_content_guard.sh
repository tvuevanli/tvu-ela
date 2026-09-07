#!/usr/bin/env bash
# The content guard refuses what a shared tree must not carry and accepts finished writing.
# Runs in a throwaway repository; touches nothing else.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
cd "$T"; git init -q; git config user.email t@t; git config user.name t
"$ROOT/hooks/install-git-hooks.sh" "$T" >/dev/null
fail=0
expect() { # expect <accept|refuse> <label>
  local want=$1 label=$2 rc=0
  git add -A >/dev/null; git commit -q -m "$MSG" >/dev/null 2>"$T/err" || rc=$?
  if [ "$want" = accept ] && [ $rc -ne 0 ]; then echo "FAIL $label: refused: $(head -2 "$T/err" | tail -1)"; fail=1; fi
  if [ "$want" = refuse ] && [ $rc -eq 0 ]; then echo "FAIL $label: accepted"; fail=1; fi
  [ $rc -ne 0 ] && git reset -q --hard >/dev/null 2>&1 || true
  git clean -fdq >/dev/null 2>&1 || true
}
MSG="docs: a clean rule"
printf 'Rule: reads are first-hand.\nReason: a report is input.\nBuilt from tag 2.1.19, image 1.0.0.12.\nSee MH-3555 and https://tvunetworks.slack.com/archives/C06553EE44X/p1\nEvan confirmed it should be recorded.\n' > good.md; expect accept "clean documentation"
printf 'x\n' > a.md; MSG='ok: Evan said "这个方案不行我们换一个吧"'; expect refuse "quoted CJK in the message"
MSG="docs: x"; printf 'source: ela design session with Evan, 2026-09-04\n' > b.md; expect refuse "source line citing a conversation"
printf 'He said "a 是OK的" so we decided this.\n' > c.md; expect refuse "reported speech"
printf 'Host node.example-tailnet.ts.net\n' > d.md; expect refuse "tailnet host"
printf 'gateway at 192.0.2.181 answers\n' > e.md; expect refuse "IPv4 address"
printf 'token = "afxp_5e21a6KK7d4NxPxbWZxFeInOtyuRsBX2FRSm"\n' > f.md; expect refuse "token"
printf 'This session found the bug.\n' > g.md; expect refuse "session narrative in .md"
printf '# this session id is a request field\nsession = req.get("session")\n' > h.py; expect accept "the word session in code"
printf 'ssh://git@example.internal/repo.git\n' > i.md; expect refuse "ssh url"
printf 'run: ssh user@box.example.com ls\n' > j.md; expect refuse "ssh user@host"
printf 'the copier asked for a new port\n' > k.md; expect accept "asked for is not reported speech"
[ $fail -eq 0 ] && echo "content guard: all cases pass"
exit $fail
