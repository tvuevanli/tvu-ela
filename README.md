# ela

Evan's working assistant at TVU, as a Claude Code plugin. Definition layer only — no product code,
no knowledge. `CLAUDE.md` says what it is and is not; `ROADMAP.md` says what exists yet.

## Install (once, this machine)

```
/plugin marketplace add <projects>/ela
/plugin install ela@ela
```

The install is a cached copy, refreshed only on a version change: bump `plugin.json`, then `/plugin update ela` (or `claude plugin update ela`).

## Site directory — `~/.claude/ela/` (never committed)

| file | holds |
|---|---|
| `site.json` | machine paths: the roots (`projects`, `code`, `work`, `lab`, `records`), map dir, git hosts and aliases, sources the map reads |
| `.env` | credentials the senses need (`JIRA_*`, `SLACK_BOT_TOKEN`, `OUTLINE_*`, `TVU_*`, `UR_*`, `TVUTEST_*`, `USERSERVICE_ADMIN_SID`), mode 600 |

## The `ela` command — no Claude session needed
```
ln -s <projects>/ela/bin/ela ~/.local/bin/ela      # once
ela MH-3568        ela 01M1GD1FEG0Q4E1761A7XTBZR4        ela <32-hex process>        ela <19-digit object>
ela graphs         ela graph <id>     ela process <id>     ela find copier     ela sync tvu264 --ref 1.0.49
ela jira jql '…' --json    ela slack mentions --since 48h    ela coverage    ela help
```
Short flat verbs; an id is recognised by its shape; `graphs` defaults to you. `--json` everywhere.
ura's reads and actions are here: `ela connect · exec · start · stop <id>` (`start`/`stop` ask y/N; typing the
command at the shell is the confirm). ura is retired once they are tested.

## Session context

Every session starts with `hooks/session-start.sh` (SessionStart hook): who Evan is (`context/evan.md`), the
latest blueprint decisions and status from the knowledge base, and which mapped area the cwd is in. Read-only.
This is how ela knows Evan in any directory without an agent or a global CLAUDE.md.

## Skills

| skill | phase | does |
|---|---|---|
| `/ela:setup` | 1 | first run / repair of `~/.claude/ela/` — paths, credentials, read-only probe of every sense |
| `/ela:jira` | 1 | read an issue (links, subtasks, comments), run JQL, or create an issue / subtask (dry-run default, confirm-gated) |
| `/ela:slack` | 1 | read a thread by permalink; list channels; history, mentions and unanswered scans; `post` — the one write, dry run until `--apply`, replies in-thread by permalink, refuses duplicates |
| `/ela:kb` | 1 | read / search Outline; write on explicit confirm |
| `/ela:object` | 1 | Object Service API: an object or a tangible by id (`object.py get` — the only read; batch and search endpoints answer 404; not objectd — a different service) |
| `/ela:graph` | 1 | UR graph and process first-hand (J2N + Pilot), no environment to set: node table in pipeline order with process ids, box ips, images; a process's live record; a user's graphs; graphs carrying an object |
| `/ela:confluence` | 1 | the web team's Confluence, read-only — spaces, a space's page tree, CQL search, one page as text; `ela wiki …` or a page URL alone |
| `/ela:gdoc` | 1 | Google Docs / Sheets / Drive, read-only with Evan's token — a doc as text, a sheet tab as CSV, recent documents; `ela gdoc …` or a docs.google.com URL alone |
| `/ela:release` | 1 | release facts first-hand — GM bundles and their bill of materials, versions per env, Jenkins builds (version · branch · sha), drift between the newest bundle and the service table; `ela bundles · bundle · versions · builds · drift` |
| `/ela:probe` | 3 | deep, read-only bug investigation: ticket → graph facts → implicated service via the service table → code (cloned if missing) → root cause with file:line → drafted comments for reporter and owner |
| `/ela:figma` | 1 | read a design: file tree, node subtree + text layers, comments, rendered image — read-only |
| `/ela:report` | 4 | digest a posted report thread into what Evan must act on, decide, and pin — cross-checked against Jira |
| `/ela:route` | 4 | a bug in, a name out: implicated service, owner, or the first checker with the exact discriminating check |
| `/ela:brief` | 4 | the morning brief: stale In-Progress, unrouted new tickets, complex tickets not broken down, report threads, threads waiting on Evan, threads he wrote alone, decisions made in Slack without a ticket — ranked, each with a drafted action; read-only |
| `/ela:task` | 2 | one piece of work Evan implements: worktree, tier, delegation to the area's stack, evidence, ledger |
| `/ela:breakdown` | 3 | requirement → layer-tagged lanes with owners, order, verification; knowledge or code depth; plan in ela-knowledge, Jira publication on confirm |
| `/ela:map` | 1 | the code layout (`code/<alias>/<remote path>`, `work/<KEY>/<repo>`) and the script that keeps it: `survey` (cache) · `find` · `services` · `where` · `probe` · `clone` · `sync` · `worktree` |

Start the session where the target's rules live (`CLAUDE.md` → *The operating rule*); ela's skills
are there because the plugin follows you.

## The loop — a new requirement, end to end

1. **`/ela:breakdown <ticket / permalink / your framing>`** — anything new goes here first. A ticket
   is not required. Single-lane? It says so and hands straight to `/ela:task`. Otherwise: lanes,
   owners, order, your decisions signed — plan in `<records>/records/breakdowns/<KEY>/plan.md`.
2. **Publish on your confirm** — parent ticket if none exists, then one subtask per lane, assigned
   **directly to the lane owner** (`jira.py create` / `create-subtask`; dry-run shown first, always).
3. **Your own lane: `/ela:task <KEY> <repo>`** — worktree, tier, delegation by governance
   (mediahub-agent's workflow for `mh-app`, the repo's own rules elsewhere). No ticket? `--source`
   works: counterparts accept `verbal` and `slack` sources.
4. **ela verifies and records** — artefacts by the target's own standard, ledger in ela-knowledge.

The two entries route to each other: breakdown steps aside when there is nothing to split; task
stops and points up when handed an unsplit multi-layer ticket.

## Records

`<records>` (`<projects>/ela-knowledge`, git): `blueprint/` (ela + Helm goals, decisions, status) · `knowledge/` (canonical knowledge: products, platform, engineering, tooling) · `records/` (breakdowns, ledger, dated records) · `map/`.
