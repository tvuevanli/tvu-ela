# The brief, unattended: the other files of the run

Part of ela's brief skill, read with `unattended.md`. `§` numbers name sections of `SKILL.md` beside this file; the other
parts are `unattended.md`, `page.md`, `files.md`, `meetings.md` and `reader.md` in the same folder.

The run that wrote `<date>-brief.md`, `<date>-actions.json` and `<date>-deep.json` (`unattended.md`) also writes:

- `<reports>/releases/<line>/<date>-build-<n>-to-<lane>.json` — **once per build a lane took in the window**, when no
  record for that build exists yet (`ela release changes <lane> --json`): what the build changed, by service and
  purpose. `{"line", "lane", "lane_name" (as the team says it: QA-AWS3), "build", "date", "at", "source", "services":
  [{"service", "from", "to", "for", "keys"}], "notes"}`. `for` is what the change is for, at most 15 words, whole,
  composed from the tickets and commits the build carries and grouped ("FloSports public API: six endpoints", not
  six titles); the ticket keys go in `keys`, never in the words. Services in the order that matters to him; today.md
  shows four lines. `ela release changes --check <file>` must say ok before the run ends. today.md's Releases fact and
  the line's release note in the vault are rendered from it; the Changes page keeps its own evidence table.
  *Why: the owner asked which services changed and what for, one line per service (2026-11-11 record).*
- **The builds' Jira, reconciled once the thread is quiet.** For each lane that took a build in the window, after its
  record exists: `ela release reconcile <lane> --build N …` (every build of the window in one call). It reads, keeps
  its reading beside the record (the release note's Jira gaps table) and raises the open questions itself (a revert
  folded into another ticket; one agent's same miss on three builds). When it prints an `ask:` line, draft **one**
  action for all of them: tier 3, rule `release-reconcile`, `text` the ask line as printed, `command` the call it
  names (`ela release reconcile <lane> --build N … --batch`, no `--apply`), `kind` `fixed-in`, `evidence` the builds
  and the reading's time, and `options` the three letters `--json` prints with N the action's number (A apply the
  batch: `apply N` · B show me each: the batch's dry run · C skip this build: `drop`). Its apply is that batch: Fixed In appends and the release label, append-only; status,
  assignee and folds are never in it. Never on the release-finished message: this pass runs at night or in the
  morning, when the thread has been quiet. Nothing is posted in the release thread.
  *Why: the engineers' release agents leave Fixed In and labels behind on about one ticket in four (builds 90 and 91,
  brief <runtime>/drafts/2026-11-12-release-reconcile-brief.md); ela is the reconciler after the release, not another
  release bot.*
- `<reports>/runner/<date>-changes.md` — the Changes page, from §2b's changes facts: a review of the day for the
  owner, not a list of what moved. The vault shows it as a day page beside the brief. Under **900 words**, in `page.md`'s
  form (a `#` title with the date, tables rather than code blocks, ticket keys bare, lanes in plain words):
  - It opens with the day in one line and what needs his word, if anything.
  - Then the sections, in this order: `## Releases and versions` · `## Docker services` · `## QA` · `## Code` · `## Tickets` ·
    `## What you did` · `## What ela did` · `## Team report`. Each opens with a one-sentence verdict; the facts
    under it are its evidence, folded in a `> [!note]- Evidence` callout, each with its source (a mail subject, a
    permalink, a build number, a sha). The page is evidence for the brief's items, so it reads in a minute folded
    and in full when opened.
    A list of tickets in an Evidence block is one row or line per ticket (key, title, status), or their count and
    a link to where the list lives; never a run of keys (`page.md`).
  - **Releases and versions**: per lane, each move as `service old → new (#build, date)`, a patch build named as
    one, a build that reached no lane as "built, not deployed", and which of the window's commits each build
    carried. The release thread's per-build lines (the tickets each carries) outrank Jenkins for what reached a
    lane. A lane whose versions are not a host read now — the QA lane since the QA environment stopped admitting
    ela's account (2026-11-04): QA's report mail or the release thread — is said so with the source and its time, from
    `lane_sources` ("QA-AWS3 as QA reported 11-03 19:07; lane not read"); a move by mail says `(reported by mail)`.
  - **Tickets**: the moves by where they went ("to Review with QA: 14, build 91's fixes"), each group a count
    with the link to its list (the build's release note, the lane's test list), then at most three tickets named
    with title and status where one needs a word: a reopen, a fail, one of his own.
  - **Docker services**, from `docker[]`: each version that moved or was announced in the window, by slug (the
    name as announced when the map has no slug), with where it landed (a lane's bundle, a QA box, a default tag) and
    its source (bundle name, mail subject, the ticket comment). The tickets it claims follow it; a version announced
    with no ticket is said so in those words. A version whose ticket has no Fixed In is an item on the brief (the
    drafted Fixed In as `apply N`), not here. *Why: docker services are announced, not built from tracked commits,
    so the commit join that fills Fixed In for the app services does not reach them.*
  - **Code** is the largest section: per repository, one row per ticket (key, title, its commits, the thread that
    discusses it; tickets one commit carries together are still a row each), then the commits without a ticket sorted into what is harmless, by category and named once
    (docs, review fixes, refactors), and the few that matter, each with why: a fix that reached a lane or prod
    without a ticket, a behaviour change riding under another ticket, correctness of billing or auth.
  - Where two sources disagree, the page says so (Helm's report calling a ticket verified while QA's mail
    tested the build before its fix).
  - **What you did** reports his own moves as done and never drafts them again; a Fixed In that Helm wrote
    under his account is Helm's (`ela.helm_fixed_in`), under *What ela did*.
  - **Team report** is one line and its Slack link; the report itself stays Helm's.
  - It carries no actions: what needs his word is an item on the brief, which links here for its evidence.
  A source the facts name in `errors` is named on the page as not read.
- `<reports>/runner/<date>-week.md` — **on a Friday, while a sprint is active**, the weekly page; the vault picks
  it up as a day page of kind week. It reports the week against the sprint, so that what the owner carried beside
  the list is visible next to what moved on it. Under **700 words**, in `page.md`'s form (a `#` title with the date,
  tables rather than code blocks, ticket keys bare, lanes in plain words), in three sections:
  - `## The sprint` — one row per goal and committed item: what moved this week, where it stands now (real
    status, read as in §0), and its "done when". The line above the table gives the day of the sprint and the
    count on track, at risk and off.
  - `## Outside the sprint` — from the week's yesterday files (§0's `week_yesterday_files`; a weekday with no
    file is named as not read): the cases outside the sprint's keys that took the owner's own time — his
    comments, his commits, the threads he answered, the tickets he broke down or routed — at most eight rows,
    each the key or thread and what it took. A last line counts the rest. This section is what makes the
    carrying-along visible; it judges nothing.
  - `## Next week` — what must happen next week for the sprint to land by its end date: per item at risk or
    off, the one move and who it waits on. On the sprint's last Friday it also gives the facts for the question
    the sprint's review answers: keep, change or drop the sprint.
  The page drafts no actions; anything to write is an item on the morning page.

