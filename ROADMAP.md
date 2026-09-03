# ROADMAP — one phase at a time, ordered by dependency

Each phase states what it delivers, what it deliberately does not, and the exit that unlocks the
next. Nothing is built ahead of its phase.

## 0 — charter · done
Manifests, `CLAUDE.md` (boundaries first), this file.

## 1 — senses + map · current
- **Senses**: `/ela:jira` · `/ela:slack` · `/ela:kb` · `/ela:object` · `/ela:figma` · `/ela:graph` (added
  2026-09-02: what `ura` did by hand — J2N graphs and Pilot processes, probing environments in order
  `prod3 → prod2 → test2` and reporting the env the data names; `connect · exec · start · stop` for the
  shell, y/N-gated) · `/ela:release` (GM bundles, versions per env, Jenkins builds, drift) · `/ela:confluence` and `/ela:gdoc`
  (added 2026-09-03: the web team's wiki and Google Docs/Sheets, read-only) · `slack post` (2026-09-03: the one
  Slack write, dry run until `--apply`). First-hand,
  read-first (`kb` and the `jira` write atoms are dry-run by default and write only with `--apply`, on confirm). Credentials from `~/.claude/ela/.env`, copied
  once from their previous homes; no runtime dependency on Helm or the old `~/.claude/skills`.
- **L1 shape** (see `CLAUDE.md` — capability layers): each sense grows into a subcommand CLI with
  `--json` as callers need it — `jira.py` first. Write *atoms* may exist as CLI early (dry-run
  default, safety gates in the script); what stays phased is their **composite/automated use**
  (Phase 5).
- **Map**: `/ela:map` → `elak/map/services.yaml` (image → slugs · GM names · owners → repos) and
  `absent.yaml` (known to exist, not here); what is on disk is a cache (`map.py survey`), never knowledge;
  `map.py remote` (2026-09-03) lists a whole GitLab group through its API, so "absent" means searched, not guessed.
  Layout (2026-09-02): `code/<alias>/<remote path>` for everything that is not Evan's, `work/<KEY>/<repo>`
  for changes, `lab/` for experiments; aliases and hosts only in `site.json`.

- **Session context** (added 2026-09-02): `hooks/session-start.sh` injects `context/evan.md`, the
  latest `blueprint/` decisions and status, and the cwd's mapped area. No global agent — the plan
  (`elak/blueprint/`) records why.

**Not built:** agents, writes to product repos, orchestration.
**Exit:** `/ela:map` runs twice in a row with an empty drift table; every repo has a governance value.

## 2 — task · next
`/ela:task <KEY> <repo>`: for work Evan implements himself. Read the ticket first-hand → locate the
repo in the map → per-task worktree from `origin/<lane>` under `<work>/<KEY>/<repo>` → write
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
dependency order, and verification. The plan lands in `<records>/records/breakdowns/<KEY>/plan.md`.

Two depths, chosen per request and recorded in the plan header:

| depth | reads | good for | cost |
|---|---|---|---|
| **knowledge** | ticket, thread, KB/architecture docs, the map | first cut within minutes; routing and sizing | no repo access |
| **code** | the above **plus the relevant services' source** in the checkouts named by the map — call sites, contracts, tests | lanes that touch inter-service seams, anything where "which service" is not obvious | first agent: a tool-restricted, read-only analyst per repo |

A knowledge-depth plan states which lanes it could not confirm without code; a code-depth plan cites
the files it read. Neither depth writes to any repo. Jira publication happens only on Evan's
explicit "create them", per-batch confirmed, through the jira capability's own gates — assigned
**directly to the lane owners**. What remains Phase 5 is the streamlined one-step form.

**Exit:** one real requirement's plan matches what Evan would have written by hand.

## 4 — brief · built 2026-09-02
`/ela:brief`: Evan's queue from Jira and Slack directly — stale In-Progress (actionable vs zombies),
Blocked, unrouted new tickets past the 4h window, complex tickets with no sub-tasks; plus what only
Slack shows: report threads since yesterday, threads waiting on his reply, threads he wrote alone,
decisions made in Slack with no ticket. Ranked, capped at 12, one drafted action each. Read-only.
The slack capability grew into a subcommand CLI for it (`read · channels · history · mentions ·
unanswered · whoami`). Definitions are stated in the skill so they can be argued with.

**Exit:** two weeks in which the brief is the first thing read and nothing it missed came up later.

## 3b — probe · built 2026-09-02
`/ela:probe`: the deep check — ticket or symptom → runtime facts (`graph.py`) → implicated service by
image (`map/services.yaml`) → code, cloned from the LAN GitLab if missing (`map.py clone`) → the
read-only analyst reads with specific questions → root cause with file:line → drafted comments, each
behind its own confirm. Modelled on the MH-3568 investigation (copier `addScteStream`).

**Exit:** three investigations whose root cause held when the owner read the code.

## 5 — actions
Writes to live systems, each behind an explicit confirm and idempotent: create/assign Jira
subtasks **directly to their owners** from a breakdown plan; Slack drafts; Outline writes; MediaHub
admin (`mha`); graph build. `hooks/` gains the portable guards (`Bash(git push:*)` deny).
When the first LLM-side consumer outside ela lands (Helm chat, the Slack app's headless sessions),
wrap the L1 CLIs in one MCP server declared in the plugin's `.mcp.json` — tools map 1:1 to
subcommands, no second implementation.
The headless entry for judgment capabilities (`bin/ela run <capability> … --json`, a JSON envelope
around `claude -p` with ela's own permission envelope) lands here too, with its first non-LLM caller.

**Exit:** a breakdown plan lands in Jira in one confirmed step with no manual re-routing.

## Agents — admission rule
No agent exists until a skill needs work that is **isolated**, **parallel**, or **tool-restricted**.
A persona is not a reason; coordination is the main session. Exists: *analyst* (read-only,
`Read Grep Glob Bash`, admitted for `/ela:breakdown` code depth — tool-restricted). Expected: a
read-only *reviewer* and per-stack *implementers* for repo-local / bare lanes (Phase 2–5). Plain
names. **Every `.md` under `agents/` is loaded as an agent** — no README there.

## Deliberately never
Web UI · launcher script · orchestration prose · editing a counterpart's repo · copying others'
knowledge · pushing to a shared lane · designing around Helm's or mht's retirement.
