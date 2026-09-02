---
name: jira
description: Jira capability — read an issue (description, links, subtasks, comments), run a JQL search, or write behind an explicit confirm: create an issue or subtask, assign, comment, transition status, add/remove labels, link issues — every write dry-run by default and idempotent. Use when the user pastes a Jira URL (tvunetworks.atlassian.net/browse/...), names a ticket key (MH-1234, FB-9693), asks what a ticket says, or asks to create a subtask under a parent. Also trigger for "read this ticket", "what's in MH-xxxx", "create a subtask", "看看这个 ticket", "查一下 jira", "建子任务".
---

# Jira — read, search, and gated writes

The capability is `jira.py` — an L1 atomic CLI (subcommands, `--json`, exit
codes 0 ok / 1 API error / 2 validation). This file is the Claude-session
adapter; other callers (Helm ops, an MCP server) invoke the same script.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py" --env-file <env> read <key-or-url>
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py" --env-file <env> jql '<JQL>' [--limit N]
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py" --env-file <env> assign <key> --assignee EMAIL|ACCOUNTID [--apply]
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py" --env-file <env> create \
        --summary 'TITLE' [--project MH] [--type Task] [--description TEXT] [--assignee EMAIL|ACCOUNTID] [--apply]
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py" --env-file <env> create-subtask \
        --parent MH-XXXX --summary '[Token] action' [--description TEXT] [--assignee EMAIL|ACCOUNTID] [--apply]
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py" --env-file <env> comment <key> [<key>…] --text '…' | --from-file f [--apply]
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py" --env-file <env> transition <key> [<key>…] --to "In Progress"|Review|Done [--apply]
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py" --env-file <env> label <key> [<key>…] --add a,b --remove c [--apply]
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py" --env-file <env> link <key> <other> --type Relates|Blocks|"is blocked by"|Duplicate|"contains" [--apply]
```

## read

Prints identity (type/status/priority/assignee/reporter/dates/labels/components/
parent), the description rendered from ADF, issue links, subtasks, attachments,
and every comment.

- `--deep` — after the issue, also print each linked issue, subtask, and parent.
  Use when the user asks about "related tickets".
- `--no-comments` — identity + description only; good for bulk reads.
- `--json` — raw fields + comments as one JSON object, for machine callers.

## jql

Key / status / assignee / summary rows. `--limit N` (default 50), `--json`.

## assign — re-assign one issue, gated twice

Idempotent (already-assigned reports and exits 0), dry-run default showing `from -> to`; the
same confirm gate below applies before `--apply`.

## create — parent-level issue, gated twice

Same gates as create-subtask minus the token rule (a parent carries cross-layer scope, so its
title is free-form; single-layer tokens belong on subtasks). Idempotent against open issues in the
project with the same title. **Dry-run default; the confirm gate below applies before `--apply`.**

## create-subtask — gated twice

**Safety gate (in the script, no caller can skip it):**
- the title must start with exactly one of
  `[Infra] [J2N] [Media] [App] [UI] [QA] [Design]` followed by the action —
  no dash separator, no invented tokens;
- idempotent: an existing subtask with the same title is reported
  (`already exists: MH-XXXX`) and nothing is created — safe to retry;
- **dry-run is the default.** Without `--apply` it validates, resolves the
  assignee, and prints what would be created.

**Confirm gate (yours, in this session):** never pass `--apply` until Evan has
seen the dry-run output (or an equivalent listing of parent + title + assignee)
and explicitly confirmed. One confirmation covers the batch it was shown for,
nothing later.

Assignee defaults to the token's own account (Evan). `--assignee` takes an email
— which must match exactly one Jira user or the call fails — or an accountId,
which resolves directly: most users hide their email address, and for them the
accountId (visible in `read --json`) is the only handle that works. Cross-layer
scope belongs on the parent ticket — a subtask carries exactly one token.

## comment · transition · label · link — the field atoms, gated twice

Each takes one or more keys (fan-out is one dry-run, one confirm), prints exactly what would change,
and does nothing without `--apply`. Each is idempotent, so a re-run after a partial failure is safe:

| atom | no-op when | how the write is chosen |
|---|---|---|
| `comment` | a comment with identical text (whitespace-insensitive) already exists on the issue | plain text → ADF paragraphs; `--from-file` for long drafts |
| `transition` | the issue is already in `--to` | the transition whose target status matches `--to` is looked up per issue; none → exit 2 listing what is reachable from the current status |
| `label` | requested labels already present / absent | only the delta is sent (`add` / `remove` ops) |
| `link` | a link of that type already joins the pair in that direction | `--type` is a type name or a phrase (`blocks`, `is blocked by`, `relates to`, `contains`, `is contained in`, `implements`), resolved against the site's link types; the dry-run prints the sentence as Jira will show it |

Confirm rule for a Claude session: show the dry-run, ask Evan, and only then re-run with `--apply` —
the same wording he saw. Never batch a confirm across different texts: one text, one confirm, any
number of keys.

## Credentials

Read `~/.claude/ela/site.json` → `env` (the path of ela's credential file, mode 600) and pass it as
`--env-file`. That file is ela's own — copied once from wherever the tokens lived before; nothing
here depends on another tool's config. The script reads only `JIRA_BASE_URL / JIRA_EMAIL / JIRA_TOKEN` from it. Missing or expired
→ run `/ela:setup`.

## Turning a ticket into knowledge

A ticket is a dated record of intent; a knowledge base holds what is currently
true. Do not paste ticket bodies into the knowledge base. Extract the durable
claim, state it as fact, record source (ticket key) + date + author, and mark
anything still unsettled as open. See the MediaHub knowledge base README,
"How to extend". Note that MH ticket descriptions are often bilingual
(中文 then English) — the two halves are the same content, do not treat them
as two sources.
