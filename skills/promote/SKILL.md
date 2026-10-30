---
name: promote
description: Assess promoting a MediaHub release line between lanes; every post and backfill is a dry-run first. Use for "promote QA to daily", "把 QA 推到 daily", "daily 上 prod 前看一下", "这次 promotion 有什么风险", "QA 比 daily 多了什么", or before a deploy request to Test2 / Prod.
user-invocable: true
---

# /ela:promote <line> <from> <to> — what moves, what QA said about it, what nobody has checked

Self-contained. The script collects and reconciles; this file is the judgement and the invariants.

```bash
P="python3 ${CLAUDE_PLUGIN_ROOT}/skills/promote/promote.py --env-file <env>"      # or: ela promote 2.1 qa daily …
$P report 2.1 qa daily --purpose prod-staging --bundles --out <runtime>/promote   # everything, ranked; JSON + markdown
$P report 2.1 qa prod --purpose prod-deploy --out <runtime>/promote                # the deploy gate: four fixed sections
$P lanes|commits|tickets|evidence|bundles 2.1 qa daily                            # one step at a time when arguing with a finding
$P constraints [--json]                                                            # the standing constraints, each pin read now; exit 3 when one is over
$P close                                                                           # the pending promotion shipped or was dropped
# Progress goes to stderr one line per step (--quiet to silence); the JSON contract is what the session reads.
```
`<line>` is a key of `<elak>/map/release.yaml lines`; `<from>`/`<to>` are lane roles (qa · daily · prod) or lane
names. Exit 3 means a lane could not be read — for daily/stage/prod that is the person's TVU session: tell Evan
to type `! ela login tvu` and stop; never read a cache or another system's file instead.

## Invariants
- **Every source is checked against another.** A commit's ticket is the key in its subject (the body's key only
  when the subject has none; a body-cited key is a reference, not a carried ticket). A ticket's Fixed In is
  checked against the build that actually carries its commits. A ticket's status is never taken as evidence.
  Dev-declared ("deployed to QA", "fixed in build …") is **not verified**. QA's N/A is a conclusion, not a gap.
- **QA's own words decide.** The verdict is the latest QA statement about that key — a Jira comment by a QA
  person, a result line or the close/reopened list in a QA report mail, a QA Slack message — quoted with source
  and date. Never re-derive a pass rate; never infer a pass from silence.
- **The to-lane is read live or declared unreadable.** Any lane ahead of the target (prod ahead of daily) is
  reported; a target lane ahead of the source stops the promotion until explained.
- **Facts here, decisions there.** The post this skill produces is step 1 of the promotion thread (elak `blueprint/decisions/2026-09-04-promotion-thread-three-steps.md`): title = the object, body =
  versions, changes **grouped by change** with the services carrying each and its QA state, *Open points* as
  questions, mentioning only Evan. No verdict, no "known issue", nothing attributed to Evan before he writes it
  in the thread. Executors are mentioned by him, afterwards.
- **Standing constraints bind every promotion.** `<elak>/blueprint/constraints.yaml` holds the owner's rulings a
  promotion must honour: a pin (a service kept at or below a version on a lane), a check done by hand on a lane,
  each with its `until`, the condition that lifts it and its source note. `report` reads it on every run: a
  source version over a pin on the target lane is a **stop** (`constraint_pin`), each hand check on the target
  lane a **high** open point (`constraint_check`), and the lift condition a note (`constraint_lift`). A stop is
  lifted only by the owner — through the source note's `ela:` line, the expiry, or a confirmed edit of the entry —
  never by rewording the finding. An expired constraint is listed for seven days, then dropped. The file is
  written only when the owner confirms the proposing note; this skill never writes it. A missing file is no
  constraints.
- **A report written with `--out` opens the pending promotion.** `<reports>/promote/pending.json` records the line,
  the lanes, the report's path and the candidate: the source lane's version per service. The next run for the same
  line and lanes refreshes it; a cell the owner still has to choose is written there as `{"awaiting": "owner",
  "options": [...], "why": "..."}` and kept until he rules. The morning shows the candidate as the next train in
  `ela matrix` and each awaiting cell as a decision for him; `close` ends it when the promotion shipped or was dropped.
- **Rank and cap.** Evan reads at most twelve findings; the rest are counted. A noisy report is an unread one.
- **Read-only until his word.** Posting (`slack post --apply`), Jira backfills (`jira label|comment … --apply`)
  and the record in elak each wait for an explicit yes, one per action.

## Purpose sets the bar
| purpose | what becomes an open point |
|---|---|
| `prod-staging` — the to-lane is where prod is rehearsed (default when a ticket in the delta is wanted on prod) | every carried ticket without a QA pass or N/A; every ticketless feat/fix/refactor; every cross-service path with a docker pin that differs between lanes; a Fixed In that names a build outside the delta |
| `prod-deploy` — the gate run before an actual deployment; implies the bundle diff and the untracked-deliverable sweep | everything `prod-staging` opens, and the output is the four fixed sections: what really changes · what QA verified · what nobody verified · the risk, with the bars the gate does not itself check named as unchecked |
| `regular` | the same, but single-service UI fixes with a dev declaration are notes; hygiene is notes |
| `demo` | versions and what is visibly new; every risk is a note, nothing blocks |
| to-lane is `prod` | `prod-staging` plus: the daily thread's open points must be closed in that thread; the bundle diff is mandatory (`--bundles`); the PM's approval mail is located (`mail search`) |

## 1 — run, then read the findings with the map in hand
For each high/medium finding, say what a failure would touch: `<elak>/map/services.yaml` (which image serves
which process type, who owns it), `<elak>/map/release.yaml trains` (concurrent lines where numbers lie), and
the reach of the changed service itself, derived from the code rather than asserted:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/map/deps.py" callers <service>   # every app-layer caller, with the endpoints
python3 "${CLAUDE_PLUGIN_ROOT}/skills/map/deps.py" check               # the scan's commit vs. the repos now
```

`callers` is the app layer only and is stamped at a commit — run `check` first, because a stale graph
understates reach, which is the one direction that matters here. For the path that leaves the app
layer (orchestration → J2N → docker), `<published>/knowledge/products/mediahub/services/dependency-map.md` is the
hand-written complement the scan does not cover; cite whichever you used.
A switch-path change in `unified-streaming` reaches orchestration → J2N → LiveTransmit → the transmitter docker;
a Billing callback change reaches warning-service and Home; a tags change spans backend, mx-service and frontend.
That reach, plus the lane's docker pin, is the risk sentence — not the commit count.

## 2 — output, in this order
1. **The summary for Evan** — in the session's language (English unless he asked for Chinese); the lane table, then the ranked findings (≤12), each with the reach and the evidence
   source; then what could not be read. He decides here; this text is not posted. With `--purpose prod-deploy`
   the summary is already in the four-section order and is read as written; the Slack body and the backfills are
   unchanged. The summary is also written as a review page to `<reports>/ela/<date>-promote-<line>-<from>-to-<to>.md`,
   with a title heading, an *In short* paragraph and a closing *What waits for your word*, and with outputs 2 to 4
   quoted beneath it. The vault sync carries it into `readings/`, where he reviews it on his own machine (elak decision
   2026-10-23, the owner reads ela in a generated Obsidian vault). Terminal text and runtime files are not readable
   there. The page stays within the vault's review budget of 2,500 words and holds no machine paths; the raw report
   is not copied, because its commit lists would fail that gate. A rerun for the same line and lanes on the same
   day rewrites the page.
   A decision the page touches (a standing constraint, a hold, a plan already in the vault) is linked, never
   restated: one decision, one note; the page says what changed since that note and when it read the bundles.
2. **The Slack body** — English, in Slack mrkdwn (the slack skill's rules), written to
   `<runtime>/promote/<date>-<line>-<from>-<to>.post.md`, then `slack post <target> --file …` as a **dry run** and
   `--preview` (DM'd to Evan) before any send. Title first (`[MH <line>] <from> → <to> promotion — <scope>`), body
   into the thread; two sends, two confirms. When Evan has already posted the title, the body is the reply in his
   thread. The body is a fixed layout, at most about forty lines; the review page holds the detail:
   - *Versions* — one ``` block, a padded column per lane and per candidate build, a row per service.
   - *<candidate build> — QA results* — one line per ticket: marker · key link · a few words · QA's verdict and date.
     *New bugs from that round* under it, one line each, with severity.
   - *Carried along from <earlier builds>* — what the target lane also gains: the unverified tickets one per line,
     the verified ones as a single ✅ line of keys, ticketless commits as one counted line.
   - *<next build> — not yet tested* — one line of keys, when a newer build is on the from-lane.
   - *Open points* — numbered questions, one line each.
   No verdict, and no decision of Evan's, even one he has stated in the session: he writes it in the thread.
3. **The QA list** — one line per ticket in the delta whose QA state is not verified (dev-declared, none, not
   scheduled): key · what changed in the reporter's words · the lane and build to test on. Written in English,
   ready to paste to the QA lead under the owner's name; it is the answer to "what does QA still need to test"
   (2026-10-21) and is not posted by this skill.
4. **Jira backfills as dry runs** — `jira label <key> --add release:mh-<line>`, a `jira comment` proposing the
   Fixed In value with its evidence — never `--apply` without his word per key.
5. **What is kept** — the facts belong to the promotion thread, which is where they were posted and where
   the decisions follow them; do not write a second copy. Into `<elak>/blueprint/` goes only what the run
   established about **ela** — a parity result, a capability that now holds — with the thread permalink.
   The review page in `<reports>` is his reading copy, not a record. The report markdown and JSON stay in `<runtime>` and are disposable (elak `blueprint/principles.md` P1); the JSON also carries quoted words, and a tracked file names the
   origin, never the utterance).

## 3 — after the thread
When he has replied with the decisions and deploy has happened, `report` again with the same arguments: the
to-lane must now equal the old from-lane for every service, or the difference is the next finding.
