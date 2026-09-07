# Architecture — ela, Helm, elak

One working system with several interfaces. The judgment and the deterministic capabilities live in
one place (ela); the knowledge lives in one place (elak); the shared, machine-readable subset is a
build output (the published directory); Helm is a runtime and a set of interfaces over ela. Every
other location is configuration or disposable working state.

## Components

| component | is | visibility | must not hold |
|---|---|---|---|
| **ela** (this repository) | L1 capability scripts (`skills/<name>/<name>.py`, stdlib, `--json`, dry-run writes), the `ela` command, the Claude skills that need judgment, three hooks, this documentation | shareable inside the company | knowledge, hosts, credentials, personal preferences, anyone's words |
| **elak** | knowledge: `knowledge/` (readings a person wrote), `map/` (facts a script derived and stamped), `blueprint/` (ela's own principles, decisions, status table, exit evidence) | private | narratives, logs, status prose, quotations, other people's documents, Helm's runtime data |
| **published directory** | the output of `ela publish`: the map subset with addresses redacted, the service catalogue, the roster (names, roles, emails and account ids — the identity source Helm resolves against; accepted for company-internal readers by the owner's decision of 2026-09-07) | shareable inside the company | anything not produced by `publish.py`; it is deleted and regenerated, never edited |
| **Helm** | Evan's operations app: web pages, the Slack bot, the scheduler, an HTTP API, deployment | shareable inside the company | new judgment logic (it calls ela through `clients/ela.py`); a second copy of knowledge |
| **site** (`~/.claude/ela/`) | `site.json` (roots, hosts, aliases), `.env` (credentials), caches, `working-with-evan.md` | this machine only | knowledge |
| **runtime** (`<projects>/.ela`) | worktrees, raw pulls, drafts, generated intermediates | this machine only, deletable | anything that must survive the task |
| **reports** (`<projects>/reports`) | Evan's reading surface: markdown sources and rendered HTML published as private artifacts | private, not versioned | — |

Three git repositories, no more: ela, Helm, elak. The published directory, the site, the runtime and
the reports are not repositories.

## Layers inside ela

| layer | form | rule |
|---|---|---|
| L0 site | `~/.claude/ela/` | paths and credentials, never in a tracked file |
| L1 atomic | one script per capability | deterministic; reads freely; every write is a dry run until `--apply` |
| L2 composite | a `SKILL.md` a Claude session follows | judgment over L1; never a raw API call |
| L3 adapter | `bin/ela`, a `SKILL.md`, Helm's `clients/ela.py`, a future MCP server | translation only; a Jira- or Slack-specific branch in an adapter is a defect |

Interfaces — the terminal, a Claude session, Helm's pages and bot, the scheduler, an external AI
through an API — all reach the same L1 and L2. Nothing is implemented twice.

## Information lifecycle

| tier | example | lives in | dies | versioned |
|---|---|---|---|---|
| conversation | the ask, the reasoning, tool output | the session | with the session | never |
| raw material | a Slack export, a ticket body, a log | runtime | with the task | never |
| working notes | a task's intermediate findings | `runtime/work/<KEY>/` | when the finding is written to the ticket or MR | never |
| reading surface | a review report | reports | at the next regeneration | no |
| derived fact | `map/services.yaml`, `map/dependencies.yaml` | elak `map/` | at the next sync | yes, stamped with its source |
| knowledge | a reading that passes the one-year test | elak `knowledge/` | when superseded | yes, on Evan's word |
| rule | a principle or decision that changes ela's behaviour | elak `blueprint/` or `docs/adr/` here | when superseded by a newer file | yes, on Evan's word |
| formal artefact | a ticket, a comment, a KB page, an MR, a post | the company system that owns it | that system's rule | not here |

Admission to elak needs all three: it will still be true in a year; no first-hand source answers it
directly (otherwise a pointer suffices); Evan confirmed it should be recorded. What merely happened is
cited by permalink, ticket key or commit and no file is kept.

## Input is not output

A message from Evan, a Slack thread, a CLI argument or a thought relayed from another AI is input.
It becomes a commit message, a document, a rule or a knowledge entry only after ela rewrites it in
the destination's genre, with the origin cited, and — for anything read by others or kept for a year —
after Evan confirms. A rule born in a conversation is drafted first and written to a shared tree in a
later pass. Nothing is committed to elak by a hook.

## Control boundaries

| action | confirm | mechanism |
|---|---|---|
| read any first-hand source | none | default |
| dry run, draft | none | default |
| write to Jira, Slack, Outline, a merge request | Evan, per item | `--apply` after his word; Helm's button after his click |
| write to elak | Evan ("record this") | a hand commit; the SessionEnd hook only reports a dirty tree |
| commit to ela or Helm | ela, under the content guard | `hooks/content-guard.sh` as pre-commit and commit-msg |
| publish the shared subset, deploy the remote | Evan | `ela publish`, then Helm's deploy script |
| a write to another team's running system | never | not implemented |

## Development

- ela and elak are edited in a session started in the repository; the location guard enforces it.
- One concern per commit. Subject under 72 characters stating what changed; body one to three
  sentences stating why the code needed it; a ticket key or an ADR filename for the reason.
- The plugin version moves when Evan reinstalls the plugin, not on every commit.
- Verification: `python3 -m py_compile` over every script, every `--help`, the guard's own test,
  unit tests for parsers and guards. Helm keeps its test suite and runs it before deploy.
- No CI for elak or the reports. The published directory is built, not developed.

## Failure modes to watch

More than one decision file a day; a `SKILL.md` per verb; a new prompt or skill in Helm; `git commit`
inside a hook; an `@` or a dotted address in the published directory; a SessionStart injection longer
than a screen; a registry of registries. Each is a sign the system is growing for its own sake.
