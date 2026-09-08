---
name: brief
description: Evan's morning brief — what needs him today, ranked, each item with a drafted action. Reads Jira (stale In-Progress, unrouted new tickets, complex tickets not broken down, the open customer-incident pile, his own rotting backlog) and Slack (report threads posted since yesterday, threads waiting on his reply, threads he wrote alone, decisions made in Slack without a ticket). Read-only, drafts only. Use for "brief", "今天有什么要我处理的", "早上先看什么", "what's waiting on me", "我的队列".
user-invocable: true
---

# /ela:brief — what needs Evan today, and the drafted next move for each

Self-contained. Argument: optional focus — `jira`, `slack`, `cadence`, `triage`, `breakdown`,
`incidents`, `backlog`, `reports`, `waiting`, `decisions`; empty runs every lane. Read-only: this
skill never posts, transitions, comments or creates. Every item ends in a drafted action Evan
approves, edits or skips; execution goes through the skill named on the item.

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
Read `~/.claude/ela/site.json` → `env`, `map`, `elak`, `published`. Bind:
```bash
JIRA="python3 ${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py --env-file <env>"
SLACK="python3 ${CLAUDE_PLUGIN_ROOT}/skills/slack/slack.py --env-file <env>"
TEAM="python3 ${CLAUDE_PLUGIN_ROOT}/skills/team/team.py --env-file <env>"   # or: ela who … · ela team areas
```
A drafted routing line is two reads, never a guess: the area from
`<published>/knowledge/products/mediahub/team/layer-classification.md`, then the person from `$TEAM
who <name|email|Uxxx|accountId>` (exit 3 = not in the roster, and that is what the line says) or
`$TEAM areas` for who to ask first about an area; both read `<published>`, falling back to elak's
private source on the office machine. Today's date and weekday matter: Evan's week is front-loaded
(Monday sweep), so a Monday brief is allowed to be longer; a Friday brief should be short.

## 1 — Jira lanes (facts by script)

Operational definitions — narrow on purpose, stated so they can be argued with. The first run
(2026-09-02) argued with two of them: Epics were misjudged as un-split, and Jira's text operator
cannot see a bracket; both fixed below.

| lane | JQL (project MH) | computed flag | drafted action → skill |
|---|---|---|---|
| **cadence** (KPI: In-Progress updated within 24h) | actionable: `status = "In Progress" AND updated <= -24h AND updated >= -14d ORDER BY updated ASC` · zombies: `status = "In Progress" AND updated < -14d` (count and owners only) · `status = Blocked ORDER BY updated ASC` (Blocked sits in the To-Do category and is invisible to the first queries) | hours since `updated`: **RED > 48h · YELLOW > 24h**; zombies are one line, never items; Blocked always listed with its age | a one-line nudge to the assignee naming the one thing missing (status? blocker? ETA?), grounded in the last comment (`$JIRA read <key>`) → `$JIRA comment <key> --text '…'` (dry-run shown; `--apply` after Evan's word) |
| **triage** (KPI: routed within 4h) | `created >= -2d AND statusCategory != Done AND assignee is EMPTY` — new and nobody's yet. A separate hygiene line from `created >= -2d AND statusCategory != Done`: count the rows whose summary does not match `^\[(Infra\|J2N\|Media\|App\|UI\|QA\|Design\|AI)\]` — computed in the session, because Jira's `~` ignores punctuation and cannot test for the bracket | `created` age; **OVERDUE > 4h** | the layer and the name, with the discriminating check → `/ela:route <key>` |
| **breakdown** (KPI: complex tickets broken down same day) | `issuetype in (Epic, Task, Improvement) AND priority in (Highest, High) AND status not in (Review, Done, Cancelled) AND created >= -30d` | keep rows with `subtasks == 0` **and** no children by parent link: for each such row run `$JIRA jql "parent = <KEY>" --json` and drop it when `count > 0` (an Epic's children hang off `parent`, never `subtasks`); age in days | one line naming the lanes it would split into → `/ela:breakdown <key>` |
| **incidents** (the customer pile) | `parent = MH-2342 AND statusCategory != Done ORDER BY updated ASC` | see §1a | one investigation per cluster, or the one missing fact → `/ela:probe`, `/ela:route`, `$JIRA comment` |
| **backlog** (Evan's own rot) | `assignee = currentUser() AND statusCategory != Done AND updated <= -30d ORDER BY updated ASC` | see §1b | close · hand over · keep with a date — one verdict each |

Run each with `--json --limit 300` (the script follows pages of 100); the JSON rows carry `status, assignee, priority, labels,
parent, subtasks, created, updated`. Compute the flags in the session (arithmetic on the timestamps),
never by eye. Tickets assigned to Evan himself go to a separate "yours" line: they are his cadence
debt, not someone else's.

### 1a — incidents: the pile is the item, not each ticket

MH-2342 is the umbrella every customer incident hangs under as a sub-task; on 2026-09-07 it carried
**31 open**, 26 of them one owner's, almost all in Backlog, the oldest untouched for months. A bot
already posts a daily roll-call of exactly this list into `#prj_dev_mediahub` and it draws **no
replies** — so another list is worthless. This lane exists to turn the pile into a small number of
decisions.

- **Verify the umbrella, don't assume it.** If the JQL returns 0 rows, say "the incident umbrella
  moved" and check MH-2342 with `$JIRA read MH-2342` — never report "no open incidents", which is
  the one thing that is certainly false.
- **Cluster before ranking.** Group rows by customer and symptom from the summary (`Reuters` +
  freeze / stuck / flicker; `Cablevision` + black; `Hekayat` + feed not received). On 2026-09-07 five
  Reuters rows were one symptom family. **A cluster is one item with one investigation**, not five
  nudges — six comments on six tickets is the failure mode this lane is meant to replace.
- **Per row, compute what decides the next move**, not how old it is:
  · does the ticket or its comments carry a graph id (26 chars), process id (32 hex) or object id
  (19 digits)? Then the first hop is free — `ela graph <id>` reads it, stopped graphs included.
  · does the summary or description name a service, image or process type in `map/services.yaml`?
  Then it is routable today (`$MAP find <word>`).
  · who spoke last — TVU or the customer? A row where TVU spoke last is waiting on the customer and
  is **not** Evan's item; a row where the customer spoke last and nobody answered is.
  · is there a dedicated channel for that customer (`$SLACK channels --all <customer>`)? The thread
  there usually holds the facts the ticket does not.
- **Contribute at most 3 items to the top list**: the oldest cluster, any row where the customer
  spoke last, and anything created inside 48h. The rest is one summary line. A lane that floods the
  list is a lane Evan stops reading.
- **The drafted action is one of three**, and says which: a cluster → `/ela:probe <the one key that
  has evidence>`; a routable single → `/ela:route <key>`; a row with no evidence at all → a comment
  asking the reporter for **the one missing fact** (graph id and the time window), never a status
  request.

### 1b — backlog: three verdicts a day, not a sweep

Evan's own name carried **30 open rows on 2026-09-07, 24 in Backlog**, the oldest (MH-83, MH-85,
MH-409, MH-540) untouched for years. These are not cadence debt — nobody is waiting on them — and
they are not a fire. Left alone they make his own queue unreadable, which is what the KPIs are
measured against.

- **Three rows per run, oldest `updated` first.** A 24-row pile clears in eight days at three a day;
  attempted in one sitting it clears in none.
- Each row gets exactly one verdict, with the reason in one line: **close** (the product moved, or a
  newer ticket covers it — name it), **hand over** (an owner exists in the roster for that layer —
  name them), or **keep** (still Evan's, with a date; a keep without a date is a close).
- Read the row before judging it (`$JIRA read <key>`): a Backlog row with a recent comment is
  somebody's live question, not rot.
- Drafted action per verdict: `$JIRA transition <key> --to Cancelled` · `$JIRA assign <key> <person>`
  · `$JIRA comment <key>` with the date — each dry-run, `--apply` only after Evan's word on that row.
- **Never batch.** One `--apply` per row: a fan-out over a list of keys is how a wrong verdict
  becomes twenty.

## 2 — Slack lanes (facts by script, judgment here)

```bash
$SLACK channels --json                                   # what the bot can see; DMs are never visible — say so
$SLACK history '#prj_dev_mediahub' --since 24h --json    # report threads posted since yesterday
$SLACK mentions --since 48h --json                       # every channel the bot is in; `unread_channels` names any it could not read
$SLACK unanswered --since 7d --json                      # threads Evan started that nobody else answered (no reply fetch: parents carry reply_users)
$SLACK history '#prj_dev_mediahub' --since 7d --threads --json   # for the decisions lane, only when that lane runs
```

`mentions` and `unanswered` are run **unscoped**: since ela 0.30.0 a channel that will not come down
whole is named in `unread_channels` instead of killing the lane, so `--channels` is now a way to go
faster, not a way to survive. Pass it only when a run must be cheap; whatever it excludes is a
channel the brief did not read, and the brief must then say so. Both verbs cost one call per thread
active in the window — nearly all of Evan's messages are in `#prj_dev_mediahub`.

**The bot is in 14 of the workspace's 2508 public channels**, and the ones it is missing are where
several of the open incidents live (Reuters has two, FloSports one, and `#alert_j2n` exists). That is
a standing gap, not a lane: `$SLACK channels --all <word>` finds them and joining is Evan's call
(it is visible to the channel). When an item's customer has such a channel, say so on the item.

| lane | fact | judgment | drafted action → skill |
|---|---|---|---|
| **reports** | top-level messages in the last 24h whose author is a bot or whose text carries a report marker (`report`, `日报`, `测试报告`, `release note`, `(1/`) | which are Evan's to digest (MediaHub QA daily, release/service test reports) vs noise | "digest" → `/ela:digest <permalink>` |
| **waiting** | `mentions` rows with `answered: false`, oldest first | is a reply actually owed, or was the mention an FYI? Product, QA and integration partners waiting > 1 working day rank at the top | a one-line reply draft (Evan posts it — ela does not write Slack), or "FYI — no reply needed" |
| **monologues** | `unanswered` rows older than 24h | a spec or a question nobody picked up is a routing gap, not a Slack curiosity | name who should have answered → route, or "convert to ticket" → `$JIRA create --summary … --description …` dry-run |
| **decisions** | Evan's own replies in the 7-day window that rule something (Chinese cues: 先…再…, 不做, 不改, 我来, 就这样, 既然…; English: `Let's …`, `we will not`, `decided`) in threads whose text carries **no** Jira key | is it a durable decision others act on? | "record" → the ruling as a fact in `<elak>/knowledge/products/mediahub/` via Evan's word (a decision others act on is knowledge about the product, not a log of a conversation — (elak `blueprint/principles.md` P1), or `$JIRA comment <key> --text '<the ruling, verbatim, with the permalink>'` dry-run |

## 3 — rank and write
Order: triage OVERDUE → waiting (product / QA / partner, > 1 day) → cadence RED → incidents
(customer spoke last, or created inside 48h) → reports → breakdown → cadence YELLOW → incidents
(oldest cluster) → monologues → decisions → Evan's own tickets → backlog. Within a lane, oldest
first. `backlog` is always last and always three rows: it is the only lane that may be skipped
outright on a busy day. Then:

```
# brief · <weekday> <date>            <n> items · lanes read: jira ✓ slack ✓ (DMs not visible)

1. [triage · OVERDUE 19h] MH-3601 "SRT output stalls after failover" — unassigned, no layer token.
   → route: [Media] · Lotus Chen (signal: SRT, frame drop). Check first: is the graph still Living?   /ela:route MH-3601
2. [waiting · 2d] #prj_dev_mediahub — Robin asked for the MH-3049 update "by end of day" on Mon.
   → reply draft: "Idle-source shutdown: app-only part is on Daily d31; docker gaps tracked in MH-3490 with Lotus."
…
lanes in one line each:
cadence   3 RED · 5 YELLOW · 1 Blocked (MH-3288, 9d)          yours: MH-2191 (In Progress, 3d silent)
incidents 31 open · 4 clusters (Reuters freeze ×5, Cablevision black ×2, …) · 7 with no evidence at all
reports   1 — MediaHub QA daily (2/3 parts)                    → /ela:digest <permalink>
breakdown 2 — MH-3513 (High, 8d), MH-3580 (Highest, 1d)
monologue 1 — "MH Admin: close a user's graph?" (4d, no reply) → ask Andy Zhao directly
decisions 2 candidates — see below
backlog   24 rotting · today's three: MH-83 (close), MH-409 (hand to UI), MH-540 (keep → 09-19)
```

Every ticket key is a Jira link, every Slack item a permalink. Under the list, the decisions lane
prints each candidate's sentence verbatim with its permalink and the proposed record title; Evan
says which to keep. Close with what could not be read, if anything.

## 4 — what this skill does not do
- Post, comment, transition, assign, create, or write a file. The drafted actions name the skill
  or the E4 atom that will, behind its own confirm.
- Read Helm's pages. Helm posts its own Daily and Weekly Report to `#helm-alerts`; the brief is
  Evan's queue, not a second copy of that, and it never cites Helm as a source.
- Read Gmail on its own account. The `mail` sense exists (QA reports, deploy notices and release
  approvals are emails), but it is `digest`'s and `promote`'s input, not a brief lane: a report that
  needs reading is one item — "digest this" — however many messages it arrived as.
- Remember. No state between runs; a ticket that was RED yesterday and is RED today is simply RED.
  `backlog` needs no memory either and must not invent one: a verdict that was applied removes its
  row from tomorrow's JQL by itself — closed is Done, handed over is not `currentUser()`, and a keep
  carries a comment, so `updated` is fresh. A row that reappears is a verdict Evan did not approve,
  and it goes to the bottom of the three, not the top.
