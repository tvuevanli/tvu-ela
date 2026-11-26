# 0026 — The session that writes elak commits and pushes it

Status: accepted, 2026-11-25; the mechanism exception added 2026-11-26. Supersedes ADR 0001. ADRs 0011 and 0012 (the
owner's word in the vault, his apply on a release pin) stand.

## Context

ADR 0001 left every elak commit to the owner's hand. In practice he commits none of ela, mh-bot or elak himself, so
recorded knowledge stayed uncommitted across sessions, and an unattended job's edits sat in the tree with nobody to
read them. The owner ruled on 2026-11-25 (working preferences, site file) that the session that writes elak commits
and pushes it, and on 2026-11-26 that a feature's mechanism, read first-hand and cited, needs no "record" each time.

## Decision

- **Who writes.** An attended session writes elak on the owner's request to record, and, without one, a product
  capability's mechanism read first-hand from code or docs and cited (its flow, configuration keys, error codes,
  recorded decisions). Judgments, verdicts and plans wait for his word. An unattended session (the runner's passes,
  owner, vault and thread jobs) never writes elak: it drafts to `<runtime>/drafts/` for the desk to admit.
- **Who commits.** The session that wrote it, one concern per commit, staged by explicit path; never `git add -A`.
  Before a push, `git status` shows nothing staged beyond the commit's paths; another session's edits stay unstaged
  and are reported. Never `--force`; a rejected push is `git pull --rebase`, resolved keeping both sides, pushed again.
- **Never a hook.** No hook adds, commits or pushes elak. The SessionEnd hook reports an uncommitted or unpushed tree.
- The admission test (elak `knowledge/README.md`, the one-year test) holds; what merely happened is cited, not stored.

## Reason

The review ADR 0001 protected is kept by the rules above: what goes in is what he asked for or what is checked
against its source, and an explicit-path commit cannot carry another session's work. A commit left to a hand that
never makes it loses the record instead. A forced push or a broad commit would erase or carry another session's work
without anyone seeing it, so both are excluded. An unattended session has nobody to read its write, hence drafts.
