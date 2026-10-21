---
name: apifox
description: The teams' API definitions, read from Apifox. Use for "这个接口的参数", "J2N 有没有 xxx 的 API", "UR 的 graph 接口返回什么", an app.apifox.com link, or when probe/breakdown needs a contract rather than a guess.
user-invocable: true
---

# /ela:apifox — the API contracts, from the source the teams edit

Self-contained. `apifox.py` is the capability; `ela api …` at the shell is the same thing. Projects are
named in `<elak>/map/apis.yaml` (`ur` → 4296487 today); a numeric id or an `app.apifox.com/project/<id>`
URL works unnamed.

```bash
A="python3 ${CLAUDE_PLUGIN_ROOT}/skills/apifox/apifox.py --env-file <env>"   # or: ela api …
$A projects                         # names, ids, cache state
$A projects --team all --grep config   # every project the recorded teams hold (ids from apis.yaml `teams:`)
$A export ur [--refresh]            # the API document, cached a day under ~/.claude/ela/apifox/; says which path read it
$A tags ur                          # folders → operation counts (Node 40, Resource 26, Box 25 …)
$A list ur --tag Graphs             # METHOD path · summary · tag
$A list ur --grep nodeOrigins       # anything whose path/summary/operationId/description carries the word
$A read ur "GET /v1beta1/graphs/{graphId}"   # one operation: parameters, request body, responses, $refs resolved
$A schema ur GraphSpec              # one component schema
```

## Two read paths, one output
1. **Export** — the Open API's `export-openapi`, OpenAPI 3.1 with folders as tags. It needs maintainer
   rights on the project.
2. **Member read** — when export answers 403, the same token reads the web client's API (`api-details`,
   `api-tree-list`, `data-schemas`) and the script converts it to the export's shape: folder path as
   tag, `#/definitions/<id>` refs renamed to component names, full-URL paths cut to their path as
   export does. `tags`, `list`, `read`, `schema` print the same either way. On ur (4296487) and
   ConfigServer (5793217), where both paths work, they agree operation for operation.

The first fetch prints `read by export` or `read by member read` on stderr; the cache records it
(`x-ela-source`) and `export` shows it. A 403 from both paths is exit 4 and names both refusals.

**The limit of the member read.** It reads only what the owner's own account sees in the web client —
it grants nothing export does not. It uses Apifox's undocumented client API, so its shape can change
without notice: every body is checked, and a mismatch exits 5 with the unexpected body. It never
returns an empty or partial document; an empty `api-details` is treated as a mismatch.

## Invariants
- **The contract is the fact; the code is the truth.** An Apifox definition is what the team *declares*;
  when it disagrees with the running service (`/ela:graph`) or the code, say so and cite both.
- **Cite the operation** (`METHOD path`, project, export date), never paste the document into elak or a
  ticket. The export is a cache of a company source; elak's `map/apis.yaml` keeps names and ids only.
- **Read-only.** The Open API can also import and modify; none of that exists in this script.
- **Ambiguity is refused, not guessed.** `read` with a fragment that matches several operations lists them
  and stops; pass `METHOD path` or `--all`.
- **A team's projects are listed, not guessed.** `projects --team <id>|all` reads each team named in
  `apis.yaml` `teams:`; a project worth a name is then added to `apis.yaml` `projects:` by its id.
  Credentials: `.env APIFOX_TOKEN`; the edge requires a User-Agent, the script sends one.
