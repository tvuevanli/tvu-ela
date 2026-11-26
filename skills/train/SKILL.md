---
name: train
description: One release line as a train — each fix with a cell per lane (QA · daily · prod · CN), verdicts, position, regressions. Use for "where does this fix stand", "2.1 的 train", "什么到了 daily 还没验".
user-invocable: true
---

# /ela:train — one object per release line

`ela train --line 2.1` builds the line's train: one row per fix riding the line's path, with one cell per lane of
the line. The QA test list, the status between lanes and the promotion candidate are views of this object; phase 1
builds the object, its parity check and a preview page (vault
to-read/2026-11-02-the-train-one-object-behind-the-test-list-and-the-lane-status.md).

## The row

| field | meaning | source |
|---|---|---|
| key, or a no-ticket id | the owner ticket a build names (two keys in one Test Focus item are one behaviour, the rest ride as `also`), or `nt-<hash>` for a change-log item with no key, flagged | the lanes' release mails, parsed by the testlist skill (`behaviours`, `owner_of`, `nt_id`) |
| title, layer, owner, status | the ticket's, else the change-log line's; the layer from the components the build names | Jira, read once per key |
| priority, reason | the test list's rules, called: P1 a customer incident, a re-test after a fail, a hotfix; P2 the sprint, Highest/High; P3 the rest; two builds old lifts one | `testlist.priority` |
| how to verify, auto | the Test Focus sentence, else the ticket's acceptance line, else "steps unknown"; auto when visible in the browser UI | testlist |
| cells | `{lane: {arrived, since, verdict, version, source, at, history}}` — the build (QA: its number; daily, prod: the release's version) that carried the fix there and the date; the verdict `pass` · `fail` · `untested` · `incident` · `n/a`, the latest word; `history` every word placed on the lane since the fix first reached the line's path (a report on any build, a word before the lane's own mail named the fix), oldest first, `[{verdict, version, at, source}]` | below |
| position | the furthest of qa → daily → prod with an arrival; `dev` when none. The aligned China prod lane is a fourth cell, never a position | the cells |
| regression | a fail or an incident on daily or prod after a pass on QA; the row is P1 with the reason "regression on <lane> <build>, passed <qa lane> on <build>" | the cells |

**A verdict is per lane.** A QA report mail belongs to the lane its subject names. A reply in the release thread
("MH-1 pass on build 78") belongs to the QA lane. A QA person's ticket comment belongs to the QA lane, unless it
proves another lane where the fix has a record: a pasted version panel whose ENV names it (`promote/envproof.panel`),
or its own words naming it and not the QA lane. A version alone proves no lane. A fail on daily or prod therefore
counts only from a source bound to that lane (its report mail, an incident) or a QA comment proven there; a verdict a
daily or prod test-list state recorded from a comment is not taken. `incident` is an
open customer incident (the brief's incidents lane: sub-tasks of the umbrella) naming the key, raised after the fix
arrived on a prod lane. `n/a` on a lane below the position means the lane's list began after the fix passed through;
it is never a demand on QA.

**Migration.** The per-lane test-list state files (`<reports>/lanes/test-list-<lane>.json`) are read as the source
of each row's first arrival and recorded verdict; the release mails of the window add the mails the state has not
seen. A build is identified by its mail, not its number: a re-sent build is read again and its rows merge with the
first mail's (an older build naming a row first moves the row's arrival back). Below `seed_after` nothing is read;
at it, only a re-send of that build. They retire after a week of parity (the design's condition); until then both are written.

## The verb

- `ela train --line 2.1` prints the preview page; `--json` the train; `--write` keeps it as `<reports>/train/<line>.json`;
  `--page` writes `<reports>/lanes/train-<line>.md`, which `ela vault sync` places at `lanes/train-<line>.md` (type `train`,
  budget 1,200 outside folds).
- `--parity` compares the train's QA view (rows whose QA cell has no pass) with the lane's test-list state: missing
  rows, extra rows, verdicts that differ; exit 0 when equal, 1 otherwise. Run it before anything retires.
- Every build carries a second parity: each key the window's QA report mails (the line's lanes) name has a row, as a
  key or an `also`, or the train names it — `report_keys_missing`, and a line under the gaps.
- Reads only: mail (release and report mails), Jira (the keys, their comments; the incidents lane), Slack (the QA
  release channel's threads), the saved lane reads and the state files. Writes only under `<reports>`. Exit 5 when
  the release mails cannot be read; a source that fails otherwise is a line under "Not read" on the page.

## The page (phase 1 preview)

`Train · <line>`: the counts line (`QA 15 open · 4 P1 · daily 12 arrived, 2 fail · prod 9 arrived, 0 incident`), the
versions row (the brief's matrix cell, ▲ ✓ ◐ ○ as on the lanes page), the rows table — `P · ticket · title · owner ·
<qa> · <daily> · <prod> · <cn> · position`, cells `✓ 78` / `❌ 79` / `· 80` / `—` / `⚠ incident` / `n/a`, regression
rows marked `↩` — folded after eight rows, a folded "No ticket" list, and a footer linking the QA lane's test list and
the lanes page. `render_block` returns the block alone; phase 2 places it in `lanes.md` per line.

## Phase 2 (not built)

`testlist list` and `--today` read the train's QA view; `promote` reads the candidate (QA passed, daily or prod cell
empty) and the blockers (a fail or an incident); `recent` reads the position; the runner calls `ela train --write`
per line before the pages render; the per-lane state retires after a week of parity. The owner's rulings still
open: the regression rule as P1 named in the QA today post, and the prod cell's sources (release checks, incidents,
Sentry; nothing asked of QA).
