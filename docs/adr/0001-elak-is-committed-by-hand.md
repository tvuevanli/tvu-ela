# 0001 — elak is committed by hand

**Decision.** No hook adds, commits or pushes the knowledge base. Knowledge is written when Evan asks
for it to be recorded and committed after the diff has been read. The SessionEnd hook reports an
uncommitted or unpushed tree and does nothing else.

**Reason.** An automatic snapshot made every file written during a session permanent and remote
before anyone had read it as a colleague would. That is the mechanism by which a knowledge base
becomes a diary. A hand commit costs seconds and restores the one review that matters.

**Supersedes** the snapshot policy recorded in elak on 2026-09-02.
