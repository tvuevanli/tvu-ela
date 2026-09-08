---
name: route
description: Decide who should take a bug ticket — the service(s) implicated, the owner(s), and when it is not certain, who checks first and what exactly they should check. Use when a bug lands on Evan for triage, or he asks "谁该接这个", "这个归哪个服务", "who should take MH-xxxx", "先找谁查".
user-invocable: true
---

# /ela:route <KEY> — a bug in, a name out (or the name who checks first)

Self-contained. Argument: a ticket key or URL. Multiple keys → route each independently.

## Invariants
- **Read the ticket first-hand** (jira capability, `--deep`): the reporter's evidence — error
  codes, exact ids, timestamps, what was already ruled out — is the routing input; never
  re-derive what the report already measured.
- **Route on evidence, not on vocabulary.** An error message names its *thrower*, not its owner.
  Find the emitter in code before naming a person.
- **Owners are read, never remembered**, and the read is two hops: the **area** from
  `<published>/knowledge/products/mediahub/team/layer-classification.md` (symptom → area; it names no
  owner, on purpose), then the **person** from the roster capability — `ela who
  <name|email|Uxxx|accountId>` for one person, exit 3 meaning the roster does not carry them, which is
  the answer and not a failure; `ela team areas` for who to ask first about an area. Both read
  `<published>`, falling back to elak's private source on the office machine. `<map>/services.yaml`
  and the area's own registry (`mediahub-agent/workspace.json`) give repo and service owners.
- **Uncertainty is a first-class verdict.** When not certain, the output is not a guess but a
  *first checker*: the person whose single cheapest check discriminates the hypotheses — plus the
  exact check and what each outcome means. Never assign a guess as if it were a conclusion.
- **Read-only over repos; writes gated.** The re-assign is proposed as a dry-run
  (`jira.py assign`); `--apply` only after Evan confirms.

## 0 — read
`~/.claude/ela/site.json` → `env`, `map`, `published`, `map_sources`. Then:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py" --env-file <env> read <KEY> --deep
TEAM="python3 ${CLAUDE_PLUGIN_ROOT}/skills/team/team.py --env-file <env>"   # or: ela who … · ela team areas
```
Note: error codes, exact resource ids (graphId, objectId, processId — testers often record
them), timestamps, environment, what the reporter excluded, linked tickets (prior art).

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

## 2 — verdict, one of two shapes
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

## 3 — confirm gate
Show the verdict and the dry-run. `--apply` only on Evan's explicit confirm, per the jira
capability's own gate. Never assign more than one person to one ticket — a second name goes in
the question text, not the assignee field.
