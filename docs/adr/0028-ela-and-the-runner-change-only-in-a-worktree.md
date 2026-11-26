# 0028 — ela and ela-runner change only in a worktree

Status: accepted, 2026-11-24 (recorded as an ADR on 2026-11-26; the rule stood in `CLAUDE.md`, hard rule 10, from
commit 96d9f5f).

## Context

Every `ela` command, the runner and every session run the main checkout of ela, so an unfinished edit there is
production the moment it is saved. On 2026-11-24 a half-written `skills/vault/vault.py` was live for a minute, and a
runner sync in that minute wrote twelve vault notes with broken front matter.

## Decision

- ela and ela-runner are changed only in a worktree: `ela session open ela|runner --name N` makes `<work>/N/<repo>`
  on branch `evan/N`.
- The main checkout receives fast-forward merges only. `ela session land N` rebases, runs `tests/run.sh`,
  fast-forwards main when no dirty file there overlaps, pushes and removes the worktree.

## Reason

A worktree makes the unit of change the landed commit, which has passed the suite, instead of the saved file. The
fast-forward keeps main's history the sequence of things that were live, and the overlap check keeps a land from
writing over an edit the main checkout still holds.
