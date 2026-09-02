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
- **Owners are read, never remembered**: `map_sources.team_roster`, `<map>/host.yaml`, and the
  area's own registry (`mediahub-agent/workspace.json`) — in that order of specificity.
- **Uncertainty is a first-class verdict.** When not certain, the output is not a guess but a
  *first checker*: the person whose single cheapest check discriminates the hypotheses — plus the
  exact check and what each outcome means. Never assign a guess as if it were a conclusion.
- **Read-only over repos; writes gated.** The re-assign is proposed as a dry-run
  (`jira.py assign`); `--apply` only after Evan confirms.

## 0 — read
`~/.claude/ela/site.json` → `env`, `map`, `map_sources`. Then:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py" --env-file <env> read <KEY> --deep
```
Note: error codes, exact resource ids (graphId, objectId, processId — testers often record
them), timestamps, environment, what the reporter excluded, linked tickets (prior art).

## 1 — locate the seam in code (the map names the checkouts)
Trace the symptom to its emitters — read-only grep across the mapped repos:
```bash
grep -rn "<error code or message>" --include=*.java --include=*.js --include=*.py <checkouts from host.yaml>
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
- **first checker**: the person whose ONE check discriminates — chosen by cost of the check, not
  by likelihood of the hypothesis. State the exact check (log grep for the recorded id, a DB
  lookup, a config read) and what each outcome routes to.
- the dry-run assigns to the first checker, with a comment-ready sentence stating the question
  they are being asked to answer (Evan posts it himself; ela does not write Jira comments).

## 3 — confirm gate
Show the verdict and the dry-run. `--apply` only on Evan's explicit confirm, per the jira
capability's own gate. Never assign more than one person to one ticket — a second name goes in
the question text, not the assignee field.
