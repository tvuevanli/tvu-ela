# 0011 — The owner's word in the vault commits elak; agreed builds wait on a branch

Status: accepted, 2026-10-26. Supersedes ADR 0001's "committed after the diff has been read" for the two cases
below; the rest of 0001 (no hook adds, commits or pushes elak; the SessionEnd hook only reports) stands.

## Decision

- **His word in the vault is the hand.** *accept* on a built note, and *confirm* on a note that proposes a standing
  constraint, are the owner's word for exactly what the note shows: ela commits it to elak. Nothing else commits
  elak unattended.
- **An agreed build waits on a branch.** A plan names its `target`. For a repository inside the ela system (ela,
  ela-runner, elak, Helm) the runner builds in a worktree of that repository on branch `ela-build/<note>`, under its
  own rules, commits there and never pushes. *accept* rebases the branch onto the repository's current branch and
  fast-forwards it; *not-done* continues on the same branch. A plan whose target is MediaHub records rulings and
  drafts, and builds nothing.
- **Outside the ela system ela only reads.** Product code and environments are never written by an unattended
  build; a write to Jira or Slack is a drafted `apply N`.

## Reason

An agreed ela change ended with nothing built: the build session ran in a scratch folder and the location guard
refused edits to ela from there. Running in the target's own worktree applies that repository's `CLAUDE.md` and
guard, and a branch keeps every unattended commit off main until the owner has seen the result. The review 0001
protects is still there: it moves from reading a diff in a terminal to reading the built note, which states what
changed with its commit ids.

Agreed in the vault plan `2026-10-26-vault-two-loops`, under the owner's rule that writes inside the ela system follow
an agreed plan directly.
