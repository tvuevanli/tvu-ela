---
name: onething
description: The owner's daily One Thing sheet rows, drafted from his own Jira and Slack, edited in the vault, appended on his word. Use for "One Thing", "工作日志", "ela: post 1, 3".
user-invocable: true
---

# /ela:onething — the owner's One Thing rows

The team lead keeps a monthly One Thing sheet: one row per working day per person, columns
`Project | Whom | Date | Content Overview`, one tab per month (`2026.10月`). This skill drafts the owner's rows from what
he did himself, puts them in a vault note he edits, and appends to the sheet only the rows he names. The rules below come
from the October backfill (vault `to-read/2026-11-02-one-thing-october.md`, five rounds of correction) and the plan
ruled on 2026-11-02 (vault `in-progress/2026-11-02-one-thing-skill.md`).

`onething.py` gives facts; the session writes the rows. Wording is judgment, so it is never in the script.

## The verbs

| verb | does | writes |
|---|---|---|
| `ela onething facts --date D --json` | the owner's own Jira comments and moves and his own Slack messages, per Asia/Shanghai day; Helm's auto-writes and bookkeeping fields (Fixed In, labels, links, rank) left out; `errors` names a source not read | nothing |
| `ela onething facts --month YYYY-MM --json` | the same for a month, up to today | nothing |
| `ela onething sheet --month YYYY-MM [--json]` | the rows already in that month's tab under his name (Drive export, read token) | nothing |
| `ela onething render --rows FILE [--out PATH] [--force]` | the vault note from drafted rows: numbered table, keys as links, the days left out, the evidence; prints the path; refuses to replace an existing note without `--force` | the vault note |
| `ela onething post NOTE --pick "1, 3"` | the picked rows as the sheet takes them (plain keys, no links), tab-separated, ready to paste | nothing (dry run) |
| `ela onething login` | the owner's one-time grant of the write token (§Write token) | the token file, the site `.env` |
| `ela onething post NOTE --pick "1, 3" --apply` | appends them to the month's tab with the write token, skips a row already there with the same date and text, reads the tab back, records the post under `## Posted` in the note | the sheet (append only), the note |

`--pick` takes `1, 3`, `1 & 3`, `2-4` or `all`; a number not in the note exits 3. Exit codes: 0 ok · 2 usage · 3 not
found · 4 auth (no write token, or a token with the wrong scope) · 5 remote.

Site env: `ONETHING_SHEET` (the spreadsheet id), `ONETHING_WHOM` (his name in column B), `ONETHING_PROJECT` (column A),
`ONETHING_OWNER` (his Jira and Slack display name), `ONETHING_SHEETS_TOKEN_FILE` (the write token, below).

## The flow

1. `ela onething facts --date D --json > <runtime>/onething/D.json` (one day reads in a minute or two).
2. Write the rows file from the facts under the six rules: `{"rows": [{"date": "YYYY-MM-DD", "text": "..."}],
   "left_out": [{"date": ..., "why": ...}], "existing": [dates already on the sheet], "evidence": "..."}`.
3. `ela onething render --rows FILE` writes `to-read/<date>-one-thing.md` in the vault (a month:
   `to-read/<today>-one-thing-YYYY-MM.md`).
4. The owner edits rows in place, then writes `ela: post 1, 3` (or `ela: post all`) in the note.
5. `ela onething post NOTE --pick "1, 3"` shows the rows; then `--apply`. **His line in the note is the confirm.**
   Never run `--apply` without it, and never pick rows he did not name.

**Nightly** (ela-runner's evening step, after the working day): steps 1–3 for that day only. The session runs only
`ela onething facts|render|sheet` and ends with exactly one line: the note's path, `No row: <date> — <why>` when the day
has nothing of his, or `Exists: <path>` when a note for that day is already there (it may hold his edits; never
`--force` it). It never posts.

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

## Write token

`gdoc` stays read-only (its scope allowlist refuses any write scope). This skill's append is the only Google write
path, and it only appends. The owner creates its token himself, once, with **`ela onething login`**:

1. It reuses the OAuth client of the read token (`GOOGLE_TOKEN_FILE`: the same Desktop client) and prints a consent URL
   that asks exactly `https://www.googleapis.com/auth/spreadsheets`, offline, with a state check and PKCE (S256), the
   site's own address as the login hint. It opens no browser: under WSL he pastes the URL into the Windows browser, and
   the loopback redirect to `127.0.0.1` reaches the listener.
2. It exchanges the code, refuses a grant with any other scope or without a refresh token, and saves
   `google-sheets-token.json` in the site directory, mode 600, with the keys gdoc's token has (`client_id`,
   `client_secret`, `refresh_token`, `token_uri`, `scopes`). The secret is never printed.
3. It sets `ONETHING_SHEETS_TOKEN_FILE` in the site `.env` (the line replaced if present) and reads the sheet's title
   with the new token. If the Sheets API is disabled in the client's GCP project, it prints the enable link (the project
   number is the client id's prefix) and exits 4; enable it and run `login` again.

Login is a step of the owner's, not ela's: ela never runs it on his behalf. `post --apply` refuses a token whose
`scopes` is anything but exactly that one scope (exit 4), refreshes the access token in memory and never rewrites the
file. Until the token exists, `--apply` exits 4 and the dry run's rows are ready to paste.

## Known limits

- The Sheets API returned 403 with the read token while Drive export worked, so reads go through Drive export. If the
  append also returns 403, the Sheets API may need enabling in the write token's GCP project; `login` prints the link.
- Read-back goes through the same Drive export, which can lag the append by a moment; a row "not read back" is
  re-checked with `sheet --month` before anything is appended again.
- Helm's own moves under the owner's account are recognised by a Helm comment within two minutes; a Helm write without
  such a comment would show as his.
- Facts are capped per message (1200 characters); the permalink is the evidence for anything longer.
