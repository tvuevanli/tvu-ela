---
paths:
  - "skills/**"
  - "bin/**"
  - "hooks/**"
  - "agents/**"
---
# Layers: how a capability is built

Edit-time guidance, loaded when a file under these paths is read. The gates a session needs before its first
command (dry run, confirm, worktree, commit rules) are in the root `CLAUDE.md`, not here.

| layer | form | holds |
|---|---|---|
| L0 site | `~/.claude/ela/` | machine paths, credentials |
| L1 atomic | `skills/<name>/<name>.py`, subcommands, `--json`, exit codes, stdlib only | deterministic work: read, search, dry-run writes |
| L2 composite | a `SKILL.md` a session follows | judgment over L1; never a raw API call |
| L3 adapter | `bin/ela` (one word, flat verbs, an id by shape) · a `SKILL.md` · an MCP server when the first external consumer exists · a caller's subprocess | translation only, no business logic |

- An L1 script is stdlib only, takes subcommands, answers `--help` and `--json`, and speaks through exit codes.
- Safety gates live in L1: closed vocabularies, idempotency, dry run by default, `--apply` explicit. Confirm gates
  live in the adapter.
- A `SKILL.md` is documentation for a session, never the capability. A capability does not need a skill; a skill
  exists only where judgment or invariants are needed to use it well.
- Where a capability helps the owner, ela builds it even if Helm has one; Helm's copy then carries a retirement
  condition (ADR 0005).
- A skill's description is loaded into every session: `tests/test_description_budget.py` holds its budget.
