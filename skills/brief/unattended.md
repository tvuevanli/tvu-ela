# The brief, unattended: the runner's morning judge

Part of ela's brief skill, read when the skill was started with `--page`. `§` numbers name sections of `SKILL.md` beside this file; the other
parts are `unattended.md`, `page.md`, `files.md`, `meetings.md` and `reader.md` in the same folder.

## 3b — when the runner asked (unattended): the page and the numbered actions, written to files

**The runner's day** (ela-runner): 07:45 the morning page, landed by 08:30 · 12:30 · 17:30, after the QA deploy · 19:00 the evening
(replay, the reader, the carried verdicts) · 01:00. The hours of the owner's day, his DM window and holidays are
`ela day --json`, never constants.

**QA's cycle.** QA-AWS3 receives a build around 17:00 and QA tests it until the same hour the next working day; the
report comes that evening, after 17:00 and often later, so the 17:30 pass may not see it, the 19:00 run usually does,
and the next morning reads it otherwise. On the morning of D, `ela day --json --date D` names `verdict_build`, the
newest build QA reported on (sent D-2, reported D-1 evening), and `under_test_build`, sent D-1, with the day its
report is `due` (an evening, never an hour). The lanes page lists the last three days' builds under its table. A
train item and every lane judgment use the verdict build; a Wednesday promotion is on Monday's 17:00 build. The build
under test is named as "under test · report due this evening", and is never "untested", "no QA report yet" or a
reason to hold a train: a hold is drafted only when the verdict build has a fail or a ticket gap. A report that
says the build's own focus went untested (`report.untested`, verdict partial) is such a gap, and the item names the
untested tickets. A build whose due
evening passed with no report (`report_missing_build`, "report not received" on the lanes page) is a gap to ask QA
about, not a fail. page-check flags a sentence that calls the build under test untested or unreported. *Why:
the 2026-10-29 page held the train because build 78 had no report, while QA was testing it that day.*

**A second morning run on the same date** rewrites the page, never the record of what was done. The actions already
in `<date>-actions.json` with `applied` or `by_owner` keep their number and text, and their item is not offered
again; new drafts take numbers after the highest one in the file, so an `apply N` he has seen never names a
different write. The carried count reads one page per date, so a rerun does not add a morning.

**The last reader's findings are input.** When the runner names the previous working day's
`<reports>/review/<D>-reader.json`, a `wrong` claim is not restated: the page states the fact from its source, or
leaves it out. A `handed-back` item's work is done first, within the run's deep budget, and the item carries the
result. *Why: without the findings reaching the morning, the evening reader only describes the page and the next
page repeats its faults.* A rerun writes
`<date>-changes.md` again from the same facts counts as the brief, so the two pages never come from different
runs. A "rewritten HH:MM" stamp is the clock when the file is written, never a planned time. A "since HH:MM" in the
opening anchors on the facts page's last line ("last morning page he could have read: <date>, in the vault since
HH:MM"), or is left out. ela-runner checks all three after the run (537d52e, c1d7113); the check is the backstop,
not the rule. *Why: the 2026-10-28 rerun left the Changes page at 06:41 and stamped a file written at 08:31 as
"rewritten 08:40".*

**Counts come from one file.** Every count on any page comes from the facts pass's counts (`counts` in
`<runtime>/runner/<date>-changes.json`, from `ela changes --json`), each with the window it covers: commits, commits
without a ticket, tickets moved, builds, lane moves, jobs, ela's writes, close-ready and verified-not-fixed (the
board's stage rows, the tickets open now, the verifications, each ticket's own page); the sprint's on track / at
risk / off from the sprint line. That means the brief, Changes,
the board, the sprint line and Home. A page never counts for itself. A count over another window is labelled with
that window ("commits, 7 days"). *Why: on 2026-10-27 close-ready read 32 on the board, 31 elsewhere and 35 on the
sprint; jobs read 16 on the brief and 19 on Changes; commits read 111/173 on one page and 79 on another.*

ela-runner starts this skill headless every weekday morning after it wrote the facts page
(`/ela:brief --page <reports>/runner/<date>.md`). Then the output of §3 is written, not only printed:

- `<reports>/runner/<date>-brief.md` — the page of §3 as Markdown, the judgment included (what each new
  ticket is about, who should hold it, the drafted reply or nudge), then §2b's `Yesterday`, every key a Jira
  link.
  The page follows the form in `page.md` exactly and fits **900 words** (the vault marks a day page over 1,200 with a
  warning).
- `<reports>/runner/<date>-actions.json` — the drafted actions as a list, in the page's order:
  `[{"n": 1, "text": "<the one line the page shows>", "command": "<the exact ela command, dry run as written>", "kind": "comment|assign|label|transition|close|slack|fixed-in",
  "tier": 1|3, "rule": "<a closed rule, or null at tier 3>", "evidence": "<one line; tier 1>"}]`.
  `text` is the decision as today.md shows it: one whole sentence of at most 20 words, never cut, naming the ticket and
  what the write does. Two writes on one ticket that serve one decision (a hand-over comment and the assignment)
  share that sentence: today.md shows them as one ask whose box applies both.
  The runner adds what it did: `applied` (a time), `failed` (`{at, error}`).
  A command is one of ela's own write verbs — `ela jira comment|assign|label|fixed-in|close …`, `ela slack
  post …` — complete with its key and text (a `--from-file` under `<reports>/runner/actions/<date>/`), and
  runnable as it stands; the runner appends `--apply` to it when the owner answers `apply <n>` in Slack or on
  the page. A file under `actions/<date>/` exists only for an action in the list: a draft the session abandons is
  not written, or is deleted before the run ends, and page-check names a file no action points to. Nothing else
  goes in the list: a reading, a question for the owner, a hand-off to another skill is
  text on the page, not an action. The session itself applies nothing (the write scripts refuse `--apply` under
  `ELA_NO_APPLY`).
- `<reports>/runner/<date>-deep.json` — the day's deep picks, at most two:
  `[{"key": "MH-2406", "lane": "prod-3", "why": "<one line: what was claimed and what doubts it>"}]`; `[]` when none.

The other files of the run (a build's record, the Jira reconcile, the Changes page, the Friday page) are `files.md`.

## The numbered actions and their tiers

- **An `apply N` is a drafted action on this page.** Number the actions in the order they appear, every one
  written beside its item; within an item the numbers ascend (a rerun that keeps applied numbers may leave gaps,
  never a descent: list a kept number before the new ones), and page-check flags a descent; never name an action that is not on the page ("apply 1 is done" from yesterday is
  noise). An action already applied is said in words, without its old number.
  A number is minted only when its drafted write is in `<date>-actions.json` and its box is on the page, beside
  its item. A table row, the backlog and an answer to a vault line never name a number without that box, and a
  number from another day is never cited. Before the page is written, `ela page-check <page> --actions
  <date>-actions.json` checks every `apply N` in it; a number with no action, or named without its box, fails the
  page. *Why: the 10-27 Backlog named apply 4, 5 and 6 with no boxes, and the 10-26 answers cited apply 9 and
  11–16, which never existed.*
- **Every drafted action has a tier.** Tier 1, ela acts at the pass that drafted it and says so: Jira only, under one
  of the closed rules `fact-comment` (a comment stating a fact, carrying its evidence), `label`, `fixed-in-ledger` (a
  Fixed In the builds ledger confirms; never a clear) and `assign-by-rule` (an assignment a closed routing rule
  gives); never a terminal status, a close, a transition or a customer-facing field. Tier 2 is retired
  (2026-11-12, the owner's rule: nothing posts to Slack on its own except the daily and weekly reports; elak
  working-with-evan.md): a thread reply, a train hold or a train promote is drafted at tier 3 as `apply N`, still an
  `ela slack post <thread permalink> … --team-thread`, and leaves only on his approve; page-check fails a tier-2
  action and the runner refuses one. Tier 3 is everything else, on his word only
  (`apply N`): customers, prod approvals, people, anything addressed to him, anything no closed rule admits. One tier-3
  rule is a meeting's list, `meeting`: an `apply N` that posts it in that day's thread (`meetings.md`); the meeting's note
  carries no box for it. `qa-today` and `dev-today` (QA today and Dev today, §3)
  are on demand, drafted only when he asks and sent on his word; either may make the day post, `ela slack post #<team channel> … --team-day-post` (Dev today only that), which slack.py refuses when
  ela already posted top level in that channel that day. `test-list` (the 19:00 post) is retired; page-check fails an
  action drafted under it (decisions/2026-10-29-writes-run-in-three-tiers.md, amendment 2026-10-30). A tier-1 action carries `evidence`, one
  line he can check; a train action's evidence names the verdict build and its QA report (`ela day --json`
  `verdict_build`). Read `<reports>/review/tiers.json` first: a rule marked `demoted` (three corrections in seven
  days) drafts tier 3 until it clears. `ela page-check` checks each tier against its rule and its form on the page.
  *Why: 62 drafts in the week of 2026-10-26 and one applied; most were writes a closed rule could have taken
  (vault in-progress/2026-10-29-ela-three-loops-review.md, proposal 2).*
- **At most three `apply` boxes stand open.** The items are written in rank order until their `apply` boxes
  total three; every item after that goes, with the same heading, facts line, bullets and Do lines, under one
  folded callout `> [!note]- N more` (N: the items folded), each of its lines prefixed `> `. A tick inside the
  fold counts as on any line, and page-check fails a page with a fourth open `apply` box. *Why: Home promises at
  most three `apply` boxes and the 2026-11-02 page carried 22 in 718 words; the budget counts what stands open
  (vault to-read/2026-11-02-ela-and-vault-workflow-review.md, fix 4).*
- **Instructions written in the vault.** Run `ela vault guidance --json` first: each line in a note starting
  `ela:` (in any note, unhandled) is something he asked; the Slack service normally acts on it within minutes, so
  one still listed here means it was not, and it becomes an item, or its drafted write an `apply N`. Append each id
  you handled to the log the command names.

## What only the unattended run drafts

**A change on a tracked ticket** (one with a probe `fix` page, in the sprint, routed by him, or with an `apply N`
pending) is read on two axes, by the closed list in `skills/probe/SKILL.md` §fix — a change on a tracked ticket:
understood means it matches one rule (Review on a branch whose commits name the key; QA's version and verdict;
Fixed In equal to the ledger's carrying build; an answer to a question the timeline holds; Done after a QA pass on
the lane's version; progress from the assignee or a developer on an In Progress ticket, asking nothing and naming no
new version; an assignment consistent with the status; a developer naming a version the ledger confirms), and anything
else is unsure, as is a developer reporting it still fails; a sure row whose furthest fix lane disagrees with the status
(on QA while Backlog, on prod while In Progress or before QA's verdict) becomes unsure with that reason. Understood and no word needed: a timeline row and a count on the
Changes page, never an item. Understood and word needed: one item, A or D. Unsure: one item, C or D, whose first
line says what ela could not place; on a prod ticket or a customer ask the runner also DMs him at the pass. Addressed
to him (his name, an assignment, a question): always a C item, whatever the reading. *Why: an item he cannot act on
costs his attention, and a change ela cannot place must never pass as a quiet timeline row.*

`lanes.tracked` holds these already grouped, one row per ticket over the brief's window (24 hours, 72 on a Monday):
`class` C when a change is addressed to him, its `first_line` who said what; D otherwise, its `first_line` "ela could
not place: <reason>". Each is one item with the moves a ticket page offers (seen, go-deep, nudge), merged by key with
any item the brief already has for that ticket. Sure rows are not on the page; the runner's *Tracked tickets* section
stays as their evidence.

**Two build rules** come through the same log (`rule` on the finding), read from the lanes' test lists once a day:
`qa-on-secondary`, a ticket assigned to QA that rides under another owner ticket in a build (its `linked`), drafted as
the tier-3 write the finding's `draft` names (reassign to its developer, the comment naming the owner ticket); and
`no-ticket-in-build`, a build's change-log line with no key, keyed by the build ("QA-AWS3 build 78"), drafted as a
tier-3 ask in that build's release thread for the ticket. This replaces the ad-hoc nudge for a build change with no
ticket. *Why: one fix, one owner ticket, assigned to QA when the whole fix is on the lane; a fix with no ticket gets
one before its build is announced (the 2026-10-29 test-list plan, Resolution C).*

**What an item owes before it reaches the page.** A train item (a build riding the next promotion) carries the
`/ela:promote` assessment's verdict for that build (the day's stored report, `<reports>/promote/<line>-daily-prod.json`,
written by `ela promote report` and read by the lanes table; the verb is not run again) and the train's
departure time from the release cadence recorded in elak, or "departure not recorded" when none states it; the
apply is the hold or the promote post that verdict supports. Its QA facts cite the lane's test list
(`<reports>/lanes/test-list-<lane>.json`, or the train `<reports>/train/<line>.json`, whichever is newer): the P1
rows without a verdict, each by key and the reason it ranks P1, or "no P1 row open";
never "no QA report yet", which names a mail instead of what is untested. A customer incident addressed to him takes the first
deep pick, before any other pick and any Backlog item, and its item carries what the logs and the graph showed
(`/ela:logs`, `/ela:graph`), not an uninvestigated lead. *Why: on 2026-10-28 item 1 offered hold or promote with no
assessment and no departure time, and item 8 answered support with a lead nobody had read.*

**The morning count.** Each item above the fold (below it, the vault titles the fold *Also noticed*, takes the boxes
off the writes today.md does not show, and nothing is counted or aged) ends its facts line with the number of mornings it has been carried ("3rd morning"),
read from `lanes.carried` (`ela brief --lane carried`): the earlier brief pages, by key, or by heading for an item with
no key. A sentence elsewhere on the page that counts carried items ("three drafts are on their fifth morning") reads
the same count, and page-check flags one the facts lines do not bear out (2026-10-29: the summary said four on the
fifth morning; the items had three, and one on its fourth). An item on its third morning means the brief failed to make it tickable: that evening's run rewrites it as an
`apply N`, or drops it with one line on the next page saying why. The evening writes its verdicts to
`<reports>/runner/<next workday>-carried.json` (`[{item, verdict: rewrite|drop, command, why}]`), and the facts page
shows them under *Carried three mornings, rewritten last evening*. The morning mints each `rewrite` as an `apply N`:
its `command` goes into `<date>-actions.json` and its box onto the page under its item, so `ela page-check` passes.
Each `drop` is one line under the facts line, its `why`, with no box and no number, never an item. When page-check
fails and the runner asks for a rejudge, the judge reads the lines page-check printed (each orphan or unboxed number)
and either mints the missing action and box or removes the number, then writes the page again. *Why: items carried for days with nothing
he could tick became the page he stopped reading (from 2026-10-28).*

**Priority and due dates by rule** (the Jira plan of 2026-10-29, rules 1 and 2). Highest: a prod incident or a customer
blocked, due today. High: needed on the next train, due the train's departure. Medium: this sprint or month. Low and
Lowest: backlog, no date. An In Progress ticket with no due date is due at the sprint's end (a sprint ticket) or the
next train's departure (a train fix); a Review ticket the next evening (QA's report). The intake rates priority and
component from the evidence it already reads (a customer's bracket, an incident, a prod lane, the next train). A
change is drafted as `ela jira priority KEY --to P --why "<rule>"` (rule `priority-by-rule`; it only raises, never
lowers what a person set) or `ela jira due KEY --date D --why "<rule>"` (rule `due-by-rule`; never moves a date),
tier 3 until he promotes the rule. The Ticket lanes open with two rows, each a count and its oldest ticket with
the title, never items and never a run of keys:
"overdue: N · oldest MH-a <its title> · +M release tickets" (`lanes.overdue`, `first`, `release_tickets`: the
project lead's release-tracking tickets, a `release:` label or an Epic or Project, which are bookkeeping, not a
commitment) and "due this week: N · …" (`lanes.due_week`), then
"Highest/High untouched 14+ days: N · oldest MH-x <its title>" (`lanes.tracked.high_untouched`). One becomes an item only
when the ticket is addressed to him or is a customer incident; the eight-item cap and Home's three stand. The
findings file keeps every one for the ticket pages and the replay.

