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
The owner's standing constraints — pins and hand checks his rulings put on a lane, each with an expiry — are one
call: `python3 "${CLAUDE_PLUGIN_ROOT}/skills/promote/promote.py" --env-file <env> constraints --json` (or `ela
promote constraints --json`; exit 3 = a pin is over). A pin `over`, or a constraint whose `days_since_expiry` is
0 or 1 (it lapsed since the last brief), is an item under *Needs you*: what it says, the lane and version, its
source note, and the one move (roll back or ask the owner to lift it; renew or let it lapse). Otherwise it is one
row in the lanes table, "standing constraints: N active" (plus "N pins unread" when a pin's `state` is `unknown`).
A missing file is "none".

The owner's sprint is the commitment the page reports against. `python3 "${CLAUDE_PLUGIN_ROOT}/skills/brief/brief.py"
sprint --json` finds the active sprint note under `<vault>/sprints/` (front matter `type: "sprint"`, `status:
"active"`) and returns its goals and committed items, each with its keys and its "done when", the working day it is
on (`day` of `days`), and on a Friday the week's `<runtime>/runner/<date>-yesterday.json` files. `{"active": null}`
means no sprint is running. The note's own "where it stands" column is a snapshot from the day it was written; each
key is read again first-hand (`$JIRA read <key>`): its comments since the fix, its latest QA verdict and any
question left open, and what the owner already did on it. Its **real status** follows the rule in §3 ("Deployed" is
a fact, never a status; a QA Fail or an open question after the fix is where it stands), never Jira's status field
alone. An item without a key (a pair of feed failures, a decision) is judged against its "done when" from the
day's other reads.

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

The day's changes in full are a page of their own, the Changes page (§3b), read from `ela changes --json` (the
runner leaves it at `<runtime>/runner/<date>-changes.json`): the lane moves, the builds and the commits each
carries, the release and QA mail, the release thread, the commits per repository and ticket for the MediaHub app
and Orchestration, what the owner did, what ela and Helm did, and the team report. The brief keeps only what
needs his word from it.

Under the heading `Yesterday`, write **at most three lines** and the link `[[<date>-changes|What changed]]`: what the
day was (where the work moved, which lane got a release, what broke), and the one or two changes that ask something
of him. A change that needs a drafted write (a nudge to the author of a branch with no ticket, a `ela jira create`
for a thread that needs a ticket, a Fixed In to correct) is an item under *Needs you* with its `apply N`; the
Changes page drafts nothing.

## 3 — rank and write

**One list of what needs his word, merged by key.** The items under *Needs you* come from five sources, read as
facts and never re-derived: this skill's own lanes (§1, §2); the findings of `ela changes --json`
(`<runtime>/runner/<date>-changes.json`, `findings[]`, each with its `rank`); the waiting lane (`ela brief --json`,
`lanes.waiting`, the F items, the vault's parked notes among them); the tracked tickets' changes (`lanes.tracked`, from the
runner's refresh log `<runtime>/runner/ticket-findings.jsonl`); the vault notes waiting for his `next` (Home's waiting table, `ela vault guidance`);
and the sprint items at risk or off (§0). A key that comes from several sources is **one item**. Its facts line
takes the most first-hand status: QA's verdict, then the version on the lane, then the Jira status. Its action is
the single strongest one: a drafted write, then a decision, then a reply, then a nudge. At most eight items; the
rest are rows in the tables below. The sources overlap by key (one ticket can be a finding, a waiting row and a
sprint row at once), and merging them is ela's work, not the reader's.

**Each item has one class and one action form**, so the owner knows what a tick does before reading the item:

| class | when | the action line |
|---|---|---|
| A | a write ela drafted and he approves | `- [ ] apply N — what it writes` |
| B | a note waits for his ruling | its `next` choices, named |
| C | someone waits on him | `- [ ] draft the reply to <who> in <where>`; he sends it |
| D | a decision only he can make | one `- [ ] <option>` per option, the recommended first |
| F | he waits on someone, past the threshold | the nudge drafted as `apply N` (§F) |

His own work is a sprint row, never an item.

**A change on a tracked ticket** (one with a probe `fix` page, in the sprint, routed by him, or with an `apply N`
pending) is read on two axes, by the closed list in `skills/probe/SKILL.md` §fix — a change on a tracked ticket:
understood means it matches one rule (Review on a branch whose commits name the key; QA's version and verdict;
Fixed In equal to the ledger's carrying build; an answer to a question the timeline holds; Done after a QA pass on
the lane's version; progress from the assignee or a developer on an In Progress ticket, asking nothing and naming no
new version; an assignment consistent with the status; a developer naming a version the ledger confirms), and anything
else is unsure, as is a developer reporting it still fails; a sure row whose furthest fix lane disagrees with the status
(on QA while Backlog, on prod while In Progress or before QA's verdict) becomes unsure with that reason. Understood and no word needed: a timeline row and a count on the
Changes page, never an item. Understood and word needed: one item, A or D. Unsure: one item, C or D, whose first
line says what ela could not place; on a prod ticket or a customer ask the runner also DMs him at the pass. Addressed
to him (his name, an assignment, a question): always a C item, whatever the reading. *Why: an item he cannot act on
costs his attention, and a change ela cannot place must never pass as a quiet timeline row.*

`lanes.tracked` holds these already grouped, one row per ticket over the brief's window (24 hours, 72 on a Monday):
`class` C when a change is addressed to him, its `first_line` who said what; D otherwise, its `first_line` "ela could
not place: <reason>". Each is one item with the moves a ticket page offers (seen, go-deep, nudge), merged by key with
any item the brief already has for that ticket. Sure rows are not on the page; the runner's *Tracked tickets* section
stays as their evidence.

**Two build rules** come through the same log (`rule` on the finding), read from the lanes' test lists once a day:
`qa-on-secondary`, a ticket assigned to QA that rides under another owner ticket in a build (its `linked`), drafted as
the tier-3 write the finding's `draft` names (reassign to its developer, the comment naming the owner ticket); and
`no-ticket-in-build`, a build's change-log line with no key, keyed by the build ("QA-AWS3 build 78"), drafted as a
tier-3 ask in that build's release thread for the ticket. This replaces the ad-hoc nudge for a build change with no
ticket. *Why: one fix, one owner ticket, assigned to QA when the whole fix is on the lane; a fix with no ticket gets
one before its build is announced (the 2026-10-29 test-list plan, Resolution C).*

**Order.**
1. Findings by their `rank`, 1 to 9: a hold asked from outside the company on a prod change; a standing pin over;
   a cell of the pending promotion awaiting his choice; a customer ask unanswered; a prod fix without a ticket or a
   prod build no QA report names; a hold asked by a colleague; then, only for services in this week's prod
   candidate, a QA build untested or moved after the run; then a change without a ticket on the way to prod.
   A finding with no `rank` is not an item: it shows in the lanes table only (○ and ▲), because QA lanes move
   several times a day. A hold from outside (`lane_change_pending_external_word`) is class C only when it is
   addressed to the owner (`to_owner`); addressed to someone else, it is an FYI line naming that person as its
   holder, and after one working day without a reply (`working_days_silent`) an F item with the nudge to the holder
   drafted. Its rank stays first either way: the prod change waits on it. *Why: on 2026-10-27 a customer-side hold
   on the Orchestration release was addressed to a colleague, not the owner, and was not his to answer.*
2. Sprint items at risk or off (D).
3. Triage overdue.
4. Class A.
5. Class C inside the company.
6. Class F, the longest silence first.
7. Class B.
8. Then the lanes' own order: cadence RED → incidents (customer spoke last, or created inside 48h) → reports →
   breakdown → cadence YELLOW → incidents (oldest cluster) → monologues → decisions → a standing constraint that
   lapsed (§0) → backlog. Within a lane, oldest first. `backlog` is always last and always three rows: it is the only
   lane that may be skipped outright on a busy day.

**§F — a nudge when he waits.** A waiting row whose `due` is true (two working days silent for a ticket he routed,
three for anything else) is an F item: the facts line says who it waits on and since when, and the action is the
nudge drafted as `apply N` — `ela slack post` in the thread or `ela jira comment` on the ticket, in English, the
person named by role in the text and mentioned for him to retype. A row not yet due is not on the page. **Review is
never read as verified:** Review is the team's "on QA, waiting for QA" state, so a ticket in Review whose QA
assignee has been silent past the threshold is an F item for QA (2026-10-26: MH-3808, MH-3821 and MH-3825 sat in
Review, moved there by their developers, with Fixed In set by Helm Lookout and no QA verdict yet).

**A parked note** (`<vault>/parked/`, a row of kind `parked`) is a plan or draft the owner sent out and set aside
until others answer; its `wake` names the ticket or Slack thread that brings it back, and the script reads those
(`checked`). A row with `woke` is one class B item, *Parked note woke: <title>*: the facts line is what woke it
(who, where, when), the action its `next` choices, *resume* or *drop*. A row that is `due` (three working days with
no movement, the owner's own word in the thread restarting the count) is an F item: the nudge drafted as `apply N`
to whom `waits-on` names, in the place it names. Before either, the note is not on the page. A row whose `checked`
is empty has a wake ela cannot read; it is an FYI line once due, asking him to name the ticket or thread.

**A decision has one note.** A later page that touches the same decision (a promotion review, the cadence
plan, a day page) links to that note and states only what changed. It never restates the note's tables. A note
that names bundles or versions says when it read them, and a note read after the lanes moved says so at its
top. *Why: on 2026-10-27 the HTML input pin was spread over three notes. One named the QA and Wednesday bundles
q26/d44 while the lanes page showed q28/d45, and two said "older" and "newer" about QA's media, each against a
different baseline.*

**The morning count.** Each item's facts line ends with the number of mornings it has been carried ("3rd morning"),
read from `lanes.carried` (`ela brief --lane carried`): the earlier brief pages, by key, or by heading for an item with
no key. A sentence elsewhere on the page that counts carried items ("three drafts are on their fifth morning") reads
the same count, and page-check flags one the facts lines do not bear out (2026-10-29: the summary said four on the
fifth morning; the items had three, and one on its fourth). An item on its third morning means the brief failed to make it tickable: that evening's run rewrites it as an
`apply N`, or drops it with one line on the next page saying why. The evening writes its verdicts to
`<reports>/runner/<next workday>-carried.json` (`[{item, verdict: rewrite|drop, command, why}]`), and the facts page
shows them under *Carried three mornings, rewritten last evening*. The morning mints each `rewrite` as an `apply N`:
its `command` goes into `<date>-actions.json` and its box onto the page under its item, so `ela page-check` passes.
Each `drop` is one line under the facts line, its `why`, with no box and no number, never an item. When page-check
fails and the runner asks for a rejudge, the judge reads the lines page-check printed (each orphan or unboxed number)
and either mints the missing action and box or removes the number, then writes the page again. *Why: items carried for days with nothing
he could tick became the page he stopped reading (from 2026-10-28).*

- **One `## <Name> at HH:MM` section per meeting the owner has that day,** right after *Needs you*, in time order.
  The meetings are data, not page logic: `<elak>/blueprint/meetings.yaml`, read by `ela day --json` (and in `ela brief --json` as `day.meetings`, each with its `section` heading), gives each meeting's `name`,
  `weekdays`, `time`, `audience` and `enabled`. A meeting that is not enabled, or has no time yet, renders
  nothing. Each section is his agenda for that meeting, in his speaking order, at most eight bullets. It adds no
  new facts: every line restates the page's own items, lanes table or sprint table, with the key or link that
  holds the evidence, so it costs the judge one more section, not one more read. A part with nothing to say is
  left out, never filled. Services are named by slug.

  **The PM scrum** (audience: product manager):
  1. **Sprint**, one line: `day N of M · x on track · y at risk`, then the at-risk item and what it needs, by key.
  2. **Releases this week**, one or two lines from the lanes table: what prod 3 runs (its bundle), what rides
     this week's train and when, and what is held and why, with the constraint or decision note linked (e.g.
     "mediahub-frontend held at 2.2.118: HTML input over MQTT is not finished").
  3. **What the PM will ask about**, at most two lines: customer tickets and Highest tickets that moved or are
     due, each with its key and its real status in one clause, never the Jira status alone.
  4. **What he needs from the PM today**, at most two lines: the D items whose decider is product, each written
     as the question he will ask (e.g. "Should the box-pool shortage code 0x81004009 show the friendly notice
     too? MH-2406").
  5. **What he commits to**, one line: the sprint items he carries himself and the date each lands.

  **The engineering, QA and UX sync** (audience: developers, QA, design):
  1. **The lanes**: what reached QA-AWS3 since the last sync and what of it no QA report names, as slug and
     version.
  2. **QA**: this week's fails by ticket, with the real status; Review tickets waiting on QA, by the version
     that carries them; the ones QA has held longest, with their age.
  3. **Engineering**: changes on a lane with no ticket, nightly-fix batches with no ticket, and Fixed In gaps,
     each as a count and the worst one by name.
  4. **UX**: tickets in Review with design or product, and open design questions on in-progress tickets.
  5. **What he needs from each group today**, one line per group with an ask, written as the question he will ask.
  6. **What he commits to**, one line.

  **After a meeting** the owner writes its rulings and answers as `ela:` lines under its section. The next pass
  (13:00) reads them as guidance, like any `ela:` line on the page: a ruling closes its D item and is recorded on
  the ticket or the decision note it names, as a drafted `apply N` for his tick.
  **On Friday** the day's meeting sections also open the Friday page (`<date>-week.md`), above `## The sprint`.
  *Why: meetings are where rulings are given and asks are answered. A page that carries the questions in his
  speaking order turns them into recorded rulings the same day, and a meeting he adds or moves is one line of
  data, not a change to the brief.*

**One place per day.** An item appears once. A key inside a lanes-table cell or a Changes page callout is evidence,
not an appearance.

Then:

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

## The lanes this morning

| | prod-3 | daily-wed | QA-AWS3 |
|---|---|---|---|
| media bundle | MediaHub 2.1.15 (2026-10-26) | mh2.1@daily-wed-s1-d44 (2026-10-26) | mh2.1@qa-q26 (2026-10-22) (list stale) |
| mediahub-frontend | 2.2.116+171 ○ | 2.2.116+171 ○ | ▲ 2.2.121+176 (was 2.2.119+174) ○ |

*3 more the same on every lane: …*

## Sprint

Sprint · day 5 of 10 · 8 on track · 1 at risk · 0 off

| item | where it stands today | on track for 6 Nov |
|---|---|---|
| MH-3768 generic MXL | merge request open for the app layer; J2N option name still unanswered | at risk: J2N's owner has not replied since 10-28 |
| MH-2406 Insufficient Resources UX | the mediahub-frontend change is in QA; no verdict yet | yes |

## Yesterday

At most three lines (§2b), then [[2026-10-28-changes|What changed]].

## New tickets

| ticket | what | holder | owes |
|---|---|---|---|
| MH-3809 | two Packs could not push; China cloud capacity, resolved | Robin Wu | nothing; close on customer word |

## Ticket lanes

| lane | today |
|---|---|
| In Progress, gone quiet | 3 silent over 48 hours (MH-3745, MH-3769, MH-3413) · 7 blocked · 102 untouched for 14 days |
| new and unassigned | none overdue · 8 recent tickets without a layer prefix |
| customer incidents | 54 open; Reuters freeze ×13 is the big cluster |
| needs a breakdown | 7 without sub-tasks; MH-3794 and MH-3795 first |
| standing constraints | 1 active, every pin held |

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

**A ticket on the page is read, not looked up.** Before an item states where a ticket stands, read its comments
since the fix, its latest QA verdict, any ticket a comment points to, and what the owner himself already did on it.
The item's facts line is then its **real status** in one sentence (it may contradict Jira: "Review, but it cannot
work"), and **Do:** is the next move with who it waits on. "Deployed" is a fact, never a status; a QA Fail or an
open question after the fix is the item. What the owner already did is stated ("waiting on the J2N owner since 10-26") and
never drafted again. A ticket whose QA observation contradicts what another layer's code expects (a code, a field,
a status), on a Highest or High ticket or one assigned to the owner, is a **deep pick**: at most two a day, most
urgent first, written to the deep file (§3b) and run after the page as `/ela:probe fix`, whose page (real status,
dated timeline, next) reaches readings; the item links it (2026-10-26: MH-2406 sat assigned to the owner for eight days with QA's Fail naming the mismatched codes in its
comments; he traced the J2N–mediahub-frontend gap by hand).

**A field is Jira's value.** A status, assignee, Fixed In or version stated for a ticket is the value the facts page
read from Jira. A comment that names one is reported as what it is ("Helm Lookout's comment says …"), never as the
field. A drafted write to a field reads the field's current value first, and a write that would change nothing is
not drafted. *Why: on 2026-10-28 item 7 said MH-3829 and MH-3830 carried MH-3800's Fixed In; Jira held the field
empty on both, only a copied comment said so, and applies 14 and 15 would have cleared empty fields.*

**What an item owes before it reaches the page.** A train item (a build riding the next promotion) carries the
`/ela:promote` assessment's verdict for that build (`ela promote report`: the stop and high findings) and the train's
departure time from the release cadence recorded in elak, or "departure not recorded" when none states it; the
apply is the hold or the promote post that verdict supports. Its QA facts cite the lane's test list (`ela testlist
--lane <lane> --json`): the P1 rows without a verdict, each by key and the reason it ranks P1, or "no P1 row open";
never "no QA report yet", which names a mail instead of what is untested. A customer incident addressed to him takes the first
deep pick, before any other pick and any Backlog item, and its item carries what the logs and the graph showed
(`/ela:logs`, `/ela:graph`), not an uninvestigated lead. *Why: on 2026-10-28 item 1 offered hold or promote with no
assessment and no departure time, and item 8 answered support with a lead nobody had read.*

The page is read in Obsidian, so its form is fixed:

- **An item is a `###` heading in plain words** (what is happening, never a lane tag such as `[cadence RED]`), one
  facts line (key, its Jira title in a few plain words, kind, who holds it, age), at most three bullets, then
  then **Do:** as one to three task lines, each finished work by ela, written by the action's tier (below):
  `- done N — what ela wrote · evidence: …` for a tier-1 action (a line, no box), `- [ ] don't N — at 10:00 unless
  you tick: what it posts` for a tier-2 one, `- [ ] apply N — what it writes` for a tier-3 one, or `- [ ] <option>`
  for a decision (class D), where the tick is the ruling. Ticking a box without `apply N` runs nothing, so its line ends with where the decision is
  taken: `· decide at the 10:00 scrum`, or `· your call, no write`; page-check flags a box with neither. *Why: on
  2026-10-28 items 1 and 7 offered four such boxes, and the page did not say that ticking them wrote nothing.*
  An item never ends in a question to him. An open point is written as ela's recommendation and the alternative,
  each with its reason, and the first box is the recommended write as `apply N`; `your call` is used only when the
  two are equal on the evidence, and the item says why. *Why: on 2026-10-28 item 5 asked whether MH-2406 stays with
  its assignee or goes to the frontend owner, and which frontend carries the notice, and drafted neither.*
  A Do line is never a command for him to run or a draft for him to write. A breakdown, a
  draft, a lookup or a probe is done before the 08:00 page, and the item carries its result: an `apply N`, or a link to the
  note it produced. When ela cannot do it unattended (it needs a login, a person to ask, or a judgment only he
  holds), the item says why in one line and offers no box. No Do line without a box. A deep pick runs in the same
  morning pass (§3b) and the item links its page, so an item never offers "go deep on MH-…". The recommended choice comes first; no "skip" choice
  (leaving it unticked is skipping). A sentence that does not change what the owner does is cut. *Why: on
  2026-10-27 the eight items carried 13 Do lines. He ticked the three apply lines and none of the ten commands or
  drafts left for him.*
- **An `apply N` is a drafted action on this page.** Number the actions in the order they appear, every one
  written beside its item; within an item the numbers ascend (a rerun that keeps applied numbers may leave gaps,
  never a descent: list a kept number before the new ones), and page-check flags a descent; never name an action that is not on the page ("apply 1 is done" from yesterday is
  noise). An action already applied is said in words, without its old number.
  A number is minted only when its drafted write is in `<date>-actions.json` and its box is on the page, beside
  its item. A table row, the backlog and an answer to a vault line never name a number without that box, and a
  number from another day is never cited. Before the page is written, `ela page-check <page> --actions
  <date>-actions.json` checks every `apply N` in it; a number with no action, or named without its box, fails the
  page. *Why: the 10-27 Backlog named apply 4, 5 and 6 with no boxes, and the 10-26 answers cited apply 9 and
  11–16, which never existed.*
- **Every drafted action has a tier.** Tier 1, ela acts at the pass that drafted it and says so: Jira only, under one
  of the closed rules `fact-comment` (a comment stating a fact, carrying its evidence), `label`, `fixed-in-ledger` (a
  Fixed In the builds ledger confirms; never a clear) and `assign-by-rule` (an assignment a closed routing rule
  gives); never a terminal status, a close, a transition or a customer-facing field. Tier 2, the runner sends it at
  10:00 unless he ticks "don't": `thread-reply` (a reply in a team channel's thread ela has read), `train-hold`,
  `train-promote`, each an `ela slack post <thread permalink> … --team-thread`, which slack.py refuses outside the
  team channels. Tier 3 is everything else, on his word only (`apply N`): customers, prod approvals, people,
  anything addressed to him, anything no closed rule admits. A tier-1 or tier-2 action carries `evidence`, one
  line he can check; a train action's evidence names the verdict build and its QA report (`ela day --json`
  `verdict_build`). Read `<reports>/review/tiers.json` first: a rule marked `demoted` (three corrections in seven
  days) drafts tier 3 until it clears. `ela page-check` checks each tier against its rule and its form on the page.
  *Why: 62 drafts in the week of 2026-10-26 and one applied; most were writes a closed rule could have taken
  (vault in-progress/2026-10-29-ela-three-loops-review.md, proposal 2).*
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
- **At most eight items** under *Needs you*, merged and ordered as above; the rest of the facts are in the tables
  below, one row each. An item is a facts line with its real status and one action line of its class.
- **The lanes this morning** is the table `ela matrix` printed, pasted as it is from the runner's facts page (the
  runner runs it after `ela changes`), under its own heading after *FYI*. It is not retyped or summarised: the same
  table is embedded in Home and must read the same in both places.
- **At most five lines** under *FYI*, each a thread §2a rated FYI: what to know and who holds it, no **Do:**.
  Beyond five, a count in the lanes table; the section is omitted when empty.
- **The sprint is a table after the lanes,** under `## Sprint`, from §0's sprint read. Its first line is exactly
  `Sprint · day N of M · x on track · y at risk · z off`; Home embeds that line. Then one row per goal and
  per committed item, at most nine rows (goals first, in the note's order). Columns: the item (its key and a few
  plain words, or the item's own words when it has no key) · where it stands today, its real status in one clause
  · on track for the end date: **yes**, **at risk** or **off**, the last two with one reason. A row is judged
  against its "done when" and the working days left, not against Jira's status. A sprint item that is also a
  *Needs you* item keeps its row, whose status cell points to the item ("see 2"). The section is omitted when no
  sprint is active.
- **Every ticket key carries its Jira title** where it first appears on the page, in a few plain words, so the
  reader knows the ticket without opening it.
- **A ticket appears once.** A new ticket that is already an item gets no row under *New tickets*.
- **Tables, not code blocks,** for anything with columns; no nested lists; no bold paragraph labels.
- **Ticket keys bare** (MH-3811): the vault and the runner turn them into links. Slack threads and other pages
  are links with a short label.
- **Services by their slug:** mediahub-frontend, mediahub-backend, unified-media-frontend, unified-media-backend,
  orchestration; a team name carries the slug once (UR Caller (unified-streaming)). Never "the frontend" or "the
  backend": unified-media-frontend is a frontend too, and the reader cannot tell which is meant. The same holds on the
  Changes page.
- **People by their roster display name** (`$TEAM who`), in prose, apply lines, FYI and tables alike: Andy Zhao,
  never the Jira or Slack name a read returned (Andyzhao). page-check flags a roster person written by their Jira
  name. *Why: the 2026-10-28 page wrote Andy Zhao in prose and Andyzhao in three apply lines, FYI and New tickets.*
- **Ticket lanes in plain words,** as in the table above: never ela's internal names (cadence, zombies, triage, stage,
  runner page) on the page.
- **Under 900 words in all.** The decisions lane, when it runs, adds one table row per candidate with its
  permalink; the owner chooses which to keep. Over the vault's day budget, page-check prints a `budget:` line
  counted the way Home counts; the runner's repair shortens the page, dropping nothing he must decide: FYI and
  Yesterday first, then sprint rows that only say "see N", then any meeting-section line that restates an item,
  which becomes "item N". *Why: the 2026-10-28 reader listed exactly these as what he would skip.*

## 3b — when the runner asked (unattended): the page and the numbered actions, written to files

**The runner's day** (ela-runner): 08:00 the morning page · 13:00 · 17:30, after the QA deploy · 19:00 the evening
(replay, the reader, the carried verdicts) · 01:00. The hours of the owner's day, his DM window and holidays are
`ela day --json`, never constants.

**QA's cycle.** QA-AWS3 receives a build around 17:00 and QA tests it until the same hour the next working day; the
report comes that evening, after 17:00 and often later, so the 17:30 pass may not see it, the 19:00 run usually does,
and the next morning reads it otherwise. On the morning of D, `ela day --json --date D` names `verdict_build`, the
newest build QA reported on (sent D-2, reported D-1 evening), and `under_test_build`, sent D-1, with the day its
report is `due` (an evening, never an hour). The lanes page lists the last three days' builds under its table. A
train item and every lane judgment use the verdict build; a Wednesday promotion is on Monday's 17:00 build. The build
under test is named as "under test · report due this evening", and is never "untested", "no QA report yet" or a
reason to hold a train: a hold is drafted only when the verdict build has a fail or a ticket gap. A report that
says the build's own focus went untested (`report.untested`, verdict partial) is such a gap, and the item names the
untested tickets. A build whose due
evening passed with no report (`report_missing_build`, "report not received" on the lanes page) is a gap to ask QA
about, not a fail. page-check flags a sentence that calls the build under test untested or unreported. *Why:
the 2026-10-29 page held the train because build 78 had no report, while QA was testing it that day.*

**A second morning run on the same date** rewrites the page, never the record of what was done. The actions already
in `<date>-actions.json` with `applied` or `by_owner` keep their number and text, and their item is not offered
again; new drafts take numbers after the highest one in the file, so an `apply N` he has seen never names a
different write. The carried count reads one page per date, so a rerun does not add a morning.

**The last reader's findings are input.** When the runner names the previous working day's
`<reports>/review/<D>-reader.json`, a `wrong` claim is not restated: the page states the fact from its source, or
leaves it out. A `handed-back` item's work is done first, within the run's deep budget, and the item carries the
result. *Why: without the findings reaching the morning, the evening reader only describes the page and the next
page repeats its faults.* A rerun writes
`<date>-changes.md` again from the same facts counts as the brief, so the two pages never come from different
runs. A "rewritten HH:MM" stamp is the clock when the file is written, never a planned time. A "since HH:MM" in the
opening anchors on the facts page's last line ("last morning page he could have read: <date>, in the vault since
HH:MM"), or is left out. ela-runner checks all three after the run (537d52e, c1d7113); the check is the backstop,
not the rule. *Why: the 2026-10-28 rerun left the Changes page at 06:41 and stamped a file written at 08:31 as
"rewritten 08:40".*

**Counts come from one file.** Every count on any page comes from the facts pass's counts (`counts` in
`<runtime>/runner/<date>-changes.json`, from `ela changes --json`), each with the window it covers: commits, commits
without a ticket, tickets moved, builds, lane moves, jobs, ela's writes, close-ready and verified-not-fixed (the
board's stage rows, the tickets open now, the verifications, each ticket's own page); the sprint's on track / at
risk / off from the sprint line. That means the brief, Changes,
the board, the sprint line and Home. A page never counts for itself. A count over another window is labelled with
that window ("commits, 7 days"). *Why: on 2026-10-27 close-ready read 32 on the board, 31 elsewhere and 35 on the
sprint; jobs read 16 on the brief and 19 on Changes; commits read 111/173 on one page and 79 on another.*

ela-runner starts this skill headless every weekday morning after it wrote the facts page
(`/ela:brief --page <reports>/runner/<date>.md`). Then the output of §3 is written, not only printed:

- `<reports>/runner/<date>-brief.md` — the page of §3 as Markdown, the judgment included (what each new
  ticket is about, who should hold it, the drafted reply or nudge), then §2b's `Yesterday`, every key a Jira
  link.
  The page follows §3's form exactly and fits **900 words** (the vault marks a day page over 1,200 with a
  warning).
- `<reports>/runner/<date>-actions.json` — the drafted actions as a list, in the page's order:
  `[{"n": 1, "text": "<the one line the page shows>", "command": "<the exact ela command, dry run as written>", "kind": "comment|assign|label|transition|close|slack|fixed-in",
  "tier": 1|2|3, "rule": "<a closed rule, or null at tier 3>", "evidence": "<one line; tier 1 and 2>", "channel": "<tier 2: the team channel's name>"}]`.
  The runner adds what it did: `applied` (a time), `vetoed` (the time he ticked "don't"), `failed` (`{at, error}`).
  A command is one of ela's own write verbs — `ela jira comment|assign|label|fixed-in|close …`, `ela slack
  post …` — complete with its key and text (a `--from-file` under `<reports>/runner/actions/<date>/`), and
  runnable as it stands; the runner appends `--apply` to it when the owner answers `apply <n>` in Slack or on
  the page. A file under `actions/<date>/` exists only for an action in the list: a draft the session abandons is
  not written, or is deleted before the run ends, and page-check names a file no action points to. Nothing else
  goes in the list: a reading, a question for the owner, a hand-off to another skill is
  text on the page, not an action. The session itself applies nothing (the write scripts refuse `--apply` under
  `ELA_NO_APPLY`).
- `<reports>/runner/<date>-deep.json` — the day's deep picks, at most two:
  `[{"key": "MH-2406", "lane": "prod-3", "why": "<one line: what was claimed and what doubts it>"}]`; `[]` when none.
- `<reports>/runner/<date>-changes.md` — the Changes page, from §2b's changes facts: a review of the day for the
  owner, not a list of what moved. The vault shows it as a day page beside the brief. Under **900 words**, in §3's
  form (a `#` title with the date, tables rather than code blocks, ticket keys bare, lanes in plain words):
  - It opens with the day in one line and what needs his word, if anything.
  - Then the sections, in this order: `## Releases and versions` · `## Docker services` · `## QA` · `## Code` · `## Tickets` ·
    `## What you did` · `## What ela did` · `## Team report`. Each opens with a one-sentence verdict; the facts
    under it are its evidence, folded in a `> [!note]- Evidence` callout, each with its source (a mail subject, a
    permalink, a build number, a sha). The page is evidence for the brief's items, so it reads in a minute folded
    and in full when opened.
  - **Releases and versions**: per lane, each move as `service old → new (#build, date)`, a patch build named as
    one, a build that reached no lane as "built, not deployed", and which of the window's commits each build
    carried. The release thread's per-build lines (the tickets each carries) outrank Jenkins for what reached a
    lane.
  - **Docker services**, from `docker[]`: each version that moved or was announced in the window, by slug (the
    name as announced when the map has no slug), with where it landed (a lane's bundle, a QA box, a default tag) and
    its source (bundle name, mail subject, the ticket comment). The tickets it claims follow it; a version announced
    with no ticket is said so in those words. A version whose ticket has no Fixed In is an item on the brief (the
    drafted Fixed In as `apply N`), not here. *Why: docker services are announced, not built from tracked commits,
    so the commit join that fills Fixed In for the app services does not reach them.*
  - **Code** is the largest section: per repository, per ticket (key, title, its commits, the thread that
    discusses it), then the commits without a ticket sorted into what is harmless, by category and named once
    (docs, review fixes, refactors), and the few that matter, each with why: a fix that reached a lane or prod
    without a ticket, a behaviour change riding under another ticket, correctness of billing or auth.
  - Where two sources disagree, the page says so (Helm's report calling a ticket verified while QA's mail
    tested the build before its fix).
  - **What you did** reports his own moves as done and never drafts them again; a Fixed In that Helm wrote
    under his account is Helm's (`ela.helm_fixed_in`), under *What ela did*.
  - **Team report** is one line and its Slack link; the report itself stays Helm's.
  - It carries no actions: what needs his word is an item on the brief, which links here for its evidence.
  A source the facts name in `errors` is named on the page as not read.
- `<reports>/runner/<date>-week.md` — **on a Friday, while a sprint is active**, the weekly page; the vault picks
  it up as a day page of kind week. It reports the week against the sprint, so that what the owner carried beside
  the list is visible next to what moved on it. Under **700 words**, in §3's form (a `#` title with the date,
  tables rather than code blocks, ticket keys bare, lanes in plain words), in three sections:
  - `## The sprint` — one row per goal and committed item: what moved this week, where it stands now (real
    status, read as in §0), and its "done when". The line above the table gives the day of the sprint and the
    count on track, at risk and off.
  - `## Outside the sprint` — from the week's yesterday files (§0's `week_yesterday_files`; a weekday with no
    file is named as not read): the cases outside the sprint's keys that took the owner's own time — his
    comments, his commits, the threads he answered, the tickets he broke down or routed — at most eight rows,
    each the key or thread and what it took. A last line counts the rest. This section is what makes the
    carrying-along visible; it judges nothing.
  - `## Next week` — what must happen next week for the sprint to land by its end date: per item at risk or
    off, the one move and who it waits on. On the sprint's last Friday it also gives the facts for the question
    the sprint's review answers: keep, change or drop the sprint.
  The page drafts no actions; anything to write is an item on the morning page.

## §reader — the evening read of the morning page

ela changes every week, so the owner's own use of a page is too little evidence to judge the workflow, and too
late. Every working evening a session reads that morning's page `<reports>/runner/<date>-brief.md` exactly as he
would. It reads under his rules (`working-with-evan.md`, the vault guide, the decision notes the page links) and
against the same sources the page cites. It writes `<reports>/review/<date>-reader.md`. It ticks nothing, posts
nothing and edits no page: its output is evidence for the next morning's judge and for ela's own review.

**Per item, one verdict and one line:**

| verdict | when | the line |
|---|---|---|
| tickable | he could tick a box within 30 seconds, without opening anything else | which box he would tick |
| question | he would have asked something back before acting | the question, written as he would ask it |
| handed back | the item leaves him work ela could have finished unattended: a lookup, a draft, a breakdown, a probe | the work, and the tool that does it |
| wrong | a fact the sources contradict | the fact, and the source that contradicts it |
| noise | state with no action for him: a row restated as an item, a parked note that has not woken, his own move reported back | why it carries nothing |

One verdict per item: the first that applies, in the order wrong, handed back, question, noise, tickable. A
wrong fact outranks everything, because he would act on it.

**The questions he asks back.** These are the shapes seen in the week of 2026-10-26. Each is a "question"
verdict when the page invites it:
- *Is this mine at all, or someone else's to answer?* An external hold or a customer mail addressed to a
  colleague was put to him as a reply to draft. The addressee test exists for this (§3 order, 2026-10-27).
- *Did you evaluate it, or only list it?* A finding reached him with no verdict on whether it needs him, when
  "FYI, held by X" was the answer (2026-10-26).
- *Which service?* "The frontend" or "the backend" when the product has several of each, or "a frontend
  version" for a change that also lives in UR Caller and a docker (2026-10-27, the HTML input change). Services
  are named by slug.
- *Did I say that?* A ruling read wider than he gave it. On 2026-10-26, "measure the sprint from 2.1.15" was
  read as "2.1.15 is the authority on every version".
- *What does this term mean?* A term from a code base or a vendor used without a clause of meaning (a field
  name, a placeholder in a config value).
- *Who has it now, and has anyone answered?* On a parked or waiting note (the RVF options for v3 Packs, parked
  on a customer thread, 2026-10-27), the item gave the draft again instead of the thread's state since.

**Then three lines for the page:**
- **Read first:** the item his eye would land on, and whether it deserved to be first.
- **Skipped:** what he would not read, and why (it was a table restated, a row he cannot act on).
- **Missing:** what he would have wanted that the sources held: a ticket moved, a thread answered, a lane
  changed, a number that did not add up.

**The next morning's judge reads it.** Before ranking, the morning session reads the newest
`<reports>/review/*-reader.md`:
- An item judged *handed back* is never offered in the same shape again. Either ela does the work before the
  page and carries the result as an `apply N` or a note link, or the item says in one line why it cannot be
  done unattended.
- An item judged *question* comes back with that question answered in its facts line. It does not come back
  as the same item with the same gap.
- An item judged *wrong* is corrected on the page, and says what was wrong yesterday.
- An item judged *noise* becomes a table row or leaves the page.

The page fails this rule when the same key carries the same verdict two mornings running. `ela brief --lane
carried` reports that next to the morning count.

*Why: on 2026-10-27 ten of thirteen Do lines handed work back, and every correction that week came from the
owner noticing it himself. A reader that runs every evening catches the shape before he has to.*

**The file and its check.** `ela review reader --date D` prints what the session reads: the page, its numbered
items, the day's actions, `<reports>/review/<D>-replay.json` and the page's lint failures. It also prints the keys
that already carry a repeated verdict. The session writes one table, `| item | verdict | line |`, with one row per
item: the item as `N. title`, a verdict from the five above, and its line. Under the table go the three page lines
as `- **Read first:** …`, `- **Skipped:** …` and `- **Missing:** …`. `ela review reader --date D --check` verifies the
file before the session ends: one verdict per item, each from the set and with its line, and the three page lines.
A failed check is fixed before the reader file is final. A passing check writes `<reports>/review/<D>-reader.json`,
the findings the next morning's judge takes as input: a list of `{kind, item, key, what}`, one per item read
`wrong`, `handed-back` or `question`, and one `skippable` for the Skipped line.

**Corrections.** `ela review replay` reads what happened after each tier-1 and tier-2 action the runner applied. A
field ela set and a colleague set otherwise (a label taken off, a Fixed In changed, an assignment moved within a
working day) is a correction, counted. A reply after a tier-1 comment or a tier-2 post is printed by `ela review
reader` as `judge action N`, and the reader judges it under a `## Corrections` heading, one row per action, `|
action N | contradicts / agrees / unrelated | line |`; the check fails an unjudged one. A reply that contradicts
is a correction on that action's rule. Replay and the passing check write `<reports>/review/tiers.json`: each rule's
corrections in the last seven days, and `demoted` once there are three, which the morning reads (§3).

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
