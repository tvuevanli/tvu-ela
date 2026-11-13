---
name: mention
description: A mention of the owner in Slack, watched through his reply. Use for "who is still waiting on my reply", "draft a reply for this mention", "谁 @ 我还没回", or the runner's draft step.
user-invocable: true
---

# /ela:mention — he goes first, ela follows through

`MENTION="python3 ${CLAUDE_PLUGIN_ROOT}/skills/mention/mention.py --env-file <env>"` (`<env>` is `env` in
`~/.claude/ela/site.json`); `$MENTION --help` lists the verbs. Decisions: `docs/adr/0021-on-a-mention-the-owner-goes-first.md`,
`docs/adr/0022-his-a-on-a-mention-card-posts-the-draft.md`.

The script triages, keeps the store, counts the wait, gathers the facts and reads his reply for commitments. A session
is needed for three things only, all judgment: the ask in one sentence, the reply, and whether that reply is one
ela may post.

## What happens to a mention

| triage | what ela does |
|---|---|
| notice (a bot's announcement, an FYI, a cc, an announcement that tags six people or more and asks him nothing alone) | recorded with its reason; never raised |
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
5. Decide whether the reply is postable by ela: it only acknowledges ("got it, thanks") or relays a fact that is on
   record. A reply that judges, commits him to something, declines or disagrees is not, and neither is one you are
   unsure about. Not postable is the default; say `--postable` only when sure.
6. `$MENTION draft <ref> --ask "<the sentence>" --reply-file <file> [--postable]` writes the card to the store and
   prints it, with what A on it will do. Nothing is sent. A `# mrkdwn:` line names text Slack would print literally:
   fix the reply and draft again. The runner sends the card to him and records `$MENTION sent <id> --ts <ts>`; in an
   attended session, show him the printed text.
7. When `$MENTION due` lists the draft with `revise` (his A came with words), write the reply again following those
   words and draft again: the new text gets its own card.

## What A does (`mention_post_as` in `site.json`)

| setting | the card's A | what `$MENTION answer <id> A` does |
|---|---|---|
| `off` (default) | A use this draft | records it; he pastes the reply; the draft's Jira commitments are prepared by class |
| `owner` | A post this draft under your name | posts the reply as him (`slack.py post --as-owner`, `SLACK_USER_TOKEN`), closes the mention |
| `ela` | A post this draft as @ela, for a `--postable` draft only; any other draft gets the `off` card | posts the reply as the bot with the signature line, closes the mention |

Before a post, in the script: the text is the text the card showed (its hash is kept at `sent`, or carried by a
today.md ask as `--shown`); the setting is still the one the card named; the thread is read now, and a reply of his
after the mention closes it with nothing posted; an unattended session (`ELA_NO_APPLY`) is refused. A failure is exit
4 with the reason and nothing recorded as answered. After it: read back, the permalink on the mention, a row in
`writes.jsonl` with the mention id, and `said`, the line for him.

## Invariants

- **A reply leaves only on his A on its card**, and only when the card offered a post. One reply, one card, one
  approve: never a second message in the thread on the strength of an earlier A, never a post from a session. A reply
  is not an action class and is never proposed for a grant. The card itself goes to him alone.
- **What is posted is what he saw.** Never edit a draft file or the record by hand; draft again, which orders a new
  card. An A with words after it ("A but say …") is a request to redraft, not an approve.
- **As @ela: acknowledgements and relayed facts only, signed.** The code appends the signature line; do not write it
  into the reply. Under `owner` there is no signature.
- **A closed mention withdraws what was drafted for its thread.** His reply, his C, a post or `close` marks each
  drafted, unapplied Slack action aimed at that thread in `<reports>/runner/*-actions.json` as `superseded`, with why.
  `$MENTION supersede <id>` does the same on request.
- **The card is Slack mrkdwn** (`ela slack check`): no Markdown in the ask or the reply.
- **No draft before the wait ends**, except on his request in a session. A draft made while he is answering is
  waste, and it interrupts him.
- **His reply withdraws a pending draft.** `$MENTION note <permalink>` (the watcher calls it on any message of his in
  a thread) marks it withdrawn; say nothing further about it. A letter that arrives afterwards is refused.
- **Follow-through stays a dry run.** His reply's commitments become batches in `ela dry` under link-named,
  parent-status and assign-by-rule, confirmed there by class. "File a ticket" becomes a local draft under the store;
  it is created only on his word. A promise no class covers is listed, not acted on.
- **His three options keep their letters and order**: A (use, or post, this draft) · B I will write it · C nothing needed. C counts
  against the triage reason of that message; `$MENTION tally` shows each reason's record, and a reason with repeated
  C answers is the one to move to notice (a change to `REASONS`, with the tally as its evidence).
- **Incidents carry facts only.** No reply is drafted for a prod incident, and its facts do not wait for his hours.

## What the runner calls

| when | call | then |
|---|---|---|
| a message mentions him, or he posts in a thread | `ela mention note <permalink> --fresh --json` | act on `do`: `timer` (call `due` at `at`), `dm` with `kind: incident` (send him the file at `text`, then `sent`) |
| a timer fires, and at each pass after `ela facts refresh` | `ela mention due --json` (the pass: `ela mention scan --json`) | `draft`: start a session on this skill for that id; `dm`: send him the file at `text`, then `ela mention sent <id> --ts <ts>`; `today`: nothing, today.md shows it |
| he answers the message with a letter | `ela mention answer <dm ts|id> <his words> --json` | say `said` back to him; exit 4: say the reason on stderr. A has prepared the draft's dry runs by class, and has posted when the card offered it |
| a today.md ask whose A carries `--shown` | the `does` as written | the same; the vault's sync leaves that letter to the runner |

Exit codes: 0 ok · 2 usage (a letter on a withdrawn or answered mention, no draft owed) · 3 not on record · 4 a post
refused, with the reason · 5 remote.

## Verification

`tests/test_mention_offline.py` (fixtures, no network): the wait in working time, each triage reason, a reply inside
the wait with its batches by class, the unanswered message, the withdrawal, the incident, the today.md slot, the tally.
`tests/test_mention_post_offline.py` (a fake Slack behind `slack.py`): A under `off`, `ela` and `owner`, each refusal,
the hash, the fresh read, the superseded action, the announcement triage.
