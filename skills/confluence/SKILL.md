---
name: confluence
description: Read the web team's Confluence wiki first-hand — spaces, a space's page tree, full-text search, one page as text. Use for "wiki 上有没有", "Confluence 里 MediaHub 那页", "web team 的文档", a Confluence page URL pasted in chat.
user-invocable: true
---

# /ela:confluence — the web team's wiki, read-only

Self-contained. `confluence.py` is the capability; `ela wiki …` at the shell is the same thing.

```bash
W="python3 ${CLAUDE_PLUGIN_ROOT}/skills/confluence/confluence.py --env-file <env>"   # or: ela wiki …
$W spaces                       # 71 spaces as of 2026-09-03 — MH (Media hub), MG (MediaMesh Graph), OS, RTIL, LR, WEB …
$W tree MH                      # a space's pages, indented, with ids and last editor
$W search "SCTE" --space MH     # CQL text search, newest first
$W read 48304779                # one page as text (id, or the page URL)
```

## Invariants
- **Read-only.** No write endpoint exists in the script; none is to be added. The PAT is Evan's own.
- **Cite the page, never paste it into the knowledge base.** A finding cites `<url>` + page id + version
  date; elak keeps at most a pointer and Evan's interpretation (rule: `<records>/knowledge/README.md`).
- **The MH space is the web team's view** (Andy Zhao, Erin Zhang, Louis Qin …): integration notes, QA
  procedures, API/debug pages — engineering facts about MediaHub from their side, dated 2024–2026. Say
  who wrote it and when; a 2024 page may describe MediaHub 1.x.
- **Office network only.** Unreachable from elsewhere; say so instead of retrying.
- Config: `site.json services.confluence.url`, `.env CONFLUENCE_TOKEN` (never in any tracked file).
