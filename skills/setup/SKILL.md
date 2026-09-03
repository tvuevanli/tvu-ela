---
name: setup
description: First-run and repair of ela's site directory (~/.claude/ela) — machine paths in site.json and credentials in .env — with a read-only probe of every sense. Use on a new machine, when a sense fails to authenticate, when a token was rotated, or on "set up ela", "ela setup", "配置 ela", "token 过期".
user-invocable: true
---

# /ela:setup — make this machine ready for ela

Self-contained. Never prints a secret value; only key names and probe results.

## Invariants
- Everything you write goes under `~/.claude/ela/` only. Never into the plugin, never into a repo.
- Host addresses (`hosts`) live **only** here. No tracked file names a git host by address; documents
  say "the media GitLab" / "the web GitLab" and point at `site.json`.
- `.env` is mode `600`. Show which keys exist, never their values.
- Probes are read-only calls. No probe writes anywhere.

## 1. site.json — machine paths

Target shape:

```json
{
  "projects": "<root — holds ela, elak, helm and the three roots below>",
  "code":     "<projects>/code     — every checkout that is not Evan's, at code/<alias>/<remote path>; never edited in place",
  "work":     "<projects>/.ela/work — one task, one dir: work/<KEY>/<repo> worktrees (or symlinks to a stack's own place); under <runtime>, so removable at close",
  "runtime":  "<projects>/.ela      — transient working state: nothing here is a record; the whole tree can be deleted when no task is open and nothing is lost",
  "lab":      "<projects>/lab      — experiments without an upstream owner",
  "records":  "<elak repo>",
  "published": "<projects>/elak-published — what elak publishes for machines to read (Helm's knowledge root, the map subset); not a repo, regenerated; on the remote the same name under its projects root, and `records`/`map` point into it",
  "site":     "<local | remote — remote: no intranet hosts/services, public-source credentials only, records is the published subset>",
  "map":      "<records>/map        — services.yaml · absent.yaml (knowledge); the disk survey is a cache at ~/.claude/ela/map/host.json",
  "env":      "~/.claude/ela/.env",
  "hosts":    { "<name>": { "url": "<git host url>", "matches": ["<hostnames as they appear in remotes>"], "api": "<http root of the GitLab API, optional>", "token_env": "<.env key holding a read_api token, optional — enables `map.py remote`>" } },
  "aliases":  { "<alias>": { "host": "<hosts key>", "group": "<gitlab group or * for a github org root>" } },
  "dir_names": { "<alias>/<remote name>": "<alias>/<dir name a team stack requires>" },
  "stacks":   { "<alias>": "<path of the team stack repo that governs that alias>" },
  "emails":   { "me": "<Evan's address>", "<alias>": "<a colleague's address — `ela graphs li`>" },
  "services": { "jenkins": { "url": "<Jenkins root>" }, "userservice": { "url": "<GM userservice, prod>" }, "userservice-test": { "url": "<GM userservice, QA>" }, "confluence": { "url": "<the web team's Confluence root>" } },
  "map_sources": {
    "mediahub_agent_workspace": "<mh-app>/mediahub-agent/workspace.json",
    "tvu_catalog_modules":      "<tvu-knowledge>/tvu-catalog/catalog/modules",
    "helm_service_catalog":     "<helm>/knowledge/mediahub/services/service-catalog.md",
    "team_roster":              "<helm>/knowledge/mediahub/team/team-map.md"
  }
}
```

For each key: if the file exists, check the path resolves (`test -e`). If it does not, look for the
obvious candidate under `projects` (same basename) and **propose** it — Evan confirms before you
write. `records` missing on disk → offer to `git init` it with the layout in its README. Never
invent a path.

## 2. .env — credentials

Keys and where each comes from when absent:

| key | source |
|---|---|
| `JIRA_BASE_URL` `JIRA_EMAIL` `JIRA_TOKEN` | Atlassian account → Security → API tokens |
| `SLACK_BOT_TOKEN` | the workspace's Slack app → OAuth & Permissions → Bot User OAuth Token (`xoxb-…`) |
| `OUTLINE_URL` `OUTLINE_TOKEN` | Outline (kb.tvunetworks.com) → Settings → API tokens |
| `TVU_OBJECT_SERVICE_HOST` `TVU_CC_BEARER_TOKEN` | Object Service host + a CC bearer token from a logged-in session |
| `FIGMA_TOKEN` | Figma → Settings → Security → Personal access tokens (read scope) |
| `GITLAB_MEDIA_TOKEN` `GITLAB_WEB_TOKEN` | each GitLab → Preferences → Access Tokens, scope `read_api` only; named by `token_env` in `site.json hosts` — lets `map.py remote` list a whole group |
| `APIFOX_TOKEN` | Apifox → account settings → personal access token (read); lets `apifox.py` export a project's OpenAPI document. Project ids by name in `<records>/map/apis.yaml` |
| `CONFLUENCE_TOKEN` | the web team's Confluence → profile → Personal Access Tokens (read); the host URL goes in `site.json services.confluence.url` |
| `GOOGLE_TOKEN_FILE` | path to a Google OAuth token JSON with read-only scopes (documents.readonly, drive.readonly) — Helm's grant copied once into the site dir, mode 600 |
| `UR_ACCESS_KEY` | UR access key — a JSON blob, copied verbatim on one line; `UR_BASE_HOST` (optional, default UR host) and `UR_ENV_ORDER` (optional comma list overriding the probe order `prod3,prod2,test2`) |
| `TVU_SSH_USER` `TVU_SSH_PASSWORD` | box ssh for `graph connect` / `exec` (user defaults to the operate account) |
| `TVUTEST_ACCOUNT` `TVUTEST_PASSWORD` `TVUTEST_SID` | release reads (QA GM host): a tvutest account; the login's SID is cached as `TVUTEST_SID` (2 h, refreshed by the script). No prod session anywhere in ela — decision `ela-needs-no-sid` |

Procedure: list which keys are present; for each missing one say where to get it and ask Evan to
paste it **into the file himself** or hand it to you for a single `printf >>` — then `chmod 600`.
If a key exists elsewhere on the machine (an older tool's env file), you may copy **that key only**,
once, and say so; ela does not keep reading the other file.

## 3. Probe every sense (read-only)

```bash
ENV=$(python3 -c "import json;print(json.load(open('$HOME/.claude/ela/site.json'))['env'])")
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py"  --env-file "$ENV" jql 'project = MH ORDER BY updated DESC' --limit 1
python3 "${CLAUDE_PLUGIN_ROOT}/skills/kb/kb.py"          --env-file "$ENV" search "MediaHub" 2>&1 | head -3
python3 "${CLAUDE_PLUGIN_ROOT}/skills/figma/figma.py" --env-file "$ENV" me
python3 "${CLAUDE_PLUGIN_ROOT}/skills/slack/slack.py" --env-file "$ENV" whoami            # auth + JIRA_EMAIL → user id
python3 "${CLAUDE_PLUGIN_ROOT}/skills/graph/graph.py" --env-file "$ENV" graphs --pages 1 --limit 1     # UR key (graphs of `me` from site.json emails); or: ela graphs
python3 "${CLAUDE_PLUGIN_ROOT}/skills/release/release.py" --env-file "$ENV" envs           # userservice SID; or: ela versions
python3 "${CLAUDE_PLUGIN_ROOT}/skills/release/release.py" --env-file "$ENV" builds mediahub-backend --limit 1   # Jenkins; or: ela builds mediahub-backend
python3 "${CLAUDE_PLUGIN_ROOT}/skills/confluence/confluence.py" --env-file "$ENV" spaces | head -3      # Confluence PAT; or: ela wiki spaces
python3 "${CLAUDE_PLUGIN_ROOT}/skills/gdoc/gdoc.py" --env-file "$ENV" list --limit 3                     # Google token refresh + Drive; or: ela gdoc list
# object: python3 "${CLAUDE_PLUGIN_ROOT}/skills/object/object.py" --env-file "$ENV" get <known id> — the only read; see skills/object/SKILL.md
```

Report a table: sense · key(s) present · probe result (`ok` / `auth failed` / `unreachable`).
Anything not `ok` → point back to §2 for that key. Stop there; do not retry with guessed values.

## 4. Done when
Every sense probes `ok` (optional keys may be absent — say which), `site.json` paths all resolve, `.env` is mode 600. Say so in one line.
