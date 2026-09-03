---
name: map
description: Build or re-verify ela's map of the world — every repo on this machine (the survey cache), everything known to exist that is NOT here (absent.yaml), and the service table (services.yaml: docker image → process types → owners → repos) — against the filesystem; find where a service's code is and clone what is missing from the LAN GitLab. Use when starting in an unfamiliar area, when a repo was added/moved/renamed, when a counterpart's registry disagrees with disk, or on "what do we have", "where is X", "is Y checked out", "update the map", "地图", "盘点仓库".
user-invocable: true
---

# /ela:map — the map is a claim, the filesystem is the fact

Self-contained. Knowledge: `map/services.yaml` and `map/absent.yaml`. Cache: `~/.claude/ela/map/host.json` (rebuilt by `map.py survey`). Read-only everywhere else; `clone`, `sync --ref` and `worktree` are the actions, and none of them edits a checkout.

## Invariants
- **"Absent" is a claim about the group listing, not about a guessed name.** Where a host has an API
  token (`site.json hosts.<host>.api` + `token_env`), `remote <alias>` lists the whole group; an image
  is recorded as having no repo only after that listing was searched, and `find` shows `remote` hits
  (not cloned) beside disk hits. A name-only probe is the fallback when no token exists.
- **No edits in a checkout.** `git` queries and file reads; `sync` fetches and `worktree` adds a
  worktree, nothing else touches a repo — never edit, stage or commit inside `code/`.
- **Disk wins.** Map and disk disagree → change the map.
- **Absent is a first-class fact.** Known-to-exist-but-not-here is recorded with owner and location,
  never dropped. Analysis that reaches an absent repo says so and stops.
- **Same name is not the same repo.** One name can resolve to several remotes, and to several
  paths on one remote, with overlapping but divergent content. Identity is proven by refs and
  content, never by the name.
- **Cite, never copy.** Record where each fact was verified (path or command).

## The layout, and the script that keeps it
Every checkout that is not Evan's lives at **`<code>/<alias>/<remote path>`** — the placement rule; the alias is a function of
the remote's (host, group), defined only in `~/.claude/ela/site.json` — `media` · `web` · `mx` ·
`lr/rx` · `lr/receiver` · `github/<org>`. No categories, no judgment; one exception table
(`dir_names`) where a team stack requires a directory name. `work/<KEY>/<repo>` is where code is
changed; `lab/` holds experiments without an upstream; `archive/` is not surveyed.

What is on disk is a **cache**, not knowledge: `survey` rebuilds `~/.claude/ela/map/host.json` in
seconds. The knowledge base keeps only what cannot be derived: `map/services.yaml` (docker image →
slugs · GM names · process types → owners → repos) and `map/absent.yaml`.
```bash
MAP="python3 ${CLAUDE_PLUGIN_ROOT}/skills/map/map.py"
$MAP survey                              # scan code/ work/ lab/ + Evan's repos → cache; reports misplaced / unaliased / dirty
$MAP find <repo|image|process type>      # paths, owners, slugs, or where to clone from
$MAP services [--image X | --type T]     # the service table
$MAP where <alias>/<path>                # the directory a remote maps to (no network)
$MAP remote <alias> [grep]               # every project of that GitLab group, subgroups included (host api + read token in site.json); ● on disk; cached a day
$MAP probe <alias>/<path> …              # ssh ls-remote — the media GitLab's API lists only public projects
$MAP clone <alias>/<path> [--dry-run]    # into its place; imatrix sibling links kept
$MAP sync <repo> [--ref R]               # fetch; branch, ahead/behind, dirty, recent tags; check out a ref (code/ only, clean only)
$MAP worktree <repo> <KEY>               # branch evan/<key>; work/<KEY>/<repo>, or beside the repo when a stack requires it
$MAP coverage                            # is the code we usually need on disk? per image and per alias
$MAP missing                             # absent.yaml, one line each
```
`slug` (Evan's convention, from Helm) · `gm_name` (what GM registers) · `service_id` are three
different things and stay apart in services.yaml.

**Enumeration of the media group** still needs a read token for the media GitLab — until then the
group is probed by name, never listed. **Naming trap:** tvu-catalog's `unified-resources` is Paul
Shen's Go monorepo, not the `mx` group.

## Step 0 — site file
Read `~/.claude/ela/site.json`. Required: `projects`, `hosts` (the two GitLab addresses; GitHub is
built in). Everything else has a default derived from `projects` (`code`, `work`, `lab`, `records`,
`map`, `aliases`, `dir_names`, `stacks`, `map_sources`). Missing file → `/ela:setup`. Never guess a root.

## Step 1 — survey disk → the cache
`$MAP survey`. It walks `<code>`, `<work>`, `<lab>` and Evan's three repos, records remote · branch ·
dirty · last commit · worktrees · rule files · governance per checkout, and reports three kinds of
drift: **misplaced** (a checkout whose remote says it belongs elsewhere under `<code>`), **no alias**
(a remote whose (host, group) has no entry — ask Evan for the alias, never invent one), **dirty in
code/** (edits belong in `<work>`). A clean survey prints one line.

## Step 2 — the service table and the absent
- `map/services.yaml`: one entry per docker image — slugs (Evan's convention), GM names, service ids,
  process types, owners, repos as GitLab group paths. Local dirs are derived, never written. Sources:
  Helm's `docker-service-map.md`, the taxonomy in agentic-observability, probes, investigations. Update
  it when a service appears in GM, when a probe finds a repo, when an investigation pins where the code
  is. Cite the source line.
- `map/absent.yaml`: what is known to exist and is not on disk — with owner, why it matters, what was
  probed. Every `map_sources` entry (mediahub-agent's `workspace.json` incl. `outOfScopeServices`,
  tvu-catalog modules, Helm's service catalog) is checked against the cache: declared and not on disk →
  an entry. Found later → the entry goes.

## Step 3 — governance, per checkout
| value | evidence |
|---|---|
| `team-stack` | the alias has a stack in `site.json` (`web` → mediahub-agent). The stack's tooling decides worktree placement and names |
| `repo-local` | the checkout carries `CLAUDE.md`, `.claude/`, `AGENTS.md` or `openspec/` |
| `bare` | nothing |
| `read-only` | Evan declared it |

## Step 4 — output
1. survey line: repos · misplaced · unaliased · dirty
2. services with no repo on disk, and absent entries that a probe could resolve
3. anything unclassifiable, with the exact evidence — never a guess

### Same name, several repos
One name resolves to several remotes: the iMatrix product source (`media/imatrix/prj/<name>`, rich
ref set, no vendored `depends/`) and its CI shell (`media/<name>`, single branch, vendored
`depends/`), plus GitHub mirrors. Under the layout rule they land in different directories by
construction; `services.yaml` says which is the module source. Judge by refs and content, never by name.
