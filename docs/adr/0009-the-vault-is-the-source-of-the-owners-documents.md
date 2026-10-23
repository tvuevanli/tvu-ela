# 0009 — The vault is the source of the owner's documents

**Supersedes** the part of ADR 0008 that keeps every note in the vault generated and the vault free of sources.

**Decision.** The owner's Obsidian vault holds, as their only source, the documents written for him to read and
think with: ela's overview (its design and abilities), the workflow, plans that wait for his decision, and the
library's topic pages. ela writes and updates them in place, in Obsidian's form, with `source: "vault"` in their
front matter; the vault sync reads them for Home and the library index and never writes, moves or removes them.
Everything else in the vault stays generated as ADR 0008 describes: Home, the morning pages, the board,
verifications, reviews, How ela runs, the library index and its source lists, and the decisions and the standing
plan that elak keeps because ela applies them. Each document has one home.

**Reason.** On 2026-10-23 the owner chose to act on the split by reader now rather than when the vault becomes a git
repository: the vault is young and changes daily, and there is nothing in these documents that must be preserved
as history yet. Writing them in place removes the conversion layer (joined lines, links, renamed files) between
what ela writes and what he reads. The decisions and the two-week plan stay in elak because skills cite them and
ADR 0007 keeps the window there.

**Safety.** The vault has no history of its own until it becomes a repository, so the daily backup
(`ela-runner backup`, 02:00) copies it, without attachments and Obsidian's window state, to the same private branch
as the reports. A topic page follows `skills/vault/obsidian/topic-template.md`.

**Rejected.** Waiting for the repository (the owner decided against it); moving the decisions too (they are ela's
working rules, cited by skills); letting the owner edit the vault (the vault abandoned on 2026-10-10 died of upkeep).
