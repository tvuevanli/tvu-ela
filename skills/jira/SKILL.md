---
name: jira
description: Jira read and search; writes are dry-run until an explicit confirm. Use for a Jira URL (tvunetworks.atlassian.net/browse/...), a ticket key (MH-1234, FB-9693), a subtask under a parent, "read this ticket", "what's in MH-xxxx", "create a subtask", "看看这个 ticket", "查一下 jira", "建子任务".
---

# Jira — read, search, and gated writes

The capability is `jira.py` — an L1 atomic CLI (subcommands, `--json`, exit
codes 0 ok / 1 API error / 2 validation). This file is the Claude-session
adapter; other callers (Helm ops, an MCP server) invoke the same script.

`python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py" --env-file <env> <verb> …` — `--help` lists the verbs
and their flags.

## read

Prints identity (type/status/priority/assignee/reporter/dates/labels/components/
parent), the description rendered from ADF, issue links, subtasks, attachments,
and every comment.

- `--deep` — after the issue, also print each linked issue, subtask, and parent.
  Use when the user asks about "related tickets".
- `--no-comments` — identity + description only; good for bulk reads.
- `--json` — raw fields + comments as one JSON object, for machine callers; `read_at` says when it was read.
  One field of it: `ela jira read KEY --json | ela pick fields.assignee.displayName` (`ela pick` with no path prints
  the shape; an interpreter one-liner is never needed for this).
- **The read serves the fact store.** `<runtime>/facts/jira/issues/<KEY>.json` holds one read per key; it is served
  while the store's last sweep (`ela facts refresh`: every MH issue updated since the previous sweep, with changelog
  and comments, `facts/jira/changes.json`) ran after that read and does not list the key as moved, and for half an
  hour after a read when no sweep followed. The store says so on stderr with the read time. `--fresh` reads Jira now.

## files

`files <KEY> [--id <attachment id>] [--out DIR]` writes the issue's attachments to disk
(`<runtime>/jira-files` by default) and prints the paths. Nothing is sent anywhere; the download
is local and `<runtime>` holds no records.

## jql

Key / status / assignee / summary rows. `--limit N` (default 50), `--json`. Two standing queries are served from the
store: the owner-name query (`assignee = currentUser() ORDER BY updated DESC`, limit 1, once a day) and the incidents
umbrella's open children; `--fresh` runs them now. Every other JQL is live.

## find

`find [PHRASE …] [--near KEY] [--project P] [--per 20] [--limit 10] [--fresh] [--json]`, read-only. A reference to a
ticket by what it is about (the async-API ticket, the observer one) is resolved with `find`, never by one keyword
search: the ticket meant rarely shares a word with the reference (MH-2564, Integrate Graph Submissions API, carries
neither 异步 nor async), but the ticket the reference came from (MH-3954) names its endpoint.

- Pass the words in both languages (`异步 async asynchronous`), the domain name the team would use if known, and
  `--near` the ticket the reference came from. Its summary, description and comments give the source terms
  (hyphen/underscore identifiers, the last literal segment of each endpoint path) and the keys it names.
- Ranking: your word ×3, source term ×1 — ×3 when the source writes it on the same line as your word (the source's
  translation: `异步接口 POST /api/v2.0/graph-submissions`) — summary carries one +2, named by the source +2, yours +1,
  the source's project +1. Every row prints its `why`.
- Show the top rows with their `why`; the owner picks when two are close. A miss is reported with the terms tried,
  never as "no such ticket"; then try the other language's word, or the endpoint or identifier the ticket would use.

## changes

`changes --since -24h|"YYYY-MM-DD HH:MM" [--project MH] [--limit N]`: each issue updated in the window with its
status, priority, assignee, label, Fixed In, type, resolution, link, parent and sprint moves and its comments. Served
from the store's sweep while it covers the window and is fresh (`read_at` in JSON); `--fresh` reads Jira now.

## assign — re-assign one issue, gated twice

Idempotent (already-assigned reports and exits 0), dry-run default showing `from -> to`; the
same confirm gate below applies before `--apply`.

## create — parent-level issue, gated twice

Same gates as create-subtask minus the token rule (a parent carries cross-layer scope, so its
title is free-form; single-layer tokens belong on subtasks). Idempotent against open issues in the
project with the same title. **Dry-run default; the confirm gate below applies before `--apply`.**

## The description (`create`, `create-subtask`)

`--description` is a Markdown subset rendered to ADF: `#`..`###` headings, `- `/`* ` bullets, `1. `
numbered lists, `**bold**`, `` `code` ``, links — `[text](https://url)` as a link on its text, and a bare
http(s) URL as a link on itself (never inside `` `code` ``). A line of three or more dashes folds
everything after it into a collapsed block titled by the words on that line (default "Technical detail").

**The standard, enforced by the script.** A ticket ela creates carries the sections its type requires,
above the fold, as `###` headings (a line that is only bold text also counts). The dry run prints
`standard ok` or what is missing; `--apply` refuses a nonstandard description unless `--nonstandard
'<reason>'` is passed, and that is passed only when the owner asked for a free-form ticket. The rule and
its reason are in elak `knowledge/products/mediahub/jira/conventions.md` § Description standard.

| type | required sections | optional |
|---|---|---|
| Bug | Problem · Steps to reproduce · QA verification (or Done when) | Cause · Change · Evidence |
| Sub-task | Scope · Done when (or QA verification) | Goal · Related |
| Task, Story, Improvement, New Feature, Epic, Project, Initiative | Goal · Scope · Done when (or QA verification) | Owner · Background · Not in scope · Related |

- **Problem** says what was seen, where (lane, build, account) and what should happen instead, in the
  reporter's words first. **Goal** says why the work exists and for whom. **Scope** is what changes, one
  bullet per lane token for a parent, ending with what is deliberately left out. **Done when** /
  **QA verification** is the criterion a reviewer can check without asking: numbered, each a step and
  its observable result. A ticket without one cannot be verified or closed by evidence.
- **English by default.** Bilingual on request or when the reporter wrote in Chinese: the English
  sections first, then one `### 中文` section with the same content; the check warns when Chinese comes
  first. Summaries are English.
- The fold (`--- Technical detail`) holds file and line citations, call sites and commit dates, and only
  on a ticket the owner implements himself; a ticket for another developer states what was reported,
  what was confirmed and what done looks like, at most a rough approach.
- Headings are for sections a reader acts on, never for emphasis. The owner rejected two drafts on
  2026-10-20 for reading like an engineer's note (MH-2281's follow-up).

The accepted Bug shape is MH-3797's; the accepted Sub-task shape is MH-3802's.

**Someone else's ticket** is not held to the standard. `describe` reports what the standard would want
as information only; a rewrite keeps the author's shape: bold paragraph labels stay bold paragraphs,
nested lists stay nested, and every link they posted keeps its text (`describe` refuses a draft that
drops one). When ela works such a ticket (verify, close, breakdown) and it has no criterion, the
criterion is added as a `### Done when` section appended after the author's text, on the owner's word,
never by rewriting what is there.

## A requirement is a project

One requirement is one ticket, carried in principle by one person from start to finish, who also owns its
coordination and its approach (the owner's word, 2026-11-10; elak `knowledge/products/mediahub/jira/conventions.md`
§ Description standard). Drafting a requirement with `create`:

- **One ticket, this level only.** The owner creates the requirement's ticket and nothing beneath it. ela does
  not break it into sub-tasks on its own; a sub-task is created only when the owner or the person carrying the
  ticket asks for it, with its lane and its person (MH-3983's `[UR]` and `[App]` sub-tasks, 2026-11-10).
  Sub-tasks do not move ownership off the parent: the carrier still answers for the whole.
- **Assigned to the carrier.** Once the person is named, the ticket is assigned to them. Until then it is assigned
  to the owner, and the description's `### Owner` section says *to be decided*.
- **The approach is a suggestion, attributed.** An approach in the description is written as a suggestion and
  names who made it ("Suggested by …"). The carrier has the final call, so the description never prescribes the
  method as scope.
- **Done when states the observable result, never the method.** Each numbered criterion is a step and what is
  seen, checkable on a lane without knowing how it was built.

## create-subtask — gated twice

**Safety gate (in the script, no caller can skip it):**
- the title must start with exactly one of
  `[Infra] [UR] [Media] [App] [UI] [QA] [Design]` followed by the action (`[UR]` is UR in the
  broad sense, J2N included) —
  no dash separator, no invented tokens;
- idempotent: an existing subtask with the same title is reported
  (`already exists: MH-XXXX`) and nothing is created — safe to retry;
- **dry-run is the default.** Without `--apply` it validates, resolves the
  assignee, and prints what would be created.

**Confirm gate (yours, in this session):** never pass `--apply` until Evan has
seen the dry-run output (or an equivalent listing of parent + title + assignee)
and explicitly confirmed. One confirmation covers the batch it was shown for,
nothing later.

Assignee defaults to the token's own account (the owner). Cross-layer scope belongs on the
parent ticket — a subtask carries exactly one token. **A ticket the owner asks for carries no
sub-tasks and is assigned to him**: he routes it himself; a sub-task is created only when he, or the
person carrying the requirement, names the lane and the person (2026-10-20, MH-3797; 2026-10-21; § A
requirement is a project).

## comment · transition · label · link · fixed-in · attach · detach · retitle · close · priority · due · version — the field atoms, gated twice

Each takes one or more keys (fan-out is one dry-run, one confirm), prints exactly what would change,
and does nothing without `--apply`. Each is idempotent, so a re-run after a partial failure is safe:

| atom | no-op when | how the write is chosen |
|---|---|---|
| `comment` | a comment with identical rendered text (whitespace-insensitive) already exists on the issue | the Markdown subset the description uses — `**bold**`, `` `code` ``, `[text](url)` and bare URLs as links, `- ` bullets, `1. ` numbered lists, `#` headings — above and inside the fold. **Two registers, one comment:** the lines before a `---` line are what a person reads (the verdict, the reason, what they are asked to do — three sentences); the lines after it go into a collapsed block titled by the words on that line (default "Technical detail": commit, build, ancestry, lane) for an agent or an investigator. **`@name` is a real mention**, resolved through the published roster to a Jira account id, else among the issue's own participants (assignee, reporter, comment authors) when exactly one of them matches the name — the dry run says which names came from the ticket; a name neither settles refuses the post (a plain-text name notifies nobody) — add the person to elak `people.yaml` and `ela publish roster`, or drop the `@`. The sentence addressed to a person comes first. `--no-mention` leaves `@` as text. **`--edit <id>`** replaces one posted comment's body: the dry run shows was / now, `--apply` writes it — the way to take a link or a wrong line out of a comment already posted, instead of a raw PUT |
| `transition` | the issue is already in `--to` | **A terminal status (Done, Cancelled, Failed, Closed Ambigous) is refused unless `--terminal` is passed**; a Claude session passes `--terminal` only when the owner named that terminal status himself in the session, one ticket per confirm, so a close he does not know about cannot happen (2026-10-21; opt-in 2026-10-22). The `close` bundle remains the way to propose a close for others to see. Otherwise the transition whose target status matches `--to` is looked up per issue; none → exit 2 listing what is reachable. With `--path`, an unreachable `--to` is walked along the lifecycle Backlog → In Progress → Review → Done one hop at a time, each hop looked up live (Jira exposes only the current status's transitions); the dry run names every hop and says the assignee is notified at each. It stops, without writing, at a hop that needs a field, and at Review → Done while the assignee is in the product area — that is the product sign-off (published `mediahub/jira/status-spec.md`), theirs to give |
| `label` | requested labels already present / absent | only the delta is sent (`add` / `remove` ops) |
| `link` | a link of that type already joins the pair in that direction | `--type` is a type name or a phrase (`blocks`, `is blocked by`, `relates to`, `contains`, `is contained in`, `implements`), resolved against the site's link types; **the phrase decides the direction** for every type (`MH-1 is contained in MH-2` makes MH-2 the container). The dry run prints the sentence on the target and as the other issue will show it; after `--apply` the link is read back, and one that does not read as asked exits 1 |
| `fixed-in` | every `--add` entry is already in the field | append-only union in the release map's grammar (`<slug>@<version>; …`): current entries keep their order, new ones follow; no entry is ever removed, because an older build stays a true record when a newer one is added. Each `--add` entry is checked against the map and refused with the reason: a slug the map does not know, a docker entry without its `<image>:<tag>`, an image name in the slug's place (the docker form is suggested); `--remove` is not checked. The value comes from `ela fixed-in <KEY>` (commit → carrying build), not from a developer's comment alone, and a docker entry always from `ela fixed-in` (its image index), never typed by hand; a value that disagrees with the rule is corrected by appending the right one and saying so in the comment |
| `attach` | a file of the same name is already on the issue | uploads one local file; the dry run names the file and its size. Used by `/ela:verify` for the self-contained QA record; the comment beside it names the file, never a link |
| `detach` | the attachment is already gone | removes one attachment by `--id`; only one this account uploaded (a reporter's evidence is refused). For a superseded copy of ela's own record — two formats of one report, an outdated version under another name |
| `describe` | the description already reads so | replaces one issue's description from a file, in the Markdown subset; the dry run shows was / now and names every link the current description carries that the new text drops, and `--apply` refuses while any is dropped (the reporter's links are theirs). The caller writes the new text in the ticket's established shape (Problem / Steps / Cause / Change / QA verification) and keeps the reporter's paragraphs where they stand |
| `retitle` | the summary already reads so | replaces one issue's summary; the dry run shows was / now. A sub-task's new title must still pass the layer-token gate of `create-subtask` |
| `close` | each step's own no-op | **a proposal, never a status change**: `--fixed-in`, `--label`, the comment (`--text` / `--from-file`), `flag:closing` and the ticket assigned to the owner, shown together as one dry run and applied in that order; the status is then his own click in Jira. Refused without a comment (`--allow-no-comment` overrides): the assignee and the reporter must see why. On a partial failure the dry run says which steps are done; a re-run skips them |
| `priority` | the issue already has `--to` | raises freely; lowering is refused when the changelog shows a person ever set the priority (a rule never overrides that word); `--why` posts the rule as a comment. Drafted under `priority-by-rule` (tier 3 until the owner promotes it) |
| `due` | the due date already reads `--date` | sets a missing due date only; a date already there is never moved; `--why` posts the rule as a comment. Drafted under `due-by-rule` (tier 3 until promoted) |
| `version` | create: the name exists · release: already released · set: the issue's Fix Version already has it | `create <name> [--release-date D]`, `release <name>`, `set KEY… --name <name>` (additive; a Fix Version is never removed) |

A refusal from this script is the answer, not an obstacle: never reach the Jira API another way to get past it.
When the rule itself is wrong, change it here in ela's repository, under ela's rules, and say so (2026-10-22,
MH-3645).

Confirm rule for a Claude session: show the dry-run, ask Evan, and only then re-run with `--apply` —
the same wording he saw. The unit of a confirm is **one ticket's bundle** — Fixed In, labels, the
comment and the walk — or **one batch of one shape**: when a rule the owner has recorded (elak
`knowledge/products/mediahub/jira/conventions.md` § Clean-up rules) selects the tickets and the same
text and the same steps fan out over all of them, the whole batch is one dry run, shown in full, and one
word applies it. A batch of mixed shapes is several confirms. This supersedes the 2026-10-19 wording
(one ticket, one confirm) for rule-selected batches only (2026-10-21); a hand-picked set of tickets is
still one confirm each.

## Classifying a ticket ela processes

Adopted 2026-10-23 for new tickets (the morning intake) and for any existing ticket ela processes for another
reason (a breakdown, a route, a revisit, a close); no batch pass over the board. The vocabulary is elak
`map/jira-labels.yaml`, read through the published map and rendered for the owner as the vault page
`ela/jira-vocabulary`; the design and its rulings are ela's knowledge in elak.

- **Feature:** the ticket's component, one primary, from the vocabulary's components, set only once that component
  exists in Jira (the owner creates them); until then the value is named in the draft, not written.
- **Transport or platform:** a `proto:` label when one applies; the gate in `label` refuses a value outside the list.
- **Customer:** the summary's leading bracket with the account's name from the vocabulary (`[Fox] SRT output drops
  after 2 h`); never a `customer:` label; sub-tasks do not repeat it.
- **Retired labels** stay on a ticket until the owner rules on removing them in the classifying edit.
- The classification is part of the edit ela already drafts for that ticket (one confirm), never a separate write.

## Credentials

Read `~/.claude/ela/site.json` → `env` (the path of ela's credential file, mode 600) and pass it as
`--env-file`. That file is ela's own — copied once from wherever the tokens lived before; nothing
here depends on another tool's config. The script reads only `JIRA_BASE_URL / JIRA_EMAIL / JIRA_TOKEN` from it. Missing or expired
→ run `/ela:setup`.

## Turning a ticket into knowledge

A ticket is a dated record of intent; a knowledge base holds what is currently
true. Do not paste ticket bodies into the knowledge base. Extract the durable
claim, state it as fact, record source (ticket key) + date + author, and mark
anything still unsettled as open. The conventions are those of
`<elak>/knowledge/`.

## Gotchas

- **A filename in a list is not evidence** (`read`, `files`). QA attaches the thing the ticket is
  about — a crash archive with a minidump, a screenshot of the wrong FPS, a log with the failing id —
  and a conclusion drawn without opening it is about the summary, not the bug. Attachments print
  with their **id** because that is what downloads them: `files <KEY> --id <id>`, then read it.
- **An email may not resolve** (`--assignee` on `assign`, `create`, `create-subtask`). An email must
  match exactly one Jira user or the call fails, and most users hide their address; pass the
  accountId (visible in `read --json`), which resolves directly.
- **A bilingual description is one source** (`read`). MH descriptions are often 中文 then English; the
  two halves are the same content, not two sources.
