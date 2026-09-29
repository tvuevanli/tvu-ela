---
name: logs
description: Read a failure's logs first-hand — a trace id, an email and a moment, a process id. Use for "看日志", "这个 trace 在哪断的", "谁抛的这个错误码", or any failure whose evidence is in the services' own logs.
user-invocable: true
---

# /ela:logs <traceId | email and moment | process id> — a failure's logs, read first-hand

Self-contained. All reads go through `ela logs` (`${CLAUDE_PLUGIN_ROOT}/skills/logs/logs.py`); tvulog
needs `ela login tvu`, and exit 4 names it.

## Invariants
- **Read-only over other teams' runtimes.** Logs are read; log levels, restarts and config refreshes
  are the owner's to do, and appear in a handoff as a request, never as an action taken.
- **Absence under a trace is never evidence of absence.** A service that did not receive the trace id
  logs under its own; say which reads came back empty.
- **Times are UTC.** Output prints UTC and local; the java-log's clock is UTC, so `--at` is UTC unless
  an offset is given.

## The steps

1. **The chain.** `ela logs chain <traceId>` lists every recorded HTTP hop of the trace, time-ordered,
   with the errorCode parsed from each reply, and marks the **first failing hop** — the innermost
   error, the one that answered first. From an email and a moment, `ela logs calls --email <addr>
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
   `@ConfigurationProperties`, a refreshable map), name the key, the endpoint that exposes the live
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
```
