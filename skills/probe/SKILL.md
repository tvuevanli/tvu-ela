---
name: probe
description: Read-only MediaHub code investigation — a bug to root cause with file:line, `probe how <mechanism>`, or `probe fix <key>` (does the shipped fix work on a lane). Use for "deep check", "go deep on MH-xxxx", "修复在 prod 上真的生效吗", "查一下根因", "看代码找原因", "why does copier …", "MH-xxxx 到底怎么回事", "这个字段哪来的", "命令行参数什么意思", "上报的数据是什么", "前后端模型", "谁调用谁", "这段逻辑在哪", "how does X work in the code", or when routing is not enough.
user-invocable: true
---

# /ela:probe <ticket | symptom> | how <mechanism> | fix <key> [--lane L] [--write PATH] — a bug in, a root cause with file:line out

Replies to the owner follow the working preferences (Chinese in conversation unless he asks otherwise); the
English of this file is not the language of the answer.

Self-contained. Argument: a Jira key or URL, a graph or process id, or a described symptom. Read-only
throughout: code is read, never changed; Jira and Slack are read, and every proposed comment is a
draft until Evan says post.

The `how` form takes a mechanism named in the owner's words (a command line, a reported field, a
status model, "who calls whom") and no ticket. It runs §0–§3 as written, skips the drafted comments
of §4, and ends with (a) the mechanism chain — each hop with file:line at the commit read, values and
defaults where the code fixes them, and what the chain does NOT assert — and (b) a `knowledge/` draft
written to `<runtime>/drafts/<slug>.md` in elak's house style (front matter `verified`, `source` =
repo@sha file:line only, no session or transcript cited, no names), for the owner to admit with
"记下来" (knowledge/README's one-year test).

The `fix` form takes a ticket whose fix is said to be shipped and answers one question: does it work on
the lane (default prod-3)? It is §fix below in place of §1–§4; "deployed" is a fact it starts from, never
its verdict.

## Invariants
- **Code before people.** The 2026-09-02 MH-3568 investigation found the cause in `addScteStream`
  defaulting to 1 only because it read the copier code instead of asking. Route only after the code
  has been read, or when the code cannot be reached — and say which.
- **Attribution by image, never by node name.** A graph node's `metadata.name` is a slot label and
  misleads (`input_srt_decoder_*` is not the SRT ingress). The image is the codebase fingerprint; the
  service table maps image → process types → owners → repos.
- **The checkout may lie about production.** Compare the image tag the graph reports with the
  checkout's branch/tag before trusting a line number; say when they differ.
- **Every claim carries a path.** file:line for code, key for Jira, permalink for Slack, the
  `graph.py` line for runtime facts. A claim without a path is a hypothesis and is labelled one.
- **Analyst for the reading, session for the judgment.** Code reading goes to the read-only analyst
  agent with specific questions; the synthesis, the product reading and the drafts stay here.

## 0 — bind
Read `~/.claude/ela/site.json` → `env`, `map`, `elak`, `published`.
```bash
JIRA="python3 ${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py --env-file <env>"
GRAPH="python3 ${CLAUDE_PLUGIN_ROOT}/skills/graph/graph.py --env-file <env>"
MAP="python3 ${CLAUDE_PLUGIN_ROOT}/skills/map/map.py"
TEAM="python3 ${CLAUDE_PLUGIN_ROOT}/skills/team/team.py --env-file <env>"   # or: ela who … · ela team areas
```
The owner §3 names is read at that moment, never recalled: the area from
`<published>/knowledge/products/mediahub/team/layer-classification.md`, the person from `$TEAM who
<name|email|Uxxx|accountId>` (exit 3 = not in the roster — say so, never compose a name) or `$TEAM
areas` for who to ask first; both read `<published>`, falling back to elak's private source on the
office machine. `<map>/services.yaml` still gives image → owners → repos.

## 1 — facts, in this order
1. **The report.** `$JIRA read <key> --deep`: reporter's evidence verbatim — ids, versions, env,
   what was ruled out. If the ticket names a graph, process or object id, or the reporter pasted a
   graph JSON, that is the anchor.
2. **The runtime.** `$GRAPH resolve <id>`: env, phase, nodes with type · process · image · box.
   `$GRAPH process <pid>` on the suspect node: status, error rates, container, shm. Write down the
   image tags — they pin the version under investigation. For the `how` form this hop is optional:
   run it when the owner names an id; otherwise say "not read at runtime" in the output.
3. **The implicated service.** `$MAP find <image|process type|service word>` → owners and repos with
   local paths. No repo → `$MAP probe media/<name> media/imatrix/prj/<name>` and, if it answers,
   `$MAP clone <path>` (GitLab, LAN, placed at `<code>/<alias>/<remote path>`). If nothing answers, the service
   goes to the routing step as "code not reachable" and the absent list gets an entry.
4. **The version.** `git -C <path> log -1 --format='%h %ad'` and tags vs the image tag from step 2.
- A trace id, an email and a moment, or a process id → the chain and the first failing hop
  (`ela logs chain`, `ela logs calls`), before the graph.

## 2 — read the code
Spawn the read-only analyst with the repo paths and **specific questions**, not "look for the bug":
which function decides the behaviour the reporter saw; what its inputs and defaults are; where the
default is set (config file, plugin xml, compile-time); what upstream would have to provide for the
other branch; what changed recently in that area (`git log -S`). Ask for file:line per answer and
the exact snippet. Read the answers against the report: does the code path explain every observed
fact? Anything unexplained is a second question, not a footnote.
- When the trace breaks at a service boundary, follow the log-evidence steps 2-4 (summary: find the
  thrower by error code in the code map; read its own lines at the failure second; read the swallowed
  exception behind a generic code; name the config key a cause turns on and mark it for the owner to
  confirm) — full text in `${CLAUDE_PLUGIN_ROOT}/skills/logs/SKILL.md`.

## 3 — conclude
Write, in this shape:
- **Root cause** — one sentence, then the mechanism as a chain (`source → … → symptom`), each hop with
  its file:line or `graph.py` fact.
- **Why it is designed that way** — read the intent before calling it a bug (the gate's rule on
  fences). Name the trade-off the default encodes.
- **What is affected** — who else sees this; is the reporter a special case or the first to notice.
- **Options** — the fix the reporter needs now, the product fix, the "real" fix; cost of each; which
  needs a product decision and from whom. A "should we fix it" answer reads the fix's cost in the code first
  (how many repositories, merge requests and owners, any new state) and states the consequence of not fixing,
  then recommends; MH-3675's first advice ("two small fixes") reversed once the code showed state in two
  repositories (2026-10-22).
- **Owner and check** — name and the exact discriminating check, via `/ela:route` when the layer is
  not obvious.
- A cause that turns on runtime config cites the value read with `ela configserver effective` and its
  layer; redacted or absent, it is stated as *needs the owner to confirm the config*, never guessed.

## 4 — record and draft
- Record what the probe **established**, not that it ran — drafted here, written on Evan's word: the conclusion and its paths go where the
  knowledge base's placement test sends them (elak `blueprint/principles.md` P1) — a platform
  finding to `knowledge/platform/<component>/`, an ela finding to `blueprint/`. A dated file of "what
  the probe did" is a diary and is not kept; the agentic-observability `investigation-*.md` files are
  a format precedent for the write-up, not a licence to keep the run.
- Drafts, each ≤ 8 lines, each a separate confirm: one for the reporter/product (what happens and
  what they can do now, no code), one for the owner (the mechanism, file:line, the question to
  decide). `$JIRA comment <key> --text …` shows the dry-run; `--apply` only after Evan's word.

## fix — does the shipped fix work on the lane
Worked example: MH-2406 (2026-10-26). The mediahub-frontend fix was on prod-3, but J2N at the prod-3 sha no longer
emitted the error code mediahub-frontend matched (refactored in March, split in September), and QA had said Fail
on 10-14; the contract change had never reached the mediahub-frontend team.
1. **The ticket's own word.** `$JIRA read <key> --deep`: the latest QA verdict (Pass/Fail and what failed,
   with the observed values), and any question left open in the last comments. A Fail after the fix is
   the lead, not a footnote.
2. **The linked tickets.** Every key in links, subtasks and the last five comments: read each for a
   contract it set or changed (a code table, a field list, a rename).
3. **The contracts the fix depends on.** Name each value that crosses a layer — error codes, response
   fields, statuses, enum values. For each layer the value crosses, find the version running on the lane
   (`ela release` → the build → its commit) and read the code at that sha: does the producer still emit
   it, under that name, and does the consumer match what is emitted? `git -C <repo> log -S<value>` dates
   when it changed and in which ticket.
4. **What the owner already did.** His comments, assignments and transitions on the ticket and the linked ones:
   the page reports them as done and never drafts them again.
5. **The page**, in this shape, under 600 words, people by name (it is the owner's own page):
   - `# <key>: <title> — <the real status in a few words>`;
   - **Real status**, one paragraph: what Jira says, what is true (*works*, *cannot work*, *blocked on <whom>*),
     and what, if anything, is the owner's to do;
   - **Timeline**, a table `| date | what happened | source | reading |`, oldest first, every layer's change dated (a
     commit, a build reaching the lane, a QA run, a comment, an assignment), including the days it sat unmoved;
     then one line on why it happened;
   - **Next**, who it waits on and since when, then the move after that; unread layers named as open;
   - at most three `- [ ] <instruction to ela>` lines the owner can tick (a nudge on a date, a reading, a draft).
   File:line evidence stays out of the page; it goes in a draft only when the owner implements or asks. A service is
   named by its slug (mediahub-frontend, unified-media-frontend, …), never "the frontend" or "the backend": the
   product has more than one of each.
- With `--write PATH` the page is written to PATH and the answer is one line. Nothing is posted.

### fix — a change on a tracked ticket
A ticket is **tracked** when it has a page from this form, is in the sprint, was routed by the owner, or has a
drafted `apply N` pending; any other ticket reaches him only through the brief's own lanes. Each change since the
last pass is read on two axes, *understood* and *needs his word*:

| the change | where it goes |
|---|---|
| understood, no word needed | a Timeline row whose `reading` names the rule; counted on the Changes page; never an item |
| understood, word needed | one item, class A (a drafted write) or D (his decision) |
| not understood | one item, class C or D, its first line saying what ela could not place; on a prod ticket or a customer ask, also a Slack DM at the pass |
| addressed to him (his name, assigned to him, a question to him) | always an item, class C, whatever the reading |

**Understood is this closed list**; a change is sure only when it matches one rule:
1. *A developer moves it to Review on a branch whose commits name the key* — the work exists in code, and Review is the team's "on QA" state; still never read as verified.
2. *QA comments a version and a verdict* — first-hand evidence bound to a build.
3. *Fixed In equals the carrying build in the release ledger* — the field agrees with what shipped.
4. *A comment answers a question the timeline already holds* — it closes a known open and opens none.
5. *Done after a QA pass on the lane's running version* — the close rests on a verdict for the build actually there.
6. *The assignee, or a developer on the ticket, comments progress on an In Progress ticket, asking nothing and naming
   no new version* — the work is moving under its owner; without this rule every progress note would be an unsure
   item. A comment with a question, a contradiction or a new ticket link still falls to unsure.
7. *An assignment consistent with the status*: to QA while Review, to a developer while To Do, Backlog or In Progress,
   or back to the reporter on Done — the ticket is moving along its own path. Two or more reassignments within a day are one
   unsure row ("reassigned 3 times in a day"): the ticket is looking for its owner. One to the owner stays addressed to him.
8. *A developer's comment naming a version or build the release ledger confirms carries a commit naming the key* — the
   fix reached a build, by evidence rather than declaration; the row is also Fixed In evidence for the drafter. A version
   the ledger does not confirm is unsure ("a version not in the ledger").

Rules 6 and 8 hold only for a comment that asks nothing and reports no failure; a comment saying the fix fails or does
not reproduce is unsure ("a developer reports it still fails").

**Then one cross-check on every sure row**: the furthest lane the ledger shows carrying the fix (prod over daily and
stage over QA) against the ticket's status. A fix on a QA lane while the ticket is Backlog or To Do, on prod while it is
In Progress, or on prod while it is Review with no QA verdict on the timeline, makes the row unsure with that reason
("fix on QA-AWS3, ticket Backlog", the lane as the lanes table names it), because the reason is the first thing he reads.

The reading is written `sure N: <short>` or `unsure: <what could not be placed>`; the owner's own change is `yours`, a
row and never an item. `ela ticket refresh KEY|--all` applies this list (Jira reads only).

**Everything else is unsure**, for example:
- a reopen — the fix failed somewhere ela has not read;
- a move backwards — someone disputes the state the page shows;
- reassignment to the owner — he now holds it, and it is addressed to him;
- a comment that contradicts the page's real status — either the page or the comment is wrong, and only he can tell;
- a status jump no rule covers (To Do → Done) — it skips the evidence the rules require;
- a reply in a customer thread — outside word, whose weight is his to judge;
- a new linked ticket — a contract may have moved under the fix (MH-2406).

## 5 — what this skill does not do
Change code, run builds, start or stop processes, post anywhere, or clone from GitHub when the LAN
GitLab has the repo (`map.py` clones GitLab-first; GitHub mirrors are read-only reference).
`probe how` does not price findings (that is arch) and does not decide support (that is feasible).
