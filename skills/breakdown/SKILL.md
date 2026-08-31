---
name: breakdown
description: Turn a requirement (Jira keys, Slack permalinks, Evan's own framing — any mix) into a plan of layer-tagged lanes with owners, dependency order, and verification; two depths (knowledge / code); the plan lands in ela-knowledge, Jira publication only on explicit confirm. Use for "break this down", "拆解", "拆票", "出个方案", "谁该做什么", or any multi-layer requirement that needs lanes before work starts.
user-invocable: true
---

# /ela:breakdown <keys / permalinks / framing…> — requirement → lanes, plan first

Self-contained. Arguments: any mix of Jira keys, Slack permalinks, and freeform framing. Evan's
framing is first-class input — it often carries the decision the sources lack.

## Invariants
- **Read first-hand.** Tickets via the jira capability, threads via the slack capability, code via
  the analyst agent. Never a counterpart's summary.
- **Split only across boundaries.** A single-area, single-layer request gets no breakdown — say so
  and point to `/ela:task`. Inside an area with a team stack, the *mechanism* split (which service,
  which file) belongs to that stack; pre-splitting it here only creates drift.
- **Decisions above, mechanisms below.** A/V semantics and product calls are Evan's: relay the
  question, record the answer signed and dated (`— Evan YYYY-MM-DD`). Never decide for him, never
  leave one implicit in a lane.
- **The plan is the deliverable; Jira is a publication.** This skill writes only
  `ela-knowledge/breakdowns/<KEY>/plan.md`. It never touches a product repo, and creates Jira
  subtasks only through §5's gate.
- **Owners are read, not remembered.** Token → owner from the roster file at run time; repo → owner
  from the map. A missing owner is `unknown`, never a guess.
- **Closed vocabulary.** Every proposed subtask title is `[Infra] [J2N] [Media] [App] [UI] [QA]
  [Design]` + action — one token each, no dash separator, cross-layer scope stays on the parent.
  (The jira capability enforces this again at create time; matching it here avoids a bounce.)

## 0 — gather
Read `~/.claude/ela/site.json` (`env`, `map`, `records`, `map_sources.team_roster`). Then:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py"  --env-file <env> read <KEY> --deep   # per key
python3 "${CLAUDE_PLUGIN_ROOT}/skills/slack/slackread.py" --env-file <env> <permalink>    # per link
```

Read the roster file (`team_roster`) for token → owner/email, and `<map>/host.yaml` for areas,
governance, repo owners. When a thread and a ticket disagree, say so — the thread is live context,
the ticket is the record.

## 1 — split test
Proceed only if the requirement crosses layers/areas, **or** contains a decision only Evan can
make. Otherwise stop: "single lane (`[X]`, area `Y`) — no breakdown needed; `/ela:task <KEY>
<repo>` when you implement it yourself."

## 2 — depth
Record the depth in the plan header.

| depth | reads | when |
|---|---|---|
| **knowledge** (default) | tickets, threads, the map, KB/architecture docs the map sources name | first cut, routing, sizing |
| **code** | the above **plus** the relevant services' source — one read-only `analyst` agent per repo, given the repo path from the map and the specific questions (call sites, contracts, tests) | lanes touch inter-service seams; "which service" is not obvious |

A knowledge-depth plan must name the lanes it could not confirm without code. A code-depth plan
cites the files read (the analyst returns them; keep the list in the plan directory).

## 3 — decide and cut lanes
1. Surface every open decision to Evan first; a lane built on an unmade decision is fiction.
2. Cut lanes by layer/owner. Per lane: token, owner, scope (what it must and must not do),
   dependencies, verification.
3. Write the **interfaces between lanes** explicitly — the field, endpoint, or ordering two lanes
   share. This is the part no single team's stack can see; it is why ela exists.
4. Sequence from the dependencies actually found (typical chain: Design → UI; App → UI;
   Infra/Media → dependents; QA gates deploy) — derive it, don't assume it.

## 4 — the plan lands

`<records>/breakdowns/<KEY>/plan.md`, committed to ela-knowledge:

```markdown
---
key: MH-XXXX            # or a slug when no ticket exists yet
depth: knowledge | code
date: YYYY-MM-DD
sources: [MH-XXXX, <permalink>, "Evan's framing"]
---
# <one-line requirement>

## Decisions (closed)
- <decision> — Evan YYYY-MM-DD

## Lanes
| # | title (token first) | owner | scope | depends on | verify |

## Interfaces between lanes
## Open questions   (blocking / non-blocking, and for whom)
## Not doing        (explicitly out of scope)
```

The exemplar is MH-3513: background, a signed placement decision, constraints, single-token
subtasks. Reasoning stays in the plan; tickets get conclusions.

## 5 — publish to Jira (only when Evan says "create them")
No ticket yet (the plan's `key` is a slug)? Create the parent first — same gate:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py" --env-file <env> create \
        --summary '<requirement>' --description '<summary + decisions + link to plan>'
```

Then for each lane, run the create **without `--apply`** and show the batch:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py" --env-file <env> create-subtask \
        --parent <KEY> --summary '<title>' --assignee <owner email> --description '<scope + verify>'
```

Assign **directly to the lane owner** (the plan already names them) unless Evan says otherwise.
Only after Evan confirms the shown batch, repeat with `--apply`; the capability's own gates
(token check, duplicate idempotency) run regardless. Record created keys back into the plan.
