---
name: release
description: Release facts read first-hand — GM bundles and their bill of materials, versions per environment (userservice), Jenkins builds with version, branch and commit, and the drift between the newest bundle and the service table. Use for "哪个 bundle", "daily 上是什么版本", "这个 build 是哪个 commit", "MH-xxxx 的修复在 prod 8 上了吗", "bundle 里有哪些 docker service".
user-invocable: true
---

# /ela:release — bundles, env versions, builds, first-hand

Self-contained. The script reads userservice (GM) and Jenkins directly from the office machine; no
store, no scheduler, nothing cached — every answer is the source's current state.

```bash
R="python3 ${CLAUDE_PLUGIN_ROOT}/skills/release/release.py --env-file <env>"      # or simply: ela bundles … / ela versions … / ela builds …
$R bundles [mh2.1@] [--qa]           # GM bundles newest first (prod host; --qa = tvutest)
$R bundle <name|id> [--qa]           # bill of materials: serviceTagList
$R envs [service] [--qa]             # versions per environment tag
$R builds <job|service> [--limit N]  # Jenkins: number, version, result, branch, sha, time
$R drift [mh2.1@] [--qa]             # GM names in the newest bundle vs map/services.yaml
$R login                             # tvutest SID for --qa (2h)
```
Config: service URLs in `site.json services` (jenkins · userservice · userservice-test); which service
ids publish which versions and which Jenkins job builds which service in `<records>/map/release.yaml`.

## Invariants
- **First-hand, current.** What userservice and Jenkins say now. History older than they keep is not
  ela's to hold; Helm's local `builds.db` can be read as a file when it matters.
- **SIDs expire.** HTTP 402 "no login" on the prod host means `USERSERVICE_ADMIN_SID` in the env file
  needs a fresh paste from the browser; say so and stop — never guess a version.
- **Judgment is composed, not computed.** "Is MH-xxxx fixed on prod 8?" = the ticket's Fixed In
  (jira) → the build carrying it (`builds`) → the version on the env (`envs`) → verdict, each step cited.
  Helm's containment rules are knowledge (E3), not code here.
- **Names are three things.** `slug` (Evan's convention), `gm_name` (what GM registers), `service_id`.
  `drift` compares GM names; a difference is either a new service or a stale table row — say which.
