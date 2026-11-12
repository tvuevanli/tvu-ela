# 0021 — On a mention the owner goes first; ela follows through

Status: accepted, 2026-11-12. Extends ADR 0019 (what his reply commits to is prepared under its classes) and uses
ADR 0018's ask shape. It adds no class and grants nothing.

## Context

The desk brief of 2026-11-12 (`<runtime>/drafts/2026-11-12-mention-rule-brief.md`) relays the owner's choice among
three options for what ela does when he is mentioned in Slack. Read against the record on the same day:

- The Slack fact store held 57 mentions of him over eight days. 14 were notices (a bot's release announcement, an
  FYI, a cc). Of the 43 that asked something he answered 29 himself, 19 of them within thirty working minutes and 14
  within ten. A reply drafted at the moment of the mention would have been wasted two times in three and would have
  interrupted him each time.
- What lags is the work his reply promises. On MH-3735 he answered the thread in minutes, and the Jira side (the
  links to the module tickets, the parent's status) waited for a session.
- The team sync note of 2026-11-12 carried a section of threads waiting on him that a session compiled by hand.
- His commitments to the team are a notice to engineers within four hours and an In Progress ticket updated within
  a day. A mention nobody answers works against both, and nothing told him about one.

## Decision

- **He goes first.** On a mention that asks something of him, ela reads the thread and gathers the facts: the tickets
  it names with their state, owner and Fixed In, and the related threads from the links index. It drafts nothing and
  sends him nothing.
- **After he replies, ela follows through.** His reply closes the mention. What the reply commits to is read by a
  closed vocabulary and prepared as dry runs under ADR 0019's classes: link-named, parent-status, assign-by-rule. A
  promise to file a ticket becomes a local draft that waits for his word. A promise no class covers is listed and not
  acted on.
- **Unanswered after the wait, one message to him.** The wait is thirty minutes of his working time, one setting
  (`MENTION_WAIT_MIN`; his hours are the day file's). The message carries the ask in one sentence, the facts in five
  lines at most with links, a reply drafted for him to paste, the dry runs that reply implies, and one ask with his
  three options: A use this draft, B I will write it, C nothing needed. ela never posts the reply; a reply under his
  name is not a class and is never proposed for a grant.
- **His reply withdraws a pending draft**, without a further message, and the follow-through rule then applies to
  that reply.
- **Two exceptions.** A prod incident addressed to him does not wait: its facts go to him at once, at any hour, with
  no drafted reply. Outside his hours nothing is sent: the unanswered mention takes an ordinary ask slot on
  today.md, with the same three options.
- **Triage errs toward telling him, and is recorded.** A mention is an ask, an incident or a notice by a closed set
  of reasons (`REASONS` in `skills/mention/mention.py`). A notice is recorded and never raised. Every triage is
  logged with its reason; a C from him counts against that reason, and `ela mention tally` is what the rules are
  tuned from.
- **One store**, `<reports>/ela/mentions/`: each mention with its thread, its triage, when he replied, what was
  prepared and what he chose. A built meeting note's Waiting on you section is a rendering of it. today.md gets no
  new section.

## The gate (CLAUDE.md §Gate)

- Problem and evidence: 14 of 43 asks unanswered in eight days with nothing raised; the MH-3735 follow-through done
  by hand; the hand-made section of the sync note.
- Strongest alternative: draft a reply at the moment of every mention. Rejected on the record above: two drafts in
  three would be discarded, and each would reach him while he is already answering. Doing nothing leaves the
  unanswered third to the morning brief, a day late for a four-hour promise.
- Conflict with a recorded decision: none. The message to him is the dry run the owner's Slack rule of 2026-11-12
  allows (it goes to him alone and nothing leaves on a timer to anyone else). The assign-by-rule batch made from his
  reply stretches that class's rule from a written routing rule to his own word in the thread; the batch stays a
  dry run he confirms, and its `why` names the reply.
- Verdict: build it. Rejected options: ela posting the reply under any name, and a wait counted in wall-clock time
  (a mention at night would then message him at night).

## Admission (ADR 0006)

1. Scenario: a new row, S27. S1 lists what waits on him once a day, S4 digests a thread on request, S22 acts on a
   drafted write; none of them watches one mention through his reply.
2. Layer: L1 `skills/mention/mention.py` (triage, the wait, the store, the facts, the commitments reader; every Jira
   write stays a batch in `skills/dry/dry.py`). L2 `skills/mention/SKILL.md`, because the ask in one sentence and the
   reply to paste are judgment. L3 `ela mention`, the today.md slot and the meeting note's section
   (`skills/vault/`). The watcher and the timer are ela-runner's.
3. Workflow: `docs/manual.md` names `ela mention` in §一. It displaces the hand-made list of threads waiting on him
   in a sync note.
4. Phase and the cost of proof: phase 6, behind the write gate. Proof: two weeks of mentions with the tally read,
   no unanswered ask older than the wait without a message or a slot, and one follow-through batch applied as
   drafted. Until then it is built, unreached.
5. Duplication: `ela slack mentions` stays the sense that lists mentions and whether he answered; it decides
   nothing. The brief's waiting-on-him lane reads the same sense once a day and keeps doing so until the tally shows
   this store covers it.
