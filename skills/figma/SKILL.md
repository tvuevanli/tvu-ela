---
name: figma
description: Read a Figma design first-hand. Use for a figma.com link (file/design/proto), what a design or frame says, design comments, a node screenshot, "看下这个设计", "figma 上怎么画的", "design spec", "设计负责人的稿".
---

# Figma — read a design first-hand

The capability is `figma.py` — an L1 atomic CLI (read-only by design: every call is a GET).
This file is the Claude-session adapter; other callers invoke the same script.

```bash
ela figma file <url>          # pages + frames tree
ela figma node <url>          # node-id= in the URL is honoured
ela figma comments <url>
ela figma image <url> --out <dir>   # then Read the png
```

- Accepts full figma.com URLs (`file/design/board/proto`); `node-id=12-34` means node `12:34`.
  A bare file key works everywhere a URL does.
- `file` fetches depth 2 by default (pages + top frames) — a whole file can be enormous; go deeper
  with `--depth`, or target one frame with `node`.
- `node` prints the subtree **and every text layer's content** — usually the fastest way to read a
  spec/annotation frame without rendering.
- `image` prints the rendered URL, or downloads with `--out` (png/jpg/svg/pdf, `--scale`). To *see*
  the design, download and `Read` the file.
- `--json` on file/node/comments for machine callers. Exit codes 0/1/2.

## Scope

Read-only by design — it cannot post comments, edit, or move anything. Writing to Figma is a
separate, outward-facing action and must not be added to this skill silently.

## Credentials

The env file is the one `~/.claude/ela/site.json` → `env` names, found automatically; no `--env-file`. It must hold
`FIGMA_TOKEN` (a personal access token). Missing or 403 → run `/ela:setup`
(token: Figma → Settings → Security → Personal access tokens; read scope is enough).
