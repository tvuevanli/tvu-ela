---
name: slack
description: Slack capability, read-only — a thread by permalink, the channels the bot can see, a channel's recent history, threads that mention Evan and whether he answered, threads he started that nobody answered. Use when the user pastes a Slack link (tvunetworks.slack.com/archives/...), asks what a thread says, or asks "who is waiting on me in Slack", "最近谁 @ 我了", "这个频道昨天说了什么", "看看这条 Slack".
user-invocable: true
---

# Slack — read-only sense

```bash
SLACK="python3 ${CLAUDE_PLUGIN_ROOT}/skills/slack/slack.py --env-file <env>"
$SLACK read <permalink>                 # root message and every reply, real names resolved
$SLACK channels                         # channels the bot is a member of — DMs are never visible
$SLACK history <channel> --since 24h    # top-level messages; --threads adds replies; channel = id or #name
$SLACK mentions --since 48h --channels '#prj_dev_mediahub,#dev-unified-resources,#boundary-agent-integration'   # who mentioned Evan; answered = he replied after the last mention
$SLACK unanswered --since 7d --channels '#prj_dev_mediahub'       # threads Evan started that nobody else replied to
$SLACK whoami                           # Evan's user id, from JIRA_EMAIL in the env file
```

Every subcommand takes `--json`. `--since` is `48h`, `7d` or `YYYY-MM-DD`. Exit codes: 0 ok · 2 usage ·
4 auth · 5 remote error. Scans cost one call per thread that was active in the window, so pass
`--channels` — Evan's own channels — unless he asks for a full sweep (minutes, 13 channels).

## Credentials

Read `~/.claude/ela/site.json` → `env` (the path of ela's credential file, mode 600) and pass it as
`--env-file`. That file is ela's own — copied once from wherever the tokens lived before; nothing
here depends on another tool's config. The script reads `SLACK_BOT_TOKEN` from it, and `JIRA_EMAIL` for
`whoami` and the default `--user me` of `mentions` / `unanswered`. Missing or expired → run `/ela:setup`.

## Scope

Read-only by design — `conversations.replies`, `conversations.info`, `conversations.history`,
`users.conversations`, `users.info`, `users.lookupByEmail`. It cannot post, edit, or react. Posting to Slack is a separate,
outward-facing action and must not be added to this skill silently.

## Turning a thread into knowledge

A Slack thread is a dated conversation; a knowledge base holds what is currently
true. Do not paste transcripts into the knowledge base. Extract the durable
claim, state it as fact, record source + date + author, and mark anything still
unsettled as open. The conventions are those of `<records>/knowledge/`.
