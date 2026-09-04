# ROADMAP — one phase at a time, ordered by dependency

Each phase states what it delivers, what it deliberately does not, and the exit that unlocks the
next. Nothing is built ahead of its phase. The target design is the report *Evan's Work System*
(`<projects>/reports`); the decisions are in `elak/blueprint/decisions/`. This file says what exists
and what is next.

## 0 — charter · done
Manifests, `CLAUDE.md` (boundaries first), this file.

## 1 — senses + map · built, exit not met
- **Senses**: `/ela:jira` · `/ela:slack` (+ `post`, the one Slack write) · `/ela:kb` · `/ela:object` ·
  `/ela:figma` · `/ela:graph` (J2N/Pilot first-hand, probe `prod3 → prod2 → test2`, `connect · exec ·
  start · stop` for the shell) · `/ela:release` (QA GM host by account login, Jenkins builds, drift —
  **no prod session**: decision `ela-needs-no-sid`) · `/ela:confluence` · `/ela:gdoc`. Read-first;
  every write is a dry run until `--apply`. Credentials from `~/.claude/ela/.env`, copied once.
- **Map**: `/ela:map` → `elak/map/services.yaml` · `absent.yaml` · `release.yaml`; disk is a cache
  (`survey`); `remote` lists a whole GitLab group through its API, so "absent" means searched.
  Layout `code/<alias>/<remote path>`, `work/<KEY>/<repo>`, `lab/`.
- **Command**: `bin/ela` — one word, flat verbs, ids by shape. **Reports**: `/ela:reports`.
- **Session context**: `hooks/session-start.sh`; SessionEnd snapshots elak.

**Not built:** agents beyond the read-only analyst, writes to product repos, orchestration.
**Exit:** `/ela:map` runs twice with an empty drift table (open: two AMPP GM services); every repo
has a governance value (met, 85/85).

## Landing order — from the work-system design (2026-09-03)

| step | delivers | exit | status |
|---|---|---|---|
| **L0** | decisions recorded: four layers + guard; Helm under its own rules; second site; no SID in ela; nothing reaches others until proven | files exist | done 2026-09-03 |
| **L1** | *use it*: `/ela:brief` every morning; `/ela:breakdown` on one real requirement; Helm's `clients/ela.py` seam (branch `ela-integration`) with the UR reads as first entries | two weeks of misses written; one plan diffed against Evan's; the seam's tests green | seam done; use starts |
| **L2** | deterministic brief lanes as L1 (`brief.py`, no model) so a 30-minute clock costs nothing; then the headless entry `ela run <skill> --json` reusing Helm's `claude` runner | Helm's scheduler runs the lanes and the 08:30 brief, output equal to a session run | not started |
| **L3** | the second site on the remote: clone, public-only `.env`, published elak subset, version pin in Helm's deploy | the bot answers `route` for someone else — only after `nothing-reaches-others-until-proven` is lifted for route | not started |
| **L4** | sink Helm's judgments into ela one at a time (Daily Report, My Report, triage, evidence rules) — needs a `mail` sense first | one Helm prompt removed per week; readers notice nothing | started 2026-09-04: `mail` sense; the version system transcribed to elak `map/release.yaml`; `promote` assesses on ela with Helm as the parity oracle (decision 2026-09-04-promotion-assessment-is-elas-helm-is-the-oracle-until-parity); Helm untouched |
| **L5** | composites over the atoms: nudge, scope tracker, ticket-from-thread, decision capture, promotion post, long-thread digest | the third follow-up on a bug is never hand-written | promotion post: step 1 of the thread is produced by `promote` (2026-09-04); the rest not started |
| **L6** | MCP for the bot's tools; heuristics in elak; display name Ella | others use it without Evan in the loop | not started |

## 2 — task · written, delegation never exercised
`/ela:task <KEY> <repo>`: ticket first-hand → repo in the map → worktree under `<work>/<KEY>/<repo>` →
tier → delegation by governance (team-stack: headless session in the counterpart's repo; repo-local /
bare: ela under the repo's files; Helm: its own rules and agents) → evidence by the target's
standard → ledger. **Exit:** MH-2191-class work end to end with the counterpart's artefacts present.

## 3 — breakdown · written, never run for real
Knowledge depth (minutes, no repo access) or code depth (the read-only analyst reads the checkouts).
Plan in `<records>/records/breakdowns/<KEY>/plan.md`; Jira publication only on Evan's "create them",
assigned directly to owners. **Exit:** one real plan matching what Evan would have written.

## 3b — probe · built, 1 of 3
Ticket → graph facts → implicated image → code (cloned if missing) → analyst → root cause with
file:line → drafted comments behind their own confirms. **Exit:** three root causes that held.

## 4 — brief · built, not yet used daily
Lanes stated in the skill so they can be argued with; ranked, capped at 12, one drafted action each;
read-only. **Exit:** two weeks in which the brief is the first thing read and nothing it missed
came up later. This is the first thing to do (L1).

## 5 — composites and automation · not started
The write composites (L5), the scheduled clock (L2/L3), the sweep (S5 bookkeeping rules in elak).
Every write behind the L1 gate and the adapter's confirm; nothing reaches others until proven.
