# The brief's meeting sections

Part of ela's brief skill, read when the day has an enabled meeting with a time (`ela day --json`, `day.meetings`). `§` numbers name sections of `SKILL.md` beside this file; the other
parts are `unattended.md`, `page.md`, `files.md`, `meetings.md` and `reader.md` in the same folder.

- **One `## <Name> at HH:MM` section per meeting the owner has that day,** right after *Needs you*, in time order.
The meetings are data, not page logic: `<elak>/blueprint/meetings.yaml`, read by `ela day --json` (and in `ela brief --json` as `day.meetings`, each with its `section` heading), gives each meeting's `name`,
`weekdays`, `time`, `audience` and `enabled`. A meeting that is not enabled, or has no time yet, renders
nothing. The list itself lives in one note per meeting, `meetings/<key>.md` in the vault, written only by
`ela meeting --key K`; the section is its pointer: the `pointer` line of `ela meeting --key K --json`
("Scrum with the PM at 10:00 · 4 items on [[meetings/scrum-pm]] · 2 new today") and its `new` items, one line
each, nothing else. No dated meeting note is written.

**What ela proposes.** Before writing the section the judge reads the page's own items, lanes table and sprint
table against the rubric below for that audience and adds each question the owner would bring, as
`ela meeting --key K --propose "<key> — <question>" --decides "<who>"` (one line, at most 140 characters as read;
the verb refuses a longer one, exit 4: shorten it and fold the evidence with `--detail`). It adds no new facts:
each restates an item with the key that holds the evidence. Only the rubric's asks become items (the PM's 3 and 4,
the sync's 2 to 5 where they ask); its status parts (sprint, releases, commitments) are said from the page. The verb skips a question already on the list. His own
`ela: raise <key> — <question>` line, anywhere in the vault or in the DM thread, is
`ela meeting --key K --raise "<key> — <question>"` for the meeting he names, else the next one whose audience
decides it.

**The PM scrum** (audience: product manager):
1. **Sprint**, one line: `day N of M · x on track · y at risk`, then the at-risk item and what it needs, by key.
2. **Releases this week**, one or two lines from the lanes table: what prod 3 runs (its bundle), what rides
   this week's train and when, and what is held and why, with the constraint or decision note linked (e.g.
   "mediahub-frontend held at 2.2.118: HTML input over MQTT is not finished").
3. **What the PM will ask about**, at most two lines: customer tickets and Highest tickets that moved or are
   due, each with its key and its real status in one clause, never the Jira status alone.
4. **What he needs from the PM today**, at most two lines: the D items whose decider is product, each written
   as the question he will ask (e.g. "Should the box-pool shortage code 0x81004009 show the friendly notice
   too? MH-2406").
5. **What he commits to**, one line: the sprint items he carries himself and the date each lands.

**The engineering, QA and UX sync** (audience: developers, QA, design):
1. **The lanes**: what reached QA-AWS3 since the last sync and what of it no QA report names, as slug and
   version.
2. **QA**: this week's fails by ticket, with the real status; Review tickets waiting on QA, by the version
   that carries them; the ones QA has held longest, with their age.
3. **Engineering**: changes on a lane with no ticket, nightly-fix batches with no ticket, and Fixed In gaps,
   each as a count and the worst one by name.
4. **UX**: tickets in Review with design or product, and open design questions on in-progress tickets.
5. **What he needs from each group today**, one line per group with an ask, written as the question he will ask.
6. **What he commits to**, one line.

**Sending the list.** The note is shown to the team on screen, so it carries no send line and no ela command:
sending is the verb's. With a `channel` set, the list is a tier-3 action under rule `meeting` (`apply N`, his word
is the confirm) that posts `ela meeting --key K --slack` in that day's thread; with none, he copies it from that
verb. The note reads Where things stand first, then To raise, then Ruled.
**After a meeting** ela closes the note itself: the first vault sync after the meeting's end (meetings.yaml `time`
plus `minutes`, default 60; a meeting without a time ends at 18:00) reads each item's ticket in the fact store, and
the thread an item links, for what changed since the meeting began, and writes the outcome under `## Ruled` /
`### <date>` ("split into MH-3997 and MH-3998", "assigned to …", "no change"). An item with no change rolls to the
next meeting once and then leaves for `reference/dropped.md`. His ticks and `ela:` lines still rule an item when
he writes them (`ela meeting --key K --rule --json` applies them, and the close applies them first); nothing
requires them. A ruling on a key shows on its project page under *At meetings*.
Each of its `follow_ups` (a ruling that names a key) becomes a drafted action that day, rewritten in the ticket's
genre (a Jira comment, a priority change), tier 3 unless a closed rule admits it. Ruled keeps 30 days; the vault
sync moves older dates to `archive/meetings-<key>-<yyyy-mm>.md` and lints an item over 140 characters.
**On Friday** the day's meeting sections also open the Friday page (`<date>-week.md`), above `## The sprint`.
*Why: meetings are where rulings are given and asks are answered. A page that carries the questions in his
speaking order turns them into recorded rulings the same day, and a meeting he adds or moves is one line of
data, not a change to the brief.*

