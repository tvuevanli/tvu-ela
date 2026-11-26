---
aliases: ["manual"]
type: "manual"
updated: "2026-11-26"
covers: ["2026-11-24-plan-today-opens-with-what-the-day-is-about", "2026-11-25-plan-read-once-at-fixed-times", "2026-11-26-plan-every-notice-goes-through-one-tier-gate", "2026-11-26-plan-fixes-followed-to-prod-one-home-per-fact", "2026-11-26-plan-ela-runs-on-its-own-asks-teach-it", "2026-11-26-plan-ela-described-in-the-vault-from-its-sources"]
---

# How you use this vault

ela runs on its own and writes this vault. You do two things here: give a **fact** ela asks for, and **rule** on what ela is not sure of. Everything else is for reading only when you want it. This page changes whenever the way you use the vault changes; its date is at the foot.

## Your day

1. **Open [[today]].** Read **In short**: at most five lines, most urgent first, each with what it means and what to do; the last line says where to start.
   Under **Today**, the line **Team yesterday** opens the team daily report as it went out to Slack, with a **For you** block on top (at most three lines: your tickets, mentions of you, and any line that contradicts Jira). On Mondays a second line opens the weekly.
2. **Answer what is under Needs you.** Each ask is lettered; A is ela's recommendation. Tick a box, or write `ela: A` under it (`ela: 2 B` anywhere on the page). An ask you leave does nothing; after three working mornings it moves to [[reference/dropped|dropped asks]].
3. **Follow a link only when a line is not enough.** The morning page and the changes page under `reference/days/` hold the evidence behind today.md; you do not need to read them every day.

## Where things live

| place | what it is for |
|---|---|
| [[today]] | the day: what matters, what needs you |
| `releases/<line>/` | a release line and its deploys: lanes, the next promotion, builds, QA's verdicts per fix |
| `projects/` | bounded work with a deadline, one page each |
| [[meetings/focus\|meetings/focus]] | the team's focus board; [[meetings/open-questions\|open questions]] beside it |
| [[ela/watch\|ela/watch]] | board-watch topics waiting for your letter |
| `ela/dry/` | Jira writes held for your A; `did.md` lists what ela wrote on its own |
| `ela/` | how ela itself works and its plans; you do not need it day to day |

## The words you can write

On any live row or ask, as a tick or an `ela:` line under it:
- `A` / `B` answers it.
- `hold <subject or key> [until <date or event>]` parks a subject on every page; `ela: resume <subject>` brings it back.
- `up <key> [why]` / `down <key>` drafts a priority change, asked back to you before Jira moves.
- `done` or `drop` closes a note where it is; nothing is deleted.
- Any other `ela: …` line is read as an instruction; one that needs a session shows `queued`, its answer later under it.

The vault is read every three minutes, 08:30–19:00 on working days: a line taken shows `✓ 10:42`, a refused one `✗` with the reason folded under it. A line written outside those hours is taken the next working morning.

> [!note]- The board watch: answering it, and correcting what it wrote
> To answer a topic: `ela watch answer watch:<KEY> <letter>` in a terminal. Each decision the watch makes carries a confidence: high and medium are written to Jira and listed on `ela/dry/did.md` (everything below high under **Review first**, at the top, with what the evidence leaves open); low, or a case ela cannot decide, is not written: it waits at the top of [[ela/watch|ela/watch]] under **Confirm first**, where A carries out what ela proposed. Tickets the watch judged nothing due close that page, least sure first. To correct something ela wrote on its own: `wrong: <why>` beside its line on `ela/dry/did.md`; the reason is kept, so the same mistake is not repeated.

## What ela does on its own, and what stays yours

- **ela's alone**: what the pages say and in what order, summaries, folding.
- **ela's, step by step**: Jira fields, labels, links and status comments; each kind starts by asking you. Once enough of them have gone through as drafted, ela asks you once whether it may do that kind unasked; on your yes it does, and lists each one on `ela/dry/did.md`. One correction sends it back to asking.
- **ela's only with proof**: anything that would take a risk out of your sight (a fail judged not to block a deploy, a mention judged to need nothing). Without first-hand proof it becomes an ask.
- **Always yours**: anything posted in Slack, any close, product and team decisions.

## In a session

Two tags, each written alone in your message (not quoted, not in code):
- `#zh`: ela answers in Chinese from that message on, until you ask for English.
- `#send`: the Slack post answering that one message goes out as ela without a preview; you get its link afterwards. It still stops for a preview when the post would go under your name, reach a person or thread you did not name, commit to a date, an owner or a release scope, or rest on a fact ela is not sure of.

## In Slack

Every word and button you can use with ela in Slack, and who else reaches it: [[ela/controls|your controls in Slack]].

Slack only reminds; the question itself is always here. A direct message from ela means one of: a prod incident addressed to you (at any hour), a question put to you that is still unanswered after its wait (inside your DM hours; outside them it becomes an ask on [[today]]), or one of ela's passes failing. Board-watch topics get at most one reminder a day, when a topic is new. The daily and weekly team reports are the only posts that go out on their own.

## Coming

> [!note]- Two changes on their way
> - Each ask will say whether it needs a **fact** or a **ruling**, and a ruling ask will carry ela's reason for you to confirm or correct ([[2026-11-26-plan-ela-runs-on-its-own-asks-teach-it|plan]]).
> - The release line page will gain **Fixes on their way**: each fix from build to prod with what changed, what QA tested, the verdict, ela's judgment of its impact on the deploy, and what is next; today.md's Facts will become **Since you last looked** ([[2026-11-26-plan-fixes-followed-to-prod-one-home-per-fact|plan]]).

---

*Updated 2026-11-26. The rules behind this page: [[ela/about-this-vault|about this vault]].*
