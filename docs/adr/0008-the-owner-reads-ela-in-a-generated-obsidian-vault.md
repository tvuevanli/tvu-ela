# 0008 — The owner reads ela in a generated Obsidian vault

**Decision.** ela reports to the owner through an Obsidian vault on his Windows disk, written entirely by
`skills/vault/vault.py` (`ela vault sync`) after the runner's morning and evening jobs. The vault holds only what
is written for him: the judged day pages, reviews, verification results, and elak's decisions and plans. Every
note passes a reading gate (a title heading, a budget in words per kind, little code, no machine paths) or is held
back and listed on the vault's Home as a rewrite ela owes. Folder and file names are lowercase and hyphenated,
folders numbered in reading order; the properties are `type`, `date`, `kind` and `status` and nothing else; a
ticket key is a direct Jira link. Nothing in the vault is edited by hand, and its `.obsidian/` settings are never
touched. Helm's `/ela` pages retire after a week in which the vault served every morning.

**Reason.** The owner reads more than he writes, and what he reads lived in WSL, reachable from Windows only in a
terminal or over a share Obsidian handles badly. A vault he maintained by hand was abandoned on 2026-10-10: the
upkeep was the cost. A generated, read-only vault has no upkeep, and the gate turns "the assistant made the work
lighter" into a check on every note, because a page that is too long to read has moved work onto the reader.
elak's knowledge and status files are written for ela; copying them would make the vault a second memory rather
than a report.

**Admission (ADR 0006).** Scenario: S1, the owner's queue, now with a reading surface. Layer: one L1 script and a
verb; no skill, because the sync needs no judgment; the judgment of what to write stays in the skills that write
the pages, which now carry the reading budgets (`brief`, `reports`, the runner's evening prompt). Workflow: the
manual's daily flow, Home first. Phase and proof: unproven until a week of mornings in which Home was the first
thing read and no held-back page went unrewritten. Duplication: it displaces Helm's `/ela` pages, which carry the
retirement condition above.

**Rejected.** Mirroring all of elak (a second copy of ela's memory, mostly unreadable to a person); one note per
ticket (two clicks to Jira, a stale copy of Jira's status); community plugins and templates (the abandoned vault's
weight); extending Helm's pages for reading (Helm is shrinking to board, ledger and team report).
