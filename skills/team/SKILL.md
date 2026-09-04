---
name: team
description: The MediaHub roster, first-hand — who a name, email, Slack id or Jira account is; the emails a caller may look up; a live check of the roster against Slack. Use on "who is X", "X 的邮箱", "who owns the UI layer", "is this person on the team", before assigning a ticket or addressing a Slack message, and whenever an answer needs a person's identity.
user-invocable: true
---

# /ela:team — people are identified by the roster, never guessed

Self-contained. `team.py` is the capability; `ela team …` / `ela who …` at the shell are the same thing.
Source: `<records>/knowledge/people/` — `people.yaml` (identity only) joined by email to
`responsibilities.yaml` (one row per responsibility; a person holds several). Decisions
`2026-09-03-people-identified-by-the-roster-never-guessed` and `2026-09-04-people-carry-responsibilities-not-rank`.

```bash
T="python3 ${CLAUDE_PLUGIN_ROOT}/skills/team/team.py --env-file <env>"     # or: ela team … · ela who …
$T people [--area ui] [--scope core|related]   # everyone: name · scope · areas · email · slack id · jira accountId
$T areas                     # every area, who to ask first about it, how many people are in it
$T who robin                 # one person: identity, then every responsibility they hold; exit 3 when unknown
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
- **No rank is recorded.** No title, no seniority, no reporting line — MediaHub responsibility is de-facto and TVU has
  no titles that match, so a level could only be invented, and it would read as a hierarchy between people. What the
  consumers actually needed is narrower: `routable` (may this person be assigned), `first_contact` (who to ask about an
  area when the owner is unknown — per person-and-area, not comparable across areas), and `review_means` on the person
  (what a Jira ticket sitting in Review means in their hands: anomaly · verification · signoff · empty, and empty is
  safe — Helm stays silent on an unrecognised assignee). Decision `2026-09-04-people-carry-responsibilities-not-rank`.
- **`scope: related` is a counterpart, not a member.** They are addressable and their graphs can be looked up; they are
  tagged or looped, never assigned MediaHub work. Derived per person as the nearest scope they hold.
- **Ownership rows are generated.** `origin: generated` comes from Helm's service catalogue and elak `map/services.yaml`
  — correct the source, not the roster. `origin: manual` rows carry their own `source`.
- Read-only. `check` reads Slack; nothing here writes anywhere but the roster file when Evan says so.
