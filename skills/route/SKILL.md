---
name: route
description: Decide who takes a bug ticket, or who checks first; localise a prod failure from its trace id to the service that threw it. Use for triage, "谁该接这个", "这个归哪个服务", "who should take MH-xxxx", "先找谁查", a trace id or error code from prod.
user-invocable: true
---

# /ela:route <KEY> — a bug in, a name out (or the name who checks first)

Self-contained. Argument: a ticket key or URL, or a failure without a ticket — a trace id, an email
and a moment, an object id, a process id. Multiple keys → route each independently. A failure with a
trace or a moment starts at §0b; a ticket that carries one runs §0 and then §0b.

## Invariants
- **Read the ticket first-hand** (jira capability, `--deep`): the reporter's evidence — error
  codes, exact ids, timestamps, what was already ruled out — is the routing input; never
  re-derive what the report already measured.
- **Route on evidence, not on vocabulary.** An error message names its *thrower*, not its owner.
  Find the emitter in code before naming a person.
- **Owners are read, never remembered.** `route.py facts` (§0) reads the area and who to ask first;
  `ela who <name|email|Uxxx|accountId>` settles one person, exit 3 meaning the roster does not carry
  them, which is the answer and not a failure. The area's own registry
  (`mediahub-agent/workspace.json`) gives repo owners the published map does not.
- **Uncertainty is a first-class verdict.** When not certain, the output is not a guess but a
  *first checker*: the person whose single cheapest check discriminates the hypotheses — plus the
  exact check and what each outcome means. Never assign a guess as if it were a conclusion.
- **Read-only over repos; writes gated.** The re-assign is proposed as a dry-run
  (`jira.py assign`); `--apply` only after Evan confirms.
- **Read-only over other teams' runtimes.** Logs are read; log levels, restarts and config refreshes
  are the owner's to do, and appear in the handoff as a request, never as an action taken.
- **The goal is the service and its owner, not the line.** A failure localised to the service that
  threw it, with its owner and the likely causes, is a complete answer; a root cause at file:line is
  a bonus. Stop when the handoff card is filled, not when the bug is understood.

## 0 — read
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/route/route.py" facts <KEY> --json   # or: ela route <KEY>
```
```
{ticket: {key, url, summary, type, status, assignee, labels, parent},
 layer_token,                                   # the [Layer] in the summary, or null
 ids: {graph: [], process: [], object: []},     # 26-char · 32-hex · 19-digit, by regex from summary + description + comments
 signals: [{word, layer}], layer_hits: {layer: n},   # layer-classification.md's signal words found in the text
 services: [{name, kind, image, owners}],       # services.yaml names found in the text
 ask_first: {layer: [{area, ask_first: [{name, email, slack}]}]},   # the roster's first contacts per candidate layer
 gaps: []}                                      # what could not be read; each is named in the verdict
```
Exit 3: the ticket does not exist; 5: Jira unreadable. Signal words are vocabulary, not evidence —
they seed §1, they never decide it. Then read the ticket itself for what no script extracts: error
codes, timestamps, environment, what the reporter excluded, linked tickets (prior art):
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py" --env-file <env> read <KEY> --deep
```

## 0b — read the failure in the logs (a trace id, an email and a moment, a process id)

The logs are first-hand; a ticket's paste of them is a report. All reads go through `ela logs`
(`skills/logs/logs.py`, read-only; tvulog needs `ela login tvu`, exit 4 names it). Times print in UTC
and local; the java-log's clock is UTC, so `--at` is UTC unless an offset is given.

1. **The chain.** `ela logs chain <traceId>` lists every recorded HTTP hop of the trace, time-ordered,
   with the errorCode parsed from each reply, and marks the **first failing hop** — the innermost
   error, the one that answered first. From an email and a moment, `ela logs calls --email <addr>
   --at <time>` finds the call and its trace id; from a process id, `ela logs loki --pid <id>`.
   Then the services' own lines under the trace: `ela logs java --trace <id> --date <UTC day>`
   (`--grep <errorCode>` narrows; a stack's first `com.tvu…` frame is shown under the line).
2. **When the trace breaks** — the failing hop calls a service with no lines under the trace — the
   forwarding service is not the owner. Grep the code map for the error code or message (§1) to find
   the service that *throws* it, then read that service's own lines by name and moment:
   `ela logs java --app <appname> --at "<failure second>" --window 3s --grep <business id>`, with the
   business ids from the chain's params (peerId, objectId, mediaId). A service that did not receive the
   trace id logs under its own; the line's `trace=` is the pivot for the rest of its story. Absence
   under the trace is never evidence of absence: say which reads came back empty.
3. **A generic error code hides a swallowed exception.** When the thrower's code is a catch-all
   ("join failed", "system error"), read its log in the second before the reply for the warn or error
   line that carries the real reason, and find where the code catches it (the `catch` that logs and
   replaces the exception). That line is the evidence; the generic code is only the symptom.
4. **Runtime config.** When the code's decision turns on a configuration value (a config server key,
   `@ConfigurationProperties`, a refreshable map), name the key, the endpoint that exposes the live
   value if the code has one, and mark the cause *needs the owner to confirm the config*. Never guess
   the value, and never call a refresh or write endpoint.

## 1 — locate the seam in code (the map names the checkouts)

**Start with the derived dependency graph, not with grep.** `map/dependencies.yaml` holds every
app-layer call read out of the code at a commit, so it answers two routing questions directly and in
seconds:

```bash
DEPS="python3 ${CLAUDE_PLUGIN_ROOT}/skills/map/deps.py"
$DEPS show <endpoint or service or word>   # where is this called from — matches either side or an endpoint path
$DEPS callers <service>                    # who breaks if this service is wrong — the blast radius
$DEPS check                                # did any repo move since the scan? a stale graph is a wrong answer
```

An error message names an endpoint far more often than it names a service, and `show` matches the
endpoint — so a report quoting `/feign/getCurrentDevice` lands on the call site and its file, in one
call. `callers` is the other direction: when the symptom is a platform service misbehaving, its
callers are who else is already broken and who can confirm it fastest.

Two cautions, both load-bearing:
- **The graph is derived, and its scope is the app layer.** "No caller" means none among the repos
  the scan covers, never none in the platform. Say which of the two you mean.
- **`[owner?]` is the common case.** The platform layer has one recorded owner across 27 services,
  so the dependency graph locates the *code* and rarely the *person*; the owner still comes from the
  roster and `services.yaml`. An edge with no owner is a routing gap to name, not a dead end.

Then trace the symptom to its emitters — read-only grep across the mapped repos:
```bash
grep -rn "<error code or message>" --include=*.java --include=*.js --include=*.py <checkouts from `map.py find <name>`>
```
Distinguish **thrower** (where the exception text lives), **wrapper** (who repackages it into
the code the user saw), and **actor** (who performs the state change that made it fail — cleanup
jobs, caches, TTLs). Search linked tickets and code comments for prior art of the same shape —
a `see MH-xxxx` comment is a routing fact. Deeper digs → the read-only `analyst` agent, one per
repo, questions only.

### the owner of a service, in this order
1. `map/services.yaml` (`ela services`, `ela find <name>`) — the media docker services.
2. The web team's own repo-owner sheet, read live:
   `ela gdoc sheet 1Bska15E4RFxDjS62uRlG92deNqQ-ZzTOsrwqyIqK974` — the app-layer repos (tvu-media-hub,
   media-hub-front, mx-service, mx-service-front, tvucc-media, orchestration, mediahub-admin-frontend).
   The team's own list outranks anything derived, because the team maintains it (owner's decision,
   2026-09-29).
3. Otherwise the top committers of the last six months,
   `git -C <checkout> shortlog -sne --since=<6 months ago> HEAD`, labelled **most recent committer, not
   a confirmed owner**; `ela who <email>` settles who that is.

## 2 — verdict, one of three shapes
**Certain** (one service, its owner):
- service · owner · evidence (file:line of the emitter + the report's discriminating fact)
- the layer token that fits, and the dry-run:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py" --env-file <env> assign <KEY> --assignee <email|accountId>
```

**Not certain** (competing hypotheses across a seam):
- each hypothesis: actor · owner · what evidence supports it
- when a hypothesis is "the service downstream is wrong", `$DEPS callers <service>` names who else
  calls it: a second caller that is *not* failing is the cheapest discriminator there is, and it
  belongs in the first checker's question.
- **first checker**: the person whose ONE check discriminates — chosen by cost of the check, not
  by likelihood of the hypothesis. State the exact check (log grep for the recorded id, a DB
  lookup, a config read) and what each outcome routes to.
- the dry-run assigns to the first checker, with a drafted comment stating the question they are
  being asked to answer (`jira.py comment <KEY> --text …` dry-run; `--apply` only on Evan's word).

**Handoff card** (a failure localised from the logs, §0b) — what the owner needs to take the case:
- **service** (and env) that threw, and the hops that only forwarded it
- **owner**, with the source that named them (services.yaml · the team's sheet · most recent committer)
- **evidence**: each log line with its source (process-log · java-log · Loki), app, UTC time and trace
  id; the code line that throws, as file:line
- **likely causes**, ranked — log-backed first, then code-backed; each with file:line, and the config
  key and endpoint where a cause depends on runtime config (*needs the owner to confirm the config*)
- **incidental findings**: a swallowed exception, a trace id not propagated, a misleading code
- **drafted message** in the owner's language, for Slack or a Jira comment — a draft; nothing is posted
  without Evan's word (`slack.py post` and `jira.py comment` stay dry runs until `--apply`)

## 3 — confirm gate
Show the verdict and the dry-run. `--apply` only on Evan's explicit confirm, per the jira
capability's own gate. Never assign more than one person to one ticket — a second name goes in
the question text, not the assignee field.
