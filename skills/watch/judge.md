# Judge mode: a ticket that reaches the owner arrives judged

Part of ela's watch skill (`SKILL.md` beside this file), read by the session started as `/ela:watch judge KEY --write PAGE`.

## Judge mode: a ticket that reaches the owner arrives judged

`/ela:watch judge KEY --write PAGE` is a different session from the pass above: one ticket, read to the bottom. The
rule is the owner's (2026-11-26; plan ela/2026-11-26-plan-tickets-reach-you-judged in the vault): a ticket assigned to
him in Review, or handed to him, reaches him with a verdict and a link, never as a bare listing. The runner starts it
for each ticket `ela watch judge` lists, at most its daily cap of deep readings, as an unattended session
(`ELA_NO_APPLY`).

**Input.** `ela watch judge-prompt KEY`: the ticket, every comment, the linked tickets, its home in the vault (a
feature or project page listing its own key, then its ticket pages), and every board-watch topic on it with the owner's
letter. **A letter he gave binds the verdict.** Depart from it only on evidence dated after the letter, and then say
in the verdict that you do and why. His letter approved words, not writes: when the option he chose carried no writes
and its words imply one (an assignment, a move), write that act with `confidence: low`, so it waits on ela/watch.md
for his confirm with the writes spelled out; never write it at high or medium on the strength of the letter.

**Gather, first-hand.** The ticket and its links (`ela jira read KEY`, `ela links KEY`); QA's reports on it (`ela mail`,
`ela slack`, `ela digest` for a report or a thread); where its fix is (`ela release`, `ela train`); who holds what
(`ela team`). `/ela:explain` makes the ticket judgeable; `/ela:probe` reads the code. Whatever cannot be read is named
as a gap, never filled from someone's summary.

**Untested parts.** Where something is fixed but QA has not tested it (a case not run, a lane not reached, a branch
of the code no case covers), read the code of that part and say what it does, with file and line, and what could
fail. That reading is ela's own assessment, marked as such; it never replaces QA's verdict.

**The page** (`PAGE`, `<reports>/ela/<date>-deep-<KEY>-judged.md`, its own file beside any deep pick's page that
day; the vault files it as the ticket's page):

- `# KEY · <summary>: <the verdict in a few words>`
- the verdict first: one or two sentences, what the ticket's state is and what should happen next, and who does it
- *Next steps*: each with its owner and, where one is known, its date; a step for the owner is a decision only he can make
- *Untested*: each untested part with the code reading above
- *Drafts*: a comment or a ticket the next step needs, as text for the owner's word (a Jira write goes through the
  decision file, not this page)
- the facts it rests on, folded (`> [!note]- Facts`): QA's results by case and build, the lanes, the timeline, each
  with its source link

**A new topic gets an entry.** When the prompt's home is empty, the topic is new to the owner, and the ticket page you
write is its entry: open it with two lines on what the capability or the problem is, for a reader meeting it the first
time. Open no project and no other page: a project is bounded work the desk opens on a committed date, and the vault's
features/ pages (the owner's ruling of 2026-11-26) come with their own plan. When the topic is a capability that will
outlive this ticket (two or more tickets, configuration or lanes to follow), say so on the page in one line, "a feature
page fits: <key>, <title>", which the desk reads. The mechanism you read first-hand (flow, configuration keys, error
codes) stays on the ticket page with its sources, and may be drafted to `<runtime>/drafts/<slug>.md` for the desk to
admit: an unattended session never writes elak (ADR 0026).

**The decision.** Write `<reports>/ela/watch/<date>-judge-<KEY>.json` with one decision in the pass's form
(`{"decisions": [{...}]}`): act, ask or none, with confidence and doubt as above. It is checked against the judge
queue: `ela watch decide --judge KEY --from <file>` (a dry run). An act or a none closes the ticket's open topic as
superseded; an ask updates it. An option that names a write (assign, move, link, priority, due) carries that write and
its comment, or it is refused.

**The verdict.** Your last message is one line, the verdict, at most 160 characters, ela's own words (never the
ticket's title or a listing). The runner records it with `ela watch judged KEY --verdict "…"` once the page exists
and the decision passed; today.md shows it where it names the ticket, with a link to its home.

