---
name: ask
description: Hand one question to a counterpart agent (a bot another team owns) and turn its answer into a decision for Evan — pick the agent from the registry, check first-hand that the question is inside its charter, address it in its own dialect, then cross-check its reply against what it cannot see. Use for "让 boundary agent 查一下", "这个卡顿问一下它", "谁能查这个 graph 的 SRT", or when a thread carries a symptom plus an id and the answer belongs to another team's agent. v1 addresses mm-boundary-agent only.
user-invocable: true
---

# /ela:ask — a symptom in, another agent's evidence out, with what it could not see

Self-contained. Argument: a Slack thread permalink, or a graph id plus the symptom in words.
`route` finds the right **person**; `ask` finds the right **machine**.

## Invariants
- **The registry is the only source of who can answer what.**
  `<records>/knowledge/products/mediahub/team/agents.yaml`. A handle that is not there, or a row whose
  `charter` is `unknown`, is **never addressed** — the same rule the roster carries for people.
  `charter` is the owner's assertion and this skill never edits it; `coverage` it may update, dated.
- **Verify the question is in charter before spending someone else's agent.** The check is first-hand
  (step 1), not a reading of the words in the thread. The number this skill is judged on is the
  misroute rate, not the hit rate: answering well is their business, addressing the right one is ours.
- **Never re-summarise the agent's answer.** Its own text is better than a paraphrase of it and a
  paraphrase adds a place to invent. Link it, then add only what it could not see (step 5).
- **`unread` is not `clean`.** mm-boundary-agent states which surfaces it could not read. That
  distinction is carried through to Evan verbatim; collapsing it into "healthy" is the main way its
  output gets misused.
- **One question per thread per turn.** Its follow-up round belongs to a human; this skill never
  auto-replies to the agent's reply.
- **A machine never answers a machine's ground-truth check.** mm-boundary-agent asks for a
  confirmed/partly/wrong reaction after a conclusion. That emoji is Evan's.
- **Never unprompted, never in someone else's thread.** ela addresses another team's agent only in a
  thread Evan opened or in which he asked for it. Observation-triggered asking does not exist here.

## 0 — bind
```bash
S="python3 ${CLAUDE_PLUGIN_ROOT}/skills/slack/slack.py --env-file <env>"
G="python3 ${CLAUDE_PLUGIN_ROOT}/skills/graph/graph.py --env-file <env>"
REG=<records>/knowledge/products/mediahub/team/agents.yaml
```
From a permalink: `$S read <permalink>` — take the ids and the symptom from the thread, not from Evan's
paraphrase of it. Extract: graph id (`01` + 24 chars), process id (32 hex), an environment word, and
the symptom class (stall/停顿·卡顿 · latency · disconnect · no media · quality).

## 1 — the pre-check that prevents the misroute (first-hand, before any agent is addressed)
```bash
$G <graphId>                    # node table in pipeline order; -d adds box and image
$G process <32-hex pid>         # a process id first resolves to its graph, then the same check runs
```
Two conditions:
- the id **resolves live**, and
- its first and last nodes are a **boundary** — ingress and egress, *whatever their type*
  (`srt_decoder`, `srt_copier`, `mpegts_receiver`, `issp_decoder` have all been observed; the
  position is the criterion, not a list of names).

Both hold → hard pass. Resolves with no boundary → **refuse and say what the topology is instead**:
a symptom in words never overrides the topology, and "卡顿" on a graph with no boundary node is not
an SRT question.

**Does not resolve → decode the ULID before deciding.** The first 10 characters are a Crockford
base32 millisecond timestamp; decoding gives the graph's creation time with no lookup (verified
against the agent's own "connection coverage: read back to graph start" line, to the minute).
- created recently and the incident is recent → **soft pass**: ask anyway. The agent holds a
  deleted-record reader that ela does not, and a live-read miss is not evidence of absence.
- old *and* not live → say so and stop; but never argue age at a graph that is live. A graph 37 days
  old was read normally because it was still running. **The criterion is liveness, never age.**
- Whatever the outcome, the decoded creation time goes to Evan: the agent's own miss-explanation
  ("probably more than a couple of weeks ago") has been wrong on a graph 8 hours old, and the ULID
  settles that in one line.

## 2 — select, and record what was rejected
Match the symptom class against `charter.does` / `charter.does_not` of each row. State the choice with
the alternative rejected and why (evidence level, not preference). If two rows both match, ask Evan —
do not fan out; two agents on one question is two teams' attention for one answer.

## 3 — compose in the agent's own dialect
Address by id: `<@U0BEP9U4KGD>` — **Slack renders a mention only from `<@Uxxx>`; the literal text
`@mm-boundary-agent` does not trigger it.** Carry the graph id (it picks the id up from earlier in the
same thread on a follow-up), name the environment (it defaults to prod when none is given), and name
the counters the symptom needs — for a stall: `pktRecvTotal`/`pktSentTotal`, loss, retransmits, drops,
RTT, negotiated TSBPD latency. Ask one question.

## 4 — send
```bash
$S post <thread permalink> --text "<@U0BEP9U4KGD> …"           # dry run
$S post <thread permalink> --text "<@U0BEP9U4KGD> …" --apply    # sends
```
**The confirm tier (Evan, 2026-09-04):** in a thread where Evan addressed ela, his message *is* the
approval — on a **hard pass** (step 1: resolves live, boundary present) send with `--apply` and show
him the decision line, not a dry run to approve. On a **soft pass** (does not resolve, ULID recent)
or an ambiguous symptom class, dry run and wait. The protection is the deterministic pre-check,
which does not tire; not a second click.

Then wait for the reply: it acknowledges in seconds, posts a per-surface progress list, and the body
lands about a minute later (`$S read <permalink>` again). A body that never arrives is `outcome: error`.

## 5 — the value ela adds: cross-check, not summary
Output to Evan is **the agent's reply (link) + `ela 补充`, three to five lines**. Only what the agent
structurally cannot see:
- **beyond the one graph** — image and box against `<map>/services.yaml` (who owns that image) and the
  release facts (which bundle carries that version, what runs on that environment);
- **evidence vs unread** — restate which surfaces were unread, so a fluent paragraph is not read as
  a clean bill of health;
- **his standards** — is this a ticket, which layer, who is notified inside 4h (`route` owns the name);
- **across threads** — the same box or image seen in an earlier observation row.

If there is nothing to add, write `无补充,可直接采信`. That is a valid output and it is more honest
than a manufactured paragraph.

## 6 — record
Append one row to `<records>/records/agents/observations.jsonl` in the shape its README fixes:
`at · agent · thread · asked · trigger · rejected · outcome · in_scope · seconds · coverage_note`.
`in_scope: false` is a misroute — the number that gets counted. A coverage fact the reply revealed
(a window that moved, a new gap) also updates `coverage` in the registry, with the date; a reply that
contradicts `charter` updates nothing and instead drafts one question for the agent's owner.

## Exit test (this capability is Evan-only until it passes)
Five real handoffs answered inside charter, judged useful by Evan, and zero misroutes. Until then,
nothing this skill produces is exposed to anyone but Evan
(decision `2026-09-03-nothing-reaches-others-until-proven`).
