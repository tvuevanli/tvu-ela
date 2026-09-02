# ela

Evan's working assistant at TVU, as a Claude Code plugin. Definition layer only — no product code,
no knowledge. `CLAUDE.md` says what it is and is not; `ROADMAP.md` says what exists yet.

## Install (once, this machine)

```
/plugin marketplace add ~/projects/ela
/plugin install ela@ela
```

The install is a cached copy, refreshed only on a version change: bump `plugin.json`, then `/plugin update ela` (or `claude plugin update ela`).

## Site directory — `~/.claude/ela/` (never committed)

| file | holds |
|---|---|
| `site.json` | machine paths: projects root, records repo, map dir, sources the map reads |
| `.env` | credentials the senses need (`JIRA_*`, `SLACK_BOT_TOKEN`, `OUTLINE_*`, `TVU_*`), mode 600 |

## Skills

| skill | phase | does |
|---|---|---|
| `/ela:setup` | 1 | first run / repair of `~/.claude/ela/` — paths, credentials, read-only probe of every sense |
| `/ela:jira` | 1 | read an issue (links, subtasks, comments), run JQL, or create an issue / subtask (dry-run default, confirm-gated) |
| `/ela:slack` | 1 | read a thread by permalink — read-only |
| `/ela:kb` | 1 | read / search Outline; write on explicit confirm |
| `/ela:object` | 1 | Object Service API: objects and their tangibles, by id or search (not objectd — a different service) |
| `/ela:figma` | 1 | read a design: file tree, node subtree + text layers, comments, rendered image — read-only |
| `/ela:report` | 4 | digest a posted report thread into what Evan must act on, decide, and pin — cross-checked against Jira |
| `/ela:route` | 4 | a bug in, a name out: implicated service, owner, or the first checker with the exact discriminating check |
| `/ela:task` | 2 | one piece of work Evan implements: worktree, tier, delegation to the area's stack, evidence, ledger |
| `/ela:breakdown` | 3 | requirement → layer-tagged lanes with owners, order, verification; knowledge or code depth; plan in ela-knowledge, Jira publication on confirm |
| `/ela:map` | 1 | build / re-verify `ela-knowledge/map/{host,absent}.yaml` against disk |

Start the session where the target's rules live (`CLAUDE.md` → *The operating rule*); ela's skills
are there because the plugin follows you.

## The loop — a new requirement, end to end

1. **`/ela:breakdown <ticket / permalink / your framing>`** — anything new goes here first. A ticket
   is not required. Single-lane? It says so and hands straight to `/ela:task`. Otherwise: lanes,
   owners, order, your decisions signed — plan in `ela-knowledge/breakdowns/`.
2. **Publish on your confirm** — parent ticket if none exists, then one subtask per lane, assigned
   **directly to the lane owner** (`jira.py create` / `create-subtask`; dry-run shown first, always).
3. **Your own lane: `/ela:task <KEY> <repo>`** — worktree, tier, delegation by governance
   (mediahub-agent's workflow for `mh-app`, the repo's own rules elsewhere). No ticket? `--source`
   works: counterparts accept `verbal` and `slack` sources.
4. **ela verifies and records** — artefacts by the target's own standard, ledger in ela-knowledge.

The two entries route to each other: breakdown steps aside when there is nothing to split; task
stops and points up when handed an unsplit multi-layer ticket.

## Records

`~/projects/ela-knowledge` (git): map · decisions · breakdowns · ledger · docs.
