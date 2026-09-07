# 0003 — content is guarded at commit time

**Decision.** `hooks/content-guard.sh` runs as `pre-commit` and `commit-msg` in ela, Helm and elak.
It refuses credentials, IPv4 addresses, tailnet and ssh hosts, a person's quoted words, and session
narrative in documentation. `hooks/install-git-hooks.sh` installs it; the bypass is an explicit
environment variable, used on purpose and visible in the shell history.

**Reason.** The PreToolUse guard sees a write as it is typed and can only judge that fragment. A
commit is the unit that reaches other people; checking its staged additions and its message catches
what several small edits assemble. Both guards stay: one gives early feedback, the other is the gate.
