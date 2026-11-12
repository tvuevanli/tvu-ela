---
name: facts
description: The fact store, every source read once per pass into <runtime>/facts/. Use for "refresh the facts", "how old are the facts", "事实库", or a page whose facts line is older than the pass.
user-invocable: true
---

# /ela:facts — read once, analyse many

`ela facts refresh` runs first in every pass (the runner calls exactly `ela facts refresh --json`, then
`ela train --line <line> --write --json` per followed line). It reads each source forward from its watermark into
`<runtime>/facts/<source>/`, one directory per source, every entry stamped with its read time:

| source | what one refresh reads | the store serves |
|---|---|---|
| `jira` | MH issues updated since the last watermark (first fill 14 days), raw with changelog and comments → `changes.json`; the key cache `issues/<KEY>.json` re-read only for keys the sweep says moved; the standing queries (`queries/incidents.json`, `owner.json` once a day) | `ela jira changes`, `ela jira read`, the incidents and owner-name JQLs, `ela recent`'s week |
| `slack` | every channel the bot is in: parents over the last 8 days (so a reply to an older thread shows on its parent), then the replies of each thread that moved; the channel list and the user names | `history`, `mentions`, `unanswered`, `search`, `channels` — the one per-channel cache (`<runtime>/slack-cache/` moves in once) |
| `mail` | the three standing searches over a rolling 21 days — `subject:Release`, `subject:("test report")`, `in:sent` — ids newest first, only the ids not yet stored fetched | `ela mail search` for any query inside one of those three; every other query lists ids live and fetches only unstored ids; `read` always; `thread` while fresh |
| `lanes` | `release envs` on both hosts and `release gateway`, once | `ela release envs|gateway`, promote's host read, stage's lane signature, fixed-in's lanes |
| `builds` | Jenkins, 80 builds per mapped job; the bundle lists per line on both hosts | `ela builds`, `ela bundles`, promote's build and bundle reads |
| `runtime` | per followed lane (release.yaml lines, daily and prod) and per config-server service (each repo's own `bootstrap.properties`): the lane's profile (`elk.config.env` = the lane token), the instance the java-log shows running it, the profile chain a graph proved (`ela facts runtime prove <graph>`: its trace → the UR Caller instance that created it, its processes → the gateway that bridged them), and the keys whose value differs between the lane profile read alone and that chain; the initConfig the owner's browser session received (`ela browser env`, kept under the lane the version panel proved, keys and non-secret values only) | `ela facts runtime show`, promote's configuration section, `ela configserver effective <app> <chain>` |

A verb serves the store while the source's watermark is younger than `ELA_FACTS_MAX_AGE` hours (default 6) and
says so on stderr with the read time. A gap (a host that refused, Jenkins down) keeps the previous content and is
recorded in the watermark; the serving verb then answers as the live read would (the lanes' exit 4, an empty
list) and names the last good read. `ela facts status` prints each source's time, freshness, size and gap.

A chain is proven only by a graph bound to its creator and its gateway; until one is, the row says "last layer
proven, earlier layers unproven" and a reader states configuration as the lane profile's alone, unproven. Decision:
the 2026-11-09 daily-wed → prod-3 promotion, where `mx_service_wed` read alone gave `mediaBox.viaGateway=false`
while daily-wed's UR Caller ran `default → mx_service_test → mx_service_wed` (proven from graph
`01M6ZB6FVC11PZRPB83KSFT0WG`: created by `ur-caller[wed]`, bridged by `mqtt_gateway_test1`).

After the sources, `refresh` updates the links index (`ela links`, `<runtime>/links/links.db`): the edges between
what the store holds — Jira links and named keys, the threads and mails that name a key, build records, the train's
lanes, vault notes, ela's writes — re-read only for the files that changed. A failure there is one line; the facts
stand without it.

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

## Verification
`tests/test_facts_offline.py` (fixtures, no network): the watermark after a first refresh, a second refresh that
reads nothing new, a failing source that keeps its content and records a gap, and the serving rules of each source.

Decision: elak `blueprint/decisions/2026-11-04-read-once-close-by-outcome-home-as-an-index.md`, phase A.
