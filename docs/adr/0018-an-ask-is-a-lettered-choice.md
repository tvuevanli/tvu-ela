# 0018 — An ask is a lettered choice

Status: accepted, 2026-11-12. Supersedes ADR 0014's "Ticking is unchanged" line. The rest of 0014 (one page, three
asks, expiry after three working mornings) stands.

## Context

The desk's addition of 2026-11-12 to the dry-run brief (`<runtime>/drafts/2026-11-12-dry-run-graduation-brief.md`)
relays the owner's request: an ask should be a quick decision with A / B / C options. Read against the vault on the same
day:

- today.md showed each ask as one box, `- [ ] apply N — <the drafted write>`. Ticking it was yes. Every other answer had
  to be typed, or the ask was left to expire. Of the 78 answers in three weeks (ADR 0014), most were written in a desk
  session, not ticked.
- The question asks of ADR 0016 put "send X the drafted message, or drop it" in one sentence with one box, so a tick
  could only mean `drop`.
- The grant ask that the dry-run classes need has three real answers: grant, keep confirming, never ask again. One box
  cannot carry three answers.

## Decision

- **One shape for every ask ela shows him**: the today.md asks, a class's batch ask, the grant ask and the
  open-question ask. Each is one line with the question and when it leaves ("no answer: nothing happens; gone Fri"),
  followed by two or three option lines with a box. Each option says in a few words what happens. A is ela's
  recommendation and says so. The others are the real alternatives. There is no invented middle option: an ask with
  only two answers has two options. When the owner named the options himself, his labels, definitions and order are
  kept.
- **One letter answers it**, wherever he is: a tick on the option line, `ela: A` under the ask, `ela: 2 B` anywhere on
  today.md, `2 B` in Slack, or the letter in a session. `apply N` still works and means that ask's A.
- **Each option carries what it runs.** `apply N` goes to the runner as it did before. `drop` and the dry-run answers
  that write nothing live are settled by the sync itself. An ask answered by a letter stays off the page until its
  evidence changes, and a drop by his word is marked so on `reference/dropped.md`.
- **The letter is recorded.** The ask state keeps the letter he chose. In the dry-run record, "applied as drafted" is
  A on an apply ask.

Rejected: keeping the single box and adding a typed vocabulary (`ela: drop 3`, `ela: never`). It leaves every answer
except yes to memory, and the record shows that answers outside a desk session are rare.

## Admission (ADR 0006, a modification)

1. Scenario: S1, the vault row of `docs/capabilities.md`, unchanged in purpose: what needs the owner today.
2. Layer: L3 rendering in `skills/vault/vault.py` (`ask_options`, `today_letters`); no new verb.
3. Workflow: `docs/manual.md`'s vault row describes the options and the letters; it replaces the single apply box.
4. Phase and the cost of proof: phase 6's write gate; three asks of at most four short lines stay within today.md's
   150 words (tested offline).
5. Duplication: none. The runner reads the letters through `ela vault guidance`, as it reads ticks.
