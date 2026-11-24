# 0023 — The evening pass proposes what the assistant should do better

Status: accepted, 2026-11-23. Uses ADR 0018's ask shape and ADR 0014's ask slots on today.md. It adds no class, grants
nothing and writes nothing live. Its clause "Who decides follows who would notice" is superseded by ADR 0024
(2026-11-24): his word is needed only when carrying a fix out would send, post or write to Jira.

## Context

The evening pass reviews one artefact, the morning page (`ela review reader`), and records what the day taught as
facts and preferences. Nothing in it asks whether the system itself cost the owner time: a mediahub-bot answer a
colleague had to question, an ela thread he followed up twice, a vault line that took a second round, a timer that
failed again. The owner asked on 2026-11-23 whether ela proposes such improvements daily across mediahub-bot, the ela
Slack bot and the ela system including the vault workflow; it did not, and he left the design to ela.

The record to propose from already exists on disk. Read back over three days (2026-11-19, -20 and -23):

- mediahub-bot's run log (`runs.jsonl`, `threads.json`) held 5, 11 and 2 tasks, each with its verdict, confidence,
  gaps and the number of runs its thread took.
- ela-runner's job records held 20, 22 and 6 asks from the owner, Slack and vault together; three threads took more
  than one turn; three jobs failed and two were still running hours after they started.

Every one of these was visible only to someone who went looking.

## Decision

- **One verb, `ela improve`, holds the loop.** `digest` reads the day's signals deterministically (mediahub-bot's runs,
  ela's jobs with follow-ups in one thread, failed and stuck jobs, failed runner units, the owner's feedback, the items
  still open). An evening session reads the digest and proposes items; `add` checks and stores them; `section` gives
  the reader page its Improve lines.
- **At most three items a day.** An item names its area (mediahub-bot, ela-bot, vault, runner, ela), the problem, the
  evidence (permalinks, job ids), the fix and who decides. An item that is the same problem as an open one is recorded
  as seen again on that day, not stored twice; how often a problem recurs is what ranks it.
- **Who decides follows who would notice.** A fix inside ela, the runner, the vault or Helm's ela-backed parts is ela's
  to make: the item starts as `go`, and an owner session opened in the projects root is told what is waiting. A fix a
  colleague would see (mediahub-bot's answers, a post, a Jira habit) takes an ordinary ask slot on today.md with A go ·
  B drop it; the vault sync records his letter itself, since a letter writes nothing outside ela.
- **Nothing is deleted.** A dropped item stays in `<reports>/ela/improve.json` with the day and the letter; a done item
  says what now behaves differently.
- **The runner proposes, ela stores.** The evening pass in ela-runner calls `digest`, `add` and `section`; the verb
  names, flags and the store path are the interface between the two repositories.

## The gate (CLAUDE.md §Gate)

- Problem and evidence: three days of run logs and job records show repeated threads, failed and stuck jobs and bot
  gaps that no pass reads; the evening pass reviews only the morning page.
- Strongest alternative: extend the reader session's Learned section with improvement lines. Rejected: Learned is
  free text with no state, so a proposal could not be answered, carried out, counted when it recurs or kept when
  dropped. Doing nothing leaves each cost to be found by the owner, one at a time.
- Conflict with a recorded decision: none. Items a colleague would see go through the confirm the charter requires;
  the ask is an ordinary slot under ADR 0014's cap and expiry.
- Verdict: build it. Rejected options: an unbounded list (a section that is skimmed is not read), and ela carrying out
  a fix a colleague would see on its own judgment.
