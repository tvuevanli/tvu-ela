# 0017 — Name order is time order

Status: accepted, 2026-11-12. Amends ADR 0015's naming rule; the rest of ADR 0015 stands.

## Context

The desk's brief of 2026-11-12 (`<runtime>/drafts/2026-11-12-naming-iso-brief.md`): a meeting note named in the compact
form, `meetings/20261112-sync-eng-qa.md`, sorted after `2026-11-13-scrum-pm.md` in the file list, so the day's note was
not where a reader looks for it. Two exceptions in the note standards allowed this: the meeting spec accepted
`<yyyymmdd>-<key>`, and the plan spec accepted an undated `releases/<line>/release-<line>-<what>-test-plan.md`.

## Decision

- **Every note with a `date` property is named `YYYY-MM-DD-<kind>-<what>.md`**, the date hyphenated ISO and nothing
  else. In `meetings/` the folder is the kind: `YYYY-MM-DD-<key>.md`. In `releases/<line>/` the kinds are promote,
  deploy, docker, hotfix, review and sync; a test plan is `<date>-plan-<what>.md`.
- **Only standing pages are undated**: a release line's record, train, dev list and test lists, the lanes and docker
  pages, the open-questions page, today.md, a project's page, and the verb's `meetings/<key>.md`. In any folder the
  dated notes read in time order and the standing pages group after them.
- **The lint names a dated note whose name does not start with its date.** ela does not rename a hand-written note
  silently: `ela vault rename OLD NEW` renames it in one step under the vault lock (the old name kept as an alias,
  links rewritten, the close log given a `renamed_to` row, the records followed).
- **A rename is followed, not mourned.** The open questions' sources, the manifest and the gone-by-hand pass resolve
  an old path through the close log's rename rows and the aliases: a renamed note is not reported as vanished and its
  boxes are not seeded again as new questions.

Rejected: accepting the compact date and sorting by the `date` property in a generated index. The file list is what
the owner reads in Obsidian; an index he must open first does not fix the list. Rejected: renaming non-conforming
notes during the sync. A hand-written note is the owner's; ela names it and offers the verb.

## Consequences

- The questions pass reads a note's meeting date from its property, its title or an ISO prefix; a compact name gives
  none of the three from the name alone and is a lint line.
- A report ruled in place (`ela/system.md`, a project's design) carries a date and is not on the standing list, so the
  lint names it; whether such reports join the standing list is the owner's call on the desk's list.
