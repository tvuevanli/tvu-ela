---
name: apifox
description: API contracts — the teams' Apifox projects and the public doc. Use for "这个接口的参数", "公开文档怎么写的", an app.apifox.com or document.tvunetworks.com link, or when probe/breakdown needs a contract.
user-invocable: true
---

# /ela:apifox — the API contracts, from the source the teams edit

Self-contained. `apifox.py` is the capability; `ela api …` at the shell is the same thing. Projects are
named in `<elak>/map/apis.yaml` (`ur` → 4296487 today); a numeric id or an `app.apifox.com/project/<id>`
URL works unnamed.

```bash
A="ela api"
$A projects                         # names, ids, cache state
$A projects --team all --grep config   # every project the recorded teams hold (ids from apis.yaml `teams:`)
$A export ur [--refresh]            # the API document, cached a day under ~/.claude/ela/apifox/; says which path read it
$A tags ur                          # folders → operation counts (Node 40, Resource 26, Box 25 …)
$A list ur --tag Graphs             # METHOD path · summary · tag
$A list ur --grep nodeOrigins       # anything whose path/summary/operationId/description carries the word
$A read ur "GET /v1beta1/graphs/{graphId}"   # one operation: parameters, request body, responses, $refs resolved
$A schema ur GraphSpec              # one component schema
$A tags public                      # the public API doc, same verbs (name from apis.yaml `docs:`)
$A read public createSourceObject   # one public endpoint, with its doc page link
$A diff public 4283785 --tag "MediaHub API"   # public vs a team's declaration: one-sided operations, mismatches
```

## The public API doc
The documentation customers code against: an Apidog doc site (project 483063) behind userservice SSO,
named `public` in `apis.yaml` `docs:`; its URL works unnamed, and an `api-<id>` page URL alone opens that
endpoint (`ela <url>`). `pubdoc.py` reads it into the same shape, so `tags`, `list`, `read`, `schema` print
as they do for Apifox, with the folder path as tag.

- **Access is the test account `li`** — session.json `tvu-com-test`, from `ela login tvu --as test`. Never the
  owner's own sign-in (`el`) or an admin SID; nothing here logs in, because the token endpoint is itself a
  documented one. A refused or missing session exits 4 with that command. The `el` SID cached for the QA
  host (`TVUTEST_SID`) gets a 302 on the doc site.
- **Lazy.** The site has no export ela can read with the stdlib: `tags`/`list` read only the catalog page;
  `read` fetches the endpoints it prints; `export`, `schema` and `diff` fetch their scope, six at a time
  (the MediaHub API folder, ~90 pages, takes about a minute and a half cold). Catalog and pages are cached
  a day under `~/.claude/ela/apifox/public/`.
- **Only the doc host**, redirects never followed; nothing the docs describe is ever called.

## Diff
`diff A B [--tag T] [--tag-b T]` compares two contracts operation by operation. Paths match exactly, then
by a segment-aligned suffix (a gateway prefix on one side) when exactly one operation on each side fits;
path-parameter names are ignored, and ambiguity stays unmatched. It reports operations on one side only
(B's outside every folder A has are counted, not listed), the same name at different paths, and for
matched pairs: parameters (auth and transport headers excepted) and top-level body fields one-sided,
required or typed differently. What it finds is a question for the owning team, not a verdict on either
side: the public doc can be ahead of a stale declaration as easily as behind.

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
