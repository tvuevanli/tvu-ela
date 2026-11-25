# `releases/next.json`: the next MediaHub release, as data

`ela release next --write` writes `<published>/releases/next.json`, and this file beside it as
`<published>/releases/README.md`. The runner refreshes both on weekdays in its morning run at 08:00 (after
its facts refresh, so QA's evening report is in it), at 12:30 and at 17:30, and `--sync` carries `releases/` to Helm Akamai so it reads the same file. A reader such as Helm's `/release/next` page shows the fields as written. Every judgment is
made here, and the page makes none: it does not compute a state, filter tickets or parse a version.

The file is computed from facts only: the fact store each pass refreshes at its head (`ela facts refresh`:
the Jira sweep and its standing `release:must` and Fixed In queries, the bundle lists and bundle details,
Jenkins builds, the service repositories fetched) and the files ela wrote (the train, the latest promotion
report, the held candidate). It reads no source live and starts no model session. What the store lacks is
a gap, never a live read; `sources.facts` names each source's read time.

Schema version **1**. A field is only added when the schema changes. A rename or a removal raises
`schema`, and readers are told before it ships.

The file is written atomically and passes through the publish redaction, so it holds no addresses.
Ticket titles, commit subjects and people's display names are carried as facts. No QA quotation is
carried: only its verdict, its source and its time.

## Top level

| field | type | meaning |
|---|---|---|
| `schema` | int | `1` |
| `generated_at` | ISO-8601 with offset | when the file was computed |
| `stale_after` | ISO-8601 with offset | the next scheduled refresh plus two hours. A reader shows the data as stale after this time. |
| `line` | string | the release train, as a key in map `release.yaml` (`"2.1"`) |
| `state` | `"planned"` \| `"released"` | `planned`: the candidate is not yet an official bundle. `released`: a plain official bundle was cut after the candidate, and the file has been recomputed on it. |
| `headline` | string | one display line: `MediaHub 2.2.0, planned for prod-3 on Monday 30 Nov`, or `MediaHub 2.2.0, released` |
| `release` | object | `{name, lane, planned_for, released_bundle}`. `name` is the release's product name (`MediaHub 2.2.0`). `lane` is the prod lane it goes to. `planned_for` is `YYYY-MM-DD` or `null`. `released_bundle` is `null`, or once released `{name, id, created}`. |
| `base` | bundle | the newest plain official bundle before the range: what the release compares against |
| `candidate` | bundle + `source` | the planned bundle: the newest daily bundle (`source: "newest"`), or one held by `ela release next --pin` (`"pin"`) or named by `--candidate` (`"argument"`). In the `released` state, it is the bundle the release was cut after. |
| `lanes` | `[{role, lane, shown}]` | the column headings of the lane cells, in order (QA · daily · prod · CN) |
| `must` | `[must]` | tickets labelled `release:must` |
| `on_candidate` | `[ticket]` | every ticket the range carries (`ela promote tickets <line> <base> <candidate>`) |
| `epics` | `[{key, url, summary, status, children}]` | the epics of tickets in `on_candidate` |
| `in_dev` | `[ticket]` | MH tickets In Progress or Review, updated within 14 days, that are not in `on_candidate` |
| `docker` | object | see below |
| `counts` | object | `{must, must_missing, on_candidate, in_dev, docker_changed, unbuilt_commits}` |
| `sources` | object | each input with its time: `facts` (the store's sources, `at` the oldest), `tickets`, `qa_report`, `train`, `jira` (`{what, at}`) |
| `gaps` | `[{kind, detail}]` | what could not be read or judged, in words. An empty list means nothing is missing. |

A **bundle** is `{name, id, created, rule}`. `created` is `YYYY-MM-DD HH:MM`, local time. `rule` says
how it was chosen.

## `must[]`

`{key, url, summary, type, status, assignee, tracked_since, on_candidate, position, cells, decision}`

- `tracked_since`: when the label was added, as an ISO time from the changelog the Jira sweep holds (14
  days), else the time the previous file carried for the ticket; `null` when neither shows it (a label
  added before the sweep's window, on a ticket new to the file).
- `on_candidate`: whether the range carries it.
- `position`: the furthest lane it has reached according to the train (`qa`, `daily`, `prod`, `cn`), or
  `null`.
- `cells`: `{<lane>: {arrived, since, verdict, version, source, at}}`. These are the train's cells
  (`ela train`), keyed by the `lane` values in `lanes[]`. A lane with no cell is absent.
- `decision`: `null`, or `"hold or defer"` when the state is `planned` and the candidate does not carry
  the ticket. It is the one item on the page that asks for a decision.

## `on_candidate[]` and `in_dev[]`

`{key, url, summary, type, status, assignee, parent, services, qa}`

- `services`: the services whose commits or Fixed In name the ticket (`on_candidate` only). A ticket a
  commit names but the Jira store holds no row of is listed with an empty `summary` and a
  `ticket_not_in_facts` gap.
- `docker`: the docker slugs whose Fixed In names it (`on_candidate` only).
- `updated`: `YYYY-MM-DD` (`in_dev` only).
- `qa`: `null`, or `{verdict, source, when}` as promote's evidence reads it from the latest saved
  promotion report. `verdict` is one of `pass`, `partial`, `fail`, `n-a`, `accepted`, `dev-declared`,
  `none`. `source` is `mail`, `jira`, `slack` or `report`.

## `docker`

- `bundle_diff`: `[{service, slug, from, to, relation, tickets}]`, the docker images that differ
  between `base` and `candidate`. `relation` is `to_ahead`, `from_ahead`, `added`, `removed` or
  `named_tags_not_comparable`.
- `lanes`: `[{service, from: {lane, version}, to: {lane, version}, relation}]`, the SaaS services'
  versions on the daily lane and the prod lane, from the latest promotion report.
- `branches`: `[{service, repo, branch, kind, build, commits}]`. These are commits on a release or
  feature branch that the newest build does not contain. `kind` is `release`, `feature`, or `null` when
  the report names no branch (a `branch_unread` gap then says why). `commits`
  is `[{sha, date, author, subject}]`.
