#!/usr/bin/env python3
"""The owner's reading vault: a one-way, generated Obsidian vault. Stdlib only.

L1: deterministic, no LLM. Every note is written by this script from a first-hand source and rewritten on the
next sync; nothing in the vault is maintained by hand (a hand-maintained vault was abandoned on 2026-10-10). The
sources are the reports root (day pages, reviews, verification records) and elak's committed decisions, plans
and sprints. elak's knowledge, status table and working preferences are written for ela and stay out. Design and
reasons: ela docs/adr/0008-the-owner-reads-ela-in-a-generated-obsidian-vault.md.

Usage:
    vault.py [--env-file F] sync [--dry-run] [--force] [--json]
    vault.py restore <path>          bring back a note the owner deleted
    vault.py guidance [--all] [--json]   his `ela:` lines anywhere in the vault, each handled once
    vault.py finish <path> [--to drop|archive]   on his word: close a note into archive/ or its subject home, kept
    vault.py tidy [--apply] [--json]   the archived notes to their subject homes; a dry run unless --apply
    vault.py lint [--fix [--apply]] [--json]   every note against its type's spec; --fix normalises front matter
    vault.py setup                   apply the Obsidian settings kept in obsidian/ (after a reset or on a new machine)

Layout, by what the owner does with a note (ela ADR 0010). Names are lowercase with hyphens and no spaces, taken
from the source's file name, never from its heading, so editing a title renames nothing; a dated name starts with
its date, so a folder sorts by time. Folders carry no numbers: Home and the bookmarks are the way in.
    home.md, board.md                           the entry point, five lines and links; the board's debt, one living page
    constraints.md                              the standing constraints, each pin read on its lane
    lanes.md                                    the lanes, what each carries that the next does not, two weeks of moves
    recent.md                                   the week's tickets placed by line and by lane (ela recent --write), a dashboard
    one-thing.md                                his One Thing rows not yet on the team's sheet, one copy block (the store
                                                <reports>/onething/, skills/onething); each day's row sits on its changes page
    lanes/test-list-<lane>.md                   what QA should verify on the lane, ranked (ela testlist --page)
    lanes/train-<line>.md                       the line's train: each fix with a cell per lane (ela train --page), a preview
    lanes/dev-list-<line>.md                    the line's tickets in development and their gaps (ela devlist --page)
    ela/review/<date>-reader.md                 the evening reader's verdict on each item of that morning's page, 30 days
    days/<year>/<date>-brief.md                 the morning page, kept, with -changes (what changed); what the day taught
                                                is the reader page's ## Learned (ela/review/), five lines at most
    to-read/<date>-<slug>.md                    a decision or plan from elak while it waits for his ruling
    to-read/<date>-verify-<key>.md              a verification; leaves once its record is on the Jira ticket, or a pass
                                                after 14 days
    readings/<date>-<slug>.md                   deep reads, release and docker-service reviews, promote checks, ticket
                                                pages: no status and no moves; kept until he finishes with them
    in-progress/<name>.md                       a note he agreed to, while ela builds it and until he accepts it
    parked/<name>.md                            a note that waits on others, with who and what brings it back
    archive/                                    what is done with, by date; where he drags a note to keep it
    cases/<date>-<slug>.md                      one note per customer support case (type case: open, answered, closed)
    mh/releases/<line>/                         closed promotions, deploys, docker checks, release reviews, verifications,
                                                one folder per release line, its record the way in; unplaced at the root
    ela/history/                                ela's own closed plans and reviews
    projects/<key>/<key>.md                     a project's page: the desk's head above the sync's first heading, the tail
                                                below (Waiting for your word, Notes, Keys and threads, Afterwards, Deadline);
                                                the folder keeps its readings and reports; `ela project list|show|new|keys`
    ela/                                        about this vault, the ela page (overview.md: generated, three sections
                                                the desk's), how ela runs, the table view, the Jira vocabulary, and
    ela/attachments/verify/<year-month>/<record>/   each verification record copied whole, hidden in the explorer

The reading gate. The vault is how ela reports to the owner, so a note over its reading budget, mostly code, or
carrying machine paths is still written, under a warning that names the problem, and Home lists it for 30 days
as a rewrite ela owes. Nothing readable is withheld; nothing unreadable passes unmarked.

Safety. A missing or unreadable source, or the notes as a whole shrinking by more than half since the last sync
(counted from ten notes up), stops the sync before anything is written (--force overrides after a deliberate removal).
The count is the vault's total, not each folder's as ADR 0008 first described: to-read empties by design as he reads.
In archive/ and the subject homes ela never rewrites a note's text; it keeps its front matter's status current. Removal is limited to files
this script recorded in its manifest, and never reaches library/ or to-learn/, retired in layout 4: the pages left there
are the owner's to move into elak. Writes are atomic and a lock serialises concurrent syncs.

Exit codes: 0 ok · 2 usage or site · 3 a source could not be read or shrank (nothing written).
"""
import argparse, datetime, fcntl, glob, json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
JIRA = os.path.join(HERE, "..", "jira", "jira.py")
PROMOTE = os.path.join(HERE, "..", "promote", "promote.py")
SITE = os.path.expanduser("~/.claude/ela/site.json")
MANIFEST = ".ela-sync.json"
DAYS_KEPT, HELD_LISTED_DAYS, NEW_DAYS, MASS_DELETE = 14, 30, 7, 8
READER_DAYS = 30                                    # a reader page is evidence for the review of ela itself, then expires
CONSTRAINTS_FRESH = 1800    # seconds a read of the pins stands; each read asks the lane hosts, and the sync runs every minute
LAYOUT = 4                  # the manifest records it; a sync across a change of layout guards the total, not each folder
DAYS, TO_READ, READINGS, ELA, ARCHIVE = "days", "to-read", "readings", "ela", "archive"
# folders of earlier layouts: the sync reads nothing there and removes nothing there; what is left is the owner's
RETIRED = ("library", "to-learn")
IN_PROGRESS = "in-progress"   # a note he agreed to, while ela builds it and until he accepts the result
PARKED = "parked"             # a live note nobody in ela works on: it waits on others (a draft he sent out, an answer pending)
# status is ela's field and the folder says the lifecycle, so each lifecycle folder allows only its own values;
# the owner sets `next`, never status. A note elsewhere (a sprint) keeps the status its kind defines; a reading has none.
STATUS_BY_FOLDER = {
    TO_READ: ("proposed", "blocked"),                       # waits on his word; only he can unblock
    IN_PROGRESS: ("building", "built", "waiting", "blocked"),   # waiting: an unattended loop that cannot finish
    PARKED: ("parked",),
    ARCHIVE: ("closed",),                                   # the outcome is in `next`, not repeated here
    "cases": ("open", "answered", "closed"),               # a support case: reported, the customer answered, done
    "mh/releases": ("closed",),
    "ela/history": ("closed",),
}
STATUSES = tuple(dict.fromkeys(v for vs in STATUS_BY_FOLDER.values() for v in vs))
CLOSED_NEXT = {"accepted": "accept", "rejected": "reject", "not now": "not-now", "not-now": "not-now", "parked": "not-now",
               "confirmed": "confirm", "planned": "make-plan", "nudged": "nudge", "drafted": "draft-comment"}
# an archived note's old outcome status, as the move that made it; the runner names the move itself with --next
# a closed note goes to its subject home when it has one, else to archive/, which keeps only what is done with (vault
# in-progress/2026-11-09-kept-notes-by-subject-cases-and-archive.md): one note per customer support case in cases/,
# promotions, deploys, docker checks, release reviews and verifications in mh/releases/, ela's own closed plans and
# reviews in ela/history/
CASES, RELEASES, HISTORY = "cases", "mh/releases", "ela/history"
SUBJECT_HOMES = (CASES, RELEASES, HISTORY)
CLOSED_FOLDERS = (ARCHIVE, RELEASES, HISTORY)   # a note there is closed, its outcome in next; a case keeps its own status
OWNER_FOLDERS = (ARCHIVE,) + SUBJECT_HOMES   # kept notes: ela never rewrites their text, only status and appended Afterwards
# a review of a release, by its file name: a release word, a line written mh<major>-<minor> (mh2-1), or a lane hop
# <lane>-to-<lane> (daily-wed-to-prod-3, qa-cn3-to-daily-wed)
LANE = r"(?:qa|daily|stage|test\d*|prod|cn)"
RELEASE_NAME = re.compile(r"(?:^|-)(?:promote|deploy|docker|release|hotfix)(?:-|$)|(?:^|-)mh\d+-\d+(?:-|$)"
                          rf"|(?:^|-){LANE}(?:-[a-z0-9]+)?-to-{LANE}(?:-|\d|$)")
LINE_NAME = re.compile(r"(?:^|-)(?:mh|promote|release)-?(\d{1,2})-(\d{1,2})(?:-|$)")   # mh2-1, promote-2-1 → 2.1
RELEASE_TITLE = re.compile(r"\b(promote|promotion|deploy|docker|release|hotfix)\b", re.I)   # … or by its title
# mh/releases/ holds one folder per release line (mh/releases/2.1/, its record the way in); a note is filed by the line
# its title names first ("MH 2.1", "Release 2.1"; a version such as 2.1.15 names no line), else by its first key's
# release label on Jira (release:mh-2.1, the label the train rides on), else it stays at the mh/releases/ root
LINE_TITLE = re.compile(r"\b(?:MH|MediaHub|release|line|train)\s*(\d+\.\d+)(?![\d.])", re.I)
LINE_LABEL = re.compile(r"^release:mh-(\d+\.\d+)$")
MH = "mh"   # the program's folder: a product reading (a review of the product, not a release event) may sit there
ELA_TARGET = re.compile(r"(?<![\w-])(ela|ela-runner|elak|vault)(?![\w-])", re.I)   # a plan or review whose target is ela
ATTACH = "ela/attachments"
DELETABLE = (DAYS, TO_READ, READINGS)
KEEP_FOREVER = ("brief", "week", "changes")   # the morning pages are the record of what ela told the owner; the rest expires
PROPS = ("title", "aliases", "type", "date", "kind", "project", "deadline", "next-step", "customer", "hubspot", "graph", "box",
         "status", "result", "target", "progress", "source",
         "moves", "next", "ela", "posted", "channels", "keys", "watch", "watched", "last", "language")
# the whole vocabulary; no tags (ADR 0010)
MARKS = {"done": ARCHIVE, "drop": ARCHIVE}   # both close the note and keep it; next says which (no data is lost)
BUDGET = {"ticket": 700, "topic": 800, "guide": 1200, "board": 1000, "day": 1200, "review": 2500, "decision": 800, "plan": 800, "sprint": 800, "report": 1200,
          "recent": 1200, "train": 1200, "one-thing": 1200, "project": 1200, "services": 2500}
# the closed set of note types, by family (the readme's Types): for his word, readings, living pages, day pages.
# A type outside it, or a family outside its folders, is a lint line on the sync, never a failure.
TYPE_FAMILY = {"decision": "decision", "plan": "plan", "sprint": "plan",
               "ticket": "reading", "review": "reading", "verify": "reading", "verify-plan": "reading",
               "home": "page", "board": "page", "lanes": "page", "recent": "page", "one-thing": "page", "test-list": "page", "dev-list": "page", "train": "page", "program": "page",
               "guide": "page", "vocabulary": "page", "system": "page", "constraints": "page", "readme": "page", "meeting": "page",
               "report": "page", "project": "page", "services": "page",
               "day": "day", "reader": "day", "case": "case", "draft": "draft"}
FAMILY_FOLDERS = {"decision": ("to-read", "in-progress", "parked", "archive", "ela/history"),
                  "plan": ("to-read", "in-progress", "parked", "archive", "sprints", "ela/history", "mh/releases"),
                  "reading": ("readings", "to-read", "archive", "projects", "mh/releases", "ela/history"),
                  "case": ("cases", "projects"),
                  "draft": ("to-read", "parked", "archive", "projects")}   # a message he sends himself: waits on his send, then on replies   # a reading waits in to-read while it asks his word; a project keeps its own
# a project: bounded work with a deadline and parties outside the program (a customer PoC, a trial), one folder
# projects/<key>/ holding its page projects/<key>/<key>.md (type project, the living family) and what it keeps; any
# note elsewhere names it with `project: <key>` (elak decisions/2026-11-04-projects-are-bounded-work-with-one-page-each.md)
PROJECTS = "projects"
PROJECT_PAGE = re.compile(r"^projects/([^/]+)/\1\.md$")
# the sync's tail, these headings in this order; the head is everything above the first of them, the boundary
# ela-runner's morning Projects section reads too, so a desk heading of these names would end the head early
TAIL_HEADS = ("Waiting for your word", "Notes", "Keys and threads", "Afterwards", "Deadline")
PROJECT_HEAD_END = "## " + TAIL_HEADS[0]
TAIL_HEAD_RX = re.compile(r"^##[ \t]+(?:" + "|".join(re.escape(h) for h in TAIL_HEADS) + r")[ \t]*$", re.M)
PROJECT_WATCH_DAYS = 14                   # the page's watch defaults to its deadline plus this
PROJECT_SOON_DAYS = 14                    # Home names a project's step only with the deadline nearer than this and the step overdue
# to-read means "waits on his word", whatever the type: a reading's asks sit under this heading, one box each
ASKS_HEAD = "Waiting for your word"
# every budget counts the words outside folded callouts (`> [!note]- …` and its quoted lines): a fold is read on
# demand, so the page's weight is what stands open (vault to-read/2026-11-02-ela-and-vault-workflow-review.md, fix 4)
# a report is a standing review or design for his decision that does not move: any folder, no lifecycle, ruled in
# place with an `ela:` line, so its status says only where his ruling stands
REPORT_STATUSES = ("proposed", "decided", "superseded")
FOLD_RX = re.compile(r"^>\s*\[![\w-]+\]-", re.M)
QUOTE = r"(?:>[ \t]*)?"                           # a box or line inside a callout keeps its meaning behind the `> `
LEARNED_MAX = 5                                  # the reader page's Learned section: more goes to a decision note
TOLERANCE = 1.1                                  # a page 10% over its budget is not worth a rewrite
KEY_RX = re.compile(r"(?<![\w/#=.-])([A-Z][A-Z0-9]{1,9}-\d{1,6})(?![\w-])")
# media and standards names that look like keys; a second guard behind the project allow-list
NOT_KEYS = re.compile(r"^(MPEG|AC|EAC|AES|HDR|SMPTE|ST|ITU|BT|SCTE|IEC|ISO|EBU|ATSC|DVB|IEEE|UTF|SHA|MD|RFC|CVE|HTTP|"
                      r"TLS|SSL|H|X|AV|AAC|MP|HEVC|AVC|UR|J2N|QA|AWS|CN|ENV|S|W)-")
MACHINE = re.compile(r"(/home/\w|/mnt/\w|\\\\wsl|\{\s*\"[a-z_]+\"\s*:|Traceback \(most recent)")
REDACT = [
    (re.compile(r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}(?::\d+)?\b"), "<address>"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "<token>"),
    (re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]+"), "<token>"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<token>"),
    (re.compile(r"(?i)\b(bearer\s+|[a-z_]*(?:token|secret|password|passwd|api_?key)\s*[:=]\s*)[^\s\"',;]{8,}"), r"\1<redacted>"),
]


class SourceError(Exception):
    pass


README = """---
type: "readme"
---

# About this vault

ela writes this vault for Evan to read and to act from. Every generated note comes from a first-hand source and is
rewritten on each sync: after the morning and evening runs, within a minute of a tick or an answer, and with the
board every half hour on working days. An edit to a generated note is overwritten, except your `ela:` lines and
ticked boxes, which are kept. To change something, write an `ela:` line in the note or ask in a session. The exceptions are the pages ela writes in place, whose source is the vault itself: how ela works,
plans for your decision.

Start at [[home]]. Five lines: what ela did since you last looked, what leaves at 10:00 (or its own send time) unless you tick "don't",
what only you can do (at most three `apply` boxes; the morning page folds the rest under "N more", where a tick
still counts), the MediaHub program's next step, and one line from ela. Below
the line, links: the morning page, lanes, board, recent, changes, the program, the ela page and all notes. A box ticked on
Home is the same as on the morning page. Below the line, `projects` names each project with its days left, and the
fourth line names a project's step instead of the program's only when its deadline is under 14 days away and the
step is overdue. While you hold tier 2 (`ela-runner hold`), nothing leaves on its own: the
block reads "held until DATE (dry run)", without boxes, and each action says what it would have posted. The QA day
post never leaves on a timer: under "Send when you tick:" it waits as `send N` until you tick it, after reviewing the
list and writing your `ela:` priority lines; the 09:30 or 10:00 pass then sends it, and the Done line lists it.

## Layout

| folder | holds | what you do |
|---|---|---|
| `home`, `board` | five lines for today, and the board's debt | look at Home each morning |
| `constraints` | the standing constraints you confirmed: what each holds, whether its lane still keeps it, when it lifts | look when Home says one is over |
| `days/<year>/` | the morning pages and what changed the day before, kept; the evening learning draft, 14 days | look back |
| `to-read/` | whatever waits on your word, any type: plans and decisions to rule, verification results, and readings whose asks sit under *Waiting for your word*; newest first | rule, or tick or answer each ask |
| `readings/` | deep reads, reviews of a release or the docker services, promote checks, ticket pages, with no ask left open; no status, no moves | read when an item links one; leave it, or *drop* it into the archive, when done |
| `in-progress/` | what you agreed to, while ela builds it, until you accept it | accept or say what is missing |
| `parked/` | what waits on others, with who it waits on and what brings it back | resume or drop |
| `lanes` | the lanes, what each carries that the next does not, two weeks of moves | look before a promotion |
| `recent` | the week's MediaHub tickets placed: by release line with the line's train, where each fix stands, what QA said and what moved; by lane, what arrived, what is under test, what was reported from it; tickets with no line and the label ela would infer | look when a ticket moved and you want its place; tick *refresh recent* for the moment |
| `lanes/` | the test list per lane, the dev list per release line, and the line's train (each fix, a cell per lane) | look before testing or a promotion |
| `one-thing` | your One Thing rows not yet on the team's monthly sheet, one copy block, a `pasted` box per row; each day's row is drafted at 19:00 and sits on the next morning's changes page under *Your day* | paste weekly from here; tick `pasted`; reword a row with an `ela:` line under *Your day* on its changes page |
| `mh/` | the MediaHub program and its evidence | look when Home names the program's next step |
| `projects/` | one folder per project: bounded work with a deadline and parties outside the program (a customer PoC, a trial, a demo), holding its page `projects/<key>/<key>.md` and the readings and reports it keeps; a note elsewhere names its project with `project: <key>` and the page lists it wherever it is | look when Home lists a project's days left; keep the head's facts current, `ela: keep this` once they are settled |
| `sprints/` | the sprints, each a plan | look at a sprint's start and end |
| `meetings/` | one note per meeting: what you raise there, its send box, and what it ruled (30 days; older months in `archive/`) | look before the meeting; tick send, or answer an item with an `ela:` line after it |
| `ela/` | the ela page (its measures, parts, schedule and week written by the sync; Waiting for your word, What changed for MediaHub this week and Known limits written by the desk), how ela runs, this page, the table view; attachments, hidden | rarely |
| `ela/service-map` | the service map from the published map: every slug ela uses, what GM registers it as, its id, repo and Jenkins job, the Fixed In grammar; the docker table folded; its Review section yours, kept as written | review a row; write `ela:` under one that is wrong and ela corrects the map on your word |
| `mediahub-bot/` | MediaHub's product bot, not ela: its design, answer contract, knowledge pack, the files it will commit (`files/`), its eval set (`eval/`) and the evidence (`evidence/`); the source until its repositories exist, then pointers | rule the design; confirm eval cases |
| `ela/review/` | the evening reader pages | read in the evening |
| `cases/` | one note per customer support case, `cases/<date>-<slug>.md` (a folder `cases/<slug>/` only when a case outgrows one note): customer, HubSpot ticket, Slack thread, graph and box, the Jira keys it opened, status *open*, *answered* or *closed*; watched like the archive | look when support asks again; all notes, *Cases* |
| `mh/releases/` | one folder per release line (`mh/releases/2.1/`, `mh/releases/2.0/`, a later line as it comes): its record, the way in, linking the line's notes in order (QA → daily → prod), and its closed promotions, deploys, docker checks, release reviews, test plans and verifications; a note whose line cannot be read waits at the root | look back on a release: open its line's record |
| `ela/history/` | ela's own closed plans and reviews; what they ruled is in elak's decisions | rarely |
| `archive/` | what is done with and has no subject home; ela adds to it and keeps its status current, never its text, except the Afterwards it appends | look back (all notes, *Archive*, with its *subject* column, lists every closed note); ask ela to tidy it |

Folders are named for what you do with a note while it is live, and carry no numbers: Home and the bookmarks are the
way in, and the file explorer is rarely needed. A closed note is the exception: it goes to its **subject home**
(`cases/`, `mh/releases/`, `ela/history/`) when it has one, by its type: a `case` to cases; a verification, a
verification plan, or a review of a release (a promotion, deploy, docker check or release review) to its line's folder
in mh/releases, the line read from the note's title (*MH 2.1*), else from its first key's release label on Jira, else
the mh/releases root, listed for you, never guessed;
a plan, decision or review whose target names ela, its runner, elak or the vault to ela/history; anything else to
`archive/`. A note you put somewhere by hand stays where you put it.

## Names and properties

- Names are lowercase, words joined by hyphens, taken from the source file's name; a dated note starts with its
  date. The readable title is the note's first heading, and an alias, so the quick switcher (Ctrl+O) finds a
  note by its title.
- Properties are `title`, `aliases` and `type`, plus `date`, `kind` on a day page, `status`, and `result` on a
  verification (pass or fail). A page ela writes in place also carries `source` ("vault": ela writes the note in
  place), `target` (what the note changes), `progress` (the desk's last state line) and `ela` (the generated or
  hand line the desk leaves for you). A note that sent something out or follows tickets carries `posted` (the
  permalinks of what went out from it), `keys` (the Jira keys to watch), `watch` (until when it is watched; empty
  stops it), `watched` (when it was last read) and `last` (the date of its newest Afterwards line). A note that
  belongs to a project carries `project` (its key; the sync infers it when the note's `keys` are among the
  project's); a project page carries `deadline`, `next-step` (the step Home may name), `channels` (the threads it
  watches) and the watch fields above. A note written in Chinese for a Chinese-speaking audience carries `language`
  ("zh"); every other note is English. status is ela's, never
  yours to set, and follows the folder: to-read *proposed* (waits on your word) or *blocked* (only you can unblock);
  in-progress *building*, *built* (waits on your accept), *waiting* (a loop that cannot finish; Progress says why) or
  *blocked*; parked *parked*; archive, mh/releases and ela/history *closed*, with the outcome in `next`; cases *open*, *answered* or *closed*. Home's *Waiting for your word* holds only
  what blocks something until you answer: a plan or decision proposed, a build to accept, something blocked, a failed
  verification, a verification plan, the evening's learnings, and any note in to-read (a review there is *proposed*
  like a plan). In readings a note carries no status.
  They feed the tables and show at the top of each note: a status to read, and `next`, the move you choose. A
  hidden `moves` property names the note's set of moves, so the chooser lists only those.
- No tags: a keyword-guessed tag would be wrong often enough to cost trust.
- Types are a closed set, in four families. For your word: `decision`, `plan` (a sprint is a plan), in to-read,
  in-progress, parked or archive. Readings: `ticket`, `review`, `verify` and `verify-plan` (checks), in readings,
  or in to-read while one asks your word (a verification waiting for its record on Jira, a review with open
  asks). Pages that live: home, board, lanes, recent, one-thing, test-list,
  dev-list, train, program, the ela page (`guide`), vocabulary, system, constraints, readme, meeting, `services` (the
  service map, `ela/service-map`, from the published map, its Review section yours), `report`: a
  standing review or design for your decision that does not move, in any folder, its evidence in folds, ruled in
  place with an `ela:` line (status proposed, decided or superseded), and `project`: a project's page,
  `projects/<key>/<key>.md`, its head yours above *Waiting for your word* and its tail the sync's from there (Notes,
  Keys and threads, Afterwards, Deadline). Day pages: `day`
  (brief, changes, week) and `reader`. A message you send under your own name: `draft` (a Slack post, a Jira comment, a mail), in to-read until you send it, then parked on the replies. A support case: `case`, in `cases/` (or a project's folder), its head in
  properties (`customer`, `hubspot`, `graph`, `box`, the thread in `channels`, `keys`) and its status *open*,
  *answered* or *closed*. A closed plan or decision may also sit in `ela/history/`, a release line's test plan in
  `mh/releases/`, a closed reading in `mh/releases/` or `ela/history/`, and a review of the product (not of a release)
  in `mh/`. A report, and a line's test plan, keep their own status in a subject home: they live there, not closed. A note outside the set, or a family outside its folders, is a lint line on
  the sync, never a failure.
- `to-read/` means "waits on your word", whatever the type. A reading that asks something puts its asks under one
  heading, **Waiting for your word**, one box each with ela's proposed answer. When every box there is ticked or
  answered with an `ela:` line under it, the next sync moves the reading to `readings/`; a plan or decision goes on
  along its own life. A reading elsewhere with an open box under that heading is a lint line on the sync.
- A ticket key is a link to Jira, one click in reading mode.

## Reading budgets

A note is written for a person: a title heading, within its budget (day page 1,200 words, review 2,500,
sprint 800, a decision or a plan 800, a report 1,200, a case 1,200, a draft 600, the recent page 1,200, a project page 1,200, the service map 2,500; the reader page's Learned five lines), mostly prose, no machine paths. The budget counts what stands open: a folded callout (`> [!note]- …`
and the quoted lines under it) is read on demand and is not counted, for every type, so a page keeps its
detail in folds and its weight above them. A note that misses is still here, under a warning, and Home lists
it for 30 days as a rewrite ela owes; a past day page is the morning's record and is not listed.

## Note standards

<!-- note standards -->

## Finishing with a note

| you want | do | ela does |
|---|---|---|
| what it says kept as knowledge | write `ela: keep this` in it | ela proposes the conclusion and where it goes in its own knowledge (elak), as a decision note in `to-read/` |
| to keep it, nothing more | drag it into `archive/`, or its subject home | nothing: it is never written again, and the copy, with its screenshots, is yours |
| it out of the way | choose *drop* | it is closed into `archive/` (or its subject home), kept, its `next` *drop*: the *Archive* view lists it as dropped. ela never deletes a note; one you delete by hand is your act, logged, and the nightly backup holds it |
| nothing yet | leave it | it stays, or ela moves it on (below) |

In `to-read/` the same moves are choices of the note's `next` field: `done` or `drop`, and within a minute the note is
closed into `archive/`, or the note's subject home, with status *closed* and the move in `next`; no session. Both keep
the note: *drop* says you did not want it, not that it is gone, so no link is left broken and nothing is lost. A
reading has no `next`: leave it when you are done, answer it with `ela:` lines, or ask ela to close it
(`ela vault finish PATH --to drop`).

Every note to read carries one field for its next move, **next**, at its top. The button beside it lists only
that note's choices, by kind: a plan *agree*, *park*, *not-now*, *reject*; a decision *confirm*, *park*; a verification
*draft-comment*; all of them *done*, *drop*. A verification plan (a run waiting for your word on its goals) offers only
*run*, *not-now* and *drop*. The note's **Next moves** section says what each does. Choose one, and it is done
within a minute; ela empties the field once it has acted, and a value that is not a move for the note runs nothing
and is pointed out under the title. An agreed note moves to `in-progress/`, ela writes each step under its Progress
heading, and when it is built the note offers *accept* or *not-done*. A plan lists each ruling it needs with ela's
proposed answer and no boxes: *agree* accepts them as proposed, and to differ on one you write an `ela:` line under
it. Beside that life (to-read → in-progress → archive) sits `parked/`: a plan or decision you *park* waits
on others, with who (`waits-on`) and what brings it back (`wake`); ela watches the wake each morning, and the note
offers *resume* or *drop*. You can also answer a note with `ela:` lines,
or continue it in any Claude session by naming its path; a session that claims a note keeps it, and records its
conclusions there.

To tell ela what you want of a note, or to answer what it waits for, write a line starting `ela:` into the note,
below its properties (the end is easiest: Ctrl+E, Ctrl+End, write, Ctrl+E), in your own words. Any note: a
rewrite keeps your lines. Two minutes after you stop typing, a session takes the lines up: at once a fold "on it ·
queued HH:MM · job …" shows under the last of them, and the answer replaces it there. A place can be named ("write this to the KB", "into elak"); without one, ela
chooses between its own knowledge in elak and the team's knowledge base (drafted, published on your word).

Ask ela now and then to tidy the archive: `ela vault tidy` lists the archived notes that have a subject home, and the
notes at the mh/releases root whose line can now be read, and `--apply` moves them; a move that would break a link
(a link naming `archive/` or `mh/releases/` in its path, or a name another note shares) is held back and named.

The archive keeps listening. A note in `archive/`, a subject home (`cases/`, `mh/releases/`, `ela/history/`) or
`in-progress/` that carries `posted` or `keys` is read at
13:00, 17:30 and 19:00 for a window after it leaves to-read: a promote or release review, a decision or plan, a
meeting note 14 days from its date; a verification, ticket page or case 30; anything else 10 working days; or until its
`watch` date. What happened since (a reply in a thread it posted, a key moving, a comment) becomes one dated line per
source per day under its own **Afterwards** heading, in ela's words with the link, never a colleague's verbatim, at
most 40 lines a note. That section is the one exception to "ela never rewrites an archived note": it is only
appended, and nothing else there changes. Clear `watch` to stop it; a note with neither `posted` nor `keys` is left
exactly as you left it. The *Archive* view of all notes lists them, newest first. A project page is watched the same
way through its `keys`, `posted` and `channels`, until its deadline plus 14 days unless its `watch` says otherwise.

Do it on the desktop; the laptop only receives. A living page (Home, the board, the lanes, how ela runs) is
written again whatever happens to it. Finishing is never a verdict: deleting a decision does not revoke it; to
change one, tell ela. `ela vault restore <path>` brings back a generated note; a page ela writes in place comes
back from the nightly backup.

## What ela moves on by itself

What ela knows was acted on, it archives: a verification once its record is on the Jira ticket, a decision or plan
once you have ruled on it (what it settled is written into elak or a living page in `ela/`). What merely expired, it
removes: a passed verification nobody posted, after 14 days. A reading stays until you delete it: it is linked from
the item or ticket it serves, not a pile to work down. What waits for your word (a failed verification, a plan to
rule on) stays until you give it, and the morning page reminds you; the evening's draft of what the day taught
expires after 14 days.

## Standing constraints

A ruling that holds a lane back (a service kept at or below a version until a condition is met) is a standing
constraint once you confirm the note that proposes it; `ela promote` then refuses a promotion that would break it.
The `constraints` page lists each one: what it says, every pin with the version its lane runs now and whether that
is held or over, when it ends or lifts, and the note it came from. One that ended stays for seven days, marked
expired, so a lapse is seen. Home says how many there are and how many are over.

## What is not here

ela's own knowledge, status table and working rules, which are written for ela; Helm's team reports, which stay
in Slack and Helm. Internal addresses and credentials are redacted from the text; screenshots are copied as they
are.

## How Obsidian is set up

Set by ela; the sync never changes these settings. `ela vault setup` reapplies them after a reset or on another
machine.

- Notes open in reading view, without the file-name title, with their properties at the top, at a readable width; the
  `ela` style sheet tidies tables and callouts and hides the attachments folder.
- Bookmarks: Home, the board, all notes as tables, how ela runs, this page.
- Core plugins on: search, quick switcher, file explorer, backlinks, outgoing links, page preview, outline,
  bookmarks, properties, Bases, Web viewer (on request only). Off: everything made for writing, tags and the
  graph.
- Three community plugins: **Homepage** opens `home` in reading view when Obsidian starts; **HTML Reader** opens a
  verification's full record (a self-contained `.html`) in a tab; **Metadata Menu** makes a note's `next` field a
  list to choose from, by the button beside it in the properties. A web link opens the default browser;
  right-click it and choose *Open in web viewer* to read it inside Obsidian (Jira works there, Slack does not).
"""

# `loop` orders Home's tables: the tickets loop (a ticket page, a verification) before ela's own changes and reviews
FORMULAS = """formulas:
  note: 'file.asLink(title)'
  loop: 'if(type == "ticket" || type == "verify", 1, 2)'
  subject: 'file.folder'
properties:
  formula.note:
    displayName: Note
  formula.subject:
    displayName: Subject
"""

VIEWS = {
    "all-notes": """filters:
  and:
    - 'file.ext == "md"'
    - not:
        - file.inFolder("library")
        - file.inFolder("to-learn")
        - file.inFolder("ela/moves")
    - 'type != "home"'
    - 'type != "readme"'
""" + FORMULAS + """views:
  - type: table
    name: Waiting for your word
    filters:
      and:
        - not:
            - file.inFolder("archive")
            - file.inFolder("cases")
            - file.inFolder("mh/releases")
            - file.inFolder("ela/history")
        - or:
            - 'status == "built"'
            - 'status == "proposed"'
            - 'result == "fail"'
            - 'status == "blocked"'
    order: [date, formula.note, type, project, status, next]
    sort:
      - property: formula.loop
        direction: ASC
      - property: date
        direction: DESC
  - type: table
    name: To read
    filters:
      and:
        - file.inFolder("to-read")
        - 'result != "fail"'
        - 'status != "blocked"'
        - 'status != "proposed"'
    order: [date, formula.note, type, next]
    limit: 5
    sort:
      - property: formula.loop
        direction: ASC
      - property: date
        direction: DESC
  - type: table
    name: Readings
    filters:
      and:
        - file.inFolder("readings")
    order: [date, formula.note, type]
    limit: 5
    sort:
      - property: formula.loop
        direction: ASC
      - property: date
        direction: DESC
  - type: table
    name: In progress
    filters:
      and:
        - file.inFolder("in-progress")
    order: [date, formula.note, project, status, progress, built, next, claimed]
    sort:
      - property: date
        direction: DESC
  - type: table
    name: Projects
    filters:
      and:
        - or:
            - file.hasProperty("project")
            - file.inFolder("projects")
    order: [project, date, formula.note, type, status, next]
    sort:
      - property: project
        direction: ASC
      - property: date
        direction: DESC
  - type: table
    name: Parked
    filters:
      and:
        - file.inFolder("parked")
    order: [date, formula.note, waits-on, parked, next]
    sort:
      - property: parked
        direction: DESC
  - type: table
    name: Cases
    filters:
      and:
        - file.inFolder("cases")
    order: [date, formula.note, customer, hubspot, status, keys, last, watch]
    sort:
      - property: date
        direction: DESC
  - type: table
    name: Archive
    filters:
      or:
        - file.inFolder("archive")
        - file.inFolder("cases")
        - file.inFolder("mh/releases")
        - file.inFolder("ela/history")
    order: [date, formula.note, formula.subject, type, next, posted, last, watch]
    sort:
      - property: date
        direction: DESC
""",
}


# ── small helpers ─────────────────────────────────────────────────────────────────────────────────────

def slug(s, limit=80):
    """A path segment: lowercase, words joined by hyphens, no spaces; CJK kept as written; cut at a word."""
    s = re.sub(r"[^a-z0-9一-鿿]+", "-", re.sub(r"['’]", "", (s or "").lower())).strip("-")
    if len(s) > limit:
        s = s[:limit].rsplit("-", 1)[0]
    return s or "untitled"


def split_front(text):
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            return text[4:end].splitlines(), text[end + 4:].lstrip("\n")
    return [], text


def body_start(text):
    """The offset where a note's body begins, past its front matter: what is written there is the note's, never an
    answer's place (an `ela:` property equal to an asked line once drew the fold into the properties)."""
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            nl = text.find("\n", end + 4)
            return len(text) if nl == -1 else nl + 1
    return 0


def front_breaks(fl):
    """The front-matter lines that do not read as the properties ela writes — `key: value` (a quoted value valid
    JSON), a block-list item under a key, a comment — one line each; Obsidian shows such properties as broken."""
    out, in_list = [], False
    for i, l in enumerate(fl, 2):
        if not l.strip() or l.lstrip().startswith("#"):
            continue
        if in_list and re.match(r"^\s*-\s", l):
            continue
        m = re.match(r"^([\w-]+):(?:\s+(.*))?$", l)
        if not m:
            out.append(f"front matter line {i} is not a property: {l.strip()[:60]!r}")
            in_list = False
            continue
        v = (m.group(2) or "").strip()
        in_list = not v
        if v and v[0] in '"[{':
            try:
                json.loads(v)
            except ValueError:
                if v[:1] == '"' or not re.match(r"^\[[^\]]*\]$|^\{[^}]*\}$", v):
                    out.append(f"front matter line {i}: {m.group(1)} does not parse")
    return out


def h1(body):
    m = re.search(r"^#\s+(.+?)\s*$", body, re.M)
    t = re.sub(r"(\*\*|__)(.+?)\1", r"\2", m.group(1)) if m else None
    return re.sub(r"(?<!\w)[*_](\S.*?\S|\S)[*_](?!\w)", r"\1", t).replace("`", "").strip() if m else None


def sentence(title):
    return title if re.match(r"^(ela|elak)\b", title) else title[:1].upper() + title[1:]


def verdict_props(verdict):
    """A verification's verdict is a result, not a lifecycle: a fail waits on his word, a blocked run on him, a pass
    is read."""
    v = (verdict or "").lower()
    return {"result": v if v in ("pass", "fail") else None,
            "status": "proposed" if v == "fail" else "blocked" if v == "blocked" else None}


def settled_status(folder, status, kind=None):
    """(status, result, next) a note in a lifecycle folder carries, from whatever status it had: the folder's own
    value, a verdict moved to result, an archived outcome moved to next. Outside those folders, as it was."""
    s = (status or "").strip().strip("'\"").lower()
    result = s if kind == "verify" and s in ("pass", "fail") else None
    if folder == READINGS:                                 # a reading is reference, not a step in a life
        return None, None, None
    if folder not in STATUS_BY_FOLDER:
        return status, None, None
    if folder in CLOSED_FOLDERS:
        return "closed", result, CLOSED_NEXT.get(s)
    if folder == CASES:                                    # a case's own life: open, answered, closed
        return s if s in STATUS_BY_FOLDER[CASES] else "open", result, None
    if folder == PARKED:
        return "parked", result, None
    if folder == IN_PROGRESS:
        return s if s in STATUS_BY_FOLDER[IN_PROGRESS] else "building", result, None
    if result:
        return ("proposed" if result == "fail" else None), result, None
    return (s if s in STATUS_BY_FOLDER[TO_READ] else "proposed"), None, None   # any type there waits on his word


def subject_home(path):
    """The subject home a folder or note path lies in (a subfolder counts as its home: mh/releases/2.1 is
    mh/releases), else None."""
    path = path.replace(os.sep, "/").strip("/")
    return next((h for h in SUBJECT_HOMES if path == h or path.startswith(h + "/")), None)


def kept_home(folder):
    """The owner folder a folder belongs to: archive/ or a subject home, a line folder counting as mh/releases; else
    None."""
    return folder if folder == ARCHIVE else subject_home(folder or "")


def folder_of(rel):
    """The lifecycle folder of a note path: the subject home it lies in, at any depth, else its top folder."""
    return subject_home(os.path.dirname(rel)) or top(rel)


def notes_under(vault, folder):
    """The .md notes of a folder as vault paths: directly in it, and in its subfolders when it is a subject home
    (a release line's folder, a case's own folder)."""
    base = os.path.join(vault, folder)
    if not os.path.isdir(base):
        return []
    if not subject_home(folder):
        return [f"{folder}/{f}" for f in sorted(os.listdir(base)) if f.endswith(".md") and os.path.isfile(os.path.join(base, f))]
    out = []
    for top_, dirs, fs in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        out += [os.path.relpath(os.path.join(top_, f), vault).replace(os.sep, "/") for f in sorted(fs) if f.endswith(".md")]
    return out


def facts_line(key):
    """The release line of one Jira key from the fact store (<runtime>/facts/jira/issues/<KEY>.json): its
    release:mh-<line> label, or None when the store has no reading of it or no such label."""
    try:
        runtime = json.load(open(SITE)).get("runtime") or ""
        d = json.load(open(os.path.join(runtime, "facts", "jira", "issues", f"{key}.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None
    d = d[0] if isinstance(d, list) and d else d
    labels = ((d or {}).get("fields") or {}).get("labels") or [] if isinstance(d, dict) else []
    found = {m.group(1) for m in (LINE_LABEL.match(l) for l in labels) if m}
    return found.pop() if len(found) == 1 else None


def release_line(props, line_of_key=None, name=""):
    """The release line a note belongs to: the first line its title names, else the line its file name writes (mh2-1,
    promote-2-1), else its first key's release label (line_of_key, the fact store by default); None when none says,
    and the note stays at the mh/releases/ root."""
    m = LINE_TITLE.search(props.get("title") or "")
    if m:
        return m.group(1)
    m = LINE_NAME.search(re.sub(r"^\d{4}-\d{2}-\d{2}-", "", name or ""))
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    keys = [k for k in KEY_RX.findall(str(props.get("keys") or "")) if not NOT_KEYS.match(k)]   # "MH-1 MH-2" or a list
    return (line_of_key or facts_line)(keys[0]) if keys else None


def home_for(rel, props, line_of_key=None):
    """Where a closing note goes: its subject home by type, else archive/. A case → cases/; a verification, a
    verification plan, or a review of a release (a promotion, deploy, docker check or release review, by its file
    name) → its line's folder mh/releases/<line>/ (release_line), else mh/releases/; a plan, decision or review whose
    target (else its title) names ela, its runner, elak or the vault → ela/history/."""
    kind = (props.get("type") or "").strip()
    name = os.path.basename(rel)[:-3] if rel.endswith(".md") else os.path.basename(rel)
    if kind == "case":
        return CASES
    if kind in ("verify", "verify-plan") or (kind == "review" and (RELEASE_NAME.search(re.sub(r"^\d{4}-\d{2}-\d{2}-", "", name))
                                                                   or RELEASE_TITLE.search(props.get("title") or ""))):
        line = release_line(props, line_of_key, name)
        return f"{RELEASES}/{line}" if line else RELEASES
    if kind in ("plan", "decision", "review") and ELA_TARGET.search(props.get("target") or props.get("title") or ""):
        return HISTORY
    return ARCHIVE


def living_in_home(folder, kind):
    """A page that lives filed in a subject home, which keeps the status its kind defines rather than the home's: a
    report anywhere (proposed, decided, superseded), and in mh/releases a release line's test plan beside its record."""
    return bool(subject_home(folder)) and (kind == "report" or (kind == "plan" and subject_home(folder) == RELEASES))


def settle_statuses(vault, dry_run=False):
    """Bring every note in a lifecycle folder to its folder's statuses, and take status off readings, front matter
    only (archive included: the body stays his). Returns one line per fix."""
    fixes = []
    for folder in tuple(STATUS_BY_FOLDER) + (READINGS,):
        for rel in notes_under(vault, folder):             # a subject home with its subfolders (a release line)
            p = os.path.join(vault, rel)
            try:
                text = open(p, encoding="utf-8").read()
            except OSError:
                continue
            fl, body = split_front(text)
            if not fl:
                continue
            props = props_of(fl)
            if living_in_home(folder, props.get("type")):
                continue                                   # a line's record or test plan keeps its own status
            st, result, nxt = settled_status(folder, props.get("status"), props.get("type"))
            want = {"status": st, "result": result or props.get("result") or None}
            if nxt and not props.get(NEXT):
                want[NEXT] = nxt
            if folder in (IN_PROGRESS, CASES) + CLOSED_FOLDERS:   # the set its status chooser lists
                want[MOVE_SET] = (props.get(MOVE_SET) if props.get(MOVE_SET) == "reopen" else "closed") if folder in CLOSED_FOLDERS \
                    else "case" if folder == CASES else props.get(MOVE_SET) or "built"
            changed = {k: v for k, v in want.items() if (v or None) != (props.get(k) or None)}
            raw = next((l for l in fl if re.match(r"^type:\s*\S", l)), None)
            if raw and not re.match(r"^type:\s*[\"']", raw):   # one spelling of type everywhere: quoted
                changed["type"] = props.get("type")
            if not changed:
                continue
            fixes.append(f"{rel}: " + ", ".join(f"type quoted" if k == "type" and v == props.get(k) else f"{k} {props.get(k) or '—'} → {v or '—'}"
                                                   for k, v in changed.items()))
            if not dry_run:
                atomic_write(p, set_front(text, **changed))
    return fixes


def short_status(v):
    """A source's status as a property: its first clause, cut at a word within 40 characters."""
    v = re.split(r" — |;| \(|, ", v)[0].strip()
    dated = re.match(r"^\D{0,30}?\d{4}-\d{2}-\d{2}", v)            # "executed 2026-10-23 without …" → up to its date
    v = dated.group(0) if dated else v
    return v if len(v) <= 40 else v[:40].rsplit(" ", 1)[0]


def front(existing, props):
    """Properties from the fixed vocabulary only; a source's own status, decided or written date fills a gap."""
    src = {}
    for l in existing:
        m = re.match(r"^(status|decided|written):\s*(.*?)\s*$", l)
        if m:
            v = m.group(2)
            src[m.group(1)] = (v[1:-1] if len(v) > 1 and v[0] == v[-1] and v[0] in "'\"" else v).strip()
    props = dict(props)
    if src.get("status") and not props.get("status"):
        props["status"] = short_status(src["status"])
    if not props.get("date") and (src.get("decided") or src.get("written")):
        props["date"] = (src.get("decided") or src.get("written"))[:10]
    if props.get("title") and props.get("type") not in ("home", "readme"):
        props["aliases"] = [props["title"]]                # the quick switcher matches an alias, not a heading
    lines = [f"{k}: {json.dumps(props[k], ensure_ascii=False)}" for k in PROPS if props.get(k) or props.get(k) is False
             or (k == "next" and props.get(k) == "")]   # an empty next field, ready for his word
    return "---\n" + "\n".join(lines) + "\n---\n\n" if lines else ""


def redact(text):
    for rx, rep in REDACT:
        text = rx.sub(rep, text)
    return text


BLOCK_START = re.compile(r"^\s*(#{1,6}\s|\||>|```|~~~|---\s*$|[-*+]\s|\d+[.)]\s|!\[\[|<|\$\$)")


FENCED_DIV = re.compile(r"^:::\s*(\w+)?\s*(.*?)\n(.*?)\n:::\s*$", re.M | re.S)


def callouts(body):
    """`::: ref` blocks (a Markdown extension Obsidian does not render) become collapsed callouts."""
    def one(m):
        title = (m.group(2) or m.group(1) or "Reference").strip() or "Reference"
        return "> [!quote]- " + title + "\n" + "\n".join("> " + l for l in m.group(3).splitlines())
    return FENCED_DIV.sub(one, body)


def unwrap(body):
    """Join hard-wrapped lines into one line per paragraph or list item. Obsidian renders a single newline as a
    break, so text wrapped at a fixed width for git reads as ragged lines. Headings, tables, quotes, code, rules
    and embeds keep their lines; a blank line or a new block ends a paragraph."""
    out, fence, joinable = [], False, False
    for line in body.split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
            out.append(line); joinable = False; continue
        if fence or not line.strip():
            out.append(line); joinable = False; continue
        if joinable and not BLOCK_START.match(line):
            out[-1] = out[-1].rstrip() + " " + line.strip(); continue
        out.append(line)
        # a paragraph or a list item may continue on the next line; a heading, table, quote or embed may not
        joinable = not re.match(r"^\s*(#{1,6}\s|\||>|---\s*$|!\[\[|<|\$\$)", line)
    # a heading stands apart, and a table starts after a blank line, or Obsidian may not render it
    spaced, fence = [], False
    for i, line in enumerate(out):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        prev = spaced[-1] if spaced else ""
        heading = not fence and re.match(r"^#{1,6}\s", line)
        table = not fence and line.startswith("|") and not prev.startswith("|")
        if (heading or table) and prev.strip():
            spaced.append("")
        spaced.append(line)
        if heading and i + 1 < len(out) and out[i + 1].strip():
            spaced.append("")
    return "\n".join(spaced)


class Note:
    def __init__(self, path, title, body, props, front_lines=(), src_rel=None):
        self.path, self.title, self.body, self.props = path, title, body, dict(props)
        self.front_lines, self.src_rel, self.held = list(front_lines), src_rel, []


# ── sources ───────────────────────────────────────────────────────────────────────────────────────────

def elak_notes(elak):
    """Committed decisions, plans and sprints. A file deleted in the working tree but still tracked is skipped."""
    if not elak or not os.path.isdir(os.path.join(elak, ".git")):
        raise SourceError(f"elak is not a git checkout: {elak}")
    r = subprocess.run(["git", "-C", elak, "ls-files", "-z", "--", "blueprint/decisions", "blueprint/plans", "blueprint/sprints"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SourceError("git ls-files in elak failed: " + (r.stderr or "").strip()[-200:])
    notes, titles = [], {}
    for rel in r.stdout.split("\0"):
        if not rel.endswith(".md") or os.path.basename(rel).lower() == "readme.md":
            continue
        p = os.path.join(elak, rel)
        if not os.path.isfile(p):
            continue
        fl, body = split_front(open(p, encoding="utf-8").read())
        base = os.path.basename(rel)[:-3]
        kind = {"decisions": "decision", "plans": "plan", "sprints": "sprint"}[rel.split("/")[1]]
        titles[rel] = sentence(h1(body) or base.replace("-", " "))
        # a decision or plan is in the vault only while it waits for the owner's ruling (`reader: owner` and
        # `status: proposed`); once decided, what it settled is written into elak or a living page (ela/) and the
        # record stays in elak, for ela (ADR 0010)
        if kind != "sprint" and not (any(re.match(r"^reader:\s*owner\b", l) for l in fl)
                                     and any(re.match(r"^status:\s*['\"]?proposed\b", l) for l in fl)):
            continue
        title = sentence(h1(body) or base.replace("-", " "))
        titles[rel] = title
        sp = re.match(r"^(\d{4})-[sS](\d{2})$", base)
        dm = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+)$", base)
        if sp:
            path, date = f"{DAYS}/{sp.group(1)}/{sp.group(1)}-s{sp.group(2)}.md", None
        elif dm:
            path, date = f"{TO_READ}/{dm.group(1)}-{slug(dm.group(2))}.md", dm.group(1)
        else:
            path, date = f"{TO_READ}/{slug(base)}.md", None
        notes.append(Note(path, title, body, {"type": kind, "date": date}, fl, src_rel=rel))
    # pages at the top of elak's blueprint marked for the owner go to ela/
    top_files = subprocess.run(["git", "-C", elak, "ls-files", "-z", "--", "blueprint/*.md"], capture_output=True, text=True).stdout.split("\0")
    for rel in (r for r in top_files if r.count("/") == 1 and r.endswith(".md")):
        p = os.path.join(elak, rel)
        if not os.path.isfile(p):
            continue
        fl, body = split_front(open(p, encoding="utf-8").read())
        if not any(re.match(r"^reader:\s*owner\b", l) for l in fl):
            continue
        title = sentence(h1(body) or os.path.basename(rel)[:-3].replace("-", " "))
        notes.append(Note(f"{ELA}/{slug(os.path.basename(rel)[:-3])}.md", title, body, {"type": "guide"}, fl, src_rel=rel))
        titles[rel] = title
    return notes, titles


def report_notes(reports, today):
    if not reports or not os.path.isdir(reports):
        raise SourceError(f"the reports root is missing: {reports}")
    notes = []
    rd = os.path.join(reports, "runner")
    lists = list_links(reports)
    for f in sorted(os.listdir(rd)) if os.path.isdir(rd) else []:
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-(brief|week|changes)\.md$", f)   # the day's learning is the reader page's ## Learned
        if not m or (m.group(2) not in KEEP_FOREVER and (today - datetime.date.fromisoformat(m.group(1))).days >= DAYS_KEPT):
            continue
        d = datetime.date.fromisoformat(m.group(1))
        fl, body = split_front(open(os.path.join(rd, f), encoding="utf-8").read())
        if m.group(2) == "brief":
            body = action_states(body, os.path.join(rd, f"{m.group(1)}-actions.json"), lists)
        label = {"brief": "Morning brief", "week": "The week", "changes": "What changed"}[m.group(2)]
        notes.append(Note(f"{DAYS}/{m.group(1)[:4]}/{m.group(1)}-{m.group(2)}.md", f"{label} · {d:%a} {m.group(1)}", body,
                          {"type": "day", "date": m.group(1), "kind": m.group(2)}, fl, src_rel=f"runner/{f}"))
    bp = os.path.join(reports, "board", "board.md")
    if os.path.isfile(bp):                                 # the board's debt, one living page, rewritten each morning
        fl, body = split_front(open(bp, encoding="utf-8").read())
        dm = re.search(r"\*(\d{4}-\d{2}-\d{2})", body)
        notes.append(Note("board.md", "The board's debt", body,
                          {"type": "board", "date": dm.group(1) if dm else None}, fl, src_rel="board/board.md"))
    lp = os.path.join(reports, "lanes", "lanes.md")
    if os.path.isfile(lp):                                 # the lanes, their differences and two weeks of moves, rewritten each pass
        fl, body = split_front(open(lp, encoding="utf-8").read())
        dm = re.search(r"\*(\d{4}-\d{2}-\d{2})", body)
        notes.append(Note("lanes.md", "The lanes", body, {"type": "lanes", "date": dm.group(1) if dm else None}, fl, src_rel="lanes/lanes.md"))
    rn = recent_note(reports)
    if rn:                                                 # the week's tickets placed, a dashboard rewritten from the newest result
        notes.append(rn)
    on = onething_note(reports, today)
    if on:                                                 # his One Thing rows not yet pasted, rendered from the store each sync
        notes.append(on)
    ld = os.path.join(reports, "lanes")
    for f in sorted(os.listdir(ld)) if os.path.isdir(ld) else []:   # what QA verifies per lane, what is in development per line
        m = re.match(r"^(test-list|dev-list|train)-(.+)\.md$", f)
        if m:
            fl, body = split_front(open(os.path.join(ld, f), encoding="utf-8").read())
            dm = re.search(r"\*(\d{4}-\d{2}-\d{2})", body)
            title = {"test-list": "Test list · ", "dev-list": "Dev list · ", "train": "Train · "}[m.group(1)] + m.group(2)
            notes.append(Note(f"lanes/{f}", title, body, {"type": m.group(1), "date": dm.group(1) if dm else None}, fl, src_rel=f"lanes/{f}"))
    rv = os.path.join(reports, "review")
    for f in sorted(os.listdir(rv)) if os.path.isdir(rv) else []:   # the evening reader's verdicts on a morning page
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-reader\.md$", f)
        if not m or (today - datetime.date.fromisoformat(m.group(1))).days >= READER_DAYS:
            continue
        fl, body = split_front(open(os.path.join(rv, f), encoding="utf-8").read())
        body = reader_heading(body, m.group(1))
        notes.append(Note(f"{ELA}/review/{f}", f"The reader · {m.group(1)}", body, {"type": "reader", "date": m.group(1)}, fl,
                          src_rel=f"review/{f}"))
    sp = os.path.join(reports, "system", "how-ela-runs.md")
    if os.path.isfile(sp):                                 # what is scheduled where, read from the machines
        fl, body = split_front(open(sp, encoding="utf-8").read())
        notes.append(Note(f"{ELA}/how-ela-runs.md", "How ela runs", body, {"type": "system"}, fl, src_rel="system/how-ela-runs.md"))
    for sub in ("ela", ""):
        d = os.path.join(reports, sub) if sub else reports
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            p = os.path.join(d, f)
            # a symlink is a living document kept elsewhere (a manual), not a report
            if not f.endswith(".md") or f.lower() == "readme.md" or os.path.islink(p) or not os.path.isfile(p):
                continue
            fl, body = split_front(open(p, encoding="utf-8").read())
            base = f[:-3]
            m = re.search(r"(\d{4}-\d{2}-\d{2})", base)
            rest = slug(re.sub(r"[-_]?\d{4}-\d{2}-\d{2}[-_]?", "-", base)) if m else slug(base)
            title = sentence(h1(body) or base.replace("-", " "))
            # a report is a reading: a deep read, a review of a release or the docker services, a promote check
            if m:
                title = re.sub(r"\s*[—–,-]?\s*[（(]?" + m.group(1) + r"[)）]?(\s*[（(][^)）]{1,6}[)）])?", "", title).strip() or title
                path = f"{READINGS}/{m.group(1)}-{rest}.md"
            else:
                path = f"{READINGS}/{rest}.md"
            # a deep reading of one ticket (`ela-runner deep`) is a ticket page: real status, timeline, next
            kind = "ticket" if re.match(r"^\d{4}-\d{2}-\d{2}-deep-", base) else "review"
            notes.append(Note(path, title, body, {"type": kind, "date": m.group(1) if m else None}, fl,
                              src_rel=f"{sub + '/' if sub else ''}{f}"))
    return notes


def reader_heading(body, date):
    """A reader page headed by its title (`# The reader · <date>`, its spec); what an older heading said beyond that,
    such as which morning page it read, stays as the line beneath."""
    want = f"The reader · {date}"
    m = re.search(r"^#[ \t]+(.+?)[ \t]*$", body, re.M)
    if not m:
        return f"# {want}\n\n{body}"
    if m.group(1) == want:
        return body
    rest = re.sub(r"^(?:The )?reader\s*·\s*", "", m.group(1), flags=re.I).strip()
    sub = f"\n\n*{rest[:1].upper() + rest[1:]}*" if rest and rest != date else ""
    return body[:m.start()] + f"# {want}{sub}" + body[m.end():]


RECENT_POINTER = "*Every ticket of the week, placed by line and lane: [[recent|Recent · 7 days]]*"


def recent_note(reports):
    """recent.md from the newest <reports>/recent/<date>.json (`ela recent --write`), rendered by the recent skill's own
    page writer so the vault and `ela recent` read the same; None when there is no result or it cannot be rendered."""
    try:
        sys.path.insert(0, os.path.join(HERE, "..", "recent"))
        import recent as RC  # noqa: E402
        path, data = RC.newest_result(reports)
        if not data:
            return None
        body = RC.render_page(data)
    except Exception as e:                                 # a result an older recent wrote, or an import problem: no page, said once
        print(f"recent: not rendered — {str(e)[:120]}", file=sys.stderr)
        return None
    return Note("recent.md", RC.TITLE, body, {"type": "recent", "date": (data.get("at") or "")[:10] or None}, [],
                src_rel=f"recent/{os.path.basename(path)}")


def onething_note(reports, today):
    """one-thing.md from the One Thing store (<reports>/onething/<month>.json), rendered by the onething skill's own page
    writer so the vault and `ela onething post` read the same rows; None when the store is empty or cannot be rendered.
    `count` on the note is the rows not yet pasted, for Home's link."""
    try:
        sys.path.insert(0, os.path.join(HERE, "..", "onething"))
        import onething as OT  # noqa: E402
        base, project, who = OT.jira_base(), OT.setting(None, "ONETHING_PROJECT", "MH"), OT.setting(None, "ONETHING_WHOM")
        if not who:
            return None                                    # no name in the site env: no copy block to offer
        body, count = OT.month_page(reports, today, base, project, who)
    except Exception as e:                                 # an import problem or a store an older onething wrote: no page, said once
        print(f"one-thing: not rendered — {str(e)[:120]}", file=sys.stderr)
        return None
    if body is None:
        return None
    n = Note("one-thing.md", OT.PAGE_TITLE.format(month=today.isoformat()[:7]), body,
             {"type": "one-thing", "date": today.isoformat()}, [], src_rel=f"onething/{today.isoformat()[:7]}.json")
    n.count = count
    return n


def with_recent_pointer(body, have_recent):
    """The morning page's New tickets line points at the recent page when the vault has one and the page does not yet."""
    if not have_recent or "[[recent" in body:
        return body
    return re.sub(r"^(## New tickets[ \t]*)$", lambda m: m.group(1) + "\n\n" + RECENT_POINTER, body, count=1, flags=re.M)


APPLY_BOX = re.compile(r"^([ \t]*" + QUOTE + r"[-*][ \t]+)\[[ xX]\]([ \t]+apply[ \t]+(\d+)\b.*?)[ \t]*$", re.M)
DONT_BOX = re.compile(r"^([ \t]*" + QUOTE + r"[-*][ \t]+\[[ xX]\][ \t]+don't[ \t]+(\d+)\b.*?)[ \t]*$", re.M)   # tier 2: his box vetoes it
SEND_BOX = re.compile(r"^([ \t]*" + QUOTE + r"[-*][ \t]+)\[[ xX]\]([ \t]+send[ \t]+(\d+)\b.*?)[ \t]*$", re.M)   # tier 3: leaves on his tick
DONE_LINE = re.compile(r"^([ \t]*" + QUOTE + r"[-*][ \t]+done[ \t]+(\d+)\b.*?)[ \t]*$", re.M)          # tier 1: ela did it
# what follows an open send box, replaced by the outcome once it has one: the runner's "unticked: stays as apply N",
# or ela's list link, channel and "untouched: not sent"
SEND_TAIL = re.compile(r"[ \t]*·[ \t]*(?:unticked: stays as apply \d+|\[\[lanes/[^\]]*\]\](?: → #[\w-]+)?|→ #[\w-]+|untouched: not sent)[ \t]*$")
LIST_COUNTS = {"qa-today": ("test-list", re.compile(r"(\d+) open(?: · P1 (\d+))?"), "P1"),
               "dev-today": ("dev-list", re.compile(r"(\d+) ticket\(s\)(?: · (\d+) with a gap)?"), "with a gap")}


def list_links(reports):
    """{(rule, lane or line): wikilink} for each lane list on disk, the page a send box would send: QA today's test list
    as [[lanes/test-list-<lane>|N rows, M P1]], Dev today's dev list as [[lanes/dev-list-<line>|N rows, M with a gap]],
    the counts read from the page's own count line."""
    out, d = {}, os.path.join(reports or "", "lanes")
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        m = re.match(r"^(test-list|dev-list)-(.+)\.md$", f)
        if not m:
            continue
        rule = "qa-today" if m.group(1) == "test-list" else "dev-today"
        try:
            c = LIST_COUNTS[rule][1].search(open(os.path.join(d, f), encoding="utf-8").read(8000))
        except OSError:
            continue
        label = f"{c.group(1)} rows, {c.group(2) or 0} {LIST_COUNTS[rule][2]}" if c else "the list"
        out[(rule, m.group(2))] = f"[[lanes/{f[:-3]}|{label}]]"
    return out


def send_tail(a, lists=None):
    """What follows an open send box: the list it would send, the channel it goes to, and that untouched it is not
    sent. Nothing of it changes the box prefix the runner reads (`- [x] send N`)."""
    scope = a.get("scope") or []
    where = scope[1] if len(scope) > 1 and scope[0] in ("--lane", "--line") else None
    kind = LIST_COUNTS.get(a.get("rule"), (None,))[0]
    link = (lists or {}).get((a.get("rule"), where)) or (f"[[lanes/{kind}-{where}|the list]]" if kind and where else None)
    chan = str(a.get("channel") or "").lstrip("#") or next(iter(re.findall(r"#([\w-]+)", str(a.get("command") or ""))), None)
    head = " ".join(x for x in (link, f"→ #{chan}" if chan else None) if x)
    return (f" · {head}" if head else "") + " · untouched: not sent"


def strip_send_tail(rest):
    while True:
        cut = SEND_TAIL.sub("", rest)
        if cut == rest:
            return rest
        rest = cut


def action_states(body, actions_path, lists=None):
    """The morning page as a checklist: each drafted write shows what became of it, read from the day's actions file.
    Applied: the apply box ticked, with the time. Not applied: a second box beside it, "I handled it myself", for a
    write he made his own way (ticking apply would run the drafted one); ticked when he ticks it or when the runner
    finds his own Jira comment newer than the draft, with the time and how."""
    try:
        acts = {str(a.get("n")): a for a in json.load(open(actions_path, encoding="utf-8"))}
    except (OSError, ValueError):
        return body

    def one(m):
        a = acts.get(m.group(3))
        if not a:
            return m.group(0)
        lead, rest, n = m.group(1), m.group(2), m.group(3)
        if a.get("applied"):
            return f"{lead}[x]{rest} · {applied_words(a, 'applied')}"
        o = a.get("by_owner")
        if not o:
            return f"{lead}[ ]{rest}\n{lead}[ ] I handled it myself — not apply {n}"
        how = f"you commented in Jira {o['at'][11:16]}" if o.get("comment") else f"marked {o['at'][11:16]}"
        return f"{lead}[ ]{rest}\n{lead}[x] I handled it myself — not apply {n} · {how}"
    def outcome(m):                                       # what the runner did with a tier-1 or tier-2 action
        a = acts.get(m.group(2))
        if not a:
            return m.group(0)
        if a.get("failed"):
            return f"{m.group(1)} · not done: {str((a['failed'] or {}).get('error') or 'failed')[:80]}"
        if (a.get("dry_run") or {}).get("line"):            # held: the runner's own line, no box left to tick
            return re.match(r"[ \t]*" + QUOTE + r"[-*][ \t]+", m.group(1)).group(0) + a["dry_run"]["line"]
        if a.get("vetoed"):
            return f"{m.group(1)} · held, you ticked {a['vetoed'][11:16]}"
        if a.get("applied"):
            return f"{m.group(1)} · {applied_words(a, 'sent' if m.re is DONT_BOX else 'done')}"
        return m.group(0)
    def sent(m):                                          # a send box: open with what it would send, ticked, sent or not
        a = acts.get(m.group(3))
        lead, rest = m.group(1), m.group(2)
        if not a or re.search(r" · (sent|not sent|ticked|applied)\b", rest):
            return m.group(0)                             # unknown, or the runner's own line already says it
        rest = strip_send_tail(rest)
        if a.get("applied"):
            return f"{lead}[x]{rest} · {applied_words(a, 'sent')}" + (f" · [link]({a['permalink']})" if a.get("permalink") else "")
        if a.get("failed"):
            return f"{lead}[x]{rest} · not sent: {str((a['failed'] or {}).get('error') or 'failed')[:80]}"
        if ticked_at(a):
            return f"{lead}[x]{rest} · ticked {ticked_at(a)[11:16]}"
        if (a.get("unsent") or {}).get("final"):
            return f"{lead}[ ]{rest} · not sent: no tick · stays as apply {m.group(3)}"
        return f"{lead}[ ]{rest}{send_tail(a, lists)}"
    return SEND_BOX.sub(sent, DONE_LINE.sub(outcome, DONT_BOX.sub(outcome, APPLY_BOX.sub(one, body))))


def record_verdict(html_path):
    """(verdict, what it means, environment) from a verification page's own text, or None when it states none."""
    try:
        t = open(html_path, encoding="utf-8").read()
    except OSError:
        return None
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).replace("&amp;", "&")
    m = re.search(r"\bVerdict\s+(PASS|FAIL|BLOCKED|UNPROVEN|PARTIAL)\b\s*([a-z][^.]{0,140}?)?\s*(?:Environment\s+(\S+))?(?=\s+[A-Z])", t)
    if not m:
        return None
    return m.group(1), (m.group(2) or "").strip(), m.group(3)


def peek_verdict(path):
    try:
        m = re.search(r"\[!\w+\]\s+(PASS|FAIL|BLOCKED)\b", open(path, encoding="utf-8").read(4000))
    except OSError:
        return None
    return m.group(1) if m else None


def verify_path(key, date, extra):
    return f"{TO_READ}/{date}-verify-{key.lower()}{extra}.md"


def posted_to_jira(reports):
    """{key: [times]} ela attached a file to the ticket (a verification's record goes up as its PDF), from ela's write log."""
    out = {}
    try:
        for line in open(os.path.join(reports, "ela", "writes.jsonl"), encoding="utf-8"):
            try:
                w = json.loads(line)
            except ValueError:
                continue
            if w.get("system") == "jira" and w.get("verb") == "attach" and w.get("ok") and w.get("key"):
                out.setdefault(w["key"], []).append(w.get("at") or "")
    except OSError:
        pass
    return out


def verify_plan_notes(reports, results):
    """The verification plans written before the gate was retired (the night run now verifies the test list's auto
    rows directly, read-only, and the rows carry the result): readings, no status, no moves. A result for the same
    ticket on or after the plan's date replaces one."""
    d = os.path.join(reports, "verify", "plans")
    done = {}
    for n in results:
        k = re.search(r"-verify-([a-z][a-z0-9]+-\d+)", n.path)
        if k:
            done.setdefault(k.group(1).upper(), []).append(n.props.get("date") or "")
    notes = []
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-([A-Z][A-Z0-9]+-\d+)\.md$", f)
        if not m or any(x >= m.group(1) for x in done.get(m.group(2), [])):
            continue
        fl, body = split_front(open(os.path.join(d, f), encoding="utf-8").read())
        notes.append(Note(f"{READINGS}/{m.group(1)}-verify-plan-{m.group(2).lower()}.md", f"{m.group(2)} · verify plan", body,
                          {"type": "verify-plan", "date": m.group(1)}, [], src_rel=f"verify/plans/{f}"))
    return notes


def verify_notes(reports, today=None):
    """One note per verification record. A record folder is copied whole into the attachments, so its own page,
    which refers to its images by relative path, still opens from the vault."""
    notes, files = [], []
    posted = posted_to_jira(reports)
    vd = os.path.join(reports, "verify")
    for name in sorted(os.listdir(vd)) if os.path.isdir(vd) else []:
        m = re.match(r"^([A-Z][A-Z0-9]+-\d+)-(\d{4}-\d{2}-\d{2})(-[a-z0-9-]+)?(\.html)?$", name)
        if not m:
            continue
        key, date, extra, single = m.group(1), m.group(2), (m.group(3) or ""), bool(m.group(4))
        # a pass is in the vault for 14 days, then lives on its Jira ticket, in the reports root and in the backup; a
        # failed or blocked one stays until the owner deletes it, since it is a finding someone must act on
        p_ = os.path.join(vd, name)
        verdict_now = peek_verdict(p_ if single else os.path.join(p_, "report.md")) or \
            (record_verdict(p_ if single else os.path.join(p_, "record.html")) or [None])[0]
        if today and (today - datetime.date.fromisoformat(date)).days >= DAYS_KEPT and verdict_now not in ("FAIL", "BLOCKED"):
            continue
        if any(at[:10] >= date for at in posted.get(key, [])):
            continue                                       # the result is on the ticket, where the report lives; he confirmed it
        if any(re.match(rf"^{key}-(\d{{4}}-\d{{2}}-\d{{2}}){re.escape(extra)}(\.html)?$", o) and o[len(key) + 1:len(key) + 11] > date
               for o in os.listdir(vd)):
            continue                                       # a later run on the same lane replaces this one
        p = os.path.join(vd, name)
        record = f"{ATTACH}/verify/{date[:7]}/{name.lower()}"
        pdfs, imgs, page = [], [], None
        if single:
            files.append((p, record)); page = record
        else:
            for top_, _, fs in os.walk(p):
                for f in sorted(fs):
                    rel = os.path.relpath(os.path.join(top_, f), p).replace(os.sep, "/")
                    dst = f"{record}/{rel}"
                    low = f.lower()
                    if low.endswith((".html", ".md")) and low != "record.html" and os.path.isfile(os.path.join(p, "record.html")):
                        continue                   # index.html and the print copy repeat record.html
                    files.append((os.path.join(top_, f), dst))
                    low = f.lower()
                    if low.endswith(".pdf"):
                        pdfs.append(dst)
                    elif low.endswith((".png", ".jpg", ".jpeg")):
                        imgs.append(dst)
                    elif low in ("index.html", "print.html", "record.html") and (page is None or low == "record.html"
                                                                                   or (low == "index.html" and not page.endswith("record.html"))):
                        page = dst             # record.html, images embedded, opens inside Obsidian through HTML Reader
        md = os.path.join(p, "report.md") if not single else ""
        if md and os.path.isfile(md):                  # the record's own Markdown, written by the verify renderer
            body = open(md, encoding="utf-8").read()
            body = re.sub(r"!\[\[(img/[^\]]+)\]\]", lambda m: f"![[{record}/{m.group(1)}]]", body)
            body = body.replace("`index.html` beside this file.", f"[[{page}|open it]].") if page else body
            vm = re.search(r"\[!\w+\]\s+([A-Z]+)", body)
            title = h1(body) if h1(body) and not h1(body).endswith(date) else (f"{key} · {vm.group(1)}" if vm else f"{key} verification")
            title += f" ({extra.strip('-')})" if extra and " on " not in title.split(" · ")[1] else ""
            if not body.lstrip().startswith("# " + key + " · "):  # an older record's heading: the title takes its place
                body = re.sub(r"^#[ \t]+.*$", "# " + title, body, count=1, flags=re.M)
            title = " · ".join(title.split(" · ")[:2])     # key and verdict on its lane; the summary is the heading's
            notes.append(Note(verify_path(key, date, extra), title, body, {"type": "verify", "date": date, **verdict_props(vm.group(1) if vm else None)},
                              src_rel=f"verify/{name}"))
            continue
        verdict = record_verdict(os.path.join(vd, name) if single else os.path.join(p, os.path.basename(page or "index.html")))
        body = [f"# {key} verification{' · ' + extra.strip('-') if extra else ''}", ""]
        if not verdict:
            continue                                       # nothing to read without opening the record; it stays in the reports
        else:
            body += [f"> [!{ {'PASS': 'success', 'FAIL': 'failure', 'BLOCKED': 'warning'}.get(verdict[0], 'info') }] {verdict[0]}"
                     + (f": {verdict[1]}" if verdict[1] else "") + (f" · {verdict[2]}" if verdict[2] else ""), ""]
        body.append(f"Ticket {key}" + (f" · [[{page}|open the full record]]" if page else ""))
        body.append("")
        if pdfs:
            body += [f"![[{pdfs[0]}]]", ""]
        if imgs:
            body += ["## Screenshots", ""] + [f"![[{e}]]" for e in imgs[:8]]
            if len(imgs) > 8:
                body += ["", f"{len(imgs) - 8} more in the full record."]
        notes.append(Note(verify_path(key, date, extra), f"{key} · {verdict[0]}", "\n".join(body) + "\n",
                          {"type": "verify", "date": date, **verdict_props(verdict[0])}, src_rel=f"verify/{name}"))
    return notes, files


# ── ticket keys ───────────────────────────────────────────────────────────────────────────────────────

def project_keys(env, runtime):
    """The projects the owner works in (assigned, reported or watched in 180 days), cached for a day. A key in text
    links to Jira only when its project is here and its prefix is not a standard's or a codec's name."""
    cache = os.path.join(runtime or "/tmp", "vault-projects.json")
    try:
        c = json.load(open(cache))
        if c.get("day") == datetime.date.today().isoformat():
            return set(c["projects"])
        stale = set(c["projects"])
    except (OSError, ValueError, KeyError):
        stale = set()
    cmd = ["python3", JIRA] + (["--env-file", env] if env else []) + [
        "jql", "(assignee was currentUser() OR reporter = currentUser() OR watcher = currentUser()) AND updated >= -180d",
        "--limit", "3000", "--json"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        keys = sorted({i["key"].split("-")[0] for i in json.loads(r.stdout)["issues"]}) if r.returncode == 0 else []
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        keys = []
    if not keys:
        return stale                                       # a failed lookup must not unlink every key in the vault
    try:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        json.dump({"day": datetime.date.today().isoformat(), "projects": keys}, open(cache, "w"))
    except OSError:
        pass
    return set(keys)


# ── links ─────────────────────────────────────────────────────────────────────────────────────────────

ELAK_PATH = re.compile(r"`(?:<elak>/)?((?:blueprint|knowledge|map)/[^`\s]+?\.md|README\.md)(?:#[^`]*)?`")
SEGMENT = re.compile(r"(```.*?```|\[[^\]]*\]\([^)]*\)|<https?://[^>]+>|https?://\S+|`[^`]*`|\[\[[^\]]*\]\])", re.S)
SLACK_LINK = re.compile(r"<(https?://[^|>]+)\|([^>]+)>")


REPORT_PATH = re.compile(r"`?(?:<reports>|REPORTS_ROOT)/([^`\s)]+?\.md)`?")


class Linker:
    def __init__(self, in_vault, titles, jira_base, projects, reports=None, report_notes=None):
        self.in_vault, self.titles, self.jira_base, self.projects = in_vault, titles, jira_base, projects
        self.reports, self.report_notes = (reports or "").rstrip("/"), report_notes or {}

    def report(self, m):
        n = self.report_notes.get(m.group(1))
        return f"[[{n.path[:-3]}|{n.title}]]" if n else m.group(0)

    def is_key(self, k):
        return bool(self.jira_base) and k.split("-")[0] in self.projects and not NOT_KEYS.match(k)

    def __call__(self, text):
        text = SLACK_LINK.sub(lambda m: f"[{m.group(2)}]({m.group(1)})", text)
        if self.reports:
            text = text.replace(self.reports + "/", "REPORTS_ROOT/")
        text = REPORT_PATH.sub(self.report, text).replace("REPORTS_ROOT/", "<reports>/")

        def elak(m):
            n = self.in_vault.get(m.group(1))
            if n:
                return f"[[{n.path[:-3]}|{n.title}]]"
            t = self.titles.get(m.group(1))
            return f"*{t}*" if t else m.group(0)
        out = []
        for i, seg in enumerate(SEGMENT.split(text)):
            if i % 2:
                out.append(ELAK_PATH.sub(elak, seg) if seg.startswith("`") and not seg.startswith("```") else seg)
            else:
                out.append(KEY_RX.sub(lambda m: f"[{m.group(1)}]({self.jira_base}/browse/{m.group(1)})"
                                      if self.is_key(m.group(1)) else m.group(1), seg))
        return "".join(out)


# ── the reading gate ──────────────────────────────────────────────────────────────────────────────────

def reading_units(text):
    """English words plus two CJK characters per unit, with code blocks and link targets left out."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"\]\([^)]*\)", "]", text)
    text = re.sub(r"https?://\S+", "", text)
    return len(re.findall(r"[A-Za-z0-9][\w'’.-]*", text)) + len(re.findall(r"[一-鿿]", text)) // 2


def code_lines(body):
    """Lines inside fenced code blocks, walked fence by fence; a mermaid block is a diagram, not code to read."""
    count, inside, diagram = 0, False, False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            if not inside:
                inside, diagram = True, line.strip().lower().startswith(("```mermaid", "~~~mermaid"))
            else:
                inside = False
            continue
        if inside and not diagram:
            count += 1
    return count


def mermaid_problems(body):
    """Mermaid faults Obsidian shows as a parse error instead of a diagram: a timeline period with a colon in it
    (`01:00 : event`), since the colon is the period's separator."""
    out, kind = [], None
    for line in body.splitlines():
        t = line.strip()
        if t.startswith(("```mermaid", "~~~mermaid")):
            kind = ""; continue
        if kind is not None and t.startswith(("```", "~~~")):
            kind = None; continue
        if kind == "":
            kind = t.split()[0] if t else ""
            continue
        if kind == "timeline" and re.match(r"^[^:]*\d:\d[^:]*:", t):
            out.append(f"a mermaid timeline period carries a colon ({t[:20]}…)")
    return out


def type_lint(path, kind):
    """One lint line when a note's type is outside the closed set, or its family outside its folders; else None."""
    fam = TYPE_FAMILY.get((kind or "").strip().strip("'\""))
    if not fam:
        return f"{path}: type {kind!r} is not in the closed set ({', '.join(sorted(set(TYPE_FAMILY.values())))})"
    folder = path.split("/", 1)[0] if "/" in path else ""
    if kind == "review" and path.startswith(MH + "/"):     # a product reading kept with the program it reads
        return None
    if fam in FAMILY_FOLDERS and not any(path.startswith(f + "/") for f in FAMILY_FOLDERS[fam]):
        return f"{path}: a {fam} belongs in {', '.join(FAMILY_FOLDERS[fam])}"
    if kind == "guide" and folder != ELA:                 # the ela page's type; a page elsewhere has its own
        return f"{path}: a guide is the ela page and belongs in {ELA}/"
    if kind == "project" and not PROJECT_PAGE.match(path):
        return f"{path}: a project page is {PROJECTS}/<key>/<key>.md"
    if kind == "services" and path != SERVICES_PAGE:
        return f"{path}: the service map is {SERVICES_PAGE}"
    return None


def project_lint(path, props, vault):
    """One lint line when a note names a project (`project: <key>`) that has no folder projects/<key>/; else None."""
    key = (props.get("project") or "").strip()
    if key and not os.path.isdir(os.path.join(vault, PROJECTS, key)):
        return f"{path}: project {key!r} has no folder {PROJECTS}/{key}/"
    return None


BOX = re.compile(r"^[ \t]*" + QUOTE + r"[-*][ \t]+\[([ xX])\][ \t]+\S", re.M)


def open_asks(body):
    """(open, total) boxes under the note's Waiting for your word heading. A box is answered when ticked, or when an
    `ela:` line follows it before the next box; (0, 0) when the note has no such heading or no box under it."""
    m = re.search(r"^##[ \t]+" + re.escape(ASKS_HEAD) + r"[ \t]*\n(.*?)(?=^#{1,2}[ \t]|\Z)", body or "", re.M | re.S)
    sec = m.group(1) if m else ""
    boxes = list(BOX.finditer(sec))
    unanswered = sum(1 for i, b in enumerate(boxes) if b.group(1) == " "
                     and not GUIDE.search(sec, b.end(), boxes[i + 1].start() if i + 1 < len(boxes) else len(sec)))
    return unanswered, len(boxes)


def asks_lint(n):
    """One lint line when a reading outside to-read still has an open box under Waiting for your word: its asks
    belong where he looks for what waits on him."""
    if TYPE_FAMILY.get(n.props.get("type")) != "reading" or top(n.path) == TO_READ:
        return None
    left, _ = open_asks(n.body)
    return f"{n.path}: {left} open under {ASKS_HEAD}; a reading that asks belongs in {TO_READ}/" if left else None


def answered_readings(vault, reports, dry_run=False):
    """A reading ela wrote in place in to-read whose every box under Waiting for your word is ticked or answered with
    an `ela:` line moves to readings/; a plan or decision keeps its own life. Returns [(from, to)]."""
    out, d = [], os.path.join(vault, TO_READ)
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not f.endswith(".md"):
            continue
        try:
            fl, body = split_front(open(os.path.join(d, f), encoding="utf-8").read())
        except OSError:
            continue
        props = props_of(fl)
        if props.get("source") != "vault" or TYPE_FAMILY.get(props.get("type")) != "reading":
            continue
        left, total = open_asks(body)
        if total and not left:
            out.append((f"{TO_READ}/{f}", None if dry_run else move_note(vault, reports, f"{TO_READ}/{f}", "readings")))
    return out


def report_lint(n):
    """Lint lines for a report ela writes in place: its budget as advice, its status, and no moves, since a report
    is ruled in place and has no lifecycle."""
    out = [f"{n.path}: {p}" for p in reading_gate(n) if "words" in p and "budget" in p]
    st = n.props.get("status")
    if st and st not in REPORT_STATUSES:
        out.append(f"{n.path}: status {st!r}: a report is {', '.join(REPORT_STATUSES)}")
    if n.props.get(MOVE_SET):
        out.append(f"{n.path}: moves {n.props[MOVE_SET]!r}: a report is ruled in place and offers no moves")
    return out


# ── note standards ────────────────────────────────────────────────────────────────────────────────────
# One written spec per note type (working preferences, *Notes of one kind follow one standard*, 2026-11-09), decided
# by ela from his recorded preferences (English for durable content, every Jira key a link, each note ends with what
# he should do and how, options keep his labels) and the vault's own rules (budgets, statuses by folder, Waiting for
# your word), the best existing notes of each type as the model. The readme prints them (spec_text); `vault.py lint`
# reports each deviation as one line, never a failure; `lint --fix` normalises what is mechanical (quoting, a title's
# links, its alias), a dry run unless --apply, and never removes body text.
WHAT_TO_DO = "What you should do"
DATED = r"\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*"
SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
KEY_TITLE = r"^[A-Z][A-Z0-9]+-\d+ · "
TAIL_ORDER = (WHAT_TO_DO, ASKS_HEAD, "Progress", "Next moves", "Afterwards")   # the closing, then what ela keeps
LIFE_PROPS = ("archived", "built", "claimed", "waits-on", "wake", "parked", "closed-by")   # set by a move, any type
# kind: what the note is for; name: (regex on the path, as written); title: (regex, as written); required and
# optional properties beyond title, aliases and type; sections: the headings in order (a trailing ? is optional);
# closing: how it ends with what he should do; budget from BUDGET, or the rule that stands in for one
SPECS = {
    "decision": dict(
        kind="a choice for your word: confirm or park",
        name=(rf"^(?:to-read|in-progress|parked|archive|ela/history)/{DATED}\.md$", "`<date>-<slug>.md`, in to-read/ until ruled"),
        title=(r".", "the choice as a sentence: what is decided, about what"),
        required=("date",), optional=("source", "target", "keys", "posted", "watch", "project", "ela", "progress"),
        sections=("The question?", "Options?", WHAT_TO_DO),
        closing=f"## {WHAT_TO_DO}: the recommended option and the alternative, each with its first step; options you named keep your labels, your order and your definitions, the recommendation a separate line"),
    "plan": dict(
        kind="work for your word: agree, park, not now or reject",
        name=(rf"^(?:to-read|in-progress|parked|archive|ela/history|mh/releases(?:/[\d.]+)?)/{DATED}\.md$|^mh/releases/[\d.]+/{SLUG}-test-plan\.md$",
              "`<date>-<slug>.md`; a release line's test plan `mh/releases/<line>/<slug>-test-plan.md`"),
        title=(r".", "what the plan builds, as a sentence"),
        required=("date",), optional=("source", "target", "keys", "posted", "watch", "project", "ela", "progress", "branch"),
        sections=("The problem?", WHAT_TO_DO, ASKS_HEAD + "?", "Progress?"),
        closing=f"## {WHAT_TO_DO}: what agree starts and what each other move means; each ruling it needs listed with ela's proposed answer, no boxes. A plan for ela's own design asks nothing: its Gate is written as reasoning"),
    "sprint": dict(
        kind="a sprint: a plan with a start and an end",
        name=(r"^sprints/\d{4}-S\d{2}\.md$", "`sprints/<year>-S<nn>.md`"),
        title=(r"^Sprint \d+ · ", "`Sprint <n> · <start> – <end>`"),
        required=("date", "start", "end"), optional=("source", "status"),
        sections=("Sprint goals", "Committed", "Stretch?"),
        closing="its goals are the ask; the sprint's end review says what landed"),
    "review": dict(
        kind="a reading of evidence: a release, a promotion, a docker check, a part of the product or of ela",
        name=(rf"^(?:readings|to-read|archive|mh|ela/history|projects/{SLUG}|mh/releases(?:/[\d.]+)?)/{DATED}\.md$",
              "`<date>-<slug>.md`; a review of a release names it in the slug (promote, deploy, docker, release or hotfix)"),
        title=(r".", "a review of a release: `MH <line> · <from> → <to> · <what>`; any other: its finding as a sentence"),
        required=("date",), optional=("source", "keys", "posted", "watch", "project", "target", "ela", "progress"),
        sections=("What could not be read?", WHAT_TO_DO, ASKS_HEAD + "?"),
        closing=f"## {WHAT_TO_DO}: each action a box or a ready command, the recommendation first; what could not be read is named as a gap above it"),
    "ticket": dict(
        kind="one ticket made judgeable: where it stands, what done is",
        name=(rf"^(?:readings|to-read|archive|projects/{SLUG}|mh/releases(?:/[\d.]+)?)/\d{{4}}-\d{{2}}-\d{{2}}-(?:deep-)?[a-z]+-\d+(?:-{SLUG})?\.md$",
              "`<date>-<key>-<slug>.md`, the key lowercase (`2026-10-30-mh-2406-timeline.md`)"),
        title=(KEY_TITLE, "`<KEY> · <where it stands>`, the key as plain text (the heading may link it)"),
        required=("date", "keys"), optional=("source", "posted", "watch", "project"),
        sections=("Done when?", "Next?"),
        closing="a **Do.** line: the move, who it waits on, and the first step"),
    "verify": dict(
        kind="a verification in a real browser on a named lane",
        name=(r"^(?:to-read|readings|archive|mh/releases(?:/[\d.]+)?)/\d{4}-\d{2}-\d{2}-verify-[a-z]+-\d+(?:-[a-z0-9-]+)?\.md$",
              "`<date>-verify-<key>[-<lane>].md`"),
        title=(KEY_TITLE + r"(?:PASS|FAIL|BLOCKED) on \S+", "`<KEY> · PASS|FAIL|BLOCKED on <lane>`"),
        required=("date", "result", "keys"), optional=("posted", "watch", "source"),
        sections=("Checks", "What failed, seen?"),
        closing="its moves: *draft-comment* puts the Jira record as `apply N`; the full record is the linked page"),
    "verify-plan": dict(
        kind="a verification run waiting for your word on its goals",
        name=(r"^(?:to-read|archive|mh/releases(?:/[\d.]+)?)/\d{4}-\d{2}-\d{2}-verify-plan-[a-z]+-\d+\.md$", "`<date>-verify-plan-<key>.md`"),
        title=(KEY_TITLE + r"verify plan$", "`<KEY> · verify plan`"),
        required=("date", "keys"), optional=("posted", "watch"),
        sections=(), closing="its moves: *run*, *not-now* or *drop*"),
    "case": dict(
        kind="one customer support case",
        name=(rf"^(?:cases|projects/{SLUG})/{DATED}\.md$|^cases/{SLUG}/{DATED}\.md$", "`cases/<date>-<slug>.md`"),
        title=(r" · ", "`<customer or stream> · <what happened>`"),
        required=("date", "customer", "keys", "status"), optional=("hubspot", "graph", "box", "channels", "posted", "watch", "source", "progress", "project"),
        sections=("Timeline?", "Findings?", "Open?", WHAT_TO_DO),
        closing=f"## {WHAT_TO_DO}: the reply to support or the next check, and who acts"),
    "report": dict(
        kind="a standing review or design for your decision, ruled in place",
        name=(rf"^(?:[a-z0-9.-]+/)*(?:{DATED}|{SLUG})\.md$", "`<slug>.md`, or `<date>-<slug>.md` when it is of a day"),
        title=(r".", "what it settles, as a sentence"),
        required=("date", "source", "status"), optional=("target", "progress", "ela", "keys", "posted", "watch", "project"),
        sections=(WHAT_TO_DO, ASKS_HEAD + "?"),
        closing=f"## {WHAT_TO_DO}: the recommendation, the alternative, the first step; status proposed, decided or superseded"),
    "project": dict(
        kind="bounded work with a deadline and parties outside the program",
        name=(r"^projects/([^/]+)/\1\.md$", "`projects/<key>/<key>.md`"),
        title=(r".", "the project's name"),
        required=("date", "source", "deadline"), optional=("next-step", "channels", "keys", "posted", "watch", "customer", "hubspot"),
        sections=("Goal", "Parties?", "Dates?", "What is known?", "Next step") + TAIL_HEADS,
        closing="## Next step in the head (`next-step` is the line Home may name); the tail from Waiting for your word is the sync's"),
    "meeting": dict(
        kind="what you raise at one meeting, and what it ruled",
        name=(rf"^(?:meetings/{SLUG}|archive/meetings-{SLUG}-\d{{4}}-\d{{2}}|archive/{SLUG})\.md$", "`meetings/<key>.md`; older months `archive/meetings-<key>-<yyyy-mm>.md`"),
        title=(r" · |^Review list$", "`<meeting> · <days and time>`"),
        required=(), optional=("date", "status", "keys", "source"),
        sections=("To raise?", "Ruled"),
        closing="the `- [ ] send` box at the top; each item under 140 characters: ticket link · question · who decides · since when"),
    "day": dict(
        kind="a morning page, what changed the day before, or the week",
        name=(r"^days/\d{4}/\d{4}-\d{2}-\d{2}-(?:brief|changes|week|learn)\.md$", "`days/<year>/<date>-<kind>.md`, kind brief, changes or week"),
        title=(r"^(?:Morning brief|What changed|The week|What the day taught) · ", "`Morning brief · <Dow> <date>`, `What changed · …`, `The week · …`"),
        required=("date", "kind"), optional=(),
        sections=(), closing="each item ends in a **Do:** line: an `apply N`, a `don't N`, or *your call: <recommended> over <alternative>*"),
    "reader": dict(
        kind="the evening reader's verdict on that morning's page",
        name=(r"^ela/review/\d{4}-\d{2}-\d{2}-reader\.md$", "`ela/review/<date>-reader.md`"),
        title=(r"^The reader · \d{4}-\d{2}-\d{2}$", "`The reader · <date>`"),
        required=("date",), optional=(),
        sections=("Learned",), closing=f"## Learned, at most {LEARNED_MAX} lines; more goes to a decision note"),
    "draft": dict(
        kind="a message you send under your own name: a Slack post or reply, a Jira comment, a mail",
        name=(rf"^(?:to-read|parked|archive|projects/{SLUG})/{DATED}-(?:slack|jira|mail)-draft\.md$", "`<date>-<slug>-<slack|jira|mail>-draft.md`"),
        title=(r"^(?:Slack|Jira|Mail) draft: ", "`Slack draft: <subject>` (or Jira, Mail)"),
        required=("date", "source"), optional=("progress", "ela", "keys", "posted", "watch", "project", "channels"),
        sections=("Root message", "Thread replies?", "Not for this post?"),
        closing="the message paste-ready in a code block, English, mentions written for you to retype; parked once sent, `waits-on` naming who answers and `wake` what brings it back"),
}
BUDGET.update({"case": 1200, "draft": 600})
PAGES_SPEC = ("home", "board", "lanes", "recent", "one-thing", "test-list", "dev-list", "train", "program", "guide",
              "vocabulary", "system", "constraints", "readme", "services")   # living pages: each one's generator is its spec
CJK = re.compile(r"[一-鿿　-〿＀-￯]")
SPEC_MARK = "<!-- note standards -->"


def spec_text():
    """The readme's Note standards section, written from SPECS so the readme and the lint cannot disagree."""
    out = ["Every note: a lowercase file name, words joined by hyphens, a dated note starting with its date (its `date` "
           "property the same day). `title` is double-quoted plain text, without links, in English, and the first entry "
           "of `aliases`; the first heading is the title (it may link a ticket key). Durable text is English, and "
           "every Jira key in it is a link. The one exception is a note written for a Chinese-speaking audience (a test "
           "plan for the China QA team): it keeps its body's language, says so with `language: \"zh\"`, and still carries "
           "an English title, the Chinese one kept as an alias. A body is never translated in place. A note ends with what you should do and how, before the sections ela keeps "
           f"({', '.join(TAIL_ORDER[1:])}, in that order). A deviation is a lint line (`ela vault lint`), never a failure; "
           "an old name or title stays as an alias, so a link and the quick switcher still find the note.", ""]
    for kind, sp in SPECS.items():
        b = BUDGET.get(kind)
        secs = [s[:-1] + " (if any)" if s.endswith("?") else s for s in sp["sections"]]
        out += [f"### {kind}", "",
                f"- **What**: {sp['kind']}",
                f"- **File**: {sp['name'][1]}",
                f"- **Title**: {sp['title'][1]}",
                "- **Properties**: " + (", ".join(f"`{p}`" for p in sp["required"]) or "none") + " required"
                + (("; " + ", ".join(f"`{p}`" for p in sp["optional"]) + " when they apply") if sp["optional"] else "")
                + "; status, next and moves by folder",
                "- **Sections**: " + (" → ".join(secs) or "as its generator writes them"),
                f"- **Ends with**: {sp['closing']}",
                f"- **Budget**: {f'{b:,} words' if b else 'none; ' + ('the record is the linked page' if kind.startswith('verify') else 'its items are bounded instead')}"
                " · **Language**: English", ""]
    out += [f"Living pages ({', '.join(PAGES_SPEC)}) are written by their generators, which are their spec."]
    return "\n".join(out)


def headings(body):
    return [h.strip() for h in re.findall(r"^##[ \t]+(.+?)[ \t]*$", re.sub(r"```.*?```", "", body or "", flags=re.S), re.M)]


def plain(text):
    """A title or heading as text: Markdown and wiki links reduced to what they show."""
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text or "")
    return re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", t).strip()


def opening(text):
    """A title's or heading's opening, up to its first · or colon, as plain text without code marks."""
    return re.split(r"\s+·\s+|:\s", plain(text).replace("`", ""), maxsplit=1)[0].strip().lower()


def is_jira_key(k, projects=None):
    """A key-shaped word that is a Jira key: not a standard's or a codec's name, not a zero-led test id (MH-035), and
    in the owner's projects when they are known."""
    return not NOT_KEYS.match(k) and not k.split("-")[1].startswith("0") and (projects is None or k.split("-")[0] in projects)


FENCE = re.compile(r"^[ \t]*(?:>[ \t]*)*(```+|~~~+)")


def prose_parts(body):
    """[(text, is_prose)]: the body cut at fenced code, a fence inside a callout (`> ~~~~`, a paste-ready Slack post)
    included, so a fence's lines are never rewritten."""
    parts, buf, inside, mark = [], [], False, ""
    for line in (body or "").splitlines(keepends=True):
        m = FENCE.match(line)
        if m and (not inside or m.group(1)[0] == mark[0] and len(m.group(1)) >= len(mark)):
            if not inside:
                parts.append(("".join(buf), True)); buf = [line]; inside, mark = True, m.group(1)
            else:
                buf.append(line); parts.append(("".join(buf), False)); buf = []; inside = False
            continue
        buf.append(line)
    parts.append(("".join(buf), not inside))
    return [p for p in parts if p[0]]


def bare_keys(body, projects=None):
    """Jira keys written as text, outside links and code: each should be a link."""
    found = []
    for text, prose in prose_parts(re.sub(r"^---\n.*?\n---\n", "", body or "", flags=re.S)):
        for i, part in enumerate(SEGMENT.split(text) if prose else []):
            if i % 2 == 0:
                found += [k for k in KEY_RX.findall(part) if is_jira_key(k, projects)]
    return list(dict.fromkeys(found))


def link_keys(body, jira_base, projects=None):
    """(body, n): each bare Jira key made a link to its Jira page; code, links and existing links untouched, nothing
    removed. The owner's standing rule: every key he reads is a link."""
    if not jira_base:
        return body, 0
    out, n = [], 0

    def one(m):
        nonlocal n
        if not is_jira_key(m.group(1), projects):
            return m.group(0)
        n += 1
        return f"[{m.group(1)}]({jira_base}/browse/{m.group(1)})"
    for text, prose in prose_parts(body):
        out += [KEY_RX.sub(one, seg) if prose and i % 2 == 0 else seg for i, seg in enumerate(SEGMENT.split(text) if prose else [text])]
    return "".join(out), n


def spec_lint(rel, text, generated=False, projects=None):
    """The note's deviations from its type's spec, one line each; [] when it meets it or has no spec."""
    fl, body = split_front(text)
    props = props_of(fl)
    kind = props.get("type")
    if kind not in SPECS:
        return [] if kind in PAGES_SPEC or kind in TYPE_FAMILY or not fl else [f"type {kind!r} has no spec"]
    sp, out = SPECS[kind], []
    if not re.match(sp["name"][0], rel):
        out.append(f"file name: want {sp['name'][1]}")
    name = os.path.basename(rel)[:-3]
    dm = re.match(r"^(\d{4}-\d{2}-\d{2})-", name)
    if dm and props.get("date") and props["date"][:10] != dm.group(1):
        out.append(f"date {props['date']} but the file name says {dm.group(1)}")
    raw = next((l for l in fl if l.startswith("title:")), None)
    title = props.get("title") or ""
    if not raw:
        out.append("no title property")
    else:
        if not raw[6:].strip().startswith('"'):
            out.append("title not quoted")
        if plain(title) != title:
            out.append("title carries a link")
        if CJK.search(title):
            out.append("title not in English")
        elif not re.search(sp["title"][0], plain(title)):
            out.append(f"title: want {sp['title'][1]}")
        al = list_prop(fl, "aliases")
        if plain(title) not in al:
            out.append("the title is not among the aliases")
        head = h1(body)
        if head is None:
            out.append("no title heading")
        elif opening(head) != opening(title):             # a heading may add a subtitle or a time; it opens the same
            out.append("the first heading is not the title")
        stem = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", name)
        lost = [n for n in re.findall(r"(?<![\d.])\d{2,}(?![\d.])", stem.replace("-", " ")) if int(n) not in {int(d) for d in re.findall(r"\d+", title)}]
        if lost:
            out.append(f"the file name says {', '.join(lost)}, the title does not")
    missing = [p for p in sp["required"] if not props.get(p)]
    if missing:
        out.append("missing " + ", ".join(missing))
    known = set(PROPS) | set(LIFE_PROPS) | set(sp["required"]) | set(sp["optional"])
    extra = [k for k in props if k not in known and k not in ALL_MOVE_PROPS + tuple(MARKS) + ("learn", "start", "end", "built")]
    if extra:
        out.append("properties outside the vocabulary: " + ", ".join(extra))
    hs = [h.lower() for h in headings(body)]
    def at(want):
        w = want.rstrip("?").lower()
        return next((i for i, h in enumerate(hs) if h == w or h.startswith(w)), None)
    closed = folder_of(rel) in CLOSED_FOLDERS                # its outcome is in next: a closing would now be history
    for want in sp["sections"]:
        if not want.endswith("?") and at(want) is None and kind not in ("project",) and not (closed and want == WHAT_TO_DO):
            out.append(f"no ## {want}")
    order = [(at(t), t) for t in TAIL_ORDER if at(t) is not None]
    if [t for _, t in sorted(order)] != [t for _, t in order]:
        out.append("tail out of order: want " + " → ".join(t for _, t in order))
    if kind in ("ticket",) and not re.search(r"\*\*Do[.:]\*\*", body):
        out.append("no **Do.** line")
    if kind == "day" and props.get("kind") == "brief" and not re.search(r"\*\*Do[.:]\*\*", body):
        out.append("no **Do:** line")
    b = BUDGET.get(kind)
    units = reading_units(outside_folds(body))
    if b and units > b * TOLERANCE:
        out.append(f"{units:,} words, budget {b:,} (lint only: nothing is cut)")
    cjk = len(CJK.findall(outside_folds(body)))
    if cjk // 2 > units / 3 and (props.get("language") or "en") == "en":   # a note for a Chinese-speaking audience says so
        out.append("body not in English (a note written for a Chinese-speaking audience carries `language: \"zh\"`)")
    keys = bare_keys(body, projects) if not generated else []       # a generated note's keys are the renderer's, by its project list
    if keys:
        out.append(f"{len(keys)} Jira key{'s' if len(keys) > 1 else ''} not linked ({', '.join(keys[:4])}{', …' if len(keys) > 4 else ''})")
    return out


def lint_notes(vault, projects=None):
    """[(path, generated, [deviations])] for every note with a type, the hidden folders, attachments, the moves
    definitions and the retired folders left out; generated means the sync writes it (fix its generator or source)."""
    try:
        gen = set((json.load(open(os.path.join(vault, MANIFEST))).get("files") or {}))
    except (OSError, ValueError):
        gen = set()
    out = []
    for rel, text in vault_notes(vault):
        found = front_breaks(split_front(text)[0]) + spec_lint(rel, text, rel in gen, projects)
        if found:
            out.append((rel, rel in gen, found))
    return out


def vault_notes(vault):
    """(path, text) of every note the standards cover: hidden folders, attachments, the moves definitions and the
    retired folders left out."""
    for top_, dirs, fs in os.walk(vault):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and os.path.relpath(os.path.join(top_, d), vault).replace(os.sep, "/")
                         not in (ATTACH, MOVE_SETS_DIR) + RETIRED)
        for f in sorted(fs):
            if f.endswith(".md"):
                try:
                    yield os.path.relpath(os.path.join(top_, f), vault).replace(os.sep, "/"), open(os.path.join(top_, f), encoding="utf-8").read()
                except OSError:
                    continue


def front_span(fl, key):
    """(start, end) of one key in the front-matter lines, its block-list items (`  - x`) included; None if absent."""
    for i, l in enumerate(fl):
        if re.match(rf"^{re.escape(key)}:", l):
            j = i + 1
            while j < len(fl) and re.match(r"^\s+\S|^-\s", fl[j]):
                j += 1
            return i, j
    return None


def list_prop(fl, key):
    """A list property as written, inline (`["a"]`) or as a block (`  - a`), or both after a bad write: its items."""
    sp = front_span(fl, key)
    if not sp:
        return []
    head = fl[sp[0]].split(":", 1)[1].strip()
    try:
        items = json.loads(head) if head else []
        items = items if isinstance(items, list) else [str(items)]
    except ValueError:
        items = [prop_text(head)]
    items += [prop_text(re.sub(r"^\s*-\s*", "", l)) for l in fl[sp[0] + 1:sp[1]]]
    return [x for x in dict.fromkeys(items) if x]


def prop_text(v):
    v = v.strip()
    try:
        d = json.loads(v) if v[:1] == '"' else v
        return d if isinstance(d, str) else v
    except ValueError:
        return v.strip("'\"")


def front_line(fl, key, value):
    """The front-matter lines with one key replaced in place, block items included (or added after title), JSON-encoded."""
    line = f"{key}: {json.dumps(value, ensure_ascii=False)}"
    sp = front_span(fl, key)
    if sp:
        return fl[:sp[0]] + [line] + fl[sp[1]:]
    at = next((i + 1 for i, l in enumerate(fl) if l.startswith("title:")), 0)
    return fl[:at] + [line] + fl[at:]


def normalise(text, jira_base="", projects=None):
    """(text, fixes): the mechanical part of a note's spec — its title quoted, plain text, first among its aliases,
    with any earlier spelling kept as an alias; and each bare Jira key in the body a link. Nothing is removed."""
    fl, _ = split_front(text)
    raw = next((l for l in fl if l.startswith("title:")), None)
    if not raw or props_of(fl).get("type") not in SPECS:
        return text, []
    rest, linked = link_keys(text[text.find("\n---", 4) + 4:], jira_base, projects)   # the body exactly as written
    title = props_of([raw])["title"]
    want, fixes = plain(title), [f"{linked} Jira key{'s' if linked > 1 else ''} linked"] if linked else []
    al = list_prop(fl, "aliases")
    sp = front_span(fl, "aliases")
    if sp and (sp[1] - sp[0] > 1 or not fl[sp[0]].split(":", 1)[1].strip().startswith("[")):
        fixes.append("aliases written as one list")          # a block list, or a list left half-rewritten
    if not raw[6:].strip().startswith('"'):
        fixes.append("title quoted")
    if want != title:
        fixes.append("links taken out of the title, the old spelling kept as an alias")
    new_al = [want] + [a for a in dict.fromkeys(al + ([title] if want != title else [])) if a != want]
    if new_al[:1] != al[:1]:
        fixes.append("the title first among the aliases")
    if not fixes:
        return text, []
    if new_al[:1] != al[:1] or want != title or not raw[6:].strip().startswith('"') or "aliases written as one list" in fixes:
        fl = front_line(front_line(fl, "title", want), "aliases", new_al)
    return "---\n" + "\n".join(fl) + "\n---" + rest, fixes


def cmd_lint(a):
    """Lint the whole vault against the note standards, one line per deviation; with --fix, normalise what is
    mechanical (front matter only), a dry run unless --apply. Exit 0 either way: a deviation is a lint line."""
    s = json.load(open(SITE))
    vault = s["vault"]
    env = a.env_file or s.get("env")
    jira_base = next((l.split("=", 1)[1].strip().rstrip("/") for l in open(env) if l.startswith("JIRA_BASE_URL=")), "") \
        if env and os.path.isfile(env) else ""
    projects = (project_keys(env, s.get("runtime")) or None) if jira_base else None
    fixed = []
    if a.fix:
        gen = set()
        try:
            gen = set((json.load(open(os.path.join(vault, MANIFEST))).get("files") or {}))
        except (OSError, ValueError):
            pass
        for rel, text in list(vault_notes(vault)):
            if rel in gen:
                continue                                   # the sync rewrites it: the fix belongs in its generator
            p = os.path.join(vault, rel)
            new, fixes = normalise(text, jira_base, projects)
            if fixes:
                fixed.append({"note": rel, "fixes": fixes})
                if a.apply:
                    atomic_write(p, new)
    found = lint_notes(vault, projects)
    if a.json:
        print(json.dumps({"dry_run": a.fix and not a.apply, "fixed": fixed,
                          "lint": [{"note": r, "generated": g, "lines": l} for r, g, l in found]}, ensure_ascii=False)); return
    for x in fixed:
        print(f"{'would fix' if not a.apply else 'fixed'}: {x['note']}: {'; '.join(x['fixes'])}")
    for rel, g, lines in found:
        for l in lines:
            print(f"{rel}{' (generated)' if g else ''}: {l}")
    print(f"lint: {sum(len(l) for _, _, l in found)} deviations in {len(found)} notes"
          + (f"; {len(fixed)} notes {'normalised' if a.apply else 'to normalise (dry run; --apply)'}" if a.fix else ""))


def layout_folders():
    """The top folders the readme's layout table names."""
    table = re.search(r"^## Layout\n(.*?)(?=^## )", README, re.M | re.S)
    cells = re.findall(r"^\|([^|]*)\|", table.group(1) if table else "", re.M)
    return {c.split("/")[0] for cell in cells for c in re.findall(r"`([^`]+)`", cell)}


def folder_lint(vault):
    """One lint line per top folder the readme's layout table does not name; hidden folders are Obsidian's."""
    named = layout_folders()
    try:
        tops = sorted(d for d in os.listdir(vault) if not d.startswith(".") and os.path.isdir(os.path.join(vault, d)))
    except OSError:
        return []
    return [f"{d}/: a top folder the readme's layout does not name" for d in tops if d not in named]


def learned_lines(body):
    m = re.search(r"^## Learned[ \t]*\n(.*?)(?=^## |\Z)", body or "", re.M | re.S)
    return [l for l in (m.group(1) if m else "").splitlines() if re.match(r"^\s*[-*]\s+\S", l)]


def outside_folds(body):
    """The note without its folded callouts: a `> [!…]-` line and the quoted lines under it are read on demand, so
    they weigh nothing in the budget. An open callout (`> [!note]`) stays."""
    out, inside = [], False
    for line in (body or "").splitlines():
        if inside and line.startswith(">"):
            continue
        inside = bool(FOLD_RX.match(line))
        if not inside:
            out.append(line)
    return "\n".join(out)


def reading_gate(n):
    kind = n.props.get("type")
    if kind == "reader" and len(learned_lines(n.body)) > LEARNED_MAX:
        return [f"{len(learned_lines(n.body))} Learned lines, at most {LEARNED_MAX}; the rest belongs in a decision note"]
    if kind not in BUDGET:
        return []
    problems = []
    if not h1(n.body):
        problems.append("no title heading")
    units = reading_units(outside_folds(n.body))
    if units > BUDGET[kind] * TOLERANCE:
        problems.append(f"{units:,} words, budget {BUDGET[kind]:,}" + (" (folded callouts not counted)" if FOLD_RX.search(n.body) else ""))
    lines = len(n.body.splitlines()) or 1
    code = code_lines(n.body)
    if code > max(12, lines // 4):
        problems.append(f"{code} of {lines} lines are code")
    problems += mermaid_problems(n.body)
    machine = len(MACHINE.findall(re.sub(r"```.*?```", "", n.body, flags=re.S)))
    if machine > 2:
        problems.append(f"{machine} machine paths or raw records")
    return problems


def tidy_title(body):
    """The first heading is a title: sentence case, and a status run after it (counts, ticks, wide spacing) moves to
    an italic line beneath, where it reads as a subtitle."""
    m = re.search(r"^#[ \t]+(.+?)[ \t]*$", body, re.M)
    if not m:
        return body
    title, rest = m.group(1), ""
    parts = re.split(r"\s{3,}", title, maxsplit=1)
    if len(parts) == 2:
        title, rest = parts[0].strip(), parts[1].strip()
    line = f"# {sentence(title)}" + (f"\n\n*{rest}*" if rest else "")
    return body[:m.start()] + line + body[m.end():]


def with_warning(body, problems):
    """The warning sits under the note's title, where a reader starts."""
    warn = f"> [!warning] Not yet fit to read: {'; '.join(problems)}. ela owes a shorter version.\n"
    m = re.search(r"^#[ \t]+.*$", body, re.M)
    return body[:m.end()] + "\n\n" + warn + body[m.end():] if m else warn + "\n" + body


def standing_constraints(s, env):
    """`ela promote constraints --json`, or None when it cannot be read. No file is no constraints and needs no read;
    a read stands for CONSTRAINTS_FRESH, or until the file changes, and a failed read falls back to the last one."""
    path = os.path.join(s.get("elak") or "", "blueprint", "constraints.yaml")
    if not os.path.isfile(path):
        return {"exists": False, "active": [], "expired": [], "gaps": [], "counts": {"active": 0, "expired": 0, "over": 0}}
    cache = os.path.join(s.get("runtime") or "/tmp", "vault-constraints.json")
    mtime = os.path.getmtime(path)
    try:
        c = json.load(open(cache))
    except (OSError, ValueError):
        c = {}
    if c.get("mtime") == mtime and datetime.datetime.now().timestamp() - c.get("at", 0) < CONSTRAINTS_FRESH:
        return c.get("data")
    cmd = ["python3", PROMOTE] + (["--env-file", env] if env else []) + ["--quiet", "constraints", "--json"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        data = json.loads(r.stdout) if r.returncode in (0, 3) else None   # 3: a pin is over, which is the news
    except (OSError, ValueError, subprocess.TimeoutExpired):
        data = None
    if data is None:
        return c.get("data")
    try:
        atomic_write(cache, json.dumps({"at": datetime.datetime.now().timestamp(), "mtime": mtime, "data": data}))
    except OSError:
        pass
    return data


def constraints_note(data, today):
    """The standing constraints as one living page: each with its pins read on their lanes, until and lift_when, and
    the note it came from; an expired one for the seven days promote keeps it."""
    L = ["# Standing constraints", ""]
    if data is None:
        L += ["> [!warning] The constraints could not be read; `ela promote constraints` says why.", ""]
        return Note("constraints.md", "Standing constraints", "\n".join(L), {"type": "constraints", "date": today.isoformat()})
    counts = data.get("counts") or {}
    if not data.get("exists"):
        L += ["No standing constraint has been confirmed yet. One is written when you confirm a note that proposes it.", ""]
    elif data.get("error"):
        L += [f"> [!warning] The constraints file is {data['error']}; nothing below is checked.", ""]
    else:
        bits = [f"{counts.get('active', 0)} active", f"{counts.get('over', 0)} over" if counts.get("over") else "",
                f"{counts.get('expired', 0)} expired" if counts.get("expired") else "", f"read {data.get('today') or today.isoformat()}"]
        L += ["*" + " · ".join(b for b in bits if b) + "*", ""]

    def entry(c, expired):
        L.append(f"{'###' if expired else '##'} {c.get('says') or c.get('id')}")
        L.append("")
        meta = [c.get("id"), f"ruled {c['ruled']}" if c.get("ruled") else ""]
        if expired:
            meta.append(f"**expired** {c.get('days_since_expiry')} day(s) ago ({c.get('until')}), no longer enforced")
        else:
            meta.append(f"until {c['until']}" + (f" ({c['days_left']} days)" if c.get("days_left") is not None else "")
                        if c.get("until") else "no end date")
        src = c.get("source") or ""
        meta.append(f"from [[{src[:-3]}|its note]]" if src.endswith(".md") else (f"from {src}" if src else ""))
        L.append("*" + " · ".join(m for m in meta if m) + "*")
        L.append("")
        if c.get("pins"):
            L.extend(["| service | lane | at most | runs now | state |", "|---|---|---|---|---|"])
            for p in c["pins"]:
                st = p.get("state") or "unknown"
                L.append(f"| {p.get('service')} | {p.get('lane')} | {p.get('max')} | {p.get('version') or '—'} | "
                         f"{'**over**' if st == 'over' else st} |")
            L.append("")
        for ck in c.get("checks") or []:
            L.append(f"- by hand on {', '.join(ck.get('lanes') or [])}: {ck.get('what')}")
        if c.get("checks"):
            L.append("")
        if c.get("lift_when"):
            L.extend([f"Lifts when: {c['lift_when']}", ""])

    for c in data.get("active") or []:
        entry(c, False)
    if data.get("expired"):
        L += ["## Expired", "", "*Ended within the last seven days: renew it, or let it lapse.*", ""]
        for c in data["expired"]:
            entry(c, True)
    gaps = data.get("gaps") or []
    if gaps:
        L += ["> [!warning]- Not read: " + str(len(gaps))] + [f"> - {g.get('host', '')} {g.get('detail', '')}".rstrip() for g in gaps] + [""]
    n = Note("constraints.md", "Standing constraints", "\n".join(L), {"type": "constraints", "date": today.isoformat()})
    n.counts = {k: counts.get(k, 0) for k in ("active", "expired", "over")}
    return n



# ── a project's page: the desk's head, the sync's tail ────────────────────────────────────────────────
# projects/<key>/<key>.md. Above the first of TAIL_HEADS the desk's settled facts (goal, dates, parties, what is known,
# the next step), kept as written. From there, written on every sync: what waits on his word (the project's notes in
# to-read and in-progress), its notes by folder, its keys and threads, their Afterwards (the archive's watch, pointed
# at the page too), and the days to the deadline with the step. Reasons: elak
# blueprint/decisions/2026-11-04-projects-are-bounded-work-with-one-page-each.md.
STEP_DATE = re.compile(r"(?<![\d-])(\d{4}-\d{2}-\d{2}|\d{2}-\d{2})(?![\d-])")
PROJECT_FOLDERS = ("in this folder", TO_READ, IN_PROGRESS, PARKED, READINGS, ARCHIVE)   # the Notes section's order


def project_pages(vault):
    """{key: text} for every project page projects/<key>/<key>.md, by key."""
    out, d = {}, os.path.join(vault, PROJECTS)
    for key in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        p = os.path.join(d, key, key + ".md")
        if key.startswith(".") or not os.path.isfile(p):
            continue
        try:
            out[key] = open(p, encoding="utf-8").read()
        except OSError:
            continue
    return out


def project_head(body):
    """(head, afterwards) of a project page's body: the desk's text above the first tail heading, and the `- ` rows of
    its Afterwards section wherever it sits (the afterwards pass appends below the tail)."""
    m = re.search(r"^" + re.escape(AFTERWARDS_HEAD) + r"[ \t]*\n(.*?)(?=^#{1,2}[ \t]|\Z)", body, re.M | re.S)
    rows = [l for l in (m.group(1) if m else "").splitlines() if l.startswith("- ")]
    cut = TAIL_HEAD_RX.search(body)
    head = body[:cut.start()] if cut else body
    return head.rstrip("\n") + "\n", rows


def step_date(text, today):
    """The date a step names: YYYY-MM-DD, or MM-DD read in the year that puts it within half a year of today; None
    without one."""
    m = STEP_DATE.search(text or "")
    if not m:
        return None
    try:
        if len(m.group(1)) == 10:
            return datetime.date.fromisoformat(m.group(1))
        d = datetime.date(today.year, int(m.group(1)[:2]), int(m.group(1)[3:]))
    except ValueError:
        return None
    if (d - today).days > 183:
        d = d.replace(year=today.year - 1)
    elif (today - d).days > 183:
        d = d.replace(year=today.year + 1)
    return d


def project_facts(key, text, today):
    """A project page as data: its title, deadline and the days to it, its step (the `next-step` property, else the
    first unticked box in the head) with its date and whether it is overdue (its date passed; with no date, the
    deadline passed), its keys, the threads it watches (`posted` and `channels`), the head and the Afterwards rows."""
    fl, body = split_front(text)
    props = props_of(fl)
    head, after = project_head(body)
    dm = re.search(r"\d{4}-\d{2}-\d{2}", props.get("deadline") or "")
    deadline = datetime.date.fromisoformat(dm.group(0)) if dm else None
    box = re.search(r"^[ \t]*[-*][ \t]+\[ \][ \t]+(\S.*?)[ \t]*$", head, re.M)
    step = (props.get("next-step") or "").strip() or (box.group(1).strip() if box else None)
    due = step_date(step, today) if step else None
    overdue = bool(step) and ((due < today) if due else (deadline is not None and deadline < today))
    keys = list(dict.fromkeys(k for k in KEY_RX.findall(props.get("keys") or "") if not NOT_KEYS.match(k)))
    links = list(dict.fromkeys(l.rstrip(".") for l in PERMALINK.findall((props.get("posted") or "") + " " + (props.get("channels") or ""))))
    return {"key": key, "path": f"{PROJECTS}/{key}/{key}.md", "title": props.get("title") or h1(body) or key, "deadline": deadline,
            "days": (deadline - today).days if deadline else None, "step": step, "step_due": due, "overdue": overdue,
            "keys": keys, "links": links, "props": props, "front": fl, "head": head, "afterwards": after}


def project_rows(vault, key, notes=()):
    """The notes of project `key`: every note carrying `project: <key>`, the vault on disk overlaid with the notes this
    sync writes, plus every note inside projects/<key>/ but the page: [{path, title, type, date, status, next, inside}],
    newest first."""
    page, folder, rows = f"{PROJECTS}/{key}/{key}.md", f"{PROJECTS}/{key}/", {}
    for top_, dirs, fs in os.walk(vault):
        dirs[:] = [d for d in dirs if not d.startswith(".") and os.path.relpath(os.path.join(top_, d), vault).replace(os.sep, "/")
                   not in (ATTACH,) + RETIRED]
        for f in fs:
            rel = os.path.relpath(os.path.join(top_, f), vault).replace(os.sep, "/")
            if not f.endswith(".md") or rel == page:
                continue
            inside = rel.startswith(folder)
            try:
                fl, body = split_front(open(os.path.join(top_, f), encoding="utf-8").read())
            except OSError:
                continue
            props = props_of(fl)
            if props.get("project") != key and not inside:
                continue
            rows[rel] = {"path": rel, "title": props.get("title") or h1(body) or f[:-3], "type": props.get("type"), "date": props.get("date"),
                         "status": props.get("status"), "next": props.get("next"), "inside": inside}
    for n in notes:
        if n.props.get("project") != key or n.path == page:
            continue
        disk = rows.get(n.path) or {}
        rows[n.path] = {"path": n.path, "title": n.title, "type": n.props.get("type"), "date": n.props.get("date"),
                        "status": note_status(n) or disk.get("status"), "next": disk.get("next") or n.props.get(NEXT), "inside": n.path.startswith(folder)}
    return sorted(rows.values(), key=lambda r: (r["date"] or "", r["path"]), reverse=True)


def days_words(days):
    """`102 days left`, `due today`, `3 days past`."""
    if days is None:
        return "no deadline"
    if days == 0:
        return "due today"
    return f"{days} day{'s' if days != 1 else ''} left" if days > 0 else f"{-days} day{'s' if days != -1 else ''} past"


def project_tail(facts, rows, today, jira_base=""):
    """The sync's half of a project page: TAIL_HEADS in their order."""
    d = facts["deadline"]
    L = [f"## {ASKS_HEAD}", ""]
    asks = [r for r in rows if top(r["path"]) in (TO_READ, IN_PROGRESS)]
    for r in asks:
        bits = [r["type"], r["status"], f"next: {r['next']}" if r.get("next") else None]
        L.append(f"- [[{r['path'][:-3]}|{r['title']}]] · " + " · ".join(b for b in bits if b))
    L += ["Nothing waits on you for this project."] if not asks else []
    L += ["", "## Notes", ""]
    if not rows:
        L.append(f"No note names this project yet: `project: {facts['key']}` in a note's properties, or a note in its folder.")
    groups = {}
    for r in rows:
        groups.setdefault("in this folder" if r["inside"] else top(r["path"]), []).append(r)
    for g in list(PROJECT_FOLDERS) + sorted(k for k in groups if k not in PROJECT_FOLDERS):
        if g not in groups:
            continue
        L.append(f"**{g}**" + ("" if g == "in this folder" else "/"))
        for r in groups[g]:
            bits = [r["type"], r["date"], r["status"] if g not in (READINGS, "in this folder") else None]
            L.append(f"- [[{r['path'][:-3]}|{r['title']}]] · " + " · ".join(b for b in bits if b))
        L.append("")
    keys = [f"[{k}]({jira_base}/browse/{k})" if jira_base else k for k in facts["keys"]]
    links = facts["links"]
    wp = facts["props"]
    watch = wp.get("watch") if "watch" in wp else ((d + datetime.timedelta(days=PROJECT_WATCH_DAYS)).isoformat() if d else None)
    bits = [f"keys {', '.join(keys)}" if keys else "no keys yet (`ela project keys <key> --add MH-…`)",
            f"{len(links)} thread{'s' if len(links) != 1 else ''}" if links else "no threads",
            f"watched until {watch}" if watch else "not watched"]
    L += [f"## {TAIL_HEADS[2]}", "", f"*{' · '.join(bits)}*"] + [f"- [thread]({l})" for l in links] + [""]
    L += [AFTERWARDS_HEAD, ""] + (facts["afterwards"] or ["*Nothing yet: the 13:00, 17:30 and 19:00 passes read its keys and threads.*"]) + [""]
    L += [f"## {TAIL_HEADS[4]}", ""]
    L.append(f"*{d.isoformat()} · {days_words(facts['days'])}" if d else "*No deadline: write `deadline: YYYY-MM-DD` in the properties")
    if facts["step"]:
        L[-1] += f" · next step: {facts['step']}" + (" (**overdue**)" if facts["overdue"] else "")
    L[-1] += "*"
    L.append("")
    return "\n".join(L)


def project_note(key, text, vault, notes, today, jira_base=""):
    """The page as the sync writes it: its properties settled (type project, watch defaulting to the deadline plus 14
    days, every other line kept), the head as written, the tail generated. The Note carries front_text, head and tail
    apart, so the head is never linked, unwrapped or retitled."""
    facts = project_facts(key, text, today)
    props = facts["props"]
    want = {"title": facts["title"], "type": "project", "date": props.get("date") or today.isoformat(), "deadline": props.get("deadline"),
            "next-step": props.get("next-step"), "source": "vault", "posted": props.get("posted"), "channels": props.get("channels"),
            "keys": props.get("keys"), "watch": props.get("watch") if "watch" in props else
            ((facts["deadline"] + datetime.timedelta(days=PROJECT_WATCH_DAYS)).isoformat() if facts["deadline"] else None),
            "watched": props.get("watched"), "last": props.get("last")}
    if "watch" in props and not props.get("watch"):
        want["watch"] = ""                                 # cleared by him: stays cleared, which stops the watch
    fm = front([], {k: v for k, v in want.items() if v})
    if "watch" in want and want["watch"] == "":
        fm = fm.replace("\n---\n\n", '\nwatch: ""\n---\n\n', 1)
    keep = [l for l in facts["front"] if re.match(r"^([\w-]+):", l) and re.match(r"^([\w-]+):", l).group(1) not in tuple(want) + ("aliases",)]
    if keep:
        fm = fm[:-len("---\n\n")] + "\n".join(keep) + "\n---\n\n"
    rows = project_rows(vault, key, notes)
    tail = project_tail(facts, rows, today, jira_base)
    n = Note(facts["path"], facts["title"], facts["head"] + "\n" + tail, {"type": "project", "date": want["date"], "deadline": want["deadline"]})
    n.front_text, n.head, n.tail, n.facts, n.rows = fm, facts["head"] + "\n", tail, facts, rows
    return n


def infer_projects(vault, projects, notes=(), natives=(), dry_run=False):
    """`project: <key>` on a note that carries none and whose keys are among one project's keys (a verification's
    ticket counts as its key): set on a note this sync writes before it is written, written into the front matter of
    a note on disk, and nothing else of it. → [(path, key)]."""
    by_key = {k: key for key, ks in projects.items() for k in ks}
    def guess(keys):
        hits = {by_key[k] for k in keys if k in by_key}
        return hits.pop() if len(hits) == 1 else None
    out, done = [], set()
    for n in notes:
        done.add(n.path)
        if n.props.get("project") or PROJECT_PAGE.match(n.path):
            continue
        keys = set(KEY_RX.findall(props_of(n.front_lines).get("keys") or ""))
        m = re.search(r"-verify-([a-z][a-z0-9]+-\d+)", n.path)
        if m:
            keys.add(m.group(1).upper())
        key = guess(keys)
        if key:
            n.props["project"] = key
            out.append((n.path, key))
    native_by_path = {n.path: n for n in natives}
    for top_, dirs, fs in os.walk(vault):
        dirs[:] = [d for d in dirs if not d.startswith(".") and os.path.relpath(os.path.join(top_, d), vault).replace(os.sep, "/")
                   not in (ATTACH,) + RETIRED]
        for f in sorted(fs):
            rel = os.path.relpath(os.path.join(top_, f), vault).replace(os.sep, "/")
            if not f.endswith(".md") or rel in done or PROJECT_PAGE.match(rel):
                continue
            try:
                text = open(os.path.join(top_, f), encoding="utf-8").read()
            except OSError:
                continue
            fl, _ = split_front(text)
            props = props_of(fl)
            if not fl or props.get("project") or not props.get("keys"):
                continue
            key = guess(set(KEY_RX.findall(props["keys"])))
            if not key:
                continue
            out.append((rel, key))
            if rel in native_by_path:
                native_by_path[rel].props["project"] = key
            if not dry_run:
                atomic_write(os.path.join(top_, f), set_front(text, project=key))
    return out


# ── home ──────────────────────────────────────────────────────────────────────────────────────────────

def link(n):
    return f"[[{n.path[:-3]}|{n.title}]]"


def home(today, now, notes, desk=None):
    """Home, five lines above a divider: what ela did since he last looked (every applied action, a tier-1 or tier-2 dry run), what leaves at 10:00 unless he
    ticks (tier 2), what only he can do (at most three tier-3 boxes), the MediaHub program's next step, and one line
    on ela. Below the divider, links. `desk`: {actions: today's and the week's, since: when he last looked, program,
    ela, hold: the tier-2 hold standing today} (vault in-progress/2026-10-29-ela-three-loops-review.md, proposal 1).
    Under a hold the tier-2 block has no boxes: nothing leaves, each action shows what it would have done."""
    desk = desk or {}
    def newest(kind):
        return sorted((n for n in notes if n.props.get("type") == "day" and n.props.get("kind") == kind),
                      key=lambda n: n.props["date"], reverse=True)
    brief = next(iter(newest("brief")), None)
    changes = next(iter(newest("changes")), None)
    iso = today.isoformat()
    today_acts = [a for a in desk.get("actions") or [] if a.get("day") == iso]
    since = desk.get("since")
    def new(at):
        return bool(at) and (at > since if since else at[:10] == iso)
    # every applied action, whatever its tier: an `apply N` he ticked or said to the desk is done work too (the vault review
    # of 2026-11-04: apply 2 applied 10:56 on his tick read as "nothing"); a dry run only for tier 1 and 2 and a send box
    done = sorted((a for a in desk.get("actions") or [] if new(a.get("applied"))
                   or ((a.get("tier") in (1, 2) or a.get("send_box")) and new((a.get("dry_run") or {}).get("at")))),
                  key=lambda a: a.get("applied") or a["dry_run"]["at"])
    soon = [a for a in today_acts if a.get("tier") == 2 and not (a.get("applied") or a.get("vetoed") or a.get("failed"))]
    # tier 3 with a send box (the QA day post): it leaves only on his tick, read by the runner's 09:30 and 10:00 passes
    send = [a for a in today_acts if a.get("send_box") and not (a.get("applied") or a.get("vetoed"))]
    mine = [a for a in today_acts if a.get("tier", 3) == 3 and not (a.get("send_box") or a.get("applied") or a.get("by_owner"))]
    hold = desk.get("hold")
    page = f"[[{brief.path[:-3]}|the morning page]]" if brief else "the morning page"
    L = [f"# {today:%a %Y-%m-%d}", ""]
    L += ["**Done since you last looked:**" + ("" if done else " nothing.")]
    L += [f"- {done_line(a)}" for a in done] + [""]
    for at in sorted({"10:00"} | {a.get("send_at") or "10:00" for a in soon}):   # one heading per send time; 10:00 always
        due = [a for a in soon if (a.get("send_at") or "10:00") == at]
        L += [(f"**At {at}, held until {hold['until']} (dry run):**" if hold else f"**At {at} unless you tick:**") + ("" if due else " nothing.")]
        L += [f"- {a['dry_run']['line']}" if (a.get("dry_run") or {}).get("line")
              else f"- {a['n']} — {a.get('text', '')}" if hold else f"- [ ] don't {a['n']} — {a.get('text', '')}" for a in due] + [""]
    if send:
        L += ["**Send when you tick:**"] + [f"- {send_line(a, desk.get('lists'))}" for a in send] + [""]
    L += ["**Only you:**" + ("" if mine else " nothing today.")]
    L += [f"- [ ] apply {a['n']} — {a.get('text', '')}" for a in mine[:3]]
    L += [f"*+{len(mine) - 3} more on {page}*"] if len(mine) > 3 else []
    L += [""]
    projects = [n.facts for n in notes if n.props.get("type") == "project" and getattr(n, "facts", None)]
    urgent = project_step(projects)
    if urgent:                                             # a project's step takes the fourth line only when it is near and late
        L += [f"**{urgent['key']}:** {urgent['step']} · {days_words(urgent['days'])} to {urgent['deadline'].isoformat()}, the step is overdue "
              f"→ [[{urgent['path'][:-3]}|the project]]", ""]
    else:
        L += [f"**MediaHub:** {desk['program']} → [[{PROGRAM[:-3]}|the program]]" if desk.get("program")
              else f"**MediaHub:** no next step in [[{PROGRAM[:-3]}|the program]].", ""]
    # labelled "From ela", never "ela:": a line starting `ela:` is his instruction to the watcher
    L += [f"**From ela:** {desk['ela']} → [[{OVERVIEW[:-3]}|the ela page]]" if desk.get("ela") else f"**From ela:** [[{OVERVIEW[:-3]}|the ela page]].", ""]
    L += ["---", ""]
    waiting = [n for n in notes if note_status(n) in ("proposed", "blocked", "built") or n.props.get("result") == "fail"]
    links = [f"[[{brief.path[:-3]}|brief]]" if brief else None,
             "[[lanes|lanes]]" if any(n.props.get("type") == "lanes" for n in notes) else None,
             "[[board|board]]" if any(n.props.get("type") == "board" for n in notes) else None,
             "[[recent|recent]]" if any(n.props.get("type") == "recent" for n in notes) else None,
             f"[[{changes.path[:-3]}|changes]]" if changes else None,
             f"[[{PROGRAM[:-3]}|program]]",
             ("projects: " + " · ".join(f"[[{f['path'][:-3]}|{f['key']}]] {days_words(f['days'])}" for f in projects)) if projects else None,
             f"[[{OVERVIEW[:-3]}|ela]]",
             f"[[{ELA}/all-notes.base|all notes]]" + (f" ({len(waiting)} wait for your word)" if waiting else ""),
             f"[[{ELA}/all-notes.base#Cases|cases]]",
             f"[[{ELA}/all-notes.base#Archive|archive]]"]
    cons = next((n for n in notes if n.props.get("type") == "constraints"), None)
    held = getattr(cons, "counts", None) or {}
    if held.get("active") or held.get("expired"):
        links.append(f"[[{cons.path[:-3]}|{held['active']} standing constraint{'s' if held['active'] != 1 else ''}]] · {held['over']} over"
                     + (f" · {held['expired']} expired" if held["expired"] else ""))
    # the One Thing page: the rows not yet on the team's sheet, one copy block (skills/onething; the store under reports)
    one = next((n for n in notes if n.props.get("type") == "one-thing"), None)
    if one:
        left = getattr(one, "count", 0) or 0
        links.append("[[one-thing|One Thing]]" + (f" ({left} to paste)" if left else ""))
    L += [" · ".join(x for x in links if x), ""]
    owed_since = (today - datetime.timedelta(days=HELD_LISTED_DAYS)).isoformat()
    # a past day page is the record of what ela told him that morning; it is never rewritten, so it is owed nothing
    owed = [n for n in notes if n.held and (n.props.get("date") or iso) >= owed_since
            and not (n.props.get("type") == "day" and (n.props.get("date") or iso) < iso)]
    if owed:
        L += ["> [!warning]- ela owes a shorter version of " + str(len(owed))] + [f"> - {link(n)}: {'; '.join(n.held)}" for n in owed] + [""]
    return "\n".join(L)


def project_step(facts):
    """The project whose step Home names instead of the program's: its deadline nearer than PROJECT_SOON_DAYS and its
    step overdue; the nearest deadline when several; None otherwise."""
    due = [f for f in facts if f.get("days") is not None and f["days"] < PROJECT_SOON_DAYS and f.get("overdue") and f.get("step")]
    return min(due, key=lambda f: f["days"]) if due else None


def action_what(a):
    """What an action does, in a few words: its rule's name and lane for a day post, else its own line."""
    scope = a.get("scope") or []
    where = f" on {scope[1]}" if len(scope) > 1 and scope[0] in ("--lane", "--line") else ""
    return {"qa-today": f"QA today{where}", "dev-today": f"Dev today{where}"}.get(a.get("rule")) \
        or re.sub(r"^at \d\d:\d\d:\s*", "", str(a.get("text") or ""))


def trigger(a):
    """What made an applied action leave, from the runner's `by` stamp: his tick, his word in Slack, his word to the desk
    session, a closed rule, the test harness; a stamp without one says so, never "on your tick" (vault
    to-read/2026-11-02-ela-and-vault-workflow-review.md, fix 5). The vocabulary is ela-runner lib/trigger.py's."""
    by = str(a.get("by") or "")
    if by == "tick":
        return "on your tick"
    if by == "slack-word":
        return "on your word in Slack"
    if by == "desk-word":
        return "on your word to the desk"
    if by.startswith("rule:") and by[5:]:
        return f"under rule {by[5:]}"
    if by == "harness":
        return "by the test harness"
    return "(trigger not recorded)"


def applied_words(a, verb):
    """`sent 08:59 on your tick`, `done 10:00 under rule label`, or `applied 08:59 (trigger not recorded)`."""
    at = str(a.get("applied") or "")[11:16]
    return f"{verb} {at} {trigger(a)}" if a.get("by") else f"applied {at} {trigger(a)}"


def ticked_at(a):
    """When the runner found his send box ticked: `send_ticked` is {at}, or a bare time as `vetoed` is."""
    t = a.get("send_ticked")
    return str((t.get("at") if isinstance(t, dict) else t) or "")


def send_line(a, lists=None):
    """A send-box action as Home lists it, in the box form the runner reads (`send N`): open, with the list it would
    send, its channel and "untouched: not sent"; ticked with the time the runner saw it; or not sent (an error, or
    no tick by the last pass), without a box."""
    what = f"{a['n']} — {action_what(a)} (your ela: lines applied first)"
    if a.get("failed"):
        return f"send {what} · not sent: {str((a['failed'] or {}).get('error') or 'failed')[:80]}"
    if ticked_at(a):
        return f"[x] send {what} · ticked {ticked_at(a)[11:16]}"
    if (a.get("unsent") or {}).get("final"):
        return f"send {what} · not sent: no tick · stays as apply {a['n']}"
    return f"[ ] send {what}{send_tail(a, lists)}"


def done_line(a):
    """One sent or dry-run tier-1/2 action as Home's Done line reads it: what, when, and the post as evidence. A dry run
    keeps the runner's own words, never "sent"."""
    if (a.get("dry_run") or {}).get("line") and not a.get("applied"):
        return a["dry_run"]["line"]
    what = action_what(a)
    slack = a.get("kind") == "slack" or str(a.get("command") or "").startswith("ela slack")
    link = f" · [link]({a['permalink']})" if a.get("permalink") else ""
    return f"{a['n']} — {what} {applied_words(a, 'sent' if slack else 'done')}{link}"


def tier2_hold(reports, date):
    """The owner's hold on tier 2 standing on `date`, from <reports>/runner/hold.json (only `ela-runner hold` writes it):
    {since, until, why} through `until` unless `lifted`, else None."""
    try:
        h = json.load(open(os.path.join(reports or "", "runner", "hold.json"), encoding="utf-8")).get("tier2")
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(h, dict) or h.get("lifted") or str(h.get("until") or "") < date:
        return None
    return h


def slack_posts(reports):
    """{second: permalink} of ela's Slack posts from its write log, for an action sent before the runner kept the link."""
    out = {}
    try:
        for line in open(os.path.join(reports or "", "ela", "writes.jsonl"), encoding="utf-8"):
            try:
                w = json.loads(line)
            except ValueError:
                continue
            if w.get("system") == "slack" and w.get("verb") == "post" and w.get("ok") and w.get("permalink"):
                out[str(w.get("at") or "")[:19]] = w["permalink"]
    except OSError:
        pass
    return out


def week_actions(reports, today, days=7):
    """The drafted actions of the last `days` days, each with its `day`: [action]."""
    out = []
    for i in range(days):
        d = (today - datetime.timedelta(days=i)).isoformat()
        try:
            acts = json.load(open(os.path.join(reports or "", "runner", f"{d}-actions.json"), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out += [dict(a, day=d) for a in acts if isinstance(a, dict) and str(a.get("n", "")).isdigit()]
    posts = slack_posts(reports) if any(a.get("applied") and not a.get("permalink") for a in out) else {}
    for a in out:
        if a.get("applied") and not a.get("permalink") and posts.get(a["applied"][:19]):
            a["permalink"] = posts[a["applied"][:19]]
    return out


def sections(body):
    """A page's `## ` sections in order: [(heading, text including the heading)]; the part before the first is ""."""
    parts = re.split(r"(?m)^(?=## )", body)
    return [((re.match(r"## (.+?)\s*$", p, re.M).group(1) if p.startswith("## ") else ""), p) for p in parts]


def first_line(text):
    """The first item or sentence of a section, as one line: its list item, or its first paragraph's first sentence."""
    for l in text.splitlines()[1:]:
        l = l.strip()
        if re.match(r"^[-*]\s+\[x\]", l, re.I) or not l or l.startswith(("|", ">", "#", "*")) and not re.match(r"^\*\*", l):
            continue
        l = re.sub(r"^(?:[-*]\s+(?:\[ \]\s+)?|\d+[.)]\s+)", "", l)
        return l if len(l) <= 240 else l[:240].rsplit(" ", 1)[0] + " …"
    return None


def program_next(vault):
    """The first step under "Next" in the MediaHub program note, or None."""
    try:
        body = split_front(open(os.path.join(vault, PROGRAM), encoding="utf-8").read())[1]
    except OSError:
        return None
    return next((first_line(t) for h, t in sections(body) if h == "Next"), None)


def ela_line(vault):
    """Home's line on ela: the first decision waiting on the ela page, else what changed for MediaHub this week."""
    try:
        body = split_front(open(os.path.join(vault, OVERVIEW), encoding="utf-8").read())[1]
    except OSError:
        return None
    got = dict(sections(body))
    for h in ("Waiting for your word", "What changed for MediaHub this week"):
        line = first_line(got.get(h) or "")
        if line and line != "Nothing yet.":
            return line
    return None


# ── the ela page: generated where it can be, three sections his ─────────────────────────────────────────
OVERVIEW, PROGRAM = "ela/overview.md", "mh/engineering-management.md"
HAND_SECTIONS = ("Waiting for your word", "What changed for MediaHub this week", "Known limits")
GENERATED_SECTIONS = ("Measures", "The parts", "The schedule", "This week in ela", "Closed by ela this week")


def run_out(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def timer_next(timer):
    """The next run of an active timer that list-timers shows none for: while its service runs (the tickets job writes
    this page at its own end) systemd computes no next elapse. Read from systemd's own calendar, every OnCalendar line,
    the earliest; None for a failed or inactive timer."""
    show = run_out(["systemctl", "--user", "show", timer, "-p", "ActiveState", "-p", "TimersCalendar"]) or ""
    if "ActiveState=active" not in show:
        return None
    exprs = re.findall(r"OnCalendar=(.+?) ;", show)
    out = run_out(["systemd-analyze", "calendar", "--iterations=1"] + exprs) if exprs else None
    runs = re.findall(r"Next elapse: \w{3} (\d{4}-\d{2}-\d{2} \d{2}:\d{2})", out or "")
    return min(runs) if runs else None


def measures(s, vault, today):
    """One line per track, and the three promises, from local records only (the sync runs every minute)."""
    since = (today - datetime.timedelta(days=7)).isoformat()
    L = []
    starts, ends = set(), set()
    try:
        for line in open(os.path.join(s.get("runtime") or "", "sessions.jsonl"), encoding="utf-8"):
            e = json.loads(line)
            if str(e.get("at") or "")[:10] >= since:
                (starts if e.get("event") == "start" else ends).add(e.get("id"))
    except (OSError, ValueError):
        pass
    L.append(f"- **Track 1 · sessions:** {len(starts)} opened in seven days, {len(starts & ends)} closed clean"
             + (f", {len(starts - ends)} still open." if starts - ends else "."))
    pages = wrong = 0
    for f in glob.glob(os.path.join(s.get("reports") or "", "review", "*-reader.json")):
        if os.path.basename(f)[:10] >= since:
            try:
                rows = json.load(open(f, encoding="utf-8"))
            except (OSError, ValueError):
                continue
            pages += 1
            wrong += sum(1 for r in rows if isinstance(r, dict) and r.get("kind") == "wrong")
    L.append(f"- **Track 2 · the system:** {wrong} wrong reading{'s' if wrong != 1 else ''} on {pages} morning page{'s' if pages != 1 else ''} "
             "the reader read in seven days" + (f" ({wrong / pages:.1f} a page)." if pages else "."))
    late = total = 0
    try:
        body = split_front(open(os.path.join(vault, PROGRAM), encoding="utf-8").read())[1]
        plan_ = dict(sections(body)).get("Plan") or ""
        for row in plan_.splitlines():
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if len(cells) >= 6 and re.fullmatch(r"\d+", cells[0]):
                total += 1
                by = re.match(r"(\d{2})-(\d{2})", cells[3])
                if by and cells[-1].lower() not in ("done", "closed") and f"{today.year}-{by.group(1)}-{by.group(2)}" < today.isoformat():
                    late += 1
    except OSError:
        pass
    L.append(f"- **Track 3 · MediaHub:** {total - late} of {total} program items on time." if total else "- **Track 3 · MediaHub:** no program plan yet.")
    briefs = sorted(glob.glob(os.path.join(s.get("runtime") or "", "runner", "*-brief.json")))
    try:
        lanes = json.load(open(briefs[-1], encoding="utf-8"))["lanes"]
        slow = sum(1 for r in lanes["breakdown"]["rows"] if (r.get("age_days") or 0) >= 1)
        L.append(f"- **The three promises** ({os.path.basename(briefs[-1])[:10]}): {slow} complex ticket{'s' if slow != 1 else ''} "
                 f"not broken down after a day · {lanes['triage']['overdue']} unassigned past 4 hours · "
                 f"{lanes['cadence']['count']} In Progress not updated in 24 hours.")
    except (IndexError, OSError, ValueError, KeyError, TypeError):
        L.append("- **The three promises:** no morning read yet.")
    return L


def overview_note(s, vault, today):
    """The ela page: the parts, the schedule, the measures and the week's commits written from ela day, the timers and
    git; every other section (Waiting for your word, What changed for MediaHub this week, Known limits, and any the
    desk added) kept verbatim from the page on disk. None when the vault has no ela page yet."""
    try:
        fl, body = split_front(open(os.path.join(vault, OVERVIEW), encoding="utf-8").read())
    except OSError:
        return None
    root = os.path.dirname(os.path.dirname(HERE))
    hand = [(h, t.rstrip() + "\n") for h, t in sections(body) if h and h not in GENERATED_SECTIONS]
    for h in HAND_SECTIONS:
        if h not in [x for x, _ in hand]:
            hand.append((h, f"## {h}\n\nNothing yet.\n"))
    # a skill is a directory under skills/ with a SKILL.md or its script, the count the manual check uses
    dirs = [d for d in glob.glob(os.path.join(root, "skills", "*")) if os.path.isfile(os.path.join(d, "SKILL.md"))
            or os.path.isfile(os.path.join(d, os.path.basename(d) + ".py"))]
    guided = sum(1 for d in dirs if os.path.isfile(os.path.join(d, "SKILL.md")))
    skills = f"{len(dirs)} skills ({guided} with a SKILL.md, {len(dirs) - guided} scripts only)"
    L = ["# ela", "", f"*The parts, the schedule, the measures and the week's commits are written by the sync from `ela day`, the timers "
         "and git on each sync; the other sections are the desk's, kept as written.*", "",
         "## Measures", ""] + measures(s, vault, today) + [""]
    L += ["## The parts", "", "| part | what it is |", "|---|---|",
          f"| ela | {skills} and the `ela` verbs, in every Claude session |",
          "| ela-runner | the clock, the vault watcher, the Slack front door, the judge sessions |",
          "| the vault | your desk: Home, the morning page, readings, decisions and plans |",
          "| elak | facts and knowledge, written on your word |",
          "| published | the redacted subset Helm and colleagues read; its service map, for your review: [[ela/service-map\\|service map]] |",
          "| Helm | the builds ledger and the live release views |", ""]
    L += ["## The schedule", ""]
    timers = run_out(["systemctl", "--user", "list-timers", "--all", "--no-legend", "--no-pager"])
    rows = []
    for line in (timers or "").splitlines():
        m = re.search(r"(\S+\.timer)\s+(\S+\.service)?\s*$", line)
        if m and m.group(1).startswith("ela-runner-"):     # the runner's clock; a keepalive would rewrite the page hourly
            nxt = re.match(r"^\w{3} (\d{4}-\d{2}-\d{2} \d{2}:\d{2})", line.strip())
            nxt = nxt.group(1) if nxt else timer_next(m.group(1))
            rows.append(f"| {m.group(1)[:-6]} | {nxt[5:] if nxt else '—'} |")
    L += (["| timer | next run |", "|---|---|"] + rows) if rows else ["The timers could not be read."]
    try:
        sys.path.insert(0, os.path.join(HERE, "..", "brief"))
        import brief as B
        day = B.day_plan(today)
        L += ["", f"Today: {'a working day' if day['working_day'] else 'not a working day'}"
              + (f", at your desk {day.get('at_desk')}, DMs {'–'.join(day.get('dm_hours') or [])}" if day.get("at_desk") else "")
              + "".join(f"; {m['section']}" for m in day["meetings"]) + "."]
    except Exception as e:                                  # the day file is elak's; a bad one costs this line only
        L += ["", f"Today: `ela day` could not be read ({type(e).__name__})."]
    L += ["", "## This week in ela", ""]
    for name, repo in (("the ela repo", root), ("ela-runner", os.path.join(s.get("projects") or "", "ela-runner"))):
        log = run_out(["git", "-C", repo, "log", "--since=7.days", "--no-merges", "--format=%h %s"])
        commits = (log or "").splitlines()
        L.append(f"- **{name}:** {len(commits)} commit{'s' if len(commits) != 1 else ''} in seven days" if log is not None
                 else f"- **{name}:** not read")
        L += [f"  - {c}" for c in commits[:5]]
    L.append("")
    L += ["## Closed by ela this week", ""] + closed_by_ela(s, today) + [""]
    text = "\n".join(L) + "\n" + "\n".join(t for _, t in hand)
    return Note(OVERVIEW, "ela", text, {"type": "guide", "date": today.isoformat()})


def closed_by_ela(s, today, days=7):
    """The built notes the runner archived after three working days with no ruling (<reports>/ela/closed-by-ela.jsonl),
    the last week's, each a link to its archived note, which offers `reopen`."""
    path = os.path.join(s.get("reports") or "", "ela", "closed-by-ela.jsonl")
    since = (today - datetime.timedelta(days=days)).isoformat()
    rows = []
    try:
        for line in open(path, encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if (r.get("at") or "")[:10] >= since and r.get("note"):
                rows.append(f"- [[{r['note'][:-3] if r['note'].endswith('.md') else r['note']}|{r.get('title') or r['note']}]] — "
                            f"closed by ela {(r.get('at') or '')[:10]}, built {r.get('built') or '?'}; reopen if wrong")
    except OSError:
        pass
    return rows or ["Nothing: every built note had your ruling."]


def home_open(vault):
    """Whether Home is open in a tab, read from Obsidian's own workspace file; False when it cannot be read."""
    def files(node):
        if node.get("type") == "leaf":
            yield ((node.get("state") or {}).get("state") or {}).get("file")
        for c in node.get("children") or []:
            yield from files(c)
    try:
        return "home.md" in set(files(json.load(open(os.path.join(vault, ".obsidian", "workspace.json"), encoding="utf-8")).get("main") or {}))
    except (OSError, ValueError, AttributeError):
        return False


def note_status(n):
    """A note's status as its property will read: set by ela, or its source's own `status:` line."""
    return n.props.get("status") or next((short_status(re.sub(r"^status:\s*", "", l).strip().strip("'\"")) for l in n.front_lines
                                           if l.startswith("status:")), None)


def meta_line(n):
    """One muted line under a record's or a review's title: what it is, when, its status. Properties are hidden while
    reading."""
    if n.props.get("type") not in ("review", "decision", "plan", "sprint", "report"):
        return n.body
    st = note_status(n)
    bits = [n.props["type"], n.props.get("date"), st]
    line = "*" + " · ".join(b for b in bits if b) + "*"
    m = re.search(r"^#[ \t]+.*$", n.body, re.M)
    return n.body[:m.end()] + "\n\n" + line + n.body[m.end():] if m else n.body


# ── a meeting's note: what he raises there and what it ruled ──────────────────────────────────────────
# One note per meeting, meetings/<key>.md, written in place by `ela meeting`: a send box, To raise (one line an item,
# its detail folded under it) and Ruled by date, newest first. The sync rolls a Ruled date older than 30 days into
# archive/meetings-<key>-<yyyy-mm>.md and lints an item over 140 characters (vault
# in-progress/2026-10-30-review-list-redesign.md).
MEETINGS = "meetings"
MEETING_ITEM_MAX = 140
MEETING_RULED_DAYS = 30
MEETING_RAISE, MEETING_RULED = "To raise", "Ruled"
MEETING_SEND = re.compile(r"^[-*][ \t]+\[([ xX])\][ \t]+send\b")
MEETING_ITEM = re.compile(r"^[-*][ \t]+\[([ xX])\][ \t]+(\S.*?)[ \t]*$")
MEETING_DAY = re.compile(r"^###[ \t]+(\d{4}-\d{2}-\d{2})\b")
MEETING_KEY = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
MEETING_DROP = re.compile(r"^(?:drop|dropped|skip|remove)\b", re.I)       # under an item: take it off, whoever added it
MEETING_ORDER = re.compile(r"^(?:first|on top)$", re.I)                  # under an item: say it first; not a ruling


def visible(line):
    """A line as reading mode shows it: each link by its text."""
    t = re.sub(r"\[\[[^\]|]*\|([^\]]+)\]\]", r"\1", line)
    t = re.sub(r"\[\[([^\]]+)\]\]", r"\1", t)
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)


def meeting_parse(text):
    """A meeting note as data: {front, title, send: {ticked, text} or None, head, items: [{text, ticked, under}], ruled_head,
    ruled: [(date, lines)], others: [(heading, lines)]}. Every line lands somewhere, so a rewrite keeps his words."""
    fl, body = split_front(text or "")
    n = {"front": fl, "title": None, "send": None, "intro": [], "head": [], "items": [], "ruled_head": [], "ruled": [], "others": []}
    sec = None
    for line in body.splitlines():
        h = re.match(r"^##[ \t]+(.+?)[ \t]*$", line)
        if h:
            sec = h.group(1)
            if sec not in (MEETING_RAISE, MEETING_RULED):
                n["others"].append((sec, []))
            continue
        if sec is None:
            t, s = re.match(r"^#[ \t]+(.+?)[ \t]*$", line), MEETING_SEND.match(line)
            if t and not n["title"]:
                n["title"] = t.group(1)
            elif s and not n["send"]:
                n["send"] = {"ticked": s.group(1) != " ", "text": line}
            else:
                n["intro"].append(line)
        elif sec == MEETING_RAISE:
            m = MEETING_ITEM.match(line)
            if m:
                n["items"].append({"text": m.group(2), "ticked": m.group(1) != " ", "under": []})
            elif n["items"] and line.strip():
                n["items"][-1]["under"].append(line)
            elif not n["items"]:
                n["head"].append(line)
        elif sec == MEETING_RULED:
            d = MEETING_DAY.match(line)
            if d:
                n["ruled"].append((d.group(1), []))
            elif n["ruled"]:
                n["ruled"][-1][1].append(line)
            else:
                n["ruled_head"].append(line)
        else:
            n["others"][-1][1].append(line)
    return n


def meeting_render(n, title, send_text, today):
    """The note written back: its properties, the title, the send box, To raise, Ruled by date (newest first), then
    any section he added, kept unchanged."""
    keep = [l for l in n["front"] if not re.match(r"^(title|aliases|type|date|source):", l)]
    props = front([], {"title": title, "type": "meeting", "date": today.isoformat(), "source": "vault"})
    if keep:
        props = props[:-len("---\n\n")] + "\n".join(keep) + "\n---\n\n"
    box = "x" if n["send"] and n["send"]["ticked"] else " "
    intro = "\n".join(n["intro"]).strip("\n")
    out = [f"# {title}", ""] + ([intro, ""] if intro else [])
    out += [f"- [{box}] send — {send_text}", "", f"## {MEETING_RAISE}", ""]
    head = "\n".join(n["head"]).strip("\n")
    out += ([head, ""] if head else [])
    for it in n["items"]:
        out += [f"- [{'x' if it['ticked'] else ' '}] {it['text']}"] + it["under"]
    out += ([""] if n["items"] else []) + [f"## {MEETING_RULED}", ""]
    rh = "\n".join(n["ruled_head"]).strip("\n")
    out += ([rh, ""] if rh else [])
    for d, lines in sorted(n["ruled"], key=lambda x: x[0], reverse=True):
        body = "\n".join(lines).strip("\n")
        out += [f"### {d}", ""] + ([body, ""] if body else [])
    for h, lines in n["others"]:
        body = "\n".join(lines).strip("\n")
        out += [f"## {h}", ""] + ([body, ""] if body else [])
    return props + "\n".join(out).rstrip("\n") + "\n"


def meeting_item(subject, question, since, decides=None, proposed=False, jira=""):
    """One item's line: the ticket as a link (or the topic), the question, who decides, since when, and whether ela
    added it."""
    subject = (subject or "").strip()
    if jira and re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", subject):
        subject = f"[{subject}]({jira.rstrip('/')}/browse/{subject})"
    parts = [f"{subject} — {question.strip()}" if subject else question.strip()]
    parts += [decides.strip()] if (decides or "").strip() else []
    parts += [f"since {since:%m-%d}"] + (["ela proposes"] if proposed else [])
    return " · ".join(parts)


def meeting_fields(text):
    """What an item's line says: {key, since (MM-DD), proposed, gist}; gist is the visible subject and question, the
    item's identity when the same ask is raised twice."""
    v = visible(text)
    since = re.search(r"·[ \t]*since[ \t]+(\d{2}-\d{2})\b", v)
    k = MEETING_KEY.search(v)
    gist = v.split(" · ")[0]
    return {"key": k.group(0) if k else None, "since": since.group(1) if since else None,
            "proposed": bool(re.search(r"·[ \t]*ela proposes\b", v)), "gist": re.sub(r"\s+", " ", gist).strip().lower()}


def meeting_add(n, line, detail=None):
    """Adds an item unless one with the same gist is still to raise; → whether it was added."""
    g = meeting_fields(line)["gist"]
    if any(meeting_fields(it["text"])["gist"] == g for it in n["items"]):
        return False
    n["items"].append({"text": line, "ticked": False, "under": [f"  - {d}" for d in detail or [] if d.strip()]})
    return True


def meeting_since(mmdd, today):
    """The date an item's `since MM-DD` names: the latest one on or before today."""
    try:
        d = datetime.date(today.year, int(mmdd[:2]), int(mmdd[3:]))
    except (TypeError, ValueError):
        return None
    return d if d <= today else d.replace(year=today.year - 1)


def meeting_rule(n, today, last_meeting):
    """His ticks and `ela:` lines applied. An item that was on the list at a meeting held (since on or before
    `last_meeting`, a date or None) is ruled by an `ela:` line under it (its words) or a tick with none; one ticked
    before any meeting saw it is dropped, and `ela: drop` drops either. Each leaves To raise for `### <today>` under
    Ruled, its plain detail folded under it. → [{key, text, outcome: ruled|dropped, words}]."""
    out, stay, lines = [], [], []
    for it in n["items"]:
        f = meeting_fields(it["text"])
        guides = [g.group(1).strip() for g in (GUIDE.match(l) for l in it["under"]) if g]
        words = [g for g in guides if not MEETING_DROP.match(g) and not MEETING_ORDER.match(g)]
        since = meeting_since(f["since"], today) if f["since"] else None
        seen = last_meeting is not None and (since is None or since <= last_meeting)
        if any(MEETING_DROP.match(g) for g in guides) or (it["ticked"] and not seen):
            outcome = "dropped"
        elif seen and (words or it["ticked"]):
            outcome = "ruled"
        else:
            stay.append(it); continue
        said = "; ".join(re.sub(r"^ruled[ \t]*[—:-]*[ \t]*", "", w, flags=re.I) for w in words)
        bare = re.sub(r"[ \t]*·[ \t]*(?:since[ \t]+\d{2}-\d{2}|ela proposes)\b", "", it["text"])
        tail = "dropped" if outcome == "dropped" else (f"ruled: {said}" if said else "ruled by your tick")
        detail = [l for l in it["under"] if not GUIDE.match(l) and not l.lstrip().startswith(">")]
        lines += [f"- {bare} · {tail}"] + detail
        out.append({"key": f["key"], "text": bare, "outcome": outcome, "words": said or None})
    if out:
        n["items"] = stay
        day = next((x for x in n["ruled"] if x[0] == today.isoformat()), None)
        if day is None:
            day = (today.isoformat(), [])
            n["ruled"].append(day)
        while day[1] and not day[1][-1].strip():
            day[1].pop()
        day[1].extend(lines)
    return out


def meeting_lint(path, text):
    """Lint lines for a meeting note: an item over 140 characters as reading mode shows it, a missing send box or
    section."""
    n, out = meeting_parse(text), []
    if not n["send"]:
        out.append(f"{path}: no `- [ ] send` box above {MEETING_RAISE}")
    for want in (MEETING_RAISE, MEETING_RULED):
        if not re.search(r"^##[ \t]+" + re.escape(want) + r"[ \t]*$", split_front(text)[1], re.M):
            out.append(f"{path}: no ## {want} section")
    for i, it in enumerate(n["items"], 1):
        k = len(visible(it["text"]))
        if k > MEETING_ITEM_MAX:
            out.append(f"{path}: item {i} is {k} characters, over {MEETING_ITEM_MAX}; fold the detail under it")
    return out


def meeting_roll(vault, today, dry_run=False):
    """Ruled dates older than 30 days leave each meetings/<key>.md for archive/meetings-<key>-<yyyy-mm>.md, appended
    in date order; the archive is written first, so a crash between the two leaves a date in both, never in neither.
    → [(note, date, archive)]."""
    moved, d = [], os.path.join(vault, MEETINGS)
    cut = (today - datetime.timedelta(days=MEETING_RULED_DAYS)).isoformat()
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        p = os.path.join(d, f)
        if not f.endswith(".md"):
            continue
        text = open(p, encoding="utf-8").read()
        fl, _ = split_front(text)
        if not any(re.match(r"^type:\s*['\"]?meeting['\"]?\s*$", l) for l in fl):
            continue
        n = meeting_parse(text)
        old = sorted((x for x in n["ruled"] if x[0] < cut), key=lambda x: x[0])
        if not old:
            continue
        key, title = f[:-3], n["title"] or f[:-3]
        for day, lines in old:
            rel = f"{ARCHIVE}/meetings-{key}-{day[:7]}.md"
            moved.append((f"{MEETINGS}/{f}", day, rel))
            if dry_run:
                continue
            ap = os.path.join(vault, rel)
            have = open(ap, encoding="utf-8").read() if os.path.exists(ap) else \
                front([], {"title": f"{title.split(' · ')[0]} · ruled in {day[:7]}", "type": "meeting", "date": day[:7] + "-01"}) \
                + f"# {title.split(' · ')[0]} · ruled in {day[:7]}\n"
            if not re.search(r"^###[ \t]+" + day + r"\b", have, re.M):
                os.makedirs(os.path.dirname(ap), exist_ok=True)
                atomic_write(ap, have.rstrip("\n") + f"\n\n### {day}\n\n" + "\n".join(lines).strip("\n") + "\n")
        if not dry_run:
            n["ruled"] = [x for x in n["ruled"] if x[0] >= cut]
            send = re.sub(r"^[-*][ \t]+\[[ xX]\][ \t]+send[ \t]*—?[ \t]*", "", n["send"]["text"]) if n["send"] else "copy the list from below"
            atomic_write(p, meeting_render(n, title, send, today))
    return moved


# ── the sync ──────────────────────────────────────────────────────────────────────────────────────────

def native_notes(vault):
    """Notes whose source is the vault itself (front matter `source: "vault"`): the owner's documents ela writes in
    place (the overview, the workflow, plans for his decision). Read, never written."""
    out = []
    for top_, dirs, fs in os.walk(vault):
        dirs[:] = [d for d in dirs if not d.startswith(".") and os.path.relpath(os.path.join(top_, d), vault).replace(os.sep, "/")
                   not in (ATTACH,) + OWNER_FOLDERS + RETIRED]
        for f in fs:
            if not f.endswith(".md"):
                continue
            p = os.path.join(top_, f)
            try:
                text = open(p, encoding="utf-8").read()
            except OSError:
                continue
            fl, body = split_front(text)
            if not any(re.match(r"^source:\s*['\"]?vault['\"]?\s*$", l) for l in fl):
                continue
            props = {}
            for l in fl:
                m = re.match(r"^(type|date|kind|status|title|moves|project):\s*['\"]?([^'\"]*)['\"]?\s*$", l)
                if m:
                    props[m.group(1)] = m.group(2)
            rel = os.path.relpath(p, vault).replace(os.sep, "/")
            if rel in (OVERVIEW, SERVICES_PAGE) or PROJECT_PAGE.match(rel):   # generated: the ela page's hand sections, the service map's Review and a project page's head kept
                continue
            out.append(Note(rel, props.pop("title", None) or h1(body) or f[:-3], body, props, fl))
    return out


def vocabulary_note(elak):
    """The Jira vocabulary ela enforces (<elak>/map/jira-labels.yaml), rendered for the owner: one section per
    namespace, headed by its prefix so a design page can embed one (`![[ela/jira-vocabulary#proto]]`). The data
    stays in elak, where ela reads it; this page is its view, never a copy to edit."""
    p = os.path.join(elak or "", "map", "jira-labels.yaml")
    if not os.path.isfile(p):
        return None
    sys.path.insert(0, os.path.join(HERE, "..", "release"))
    from release import _yaml_subset                       # the stdlib subset reader the release map uses
    d = _yaml_subset(open(p, encoding="utf-8").read()) or {}
    def cell(x):
        return str(x if x is not None else "").replace("|", "/").replace("\n", " ")
    L = ["# Jira vocabulary for MH", "",
         f"*Every component and label value ela writes, read from Jira on {d.get('read', '?')} ({d.get('tickets', '?')} tickets, "
         f"{d.get('open', '?')} open); {d.get('status') or 'in force'}. The rules are ela's knowledge in elak.*", ""]
    for n in d.get("namespaces") or []:
        vals = n.get("values") or []
        L += [f"## {n.get('prefix')}", "", f"*{cell(n.get('meaning'))}* · {len(vals)} values", ""]
        moving = any(v.get("to") or v.get("action") in ("rename", "retire") for v in vals) and not any(v.get("meaning") for v in vals[:1]) \
            or n.get("prefix") in ("bare", "old-component")
        if moving:                                         # a migration table: where each current value goes
            L += ["| value | open | all | becomes |", "|---|---|---|---|"]
            L += [f"| {cell(v.get('value'))} | {cell(v.get('count_open'))} | {cell(v.get('count_all'))} | "
                  f"{cell(v.get('to')) if v.get('to') else cell(v.get('action'))} |" for v in vals]
        else:
            extra = "example" if any(v.get("example") for v in vals) else "aliases" if any(v.get("aliases") for v in vals) else None
            count = "estimated" if any(v.get("trial") is not None for v in vals) else None   # a component not yet in use: its estimate
            L += [f"| value | meaning |{f' {extra} |' if extra else ''} {'estimated |' if count else 'open | all |'} action |",
                  "|---|---|" + ("---|" if extra else "") + ("---|" if count else "---|---|") + "---|"]
            for v in vals:
                ex = v.get(extra) if extra else None
                ex = ", ".join(ex) if isinstance(ex, list) else ex
                nums = f" {cell(v.get('trial'))} |" if count else f" {cell(v.get('count_open'))} | {cell(v.get('count_all'))} |"
                L.append(f"| `{cell(v.get('value'))}` | {cell(v.get('meaning'))} |" + (f" {cell(ex)} |" if extra else "") + nums
                         + f" {cell(v.get('to') or v.get('action'))} |")
        L.append("")
    return Note(f"{ELA}/jira-vocabulary.md", "Jira vocabulary for MH", "\n".join(L), {"type": "vocabulary", "date": d.get("read")},
                src_rel="elak:map/jira-labels.yaml")


# the service map: one living page, ela/service-map.md, written from the published map (site.json `map`: services.yaml
# and release.yaml, never elak directly) so the slugs ela uses never drift from it; the owner's Review section is his
SERVICES_PAGE = f"{ELA}/service-map.md"
SERVICES_TITLE = "The service map for review"
SERVICES_HEAD = "## Review"
SERVICES_GENERATED = ("The Fixed In grammar", "App-layer services (SaaS)", "Docker images and their services")
HEX_ID = re.compile(r"\b([0-9a-f]{8})[0-9a-f]{24}\b")


def services_map(path):
    """The published services.yaml, read the way brief.py reads it: a prose header, then `  <image>:` blocks whose
    `arch:` is JSON, whose `owners:` is a JSON list, whose service rows are `- {…}` and whose repos are `- gitlab:`
    lines. Not strict YAML, so no YAML reader; the regexes are the contract. None when the file is not there."""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return None
    out, image = {"verified": None, "images": {}}, None
    for line in text.splitlines():
        m = re.match(r"^verified:\s*['\"]?([\d-]+)", line)
        if m and not out["verified"]:
            out["verified"] = m.group(1)
        h = re.match(r"^  ([\w.-]+):\s*$", line)
        if h:
            image = out["images"].setdefault(h.group(1), {"class": None, "owners": [], "services": [], "repos": []})
            continue
        if image is None:
            continue
        m = re.match(r"^    (arch|owners):\s*(\{.*\}|\[.*\])\s*$", line)
        if m:
            try:
                v = json.loads(m.group(2))
            except ValueError:
                continue
            if m.group(1) == "arch" and isinstance(v, dict):
                image["class"] = v.get("class")
            elif m.group(1) == "owners" and isinstance(v, list):
                image["owners"] = [str(x) for x in v]
            continue
        m = re.match(r"^\s+- (\{.*\})\s*$", line)
        if m:
            try:
                row = json.loads(m.group(1))
            except ValueError:
                row = None
            if isinstance(row, dict) and row.get("slug"):
                image["services"].append(row)
            continue
        m = re.match(r"^\s+- gitlab:\s*(\S+)", line)
        if m:
            image["repos"].append(m.group(1))
    return out


def services_review(body):
    """The owner's Review section as written on disk: everything from `## Review` to the end, verbatim, the way a
    project page keeps its head. A section of his above it, or every section of his when there is no Review yet (the
    desk's first write), is kept under it one level down, so the next sync finds it there."""
    m = re.search(r"^" + re.escape(SERVICES_HEAD) + r"[ \t]*$", body or "", re.M)
    head = body[:m.start()] if m else (body or "")
    kept = body[m.start():].rstrip("\n") + "\n" if m else ""
    extra = [t.rstrip("\n") for h, t in sections(head) if h and h not in SERVICES_GENERATED]
    if not kept:
        kept = SERVICES_HEAD + "\n" + ("" if extra else "\nNothing yet: write your review here, or an `ela:` line under a row; "
                                                          "this section is kept as written.\n")
    for t in extra:
        kept += "\n#" + t + "\n"
    return kept


def services_note(s, vault, today):
    """The service map as one living page, from the published map: the Fixed In grammar (release.yaml `fixed_in`),
    the app-layer services (`repos`, `jobs`, `service_ids`, `qa_service_ids`, `version_rules`) and every docker
    image's GM services (services.yaml `images:`), folded so the page reads short; the Review section his, kept
    as written. None when the published map has no services.yaml."""
    mdir = s.get("map") or ""
    m = services_map(os.path.join(mdir, "services.yaml"))
    if m is None:
        return None
    sys.path.insert(0, os.path.join(HERE, "..", "release"))
    from release import _yaml_subset
    try:
        r = _yaml_subset(open(os.path.join(mdir, "release.yaml"), encoding="utf-8").read()) or {}
    except OSError:
        r = {}
    try:
        _, disk = split_front(open(os.path.join(vault, SERVICES_PAGE), encoding="utf-8").read())
    except OSError:
        disk = ""

    def cell(x):
        return str(x if x is not None else "").replace("|", "/").replace("\n", " ").strip()

    def short(x):
        x = cell(x)
        if not x or x == "—":
            return "—"
        return f"`{HEX_ID.sub(r'\1…', x)}`" if HEX_ID.fullmatch(x) else HEX_ID.sub(r"\1…", x)
    L = [f"# {SERVICES_TITLE}", "",
         f"*Written by the sync from the published map, `map/services.yaml` (verified {m.get('verified') or '?'}) and "
         f"`map/release.yaml` (verified {r.get('verified') or '?'}), for your review: every slug ela uses, what GM registers "
         "it as, its id, its repo and Jenkins job, and the form a Fixed In entry takes. Three words are kept apart on purpose: "
         "the **slug** is ela's and Helm's name, the **GM name** is what GM registers, the **service id** is GM's id. The page "
         "is written again on every sync; your `ela:` lines under a row change the map on your word, and the Review section "
         "at the end is yours, kept as written.*", ""]
    fx = r.get("fixed_in") or {}
    L += [f"## {SERVICES_GENERATED[0]}", ""]
    if not fx:
        L += ["The release map is not published; the grammar and the app-layer table wait for it.", ""]
    else:
        L += [f"- Field `{cell(fx.get('field'))}`; grammar `{cell(fx.get('grammar'))}`; canonical version `{cell(fx.get('canonical_version'))}`.",
              f"- Docker form: `{cell(fx.get('docker_form'))}`.",
              f"- Patch-only dot form: {cell(fx.get('patch_only_dot_form'))}.",
              f"- Same slug twice: {cell(fx.get('same_slug_twice'))}.",
              "- Grandfathered: " + "; ".join(cell(x) for x in (fx.get("grandfathered_forms") or [])) + ".", ""]
    vr = r.get("version_rules") or {}
    app, sem = vr.get("app_layer") or {}, vr.get("semver_build") or {}
    ids, qids, jobs, repos = r.get("service_ids") or {}, r.get("qa_service_ids") or {}, r.get("jobs") or {}, r.get("repos") or {}
    by_slug, qa_by_slug = {}, {}
    for table, dst in ((ids, by_slug), (qids, qa_by_slug)):
        for sid, pairs in table.items():
            for pair in pairs or []:
                if isinstance(pair, list) and len(pair) == 2:
                    dst.setdefault(pair[0], (sid, pair[1]))
    slugs = list(dict.fromkeys(list(repos) + list(by_slug) + list(qa_by_slug)))
    canonical = cell(fx.get("canonical_version")) or "M.m.p+BUILD"
    L += [f"## {SERVICES_GENERATED[1]}", "",
          "| slug | repo | Jenkins job | prod userservice id · field | QA userservice id · field | version grammar | Fixed In form |",
          "|---|---|---|---|---|---|---|"]
    for sl in slugs:
        job = next((j for j, v in jobs.items() if v == sl), None)
        prod, qa = by_slug.get(sl), qa_by_slug.get(sl)
        if sl in (app.get("slugs") or []):
            grammar = f"app_layer: `{cell(app.get('grammar'))}`"
        elif sl in (sem.get("slugs") or []):
            grammar = f"semver_build: `{cell(sem.get('grammar'))}`"
        else:
            grammar = f"semver_build (default): `{cell(sem.get('grammar')) or 'M.m.p+SUFFIX'}`"
        L.append(f"| `{sl}` | {f'`{cell(repos[sl])}`' if repos.get(sl) else '—'} | {f'`{job}`' if job else '—'} | "
                 f"{f'{short(prod[0])} · {cell(prod[1])}' if prod else '—'} | {f'{short(qa[0])} · {cell(qa[1])}' if qa else '—'} | "
                 f"{grammar} | `{sl}@{canonical}` |")
    L.append("")
    for name, gw in (r.get("gateway_versions") or {}).items():
        if isinstance(gw, dict) and gw.get("path"):
            L += [f"{sentence(name)} publishes no lane version in userservice; its version is read through the API gateway at "
                  f"`{cell(gw['path'])}` per lane token ({len(gw.get('lanes') or {})} lanes).", ""]
    images = m["images"]
    n_services = sum(len(i["services"]) for i in images.values())
    L += [f"## {SERVICES_GENERATED[2]}", "",
          "One row per GM service; the image is the codebase and the Fixed In's `<image>:<tag>` qualifier, its class as the "
          "map records it (`?` where the map has not settled it). Repos are the first two the map lists; owners as the map records them.", "",
          f"> [!note]- {len(images)} images · {n_services} services",
          "> | image (class) | slug | GM name | process type | MQTT topic | service id | status | repo | owner |",
          "> |---|---|---|---|---|---|---|---|---|"]
    for name in sorted(images):
        im = images[name]
        first = [f"`{cell(name)}` ({cell(im['class']) or '?'})", "<br>".join(f"`{cell(x)}`" for x in im["repos"][:2]), ", ".join(cell(x) for x in im["owners"])]
        rows = im["services"] or [{}]
        for i, sv in enumerate(rows):
            lead, repo, owner = first if i == 0 else ("", "", "")
            topic = cell(sv.get("mqtt_topic"))
            L.append(f"> | {lead} | `{cell(sv.get('slug'))}` | {cell(sv.get('gm_name'))} | `{cell(sv.get('process_type'))}` | "
                     f"{f'`{topic}`' if topic and topic != '—' else '—'} | {short(sv.get('service_id'))} | {cell(sv.get('status'))} | {repo} | {owner} |")
    L += ["", f"{len(images)} images, {n_services} GM services.", "", services_review(disk)]
    return Note(SERVICES_PAGE, SERVICES_TITLE, "\n".join(L), {"type": "services", "date": today.isoformat()},
                src_rel="published:map/services.yaml")


def plan(s, env, today, now, removed=frozenset(), removed_src=frozenset(), since=None, dry_run=False):
    reports = s.get("reports")
    enotes, titles = elak_notes(s.get("elak"))
    notes = report_notes(reports, today) + enotes + [constraints_note(standing_constraints(s, env), today)]
    vnotes, files = verify_notes(reports, today)
    notes += vnotes + verify_plan_notes(reports, vnotes)
    # what the owner deleted is not written, linked or listed; matched by source too, so a new layout keeps it deleted
    notes = [n for n in notes if n.path not in removed and not (n.src_rel and n.src_rel in removed_src)]
    native = native_notes(s["vault"])
    native_paths = {n.path.lower() for n in native}
    notes = [n for n in notes if n.path.lower() not in native_paths]
    native_warn = []
    for n in native:                                       # a page ela writes in place is not gated, only checked
        native_warn += [f"{n.path}: {p}" for p in mermaid_problems(n.body)]
        if n.props.get("type") == "report":              # a report is his document; its budget is advice, never a hold
            native_warn += report_lint(n)
        if n.props.get("type") == "meeting" and top(n.path) == MEETINGS:
            native_warn += [f"meeting: {x}" for x in meeting_lint(n.path, n.body)]
    for n in notes:                                        # a source's own `project:` line names its project
        if not n.props.get("project") and props_of(n.front_lines).get("project"):
            n.props["project"] = props_of(n.front_lines)["project"]
    pages = project_pages(s["vault"])
    inferred = infer_projects(s["vault"], {k: set(project_facts(k, t, today)["keys"]) for k, t in pages.items()}, notes, native, dry_run)
    native_warn += [f"type: {x}" for x in (type_lint(n.path, n.props.get("type")) for n in notes + native) if x]
    native_warn += [f"project: {x}" for x in (project_lint(n.path, n.props, s["vault"]) for n in notes + native) if x]
    native_warn += [f"asks: {x}" for x in (asks_lint(n) for n in notes + native) if x]
    native_warn += [f"layout: {x}" for x in folder_lint(s["vault"])]
    ov = overview_note(s, s["vault"], today)
    if ov:
        notes.append(ov)
    vocab = vocabulary_note(s.get("elak"))
    if vocab:
        notes.append(vocab)
    smap = services_note(s, s["vault"], today)
    if smap:
        notes.append(smap)
    taken = set()
    for n in notes:                                        # one note per path; a namesake gets -2, never an overwrite
        stem, i = n.path[:-3], 2
        while n.path.lower() in taken:
            n.path = f"{stem}-{i}.md"; i += 1
        taken.add(n.path.lower())
    jira_base = ""
    if env and os.path.isfile(env):
        jira_base = next((l.split("=", 1)[1].strip().rstrip("/") for l in open(env) if l.startswith("JIRA_BASE_URL=")), "")
    for key, text in pages.items():                        # each project's page: its head as written, its tail from the notes
        notes.append(project_note(key, text, s["vault"], notes + native, today, jira_base))
    projects = project_keys(env, s.get("runtime")) if jira_base else set()
    spec = lint_notes(s["vault"], projects or None)
    if spec:                                               # one line here; each deviation is `vault.py lint`'s
        native_warn.append(f"spec: {sum(len(l) for _, _, l in spec)} deviations from the note standards in {len(spec)} notes; "
                           "`ela vault lint` lists them")
    warnings = native_warn + ([] if jira_base and projects else ["ticket keys are not linked: no Jira base URL or project list"])
    reps = {n.src_rel: n for n in notes if n.src_rel and n.props.get("type") in ("day", "review", "reader")}
    linker = Linker({n.src_rel: n for n in enotes}, titles, jira_base, projects, reports, reps)
    planned = {}
    have_recent = any(n.props.get("type") == "recent" for n in notes)
    for n in notes:
        if n.props.get("type") == "day" and n.props.get("kind") == "brief":
            n.body = with_recent_pointer(n.body, have_recent)
        if folder_of(n.path) in tuple(STATUS_BY_FOLDER) + (READINGS,):
            st, result, _ = settled_status(folder_of(n.path), note_status(n), n.props.get("type"))
            n.props.update(status=st, result=n.props.get("result") or result)
            n.front_lines = [l for l in n.front_lines if not l.startswith("status:")]   # the source's own word is settled
        if top(n.path) == TO_READ:
            n.props.update({NEXT: "", MOVE_SET: move_set(n.props.get("type"))})
        n.held = reading_gate(n)
        if getattr(n, "front_text", None):                 # a project page: the head as the desk wrote it, the tail linked
            body = n.head + linker(n.tail)
            planned[n.path] = redact(n.front_text + (with_warning(body, n.held) if n.held else body))
            continue
        body = linker(unwrap(callouts(meta_line(Note(n.path, n.title, tidy_title(n.body), n.props, n.front_lines)))))
        if top(n.path) == TO_READ:
            body = with_moves(body, n.path, n.props.get("type"))
        planned[n.path] = redact(front(n.front_lines, dict(n.props, title=n.title)) + (with_warning(body, n.held) if n.held else body))
    planned["home.md"] = redact(front([], {"type": "home", "date": today.isoformat()}) + linker(home(today, now, notes + native, {
        "actions": week_actions(reports, today), "since": since, "program": program_next(s["vault"]), "ela": ela_line(s["vault"]),
        "hold": tier2_hold(reports, today.isoformat()), "lists": list_links(reports)})))
    planned[f"{ELA}/about-this-vault.md"] = unwrap(README.replace(SPEC_MARK, spec_text()))
    for name, text in VIEWS.items():
        planned[f"{ELA}/{name}.base"] = text
    return planned, files, notes, warnings, {n.path for n in native}, inferred


def ruled(elak, src):
    """Whether an elak decision or plan left to-read because it was ruled on: its file still exists and no longer says
    proposed. A renamed or deleted file was not ruled on, so its note is not archived as if it had been."""
    try:
        head = open(os.path.join(elak or "", src), encoding="utf-8").read(4000)
    except OSError:
        return False
    return not re.search(r"^status:\s*['\"]?proposed\b", head, re.M)


def load_removed(path):
    """(paths, sources) the owner deleted and has not restored. A row names the note's path and, since layout 2,
    its source, so a note keeps its deletion when the layout moves it. ela's own archiving of a ruled elak source is
    not a deletion: the source no longer qualifies anyway, and if it comes back as proposed it must come back."""
    paths, src_of = set(), {}
    try:
        for line in open(path, encoding="utf-8"):
            try:
                row = json.loads(line)
                if row.get("restored"):
                    gone = {row["path"]} | {p for p, s_ in src_of.items() if row.get("src") and s_ == row["src"]}
                    paths.difference_update(gone)
                    for p in gone:
                        src_of.pop(p, None)
                elif not (row.get("by") == "ela" and str(row.get("src") or "").startswith("blueprint/")):
                    paths.add(row["path"])
                    if row.get("src"):
                        src_of[row["path"]] = row["src"]
            except (ValueError, KeyError):
                pass
    except OSError:
        pass
    return paths, set(src_of.values())


def archive_names(vault):
    """{file name, lowercased: folder} under archive/: a generated note that left its folder and
    appears there was moved by the owner, and the folder says what he meant."""
    out = {}
    for folder in OWNER_FOLDERS:
        for top_, _, fs in os.walk(os.path.join(vault, folder)):
            out.update({f.lower(): folder for f in fs if f.endswith(".md")})
    return out


def archive_refs(vault):
    """Attachments the archived notes embed or link (a verification's screenshots and record), kept on disk so an
    archived note still shows them; they leave the manifest and are the owner's from then on."""
    refs = set()
    for top_, _, fs in (w for folder in OWNER_FOLDERS for w in os.walk(os.path.join(vault, folder))):
        for f in fs:
            if f.endswith(".md"):
                try:
                    text = open(os.path.join(top_, f), encoding="utf-8").read()
                except OSError:
                    continue
                refs |= {m.lower() for m in re.findall(r"\[\[(" + re.escape(ATTACH) + r"/[^\]|#]+)", text)}
    # a record's page sits beside its images: keep the whole record folder of anything referenced
    return {r.rsplit("/img/", 1)[0] if "/img/" in r else os.path.dirname(r) for r in refs}


def record_removed(path, rels, sources, now, archived=None, by="owner"):
    """Log each note the owner finished with: dragged into archive/ (keep it, nothing to do) or deleted (drop it). Each way he has read it, so it stays out of the generated folders. None is criticism or
    a verdict on a decision; feedback comes as a message (Slack `feedback`, a session)."""
    archived = archived or {}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for r in rels:
            title = sentence(re.sub(r"^\d{4}-\d{2}-\d{2}-", "", os.path.basename(r)[:-3]).replace("-", " "))
            to = archived.get(os.path.basename(r).lower())
            to = kept_home(to) or to                       # a release line's folder is mh/releases
            row = {"at": now.isoformat(timespec="seconds"), "path": r, "title": title,
                   "fate": "archived" if to in OWNER_FOLDERS else {IN_PROGRESS: "in-progress", PARKED: "parked",
                                                                   TO_READ: "to-read"}.get(to, "deleted"), "by": by}
            if to in SUBJECT_HOMES:                        # kept by subject: the home it went to
                row["home"] = to
            if sources.get(r):
                row["src"] = sources[r]
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def cmd_setup(a):
    """Apply the vault's Obsidian settings from ela's versioned copy (obsidian/): reading view, no file-name title or
    properties panel, the style sheet, the core plugins, Homepage, the bookmarks. Merges into what is there; the
    plugin's code is fetched only when absent, pinned to the recorded version. Restart Obsidian afterwards."""
    s = json.load(open(SITE))
    src = os.path.join(HERE, "obsidian")
    cfg = json.load(open(os.path.join(src, "settings.json")))
    o = os.path.join(s["vault"], ".obsidian")
    os.makedirs(os.path.join(o, "snippets"), exist_ok=True)
    def merge(name, upd):
        p = os.path.join(o, name)
        try:
            cur = json.load(open(p))
        except (OSError, ValueError):
            cur = {}
        cur.update(upd); atomic_write(p, json.dumps(cur, indent=2))
    merge("app.json", cfg["app"])
    try:                                                   # the table's boxes are checkbox properties, so one click ticks
        types = json.load(open(os.path.join(o, "types.json")))
    except (OSError, ValueError):
        types = {}
    types.setdefault("types", {}).update(cfg.get("types") or {})
    atomic_write(os.path.join(o, "types.json"), json.dumps(types, indent=2))
    merge("appearance.json", cfg["appearance"])
    try:
        core = json.load(open(os.path.join(o, "core-plugins.json")))
    except (OSError, ValueError):
        core = {}
    core = {k: (k in cfg["core_on"]) for k in set(core) | set(cfg["core_on"])}
    atomic_write(os.path.join(o, "core-plugins.json"), json.dumps(core, indent=2))
    try:                                                   # his own plugins stay enabled beside ela's
        mine = json.load(open(os.path.join(o, "community-plugins.json")))
    except (OSError, ValueError):
        mine = []
    atomic_write(os.path.join(o, "community-plugins.json"), json.dumps(list(dict.fromkeys(list(cfg["community"]) + [x for x in mine if isinstance(x, str)]))))
    for pid, opts in (cfg.get("core_options") or {}).items():   # a core plugin's options live in .obsidian/<id>.json
        merge(f"{pid}.json", opts)
    shutil.copyfile(os.path.join(src, "ela.css"), os.path.join(o, "snippets", "ela.css"))
    for pid, spec in cfg["plugins"].items():           # each community plugin pinned to a recorded release
        hp = os.path.join(o, "plugins", pid); os.makedirs(hp, exist_ok=True)
        for f in spec["files"]:
            if not os.path.isfile(os.path.join(hp, f)):
                url = f"https://github.com/{spec['repo']}/releases/download/{spec['version']}/{f}"
                r = subprocess.run(["curl", "-fsSL", "-m", "120", "-o", os.path.join(hp, f), url], capture_output=True, text=True)
                if r.returncode != 0:
                    print(f"could not fetch {pid} {f}: {r.stderr.strip()[-120:]}", file=sys.stderr)
    shutil.copyfile(os.path.join(src, "homepage-data.json"), os.path.join(o, "plugins", "homepage", "data.json"))
    # the note's next field as a Select: the button beside it in the properties lists the moves
    shutil.copyfile(os.path.join(src, "metadata-menu-data.json"), os.path.join(o, "plugins", "metadata-menu", "data.json"))
    write_move_sets(s["vault"])
    now = int(datetime.datetime.now().timestamp() * 1000)
    try:                                                   # his own bookmarks stay, after ela's
        had = [b for b in json.load(open(os.path.join(o, "bookmarks.json"))).get("items") or [] if isinstance(b, dict)]
    except (OSError, ValueError, AttributeError):
        had = []
    ours = [dict(b, type="file", ctime=now) for b in cfg["bookmarks"]]
    taken = {b.get("path") for b in ours}
    atomic_write(os.path.join(o, "bookmarks.json"), json.dumps({"items": ours + [b for b in had if b.get("path") not in taken]}, indent=2))
    print("vault settings applied; restart Obsidian to load them")


TICKED = re.compile(r"^[ \t]*" + QUOTE + r"[-*][ \t]+\[[xX]\][ \t]+(\S.*?)[ \t]*$", re.M)   # a choice he ticked in a note: a click, not typing
# horizontal whitespace only: an empty `ela:` property must not reach across the line break to the next line; before
# `ela:` only list or quote markers, a list marker with its space, so a bold `**ela:**` is never his line
GUIDE = re.compile(r"^[ \t]*(?:[-*+][ \t]+|>[ \t]*)*ela[ \t]*[:：][ \t]*(\S.*?)[ \t]*$", re.I | re.M)
SECTION = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.M)


def section_at(text, pos):
    """The `## ` heading a position in a note sits under, or None above the first."""
    found = None
    for m in SECTION.finditer(text, 0, pos):
        found = m.group(1)
    return found


def place_lines(text, lines):
    """His kept lines put back into a rewritten note, each at the end of the section it was written under when that
    section is still there (a meeting's rulings stay under the meeting), the rest at the end. lines: [(section, line)]."""
    tail = []
    for sec, line in lines:
        m = re.search(r"^##[ \t]+" + re.escape(sec) + r"[ \t]*$", text, re.M) if sec else None
        if not m:
            tail.append(line); continue
        nxt = re.compile(r"^#{1,2}[ \t]", re.M).search(text, m.end())
        end = nxt.start() if nxt else len(text)
        body = text[:end].rstrip("\n")
        text = body + "\n\n" + line + "\n" + ("\n" + text[end:] if nxt else "")
    return text.rstrip("\n") + ("\n\n" + "\n".join(tail) if tail else "") + "\n"


def load_answers(reports):
    """The runner's answers to his `ela:` lines, <reports>/ela/answers.jsonl: {note, lines, at, status, job, answer}."""
    try:
        return [json.loads(l) for l in open(os.path.join(reports, "ela", "answers.jsonl"), encoding="utf-8") if l.strip()]
    except (OSError, ValueError):
        return []


PENDING = ("queued", "running")                  # a job's states before its answer
PENDING_FOLD = re.compile(r"\n*^> \[!note\]- on it · queued \d\d:\d\d · job \S+\n(?:>.*(?:\n|\Z))*", re.M)


def load_pending(reports):
    """The runner's vault jobs not yet answered, from their job files (<reports>/runner/jobs/<id>.json), in the shape
    of an answer row: {note, lines, at, status, job}. The runner writes the job; the vault only renders it."""
    d, out = os.path.join(reports or "", "runner", "jobs"), []
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        try:
            j = json.load(open(os.path.join(d, f), encoding="utf-8")) if f.endswith(".json") else {}
        except (OSError, ValueError):
            continue
        o = j.get("origin") or {}
        if j.get("kind") == "vault" and j.get("status") in PENDING and o.get("note"):
            out.append({"note": o["note"], "lines": o.get("lines") or [], "at": j.get("created"), "status": j["status"],
                        "job": j.get("id"), "started": j.get("started")})
    return out


def pending_block(row):
    """A line ela has taken up, folded under it until the answer replaces it."""
    doing = f"running since {(row.get('started') or '')[11:16]}" if row.get("status") == "running" else "waiting its turn"
    return "\n".join([f"> [!note]- on it · queued {(row.get('at') or '')[11:16]} · job {row.get('job')}",
                      f"> {doing}; the answer replaces this fold."])


def answer_block(row):
    """One answer as a folded callout. A line of the answer that reads as an instruction (`ela: …`) is defused, so
    the answer is never taken for a new ask."""
    head = "ela answered" if row.get("status") == "done" else "ela could not finish"
    body = [re.sub(r"^(\s*(?:[-*>]\s*)*)ela(\s*[:：])", r"\1ela —", l) for l in (row.get("answer") or "").strip().splitlines()]
    lines = [f"> [!note]- {head} · {(row.get('at') or '')[11:16]} · job {row.get('job')}"] + [f"> {l}" if l.strip() else ">" for l in body]
    return "\n".join(lines)


def with_answers(text, rel, answers):
    """Each answer placed under the last of the `ela:` lines it answers, once (the job id marks it); a job still
    queued or running shows as an "on it" fold there, which its answer replaces."""
    text = PENDING_FOLD.sub("", text)
    answered = {r.get("job") for r in answers if r.get("status") not in PENDING}
    rows = [r for r in answers if r.get("status") not in PENDING] + [r for r in answers if r.get("status") in PENDING
                                                                     and r.get("job") not in answered]
    for row in (r for r in rows if r.get("note") == rel and r.get("job") and r["job"] not in text):
        says = {x.strip() for x in row.get("lines") or []}
        hits = [m for m in GUIDE.finditer(text, body_start(text)) if m.group(1).strip().strip('"').strip("'") in says]
        if hits:
            at = hits[-1].end()
            text = text[:at] + "\n\n" + (pending_block(row) if row.get("status") in PENDING else answer_block(row)) + "\n" + text[at:]
    return text


def answer_native(vault, answers, dry_run=False):
    """A note whose source is the vault is never rewritten by the sync; its answers are inserted in place, nothing
    else. Returns the paths changed."""
    out = []
    for rel in sorted({r.get("note") for r in answers if r.get("note")}):
        p = os.path.join(vault, rel)
        try:
            text = open(p, encoding="utf-8").read()
        except OSError:
            continue
        if not any(re.match(r"^source:\s*['\"]?vault['\"]?\s*$", l) for l in split_front(text)[0]):
            continue
        new = with_answers(text, rel, answers)
        if new != text:
            out.append(rel)
            if not dry_run:
                atomic_write(p, new)
    return out


# ── a note's life: to-read → in-progress → archive, and parked beside them ──────────────────────────────
# Each note to read ends in its next moves, by kind. A tick is the owner's word for that move and nothing wider; the
# runner does a move by script (a note moved, its status set) and starts a session only to build, plan or draft.
MOVE_PROPS = {                   # by kind, beyond done and drop, which every note to read carries
    "plan": ["agree", "park", "not-now", "reject"],
    "sprint": ["agree", "not-now"],
    "review": ["make-plan", "park"],
    "verify": ["draft-comment"],
    "decision": ["confirm", "park"],
    "built": ["accept", "not-done"],
    "ticket": ["nudge", "go-deep", "seen", "drop"],   # a ticket's moves only: "done" would read as the ticket's Jira Done
    "parked": ["resume", "drop"],          # a parked note's only moves: it comes back, or it ends
    "reopen": ["reopen"],                  # a built note ela archived after three working days unruled: one click back
}
OUT_OF_TO_READ = ("built", "parked", "reopen")       # kinds whose moves are their own, without done and drop
ALL_MOVE_PROPS = ("agree", "park", "not-now", "reject", "make-plan", "draft-comment", "confirm", "accept", "not-done", "nudge", "go-deep",
                  "seen", "resume", "run", "reopen")   # run: the retired verify-plan gate's box, still stripped from old notes
MOVE_MEANING = {
    "agree": "ela builds it: the note moves to `in-progress/` and each step is written under Progress",
    "park": "parked: it waits on others; comes back when `wake` happens",
    "not-now": "archived: not now", "reject": "archived as rejected",
    "make-plan": "ela writes a plan from the findings as a new note to read; this one is archived",
    "draft-comment": "ela drafts the short Jira comment as `apply N`; nothing is posted",
    "confirm": "archived as confirmed", "accept": "archived as accepted",
    "not-done": "ela carries on; write what is missing as `ela:` lines first",
    "nudge": "ela drafts a short nudge to whoever the ticket waits on, as `apply N`; nothing is posted",
    "go-deep": "ela reads the ticket to its root cause in the code (`ela probe`) and writes what it finds under this page",
    "seen": "archived: you have read where it stands",
    "resume": "back to `to-read/` as proposed, for your next decision",
    "reopen": "back to `in-progress/` as built, for your accept or not-done: ela closed it, and that was wrong",
    "done": "archived, nothing more",
    "drop": "closed and kept: archived (or its subject home) with next drop; nothing is deleted",
}
MOVES = MOVE_PROPS               # a kind with moves gets the section that explains them
AGREEABLE = ("plan", "sprint")
MOVES_HEAD = "## Next moves"
PROP_RE = re.compile(r"^(?:(?:" + "|".join(re.escape(k) for k in ("done", "learn", "drop") + ALL_MOVE_PROPS)
                     + r"):\s*(?:true|false)|(?:next|moves):\s*.*)\s*\n", re.M | re.I)   # the move fields, old boxes included
NEXT = "next"   # one field, one value: the move he chose, from the list Metadata Menu shows beside it
# the note's set of moves, by name: Metadata Menu reads it (its fileClass alias) and lists only that set's moves for
# `next`; one definition per set lives in MOVE_SETS_DIR, written from MOVE_PROPS so the two cannot disagree
MOVE_SET, MOVE_SETS_DIR = "moves", "ela/moves"


def move_props(kind, in_to_read=True):
    """The checkbox properties a note carries for its next moves: its kind's own, then done and drop."""
    if kind == "ticket":                    # its moves only: "done" would read as the ticket's Jira Done
        return list(MOVE_PROPS[kind])
    return list(MOVE_PROPS.get(kind) or []) + (list(MARKS) if in_to_read else [])


def move_set(kind, in_to_read=True):
    """The name of the moves a note offers: its kind's when it has its own, else the plain to-read two."""
    if kind in OUT_OF_TO_READ or (kind in MOVE_PROPS and in_to_read):
        return kind
    return "read" if in_to_read else None


def write_move_sets(vault):
    """One Metadata Menu field definition per set of moves, so a note's `next` chooser lists its moves and no other,
    and its `status` chooser the statuses of the folder that set lives in (STATUS_BY_FOLDER)."""
    d = os.path.join(vault, MOVE_SETS_DIR)
    os.makedirs(d, exist_ok=True)
    sets = {k: move_props(k, in_to_read=k not in OUT_OF_TO_READ) for k in MOVE_PROPS}
    sets["read"] = list(MARKS)
    sets["closed"] = []                                    # an archived note: its status only, its next already written
    sets["case"] = []                                      # a case: its status only (open, answered, closed)
    folder_of = {"built": IN_PROGRESS, "parked": PARKED, "closed": ARCHIVE, "reopen": ARCHIVE, "case": CASES}

    def field(name, values):
        vals = "".join(f'\n        "{i}": {m}' for i, m in enumerate(values, 1))
        return (f"  - name: {name}\n    id: {name}\n    type: Select\n    path: \"\"\n    options:\n"
                f"      sourceType: ValuesList\n      valuesList:{vals}\n")
    for name, moves in sets.items():
        text = ("---\nfields:\n" + (field("next", moves) if moves else "")
                + field("status", STATUS_BY_FOLDER[folder_of.get(name, TO_READ)]) + "---\n")
        p = os.path.join(d, f"{name}.md")
        if not os.path.isfile(p) or open(p, encoding="utf-8").read() != text:
            atomic_write(p, text)


def moves_section(rel, kind, stamp=None):
    """What each choice of the note's `next` field does, and where to continue it. The field is set at the top of
    the note (the button beside it lists the choices) or typed in its Home row; ela empties it once it has acted."""
    props = move_props(kind, in_to_read=kind not in OUT_OF_TO_READ)
    if not MOVE_PROPS.get(kind):
        return ""
    return "\n".join([MOVES_HEAD, "", "Choose one for **next** at the top of this note (the button beside it lists them), "
                       "or type it in the note's row on Home:", ""]
                      + [f"- **{k}**: {MOVE_MEANING[k]}" for k in props]
                      + ["", f"*Or write `ela:` lines above, or continue in a session: `{rel}`.*"])


def with_moves(body, rel, kind, stamp=None):
    """The note with its next moves at the end, replacing any it had."""
    sec = moves_section(rel, kind, stamp)
    body = re.split(r"^" + re.escape(MOVES_HEAD) + r"[ \t]*$", body, maxsplit=1, flags=re.M)[0].rstrip("\n")
    return body + ("\n\n" + sec + "\n" if sec else "\n")


def keep_choice(text, disk_lines, rel):
    """The planned note with the `next` he chose on disk, and a status he picked from the folder's chooser, when each is
    one the note offers: a rewrite between his choice and the watcher's poll must not erase it."""
    fl, _ = split_front(text)
    planned = props_of(fl)
    disk = props_of(disk_lines)
    kind = "built" if planned.get("status") == "built" else planned.get("type")
    keep = {}
    chosen = (disk.get(NEXT) or "").lower()
    if chosen and chosen != (planned.get(NEXT) or "") and chosen in move_props(kind, in_to_read=top(rel) == TO_READ):
        keep[NEXT] = chosen
    st = disk.get("status")
    if st and st != planned.get("status") and st in STATUS_BY_FOLDER.get(folder_of(rel), ()):
        keep["status"] = st
    return set_front(text, **keep) if keep else text


def free_path(folder, name, own=None):
    """A path in `folder` for a note called `name` that overwrites nothing: the name itself, else name-2, name-3, …
    (`own` is the note's current path, which it may keep)."""
    stem, ext = os.path.splitext(name)
    cand, i = os.path.join(folder, name), 2
    while os.path.exists(cand) and (not own or os.path.realpath(cand) != os.path.realpath(own)):
        cand, i = os.path.join(folder, f"{stem}-{i}{ext}"), i + 1
    return cand


def props_of(lines):
    """A note's front-matter lines → {key: value}, quotes taken off: the one reading every caller shares."""
    return {m.group(1): m.group(2).strip().strip("'\"") for m in (re.match(r"^([\w-]+):\s*(.*)$", l) for l in lines) if m}


def set_front(text, **props):
    """Set or remove (None) front-matter keys in a note's text, keeping the rest as written."""
    fl, body = split_front(text)
    fl = [l for l in fl if not any(re.match(rf"^{k}:", l) for k in props)]
    fl += [f'{k}: "{v}"' for k, v in props.items() if v is not None]
    return "---\n" + "\n".join(fl) + "\n---\n" + body.lstrip("\n") if fl else body


def progress_line(text, line):
    """A dated line under the note's Progress heading, made before the next moves when it does not exist yet."""
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    row = f"- {stamp} · {line}"
    if re.search(r"^## Progress[ \t]*$", text, re.M):
        head, rest = re.split(r"^## Progress[ \t]*$\n?", text, maxsplit=1, flags=re.M)
        nxt = re.search(r"^## ", rest, re.M)
        cut = nxt.start() if nxt else len(rest)
        return head + "## Progress\n" + rest[:cut].rstrip("\n") + "\n" + row + "\n\n" + rest[cut:]
    parts = re.split(r"(^" + re.escape(MOVES_HEAD) + r"[ \t]*$)", text, maxsplit=1, flags=re.M)
    block = "## Progress\n\n" + row + "\n\n"
    return parts[0].rstrip("\n") + "\n\n" + block + "".join(parts[1:]) if len(parts) > 1 else text.rstrip("\n") + "\n\n" + block


def note_path(vault, path):
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(vault)) if os.path.isabs(path) else path
    rel = rel.replace(os.sep, "/")
    p = os.path.join(vault, rel)
    if rel.startswith("..") or not rel.endswith(".md") or not os.path.isfile(p):
        print(f"not a note in the vault: {path}", file=sys.stderr); sys.exit(2)
    return rel, p


def move_note(vault, reports, rel, to, status=None, waits_on=None, wake=None, next_=None):
    """Move a note on the owner's word. Out of to-read it becomes a page whose source is the vault, so the sync
    never writes it again where it was nor overwrites it where it went; the move is logged as his. Into parked it
    carries who it waits on, since when and what brings it back, and offers only resume and drop; out of parked
    those go."""
    p = os.path.join(vault, rel)
    if to in ("drop", "delete"):                           # closed as dropped and kept, never removed
        return finish(vault, reports, rel, "drop")
    folder = {"in-progress": IN_PROGRESS, "archive": ARCHIVE, "to-read": TO_READ, "parked": PARKED, "readings": READINGS}[to]
    text = open(p, encoding="utf-8").read()
    kind = props_of(split_front(text)[0]).get("type")
    if folder == ARCHIVE:                                  # closing: its subject home when it has one
        folder = home_for(rel, props_of(split_front(text)[0]))
    life = kept_home(folder) or folder                     # a release line's folder lives as mh/releases
    if life == CASES:
        status = "closed"
    text = clear_warn(PROP_RE.sub("", text))
    st, result, nxt = settled_status(life, status, kind)
    nxt = next_ or nxt                                     # the move that ended it, as the runner names it
    if folder == PARKED:
        old = dict(m.groups() for m in (re.match(r"^([\w-]+):\s*['\"]?(.*?)['\"]?\s*$", l) for l in split_front(text)[0]) if m)
        text = set_front(text, source="vault", status=st, claimed=None, **{
            "waits-on": waits_on or old.get("waits-on") or "", "wake": wake or old.get("wake") or "",
            "parked": old.get("parked") if top(rel) == PARKED and old.get("parked") else datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            MOVE_SET: "parked", NEXT: ""})
    else:
        text = set_front(text, source="vault", status=st, claimed=None, **{"waits-on": None, "wake": None, "parked": None})
        if life in CLOSED_FOLDERS and next_ == "reopen":   # closed by ela, unruled: his one move is to reopen it
            text = set_front(text, **{MOVE_SET: "reopen", NEXT: "", "closed-by": "ela"})
        elif life in CLOSED_FOLDERS:                       # the outcome stays in next; status says only that it is closed
            text = set_front(text, **{MOVE_SET: "closed", NEXT: nxt or ""})
        elif life == CASES:                              # a case closes in its home, its outcome in next
            text = set_front(text, **{MOVE_SET: "case", NEXT: nxt or ""})
        elif folder == IN_PROGRESS:
            text = set_front(text, **{MOVE_SET: "built", NEXT: "", "closed-by": None})
        elif folder == READINGS:                           # a reading has no life: no status, no moves
            text = set_front(text, **{MOVE_SET: None, NEXT: None})
    dst = free_path(os.path.join(vault, folder), os.path.basename(rel), own=p)
    fl, body = split_front(text)
    body = with_moves(body, f"{folder}/{os.path.basename(dst)}", "parked" if folder == PARKED else kind if folder == TO_READ else None)
    text = "---\n" + "\n".join(fl) + "\n---\n" + body.lstrip("\n")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    atomic_write(dst, text)
    if os.path.realpath(dst) != os.path.realpath(p):
        os.remove(p)
        try:
            src = (json.load(open(os.path.join(vault, MANIFEST))).get("sources") or {}).get(rel)
        except (OSError, ValueError):
            src = None
        record_removed(os.path.join(reports, "ela", "vault-removed.jsonl"), [rel], {rel: src} if src else {},
                       datetime.datetime.now(), {os.path.basename(rel).lower(): folder}, by="owner")
    return f"{folder}/{os.path.basename(dst)}"


def cmd_note(a):
    """A note's life from any session or the runner: claim it (the watcher leaves its `ela:` lines to the session),
    release it, add a Progress line, mark it built (its acceptance moves follow), or move it."""
    s = json.load(open(SITE))
    vault, reports = s["vault"], s.get("reports") or ""
    rel, p = note_path(vault, a.path)
    text = open(p, encoding="utf-8").read()
    if a.act == "claim":
        atomic_write(p, set_front(text, claimed=datetime.datetime.now().astimezone().isoformat(timespec="seconds")))
        print(f"{rel}: claimed by this session")
    elif a.act == "release":
        atomic_write(p, set_front(text, claimed=None)); print(f"{rel}: released")
    elif a.act == "progress":
        line = " ".join(a.text)
        atomic_write(p, progress_line(set_front(text, progress=line[:120]), line)); print(f"{rel}: progress noted")
    elif a.act == "built":
        stamp = datetime.datetime.now().strftime("%m-%d %H:%M")
        text = progress_line(set_front(text, status="built", claimed=None, built=stamp, progress=" ".join(a.text)[:120]),
                             "built: " + " ".join(a.text))
        text = PROP_RE.sub("", text)
        fl0, b0 = split_front(text)
        text = "---\n" + "\n".join(fl0 + [f'{MOVE_SET}: "built"', f'{NEXT}: ""']) + "\n---\n" + b0
        fl, body = split_front(text)
        atomic_write(p, "---\n" + "\n".join(fl) + "\n---\n" + with_moves(body, rel, "built", stamp).lstrip("\n"))
        print(f"{rel}: built; waiting for the owner's acceptance")
    elif a.act == "move":
        print(f"{rel} → {move_note(vault, reports, rel, a.to, a.status, a.waits_on, a.wake, a.next)}")


def ensure_native_moves(vault, dry_run=False):
    """A page ela wrote in place in to-read gets its next moves once, by kind, if it has none. A note in parked/ gets
    only the fields its `next` chooser needs; its body is never rewritten there."""
    d = os.path.join(vault, PARKED)
    for f in sorted(os.listdir(d)) if os.path.isdir(d) and not dry_run else []:
        p = os.path.join(d, f)
        if f.endswith(".md"):
            fl, body = split_front(open(p, encoding="utf-8").read())
            missing = [w for w in (f'{MOVE_SET}: "parked"', f'{NEXT}: ""') if not any(l.startswith(w.split(":")[0] + ":") for l in fl)]
            if fl and missing:
                atomic_write(p, "---\n" + "\n".join(fl + missing) + "\n---\n" + body)
    d = os.path.join(vault, TO_READ)
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        p = os.path.join(d, f)
        if not f.endswith(".md"):
            continue
        text = open(p, encoding="utf-8").read()
        fl, body = split_front(text)
        if not any(re.match(r"^source:\s*['\"]?vault['\"]?\s*$", l) for l in fl):
            continue
        kind = props_of(fl).get("type")
        has_moves = re.search(r"^" + re.escape(MOVES_HEAD), body, re.M)
        # the same table properties a generated note to read carries, so its Home row has working boxes
        wanted = [f'{MOVE_SET}: "{move_set(kind)}"', f'{NEXT}: ""']
        missing = [w for w in wanted if not any(l.startswith(w.split(":")[0] + ":") for l in fl)]
        if MOVES.get(kind) and (not has_moves or missing) and not dry_run:
            fl = fl + missing
            body = body if has_moves else with_moves(body, f"{TO_READ}/{f}", kind)
            atomic_write(p, "---\n" + "\n".join(fl) + "\n---\n" + body.lstrip("\n"))


def guidance_id(name, says, nth=1):
    """A stable id for one `ela:` line or tick: the note's file name and the words, and for a repeat its count."""
    import hashlib
    return hashlib.sha256((f"{name}\0{says}" + (f"\0{nth}" if nth > 1 else "")).encode()).hexdigest()[:12]


def cmd_guidance(a):
    """The owner's instructions written into his notes: every line starting `ela:` anywhere in the vault (a generated
    note keeps his lines through its rewrite), with a stable id so a job handles each once (ids already in <reports>/ela/
    guidance-handled.jsonl are left out unless --all)."""
    import hashlib
    s = json.load(open(SITE))
    vault, reports = s["vault"], s.get("reports") or ""
    try:
        done = {json.loads(l).get("id") for l in open(os.path.join(reports, "ela", "guidance-handled.jsonl"), encoding="utf-8")}
    except (OSError, ValueError):
        done = set()
    lines = []
    try:
        source_ticks = json.load(open(os.path.join(vault, MANIFEST))).get("source_ticks") or {}
    except (OSError, ValueError):
        source_ticks = {}
    for top_, dirs, fs in os.walk(vault):
        dirs[:] = [d for d in dirs if not d.startswith(".") and os.path.relpath(os.path.join(top_, d), vault).replace(os.sep, "/") != ATTACH]
        if True:
            for f in sorted(fs):
                if not f.endswith(".md"):
                    continue
                p = os.path.join(top_, f)
                rel = os.path.relpath(p, vault).replace(os.sep, "/")
                text = open(p, encoding="utf-8").read()
                ticks = [x for x in TICKED.finditer(text) if x.group(1) not in source_ticks.get(rel, [])]
                # kind tells a typed line, which a watcher lets settle before taking it up, from a ticked box, a click
                found = [(x, "line") for x in GUIDE.finditer(text)] + [(x, "tick") for x in ticks]
                times = {}
                for m, kind in ((x, k) for x, k in found if x.group(1).strip('"\' ')):
                    # the same words written again in the note are a new instruction: the nth repeat has its own id, the
                    # first keeps the id it always had, so nothing already handled comes back
                    times[m.group(1)] = times.get(m.group(1), 0) + 1
                    gid = guidance_id(f, m.group(1), times[m.group(1)])
                    if a.all or gid not in done:
                        lines.append({"id": gid, "note": rel, "kind": kind, "says": m.group(1).strip().strip('"').strip("'"),
                                      "section": section_at(text, m.start())})
    r = {"guidance": lines,
         "handled_log": os.path.join(reports, "ela", "guidance-handled.jsonl")}
    if a.json:
        print(json.dumps(r, ensure_ascii=False)); return
    for g in lines:
        print(f"{g['id']}  {g['note']}: {g['says']}")
    print(f"{len(lines)} instructions")


def apply_marks(vault, reports, dry_run=False):
    """The move he chose in a note's `next` field. done and drop finish the note here, as if he had dragged or
    deleted it; every other move is reported for the runner, which acts and empties the field. A value that is not a
    move for that note runs nothing, and the note says so. Returns [(path, move)]."""
    out = []
    found = [(folder, rel) for folder in (TO_READ, IN_PROGRESS, PARKED) + CLOSED_FOLDERS for rel in notes_under(vault, folder)]
    for folder, rel in found:
        f = os.path.basename(rel)
        if not f.endswith(".md"):
            continue
        p = os.path.join(vault, rel)
        try:
            fl, _ = split_front(open(p, encoding="utf-8").read())
        except OSError:
            continue
        props = props_of(fl)
        if folder in CLOSED_FOLDERS and props.get(MOVE_SET) != "reopen":
            continue                                        # the owner's archive: only a note ela closed offers a move
        kind = "reopen" if folder in CLOSED_FOLDERS else "parked" if folder == PARKED else "built" if props.get("status") == "built" else props.get("type")
        allowed = move_props(kind, in_to_read=folder == TO_READ)
        # the earlier checkbox form, while a note still carries it
        boxes = [k for k in tuple(MARKS) + ALL_MOVE_PROPS if props.get(k, "").lower() == "true"]
        move = (props.get(NEXT) or "").strip().lower() or (boxes[0] if len(boxes) == 1 else "")
        if not move:
            continue
        if move not in allowed:
            if not dry_run:
                warn_move(p, move, allowed)
            continue
        out.append((rel, move))
        if move in tuple(MARKS) + ("seen",) and not dry_run:
            finish(vault, reports, rel, "archive", move)   # drop closes it too: kept, its next says drop
        elif move == "resume" and not dry_run:      # a script move: the note's next decision is his again
            move_note(vault, reports, rel, "to-read", "proposed")
        elif move == "reopen" and not dry_run:      # ela closed it wrongly: back to building's end, his to accept
            move_note(vault, reports, rel, "in-progress", "built")
    return out


MOVE_WARN = "> [!warning] Not a move for this note"


def warn_move(p, move, allowed):
    """A `next` value that is not one of the note's moves: said once under the title, until the field changes."""
    text = open(p, encoding="utf-8").read()
    fl, body = split_front(text)
    body = clear_warn(body)
    line = f"{MOVE_WARN}: `{move}`\n> Choose one of: {', '.join(allowed)}.\n\n"
    m = re.search(r"^#[ \t]+.*\n", body, re.M)
    body = body[:m.end()] + "\n" + line + body[m.end():].lstrip("\n") if m else line + body
    new = "---\n" + "\n".join(fl) + "\n---\n" + body
    if new != text:
        atomic_write(p, new)


def clear_warn(text):
    return re.sub(r"^" + re.escape(MOVE_WARN) + r".*\n(?:>.*\n)*\n?", "", text, flags=re.M)


def cmd_marks(a):
    s = json.load(open(SITE))
    done = apply_marks(s["vault"], s.get("reports") or "", a.dry_run)
    if a.json:
        print(json.dumps([{"note": p, "box": k} for p, k in done])); return
    for p, k in done:
        print(f"{p}: {k}")


def linked_from(vault, rel):
    """The notes that link this one by a wikilink, its name or its path; Home is rewritten each sync and does not count."""
    stem = os.path.basename(rel)[:-3].lower()
    rx = re.compile(r"\[\[(?:[^\]|#]*/)?" + re.escape(stem) + r"(?:\.md)?[\]|#]", re.I)
    out = []
    for top_, dirs, fs in os.walk(vault):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in fs:
            r = os.path.relpath(os.path.join(top_, f), vault).replace(os.sep, "/")
            if not f.endswith(".md") or r in (rel, "home.md"):
                continue
            try:
                if rx.search(open(os.path.join(top_, f), encoding="utf-8").read()):
                    out.append(r)
            except OSError:
                pass
    return sorted(out)


def finish(vault, reports, rel, to, move=None):
    """Close a note on the owner's word: into its subject home, else archive/, status closed and the move that closed
    it in next. `to` "drop" (or the older "delete") closes it the same way with next drop: ela never deletes a note
    (working preferences, *No data is lost*, 2026-11-09). Logged as his. Returns the folder."""
    p = os.path.realpath(os.path.join(vault, rel))
    if to in ("drop", "delete"):
        move = "drop"
    try:
        src = (json.load(open(os.path.join(vault, MANIFEST))).get("sources") or {}).get(rel)
    except (OSError, ValueError):
        src = None
    folder = home_for(rel, props_of(split_front(open(p, encoding="utf-8").read())[0]))
    os.makedirs(os.path.join(vault, folder), exist_ok=True)
    dst = free_path(os.path.join(vault, folder), os.path.basename(rel))
    os.replace(p, dst)
    text = clear_warn(PROP_RE.sub("", open(dst, encoding="utf-8").read()))   # the boxes belong to to-read
    if kept_home(folder):                                  # closed, and the move that closed it kept in next
        text = set_front(text, status="closed", **{MOVE_SET: "case" if folder == CASES else "closed", NEXT: move or "done"})
    open(dst, "w", encoding="utf-8").write(text)
    record_removed(os.path.join(reports, "ela", "vault-removed.jsonl"), [rel], {rel: src} if src else {},
                   datetime.datetime.now(), {os.path.basename(rel).lower(): folder}, by="owner")
    return folder


def cmd_finish(a):
    """Finish with a note on the owner's word (an `ela:` line asking it): close it into archive/ or its subject home,
    as done or as dropped, kept either way, and log it as his. Only a note in days/, to-read/ or readings/; a living
    page is not his to finish, and his own folders are already his."""
    s = json.load(open(SITE))
    vault = s["vault"]
    rel = a.path.replace("\\", "/").lstrip("/")
    p = os.path.realpath(os.path.join(vault, rel))
    if not p.startswith(os.path.realpath(vault) + os.sep) or top(rel) not in DELETABLE or not rel.endswith(".md") or not os.path.isfile(p):
        print(f"not a note in days/, to-read/ or readings/: {a.path}", file=sys.stderr); sys.exit(2)
    folder = finish(vault, s.get("reports") or "", rel, a.to)
    print(f"{rel}: closed into {folder}/ as {'dropped' if a.to in ('drop', 'delete') else 'done'}, kept; logged as the owner's")


def tidy_plan(vault, line_of_key=None):
    """Each kept note not yet in its home, with what would keep it from moving: [{note, to, blocked}]. A note directly
    in archive/ that has a subject home, and a note at the mh/releases/ root whose release line can be read
    (release_line), go there. A wikilink resolves by name, so a move breaks only a link that names the note's old
    folder in its path, or a name that another note in the vault shares; a note he put elsewhere by hand is never read
    here."""
    plan = []
    for folder in (ARCHIVE, RELEASES):
        d = os.path.join(vault, folder)
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            p = os.path.join(d, f)
            if not f.endswith(".md") or not os.path.isfile(p):
                continue
            try:
                props = props_of(split_front(open(p, encoding="utf-8").read())[0])
            except OSError:
                continue
            if folder == ARCHIVE:
                to = home_for(f"{ARCHIVE}/{f}", props, line_of_key)
            else:                                          # filed as a release note already: only its line is read
                line = release_line(props, line_of_key, f[:-3])
                to = f"{RELEASES}/{line}" if line else RELEASES
            if to != folder:
                plan.append({"note": f"{folder}/{f}", "to": f"{to}/{f}", "blocked": []})
    if not plan:
        return plan
    stems = {os.path.basename(x["note"])[:-3].lower(): x for x in plan}
    rx = re.compile(r"(?:\[\[|\]\()(" + "|".join(re.escape(f) for f in (ARCHIVE, RELEASES)) + r")/([^\]|#)]+?)(?:\.md)?[\]|#)]", re.I)
    for top_, dirs, fs in os.walk(vault):
        dirs[:] = [x for x in dirs if not x.startswith(".")]
        for f in fs:
            r = os.path.relpath(os.path.join(top_, f), vault).replace(os.sep, "/")
            if f[:-3].lower() in stems and r != stems[f[:-3].lower()]["note"] and f.endswith(".md"):
                stems[f[:-3].lower()]["blocked"].append(f"{r} has the same name")
            if not f.endswith((".md", ".base", ".canvas")):
                continue
            try:
                text = open(os.path.join(top_, f), encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            for m in rx.finditer(text):
                x = stems.get(m.group(2).lower())
                if x and x["note"].lower() == f"{m.group(1)}/{m.group(2)}.md".lower():
                    x["blocked"].append(f"{r} links it by its {m.group(1)}/ path")
    for x in plan:
        if os.path.exists(os.path.join(vault, x["to"])):
            x["blocked"].append(f"{x['to']} exists")
    return plan


def cmd_tidy(a):
    """Move the archived notes that have a subject home there (cases/, mh/releases/, ela/history/), and the notes at the
    mh/releases/ root into their release line's folder, by the rule a closing note follows (home_for). A dry run
    unless --apply; a note whose move would break a link stays."""
    s = json.load(open(SITE))
    vault = s["vault"]
    plan = tidy_plan(vault)
    moved = []
    if a.apply:
        for x in plan:
            if x["blocked"]:
                continue
            dst = os.path.join(vault, x["to"])
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(os.path.join(vault, x["note"]), dst)
            moved.append(x)
    r = {"dry_run": not a.apply, "plan": plan, "moved": len(moved), "blocked": sum(1 for x in plan if x["blocked"]),
         "by_home": {h: sum(1 for x in plan if x["to"].startswith(h + "/")) for h in SUBJECT_HOMES},
         "by_line": {l: sum(1 for x in plan if os.path.dirname(x["to"]) == f"{RELEASES}/{l}")
                     for l in sorted({os.path.dirname(x["to"])[len(RELEASES) + 1:] for x in plan if kept_home(os.path.dirname(x["to"])) == RELEASES} - {""})}}
    if a.json:
        print(json.dumps(r, ensure_ascii=False)); return
    for x in plan:
        print(f"{x['note']} → {x['to']}" + (f"  (stays: {'; '.join(x['blocked'])})" if x["blocked"] else ""))
    print(f"{'DRY RUN — ' if not a.apply else ''}tidy: {len(plan)} to their homes ("
          + ", ".join(f"{h} {n}" for h, n in r["by_home"].items()) + f"), {r['blocked']} held, {len(moved)} moved")


def cmd_restore(a):
    """Bring back a note the owner deleted: the next sync writes it again."""
    s = json.load(open(SITE))
    path = os.path.join(s.get("reports") or "", "ela", "vault-removed.jsonl")
    paths, srcs = load_removed(path)
    try:                                                   # the note's source under the current layout, from the manifest
        src = (json.load(open(os.path.join(s["vault"], MANIFEST))).get("sources") or {}).get(a.path)
    except (OSError, ValueError, KeyError):
        src = None
    if a.path not in paths and src not in srcs:
        print(f"not among the deleted notes: {a.path}", file=sys.stderr); sys.exit(2)
    row = {"at": datetime.datetime.now().isoformat(timespec="seconds"), "path": a.path, "restored": True}
    if src:
        row["src"] = src
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    print(f"restored: {a.path}; the next sync writes it again")


def top(rel):
    return rel.split("/")[0]


def digest(text):
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def atomic_write(path, text):
    tmp = path + ".ela-tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


WRITERS = ("sync", "marks", "finish", "note", "restore", "setup", "afterwards", "tidy", "lint")   # guidance only reads; lint writes with --fix --apply


def vault_lock():
    """The vault's one lock (<runtime>/vault-sync.lock): a sync, a tick handled, a note moved or a progress line written
    each read-modify-write notes, and the Slack watcher runs them while a sync may be running. One at a time."""
    try:
        runtime = json.load(open(SITE)).get("runtime") or "/tmp"
    except (OSError, ValueError):
        runtime = "/tmp"
    os.makedirs(runtime, exist_ok=True)
    lock = open(os.path.join(runtime, "vault-sync.lock"), "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    return lock


def cmd_sync(a):
    s = json.load(open(SITE))
    vault = s.get("vault")
    if not vault or not os.path.isdir(vault):
        print(f"site.json `vault` is not a folder: {vault}", file=sys.stderr); sys.exit(2)
    env = a.env_file or s.get("env")
    today, now = datetime.date.today(), datetime.datetime.now()
    mpath = os.path.join(vault, MANIFEST)
    old, old_src, old_layout, old_gen, old_seen, old_home = [], {}, None, {}, {}, {}
    if os.path.exists(mpath):
        try:
            m = json.load(open(mpath))
            old, old_src, old_layout, old_gen, old_seen = (m["files"], m.get("sources") or {}, m.get("layout"), m.get("generated") or {},
                                                           m.get("seen") or {})
            old_home = m.get("home") or {}
        except (ValueError, KeyError):
            print("vault: the manifest is unreadable; not synced (remove it deliberately to start over)", file=sys.stderr); sys.exit(3)
    # a note the sync wrote that is gone from disk was deleted by the owner: that is feedback, and it stays deleted
    removed_path = os.path.join(s.get("reports") or "", "ela", "vault-removed.jsonl")
    marked = [] if a.dry_run else apply_marks(vault, s.get("reports") or "")   # ticked boxes first: they are his moves
    answered = answered_readings(vault, s.get("reports") or "", a.dry_run)
    rolled = meeting_roll(vault, today, a.dry_run)
    for fix in settle_statuses(vault, a.dry_run):
        print(f"status: {fix}", file=sys.stderr)
    if not a.dry_run:
        write_move_sets(vault)                             # the choosers follow MOVE_PROPS without a setup run
    removed, removed_src = load_removed(removed_path)
    # only a dated note in a reading folder can be done with; a living page (Home, the board, the library index, how
    # ela runs) is rewritten whatever happens to it
    newly = sorted(r for r in old if r.endswith(".md") and r not in removed and top(r) in DELETABLE
                   and not os.path.exists(os.path.join(vault, r)))
    archived = archive_names(vault)
    kept = [r for r in newly if os.path.basename(r).lower() in archived]
    mass = len(newly) - len(kept) > MASS_DELETE
    if mass:
        print(f"vault: {len(newly) - len(kept)} notes vanished in one go; not recorded as read, written again (a move or a wipe, "
              "not reading)", file=sys.stderr)
        newly = kept
    # "done since you last looked": each opening of Home (a sync that finds it open after one that did not) is
    # remembered; while it is open, Home counts from the opening before, so the count he reads stays put
    is_open = home_open(vault)
    opening = is_open and not old_home.get("open")
    looked = now.astimezone().isoformat(timespec="seconds") if opening else old_home.get("looked")
    before = old_home.get("looked") if opening else old_home.get("before")
    since = before if is_open else looked
    try:
        planned, files, notes, warnings, native_paths, inferred = plan(s, env, today, now, removed | set(newly),
                                                                        removed_src | {old_src[r] for r in newly if old_src.get(r)},
                                                                        since, a.dry_run)
    except SourceError as e:
        print(f"vault: not synced — {e}", file=sys.stderr); sys.exit(3)
    if newly and not a.dry_run:
        record_removed(removed_path, newly, old_src, now, archived)
    removed |= set(newly)
    # a note the layout moved (a review from to-read/ to readings/) is moved on disk before it is rewritten, so his
    # `ela:` lines and ticks go with it; a note already at its new place is left as it is
    old_at = {src: r for r, src in old_src.items() if r in old and r not in removed and top(r) not in RETIRED}
    moved = sorted((old_at[n.src_rel], n.path) for n in notes if n.src_rel in old_at and old_at[n.src_rel] != n.path
                   and os.path.exists(os.path.join(vault, old_at[n.src_rel])) and not os.path.exists(os.path.join(vault, n.path)))
    if not a.dry_run:
        for r, dst in moved:
            os.makedirs(os.path.dirname(os.path.join(vault, dst)), exist_ok=True)
            os.replace(os.path.join(vault, r), os.path.join(vault, dst))
    # counted from the day the note entered the vault (the manifest's `seen`), not from the day its source was written
    seen = {r: old_seen.get(r) or today.isoformat() for r in planned if r.endswith(".md")}
    now_files = set(planned) | {dst for src, dst in files}
    if not a.force:
        # the notes as a whole halving is a failure until shown to be a removal (a source that read empty, a broken
        # path); the owner's own finishing and the archive are already out of the count, and single folders shrink by
        # design (to-read empties as he reads)
        native_lower = {p.lower() for p in native_paths}
        had = sum(1 for r in old if r.endswith(".md") and r not in removed and r.lower() not in native_lower)
        after = sum(1 for r in planned if r.endswith(".md"))
        if had >= 10 and after < had / 2:
            print(f"vault: not synced — the notes would shrink from {had} to {after}; --force if that is intended", file=sys.stderr)
            sys.exit(3)
    listing = {}

    def names_in(d):
        if d not in listing:
            listing[d] = set(os.listdir(d)) if os.path.isdir(d) else set()
        return listing[d]
    wrote, same = [], 0
    answers = load_answers(s.get("reports") or "") + load_pending(s.get("reports") or "")
    answer_native(vault, answers, a.dry_run)
    ensure_native_moves(vault, a.dry_run)
    # a task its source already ticked is not his choice; recorded so the guidance verb tells the two apart
    source_ticks = {r: [m.group(1) for m in TICKED.finditer(t)] for r, t in planned.items() if r.endswith(".md") and TICKED.search(t)}
    for rel in [r for r in planned if r.endswith(".md")]:  # his `ela:` lines in a generated note outlive its rewrite
        try:
            disk = open(os.path.join(vault, rel), encoding="utf-8").read()
        except OSError:
            continue
        dfl, dbody = split_front(disk)
        planned[rel] = keep_choice(planned[rel], dfl, rel)   # the move he chose waits for the watcher, not for this rewrite
        for m in TICKED.finditer(dbody):                   # a choice he ticked stays ticked when the page is rewritten
            planned[rel] = re.sub(r"^(\s*" + QUOTE + r"[-*]\s+)\[ \](\s+" + re.escape(m.group(1)) + r"\s*)$", r"\1[x]\2", planned[rel], count=1, flags=re.M)
        mine = [(section_at(dbody, m.start()), m.group(0).strip()) for m in GUIDE.finditer(dbody) if m.group(0).strip() not in planned[rel]]
        # a word typed in the ela property, which the tables no longer offer, stays as a line in the note, written as
        # typed so its guidance id is the one already handled
        said = next((l.strip() for l in dfl if re.match(r'^ela:\s*\S', l) and not re.match(r'^ela:\s*""\s*$', l)), None)
        if said and said not in planned[rel] and said not in [l for _, l in mine]:
            mine.append((None, said))
        if mine:
            planned[rel] = place_lines(planned[rel], mine)
        planned[rel] = with_answers(planned[rel], rel, answers)   # each ask shows its answer under it
    for rel, text in planned.items():
        p = os.path.join(vault, rel)
        d, name = os.path.split(p)
        present = names_in(d)
        if name in present:
            if rel.endswith(".base") and old_gen.get(rel) == digest(text):
                same += 1; continue                       # Obsidian rewrites a base in its own style; ours has not changed
            try:
                if open(p, encoding="utf-8").read() == text:
                    same += 1; continue
            except OSError:
                pass
        wrote.append(rel)
        if a.dry_run:
            continue
        os.makedirs(d, exist_ok=True)
        stale = next((f for f in present if f != name and f.lower() == name.lower()), None)
        if stale:                                          # the disk is case-insensitive: rename, then write
            os.rename(os.path.join(d, stale), p)
        atomic_write(p, text)
        present.add(name)
    copied = 0
    for src, rel in files:
        dst = os.path.join(vault, rel)
        st = os.stat(src)
        try:
            dt = os.stat(dst)
            if dt.st_size == st.st_size and int(dt.st_mtime) == int(st.st_mtime):
                continue
        except OSError:
            pass
        copied += 1
        if not a.dry_run:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst + ".ela-tmp"); os.replace(dst + ".ela-tmp", dst)
    lower = {r.lower() for r in now_files}
    native_lower = {p.lower() for p in native_paths}
    # a note that leaves because it was acted on (its verification record went up to Jira, its plan or decision was
    # ruled on) is archived by ela, once, at that moment; one that merely expired is removed
    posted = posted_to_jira(s.get("reports") or "")
    def acted(r):
        src = old_src.get(r) or ""
        key = (re.match(r"^verify/([A-Z][A-Z0-9]+-\d+)-(\d{4}-\d{2}-\d{2})", src) or [None, None, None])
        if key[1]:
            return any(at[:10] >= key[2] for at in posted.get(key[1], []))
        return src.startswith("blueprint/") and ruled(s.get("elak"), src)
    to_archive = sorted(r for r in set(old) - now_files if r.endswith(".md") and top(r) == TO_READ and acted(r)
                        and os.path.exists(os.path.join(vault, r)))
    homes = {}                                             # each to its subject home, else archive/
    for r in to_archive:
        try:
            homes[r] = home_for(r, props_of(split_front(open(os.path.join(vault, r), encoding="utf-8").read())[0]))
        except OSError:
            homes[r] = ARCHIVE
    if to_archive and not a.dry_run:
        for r in to_archive:
            os.makedirs(os.path.join(vault, homes[r]), exist_ok=True)
            os.replace(os.path.join(vault, r), free_path(os.path.join(vault, homes[r]), os.path.basename(r)))
        record_removed(removed_path, to_archive, old_src, now, {os.path.basename(r).lower(): homes[r] for r in to_archive}, by="ela")
    keep_dirs = archive_refs(vault)
    gone = sorted(r for r in set(old) - now_files if not r.startswith(".obsidian") and r.lower() not in lower
                  and r.lower() not in native_lower and not any(r.lower().startswith(d + "/") for d in keep_dirs)
                  and top(r) not in RETIRED and r not in {f for f, _ in moved})
    left = sorted(r for r in set(old) - now_files if top(r) in RETIRED)   # the owner's now; never removed by the sync
    if not a.dry_run:
        # the manifest first: a crash before the removals leaves files it no longer lists, never removals it would
        # later read as the owner's deletions
        atomic_write(mpath, json.dumps({"synced": now.isoformat(timespec="seconds"), "layout": LAYOUT, "files": sorted(now_files),
                                        "sources": {n.path: n.src_rel for n in notes if n.src_rel},
                                        "generated": {r: digest(t) for r, t in planned.items() if r.endswith(".base")},
                                        "seen": {r: d for r, d in seen.items() if r in planned},
                                        "home": {"open": is_open, "looked": looked, "before": before},
                                        "source_ticks": source_ticks}, indent=0))
        for rel in gone:
            try:
                os.remove(os.path.join(vault, rel))
            except OSError:
                pass
        for d in sorted({os.path.dirname(r) for r in gone if os.path.dirname(r)}, key=lambda x: -x.count("/")):
            parts = d.split("/")
            for i in range(len(parts), 0, -1):
                try:
                    os.rmdir(os.path.join(vault, *parts[:i]))
                except OSError:
                    break
    held = [{"note": n.path, "problems": n.held} for n in notes if n.held]
    in_archive = sum(len([f for f in fs if f.endswith(".md")]) for d in OWNER_FOLDERS for _, _, fs in os.walk(os.path.join(vault, d)))
    counts = {"generated": len(planned), "in_place": len(native_paths), "archived": in_archive}
    r = {**counts, "dry_run": a.dry_run, "deleted_by_owner": newly, "archived_by_ela": to_archive, "moved": [{"from": f, "to": t} for f, t in moved],
         "answered": [{"from": f, "to": t} for f, t in answered],
         "rolled": [{"note": f, "date": d, "to": t} for f, d, t in rolled],
         "left_in_retired": left, "notes": len(planned), "written": len(wrote), "unchanged": same, "files_copied": copied,
         "removed": gone, "held": held, "warnings": warnings, "projects": [{"note": p, "project": k} for p, k in inferred]}
    if a.json:
        print(json.dumps(r, ensure_ascii=False)); return
    print(f"{'DRY RUN — ' if a.dry_run else ''}vault: {counts['generated']} generated · {counts['in_place']} in place · "
          f"{counts['archived']} archived ({len(wrote)} written, {same} unchanged), "
          f"{copied} files copied, {len(moved)} moved, {len(gone)} removed, {len(held)} under a warning")
    for f, t in moved:
        print(f"  moved {f} → {t}")
    for r in left:
        print(f"  left for the owner (retired folder, no longer synced): {r}")
    for g in gone[:20]:
        print(f"  removed {g}")
    if len(gone) > 20:
        print(f"  … and {len(gone) - 20} more (--json lists them all)")
    for f, t in answered:
        print(f"  every ask answered, moved to readings: {f}" + (f" → {t}" if t else ""))
    for d in to_archive:
        print(f"  acted on, archived by ela: {d}")
    for f, d, t in rolled:
        print(f"  ruled {d}, over {MEETING_RULED_DAYS} days: {f} → {t}")
    for d in newly:
        print(f"  deleted by the owner, recorded as read: {d}")
    for p_, k in inferred:
        print(f"  project {k} inferred from its keys: {p_}")
    for h in held:
        print(f"  warning {h['note']}: {'; '.join(h['problems'])}")
    for w in warnings:
        print(f"  note: {w}", file=sys.stderr)


# ── the archive keeps listening: Afterwards ───────────────────────────────────────────────────────────
# A note that sent something out (`posted:` permalinks) or follows tickets (`keys:`) is watched for a window after it
# leaves to-read: the threads' replies and the keys' status changes and comments since `watched:` become one dated line
# per source per day under its own `## Afterwards`, append-only; nothing else in the note is rewritten (vault
# to-read/2026-10-30-vault-workflow-review.md, proposal 5). The reading is brief.py's parked watcher, pointed here.
AFTERWARDS_HEAD = "## Afterwards"
WATCH_FOLDERS = OWNER_FOLDERS + (IN_PROGRESS, PROJECTS)   # a project page, and what its folder keeps, carries keys and threads too
WATCH_DAYS = {"review": 14, "decision": 14, "plan": 14, "meeting": 14, "verify": 30, "ticket": 30, "case": 30}   # calendar days from archived, else its date
WATCH_WORKDAYS = 10              # any other type: working days, counted the same way
WATCH_NOTES, WATCH_LINES = 40, 40   # at most 40 notes a pass, oldest window first; at most 40 lines a note
PERMALINK = re.compile(r"https://[\w.-]+\.slack\.com/archives/[^\s\"'\],)>]+")
STAMP_KEYS = 8                   # an archived note's subject: the keys of its title and opening, not every key it cites


def archive_stamp(text, today):
    """What an archived note is watched by, read from its own text the first pass after it reaches archive/: its subject
    keys (the title and the part above the first `##`, where the status block sits; a key the body only cites would
    flood the Afterwards), every Slack thread it links, and the day the window counts from. None for a note that
    already carries keys, posted or archived, so a pass never re-stamps one or overrides the writer's own choice."""
    fl, body = split_front(text)
    props = props_of(fl)
    if any(k in props for k in ("keys", "posted", "archived")):
        return None
    m = re.search(r"^##[ \t]", body, re.M)
    head = (props.get("title") or "") + "\n" + (body[:m.start()] if m else body)
    keys = list(dict.fromkeys(k for k in KEY_RX.findall(head) if not NOT_KEYS.match(k)))[:STAMP_KEYS]
    links = list(dict.fromkeys(l.rstrip(".") for l in PERMALINK.findall(body)))
    return {"archived": today.isoformat(), "keys": " ".join(keys) or None, "posted": " ".join(links) or None}


def stamp_archive(vault, today, dry_run=False):
    """Stamp every note in archive/ or a subject home not yet stamped, however it got there: finish, a ticked box, a
    script move or his drag in Obsidian. Returns {rel: stamp}; a dry run writes nothing and the caller reads the stamps
    as if written."""
    out = {}
    for rel in (r for fo in OWNER_FOLDERS for r in notes_under(vault, fo)):   # a release line's folder included
        p = os.path.join(vault, rel)
        text = open(p, encoding="utf-8").read()
        stamp = archive_stamp(text, today)
        if stamp:
            out[rel] = stamp
            if not dry_run:
                atomic_write(p, set_front(text, **stamp))
    return out


def plus_workdays(d, n):
    while n > 0:
        d += datetime.timedelta(days=1)
        n -= d.weekday() < 5
    return d


def watch_until(props):
    """The last day a note is watched: its `watch` (a date, or "until DATE"), else its type's window from its date; None
    when `watch` is present and empty (he cleared it: stop) or the note has no date to count from."""
    if "watch" in props:
        m = re.search(r"\d{4}-\d{2}-\d{2}", props.get("watch") or "")
        return datetime.date.fromisoformat(m.group(0)) if m else None
    m = re.match(r"\d{4}-\d{2}-\d{2}", props.get("deadline") or "") if props.get("type") == "project" else None
    if m:                                                  # a project: until its deadline plus 14 days
        return datetime.date.fromisoformat(m.group(0)) + datetime.timedelta(days=PROJECT_WATCH_DAYS)
    m = re.match(r"\d{4}-\d{2}-\d{2}", props.get("archived") or props.get("date") or "")
    if not m:
        return None
    d = datetime.date.fromisoformat(m.group(0))
    kind = props.get("type")
    return d + datetime.timedelta(days=WATCH_DAYS[kind]) if kind in WATCH_DAYS else plus_workdays(d, WATCH_WORKDAYS)


def watched_notes(vault, today, stamps=None):
    """The notes in archive/, the subject homes, in-progress/ and projects/ carrying `posted:` or `keys:` whose window is open today, oldest window
    first, at most WATCH_NOTES: [{note, props, keys, links, until}]. `stamps` are a dry run's unwritten archive stamps."""
    out = []
    for folder in WATCH_FOLDERS:
        for top_, dirs, fs in os.walk(os.path.join(vault, folder)):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in sorted(fs):
                if not f.endswith(".md"):
                    continue
                try:
                    props = props_of(split_front(open(os.path.join(top_, f), encoding="utf-8").read())[0])
                except OSError:
                    continue
                rel = os.path.relpath(os.path.join(top_, f), vault).replace(os.sep, "/")
                props.update({k: v for k, v in ((stamps or {}).get(rel) or {}).items() if v is not None})
                keys = sorted({k for k in KEY_RX.findall(props.get("keys") or "") if not NOT_KEYS.match(k)})
                links = sorted(set(PERMALINK.findall((props.get("posted") or "") + " " + (props.get("channels") or ""))))
                until = watch_until(props)
                if (keys or links) and until and until >= today:
                    out.append({"note": rel, "props": props,
                                "keys": keys, "links": links, "until": until})
    return sorted(out, key=lambda w: (w["until"], w["note"]))[:WATCH_NOTES]


def afterwards_lines(woke, jira_base=""):
    """brief.parked_row's wake events as dated lines, one per source per day, in ela's words: who moved a key where,
    who commented or replied, and the link; never what a colleague wrote. [(ref, date, line)]"""
    groups = {}
    for w in woke:
        at = parse_at(w.get("at"))
        if at:
            groups.setdefault((w["ref"], at.astimezone().date().isoformat()), []).append(w)
    out = []
    for (ref, day), ws in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        ws.sort(key=lambda w: w.get("at") or "")
        def names(kind):
            return ", ".join(dict.fromkeys(w.get("who") or "someone" for w in ws if w.get("kind") == kind))
        if ws[0]["source"] == "slack":
            line = f"thread: {'a reply' if len(ws) == 1 else f'{len(ws)} replies'} from {names('reply')} → [thread]({ref})"
        else:
            bits = [f"{w.get('from')} → {w.get('to')} ({w.get('who')})" for w in ws if w.get("kind") == "status"]
            if names("comment"):
                bits.append(f"a comment from {names('comment')}")
            line = (f"[{ref}]({jira_base}/browse/{ref})" if jira_base else ref) + ": " + "; ".join(bits)
        out.append((ref, day, f"- {day[5:]} · {line}"))
    return out


def parse_at(s):
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.datetime.strptime(s or "", fmt)
        except ValueError:
            continue
    return None


def with_afterwards(text, lines):
    """The note with its Afterwards lines: a line for a (ref, day) already there is brought up to date in place, a new
    one appended, at most WATCH_LINES; the section sits at the note's end, above its next moves. Nothing else changes.
    Returns (text, [(ref, day, line)] newly appended)."""
    fl, body = split_front(text)
    m = re.search(r"^" + re.escape(AFTERWARDS_HEAD) + r"[ \t]*\n", body, re.M)
    if m:
        nxt = re.search(r"^#{1,2}[ \t]", body[m.end():], re.M)
        end = m.end() + (nxt.start() if nxt else len(body) - m.end())
        head, sec, tail = body[:m.start()], body[m.end():end], body[end:]
    else:
        moves = re.search(r"^" + re.escape(MOVES_HEAD) + r"[ \t]*$", body, re.M)
        cut = moves.start() if moves else len(body)
        head, sec, tail = body[:cut].rstrip("\n") + "\n\n", "", ("\n" + body[cut:]) if moves else ""
    rows = [l for l in sec.strip("\n").splitlines() if l.strip()]
    new = []
    for ref, day, line in lines:
        at = next((i for i, l in enumerate(rows) if l.startswith(f"- {day[5:]} · ") and ref in l), None)
        if at is not None:
            rows[at] = line
        elif sum(1 for l in rows if l.startswith("- ")) < WATCH_LINES:
            rows.append(line); new.append((ref, day, line))
    if not rows:
        return text, []
    body = head + AFTERWARDS_HEAD + "\n\n" + "\n".join(rows) + "\n" + tail
    return ("---\n" + "\n".join(fl) + "\n---\n" + body if fl else body), new


def cmd_afterwards(a):
    """Read what happened after each watched note left to-read and append it under the note's Afterwards, first stamping
    the archived notes not yet stamped (archive_stamp); the runner calls this at 13:00, 17:30 and 19:00. Reads only; writes the vault and <reports>/ela/afterwards.jsonl."""
    s = json.load(open(SITE))
    vault, reports = s["vault"], s.get("reports") or ""
    env = a.env_file or s.get("env")
    e = ["--env-file", env] if env else []
    now = datetime.datetime.now().astimezone()
    sys.path.insert(0, os.path.join(HERE, "..", "brief"))
    import brief as B                                       # the parked watcher: key events and thread replies since a time
    since_arg = None
    if a.since:
        rel = re.match(r"^-(\d+)d$", a.since)
        since_arg = (now - datetime.timedelta(days=int(rel.group(1)))).date() if rel else datetime.date.fromisoformat(a.since)
    stamps = stamp_archive(vault, now.date(), a.dry_run)
    watched = watched_notes(vault, now.date(), stamps if a.dry_run else None)
    for w in watched:                                      # from the start of the day last watched: a day's line is whole
        day = re.match(r"\d{4}-\d{2}-\d{2}", w["props"].get("watched") or w["props"].get("date") or "")
        w["since"] = since_arg or (datetime.date.fromisoformat(day.group(0)) if day else now.date())
    gaps, jira_rows, threads = [], [], {}
    jira_base = ""
    if env and os.path.isfile(env):
        jira_base = next((l.split("=", 1)[1].strip().rstrip("/") for l in open(env) if l.startswith("JIRA_BASE_URL=")), "")
    me = B.owner_jira_name(e) if watched else None
    keys = sorted({k for w in watched for k in w["keys"]})
    first = min((w["since"] for w in watched), default=now.date())
    for proj in sorted({k.split("-")[0] for k in keys}):
        try:
            got = B.run_json(["python3", JIRA, *e, "changes", "--project", proj, "--since", f"{first.isoformat()} 00:00",
                              "--limit", "400", "--json"])
            jira_rows += [r for r in got["issues"] if r["key"] in keys]
        except (B.LaneError, subprocess.TimeoutExpired, ValueError) as x:
            gaps.append({"source": f"jira {proj}", "error": str(x)[:200]})
    for link in sorted({l for w in watched for l in w["links"]}):
        try:
            threads[link] = B.run_json(["python3", B.SLACK, *e, "read", link, "--json"], timeout=120)
        except (B.LaneError, subprocess.TimeoutExpired, ValueError) as x:
            gaps.append({"source": "slack", "error": str(x)[:200]})
    try:
        logged = {(r.get("note"), r.get("ref"), r.get("date")) for r in
                  (json.loads(l) for l in open(os.path.join(reports, "ela", "afterwards.jsonl"), encoding="utf-8") if l.strip())}
    except (OSError, ValueError):
        logged = set()
    out_lines, log = [], []
    for w in watched:
        n = {"note": w["note"], "title": w["props"].get("title") or w["note"], "waits_on": None,
             "parked": f"{w['since'].isoformat()} 00:00", "wake": " ".join(w["keys"] + w["links"])}
        lines = afterwards_lines(B.parked_row(n, jira_rows, threads, me, now)["woke"], jira_base)
        p = os.path.join(vault, w["note"])
        text = open(p, encoding="utf-8").read()
        new_text, _ = with_afterwards(text, lines)
        stamp = {"watched": now.strftime("%Y-%m-%d %H:%M")}
        if lines:
            stamp["last"] = max(d for _, d, _ in lines)
        new_text = set_front(new_text, **stamp)
        for ref, day, line in lines:
            out_lines.append({"note": w["note"], "ref": ref, "date": day, "line": line})
            if (w["note"], ref, day) not in logged:
                log.append({"at": now.isoformat(timespec="seconds"), "note": w["note"], "ref": ref, "date": day, "line": line})
        if not a.dry_run and new_text != text:
            atomic_write(p, new_text)
    if log and not a.dry_run:
        os.makedirs(os.path.join(reports, "ela"), exist_ok=True)
        with open(os.path.join(reports, "ela", "afterwards.jsonl"), "a", encoding="utf-8") as fh:
            fh.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in log)
    r = {"dry_run": a.dry_run, "since": (since_arg or first).isoformat(), "notes": [w["note"] for w in watched],
         "stamped": sorted(stamps),
         "lines": out_lines, "appended": len(log), "watched": len(watched), "gaps": gaps}
    if a.json:
        print(json.dumps(r, ensure_ascii=False)); return
    print(f"{'DRY RUN — ' if a.dry_run else ''}afterwards: {len(stamps)} archived notes stamped, {len(watched)} notes watched, "
          f"{len(log)} new lines, {len(out_lines)} in all")
    for l in out_lines:
        print(f"  {l['note']}: {l['line']}")
    for g in gaps:
        print(f"  gap {g['source']}: {g['error']}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", help="ela's env file; its Jira base URL turns ticket keys into links")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sync", help="regenerate the vault from the reports root and elak's decisions and plans")
    p.add_argument("--dry-run", action="store_true", help="report what would change; write nothing")
    p.add_argument("--force", action="store_true", help="sync although the notes as a whole shrink by more than half")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_sync)
    p = sub.add_parser("setup", help="apply the vault's Obsidian settings from ela's versioned copy, then restart Obsidian")
    p.set_defaults(func=cmd_setup)
    p = sub.add_parser("guidance", help="the owner's `ela:` lines anywhere in the vault")
    p.add_argument("--all", action="store_true", help="include instructions already handled")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_guidance)
    p = sub.add_parser("marks", help="finish the to-read notes whose done or drop box is ticked (no session)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_marks)
    p = sub.add_parser("finish", help="on the owner's word: close a note into archive/ or its subject home, kept (drop or done)")
    p.add_argument("path", help="the note's path in the vault, e.g. to-read/2026-09-07-mh-review.md")
    p.add_argument("--to", choices=("drop", "archive", "delete"), default="drop", help="delete: the older name of drop; nothing is deleted")
    p.set_defaults(func=cmd_finish)
    p = sub.add_parser("note", help="a note's life: claim, release, progress TEXT, built TEXT, move --to in-progress|parked|archive|to-read|readings|drop")
    p.add_argument("act", choices=("claim", "release", "progress", "built", "move"))
    p.add_argument("path", help="the note's path in the vault, e.g. to-read/2026-10-26-system-plan.md")
    p.add_argument("text", nargs="*", help="progress or built: the line to record")
    p.add_argument("--to", choices=("in-progress", "parked", "archive", "to-read", "readings", "drop", "delete"))
    p.add_argument("--status", help="move: the status the note carries after it, settled to its folder's own (an archived "
                                    "outcome such as accepted goes to next)")
    p.add_argument("--next", help="move --to archive: the move that ended the note (make-plan, nudge, draft-comment, …), "
                                  "kept in its next field; without it an outcome --status is read as one")
    p.add_argument("--waits-on", help="move --to parked: who it waits on, and where")
    p.add_argument("--wake", help="move --to parked: what brings it back (a Slack thread, a ticket key)")
    p.set_defaults(func=cmd_note)
    p = sub.add_parser("afterwards", help="append what happened since to each watched note in archive/, cases/, the other subject homes and in-progress/ "
                                          "(its posted threads' replies, its keys' changes)")
    p.add_argument("--since", help="read from this day (YYYY-MM-DD or -Nd) instead of each note's watched")
    p.add_argument("--dry-run", action="store_true", help="read and report; write nothing")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_afterwards)
    p = sub.add_parser("lint", help="every note against its type's spec (the readme's Note standards), one line per deviation")
    p.add_argument("--fix", action="store_true", help="normalise what is mechanical: a title quoted, plain, first among its aliases")
    p.add_argument("--apply", action="store_true", help="with --fix, write; without it, a dry run")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_lint)
    p = sub.add_parser("tidy", help="move the archived notes that have a subject home (cases/, mh/releases/, ela/history/) "
                                    "there, and mh/releases/ root notes into their line's folder; a dry run unless --apply")
    p.add_argument("--apply", action="store_true", help="move them; without it, list the moves and what holds any back")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_tidy)
    p = sub.add_parser("restore", help="bring back a note the owner deleted in the vault")
    p.add_argument("path", help="the note's path in the vault, as the deletion log lists it")
    p.set_defaults(func=cmd_restore)
    a = ap.parse_args()
    if a.cmd in WRITERS:                                   # every writer of the vault takes the same lock as the sync
        hold = vault_lock()                                # noqa: F841  (held until the process exits)
    a.func(a)


if __name__ == "__main__":
    main()
