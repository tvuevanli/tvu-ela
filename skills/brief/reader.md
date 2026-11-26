# §reader: the evening read of the morning page

Part of ela's brief skill, read by the evening session; it is that mode whole. `§` numbers name sections of `SKILL.md` beside this file; the other
parts are `unattended.md`, `page.md`, `files.md`, `meetings.md` and `reader.md` in the same folder.

## §reader — the evening read of the morning page

ela changes every week, so the owner's own use of a page is too little evidence to judge the workflow, and too
late. Every working evening a session reads that morning's page `<reports>/runner/<date>-brief.md` exactly as he
would. It reads under his rules (`working-with-evan.md`, the vault guide, the decision notes the page links) and
against the same sources the page cites. It writes `<reports>/review/<date>-reader.md`. It ticks nothing, posts
nothing and edits no page: its output is evidence for the next morning's judge and for ela's own review.

**Per item, one verdict and one line:**

| verdict | when | the line |
|---|---|---|
| tickable | he could tick a box within 30 seconds, without opening anything else | which box he would tick |
| question | he would have asked something back before acting | the question, written as he would ask it |
| handed back | the item leaves him work ela could have finished unattended: a lookup, a draft, a breakdown, a probe | the work, and the tool that does it |
| wrong | a fact the sources contradict | the fact, and the source that contradicts it |
| noise | state with no action for him: a row restated as an item, a parked note that has not woken, his own move reported back | why it carries nothing |

One verdict per item: the first that applies, in the order wrong, handed back, question, noise, tickable. A
wrong fact outranks everything, because he would act on it.

**The questions he asks back.** These are the shapes seen in the week of 2026-10-26. Each is a "question"
verdict when the page invites it:
- *Is this mine at all, or someone else's to answer?* An external hold or a customer mail addressed to a
  colleague was put to him as a reply to draft. The addressee test exists for this (§3 order, 2026-10-27).
- *Did you evaluate it, or only list it?* A finding reached him with no verdict on whether it needs him, when
  "FYI, held by X" was the answer (2026-10-26).
- *Which service?* "The frontend" or "the backend" when the product has several of each, or "a frontend
  version" for a change that also lives in UR Caller and a docker (2026-10-27, the HTML input change). Services
  are named by slug.
- *Did I say that?* A ruling read wider than he gave it. On 2026-10-26, "measure the sprint from 2.1.15" was
  read as "2.1.15 is the authority on every version".
- *What does this term mean?* A term from a code base or a vendor used without a clause of meaning (a field
  name, a placeholder in a config value).
- *Who has it now, and has anyone answered?* On a parked or waiting note (the RVF options for v3 Packs, parked
  on a customer thread, 2026-10-27), the item gave the draft again instead of the thread's state since.

**Then three lines for the page:**
- **Read first:** the item his eye would land on, and whether it deserved to be first.
- **Skipped:** what he would not read, and why (it was a table restated, a row he cannot act on).
- **Missing:** what he would have wanted that the sources held: a ticket moved, a thread answered, a lane
  changed, a number that did not add up.

**The next morning's judge reads it.** Before ranking, the morning session reads the newest
`<reports>/review/*-reader.md`:
- An item judged *handed back* is never offered in the same shape again. Either ela does the work before the
  page and carries the result as an `apply N` or a note link, or the item says in one line why it cannot be
  done unattended.
- An item judged *question* comes back with that question answered in its facts line. It does not come back
  as the same item with the same gap.
- An item judged *wrong* is corrected on the page, and says what was wrong yesterday.
- An item judged *noise* becomes a table row or leaves the page.

The page fails this rule when the same key carries the same verdict two mornings running. `ela brief --lane
carried` reports that next to the morning count.

*Why: on 2026-10-27 ten of thirteen Do lines handed work back, and every correction that week came from the
owner noticing it himself. A reader that runs every evening catches the shape before he has to.*

**The file and its check.** `ela review reader --date D` prints what the session reads: the page, its numbered
items, the day's actions, `<reports>/review/<D>-replay.json` and the page's lint failures. It also prints the keys
that already carry a repeated verdict. The session writes the heading `# The reader · <D>` (the vault's spec for a
reader page), then one table, `| item | verdict | line |`, with one row per
item: the item as `N. title`, a verdict from the five above, and its line. Under the table go the three page lines
as `- **Read first:** …`, `- **Skipped:** …` and `- **Missing:** …`. `ela review reader --date D --check` verifies the
file before the session ends: one verdict per item, each from the set and with its line, and the three page lines.
A failed check is fixed before the reader file is final. A passing check writes `<reports>/review/<D>-reader.json`,
the findings the next morning's judge takes as input: a list of `{kind, item, key, what}`, one per item read
`wrong`, `handed-back` or `question`, and one `skippable` for the Skipped line.

**Corrections.** `ela review replay` reads what happened after each tier-1 and tier-2 action the runner applied. A
field ela set and a colleague set otherwise (a label taken off, a Fixed In changed, an assignment moved within a
working day) is a correction, counted. A reply after a tier-1 comment or a tier-2 post is printed by `ela review
reader` as `judge action N`, and the reader judges it under a `## Corrections` heading, one row per action, `|
action N | contradicts / agrees / unrelated | line |`; the check fails an unjudged one. A reply that contradicts
is a correction on that action's rule. Replay and the passing check write `<reports>/review/tiers.json`: each rule's
corrections in the last seven days, and `demoted` once there are three, which the morning reads (`unattended.md`, the tiers).

**Signed writes, sampled.** Replay also puts up to five of the day's signed writes (ela's own tier-1 acts in the dry
record) before the reader, fixed by the day and the act; `ela review reader` prints each as `audit act <id>`. The reader
reads the ticket first-hand and judges whether the reason the signed comment gave holds, under an `## Audit` heading, one
row per act, `| act <id> | holds / fails / unclear | line |`; the check fails an unaudited one. `fails` is a correction on
the act's class, its line the cause (it returns the class to confirm and reaches the improve digest); `unclear` is a
question for the morning (decision 2026-11-24, amendment on learning from ela's own writes).

