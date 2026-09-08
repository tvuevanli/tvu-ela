---
name: digest
description: Digest a posted report thread (MediaHub daily QA report, release test report, service test report) or a long investigation thread into what Evan must know and act on — new/reopened issues and their routing, decisions waiting on him or product, expired dates, environment gaps, risks named in passing, and a drafted ticket for every finding the thread left unticketed. Use when the user pastes a report or thread permalink from Slack, or asks "summarize this report", "日报说了什么", "这份报告我该知道什么", "test report 总结", "这个 thread 里的问题建单了吗".
user-invocable: true
---

# /ela:digest <permalink> — a report in, what it means for Evan out

Self-contained. Argument: a Slack permalink to the report thread (the daily aggregate in
#prj_dev_mediahub, or any single test/release report), or to a long investigation thread — the
extraction below applies to both, and §3 is the reason it must: a conclusion reached in a thread and
never written down is lost either way.

## Invariants
- **Read first-hand, whole thread.** The slack capability for every message in the thread; the
  jira capability for every ticket key that shapes a conclusion. Never summarize a summary when
  the claim is checkable.
- **The lens is Evan's responsibility, not completeness.** He routes work, makes or chases
  decisions, unblocks, and owns two cadence KPIs (complex tickets broken down same day;
  In-Progress updated within 24h). A pass is one line; an unrouted High or an expired date is a
  paragraph.
- **Numbers stay attached to their evidence.** Quote TC ids, ticket keys, and the report's own
  wording; never re-derive pass rates or paraphrase a severity.
- **Read-only.** Proposed tickets, replies, or re-routes are proposals; any create goes through
  the jira capability's own gates on Evan's explicit ask.
- **A finding that stays in the thread is the failure.** The 2026-09-01 daily report carried a
  BT2020 result whose own conclusion was that the transcode path writes no colour tags at all,
  followed by «暂未建单»; six days later there was still no ticket. Reading a report and leaving it
  read is not a digest — §3 is not optional.

## 0 — gather
Read `~/.claude/ela/site.json` → `env`, `map`, `published`. Bind:

```bash
SLACK="python3 ${CLAUDE_PLUGIN_ROOT}/skills/slack/slack.py --env-file <env>"
JIRA="python3 ${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py --env-file <env>"
MAP="python3 ${CLAUDE_PLUGIN_ROOT}/skills/map/map.py"
TEAM="python3 ${CLAUDE_PLUGIN_ROOT}/skills/team/team.py --env-file <env>"   # or: ela who … · ela team areas

$SLACK read <permalink>
$SLACK files <permalink> --thread --out <runtime>/slack-files   # only when a screenshot carries the finding
```
A finding's layer token comes from
`<published>/knowledge/products/mediahub/team/layer-classification.md` and the name it routes to from
`$TEAM who <name|email|Uxxx|accountId>` (exit 3 = not in the roster, and the draft says that) or
`$TEAM areas` for who to ask first about an area; both read `<published>`, falling back to elak's
private source on the office machine.

A report's numbers are usually in its text, but an investigation thread's evidence is often an
image. Fetch the files only when a conclusion depends on one, and then read it — a screenshot named
and unopened is the same as unread.

The daily aggregate is several reports stitched by a bot, often split "(1/3)" — read all
messages. Reports are bilingual; the two halves are one content, not two sources.

## 1 — extract, in this priority order
1. **New issues** — key, severity, one-line symptom, and whether the title carries a layer token.
2. **Reopened issues** — these are regressions or premature closes; name what reopened them if
   the report says.
3. **Findings without a ticket** («暂未建单», ad-hoc investigations) — each is a routing decision
   Evan has not made yet. Keep the report's own conclusion verbatim.
4. **Blocked / N-A verification and environment gaps** — work that shipped but cannot be verified
   where QA runs is silently unverified, not done.
5. **Decision items** («口径», “needs X to decide”) — the exact question, who it waits on, and
   since when.
6. **Dates** — any deadline, POC date, or “still pending since …” the report names: compare to
   today and flag the expired ones.
7. **Risks named in passing** — facts buried in 遗留 lists that will bite later (an unreleased
   image a test depends on, a wrong attribution, a missing log rotation). These are the easiest
   to lose and the reason this skill exists.
8. **Cross-team hand-offs** — anything pointed at UR / Media Mesh / another surface.
9. **Closed / passed** — one line each, keys only.

## 2 — cross-check before concluding
For every key in 1–6, read Jira (batch with `jql 'key in (…)'`, deep-read only what changes a
conclusion):

```bash
$JIRA jql 'key in (MH-…, MH-…)' --json
```

Flag against the two KPIs: a new High still unassigned or untokenized; a reopened ticket whose
assignee no longer matches the work; a decision thread stalled past its own named date.
Owners come from `$TEAM` and `<map>/services.yaml` — read, never remembered.

## 3 — the unticketed findings become drafted tickets

Everything in category 3 (a finding the thread itself says has no ticket), plus any product
requirement stated in passing — an investigation thread that concludes MediaHub must detect a class of
conflict it does not detect today has stated a requirement, not made a remark — gets one draft each.
Nothing is created here.

**First, is it a ticket at all?** Three tests, in order, and a no at any of them stops the draft:

1. **Is the conclusion the thread's, or would it be ours?** Only a finding the thread *concluded*
   becomes a ticket. A symptom still under discussion becomes a question posted back in the thread
   ("what would settle this is X") — a ticket built on our own inference lands on an owner who then
   has to re-derive it.
2. **Does it already exist?** Search before drafting, on the distinctive words, not the summary:
   ```bash
   $JIRA jql 'project = MH AND statusCategory != Done AND (summary ~ "<word>" OR description ~ "<word>")' --json
   ```
   Jira's `~` ignores punctuation and cannot see a bracket, so search the noun (`passphrase`,
   `BT2020`, `SCTE-35`), never the layer token. A hit is not automatically a duplicate: say which
   key it is and whether the finding is the same defect, a second occurrence, or a different layer of
   it. A second occurrence belongs in a comment on the existing key, not in a new ticket.
3. **Is it one ticket or several?** One defect per ticket, split by the layer that must change. A
   finding that spans layers is a parent plus sub-tasks and belongs in `/ela:breakdown`, not here —
   name it and hand it over.

**Then the draft**, one per finding, each carrying:

| part | rule |
|---|---|
| summary | `[Token] <what is wrong, not what to do>`, token from the seven-layer vocabulary the jira capability enforces. The symptom and its cause if the thread established one — the titles in this project carry both, and they are what make the pile searchable a month later |
| description | the thread's own conclusion **verbatim**, the permalink, the ids it turned on (graph / process / object / image tag), and what would verify the fix. Never a paraphrase of a QA engineer's wording |
| assignee | from the roster and `<map>/services.yaml` — the owner of the layer that must change. No owner found: leave it unassigned and say so, so it lands in the triage lane instead of on a guess |
| priority | not set here. The thread's severity is the reporter's; re-grading it is a product call |

Show each as its dry run, and stop:

```bash
$JIRA create --type Bug --summary '[Media] …' --description '…'          # dry run
$JIRA create-subtask --parent MH-2342 --summary '[App] …' --description '…'   # a customer incident hangs here
```

**One `--apply` per ticket, after Evan's word on that ticket.** Never a fan-out over the drafts: a
report with six findings is six decisions, and the whole point of drafting them is that he can reject
four. Report back the keys created, and add the new key to the thread only if he asks — posting to
Slack is `slack post`'s own confirm, not this skill's.

## 4 — output (the session's language — English unless he asked for Chinese; keys, quotes and TC ids verbatim)
1. **VERDICT, one line** — builds/envs, pass/fail totals as the report states them.
2. **ACT** — each: what · evidence (quote/TC) · next action · who. Unrouted High,
   reopened, expired dates live here.
3. **TICKET** — the §3 drafts: for each, the proposed summary, the owner, the duplicate
   search result, and the dry-run command. A finding that failed one of the three tests appears here
   too, with which test it failed and what would change that.
4. **DECIDE** — the exact open question, who it waits on, since when.
5. **RISKS** — the in-passing facts, each with where it was said.
6. **FYI** — closed/passes, one line each.

End with nothing unattributed: every item carries a key, a quote, or a TC id.
