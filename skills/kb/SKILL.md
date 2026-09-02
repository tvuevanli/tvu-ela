---
name: kb
description: Read and write documents in the TVU knowledge base at kb.tvunetworks.com (Outline). Use when the user pastes a kb.tvunetworks.com link, asks what a KB doc says, wants to search the wiki, or wants to record something in the knowledge base. Also trigger for "check the KB", "search the wiki", "write this up in the KB", "add a runbook", "看看 KB", "写到知识库".
---

# TVU knowledge base (Outline) — read and write

```bash
KB="python3 ${CLAUDE_PLUGIN_ROOT}/skills/kb/kb.py --env-file <env>"   # <env> from ~/.claude/ela/site.json
```

Documents are plain markdown in and out. A document is addressed by full URL,
by its `urlId` slug (`design-audio-remapping-0aa0ItyDui`), or by UUID —
all three work anywhere a `<doc>` is taken.

## Reading

```bash
$KB tree                                 # collections + permissions
$KB tree 'MediaHub & UR'                 # that collection's document tree
$KB search 'srt listener' --limit 10     # full-text; --collection to narrow
$KB read <doc>                           # metadata header + markdown body
$KB read <doc> --children                # also print every child document
```

`tree` first when you don't know the layout — collection names are matched by
exact name or unique prefix, so `--collection MediaHub` resolves `MediaHub & UR`.
Search hits print a snippet; read the doc before relying on it.

## Writing

```bash
$KB write '<title>' --collection 'Engineering' --file draft.md          # dry-run: prints what would be created
$KB write '<title>' --parent <doc> --file draft.md --apply              # nest under a doc — the real write
$KB update <doc> --file new.md [--apply]                                # replace the body
$KB update <doc> --append --file addition.md [--apply]                  # append to the body
$KB update <doc> --title '<new title>' [--apply]
$KB delete <doc> [--apply]                                              # to trash, restorable
```

**Dry-run is the default.** `write`, `update` and `delete` print exactly what would change — title,
target collection or parent, body — and do nothing without `--apply`. Body comes from `--file <path>`,
`--file -` (stdin), or `--text '<markdown>'` — one of those is required; there is no implicit stdin,
so a call that passes no body can never blank a document. Other flags: `--icon <emoji>`, `--draft`
(create unpublished), `--publish` (publish a draft).

### Rules for writing

This is a shared company wiki — every write is outward-facing.

- **Evan's word precedes `--apply`.** Run the command without `--apply` first — the
  dry-run prints the title, the target collection or parent, and the body — show it,
  and only after his explicit go-ahead re-run the same command with `--apply`. One
  confirm covers the one call it was shown for. Don't create or edit a doc as a side
  effect of some other task.
- **Draft first when unsure.** `--draft` creates an unpublished document visible
  only to you; `--publish` releases it once the user approves. A draft cannot be
  a `--parent` (Outline returns 403) — publish it first.
- **`update` without `--append` replaces the whole body.** Read the doc first,
  and prefer `--append` for additions. On someone else's document, say what you
  changed; revisions are kept but nobody diffs a wiki.
- **Don't paste sources verbatim.** A Jira ticket or Slack thread is a dated
  record of intent; the KB holds what is currently true. Extract the durable
  claim, state it as fact, record source + date + author, mark what's unsettled
  as open. Match the surrounding docs' conventions — the `[DESIGN]` /
  `[EXPLAINER]` title prefixes and the runbook date suffixes are house style.
- Collections show `read` or `read_write` in `tree`; writing to a `read`
  collection fails with 403.

## Credentials

Read `~/.claude/ela/site.json` → `env` (the path of ela's credential file, mode 600) and pass it as
`--env-file`. That file is ela's own — copied once from wherever the tokens lived before; nothing
here depends on another tool's config. The script reads only `OUTLINE_URL / OUTLINE_TOKEN` from it. Missing or expired
→ run `/ela:setup`.

## Scope

Documents and collections only, via the Outline API (`documents.search|info|
list|create|update|delete`, `collections.list|documents`). It does not touch
users, groups, permissions, shares, or collection creation — those are
administrative and must not be added here silently. `delete` moves to trash
(restorable); there is no permanent-delete path on purpose.
