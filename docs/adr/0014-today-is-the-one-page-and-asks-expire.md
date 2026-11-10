# 0014 — today.md is the one page, and an unanswered ask expires

Status: accepted, 2026-11-10. Supersedes ADR 0010's "Home is short and live" and the Home paragraph of the vault
readme. The rest of 0010's layout stands until the layout decision that follows this one.

## Context

The vault's own record, read on 2026-11-10 (the desk brief `<runtime>/drafts/2026-11-11-vault-from-zero-brief.md`):

- Home was last opened on 2026-11-04 (`.ela-sync.json`, `home.looked`).
- The morning page had seven answers in three weeks and Home two. The owner's 78 answers fall on three days, each
  one a day he worked through the vault with a desk session.
- The morning page carries 17 to 24 apply boxes, and one ask waited eleven mornings (MH-2406, drafted as a comment and
  then as an assignment).
- Every write to Jira or Slack (129) happened in an attended session.

The vault worked as a control panel: ela queued boxes and the owner ruled them. He works by conversation and under
time pressure, so the panel produced obligations faster than he could clear them, and each morning repeated what he
had not done. The design was at fault, not the owner. The owner asked for the vault to be rebuilt from zero, with ela
deciding its design and him giving feedback (the desk, 2026-11-10).

## Decision

- **One page.** `today.md` at the root is what he opens. It has three parts:
  - *Facts*: up to four first sentences from the newest What-changed page (releases, docker services, QA, tickets).
  - *Needs you*: at most three asks only he can answer. Each says what happens if he does nothing ("nothing") and
    when the ask leaves.
  - *Today*: meetings, a project deadline within 14 days, and what leaves at 10:00.

  Then one line of links. Above that line the page stays within 150 words; facts are cut first, never below three.
- **An ask expires.** An ask unanswered on three working mornings leaves the page. It is written once to
  `reference/dropped.md`, with the day it dropped and the day it was first asked. It comes back only when its
  evidence changes.
- **What counts as one ask.** A drafted action is identified by the tickets its command acts on, whatever its number
  or form that day. Its first day is backfilled from the week's action files, so an ask already old when this lands
  drops at once. The state lives in `<reports>/ela/asks.json`.
- **Asks come from three sources:** a to-read note with an open box under Waiting for your word, and a project
  head's unticked box, count as asks too, with the same cap and expiry.
- **Ticking is unchanged.** A ticked `apply N` or `don't N` on today.md is read like one on Home.
- **Home is a pointer.** Until 2026-11-25 `home.md` is three lines pointing to today.md; after that the sync stops
  writing it. Opening today.md counts as looking.

Rejected: keeping Home and capping its asks at three. That is the panel the record shows unused: the asks it hides
still pile up below, and the eleventh morning still comes.

## Admission (ADR 0006, a modification)

1. Scenario: the vault row of `docs/capabilities.md`, unchanged.
2. Workflow: `docs/manual.md` names today.md where it named Home.
3. Duplication: none. today.md reads the morning page's drafted actions and holds no verdict of its own.
