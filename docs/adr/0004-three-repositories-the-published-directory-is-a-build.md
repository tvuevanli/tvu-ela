# 0004 — three repositories; the published directory is a build

**Decision.** ela, Helm and elak are the only git repositories. The published directory is produced
by `ela publish` from elak sources and can be deleted and regenerated at any time; it has no history
and is never edited. The site directory, the runtime directory and the reports directory are not
versioned.

**Reason.** Each repository has a distinct audience and lifecycle: a tool others may reuse, an
application with tests and a deploy, and private knowledge. A fourth repository for the shared
subset would need its own review and would drift from its source; a generated directory cannot.
Working state and personal reading material have no second reader and gain nothing from history.
