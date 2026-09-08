---
name: explain
description: Make one ticket judgeable — the runtime instance behind it, whether the fix named on it still exists, what the ticket asserts versus what was decided in the thread, and who it is waiting on. The first step before route, probe, feasible or breakdown, and the step that makes their conclusions reviewable. Use for "这票在说什么", "先讲清楚这张票", "MH-xxxx 到底什么情况", "这个 ticket 我看不懂", or when a ticket arrives from someone else's hands.
user-invocable: true
---

# /ela:explain <KEY | permalink> — a ticket in, a judgeable picture out

Self-contained. Argument: a Jira key or URL, or the Slack permalink a ticket came from. Read-only
everywhere; the output lives in the conversation and is not written anywhere.

## Who this is written for

The owner — the person carrying MediaHub product responsibility across teams they do not manage.
They know the product, and on most tickets they witnessed or made part of the history. Two
consequences, and they are the whole discipline of this skill:

- **Never explain a product concept.** What seamless switching is, what a switcher node does, what a
  copier or a destination type is — that is known. A sentence the reader could have written
  themselves is noise, and enough of them make the output unreadable at exactly the moment it must be
  scanned.
- **Output only what is not on the ticket.** The ticket is readable without this skill. The value is
  the runtime instance, the state of the code, the decision that only exists in a thread, and the
  name of whoever is blocking — each with its source. Restating the description is the failure mode.

No diagrams, no teaching, no summary of the summary. Dense lines with a citation each.

## Invariants
- **Cheap, or it will not be run first.** Two reads always (the ticket, the thread it came from),
  and at most two more (the runtime instance, one fix-state check). If an answer needs code traced
  through layers, that is `/ela:probe` — name the question and stop, do not start tracing.
- **Nothing is concluded.** No root cause, no owner assignment, no feasibility verdict. This skill
  makes those judgeable; it does not make them.
- **A ticket's own root-cause section is an assertion.** In this Jira the reporter and the first
  responder both write confident causes; they are day-one readings. Mark which is asserted and which
  is established, and say by what.
- **The last comment is not the decision.** Decisions are made in the thread and rarely land on the
  ticket. The thread is read to the end, every time.
- **An unknown is stated as an unknown.** No runtime evidence, no live graph, an external config in
  no repository — each is a line in the output, never a gap the reader has to notice.

## 0 — the ticket and its thread
`~/.claude/ela/site.json` → `env`, `map`, `published`. Then:
```bash
JIRA="python3 ${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py --env-file <env>"
SLACK="python3 ${CLAUDE_PLUGIN_ROOT}/skills/slack/slack.py --env-file <env>"
$JIRA read <KEY> --deep
$SLACK read <permalink>        # the description's source link, and any permalink in the comments
```
Take from them: the symptom as the reporter saw it, every id (graph, object, process, commit,
environment), who was asked, who answered, and what changed between the description and the last
message.

## 1 — the runtime instance
A MediaHub ticket is about a pipeline that either exists or does not, and that fact decides how much
of the ticket is evidence and how much is intention.

```bash
GRAPH="python3 ${CLAUDE_PLUGIN_ROOT}/skills/graph/graph.py --env-file <env>"
$GRAPH resolve <id>                 # an id in the ticket or the thread — graph, process, object
$GRAPH graphs <reporter email>      # no id: does the case still exist under the reporter?
```
Report the node chain as it is, its environment, and whether it is still alive. When nothing is
found, say so and say what it costs: a ticket with no instance has never been verified end to end,
and any "works" or "does not work" on it is a reading of a screen, not of a pipeline. Where an output
cannot be probed at all (a mesh, a customer's own receiver), that is a permanent gap, named once.

## 2 — the state of the fix
A ticket names commits; a reverted commit reads exactly like a shipped one on the ticket.
```bash
ela find <repo>            # the checkout the map names
git -C <path> log --oneline -1 <sha> 2>/dev/null || echo "not in this checkout"
git -C <path> log --oneline --all --grep <sha>      # a revert names the sha it undoes
```
One line: in HEAD, undone (by which commit), or never merged.

## 3 — the ticket against the thread
Two short blocks:
- **asserted vs established** — which sentence of the description or the root-cause comment is a
  claim, and what is established, by what evidence. Only where the two differ; a ticket that is
  accurate gets one line saying so.
- **what the thread decided** — the decisions that never reached the ticket, in order, each with who
  made it. This is usually the most valuable block, and on a ticket whose direction changed it is the
  only place the current direction can be read.

## 4 — who it is waiting on
One of: a product call, an owner's work, or nothing at all (the ticket is finishable now). Name the
person and what exactly is expected from them. Layer tags and owners belong here only as far as they
identify the blocker — the full lane split is `/ela:breakdown`, the owner search is `/ela:route`.

Close with the next skill: `route` (owner unknown), `probe` (cause unknown), `feasible` (the ask is
a capability question), `breakdown` (direction settled, work to split), or none — say which and why.

## Output
Four blocks in this order — runtime, fix state, ticket against thread, waiting on — each line
carrying its source (`file:line`, a commit, a comment date, a graph id). No headings beyond those
four, no restatement of the description, no closing summary. A block with nothing worth saying is one
line, not a paragraph.

## What this skill does not do
- Trace code across layers, read a service's source, or produce `file:line` of its own. It cites what
  a prior probe or a thread already established, and turns anything else into a question for probe.
- Write anywhere: no Jira comment, no Slack reply, no elak file. Its output is a reading for one
  person, cited by whoever acts next, not archived (`CLAUDE.md`, hard rule 7).
- Replace `/ela:digest`. That one owns a thread — a report, a long investigation; this one owns a
  ticket.
