---
name: watch
description: The MH board watch's judgment pass — for each ticket `ela watch` found due, decide act, ask or none; and the second reading of what the decider could not settle. Run by the runner's watch sessions.
user-invocable: false
---

# /ela:watch — a decision for each MH ticket the watch found due

Self-contained. The rule is the owner's decision of 2026-11-24 (elak `blueprint/decisions/2026-11-24-ela-watches-the-mh-board-and-acts-on-jira-signing-each-write.md`).
The pass runs unattended (`ELA_NO_APPLY`): it reads, decides and writes one file. Nothing in it reaches Jira
or Slack; the runner carries the file out afterwards, through gates the pass cannot bypass.

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

`/ela:watch judge KEY --write PAGE` is a different session from the pass above: one ticket, read to the bottom. The
rule is the owner's (2026-11-26; plan ela/2026-11-26-plan-tickets-reach-you-judged in the vault): a ticket assigned to
him in Review, or handed to him, reaches him with a verdict and a link, never as a bare listing. The runner starts it
for each ticket `ela watch judge` lists, at most its daily cap of deep readings, as an unattended session
(`ELA_NO_APPLY`).

**Input.** `ela watch judge-prompt KEY`: the ticket, every comment, the linked tickets, its home in the vault (a
feature or project page listing its own key, then its ticket pages), and every board-watch topic on it with the owner's
letter. **A letter he gave binds the verdict.** Depart from it only on evidence dated after the letter, and then say
in the verdict that you do and why. His letter approved words, not writes: when the option he chose carried no writes
and its words imply one (an assignment, a move), write that act with `confidence: low`, so it waits on ela/watch.md
for his confirm with the writes spelled out; never write it at high or medium on the strength of the letter.

**Gather, first-hand.** The ticket and its links (`ela jira read KEY`, `ela links KEY`); QA's reports on it (`ela mail`,
`ela slack`, `ela digest` for a report or a thread); where its fix is (`ela release`, `ela train`); who holds what
(`ela team`). `/ela:explain` makes the ticket judgeable; `/ela:probe` reads the code. Whatever cannot be read is named
as a gap, never filled from someone's summary.

**Untested parts.** Where something is fixed but QA has not tested it (a case not run, a lane not reached, a branch
of the code no case covers), read the code of that part and say what it does, with file and line, and what could
fail. That reading is ela's own assessment, marked as such; it never replaces QA's verdict.

**The page** (`PAGE`, `<reports>/ela/<date>-deep-<KEY>-judged.md`, its own file beside any deep pick's page that
day; the vault files it as the ticket's page):

- `# KEY · <summary>: <the verdict in a few words>`
- the verdict first: one or two sentences, what the ticket's state is and what should happen next, and who does it
- *Next steps*: each with its owner and, where one is known, its date; a step for the owner is a decision only he can make
- *Untested*: each untested part with the code reading above
- *Drafts*: a comment or a ticket the next step needs, as text for the owner's word (a Jira write goes through the
  decision file, not this page)
- the facts it rests on, folded (`> [!note]- Facts`): QA's results by case and build, the lanes, the timeline, each
  with its source link

**A new topic gets an entry.** When the prompt's home is empty, the topic is new to the owner, and the ticket page you
write is its entry: open it with two lines on what the capability or the problem is, for a reader meeting it the first
time. Open no project and no other page: a project is bounded work the desk opens on a committed date, and the vault's
features/ pages (the owner's ruling of 2026-11-26) come with their own plan. When the topic is a capability that will
outlive this ticket (two or more tickets, configuration or lanes to follow), say so on the page in one line, "a feature
page fits: <key>, <title>", which the desk reads. The mechanism you read first-hand (flow, configuration keys, error
codes) stays on the ticket page with its sources; an unattended session does not write elak.

**The decision.** Write `<reports>/ela/watch/<date>-judge-<KEY>.json` with one decision in the pass's form
(`{"decisions": [{...}]}`): act, ask or none, with confidence and doubt as above. It is checked against the judge
queue: `ela watch decide --judge KEY --from <file>` (a dry run). An act or a none closes the ticket's open topic as
superseded; an ask updates it. An option that names a write (assign, move, link, priority, due) carries that write and
its comment, or it is refused.

**The verdict.** Your last message is one line, the verdict, at most 160 characters, ela's own words (never the
ticket's title or a listing). The runner records it with `ela watch judged KEY --verdict "…"` once the page exists
and the decision passed; today.md shows it where it names the ticket, with a link to its home.

## The second reading

A second session, after the decider, reads again what the decider could not settle: a ruling ask whose option A is
only the watch's own writes (assign, a non-terminal status, a raised priority, a due date, a link), and a low act.
Those wait as review-pending, off the owner's page, until this reading. Asks that are never ela's (a close, release
scope, a person, Slack, a lowered priority, Fixed In, labels) never come here; they went straight to him.

`ela watch review prompt` lists the cases. You have the decider's tools: read first-hand what the decider did not (the
ticket's comments, `ela release`, `ela mail`, `ela slack`, `ela configserver`, `ela team`, `ela asks fact get`). A case
is settled only by a first-hand source you read yourself, named as `{"kind", "ref"}`, kind one of: reporter-comment,
qa-report, build-record, config-value, roster, owner-fact. Agreeing with the decider is not a source; a precedent
strengthens a leaning but does not settle a case. Write `<reports>/ela/watch/<date>-review.json` (the prompt names it):

```json
{"cases": [
  {"topic": "watch:MH-1", "settles": true, "letter": "A",
   "source": {"kind": "build-record", "ref": "mh-web build 2.2.170 carries the merge"}, "why": "one line"},
  {"topic": "watch:MH-6", "settles": false, "why": "what you read, and why it does not settle it"}
]}
```

Then `ela watch review settle --from <that file>` (a dry run) checks it. A settled ruling ask is closed with its letter
and its writes go out at the next pass; a settled low act stays with the owner, your source shown beside it, until his
amendment of the low-act rule is recorded. A case you leave unsettled reaches him with your `why`, so he sees what was
tried. A case you leave out of the file stays pending; if the reading fails or times out, the runner releases every
pending case to him marked "not read twice".
