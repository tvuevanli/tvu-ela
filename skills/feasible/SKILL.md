---
name: feasible
description: Answer "do we support this, and can we?" for a capability someone asks about — a customer requirement relayed in Slack, a Jira ask, a sales question. Splits the ask into checkable items, traces each to the point where it would actually take effect, and returns two verdicts per item: what happens today (with runtime evidence) and whether it can be supported (with the layer it is blocked at and the cost). Use for "我们支持吗", "能不能做到", "客户要 X，我们行不行", "confirm whether HLS supports …", or any thread that asks for a capability answer rather than a bug fix.
user-invocable: true
---

# /ela:feasible <thread | ticket | ask> — a capability question in, two verdicts out

Self-contained. Argument: a Slack permalink, a Jira key or URL, or the ask in Evan's own words.
Read-only everywhere: code, Jira, Slack, UR and the stream are read; nothing is changed and no
answer leaves the machine until Evan says post.

## The discipline this skill exists for
**A field in the code is not a supported capability.** Three failure shapes, all one pattern —
a reading taken at one layer and promoted to a conclusion about the whole chain:

- `StreamProfileParam.mpegtsPmtStartPid` is declared and never written. Reading the model says
  supported; it is not.
- `videoStartPid` is set in the profile, sent in `CreateInstance`, parsed by the copier — and dropped
  when the HLS branch builds its command line. Reading the app says supported; the output says 256.
- A "not supported" answer from the owning layer described that implementation, not the engine
  underneath it: the bridge across the engine's own internal boundary (`hls_ts_options`) existed
  all along. An owner is authoritative about their code and not about what their dependency can do.

So a verdict is only as good as the checkpoint it was taken at, and there are five.

## The five checkpoints
Every item is traced along this chain, and the verdict names where it stops:

```
① UI / profile      the field can be entered and stored
② app → downstream  it is in the payload the service actually sends
③ process command   it reaches the binary's arguments
④ engine            the binary has somewhere to put it
⑤ output            it is in the bytes on the wire
```

A break at ① or ② is app work. At ③ it is the adapter or its command template. At ④ it is either
an unwired option or a real engine limit — **and those two must be told apart** (see step 4).

## 0 — bind
Read `~/.claude/ela/site.json` → `env`, `map`, `elak`.
```bash
SLACK="python3 ${CLAUDE_PLUGIN_ROOT}/skills/slack/slack.py --env-file <env>"
JIRA="python3 ${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py --env-file <env>"
GRAPH="python3 ${CLAUDE_PLUGIN_ROOT}/skills/graph/graph.py --env-file <env>"
STREAM="python3 ${CLAUDE_PLUGIN_ROOT}/skills/stream/stream.py"
MAP="python3 ${CLAUDE_PLUGIN_ROOT}/skills/map/map.py"
```

## 1 — the ask, as checkable items
Read the source first-hand: `$SLACK read <permalink>` (on `not_in_channel` the script says whether
the bot may join — joining is visible, so it is Evan's call, not the skill's), `$JIRA read <key> --deep`.

Then **split the ask into items that can each be answered yes or no**, in the asker's own numbers.
A customer's "keep the same PID mapping" is five items (PMT, PCR, video, audio, service metadata),
not one. Items that travel together in the ask often part company in the code — that separation is
most of this skill's value. State the items back before investigating: a wrong split makes every
verdict below it wrong.

## 2 — the runtime anchor
If a live example exists, take it — it is worth more than any amount of reading.
`$GRAPH graphs <email>` → the graph, `$GRAPH graph <id> -d` → the nodes with their images and
`profileId`, `$GRAPH profile <id>` → what the profile actually holds. Write down the image tags:
they pin which source is under investigation.

**A contrast pair is the strongest artefact available.** Two graphs, same object and same profile,
differing only in the item under question, settle in one comparison what days of reading argue
about. Look for one before building an argument; ask Evan to create one if the ask deserves it.

## 3 — trace each item through the five checkpoints
`$MAP find <image|process type|word>` for the repos, then read them — the analyst agent with
**specific questions**, one per checkpoint, not "see if it supports PIDs":

- ① where is the field entered, stored, and read back — and **is it ever written**? A declared field
  that no writer touches is the commonest false positive; `grep -rn` the setter, not the type.
- ② is it in the payload? The service's own log of the outbound call beats reading the builder.
- ③ does it reach the arguments? Command templates (`plugin_cmd.xml`) and their `snprintf` call sites
  are where fields die quietly — a value can be parsed, logged, and never used. **The process's own
  command line, from its log, is the fact**; the template is only the explanation.
- ④ does the engine have a place for it? Name the option and its file:line, or say there is none.
- ⑤ `$STREAM probe <output>` — what actually came out. **No item is closed "supported" without this.**

Where the same capability works on a neighbouring path, diff the two — the difference is the answer,
and it is usually one structural fact (one muxer versus two, one process versus a pipeline).

## 4 — when today's answer is "no", ask the second question
"Not supported" is a statement about the implementation. Whether it *can* be supported is a separate
finding, and skipping it is how a capability request dies for the wrong reason.

- **Look for the bridge before concluding a limit.** Engines usually provide a way across their own
  internal boundaries; the absence of an option at one level rarely means absence at the next.
- **Prove it with the smallest thing that runs.** A one-command reproduction against the same engine
  outside the product — the customer's own target values, on any input — converts "should work" into
  "does work" for the cost of a minute. When the local build differs from the shipped one, say so and
  name what stays unverified.
- **Distinguish a rename from a removal** when the local engine and the shipped engine differ in
  version; an option missing locally may be present under another name in the build that matters.
- **A derived value is not a gap.** Before asking for a knob, check whether the value already follows
  from one that exists (PCR PID follows video PID). Cheapest capability is the one already there.

## 5 — conclude, in two tables
**Today** — one row per item: verdict (supported · partial · not) · the checkpoint it stops at ·
the evidence (file:line, command line, `$STREAM` output). No row without a path.

**Feasible** — one row per item: yes/no · the layer that must change · the cost band (a template
line · an app field · an engine patch · architectural) · what it depends on.

Then, separately: **the change list** by layer with owners from the roster, and **what stays
unverified** — named, not omitted. Where an item's cost depends on an answer only the asker has,
say so and put the question in the draft rather than guessing a scope.

## 6 — record and draft
- Record what the answer **established**, drafted here and written on Evan's word, where the placement test sends it (decision
  `2026-09-07-elak-is-elas-knowledge`): a capability limit and where it is enforced is a fact about the
  product → `<elak>/knowledge/products/mediahub/`; a platform limit → `<elak>/knowledge/platform/<component>/`.
  A dated file of "what this run checked" is not kept. The two tables, the evidence paths, the change
  list. Reproduction commands go in verbatim: the next person to verify the fix needs the same ones.
- Drafts, each a separate confirm: one for the asker (per item, plainly; the open question if there
  is one; no schedule promised), one for the owner (the checkpoint that breaks, file:line, the
  reproduction, the proposed change). `$SLACK post <permalink> --file …` shows the dry run; `--apply`
  only after Evan's word.

## What this skill does not do
Change code, build, deploy, start or stop anything, post without confirmation, or promise a schedule.
It also does not replace `/ela:probe`: probe explains a thing that is broken, this one judges whether
a thing exists and whether it can. When the ask turns out to be a defect, hand over to probe.
