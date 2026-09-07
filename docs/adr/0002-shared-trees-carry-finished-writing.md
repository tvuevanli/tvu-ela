# 0002 — shared trees carry finished writing

**Decision.** ela, Helm and the published directory are read by colleagues. A tracked file or commit
message there states the rule in force and its engineering reason, cites the origin by ticket key,
link, or date and role, and names people by role. It does not narrate a session, quote what someone
said, or date itself to a conversation. A rule that arises in a conversation is drafted first and
written to a shared tree in a later pass.

**Reason.** Text written in the same breath as the conversation that produced it reads as the
conversation: tentative, dated, personal. Readers cannot tell a settled rule from a passing remark,
and a person's sentence in someone else's repository is a liability that a later edit cannot recall
once pushed.

**Enforced by** `hooks/content-guard.sh` (ADR 0003).
