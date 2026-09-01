---
name: map
description: Build or re-verify ela's map of the world — every repo on this machine (host.yaml) and everything known to exist that is NOT here (absent.yaml) — against the filesystem. Use when starting in an unfamiliar area, when a repo was added/moved/renamed, when a counterpart's registry disagrees with disk, or on "what do we have", "where is X", "is Y checked out", "update the map", "地图", "盘点仓库".
user-invocable: true
---

# /ela:map — the map is a claim, the filesystem is the fact

Self-contained. Produces two YAML files in the records repo. Read-only everywhere else.

## Invariants
- **Read-only over product repos.** `git` queries and file reads only; never edit, commit, fetch
  into, or create files in any repo other than the `map` dir.
- **Disk wins.** Map and disk disagree → change the map.
- **Absent is a first-class fact.** Known-to-exist-but-not-here is recorded with owner and location,
  never dropped. Analysis that reaches an absent repo says so and stops.
- **Same name is not the same repo.** One name can resolve to several remotes, and to several
  paths on one remote, with overlapping but divergent content. Identity is proven by refs and
  content, never by the name.
- **Cite, never copy.** Record where each fact was verified (path or command).

## Step 0 — site file
Read `~/.claude/ela/site.json`: `projects`, `map`, `map_sources` (`mediahub_agent_workspace`,
`tvu_catalog_modules`, `helm_service_catalog`, `team_roster`). Missing file or missing
`projects`/`map` → stop; run `/ela:setup`. Never guess a root.

## Step 1 — survey disk → `host.yaml`
Walk `projects` into aggregators (`mh-app/`, `ur/`, `mds/`, `lr/`, `others/`, `prototypes/`, and
any dir that itself contains git repos). Aggregators nest — `mds/` holds `AI/`, `github/`,
`playeroftvu-deps/` — so descend until the directories are repos. Per git repo:

| field | how |
|---|---|
| `path` `area` | absolute; area = the **top-level** aggregator (`root` if top-level); a sub-grouping such as `playeroftvu-deps/` shows only in `path` |
| `remote` `branch` `dirty` `last_commit` | `git remote get-url origin` · `rev-parse --abbrev-ref HEAD` · `status --porcelain \| wc -l` · `log -1 --format='%ad %an' --date=short` |
| `worktrees` | `git worktree list` minus the main entry |
| `governance` | taxonomy below, with the evidence seen |
| `federate` | the rule files found in the repo (`CLAUDE.md`, `.claude/settings.json`, `AGENTS.md`, `openspec/`, `.husky/`) |
| `owner` | from the area's own source of truth (`mediahub_agent_workspace`, `team_roster`, the repo's `CLAUDE.md`); else `unknown` — never invent |

Non-git directories → `non_repos` with size and a one-line purpose; never treated as projects.

### Governance taxonomy
| value | evidence |
|---|---|
| `team-stack` | a **sibling resource repo** in the same area holds `.claude/agents/` + skills/hooks and no product code (`mediahub-agent` for `mh-app`), or the area's team ships an agent plugin (`tvu-engineering-team` for `mds`). Record `stack:`. |
| `repo-local` | the repo itself carries any `federate` file |
| `bare` | README only, or nothing |
| `read-only` | Evan declared it; never inferred |

`team-stack` repos usually also have repo-local files — record `team-stack` and still list `federate`.

### Area block
Per area: `path`, `governance`, `stack` (if team-stack), `humans` (from `team_roster` / the area's own registry), `host` (git host, when it differs — `mds` is on `10.12.23.181:22222`).

### Host precedence and mirrors
Some repos are reachable on more than one host — GitLab `10.12.23.181:22222` (LAN) and GitHub
`tvunetworks-com`. Treat the host as part of the repo's identity.

| rule | why |
|---|---|
| Acquire from GitLab when the repo exists there; GitHub only when it does not | GitLab is on the LAN, so clones are far faster |
| Resolve the path by refs before cloning — `git ls-remote <url>`, compare branches and tags | one host can carry several paths for one name, and the richer ref set is the product source, not the shell |
| Every checkout on disk is its own entry — `authoritative: true` on the source, `mirror_of` on the copy | the survey must list what is on disk; folding a copy into the source hides staleness and hides decoys |
| State the divergence as a measurement | `git log -1 --format='%h %ad'` on both, plus `diff -rq -x .git \| wc -l` |

Three divergence shapes, all seen in `mds`, all needing different handling:

| shape | signature | handling |
|---|---|---|
| **identical** | same HEAD, zero content diff | note the mirror, use either |
| **stale mirror** | same lineage, one side months behind | authoritative = the advanced side; the other is read-only reference |
| **different repo under one name** | unrelated commit subjects or a different tree layout | two entries, never merged; say what each actually is |

A repo present only on GitHub is a normal fact, not a gap — record the host and move on.

**Enumeration gap.** The GitLab API on `10.12.23.181` answers anonymously, but only about public
projects — and that is worse than a refusal, because the answer looks complete. Measured 2026-09-01:
`/api/v4/groups/media/projects` returned 2 entries, neither of them a product repo, while
`/api/v4/groups/media%2Fimatrix` and `%2FAI` — where the repos actually live — returned 404 and
`/groups/media/subgroups` returned `[]`. `git ls-remote` over SSH is the only enumeration that sees
them, and it can only confirm names it is given — so a group listing is **never** recorded as
complete. Record `enumeration: probed` plus the candidate list used, and ask Evan for the group's
listing or a token before claiming an area is fully mapped.

## Step 2 — the known-absent → `absent.yaml`
For each `map_sources` entry, list what it declares and check for a local checkout (match on repo /
dir name; honour aliases such as `tvucc-media` = Eureka `media-mx`):
- `mediahub_agent_workspace` → `services[].dir`, `frontends[].dir`, and **`outOfScopeServices`**
  (real Feign callers of in-scope services — the absences that bite hardest).
- `tvu_catalog_modules` → one per `*.yaml`.
- `helm_service_catalog` → each service entry with a repo reference.

Each absence: `name`, `declared_by`, `owner`, `location`, `why_it_matters` (one line, e.g. "inbound
Feign caller of orchestration"), `verified`.

## Step 3 — diff against the existing map
If the files exist, compare field by field and report: **moved/renamed** · **gone** · **new** ·
**lane drift** · **governance drift** · **absent↔present**. Then write both files with `verified:`
dates.

## Step 4 — output
1. one line of totals: repos · non-repos · absent · drift count
2. the drift table (empty is good)
3. absences whose `why_it_matters` names an in-scope caller
4. anything unclassifiable, with the exact evidence — never a guess

**Phase 1 exit:** two consecutive runs with an empty drift table.

## Schema (abridged)
```yaml
# host.yaml
verified: 2026-08-28
areas:
  mh-app: { path: /home/evan/projects/mh-app, governance: team-stack,
            stack: /home/evan/projects/mh-app/mediahub-agent,
            humans: "Andy Zhao (backend) · Summer Chen (frontend)" }
repos:
  - { name: mx-service, area: mh-app, path: /home/evan/projects/mh-app/mx-service,
      remote: git@10.12.22.173:webteam/mx-service.git, branch: release2.1, dirty: 0, worktrees: [],
      governance: team-stack, federate: [CLAUDE.md, .claude/], owner: "Andy Zhao", verified: 2026-08-28 }
  - { name: libplayer, area: mds, path: /home/evan/projects/mds/playeroftvu-deps/libplayer,
      remote: ssh://git@10.12.23.181:22222/media/imatrix/prj/libplayer.git, branch: main,
      dirty: 0, last_commit: 2026-07-22 shawnpan, authoritative: true, verified: 2026-09-01 }
  - { name: libplayer, area: mds, path: /home/evan/projects/mds/github/libplayer,
      remote: git@github.com:tvunetworks-com/libplayer.git, branch: main,
      dirty: 0, last_commit: 2025-12-24 jasson, mirror_of: "libplayer@10.12.23.181",
      drift: "stale: 2025-12-24 vs 2026-07-22, 48 entries differ", verified: 2026-09-01 }
non_repos:
  - { path: /home/evan/projects/_analysis, size: 7.5M, note: "architecture analysis artefacts" }

# absent.yaml
verified: 2026-08-28
absent:
  - { name: tvugo, declared_by: mediahub_agent_workspace.outOfScopeServices, owner: unknown,
      location: unknown, verified: 2026-08-28,
      why_it_matters: "calls tvucc-media, mx-service (/feign/stopByObjectId, shared DB+Redis), workflow-engine" }
```
