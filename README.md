# ela

Evan's working assistant at TVU, as a Claude Code plugin. Definition layer only — no product code,
no knowledge. `CLAUDE.md` says what it is and is not; `ROADMAP.md` says what exists yet.

## Install (once, this machine)

```
/plugin marketplace add ~/projects/ela
/plugin install ela@ela
```

The install is a cached copy. After editing this repo: `/plugin update ela`.

## Site directory — `~/.claude/ela/` (never committed)

| file | holds |
|---|---|
| `site.json` | machine paths: projects root, records repo, map dir, sources the map reads |
| `.env` | credentials the senses need (`JIRA_*`, `SLACK_BOT_TOKEN`, `OUTLINE_*`, `TVU_*`), mode 600 |

## Skills

| skill | phase | does |
|---|---|---|
| `/ela:setup` | 1 | first run / repair of `~/.claude/ela/` — paths, credentials, read-only probe of every sense |
| `/ela:jira` | 1 | read an issue (links, subtasks, comments) or run JQL — read-only |
| `/ela:slack` | 1 | read a thread by permalink — read-only |
| `/ela:kb` | 1 | read / search Outline; write on explicit confirm |
| `/ela:objsvc` | 1 | Object Service API: objects and their tangibles, by id or search (not objectd — a different service) |
| `/ela:task` | 2 | one piece of work Evan implements: worktree, tier, delegation to the area's stack, evidence, ledger |
| `/ela:map` | 1 | build / re-verify `ela-knowledge/map/{host,absent}.yaml` against disk |

Start the session where the target's rules live (`CLAUDE.md` → *The operating rule*); ela's skills
are there because the plugin follows you.

## Records

`~/projects/ela-knowledge` (git): map · decisions · breakdowns · ledger · docs.
