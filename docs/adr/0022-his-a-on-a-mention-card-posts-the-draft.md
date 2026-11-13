# 0022 — His A on a mention card posts the draft

Status: accepted, 2026-11-13. Supersedes one clause of ADR 0021, "ela never posts the reply"; the rest of 0021
stands (he goes first, the wait, the follow-through, the triage record). It adds no class under ADR 0019 and grants
nothing.

## Context

The desk brief of 2026-11-13 (`<runtime>/drafts/2026-11-13-mention-post-brief.md`) relays the owner's decision on the
first mention card that reached him:

- The card was sent on 2026-11-13 for an announcement in the unified-resources channel. Its draft was a two-word
  acknowledgement. The owner asked why a draft he accepts must still be copied into the thread by hand.
- A second reply for the same thread was then drafted as an ordinary Slack action in the runner's actions file, while
  the mention stayed open for his own reply. Both would have posted; the desk withdrew the action by hand.
- The message itself tagged more than a dozen people and put no question to him. It was triaged as an ask because its text
  carries polite imperatives ("please reply in this thread").
- The owner's Slack rule of 2026-11-12 (working preferences) lets a message leave only on his approve of its dry
  run. The card is that dry run and his A is that approve, so posting on A needs no new permission: no grant, no
  timer, no class.

## Decision

- **A posts the draft the card showed.** The three letters keep their order: A post this draft, B I will write it,
  C nothing needed. Each reply is its own card and its own approve; ela never continues a thread by itself, and a
  reply to a mention stays outside the dry-run classes and is never proposed for a grant.
- **The identity is one site setting**, `mention_post_as` in `site.json`: `off`, `ela` or `owner`. `off` is the
  default and the shipped value until the owner chooses: A means he used the draft and pastes it, as under 0021.
- **Under `owner`** the reply leaves under his own name through `ela slack post --as-owner`, with a user token
  (`SLACK_USER_TOKEN`, scope `chat:write`) in the site's env file. A missing token, a token that is not his, or one
  without the scope is a refusal that names the fix. Nothing falls back to the bot.
- **Under `ela`** the bot posts, and only an acknowledgement or a relayed fact. The drafter marks such a draft
  (`ela mention draft --postable`); the default is not postable, and the script withdraws the mark from a draft in
  which its own reader finds a commitment or a promise. A draft that judges, commits or disagrees keeps the `off`
  card: he sends it himself. A reply posted as the bot ends with one fixed line appended by the code, saying whose
  word it is and that replies reach him. The line is part of what the card shows and of the hash.
- **The text posted is the text he saw.** The hash of the text is kept when the card is recorded as sent, or
  carried in the A of a today.md ask. A draft made again after its card owes a new card; an A that carries words
  after the letter is not an approve and orders a new draft.
- **The thread is read at the moment of the A.** A reply of his after the mention closes the mention under 0021 and
  nothing is posted.
- **One post, on record.** The post goes through `slack.py post`, so its duplicate refusal and its mrkdwn check
  apply. It is read back, the permalink is kept on the mention, the mention is closed, and the row in `writes.jsonl`
  names the mention.
- **A closed mention withdraws what was drafted for its thread.** When a mention closes (his reply, his C, a
  post, his word), each drafted and unapplied Slack action aimed at the same thread in the runner's actions files is
  marked `superseded` with the reason.
- **An announcement to many is a notice.** A message that tags six people or more and puts no question to him
  alone is recorded under a new reason, `broadcast`. A question that names him alone among them stays an ask, and a
  prod incident stays an incident.

## The gate (CLAUDE.md §Gate)

- Problem and evidence: the first card cost him a copy and a paste for two words; the same thread held a second
  drafted reply that would have posted beside his; the card should not have been raised at all.
- Strongest alternative: keep 0021, since two mentions in three are answered by him within the wait. Rejected for
  the remaining third: an accepted draft that waits for a paste is the delay 0021 was written to remove. Doing
  nothing also leaves the double post to be caught by hand.
- Conflict with a recorded decision: ADR 0021's "ela never posts the reply", superseded here. The working preference
  that messages to colleagues go out under his name is why `owner` exists and why `ela` is held to acknowledgements
  and signed. The rule of 2026-11-12 is kept: nothing leaves without his approve of that text.
- Verdict: build it, shipped `off`. Rejected: a grant or a class for replies (a reply is judged one at a time);
  falling back to the bot when the user token fails (the reader would see a different author than he approved);
  posting on a timer when he does not answer the card.

## Admission (ADR 0006)

1. Scenario: S27, extended. No new row.
2. Layer: L1 holds every gate (`skills/mention/mention.py answer`: the hash, the fresh read, the identity, the
   refusal of an unattended session; `skills/slack/slack.py post --as-owner`: the token checks). L2 is the
   drafter's mark in `skills/mention/SKILL.md`. The confirm is the adapter's: his letter under the card, taken by
   ela-runner.
3. Workflow: `docs/manual.md` §一, the mention row.
4. Phase and the cost of proof: phase 6, with 0021. Proof: under each setting one real card answered A, the reply in
   the thread once, the permalink on the mention. Until the owner chooses a setting it is built, unreached.
5. Duplication: none. `ela slack post` stays the one write path to Slack.
