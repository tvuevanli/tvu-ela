---
name: object
description: >
  TVU Object Service (the /route-object/object-service API — not objectd, which is a different service) — query objects AND tangibles, plus media stream metadata. An object (19-digit numeric id) holds one or more tangibles (32-hex ids); both are readable here.
  Use this skill when the user runs /ela:object, wants to look up a tangible by tangible ID, search objects,
  or inspect ObjectService data. Also trigger for: "find tangible", "look up object", "search tangible ID",
  "查找切片", "查询对象", "object service查询".
---

# /ela:object — objects and tangibles, first-hand

Self-contained. The L1 script does the calls; this file says when and how to read the answer.

```bash
O="python3 ${CLAUDE_PLUGIN_ROOT}/skills/object/object.py --env-file <env>"   # <env> from ~/.claude/ela/site.json
$O get <id>              # object (19 digits) or tangible (16–32 hex); falls through to the other on a miss and says which answered
```
`get` is the whole read surface: the service exposes `GET /base/object/<id>` and `GET /base/tangible/<id>`.
A batch-by-ids endpoint and a keyword search were documented here before; both answer 404 (verified
2026-09-02), so there is no search — an object is found by id, or from a graph's `objectId` annotation.
Every subcommand takes `--json`; `get` takes `--raw` for the body as-is. Exit codes: 0 ok · 2 usage ·
3 not found · 4 auth (token rejected → `/ela:setup`) · 5 remote error.

## What the record carries, and what it does not
- An object: `objectType` 1 = Source, 2 = Destination; `origin` (e.g. `UnifiedMediaService`); `owner.users`
  — **userIds, not emails**; `tangibleInfo[]` with each tangible's type and `extraInfo` (url, urLoadTier…).
- The bare tangible record does **not** carry its objectId. A 32-hex id can also be a UR **process** id — if
  the Object Service has no tangible for it, try `/ela:graph process <id>`.
- An **active** object's `tangibleInfo` includes SHM and RTIL rows named `<graphId>:<node>` whose
  `tangibleId` is the **process id** — `get` prints the derived `graphs` line; `/ela:graph resolve <objectId>`
  follows it into the graph tables.
- For an **inactive** object there is no graph to derive; J2N's list by owner email
  (`/ela:graph graphs <email> --object <objectId>`) still finds finished graphs — J2N annotates each graph
  with its `objectId`.

## Output
State the id shape you resolved and which endpoint answered. Show tangible types prominently
(HLS, SRTLISTENER, T…). Never print the bearer token.
