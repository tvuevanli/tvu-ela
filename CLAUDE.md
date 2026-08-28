# ela — authoring rules

This file loads only when a session starts in this repo — that is, when **editing ela**. In use,
ela is a plugin, and plugins carry skills, agents and hooks, not this file. Every skill must
therefore be **self-contained**: it states its own invariants and assumes nothing else is in context.

## What ela is

ela is the set of capabilities Evan uses to carry MediaHub product responsibility across teams he
does not manage and code he does not own: read first-hand, break work down by layer, route it to
owners, track it, and — when Evan implements something himself — do so under the target repo's
rules. **Capabilities first; personas only where a tool restriction or isolation demands one.**

Scope follows **responsibility, not product**. MediaHub is the origin and centre of gravity, never
the boundary. The gate is the map: ela works in an area once that area is in `host.yaml` with a
governance shape.

**ela holds no product code and no knowledge.** Definitions live here; what ela knows, decided, did
or wrote lives in `ela-knowledge`. The dividing rule:

> Changes because **the world changed** → `ela-knowledge`.
> Changes because **ela's behaviour should change** → `ela`.

## Two capabilities ela never gives away

1. **Independent cognition.** Read and analyse first-hand — Jira, Slack, Outline, code, disk. What
   cannot be read is named as a gap, never filled with a counterpart's summary. A report is an
   input; evidence is a fact.
2. **Delegated execution.** Writing code goes to whoever owns the rules for that repo. Where nobody
   does, ela works under the repo's own conventions.

**Never delegated** — they cross every counterpart's boundary, so no counterpart can hold them:
isolation, write permission, cross-repo contracts, release order, the evidence ledger.

**Consulted, never binding:** `tvu-standards` / `tvu-catalog` module-first checks.

## The operating rule

> **Rules are bound to a location. ela is bound to the person.
> Start each session where the rules live — ela is already there.**

| Where the target's rules live | Governance | Session starts in | Who implements |
|---|---|---|---|
| a sibling resource repo (`mediahub-agent` for `mh-app`) | **team-stack** | that resource repo; `/add-dir` the task worktree | their stack, their workflow |
| the repo itself (`CLAUDE.md`, `.claude/`, `AGENTS.md`) | **repo-local** | the task worktree — rules travel with the checkout | ela, federating those files |
| nowhere | **bare** | the task worktree | ela, defaults |
| Evan says read-only | **read-only** | anywhere | nobody |

A worktree carries `CLAUDE.md` and `.claude/` with it; a sibling repo's agents, skills and hooks do
not — Claude Code loads them only for the session's project directory. Hence the session switch for
team-stack lanes, and hence ela as a plugin: the only thing present on both sides.

## What ela does not do

- Implement in a team-stack repo itself. It prepares (worktree, tier, context) and **delegates**: a
  headless session started in the counterpart's repo, so their agents, hooks and workflow run — ela
  supplies the task, the worktree and the permission envelope, then verifies the artefacts.
- Edit a counterpart's repo (`helm`, `mediahub-agent`, `tvu-engineering-team`). That is a conversation.
- Copy knowledge in — not theirs, not the team's. Paths and URLs only.
- Orchestrate in prose. The platform sequences agents; ela states invariants.
- Run a server, a launcher script, or a web UI.
- Write to a live system (Jira, Slack, Outline, MediaHub admin) without an explicit confirm.
- Push to a shared lane (`master`, `main`, `develop`, `release*`). Ever.
- Depend on a legacy location. Credentials and paths ela needs are copied once into ela's own site
  directory; Helm and the old personal skills are sources, not dependencies.
- Carry history. Helm and mht keep doing what they do; ela is built to today's correct shape and
  duplicates are tolerated until ela is mature enough to decide what the other copy becomes.
- Build ahead of its phase (`ROADMAP.md`).

## Where things live

| What | Where | Notes |
|---|---|---|
| definitions | `~/projects/ela` — installed as plugin `ela@ela` from a directory marketplace | install is a **cached copy**; after editing run `/plugin update ela` |
| records | `~/projects/ela-knowledge` (git, never a plugin) | map · decisions · breakdowns · ledger · docs |
| site dir | `~/.claude/ela/` — `site.json` (machine paths) and `.env` (credentials, mode 600) | never committed anywhere |
| shared knowledge | Outline, `helm/knowledge`, counterparts' KBs | cited by URL/path |

Writing rule for documents: Evan says where a document goes, and ela writes it there. Nothing is
written locally unless he says so; nothing is synced.

## Layout

| Path | Holds | Phase |
|---|---|---|
| `skills/jira` `slack` `kb` `object` | **senses** — first-hand, read-only (`kb` also writes, confirm-gated). Their scripts are sense implementations, not product code | 1 |
| `skills/map` | `/ela:map` — build and re-verify the map against disk | 1 |
| `skills/setup` | `/ela:setup` — guided creation/repair of the site dir, probes every sense | 1 |
| `skills/task` | for work Evan implements: worktree · tier · **delegation** to the area's stack (headless session in the counterpart's repo) or ela's own implementer · evidence check · ledger | 2 |
| `skills/breakdown` | requirement → layer-tagged lanes with owners; two depths — *knowledge* (docs/KB/map only) or *code* (plus the relevant services' source via a read-only analyst); produces a plan, publishes only on confirm | 3 |
| `skills/brief` | Evan's queue: blocked, stale, unrouted — against the two cadence KPIs | 4 |
| `agents/` | roster — created when the first agent is needed; every `.md` in it is loaded as an agent, so no README lives there (rule in `ROADMAP.md`) | 3+ |
| `hooks/` `policy/` | portable guards; full protocols once phases need them | 4–5 |

## Hard rules

1. **The map is a claim; disk is the fact.** Disagree → fix the map.
2. **Cite, never copy.**
3. **Evidence outranks report**, judged by the *target repo's* standard.
4. **One task, one worktree, one session**; pathspec commits only.
5. **One phase at a time.**
6. **Commits record conclusions, not the path to them.** Work in the tree; commit one concern at a
   time; propose the commit list before committing. Direction changes go to
   `ela-knowledge/decisions/`, not into history.

## Language and naming

English throughout. Plain names, not titles — `ela` is a name, not an acronym. Describe Evan's
responsibility, never a title.

Every command starts with `ela`: one plugin today (`/ela:*`); if a shareable subset is ever split
out, the second plugin is `ela-<subset>` (`/ela-senses:*`) in the same marketplace — never a bare name.
