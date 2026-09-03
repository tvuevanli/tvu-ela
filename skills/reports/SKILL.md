---
name: reports
description: Regenerate and republish Evan's standing reports — ela target and status, Helm vs ela, and any comparison or assessment he wants to keep reading — as private claude.ai artifacts with stable URLs, from markdown sources in <projects>/reports. Use on "更新 status report", "ela 现状", "帮我出一份 … 的对比报告", "刷新 report", or when a phase, decision or capability changed enough that the reports lie.
user-invocable: true
---

# /ela:reports — the reading surface, regenerated at will

Self-contained. Sources: `<reports>/<name>.md` (site.json `reports`, default `<projects>/reports`), one
markdown file per report with front matter `title · as_of · sources`. `reports.py build` renders them to
`<reports>/out/<name>.html`; this skill then publishes with the Artifact tool. `<reports>/README.md` is
the index: name · title · URL · as of.

```bash
R="python3 ${CLAUDE_PLUGIN_ROOT}/skills/reports/reports.py"      # or: ela reports …
$R list                       # every report, its as-of date and URL
$R build [name…]              # markdown → HTML (all when no name)
```

## The scheme
1. **Read first-hand before writing.** A status report is rebuilt from `ROADMAP.md`, `plugin.json`,
   `bin/ela`, `elak/blueprint/status.md` and the decisions — not from memory of the last version.
   A comparison report reads both sides' files (for Helm: `CLAUDE.md`, `.claude/skills`, `.claude/agents`, `docs/`).
2. **Rewrite the markdown**, set `as_of` to today, keep the section shape so the reader finds things
   where they were. Diagrams are ```mermaid fences — the artifact renders them natively. Prefer a table
   or a diagram to a paragraph wherever the content is parallel or structural.
3. **Build, then publish to the same URL.** Load the `artifact-design` skill before publishing. In the
   conversation that created the artifact, republish `out/<name>.html`; from any other conversation pass
   the URL from `README.md` as `url` (read it first with `action: read`). Never publish a new URL for an
   existing report; a new report gets a new file, a new URL, and a row in `README.md`.
4. **Tell Evan the URL and what changed** in three lines. The report is the deliverable, not the chat.

## Invariants
- **Not knowledge.** Reports point at decisions and status; they never become the place a fact lives.
  Anything a report states that is not in ela, elak or a first-hand source is a bug in the report.
- **Stable URLs, moving dates.** One URL per report for life; `as_of` moves; the artifact version label
  is the date.
- **Private by default.** Artifacts are private; Evan shares from the page when he wants to.
- **Roots by name, no addresses, no credentials** — the same rule as every tracked file, because a
  report may be shared onward.

## Standing reports
| name | what it answers |
|---|---|
| `ela-status` | where ela stands against its target: tracks vs exits, the command today, what waits on Evan, what is next |
| `helm-and-ela` | why both exist, who develops Helm, the remote, skill-by-skill overlaps, the hand-over plan |

Add a report when Evan asks the same question a second time.
