---
name: arch
description: Review a subsystem's architecture as it actually is — MediaHub's app layer, unified-resources, media, one service, or the boundary between two. Renders the derived fact base into a picture stamped with the commits it was read at, checks it against a live graph, then judges the structure: ranked findings, each priced with the tickets and incidents the seam produced, each with the layer and owner it belongs to. Read-only; findings become lanes through /ela:breakdown, never tickets here. Use for "做个架构 review", "UR review", "media 层的结构看一下", "这个依赖对不对", "重构该从哪开始", or when the same seam produces a third bug.
user-invocable: true
---

# /ela:arch <subsystem> — the structure as it is, then the reading

Self-contained. Argument: `mediahub app` · `unified-resources` · `media` · one service · a boundary
between two (`mx-service ↔ orchestration`). Read-only throughout: code, Jira, Slack and the runtime
are read; nothing is created, and the findings are handed on rather than filed.

A structural verdict routes months of other people's work, so this is the one output where being
right matters more than being fast. It has exactly two failure modes, and every invariant below
exists against one of them: **taste** (a finding with no price) and **staleness** (a picture drawn
once and believed afterwards).

## Invariants
- **The picture is generated; the reading is written.** `deps.py render` projects
  `map/dependencies.yaml` at the commits its edges were read at. Never hand-draw a box, and never
  edit a render — regenerate it (decision
  `2026-09-07-derived-facts-are-generated-knowledge-carries-the-reading`, which rejected a
  hand-maintained architecture document precisely because its mechanical half rots silently).
- **Name the standard before drawing.** A review with no standard is taste with a diagram. The
  standards available: the layer model (`[Infra] [J2N] [Media] [App] [UI]`), the recorded decisions
  in `blueprint/decisions/`, the stated intent of the rearchitecture (source / destination /
  process), and `tvu-standards` module-first — consulted, never binding. Every finding names the one
  it is measured against.
- **As-is and to-be are two pictures.** A single diagram that mixes what runs with what should run is
  the classic architecture-review lie. The render is as-is by construction, because it is a
  projection of what the code declares; a proposal is drawn separately and labelled.
- **A finding carries its price or it is deleted.** The price is evidence, not adjectives: the
  tickets that seam produced, the incident cluster, how far a change there reaches at promotion, who
  gets routed at it and how often. An ugly structure that has cost nothing is not a finding.
- **The code's call graph and the runtime graph are different shapes, and both are needed.** A
  service can be architecturally central and runtime-irrelevant, and the reverse. Only UR says what
  actually runs.
- **What was not read is named, not omitted.** The scan's three blind spots (config-server
  addresses, event bindings written in Java config, a frontend's run-time `initConfig`) are in the
  artefact's header and belong in the output too. A gap is legible; a guess is not.
- **Findings become lanes, never tickets here.** `/ela:breakdown` cuts and publishes them, behind its
  own confirm.
- **People appear as roles; no addresses, no credentials.** A review is the artefact most likely to
  be shared onward.

## 0 — bind
Read `~/.claude/ela/site.json` → `env`, `map`, `elak`, `code`.
```bash
DEPS="python3 ${CLAUDE_PLUGIN_ROOT}/skills/map/deps.py"
MAP="python3 ${CLAUDE_PLUGIN_ROOT}/skills/map/map.py"
GRAPH="python3 ${CLAUDE_PLUGIN_ROOT}/skills/graph/graph.py --env-file <env>"
JIRA="python3 ${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py --env-file <env>"
```
**Read Evan's own prior reading first** — `knowledge/products/mediahub/app-dependencies.md`,
`knowledge/platform/unified-resources/README.md`, `knowledge/platform/media/README.md`, and the
area's decisions. That is the baseline; a review that re-derives what he already concluded is wasted,
and a review that contradicts it must say so explicitly.

## 1 — is the fact base current?
```bash
$DEPS check --fetch          # which repos moved since the scan — staleness is a rev-parse, not a date
$DEPS scan --write --fetch   # when any did: re-derive before drawing
$MAP coverage                # is the code we need on disk at all
```
A picture drawn on a stale scan is worse than no picture. State the commit each fact was read at, in
the output, every time.

## 2 — render the as-is
```bash
$DEPS render --out <runtime>/arch/<date>-<subsystem>.mmd     # whole app layer
$DEPS render --focus <service>                                # one service or one boundary
```
Then **read the render before judging it**. What the picture is for:
| what to look at | what it means |
|---|---|
| the node with the most out-edges | the hub — a change there reaches everything; `mx-service` is one today |
| edges **inside** the app subgraph | intra-layer coupling; a pair with edges both ways is a cycle |
| the `owner unknown` subgraph | the platform layer nobody in the review owns — the routing cost |
| `url` on an edge | pinned address, bypasses Eureka: invisible to service discovery and to failover |
| dashed edge / `client only` | a declared client with no call site at this ref — a claim to verify, never a verdict |
| `?<property>` | a real edge to a callee only the config server can name |

## 3 — check it against what runs
`$GRAPH` on a live graph of the area: the node table in pipeline order **is** the media path as
built. For an app-layer review, one graph is enough to test whether the picture's centre is also the
runtime's centre; for a media or UR review the runtime is the subject, and the code is the check.
Name the environment and the graph id.

## 4 — read the code where structure is decided
Hand the read-only **analyst** agent specific *structural* questions, one repo at a time — never a
free-form "review this repo":
- where does the state for X live, and who else writes it
- is the contract in one place, or restated per caller
- what does this module know about its callers
- is the seam crossed in both directions, and at which line
This is not a code review. Bugs found here are noted and handed to `/ela:probe`; they are not
findings of this skill unless the *structure* produced them.

## 5 — price every candidate
For each candidate, before it may be called a finding:
```bash
$JIRA jql 'project = MH AND text ~ "<the seam'"'"'s own words>" ORDER BY created DESC'
```
- the tickets and the incident cluster it produced (keys, verbatim signature words — not a summary)
- how far a change at that seam reaches: which bundle, which lanes, whose promotion
- who is routed at it, how often, and whether the routing is ever wrong because of it
Rank by price. Drop what has no price, and say how many were dropped — that number is what keeps the
review honest.

## 6 — output
1. **中文 for Evan** — the standard used · the picture · the ranked findings table (finding · what it
   costs, cited · layer · owner · the cheapest change that removes the cost) · what could not be read
   · how many candidates were dropped for having no price.
2. **The artifact** — the render plus the findings table, published private. Load `artifact-design`
   first; mermaid goes in ```mermaid fences and renders natively. One review, one URL; a re-run of the
   same review republishes to it (`/ela:reports` holds the rules for standing reports — a review
   asked for a second time belongs there instead).
3. **The working file** — `<runtime>/arch/<date>-<subsystem>.md`: the standard, the findings with
   their prices, the commits read, the artifact URL. It is a draft and is not kept; the artifact is the copy.
4. **The durable reading**, on Evan's word — into `knowledge/<area>/…`, citing `map/dependencies.yaml` and never
   restating its rows. Only what a script cannot produce: which edge is load-bearing, which seam
   should not exist, what to close next.
5. **On Evan's word** — `/ela:breakdown` takes the findings that are work and cuts them into lanes.

## What this skill does not do
- Create or transition a ticket, edit code, hand-maintain a diagram, or publish outward.
- Hunt bugs — that is `/ela:probe`. Answer "can we support X" — that is `/ela:feasible`. Decide the
  rearchitecture — that is Evan's and the product's.
- Explain a system to someone who lacks the background: this output is dense on purpose. The
  zero-background picture explainer is the upstream `/eli5` skill, a different job with a different
  audience.
