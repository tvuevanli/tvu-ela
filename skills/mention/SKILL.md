---
name: mention
description: A mention of the owner in Slack, watched through his reply. Use for "who is still waiting on my reply", "draft a reply for this mention", "谁 @ 我还没回", or the runner's draft step.
user-invocable: true
---

# /ela:mention — he goes first, ela follows through

`MENTION="python3 ${CLAUDE_PLUGIN_ROOT}/skills/mention/mention.py --env-file <env>"` (`<env>` is `env` in
`~/.claude/ela/site.json`); `$MENTION --help` lists the verbs. Decision: `docs/adr/0021-on-a-mention-the-owner-goes-first.md`.

The script triages, keeps the store, counts the wait, gathers the facts and reads his reply for commitments. A session
is needed for two things only, both judgment: the ask in one sentence and the reply he can paste.

## What happens to a mention

| triage | what ela does |
|---|---|
| notice (a bot's announcement, an FYI, a cc) | recorded with its reason; never raised |
| ask (a question, a request, a decision put to him) | the thread read, the facts gathered, then a wait of thirty minutes of his working time. He replies: closed, and what his reply commits to is prepared as dry runs by class. He does not: one message to him |
| incident (prod and a failure, addressed to him) | the facts to him at once, at any hour; no reply drafted |

Outside his hours (the day file's `dm_hours`) nothing is sent: an unanswered ask takes an ordinary ask slot on
today.md with the same options. An ask still open after three working days is closed as expired and kept.

## Drafting the message (`/ela:mention <id|permalink>`, and the runner's draft step)

1. `$MENTION show <ref> --json`, then read the thread first-hand: `ela slack read <permalink>`. Read the tickets it
   names (`ela jira read KEY`) when the answer turns on them. A summary in the thread is input, not fact.
2. `$MENTION facts <ref>` gathers the tickets' state, owner and Fixed In and the related threads. A key it could not
   read is named in the facts as not read; do not fill it from memory.
3. Write the ask in one sentence, in the third person, in your own words: who asks, and what they need from him.
4. Write the reply to a file: what he would say, in his voice, English unless he asked otherwise, Slack mrkdwn, a
   mention written as the person's name for him to retype. Say only what the facts support; where the answer is his
   decision, give the decision's options instead of choosing. If the reply promises Jira work (link these, update the
   parent, assign to someone, file a ticket), say it in plain words: the script reads those and lists the dry runs.
5. `$MENTION draft <ref> --ask "<the sentence>" --reply-file <file>` writes the message to the store and prints it.
   Nothing is sent. The runner sends it to him and records `$MENTION sent <id> --ts <ts>`; in an attended session,
   show him the printed text.

## Invariants

- **ela never posts the reply.** No verb here writes to Slack. A reply under his name is not an action class and is
  never proposed for a grant. The message the runner sends goes to him alone.
- **No draft before the wait ends**, except on his request in a session. A draft made while he is answering is
  waste, and it interrupts him.
- **His reply withdraws a pending draft.** `$MENTION note <permalink>` (the watcher calls it on any message of his in
  a thread) marks it withdrawn; say nothing further about it. A letter that arrives afterwards is refused.
- **Follow-through stays a dry run.** His reply's commitments become batches in `ela dry` under link-named,
  parent-status and assign-by-rule, confirmed there by class. "File a ticket" becomes a local draft under the store;
  it is created only on his word. A promise no class covers is listed, not acted on.
- **His three options keep his labels and order**: A use this draft · B I will write it · C nothing needed. C counts
  against the triage reason of that message; `$MENTION tally` shows each reason's record, and a reason with repeated
  C answers is the one to move to notice (a change to `REASONS`, with the tally as its evidence).
- **Incidents carry facts only.** No reply is drafted for a prod incident, and its facts do not wait for his hours.

## What the runner calls

| when | call | then |
|---|---|---|
| a message mentions him, or he posts in a thread | `ela mention note <permalink> --fresh --json` | act on `do`: `timer` (call `due` at `at`), `dm` with `kind: incident` (send him the file at `text`, then `sent`) |
| a timer fires, and at each pass after `ela facts refresh` | `ela mention due --json` (the pass: `ela mention scan --json`) | `draft`: start a session on this skill for that id; `dm`: send him the file at `text`, then `ela mention sent <id> --ts <ts>`; `today`: nothing, today.md shows it |
| he answers the message with a letter | `ela mention answer <dm ts|id> <A|B|C> --json` | nothing; A has prepared the draft's dry runs by class |

Exit codes: 0 ok · 2 usage (a letter on a withdrawn or answered mention, no draft owed) · 3 not on record · 5 remote.

## Verification

`tests/test_mention_offline.py` (fixtures, no network): the wait in working time, each triage reason, a reply inside
the wait with its batches by class, the unanswered message, the withdrawal, the incident, the today.md slot, the tally.
