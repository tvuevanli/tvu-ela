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
  the first time); a paste field is the fallback. The session lives in `~/.claude/ela/session.json` —
  the SID and, since 1a7846f, every `.tvunetworks.com` cookie the browser sent with it: the gateway routes
  each product service by per-user tag cookies set from the account's user group, so a replay with the SID
  alone lands on the gateway's default lane (`ela browser env` then shows a panel with no ENV). After the
  owner switches his account between lanes by bundle, the cookies are stale: `ela login tvu --force`
  (mode 600) and nowhere else; the first refusal records `rejected_at`, so `login tvu` can print how long
  the previous session lasted. Decision elak `blueprint/decisions/2026-09-04-prod-gm-read-through-a-person-login.md`.
  `ela logs` and `ela configserver` read under this login too.
- **The session is kept alive, never re-obtained.** `ela login tvu --keepalive` makes one validation call and
  exits: 0 renewed (one line: the email and the errorCode) · 4 refused, recorded as `rejected_at` so
  `lifetimes_s` still measures, or already refused/missing without a call · 5 network, not recorded. It never
  logs in and never retries; a refused session waits for the owner's `ela login tvu`.
  Why a call is enough: user-auth keeps the session in Redis with TTL `sessionInterval` and renews it to that
  whenever a validation finds less than `left.expire.time` left
  (`<code>/web/user-auth/src/main/java/com/tvunetworks/user/auth/service/impl/UserAuthServiceImpl.java:727-790`);
  Config Server gives both as 7200 (`ela configserver get user-auth default --key sessionInterval`), so every
  call renews to two hours. The session ends only after two idle hours or on logout (`logOut`, `:690-712`).
  The call is `POST <user-auth>/main/GetInfoJSON` with the SID in the form body, never the URL, so it stays
  out of access logs (`UserApiController.java:43,133`); `<user-auth>` defaults to the `userAuthUrl` UAS's
  initData returns, `.env` `TVU_USER_AUTH_BASE` overrides.
  **Security:** kept alive, the SID in `session.json` no longer expires on its own while the machine is up;
  logging out in the browser still ends it at once. Accepted by the owner (2026-09-30).
- **Lane names are the release map's.** `aws-cn3-env` and `AWSCN3` are both `qa-cn3`; `MediaHubWednesday`
  is `daily-wed`; `UnifiedResourcesTest2` is `daily-test2`. Answer in lane names, show the tag once.
- **Judgment is composed, not computed.** "Is MH-xxxx fixed on prod 3?" = the ticket's Fixed In (jira) → the
  build carrying it (`builds`) → the version on the lane (`envs --host prod`), whose +BUILD names the lane's own
  build → whether that build's sha descends from the fix commit → verdict, each step cited. A higher version is
  not containment: one job builds several branches (release.yaml trains), so `ela fixed-in` judges by ancestry.
- **Names are three things.** `slug` (Evan's convention), `gm_name` (what GM registers), `service_id`.
  `drift` compares GM names; a difference is either a new service or a stale table row — say which.

## Keepalive timer (installed by setup on the owner's word)
Templates in `skills/release/keepalive/`: a oneshot service whose `ExecStart` carries `@ELA@` for the absolute
path of `ela`, and a timer firing two minutes after boot, then every 30 minutes. `/ela:setup` checks for them and
installs them on the owner's confirm: templates that are only in the tree renew nothing, and the session expires.
Install, from the ela checkout (`<projects>/ela`), with systemd running for the user (on WSL, `[boot]
systemd=true` in `/etc/wsl.conf`):

```sh
K=<projects>/ela/skills/release/keepalive; D=~/.config/systemd/user; mkdir -p "$D"
sed "s|@ELA@|$(command -v ela)|" "$K/ela-tvu-keepalive.service" > "$D/ela-tvu-keepalive.service"
cp "$K/ela-tvu-keepalive.timer" "$D/"
systemctl --user daemon-reload && systemctl --user enable --now ela-tvu-keepalive.timer
systemctl --user list-timers ela-tvu-keepalive.timer; journalctl --user -u ela-tvu-keepalive -n 5
```

Uninstall:

```sh
systemctl --user disable --now ela-tvu-keepalive.timer
rm ~/.config/systemd/user/ela-tvu-keepalive.{service,timer} && systemctl --user daemon-reload
```

What it does not do: log in, retry, run while the machine is down, or revive a refused session. Exit 4 or 5 leaves
the unit failed in `systemctl --user status`; the next tick tries once more, and a recorded refusal makes every
later tick exit 4 without a call until `ela login tvu`.

## Gotchas
- **The wrong host shows no bundle** (`bundles`, `bundle`, `drift`, `--host`). QA bundles live on qa;
  daily, stage and prod bundles on prod. Pass `--host prod` for anything past QA.
- **A refused prod read exits 4 and names the command** (`--host prod`). It never falls back to a cache
  or another system's file. In a Claude session, tell Evan to type `! ela login tvu`; do not paste a
  SID for him.
- **A bundle's SaaS rows mirror the lane; its docker rows are its content** (`bundle`). Never read a
  bundle's SaaS row as a frozen version — `envs` is the version source.
