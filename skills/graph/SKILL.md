---
name: graph
description: Read a MediaHub graph or process first-hand from UR (J2N and Pilot) without choosing an environment — node table in pipeline order with process ids, box ips and images; one process's live record; a user's graphs; which graphs carry an object. Use when the user pastes a 26-character graph id, a 32-hex process id, asks "这个 graph 跑在哪", "哪个 box", "process 是什么状态", "看下 graph", "ura", or needs the first hop of an incident from an object or graph id.
user-invocable: true
---

# /ela:graph — a graph or process id in, where it runs and what it is made of out

Self-contained. Argument: a graph id (26 chars, `01M1…`), a process id (32 hex), an object id
(19 digits, with the owner's email), or an email. Read-only: J2N and Pilot are only ever read.

## Invariants
- **No environment to set.** The script probes UR environments in a fixed order — stable prod first
  (`prod8`), then `prod3` (MH 2.1), then `test2`, then the rest — and stops at the first that has the
  data. The **environment printed is the one the data says** (`app.tvunetworks.com/environment` on a
  graph, `env` on a process), not the path that answered: the prod environments share one J2N, so a
  prod8 graph also answers on prod3. Say both when they differ.
- **A deleted process still answers.** Pilot returns a 200 skeleton with every field `None`; the
  script treats that as not found. Say "no live record" rather than "does not exist".
- **First-hand or nothing.** What UR does not return (a box's owner, a service's owner) comes from
  the map and the roster, and is cited as such.
- **Never act.** No start, stop, connect or exec — those remain `ura`'s and Evan's hands.

## 0 — bind
Read `~/.claude/ela/site.json` → `env`. Then:
```bash
G="python3 ${CLAUDE_PLUGIN_ROOT}/skills/graph/graph.py --env-file <env>"
O="python3 ${CLAUDE_PLUGIN_ROOT}/skills/object/object.py --env-file <env>"
```
The env file carries `UR_ACCESS_KEY`, optional `UR_BASE_HOST` and `UR_ENV_ORDER` (comma list; overrides
the default probe order). Missing → `/ela:setup`.

## 1 — by id shape

| input | run | what comes back |
|---|---|---|
| graph id | `$G graph <id>` | env, phase, owner email, object id, nodes in pipeline order (type · process · box ip · image), shm edges, errors. `--all` lists every env that returns it; `--raw` the J2N body |
| process id | `$G process <id>` | env, type, status, graph id, owner, image, box id, control port, container, video codec/size, error rates, shm names |
| box id | `$G box <id>` | Pilot's box record |
| email | `$G graphs <email>` | that user's graphs: env, type, phase, object id, name. `--all` walks every env, `--object <id>` keeps the graphs carrying that object |
| object id | `$O get <id>` then `$G graphs <owner email> --object <id>` | the object (type, tangibles, owner userId) and its graphs. J2N lists by email and the object record has only the owner's userId, so the email is needed — from the Slack card, the ticket, or the roster |
| anything | `$G resolve <id> [--email …]` | detects the shape and routes as above |

## 2 — the first hop of an incident
Someone pastes a graph id or an object card. Answer in this order, each line from a script call:
1. `graph` → env, phase, owner, object. If `phase` is not `Dispatched` or `errors` is non-empty,
   that is the lead.
2. Per node: type → **which service** (image name is the codebase fingerprint: `playeroftvu` decoder,
   `tvu264_all` encoder, `copier`, `agoraencoder` rtil) → **owner** from the roster; box ip for the
   person who will ssh.
3. `process <id>` on the suspect node: `status`, error rates, container, video codec. A `running`
   process with rising error rates and a `Dispatched` graph points at media; a node with no process
   id points at UR/J2N dispatch.
4. Name one person and one check (`/ela:route` when the layer is not obvious).

## 3 — what this skill does not do
Start or stop processes, ssh to boxes, change anything. It does not know bundles or which build is
on which env — that is Helm's release module (future read through its API).
