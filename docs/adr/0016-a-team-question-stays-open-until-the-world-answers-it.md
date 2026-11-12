# 0016 — A team question stays open until the world answers it

Status: accepted, 2026-11-12. Narrows ADR 0014's expiry to ela's own asks. Supersedes the meeting close's second-meeting
drop (commit 926c544): a meeting item no longer leaves for `reference/dropped.md`. ADR 0015's layout stands; this adds
one page to `meetings/`.

## Context

The desk's brief of 2026-11-12 (`<runtime>/drafts/2026-11-12-open-questions-brief.md`), read against the vault:

- The 11-11 sync note listed 14 items. ela's close marked 10 of them "no change: raised again next meeting", and the rule
  then in force let an item roll once and leave for `reference/dropped.md`. The questions behind them (the CN Prod2
  upgrade date on MH-3752, owners for five tickets, the media queue order, the In-Review past-due list) were still open
  in Jira and Slack the next morning.
- The next note, written by hand, put them under "If time allows", the part a meeting does not reach.
- Nothing counted how many meetings a question had been carried through; today.md aged only ela's asks.

Two kinds of ask had one life cycle. An ask of ela's is a write ela proposes: if the owner does not take it, nothing is
lost and it may expire. A question about the product or the team stays open whether or not he looks at it.

## Decision

- **A question is one record**, `<reports>/ela/questions.json`: the question in one sentence, who answers, what it
  belongs to (a project page, a ticket, or the meeting's topic), when and where it was first raised, every meeting that
  listed it, and the ticket state it was last said to be open against. Each sync reads every meeting note's boxes (a
  note written by hand is read, never rewritten), the To raise items of a note in the verb's form, and the boxes under a
  project page's Open questions, and merges the same question by ticket and by meaning; two boxes of one note are never
  merged.
- **Closed by outcome, never by age.** Each pass reads the question's tickets in the fact store (every one, when the
  line opens with a list of them) and the thread it links: assigned, moved, closed, re-dated, answered in a comment by
  someone other than the owner, split into new tickets, replied to. Any of these closes it, and the outcome is written
  on the record. His tick, an `ela:` line under it on the standing page (`ela: drop` drops it), or `drop` on today.md
  closes it too. No team question goes to `dropped.md`.
- **One standing page**, `meetings/open-questions.md`: one line a question, grouped by who answers, oldest first, each
  with its ticket, since when, and at how many meetings it was listed. A closed one leaves the page; the record keeps it.
- **today.md carries one line** in Today: how many are open, the oldest and its age, the next sync. A question listed at
  three meetings without an outcome takes one of the three ask slots once, with a message drafted under his name to
  whoever answers (a Jira comment on its ticket, else a reply in its thread). That ask is ela's and expires as any ask
  (ADR 0014); the question does not. It asks again only after three more meetings.
- **A meeting note is built from the records**: `meetings/<yyyy-mm-dd>-<key>.md`, its sections the topics with open
  questions that changed or are due, each with where it stands and its questions, then what waits on him, then every
  other open question of that audience under Carried. A note written by hand for that date is left alone and read.

Rejected: keeping the roll-once rule and widening it to three meetings. It moves the day the question disappears; the
question is still open in the world on that day.

## Admission (ADR 0006, a modification)

1. Scenario: S1, the vault row of `docs/capabilities.md`, unchanged in purpose: what needs the owner today.
2. Workflow: `docs/manual.md`'s meeting and vault rows name the standing page and `ela vault questions`.
3. Duplication: the meeting close's per-item verdict and the records' outcome are one reading
   (`skills/vault/questions.py`); the close writes outcomes the records hold.
