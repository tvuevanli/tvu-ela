# The brief's page: its form

Part of ela's brief skill, read before the full page is written or printed. `§` numbers name sections of `SKILL.md` beside this file; the other
parts are `unattended.md`, `page.md`, `files.md`, `meetings.md` and `reader.md` in the same folder.

## The page, by example

```
# Morning brief · Fri 2026-10-23

*7 items · read Jira and Slack; direct messages are not visible*

One to three sentences: what the day is about. Friday, so the brief is short. The one live customer problem
is Reuters.

## Needs you

### 1. Reuters feeds froze twice in two days
MH-3811 · Reuters confidence streams frozen · incident, new · Robin Wu holds it
- Both feeds froze for 23 seconds on 10-22; the same happened on 10-21 (MH-3805).
- Open lead: the shared decoder input ran at twice real time just before the stall.
- **Do:** `apply 1` records the findings on MH-3811, then probe MH-3805.

### 2. MH-3745: Jira is behind the release mails
MH-3745 · Search's recording blocks MediaHub's SRT receiver · Gabriel Liu (orchestration) · In Progress
- Fixed in orchestration 4.0.205; QA verified it on 10-22 and the daily release was requested (release mails).
- **Do:** `apply 2` posts that status and sets Fixed In.

> [!note]- 2 more
> ### 3. MH-3752: Jira is behind the CN2 release mails
> MH-3752 · China Environment B on 2.1 · Alice Wang · In Progress, Jira silent since 10-28 · 1st morning
> - Mail holds four config changes and the partial report of 10-30.
> - **Do:**
> - [ ] apply 3 — post the 11-02 status, bilingual, citing the mail thread and the report
>
> ### 4. …

## FYI

- Customer YouTube output loses audio · support holds it · the capture card reads audio at 0, so the
  customer's SDI source is the lead; nothing in MediaHub so far

## The lanes this morning

| | prod-3 | daily-wed | QA-AWS3 |
|---|---|---|---|
| media bundle | MediaHub 2.1.15 (2026-10-26) | mh2.1@daily-wed-s1-d44 (2026-10-26) | mh2.1@qa-q26 (2026-10-22) (list stale) |
| mediahub-frontend | 2.2.116+171 ○ | 2.2.116+171 ○ | ▲ 2.2.121+176 (was 2.2.119+174) ○ |

*3 more the same on every lane: …*

## Sprint

Sprint · day 5 of 10 · 8 on track · 1 at risk · 0 off

| item | where it stands today | on track for 6 Nov |
|---|---|---|
| MH-3768 generic MXL | merge request open for the app layer; J2N option name still unanswered | at risk: J2N's owner has not replied since 10-28 |
| MH-2406 Insufficient Resources UX | the mediahub-frontend change is in QA; no verdict yet | yes |

## Yesterday

At most three lines (§2b), then [[2026-10-28-changes|What changed]].

## New tickets

| ticket | what | holder | owes |
|---|---|---|---|
| MH-3809 | two Packs could not push; China cloud capacity, resolved | Robin Wu | nothing; close on customer word |

## Ticket lanes

| lane | today |
|---|---|
| In Progress, gone quiet | 3 silent over 48 hours (longest MH-3745 Search's recording blocks MediaHub's SRT receiver) · 7 blocked · 102 untouched for 14 days |
| new and unassigned | none overdue · 8 recent tickets without a layer prefix |
| customer incidents | 54 open; Reuters freeze ×13 is the big cluster |
| needs a breakdown | 7 without sub-tasks; MH-3794 and MH-3795 first |
| standing constraints | 1 active, every pin held |

## Backlog, today's three

| ticket | verdict | why |
|---|---|---|
| MH-1555 | close | release checklists now live in the promotion threads |

*Not read: Slack direct messages; channels the bot has not joined (Reuters, FloSports).*
```

## The form

**One place per day.** An item appears once. A key inside a lanes-table cell or a Changes page callout is evidence,
not an appearance.

**A due release of `<published>` is one line, never an item.** `release_due.line` in `<date>-brief.json` (`ela pick
release_due.line --file …`), when it is not null, is the first bullet under `## FYI`, copied as it is: no box, no
number, no Slack post, nothing committed. It comes back every morning until he releases (`ela publish release
--apply` on his word), because brief.py reads the verdict once a day and the release changes it. A `release_due.error`
is named in the gaps line. *Why: the team's knowledge is released only on his signal, and nothing else reminds him
that one is due (elak decisions/2026-11-25-published-knowledge-is-a-versioned-release.md).*

The page is read in Obsidian, so its form is fixed:

- **An item is a `###` heading in plain words** (what is happening, never a lane tag such as `[cadence RED]`), one
  facts line (key, its Jira title in a few plain words, kind, who holds it, age), at most three bullets, then
  then **Do:** as one to three task lines, each finished work by ela, written by the action's tier (`unattended.md`):
  `- done N — what ela wrote · evidence: …` for a tier-1 action (a line, no box), `- [ ] apply N — what it writes` for a tier-3 one (every Slack post among them; no box sends on a timer), or `- [ ] <option>`
  for a decision (class D), where the tick is the ruling. Ticking a box without `apply N` runs nothing, so its line ends with where the decision is
  taken: `· decide at the 10:00 scrum`, or `· your call, no write`; page-check flags a box with neither. *Why: on
  2026-10-28 items 1 and 7 offered four such boxes, and the page did not say that ticking them wrote nothing.*
  An item never ends in a question to him. An open point is written as ela's recommendation and the alternative,
  each with its reason, and the first box is the recommended write as `apply N`; `your call` is used only when the
  two are equal on the evidence, and the item says why. *Why: on 2026-10-28 item 5 asked whether MH-2406 stays with
  its assignee or goes to the frontend owner, and which frontend carries the notice, and drafted neither.*
  A Do line is never a command for him to run or a draft for him to write. A breakdown, a
  draft, a lookup or a probe is done before the morning page, and the item carries its result: an `apply N`, or a link to the
  note it produced. When ela cannot do it unattended (it needs a login, a person to ask, or a judgment only he
  holds), the item says why in one line and offers no box. No Do line without a box. A deep pick runs in the same
  morning pass (§3b) and the item links its page, so an item never offers "go deep on MH-…". The recommended choice comes first; no "skip" choice
  (leaving it unticked is skipping). A sentence that does not change what the owner does is cut. *Why: on
  2026-10-27 the eight items carried 13 Do lines. He ticked the three apply lines and none of the ten commands or
  drafts left for him.*
- **One close path, named as such.** A close ela proposes goes through the board's batch (one confirm posts the
  proposals); a close the owner names is `close MH-…` in a session. `ela stage` reads a ticket's lanes; it closes
  nothing, so it is never written as the way to close.
- **A verification outranks a close.** Before an item or a table row says a ticket can close or be dropped, read
  its latest result under `<reports>/verify/`; a FAIL or BLOCKED after the fix is the item, not the close
  (2026-10-23: the page said drop MH-3416 while two of its verifications had failed).
- **At most eight items** under *Needs you*, merged and ordered as §3 says; the rest of the facts are in the tables
  below, one row each. An item is a facts line with its real status and one action line of its class.
- **The lanes this morning** is the table `ela matrix` printed, pasted as it is from the runner's facts page (the
  runner runs it after `ela changes`), under its own heading after *FYI*. It is not retyped or summarised: the same
  table is embedded in Home and must read the same in both places. It shows the morning's line only (its budget);
  the pointer line under it (`2.0 on [[lanes]]`) names the other lines the lanes page renders, one section each.
- **At most five lines** under *FYI*, each a thread §2a rated FYI: what to know and who holds it, no **Do:**.
  Beyond five, a count in the lanes table; the section is omitted when empty.
- **The sprint is a table after the lanes,** under `## Sprint`, from §0's sprint read. Its first line is exactly
  `Sprint · day N of M · x on track · y at risk · z off`; Home embeds that line. Then one row per goal and
  per committed item, at most nine rows (goals first, in the note's order). Columns: the item (its key and a few
  plain words, or the item's own words when it has no key) · where it stands today, its real status in one clause
  · on track for the end date: **yes**, **at risk** or **off**, the last two with one reason. A row is judged
  against its "done when" and the working days left, not against Jira's status. A sprint item that is also a
  *Needs you* item keeps its row, whose status cell points to the item ("see 2"). The section is omitted when no
  sprint is active.
- **Every ticket key carries its Jira title** where it first appears on the page, in a few plain words, so the
  reader knows the ticket without opening it.
- **A key never stands in a run.** Three or more keys with only punctuation between them are written nowhere on a
  page, an Evidence block included. A list of tickets is one line or one table row per ticket (key, its Jira title,
  status), or, where that would take the page past its budget, their count and a link to where the list lives: the
  service's section of the build's release note (`[[releases/<line>/<build note>#<service>|N tickets]]`), the lane's
  test list, the train. A row of *New tickets* is one ticket. `ela page-check` names each run as a `lint:` line.
  *Why: a run of keys cannot be matched to the words beside it without opening Jira (the vault's note standards,
  the key and title rule of 2026-11-12).*
- **A ticket appears once.** A new ticket that is already an item gets no row under *New tickets*.
- **Tables, not code blocks,** for anything with columns; no nested lists; no bold paragraph labels.
- **Ticket keys bare** (MH-3811): the vault and the runner turn them into links. Slack threads and other pages
  are links with a short label.
- **Services by their slug:** mediahub-frontend, mediahub-backend, unified-media-frontend, unified-media-backend,
  orchestration; a team name carries the slug once (UR Caller (unified-streaming)). Never "the frontend" or "the
  backend": unified-media-frontend is a frontend too, and the reader cannot tell which is meant. The same holds on the
  Changes page.
- **People by their roster display name** (`$TEAM who`), in prose, apply lines, FYI and tables alike: Andy Zhao,
  never the Jira or Slack name a read returned (Andyzhao). page-check flags a roster person written by their Jira
  name. *Why: the 2026-10-28 page wrote Andy Zhao in prose and Andyzhao in three apply lines, FYI and New tickets.*
- **Ticket lanes in plain words,** as in the table above: never ela's internal names (cadence, zombies, triage, stage,
  runner page) on the page.
- **Under 900 words in all.** The decisions lane, when it runs, adds one table row per candidate with its
  permalink; the owner chooses which to keep. Over the vault's day budget, page-check prints a `budget:` line
  counted the way Home counts; the runner's repair shortens the page, dropping nothing he must decide: FYI and
  Yesterday first, then sprint rows that only say "see N", then any meeting-section line that restates an item,
  which becomes "item N". *Why: the 2026-10-28 reader listed exactly these as what he would skip.*

