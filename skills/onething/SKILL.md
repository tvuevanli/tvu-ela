---
name: onething
description: The owner's daily One Thing sheet rows, drafted from his own Jira and Slack, edited in the vault, copied to the sheet by him. Use for "One Thing", "工作日志", "ela: post 1, 3".
user-invocable: true
---

# /ela:onething — the owner's One Thing rows

The team lead keeps a monthly One Thing sheet: one row per working day per person, columns
`Project | Whom | Date | Content Overview`, one tab per month (`2026.10月`). This skill drafts the owner's rows from what
he did himself, puts them in a vault note he edits, and lays out the rows he names for him to paste. ela never writes
to the sheet. The rules below come
from the October backfill (vault `to-read/2026-11-02-one-thing-october.md`, five rounds of correction) and the plan
ruled on 2026-11-02 (vault `in-progress/2026-11-02-one-thing-skill.md`).

`onething.py` gives facts; the session writes the rows. Wording is judgment, so it is never in the script.

## The verbs

| verb | does | writes |
|---|---|---|
| `ela onething facts --date D --json` | the owner's own Jira comments and moves and his own Slack messages, per Asia/Shanghai day; Helm's auto-writes and bookkeeping fields (Fixed In, labels, links, rank) left out; `errors` names a source not read | nothing |
| `ela onething facts --month YYYY-MM --json` | the same for a month, up to today | nothing |
| `ela onething sheet --month YYYY-MM [--json]` | the rows already in that month's tab under his name (Drive export, read token) | nothing |
| `ela onething render --rows FILE [--out PATH] [--force]` | the vault note from drafted rows: numbered table, keys as links, the days left out, the evidence, and `## Copy to the sheet` with every row as drafted, so a fresh note is copy-ready; prints the path; refuses to replace an existing note without `--force` | the vault note |
| `ela onething post NOTE --pick "1, 3"` | rewrites `## Copy to the sheet` for the picked rows (plain keys, no links), after he edits rows or for a subset: the section with a line naming the tab and the rows, then a fenced block of tab-separated lines, Project · Whom · Date (YYYY/MM/DD) · Content, which pasted at column A fill A–D; the same block printed; the note's progress set to `<stamp>: rows N ready to copy` | the vault note |

`--pick` takes `1, 3`, `1 & 3`, `2-4` or `all`; a number not in the note exits 3. Exit codes: 0 ok · 2 usage · 3 not
found · 4 auth (the read token) · 5 remote.

Site env: `ONETHING_SHEET` (the spreadsheet id), `ONETHING_WHOM` (his name in column B), `ONETHING_PROJECT` (column A),
`ONETHING_OWNER` (his Jira and Slack display name); `GOOGLE_TOKEN_FILE`, the read-only token gdoc uses.

## The flow

1. `ela onething facts --date D --json > <runtime>/onething/D.json` (one day reads in a minute or two).
2. Write the rows file from the facts under the six rules: `{"rows": [{"date": "YYYY-MM-DD", "text": "..."}],
   "left_out": [{"date": ..., "why": ...}], "existing": [dates already on the sheet], "evidence": "..."}`.
3. `ela onething render --rows FILE` writes `to-read/<date>-one-thing.md` in the vault (a month:
   `to-read/<today>-one-thing-YYYY-MM.md`).
4. The note is copy-ready as rendered, and Home links the newest One Thing note in `to-read/` ("One Thing (copy block
   ready)" in its links line) until he moves it out. If he edits rows, he writes `ela: post all` (or `ela: post 1, 3`)
   in the note.
5. `ela onething post NOTE --pick "1, 3"` rewrites the block from the rows as they now stand; he pastes it into the
   sheet. Run it only on his line, and never pick rows he did not name.

**Nightly** (ela-runner's evening step, after the working day): steps 1–3 for that day only. The session runs only
`ela onething facts|render|sheet` and ends with exactly one line: the note's path; `No row: <date> — <why>` when both
sources were read and the day has nothing of his; `Gap: <date> — <source>` when `errors` names a source not read (the
runner reports it as failed); or `Exists: <path>` when a note for that day is already there (it may hold his edits;
never `--force` it). It never runs `post`.

**A month backfill:** `ela onething sheet --month YYYY-MM --json` first, and leave out the days already on the sheet
(name them under `existing`). `facts --month` searches every channel's history for the month and takes about ten
minutes: run it in the background and wait for it, never in a foreground call that times out.

## How a row is written

1. **Only what he did himself.** A row names his comment, analysis, decision, verification, routing or fix. QA's
   results, a colleague's finding, or a review ela wrote are not his, even when he was in the thread. *Why:* the sheet
   is his report to his manager; one claimed item that is not his costs more than a thin day.
2. **The evaluation behind a decision, never the Jira move.** "Closed a ticket" or "chose build 78" hides the work and
   reads as trivial. Write what it took: the reports read, the tickets assessed, what was found, then the decision
   ("reviewed the QA reports for builds 78 and 79, assessed the open 2.1 tickets and promoted build 78"). *Why:* the
   team lead reads outcomes against effort.
3. **Slack is a first-class source.** Much of a day is only in threads: an unblock, a ruling, a design meeting. Read
   the `slack` facts as fully as the `jira` ones. *Why:* his coordination happens in threads, not in Jira fields.
4. **One row a day, at most three works, joined by " / ".** The team writes this way. *Why:* `post 1, 3` then picks
   days, and the sheet stays scannable.
5. **English, short, verb-first.** Keep a ticket key where the ticket is the point; it is a link in the vault and plain
   text on the sheet. *Why:* the sheet is read in a glance; a row never carries a link there.
6. **No evidence, no row.** A day with nothing of his in either source is named under `left_out` with why, never filled
   in. If `errors` is not empty, a day is not "nothing of yours": say which source was not read. *Why:* an invented row
   is worse than a missing one, and a gap is not an absence.

## No write path

The owner posts to the sheet himself; ela only drafts (his ruling of 2026-11-02, after the plan's option A, a write
token, had been accepted earlier that day). The skill is read-only toward Google like `gdoc`: `sheet` reads through
Drive export with the read token, and `post` writes nothing but the vault note. Do not add an append, a write token or
a Sheets write scope without a new ruling from him.

## Known limits

- The Sheets API returned 403 with the read token while Drive export worked, so `sheet` reads through Drive export.
- `post` does not check the sheet for rows already pasted; before a backfill, `sheet --month` names the days already
  there.
- Helm's own moves under the owner's account are recognised by a Helm comment within two minutes; a Helm write without
  such a comment would show as his.
- Facts are capped per message (1200 characters); the permalink is the evidence for anything longer.
