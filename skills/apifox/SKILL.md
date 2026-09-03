---
name: apifox
description: Read the teams' API definitions first-hand from Apifox — a project's OpenAPI export, its tags, the operations matching a word, one operation with parameters, request body and responses, a component schema. Use for "这个接口的参数", "J2N 有没有 xxx 的 API", "UR 的 graph 接口返回什么", an app.apifox.com link pasted in chat, or when probe/breakdown needs a contract rather than a guess.
user-invocable: true
---

# /ela:apifox — the API contracts, from the source the teams edit

Self-contained. `apifox.py` is the capability; `ela api …` at the shell is the same thing. Projects are
named in `<records>/map/apis.yaml` (`ur` → 4296487 today); a numeric id or an `app.apifox.com/project/<id>`
URL works unnamed.

```bash
A="python3 ${CLAUDE_PLUGIN_ROOT}/skills/apifox/apifox.py --env-file <env>"   # or: ela api …
$A projects                         # names, ids, cache state
$A export ur [--refresh]            # the OpenAPI 3.1 document, cached a day under ~/.claude/ela/apifox/
$A tags ur                          # folders → operation counts (Node 40, Resource 26, Box 25 …)
$A list ur --tag Graphs             # METHOD path · summary · tag
$A list ur --grep nodeOrigins       # anything whose path/summary/operationId/description carries the word
$A read ur "GET /v1beta1/graphs/{graphId}"   # one operation: parameters, request body, responses, $refs resolved
$A schema ur GraphSpec              # one component schema
```

## Invariants
- **The contract is the fact; the code is the truth.** An Apifox definition is what the team *declares*;
  when it disagrees with the running service (`/ela:graph`) or the code, say so and cite both.
- **Cite the operation** (`METHOD path`, project, export date), never paste the document into elak or a
  ticket. The export is a cache of a company source; elak's `map/apis.yaml` keeps names and ids only.
- **Read-only.** The Open API can also import and modify; none of that exists in this script.
- **Ambiguity is refused, not guessed.** `read` with a fragment that matches several operations lists them
  and stops; pass `METHOD path` or `--all`.
- Team pages cannot be enumerated with the token's rights; a new project is added to `apis.yaml` by its id
  from the UI URL. Credentials: `.env APIFOX_TOKEN`; the edge requires a User-Agent, the script sends one.
