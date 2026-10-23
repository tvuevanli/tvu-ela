# 0010 — The vault is laid out by what the owner does with a note

Status: accepted, 2026-10-23. Supersedes the layout, naming and property rules of ADR 0008; the rest of 0008
(a generated, one-way vault; the reading gate; deletion as done) stands.

## Context

The first layout had ten numbered top folders for about sixty notes, split by source type (reviews apart from
verifications, decisions apart from plans) and again by year or month, so most folders held one to five files
two clicks deep. Home embedded the whole morning page and listed the week's notes as static text that went
stale, with dead links, as soon as the owner deleted one. The owner found it untidy and asked whether folders
need numbers at all, whether tags would help, and which Obsidian features would cut friction. An adversarial
review and a survey of current Obsidian practice informed the choices below.

## Decision

- **Folders by what he does with a note**, without numbers: `days/<year>/` (look back), `to-read/` (read, then
  delete: reviews and verifications, flat, date-first names), `records/<year>/` (decisions, plans, sprints),
  `library/` (topics), `ela/` (how ela works and runs, the table view, the attachments). `home` and `board` sit at
  the root. Numbers only fixed the explorer's order, and Home and the bookmarks are the way in; the reserved
  ranges promised structure a generated vault never needs.
- **No tags.** A tag guessed from keywords would be wrong on most notes (every note mentions MediaHub, Jira and
  ela) and one wrong tag discredits the rest. When a source names its topic (`area:` in its front matter), the
  note's meta line links to that library page, whose backlinks are the cross-cut.
- **An alias per note** equal to its title, so the quick switcher finds a note by title rather than by slug.
- **A meta line** under the title of a review or record: what it is, when, its status, its topic.
- **Home is short and live:** what waits for his word, today's "Needs you" section (the whole page when it has
  none), and a Bases table of what there is to read, which updates the moment he deletes a note.
- **Verification notes** lead with the result and the ticket's summary, put the result first in the checks table,
  and fold the passing screenshots.
- **Bookmarks** (Home, Board, Library, All notes, How ela runs, About this vault) are applied by `ela vault setup`;
  the attachments folder is hidden in the explorer; the graph is off.
- **No inbox page.** Feedback stays in Slack (`feedback …`) and sessions: the laptop only receives the vault, and
  a page both sides write would break the one-way rule ADR 0009 kept.

## Consequences

- The deletion log records each note's source as well as its path, and the manifest records the layout, so a
  later change of layout keeps deletions and guards the total number of notes instead of each folder.
- A test fails if a folder of the first layout is named in the code again.
