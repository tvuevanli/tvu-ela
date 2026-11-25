# reports/ — the team's daily and weekly report narrative

Written by `ela teamreport write` (ela, `skills/teamreport/`), one file per day and per ISO week. Helm reads these
files, renders the report page and posts it to Slack; ela itself posts nothing. Generated, never edited by hand.

| path | what |
|---|---|
| `reports/daily/<YYYY-MM-DD>.json` | the day's narrative (the local day, Asia/Shanghai, up to the time it was written) |
| `reports/weekly/<YYYY-Www>.json` | the ISO week's narrative (Monday to Sunday) |
| `reports/README.md` | this schema |

## Fields (schema 1)

| field | type | meaning |
|---|---|---|
| `schema` | int | 1. A field removed or changing meaning raises it; a field added does not. |
| `kind` | `daily` · `weekly` | |
| `id` | string | the date (`2026-11-25`) or the ISO week (`2026-W48`) — the file's name |
| `date` | string | daily only: the day |
| `week`, `range` | string, [string, string] | weekly only: the ISO week and its Monday and Sunday |
| `state` | `ok` · `quiet` · `incomplete` | `ok`: written from activity. `quiet`: no activity in any source and every source read whole. `incomplete`: no activity came back and a source has a gap, so the day is not claimed quiet. The last two carry a one-bullet stub and no model was called. |
| `generated_at` | ISO time | when the file was written |
| `writer` | string | `ela teamreport` |
| `model` | bool | whether a model wrote `narrative` (false for a stub) |
| `narrative` | markdown | the report text, see below |
| `keys` | [string] | every Jira key `narrative` cites; each one is in the data the narrative was written from |
| `sources` | object | per source (`jira`, `slack`, `mail`; weekly: `jira`, `mail`, `dailies`): `status` (`ok` · `gap` · `unread` · weekly `dailies`: `missing`), `count`, `read_at` (the facts store's read), `gap` (why, when the store recorded one); `jira.board_read_at` is the read of the Blocked and In Progress tickets; `slack.cap_hit` and `slack.seen` when the day held more than 200 messages (the project channel is kept first, then the latest); `dailies.dates` the days whose narrative the week was written from |
| `window` | [ISO time, ISO time] | the half-open window the data was taken from |
| `removed` | object | what the checks took out of the model's text: `sections` (headings Helm owns), `keys` (Jira keys the data does not hold), `tokens` (weekly: version, build or bundle-shaped tokens), `lines` (a title, a Sources line), `missing_sections` (a required heading the text lacks). Empty when nothing was removed. |

## The narrative

Markdown in the form Helm's own writer produced, so the page and the Slack conversion read it unchanged: section
headers are `**bold**` lines, never `#` headings; bullets are `-`; a Slack thread is cited as `[#channel](permalink)`;
Jira keys are bare (`MH-1234`), for the renderer to link.

- **Daily**: `**Summary**` (always), then, each only when it has items, `**Pushed forward**`, `**Discussions &
  decisions**`, `**New work surfaced**`, `**Blockers & escalations**`. It holds no `**Release & QA**` section and no
  `_Sources:` line: Helm inserts its parsed Release & QA block after the Summary section and its sources line at the
  foot, as it does for its own narrative.
- **Weekly**: `**Week in one paragraph**` and `**Themes**`, nothing else. Helm appends its computed sections
  (`**Shipped this week**`, `**Numbers**`, `**Blocked & at risk**`, `**Carry-over into next week**`) and its sources
  line after them.

## When it is written

ela's runner writes the daily on weekdays at 22:00 and the weekly (for the previous ISO week) on Mondays at 08:30,
the times of Helm's own report tasks. A rewrite of the same day or week replaces the file.
