# ROADMAP — one phase at a time, ordered by dependency

Each phase states what it delivers, what it deliberately does not, and the exit that unlocks the
next. Nothing is built ahead of its phase.

## 0 — charter · done
Manifests, `CLAUDE.md` (boundaries first), this file.

## 1 — senses + map · current
- **Senses**: `/ela:jira` · `/ela:slack` · `/ela:kb` · `/ela:object`. First-hand, read-only
  (`kb` writes on confirm). Credentials from `~/.claude/ela/.env`, copied once from their previous
  homes; no runtime dependency on Helm or the old `~/.claude/skills`.
- **Map**: `/ela:map` → `ela-knowledge/map/host.yaml` (repos on this machine, with governance shape
  and owner) and `absent.yaml` (known to exist, not here — with owner and location).

**Not built:** agents, writes to product repos, orchestration.
**Exit:** `/ela:map` runs twice in a row with an empty drift table; every repo has a governance value.

## 2 — task · next
`/ela:task <KEY> <repo>`: for work Evan implements himself. Read the ticket first-hand → locate the
repo in the map → per-task worktree from `origin/<lane>` under `~/ela-runtime/<task>/<repo>` → write
tier → **delegate by governance**: team-stack → a headless session started in the counterpart's repo
(`claude -p --agent <their router> --add-dir <worktree>`) so their agents, hooks and workflow run,
with ela relaying any confirmation they need and resuming the session; repo-local / bare → ela
implements in the worktree under the repo's own files. Then verify artefacts and evidence by the
target's standard (their change dir, their test line, no push), and write the ledger entry.

**Exit:** MH-2191-class work end to end with the counterpart's artefacts present and no manual
session switch.

## 3 — breakdown
`/ela:breakdown`: Jira/Slack input + Evan's own framing → a plan of layer-tagged lanes
(`[Infra] [J2N] [Media] [App] [UI] [QA] [Design]`) each with owner (from the map + team roster),
dependency order, and verification. The plan lands in `ela-knowledge/breakdowns/<key>/plan.md`.

Two depths, chosen per request and recorded in the plan header:

| depth | reads | good for | cost |
|---|---|---|---|
| **knowledge** | ticket, thread, KB/architecture docs, the map | first cut within minutes; routing and sizing | no repo access |
| **code** | the above **plus the relevant services' source** in the checkouts named by the map — call sites, contracts, tests | lanes that touch inter-service seams, anything where "which service" is not obvious | first agent: a tool-restricted, read-only analyst per repo |

A knowledge-depth plan states which lanes it could not confirm without code; a code-depth plan cites
the files it read. Neither depth writes to any repo or to Jira.
**Publishing to Jira is Phase 5** — until then Evan creates the tickets from the plan.

**Exit:** one real requirement's plan matches what Evan would have written by hand.

## 4 — brief
`/ela:brief`: Evan's queue from Jira directly — unrouted, blocked, stale In-Progress — against the
two cadence KPIs (complex tickets broken down same day; In-Progress updated within 24h). Read-only.

**Exit:** a week in which the brief is the first thing read and nothing it missed came up later.

## 5 — actions
Writes to live systems, each behind an explicit confirm and idempotent: create/assign Jira
subtasks **directly to their owners** from a breakdown plan; Slack drafts; Outline writes; MediaHub
admin (`mha`); graph build. `hooks/` gains the portable guards (`Bash(git push:*)` deny).

**Exit:** a breakdown plan lands in Jira in one confirmed step with no manual re-routing.

## Agents — admission rule
No agent exists until a skill needs work that is **isolated**, **parallel**, or **tool-restricted**.
A persona is not a reason; coordination is the main session. Expected: a read-only *analyst*
(Phase 3, `Read Grep Glob Bash` + code-graph tools), a read-only *reviewer* and per-stack
*implementers* for repo-local / bare lanes (Phase 2–5). Plain names. **Every `.md` under `agents/`
is loaded as an agent** — no README there.

## Deliberately never
Web UI · launcher script · orchestration prose · editing a counterpart's repo · copying others'
knowledge · pushing to a shared lane · designing around Helm's or mht's retirement.
