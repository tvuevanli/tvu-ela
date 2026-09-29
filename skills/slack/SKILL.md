---
name: slack
description: Slack read first-hand, plus one write, post (dry run until --apply). Use for a Slack link (tvunetworks.slack.com/archives/...), what a thread says, sending or replying, "who is waiting on me in Slack", "最近谁 @ 我了", "这个频道昨天说了什么", "回一下这个 thread", "发到 prj_dev_mediahub".
user-invocable: true
---

# Slack — a sense that reads first-hand, plus one write

`SLACK="python3 ${CLAUDE_PLUGIN_ROOT}/skills/slack/slack.py --env-file <env>"`; `$SLACK --help` lists the
verbs and their flags. `mentions` counts a mention answered when Evan replied after the last one;
`users` walks the whole workspace, Slack Connect guests included, and takes about a minute.

Every subcommand takes `--json`. `--since` is `48h`, `7d` or `YYYY-MM-DD`. Exit codes: 0 ok · 2 usage ·
4 auth · 5 remote error. Scans cost one call per thread active in the window, so `--channels` makes a
run cheaper — but it is no longer what keeps one alive: a channel that will not come down whole is
named in `unread_channels` and the rest are still reported.

## Credentials

Read `~/.claude/ela/site.json` → `env` (the path of ela's credential file, mode 600) and pass it as
`--env-file`. That file is ela's own — copied once from wherever the tokens lived before; nothing
here depends on another tool's config. The script reads `SLACK_BOT_TOKEN` from it, and `JIRA_EMAIL` for
`whoami` and the default `--user me` of `mentions` / `unanswered`. Missing or expired → run `/ela:setup`.

## Scope

Reads — `conversations.replies`, `conversations.info`, `conversations.history`, `users.conversations`,
`users.info`, `users.lookupByEmail`, `users.list`. One write — `chat.postMessage` via `post`. No edit, no delete, no
reaction; none is to be added silently.

## Posting — the rules (elak `blueprint/principles.md` P7)

- **Dry run first, always.** Show Evan the dry-run output (target, identity, full text). `--apply` is sent
  only after his word in this conversation, once per message. Never batch several `--apply` behind one yes.
- **The bot speaks as itself** (`@helm` until renamed Ella), never as Evan. Write in the third person
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
unsettled as open. The conventions are those of `<elak>/knowledge/`.

## Gotchas

- **Reach** (`channels`, `join`). The bot is in a small fraction of the workspace's public channels, and
  DMs are never visible. `channels --all <word>` finds the rest — several customers in the open
  incident pile have their own channel — and `join` is Evan's call, never automatic, because the
  channel sees it. A `channel_not_found` says which case it is: public and unjoined (with the join
  command), or private (a member must invite the bot).
- **A filename is not evidence** (`read`, `files`). `read` lists files with ids; download them with
  `files <permalink> [--thread]` — a screenshot is evidence, a filename is not.
- **Response size** (every listing). A large body truncates on this link, so pages back off to a smaller
  size at the same cursor. If a listing still fails, that is reported, not swallowed.
- **A narrowed scan is a partial read** (`mentions`, `unanswered`, `--channels`). Whatever `--channels`
  excludes, and every channel named in `unread_channels`, was not read; any answer built on the run
  must say so.
