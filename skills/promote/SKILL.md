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
$P proof text <file> --lane daily-wed | graph <id> --lane L | lane L           # the environment proof; `lane` reads the lane's own /base/version
$P constraints [--json]                                                            # the standing constraints, each pin read now; exit 3 when one is over
$P plan 2.1 daily prod --on 2026-11-06 --after "QA's report on Thursday's build" --carry MH-1860   # a planned promotion, local file only
$P close                                                                           # the pending promotion shipped or was dropped
# Progress goes to stderr one line per step (--quiet to silence); the JSON contract is what the session reads.
```
`<line>` is a key of `<elak>/map/release.yaml lines`; `<from>`/`<to>` are lane roles (qa · daily · prod) or lane
names. Exit 3 means a lane could not be read — for daily/stage/prod that is the person's TVU session: tell Evan
to type `! ela login tvu` and stop; never read a cache or another system's file instead. The qa host is the exception
since 2026-11-04 (the QA environment no longer admits ela's account): a QA lane's rows then come from QA's report mails
and the day's release thread, as the brief keeps them in the last saved lane read (`host: mail`, `reported` or
`built`), the gap `host_from_mail` names the source and its newest time (a medium finding, not a stop), and the
version table's `source` column says so per service. With no report or release naming the lanes it is unreadable as
before.

One docker image moving on its own — QA's summary report for `copier:1.0.88`, say — is not a line's promotion:
`ela docker [--image I]` joins that image's report to the lanes' bundles and gives ready / not ready and, for a daily
lane behind it, the dry-run bundle command. The line's promotion stays here, and prod moves only with the line.

## Invariants
- **Every source is checked against another.** A commit's ticket is the key in its subject (the body's key only
  when the subject has none; a body-cited key is a reference, not a carried ticket). A ticket's Fixed In is
  checked against the build that actually carries its commits. A ticket's status is never taken as evidence.
  Dev-declared ("deployed to QA", "fixed in build …") is **not verified**. QA's N/A is a conclusion, not a gap.
- **QA's own words decide, read from Jira first.** The verdict is QA's latest statement about that key. Jira comes
  first: `qajira.py` reads every ticket's latest QA-person comment (roster area qa; a copy headed by another key, or by
  an automation account, is not this ticket's verdict). Mail reports, a QA Slack message and the train come second,
  and the newest statement across sources wins. A result comment is pass, **partial** (⚠: both Pass and Fail counts,
  遗漏 or ⚠️, a 待确认 count, or a 说明 / 存在的问题 line naming what is still open), fail, accepted (保持现状: the
  described change does not ship) or n-a. Each verdict is shown with its counts, the lane and build its environment
  block proves (`envproof`), and the tickets it split into or was cloned to, each with its own verdict and status.
  A partial is never shown as a pass. Never re-derive a pass rate; never infer a pass from silence. On 2026-11-09 mail
  alone missed seven build-85 verdicts (MH-3872, 3882, 3885, 3909, 3911, 3916, 3924).
- **A test counts for a lane only when the lane is proven.** The gateway routes by the account, so "tested on Wed"
  proves nothing by itself: on 2026-11-09 a volume test "on Wed" ran through prod-3's UR Caller. The verify skill's
  rule applies to every piece of test evidence promote shows, and to any sentence of the page that says something
  works on a lane: `$P proof text <file> --lane L` reads a version-panel block (a QA comment's 验证环境, a pasted panel),
  `$P proof graph <id> --lane L` binds a graph to the UR Caller instance that created it (its trace in the java-log).
  `proven` counts for the lane; `same-build` (another lane at the same versions) is said as "on <lane> at <build>",
  never as the claimed lane; `other-lane` and `unproven` do not count, and the sentence is rewritten or dropped.
  A QA verdict stays QA's word on the ticket either way; its proof only says where and on which build it was seen.
- **Every ticket is placed against the target lane before it is called new.** `placement.py`: per service part, the
  Fixed In version against the version the target lane runs, and the commits in the range the key owns (a commit
  scoped to another key, or citing it only in its body, cites it; docs/test/chore commits ship nothing). The ticket is
  `new`, `on-target` (nothing new for users; at most what the citing commits add) or `partly-new` (which part). QA's
  pass environment places a ticket only when nothing else does. The line's label brings in tickets with no commit in
  the range, so the page cannot list as new what the target already runs (MH-3579, MH-3503, MH-3582, MH-3668 on
  2026-11-09); every `on-target` and `partly-new` ticket is a note in the report.
- **What the deploy needs is read, not asked for.** `prereqs.py` scans the release's tickets (description, comments)
  and the docs the range changes for deploy-time items (an SQL statement on a table, a one-off backfill call, a
  发版待办 list, a key = value beside a release word), lists the release-branch commits after the promoted build, and
  dry-runs every unmerged branch named after a release ticket with `git merge-tree` against the release branch and
  against the other such branches. A deploy item is a high finding with its citation; an unbuilt commit or a conflict
  is medium. On 2026-11-09 the MH-3891 DDL (two databases), its backfill call and the MH-3961 / MH-3966 conflict all
  surfaced only when the owner asked.
- **The shipped version is the one the source lane proves, or the gap is listed.** `--ship SERVICE=VERSION` (UR
  Caller=2.1.87, or a build `#377`) names what the release ships; where that is not the source lane's build,
  `shipcheck.py` lists the commits between with their tickets, and for each ticket the QA verdicts run on a build that
  carries it. A ticket with none is high; a source-lane test or a verdict on the older build never covers it. Without
  `--ship`, a newer successful build on the source build's branch is a note naming the flag. On 2026-11-09 UR Caller
  2.1.87 was named for prod-3 while daily-wed ran 2.1.85, and MH-3961 and MH-3966 ×2 sat in between with no QA.
- **What the release calls is read live on the target.** For a prod target, `livedeps.py` takes every fixed-URL Feign
  client of a range repo from the dependency map, reads its URL key along the target lane's proven profile chain (a key
  absent there falls to the code default, high when that default is a dev or test URL), finds the gateway route and,
  for a version-controlled route, every instance behind it, and reads each one's `/base/version` now. An instance
  built before a commit that names a release ticket is high. A config server or instance that cannot be read is
  named as unread on every edge that needed it, never left out. On 2026-11-09 every audio-mixer instance predated the
  mediabox mixer's gateway leg, and the route was version-controlled across prods; both surfaced only when asked.
- **The to-lane is read live or declared unreadable.** Any lane ahead of the target (prod ahead of daily) is
  reported; a target lane ahead of the source stops the promotion until explained. A from-lane that is a QA lane may
  be QA's word (its report's environment block) or the release's (the thread, the `[Release Mediahub QA-AWS3]` mail)
  when the host is unreadable; the post says which, with the time.
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
- **A report written with `--out` opens the pending promotion for its line and lanes.** `<reports>/promote/pending.json`
  holds one record per line and lane pair (`{"2.1|daily-wed|prod-3": {...}, "2.0|qa-cn2|prod-8": {...}}`): the line,
  the lanes, the report's path and the candidate: the source lane's version per service. The next run for the same
  line and lanes refreshes that record and no other; a cell the owner still has to choose is written there as
  `{"awaiting": "owner", "options": [...], "why": "..."}` and kept until he rules, as are the fields the report does
  not produce (label, bundle, open_items, notes, waiting_on). A source lane the run could not read never blanks a
  filled candidate: the last good versions stand, marked `stale: "<when> source unreadable"`. The morning shows each
  line's candidate as the next train on the lanes page and each awaiting cell as a decision for him; `close` ends one
  record when the promotion shipped or was dropped (`--line`/`--to` when several are open).
- **A planned promotion is on the same record.** `plan <line> <from> <to> --on YYYY-MM-DD --after "<condition>"
  [--carry KEY…]` writes the day, the condition in words and the keys the train carries (the local file only, never
  Slack); the lanes block, the next-train column and `report` show it as one line — "planned Fri 11-06 after QA's
  report on Thursday's build · carries MH-1860 (feature/MH-1860 not merged into release2.1 in 3 repos as of 11-04)".
  Every `plan`, `plan --check` and `report` run, and every lanes-page pass, re-checks three facts as ✓/·/✗ lines: each
  carried key's branches against `origin/release<line>` in every mapped checkout (the refs as last fetched), whether
  the newest QA build's release mail names the key, and whether that build has a QA report. `close` clears the plan.
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
   in the shape the vault's spec for a review sets (its readme, *Note standards*; `ela vault lint` checks it): the
   title and heading `MH <line> · <from> → <to> · <what>`, an *In short* paragraph, the findings, what could not be
   read, then `## What you should do` (the recommendation first, each action a box or a ready command, the
   alternative named) and, when something needs his word, `## Waiting for your word` after it; outputs 2 to 4
   quoted beneath it, folded. The vault sync carries it into `readings/`, where he reviews it on his own machine (elak decision
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
