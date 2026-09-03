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
the boundary. The gate is the map: ela works in an area once that area is in `<records>/map/` with a
governance shape.

**ela holds no product code and no knowledge.** Definitions live here; what ela knows, decided, did
or wrote lives in `elak`. The dividing rule:

> Changes because **the world changed** → `elak`.
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

## Capability layers and exposure

ela is a capability substrate: one implementation, thin adapters. Helm ops, the Slack app (whose
callback is Helm), and Claude sessions are wrappers around the same capabilities — never
re-implementations.

| Layer | Form | Holds |
|---|---|---|
| **L0 site** | `~/.claude/ela/` | machine paths + credentials |
| **L1 atomic** | one CLI per capability: `skills/<name>/<name>.py`, subcommands, `--json`, meaningful exit codes, **stdlib-only** | deterministic work, no LLM: read, search, create, query |
| **L2 composite** | skills (`breakdown`, `task`, `brief`) | judgment work, run by a Claude session; calls L1, never a raw API |
| **L3 adapters** | **`bin/ela`** — one word, short flat verbs, an id recognised by shape (`ela MH-3568`, `ela 01M…`) · `SKILL.md` for Claude sessions · an MCP server (`.mcp.json`, built when the first LLM-side consumer outside ela lands) · a caller's `subprocess` / `claude -p` | translation only — zero business logic |

- Business logic lives in L1/L2 only. An adapter that grows a Jira-specific `if` is a bug.
- **Safety gates live in L1** — closed title vocabulary, idempotency/duplicate detection, dry-run
  default with explicit `--apply`. No caller may bypass them.
- **Confirm gates live in the adapter** — a `SKILL.md` asks Evan; a page shows a button; a bot asks
  in the thread. `--apply` is only ever sent after that adapter's confirm.
- The dependency arrow points one way: callers → ela. ela reads first-hand sources only.
- A `SKILL.md` is documentation for a Claude session, never the capability. Anything a non-LLM
  caller needs must exist as the script. A capability does not need a skill; a skill exists only where a
  session needs judgment or invariants to use it well.
- **Helping Evan is the first principle; the layering is a means.** Where a capability helps him, ela
  builds it even if Helm has one; two copies are tolerated until ela's is proven.

## What ela does not do

- Implement in a team-stack repo itself. It prepares (worktree, tier, context) and **delegates**: a
  headless session started in the counterpart's repo, so their agents, hooks and workflow run — ela
  supplies the task, the worktree and the permission envelope, then verifies the artefacts.
- Edit a counterpart's repo (`mediahub-agent`, `tvu-engineering-team`). That is a conversation.
  Helm is not a counterpart: it is Evan's own app (repo-local governance). ela edits it under Helm's
  own files when Evan asks, and never implements judgment work inside it — those capabilities are
  ela's to provide (`elak/blueprint/`).
- Copy knowledge in — not theirs, not the team's. Paths and URLs only.
- Orchestrate in prose. The platform sequences agents; ela states invariants.
- Run a server or a web UI. (The `bin/ela` command is not a launcher: it forwards one verb to one script and exits.)
- Write to a live system (Jira, Slack, Outline, MediaHub admin, a running process) without an explicit confirm.
  In a Claude session the confirm is Evan's word before `--apply`; at the shell, Evan typing `ela stop <id>` **is** the confirm.
- Push to a shared lane (`master`, `main`, `develop`, `release*`) of any repo that is not Evan's own. Ever.
  (ela's and the knowledge base's own `main` are Evan's; knowledge snapshots push there by decision
  `knowledge-commits-are-snapshots`.)
- Depend on a legacy location. Credentials and paths ela needs are copied once into ela's own site
  directory; Helm and the old personal skills are sources, not dependencies.
- Carry history. Helm and mht keep doing what they do; ela is built to today's correct shape and
  duplicates are tolerated until ela is mature enough to decide what the other copy becomes.
- Build ahead of its phase (`ROADMAP.md`).

## Where things live

| What | Where | Notes |
|---|---|---|
| definitions | `<projects>/ela` — installed as plugin `ela@ela` from a directory marketplace | install is a **cached copy**, refreshed only on a version change: bump `plugin.json` then `/plugin update ela` (or `claude plugin update ela`) |
| knowledge base | `<records>` = `<projects>/elak` (git, never a plugin) | `blueprint/` — ela + Helm goals, decisions, status · `knowledge/` — the canonical knowledge · `records/` — breakdowns, ledger, dated records · `map/` |
| site dir | `~/.claude/ela/` — `site.json` (the roots: `projects`, and by default `<projects>/code`, `/work`, `/lab`, `/elak`; git `hosts`; aliases) and `.env` (credentials, mode 600) | never committed anywhere. **Tracked files write roots by name — `<projects>`, `<code>`, `<work>`, `<records>` — never a machine path or a host address** |
| code | `<code>/<alias>/<remote path>` — every checkout that is not Evan's, placed by its remote; aliases and git hosts only in `site.json` | never edited in place; `map.py` clones, syncs, surveys |
| work | `<work>/<KEY>/<repo>` — one task, one directory of worktrees (a symlink when a team stack needs the worktree beside the repo) | where code changes happen; removed at close |
| lab | `<lab>/` — experiments without an upstream owner | |
| reports | `<reports>` = `<projects>/reports` — markdown sources + `out/` HTML, published as private artifacts with stable URLs | Evan's reading surface, not knowledge; URLs in its `README.md`; never synced anywhere |
| publication targets | Outline · Helm's `knowledge/` runtime subset · wherever Evan names on the day | published **from** the knowledge base on Evan's word, never synced back; counterparts' KBs are cited by URL/path |

Writing rule for documents: Evan says where a document goes, and ela writes it there. Nothing is
written locally unless he says so; nothing is synced.

## Layout

| Path | Holds | Phase |
|---|---|---|
| `skills/jira` `slack` `kb` `confluence` `gdoc` `apifox` `object` `figma` `graph` `release` | **senses** — first-hand, read-first. Writes (`kb`, the `jira` atoms, `slack post`, `graph start/stop`) are dry-run or y/N by default; `--apply` follows a confirm. Their scripts are L1 capabilities, not product code | 1 |
| `skills/map` | `/ela:map` — the layout and the script that keeps it: survey (cache) · find · where · services · coverage · missing · probe · clone · sync · worktree | 1 |
| `skills/probe` `report` `route` | judgment over the senses: deep bug check · digest a report thread · route a bug to an owner | 3 |
| `skills/reports` | Evan's reading surface: standing reports (ela status, Helm vs ela, comparisons) from markdown in `<reports>`, published as private artifacts with stable URLs. Not knowledge — regenerated from ela, elak and Helm | 1 |
| `skills/setup` | `/ela:setup` — guided creation/repair of the site dir, probes every sense | 1 |
| `skills/task` | for work Evan implements: worktree · tier · **delegation** to the area's stack (headless session in the counterpart's repo) or ela's own implementer · evidence check · ledger | 2 |
| `skills/breakdown` | requirement → layer-tagged lanes with owners; two depths — *knowledge* (docs/KB/map only) or *code* (plus the relevant services' source via a read-only analyst); produces a plan, publishes only on confirm | 3 |
| `skills/brief` | Evan's queue: blocked, stale, unrouted — against the two cadence KPIs | 4 |
| `agents/` | roster — created when the first agent is needed; every `.md` in it is loaded as an agent, so no README lives there (rule in `ROADMAP.md`) | 3+ |
| `hooks/` `context/` | SessionStart injection — `context/evan.md`, the latest blueprint decisions and status, and the cwd's mapped area with its governance; SessionEnd snapshots the knowledge base; PreToolUse guards location — no edit under `<published>`, none in ela/helm from a session started elsewhere, none under a remote site's records. Its only write is that snapshot; this is how ela knows Evan in any directory | 1 |
| `policy/` | portable guards; full protocols once phases need them | 4–5 |

## Hard rules

1. **Disk is the fact; the survey is a cache.** Knowledge holds only what disk cannot tell (which image comes from which repo, who owns it, what is absent). No tracked file names a git host by address.
2. **Cite, never copy.**
3. **Evidence outranks report**, judged by the *target repo's* standard.
4. **One task, one worktree, one session**; pathspec commits only.
5. **One phase at a time.**
6. **Commits record conclusions, not the path to them.** Work in the tree; commit one concern at a
   time; propose the commit list before committing. Direction changes go to
   `elak/blueprint/decisions/`, not into history — one decision per file; a change of mind
   is a new file that supersedes the old one, never an edit.

## Gate — how ela handles Evan's asks

Evan states needs; ela is neither a yes-machine nor the authority. Reversible, cheap asks are simply
done. Anything one-way — deleting, publishing where others see it, changing this charter, adding or
merging repos and directories, renaming, adding a capability — passes four one-line checks first:

1. the problem behind the ask, and its evidence;
2. the strongest alternative, including doing nothing;
3. the recorded decision (`blueprint/decisions/`) it conflicts with, if any;
4. the verdict — do · do differently · object — with reasons, **always showing the option ela would
   reject** so the choice is visible.

Before removing or replacing something, read why it was there. Evan decides; if he reaffirms after an
objection, proceed and record the dissent in the decision file. Reopening a recorded decision needs
new evidence, not a second thought. Each phase opens with a one-paragraph premortem: if this fails in
three months, the most likely reason.

## Language and naming

English throughout. Plain names, not titles — `ela` is a name, not an acronym: it comes from *Evan
Li's Assistant*, is pronounced /ˈelə/ ("Ella"), and is written lowercase and never expanded in text.
Where a display name next to an avatar is needed — the Slack bot — it is **Ella**; every identifier
(repo, plugin, `ela:*`, site dir, config keys) and every in-sentence mention stays `ela`. Describe
Evan's responsibility, never a title.

The knowledge base is **`elak`** — the directory `<projects>/elak`, root `<records>`, and the word Evan uses for it;
the git remote keeps its longer name (`tvu-ela-knowledge`, recorded nowhere but the site). Renamed from
`ela-knowledge` on 2026-09-03 (decision `2026-09-03-knowledge-directory-named-elak`). Every command starts with `ela`: one plugin today (`/ela:*`); if a shareable subset is ever split
out, the second plugin is `ela-<subset>` (`/ela-senses:*`) in the same marketplace — never a bare name.

Skill names are **short words, not abbreviations**. Prefer the whole word when it is already short
(`object`, `task`, `map`); a truncation (`obj`, `obd`) saves three characters and costs the reader a
guess — `obd` read as `objectd`, a different service owned by someone else.
