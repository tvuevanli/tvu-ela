# 0008 — The owner reads ela in a generated Obsidian vault

*Status: the layout, naming and property rules are superseded by ADR 0010 (2026-10-23); the rest stands.*

**Decision.** ela reports to the owner through an Obsidian vault on his Windows disk, written entirely by
`skills/vault/vault.py` (`ela vault sync`) after the runner's morning and evening jobs. The vault holds only what
is written for him: the judged day pages, reviews, verification results, and elak's decisions and plans. Every
note passes a reading gate (a title heading, a budget in words per kind, little code, no machine paths) or carries a
warning under its title and is listed on Home for 30 days as a rewrite ela owes; nothing readable is withheld.
Folder and file names are lowercase and hyphenated and come from the source file's name, never its heading, so an
edited title renames nothing;
top folders are numbered by range (10–19 by time, 20–39 reports and evidence, 40–59 records, 60–79 reserved,
80–99 system), and a dated archive is split by year, a high-volume one by month, so the vault grows without
renames; a generated `readme.md` at the root states the layout; the properties are `type`, `date`, `kind` and `status` and nothing else; a
ticket key is a direct Jira link. Nothing in the vault is edited by hand. Its `.obsidian/` settings were set once and the sync never touches them: reading
view by default, no file-name title or properties panel, the writing plugins off, and one community plugin,
Homepage, so the vault opens on Home; a vault that needed eleven plugins was the one abandoned. A missing source, an unreadable manifest, or a folder that would shrink by more than half stops the
sync before it writes; removal is limited to files the sync recorded; writes are atomic and serialised. A ticket
key links only when its project is one the owner works in and its prefix is not a codec's or a standard's name.
Helm's `/ela` pages retire after a week in which the vault served every morning, and once the morning direct
message carries a link that opens the vault page.

Revised the same day after an adversarial review: notes that fail the gate are flagged rather than withheld, and
names come from file names rather than headings.

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
weight); extending Helm's pages for reading (Helm is shrinking to board, ledger and team report). Mirroring Helm's team daily and weekly reports (written for the team, they stay in Slack and Helm; the
owner's need from them is the morning page's Yesterday section, and a gap there is fixed in the brief, not by a
second copy). The owner's weekly view, when it comes, is a page ela writes for him from the week's Yesterday
sections and the sprint's state (`15-weeks/<year>/<year>-w<nn>.md`), first on the Friday of the first sprint week.
