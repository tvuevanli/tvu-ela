# Roadmap

What exists, what each phase must prove before the next starts, and what is deliberately not built.
The architecture is `docs/architecture.md`; the scenarios are `docs/capabilities.md`.

| phase | delivers | exit test | state |
|---|---|---|---|
| 0 charter | this repository's rules, the layers, the guards | — | done |
| 1 senses and map | first-hand reads of Jira, Slack, Outline, Confluence, Google Docs, Apifox, Figma, Object Service, UR, release lanes, mail, the stream on the wire; the code map; the `ela` command; publication to the shared directory | `ela publish list` clean; every repository in the map has a governance value | done |
| 2 task | one piece of the owner's own work end to end: worktree, tier, delegation to the area's stack, evidence in the merge request | one task delivered with the counterpart's artefacts present | written, not exercised |
| 3 judgment | breakdown, probe, route, feasible, arch over the senses; the existence verdict on an old ticket (revisit) | one plan matching what the owner would have written; three root causes that held | built; one root cause held |
| 4 brief and digest | the morning queue and report digests, drafts only | two weeks in which the brief is read first and nothing it missed surfaced later | built; window not started |
| 5 diagnostics | `ela logs`, `ela inspect`, UR diagnostic reads, Sentry over mail; the boundary agent through its API | the three cases in the 2026-09-07 review answered without a person at a terminal | not started |
| 6 composites | nudge, sweep, ticket-from-thread, decision capture behind the write gate; the headless entry `ela run` | the third follow-up on a bug is never hand-written | not started |
| 7 exposure | an MCP server for the bot and external models; Helm's duplicated skills retired on parity | others use it without the owner in the loop | not started |

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
