# The pending promotion and its plan

Part of ela's promote skill (`SKILL.md` beside this file), read for `plan`, `close`, or a cell of `<reports>/promote/pending.json`.

- **A report written with `--out` opens the pending promotion for its line and lanes.** `<reports>/promote/pending.json`
  holds one record per line and lane pair (`{"2.1|daily-wed|prod-3": {...}, "2.0|qa-cn2|prod-8": {...}}`): the line,
  the lanes, the report's path and the candidate: the source lane's version per service. The next run for the same
  line and lanes refreshes that record and no other; a cell the owner still has to choose is written there as
  `{"awaiting": "owner", "options": [...], "why": "..."}` and kept until he rules, as are the fields the report does
  not produce (label, bundle, open_items, notes, waiting_on). A source lane the run could not read never blanks a
  filled candidate: the last good versions stand, marked `stale: "<when> source unreadable"`. The morning shows each
  line's candidate as the next train on the lanes page and each awaiting cell as a decision for him; `close` ends one
  record when the promotion shipped or was dropped (`--line`/`--to` when several are open).
- **A planned promotion is on the same record.** `plan <line> <from> <to> --on YYYY-MM-DD --after "<condition>"
  [--carry KEY…]` writes the day, the condition in words and the keys the train carries (the local file only, never
  Slack); the lanes block, the next-train column and `report` show it as one line — "planned Fri 11-06 after QA's
  report on Thursday's build · carries MH-1860 (feature/MH-1860 not merged into release2.1 in 3 repos as of 11-04)".
  Every `plan`, `plan --check` and `report` run, and every lanes-page pass, re-checks three facts as ✓/·/✗ lines: each
  carried key's branches against `origin/release<line>` in every mapped checkout (the refs as last fetched), whether
  the newest QA build's release mail names the key, and whether that build has a QA report. `close` clears the plan.
