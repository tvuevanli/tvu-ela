---
name: j2n
description: J2N scheduling scores, read-only — what an app instance costs a box (Cpu, Qsv) per J2N env and label set; two envs compared. Use for "J2N 的分", "UHD encoder 扣多少 Cpu", "prod3 和 test2 差在哪", or a placement question.
user-invocable: true
---

# /ela:j2n scores <env> — J2N's scheduling scores, read first-hand

Self-contained. All reads go through `ela j2n` (`${CLAUDE_PLUGIN_ROOT}/skills/j2n/j2n.py`), which reads the J2N
config UI's own proxy as the owner.

```bash
ela j2n envs                                         # environments, category, production mark, the owner's access
ela j2n scores <env> [--subtype S] [--labels k=v,…]  # the score rows of one environment, narrowed
ela j2n scores <env> --diff <env2> [filters]         # the UI's compare view: rows only in one side, values that differ
```
Every subcommand takes `--json`. A label key is matched by its full name (`encoder.app.tvunetworks.com/resolution`),
its short form (`encoder/resolution`) or its last segment (`resolution`); values case-insensitively.
Exit codes: 0 ok · 2 usage or a refused request · 3 not found (unknown env, a 404, no row matches) · 4 auth ·
5 remote error or a certificate that is not the pin.

## What the data is
A row is one label set (always `app.tvunetworks.com/subtype`, sometimes more: `encoder…/resolution=UHD`,
`box…/hardwareAcceleration=Qsv`, `encoding…/codec=H.265`, `selector…/strategy=SpecifiedPoolOnly`) and the resources one
instance of that app costs a box (`Cpu`, `QsvRender3D`, `QsvVideo`). J2N and UR fit work onto boxes with these
numbers. The store is not Config Server: no application, no profile; environment × label set. The reading of
2026-11-09 (the vault's `mh/2026-11-09-j2n-config-ui-scores.md`) describes the environments' generations and the drift
between prod and pre-prod.

## Invariants
- **Read-only, by construction.** The owner's account can **write** on `qa` and `qa2` in this UI. The script sends a
  GET from a closed list (the env list, the owner's permissions, one environment's scores) and a POST to the sign-in
  path only; any other method or path is refused in code before a connection (exit 2). A score change is the owning
  team's act and appears in a handoff as a request, never as a click made on the owner's behalf.
- **TLS is pinned, never disabled.** The UI's leaf certificate (issued by the C# team's private CA) is pinned at
  `~/.claude/ela/certs/j2n-config-ui.pem` with its SHA-256 beside it; verification is partial-chain against that PEM,
  the host name checked, then the fingerprint compared. Another certificate refuses the connection (exit 5). When the
  team's CA is published, it replaces the pin.
- **The owner's sign-in, never printed.** `TVU_ACCOUNT` / `TVU_PASSWORD` from the site env file, through the UI's own
  sign-in; the bearer token is cached at `<runtime>/j2n-config-ui.token` (mode 600) and renewed on a 401. Exit 4 names
  `ela secret TVU_PASSWORD`. A read-only service token from the owning team would be better than a person's
  write-capable login; until one exists, the gate above is what keeps this read-only.
- **The host is a site fact.** `services.j2n-config-ui.url` in `site.json`; a tracked file, a ticket or a Slack draft
  says "the J2N config UI", never the address.
- Output passes through the shared redaction (`skills/configserver/redact.py`).

## Gaps, said every time they matter
- **Environment mapping is assumed by name.** J2N's `prod3` is taken to back MediaHub's prod-3 (`prod8` → prod-8,
  `test2` → test2) because the names match; nothing read proves it. When a conclusion depends on the mapping, say
  "assumed by name" and, where possible, confirm from the graph itself (`ela graph <id>` reports its env).
- **qa and qa2 are not readable here.** The proxy answers 404: their scores sit on a separate score server.
- **Which row wins** when several match one instance (most labels, first match) is decided in the j2n-config service,
  whose code is not in the local checkout. Show every matching row; do not pick a winner.
- No subtype has an owner in the UI's metadata and the change ledger is empty for the production environments: a
  difference has no recorded author or reason. Say so rather than infer one.

## Source quirks
- The direct score service (each environment's `scoreApiServer` in the UI's config) answers 401 to the UI's token; the
  UI's proxy is the path. Do not work around it.
- A scores GET sometimes answers 500 "Version conflict (WriteStateAsync) … readonlyscoresettings/<env>": the
  service's own cache write racing. The script retries the GET twice, then reports exit 5.

## Who uses this and when
`/ela:probe` and `/ela:route` when a placement, capacity or "UHD will not start" symptom may be a score, not code:
`ela j2n scores <env> --subtype <subtype>` with the instance's labels. `/ela:promote` before a release when a lane hop
changes scheduling: `ela j2n scores <pre-prod> --diff <prod>` shows what pre-prod does not exercise.
