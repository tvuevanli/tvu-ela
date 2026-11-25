---
name: logs
description: Read a failure's logs first-hand — a trace id, an email and a moment, a process id. Use for "看日志", "这个 trace 在哪断的", "谁抛的这个错误码", or any failure whose evidence is in the services' own logs.
user-invocable: true
---

# /ela:logs <traceId | email and moment | process id> — a failure's logs, read first-hand

Self-contained. All reads go through `ela logs` (`${CLAUDE_PLUGIN_ROOT}/skills/logs/logs.py`); tvulog
needs `ela login tvu`, and exit 4 names it.

## Invariants
- **Small reads, one at a time.** A process-log or Loki read (`chain`, `calls`, `loki`) covers the last 5 minutes by
  default, or a few minutes around a named moment (`--at`; ±2 min for `chain` and `loki`, ±10 s for `calls`), with a
  server-side filter (`--grep`) and a small `--limit` (20); read the result before the next read. A wider window is
  read only with `--wide "<reason>"`, the reason naming why this case needs it (a ticket, the span the evidence leaves
  open); the tool prints it on the result (`wide` in `--json`), so the answer carries it. The limits on the shared
  log servers are mh-bot's to enforce; ela reads wide when the case needs it and says why (the owner's ruling of
  2026-11-24). No moment known is a reason to find one (the question, the thread, a status change) before a wide
  read. Loki's 4 hours per call is the server's ceiling, `--wide` or not; an unfiltered Loki read stops at 30
  minutes (MH-4049: a 16-hour pull, then four 4-hour pulls of 5,000 progress lines).
- **One service or one process, never all.** A Loki read names `--service`, `--pid`, or a `--query` with
  `service_name="…"` or ``process_id = `…` ``; an all-services query is refused, `--wide` or not. Loki is not a
  survey tool: which services ship, which boxes report, what a lane runs are read from code, config and the release
  records (2026-11-24: an all-services Loki read to list who ships, stopped by the owner).
- **Prove, don't sweep.** Before reading a range window by window, look for an invariant that covers it from two
  lines: libsrt socket ids fall by one per new socket (srtcore/api.cpp:315, v1.5.4), so the same id at both ends
  of a span proves no connection in between; `total N` on a `max_clients 1` listener says who was connected at
  that instant. In MH-4049 a planned 35-window sweep became two lines.
- **State at T is the last event before T with nothing unread between.** "No events in this window" is not "not
  connected"; a span nobody read is NOT checked.
- **Times in UTC, with the source's zone named.** `ela logs` prints UTC and local (UTC+8). An Outlook "Sent:" is
  the sender's zone and a screenshot header the viewer's; when a zone is unknown, carry both readings, check both
  and say which the evidence favours and why.
- **A running timeline, from the first read, not only at the end.** While an investigation runs, keep one table,
  `UTC | event | source | status`, oldest first: each event with the read that shows it, status `checked` (read
  first-hand), `inferred` (follows from reads, not read itself) or `NOT checked`, and every span nobody read as a
  `NOT checked` row of its own. Show it with each progress report; the answer's timeline is its last state. In Slack
  it goes in the detail as one fenced block with aligned columns, cells split by `|` and a divider row under the header
  (`---|---`), which `ela slack post` sends as Slack's table block (the fence stays when Slack refuses it); in a vault note, a table.
- **Read-only over other teams' runtimes.** Logs are read; log levels, restarts and config refreshes
  are the owner's to do, and appear in a handoff as a request, never as an action taken.
- **Absence under a trace is never evidence of absence.** A service that did not receive the trace id
  logs under its own; say which reads came back empty.
- **Times are UTC.** Output prints UTC and local; the java-log's clock is UTC, so `--at` is UTC unless
  an offset is given.
- **Only a box that ships its logs is in Loki, and a module's log is the media team's.** A MediaBox-version box
  ships its media containers' lines to Loki; another box ships none. An empty `loki --pid` therefore says nothing
  until a line from that same process (the named pid, at another moment) shows its lines reach Loki; a line from
  another process on the box shows only that the box ships. A media docker service's log (decoder, copier,
  encoder, mixer and the rest) is read and explained by the media team, whoever's tool read it: in Loki where the
  box ships, on the box where it does not, with the UR team's help only for access to the box. A handoff names the
  media team for it, not UR: UR can open the box but cannot judge the module's lines, so a handoff to UR adds a hop
  before the one reader who can.
- **A MediaBox process with no lines: its docker service's owner reads it on the box, UR opens the box** (the
  owner's rule, 2026-11-25). When `loki --pid` finds nothing for a graph's processes and they run as MediaBox
  containers (a wrapped image, a control port in `graph -d`), the thread mentions the owner of the suspect node's
  image (`ela find <image>` gives the owners, `ela who` their Slack id) with the graph, the process ids and their
  boxes, and copies the UR area's ask-first person (`ela team areas`) for access to the box. When no owner is on
  record, the UR lead is mentioned and routes it. Shipping is per site, not per box type: a physical box in TVU's
  own office ships its SDI lines, a customer site's physical boxes may ship nothing (a site firewall that does not
  pass the reporting ports).
  The SDI modules log as `service_name` `capture` (SDI in) and `render` (SDI out), files `capture_<pid>.log` and
  `render_<pid>.log`.
- **A chain is cleared node by node, upstream first, each on its own box.** Before a downstream node is blamed,
  the node feeding it is shown to produce (its own log lines, its frame or byte counters moving) or named unread;
  "no logs" is said of the process that was probed, never of the other nodes in the chain. The nodes of one chain
  (a `grid_decoder` feeding an `srt_copier`) may run on different boxes that ship differently, so one probe says
  nothing about the rest, and an upstream node left unread and taken as healthy sends the fix to the wrong owner.
  A node that is unread because its box ships nothing has one next read: its owner on the box, and where the owner
  has a bot of their own in the agent registry, that bot through `/ela:ask`, the owner copied.
- **Loki has a process's text, not every body it wrote.** The syncer ships only lines carrying the
  `[YYYYMMDD hh:mm:ss.mmm L]` prefix, so a multi-line body written without it (the copier's `sent metrics
  json: {`, `send SRT conn status: {`; decoderMediaBox's `…,json:`) arrives as its first line only. `loki`
  marks such a line `⟂ body not in Loki` (`body_cut` in `--json`), or `⟂?` when a `--grep` may have filtered
  the body out. Never read an empty result for those bodies as "no data": a copier's SRT statistics are in
  Observer's metrics history, not here (verified against the file on the box, 2026-11-05).

## The steps

1. **The chain.** `ela logs chain <traceId> --at "<moment>"` lists every recorded HTTP hop of the trace, time-ordered,
   with the errorCode parsed from each reply, and marks the **first failing hop** — the innermost
   error, the one that answered first. Without `--at` it reads the last 5 minutes; a trace whose day is
   unknown is read with `--since 2d --wide "<why>"`. From an email and a moment, `ela logs calls --email <addr>
   --at <time>` finds the call and its trace id; from a process id, `ela logs loki --pid <id>`.
   Then the services' own lines under the trace: `ela logs java --trace <id> --date <UTC day>`
   (`--grep <errorCode>` narrows; a stack's first `com.tvu…` frame is shown under the line).
2. **When the trace breaks** — the failing hop calls a service with no lines under the trace — the
   forwarding service is not the owner. Grep the code map for the error code or message (`ela find <error code>` over the checkouts, the step
   route §1 and probe §2 describe) to find
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
   `@ConfigurationProperties`, a refreshable map), name the key and read it:
   `ela configserver effective <app> <profile> --key <key>`, the profile found from the java-log's
   `env` (`ela configserver get <app> all --key elk.config.env`; the rule is in that skill); the value prints with the layer it came from, `(default)` or
   `(<profile>)`. When the key is redacted, absent from the config server (the code's default then
   applies — read it from the code), or not held there at all, name the endpoint that exposes the live
   value if the code has one, and mark the cause *needs the owner to confirm the config*. Never guess
   the value, and never call a refresh or write endpoint.

## Who uses this and when

A trace that breaks at a service boundary is common, and both callers need the chain to name the
service; they differ in where they stop.
- **route** — its goal is the service and its owner (coordination). Step 1 always; steps 2-4 only when
  the failing hop's service only forwarded the error and is not the thrower. It stops at the handoff card.
- **probe** — its goal is the root cause at file:line (knowing), which additionally needs the thrower's
  own lines and the swallowed exception. All four steps whenever the failure has a trace or a moment.

## The subcommands
```bash
ela logs chain --help   # process-log records of one trace, the first failing hop marked
ela logs calls --help   # process-log records around a moment for one service or user
ela logs java --help    # java-log lines by trace, or by app around a moment
ela logs loki --help    # Loki lines through Observer
ela configserver --help # step 4: a config key's value per environment (skills/configserver)
```
