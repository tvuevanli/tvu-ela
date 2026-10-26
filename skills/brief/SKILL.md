---
name: brief
description: The owner's morning brief from Jira and Slack, ranked, with drafted actions. Read-only. Use for "brief", "今天有什么要我处理的", "早上先看什么", "what's waiting on me", "我的队列".
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
- **Three KPIs are the lens.** Complex tickets broken down the same day; In-Progress updated within
  24h; a new ticket routed within 4h. Everything else is ranked below these.
- **Ranked, capped, honest.** At most 12 items in the top list; the rest in one line per lane. Each
  item states the fact (with key or permalink), why it is on the list, and the drafted action. If a
  lane could not be read (missing token, channel the bot is not in, API error), the brief says so in
  that lane's line — a silent lane is a lie.
- **Facts are computed, judgment is written.** Hours since update, routing overdue, "no sub-tasks"
  are computed by `brief.py` (§1) and the slack capability (§2); whether a Slack message is a decision, and how urgent an item is
  relative to another, is this skill's judgment and is written as such.
- **Nothing is written anywhere.** Not to Jira, not to Slack, not to the knowledge base. The brief is
  the day's view; tomorrow recomputes it.

## 0 — gather
Read `~/.claude/ela/site.json` → `env`, `map`, `elak`, `published`. The Jira lanes are one call:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/brief/brief.py" --env-file <env> lanes --json   # or: ela brief --json
```
For the per-row follow-ups (§1a, §1b, drafted actions) and the Slack lanes, bind:
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

## The runner's page is the input, this skill's reading is the output

On a weekday morning `ela-runner` has already written `<runtime>/runner/<date>.md` from `ela brief`,
`ela stage` and `ela slack mentions` and sent it to the owner as a direct message. This skill does not
recompute those facts: it reads that page (or runs the three verbs when the page is missing) and adds
what only a reading can add — for every intake row, what the ticket is about in the reporter's words,
the layer, who should hold it, and the one action it owes or "read, nothing to change"; for every
stage row, whether the owed action still holds today. The drafted actions are dry runs; the page the
owner reads stays one line per item.

## 1 — Jira lanes (facts by script)

Operational definitions — narrow on purpose, stated so they can be argued with. Epics hang their
children off `parent`, never `subtasks`, and Jira's text operator cannot see a bracket; both are
handled in the script. The table is **what `brief.py` computes**; the drafted action is this skill's.

| lane | JQL (project MH) | computed flag | drafted action → skill |
|---|---|---|---|
| **intake** (every new ticket gets one pass) | `created >= -1d ORDER BY created ASC` — every ticket created since yesterday, whatever its status or assignee | `UNASSIGNED` · `NOPREFIX` (a sub-task without a layer token) · `EPIC-NO-CHILDREN` (a support escalation filed as an Epic) | one line per ticket on the page, always, even when nothing changes: what it is about in the reporter's terms, who holds it, and the one action it owes or "read, nothing to change". A ticket on the MH board concerns the owner by definition; the failure this lane prevents is a ticket he never saw. Flagged rows route to `/ela:route` or `/ela:breakdown`; its classification (component, `proto:`, the summary's `[Account]` bracket; jira SKILL, *Classifying a ticket ela processes*) is drafted here as one `apply N` per ticket |
| **cadence** (KPI: In-Progress updated within 24h) | actionable: `status = "In Progress" AND updated <= -24h AND updated >= -14d ORDER BY updated ASC` · zombies: `status = "In Progress" AND updated < -14d` (count and owners only) · `status = Blocked ORDER BY updated ASC` (Blocked sits in the To-Do category and is invisible to the first queries) | hours since `updated`: **RED > 48h · YELLOW > 24h**; zombies are one line, never items; Blocked always listed with its age | a one-line nudge to the assignee naming the one thing missing (status? blocker? ETA?), grounded in the last comment (`$JIRA read <key>`) → `$JIRA comment <key> --text '…'` (dry-run shown; `--apply` after Evan's word) |
| **triage** (KPI: routed within 4h) | `created >= -2d AND statusCategory != Done AND assignee is EMPTY` — new and nobody's yet. A separate hygiene line from `created >= -2d AND statusCategory != Done`: count the rows whose summary does not match `^\[(Infra\|J2N\|Media\|App\|UI\|QA\|Design\|AI)\]` — computed in the script, because Jira's `~` ignores punctuation and cannot test for the bracket | `created` age; **OVERDUE > 4h** | the layer and the name, with the discriminating check → `/ela:route <key>` |
| **breakdown** (KPI: complex tickets broken down same day) | `issuetype in (Epic, Task, Improvement) AND priority in (Highest, High) AND status not in (Review, Done, Cancelled) AND created >= -30d` | keep rows with `subtasks == 0` **and** no children by parent link: one `parent in (K1, K2, …)` query over all candidates, and the parents that appear are dropped (an Epic's children hang off `parent`, never `subtasks`); age in days | one line naming the lanes it would split into → `/ela:breakdown <key>` |
| **incidents** (the customer pile) | `parent = MH-2342 AND statusCategory != Done ORDER BY updated ASC` | see §1a | one investigation per cluster, or the one missing fact → `/ela:probe`, `/ela:route`, `$JIRA comment` |
| **backlog** (Evan's own rot) | `assignee = currentUser() AND statusCategory != Done AND updated <= -30d ORDER BY updated ASC` | see §1b | close · hand over · keep with a date — one verdict each |

The output is `{"generated", "lanes": {<lane>: {"rows", "count", …}}, "errors"}`. Rows carry the jira
capability's fields (`key, summary, status, assignee, priority, labels, parent, subtasks, created,
updated`) plus the computed ones: `flag`, `hours_since_update` or `hours_since_created`, `prefix_ok`
(triage), `age_days` (breakdown). Per lane: cadence adds `red`, `yellow`, `blocked` rows and `zombies`
(count and owners); triage adds `overdue` and `hygiene.missing_prefix`; incidents sets
`umbrella_moved` when it returns nothing; backlog returns only `next_three` as rows with `rest_count`.
Tickets assigned to Evan himself come out of cadence as the `yours` lane: they are his cadence debt,
not someone else's. A lane in `errors` (exit 5) was not read — say so in that lane's line. Use the
flags as computed; never recompute them by eye.

### 1a — incidents: the pile is the item, not each ticket

MH-2342 is the umbrella every customer incident hangs under as a sub-task. The pile tends to be
large, concentrated on one owner, mostly in Backlog, with the oldest rows untouched for months. A bot
already posts a daily roll-call of exactly this list into `#prj_dev_mediahub` and it draws **no
replies** — so another list is worthless. This lane exists to turn the pile into a small number of
decisions.

- **Verify the umbrella, don't assume it.** If the lane carries `umbrella_moved: true`, say "the
  incident umbrella moved" and check MH-2342 with `$JIRA read MH-2342` — never report "no open incidents", which is
  the one thing that is certainly false.
- **Cluster before ranking.** Group rows by customer and symptom from the summary (`Reuters` +
  freeze / stuck / flicker; `Cablevision` + black; `Hekayat` + feed not received). Several rows from one
  customer are often one symptom family. **A cluster is one item with one investigation**, not one
  nudge per row — a comment on every ticket is the failure mode this lane is meant to replace.
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

Evan's own open rows untouched for 30 days, mostly in Backlog, some untouched for years. These are
not cadence debt — nobody is waiting on them — and
they are not a fire. Left alone they make his own queue unreadable, which is what the KPIs are
measured against.

- **Three rows per run, oldest `updated` first** — the lane's `next_three`. A pile of any size clears
  at three a day; attempted in one sitting it clears in none.
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
| **waiting** | `mentions` rows with `answered: false`, oldest first | the thread's role from the assessment below (act · reply · FYI · none), with its reason. Product, QA and integration partners waiting > 1 working day rank at the top of act and reply | act or reply: the drafted action or a one-line reply (Evan posts it; the slack capability's `post` is dry-run and confirm-gated); FYI: one line under *FYI*; none: counted only |
| **monologues** | `unanswered` rows older than 24h | a spec or a question nobody picked up is a routing gap, not a Slack curiosity | name who should have answered → route, or "convert to ticket" → `$JIRA create --summary … --description …` dry-run |
| **decisions** | Evan's own replies in the 7-day window that rule something (Chinese cues: 先…再…, 不做, 不改, 我来, 就这样, 既然…; English: `Let's …`, `we will not`, `decided`) in threads whose text carries **no** Jira key | is it a durable decision others act on? | "record" → the ruling as a fact in `<elak>/knowledge/products/mediahub/` via Evan's word (a decision others act on is knowledge about the product, not a log of a conversation — (elak `blueprint/principles.md` P1), or `$JIRA comment <key> --text '<the ruling, verbatim, with the permalink>'` dry-run |

### 2a — what a thread needs from Evan

Every thread that reaches the brief through Evan — a mention, a tag, a cc, a thread he took part in — is
read to its latest reply and **assessed**. Being tagged does not make a thread his, and someone else
driving it does not make it not his: an unanswered mention read as owed drafts work in another person's
lane, and a driven thread read as settled hides a decision only he can make. The assessment gives one
role, with the reason in one clause:

| role | what it means | on the page |
|---|---|---|
| **act** | something only Evan can or should do: a decision, a routing, a ticket the product needs, a merge request of his | an item under *Needs you*, with the drafted action |
| **reply** | a question to him, or a correction only he can make, that nobody has covered | an item under *Needs you*, with the drafted reply |
| **FYI** | nothing to do, but something the product's technical lead should know: where an incident stands, a lead, a decision taken | one line under *FYI*: what to know, and who holds it |
| **none** | nothing to do or know: answered, outside his product, noise | left out; counted in the lanes table |

What the assessment weighs — inputs, not rules; any of them can be outweighed by another:

- **Who drives the thread**, and whether they are moving it. A driver who is moving it lowers the chance
  Evan needs to act; it does not settle it.
- **Whether anything asked of Evan is still open**, or someone else covered it.
- **Where the evidence points.** A defect shown in MediaHub (a component, a log line, a reproduction) can
  owe a ticket or a lane; a cause outside it (the customer's source, their network, a third-party product)
  usually owes none from him.
- **Whether something said is wrong** about how MediaHub behaves, which layer owns what, or what a release
  contains, checked against elak's knowledge, the map or the code. A claim ela cannot check against a
  source is not flagged; that call is Evan's.
- **Whether the thread touches his KPIs**: a ticket to break down, route or update.

The role is this skill's judgment and is written as such; Evan overrules it by answering the item. An
action on someone else's thread is drafted for Evan to send under his own name, and a nudge on the
driver's behalf is drafted only when the assessment finds the driver stuck and Evan the one to unstick it
(2026-10-26: a page drafted an incident ticket and a nudge on a customer audio thread support was
driving, where the evidence pointed at the customer's SDI source; the right role was FYI).

## 2b — yesterday, by case

The owner carries the product's technical responsibility, so the page opens its second half with what
changed, not only what waits. `ela yesterday --json` (the runner leaves it at
`<runtime>/runner/<date>-yesterday.json`; 72 hours on a Monday) joins by ticket key what moved in the window:
each case's Jira moves and comments, the commits naming the key (subject, body or branch, every checkout
under `<code>` as last fetched), the Slack messages naming it; then the commits and the discussed threads
that name no ticket; then ela's own jobs and applied writes, and Helm's auto-writes, which Jira shows under
the owner's account. A message or commit naming more than four keys is a list (release notes) and only
reinforces cases another source opened.

Write it as one short paragraph and at most eight case lines, under the heading `Yesterday`:

- The paragraph says what the day was, in three sentences at most: where the work moved (which features
  reached Review or Done, which lane got a release), what broke or was escalated, and the tracking gap.
- A case line is a case that asks something of the owner or that he would want to know as the product's
  technical lead: a fix that reached Review with nobody verifying, code that moved on a ticket whose Jira
  did not, a thread that turned into a decision, a priority raised, a ticket bounced back. One line each:
  key, what happened across the sources in one sentence, and the next step if any. Cases from other
  products' projects stay out unless a MediaHub ticket is in the same case.
- **Code without a ticket** is one line per repository with a count and the authors; when a branch of
  several commits carries no key, the line names the branch, and the drafted action may be a Slack nudge to
  the author asking which ticket it belongs to (the owner's rule: every change is tracked by a ticket).
- **Threads without a ticket**: a thread §2a rates **act** because the product needs a ticket (an outage
  shown in MediaHub, a customer ask, a decision) gets one line and a drafted `ela jira create` in the
  description standard; any other thread takes its assessed role.
- **ela** is one line: jobs run and failed, writes applied (with keys), Helm's auto-writes, and anything
  in them that looks wrong (a malformed Fixed In value, a write the owner did not ask for).

## 3 — rank and write
Order: triage OVERDUE → waiting (product / QA / partner, > 1 day) → cadence RED → incidents
(customer spoke last, or created inside 48h) → reports → breakdown → cadence YELLOW → incidents
(oldest cluster) → monologues → decisions → Evan's own tickets → backlog. Within a lane, oldest
first. `backlog` is always last and always three rows: it is the only lane that may be skipped
outright on a busy day. Then:

```
# Morning brief · Fri 2026-10-23

*7 items · read Jira and Slack; direct messages are not visible*

One to three sentences: what the day is about. Friday, so the brief is short. The one live customer problem
is Reuters.

## Needs you

### 1. Reuters feeds froze twice in two days
MH-3811 · Reuters confidence streams frozen · incident, new · Robin Wu holds it
- Both feeds froze for 23 seconds on 10-22; the same happened on 10-21 (MH-3805).
- Open lead: the shared decoder input ran at twice real time just before the stall.
- **Do:** `apply 1` records the findings on MH-3811, then probe MH-3805.

### 2. MH-3745: Jira is behind the release mails
MH-3745 · Search's recording blocks MediaHub's SRT receiver · Gabriel Liu (orchestration) · In Progress
- Fixed in orchestration 4.0.205; QA verified it on 10-22 and the daily release was requested (release mails).
- **Do:** `apply 2` posts that status and sets Fixed In.

## FYI

- Customer YouTube output loses audio · support holds it · the capture card reads audio at 0, so the
  customer's SDI source is the lead; nothing in MediaHub so far

## Yesterday

Two or three sentences, then at most five case lines (§2b).

## New tickets

| ticket | what | holder | owes |
|---|---|---|---|
| MH-3809 | two Packs could not push; China cloud capacity, resolved | Robin Wu | nothing; close on customer word |

## Lanes

| lane | today |
|---|---|
| In Progress, gone quiet | 3 silent over 48 hours (MH-3745, MH-3769, MH-3413) · 7 blocked · 102 untouched for 14 days |
| new and unassigned | none overdue · 8 recent tickets without a layer prefix |
| customer incidents | 54 open; Reuters freeze ×13 is the big cluster |
| needs a breakdown | 7 without sub-tasks; MH-3794 and MH-3795 first |

## Backlog, today's three

| ticket | verdict | why |
|---|---|---|
| MH-1555 | close | release checklists now live in the promotion threads |

*Not read: Slack direct messages; channels the bot has not joined (Reuters, FloSports).*
```

**Jira is kept true to the conversations: that is ela's job, not the owner's.** Before an item calls a ticket
silent, stalled or waiting, read what happened since its last Jira update: `ela slack search` for the key and for
two or three distinctive words of its title, and `ela mail search` for the key and for its service and version
words (`newer_than:14d`). Release and test mails often describe a fix without its key. When the conversations are
ahead of Jira, the item says so ("Jira is behind the release mails"), states what they say, and drafts the status
comment, plus Fixed In when a version is named, as its action, each source cited. A ticket is called silent only
when Slack and mail are silent too (2026-10-23: MH-3752 and MH-3745 were reported as stalled while their
progress sat in mail and Slack).

**Deployed is not a verdict.** An item that says a fix shipped also says the ticket's latest QA verdict and any
question left open in its last comments; a QA Fail after the fix is the item. A fix that shipped while QA failed or
a question is open, on a Highest or High ticket or one assigned to the owner, is a **deep pick**: at most two a
day, most urgent first, written to the deep file (§3b) and run after the page as `/ela:probe fix`, whose verdict
reaches to-read as its own note; the item says it is being read in depth. Any other ticket item may offer
`- [ ] go deep on MH-…` as a choice (2026-10-26: MH-2406's frontend fix was on prod-3, yet J2N there no longer
emitted the code it matched, and QA had failed it).

The page is read in Obsidian, so its form is fixed:

- **An item is a `###` heading in plain words** (what is happening, never a lane tag such as `[cadence RED]`), one
  facts line (key, its Jira title in a few plain words, kind, who holds it, age), at most three bullets, then
  **Do:** as one to three choices, each a task line he ticks in Obsidian: `- [ ] apply N — what it writes` for a drafted
  write (a tick runs it, as `apply N` in Slack does), `- [ ] <an instruction to ela>` for work a session does (a tick
  starts it: "probe MH-3805 from the 2× input replay", "draft the reply to Robin in the thread"), the recommended choice
  first. A choice is a whole instruction on one line; no "skip" choice (leaving it unticked is skipping). A sentence
  that does not change what the owner does is cut.
- **An `apply N` is a drafted action on this page.** Number the actions in the order they appear, every one
  written beside its item; never name an action that is not on the page ("apply 1 is done" from yesterday is
  noise). An action already applied is said in words, without its old number.
- **Instructions written in the vault.** Run `ela vault guidance --json` first: each line in a note starting
  `ela:` (in any note, unhandled) is something he asked; the Slack service normally acts on it within minutes, so
  one still listed here means it was not, and it becomes an item, or its drafted write an `apply N`. Append each id
  you handled to the log the command names.
- **One close path, named as such.** A close ela proposes goes through the board's batch (one confirm posts the
  proposals); a close the owner names is `close MH-…` in a session. `ela stage` reads a ticket's lanes; it closes
  nothing, so it is never written as the way to close.
- **A verification outranks a close.** Before an item or a table row says a ticket can close or be dropped, read
  its latest result under `<reports>/verify/`; a FAIL or BLOCKED after the fix is the item, not the close
  (2026-10-23: the page said drop MH-3416 while two of its verifications had failed).
- **At most eight items** under *Needs you*; the rest of the facts are in the tables below, one row each.
- **At most five lines** under *FYI*, each a thread §2a rated FYI: what to know and who holds it, no **Do:**.
  Beyond five, a count in the lanes table; the section is omitted when empty.
- **Every ticket key carries its Jira title** where it first appears on the page, in a few plain words, so the
  reader knows the ticket without opening it.
- **A ticket appears once.** A new ticket that is already an item gets no row under *New tickets*.
- **Tables, not code blocks,** for anything with columns; no nested lists; no bold paragraph labels.
- **Ticket keys bare** (MH-3811): the vault and the runner turn them into links. Slack threads and other pages
  are links with a short label.
- **Lanes in plain words,** as in the table above: never ela's internal names (cadence, zombies, triage, stage,
  runner page) on the page.
- **Under 900 words in all.** The decisions lane, when it runs, adds one table row per candidate with its
  permalink; the owner chooses which to keep.

## 3b — when the runner asked (unattended): the page and the numbered actions, written to files

ela-runner starts this skill headless every weekday morning after it wrote the facts page
(`/ela:brief --page <reports>/runner/<date>.md`). Then the output of §3 is written, not only printed:

- `<reports>/runner/<date>-brief.md` — the page of §3 as Markdown, the judgment included (what each new
  ticket is about, who should hold it, the drafted reply or nudge), then §2b's `Yesterday`, every key a Jira
  link.
  The page follows §3's form exactly and fits **900 words** (the vault marks a day page over 1,200 with a
  warning).
- `<reports>/runner/<date>-actions.json` — the drafted actions as a list, in the page's order:
  `[{"n": 1, "text": "<the one line the page shows>", "command": "<the exact ela command, dry run as written>", "kind": "comment|assign|label|transition|close|slack|fixed-in"}]`.
  A command is one of ela's own write verbs — `ela jira comment|assign|label|fixed-in|close …`, `ela slack
  post …` — complete with its key and text (a `--from-file` under `<reports>/runner/actions/<date>/`), and
  runnable as it stands; the runner appends `--apply` to it when the owner answers `apply <n>` in Slack or on
  the page. Nothing else goes in the list: a reading, a question for the owner, a hand-off to another skill is
  text on the page, not an action. The session itself applies nothing (the write scripts refuse `--apply` under
  `ELA_NO_APPLY`).
- `<reports>/runner/<date>-deep.json` — the day's deep picks, at most two:
  `[{"key": "MH-2406", "lane": "prod-3", "why": "<one line: what was claimed and what doubts it>"}]`; `[]` when none.

## 4 — what this skill does not do
- Post, comment, transition, assign, create, or write a file. The drafted actions name the skill
  or the jira capability's write atoms that will, behind their own confirm.
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
