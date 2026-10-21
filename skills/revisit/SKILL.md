---
name: revisit
description: Decide whether an old ticket should still exist — close, carry or keep — and propose a close as one bundle (Fixed In, labels, comment, Done). Use for "fill Fixed In and close", "填 Fixed In 关票", "这票能关了吗", "旧票清一清", or a ticket whose face has aged.
user-invocable: true
---

# /ela:revisit <KEY…| batch class> — an old ticket in, a verdict on its existence out

Self-contained. Argument: one or more Jira keys or URLs, or one of the batch classes in step 5. Replies
to the owner follow the working preferences (Chinese in conversation unless he asks otherwise); the
English of this file is not the language of the answer.
Read-only over code and runtime; Jira writes are dry-run until the owner's word.

## The discipline this skill exists for

**A ticket's reason to exist is its problem, not the plan written on it.** Three failure shapes,
each the ticket's own face promoted to a statement about today:

- **The plan was never carried out, so the ticket stays open** — while the problem it was filed for
  was dissolved by an unrelated change. MH-1649 asked for an audio-only parameter on the NDI input
  process; that parameter was never added, and the problem went away regardless once the bridge
  sender became one process per shared-memory segment, which made the audio path stand alone.
  Judging the plan keeps a ticket like that open forever, and its subject is never revisited because
  the ticket looks alive.
- **One item in a report still fails, so the ticket is not done** — while that failure has a
  different origin from the ticket's subject. MH-2798's only failing item is an input path that no
  longer runs the process the ticket is about. A residual from another origin belongs to its own
  ticket; parking the parent on it hides both, and the parent's finished work is never counted.
- **The ticket's statement of what the product supports ages, and is later quoted as current.**
  MH-1649 carries a postscript naming the only supported source/destination combination; a later
  verification used a different one. Closing a ticket without repairing that sentence publishes it:
  a closed ticket is read as a settled fact, and its stale sentences travel further than its open
  ones.

The cost of getting this wrong is asymmetric. A ticket wrongly kept costs a line in every sweep from
now on; a ticket wrongly closed costs one reopen, which the closing comment makes cheap. Bias toward
the verdict that can be undone — never toward closing something whose problem is still live.

## Invariants

- **Read `/ela:explain`'s picture; do not rebuild it.** That skill already establishes the runtime
  instance, whether the fix named on the ticket survives, the ticket's assertions against the
  thread's decisions, and who it waits on. This one owns only the verdict over that picture
  (ADR 0006 Q5: a shared input step belongs to one ability and is called by the others).
- **Evidence is taken in cost order and stops the moment it answers** (step 2). The reflex to trace
  code is the expensive failure here: a verification comment from QA settles most of these tickets,
  and a five-layer trace answers a question nobody asked.
- **Code, when reached at all, answers one question**: is the original problem still present.
  Anything wider — why, where, whether it could be supported — is `/ela:probe` or `/ela:feasible`,
  named as a hand-off and not started.
- **A residual has a ticket key or it is not tracked.** "Followed up elsewhere" without a key is a
  closed ticket with a lost thread. When the key does not exist yet, the verdict is not *close* but
  *close after filing*, and the filing is proposed here as a dry run.
- **Status is the state.** This Jira does not use the resolution field: Done is terminal, and an
  unfinished set is filtered by status, never by resolution.
- **The verdict names the option it rejects.** Every close carries the reason the ticket could have
  been kept, so a later reopen is a decision and not a discovery.
- **Writes gated, one bundle per ticket.** A close is one decision, so its writes are one dry run and one
  word: `jira.py close <KEY> --fixed-in … --label … --from-file …` carries Fixed In, labels, the comment,
  `flag:closing` and the assignment to the owner together (`skills/jira/SKILL.md`); the status itself is
  his click in Jira, never this skill's. A carry's link is `jira.py link`.
  Several tickets are several confirms. (Supersedes "each verdict confirms separately", 2026-10-19:
  split confirms produced closes with the comment missing.)

## 0 — bind

Read `~/.claude/ela/site.json` → `env`, `map`, `published`.

```bash
JIRA="python3 ${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py --env-file <env>"
MAIL="python3 ${CLAUDE_PLUGIN_ROOT}/skills/mail/mail.py --env-file <env>"
SLACK="python3 ${CLAUDE_PLUGIN_ROOT}/skills/slack/slack.py --env-file <env>"
GRAPH="python3 ${CLAUDE_PLUGIN_ROOT}/skills/graph/graph.py --env-file <env>"
```

Then `/ela:explain <KEY>` for each ticket, and work from its four blocks. On a batch, run explain
only for the tickets that survive the step 1 split with an open question — the rest are decided on
the ticket alone. A clean-up ticket whose face already answers step 1 (the fix is named, QA or the
owner verified it on a lane) skips explain; the verdict then rests on step 2's rung 1 or 3.

## 1 — split the ticket face into three

The single act that makes an old ticket judgeable. Written back as three lines before anything is
checked; a wrong split makes every verdict below it wrong.

| | what it is | what it decides |
|---|---|---|
| **the problem** | the condition that made someone file it, in the reporter's terms | the verdict, and nothing else decides it |
| **the plan** | the TODO, the design, the assigned lanes written on it later | why the ticket *looks* unfinished; never a reason to keep it |
| **the vintage** | the versions, release line and architecture current when it was written | dates every claim on the face, including the ones now false |

Sub-tasks inherit the parent's problem but carry their own plan; split each on its own terms, or a
finished sub-task is kept alive by its parent's leftovers.

## 2 — check the problem against today, in cost order

Stop at the first rung that answers whether the problem still occurs. Record which rung answered —
it is the evidence line in the closing comment.

1. **The ticket** — a verification comment, a linked ticket that superseded it, a decision in the
   thread. `$JIRA read <KEY> --deep`.
2. **The report the verification lives in** — QA test reports arrive as mail; a Jira comment is at
   most a summary of one. `$MAIL search …`, `$SLACK read <permalink>`.
3. **Runtime** — does the environment that had the problem still exist, and does it still show it.
   `$GRAPH resolve <id>` for an id on the ticket; the release lane for whether the fix's version is
   where the reporter was. A verification screenshot on the ticket often names the destination and
   the environment, which is enough to date it.
4. **Code** — only when 1–3 cannot answer, and only for "is the original problem still present",
   with `file:line`. If the answer needs a chain traced across layers, stop and hand to `/ela:probe`.

An architectural change that dissolved the problem is the common finding at rung 3–4, and it is a
*close* even though nothing on the plan was done. Say which change, in one line, so the reader does
not have to trust the verdict.

## 3 — the verdict, three exits only

| verdict | when | what it must carry |
|---|---|---|
| **close** | the problem no longer occurs | the rung that established it · the fact in one sentence · the plan item deliberately not done, so nobody re-derives it · any stale sentence on the face, repaired |
| **carry** | the problem persists but from another origin | the carrier ticket's **key** (filed here if it does not exist) · what exactly moved to it · what stays finished on this one |
| **keep** | the problem persists from the same origin | the skill that takes it next — `breakdown` (direction settled, work to split) · `route` (owner unknown) · `probe` (cause unknown) · `feasible` (it turned into a capability question) — and what it is waiting on |

*Keep* is a hand-off, never an outcome by itself: a ticket kept without a named next step is the
state this skill exists to end.

## 4 — the closing draft, as one bundle

One `jira.py close` per ticket, dry run first — a proposal the owner finishes in Jira. Its parts:

- **Fixed In** — only for a Bug or Task that a code change fixed, and only as the last step of a close
  verdict (never as the entry): `ela fixed-in <KEY> [--author A --since D | --path P | --thread URL]`
  gives the candidate commits, the carrying builds, the lanes judged by ancestry and the gaps. The
  value is the **earliest verifiable** build on the ticket's release line that carries the fix
  (`<slug>@<M.m.p+BUILD>`); when the verified lane runs a build that cannot be compared, that lane's
  own build is the value and the comment says "earliest verifiable on <lane>". A value already in the
  field that disagrees is not removed: append the right one and say so. No build derivable (the
  service is unmapped, the sha is not in a checkout, the change was replaced by later tickets) → the
  field stays as it is and the comment names the commit instead. Published
  `mediahub/jira/conventions.md` holds the rule; `map/release.yaml` holds only the grammar.
- **Labels** — `release:mh-<line>` for every release line whose lane carries the fix by ancestry
  (`map/release.yaml` lane → line); two lines, two labels. **The 1.5 line is not tracked**: no
  `release:mh-1.5`, and no sentence about 1.5 in the comment, whatever fixed-in reports for it
  (owner, 2026-10-20, MH-2449 and MH-3156).
- **The comment** — English by default; bilingual (English first) only when the ticket's own text is
  Chinese; never Chinese-only. **No `@mention` unless the owner names someone** (a close is a record,
  not a request; he removed every unasked mention on 2026-10-20 and 2026-10-21); when he does, the
  sentence to that person comes first as a real mention. Then the fact
  that closed it and where it came from, the plan item not done and why it is not a debt, the carrier
  key when there is one; after a `---` line, the technical part (commit, build, ancestry, lane) that
  an agent or an investigator opens. "On <lane>" is written only with ancestry evidence for that
  lane's build; otherwise the comment names the commit and the build, not the lane. No schedule, no
  apology, no restatement of the description.
- **The status is the owner's click, never this skill's.** `jira.py close` ends by adding
  `flag:closing` and assigning the ticket to the owner; the script refuses every transition to a
  terminal status. The owner reviews the proposal in his own queue and clicks Done in Jira, or keeps
  the ticket and removes the flag (2026-10-21, after five tickets were closed in one step). The dry
  run therefore shows the evidence, the comment, the flag and the assignment, and nothing else.

The link to a carrier is a separate `jira.py link` dry run, confirmed with the same word.

Repairing a stale sentence on the face is part of the close, not a separate task: state the current
fact in the same comment, since editing a description silently loses the history.

Do not open a follow-up ticket for an imperfection nobody has asked for. An improvement with no
requester becomes the next ticket this skill has to judge; it is filed when someone reports the cost,
and then it carries its own evidence.

## 5 — batch

The batch is the main entry; a single key is its degenerate case. Three classes, cheapest first:

```bash
$JIRA jql 'project = MH AND issuetype = Sub-task AND status not in (Done) ORDER BY updated ASC'
$JIRA jql 'project = MH AND status = Review AND updated < -30d ORDER BY updated ASC'
$JIRA jql 'project = MH AND status = Backlog AND updated < -180d ORDER BY updated ASC'
```

For the first class, read each parent's status: **a parent already Done whose sub-tasks are still
open is the cheapest set to settle**, because the parent's own closure is already the evidence that
its problem was resolved, and the sub-tasks usually hold nothing but plan. JQL cannot express the
parent's status, so it is a second read per row.

Output one line per ticket — key · verdict · the rung that decided it · the carrier key or the next
skill — and the drafts only for the rows the owner marks.

## What this skill does not do

- Rebuild `/ela:explain`'s reading, split lanes, find a root cause, or judge a capability. Each of
  those is a hand-off named in the verdict.
- Close on the plan's account, close a ticket whose problem is still live, or close a carry verdict
  before its carrier exists.
- Write to Jira without a confirm, or file a follow-up ticket for an unrequested improvement.
- Keep a file of what a run checked. The verdict lives in the ticket; a capability limit the run
  established is recorded through the placement test in elak `blueprint/principles.md` P1, on the
  owner's word.
