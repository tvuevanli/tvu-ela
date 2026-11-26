# 0027 — Context is paid on every turn

Status: accepted, 2026-11-24 (recorded as an ADR on 2026-11-26; the rule stood in `CLAUDE.md`, hard rule 9, from
commit f43df29).

## Context

Each turn of a session re-reads the whole context from cache. A file read whole is therefore paid again on every
turn after the read, not once. On 2026-11-20 four long ela sessions were about 80% of the day's weighted tokens
(`ela improve digest`); the largest single cause was a whole read of one of the three scripts over 1,500 lines
(`vault.py`, `brief.py`, `jira.py`) early in a session that then ran for hours.

## Decision

- A file over 1,500 lines is located with grep and read by line range, never whole, and re-read only when it has
  changed.
- A worker session keeps to one concern and closes when it is done.
- The same reasoning governs what is injected: a text every session loads has a character ceiling in
  `tests/test_session_start_offline.py`, and the skill descriptions have theirs in `tests/test_description_budget.py`.

## Reason

The cost of a read is its size times the turns that follow it, so the cheap moment to save is before the read. A
session that changes concern carries the first concern's context through the second; closing and opening a new
worker costs one brief and drops the rest.
