---
name: brief
description: Evan's morning brief — what needs him today, ranked, each item with a drafted action. Reads Jira (stale In-Progress, unrouted new tickets, complex tickets not broken down) and Slack (report threads posted since yesterday, threads waiting on his reply, threads he wrote alone, decisions made in Slack without a ticket). Read-only, drafts only. Use for "brief", "今天有什么要我处理的", "早上先看什么", "what's waiting on me", "我的队列".
user-invocable: true
---

# /ela:brief — what needs Evan today, and the drafted next move for each

Self-contained. Argument: optional focus — `jira`, `slack`, `cadence`, `triage`, `breakdown`,
`reports`, `waiting`, `decisions`; empty runs every lane. Read-only: this skill never posts,
transitions, comments or creates. Every item ends in a drafted action Evan approves, edits or skips;
execution goes through the skill named on the item.

## Invariants
- **First-hand.** Jira through the jira capability, Slack through the slack capability. Never a
  dashboard's summary, never memory of yesterday's brief.
- **Two KPIs are the lens.** Complex tickets broken down the same day; In-Progress updated within
  24h; a new ticket routed within 4h. Everything else is ranked below these.
- **Ranked, capped, honest.** At most 12 items in the top list; the rest in one line per lane. Each
  item states the fact (with key or permalink), why it is on the list, and the drafted action. If a
  lane could not be read (missing token, channel the bot is not in, API error), the brief says so in
  that lane's line — a silent lane is a lie.
- **Facts are computed, judgment is written.** Hours since update, routing overdue, "no sub-tasks"
  are computed by the scripts below; whether a Slack message is a decision, and how urgent an item is
  relative to another, is this skill's judgment and is written as such.
- **Nothing is written anywhere.** Not to Jira, not to Slack, not to the knowledge base. The brief is
  the day's view; tomorrow recomputes it.

## 0 — gather
Read `~/.claude/ela/site.json` → `env`, `map`, `records`, `map_sources.team_roster`. Bind:
```bash
JIRA="python3 ${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py --env-file <env>"
SLACK="python3 ${CLAUDE_PLUGIN_ROOT}/skills/slack/slack.py --env-file <env>"
```
Read the roster file (owner ↔ layer ↔ signal words) so drafted routing names a person, never a
guess. Today's date and weekday matter: Evan's week is front-loaded (Monday sweep), so a Monday brief
is allowed to be longer; a Friday brief should be short.

## 1 — Jira lanes (facts by script)

Operational definitions — narrow on purpose, stated so they can be argued with. The first run
(2026-09-02) argued with two of them: Epics were misjudged as un-split, and Jira's text operator
cannot see a bracket; both fixed below.

| lane | JQL (project MH) | computed flag | drafted action → skill |
|---|---|---|---|
| **cadence** (KPI: In-Progress updated within 24h) | actionable: `status = "In Progress" AND updated <= -24h AND updated >= -14d ORDER BY updated ASC` · zombies: `status = "In Progress" AND updated < -14d` (count and owners only) · `status = Blocked ORDER BY updated ASC` (Blocked sits in the To-Do category and is invisible to the first queries) | hours since `updated`: **RED > 48h · YELLOW > 24h**; zombies are one line, never items; Blocked always listed with its age | a one-line nudge to the assignee naming the one thing missing (status? blocker? ETA?), grounded in the last comment (`$JIRA read <key>`) → `$JIRA comment <key> --text '…'` (dry-run shown; `--apply` after Evan's word) |
| **triage** (KPI: routed within 4h) | `created >= -2d AND statusCategory != Done AND assignee is EMPTY` — new and nobody's yet. A separate hygiene line from `created >= -2d AND statusCategory != Done`: count the rows whose summary does not match `^\[(Infra\|J2N\|Media\|App\|UI\|QA\|Design\|AI)\]` — computed in the session, because Jira's `~` ignores punctuation and cannot test for the bracket | `created` age; **OVERDUE > 4h** | the layer and the name, with the discriminating check → `/ela:route <key>` |
| **breakdown** (KPI: complex tickets broken down same day) | `issuetype in (Epic, Task, Improvement) AND priority in (Highest, High) AND status not in (Review, Done, Cancelled) AND created >= -30d` | keep rows with `subtasks == 0` **and** no children by parent link: for each such row run `$JIRA jql "parent = <KEY>" --json` and drop it when `count > 0` (an Epic's children hang off `parent`, never `subtasks`); age in days | one line naming the lanes it would split into → `/ela:breakdown <key>` |

Run each with `--json --limit 300` (the script follows pages of 100); the JSON rows carry `status, assignee, priority, labels,
parent, subtasks, created, updated`. Compute the flags in the session (arithmetic on the timestamps),
never by eye. Tickets assigned to Evan himself go to a separate "yours" line: they are his cadence
debt, not someone else's.

## 2 — Slack lanes (facts by script, judgment here)

```bash
$SLACK channels --json                                   # what the bot can see; DMs are never visible — say so
$SLACK history C06553EE44X --since 24h --json            # #prj_dev_mediahub: report threads posted since yesterday
$SLACK mentions --since 48h --channels C06553EE44X,C0BS83BRU3D,C07BVLXFKED,CRY6XQQ7J --json
                                                         # threads that mention Evan; answered = he replied after the last mention
$SLACK unanswered --since 7d --channels C06553EE44X,C0BS83BRU3D,C07BVLXFKED --json
                                                         # threads Evan started that nobody else answered (no reply fetch: parents carry reply_users)
$SLACK history C06553EE44X --since 7d --threads --json   # for the decisions lane, only when that lane runs
```

| lane | fact | judgment | drafted action → skill |
|---|---|---|---|
| **reports** | top-level messages in the last 24h whose author is a bot or whose text carries a report marker (`report`, `日报`, `测试报告`, `release note`, `(1/`) | which are Evan's to digest (MediaHub QA daily, release/service test reports) vs noise | "digest" → `/ela:report <permalink>` |
| **waiting** | `mentions` rows with `answered: false`, oldest first | is a reply actually owed, or was the mention an FYI? Product, QA and integration partners waiting > 1 working day rank at the top | a one-line reply draft (Evan posts it — ela does not write Slack), or "FYI — no reply needed" |
| **monologues** | `unanswered` rows older than 24h | a spec or a question nobody picked up is a routing gap, not a Slack curiosity | name who should have answered → route, or "convert to ticket" → `$JIRA create --summary … --description …` dry-run |
| **decisions** | Evan's own replies in the 7-day window that rule something (Chinese cues: 先…再…, 不做, 不改, 我来, 就这样, 既然…; English: `Let's …`, `we will not`, `decided`) in threads whose text carries **no** Jira key | is it a durable decision others act on? | "record" → `records/decisions/<date>-<slug>.md` via Evan's word, or `$JIRA comment <key> --text '<the ruling, verbatim, with the permalink>'` dry-run |

Slack scans cost one call per thread that was active in the window; the channel lists above are the
ones Evan posts in (his messages: 339 of 352 in #prj_dev_mediahub over a month). Widen `--channels`
only when he asks; a full 13-channel scan takes minutes.

## 3 — rank and write
Order: triage OVERDUE → waiting (product / QA / partner, > 1 day) → cadence RED → reports →
breakdown → cadence YELLOW → monologues → decisions → Evan's own tickets. Within a lane, oldest
first. Then:

```
# brief · <weekday> <date>            <n> items · lanes read: jira ✓ slack ✓ (DMs not visible)

1. [triage · OVERDUE 19h] MH-3601 "SRT output stalls after failover" — unassigned, no layer token.
   → route: [Media] · Lotus Chen (signal: SRT, frame drop). Check first: is the graph still Living?   /ela:route MH-3601
2. [waiting · 2d] #prj_dev_mediahub — Robin asked for the MH-3049 update "by end of day" on Mon.
   → reply draft: "Idle-source shutdown: app-only part is on Daily d31; docker gaps tracked in MH-3490 with Lotus."
…
lanes in one line each:
cadence   3 RED · 5 YELLOW · 1 Blocked (MH-3288, 9d)          yours: MH-2191 (In Progress, 3d silent)
reports   1 — MediaHub QA daily (2/3 parts)                    → /ela:report <permalink>
breakdown 2 — MH-3513 (High, 8d), MH-3580 (Highest, 1d)
monologue 1 — "MH Admin: close a user's graph?" (4d, no reply) → ask Andy Zhao directly
decisions 2 candidates — see below
```

Every ticket key is a Jira link, every Slack item a permalink. Under the list, the decisions lane
prints each candidate's sentence verbatim with its permalink and the proposed record title; Evan
says which to keep. Close with what could not be read, if anything.

## 4 — what this skill does not do
- Post, comment, transition, assign, create, or write a file. The drafted actions name the skill
  or the E4 atom that will, behind its own confirm.
- Read Gmail or Helm's pages. Reports that arrive only by email are out of scope until a sense exists.
- Remember. No state between runs; a ticket that was RED yesterday and is RED today is simply RED.
