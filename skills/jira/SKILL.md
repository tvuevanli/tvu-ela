---
name: jira
description: Read a Jira issue (description, links, subtasks, comments) or run a JQL search, read-only. Use when the user pastes a Jira URL (tvunetworks.atlassian.net/browse/...), names a ticket key (MH-1234, FB-9693), or asks what a ticket says. Also trigger for "read this ticket", "what's in MH-xxxx", "看看这个 ticket", "查一下 jira".
---

# Read a Jira issue by key or URL

```bash
python3 "\${CLAUDE_PLUGIN_ROOT}/skills/jira/jiraread.py" <key-or-url>
```

Prints identity (type/status/priority/assignee/reporter/dates/labels/components/
parent), the description rendered from ADF, issue links, subtasks, attachments,
and every comment.

Options:

- `--deep` — after the issue, also print each linked issue, subtask, and parent.
  Use when the user asks about "related tickets".
- `--no-comments` — identity + description only; good for bulk reads.
- `--jql '<JQL>'` — search instead of reading one issue; prints key / status /
  assignee / summary rows. `--limit N` (default 50).

## Credentials

Read `~/.claude/ela/site.json` → `env` (the path of ela's credential file, mode 600) and pass it as
`--env-file`. That file is ela's own — copied once from wherever the tokens lived before; nothing
here depends on another tool's config. The script reads only `JIRA_BASE_URL / JIRA_EMAIL / JIRA_TOKEN` from it. Missing or expired
→ run `/ela:setup`.

## Scope

Read-only by design — `GET /rest/api/3/issue/{key}`, `.../comment`, and
`/rest/api/3/search/jql`. It cannot create, transition, comment, or edit.
Writing to Jira is a separate, outward-facing action and must not be added to
this skill silently.

## Turning a ticket into knowledge

A ticket is a dated record of intent; a knowledge base holds what is currently
true. Do not paste ticket bodies into the knowledge base. Extract the durable
claim, state it as fact, record source (ticket key) + date + author, and mark
anything still unsettled as open. See the MediaHub knowledge base README,
"How to extend". Note that MH ticket descriptions are often bilingual
(中文 then English) — the two halves are the same content, do not treat them
as two sources.
