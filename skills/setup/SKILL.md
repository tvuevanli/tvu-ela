---
name: setup
description: First-run and repair of ela's site directory (~/.claude/ela) — machine paths in site.json and credentials in .env — with a read-only probe of every sense. Use on a new machine, when a sense fails to authenticate, when a token was rotated, or on "set up ela", "ela setup", "配置 ela", "token 过期".
user-invocable: true
---

# /ela:setup — make this machine ready for ela

Self-contained. Never prints a secret value; only key names and probe results.

## Invariants
- Everything you write goes under `~/.claude/ela/` only. Never into the plugin, never into a repo.
- `.env` is mode `600`. Show which keys exist, never their values.
- Probes are read-only calls. No probe writes anywhere.

## 1. site.json — machine paths

Target shape:

```json
{
  "projects": "<root that holds the area dirs, e.g. ~/projects>",
  "records":  "<ela-knowledge repo>",
  "map":      "<records>/map",
  "env":      "~/.claude/ela/.env",
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

Procedure: list which keys are present; for each missing one say where to get it and ask Evan to
paste it **into the file himself** or hand it to you for a single `printf >>` — then `chmod 600`.
If a key exists elsewhere on the machine (an older tool's env file), you may copy **that key only**,
once, and say so; ela does not keep reading the other file.

## 3. Probe every sense (read-only)

```bash
ENV=$(python3 -c "import json;print(json.load(open('$HOME/.claude/ela/site.json'))['env'])")
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py"  --env-file "$ENV" jql 'project = MH ORDER BY updated DESC' --limit 1
python3 "${CLAUDE_PLUGIN_ROOT}/skills/kb/kb.py"          --env-file "$ENV" search "MediaHub" 2>&1 | head -3
# slack: needs a permalink to read; probe auth only if one is at hand
# object: GET <TVU_OBJECT_SERVICE_HOST>/route-object/object-service/base/object/<known id> with the bearer — see skills/object/SKILL.md
```

Report a table: sense · key(s) present · probe result (`ok` / `auth failed` / `unreachable`).
Anything not `ok` → point back to §2 for that key. Stop there; do not retry with guessed values.

## 4. Done when
All four senses probe `ok`, `site.json` paths all resolve, `.env` is mode 600. Say so in one line.
