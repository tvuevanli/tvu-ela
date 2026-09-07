---
name: sentry
description: Read crashes and errors first-hand from the self-hosted Sentry — the org's projects, the issue table worst first, one issue with its latest event's exception, stack and tags, and an issue's recent events with the box and version each fired on. Use when a symptom looks like a crash rather than a misconfiguration, when a module "restarts by itself", when a Sentry alert mail or a sentry link is pasted in chat, or for "有没有报错", "是不是崩了", "这个模块崩溃过吗", "哪台 box 在报这个".
user-invocable: true
---

# /ela:sentry — the crash nobody reported

Self-contained. Read-only: this capability has no write path, and none is to be added. Resolving,
ignoring or assigning a Sentry issue is the owning team's act, made in their own tool.

## Why it exists

MH-3571 states the problem: a module crashes leaving a minidump, **neither recovers nor reports it**,
and none of the three control planes — J2N, MediaHub, Observer — shows anything wrong. Every sense ela had reads
the control plane — a graph's state, a process's statistic, a ticket's status — and a process that
died and was restarted leaves all three green. Sentry is where that crash already is.

Evan receives Sentry alerts by mail, one message per event. A mail is one event: no count, no first
seen, no other boxes. The issue is the fact.

## Bind

```bash
SENTRY="python3 ${CLAUDE_PLUGIN_ROOT}/skills/sentry/sentry.py --env-file <env>"
$SENTRY projects [match]                             # the org's projects
$SENTRY issues [project] [--query Q] [--since 7d]    # the issue table, worst first
$SENTRY issue <id> [--frames N]                      # counts, first/last seen, the latest exception and its tags
$SENTRY events <id>                                  # recent events: when, which box, which version
```

`<env>` is `~/.claude/ela/site.json` → `env`. The deployment's URL and the token live there
(`SENTRY_URL`, `SENTRY_TOKEN`, `SENTRY_ORG`) — **no address belongs in this file or any tracked
one.** `--since` is Sentry's own `statsPeriod` vocabulary (`24h`, `7d`, `14d`), not ela's `--since`.
Every subcommand takes `--json`. Exit codes: 0 ok · 2 usage · 3 not found · 4 auth or no credential
· 5 remote error.

**Exit 4 with "no SENTRY_URL and SENTRY_TOKEN" is a state, not a fault** — say so plainly and move
on; it means the token has not been made yet, and `/ela:setup` says where it comes from.

## Invariants

- **An issue is not a bug.** A Sentry issue says something threw, how often, since when and where.
  Whether it is the bug the user reported is a separate claim, and it needs the times to line up
  with the report and the box to be one the report names. `events <id>` is what settles that; the
  `server_name` and `Version` tags are the columns that matter.
- **Frequency is the only ranking Sentry is sure of.** `issues` orders by level then count. Do not
  present a high count as severity, or a `fatal` that fired twice as an outage.
- **One box is not the platform.** An issue whose events all carry the same `server_name` is that
  box's problem until a second box appears; say which of the two the data shows.
- **A version tag dates the crash.** An issue whose last event is on a version no lane runs any more
  is history, not a live defect — check against `<elak>/map/release.yaml` and `ela versions`
  before routing it to anyone.
- **Read-only, and quiet.** Never resolve, ignore, assign or comment. If an issue should be someone's
  work, the output is a drafted Jira ticket through `jira create` (dry-run, `--apply` on Evan's
  word), never a change in Sentry.
- **The project slug is not the service name.** Sentry project slugs are their own vocabulary
  (`Receiver_78` for a receiver line); map them to a service through `<elak>/map/services.yaml`
  and say when you could not.

## Reading an alert mail into an issue

A Sentry alert mail carries the issue URL, whose last path segment is the issue id:

```
…/<org>/<project>/issues/<id>/     →  $SENTRY issue <id>
```

Read the issue, not the mail, before saying anything about how often it happens.

## What this capability does not do

- Write anything, anywhere in Sentry.
- Decide that a crash is the cause of a reported symptom. It supplies the crash; `/ela:probe` does
  the causal work, and the code is still the arbiter.
- Cover what does not report to Sentry. A C++ module that dies with a minidump and no Sentry SDK is
  invisible here too — that absence is a finding to name, not a silence to read as health.
