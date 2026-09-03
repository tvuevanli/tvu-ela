---
name: gdoc
description: Read Google Docs, Sheets and Drive listings first-hand with Evan's read-only token — a doc as text, a sheet tab as CSV, recent documents by name/full text. Use for a docs.google.com link pasted in chat, "那个 sheet 里", "Louis 的 service summary", "repo owner map".
user-invocable: true
---

# /ela:gdoc — Google Docs / Sheets, read-only

Self-contained. `gdoc.py` is the capability; `ela gdoc …` or a bare `ela <docs.google.com url>` at the shell.

```bash
G="python3 ${CLAUDE_PLUGIN_ROOT}/skills/gdoc/gdoc.py --env-file <env>"   # or: ela gdoc …
$G list [text] [--limit N]     # docs + sheets the account can see, newest first (Drive)
$G read <url|id>               # a Doc as text — headings, bullets, tables as rows
$G sheet <url|id> [--gid N]    # a Sheet tab as CSV (the gid in the URL is honoured)
$G info <url|id>               # owner, modified, type
```

## Invariants
- **Read-only, enforced twice.** The token's granted scopes must be a subset of the read-only allowlist
  in the script, and each command asserts the scope it needs. No write scope is ever added.
- **The token is shared with Helm** — the same Google OAuth grant, copied once into ela's site dir
  (`GOOGLE_TOKEN_FILE` in `.env`). Re-authorising is Evan's hand, out of band; the script never
  rewrites the file.
- **Cite, never copy.** A sheet read for a fact is cited by URL and date; elak keeps the pointer.
- **Sheets are living documents** — quote the date read; a number is only as current as `info` says.
