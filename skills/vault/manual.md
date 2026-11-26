---
aliases: ["manual"]
type: "manual"
updated: "2026-11-26"
covers: ["2026-11-24-plan-today-opens-with-what-the-day-is-about", "2026-11-25-plan-read-once-at-fixed-times", "2026-11-26-plan-every-notice-goes-through-one-tier-gate", "2026-11-26-plan-fixes-followed-to-prod-one-home-per-fact", "2026-11-26-plan-ela-runs-on-its-own-asks-teach-it", "2026-11-26-plan-ela-described-in-the-vault-from-its-sources", "2026-11-26-plan-permanent-pages-apart-from-working-notes", "2026-11-26-plan-weekly-ai-radar", "2026-11-26-plan-tickets-reach-you-judged"]
---

# How you use this vault

ela runs on its own and writes this vault. You do two things here: give a **fact** ela asks for, and **rule** on what ela is not sure of. Everything else is for reading only when you want it. This page changes whenever the way you use the vault changes; its date is at the foot.

## Your day

1. **Open [[today]].** Read **In short**: at most five lines, most urgent first, each with what it means and what to do; the last line says where to start.
   **Since you last looked** follows, at most five lines; a fix whose QA verdict changed leads it and links its row on the release line page.
   Under **Today**, the line **Team yesterday** opens the team daily report as it went out to Slack, with a **For you** block on top (at most three lines: your tickets, mentions of you, and any line that contradicts Jira). On Mondays a second line opens the weekly.
   A ticket of yours named there shows ela's verdict and links its page; [[ela/watch|ela/watch]] lists every ticket ela judged.
2. **Answer what is under Needs you.** Each ask needs a *fact* or a *ruling*; A is ela's recommendation, with its reason. Tick a box or write `ela: A` under it; words after the letter are kept as your reason. An unanswered ask expires after three working mornings.
   A deploy ruling (does this fix's QA fail block the next move?) is an ask like any other: ela's leaning is A with its reason; if it is wrong, tick B or write `ela: B because …`, and the reason decides the next fail of that kind. Rulings beyond three wait on the line page under **Fixes on their way**, answered there the same way: tick under the row, or write `ela: B because …` under it.
   On a week when the radar finds something to adopt or try, one line under **Today** (Friday to Monday) opens [[ela/radar|the radar]]; ela takes the adopt items into its own work. To correct a verdict, write an `ela:` line under its item.
3. **Follow a link only when a line is not enough.** The morning page and the changes page under `reference/days/` hold the evidence behind today.md; you do not need to read them every day. On Fridays the changes page ends with **Quiet for two weeks**: live notes whose text has not changed in 14 days, with what each waits for; write `done` on one that is finished, or leave it.

## Where things live

> [!note]- Every place and what it is for
> | place | what it is for |
> |---|---|
> | [[today]] | the day: what matters, what needs you |
> | `releases/<line>/` | a release line and its deploys: lanes, the next promotion, **Fixes on their way** (blocks, your call, not yet verified, does not block), builds |
> | `projects/` | bounded work with a deadline, one page each |
> | [[meetings/focus\|meetings/focus]] | the team's focus board; [[meetings/open-questions\|open questions]] beside it |
> | [[ela/watch\|ela/watch]] | board-watch topics waiting for your letter; your tickets ela judged this week, each with its verdict |
> | [[ela/radar\|ela/radar]] | what is new in Claude and AI tooling, each item judged for ela and mh-bot (adopt · try · watch · none); rewritten each Friday, earlier weeks folded |
> | `ela/dry/` | Jira writes held for your A; `did.md` lists what ela wrote on its own |
> | `ela/` | how ela itself works and its plans ([[ela/all-notes.base#Plans\|Plans]] lists every plan by folder, newest first); you do not need it day to day |
> | `history/` | done work: a closed note in `ela/`, `reference/` or a release line moves to that folder's `history/` the day after it closes, unless you edited it since or have it open; links to it keep working |

## The words you can write

On any live row or ask, as a tick or an `ela:` line under it:
- `A` / `B` answers it.
- `hold <subject or key> [until <date or event>]` parks a subject on every page; `ela: resume <subject>` brings it back.
- `up <key> [why]` / `down <key>` drafts a priority change, asked back to you before Jira moves.
- `done` or `drop` closes a note where it is; nothing is deleted.
- Any other `ela: …` line is read as an instruction; one that needs a session shows `queued`, its answer later under it.

The vault is read every three minutes, 08:30–19:00 on working days: a line taken shows `✓ 10:42`, a refused one `✗` with the reason folded under it. A line written outside those hours is taken the next working morning.

> [!note]- The board watch: answering it, and correcting what it wrote
> To answer a topic: tick a letter on [[ela/watch|ela/watch]], or write `ela: B because …` under it, or `ela watch answer watch:<KEY> <letter> [words]` in a terminal. Each topic shows how sure ela was. Each decision the watch makes carries a confidence: high and medium are written to Jira and listed on `ela/dry/did.md` (everything below high under **Review first**, at the top, with what the evidence leaves open); low, or a case ela cannot decide, is not written: it waits at the top of [[ela/watch|ela/watch]] under **Confirm first**, where A carries out what ela proposed. Tickets the watch judged nothing due close that page, least sure first. To correct something ela wrote on its own: `wrong: <why>` beside its line on `ela/dry/did.md`; the reason is kept, so the same mistake is not repeated. A correction (yours, an undo, or a colleague disputing ela's comment) keeps ela off that field on that ticket for a week; the watch goes on writing elsewhere. To follow a ticket rather than rule on it now: `ela watch track <KEY>… --why <reason> [--until <date>]` (or ask ela to track it); each time a colleague changes it, its state comes back judged against your reason on [[ela/watch|ela/watch]], until `ela watch untrack <KEY>`. [[ela/watch-measure|ela/watch-measure]], linked from the top of ela/watch.md, shows week by week how much of the judged ticket work ela settled without you; nothing there needs an answer.

> [!note]- Your reasons and facts: how ela keeps them
> Your words after a letter (`ela: 2 B because QA already said it`, or a plain line under the box you ticked) are kept with the answer. A letter against ela's A is a correction: ela keeps it with your reason in that kind of ask's own record and cites it the next time the same kind of case comes up. Without a reason it waits for one; the next ask of that kind says so in one line, and `ela: because …` under that ask gives it (for the board watch also `ela watch cause watch:<KEY> <why>`). A fact you give (who owns an area, whose account a name is, a date no source has) is kept by its kind and subject and is not asked again for another ticket. An ask that expires names its note and [[reference/dropped|dropped asks]].

## What ela does on its own, and what stays yours

- **ela's alone**: what the pages say and in what order, summaries, folding.
- **ela's, step by step**: Jira fields, labels, links and status comments; each kind starts by asking you. Once enough of them have gone through as drafted, ela asks you once whether it may do that kind unasked; on your yes it does, and lists each one on `ela/dry/did.md`. One correction sends it back to asking (the board watch's writes excepted: there a correction quiets that field on that ticket).
- **ela's only with proof**: anything that would take a risk out of your sight (a fail judged not to block a deploy, a mention judged to need nothing). Without first-hand proof it becomes an ask.
- **Always yours**: anything posted in Slack, any close, product and team decisions.

## In a session

> [!note]- Two tags you can write in a message: `#zh` and `#send`
> Two tags, each written alone in your message (not quoted, not in code):
> - `#zh`: ela answers in Chinese from that message on, until you ask for English.
> - `#send`: the Slack post answering that one message goes out as ela without a preview; you get its link afterwards. It still stops for a preview when the post would go under your name, reach a person or thread you did not name, commit to a date, an owner or a release scope, or rest on a fact ela is not sure of.

## In Slack

Every word and button you can use with ela in Slack, and who else reaches it: [[ela/controls|your controls in Slack]].

What the MediaHub PM asked for in the design channel and ela already carried out, each request with its undo: [[releases/pm-requests|the PM's release requests]].

Slack only reminds; the question itself is always here. A direct message from ela means one of: a prod incident addressed to you (at any hour), a question put to you that is still unanswered after its wait (inside your DM hours; outside them it becomes an ask on [[today]]), or one of ela's passes failing. Board-watch topics get at most one reminder a day, when a topic is new. The daily and weekly team reports are the only posts that go out on their own.

---

*Updated 2026-11-26. The rules behind this page: [[ela/about-this-vault|about this vault]].*
