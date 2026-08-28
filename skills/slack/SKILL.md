---
name: slack
description: Read a Slack message and its thread by permalink, read-only. Use when the user pastes a Slack link (tvunetworks.slack.com/archives/...) or asks what a Slack message/thread says. Also trigger for "read this slack", "what does this thread say", "看看这条 Slack".
user-invocable: true
---

# Read a Slack thread by permalink

```bash
python3 "\${CLAUDE_PLUGIN_ROOT}/skills/slack/slackread.py" <permalink>
```

Prints the root message and every threaded reply, with real names resolved.

## Credentials

Read `~/.claude/ela/site.json` → `env` (the path of ela's credential file, mode 600) and pass it as
`--env-file`. That file is ela's own — copied once from wherever the tokens lived before; nothing
here depends on another tool's config. The script reads only `SLACK_BOT_TOKEN` from it. Missing or expired
→ run `/ela:setup`.

## Scope

Read-only by design — `conversations.replies`, `conversations.info`,
`users.info`. It cannot post, edit, or react. Posting to Slack is a separate,
outward-facing action and must not be added to this skill silently.

## Turning a thread into knowledge

A Slack thread is a dated conversation; a knowledge base holds what is currently
true. Do not paste transcripts into the knowledge base. Extract the durable
claim, state it as fact, record source + date + author, and mark anything still
unsettled as open. See the MediaHub knowledge base README, "How to extend".
