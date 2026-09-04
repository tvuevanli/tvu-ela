---
name: release
description: Release facts read first-hand on both userservice hosts — GM bundles and their bill of materials, versions per lane (qa-*, daily-*, stage, prod-N), Jenkins builds with version, branch and commit, and the drift between the newest bundle and the service table. The prod host needs a person's session — `ela login tvu` collects it from the browser once. Use for "哪个 bundle", "daily 上是什么版本", "prod-3 跑的是哪个 build", "这个 build 是哪个 commit", "MH-xxxx 的修复在 prod 3 上了吗", "bundle 里有哪些 docker service".
user-invocable: true
---

# /ela:release — bundles, lane versions, builds, first-hand

Self-contained. The script reads userservice (both hosts) and Jenkins directly; no store, no scheduler,
nothing cached — every answer is the source's current state.

```bash
R="python3 /home/evan/projects/ela/skills/release/release.py --env-file <env>"   # or: ela bundles … / ela versions … / ela builds … / ela login tvu
$R bundles [mh2.1@] [--host qa|prod]  # GM bundles newest first — QA bundles live on qa, daily/stage/prod bundles on prod
$R bundle <name|id> [--host qa|prod]  # bill of materials: serviceTagList
$R envs [service] [--host qa|prod]    # versions per lane; tag names mapped to lanes by <records>/map/release.yaml hosts
$R builds <job|service> [--limit N]   # Jenkins: number, version, result, branch, sha, time
$R drift [mh2.1@] [--bundles N] [--host qa|prod]
$R login tvu [--force]                # one-time HTTPS page under ela.tvunetworks.com collects the browser's SID; paste fallback
$R login qa                           # tvutest account login → SID (2h); the script does this itself when needed
```
Config: service URLs in `site.json services` (jenkins · userservice · userservice-test); which service ids publish
which versions on which host, how a tag name maps to a lane, which Jenkins job builds which service, and which
lanes each release line uses — all in `<records>/map/release.yaml` (transcribed from Helm 2026-09-04, origin per block).

## Invariants
- **First-hand, current.** What userservice and Jenkins say now. History older than they keep is not
  ela's to hold.
- **Two hosts, two sessions.** qa is an account login the script renews. prod is a person's session:
  `ela login tvu` opens a page at `https://ela.tvunetworks.com:8443/`; because that name sits under
  `.tvunetworks.com`, a browser already signed in to userservice sends its SID to the page (a hosts-file
  line `127.0.0.1 ela.tvunetworks.com` on the machine that runs the browser, one self-signed certificate
  warning the first time); a paste field is the fallback. The session lives in `~/.claude/ela/session.json`
  (mode 600) and nowhere else; the first refusal records `rejected_at`, so `login tvu` can print how long
  the previous session lasted. Decision `2026-09-04-prod-gm-is-read-through-a-persons-login-at-the-cli`.
- **A refused prod read exits 4 and names the command.** It never falls back to a cache or another
  system's file. In a Claude session, tell Evan to type `! ela login tvu`; do not paste a SID for him.
- **Lane names are the release map's.** `aws-cn3-env` and `AWSCN3` are both `qa-cn3`; `MediaHubWednesday`
  is `daily-wed`; `UnifiedResourcesTest2` is `daily-test2`. Answer in lane names, show the tag once.
- **A bundle's SaaS rows mirror the lane; its docker rows are its content.** Never read a bundle's
  SaaS row as a frozen version — `envs` is the version source.
- **Judgment is composed, not computed.** "Is MH-xxxx fixed on prod 3?" = the ticket's Fixed In (jira) → the
  build carrying it (`builds`) → the version on the lane (`envs --host prod`) → verdict, each step cited.
- **Names are three things.** `slug` (Evan's convention), `gm_name` (what GM registers), `service_id`.
  `drift` compares GM names; a difference is either a new service or a stale table row — say which.
