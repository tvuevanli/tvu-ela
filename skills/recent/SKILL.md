---
name: recent
description: The week's MH tickets placed by release line and by lane, the vault's recent page. Use for "recent tickets", "this week's picture", "这周的票在哪条线".
user-invocable: true
---

# /ela:recent — the week's tickets, placed

`ela recent` lays out every MH ticket created or updated in the window (seven days unless `--days`) so the owner reads
in one glance which release line a ticket belongs to, where its fix stands on that line's train, what QA said about
it, and what moved. It is a dashboard, not a report: the vault's root page `recent` ("Recent · 7 days", type `recent`)
beside `board` and `lanes`, rewritten on every sync from the newest result `ela recent --write` kept, never a dated
note (vault to-read/2026-11-02-recent-tickets-by-line-and-lane.md, ruled 2026-11-02).

## What the verb reads, and from where

Every column is a fact ela already reads; the verb only joins them. Nothing is written to Jira.

| column | source |
|---|---|
| the line | the ticket's `release:mh-<line>` label; lines and their lanes from the published map `map/release.yaml` § lines, through the release skill's map reader (`rmap`) |
| the train row | the last lane read saved by `ela changes` / `ela matrix --page` (`<runtime>/runner/versions-*.json`), rendered cell by cell by the brief's `matrix_cell`, so ▲ ✓ ◐ ○ mean what they mean on the lanes page; the constraints' 🔒/⛔ are not read here (that read asks the lane hosts) |
| type · status · assignee, P / due | the ticket |
| seen on | the lanes the summary or description names (prod-3, CN Prod2, QA-AWS3, daily-wed, stage), canonical through the release skill's lane words |
| fix stands at | the Fixed In field (`slug@version`, aliases resolved by the map) against the lane versions of the line's qa, daily and prod lanes, compared by the promote skill's `cmp_versions`: `dev` without a Fixed In; the furthest lane whose versions carry every judged entry, the QA lane with its build; `declared` when no entry can be read against a lane (a docker image, a bundle-tracked slug); `· CN behind` when the China lane aligned with prod has not caught up. This is a version comparison, not the commit-ancestry chain `ela fixed-in` runs per ticket |
| QA said | the lane test lists' state on disk (`<reports>/lanes/test-list-<lane>.json`, written by `ela testlist`): the row that owns or also names the key, its latest verdict and build; `—` when no list names it. No mail or Slack is read here |
| last change | the changelog inside the window: status, Fixed In, assignee, priority, labels, or `created`; `updated` when only unclassed edits happened. Comments are not read (one more call per ticket) |

**By lane**, folded under each line: for each of its lanes the fixes that arrived in the window (carried now and not
in the oldest lane read of the window), the fixes under test (the fix stands on it, no QA verdict), and the tickets
reported from it (the ticket names the lane).

**No line**: each ticket without a line label, with the label ela would infer from its Fixed In (the one line whose
lanes run that slug in the same M.m series) and why, or why none can be. The page writes nothing: the label is a
drafted action for the owner's word until the rule is closed.

## The page

Sections in the order 2.1, 2.0, 2.2 (then any other line, then No line), each: the train (backend and frontend per
lane), the ticket table with seven columns, the By lane fold. Tables fold after eight rows under `> [!note]- N more`
and the fold shrinks until the open words fit the vault's 1,200 budget (counted outside folds). At the top, the box
`- [ ] refresh recent (last HH:MM; …)`: the runner's vault watcher runs `ela recent --write` and a sync on that tick,
as it runs the board's refresh on `refresh the board`. Home's footer links the page beside lanes and board, and the
morning page's New tickets heading carries a pointer to it.

## How it runs

- `ela recent` prints the page; `--json` the result; `--write` keeps the result as `<reports>/recent/<date>.json`
  (one file a day, rewritten within it) and the vault's next sync renders `recent.md` from the newest file.
- The runner calls `ela recent --write` at the morning, 13:00, 17:30 and evening passes and on the refresh tick,
  then `ela vault sync`.
- Exit 5 when the Jira search fails; a missing lane read or test list is not a failure: the page names it under
  "Not read".
