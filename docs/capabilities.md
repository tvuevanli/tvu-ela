# Capabilities — what ela is for, and how each is exposed

The scenarios ela serves for a person who carries product responsibility across teams they do not
manage. Each names the skill or verb that serves it today; "not built" marks a gap.

| # | scenario | served by |
|---|---|---|
| S1 | The morning queue: what needs the owner today, ranked, each item with a drafted action; report threads included | `/ela:brief` |
| S2 | Break a requirement into layer-tagged lanes with owners and order; publish to Jira on confirm; a ticket is not required to start | `/ela:breakdown` |
| S3 | Route a bug to a service and a name, or to the first checker with the exact check | `/ela:route` |
| S4 | Digest a posted report thread into what must be acted on, decided, or ticketed | `/ela:digest` |
| S5 | Implement the owner's own lane under the target repository's rules: worktree, delegation, evidence in the merge request | `/ela:task` |
| S6 | Read code and technology first-hand and record the reading on the owner's word | `/ela:probe`, `/ela:feasible`, `/ela:arch`, `/ela:map` |
| S7 | Assess a promotion between lanes from first-hand release facts | `/ela:promote`, `ela release` |
| S8 | Answer colleagues' questions through the Slack bot, speaking as ela, citing recorded decisions | Helm's bot over `clients/ela.py`; gated by ADR 0005 and the proof rule |
| S9 | Nudge, evidence fill and ticket hygiene behind confirm and idempotency | `ela jira` atoms; composites not built |
| S10 | Write and update knowledge in the company wiki in place | `/ela:kb` |
| S11 | Develop Helm and ela under each repository's own rules | `docs/`, the location guard |
| S12 | Record decisions and changes of mind by supersession, never by rewriting | `docs/adr/`, elak `blueprint/decisions/` |
| S13 | Set up or repair credentials on a new machine | `/ela:setup` |
| S14 | Gate the owner's own one-way asks: problem, alternative, conflicting decision, verdict with the rejected option | `CLAUDE.md` §Gate |
| S15 | Know the owner in any directory without a persona or a global agent | `hooks/session-start.sh` |
| S16 | Read a process's logs and state on a box, and the platform's diagnostic records, without a person at a terminal | `ela connect/exec` interactive only; `logs`, `inspect`, UR diagnostics not built |
| S17 | Make one ticket judgeable before acting on it: the runtime instance, whether the fix named on it still exists, the ticket's assertions against the thread's decisions, who it waits on | `/ela:explain` |
| S18 | Decide whether an old ticket still needs to exist: the problem read apart from the plan written for it, checked against today in cost order, then close / carry to a keyed ticket / keep with the next skill named | `/ela:revisit` |

## Exposure by kind

| kind | examples | script | session | headless | MCP |
|---|---|---|---|---|---|
| read | jira, slack, kb, object, graph, release, map, apifox, mail | yes | yes | yes | yes (when built) |
| gated write | jira comment/transition/label/link/assign, slack post, kb write | yes, dry run until `--apply` | yes, after the owner's word | yes, `--apply` only behind the caller's confirm | no |
| judgment | explain, brief, breakdown, route, digest, promote, probe, feasible, ask | — | yes | yes (`ela run`, not built) | no — an MCP consumer is a model |

A capability is a script first. A skill exists only where a session needs judgment or invariants to
use it well; a verb where a person wants it at the shell; an MCP tool where another model needs it.
None implies the others.
