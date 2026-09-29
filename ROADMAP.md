# Roadmap

What exists, what each phase must prove before the next starts, and what is deliberately not built.
The architecture is `docs/architecture.md`; the scenarios are `docs/capabilities.md`.

| phase | delivers | exit test | state |
|---|---|---|---|
| 0 charter | this repository's rules, the layers, the guards | — | done |
| 1 senses and map | first-hand reads of Jira, Slack, Outline, Confluence, Google Docs, Apifox, Figma, Object Service, UR, release lanes, mail, Sentry, the stream on the wire; the code map; the `ela` command; publication to the shared directory | `ela publish list` clean; every repository in the map has a governance value | done |
| 2 task | one piece of the owner's own work end to end: worktree, tier, delegation to the area's stack, evidence in the merge request | one merge request in the owner's hands, opened from `ela mr` after the counterpart's artefacts are present | written; `ela mr` preflight + dry run built 2026-09-29, first preflight found both GitLab tokens refused (site configuration) |
| 3 judgment | breakdown, probe (and `probe how`, a mechanism explained), route, feasible, arch over the senses; explain, one ticket made judgeable; the existence verdict on an old ticket (revisit) | one plan matching what the owner would have written; three root causes that held | built; one root cause held |
| 4 brief and digest | the morning queue and report digests, drafts only | two weeks in which the brief is read first and nothing it missed surfaced later | built; `brief.py` landed 2026-09-29; the two-week window starts on the owner's word, not before that date |
| 5 diagnostics | `ela logs`, `ela inspect`, UR diagnostic reads; the boundary agent through its API | the three cases in the 2026-09-07 review answered without a person at a terminal | open; `ela logs` (tvulog process-log and java-log, Loki through Observer) and `/ela:route`'s log steps built 2026-09-29; exit test unchanged; `inspect`, UR diagnostics and the boundary agent not started |
| 6 composites | nudge, sweep, ticket-from-thread, decision capture behind the write gate; the headless entry `ela run` | the third follow-up on a bug is never hand-written | not started |
| 7 exposure | an MCP server for the bot and external models; Helm's duplicated skills retired on parity | others use it without the owner in the loop | not started |

Phase 5 was opened on 2026-09-29 for one ability: localise a failure to the service that produced it,
name its owner and list the likely causes, so the case can be handed to that owner; a root cause at
file:line is a bonus. The log reads are an L1 sense and `/ela:route` gains the steps that use them.
- Problem and evidence: a prod-3 startLive failure (error 82400103) took an interactive session about an
  hour and two facts copied in by hand, because tvulog could not be read; with the log reads the same
  case resolves in a handful of calls, and the service that threw it is visible in its own java-log
  although the trace id never reached it.
- Strongest alternative: a separate `/ela:debug` skill — rejected, it would duplicate route and probe
  and split their rules. Doing nothing leaves the case above at an hour per failure.
- Conflict with a recorded decision: none; this row already listed `ela logs`.
- Rejected option: any write to another team's runtime — log levels, restarts, config refreshes.

A row whose phase is open and that records no run for two weeks is marked `built, unreached` in elak's status
table and enters the next cut list: a verb carries a price, per elak `blueprint/status.md`.

## Helm's retirement schedule

Each Helm skill that duplicates an ela skill is removed when ela's passes the same input with no
unexplained difference (ADR 0005). Pairs: daily-brief/standup → brief · triage → route ·
breakdown → breakdown · slack-summary → digest · promote, promote-note, release-gate, release-note →
promote · nudge, evidence-fill, ticket-hygiene → the phase 6 composites. Helm keeps what has no ela
counterpart: its pages, scheduler, store, permissions, deployment.

## Not built, on purpose

A server or web UI in ela; a persona; a broker between sessions; a second copy of any judgment in
Helm; a ledger of ela's own runs; automatic commits to the knowledge base; per-commit plugin
versions. Each has a recorded reason in `docs/adr/` or `docs/architecture.md`.
