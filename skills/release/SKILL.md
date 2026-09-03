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
$R bundles [mh2.1@]                  # GM bundles newest first — QA host (tvutest), by account login
$R bundle <name|id>                  # bill of materials: serviceTagList
$R envs [service]                    # versions per environment tag on the QA host
$R builds <job|service> [--limit N]  # Jenkins: number, version, result, branch, sha, time
$R drift [mh2.1@] [--bundles N]      # GM names shipped in the newest N bundles vs map/services.yaml
$R login                             # tvutest login → SID (2h); the script does this itself when needed
```
Config: service URLs in `site.json services` (jenkins · userservice · userservice-test); which service
ids publish which versions and which Jenkins job builds which service in `<records>/map/release.yaml`.

## Invariants
- **First-hand, current.** What userservice and Jenkins say now. History older than they keep is not
  ela's to hold; Helm's local `builds.db` can be read as a file when it matters.
- **No prod session.** ela reads the QA GM host by account login and Jenkins; prod bundles and prod
  env versions are Helm's (its UI login holds that session — decision `2026-09-03-ela-needs-no-sid`).
  Asked about prod, point at Helm's release pages; never guess a version, never ask for a SID.
- **Judgment is composed, not computed.** "Is MH-xxxx fixed on prod 8?" = the ticket's Fixed In
  (jira) → the build carrying it (`builds`) → the version on the env (`envs`) → verdict, each step cited.
  Helm's containment rules are knowledge (E3), not code here.
- **Names are three things.** `slug` (Evan's convention), `gm_name` (what GM registers), `service_id`.
  `drift` compares GM names; a difference is either a new service or a stale table row — say which.
