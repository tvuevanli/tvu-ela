---
name: watch
description: The MH board watch's judgment pass — for each ticket `ela watch` found due, decide act, ask or none. Run by the runner's watch session.
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
  — and always one `comment` that says, to the people on the ticket, what changed and why. A comment alone
  is an act too (a question to the assignee, a nudge on a stall, the answer a reply was waiting for).
- **ask** — the owner decides. Use it when the right move is unclear, when the evidence does not settle it,
  and always for what ela never does: a terminal status (Done, Closed, Cancelled, Won't Fix, Failed), a Slack
  post under his name, anything for a customer channel, anything about a person (their work, their speed,
  their attitude). The question is one sentence he can answer with a letter; offer two or three options, the
  first the one you recommend; an option may carry the writes and comment that carry it out.
- **none** — nothing is due after all (the trigger is noise, the ticket is moving, the question was answered
  elsewhere). Say why in one line. Prefer none to a comment that adds nothing.

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

## Replies to ela's comments

The prompt's last section lists each reply after a comment ela signed that no pass has judged. Mark each: does it
dispute what ela's comment said or did (the change was wrong, the evidence is wrong, it is not theirs, undo it)?
Conservatively: `false` only when the reply plainly agrees, thanks, or carries on without contesting; when unsure, it
is a dispute (`"unsure"` or `true`). A dispute is recorded as a correction: board-watch returns to the owner's confirm,
the reply becomes his ask, and ela posts no comment on that ticket for 7 days (the prompt marks such a ticket; decide
ask or none for it). Do not answer the reply yourself.

## The comment

- What changed and why, in two or three sentences, to the reader on the ticket. Cite evidence (a build, a
  comment, a log line) rather than a judgment. Never about a person.
- English. When the ticket's text is Chinese (the prompt says so), bilingual: the English paragraph first,
  then the same in Chinese.
- Do not sign it and do not repeat a comment ela already wrote there: jira.py appends the one signature line
  (`— ela, <owner>'s assistant, writing on his account. If this is wrong, reply here or message <owner>.`), and a
  repeated comment is refused.

## The file

Write `<reports>/ela/watch/<date>-decisions.json` (the prompt names the path):

```json
{"decisions": [
  {"key": "MH-1", "verdict": "act", "why": "one line for the owner's review",
   "writes": [{"verb": "assign", "assignee": "<accountId>"}, {"verb": "transition", "to": "Review"},
              {"verb": "priority", "to": "High"}, {"verb": "due", "date": "2026-12-01"},
              {"verb": "link", "other": "MH-2", "type": "relates to"}],
   "comment": "Assigned to the player owner: the trace in the last comment ends in the player service."},
  {"key": "MH-3", "verdict": "ask", "question": "Close MH-3 as fixed on prod-3, or keep it for the QA pass?",
   "options": [{"letter": "A", "text": "keep it in Review for QA"},
               {"letter": "B", "text": "you close it yourself"}]},
  {"key": "MH-4", "verdict": "none", "why": "the reviewer answered in Slack; nothing is waiting"}
 ],
 "replies": [{"key": "MH-5", "reply": "10234", "disputes": false},
             {"key": "MH-6", "reply": "10240", "disputes": "unsure"}]}
```

Then run `ela watch decide --from <that file>`: a dry run that checks every decision against the gates
(the verbs, terminal statuses, one set a day, the language rule, a repeated comment) and shows each write as
jira.py would make it. Fix what it refuses, or turn it into an ask. Your last message lists, per ticket, the
verdict in one line.
