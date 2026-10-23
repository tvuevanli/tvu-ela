# Capabilities — what ela is for, and how each is exposed

The scenarios ela serves for a person who carries product responsibility across teams they do not
manage. Each names the skill or verb that serves it today; "not built" marks a gap.

| # | scenario | served by |
|---|---|---|
| S1 | The morning queue: what needs the owner today, ranked, each item with a drafted action; report threads included; read in the owner's Obsidian vault, every note within a reading budget | `/ela:brief`, `ela yesterday`, `ela vault sync` (ADR 0008) |
| S2 | Break a requirement into layer-tagged lanes with owners and order; publish to Jira on confirm; a ticket is not required to start | `/ela:breakdown` |
| S3 | Route a bug to a service and a name, or to the first checker with the exact check | `/ela:route` |
| S4 | Digest a posted report thread into what must be acted on, decided, or ticketed | `/ela:digest` |
| S5 | Implement the owner's own lane under the target repository's rules: worktree, delegation, evidence in the merge request | `/ela:task`, `ela mr` |
| S6 | Read code and technology first-hand and record the reading on the owner's word | `/ela:probe`, `probe how`, `/ela:feasible`, `/ela:arch`, `/ela:map`, `ela sessions` |
| S7 | Assess a promotion between lanes from first-hand release facts | `/ela:promote`, `ela release`, `ela bundle-diff` |
| S8 | Answer colleagues' questions through the Slack bot, speaking as ela, citing recorded decisions | Helm's bot over `clients/ela.py`; gated by ADR 0005 and the proof rule |
| S9 | Nudge, evidence fill and ticket hygiene behind confirm and idempotency | `ela jira` atoms; composites not built |
| S10 | Write and update knowledge in the company wiki in place | `/ela:kb` |
| S11 | Develop Helm and ela under each repository's own rules | `docs/`, the location guard |
| S12 | Record decisions and changes of mind by supersession, never by rewriting | `docs/adr/`, elak `blueprint/decisions/` |
| S13 | Set up or repair credentials on a new machine | `/ela:setup` |
| S14 | Gate the owner's own one-way asks: problem, alternative, conflicting decision, verdict with the rejected option | `CLAUDE.md` §Gate |
| S15 | Know the owner in any directory without a persona or a global agent | `hooks/session-start.sh` |
| S16 | Read a process's logs and state on a box, and the platform's diagnostic records, without a person at a terminal | `ela logs` (tvulog process-log and java-log, Loki), used by `/ela:route`; `ela configserver` (the runtime configuration a decision reads, per environment, redacted); `ela connect/exec` interactive only; `inspect`, UR diagnostics not built |
| S17 | Make one ticket judgeable before acting on it: the runtime instance, whether the fix named on it still exists, the ticket's assertions against the thread's decisions, who it waits on | `/ela:explain` |
| S19 | Verify a ticket's behaviour in the product in a real browser on a named lane, read-only: the version panel read in the same browser run and matched against the release map is the proof, the cases come from the ticket and from the file at the lane's build, and the result goes to the owner as a report and to the ticket as a short comment | `/ela:verify`, `ela browser env · run`; the browser is a sense, the verdict is the skill's |
| S20 | Keep the board true to the builds: for every open ticket, where its fix actually is (none / QA lane / daily / prod, by ancestry), how long, and what the ticket still owes — a close proposal, a Fixed In, a word to QA — grouped by action so the owner confirms batches; an Epic is one queue with its children; a terminal status is the owner's own click in Jira, or a close he names himself, which `ela jira close --terminal` performs one ticket per confirm | `ela stage`, over `ela fixed-in`; the writes are the `jira` atoms, dry run each; `ela jira transition` refuses terminal statuses |
| S18 | Decide whether an old ticket still needs to exist: the problem read apart from the plan written for it, checked against today in cost order, then close / carry to a keyed ticket / keep with the next skill named | `/ela:revisit` |

## Exposure by kind

| kind | examples | script | session | headless | MCP |
|---|---|---|---|---|---|
| read | jira, slack, kb, object, graph, release, map, apifox, mail | yes | yes | yes | yes (when built) |
| gated write | jira comment/transition/label/link/fixed-in/assign, slack post, kb write | yes, dry run until `--apply` | yes, after the owner's word | yes, `--apply` only behind the caller's confirm | no |
| judgment | explain, brief, breakdown, route, digest, promote, probe, feasible, ask | — | yes | yes: an unattended session (`claude -p`, reads and dry runs only under `ELA_NO_APPLY`), as ela-runner and its Slack service start one; the `ela run` verb is not built | no — an MCP consumer is a model |

A capability is a script first. A skill exists only where a session needs judgment or invariants to
use it well; a verb where a person wants it at the shell; an MCP tool where another model needs it.
None implies the others.
