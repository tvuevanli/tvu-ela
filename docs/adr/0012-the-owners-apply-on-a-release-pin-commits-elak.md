# 0012 — The owner's apply on a release pin commits elak

Status: accepted, 2026-10-27. Adds a third case to ADR 0011's "his word commits elak"; the rest of 0011 and 0001
stands.

## Decision

- **The official release bundle per line is a ruled fact in elak.** `<elak>/blueprint/releases.yaml` holds, per
  release line, the bundle ruled as the one its prod lane runs: its name, its id on the prod host, the date
  it was set and by whom.
- **One verb writes it.** `ela release pin <line> <bundle>` resolves the bundle on the prod host and shows the
  change; with `--apply` it writes that one entry and commits `blueprint/releases.yaml` alone. The morning offers
  it as an `apply N` when a release-named bundle newer than the pin exists; the owner's tick is his word for
  exactly that entry.
- **Readers.** `ela matrix` and `ela changes` read the pin; without one they infer prod's bundle from the newest
  release-named bundle and mark it unconfirmed. ela does not read Helm's own pin file; Helm reads this one, and its
  file retires once it does.

## Reason

GM records no deployment, so which bundle a prod lane runs cannot be read; it can only be ruled. The prod lane's
bundle had been guessed from the `rc` lane token, which release bundles do not follow ("MediaHub 2.1.15" took
prod 3 on 2026-10-26 while the guess showed a September bundle). The ruling existed only in Helm's data, and ela
depends on first-hand sources, never on a caller, so the fact moves to elak with the other ruled facts. A
one-entry write behind an explicit apply keeps ADR 0001's review: the item states the line and the bundle before
the tick.

Decided by the owner on 2026-10-27, after the design session proposed elak as the home and an elak commit on
apply as the write.
