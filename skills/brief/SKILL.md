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

## Modes: what to read before starting

This file is the core: the lanes, the judgment and the ranking, which every mode needs. The rest is in files beside
it (`${CLAUDE_PLUGIN_ROOT}/skills/brief/<name>`), and a mode reads its files **first**, whole, before §0. A file not
read is a rule not applied.

| how the skill was started | Read first |
|---|---|
| in a session, on his ask (`/ela:brief`, a focus lane) | this file; `page.md` before printing the full page |
| with `--page <facts page>`: the runner's morning judge, unattended | `unattended.md`, `page.md` and `files.md`; `meetings.md` when `ela day --json` names an enabled meeting with a time that day |
| by a prompt that names §reader: the evening read of the morning page | `reader.md`, and nothing else of this skill |

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
- **A held subject asks nothing.** The owner parks a subject with `ela: hold <subject or key> [until X]`
  (`ela focus holds` lists them; skills/focus/hold.py). `ela brief --json` already leaves held tickets out
  of every lane and names them under `held`; an item from any other source (a Slack thread, yesterday's
  cases, a mention) that names a held key or carries a held subject's words is left out the same way. The
  page says at most one line, `Held: N subjects (see the focus board)`, never the items again.
- **Nothing is written anywhere.** Not to Jira, not to Slack, not to the knowledge base. The brief is
  the day's view; tomorrow recomputes it.

## 0 — gather
**The saved facts are the input; the sources are not read again.** The runner's pass has already run `ela facts
refresh` and the facts verbs, and saved `<runtime>/runner/<date>-{brief,stage,slack,yesterday,changes}.json`, the
lanes table, the test and dev lists and the train (`<reports>/train/<line>.json`). The judge reads those files. A
verb it still runs (`ela jira read`, `ela slack history`, `ela mail search`, `ela promote constraints`) answers from
the fact store (`<runtime>/facts/`, `/ela:facts`) and prints its read time; that is one process, not a live call.
A fact the page needs and no file holds is a **gap**: the judge fills at most one per page with a single `--fresh`
read, names it in the page's gaps line (`gaps: read live — ela jira read MH-3871 --fresh, the comment after 17:00`),
and never re-reads what the files hold (elak `blueprint/decisions/2026-11-04-read-once-close-by-outcome-home-as-an-index.md`).

Read `~/.claude/ela/site.json` → `map`, `elak`, `published`. The Jira lanes are one call, already saved as
`<date>-brief.json` by the runner; run it only when that file is missing:
```bash
ela brief --json
```
Fields come out of that file, and out of any verb's `--json`, with `ela pick`, never an interpreter one-liner:
`ela pick --file <date>-brief.json` prints the shape, `ela pick 'lanes[].@key' .count --file <date>-brief.json` one
line per lane, `ela pick 'lanes.cadence.rows[].key' .status .assignee .flag --file …` one tab-separated line per row,
`ela pick --file <date>-actions.json --where n=3` one action whole (`ela pick --help`: `[N]`, `[A:B]`, `**`,
`--where K=V|K!=V|K~V`, `--count`, `--max N`).
For the per-row follow-ups (§1a, §1b, drafted actions) and the Slack lanes, bind:
```bash
JIRA="ela jira"
SLACK="ela slack"
TEAM="ela team"   # also: ela who …
```
The owner's standing constraints — pins and hand checks his rulings put on a lane, each with an expiry — are in
`<date>-changes.json` (`findings` of kind `constraint_*`) and on the lanes table; the verb itself
(`ela promote constraints --json`, exit 3 = a pin is over) is run only when neither file is there. A pin `over`, or a constraint whose `days_since_expiry` is
0 or 1 (it lapsed since the last brief), is an item under *Needs you*: what it says, the lane and version, its
source note, and the one move (roll back or ask the owner to lift it; renew or let it lapse). Otherwise it is one
row in the lanes table, "standing constraints: N active" (plus "N pins unread" when a pin's `state` is `unknown`).
A missing file is "none".

The owner's sprint is the commitment the page reports against. `python3 "${CLAUDE_PLUGIN_ROOT}/skills/brief/brief.py"
sprint --json` finds the active sprint note under `<vault>/sprints/` (front matter `type: "sprint"`, `status:
"active"`) and returns its goals and committed items, each with its keys and its "done when", the working day it is
on (`day` of `days`), and on a Friday the week's `<runtime>/runner/<date>-yesterday.json` files. `{"active": null}`
means no sprint is running. The note's own "where it stands" column is a snapshot from the day it was written; each
key's comments since the fix, its latest QA verdict and any open question are read from the saved facts (`<date>-
changes.json` tickets, the train's row, `<date>-stage.json`), and `$JIRA read <key>` (the store's copy) only for a key
none of them holds; what the owner already did on it is in `<date>-changes.json` `you`. Its **real status** follows the rule in §3 ("Deployed" is
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
| **intake** (every new ticket gets one pass) | `created >= -1d ORDER BY created ASC` — every ticket created since yesterday, whatever its status or assignee | `UNASSIGNED` · `NOPREFIX` (a sub-task without a layer token) · `EPIC-NO-CHILDREN` (a support escalation filed as an Epic) · `ENV-ONLY` (its summary names a lane and says that lane differs: an environment's problem, not a build's; the row carries a tier-3 `draft` labelling it `env:<lane>`, so the test list shows it under "Environment, not code" and no developer is asked to fix it) | one line per ticket on the page, always, even when nothing changes: what it is about in the reporter's terms, who holds it, and the one action it owes or "read, nothing to change". A ticket on the MH board concerns the owner by definition; the failure this lane prevents is a ticket he never saw. Flagged rows route to `/ela:route` or `/ela:breakdown`; its classification (component, `proto:`, the summary's `[Account]` bracket; jira SKILL, *Classifying a ticket ela processes*) is drafted here as one `apply N` per ticket |
| **cadence** (KPI: In-Progress updated within 24h) | actionable: `status = "In Progress" AND updated <= -24h AND updated >= -14d ORDER BY updated ASC` · zombies: `status = "In Progress" AND updated < -14d` (count and owners only) · `status = Blocked ORDER BY updated ASC` (Blocked sits in the To-Do category and is invisible to the first queries) | hours since `updated`: **RED > 48h · YELLOW > 24h**; zombies are one line, never items; Blocked always listed with its age | a one-line nudge to the assignee naming the one thing missing (status? blocker? ETA?), grounded in the last comment (`$JIRA read <key>`) → `$JIRA comment <key> --text '…'` (dry-run shown; `--apply` after Evan's word) |
| **triage** (KPI: routed within 4h) | `created >= -2d AND statusCategory != Done AND assignee is EMPTY` — new and nobody's yet. A separate hygiene line from `created >= -2d AND statusCategory != Done`: count the rows whose summary does not match `^\[(Infra\|UR\|J2N\|Media\|App\|UI\|QA\|Design\|AI)\]` (`J2N` for titles from before `[UR]` replaced it) — computed in the script, because Jira's `~` ignores punctuation and cannot test for the bracket | `created` age; **OVERDUE > 4h** | the layer and the name, with the discriminating check → `/ela:route <key>` |
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

The Slack facts are saved: `<date>-slack.json` (mentions, by the runner), `<date>-yesterday.json` (every channel's
history with threads for the window) and `<date>-changes.json` `dev_threads`. The verbs below are run only for a
window no file covers, and they answer from the fact store's per-channel cache (their read time on stderr):
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
| **proposals** | `lanes.proposals` (`ela brief --lane proposals`): mediahub-bot's knowledge proposals ela first saw in the brief's window (24h, 72h on a Monday), from the fact store — claim, evidence, source (a person in the thread, or a read the bot made), the thread link, the routes; `older` counts those seen before; `state` or `gap` says a route was not configured or not read | does the claim hold against elak's knowledge, the map or the code, and is it knowledge (what others act on) or one thread's circumstance? A claim from a read the bot made is checked against that read where ela can; one from a person is that person's word, said so | one class-D item per proposal worth his word: `- [ ] 记下来 — <the claim in elak's words> → <elak>/knowledge/<path>` and `- [ ] drop — <why>`, the recommended first; on his 记下来 the session writes the file in elak, then commits and pushes it under elak's commit rules (ADR 0026); a proposal that contradicts elak names the line it contradicts; the rest one line in the lanes table. A gap is in the page's gaps line, never "no proposals" |
| **decisions** | Evan's own replies in the 7-day window that rule something (Chinese cues: 先…再…, 不做, 不改, 我来, 就这样, 既然…; English: `Let's …`, `we will not`, `decided`) in threads whose text carries **no** Jira key | is it a durable decision others act on? | "record" → the ruling as a fact in `<elak>/knowledge/products/mediahub/` via Evan's word (a decision others act on is knowledge about the product, not a log of a conversation — (elak `blueprint/principles.md` P1), or `$JIRA comment <key> --text '<the ruling, verbatim, with the permalink>'` dry-run |

### 2a — what a thread needs from Evan

Every thread that reaches the brief through Evan — a mention, a tag, a cc, a thread he took part in — is
read to its latest reply (the replies are in the saved history; `$SLACK read <permalink>` is the one live read, for
a thread the files truncate) and **assessed**. Being tagged does not make a thread his, and someone else
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

The day's changes in full are a page of their own, the Changes page (`unattended.md`), read from `ela changes --json` (the
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

**One list of what needs his word, merged by key.** The items under *Needs you* come from these sources, read as
facts and never re-derived: this skill's own lanes (§1, §2); the findings of `ela changes --json`
(`<runtime>/runner/<date>-changes.json`, `findings[]`, each with its `rank`); the waiting lane (`ela brief --json`,
`lanes.waiting`, the F items, the vault's parked notes among them); the tracked tickets' changes (`lanes.tracked`, from the
runner's refresh log `<runtime>/runner/ticket-findings.jsonl`); the vault notes waiting for his `next` (Home's waiting table, `ela vault guidance`); mediahub-bot's knowledge proposals (`lanes.proposals`, §2);
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

**A parked note** (a live note carrying `waits-on`, wherever its thing lives; a row of kind `parked`) is a plan or draft the owner sent out and set aside
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

**QA today and Dev today are on demand** (the desk's from-zero brief, 2026-11-10: drafted every morning, they were
not sent). The morning page has no QA today or Dev today section, and no send box for them. When the owner asks, in a
session or a Slack DM to ela, the plan is built then: `ela testlist --lane <lane> --today --json` (QA's ranked day, cut
at ten, with the post text and the table) or `ela devlist --today --json` (the developers' cut, at most twelve rows).
His `ela:` lines (`drop KEY`, `KEY first`, `add KEY`, `KEY P1`) go back as `--guidance FILE`. The post is a dry run,
`ela slack post … --team-day-post` for the day post or in the build's release thread (the json's `post`), and it
leaves only on his word. A developer never reads QA rows, and QA never reads a developer's (Resolution B3).

**The unattended run's own rules** are in `unattended.md`: a change on a tracked ticket (`lanes.tracked`) and the two
build rules, the morning count, priority and due dates by rule, and what a train item or a customer incident owes
before it reaches the page. **The meeting sections** are `meetings.md`.

**Every section written for him ends with what he does.** An item and the
program's Next each end with a Do line (a meeting section's is its note's send box and rulings): an `apply N` or "your call: <recommended> over <alternative>
because …". `ela review lint` names a section or an item without one. *Why: a description is not a deliverable; every
answer ends with what he should do, what he can do, and how (working-with-evan.md, 2026-10-29).*

**Jira is kept true to the conversations: that is ela's job, not the owner's.** Before an item calls a ticket
silent, stalled or waiting, read what happened since its last Jira update: `ela slack search` for the key and for
two or three distinctive words of its title, and `ela mail search` for the key and for its service and version
words (`newer_than:14d`) — both answer from the fact store (the Slack cache; the standing mail searches), so they
cost no call and say their read time. Release and test mails often describe a fix without its key. When the conversations are
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
urgent first, written to the deep file (`unattended.md`) and run after the page as `/ela:probe fix`, whose page (real status,
dated timeline, next) reaches readings; the item links it (2026-10-26: MH-2406 sat assigned to the owner for eight days with QA's Fail naming the mismatched codes in its
comments; he traced the J2N–mediahub-frontend gap by hand).

**A field is Jira's value.** A status, assignee, Fixed In or version stated for a ticket is the value the facts page
read from Jira. A comment that names one is reported as what it is ("Helm Lookout's comment says …"), never as the
field. A drafted write to a field reads the field's current value first, and a write that would change nothing is
not drafted. *Why: on 2026-10-28 item 7 said MH-3829 and MH-3830 carried MH-3800's Fixed In; Jira held the field
empty on both, only a copied comment said so, and applies 14 and 15 would have cleared empty fields.*

## 3b — when the runner asked (unattended): the page and the numbered actions, written to files

With `--page`, Read `unattended.md` first, then `page.md` and `files.md` (Modes, above). `unattended.md` holds the
runner's day, QA's cycle, a second run on one date, the reader's findings as input, the counts, the `apply N`
numbers, the tiers and the files `<date>-brief.md`, `<date>-actions.json` and `<date>-deep.json`. `files.md` holds
the other files of the run: the build records, the Jira reconcile, the Changes page and the Friday page.

## §reader — the evening read of the morning page

Read `reader.md` first: it is the whole of this mode (the verdicts, the questions he asks back, the reader file and
its check, corrections, the audit of signed writes). The evening session ticks nothing, posts nothing and edits no
page.

## The page

The page's fixed form and its example are `page.md`: read it before writing or printing the full page.

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
