# 0013 — Prod follows the newest official bundle; a pin only holds it

Status: accepted, 2026-10-27. Supersedes ADR 0012's "the pin is the record of prod's bundle"; 0012's write (one
entry, committed alone on the owner's apply) stands for the pin that remains.

## Decision

- **Prod's bundle is the newest official bundle of its line**, read from the prod host by the closed name grammar
  (`MediaHub <M.m>.N` with an optional qualifier, `MediaHub <M.m> rcN`; side bundles such as "Docker Only" or "pre"
  never qualify). No one has to set it.
- **A pin is an exception, not the record.** `ela release pin <line> <bundle> --why "<reason>"` holds prod on an older
  official on purpose; the reason is written with it. `ela release unpin <line>` lifts it. Both are dry runs until
  `--apply`, which commits `blueprint/releases.yaml` alone.
- **A hold is reviewed while it is behind.** The morning raises a held line as the owner's decision whenever a newer
  official exists, with the hold's reason and `unpin` as the drafted action. A line not held raises nothing.

## Reason

A record that needs a hand on every release goes stale: Helm's own pin sat on 2.0 rc11 while rc14 and rc16 shipped,
and on 1.5.5 while 1.5.6 shipped, and the owner dropped it in Helm for the newest matching bundle. The owner keeps
the official bundles current himself, so the newest one is already his word; only a deliberate hold needs saying.

Decided by the owner at ela's gate on 2026-10-27, choosing "override only" over keeping the pin as the record or
retiring it.
