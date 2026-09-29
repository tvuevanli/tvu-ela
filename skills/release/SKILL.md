---
name: release
description: Release facts — GM bundles, versions per lane (qa-*, daily-*, stage, prod-N), Jenkins builds. Use for "哪个 bundle", "daily 上是什么版本", "prod-3 跑的是哪个 build", "这个 build 是哪个 commit", "MH-xxxx 的修复在 prod 3 上了吗", "bundle 里有哪些 docker service".
user-invocable: true
---

# /ela:release — bundles, lane versions, builds, first-hand

Self-contained. The script reads userservice (both hosts) and Jenkins directly; no store, no scheduler,
nothing cached — every answer is the source's current state.

`R="python3 ${CLAUDE_PLUGIN_ROOT}/skills/release/release.py --env-file <env>"` (or `ela bundles · versions ·
builds · login tvu`); `$R --help` lists the verbs and their flags. `bundle` is the bill of materials
(`serviceTagList`); `envs` gives versions per lane; `builds` gives Jenkins number, version, result, branch, sha, time.

Config: service URLs in `site.json services` (jenkins · userservice · userservice-test); which service ids publish
which versions on which host, how a tag name maps to a lane, which Jenkins job builds which service, and which
lanes each release line uses — all in `<elak>/map/release.yaml` (origin per block).

## Invariants
- **First-hand, current.** What userservice and Jenkins say now. History older than they keep is not
  ela's to hold.
- **Two hosts, two sessions.** qa is a tvutest account login (a two-hour SID) the script renews. prod is a person's session:
  `ela login tvu` opens a page at the hostname `release.py` names for `login tvu`, mapped in the machine's
  hosts file (site configuration, not written here); because that name sits under the company domain, a
  browser already signed in to userservice sends its SID to the page (one self-signed certificate warning
  the first time); a paste field is the fallback. The session lives in `~/.claude/ela/session.json`
  (mode 600) and nowhere else; the first refusal records `rejected_at`, so `login tvu` can print how long
  the previous session lasted. Decision elak `blueprint/decisions/2026-09-04-prod-gm-read-through-a-person-login.md`.
- **Lane names are the release map's.** `aws-cn3-env` and `AWSCN3` are both `qa-cn3`; `MediaHubWednesday`
  is `daily-wed`; `UnifiedResourcesTest2` is `daily-test2`. Answer in lane names, show the tag once.
- **Judgment is composed, not computed.** "Is MH-xxxx fixed on prod 3?" = the ticket's Fixed In (jira) → the
  build carrying it (`builds`) → the version on the lane (`envs --host prod`) → verdict, each step cited.
- **Names are three things.** `slug` (Evan's convention), `gm_name` (what GM registers), `service_id`.
  `drift` compares GM names; a difference is either a new service or a stale table row — say which.

## Gotchas
- **The wrong host shows no bundle** (`bundles`, `bundle`, `drift`, `--host`). QA bundles live on qa;
  daily, stage and prod bundles on prod. Pass `--host prod` for anything past QA.
- **A refused prod read exits 4 and names the command** (`--host prod`). It never falls back to a cache
  or another system's file. In a Claude session, tell Evan to type `! ela login tvu`; do not paste a
  SID for him.
- **A bundle's SaaS rows mirror the lane; its docker rows are its content** (`bundle`). Never read a
  bundle's SaaS row as a frozen version — `envs` is the version source.
