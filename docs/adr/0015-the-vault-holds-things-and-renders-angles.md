# 0015 — The vault holds things and renders angles

Status: accepted, 2026-11-11. Supersedes ADR 0010 (the layout by what the owner does with a note, and its
amendments) and the vault readme's layout section. ADR 0014 (today.md, asks that expire) stands. ADR 0008's one-way
rule and reading gate stand.

## Context

The desk's briefs of 2026-11-10 (`<runtime>/drafts/2026-11-11-vault-things-and-angles-brief.md`,
`<runtime>/drafts/2026-11-11-vault-migration-brief.md`) record the owner's steer on the from-zero design: the things he
tracks are all in the vault already, and what differs is the angle each reader needs. Laid out by what he does with a note (ADR 0010), the
vault filed the same facts again by document type and by life stage: a plan in `to-read/`, then `in-progress/`, then
`parked/` or `archive/`; a release review in `mh/releases/`, its line's lists in `lanes/`; a project's evaluation in
`to-read/` while its page sat in `projects/`. A thing he tracks was spread over four folders. A note's place changed
with every move, so links pointed at old folders and an ask lived in two places at once: on the note, and echoed on
the project page.

The vault's own record (2026-11-10): of 172 notes, he opened today.md, the project pages, the notes in to-read, the
meeting page and some of archive. He never opened the board, recent, One Thing, the constraints page, the lanes
lists or a reader page, and wrote no answer on them. Every write to Jira or Slack happened in a session.

## Decision

- **Things and angles.** The vault stores no second copy of the facts. It holds *things*, which he tracks, with one
  home each and everything about the thing in that home, and *angles*, which are rendered from the things for one
  reader at one moment and store nothing of their own.
  - `projects/`: a requirement one person carries (Jira `kind:project`) or bounded outside work. One page
    `projects/<key>-<slug>.md`; a folder `projects/<key>-<slug>/` with the page inside once its plans, evaluations
    and reads sit beside it.
  - `releases/<line>/`: a release line. `record.md` is the way in; each promote, deploy, docker check and hotfix is a
    dated note; the line's train, dev list and test lists live here. `releases/lanes.md` is the overview across lines.
  - `cases/`: a customer incident.
- **Eight roots**, in full lowercase nouns: `today.md` · `meetings/` · `projects/` · `releases/` · `cases/` ·
  `reference/` · `ela/` · `archive/`. `home.md` points to today.md until 2026-11-25 (ADR 0014).
  `reference/` keeps what serves no single thing (a product review, engineering management, the day pages, One
  Thing, dropped asks); `ela/` is ela's own; `archive/` keeps what he put away.
- **Naming.** Lowercase nouns joined by hyphens. A dated note is `<date>-<kind>-<what>.md`, and its folder carries
  the subject: `releases/2.1/2026-11-09-deploy-daily-wed-to-prod-3.md`, not `…-mh2-1-…`.
- **Two states for a work note**: `status: live` or `status: done`, a property on the note in its thing's folder. A
  move changes the property, never the folder. A done note is the record: the sync never rewrites it, and its
  Afterwards watch runs as before. A case keeps its own states (open, answered, closed); a report keeps proposed,
  decided, superseded. `next` stays the owner's chooser, and each move sets the state.
- **An ask is stored once, on its thing.** today.md shows it as one line linking the thing (ADR 0014's cap and
  expiry apply). A project page no longer echoes its own open questions, and once its notes sit beside it the page
  has no "Waiting for your word" section.
- **An angle is generated daily only if something consumes it**: the owner (opened or answered, per the record), a
  verb, or the runner. The board, recent, the constraints page, the weekly page and the reader pages stop being
  generated into the vault. Each verb still renders them on demand and keeps its source under the reports root.
- **One migration**, `ela vault migrate`: a dry run by default that lists every move, rename, link rewrite and alias;
  `--apply` under the vault lock, each move logged with `renamed_from`, old names kept as aliases, links rewritten.
  The sync does not run it: it refuses to write a vault still in the old layout. For 14 days an old path given to a
  verb is read as its new one.

Rejected: keeping the lifecycle folders and only adding `projects/`. That is today's spread, with one folder more.
Rejected: folding every evaluation into its project page. A page would outgrow one screen; a note beside the page,
linked from it, keeps the page short and the evaluation whole.

## Admission (ADR 0006, a modification)

1. Scenario: the vault row of `docs/capabilities.md` (S1), unchanged in purpose.
2. Workflow: the readme in the vault (`ela/about-this-vault.md`) becomes one screen: the model, the eight entries,
   the naming rule.
3. Duplication: removed. A thing has one home; an angle holds nothing of its own.

## Consequences

- The manifest records layout 5 and the migration's moves, so a verb given an old path finds the note until
  2026-11-25.
- ela-runner reads paths that change (the project head boundary, `one-thing.md`, the morning page, `in-progress/`);
  its worker follows the migration's list.
- A test fails if a folder of the old layout is written by the sync again.
