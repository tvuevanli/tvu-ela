---
name: reports
description: Republish the owner's standing reports as claude.ai artifacts at stable URLs. Use on "更新 status report", "ela 现状", "帮我出一份 … 的对比报告", "刷新 report", or when a change makes the reports lie.
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

## Read in the owner's vault

Everything written for the owner reaches him through his Obsidian vault (`ela vault sync`, `skills/vault/vault.py`), and
the sync marks a note a person should not have to read: no title heading, over its reading budget, more than a
quarter code, or machine paths and raw records in the text. Such a note carries a warning under its title and is
listed on the vault's Home for 30 days as a rewrite this skill owes. Budgets, in English words (two CJK characters count as one): day page 1,200 · review
2,500 · decision 1,200 · plan 2,500 · sprint 800. Write to fit: the conclusion first, one idea per sentence,
numbers in a short table, file paths and code only where he must act on them, the full record linked, not
pasted.

A report in the reports root is a reading: the sync puts it in the vault's `readings/`, with no status and no
moves, and the morning item or the ticket it serves links it. A plan or proposal that waits for his ruling is an
elak decision or plan with `reader: owner` and `status: proposed`, which the sync carries into `to-read/` until
the status changes. A mermaid timeline's
periods carry no colon (`6.30 am`, not `06:30`): the colon separates a period from its event.

Where the owner drags a note states his intent: `archive/` (keep it) or the bin. What is worth keeping as
knowledge goes to elak, proposed as a decision note in `to-read/` and written on his word.

## What a report is now

- **ela's own design and abilities are not a report.** They live in the owner's vault (`ela/overview.md`, its source since 2026-10-23), which the owner
  reads there and which changes in the same pass as ela; no claude.ai report about ela is published or
  republished (decided 2026-10-23).
- **A review is written as a Claude doc** (shareable, commentable) when colleagues may read it. What it decides is
  recorded in elak (a decision, a rule, a knowledge entry), and what the owner must act on reaches his vault; the doc
  stays as the reference, linked from the library.
- Standing reports for colleagues (release comparisons, product analyses) remain artifacts or docs as before.

## The library's list

A report published or republished as a claude.ai artifact is added to `<reports>/library/artifacts.json` (title,
url, updated, and its group: `product`, `ela` or `verify`), so the owner's vault library links it the next morning.
An artifact that a newer one replaces keeps its row with "(earlier version)" in the title.

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
| `evan-work-system` | the top-level design: Evan's situations and problems, who does what through ela and Helm, the clock, responsibilities, the landing order |

Add a report when Evan asks the same question a second time.
