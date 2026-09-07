---
name: graph
description: Read a MediaHub graph or process first-hand from UR (J2N and Pilot) without choosing an environment — node table in pipeline order with each node's state, process ids, box ips, images and encoding profiles; one process's live record with its video/audio statistic; a box's capacity and load; a user's graphs; every graph an object ever ran in, stopped ones included. Use when the user pastes a 26-character graph id, a 32-hex process id, an object id, asks "这个 graph 跑在哪", "哪个 box", "process 是什么状态", "停掉的 graph 还能查吗", "encoding profile 是什么", "看下 graph", "ura", or needs the first hop of an incident from an object or graph id.
user-invocable: true
---

# /ela:graph — a graph or process id in, where it runs and what it is made of out

Self-contained. Argument: a graph id (26 chars, `01M1…`), a process id (32 hex), an object id
(19 digits, with the owner's email), or an email. Read-only: J2N and Pilot are only ever read.

## Invariants
- **No environment to set.** The script probes three UR environments in order — `prod3` (MediaHub
  2.1, which answers 2.0 too), `prod2` (older prod), `test2` — and stops at the first that has the
  data; `UR_ENV_ORDER` in the env file overrides the list, `-e p3` pins one. The **environment printed
  is the one the data says** (`app.tvunetworks.com/environment` on a graph, `env` on a process), not the
  path that answered: the prod environments share one J2N. Say both when they differ.
- **`-d` and `-c` are the detail views — progressive disclosure.** The default table (type · process ·
  public ip · private ip, pipeline order) comes from the one J2N read, about 2–3 s. `-d` adds control
  port, box location, box id and image per node — one Pilot call per node, run in parallel over warmed
  connections; `-c` lists the edges as connections with their shm types. Connecting to UR costs ~2 s
  of TLS, a request on an open connection ~1 s: that is the floor, not the script.
- **A deleted process still answers.** Pilot returns a 200 skeleton with every field `None`; the
  script treats that as not found. Say "no live record" rather than "does not exist".
- **Stopped is not gone — never answer "not found" for a finished job.** J2N keeps the graph after it
  stops, and three routes return it: `graphs/{id}/any` (used by `graph` always), `query_mode=any` on
  the v2 lists (`graphs --any/--deleted`), and v2's object/process routes (`resolve <objectId>`,
  `process <deadId>`). So an object the app shows as **Inactive** still has a full history: which
  graphs it ran in, when each ended and how long it ran. A stopped graph's node rows are the **last
  known** placement, not live — the script says so in the output, and so must the answer.
- **J2N v2 is not everywhere.** `/j2n/api/v2` answers on prod3 and test2 today; prod2 has no v2 (404).
  Everything v2-only — the object history, a dead process's graph, `--any/--deleted` — is therefore
  environment-dependent; the v1beta1 `/any` route works on all of them.
- **Declared vs running.** The image in the node row is what J2N declared (`options.dockerImage`); with
  `-d` the line below is what Pilot reports actually running (`imageVersion`). When they differ the
  script marks it — that is a deploy or promotion problem, not a graph problem.
- **An encoding profile is an id in the graph and a record in Pilot.** Encoder, copier and switcher
  nodes carry `profileId` only, and `-d` prints that id — the graph view stays one Pilot call per node.
  Reading the profile is a step of its own: `profile <id>` prints every field, `profiles <name>` searches. Pilot keeps five families under `/ep`: the two assembled ones (**single-tier** = one video
  + audio + stream, **multi-tier** = several tiers) and the three parts (**video**, **audio**,
  **stream**) they are built from. An id does not say which family it belongs to, so they are asked in
  turn; `/details` is what resolves the parts — without it a record carries the child ids only.
  The v2 EP API in Apifox (`/api/v2/ep/profiles`) and `encodingprofilecontroller`
  (`/profile/queryEncodingProfile`) are declared but do **not** answer on the UR edge — do not reach
  for them.
- **Two /ep gotchas, both verified live.** `pageIndex` is **0-based** there (asking page 1 of a
  one-row result returns `count: 1` with an empty `data` — it looks like a broken filter and is not),
  and `ids` is a **repeated** parameter (`ids=a&ids=b`), not a comma list. Single-tier holds ~11.9k
  profiles, so a listing is only useful with `name` or `ids`.
- **A box's occupancy is a table of owners, not a load figure.** When the question is a conflict or a
  leak — two objects on one SDI interface, a port that will not free, a graph deleted whose process
  never went away — the answer is `box <id> -d`, and it names the object and the person, because that
  is what has to be asked or told. Three shapes come out of it and they are different findings:
  **ORPHAN** (the port names a graph with no node on this box — the process is gone and the range was
  never returned), **UNCLAIM** (no process record and no declared usage, so nothing accounts for it),
  and **reserved** (a usage, no process — by design, and reporting it as a leak buries the real ones).
  A production box read on 2026-09-07 carried 147 occupied ports: 5 orphaned, 6 unclaimed, 78 reserved.
- **UR does not bind an SDI connector to a node.** The connector list and each connector's
  `statusBusy` are readable; the device number a process actually opened lives in that process's own
  command line, on the box. So `-d` gives the connectors and the SDI nodes, and the last hop is
  `$G connect <box>`. Never present a connector-to-object binding as read when it was inferred.
- **First-hand or nothing.** What UR does not return (a box's owner, a service's owner) comes from
  the map and the roster, and is cited as such.
- **Acting is Evan's hand, not the session's.** `connect`, `exec`, `start`, `stop` exist for the shell
  (`ela connect <id>` typed by Evan is the confirm; `start`/`stop` ask y/N). A Claude session never
  runs them on its own initiative — it proposes the command and stops.

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
| graph id | `$G graph <id>` | env, phase, owner email, object id, nodes in pipeline order (type · state · process · box ip), shm edges, errors per node. Stopped graphs included, with when they were deleted and how long they ran. `-d` adds control port, box location/id, the live process status, the running image and the encoding profile **id** per node (read it with `$G profile <id>`). `--all` lists every env that returns it; `--raw` the J2N body |
| process id | `$G process <id>` | env, type, status, graph id, owner, image, box id, control port, container, uptime, the video and audio statistic (codec, size, fps, bitrate, dropped frames, jitter), error rates 1s/8s/60s, shm names and local shm depths. A **stopped** process prints the graph it ran in and that graph's table instead of an error |
| profile id | `$G profile <id>` | which family holds it, then every field: video (codec, resolution, bitrate, fps, gop, cbr, profile@level, preset, tune, bframes, refframes, bpp, hdr, deinterlace, scale), each audio profile, and the stream profile's MPEG-TS pids. `--default` is the profile Pilot uses when a graph names none |
| profile name | `$G profiles <part of the name> [--kind single\|multi\|video\|audio\|stream] [--limit N]` | matching profiles per family, one summary line each — the way to find an id when only the name is known (from a UI screenshot or a ticket) |
| box id | `$G box <id>` | placement (type · cloud · region), state, cpu/mem/disk/shm with idle %, load 1/5/15m, agent and process versions, created/connected/heartbeat/last-disconnect, ports. **`-d` answers "who holds what"**: the SDI connectors with their busy status, every occupied port and every node placed there, each carried back to its graph, its object and the person who owns it |
| email or name | `$G graphs <email|name>` | that user's graphs: env, type, phase, object id, name. A full address is looked up as given (most UR users are customers, not on the roster); a bare name resolves through the roster (`robin`), never a composed address. `--all` walks every env, `--object <id>` keeps the graphs carrying that object |
| object id | `$G resolve <id> [-d] [--limit N]` | **every graph the object ever ran in** (v2, `query_mode=any`, newest first): id, env, business type, phase, process count, created, stopped and how long it ran — then the live graph in full, or the last one that ran when the object is Inactive. `$O get <id>` adds the object record itself (tangibles, owner userId) |
| email or name, history | `$G graphs <email> --any` (or `--deleted`) | the same list by owner instead of by object — v2's options route; the plain listing is live graphs only |
| anything | `$G resolve <id> [--email …]` | detects the shape and routes as above; `--email` is the fallback when v2 has no answer on the environments probed |

## 2 — the first hop of an incident
Someone pastes a graph id or an object card. Answer in this order, each line from a script call:
1. `graph` → env, phase, owner, object. If `phase` is not `Dispatched` or `errors` is non-empty,
   that is the lead.
2. Per node: type → **which service** (image name is the codebase fingerprint: `playeroftvu` decoder,
   `tvu264_all` encoder, `copier`, `agoraencoder` rtil) → **owner** from the roster; box ip for the
   person who will ssh.
3. `process <id>` on the suspect node: `status`, error rates, dropped frames, jitter, video/audio.
   A `running` process with rising error rates and a `Dispatched` graph points at media; a node with
   no process id (state `pending`) points at UR/J2N dispatch; `running ≠ declared` points at the deploy.
4. When the complaint is about picture or sound quality, take the node's profile id from `-d` and read
   it with `profile <id>` — codec, bitrate, resolution, gop — before anyone opens code.
5. Name one person and one check (`/ela:route` when the layer is not obvious).

## 2b — the job already finished
The reporter says "it stopped" or the app shows the object **Inactive**. `resolve <objectId>` still
answers: the history table gives the graph that was running at the reported time (match the
`stopped` column against the timestamp in the report), and its table gives the boxes and process ids
to look at in the logs. A 32-hex id from a log that no longer runs: `process <id>` names its graph.

## 3 — what this skill does not do
Start, stop or ssh on the session's own initiative (see the last invariant), or change anything. It
does not know bundles or which build is on which env — that is `/ela:release` (`ela bundles · versions · builds`).
