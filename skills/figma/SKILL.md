---
name: figma
description: Read a Figma design first-hand — file structure (pages/frames), one node's subtree and text content, comments, or a rendered image of a node. Use when the user pastes a figma.com link (file/design/proto), asks what a design or a frame says, wants design comments, or needs a screenshot of a Figma node. Also trigger for "看下这个设计", "figma 上怎么画的", "design spec", "Lora 的设计".
---

# Figma — read a design first-hand

The capability is `figma.py` — an L1 atomic CLI (read-only by design: every call is a GET).
This file is the Claude-session adapter; other callers invoke the same script.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/figma/figma.py" --env-file <env> file <url>          # pages + frames tree
python3 "${CLAUDE_PLUGIN_ROOT}/skills/figma/figma.py" --env-file <env> node <url>          # node-id= in the URL is honoured
python3 "${CLAUDE_PLUGIN_ROOT}/skills/figma/figma.py" --env-file <env> comments <url>
python3 "${CLAUDE_PLUGIN_ROOT}/skills/figma/figma.py" --env-file <env> image <url> --out <dir>   # then Read the png
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

Read `~/.claude/ela/site.json` → `env` and pass it as `--env-file`. The script reads only
`FIGMA_TOKEN` from it (a personal access token). Missing or 403 → run `/ela:setup`
(token: Figma → Settings → Security → Personal access tokens; read scope is enough).
