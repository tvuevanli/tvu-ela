---
name: promote
description: Assess a promotion of a MediaHub release line between lanes (QA→Daily, Daily→Prod, any purpose) — both lanes' versions read live, every commit between them, every ticket those commits carry, the QA evidence for each from Jira, mail and Slack, the docker bundle diff — reconciled against each other and ranked; then the facts-only Slack post for the promotion thread and the Jira backfills, each behind its own dry-run. Use for "promote QA to daily", "把 QA 推到 daily", "daily 上 prod 前看一下", "这次 promotion 有什么风险", "QA 比 daily 多了什么", or before any deploy request to Test2 / Prod.
user-invocable: true
---

# /ela:promote <line> <from> <to> — what moves, what QA said about it, what nobody has checked

Self-contained. The script collects and reconciles; this file is the judgement and the invariants.

```bash
P="python3 ${CLAUDE_PLUGIN_ROOT}/skills/promote/promote.py --env-file <env>"      # or: ela promote 2.1 qa daily …
$P report 2.1 qa daily --purpose prod-staging --bundles --out <runtime>/promote   # everything, ranked; JSON + markdown
$P lanes|commits|tickets|evidence|bundles 2.1 qa daily                            # one step at a time when arguing with a finding
# Progress goes to stderr one line per step (--quiet to silence); the JSON contract is what the session reads.
```
`<line>` is a key of `<records>/map/release.yaml lines`; `<from>`/`<to>` are lane roles (qa · daily · prod) or lane
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
- **Facts here, decisions there.** The post this skill produces is step 1 of the promotion thread (decision
  `2026-09-04-a-promotion-thread-carries-facts-then-a-decision-then-execution`): title = the object, body =
  versions, changes **grouped by change** with the services carrying each and its QA state, *Open points* as
  questions, mentioning only Evan. No verdict, no "known issue", nothing attributed to Evan before he writes it
  in the thread. Executors are mentioned by him, afterwards.
- **Rank and cap.** Evan reads at most twelve findings; the rest are counted. A noisy report is an unread one.
- **Read-only until his word.** Posting (`slack post --apply`), Jira backfills (`jira label|comment … --apply`)
  and the record in elak each wait for an explicit yes, one per action.

## Purpose sets the bar
| purpose | what becomes an open point |
|---|---|
| `prod-staging` — the to-lane is where prod is rehearsed (default when a ticket in the delta is wanted on prod) | every carried ticket without a QA pass or N/A; every ticketless feat/fix/refactor; every cross-service path with a docker pin that differs between lanes; a Fixed In that names a build outside the delta |
| `regular` | the same, but single-service UI fixes with a dev declaration are notes; hygiene is notes |
| `demo` | versions and what is visibly new; every risk is a note, nothing blocks |
| to-lane is `prod` | `prod-staging` plus: the daily thread's open points must be closed in that thread; the bundle diff is mandatory (`--bundles`); the PM's approval mail is located (`mail search`) |

## 1 — run, then read the findings with the map in hand
For each high/medium finding, say what a failure would touch: `<records>/map/services.yaml` (which image serves
which process type, who owns it), `<records>/map/release.yaml trains` (concurrent lines where numbers lie), and
Helm's `knowledge/mediahub/services/dependency-map.md` (which app path crosses orchestration, J2N, docker).
A switch-path change in `unified-streaming` reaches orchestration → J2N → LiveTransmit → the transmitter docker;
a Billing callback change reaches warning-service and Home; a tags change spans backend, mx-service and frontend.
That reach, plus the lane's docker pin, is the risk sentence — not the commit count.

## 2 — output, in this order
1. **中文摘要 for Evan** — the lane table, then the ranked findings (≤12), each with the reach and the evidence
   source; then what could not be read. He decides here; this text is not posted.
2. **The Slack body** — English, written to `<runtime>/promote/<date>-<line>-<from>-<to>.post.md`, then shown as
   `slack post '#prj_dev_mediahub' --file … ` **dry run**. Title first (`[MH <line>] <from> → <to> promotion — <scope>`),
   body into the thread; two sends, two confirms.
3. **Jira backfills as dry runs** — `jira label <key> --add release:mh-<line>`, a `jira comment` proposing the
   Fixed In value with its evidence — never `--apply` without his word per key.
4. **The record** — on his word: the report markdown into `<records>/records/promotions/<date>-mh<line>-<from>-<to>.md`
   with a header stating what was posted, what moved after, what the run could not read. The JSON stays in
   `<runtime>` (it carries quoted words; a record names the origin, not the utterance).

## 3 — after the thread
When he has replied with the decisions and deploy has happened, `report` again with the same arguments: the
to-lane must now equal the old from-lane for every service, or the difference is the next finding.
