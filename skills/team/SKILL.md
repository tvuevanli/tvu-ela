---
name: team
description: The MediaHub roster, first-hand — who a name, email, Slack id or Jira account is; the emails a caller may look up; a live check of the roster against Slack. Use on "who is X", "X 的邮箱", "who owns the UI layer", "is this person on the team", before assigning a ticket or addressing a Slack message, and whenever an answer needs a person's identity.
user-invocable: true
---

# /ela:team — people are identified by the roster, never guessed

Self-contained. `team.py` is the capability; `ela team …` / `ela who …` at the shell are the same thing.
Source: `<records>/knowledge/products/mediahub/team/roster.yaml` — elak at the office, the published copy on
a remote site (same path). Decision `2026-09-03-people-identified-by-the-roster-never-guessed`.

```bash
T="python3 ${CLAUDE_PLUGIN_ROOT}/skills/team/team.py --env-file <env>"     # or: ela team … · ela who …
$T list [--area ui]          # everyone: name · role · area · email · slack id · jira accountId
$T who robin                 # one person by name fragment, email, Slack id or Jira accountId; exit 3 when unknown
$T emails                    # the roster's emails (any full address may still be looked up directly — the roster only resolves names)
$T check                     # read Slack users.list (a minute) and report any email/id that no longer matches
```

## Invariants
- **First names are the aliases** (wilson, kris, robin, bom …): an exact first-name match outranks a substring; a surname shared by several people is an ambiguity and is listed, not picked.
- **Unknown means unknown.** A query that matches nobody exits 3 and says "not in the roster". The answer to the
  user is that the roster does not carry the person — not a composed address. Robin Wu's address is `rwu@`, not
  `robinwu@`; the composed form was looked up live once (2026-09-03) and was wrong.
- **Adding a person is a first-hand act.** `ela slack users <name>` returns the Slack id, the profile email and
  the title from `users.list`; a Jira accountId comes from a ticket the person is assigned to (`ela MH-… --json`).
  Both go into `roster.yaml` with the source line updated, then `ela publish roster`. Never from memory, a
  signature, or a pattern.
- **Role, layer and reporting line come from Helm's team table and team-map.** Empty where those files record none; the skill does
  not infer a manager from an area.
- **`external: true` is a counterpart, not a member.** They are addressable (their graphs can be looked up),
  never assigned MediaHub work by ela.
- Read-only. `check` reads Slack; nothing here writes anywhere but the roster file when Evan says so.
