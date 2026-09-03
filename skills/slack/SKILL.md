---
name: slack
description: Slack capability — a thread by permalink, the channels the bot can see, a channel's recent history, threads that mention Evan and whether he answered, threads he started that nobody answered; and one write, post (dry run until --apply). Use when the user pastes a Slack link (tvunetworks.slack.com/archives/...), asks what a thread says, asks "who is waiting on me in Slack", "最近谁 @ 我了", "这个频道昨天说了什么", or asks to send a message or reply in a thread ("回一下这个 thread", "发到 prj_dev_mediahub").
user-invocable: true
---

# Slack — a sense that reads first-hand, plus one write

```bash
SLACK="python3 ${CLAUDE_PLUGIN_ROOT}/skills/slack/slack.py --env-file <env>"
$SLACK read <permalink>                 # root message and every reply, real names resolved
$SLACK channels                         # channels the bot is a member of — DMs are never visible
$SLACK history <channel> --since 24h    # top-level messages; --threads adds replies; channel = id or #name
$SLACK mentions --since 48h --channels '#prj_dev_mediahub,#dev-unified-resources,#boundary-agent-integration'   # who mentioned Evan; answered = he replied after the last mention
$SLACK unanswered --since 7d --channels '#prj_dev_mediahub'       # threads Evan started that nobody else replied to
$SLACK whoami                           # Evan's user id, from JIRA_EMAIL in the env file
$SLACK post <permalink> --file reply.md            # DRY RUN: shows where, as whom, and the text; nothing is sent
$SLACK post <permalink> --file reply.md --apply    # sends — only after Evan has read the dry run and said so
$SLACK post '#prj_dev_mediahub' --text "…"         # top level in a channel; --dm me|email|Uxxx for a direct message
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

Reads — `conversations.replies`, `conversations.info`, `conversations.history`, `users.conversations`,
`users.info`, `users.lookupByEmail`. One write — `chat.postMessage` via `post`. No edit, no delete, no
reaction; none is to be added silently.

## Posting — the rules (decision `2026-09-02-slack-voice-policy`, added 2026-09-03)

- **Dry run first, always.** Show Evan the dry-run output (target, identity, full text). `--apply` is sent
  only after his word in this conversation, once per message. Never batch several `--apply` behind one yes.
- **The bot speaks as itself** (today `@helm`; Ella once renamed), never as Evan. Write in the third person
  about him ("Evan's position, recorded on … is …"), cite the source of every claim (a Jira key, a
  decision file, a doc URL), and answer in the asker's language.
- **Reply in the thread** where the question lives (pass the permalink); a top-level post needs a reason
  Evan stated. A DM to anyone other than Evan needs him to name the person.
- **Idempotent by content.** The script refuses a message identical to one the bot already posted in the
  last 20 of that thread or channel — a rerun cannot double-post.
- **Nothing unsettled goes out as fact.** If a claim is not on record, the message says so and offers to
  relay; drafting the question back to Evan is the right move, not guessing.

## Turning a thread into knowledge

A Slack thread is a dated conversation; a knowledge base holds what is currently
true. Do not paste transcripts into the knowledge base. Extract the durable
claim, state it as fact, record source + date + author, and mark anything still
unsettled as open. The conventions are those of `<records>/knowledge/`.
