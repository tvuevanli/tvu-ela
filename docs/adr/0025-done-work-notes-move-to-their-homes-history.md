# 0025 — Done work notes in ela/ and reference/ move to their home's history/

Status: accepted, 2026-11-26. Amends ADR 0015 for done work notes in `ela/` and `reference/` only. ADR 0015's two
states, its subject homes and its rule that a live note's move changes a property and never its folder stand; ADR
0017 (the logged rename) stands and is the means.

## Context

Under ADR 0015 a done note stayed where its thing lives and nothing aged out. By 2026-11-26 `ela/` held 13
permanent pages beside 15 dated plans, done and live at one level, and `reference/` the same; only release lines moved
their done notes, through `tidy_releases`. A note moved by `ela vault rename` with its name kept left every link that
spelled its old folder broken, because the rename rewrote links by name only; about 20 such links were found. The plan
and its three adversarial rounds are the vault note
`ela/2026-11-26-plan-permanent-pages-apart-from-working-notes.md`.

## Decision

- **What moves.** A note whose type is a work type (decision, plan, sprint, review, ticket, verify, verify-plan,
  draft) and whose status is `done`, at the top of `ela/` or `reference/`, moves to that home's `history/` under the
  same name. Nothing else moves: a live note, a permanent page, a report, a case. A project's notes stay with it; the
  project leaves as a whole folder when it ends. Release lines keep `tidy_releases`.
- **When.** Only once quiet: its `archived:` stamp is before today (a done note without one is stamped and moves the
  next day), its text is what the sync last wrote (the manifest's `wrote` digest) or the vault's own, and it is not
  open in Obsidian's workspace. A namesake already in `history/` holds it for the owner's word, never a silent skip.
- **How.** Each move is a rename row in the close log, by ela, tagged `pass: tidy` and a batch id, written before the
  file moves, so a crash between the two never reads as the owner's deletion and the sync and the records follow it.
  A batch is all or nothing: a failed move puts back those made and logs their reverse. Path links to a moved note
  are rewritten, keeping `#heading`, `#^block`, the alias and a table's escaped pipe, in the notes the vault owns; a
  page the sync generates links such notes by bare name, since a rewrite there is undone by the next sync. Links from
  outside the vault resolve by the note's name, which is kept.
- **Who runs it.** The sync, after the status fixes, at most ten moves a run, and only once armed: the first
  `ela vault tidy --apply`, run after its dry run was checked, arms it. `ela vault tidy --undo <date|batch>` replays a
  batch backwards through the same move and appends rows tagged `undo_of`; nothing is taken out of the log, and a move
  undone resolves to the original path in the rename map.
- **Not in this decision.** The weekly list of live work notes gone quiet waits for a body digest per note in the
  manifest, since file times cannot tell quiet: bulk passes and stamps touch many notes at once. No note is retyped,
  asked about or closed by age.

## Consequences

Each home's top level shows its permanent pages and the work still in play. Every plan stays reachable in one list
through the Plans view of `ela/all-notes.base`, grouped by folder, without a plans folder. A citation of a plan by path
in a tracked file goes stale when the plan moves; its name does not, so a citation names the plan's file name.
