# ela — authoring rules

This file loads when a session starts in this repository, that is, when editing ela. In use, ela is a
plugin: skills, agents and hooks travel with it, this file does not. Every skill is therefore
self-contained and assumes nothing else is in context. The architecture is `docs/architecture.md`;
the decisions about how ela is built are `docs/adr/`; the scenarios are `docs/capabilities.md`.

## What ela is

ela is the set of capabilities a person uses to carry product responsibility across teams they do not
manage and code they do not own: read first-hand, break work down by layer, route it to owners, track
it, and — when they implement something themselves — do so under the target repository's rules.
Capabilities first; a persona only where a tool restriction or isolation demands one.

Scope follows responsibility, not product. The gate is the map: ela works in an area once that area
is in `<elak>/map/` with a governance shape. Presence is not enrollment: ela is injected into every
session on the machine, but only the roots named in `site.json` are governed. A session outside a
surveyed checkout says so, and that is correct behaviour.

**ela holds no product code and no knowledge.** Definitions live here; what ela knows lives in elak.
A change because the world changed goes to elak; a change because ela's behaviour should change goes
here.

## Two capabilities ela never gives away

1. **Independent cognition.** Read and analyse first-hand — Jira, Slack, the wiki, code, disk. What
   cannot be read is named as a gap, never filled with a counterpart's summary. A report is input;
   evidence is fact.
2. **Delegated execution.** Writing code goes to whoever owns the rules for that repository. Where
   nobody does, ela works under the repository's own conventions.

Never delegated, because they cross every counterpart's boundary: isolation, write permission,
cross-repository contracts, release order, the evidence standard. Consulted, never binding: the
company's module-first standards.

## The operating rule

Rules are bound to a location; ela is bound to the person. Start each session where the rules live.

| where the target's rules live | governance | session starts in | who implements |
|---|---|---|---|
| a sibling resource repository (the web team's stack for its app) | team-stack | that resource repository, the task worktree added | their stack, their workflow |
| the repository itself (`CLAUDE.md`, `.claude/`, `AGENTS.md`) | repo-local | the task worktree | ela, under those files |
| nowhere | bare | the task worktree | ela, defaults |
| declared read-only by the owner | read-only | anywhere | nobody |

A worktree carries `CLAUDE.md` and `.claude/` with it; a sibling repository's agents and hooks do not.
Hence the session switch for team-stack lanes, and hence ela as a plugin: present on both sides.

## Layers

| layer | form | holds |
|---|---|---|
| L0 site | `~/.claude/ela/` | machine paths, credentials, the working preferences |
| L1 atomic | `skills/<name>/<name>.py`, subcommands, `--json`, exit codes, stdlib only | deterministic work: read, search, dry-run writes |
| L2 composite | a `SKILL.md` a session follows | judgment over L1; never a raw API call |
| L3 adapter | `bin/ela` (one word, flat verbs, an id by shape) · a `SKILL.md` · an MCP server when the first external consumer exists · a caller's subprocess | translation only, no business logic |

- Safety gates live in L1: closed vocabularies, idempotency, dry run by default, `--apply` explicit.
- Confirm gates live in the adapter: a `SKILL.md` asks; a page shows a button; a bot asks in the thread.
- Callers depend on ela; ela depends on first-hand sources only.
- A `SKILL.md` is documentation for a session, never the capability. A capability does not need a
  skill; a skill exists only where judgment or invariants are needed to use it well.
- Where a capability helps the owner, ela builds it even if Helm has one; Helm's copy then carries a
  retirement condition (ADR 0005).

## What ela does not do

- Implement in a team-stack repository itself. It prepares (worktree, tier, context) and delegates to
  a headless session in the counterpart's repository, then verifies the artefacts.
- Edit a counterpart's repository. Helm is not a counterpart: it is the owner's own application and
  is edited under its own files; judgment work is never implemented inside it.
- Copy knowledge in. Paths and URLs only.
- Orchestrate in prose. The platform sequences agents; ela states invariants.
- Run a server or a web UI. `bin/ela` forwards one verb to one script and exits.
- Write to a live system — Jira, Slack, the wiki, the product's admin, a running process — without an
  explicit confirm. In a session the confirm is the owner's word before `--apply`; at the shell,
  typing the action verb is the confirm.
- Push to a shared lane (`master`, `main`, `develop`, `release*`) of any repository that is not the
  owner's.
- Commit to elak from a hook. Knowledge is written on the owner's word and committed by hand (ADR 0001).
- Depend on a legacy location. Credentials and paths are copied once into the site directory.
- Build ahead of its phase (`ROADMAP.md`).

## Where things live

| what | where | notes |
|---|---|---|
| definitions | `<projects>/ela`, installed as plugin `ela@ela` from a directory marketplace | the install is a cached copy; bump `plugin.json` and `/plugin update ela` when the owner reinstalls, not per commit |
| knowledge | `<elak>` = `<projects>/elak` (git, private) | `blueprint/` principles, decisions, status table, exit evidence · `knowledge/` readings · `map/` generated facts |
| the shared subset | `<published>` = `<projects>/elak-published` | the output of `ela publish`; regenerated, never edited; addresses redacted |
| site | `~/.claude/ela/` — `site.json`, `.env` (mode 600), caches, `working-with-evan.md` | never committed. Tracked files write roots by name — `<projects>`, `<code>`, `<work>`, `<elak>`, `<published>`, `<runtime>` — never a machine path or a host address |
| code | `<code>/<alias>/<remote path>` | never edited in place; `map.py` clones, syncs, surveys |
| runtime | `<runtime>` = `<projects>/.ela` — `work/`, raw pulls, drafts | deletable by contract; `ela runtime status|clean` |
| work | `<work>/<KEY>/<repo>` worktrees | where code changes happen; removed at close |
| reports | `<projects>/reports` | the owner's private reading surface; not versioned |

Reads of the map and the roster go through `<published>` on every machine (site.json `map`); the
private map is the publish source (`map_source`). Whatever a verb needs at runtime is thereby forced
through the publish gate.

## Hard rules

1. Disk is the fact; the survey is a cache. Knowledge holds only what disk cannot tell. No tracked
   file names a git host by address.
2. Cite, never copy.
3. Evidence outranks report, judged by the target repository's standard.
4. One task, one worktree, one session; pathspec commits only.
5. One phase at a time.
6. One concern per commit. The subject says what changed, the body why the code needed it, with a
   ticket key or an ADR filename for the reason. A direction change is a new ADR that supersedes the
   old one, never an edit. `hooks/content-guard.sh` refuses a commit that carries a credential, an
   address, a person's quoted words or session narrative.
7. Input is not output. A message from the owner, a Slack thread or a relayed thought is input; it
   becomes a rule, a document or a commit message only rewritten in the destination's genre with the
   origin cited, and — for anything read by others — in a later pass than the conversation that
   produced it (ADR 0002).
8. People appear as roles. A tracked file names a role and the area it owns; individual performance
   and private circumstances are not engineering material. Attribution of a design choice to a dated
   ADR is authority, not deliberation.

## Gate — one-way asks

Reversible, cheap asks are simply done. Anything one-way — deleting, publishing where others see it,
changing this charter, adding or merging repositories, renaming, adding a capability — passes four
one-line checks first: the problem and its evidence; the strongest alternative, including doing
nothing; the recorded decision it conflicts with; the verdict, always showing the option ela would
reject. The owner decides; if they reaffirm after an objection, proceed and record the dissent in the
ADR. Reopening a recorded decision needs new evidence. Each phase opens with a one-paragraph
premortem.

## Verification

`tests/run.sh`: every script compiles, every capability answers `--help`, every hook parses, the
content guard's cases pass. Run it before a commit that touches a script or a hook.

## Language and naming

English throughout. `ela` is a name, not an acronym, written lowercase and never expanded in text;
the Slack display name is **Ella**. Describe the owner's responsibility, never a title.
