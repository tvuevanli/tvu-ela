---
name: project
description: The owner's projects in the vault — bounded work with a deadline, one folder and page each. Use for "project list", "days to the Super Bowl", "new project", "这个项目还剩几天".
user-invocable: true
---

# /ela:project — a project's folder, page and watch

A **project** is bounded work with a deadline and parties outside MediaHub's standing program: the WTAE 4K ATSC 3.0
PoC, a customer trial, a demo. MediaHub itself stays a program (`mh/`), never a project. Each project has a folder
`projects/<key>/` in the owner's vault holding its page `projects/<key>/<key>.md` (type `project`, the living family,
1,200 words outside folds) and the readings and reports it keeps. Any note anywhere names its project with the
property `project: <key>` and keeps its own life and folder; the page lists it. Rule: elak
`blueprint/decisions/2026-11-04-projects-are-bounded-work-with-one-page-each.md`.

## The page

Two halves. The boundary is the first of the sync's five `##` headings, in this order: *Waiting for your word*,
*Notes*, *Keys and threads*, *Afterwards*, *Deadline* (ela-runner's morning Projects section reads the same
boundary, so the head never uses one of those five names).

- **The head**, above it, is the desk's: goal, dates, parties and roles, what is known, the next step (the first
  unticked box there, or the `next-step` property; a box whose line carries a date is an ask the morning page can
  see). The sync keeps it as written. Once the owner writes `ela: keep this`, its settled facts go to elak
  `knowledge/projects/<key>/<key>.md` and the head is rendered from that copy; until then the page says the head is
  the desk's.
- **The tail** is written on every `ela vault sync`: *Waiting for your word* (the project's notes in `to-read/` and
  `in-progress/`, with status and `next`); *Notes* by folder, newest first (every note carrying `project: <key>`,
  plus what the folder keeps); *Keys and threads* (what is watched, until when); *Afterwards*; *Deadline* (the days
  to it and the step, marked overdue when its date has passed, or, with no date, when the deadline has).
- **Properties**: `deadline`, `next-step`, and the archive's watch fields: `keys` (the Jira keys to follow),
  `posted` and `channels` (Slack permalinks), `watch` (defaults to the deadline plus 14 days; empty stops it),
  `watched`, `last`. The 13:00, 17:30 and 19:00 afterwards passes read the page like an archived note and append
  one dated line per source per day under its Afterwards.

Home lists each project below the line with its days left; the fourth line names a project's step instead of the
program's only when the deadline is under 14 days away and the step is overdue. The all-notes base has a *Projects*
view.

## The verbs

| verb | does | writes |
|---|---|---|
| `ela project list [--json]` | every project: key, deadline, days left, open asks (its notes waiting on the owner's word), title | nothing |
| `ela project show <key> [--json]` | one project's facts, asks, notes, keys, threads and watch | nothing |
| `ela project new <key> --deadline YYYY-MM-DD [--title T]` | the folder and the page with the head skeleton (Goal, Deadline, Parties, What is known, Next step) and a first tail; refuses an existing key | the vault |
| `ela project keys <key> --add MH-… [--json]` | adds keys to the page's `keys`, deduplicated | the page's front matter |

Exit codes: 0 ok · 2 usage or site · 3 no such project (or it exists already, on `new`).

## What the sync does on its own

- Infers `project: <key>` on a note that has none when its `keys` (or, for a verification, its ticket) are among
  exactly one project's `keys`; written into the note's front matter, nothing else of it touched.
- Lints: a `project` page outside `projects/<key>/<key>.md`; a `project: <key>` whose folder does not exist.

## Judgment

- The desk writes the first page and moves readings into the folder; the script only makes the skeleton. Write the
  head in the owner's words, a date on each step, so Home's fourth line can tell overdue from pending.
- Keys and threads are the watch: add a ticket only when the project depends on it, or the Afterwards fills with
  noise. The project concept stays in the vault for now (the owner's ruling of 2026-11-04): there is no
  `project:<key>` Jira label, and `ela project` writes nothing to Jira.
- Skills that write notes (`breakdown`, `explain`, `digest`, `verify`) do not yet take `--project`; set the
  property on the note by hand until they do.
