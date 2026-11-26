# The two checkers

Part of ela's promote skill (`SKILL.md` beside this file), read before a run's result is shown to the owner (§1b).

- Spawn the **Jira checker** and the **system checker** in one message, in parallel, each a fresh agent given the draft
  note, the report JSON's path and its own claim list only, never the drafting session's conclusions. The Jira checker reads
  each ticket's QA comment, counts, environment block and splits, and each Fixed In; the system checker reads lane
  versions (`promote proof lane`), profile chains (`facts runtime show`, `configserver effective <app> <chain>`), code
  and branch state (git), live dependencies and the shipped versions. Each returns per claim: confirmed / wrong (with
  the first-hand reading) / unread (with why).
- Every line of the Slack text and every list in the note is a claim of its own: a list is checked for what it
  leaves out (call sites, versions a flag arrives in, the endpoints a call really uses), and a Slack line for the cause
  it states. On the 2026-11-09 rerun, the misses were all of this shape (an incomplete list of gateway call sites, the
  build a flag first arrives in, a Slack line naming the wrong cause).
  Two shapes need the read spelled out, because a checker that verified the gate or the range still passed them
  (the 2026-11-09 rerun): a list of call sites is checked by enumerating every caller of the mechanism (`git grep` the
  method, every path), not by confirming the ones listed; a range claim ("206 → 208 adds …") is checked per item with
  `git merge-base --is-ancestor <item commit> <each build>`, and the note names the build each item first arrives in.
- A claim either checker cannot read is written as unread in the note, never kept as stated. A wrong claim is corrected
  in the note before it is shown, and the checker's reading is cited.
- The note ends its body with `## Checked`: when, the two checkers, how many claims each confirmed, corrected and left
  unread, and each correction in one line. `note.py lint` refuses a note without it.

