---
name: onething
description: The owner's daily One Thing sheet rows, drafted from his own Jira and Slack into a store, shown on the day's changes page, copied to the sheet by him. Use for "One Thing", "工作日志", "the row for yesterday".
user-invocable: true
---

# /ela:onething — the owner's One Thing rows

The team lead keeps a monthly One Thing sheet: one row per working day per person, columns
`Project | Whom | Date | Content Overview`, one tab per month (`2026.10月`). This skill drafts the owner's row from what
he did himself into a store, puts it on the next morning's changes page as part of yesterday's truth (his ruling of
2026-11-03: the row lives beside everything else that happened, not in a note per day), takes his rewording and his
"pasted" tick from that page, and keeps the month's unpasted rows on one page he pastes from. ela never writes to the
sheet. The row rules below come from the October backfill (five rounds of correction, vault
`to-read/2026-11-02-one-thing-october.md`, now imported into the store) and the plan ruled on 2026-11-02 (vault
`in-progress/2026-11-02-one-thing-skill.md`).

`onething.py` gives facts and keeps the store; the session writes the rows. Wording is judgment, so it is never in the
script.

## The store

`<reports>/onething/<YYYY-MM>.json`, one file per month, one entry per working day:

```
{"month": "2026-11", "days": [
  {"date": "2026-11-02", "drafted_at": "…", "source_errors": [],
   "rows": [{"n": 1, "text": "…", "evidence": "…", "pasted": false, "ela_lines": []}]}]}
```

`text` is the row as it stands (the latest `ela:` line once one is applied; every applied line is kept under
`ela_lines`); `pasted` is his tick; `source_errors` names a source `facts` could not read. An entry is replaced only
for its own date; other days are never touched.

## The verbs

| verb | does | writes |
|---|---|---|
| `ela onething facts --date D --json` | the owner's own Jira comments and moves and his own Slack messages, per Asia/Shanghai day; Helm's auto-writes and bookkeeping fields (Fixed In, labels, links, rank) left out; `errors` names a source not read | nothing |
| `ela onething facts --month YYYY-MM --json` | the same for a month, up to today | nothing |
| `ela onething sheet --month YYYY-MM [--json]` | the rows already in that month's tab under his name (Drive export, read token) | nothing |
| `ela onething render --rows FILE [--force]` | the drafted rows into the store, that date's entry appended or (with `--force` only) replaced; refuses a date already drafted, it may hold his edits. `--out PATH` writes a vault note instead, on request | the store |
| `ela onething block --date D [--json]` | the day's block for the changes page: `## Your day, <weekday date>`, the numbered row table (keys linked), the evidence folded, a folded *Copy to the sheet* with the tab-separated line(s) as `post` prints them, one `- [ ] pasted n` box per row | nothing |
| `ela onething apply --date D --lines FILE` | his lines from the page, one per line: a bare line (or `n: …`) replaces row n's text and is kept under `ela_lines`; `pasted n` (or `pasted YYYY-MM-DD [n]`, from the month page) sets the flag. Applied once: the same line at a later pass changes nothing | the store |
| `ela onething post (--date D \| --month YYYY-MM) [--pick "1, 3"] [--all]` | the rows as the sheet takes them (plain keys), tab-separated, Project · Whom · Date (YYYY/MM/DD) · Content, which pasted at column A fill A–D; a month prints its rows not yet pasted (`--all`: every row) | nothing |
| `ela onething import NOTE [--force] [--pasted]` | one-off: a One Thing vault note's table into the store, the note's Evidence fold on each row | the store |

`--pick` takes `1, 3`, `1 & 3`, `2-4` or `all`; a number not drafted exits 3. Exit codes: 0 ok · 2 usage · 3 not
found · 4 auth (the read token) · 5 remote.

Site env: `ONETHING_SHEET` (the spreadsheet id), `ONETHING_WHOM` (his name in column B), `ONETHING_PROJECT` (column A),
`ONETHING_OWNER` (his Jira and Slack display name); `GOOGLE_TOKEN_FILE`, the read-only token gdoc uses.

## Where he meets the rows

- **The day's changes page** (`reference/days/<year>/<date>-changes.md`, "What changed"): its last section, *Your day, <the
  previous working day>*, is the block above. ela-runner inserts it after the morning's judge writes the page and
  again at the 13:00, 17:30 and 19:00 passes, applying the page's own marks first: an `ela:` line under the section
  rewords the row (`ela: 2: …` for row 2 of a day with several); a ticked `pasted n` marks the row as on the sheet. The vault keeps his lines and ticks through each rewrite.
- **`reference/one-thing.md`** in the vault ("One Thing · <month>", type `one-thing`, a living page of the vault's page
  family rendered by the sync from the store): the month's rows not yet pasted, one *Copy to the sheet* block, a
  `pasted <date>` box per row, and earlier months' unpasted rows under their own heading. He pastes weekly from here
  and ticks; Home's links line points at it with the count still to paste.

## The flow

1. `ela onething facts --date D --json > <runtime>/onething/D.json` (one day reads in a minute or two).
2. Write the rows file from the facts under the six rules: `{"rows": [{"date": "YYYY-MM-DD", "text": "..."}],
   "left_out": [{"date": ..., "why": ...}], "existing": [dates already on the sheet], "evidence": "...",
   "errors": [...]}`.
3. `ela onething render --rows FILE` writes the day's entry into the store. The next morning's changes page carries
   it; `one-thing.md` lists it until he ticks `pasted`.
4. He rewords with an `ela:` line under *Your day* and ticks `pasted` after pasting; the runner's passes apply both.
   `ela onething post --month YYYY-MM` prints the month's unpasted lines when he asks for them in a session.

**Nightly** (ela-runner's evening step, after the working day): steps 1–3 for that day only. The session runs only
`ela onething facts|render|sheet` and ends with exactly one line: render's line naming the store; `No row: <date> —
<why>` when both sources were read and the day has nothing of his; `Gap: <date> — <source>` when `errors` names a
source not read (the runner reports it as failed); or `Exists: <date>` when render says the date is already drafted
(the entry may hold his edits; never `--force` it). It never runs `post`, `apply` or `import`.

**A month backfill:** `ela onething sheet --month YYYY-MM --json` first, and leave out the days already on the sheet
(name them under `existing`). `facts --month` searches every channel's history for the month and takes about ten
minutes: run it in the background and wait for it, never in a foreground call that times out. `render --rows` with
many dates writes one entry per date; a date already drafted stops the whole write unless `--force`.

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
4. **One row a day, at most three works, joined by " / ".** The team writes this way. *Why:* the sheet stays
   scannable, and one `pasted` box says the day is done.
5. **English, short, verb-first.** Keep a ticket key where the ticket is the point; it is a link in the vault and plain
   text on the sheet. *Why:* the sheet is read in a glance; a row never carries a link there.
6. **No evidence, no row.** A day with nothing of his in either source is named under `left_out` with why, never filled
   in. If `errors` is not empty, a day is not "nothing of yours": say which source was not read. *Why:* an invented row
   is worse than a missing one, and a gap is not an absence.

## No write path

The owner posts to the sheet himself; ela only drafts (his ruling of 2026-11-02, after the plan's option A, a write
token, had been accepted earlier that day). The skill is read-only toward Google like `gdoc`: `sheet` reads through
Drive export with the read token, and `post` prints and writes nothing. Do not add an append, a write token or a
Sheets write scope without a new ruling from him.

## Known limits

- The Sheets API returned 403 with the read token while Drive export worked, so `sheet` reads through Drive export.
- `pasted` is his tick, not a read of the sheet; before a backfill, `sheet --month` names the days already there.
- Helm's own moves under the owner's account are recognised by a Helm comment within two minutes; a Helm write without
  such a comment would show as his.
- Facts are capped per message (1200 characters); the permalink is the evidence for anything longer.
- A rewording on the month page is not read; it belongs under *Your day* on the day's changes page.
