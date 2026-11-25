---
name: facts
description: The fact store, every source read once per pass into <runtime>/facts/. Use for "refresh the facts", "how old are the facts", "事实库", or a page whose facts line is older than the pass.
user-invocable: true
---

# /ela:facts — read once, analyse many

`ela facts refresh` runs first in every pass (the runner calls exactly `ela facts refresh --json`, then
`ela train --line <line> --write --json` per followed line; a field of any `--json` or of a store file is read with
`ela pick <path> [--file F]`, no path for the shape). It reads each source forward from its watermark into
`<runtime>/facts/<source>/`, one directory per source, every entry stamped with its read time:

| source | what one refresh reads | the store serves |
|---|---|---|
| `jira` | MH issues updated since the last watermark (first fill 14 days), raw with changelog and comments → `changes.json`; the key cache `issues/<KEY>.json` re-read only for keys the sweep says moved; the standing queries (`queries/incidents.json`; `release-must.json`, every ticket labelled release:must; `fixed-in.json`, every MH ticket with a Fixed In updated within 120 days, its Fixed In with the row; `board-state.json`, every MH ticket Blocked or In Progress now; `owner.json` once a day) | `ela jira changes`, `ela jira read`, the incidents and owner-name JQLs, `ela recent`'s week, `ela release next`'s must and in-development rows, promote's Fixed In lookups under facts-only, the team report's blocked and carry-over rows |
| `slack` | every channel the bot is in: parents over the last 8 days (so a reply to an older thread shows on its parent), then the replies of each thread that moved; the channel list and the user names | `history`, `mentions`, `unanswered`, `search`, `channels` — the one per-channel cache (`<runtime>/slack-cache/` moves in once) |
| `mail` | the standing searches over a rolling 21 days — `subject:Release`, `subject:("test report")`, `in:sent`, and `team` (the roster's QA area under any subject, and the service, image and deploy subjects) — ids newest first, only the ids not yet stored fetched | `ela mail search` for any query inside one of the first three; `ela teamreport` reads `team` with the first two; every other query lists ids live and fetches only unstored ids; `read` always; `thread` while fresh |
| `lanes` | `release envs` on every host (qa, prod, and the China region's cn in a file of its own, `envs-cn.json`; a site without its names or a map without its ids is a state in the pass line, not a gap) and `release gateway`, once | `ela release envs|gateway`, promote's host read, stage's lane signature, fixed-in's lanes |
| `builds` | Jenkins, 80 builds per mapped job; the bundle lists per line on qa and prod, each line's daily-lane list, and the China host's own list under `bundles/cn/`; then the details (each image's tag) of each line's two newest daily bundles, three newest plain officials and the candidate `ela release next` holds | `ela builds`, `ela bundles`, promote's build and bundle reads, `ela release next`'s base and candidate |
| `code` | `git fetch --all --prune` in each service repository the release map names (`release.yaml` `repos`) that is cloned under `<code>`; nothing is copied, the watermark holds each repo's outcome | promote's commit ranges and `ela release next`, which then fetch nothing |
| `proposals` | mediahub-bot's knowledge proposals (each marked `mhbot-knowledge-proposal v1`): the replies under the bot's daily parent in its proposals channel over the last 8 days, through the Slack store, and the JSON files in its `data/knowledge-proposals/` directory when it is on this machine; site.json `knowledge_proposals` → `{"channel": <id>, "dir": <path>}`, either left out = that route not read (a state); a route set and unreadable is a gap and the other is still read; one record per claim (the bot's own claim key), with the routes it came by and when ela first saw it, kept 60 days | the brief's `proposals` lane, `ela facts proposals show [--hours N] [--json]` |
| `runtime` | per followed lane (release.yaml lines, daily and prod) and per config-server service (each repo's own `bootstrap.properties`): the lane's profile (`elk.config.env` = the lane token), the instance the java-log shows running it, the profile chain a graph proved (`ela facts runtime prove <graph>`: its trace → the UR Caller instance that created it, its processes → the gateway that bridged them), and the keys whose value differs between the lane profile read alone and that chain; the initConfig the owner's browser session received (`ela browser env`, kept under the lane the version panel proved, keys and non-secret values only) | `ela facts runtime show`, promote's configuration section, `ela configserver effective <app> <chain>` |

A verb serves the store while the source's watermark is younger than `ELA_FACTS_MAX_AGE` hours (default 6) and
says so on stderr with the read time. A gap (a host that refused, Jenkins down) keeps the previous content and is
recorded in the watermark; the serving verb then answers as the live read would (the lanes' exit 4, an empty
list) and names the last good read. A host login refused as not admitted is said in the gap (`cn: exit 4, account
not admitted (0x80060018)`). The qa host is not read at all (release `SKILL.md`): its lanes come from QA's report
mails and the release channel. `ela facts status` prints each source's
time, freshness, size and gap.

A chain is proven only by a graph bound to its creator and its gateway; until one is, the row says "last layer
proven, earlier layers unproven" and a reader states configuration as the lane profile's alone, unproven. Decision:
the 2026-11-09 daily-wed → prod-3 promotion, where `mx_service_wed` read alone gave `mediaBox.viaGateway=false`
while daily-wed's UR Caller ran `default → mx_service_test → mx_service_wed` (proven from graph
`01M6ZB6FVC11PZRPB83KSFT0WG`: created by `ur-caller[wed]`, bridged by `mqtt_gateway_test1`).

After the sources, `refresh` updates the links index (`ela links`, `<runtime>/links/links.db`): the edges between
what the store holds — Jira links and named keys, the threads and mails that name a key, build records, the train's
lanes, vault notes, ela's writes — re-read only for the files that changed. A failure there is one line; the facts
stand without it.

**Facts only.** `ELA_FACTS_ONLY=1` (set by `ela release next`, inherited by its subprocesses) makes a verb answer
from the store alone: any stored read is served whatever its age (the consumer states the age), every live read
is refused at its chokepoint (Jira, userservice, Jenkins) with exit 7 and "not in the facts store", and `ela jira
read` serves a key the cache lacks from the sweep or a standing query. A consumer turns a refusal into a gap.

## Invariants
- **Staleness shown, never hidden.** Every result carries `read_at` (JSON) or a `facts: jira 11-04 08:02 · …`
  line (a page). A reader who needs the world as it is now says `--fresh` on that one verb and names the gap it
  fills; `ELA_FACTS_FRESH=1` makes every read below a consumer live (`ela changes --fresh` does that).
- **Incremental and idempotent.** A second refresh in the same window reads the watermark forward and fetches
  nothing already stored; `--fresh` on `refresh` re-reads every source whole.
- **The store is working state.** `<runtime>` is deletable by contract (`ela runtime clean`); the next refresh
  refills it. Nothing in it is a record; the records are the dated files under `<reports>` and `<runtime>/runner/`.
- **One live call is one trace line.** `ELA_FACTS_TRACE=1` prints `facts-trace <source> <what>` per request, so a
  pass can be measured: `ELA_FACTS_TRACE=1 ela changes --hours 24 2>&1 >/dev/null | grep -c facts-trace`.
- **Every live call is counted for the day.** Each call also goes to `<runtime>/facts/calls/<date>.jsonl` with its
  caller: `read` inside `facts refresh`, else `ELA_FACTS_CALLER` (the runner names each pass and service), else
  `session`. `ela facts calls [--date D]` shows the fixed reads' share and the rest by caller, verb and source, so a
  consumer that still reads for itself is seen. `ELA_FACTS_CALLS=0` turns it off (`tests/run.sh` does).

## Verification
`tests/test_facts_offline.py` (fixtures, no network): the watermark after a first refresh, a second refresh that
reads nothing new, a failing source that keeps its content and records a gap, and the serving rules of each source.

Decision: elak `blueprint/decisions/2026-11-04-read-once-close-by-outcome-home-as-an-index.md`, phase A.
