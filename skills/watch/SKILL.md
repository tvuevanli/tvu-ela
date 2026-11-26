---
name: watch
description: The MH board watch's judgment pass — for each ticket `ela watch` found due, decide act, ask or none; and the second reading of what the decider could not settle. Run by the runner's watch sessions.
user-invocable: false
---

# /ela:watch — a decision for each MH ticket the watch found due

Self-contained. The rule is the owner's decision of 2026-11-24 (elak `blueprint/decisions/2026-11-24-ela-watches-the-mh-board-and-acts-on-jira-signing-each-write.md`).
The pass runs unattended (`ELA_NO_APPLY`): it reads, decides and writes one file. Nothing in it reaches Jira
or Slack; the runner carries the file out afterwards, through gates the pass cannot bypass.

## Modes

Three sessions use this skill. The pass (the decider) is this file. The other two read their own file first
(`${CLAUDE_PLUGIN_ROOT}/skills/watch/<name>`):

| session | Read first |
|---|---|
| the pass: `ela watch prompt`, a decision per ticket | this file, whole |
| judge mode: `/ela:watch judge KEY --write PAGE` | `judge.md`; a decision's form (act, ask, none, confidence, doubt) is this file's *What to decide* and *The file* |
| the second reading: `ela watch review prompt` | `second-reading.md`; it needs nothing else of this file |

## Input

`ela watch prompt --date <date>` (or `--json`): each ticket due a decision, the owner's first, with its
triggers, fields, description and last comments. Read more first-hand when a decision turns on it:
`ela jira read KEY` (comments, links), `ela team people --json` (who holds which area, and their Jira
accountId), `ela route KEY` (which layer and owner a bug belongs to), `ela links KEY`.

## What to decide, per ticket

One of three, never more than one set per ticket:

- **act** — ela itself writes. The writes are any of: `assign` (an accountId from the roster), `transition` to
  a non-terminal status (In Progress, Review, Reopened, Blocked, On Hold, Backlog), `priority`, `due`, `link`
  — and one `comment` that says, to the people on the ticket, what changed and why. A set of links alone carries
  no comment (one given is refused): the link shows on both tickets and its reason stays in ela/dry/did.md. A comment alone is an act
  too (a question to the assignee, a nudge on a stall, the answer a reply was waiting for).
- **ask** — the owner decides. Use it when the right move is unclear, when the evidence does not settle it,
  and always for what ela never does: a terminal status (Done, Closed, Cancelled, Won't Fix, Failed), a Slack
  post under his name, anything for a customer channel, anything about a person (their work, their speed,
  their attitude). The question is one sentence he can answer with a letter; offer two or three options, the
  first the one you recommend; an option may carry the writes and comment that carry it out.
- **none** — nothing is due after all (the trigger is noise, the ticket is moving, the question was answered
  elsewhere). Say why in one line. Prefer none to a comment that adds nothing.

An act you would not defend to the assignee is an ask.

**What an ask needs from him.** Every ask carries `kind` and `confidence`. `kind` is `fact` when ela cannot read the
answer anywhere (who owns an area, whose account a name is, a date no source carries): add `"fact": {"kind": …,
"key": …}` with a kind from `ela asks fact list`'s closed list (owner, account, lane, date, scope). A fact he gave
once is kept and the same fact is never asked again: `decide` returns the kept answer under `known` instead of a
topic, so decide with it. Otherwise `kind` is `ruling`: add `why`, your leaning's reason, which is written into
option A so he answers right or wrong and writes a reason only to correct you.

**Precedents.** The prompt lists, under a ticket, the owner's earlier corrections of the same trigger kind with their
cause (`ela asks precedents --domain watch --kind <trigger>`). Cite one when it decides the case. On a case that
would take a risk out of his sight (a fail judged not blocking, a "nothing needed"), a precedent strengthens your
leaning; it never replaces an ask.

**Confidence.** Every act and every none carries `confidence`: `high` (the evidence settles it), `medium` (it
points one way but leaves something open) or `low` (a judgment the evidence does not settle). Below high, add
`doubt`: one line on what the evidence leaves open. A decision without them is refused. The level decides what
happens (the owner's ruling, 2026-11-26):

- `high`: the writes go out, and ela/dry/did.md lists them.
- `medium`: the writes go out, and did.md lists them first, under "Review first".
- `low`: nothing is written to Jira. `decide` holds the act as the owner's topic: the question carries your `why`,
  option A is your writes and comment exactly as written (carried out at the next pass once he chooses it), option B
  leaves the ticket. ela/watch.md lists it first, under "Confirm first: ela was not sure", with your `doubt`.

So write a low act in full, as you would send it: he confirms it as written or leaves it. When you cannot say what
the act should be, write an ask instead. A none lists its level too (ela/watch.md, the least sure first).

**Comment sparingly.** MH's Jira Automation copies every comment to each linked ticket (the owner found ela's notes
flooding linked tickets, 2026-11-25; the rule is not his to change). A comment goes out only when someone on the
ticket must read or answer it there: a question they owe, a change made to their ticket. A recap, a status the
fields already show, or bookkeeping is none, or a line in the owner's vault through an ask. The prompt's `links`
count is how many tickets will get a copy; the more there are, the higher the bar.

How to read the triggers:

| trigger | what usually settles it |
|---|---|
| owner-held | the owner holds it: settle it (the next step is clear and ela can take it) or hand it to whoever should hold it (assign by layer and area from the roster, comment why); a ticket that needs his own judgment is an ask |
| unassigned | assign the owner of its layer/area, or ask when two areas could own it |
| behind | the assignee wrote it is fixed: move it to Review with a comment, or ask the assignee to confirm |
| stalled | a comment to the assignee asking for the next step and a date; a due date when none is set; never a close |
| unanswered | answer it when the evidence answers it; otherwise route the question to who can answer, or ask |
| answered | carry the answer: the next step it implies (assign, status, a reply) |
| changed | respond to the change: a reopen to its assignee, a question to the owner answered or asked |
| tracked | the owner follows this ticket (its reason is on the ticket's line): judge its whole state after the change, as he would read it against that reason. Act only where another trigger would; otherwise a none whose `why` says in one line where it now stands (who holds it, what changed, what is left against his reason), or an ask when the change touches his reason |

## A fix that waits only on a check: verify it first

A ticket whose fix is live on a lane and that now waits only on someone checking it is not handed to QA by default
(the owner's word, 2026-11-26). First judge whether ela can test it itself, read-only over the product, as the test
account `li` (`TVU_TEST_ACCOUNT`; `el` is used only to switch li's bundle to the lane under test):

1. Where the fix is: `ela fixed-in <KEY> --json` (the lanes whose build carries it) or `ela release`.
2. Whether it can be driven: a behaviour in the product (`/ela:verify <KEY> --lane <lane>`, the version panel as
   proof), the stream itself (`ela stream probe`), the product's own data (`ela graph`, `ela logs`, Sentry). Set up
   what the case needs as li: a graph, a source the case allows (YouTube, HTML, HLS are at hand; a passthrough case
   cannot use YouTube; SRT is pushed by ela or by MediaHub from another source), a destination.
3. Write the plan, run it, keep the evidence in `<runtime>/browser/runs/<KEY>-<date>/`. The run must start with
   `ela browser env --key <KEY> --lane <lane> --shots <run>/shots --json > <run>/env.json` (the proven lane) and keep
   the cases' results in `<run>/cases.json` (`ela browser run --json`).

Then decide:

- **Pass**: an act with the single write `{"verb": "verified-close", "run": "<the run dir>", "lane": "<lane>"}`,
  confidence high, and the proof as the comment: the lane, the build, what passed, in a few lines. decide checks the
  run itself (env.json proven on that lane, cases.json passing by /ela:verify's verdict) and refuses anything less;
  the close goes out as `ela jira close --terminal`, signed, under its own class.
- **Fail**: an act that reopens it (`transition` to Reopened, or `assign` back to its developer) with the evidence in
  the comment: what was run, on which lane and build, what was observed.
- **Cannot be driven** (hardware, a customer's setup, a case li cannot reach): a short comment to QA built from the
  code: the cases to run, the lane, the build that carries the fix. A few lines, never a file-and-line explanation.

The worked case is MH-3823 on 2026-11-26 (run `<runtime>/browser/runs/MH-3823-2026-11-26/`): an SRT listener set up as
li on prod-3, two clients connected and dropped, the state read off the page. That run kept no env.json, so under this
gate it would have gone to the owner, not closed: start every run with the panel read.

## Replies to ela's comments

The prompt's last section lists each reply after a comment ela signed that no pass has judged. Mark each: does it
dispute what ela's comment said or did (the change was wrong, the evidence is wrong, it is not theirs, undo it)?
Conservatively: `false` only when the reply plainly agrees, thanks, or carries on without contesting; when unsure, it
is a dispute (`"unsure"` or `true`). A dispute is recorded as a correction of that ticket, not of the class: board-watch
keeps its tier, the reply becomes his ask, and ela posts no comment on that ticket for 7 days. A revert or his `wrong:`
quiets the field it names on its ticket the same way. The prompt marks a quiet ticket or field; decide ask or none for
it, or act on the other fields. Do not answer the reply yourself.

## The comment

- What changed and why, in two or three sentences, to the reader on the ticket. Cite evidence (a build, a
  comment, a log line) rather than a judgment. Never about a person.
- English, one language, also on a ticket written in Chinese (the owner's ruling, 2026-11-26).
- Do not sign it and do not repeat a comment ela already wrote there: jira.py appends the one signature line
  (`— ela, <owner>'s assistant, writing on his account. If this is wrong, reply here or message <owner>.`), and a
  repeated comment is refused.

## The file

Write `<reports>/ela/watch/<date>-decisions.json` (the prompt names the path):

```json
{"decisions": [
  {"key": "MH-1", "verdict": "act", "why": "one line for the owner's review", "confidence": "medium",
   "doubt": "the trace ends in the player, but nobody on the ticket has said so",
   "writes": [{"verb": "assign", "assignee": "<accountId>"}, {"verb": "transition", "to": "Review"},
              {"verb": "priority", "to": "High"}, {"verb": "due", "date": "2026-12-01"},
              {"verb": "link", "other": "MH-2", "type": "relates to"}],
   "comment": "Assigned to the player owner: the trace in the last comment ends in the player service."},
  {"key": "MH-3", "verdict": "ask", "kind": "ruling", "confidence": "medium",
   "why": "QA has not run the case on prod-3 yet",
   "question": "Close MH-3 as fixed on prod-3, or keep it for the QA pass?",
   "options": [{"letter": "A", "text": "keep it in Review for QA"},
               {"letter": "B", "text": "you close it yourself"}]},
  {"key": "MH-7", "verdict": "ask", "kind": "fact", "confidence": "low", "fact": {"kind": "owner", "key": "WebRenderer"},
   "question": "Who owns the WebRenderer now?", "options": [{"letter": "A", "text": "write the owner after the letter"}]},
  {"key": "MH-4", "verdict": "none", "why": "the reviewer answered in Slack; nothing is waiting", "confidence": "high",
   "judged_unneeded": ["assignee", "status", "priority", "due", "links", "comment"]}
 ],
 "replies": [{"key": "MH-5", "reply": "10234", "disputes": false},
             {"key": "MH-6", "reply": "10240", "disputes": "unsure"}]}
```

A none names in `judged_unneeded` the fields you looked at and judged need no change, from: assignee, status,
priority, due, links, comment. It is how ela measures itself: a none whose field a person then changes within a week
counts as a miss, so name only what you actually judged.

Then run `ela watch decide --from <that file>`: a dry run that checks every decision against the gates
(the verbs, terminal statuses, one set a day, the language rule, a repeated comment) and shows each write as
jira.py would make it. Fix what it refuses, or turn it into an ask. Your last message lists, per ticket, the
verdict in one line.

## Judge mode: a ticket that reaches the owner arrives judged

`/ela:watch judge KEY --write PAGE` is a different session from the pass above: one ticket, read to the bottom,
unattended (`ELA_NO_APPLY`). Read `judge.md` first: the input, the letter that binds the verdict, the page, the
decision file and the one-line verdict are there.

## The second reading

A second session, after the decider, reads again what the decider could not settle. Read `second-reading.md` first:
the cases, the first-hand source that settles one, the review file and its check are there.
