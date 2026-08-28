# agents/ — reserved

No agent in Phase 1; the main session runs the skills.

**Admission rule:** an agent is defined only when a skill needs work that is **isolated** (its own
context), **parallel**, or **tool-restricted** (e.g. read-only over product repos). A persona is not
a reason. There is no coordinator agent — coordination is the main session.

| phase | agent | why it must be an agent |
|---|---|---|
| 2 | analyst — reads product repos first-hand, never edits | tool-restricted: `Read Grep Glob Bash`; may hold code-graph tools |
| 5 | reviewer — verifies evidence, never implements | tool-restricted, read-only |
| 5 | implementer per stack, repo-local / bare lanes only | isolated per worktree, tier-scoped |

Names are plain names. Anything an agent needs to know is reached by path from the site file.
