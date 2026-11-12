# 0019 — A kind of write earns its way out of the confirm

Status: accepted, 2026-11-12. Extends the tiers decision in elak (`blueprint/decisions/2026-10-29-writes-run-in-three-tiers.md`):
a kind of write can now rise a tier on evidence and the owner's word, as well as fall on corrections. The rest of that
decision stands.

## Context

The desk brief of 2026-11-12 (`<runtime>/drafts/2026-11-12-dry-run-graduation-brief.md`) relays the owner's request:
ela should dry-run as much of his work as it can; he reviews; once a kind of action has matured, it should not need his
confirm. The design is ela's to decide. The grant stays his.

The record, read on 2026-11-12:

- `<reports>/ela/writes.jsonl` holds 156 writes, every one made in an attended session. Tier 1 and tier 2 have never
  produced a write. The tiers decision lets a rule fall (three corrections in a week). Nothing lets a kind of write
  rise.
- On MH-3735 the owner noticed his parent ticket was not linked to the module tickets a colleague's comment named. A
  session found six links. He approved each kind in one sentence, without editing, and they were applied. The judgment
  was his: which tickets belong, and on which release track. Most of the mechanical part (find the named tickets,
  link them, read their status, summarise on the parent) ela could have prepared without being asked. A written rule
  run against the parent as it stood before the links proposes four of the six. The other two were found by following
  a named ticket to its sibling, which was judgment.
- today.md holds at most three asks (ADR 0014). A queue of single dry runs would not fit there, and that queue is what
  the tiers were meant to remove.

## Decision

- **A class** is one atom in one scope with a written rule that selects its targets, named in plain words. The
  vocabulary is closed (`skills/dry/dry.py`, `CLASSES`). A draft that no class covers stays as it is today. A class is
  added only from a case in the record. The first classes are: link a named child to a parent the owner owns; a
  status comment on that parent from its children's states; the release-reconcile work's Fixed In and release label;
  and assign by a written routing rule.
- **A track record per class**: every dry run shown to the owner and its verdict. A run is applied as drafted, applied
  after his edit, cancelled, expired unanswered, or afterwards corrected or reverted by anyone. The record is seeded
  from history wherever history can attribute a run. A write that the log alone shows has an unknown draft. It counts
  in the totals and never toward maturity.
- **Maturity is evidence; the grant is his word, once.** A class matures with at least ten runs applied as drafted
  over at least three days, none edited or cancelled among the last ten, and none corrected. It then gets one grant
  ask: A grant (ela does these and tells you), B keep confirming, C never ask again. Yes moves the class one step up its
  ladder. A Jira class goes 3 → 1, because tier 2 is the team-channel veto window. If he does not answer, nothing
  changes, and the ask comes back only after ten more clean runs. A class that tier 3 names by rule (a customer
  channel, a prod approval, a message to a person, anything about people, any close) is recorded but never proposed.
- **It can fall by itself.** One correction, a revert, or an `ela:` line from him against it returns a granted class to
  confirm, and today.md says so. Writes made without confirm are listed under Facts with a list page, and the list
  gives the word that undoes each one.
- **Review by class.** All waiting dry runs of one class are one ask that links a review note showing each exact
  write. A applies the batch. A struck line is left out. An edited line is applied as edited and recorded as an edit.

## The gate (CLAUDE.md §Gate)

- Problem and evidence: 156 writes, all attended; tiers 1 and 2 never fired; the MH-3735 links.
- Strongest alternative: promote rules into the tiers decision by hand, as `PENDING_RULES` waits to be. Rejected:
  that asks him to decide without a record, and a hand-promoted rule has no evidence to fall back from. Doing nothing
  leaves every write attended.
- Conflict with a recorded decision: the tiers decision admits a kind of write to tier 1 or 2 only under a closed rule.
  The class vocabulary is that closed rule set, extended by grant. Demotion by three corrections stays. A granted class
  falls on one.
- Verdict: build it. Rejected options: a grant that never expires, and a class proposed from frequency alone without a
  written selection rule.

## Admission (ADR 0006)

1. Scenario: S22, extended. A kind of write rises a tier on its record and the owner's word.
2. Layer: L1 `skills/dry/dry.py` (the record, the selection rules, the grant and the fall, every Jira write through
   jira.py with dry run by default); L3 today.md's asks and the review notes (`skills/vault/vault.py`); the page check
   admits granted classes (`skills/brief/brief.py`).
3. Workflow: `docs/manual.md` names `ela dry`. The class ask replaces single `apply N` asks for writes a class covers.
4. Phase and the cost of proof: phase 6, behind the write gate. Proof: one class granted, then exercised for two weeks
   with its falls counted. Until then it is built, unreached.
5. Duplication: the evening review's corrections are read, not recomputed. `ela dry` folds its correction rows into
   the class record.
