---
name: digest
description: Digest a posted report thread (MediaHub daily QA report, release test report, service test report) into what Evan must know and act on — new/reopened issues and their routing, decisions waiting on him or product, expired dates, environment gaps, and risks named in passing. Use when the user pastes a report permalink from Slack, or asks "summarize this report", "日报说了什么", "这份报告我该知道什么", "test report 总结".
user-invocable: true
---

# /ela:digest <permalink> — a report in, what it means for Evan out

Self-contained. Argument: a Slack permalink to the report thread (the daily aggregate in
#prj_dev_mediahub, or any single test/release report).

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

## 0 — gather
Read `~/.claude/ela/site.json` → `env`, `map`, `map_sources.team_roster`.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/slack/slack.py" --env-file <env> read <permalink>
```

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
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py" --env-file <env> jql 'key in (MH-…, MH-…)' --json
```

Flag against the two KPIs: a new High still unassigned or untokenized; a reopened ticket whose
assignee no longer matches the work; a decision thread stalled past its own named date.
Owners come from the roster file and `<map>/services.yaml` — read, never remembered.

## 3 — output (Chinese; keys, quotes and TC ids verbatim)
1. **一行判定** — builds/envs, pass/fail totals as the report states them.
2. **要动手 (ACT)** — each: what · evidence (quote/TC) · next action · who. Unrouted High,
   reopened, expired dates live here.
3. **要拍板 (DECIDE)** — the exact open question, who it waits on, since when.
4. **风险钉住 (RISKS)** — the in-passing facts, each with where it was said.
5. **知道即可 (FYI)** — closed/passes, one line each.

End with nothing unattributed: every item carries a key, a quote, or a TC id.
