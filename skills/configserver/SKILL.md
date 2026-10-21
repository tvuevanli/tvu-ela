---
name: configserver
description: TVU Config Server, read-only, values redacted — a service's runtime config per environment. Use for "配置中心", "这个 key 在 prod 是多少", or when a decision turns on a config key.
user-invocable: true
---

# /ela:configserver <app> <profile> [--key k] — the runtime value, read first-hand

Self-contained. All reads go through `ela configserver` (`${CLAUDE_PLUGIN_ROOT}/skills/configserver/configserver.py`),
under the person's TVU session from `ela login tvu`; exit 4 names that command.

```bash
ela configserver apps [--grep text]                      # application names this account can see
ela configserver profiles <app>                          # its environments
ela configserver effective <app> <profile> [--key k]…    # what the service receives, each value marked (default) or (<profile>)
ela configserver get <app> <profile|all> [--key k]…      # stored items, with id and updateTime
ela configserver search <text>                           # key or value contains text, across all applications
ela configserver history <app> <profile> <key>           # the last five versions, the current marked
```
Every subcommand takes `--json`, redacted identically. Exit codes: 0 ok · 2 usage · 3 not found (what
was searched is printed) · 4 session refused · 5 remote error.

## Invariants
- **Read-only.** The script calls five GET paths and names no write, rollback, pending-confirm,
  cipher or plaintext-search endpoint. A config change, a refresh or a rollback is the owning team's
  act and appears in a handoff as a request.
- **Redaction is always on.** A key whose name carries a credential word (password, secret, token,
  cert, keystore, apikey, clientId, …) or whose last segment ends in `key` (`admin.key`, `appKey`), a
  `{cipher}` value, or a value shaped like a credential (the backend's
  own detector rules, a URI with user:pass@, a JWT, a long hex or base64 blob) prints as
  `<redacted: N chars, shape, reason>`. False positives are accepted: `center.version.renewToken` is
  a platform-version map, redacted by its name. The owner reads such a value in the web UI; the
  session names the key and says it was withheld. A value never enters a tracked file, a ticket or a
  Slack draft beyond what the command printed.
- **The profile is found from the log, not read off it.** The java-log's `app[env]` are the
  service's own `elk.config.indexName` and `elk.config.env` (logback `springProperty`, e.g.
  mx-service `logback-spring.xml:14-15`), not the config application and profile: mx-service logs as
  `ur-caller[prod3]`. Map it back with `ela configserver get <app> all --key elk.config.env`; the
  profile whose value equals the log's env is the one the service runs. When several share it (in
  mx-service, `prod` is set by `default`, `mx_service_prod`, `mx_service_prodcn1/2` and `urv4`), say
  the profile is ambiguous and name the candidates. The config application is the service's
  `bootstrap.properties` `spring.cloud.config.name`, never the log's app name.
- **Absent is a finding.** A key the code reads that is absent from both layers means the code's own
  default applies (`@Value("${k:default}")`, a field initialiser): read it from the code and say so.

## Layering, and what it rests on
The server is Spring Cloud Config over JDBC (`spring.profiles.active=jdbc`, the query selects
`status = 1 and delete_flag = 0` items of one application, profile and label; config-server-backend
`src/main/resources/application.properties:35,43`). A client asking for (app, profile) receives the
profile's properties layered over the app's `default`, the profile winning per key — the framework's
documented composition, applied by `effective` to the stored items, not read back from the server.
No shared `application` app exists in this server's list, but a service may load several
applications: its `bootstrap.properties` `spring.cloud.config.name` lists them (MediaHub reads
`command-center-plus,tvu-media-hub`). `effective` layers one application; read each named one, a
name without the service's profile contributing its `default` only, and say that the precedence
between names is the framework's (the later name wins, unverified here) when the same key is in two.
`{cipher}` values are decrypted for clients by the server; this sense never asks it to.

## Boundaries and quirks
- The service-to-service paths (`/config/{app}/{profile}`, `/api/get/…`) are IP-whitelisted and
  answer 401 to this machine. That is the boundary; do not work around it.
- An expired SID answers HTTP 200 with errorCode -1 and a login URL; the script treats it as a
  refused session, records it on the session, and exits 4. `ELA_TVU_SID=<sid>` overrides the stored
  session for one run without recording a refusal.
- `/op/profile/get` fails (HTTP 500, errorCode 2002, a NullPointerException) when `searchKey` is
  absent although the API definition marks it optional; the script always sends it. An observed
  quirk of the server, not something to fix from here.
- `search` sends its text in the URL, which the server logs: search by key text, never by a value
  that might be a secret.
- `valueType` is 0 string / 1 boolean, not a secrecy marker.

## Who uses this and when
The failure-localisation steps in `/ela:logs` (step 4, runtime config), and through them `/ela:route`
and `/ela:probe`: when the code's decision turns on a key, `ela configserver effective <app> <profile
found from the log env> --key <key>` replaces "have the owner confirm"; a redacted or absent key falls back
to it.
