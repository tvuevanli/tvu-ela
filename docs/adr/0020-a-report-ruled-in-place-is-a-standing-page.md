# 0020 — A report ruled in place is a standing page

Status: accepted, 2026-11-12. Settles the question ADR 0017 left open in its Consequences; the rest of 0017 stands.

## Context

ADR 0017 named every note with a `date` from that date, with a list of standing pages exempt. It left one case to the
owner: a report ruled in place (`ela/system.md`, a project's design) carries a date and is not on the list, so the lint
named it. On the vault of 2026-11-12 that was seven lines a pass (the four `ela/` reports and three in
`projects/mediahub-bot/`), none of which a rename would improve: each is read by its name and updated in place. The
desk's brief of the same day (`<runtime>/drafts/2026-11-12-ela-followups-brief.md`, item 7) ruled them standing pages.

## Decision

- **A report named by its slug is a standing page.** The report spec already offers two names, `<slug>.md` and
  `<date>-<slug>.md` "when it is of a day"; the first is now exempt from the date-in-name lint, as a project's page is.
  A report named with a date keeps the rule.
- **A standing report may carry `updated` in place of `date`**: the day it was last brought up to date, where `date`
  would be the day it was first written. The spec requires one of the two.

Rejected: renaming the seven to `<date>-<slug>.md`. Their date is the day they were first written, not what they are
about, and every link to them would change for an ordering nobody reads them by. Rejected: a list of exempt paths in
the code; a path list goes stale with the next report, the name form does not.

## Consequences

- The lint stays quiet on the seven without a rename; a report written for one day is still named from its date.
