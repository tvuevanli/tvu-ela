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
    vault.py finish <path> [--to drop|archive]   on his word: a note done where it is, kept
    vault.py migrate [--apply] [--slug KEY=WORDS] [--json]   the one pass to layout 5; a dry run unless --apply
    vault.py lint [--fix [--apply]] [--json]   every note against its type's spec; --fix normalises front matter
    vault.py setup                   apply the Obsidian settings kept in obsidian/ (after a reset or on a new machine)

Layout 5, things and angles (ela ADR 0015). The vault holds things (what the owner tracks, one home each, everything
about a thing in that home) and angles (the same things told for one reader at one moment, storing nothing of their
own). Eight roots, full lowercase nouns; a dated note is <date>-<kind>-<what>.md and its folder carries the subject.
A work note (decision, plan, sprint, review, ticket, verify, verify-plan, draft) is `live` or `done`, a property: a
move sets it, never the folder. A vault in another layout is not synced: `vault.py migrate` lists the one pass, and
`--apply` makes it; for 14 days an old path given to a verb is read as its new one.
    today.md                                    the one page: facts, at most three asks, today (ADR 0014); home.md
                                                points to it until 2026-11-25
    meetings/<audience>.md                      one page per meeting, team-facing
    projects/<key>-<slug>.md                    a project's page: the desk's head above the sync's first heading, the
                                                tail below (Where it stands, Notes, Keys and threads, Afterwards,
                                                Deadline); projects/<key>-<slug>/ holds the page and its notes once
                                                they sit beside it; `ela project list|show|new|keys`
    releases/lanes.md                           the lanes across lines (ela matrix --page)
    releases/<line>/                            a release line: release-<line>-record.md the way in, each promote,
                                                deploy, docker check and hotfix, verifications, and the line's
                                                train-<line>.md, dev-list-<line>.md and test-list-<lane>.md
    cases/<date>-<customer>-<what>.md           one note per customer case (open, answered, closed)
    reference/                                  what serves no single thing: a product review, engineering management,
                                                the day pages (reference/days/<year>/<date>-brief|changes.md, kept),
                                                one-thing.md (his rows to paste), dropped.md (asks that left today)
    ela/                                        ela's own: about this vault, the ela page, how ela runs, the service map,
                                                the Jira vocabulary, the table view, history/, moves/, attachments/
    archive/                                    what he put away; ela never rewrites its text
The board, recent, the constraints page, the week and the reader pages are not written into the vault: nothing
consumed them there; their verbs render them on demand and their sources stay under the reports root.

The reading gate. The vault is how ela reports to the owner, so a note over its reading budget, mostly code, or
carrying machine paths is still written, under a warning that names the problem, and Home lists it for 30 days
as a rewrite ela owes. Nothing readable is withheld; nothing unreadable passes unmarked.

Safety. A missing or unreadable source, or the notes as a whole shrinking by more than half since the last sync
(counted from ten notes up), stops the sync before anything is written (--force overrides after a deliberate removal).
The count is the vault's total, not each folder's as ADR 0008 first described. In archive/ ela never rewrites a note's
text, and a done note anywhere is the record the same way (his ticks live only there): the sync never writes it, keeps
only its status current, a later change to its source is one dated line under its Afterwards, and lint names each such
note until he has carried over by hand what should be kept. Removal is limited to files this script recorded in its
manifest, never a done note, and never reaches a folder of an earlier layout (library/, to-learn/, layout 4's to-read/
and the rest): what is left there is the owner's. Writes are atomic and a lock serialises concurrent syncs.

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
LAYOUT = 5                  # the manifest records it; a vault in another layout is migrated first (`ela vault migrate`)
# layout 5, things and angles (ADR 0015): eight roots; a work note lives in its thing's folder, live or done
DAYS, ELA, ARCHIVE, REF = "reference/days", "ela", "archive", "reference"
# the lifecycle folders of layout 4, read as input only (an old path given to a verb, a leftover note): never written
TO_READ, READINGS, IN_PROGRESS, PARKED = "to-read", "readings", "in-progress", "parked"
# folders of earlier layouts: the sync reads nothing there and removes nothing there; what is left is the owner's
RETIRED = ("library", "to-learn", TO_READ, READINGS, IN_PROGRESS, PARKED, "days", "lanes", "mh", "sprints", "mediahub-bot")
# a work note's two states, a property on the note in its thing's folder; a move sets it, never moves the file.
# What a live note waits for is said by its other properties: open boxes (his word), `built` (his accept),
# `waits-on` (others). A case keeps its own life; a report the state of his ruling.
LIVE, DONE = "live", "done"
WORK_TYPES = ("decision", "plan", "sprint", "review", "ticket", "verify", "verify-plan", "draft")
STATUS_BY_KIND = {"work": (LIVE, DONE), "case": ("open", "answered", "closed"), "report": ("proposed", "decided", "superseded"),
                  "project": (LIVE, "parked", DONE)}
LEGACY_LIVE = ("proposed", "blocked", "building", "built", "waiting", "parked")   # layout 4's statuses of a live note
# any note's statuses but a report's (proposed, decided, superseded are a ruling's), layout 4's read as input
STATUSES = tuple(dict.fromkeys(STATUS_BY_KIND["work"] + STATUS_BY_KIND["case"] + STATUS_BY_KIND["project"] + LEGACY_LIVE + ("closed",)))
CLOSED_NEXT = {"accepted": "accept", "rejected": "reject", "not now": "not-now", "not-now": "not-now", "parked": "not-now",
               "confirmed": "confirm", "planned": "make-plan", "nudged": "nudge", "drafted": "draft-comment"}
# an archived note's old outcome status, as the move that made it; the runner names the move itself with --next
# a closed note goes to its subject home when it has one, else to archive/, which keeps only what is done with (vault
# in-progress/2026-11-09-kept-notes-by-subject-cases-and-archive.md): one note per customer support case in cases/,
# promotions, deploys, docker checks, release reviews and verifications in mh/releases/, ela's own closed plans and
# reviews in ela/history/
CASES, RELEASES, HISTORY = "cases", "releases", "ela/history"
LAYOUT5, RELEASES5 = 5, RELEASES     # ADR 0015: the layout `ela vault migrate` brings the vault to
LEGACY_RELEASES = "mh/releases"      # layout 4's release folder, read as input only
SUBJECT_HOMES = (CASES, RELEASES, HISTORY, "projects", REF)   # the things' homes: a note's folder by what it serves
CLOSED_FOLDERS = (ARCHIVE,)          # a note there is done whatever it says; elsewhere its status says
OWNER_FOLDERS = (ARCHIVE,)           # kept by folder; a done note anywhere is kept by its status (is_kept)
# a review of a release, by its file name: a release word, a line written mh<major>-<minor> (mh2-1), or a lane hop
# <lane>-to-<lane> (daily-wed-to-prod-3, qa-cn3-to-daily-wed)
LANE = r"(?:qa|daily|stage|test\d*|prod|cn)"
RELEASE_NAME = re.compile(r"(?:^|-)(?:promote|deploy|docker|release|hotfix)(?:-|$)|(?:^|-)mh\d+-\d+(?:-|$)"
                          rf"|(?:^|-){LANE}(?:-[a-z0-9]+)?-to-{LANE}(?:-|\d|$)")
# a review of a release in mh/releases/<line>/: <date>-<kind>-<what>, the line left to the folder (no 2-1 after the kind)
RELEASE_KINDS = ("promote", "deploy", "docker", "hotfix", "review", "sync")   # sync: a release line's sync meeting or reading
RELEASE_REVIEW_NAME = r"\d{4}-\d{2}-\d{2}-(?:" + "|".join(RELEASE_KINDS) + r")-(?!\d+-\d+-)[a-z0-9]+(?:-[a-z0-9]+)*"
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
DELETABLE = ("projects", RELEASES, CASES, REF, HISTORY, TO_READ, READINGS, "days")   # a generated dated note in these: his to delete
KEEP_FOREVER = ("brief", "week", "changes")   # the morning pages are the record of what ela told the owner; the rest expires
PROPS = ("title", "aliases", "type", "date", "kind", "project", "slug", "deadline", "next-step", "customer", "hubspot", "graph", "box",
         "status", "result", "target", "progress", "source",
         "moves", "next", "ela", "posted", "channels", "keys", "watch", "watched", "last", "language", "by")
# the whole vocabulary; no tags (ADR 0010)
MARKS = {"done": DONE, "drop": DONE}   # both close the note where it is and keep it; next says which (no data is lost)
BUDGET = {"ticket": 700, "topic": 800, "guide": 1200, "board": 1000, "day": 1200, "review": 2500, "decision": 800, "plan": 800, "sprint": 800, "report": 1200,
          "recent": 1200, "train": 1200, "one-thing": 1200, "project": 1200, "services": 2500}
# the closed set of note types, by family (the readme's Types): for his word, readings, living pages, day pages.
# A type outside it, or a family outside its folders, is a lint line on the sync, never a failure.
TYPE_FAMILY = {"decision": "decision", "plan": "plan", "sprint": "plan",
               "ticket": "reading", "review": "reading", "verify": "reading", "verify-plan": "reading",
               "home": "page", "today": "page", "dropped": "page", "board": "page", "lanes": "page", "docker": "page", "recent": "page", "one-thing": "page", "test-list": "page", "dev-list": "page", "train": "page", "program": "page",
               "guide": "page", "vocabulary": "page", "system": "page", "constraints": "page", "readme": "page", "meeting": "page",
               "report": "page", "project": "page", "services": "page", "questions": "page",
               "day": "day", "reader": "day", "case": "case", "draft": "draft"}
THING_FOLDERS = ("projects", RELEASES, CASES, REF, ELA, ARCHIVE)   # ela/ includes ela/history/   # where a work note lives: its thing's home
FAMILY_FOLDERS = {"decision": THING_FOLDERS, "plan": THING_FOLDERS, "reading": THING_FOLDERS,
                  "case": (CASES, "projects", ARCHIVE), "draft": THING_FOLDERS}   # a message he sends himself: waits on his send, then on replies   # a reading waits in to-read while it asks his word; a project keeps its own
# a project: bounded work with a deadline and parties outside the program (a customer PoC, a trial), one folder
# projects/<key>/ holding its page projects/<key>/<key>.md (type project, the living family) and what it keeps; any
# note elsewhere names it with `project: <key>` (elak decisions/2026-11-04-projects-are-bounded-work-with-one-page-each.md)
PROJECTS = "projects"
PROJECT_PAGE = re.compile(r"^projects/(?:([^/]+)/\1|[a-z0-9][a-z0-9-]*)\.md$")   # projects/<key>/<key>.md, or one page projects/<key>.md
# the sync's tail, these headings in this order; the head is everything above the first of them, the boundary
# ela-runner's morning Projects section reads too, so a desk heading of these names would end the head early
# Waiting for your word is gone from the tail (ADR 0015): an ask is stored once, on the note that holds it, and shows on
# today.md by a link; the heading still ends the head on a page written before
TAIL_HEADS = ("Notes", "Keys and threads", "Afterwards", "Deadline")
LEGACY_TAIL_HEAD = "Waiting for your word"
PROJECT_HEAD_END = "## " + TAIL_HEADS[0]
STANDS_HEAD = "Where it stands"          # a Jira project's state, from the fact store; the first of the sync's sections
MEETINGS_HEAD = "At meetings"            # what its meetings ruled on its keys, after Notes, so the head still ends at Notes
TAIL_HEAD_RX = re.compile(r"^##[ \t]+(?:" + "|".join(re.escape(h) for h in (STANDS_HEAD, LEGACY_TAIL_HEAD, MEETINGS_HEAD) + TAIL_HEADS)
                          + r")[ \t]*$", re.M)
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

ela writes this vault from first-hand sources, and it holds things and angles (ela ADR 0015).

- A **thing** is what you track: a project, a release line, a customer case. It has one home, and everything about
  it sits there, its open questions included.
- An **angle** is the same things told for one reader at one moment: [[today]] for you, a meeting page for a team.
  It stores nothing of its own.
- A work note (a plan, a review, a verification, a draft) is `live` or `done`, a property. Choosing its `next`
  changes that, never its folder; a done note is the record and is never written again.
- An ask lives once, on its thing. today.md links at most three; one unanswered on three working mornings leaves
  for `reference/dropped.md`.
- An ask is a question and two or three lettered options; A is ela's recommendation. Answer with one letter: tick
  the option, or write `ela: A` under the ask (`ela: 2 B` anywhere on the page). `apply N` still means that ask's A.
- Your `ela:` lines and ticked boxes survive every rewrite. Ask in a session for anything else.

## Layout

| entry | holds |
|---|---|
| `today.md` | the one page: facts, at most three asks, today |
| `meetings/` | one page per meeting, worded for the team |
| `projects/` | one page per project, `<key>-<slug>.md`; a folder `<key>-<slug>/` once notes sit beside the page |
| `releases/` | a folder per line: its record, train, dev and test lists, each promote, deploy and docker check; `lanes.md` across lines |
| `cases/` | one note per customer case |
| `reference/` | what serves no single thing: product reviews, the day pages, One Thing, dropped asks |
| `ela/` | ela's own pages and history |
| `archive/` | what you put away |

## Names

Lowercase nouns joined by hyphens. A dated note is `<date>-<kind>-<what>.md` (plan, review, decision, verify, deep,
promote, deploy, docker, hotfix, draft); its folder carries the subject, so the name does not repeat it. An old name
stays an alias, so links and the quick switcher still find the note.

> [!note]- Note standards
<!-- note standards -->
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
    name: Live
    filters:
      and:
        - not:
            - file.inFolder("archive")
        - or:
            - 'status == "live"'
            - 'result == "fail"'
    order: [date, formula.note, formula.subject, type, project, progress, waits-on, next]
    sort:
      - property: formula.loop
        direction: ASC
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
        - file.hasProperty("waits-on")
        - 'status == "live"'
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
    name: Done
    filters:
      or:
        - file.inFolder("archive")
        - 'status == "done"'
        - 'status == "closed"'
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


def family_of(kind):
    """The life a type has: work (live, done), case, report, project; None for a page."""
    kind = (kind or "").strip()
    return "work" if kind in WORK_TYPES else kind if kind in ("case", "report", "project") else None


def settled_status(folder, status, kind=None):
    """(status, result, next) a note carries, from whatever status it had (layout 4's included): a work note live or
    done, a verdict moved to result, an old outcome (accepted, rejected …) moved to next; in archive/ a work note is
    done and a case closed. A case, a report and a project keep their own states; a page as it was."""
    s = (status or "").strip().strip("'\"").lower()
    result = s if kind == "verify" and s in ("pass", "fail") else None
    fam = family_of(kind)
    if fam is None:
        return status, None, None
    archived = folder in CLOSED_FOLDERS
    if fam == "case":
        return ("closed" if archived else s if s in STATUS_BY_KIND["case"] else "open"), result, None
    if fam == "report":
        return (s if s in STATUS_BY_KIND["report"] else status), None, None
    if fam == "project":
        return (s if s in STATUS_BY_KIND["project"] else None), None, None
    if archived or s in (DONE, "closed") or (s in CLOSED_NEXT and s not in LEGACY_LIVE):   # parked outside archive/ is live
        return DONE, result, CLOSED_NEXT.get(s)
    return LIVE, result, None


def subject_home(path):
    """The thing's home a folder or note path lies in, at any depth (releases/2.1 is releases, projects/x/ is
    projects), else None."""
    path = path.replace(os.sep, "/").strip("/")
    return next((h for h in SUBJECT_HOMES if path == h or path.startswith(h + "/")), None)


def kept_home(folder):
    """archive/ or the thing's home a folder lies in; else None."""
    return folder if folder == ARCHIVE else subject_home(folder or "")


def folder_of(rel):
    """The home of a note path: the thing's home it lies in, at any depth, else its top folder."""
    return subject_home(os.path.dirname(rel)) or top(rel)


def notes_under(vault, folder):
    """The .md notes of a folder as vault paths, its subfolders included (a release line's folder, a project's)."""
    base = os.path.join(vault, folder)
    if not os.path.isdir(base):
        return []
    out = []
    for top_, dirs, fs in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and os.path.relpath(os.path.join(top_, d), vault).replace(os.sep, "/") != ATTACH)
        out += [os.path.relpath(os.path.join(top_, f), vault).replace(os.sep, "/") for f in sorted(fs) if f.endswith(".md")]
    return out


def is_done(props):
    """A note that is the record: status done, or a case closed. The sync never rewrites it."""
    st = (props.get("status") or "").strip().lower()
    return st == DONE or st == "closed"                   # closed: a case's end, and layout 4's word for done


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
    """The thing's home of a work note that names no project: a case → cases/; a verification, a verification plan,
    or a review of a release (a promotion, deploy, docker check or release review, by its file name or title) → its
    line's folder releases/<line>/ (release_line), else releases/; a plan, decision or review whose target (else its
    title) names ela, its runner, elak or the vault → ela/ (live; ela/history/ keeps what was closed before layout 5);
    anything else → reference/."""
    kind = (props.get("type") or "").strip()
    name = os.path.basename(rel)[:-3] if rel.endswith(".md") else os.path.basename(rel)
    if kind == "case":
        return CASES
    if kind in ("verify", "verify-plan") or (kind == "review" and (RELEASE_NAME.search(re.sub(r"^\d{4}-\d{2}-\d{2}-", "", name))
                                                                   or RELEASE_TITLE.search(props.get("title") or ""))):
        line = release_line(props, line_of_key, name)
        return f"{RELEASES}/{line}" if line else RELEASES
    if kind in ("plan", "decision", "review") and ELA_TARGET.search(props.get("target") or props.get("title") or ""):
        return ELA
    return REF


def settle_statuses(vault, dry_run=False):
    """Bring every note in the things' homes and the archive to its type's states (a work note live or done, layout 4's
    statuses read as the state they meant), front matter only: the body stays his. Returns one line per fix."""
    fixes = []
    for folder in THING_FOLDERS:
        for rel in notes_under(vault, folder):
            p = os.path.join(vault, rel)
            try:
                text = open(p, encoding="utf-8").read()
            except OSError:
                continue
            fl, body = split_front(text)
            if not fl:
                continue
            props = props_of(fl)
            if not family_of(props.get("type")) or PROJECT_PAGE.match(rel):
                continue
            st, result, nxt = settled_status(folder_of(rel), props.get("status"), props.get("type"))
            want = {"status": st, "result": result or props.get("result") or None}
            if nxt and not props.get(NEXT):
                want[NEXT] = nxt
            if props.get("type") == "case":
                want[MOVE_SET] = "case"
            elif st == DONE and family_of(props.get("type")) == "work":
                want[MOVE_SET] = "reopen" if props.get(MOVE_SET) == "reopen" else "closed"
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


def keys_list(v):
    """A `keys` property as a list whatever form it was written in: a list, a list's text, or a string of keys."""
    v = as_list(v)
    if isinstance(v, str):
        found = KEY_RX.findall(v)
        return list(dict.fromkeys(found)) if found else [x for x in re.split(r"[\s,;]+", v) if x]
    return v if isinstance(v, list) else ([] if v is None else [v])


def as_list(v):
    """A property read back as the text of a list (`["https://…"]`) written as that list, not as a string of it."""
    if isinstance(v, str) and v.startswith("[") and v.endswith("]"):
        try:
            d = json.loads(v)
            if isinstance(d, list):
                return d
        except ValueError:
            pass
    return v


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
    lines = [f"{k}: {json.dumps(keys_list(props[k]) if k == 'keys' else as_list(props[k]) if k in ('channels', 'posted') else props[k], ensure_ascii=False)}"
             for k in PROPS if props.get(k) or props.get(k) is False
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
            path, date = f"{REF}/{sp.group(1)}-sprint-{int(sp.group(2))}.md", None
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


def report_notes(reports, today, runtime=None, helm=None):
    if not reports or not os.path.isdir(reports):
        raise SourceError(f"the reports root is missing: {reports}")
    notes = []
    rd = os.path.join(reports, "runner")
    lists = list_links(reports)
    for f in sorted(os.listdir(rd)) if os.path.isdir(rd) else []:
        # the morning page and what changed: today.md reads them, the runner reads their ticks; the week is not written
        # into the vault any more (ADR 0015: nothing consumed it), its source stays
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-(brief|changes)\.md$", f)
        if not m or (m.group(2) not in KEEP_FOREVER and (today - datetime.date.fromisoformat(m.group(1))).days >= DAYS_KEPT):
            continue
        d = datetime.date.fromisoformat(m.group(1))
        fl, body = split_front(open(os.path.join(rd, f), encoding="utf-8").read())
        body = layout5_links(body)
        if m.group(2) == "brief":
            body = action_states(body, os.path.join(rd, f"{m.group(1)}-actions.json"), lists)
        label = {"brief": "Morning brief", "week": "The week", "changes": "What changed"}[m.group(2)]
        notes.append(Note(f"{DAYS}/{m.group(1)[:4]}/{m.group(1)}-{m.group(2)}.md", f"{label} · {d:%a} {m.group(1)}", body,
                          {"type": "day", "date": m.group(1), "kind": m.group(2)}, fl, src_rel=f"runner/{f}"))
    for rec in build_records(reports):                    # a build a lane took: its release note, written once (source vault)
        R = release_mod()
        reading = R.reconcile_mod().saved_reading(reports, rec)   # its Jira gaps, as `ela release reconcile` last read them
        tickets = R.facts_tickets(runtime, [k for v in rec["services"] for k in v.get("keys") or []])
        notes.append(Note(f"{RELEASES}/{rec['line']}/{rec['name']}.md", R.build_title(rec), R.build_note(rec, reading, tickets, R.helm_compare(rec, runtime, helm)),
                          {"type": "report", "date": rec["date"], "status": "decided", "source": "vault",
                           "keys": sorted({k for v in rec["services"] for k in v.get("keys") or []})}, [],
                          src_rel=f"releases/{rec['line']}/{rec['name']}.json"))
    # the board, recent and the constraints page are angles nothing consumed: their verbs render them on demand, their
    # sources stay under the reports root, and the vault no longer carries them (ADR 0015)
    lp = os.path.join(reports, "lanes", "lanes.md")
    if os.path.isfile(lp):                                 # the lanes, their differences and two weeks of moves, rewritten each pass
        fl, body = split_front(open(lp, encoding="utf-8").read())
        dm = re.search(r"\*(\d{4}-\d{2}-\d{2})", body)
        body = lanes_live(layout5_links(body), helm)
        notes.append(Note(LANES_PAGE, "The lanes", body, {"type": "lanes", "date": dm.group(1) if dm else None}, fl, src_rel="lanes/lanes.md"))
    on = onething_note(reports, today)
    if on:                                                 # his One Thing rows not yet pasted, rendered from the store each sync
        notes.append(on)
    ld = os.path.join(reports, "lanes")
    lanes = lane_lines()
    for f in sorted(os.listdir(ld)) if os.path.isdir(ld) else []:   # what QA verifies per lane, what is in development per line
        if f == "docker.md":                               # the docker candidates, linked from the day pages
            fl, body = split_front(open(os.path.join(ld, f), encoding="utf-8").read())
            dm = re.search(r"\*(\d{4}-\d{2}-\d{2})", body)
            notes.append(Note(DOCKER_PAGE, "Docker candidates", body, {"type": "docker", "date": dm.group(1) if dm else None}, fl,
                              src_rel=f"lanes/{f}"))
            continue
        m = re.match(r"^(test-list|dev-list|train)-(.+)\.md$", f)
        if m:
            fl, body = split_front(open(os.path.join(ld, f), encoding="utf-8").read())
            body = layout5_links(body, lanes)
            dm = re.search(r"\*(\d{4}-\d{2}-\d{2})", body)
            title = {"test-list": "Test list · ", "dev-list": "Dev list · ", "train": "Train · "}[m.group(1)] + m.group(2)
            notes.append(Note(list_home(f, lanes), title, body, {"type": m.group(1), "date": dm.group(1) if dm else None}, fl, src_rel=f"lanes/{f}"))
    # the evening reader's pages are not written into the vault any more (ADR 0015): nothing read the vault copy
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
            # a deep reading of one ticket (`ela-runner deep`) is a ticket page: real status, timeline, next; its title
            # plain text (the heading may link the key) and its key the one the file is named for
            deep = re.match(r"^\d{4}-\d{2}-\d{2}-deep-([A-Za-z][A-Za-z0-9]+-\d+)", base)
            kind = "ticket" if deep else "review"
            props = {"type": kind, "date": m.group(1) if m else None}
            if deep:
                title = plain(title)
                props["keys"] = [deep.group(1).upper()]
            notes.append(Note(path, title, body, props, fl, src_rel=f"{sub + '/' if sub else ''}{f}"))
    return notes


def lanes_live(body, helm):
    """The lanes page with, under each line's heading, its lanes' live views in Helm (`/lanes/<lane>`), in the heading's
    order; the page as it is without a Helm URL or a line the release map does not know."""
    if not helm:
        return body
    lines = (release_mod().rmap("lines") or {})

    def live(m):
        lanes = (lines.get(m.group(1)) or {}).get("lanes") or {}
        order = [lanes[r] for r in ("prod", "daily", "qa") if lanes.get(r)]
        if not order:
            return m.group(0)
        return m.group(0) + "\n\nlive: " + " · ".join(f"[{l}]({helm.rstrip('/')}/lanes/{l})" for l in order)
    return re.sub(r"(?m)^## Line ([\d.]+) · .*$", live, body)


def release_mod():
    sys.path.insert(0, os.path.join(HERE, "..", "release"))
    import release as R                                    # noqa: E402 — the build records' one reader and renderer
    return R


def build_records(reports):
    """The build records under <reports>/releases/ (`ela release changes`), newest first; [] when release cannot load."""
    try:
        return release_mod().build_records(reports)
    except Exception as e:                                 # a broken import costs the build block, said once
        print(f"builds: not read — {str(e)[:120]}", file=sys.stderr)
        return []


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


LANES_PAGE, ONE_THING, DOCKER_PAGE = f"{RELEASES}/lanes.md", f"{REF}/one-thing.md", f"{RELEASES}/docker.md"
OLD_LANE_LINK = re.compile(r"\[\[lanes/([^\]|#]+)")


def layout5_links(body, lanes=None):
    """A page's links to layout 4's lanes/ folder written to where layout 5 keeps the page (a session that wrote
    `[[lanes/docker|…]]` from habit links a path that no longer exists)."""
    return OLD_LANE_LINK.sub(lambda m: "[[" + list_home(m.group(1) + ".md", lanes)[:-3], body or "")
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
    return Note(f"{REF}/recent.md", RC.TITLE, body, {"type": "recent", "date": (data.get("at") or "")[:10] or None}, [],
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
    n = Note(ONE_THING, OT.PAGE_TITLE.format(month=today.isoformat()[:7]), body,
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
SEND_TAIL = re.compile(r"[ \t]*·[ \t]*(?:unticked: stays as apply \d+|\[\[(?:lanes|releases)/[^\]]*\]\](?: → #[\w-]+)?|→ #[\w-]+|untouched: not sent)[ \t]*$")
LIST_COUNTS = {"qa-today": ("test-list", re.compile(r"(\d+) open(?: · P1 (\d+))?"), "P1"),
               "dev-today": ("dev-list", re.compile(r"(\d+) ticket\(s\)(?: · (\d+) with a gap)?"), "with a gap")}


def list_links(reports):
    """{(rule, lane or line): wikilink} for each lane list on disk, the page a send box would send: QA today's test list
    as [[releases/<line>/test-list-<lane>|N rows, M P1]], Dev today's dev list as [[releases/<line>/dev-list-<line>|N
    rows, M with a gap]], the counts read from the page's own count line."""
    out, d = {}, os.path.join(reports or "", "lanes")
    lanes = lane_lines() if os.path.isdir(d) else {}
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
        out[(rule, m.group(2))] = f"[[{list_home(f, lanes)[:-3]}|{label}]]"
    return out


def send_tail(a, lists=None):
    """What follows an open send box: the list it would send, the channel it goes to, and that untouched it is not
    sent. Nothing of it changes the box prefix the runner reads (`- [x] send N`)."""
    scope = a.get("scope") or []
    where = scope[1] if len(scope) > 1 and scope[0] in ("--lane", "--line") else None
    kind = LIST_COUNTS.get(a.get("rule"), (None,))[0]
    link = (lists or {}).get((a.get("rule"), where)) or (f"[[{kind}-{where}|the list]]" if kind and where else None)
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
        # a Jira number never starts with 0: `[FloSports MH-030]` in a summary is the customer's own item id
        return bool(self.jira_base) and k.split("-")[0] in self.projects and not NOT_KEYS.match(k) and not k.split("-")[1].startswith("0")

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
    if fam in FAMILY_FOLDERS and not any(path.startswith(f + "/") for f in FAMILY_FOLDERS[fam]):
        return f"{path}: a {fam} belongs in {', '.join(FAMILY_FOLDERS[fam])}"
    if kind == "guide" and folder != ELA:                 # the ela page's type; a page elsewhere has its own
        return f"{path}: a guide is the ela page and belongs in {ELA}/"
    if kind == "project" and not PROJECT_PAGE.match(path):
        return f"{path}: a project page is {PROJECTS}/<key>.md, or {PROJECTS}/<key>/<key>.md once it has a folder"
    if kind == "services" and path != SERVICES_PAGE:
        return f"{path}: the service map is {SERVICES_PAGE}"
    return None


def project_lint(path, props, vault):
    """One lint line when a note names a project (`project: <key>`) that has no folder projects/<key>/; else None."""
    key = (props.get("project") or "").strip()
    if key and not os.path.isdir(os.path.join(vault, PROJECTS, key)) and not os.path.isfile(os.path.join(vault, PROJECTS, key + ".md")):
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
                     and not his_lines(sec, b.end(), boxes[i + 1].start() if i + 1 < len(boxes) else len(sec)))
    return unanswered, len(boxes)


def asks_lint(n):
    """One lint line when a done note in a thing's home still has an open box under Waiting for your word: an ask on
    a closed note reaches nobody (today.md lists the asks of live notes only). The record folders, ela/history/ and
    archive/, are not read: a plan agreed as a whole leaves its proposals' boxes unticked, and that is its history."""
    if family_of(n.props.get("type")) != "work" or not is_done(n.props) or top(n.path) == ARCHIVE or n.path.startswith(HISTORY + "/"):
        return None
    left, _ = open_asks(n.body)
    return f"{n.path}: {left} open under {ASKS_HEAD} on a done note; mark it live to ask, or answer them" if left else None


def answered_readings(vault, reports, dry_run=False):
    """A reading ela wrote in place, live, whose every box under Waiting for your word is ticked or answered with an
    `ela:` line is done where it is; a plan or decision keeps its own life. Returns [(path, path)]."""
    out = []
    for rel in (r for fo in THING_FOLDERS if fo != ARCHIVE for r in notes_under(vault, fo)):
        try:
            fl, body = split_front(open(os.path.join(vault, rel), encoding="utf-8").read())
        except OSError:
            continue
        props = props_of(fl)
        if props.get("source") != "vault" or TYPE_FAMILY.get(props.get("type")) != "reading" or is_done(props):
            continue
        left, total = open_asks(body)
        if total and not left:
            out.append((rel, None if dry_run else move_note(vault, reports, rel, "readings")))
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
# a work note's home: a project's folder, a release line's, a case's, reference, ela's history, the archive (ADR 0015)
THING = rf"(?:projects/{SLUG}|releases(?:/[\d.]+)?|cases(?:/{SLUG})?|reference|ela(?:/history)?|archive)"
THING_NOT_RELEASES = rf"(?:projects/{SLUG}|cases(?:/{SLUG})?|reference|ela(?:/history)?|archive)"   # a review there follows its own rule
THING_NAME = "`<date>-<kind>-<what>.md` in its thing's folder"
SPECS = {
    "decision": dict(
        kind="a choice for your word: confirm or park",
        name=(rf"^{THING}/{DATED}\.md$", THING_NAME),
        title=(r".", "the choice as a sentence: what is decided, about what"),
        required=("date",), optional=("source", "target", "keys", "posted", "watch", "project", "ela", "progress"),
        sections=("The question?", "Options?", WHAT_TO_DO),
        closing=f"## {WHAT_TO_DO}: the recommended option and the alternative, each with its first step; options you named keep your labels, your order and your definitions, the recommendation a separate line"),
    "plan": dict(
        kind="work for your word: agree, park, not now or reject",
        name=(rf"^{THING}/{DATED}\.md$", THING_NAME + "; a release line's test plan `releases/<line>/<date>-plan-<what>.md`"),
        title=(r".", "what the plan builds, as a sentence"),
        required=("date",), optional=("source", "target", "keys", "posted", "watch", "project", "ela", "progress", "branch"),
        sections=("The problem?", WHAT_TO_DO, ASKS_HEAD + "?", "Progress?"),
        closing=f"## {WHAT_TO_DO}: what agree starts and what each other move means; each ruling it needs listed with ela's proposed answer, no boxes. A plan for ela's own design asks nothing: its Gate is written as reasoning"),
    "sprint": dict(
        kind="a sprint: a plan with a start and an end",
        name=(r"^(?:archive|reference)/(?:\d{4}-\d{2}-\d{2}|\d{4})-sprint-\d+\.md$", "`<end date>-sprint-<n>.md`, in reference/ while it runs"),
        title=(r"^Sprint \d+ · ", "`Sprint <n> · <start> – <end>`"),
        required=("date", "start", "end"), optional=("source", "status"),
        sections=("Sprint goals", "Committed", "Stretch?"),
        closing="its goals are the ask; the sprint's end review says what landed"),
    "review": dict(
        kind="a reading of evidence: a release, a promotion, a docker check, a part of the product or of ela",
        name=(rf"^(?:{THING_NOT_RELEASES}/{DATED}|releases(?:/[\d.]+)?/{RELEASE_REVIEW_NAME})\.md$",
              "`<date>-<slug>.md`; in `mh/releases/<line>/` a review of a release is `<date>-<promote|deploy|docker|hotfix|review>-<what>.md`, "
              "the line left to the folder (`2026-11-09-deploy-daily-wed-to-prod-3.md`)"),
        title=(r".", "a review of a release: `MH <line> · <from> → <to> · <what>`; any other: its finding as a sentence"),
        required=("date",), optional=("source", "keys", "posted", "watch", "project", "target", "ela", "progress"),
        sections=("What could not be read?", WHAT_TO_DO, ASKS_HEAD + "?"),
        closing=f"## {WHAT_TO_DO}: each action a box or a ready command, the recommendation first; what could not be read is named as a gap above it"),
    "ticket": dict(
        kind="one ticket made judgeable: where it stands, what done is",
        name=(rf"^{THING}/\d{{4}}-\d{{2}}-\d{{2}}-(?:deep-)?[a-z]+-\d+(?:-{SLUG})?\.md$",
              "`<date>-<key>-<slug>.md`, the key lowercase (`2026-10-30-mh-2406-timeline.md`)"),
        title=(KEY_TITLE, "`<KEY> · <where it stands>`, the key as plain text (the heading may link it)"),
        required=("date", "keys"), optional=("source", "posted", "watch", "project"),
        sections=("Done when?", "Next?"),
        closing="a **Do.** line: the move, who it waits on, and the first step"),
    "verify": dict(
        kind="a verification in a real browser on a named lane",
        name=(rf"^{THING}/\d{{4}}-\d{{2}}-\d{{2}}-verify-[a-z]+-\d+(?:-[a-z0-9-]+)?\.md$",
              "`<date>-verify-<key>[-<lane>].md`"),
        title=(KEY_TITLE + r"(?:PASS|FAIL|BLOCKED) on \S+", "`<KEY> · PASS|FAIL|BLOCKED on <lane>`"),
        required=("date", "result", "keys"), optional=("posted", "watch", "source"),
        sections=("Checks", "What failed, seen?"),
        closing="its moves: *draft-comment* puts the Jira record as `apply N`; the full record is the linked page"),
    "verify-plan": dict(
        kind="a verification run waiting for your word on its goals",
        name=(rf"^{THING}/\d{{4}}-\d{{2}}-\d{{2}}-verify-plan-[a-z]+-\d+\.md$", "`<date>-verify-plan-<key>.md`"),
        title=(KEY_TITLE + r"verify plan$", "`<KEY> · verify plan`"),
        required=("date", "keys"), optional=("posted", "watch"),
        sections=(), closing="its moves: *run*, *not-now* or *drop*"),
    "case": dict(
        kind="one customer support case",
        name=(rf"^(?:cases|projects/{SLUG})/{DATED}\.md$|^cases/{SLUG}/{DATED}\.md$", "`cases/<date>-<slug>.md`"),
        title=(r" · ", "`<customer or stream> · <what happened>`"),
        # keys optional: a support case often has no Jira ticket, and one without was a lint line for ever (review 11-10)
        required=("date", "customer", "status"), optional=("keys", "hubspot", "graph", "box", "channels", "posted", "watch", "source", "progress", "project"),
        sections=("Timeline?", "Findings?", "Open?", WHAT_TO_DO),
        closing=f"## {WHAT_TO_DO}: the reply to support or the next check, and who acts"),
    "report": dict(
        kind="a standing review or design for your decision, ruled in place",
        name=(rf"^(?:[a-z0-9.-]+/)*(?:{DATED}|{SLUG})\.md$", "`<slug>.md`, or `<date>-<slug>.md` when it is of a day"),
        title=(r".", "what it settles, as a sentence"),
        # a standing report may say when it was last brought up to date (`updated`) in place of the day it was written
        required=("date|updated", "source", "status"), optional=("target", "progress", "ela", "keys", "posted", "watch", "project"),
        sections=(WHAT_TO_DO, ASKS_HEAD + "?"),
        closing=f"## {WHAT_TO_DO}: the recommendation, the alternative, the first step; status proposed, decided or superseded"),
    "project": dict(
        kind="bounded work with a deadline and parties outside the program",
        name=(r"^projects/(?:([^/]+)/\1|[a-z0-9][a-z0-9-]*)\.md$", "`projects/<key>.md`, or `projects/<key>/<key>.md` once it has a folder"),
        title=(r".", "the project's name"),
        # deadline optional for every project: a page without one says nothing of it (review of 2026-11-11)
        required=("date", "source"), optional=("deadline", "next-step", "channels", "keys", "posted", "watch", "customer", "hubspot", "slug", "status"),
        sections=("Goal", "Parties?", "Dates?", "What is known?", "Next step") + TAIL_HEADS,
        closing="## Next step in the head (`next-step` is the line Home may name); the tail from Waiting for your word is the sync's"),
    "meeting": dict(
        kind="what you raise at one meeting, and what it ruled",
        name=(rf"^(?:meetings/(?:{DATED}|(?!\d{{8}}-){SLUG})|archive/meetings-{SLUG}-\d{{4}}-\d{{2}}|archive/{SLUG})\.md$",
              "`meetings/<yyyy-mm-dd>-<key>.md`, the verb's `meetings/<key>.md`; older months `archive/meetings-<key>-<yyyy-mm>.md`"),
        title=(r" · |^Review list$", "`<meeting> · <day and date>`"),
        required=(), optional=("date", "status", "keys", "source", "by"),
        sections=("To raise?", "Ruled?"),                 # Ruled comes after the meeting; a dated note has its own sections (ADR 0016)
        closing="the `- [ ] send` box at the top; each item under 140 characters: ticket link · question · who decides · since when"),
    "day": dict(
        kind="a morning page, what changed the day before, or the week",
        name=(r"^reference/days/\d{4}/\d{4}-\d{2}-\d{2}-(?:brief|changes|week|learn)\.md$", "`reference/days/<year>/<date>-<kind>.md`, kind brief or changes"),
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
        name=(rf"^{THING}/{DATED}-(?:slack|jira|mail)-draft\.md$", "`<date>-<slug>-<slack|jira|mail>-draft.md` in its thing's folder"),
        title=(r"^(?:Slack|Jira|Mail) draft: ", "`Slack draft: <subject>` (or Jira, Mail)"),
        required=("date", "source"), optional=("progress", "ela", "keys", "posted", "watch", "project", "channels"),
        sections=("Root message", "Thread replies?", "Not for this post?"),
        closing="the message paste-ready in a code block, English, mentions written for you to retype; parked once sent, `waits-on` naming who answers and `wake` what brings it back"),
}
BUDGET.update({"case": 1200, "draft": 600})
PAGES_SPEC = ("home", "today", "dropped", "board", "lanes", "docker", "recent", "one-thing", "test-list", "dev-list", "train", "program", "guide",
              "vocabulary", "system", "constraints", "readme", "services", "questions", "dry")   # living pages: each one's generator is its spec
CJK = re.compile(r"[一-鿿　-〿＀-￯]")
SPEC_MARK = "<!-- note standards -->"


def spec_text():
    """The readme's Note standards section, written from SPECS so the readme and the lint cannot disagree."""
    out = ["Every note: a lowercase file name, words joined by hyphens, a dated note starting with its date (its `date` "
           "property the same day). `title` is double-quoted plain text, without links, in English, and the first entry "
           "of `aliases`; the first heading is the title (it may link a ticket key). Durable text is English, and "
           "every Jira key in it is a link. A key never stands alone: it is written `[KEY](link) <Jira summary> · <status>`, "
           "the summary as Jira has it up to about 90 characters (a longer one cut at a word boundary), and a list of keys "
           "is one line a ticket, never a cluster in brackets. The one exception is a note written for a Chinese-speaking audience (a test "
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
                "- **Properties**: " + (", ".join(" or ".join(f"`{x}`" for x in p.split("|")) for p in sp["required"]) or "none") + " required"
                + (("; " + ", ".join(f"`{p}`" for p in sp["optional"]) + " when they apply") if sp["optional"] else "")
                + "; status (live or done), next and moves by type",
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


# a release line's record and the release note of a build it took: what happened, with nothing to rule
RELEASE_RECORD = re.compile(r"^releases/[\d.]+/(?:release-[\d-]+-record|\d{4}-\d{2}-\d{2}-build-[\w.]+-to-[a-z0-9-]+)\.md$")


def undated(kind, rel, text):
    """A standing page, named without a date though it carries one (ADR 0017): a project's page, a release line's
    record, the verb's meetings/<key>.md, and a report ruled in place, named by its slug (ADR 0020: the report spec's
    `<slug>.md`, a report that is not of a day). Every other note with a `date` is named from it."""
    return (kind == "project" or bool(RELEASE_RECORD.match(rel)) or (kind == "meeting" and legacy_form(text))
            or (kind == "report" and not re.match(r"\d{4}-\d{2}-\d{2}-", os.path.basename(rel))))


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
    if not dm and props.get("date") and not undated(kind, rel, text):    # name order is time order (ADR 0017)
        out.append(f"dated {props['date'][:10]} but the file name does not start with it: want `{props['date'][:10]}-…`")
    if dm and props.get("date") and props["date"][:10] != dm.group(1) and (props.get("end") or "")[:10] != dm.group(1):   # a sprint is named by its end
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
    missing = [p for p in sp["required"] if not any(props.get(x) for x in p.split("|"))]   # `a|b`: either will do
    if missing:
        out.append("missing " + ", ".join(p.replace("|", " or ") for p in missing))
    known = set(PROPS) | set(LIFE_PROPS) | {x for p in sp["required"] for x in p.split("|")} | set(sp["optional"])
    extra = [k for k in props if k not in known and k not in ALL_MOVE_PROPS + tuple(MARKS) + ("learn", "start", "end", "built")]
    if extra:
        out.append("properties outside the vocabulary: " + ", ".join(extra))
    hs = [h.lower() for h in headings(body)]
    def at(want):
        w = want.rstrip("?").lower()
        return next((i for i, h in enumerate(hs) if h == w or h.startswith(w)), None)
    closed = folder_of(rel) in CLOSED_FOLDERS or is_done(props) or bool(RELEASE_RECORD.match(rel))   # nothing left to rule
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
        found = front_breaks(split_front(text)[0]) + spec_lint(rel, text, rel in gen, projects) + own_lines_lint(text) + key_cluster_lint(text)
        if found:
            out.append((rel, rel in gen, found))
    return out


KEY_CLUSTER = re.compile(r"(?<![\w-])[A-Z][A-Z0-9]+-\d+(?:[\s,;/、()]+[A-Z][A-Z0-9]+-\d+){2,}")


def key_cluster_lint(text):
    """One lint line per run of three or more Jira keys with no words between them, in any note: a key never stands
    alone; each is written with its title and status, one line a ticket. A hand-written note is only named, never
    rewritten."""
    out = []
    for line in split_front(text)[1].splitlines():
        for m in KEY_CLUSTER.finditer(plain(line)):
            keys = re.findall(r"[A-Z][A-Z0-9]+-\d+", m.group(0))
            if not all(NOT_KEYS.match(k) for k in keys):
                out.append(f"{len(keys)} Jira keys with no words between them ({', '.join(keys[:3])}, …): "
                           "write each as its title and status, one line a ticket")
    return out


def own_lines_lint(text):
    """One lint line per `ela:` line ela wrote for itself: a stub belongs as a box under Waiting for your word, a dated
    record in `progress`; the watcher skips both, the lint says where they go."""
    front = body_start(text)
    out = []
    for m in GUIDE.finditer(text):
        if ela_own(m.group(1), m.start() < front):
            where = "the ela property holds ela's record; it belongs in progress" if m.start() < front else \
                "an ela: stub ela wrote; ask with a box under " + ASKS_HEAD + " instead"
            out.append(f"{where} (skipped by the watcher): {m.group(1)[:60]}")
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
    for c in source_changes(vault, s.get("reports") or "", s.get("elak")):   # the vault copy is the record
        found.append((c["note"], False, [f"the source {c['src']} changed after the note closed ({c['closed']}, changed "
                                         f"{c['changed']}); this copy is the record, carry over by hand what should be kept"]))
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


WARNING_RX = re.compile(r"^> \[!warning\] Not yet fit to read: .*\n\n?", re.M)


def with_warning(body, problems):
    """The warning sits under the note's title, where a reader starts; one only, whatever the body already carried (a
    project page's head is read back from disk with the last sync's warning in it)."""
    body = WARNING_RX.sub("", body)
    warn = f"> [!warning] Not yet fit to read: {'; '.join(problems)}. ela owes a shorter version.\n"
    m = re.search(r"^#[ \t]+.*$", body, re.M)
    return body[:m.end()] + "\n\n" + warn + "\n" + body[m.end():].lstrip("\n") if m else warn + "\n" + body


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
# the next step), kept as written. From there, written on every sync: what waits on his word (the head's own unticked
# boxes, then the project's notes in to-read and in-progress), its notes by folder, its keys and threads, their Afterwards (the archive's watch, pointed
# at the page too), and the days to the deadline with the step. Reasons: elak
# blueprint/decisions/2026-11-04-projects-are-bounded-work-with-one-page-each.md.
STEP_DATE = re.compile(r"(?<![\d-])(\d{4}-\d{2}-\d{2}|\d{2}-\d{2})(?![\d-])")
PROJECT_FOLDERS = ("in this folder", "projects", RELEASES, CASES, REF, HISTORY, ARCHIVE)   # the Notes section's order


def project_path(vault, key):
    """A project's page as a vault path: projects/<key>/<key>.md when its folder holds the page, else the one page
    projects/<key>.md, which a folder of its notes may sit beside until `ela vault migrate` or he moves the page in."""
    if os.path.isfile(os.path.join(vault or "", PROJECTS, key, key + ".md")) or (
            os.path.isdir(os.path.join(vault or "", PROJECTS, key)) and not os.path.isfile(os.path.join(vault or "", PROJECTS, key + ".md"))):
        return f"{PROJECTS}/{key}/{key}.md"
    return f"{PROJECTS}/{key}.md"


def project_pages(vault):
    """{key: text} for every project page, projects/<key>/<key>.md or projects/<key>.md, by key."""
    out, d = {}, os.path.join(vault, PROJECTS)
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if name.startswith("."):
            continue
        key = name[:-3] if name.endswith(".md") else name
        p = os.path.join(d, name) if name.endswith(".md") else os.path.join(d, name, name + ".md")
        if not os.path.isfile(p) or key in out:
            continue
        try:
            out[key] = open(p, encoding="utf-8").read()
        except OSError:
            continue
    return out


def jira_projects(runtime):
    """The open Jira tickets labelled kind:project, from the fact store (<runtime>/facts/jira/issues/): [{key, summary,
    owner, status, since, updated, read_at, due, subtasks: [(key, summary, status, owner)]}]. A requirement is a
    project: one ticket, in principle one person (elak conventions, 2026-11-10)."""
    d, out = os.path.join(runtime or "", "facts", "jira", "issues"), []
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        try:
            r = json.load(open(os.path.join(d, f), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        fl = r.get("fields") or {}
        if "kind:project" not in (fl.get("labels") or []) or ((fl.get("status") or {}).get("statusCategory") or {}).get("key") == "done":
            continue
        out.append({"key": r.get("key"), "summary": fl.get("summary") or "", "owner": (fl.get("assignee") or {}).get("displayName"),
                    "status": (fl.get("status") or {}).get("name"), "since": (fl.get("statuscategorychangedate") or "")[:10],
                    "updated": (r.get("updated") or fl.get("updated") or "")[:10], "read_at": (r.get("read_at") or "")[:16],
                    "due": fl.get("duedate"),
                    "subtasks": [(x.get("key"), (x.get("fields") or {}).get("summary") or "", ((x.get("fields") or {}).get("status") or {}).get("name"),
                                  ((x.get("fields") or {}).get("assignee") or {}).get("displayName")) for x in fl.get("subtasks") or []]})
    return out


SLUG_STOP = frozenset("a an and as at by for from in into of on or over the to via with without vs".split())


def project_slug(summary):
    """Two to four whole words of a summary: its words, a layer tag (`[UR]`) left out, up to the first function word
    once two are taken, never more than four (`Encoding Level: Auto as the default …` → encoding-level-auto). A summary
    cut at a character count mid-phrase (`encoding-level-auto-as-the`) is what this replaces."""
    words = []
    for w in slug(re.sub(r"\[[^\]]*\]", " ", summary or ""), 400).split("-"):
        if not w or w == "untitled":
            continue
        if w in SLUG_STOP:
            if len(words) >= 2:
                break
            if not words:
                continue
        words.append(w)
        if len(words) == 4:
            break
    return "-".join(words) or "project"


def jira_project_key(t):
    """The page name of a Jira project: the ticket key and two to four whole words of its title
    (`mh-3982-encoding-level-auto`). A `slug` property on an existing page, or a rename by hand, wins: a page is found
    by its key, never by its name."""
    return f"{t['key'].lower()}-{project_slug(t['summary'])}"


def page_ticket_key(text):
    """The ticket a project page belongs to: the first key of its `keys` property, or None."""
    keys = [k for k in KEY_RX.findall(props_of(split_front(text)[0]).get("keys") or "") if not NOT_KEYS.match(k)]
    return keys[0] if keys else None


def jira_project_page(t, today):
    """A new page for a Jira project: its properties, its title, and a head the owner and the carrier keep: the next
    step and the open questions. Where it stands, and the rest, the sync writes below."""
    title = f"{t['key']} · {t['summary']}"
    fm = front([], {"title": title, "type": "project", "date": today.isoformat(), "source": "vault", "keys": t["key"]})
    return (fm + f"# {title}\n\n## Next step\n\nNot written yet: one line, with its date.\n\n## Open questions\n\n"
            "None yet. Each is a box with ela's proposed answer; tick it, or answer with an `ela:` line under it.\n")


def project_head(body):
    """(head, afterwards) of a project page's body: the desk's text above the first tail heading, and the `- ` rows of
    its Afterwards section wherever it sits (the afterwards pass appends below the tail)."""
    m = re.search(r"^" + re.escape(AFTERWARDS_HEAD) + r"[ \t]*\n(.*?)(?=^#{1,2}[ \t]|\Z)", body, re.M | re.S)
    rows = [l for l in (m.group(1) if m else "").splitlines() if l.startswith("- ")]
    cut = TAIL_HEAD_RX.search(body)
    head = WARNING_RX.sub("", body[:cut.start()] if cut else body)   # the reading gate's warning is the sync's, not the head's
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


def project_facts(key, text, today, path=None, ticket=None):
    """A project page as data: its title, deadline and the days to it, its step (the `next-step` property, else the
    first unticked box in the head) with its date and whether it is overdue (its date passed; with no date, the
    deadline passed), its keys, the threads it watches (`posted` and `channels`), the head and the Afterwards rows."""
    fl, body = split_front(text)
    props = props_of(fl)
    head, after = project_head(body)
    dm = re.search(r"\d{4}-\d{2}-\d{2}", props.get("deadline") or "")
    deadline = datetime.date.fromisoformat(dm.group(0)) if dm else None
    box = re.search(r"^[ \t]*[-*][ \t]+\[ \][ \t]+(\S.*?)[ \t]*$", head, re.M)
    # the step: the property, else the Next step section's first box, else its first paragraph (an open question
    # further down is not the step), else the head's first box
    sec = re.search(r"^##[ \t]+Next step[ \t]*\n(.*?)(?=^##[ \t]|\Z)", head, re.M | re.S)
    sec_box = HEAD_BOX.search(sec.group(1)) if sec else None
    para = next((" ".join(p.split()) for p in re.split(r"\n\s*\n", sec.group(1)) if p.strip()), None) if sec else None
    if para and (para.startswith(("Not written yet", "-", "*")) or sec_box):
        para = None
    step = ((props.get("next-step") or "").strip() or (sec_box.group(1).strip() if sec_box else None) or para
            or (box.group(1).strip() if box else None))
    due = step_date(step, today) if step else None
    overdue = bool(step) and ((due < today) if due else (deadline is not None and deadline < today))
    keys = list(dict.fromkeys(k for k in KEY_RX.findall(props.get("keys") or "") if not NOT_KEYS.match(k)))
    links = list(dict.fromkeys(l.rstrip(".") for l in PERMALINK.findall((props.get("posted") or "") + " " + (props.get("channels") or ""))))
    if deadline is None and (ticket or {}).get("due"):     # a Jira project's due date, until the page names its own
        deadline = datetime.date.fromisoformat(ticket["due"][:10])
    return {"key": key, "path": path or f"{PROJECTS}/{key}/{key}.md", "title": props.get("title") or h1(body) or key, "deadline": deadline,
            "days": (deadline - today).days if deadline else None, "step": step, "step_due": due, "overdue": overdue,
            "keys": keys, "links": links, "props": props, "front": fl, "head": head, "afterwards": after, "ticket": ticket}


def project_rows(vault, key, notes=(), page=None):
    """The notes of project `key`: every note carrying `project: <key>`, the vault on disk overlaid with the notes this
    sync writes, plus every note inside projects/<key>/ but the page: [{path, title, type, date, status, next, inside}],
    newest first."""
    page, folder, rows = page or f"{PROJECTS}/{key}/{key}.md", f"{PROJECTS}/{key}/", {}
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


HEAD_BOX = re.compile(r"^[ \t]*[-*][ \t]+\[ \][ \t]+(\S.*?)[ \t]*$", re.M)


def head_asks(head):
    """The head's own unticked boxes, each with the section it sits under: [(section, text)]. A box answered by an
    `ela:` line of his before the next box is not open (as under a reading's Waiting for your word)."""
    boxes = list(HEAD_BOX.finditer(head))
    return [(section_at(head, b.start()), b.group(1)) for i, b in enumerate(boxes)
            if not his_lines(head, b.end(), boxes[i + 1].start() if i + 1 < len(boxes) else len(head))]


def stands_lines(t, jira_base=""):
    """A Jira project's Where it stands, from the fact store: who carries it, its status and since when, its sub-tasks
    each with its status and person, and when Jira was read. [] for a project with no ticket."""
    if not t:
        return []
    def k(x):
        return f"[{x}]({jira_base}/browse/{x})" if jira_base else x
    L = [f"## {STANDS_HEAD}", "", f"Carried by {t.get('owner') or 'nobody yet'} · {t.get('status')}"
         + (f" since {t['since']}" if t.get("since") else "") + (f" · last changed {t['updated']}" if t.get("updated") else "")]
    if t.get("subtasks"):
        L += ["", "Sub-tasks, each under the carrier's ownership:"]
        L += [f"- {k(sk)} {summ} · {st}" + (f" · {who}" if who else "") for sk, summ, st, who in t["subtasks"]]
    L += ["", f"*Read from Jira {t.get('read_at') or 'at the last pass'}.*", ""]
    return L


def meeting_outcomes(notes, keys, today, days=30):
    """What the meeting notes ruled on any of `keys` in the last `days`: [(date, meeting note path, meeting name, line)],
    newest first. A meeting note holds the outcome; the project page shows it (an angle, nothing stored twice)."""
    out, cut = [], (today - datetime.timedelta(days=days)).isoformat()
    want = set(keys or [])
    for n in notes:
        if n.props.get("type") != "meeting" or top(n.path) != MEETINGS or not want:
            continue
        m = meeting_parse("---\n---\n" + n.body)
        name = (m["title"] or n.title or "").split(" · ")[0]
        for d, lines in m["ruled"]:
            if d < cut:
                continue
            for l in lines:
                if l.startswith("- ") and want & set(KEY_RX.findall(l)):
                    out.append((d, n.path, name, l[2:].strip()))
    return sorted(out, key=lambda x: x[0], reverse=True)


def project_tail(facts, rows, today, jira_base="", met=(), asked=()):
    """The sync's half of a project page: TAIL_HEADS in their order, each printed only when it has something to say
    (the hand-kept head is what he reads; the review of 2026-11-11 found the tail a third of the page saying nothing).
    No Waiting for your word: the page's own open questions are on the page, a note beside it holds its own asks, and
    today.md links each once (ADR 0015). The next step is the head's and is not repeated. A label is plain text: a
    title carrying a Markdown link would break the wikilink around it."""
    d = facts["deadline"]
    L = stands_lines(facts.get("ticket"), jira_base)
    if rows:
        L += ["## Notes", ""]
        groups = {}
        for r in rows:
            groups.setdefault("in this folder" if r["inside"] else top(r["path"]), []).append(r)
        for g in list(PROJECT_FOLDERS) + sorted(k for k in groups if k not in PROJECT_FOLDERS):
            if g not in groups:
                continue
            L.append(f"**{g}**" + ("" if g == "in this folder" else "/"))
            for r in groups[g]:
                bits = [r["type"], r["date"], r["status"]]
                L.append(f"- [[{r['path'][:-3]}|{label(r['title'])}]] · " + " · ".join(b for b in bits if b))
            L.append("")
    if met or asked:                                       # what its meetings still ask (ADR 0016), then what they ruled
        L += [f"## {MEETINGS_HEAD}", ""] + [f"- open: {a}" for a in asked] + \
             [f"- {d_[5:]} · [[{p[:-3]}|{label(name)}]]: {line}" for d_, p, name, line in met] + [""]
    keys = [f"[{k}]({jira_base}/browse/{k})" if jira_base else k for k in facts["keys"]]
    links = facts["links"]
    wp = facts["props"]
    watch = wp.get("watch") if "watch" in wp else ((d + datetime.timedelta(days=PROJECT_WATCH_DAYS)).isoformat() if d else None)
    bits = ([f"keys {', '.join(keys)}"] if keys else []) + \
           ([f"{len(links)} thread{'s' if len(links) != 1 else ''}"] if links else []) + ([f"watched until {watch}"] if watch else [])
    if bits or links:
        L += [f"## {TAIL_HEADS[1]}", "", f"*{' · '.join(bits)}*"] + [f"- [thread]({l})" for l in links] + [""]
    if facts["afterwards"]:
        L += [AFTERWARDS_HEAD, ""] + facts["afterwards"] + [""]
    if d:
        L += [f"## {TAIL_HEADS[3]}", "", f"*{d.isoformat()} · {days_words(facts['days'])}*", ""]
    return "\n".join(L)


def project_note(key, text, vault, notes, today, jira_base="", ticket=None, questions=None):
    """The page as the sync writes it: its properties settled (type project, watch defaulting to the deadline plus 14
    days, every other line kept), the head as written, the tail generated. The Note carries front_text, head and tail
    apart, so the head is never linked, unwrapped or retitled."""
    facts = project_facts(key, text, today, project_path(vault, key), ticket)
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
    rows = project_rows(vault, key, notes, facts["path"])
    asked = []
    if questions:                                          # its open team questions raised elsewhere; its own boxes are in its head
        Q = questions_mod()
        for r in Q.open_records(questions):
            if (r.get("thing") or {}).get("ref") == facts["path"] and not all(x.startswith(facts["path"] + "#") for x in r["sources"]):
                asked.append(Q.line(r, jira_base) + (f" · {r['who']}" if r.get("who") else "") +
                             f" · {Q.waited(r, today)} · [[{Q.QUESTIONS_PAGE[:-3]}#^{r['id']}|on the list]]")
    tail = project_tail(facts, rows, today, jira_base, meeting_outcomes(notes, facts["keys"], today), asked)
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

def label(text):
    """A wikilink's label: plain text, no `|` and no `]]`. A Markdown link inside a label (`[[…|[MH-3987](…) · …]]`)
    breaks the wikilink, so a key in a title stays the plain key."""
    return plain(text or "").replace("|", "/").replace("[[", "[").replace("]]", "]")


def link(n):
    return f"[[{n.path[:-3]}|{label(n.title)}]]"


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
             f"[[{ELA}/all-notes.base#Done|done]]"]
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


def parts_rows(skills):
    """The overview's "The parts" table. The vault's row names what the desk is today (layout 5): today.md, a page per
    project, a folder per release line and the meetings, each linked."""
    return ["| part | what it is |", "|---|---|",
            f"| ela | {skills} and the `ela` verbs, in every Claude session |",
            "| ela-runner | the clock, the vault watcher, the Slack front door, the judge sessions |",
            f"| the vault | your desk: [[{TODAY[:-3]}\\|today.md]], a page per project in {PROJECTS}/, a folder per release line in "
            f"{RELEASES}/, the meetings in {MEETINGS}/ |",
            "| elak | facts and knowledge, written on your word |",
            "| published | the redacted subset Helm and colleagues read; its service map, for your review: [[ela/service-map\\|service map]] |",
            "| Helm | the builds ledger and the live release views |"]


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
    L += ["## The parts", ""] + parts_rows(skills) + [""]
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


# ── today.md: the one page ───────────────────────────────────────────────────────────────────────────────────
# The vault as a control panel queued boxes faster than he could clear them (the 11-10 record: Home last opened 11-04,
# items waiting up to eleven mornings). today.md is the one page to open: a few facts, at most three asks that only he
# can answer, today's meetings and deadlines, then one line of links. An ask unanswered for three working mornings
# leaves the page and is written once to reference/dropped.md; it comes back only when its evidence changes. Home is a
# pointer to it for 14 days. Reasons: docs/adr/0014-today-is-the-one-page-and-asks-expire.md.
TODAY, REF = "today.md", "reference"
DROPPED = f"{REF}/dropped.md"
ASK_CAP, ASK_MORNINGS, TODAY_WORDS = 3, 3, 150
HOME_POINTER_UNTIL = datetime.date(2026, 11, 25)       # today.md took Home's place on 2026-11-11; the pointer stays 14 days
FACT_SECTIONS = ("Releases and versions", "Docker services", "QA", "Tickets", "Code")
FACT_LABEL = {"Releases and versions": "Releases", "Docker services": "Docker"}


def working_mornings(first, today):
    """The working mornings (Mon–Fri) from `first` through `today`, both counted."""
    n, d = 0, first
    while d <= today:
        n += d.weekday() < 5
        d += datetime.timedelta(days=1)
    return n


def drop_day(first, today):
    """The working morning an ask first seen on `first` leaves the page: the one after its ASK_MORNINGS-th."""
    d = today
    while working_mornings(first, d) <= ASK_MORNINGS:
        d += datetime.timedelta(days=1)
    while d.weekday() >= 5:
        d += datetime.timedelta(days=1)
    return d


FACT_CHARS = 110
FACTS_MIN = 3                                           # ADR 0014: facts are cut first, never below three


def short_sentence(text, n=FACT_CHARS):
    """The first whole sentence of `text` no longer than n characters, else None: a fact is never cut mid-sentence."""
    for m in re.finditer(r"(.+?[.!?])(?=\s|$)", (text or "").strip()):
        sent = m.group(1).strip()
        if len(plain(sent)) <= n:
            return sent
    return None


def action_id(a):
    """One drafted action's identity across mornings, whatever its number or its form that day: the tickets its command
    acts on (MH-2406 was drafted as a comment, then an assignment, over eleven mornings: one ask), else its command."""
    import hashlib
    targets = re.split(r"\s--", a.get("command") or "", 1)[0]          # the positional targets, not a key in --text
    keys = sorted(set(KEY_RX.findall(targets if a.get("command") else a.get("text") or "")))
    if keys:
        return "keys:" + ",".join(keys)
    return "cmd:" + hashlib.sha256(" ".join((a.get("command") or a.get("text") or "").split()).encode()).hexdigest()[:12]


def evidence_sig(text):
    import hashlib
    return hashlib.sha256(" ".join((text or "").split()).encode()).hexdigest()[:12]


def ask_candidates(today, actions, notes):
    """What only he can answer, in the morning page's order: today's tier-3 drafted actions not yet applied, handled or
    vetoed (a send box is not an ask), then each live note with an open box under Waiting for your word, then each
    project: its head's open questions and its notes' open boxes as one line linking the page.
    [{id, box, text, link, sig, first, options?}]; `first` is the earliest day it was seen; an action that carries its own
    `options` keeps them."""
    iso = today.isoformat()
    seen = {}
    for a in actions:
        if a.get("day"):
            i = action_id(a)
            seen[i] = min(seen.get(i, a["day"]), a["day"])
    out, by_id = [], {}
    for a in sorted((a for a in actions if a.get("day") == iso), key=lambda a: int(a["n"])):
        if a.get("tier", 3) != 3 or a.get("send_box") or a.get("applied") or a.get("by_owner") or a.get("vetoed"):
            continue
        if a.get("rule") == "question":                    # a question's drafted message: its ask is the question's own
            continue
        i = action_id(a)
        if i in by_id:                                     # a second write on the same tickets is the same decision
            c = by_id[i]
            c["ns"].append(int(a["n"]))
            c["box"] = "apply " + ", ".join(str(n) for n in c["ns"])
            c["sig"] = evidence_sig(c["sig"] + (a.get("evidence") or ""))
            continue
        c = {"id": i, "box": f"apply {a['n']}", "ns": [int(a["n"])], "text": a.get("text") or "",
             "sig": evidence_sig(a.get("evidence")), "first": seen.get(i, iso)}
        if a.get("options"):                               # the action's own letters (a reconcile batch: apply · each · skip)
            c["options"] = a["options"]
        by_id[i] = c
        out.append(c)
    projects = {n.facts["key"]: n.facts for n in notes if n.props.get("type") == "project" and getattr(n, "facts", None)}
    held = {}                                              # a project's asks, its notes' open boxes folded in: {key: [n]}
    in_folder = {f["path"].rsplit("/", 1)[0] + "/": k for k, f in projects.items() if f["path"].count("/") == 2}
    for n in sorted(notes, key=lambda n: n.path):
        if (n.props.get("status") or "").lower() not in (LIVE,) + LEGACY_LIVE or n.props.get("type") == "project":
            continue
        left, _ = open_asks(n.body)
        if left and not n.props.get("project"):            # a note in a project's folder belongs to it
            n.props["project"] = next((k for d, k in in_folder.items() if n.path.startswith(d)), None) or \
                next((k for k in projects if n.path.startswith(f"{PROJECTS}/{k}/")), None)
        if left and n.props.get("project") in projects:
            held.setdefault(n.props["project"], []).append((left, n))
        elif left:
            out.append({"id": f"note:{n.path}", "text": f"{n.title} ({left} open)", "link": n.path[:-3],
                        "sig": evidence_sig(n.body), "first": (n.props.get("date") or iso)[:10]})
    for key, f in projects.items():                        # an ask on a thing shows once, as a line linking the thing
        mine = head_asks(f["head"])
        others = held.get(key, [])
        count = len(mine) + sum(left for left, _ in others)
        if not count:
            continue
        name = re.sub(r"^[A-Z][A-Z0-9]+-\d+ · ", "", plain(f["title"]))
        first = min([(n.props.get("date") or iso)[:10] for _, n in others] + [iso])   # the state keeps the earliest seen
        lead = (f["keys"] or [""])[0]
        out.append({"id": f"project:{key}", "text": f"{count} open question{'s' if count != 1 else ''} on "
                    f"{lead + ' ' if lead else ''}{name}", "link": f["path"][:-3],
                    "sig": evidence_sig(" ".join(t for _, t in mine) + " ".join(n.path for _, n in others)), "first": first})
    return out


def settle_asks(state, cands, today):
    """(shown, more, dropped now, state): an ask shown on more than ASK_MORNINGS working mornings leaves the page,
    recorded once in the state with the day it dropped; a dropped ask stays off until its evidence changes, when it
    starts over. At most ASK_CAP are shown. An ask is aged from the first morning it is shown: what waits below the cap
    is not counted, not aged and not stored (`more` says how many, for the caller's own use only).
    state: {id: {first, text, sig, dropped}}."""
    iso = today.isoformat()
    state = {k: dict(v) for k, v in (state or {}).items()}
    live, dropped_now, waiting = [], [], 0
    for c in cands:
        st = state.get(c["id"])
        if st and st.get("answered") and st.get("sig") == c["sig"]:
            continue                                       # he answered it by a letter: off the page until it changes
        if st and st.get("dropped"):
            if st.get("sig") == c["sig"]:
                continue                                   # nothing changed since it dropped: it stays off the page
            first = iso                                    # the world changed: it starts over today
        elif st:
            first = st["first"]
        elif len(live) >= ASK_CAP:
            waiting += 1                                   # below the cap: an also-noticed line, not an ask yet
            continue
        else:
            first = iso                                    # first shown today: its mornings start now
        st = {"first": first, "text": c["text"], "sig": c["sig"], "dropped": None}
        if working_mornings(datetime.date.fromisoformat(first), today) > ASK_MORNINGS:
            st["dropped"] = iso
            dropped_now.append(dict(c, first=first))
        elif len(live) < ASK_CAP:
            live.append(dict(c, first=first))
        else:
            waiting += 1                                   # shown before, pushed below the cap today: it keeps its age
            continue
        state[c["id"]] = st
    return live, waiting, dropped_now, state


def fact_lines(notes, limit=4):
    """The newest What-changed page's first line per section that changes the picture (releases, docker services, QA,
    tickets, code): [(label, line)], with the page's date."""
    pages = sorted((n for n in notes if n.props.get("type") == "day" and n.props.get("kind") == "changes"),
                   key=lambda n: n.props.get("date") or "", reverse=True)
    if not pages:
        return None, []
    out = []
    for head, text in sections(pages[0].body):
        if head in FACT_SECTIONS:
            line = short_sentence(first_line(text) or "")
            if line:
                out.append((head, line))
    order = {h: i for i, h in enumerate(FACT_SECTIONS)}
    return pages[0], sorted(out, key=lambda x: order[x[0]])[:limit]


HANDLED_BOX = re.compile(r"^[ \t]*" + QUOTE + r"[-*][ \t]+\[[ xX]\][ \t]+I handled it myself — not apply[ \t]+(\d+)\b.*$")
MORE_FOLD = re.compile(r"^(>[ \t]*\[!note\]-[ \t]*)\d+ more[ \t]*$")


def also_noticed(text, hidden):
    """The morning page with a box and a number only on the apply actions today.md shows as asks: each open apply box
    in `hidden` (the drafted asks below the cap, numbers) becomes a plain line, its "handled it myself" box goes, and
    the `N more` fold is titled Also noticed. A box already ticked or settled is left as it is."""
    out = []
    for line in text.split("\n"):
        h = HANDLED_BOX.match(line)
        if h and int(h.group(1)) in hidden and "[ ]" in line:
            continue
        m = re.match(r"^([ \t]*" + QUOTE + r"[-*][ \t]+)\[ \][ \t]+apply[ \t]+(\d+)\b[ \t]*(?:—[ \t]*)?(.*)$", line)
        if m and int(m.group(2)) in hidden:
            line = m.group(1) + m.group(3)
        f = MORE_FOLD.match(line)
        if f:
            line = f.group(1) + "Also noticed"
        out.append(line)
    return "\n".join(out)


INLINE_MAX = 5                                          # tickets shown under the build block's service lines, in all
QA_TROUBLE = ("reopened", "blocked", "failed", "qa failed")


def inline_tickets(rec, tickets, owner="", meeting_keys=()):
    """{key} shown inline under their service on today.md, by what each means to the owner: (a) assigned to or reported
    by him, (b) reopened, blocked or failed in QA, (c) on a meeting note dated today; then a service's tickets when it
    carries three or fewer. At most INLINE_MAX in that order; the rest are the count linking the build note."""
    keys = list(dict.fromkeys(k for v in rec["services"] for k in v.get("keys") or []))
    t = lambda k: tickets.get(k) or {}                    # noqa: E731
    a = [k for k in keys if owner and owner in (t(k).get("assignee"), t(k).get("reporter"))]
    b = [k for k in keys if (t(k).get("status") or "").lower() in QA_TROUBLE]
    c = [k for k in keys if k in set(meeting_keys)]
    small = [k for v in rec["services"] if len(v.get("keys") or []) <= 3 for k in v.get("keys") or []]
    return set(list(dict.fromkeys(a + b + c + small))[:INLINE_MAX])


def build_block(notes, builds, today, tickets=None, owner=""):
    """The Releases fact when a lane took a build since the last page: each build a sentence linking its release note,
    then one line per changed service (its move and what for, never a cluster of keys), BUILD_LINES lines in all. Under
    a service, the tickets inline_tickets picks, each in words; the rest as "N more tickets" linking the service's
    section of the note. A ticket two services carry shows once, under the first, its line naming the others. Since
    the last page: dated from the page before the newest What-changed page (the day before
    today when there is none) through today. None when no build."""
    if not builds:
        return None
    R = release_mod()
    tickets = tickets or {}
    days = sorted({(n.props.get("date") or "")[:10] for n in notes if n.props.get("type") == "day" and n.props.get("kind") == "changes"})
    days = [d for d in days if d and d <= today.isoformat()]
    since = days[-2] if len(days) > 1 else (today - datetime.timedelta(days=1)).isoformat()
    recent = sorted((b for b in builds if since <= b["date"] <= today.isoformat()), key=lambda b: (b["date"], b["name"]))
    if not recent:
        return None
    met = {k for n in notes if n.props.get("type") == "meeting" and (n.props.get("date") or "")[:10] == today.isoformat()
           for k in KEY_RX.findall(n.body or "")}
    heads, rows, room, budget = [], [], R.BUILD_LINES, INLINE_MAX
    placed = set()                                          # a ticket shown once in the block, under its first service
    for b in recent:
        if room <= 0:
            break
        note = f"{RELEASES}/{b['line']}/{b['name']}"
        heads.append(f"{b.get('lane_name') or b['lane']} took build {b['build']} ([[{note}|release note]])")
        svcs = b.get("services") or []
        shown = svcs if len(svcs) <= room else svcs[:max(room - 1, 1)]
        pick = inline_tickets(b, tickets, owner, met)
        carriers = {}
        for v in svcs:
            for k in v.get("keys") or []:
                carriers.setdefault(k, []).append(v["service"])
        for v in shown:
            keys = v.get("keys") or []
            inline = [k for k in keys if k in pick and k not in placed][:budget]
            budget -= len(inline)
            placed.update(inline)
            rest = len([k for k in keys if k not in inline and not (k in placed and k in pick)])
            more = f" · [[{note}#{v['service']}|{rest} {'more ' if inline else ''}ticket{'s' if rest != 1 else ''}]]" if rest else ""
            rows.append(f"  - {v['service']} {R.service_move(v)}: {' '.join(str(v['for']).split())}{more}")
            rows += [f"    - {R.ticket_line(k, tickets.get(k), who=False)}"
                     + (" · also " + ", ".join(s for s in carriers[k] if s != v["service"]) if len(carriers.get(k, [])) > 1 else "")
                     for k in inline]
        if len(shown) < len(svcs):
            rows.append(f"  - {len(svcs) - len(shown)} more services in the release note")
        room -= len(shown) + (len(shown) < len(svcs))
    return "; ".join(heads) + ".\n" + "\n".join(rows)


ASK_WORDS = 20


def ask_words(text, n=ASK_WORDS):
    """An ask as one whole sentence of at most n words: the text when it fits, else its first clause (up to `;`, ` (`
    or ` — `) when that fits, else the whole text: an ask is never cut mid-phrase. It ends with a full stop."""
    text = " ".join((text or "").split())
    head = re.split(r";\s| \(| — ", text, 1)[0]
    out = text if len(plain(text).split()) <= n or len(plain(head).split()) > n else head
    out = out.rstrip(" ,;:")
    return out if re.search(r"[.!?]$", out) else out + "."


# ── the shape of an ask (the desk's addition to the dry-run brief, 2026-11-12) ─────────────────────────────────────
# Every ask is one line of question and two or three lettered options, each saying what happens; A is ela's
# recommendation and says so; doing nothing is stated once. He answers by one letter: a tick on the option line,
# `ela: A` under the ask or `ela: 2 B` anywhere on today.md, the letter in a session. `apply N` keeps meaning that ask's A.
# An option's `does` is what the letter runs: `apply N` (the runner, as before), `drop` (the sync: the ask leaves, by his
# word), `ela dry answer …` (the sync runs it, unless it carries --apply, which is the runner's), or None (nothing to run).
def opt(letter, text, does, recommended=False):
    return {"letter": letter, "text": text, "does": does, "recommended": recommended}


def ask_options(c):
    """A candidate's options: its own when it carries them, else by its kind."""
    if c.get("options"):
        return c["options"]
    ns = c.get("ns") or []
    if c["id"].startswith(("keys:", "cmd:")) and ns:
        both = "" if len(ns) == 1 else " both" if len(ns) == 2 else f" all {len(ns)}"
        return [opt("A", f"apply{both} as drafted", "apply " + ", ".join(str(n) for n in ns), True), opt("B", "drop it", "drop")]
    return [opt("A", "answer in the note", None, True), opt("B", "drop it from today", "drop")]


ASK_HEAD = re.compile(r"^(\d+)\.[ \t]+\S", re.M)
OPTION_TICK = re.compile(r"^([ABC])(?:[ \t]+\(recommended\))?:")
LETTER_LINE = re.compile(r"^(?:(\d+)[ \t]*)?([ABCabc])\.?$")


def slot_at(text, pos):
    found = None
    for m in ASK_HEAD.finditer(text, 0, pos):
        found = int(m.group(1))
    return found


def today_letters(text, state):
    """His letters on today.md: [{slot, letter, id, does, raw, kind, pos}], each resolved against the ask state's slots
    (the asks the page was written with). A tick on an option line, or `ela: A` under an ask, answers that ask; `ela: 2 B`
    answers ask 2 wherever it is written. A letter no ask offers is left out."""
    slots = {v["slot"]: (k, v) for k, v in (state or {}).items() if isinstance(v, dict) and v.get("slot")}
    out = []
    found = [(m, "tick", OPTION_TICK.match(m.group(1))) for m in TICKED.finditer(text or "")]
    found += [(m, "line", LETTER_LINE.match(m.group(1).strip())) for m in his_lines(text or "")]
    for m, kind, x in found:
        if not x:
            continue
        if kind == "tick":
            slot, letter = slot_at(text, m.start()), x.group(1)
        else:
            slot = int(x.group(1)) if x.group(1) else (slot_at(text, m.start()) or (next(iter(slots)) if len(slots) == 1 else None))
            letter = x.group(2).upper()
        if slot not in slots:
            continue
        aid, v = slots[slot]
        if letter not in (v.get("options") or {}):
            continue
        out.append({"slot": slot, "letter": letter, "id": aid, "does": v["options"][letter], "raw": m.group(1), "kind": kind, "pos": m.start()})
    return out


def sync_handles(does):
    """Whether the sync acts on this letter itself (nothing leaves ela): a drop, a no-op, or a dry answer that writes
    nothing live. The rest goes to the runner through `ela vault guidance`."""
    return does is None or does == "drop" or (does.startswith("ela dry answer ") and "--apply" not in does)


def settle_letters(vault, reports, state, today, dry_run=False):
    """The letters on today.md the sync acts on itself, once each: B `drop` takes the ask off the page by his word (into
    dropped.md, marked so); a dry answer that writes nothing live (a grant's A, B or C; a batch's B) runs here. The ask
    remembers the letter, so a page rewritten with the tick still on it does not act twice. → [(id, letter)]."""
    try:
        text = open(os.path.join(vault, TODAY), encoding="utf-8").read()
    except OSError:
        return []
    return [(x["id"], x["letter"]) for x in today_letters(text, state)
            if settle_one(reports, state, x["id"], x["letter"], x["does"], today, dry_run)]


def settle_one(reports, state, aid, letter, does, today, dry_run=False):
    """One letter the sync acts on itself, once: True when it acted (a dry run acts on the state, not the dry store)."""
    v = state.get(aid) or {}
    if v.get("answered") or not sync_handles(does):
        return False
    if does and does.startswith("ela dry answer ") and not dry_run:
        parts = does.split()
        try:
            dry_mod().answer(reports, parts[3], parts[4])
        except (KeyError, ValueError):
            return False
    v["answered"] = {"letter": letter, "at": today.isoformat()}
    if does == "drop":
        v["dropped"], v["by"] = today.isoformat(), "owner"
    state[aid] = v
    return True


def answer_by_letter(reports, slot, letter, today, apply=False):
    """His letter given outside the page (`2 B` in Slack, the letter in a session), resolved exactly as a tick on
    today.md is: → {ask, letter, does, done, run}. `done` when this verb settled it (a drop, a dry answer that writes
    nothing live), with --apply; `run` the command the runner runs otherwise (`apply N`, a batch's --apply). Raises
    KeyError for a slot today.md does not show, ValueError for a letter that ask does not offer."""
    state = load_asks(reports)
    slots = {v["slot"]: k for k, v in state.items() if isinstance(v, dict) and v.get("slot")}
    if slot not in slots:
        raise KeyError(slot)
    aid, letter = slots[slot], letter.upper()
    opts = state[aid].get("options") or {}
    if letter not in opts:
        raise ValueError(f"ask {slot} offers {', '.join(sorted(opts))}, not {letter}")
    does = opts[letter]
    out = {"ask": aid, "slot": slot, "letter": letter, "does": does, "done": False, "run": None}
    if state[aid].get("answered"):
        out["done"] = "already answered " + state[aid]["answered"]["letter"]
    elif sync_handles(does):
        if apply and settle_one(reports, state, aid, letter, does, today):
            atomic_write(os.path.join(reports, "ela", "asks.json"), json.dumps(state, indent=1, ensure_ascii=False))
        out["done"] = apply
    else:
        out["run"] = does
    return out


def cmd_answer(a):
    """`ela vault answer N L`: one letter on today's ask N, from anywhere."""
    s = json.load(open(SITE))
    try:
        r = answer_by_letter(s.get("reports") or "", a.slot, a.letter, datetime.date.today(), a.apply)
    except KeyError:
        print(f"no ask {a.slot} on today.md", file=sys.stderr); sys.exit(3)
    except ValueError as x:
        print(str(x), file=sys.stderr); sys.exit(2)
    if a.json:
        print(json.dumps(r, ensure_ascii=False)); return
    if r["run"]:
        print(f"ask {r['slot']} {r['letter']}: the runner runs `{r['run']}`")
    elif r["done"] is True:
        print(f"ask {r['slot']} {r['letter']}: done ({r['does'] or 'nothing to run'})")
    elif r["done"]:
        print(f"ask {r['slot']}: {r['done']}")
    else:
        print(f"ask {r['slot']} {r['letter']}: would do `{r['does'] or 'nothing'}`; --apply settles it")


def dry_asks(reports, today, asks_state, dry_run=False):
    """The dry-run classes on today.md: one ask per class batch waiting, one grant ask per mature class, each in the
    lettered shape; and the Facts lines, what granted classes did without confirm and any class that fell back to
    confirm today. → (candidates, fact lines). A broken store costs these asks only."""
    try:
        D = dry_mod()
        got = D.asks(reports, today, commit=not dry_run, ask_state=asks_state)
        line, _ = D.did(reports, today.isoformat())
        facts = ([f"{line} → [[{ELA}/dry/did|the list, each undoable by a word]]"] if line else []) + D.notices(reports, today.isoformat())
    except Exception:                                      # noqa: BLE001 — the page is written without them
        return [], []
    out = []
    for x in got:
        text = x["question"] + (f" {x['record']}." if x.get("record") else "")
        out.append({"id": x["id"], "text": text, "whole": True, "options": x["options"], "link": x.get("link"),
                    "sig": x["sig"], "first": today.isoformat()})
    return out, facts


def dry_pages(vault, reports, today):
    """ela/dry/<batch>.md for each batch waiting: written once, then his (a struck or edited line is what the answer
    reads), and ela/dry/did.md, today's acts without confirm with the word that undoes each."""
    out = {}
    try:
        D = dry_mod()
        for b in D.batches(reports):
            if b.get("state") != "open":
                continue
            rel = f"{D.note_rel(b['id'])}.md"
            try:
                out[rel] = open(os.path.join(vault, rel), encoding="utf-8").read()   # his copy: struck and edited lines stay
            except OSError:
                out[rel] = front([], {"type": "dry", "date": today.isoformat()}) + D.review_note(b)
        line, rows = D.did(reports, today.isoformat())
        out[f"{ELA}/dry/did.md"] = front([], {"type": "dry", "date": today.isoformat()}) + "\n".join(
            [f"# Done by ela · {today:%a %Y-%m-%d}", "", "Writes of a granted class ela made without asking. Write the undo line "
             "here or on today.md and ela reverses that one; a reversal also returns the class to your confirm.", ""]
            + ([f"- {n}. {t} · `{u}`" for n, t, u in rows] or ["Nothing today."])) + "\n"
    except Exception:                                      # noqa: BLE001
        pass
    return out


def dry_mod():
    sys.path.insert(0, os.path.join(HERE, "..", "dry"))
    import dry as D                                        # noqa: E402 — the class records' one reader and writer
    return D


def short(text, n):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + " …"


def today_page(today, notes, desk=None, shown=(), more=0, dropped=0, questions_line=None):
    """today.md: Facts (3–5 lines), Needs you (at most three asks, each with what happens if he does nothing and
    when), Today (meetings, a near deadline, what leaves at 10:00), then one line of links. Above the line it keeps
    within TODAY_WORDS words: facts are cut from the end until it does."""
    desk = desk or {}
    iso = today.isoformat()
    changes, facts = fact_lines(notes)
    block = build_block(notes, desk.get("builds") or [], today, desk.get("tickets"), desk.get("owner") or "")
    if block:                                              # a lane took a build: the Releases fact is the build, by service
        facts = [("Releases and versions", block)] + [f for f in facts if f[0] != "Releases and versions"]
    facts = [("Done by ela", l) for l in desk.get("dry_facts") or []] + facts   # ela's own acts and falls lead: never cut
    briefs = sorted((n for n in notes if n.props.get("type") == "day" and n.props.get("kind") == "brief"),
                    key=lambda n: n.props.get("date") or "", reverse=True)
    brief = briefs[0] if briefs else None
    asks = []
    for k, c in enumerate(shown, 1):
        gone = drop_day(datetime.date.fromisoformat(c["first"]), today)
        # the words stay outside the wikilink: a ticket key inside a link's label would be linked again and break it
        what = (c["text"] if c.get("whole") else ask_words(c["text"])) + \
            (f" → [[{c['link']}|{'its section' if '#' in c['link'] else 'the note'}]]" if c.get("link") else "")
        asks.append(f"{k}. {what} · *no answer: nothing happens; gone {gone:%a}*")
        asks += [f"    - [ ] {o['letter']}{' (recommended)' if o['recommended'] else ''}: {o['text']}" for o in ask_options(c)]
    acts = [a for a in desk.get("actions") or [] if a.get("day") == iso]
    soon = [a for a in acts if a.get("tier") == 2 and not (a.get("applied") or a.get("vetoed") or a.get("failed"))]
    hold = desk.get("hold")
    day = []
    notes_today = sorted((n for n in notes if n.props.get("type") == "meeting" and (n.props.get("date") or "")[:10] == iso),
                         key=lambda n: n.path)
    for n in notes_today:                                  # the meeting's own note, dated today, by its title
        day.append(f"- [[{n.path[:-3]}|{n.title}]]")
    have = {os.path.basename(n.path)[:-3] for n in notes_today}
    for m in [m for m in desk.get("meetings") or [] if m.get("key") not in have] if not notes_today else []:
        note = f"{MEETINGS}/{m['key']}" if m.get("key") else None
        day.append(f"- {m.get('time')} {m.get('name')}" + (f" → [[{note}|its list]]" if note else ""))
    projects = [n.facts for n in notes if n.props.get("type") == "project" and getattr(n, "facts", None)]
    for f in projects:
        if f.get("days") is not None and 0 <= f["days"] <= PROJECT_SOON_DAYS:
            day.append(f"- [[{f['path'][:-3]}|{f['key']}]]: {days_words(f['days'])} to {f['deadline'].isoformat()}")
    if questions_line:                                     # the team's open questions: one line, the page behind it
        day.append(questions_line)
    if soon:
        day.append(f"- At 10:00 ela does {len(soon)} drafted action{'s' if len(soon) != 1 else ''}"
                   + (f", held until {hold['until']} (dry run)" if hold else "; tick `don't N` to stop one"))
        day += [] if hold else [f"  - [ ] don't {a['n']} — {short(a.get('text'), 90)}" for a in soon]

    def render(facts):
        L = [f"# Today · {today:%a %Y-%m-%d}", "", "## Facts", ""]
        L += [f"- **{FACT_LABEL.get(h, h)}:** {l}" for h, l in facts] or ["- Nothing new was read since the last page."]
        L += ["", "## Needs you", ""] + (asks or ["Nothing only you can do."])
        L += ["", "## Today", ""] + (day or ["No meeting and no deadline today."]) + [""]
        return L
    L = render(facts)
    def words(L):
        return len(plain("\n".join(L)).split())
    while len(facts) > FACTS_MIN and words(L) > TODAY_WORDS:   # whole facts leave from the end, never below three
        facts = facts[:-1]
        L = render(facts)
    links = [f"[[{changes.path[:-3]}|what changed]]" if changes else None,
             f"[[{brief.path[:-3]}|morning page]]" if brief else None,
             f"[[{LANES_PAGE[:-3]}|lanes]]" if any(n.props.get("type") == "lanes" for n in notes) else None,
             ("projects: " + " · ".join(f"[[{f['path'][:-3]}|{project_label(f)}]]" for f in projects)) if projects else None,
             f"[[{DROPPED[:-3]}|dropped asks]]" + (f" ({dropped})" if dropped else ""),
             f"[[{OVERVIEW[:-3]}|ela]]"]
    return "\n".join(L + ["---", "", " · ".join(x for x in links if x), ""])


def project_label(f):
    """A project's short name in a list of links: its ticket key when the page is that ticket's, else its page key."""
    lead = (f.get("keys") or [None])[0]
    return lead if lead and f["key"].startswith(lead.lower() + "-") else f["key"]


def dropped_page(state):
    """reference/dropped.md: every ask that left today.md unanswered, newest first, once each: the day it dropped, the ask,
    and the day it was first asked. Written from the ask state, so a drop appears once and stays."""
    rows = sorted(((v["dropped"], v.get("first") or "", (v.get("text") or k) + (" · dropped by your word" if v.get("by") == "owner" else ""))
                   for k, v in (state or {}).items() if v.get("dropped")), reverse=True)
    L = ["# Dropped asks", "", "Asks that left today's page after three working mornings without your word. Nothing was "
         "done about them. One comes back only when its evidence changes; say the word in a session to act on one now.", ""]
    L += [f"- {d} · {short(t, 160)} · asked since {f}" for d, f, t in rows] or ["Nothing has dropped yet."]
    return "\n".join(L) + "\n"


def home_pointer():
    """home.md until HOME_POINTER_UNTIL: three lines pointing to today.md."""
    return (f"# Home\n\nThe page to open is [[today]]: facts, at most three asks, today's meetings.\n\n"
            f"This pointer goes on {HOME_POINTER_UNTIL.isoformat()}.\n")


def load_asks(reports):
    try:
        return json.load(open(os.path.join(reports or "", "ela", "asks.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def home_open(vault):
    """Whether Home is open in a tab, read from Obsidian's own workspace file; False when it cannot be read."""
    def files(node):
        if node.get("type") == "leaf":
            yield ((node.get("state") or {}).get("state") or {}).get("file")
        for c in node.get("children") or []:
            yield from files(c)
    try:
        return bool({"home.md", TODAY} & set(files(json.load(open(os.path.join(vault, ".obsidian", "workspace.json"), encoding="utf-8")).get("main") or {})))
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
# One note per meeting, meetings/<key>.md, written in place by `ela meeting` and shown to the team: Where things stand,
# To raise (one line an item, its detail folded under it) and Ruled by date, newest first; no send line. The sync rolls a Ruled date older than 30 days into
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


MEETING_STAND = "Where things stand"
SINCE_TAG = re.compile(r"[ \t]*·[ \t]*since[ \t]+(\d{2}-\d{2})\b")


def meeting_day(title):
    """The meeting day a note's title names (`… · Wed 2026-11-11`), else None."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*$", title or "")
    try:
        return datetime.date.fromisoformat(m.group(1)) if m else None
    except ValueError:
        return None


def meeting_render(n, title, send_text=None, today=None):
    """The note written back, as it is shown to the team: its properties (aliases hold only the title), the title,
    Where things stand, To raise, Ruled by date (newest first), then any other section he added, kept unchanged. No send
    line and no ela command: sending is the verb's (`ela meeting --key K --slack`). An item says `since <date>` only
    when it is older than the meeting day; the date is kept on the item otherwise and comes back when it rolls."""
    keep = [l for l in n["front"] if not re.match(r"^(title|aliases|type|date|source):", l)]
    day = meeting_day(title)                               # its date is the meeting's: today.md lists it on that day only
    props = front([], {"title": title, "type": "meeting", "date": (day or today or datetime.date.today()).isoformat(), "source": "vault"})
    if keep:
        props = props[:-len("---\n\n")] + "\n".join(keep) + "\n---\n\n"
    intro = "\n".join(n["intro"]).strip("\n")
    out = [f"# {title}", ""] + ([intro, ""] if intro else [])
    others = list(n["others"])
    for h, lines in [x for x in others if x[0] == MEETING_STAND]:   # what stands is read before what is raised
        body = "\n".join(lines).strip("\n")
        out += [f"## {h}", ""] + ([body, ""] if body else [])
    out += [f"## {MEETING_RAISE}", ""]
    head = "\n".join(n["head"]).strip("\n")
    out += ([head, ""] if head else [])
    for it in n["items"]:
        text = it["text"]
        since = meeting_fields(text)["since"]
        if day and since and meeting_since(since, day) == day:
            text = SINCE_TAG.sub("", text)                  # raised for this meeting: no age to show
        out += [f"- [{'x' if it['ticked'] else ' '}] {text}"] + it["under"]
    out += ([""] if n["items"] else []) + [f"## {MEETING_RULED}", ""]
    rh = "\n".join(n["ruled_head"]).strip("\n")
    out += ([rh, ""] if rh else [])
    for d, lines in sorted(n["ruled"], key=lambda x: x[0], reverse=True):
        body = "\n".join(lines).strip("\n")
        out += [f"### {d}", ""] + ([body, ""] if body else [])
    for h, lines in [x for x in others if x[0] != MEETING_STAND]:
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
    parts += [f"since {since:%m-%d}"]                     # no "ela proposes": the note is shown to the team (2026-11-10)
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


def meeting_rule(n, today, last_meeting, raised_for=None):
    """His ticks and `ela:` lines applied. An item that was on the list at a meeting held (since on or before
    `last_meeting`, a date or None) is ruled by an `ela:` line under it (its words) or a tick with none; one ticked
    before any meeting saw it is dropped, and `ela: drop` drops either. Each leaves To raise for `### <today>` under
    Ruled, its plain detail folded under it. An item without its `since` was raised for the meeting the title names
    (`raised_for`). → [{key, text, outcome: ruled|dropped, words}]."""
    out, stay, lines = [], [], []
    for it in n["items"]:
        f = meeting_fields(it["text"])
        guides = [g.group(1).strip() for g in (GUIDE.match(l) for l in it["under"]) if g]
        words = [g for g in guides if not MEETING_DROP.match(g) and not MEETING_ORDER.match(g)]
        since = meeting_since(f["since"], today) if f["since"] else raised_for
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
    """Lint lines for a meeting note: an item over 140 characters as reading mode shows it, a send line left on it, a
    missing section."""
    n, out = meeting_parse(text), []
    dated = bool(re.match(r"^\d{4}-?\d{2}-?\d{2}-", os.path.basename(path)))
    if not ela_wrote(text) or dated:                       # his own note, or one built from the records: its sections are its own
        return [f"{path}: a send line on a page shown to the team; sending is `ela meeting --key <key> --slack`"] if n["send"] else []
    if n["send"]:
        out.append(f"{path}: a send line on a page shown to the team; sending is `ela meeting --key <key> --slack`")
    for want in (MEETING_RAISE, MEETING_RULED):
        if not re.search(r"^##[ \t]+" + re.escape(want) + r"[ \t]*$", split_front(text)[1], re.M):
            out.append(f"{path}: no ## {want} section")
    for i, it in enumerate(n["items"], 1):
        k = len(visible(it["text"]))
        if k > MEETING_ITEM_MAX:
            out.append(f"{path}: item {i} is {k} characters, over {MEETING_ITEM_MAX}; fold the detail under it")
    return out


def legacy_form(text):
    """The verb's form of a meeting note, meetings/<key>.md with a `## To raise` section: the one close and roll write."""
    return bool(re.search(r"^##[ \t]+" + re.escape(MEETING_RAISE) + r"[ \t]*$", split_front(text or "")[1], re.M))


def ela_wrote(text):
    """Whether ela wrote this meeting note and may write it again: the verb's form (a `## To raise` section) or a dated
    note it built (`by: "ela"`). A note he or a session wrote by hand is input only, never rewritten (the hand-written
    sync note of 2026-11-12, <runtime>/drafts/2026-11-12-open-questions-brief.md)."""
    fl, body = split_front(text or "")
    return any(re.match(r"^by:\s*['\"]?ela['\"]?\s*$", l) for l in fl) or \
        bool(re.search(r"^##[ \t]+" + re.escape(MEETING_RAISE) + r"[ \t]*$", body, re.M))


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
        if not any(re.match(r"^type:\s*['\"]?meeting['\"]?\s*$", l) for l in fl) or not legacy_form(text):
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


# ── a meeting closed by ela: what changed on each item's ticket after the meeting began ───────────────
# His ticks and `ela:` lines rule an item when he writes them; nothing requires them. After the meeting's end, the
# next sync reads each item's ticket in the fact store (<runtime>/facts/jira/issues/) and its thread, if the item links
# one (<runtime>/facts/slack/), for what changed since the meeting began, and writes the outcome under Ruled itself. An
# item with no change is carried to the next meeting until an outcome comes (ADR 0016). Reason: the review of the
# vault's first day on layout 5 (<runtime>/drafts/2026-11-12-vault-two-day-review-brief.md, change 4).
MEETING_HOURS = 1                                       # a meeting's length when meetings.yaml gives no `minutes`
# its own name: as SLACK_LINK it replaced the Linker's `<url|text>` pattern, which then turned every permalink in a page
# into "[<ts>](<channel>)" (build 91's release note, 2026-11-12)
SLACK_THREAD = re.compile(r"/archives/([A-Z0-9]+)/p(\d{10})(\d{6})")


def facts_issue(facts, key):
    try:
        return json.load(open(os.path.join(facts, "jira", "issues", f"{key}.json"), encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def jira_time(v):
    """A Jira or ISO timestamp → an aware datetime, None when it does not parse."""
    try:
        return datetime.datetime.fromisoformat(re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", str(v or "").replace("Z", "+00:00")))
    except ValueError:
        return None


def and_list(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


BOT_AUTHOR = re.compile(r"^(?:Automation\b|Slack$|Jira$|GitLab|GitHub|Jenkins)", re.I)   # an integration's comment is not a person's


def ticket_outcome(facts, key, start, before=None):
    """What changed on `key` after `start` (aware), read from the fact store: the tickets it was split into (linked
    tickets created since), a status it moved to, a new assignee (against `before`, the item's ticket as the pass
    before the meeting saw it: {status, assignee}), who commented. → (words or None when nothing changed, read)."""
    d = facts_issue(facts, key)
    if not d:
        return None, False
    f = d.get("fields") or {}
    bits = []
    linked = sorted({(l.get("outwardIssue") or l.get("inwardIssue") or {}).get("key") for l in f.get("issuelinks") or []}
                    | {x.get("key") for x in f.get("subtasks") or []} - {None})
    new = []
    for k in linked:
        o = facts_issue(facts, k) if k else None
        t = jira_time(((o or {}).get("fields") or {}).get("created"))
        if t and t >= start:
            new.append(k)
    if new:
        bits.append(("split into " if len(new) > 1 else "opened ") + and_list(new))
    status = (f.get("status") or {}).get("name")
    moved = jira_time(f.get("statuscategorychangedate"))
    if status and ((before or {}).get("status") and before["status"] != status or not before and moved and moved >= start):
        bits.append(f"moved to {status}")
    who = (f.get("assignee") or {}).get("displayName")
    if before and who and before.get("assignee") != who:
        bits.append(f"assigned to {who}")
    authors = []
    for c in d.get("comments") or ((f.get("comment") or {}).get("comments") or []):
        a = (c.get("author") or {}).get("displayName") or ""
        t = jira_time(c.get("created"))
        if t and t >= start and a and not BOT_AUTHOR.match(a) and a not in authors:
            authors.append(a)
    if authors:
        bits.append("comment by " + and_list(authors))
    return ("; ".join(bits) or None), True


def thread_outcome(facts, text, start):
    """Replies after `start` in the Slack thread an item links, from the fact store: 'N replies in its thread' or None."""
    m = SLACK_THREAD.search(text or "")
    if not m:
        return None
    try:
        doc = json.load(open(os.path.join(facts, "slack", f"{m.group(1)}.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ts = f"{m.group(2)}.{m.group(3)}"
    replies = (doc.get("replies") or {}).get(ts) or []
    n = sum(1 for r in replies if r.get("ts") != ts and float(r.get("ts") or 0) >= start.timestamp())
    return f"{n} repl{'y' if n == 1 else 'ies'} in its thread" if n else None


def meeting_window(meeting, day):
    """(start, end) of the meeting on `day`, aware, from meetings.yaml (`time`, `minutes`); a meeting without a time
    is taken as the working day (09:00–18:00)."""
    tz = datetime.datetime.now().astimezone().tzinfo
    t = str((meeting or {}).get("time") or "").strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", t):
        start = datetime.datetime.combine(day, datetime.time(*map(int, t.split(":"))), tz)
        mins = int((meeting or {}).get("minutes") or MEETING_HOURS * 60)
        return start, start + datetime.timedelta(minutes=mins)
    return datetime.datetime.combine(day, datetime.time(9), tz), datetime.datetime.combine(day, datetime.time(18), tz)


def meeting_book():
    """(meetings.yaml's meetings, next_day): read through the brief, which owns the owner's day; ([], None) when it
    cannot be read, so a sync never fails on it."""
    try:
        sys.path.insert(0, os.path.join(HERE, "..", "brief"))
        import brief as B
        doc = B.owner_day()
        return doc.get("meetings") or [], lambda m, day: next(B.meeting_slots(m, doc, day + datetime.timedelta(days=1), 1), None)
    except Exception:
        return [], None


def meeting_snapshot_path(reports):
    return os.path.join(reports or "", "ela", "meetings.json")


def meeting_close(vault, reports, facts, now, meetings, next_day=None, dry_run=False, jira=""):
    """Each meeting note whose meeting has ended and is not yet closed: his ticks and `ela:` lines applied first, then
    each item left is read for what changed since the meeting began; a change is its outcome under `### <day>` in
    Ruled, the rest are carried to the next meeting (their `since` kept) until an outcome comes: a team question never
    leaves for reference/dropped.md (ADR 0016); its record is the open-questions pass's. Before a meeting
    begins, its tickets' status and assignee are kept (<reports>/ela/meetings.json) so an assignment can be told
    after. `meetings`: meetings.yaml's list; `next_day(meeting, day)`: the meeting's next date after `day`, or None;
    `jira`: the base URL the outcome's ticket keys are linked to.
    → [{note, day, outcome: [(text, words)], rolled: [text]}]."""
    out, d = [], os.path.join(vault, MEETINGS)
    snap_path = meeting_snapshot_path(reports)
    try:
        snaps = json.load(open(snap_path, encoding="utf-8"))
    except (OSError, ValueError):
        snaps = {}
    snaps_changed = False
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        p = os.path.join(d, f)
        if not f.endswith(".md"):
            continue
        text = open(p, encoding="utf-8").read()
        fl, _ = split_front(text)
        if not any(re.match(r"^type:\s*['\"]?meeting['\"]?\s*$", l) for l in fl) or not legacy_form(text):
            continue                                       # a hand-written note is read, never rewritten; a built one is the records' view
        n = meeting_parse(text)
        key, title = f[:-3], n["title"] or f[:-3]
        day = meeting_day(title)
        m = next((x for x in meetings or [] if isinstance(x, dict) and x.get("key") == key), None)
        if not day:
            continue
        start, end = meeting_window(m, day)
        sk = f"{key}@{day.isoformat()}"
        if now < start:                                    # before it: keep what each ticket is now
            cur = {}
            for it in n["items"]:
                k = meeting_fields(it["text"])["key"]
                fx = facts_issue(facts, k) if k else None
                if fx:
                    fs = fx.get("fields") or {}
                    cur[k] = {"status": (fs.get("status") or {}).get("name"), "assignee": (fs.get("assignee") or {}).get("displayName")}
            if cur and snaps.get(sk) != cur:
                snaps[sk] = cur; snaps_changed = True
            continue
        if now < end or any(x[0] == day.isoformat() for x in n["ruled"]) and not n["items"]:
            continue
        if (snaps.get("closed") or {}).get(sk):
            continue                                       # closed once; what he adds after is the next meeting's
        meeting_rule(n, day, day, raised_for=day)          # his ticks and words first, as the meeting's own
        before = snaps.get(sk) or {}
        stay, lines, res = [], [], {"note": f"{MEETINGS}/{f}", "day": day.isoformat(), "outcome": [], "rolled": []}
        for it in n["items"]:
            fld = meeting_fields(it["text"])
            words, read = (ticket_outcome(facts, fld["key"], start, before.get(fld["key"])) if fld["key"] else (None, False))
            thread = thread_outcome(facts, it["text"] + "\n" + "\n".join(it["under"]), start)
            words = "; ".join(x for x in (words, thread) if x) or None
            if words and jira:                             # the note is read on screen: every key a link
                words = KEY_RX.sub(lambda k: f"[{k.group(1)}]({jira.rstrip('/')}/browse/{k.group(1)})", words)
            bare = re.sub(r"[ \t]*·[ \t]*(?:since[ \t]+\d{2}-\d{2}|ela proposes)\b", "", it["text"])
            if words:
                detail = [l for l in it["under"] if not GUIDE.match(l) and not l.lstrip().startswith(">")]
                lines += [f"- {bare} · {words}"] + detail
                res["outcome"].append((bare, words))
                continue
            gone = "no ticket to read" if not fld["key"] else ("not read" if not read else "no change")
            if not fld["since"]:                           # it keeps the day it was raised for, shown from the next meeting on
                it["text"] = it["text"].rstrip() + f" · since {day:%m-%d}"
            lines.append(f"- {bare} · {gone}: carried to the next meeting")   # a team question stays until answered (ADR 0016)
            res["rolled"].append(bare)
            stay.append(it)
        n["items"] = stay
        if lines:
            ruled = next((x for x in n["ruled"] if x[0] == day.isoformat()), None)
            if ruled is None:
                ruled = (day.isoformat(), []); n["ruled"].append(ruled)
            while ruled[1] and not ruled[1][-1].strip():
                ruled[1].pop()
            ruled[1].extend(lines)
        nxt = next_day(m, day) if next_day and m else None
        new_title = f"{title.rsplit(' · ', 1)[0]} · {nxt:%a %Y-%m-%d}" if nxt else title
        snaps.setdefault("closed", {})[sk] = now.isoformat(timespec="seconds"); snaps_changed = True
        out.append(res)
        if not dry_run:
            atomic_write(p, meeting_render(n, new_title, None, now.date()))
    if not dry_run and snaps_changed:
        os.makedirs(os.path.dirname(snap_path), exist_ok=True)
        atomic_write(snap_path, json.dumps(snaps, indent=1, ensure_ascii=False))
    return out


# ── open team questions: one record each, open until the world answers (ADR 0016; questions.py) ─────────
def questions_mod():
    sys.path.insert(0, HERE)
    import questions as Q
    return Q


def owner_name(facts):
    """The owner's Jira display name, from the fact store's own query (assignee = currentUser())."""
    try:
        d = json.load(open(os.path.join(facts, "jira", "owner.json"), encoding="utf-8"))
        return ((((d.get("issues") or [{}])[0].get("fields") or {}).get("assignee")) or {}).get("displayName") or ""
    except (OSError, ValueError, AttributeError, IndexError):
        return ""


def next_meeting(meetings, today, key=None):
    """(key, name, date) of the soonest standing meeting after today by its weekdays (on or off in the book), or of
    `key`'s; None when none has weekdays."""
    try:
        sys.path.insert(0, os.path.join(HERE, "..", "brief"))
        import brief as B
        names, working = B.WEEKDAY_NAMES, lambda d: B.is_working_day(d)
    except Exception:
        names, working = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"), lambda d: d.weekday() < 5
    best = None
    for m in meetings or []:
        if not isinstance(m, dict) or (key and m.get("key") != key):
            continue
        days_ = [str(x).strip() for x in (m.get("weekdays") or [])] if isinstance(m.get("weekdays"), list) else \
            re.findall(r"\w+", str(m.get("weekdays") or ""))
        for i in range(1, 22):
            d = today + datetime.timedelta(days=i)
            if names[d.weekday()] in days_ and working(d):
                if not best or d < best[2]:
                    best = (m.get("key"), m.get("name") or m.get("key"), d)
                break
    return best


def questions_pass(vault, reports, facts, now, meetings=(), jira="", seeds=(), dry_run=False, words=()):
    """The open team questions brought up to date: his ticks and `ela:` lines on the standing page and his `drop`
    on today.md first, then each open one read against its ticket and thread (an outcome closes it), then every
    meeting note, project page and seed (a meeting note outside the vault, e.g. from the backup) read for boxes and
    merged into the records; then the words given for a question's line (words: [(id, subject, sentence)]).
    → (state, {consumed: [his lines on the page], closed: [(id, outcome)], new: [id], refused: [(id, why)],
    unworded: [id]})."""
    Q = questions_mod()
    state = Q.load(reports)
    followed = Q.follow(state, renames(vault, reports))   # a renamed note keeps its questions, never seeds them again
    today = now.date()
    owner = owner_name(facts)
    cache = {}
    def issue(k):
        if k not in cache:
            cache[k] = facts_issue(facts, k)
        return cache[k]
    closed = []
    try:
        disk = open(os.path.join(vault, Q.QUESTIONS_PAGE), encoding="utf-8").read()
    except OSError:
        disk = ""
    got, consumed = Q.by_word(state, disk, today)
    closed += got
    try:                                                   # `drop` ticked on today.md's ask for a question, or its letter
        page = open(os.path.join(vault, TODAY), encoding="utf-8").read()
    except OSError:
        page = ""
    said = [m.group(1) for m in re.finditer(r"^[ \t]*[-*][ \t]+\[[xX]\][ \t]+drop\b.*?" + Q.QREF.pattern, page, re.M)]
    said += [x["id"].split(":")[1] for x in today_letters(page, load_asks(reports))
             if x["id"].startswith("question:") and x["does"] == "drop"]
    for qid in said:
        r = state["questions"].get(qid)
        if r and r["status"] == "open":
            r.update(status="dropped", outcome="dropped by your word on today.md", closed=today.isoformat(), by="owner")
            closed.append((r["id"], r["outcome"]))
    closed += Q.settle(state, now, issue, owner, lambda raw, at: thread_outcome(facts, raw, at))
    keys = [m.get("key") for m in meetings or [] if isinstance(m, dict) and m.get("key")]
    def start(aud, d):
        m = next((x for x in meetings or [] if isinstance(x, dict) and x.get("key") == aud), None)
        return meeting_window(m, d)[0]
    cands, d = [], os.path.join(vault, MEETINGS)
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        rel = f"{MEETINGS}/{f}"
        if not f.endswith(".md") or rel == Q.QUESTIONS_PAGE:
            continue
        try:
            text = open(os.path.join(d, f), encoding="utf-8").read()
        except OSError:
            continue
        if not any(re.match(r"^type:\s*['\"]?meeting['\"]?\s*$", l) for l in split_front(text)[0]):
            continue
        cands += Q.meeting_candidates(rel, text, keys, os.path.getmtime(os.path.join(d, f)))
    for path in seeds or ():
        text = open(path, encoding="utf-8").read()
        cands += Q.meeting_candidates(f"{MEETINGS}/{os.path.basename(path)}", text, keys, os.path.getmtime(path))
    projects, project_srcs = {}, set()
    for key, text in project_pages(vault).items():
        rel = project_path(vault, key)
        fl, body = split_front(text)
        for k in KEY_RX.findall(" ".join(fl) + " " + (h1(body) or "")):
            if is_jira_key(k):
                projects.setdefault(k, rel)
        head, _ = project_head(body)
        pc = Q.project_candidates(rel, head, section_at)
        project_srcs |= {f"{rel}#{Q.gist(c['raw'])}" for c in pc}
        cands += pc
    try:
        snaps = json.load(open(meeting_snapshot_path(reports), encoding="utf-8"))
    except (OSError, ValueError):
        snaps = {}
    before = set(state["questions"])
    titles = {project_path(vault, key): h1(split_front(text)[1]) or key for key, text in project_pages(vault).items()}
    Q.harvest(state, cands, now, issue, projects, snaps, start, keys, titles)
    closed += Q.gone_from_pages(state, project_srcs, today)
    Q.wait_since(state, today, question_evidence(vault, reports, issue, owner))
    page_keys = {}
    for key, text in project_pages(vault).items():
        rel = project_path(vault, key)
        k = next((x for x in Q.keys_in(h1(split_front(text)[1]) or "")), None) or next((x for x, p in projects.items() if p == rel), None)
        if k:
            page_keys[rel] = k
    Q.hold(state, issue, page_keys, owner)
    build_meeting_notes(vault, state, now, meetings, issue, owner, jira, dry_run, stand=stand_lines(build_records(reports), today))
    for n in Q.nudges(state, today):                       # listed at three meetings: the message he can send, drafted
        r = state["questions"][n["id"]]
        dr = Q.draft(r, owner.split()[0] if owner else "")
        if dr:
            path = os.path.join(reports, "ela", "drafts", f"question-{r['id']}.txt")
            cmd = dr.pop("command")
            dr["command"] = (f"ela {cmd[0]} {cmd[1]} {cmd[2]} " + ("--from-file " if cmd[0] == "jira" else "--file ") + path) if cmd else None   # a direct message: he sends it
            dr["file"] = path
            if not dry_run and r.get("draft", {}).get("text") != dr["text"]:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                atomic_write(path, dr["text"] + "\n")
            r["draft"] = dr
    refused = [(w[0], why) for w in words or () for why in [Q.set_words(state, *w)] if why]
    if not dry_run:
        Q.save(reports, state, atomic_write)
    return state, {"consumed": consumed, "closed": closed, "new": sorted(set(state["questions"]) - before), "refused": refused,
                   "followed": followed,
                   "unworded": [r["id"] for r in Q.open_records(state) if Q.unworded(r)]}


# an item under Needs you: its heading and at most three lines after it, never past the next heading (an item of two
# lines once swallowed the next item's heading, whose `Nth morning` was then never read)
MORNING_ITEM = re.compile(r"^(?:>[ \t]*)?###[ \t]+(?:\d+\.[ \t]*)?(.+)\n((?:(?!(?:>[ \t]*)?#{1,6}[ \t])(?:.*\n|.+$)){0,3})", re.M)
NTH_MORNING = re.compile(r"\b(\d+)(?:st|nd|rd|th) morning\b")


def morning_items(text):
    """[(heading, n)]: each item on a morning page that says its own `Nth morning`, in page order."""
    out = []
    for m in MORNING_ITEM.finditer(text or ""):
        n = NTH_MORNING.search(m.group(2))
        if n:
            out.append((m.group(1), int(n.group(1))))
    return out


def question_evidence(vault, reports, issue, owner=""):
    """key → [(date, why)]: the earlier evidence that a question about one ticket was already waiting. His asks on it
    (the asks store, which reference/dropped.md is written from: its first day), the morning pages carrying it under
    Needs you (the latest page's own `Nth morning`, counted back over the pages), the archived meeting lists that listed it
    (archive/, type meeting: its `since MM-DD`, else the note's date), and the ticket's last movement by someone
    other than the owner."""
    Q = questions_mod()
    by = {}
    def put(k, d, why):
        by.setdefault(k, []).append((d, why))
    for k, v in load_asks(reports).items():
        if k.startswith("keys:") and isinstance(v, dict) and v.get("first"):
            for x in k[5:].split(","):
                put(x, v["first"], f"your ask since {v['first']}")
    pages = []
    root = os.path.join(vault, DAYS)
    for y in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        for f in sorted(os.listdir(os.path.join(root, y))) if os.path.isdir(os.path.join(root, y)) else []:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}-brief\.md", f):
                pages.append((f[:10], os.path.join(root, y, f)))
    for i, (d, p) in enumerate(pages):
        try:
            text = open(p, encoding="utf-8").read()
        except OSError:
            continue
        for head, n in morning_items(text):
            ks = Q.keys_in(Q.visible(head))
            if ks:                                         # the page's own age; an earlier run that broke off is not this one
                start = pages[max(0, i - (n - 1))][0]
                by[ks[0]] = [e for e in by.get(ks[0], []) if not e[1].startswith("on the morning page")]
                put(ks[0], start, f"on the morning page since {start}")
    arch = os.path.join(vault, ARCHIVE)
    for f in sorted(os.listdir(arch)) if os.path.isdir(arch) else []:
        try:
            text = open(os.path.join(arch, f), encoding="utf-8").read()
        except OSError:
            continue
        if not f.endswith(".md") or not re.search(r"^type:\s*['\"]?meeting['\"]?\s*$", text, re.M):
            continue
        day = Q.note_date(f, text)
        for b in Q.boxes(text):
            vis = Q.visible(b["raw"])
            lead = Q.lead_keys(vis)
            s = re.search(r"·[ \t]*since[ \t]+(\d{2})-(\d{2})\b", vis)
            d = f"{day[:4]}-{s.group(1)}-{s.group(2)}" if s and day else day
            if len(lead) == 1 and d:
                put(lead[0], d, f"listed on {ARCHIVE}/{f} since {d}")
    def evidence(k):
        out = list(by.get(k, ()))
        s = Q.silent_since(issue(k), owner)
        if s:
            out.append((s, f"Jira silent since {s}"))
        return out
    return evidence


STAND_DAYS, STAND_LANES = 14, 5


def stand_lines(builds, today):
    """A meeting note's Where things stand: the newest build each lane took in the last STAND_DAYS days, newest first,
    at most STAND_LANES lanes, each linking its release note; team-facing words, no ask."""
    lo = (today - datetime.timedelta(days=STAND_DAYS)).isoformat()
    seen, out = set(), []
    for b in sorted(builds or [], key=lambda b: (b.get("date") or "", b.get("name") or ""), reverse=True):
        lane = b.get("lane_name") or b.get("lane")
        if not lane or lane in seen or not (lo <= (b.get("date") or "") <= today.isoformat()):
            continue
        seen.add(lane)
        note = f"{RELEASES}/{b['line']}/{b['name']}" if b.get("line") and b.get("name") else None
        out.append(f"{lane} runs {b.get('line') or '?'} build {b.get('build')}, taken {b['date'][5:]}"
                   + (f" ([[{note}|release note]])" if note else ""))
    return out[:STAND_LANES]


def build_meeting_notes(vault, state, now, meetings, issue, owner="", jira="", dry_run=False, stand=None):
    """For each standing meeting with weekdays, its next note built from the records: meetings/<yyyy-mm-dd>-<key>.md for
    today's meeting before it ends, else the next one. A note for that day he or a session wrote by hand is left alone
    (and read as input); a built note he has edited since ela wrote it is his from then on. → the paths written."""
    Q = questions_mod()
    today, out = now.date(), []
    d = os.path.join(vault, MEETINGS)
    present = sorted(os.listdir(d)) if os.path.isdir(d) else []
    titles = {}
    for key, text in project_pages(vault).items():
        titles[project_path(vault, key)] = h1(split_front(text)[1]) or key
    for m in meetings or []:
        if not isinstance(m, dict) or not m.get("key") or not m.get("weekdays"):
            continue
        k = m["key"]
        _, end = meeting_window(m, today)
        nm = next_meeting([m], today - datetime.timedelta(days=1), k)   # today's counts while it has not ended
        day = nm[2] if nm and (nm[2] > today or now < end) else (next_meeting([m], today, k) or (None, None, None))[2]
        if not day:
            continue
        rel = f"{MEETINGS}/{day.isoformat()}-{k}.md"
        hand = False
        for f in present:
            if f.endswith(".md") and f"{MEETINGS}/{f}" != rel and Q.same_audience_strict(Q.audience(f, [k]), k):
                try:
                    t = open(os.path.join(d, f), encoding="utf-8").read()
                except OSError:
                    continue
                if Q.note_date(f, t) == day.isoformat() and not legacy_form(t):
                    hand = True
        if hand:
            continue
        p = os.path.join(vault, rel)
        if os.path.exists(p) and digest(open(p, encoding="utf-8").read()) != state["built"].get(rel):
            continue                                       # he edited it: his now, read as input
        name = (m.get("name") or k).split(" · ")[0]
        title = f"{name} · {day:%a %Y-%m-%d}"
        body = Q.meeting_note(state, k, title, day, now, issue, owner.split()[0] if owner else "", jira, titles, stand)
        text = front([], {"title": title, "type": "meeting", "date": day.isoformat(), "by": "ela", "source": "vault"}) + body
        if os.path.exists(p) and re.sub(r"\*Built from[^*]*\*", "", open(p, encoding="utf-8").read()) == re.sub(r"\*Built from[^*]*\*", "", text):
            continue                                       # nothing but the stamp would change
        if not dry_run:
            os.makedirs(d, exist_ok=True)
            atomic_write(p, text)
            state["built"][rel] = digest(text)
        out.append(rel)
    return out


def question_asks(state, today, actions=()):
    """The asks a question earns on today.md: listed at three meetings (and each three more) with no outcome, once
    each, ahead of the drafted actions."""
    Q = questions_mod()
    out = []
    for n in Q.nudges(state, today):
        r = state["questions"][n["id"]]
        who = Q.answerer(r)[0]
        act = next((a for a in actions if a.get("rule") == "question" and a.get("question") == r["id"] and a.get("day") == today.isoformat()
                    and not (a.get("applied") or a.get("vetoed") or a.get("by_owner"))), None)
        if act:                                            # the runner drafted it as an action: send is `apply N`
            options = [opt("A", f"send {who} the drafted message", f"apply {act['n']}", True), opt("B", "drop the question", "drop")]
        else:
            options = [opt("A", f"keep it for {who} at the next meeting", None, True), opt("B", "drop the question", "drop")]
        out.append({"id": f"question:{r['id']}:{n['bucket']}", "box": f"apply {act['n']}" if act else "drop", "whole": True,
                    "ns": [int(act["n"])] if act else [], "options": options,
                    "text": f"{Q.line(r)} — carried through {n['count']} meetings.",
                    "link": f"{Q.QUESTIONS_PAGE[:-3]}#^{r['id']}", "sig": evidence_sig(r["id"]), "first": today.isoformat()})
    return out


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


def plan(s, env, today, now, removed=frozenset(), removed_src=frozenset(), since=None, dry_run=False, questions=None):
    reports = s.get("reports")
    enotes, titles = elak_notes(s.get("elak"))
    notes = report_notes(reports, today, s.get("runtime"), s.get("helm_local_url")) + enotes      # the constraints page is retired (ADR 0015); `ela promote` reads the pins
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
    tickets = jira_projects(s.get("runtime"))
    def ticket_of(text):                                   # a page belongs to the ticket its keys lead with
        lead = page_ticket_key(text)
        return next((t for t in tickets if t["key"] == lead), None)
    def watched(k, text):                                  # a Jira project's notes may name it or any of its sub-tasks
        t = ticket_of(text)
        return set(project_facts(k, text, today)["keys"]) | {x[0] for x in (t or {}).get("subtasks") or []}
    inferred = infer_projects(s["vault"], {k: watched(k, t) for k, t in pages.items()}, notes, native, dry_run)
    for n in notes:                                        # each work note in its thing's home (ADR 0015), live
        n.path = place(n, pages)
        if family_of(n.props.get("type")) == "work":
            n.props["status"] = LIVE
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
        notes.append(project_note(key, text, s["vault"], notes + native, today, jira_base, ticket_of(text), questions))
    # a ticket a page leads with, or names among its keys (MH-3990 under the MH-3735 project), has its page: never a second
    paged = {k for text in pages.values() for k in KEY_RX.findall(props_of(split_front(text)[0]).get("keys") or "")}
    for t in tickets:                                      # an open kind:project ticket with no page gets one, once
        if t["key"] not in paged:
            key = jira_project_key(t)
            fresh = jira_project_page(t, today)
            notes.append(project_note(key, fresh, s["vault"], notes + native, today, jira_base, t))
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
        if family_of(n.props.get("type")) == "work":       # a generated work note is live: done is his word, kept on disk
            _, result, _ = settled_status(folder_of(n.path), note_status(n), n.props.get("type"))
            n.props.update(status=LIVE, result=n.props.get("result") or result, **{NEXT: "", MOVE_SET: move_set(n.props.get("type"))})
            n.front_lines = [l for l in n.front_lines if not l.startswith("status:")]   # the source's own word is settled
        n.held = reading_gate(n)
        if getattr(n, "front_text", None):                 # a project page: the head as the desk wrote it, the tail linked
            body = n.head + linker(n.tail)
            planned[n.path] = redact(n.front_text + (with_warning(body, n.held) if n.held else body))
            continue
        body = linker(unwrap(callouts(meta_line(Note(n.path, n.title, tidy_title(n.body), n.props, n.front_lines)))))
        if family_of(n.props.get("type")) == "work":
            body = with_moves(body, n.path, n.props.get("type"))
        planned[n.path] = redact(front(n.front_lines, dict(n.props, title=n.title)) + (with_warning(body, n.held) if n.held else body))
    asks_state = load_asks(reports)
    settle_letters(s["vault"], reports, asks_state, today, dry_run)   # his letters the sync acts on itself, before the asks are counted
    cands = ask_candidates(today, week_actions(reports, today), notes + native)
    qcands = question_asks(questions, today, week_actions(reports, today)) if questions else []
    dcands, dry_facts = dry_asks(reports, today, asks_state, dry_run)
    shown, more, _, asks_state = settle_asks(asks_state, qcands + dcands + cands, today)
    for v in asks_state.values():                          # the slots are today's page's: yesterday's numbers mean nothing
        for k in ("slot", "options"):
            v.pop(k, None)
    for k, c in enumerate(shown, 1):
        asks_state[c["id"]].update(slot=k, options={o["letter"]: o["does"] for o in ask_options(c)})
    if not dry_run:
        os.makedirs(os.path.join(reports, "ela"), exist_ok=True)
        atomic_write(os.path.join(reports, "ela", "asks.json"), json.dumps(asks_state, indent=1, ensure_ascii=False))
    try:
        sys.path.insert(0, os.path.join(HERE, "..", "brief"))
        import brief as B
        meetings = B.day_plan(today)["meetings"]
    except Exception:                                      # the day file is elak's; a bad one costs the meeting lines only
        meetings = []
    dropped = sum(1 for v in asks_state.values() if v.get("dropped"))
    qline = None
    if questions:
        Q = questions_mod()
        aud = max(((r.get("audience"), 1) for r in Q.open_records(questions) if r.get("audience")), default=(None, 0))[0]
        counts = {}
        for r in Q.open_records(questions):
            if r.get("audience"):
                counts[r["audience"]] = counts.get(r["audience"], 0) + 1
        aud = max(counts, key=counts.get) if counts else None
        nm = next_meeting(meeting_book()[0], today, aud) if aud else None
        label = (("sync" if "sync" in (nm[0] or "") else nm[1]), nm[2]) if nm else None
        qline = Q.today_line(questions, today, label, jira_base)
    builds = build_records(reports)
    day_brief = f"{DAYS}/{today:%Y}/{today.isoformat()}-brief.md"
    if day_brief in planned:                               # the morning page: boxes only on the asks today.md shows
        planned[day_brief] = also_noticed(planned[day_brief], {n for c in cands for n in c.get("ns") or []}
                                          - {n for c in shown for n in c.get("ns") or []})
    planned[TODAY] = redact(front([], {"type": "today", "date": today.isoformat()}) + linker(today_page(today, notes + native, {
        "actions": week_actions(reports, today), "hold": tier2_hold(reports, today.isoformat()), "lists": list_links(reports),
        "meetings": meetings, "builds": builds, "tickets": release_mod().facts_tickets(s.get("runtime"), [k for b in builds for v in b["services"] for k in v.get("keys") or []]),
        "owner": owner_name(os.path.join(s.get("runtime") or "", "facts")), "dry_facts": dry_facts}, shown, more, dropped, questions_line=qline)))
    planned.update(dry_pages(s["vault"], reports, today))
    if questions:
        Q = questions_mod()
        drafts = {r["id"]: r["draft"] for r in Q.open_records(questions) if r.get("draft") and (len(r["meetings"]) >= Q.NUDGE_EVERY or r.get("message"))}
        planned[Q.QUESTIONS_PAGE] = front([], {"type": "questions", "date": today.isoformat()}) + Q.page(questions, today, jira_base, drafts)
    planned[DROPPED] = redact(front([], {"type": "dropped", "date": today.isoformat()}) + linker(dropped_page(asks_state)))
    if today <= HOME_POINTER_UNTIL:                        # Home points to today.md for two weeks, then is not written
        planned["home.md"] = front([], {"type": "home", "date": today.isoformat()}) + home_pointer()
    else:
        planned.pop("home.md", None)
    planned[f"{ELA}/about-this-vault.md"] = README.replace(SPEC_MARK, "\n".join(("> " + l).rstrip() for l in spec_text().splitlines()))
    for name, text in VIEWS.items():
        planned[f"{ELA}/{name}.base"] = text
    return planned, files, notes, warnings, {n.path for n in native}, inferred


def place(n, pages=None):
    """A generated work note's path in layout 5 (ADR 0015): beside its project's page in projects/<key>/ when it names
    one (`project:`, set or inferred), else its thing's home (home_for: a case, a release line, ela's history, or
    reference/), named `<date>-<kind>-<what>.md`. A page, a day page and a note already in a thing's home stay."""
    if family_of(n.props.get("type")) != "work" or subject_home(os.path.dirname(n.path)) or top(n.path) == ELA:
        return n.path
    name = os.path.basename(n.path)
    key = n.props.get("project")
    if key and (pages is None or key in pages):
        return f"{PROJECTS}/{key}/{beside_name(name, dict(n.props, title=n.title), key)}"
    return f"{home_for(n.path, dict(n.props, title=n.title))}/{dated_name(name, n.props.get('type'))}"


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
                    if row.get("renamed_from"):          # the old path is gone by the owner's close, not a deletion
                        paths.add(row["renamed_from"])
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
    for rel in kept_notes(vault):                         # archive/ and every done note
        try:
            text = open(os.path.join(vault, rel), encoding="utf-8").read()
        except OSError:
            continue
        refs |= {m.lower() for m in re.findall(r"\[\[(" + re.escape(ATTACH) + r"/[^\]|#]+)", text)}
    # a record's page sits beside its images: keep the whole record folder of anything referenced
    return {r.rsplit("/img/", 1)[0] if "/img/" in r else os.path.dirname(r) for r in refs}


def record_removed(path, rels, sources, now, archived=None, by="owner", renamed=None):
    """Log each note the owner finished with: dragged into archive/ (keep it, nothing to do) or deleted (drop it). Each way he has read it, so it stays out of the generated folders. None is criticism or
    a verdict on a decision; feedback comes as a message (Slack `feedback`, a session)."""
    archived = archived or {}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for r in rels:
            title = sentence(re.sub(r"^\d{4}-\d{2}-\d{2}-", "", os.path.basename(r)[:-3]).replace("-", " "))
            to = archived.get(os.path.basename(r).lower())
            to = kept_home(to) or to                       # a release line's folder is releases
            row = {"at": now.isoformat(timespec="seconds"), "path": r, "title": title,
                   "fate": "archived" if to in OWNER_FOLDERS + (DONE,) + SUBJECT_HOMES else {IN_PROGRESS: "in-progress", PARKED: "parked",
                                                                                   TO_READ: "to-read"}.get(to, "deleted"), "by": by}
            if to in SUBJECT_HOMES:                        # kept by subject: the home it went to
                row["home"] = to
            elif to == DONE:                               # done where it is
                row["home"] = folder_of(r)
            if sources.get(r):
                row["src"] = sources[r]
            if (renamed or {}).get(r):                     # closed under a new name: logged there, the old one kept
                row["path"], row["renamed_from"] = renamed[r], r
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
# ela's own `ela:` lines, never his word: a blank ela leaves for his words ends in a dash or an ellipsis (`ela: keep /
# revert —`) and is read only once he writes after it; a front-matter `ela` value in the dated progress form
# (`ela: "2026-11-09: …"`) is ela's record. On 2026-11-09 five runner jobs fired on such lines (vault review 11-10).
STUB_END = re.compile(r"(?:—|–|-{2,}|…|\.{3}|_{3,})$")
DATED_SAYS = re.compile(r"^\d{4}-\d{2}-\d{2}\s*[:：]\s")


def ela_own(says, in_front=False):
    """Whether the words of one `ela:` line are ela's own (a stub awaiting his words, or a dated record in the front
    matter) rather than his instruction."""
    says = (says or "").strip().strip('"').strip("'").strip()
    return bool(STUB_END.search(says)) or (in_front and bool(DATED_SAYS.match(says)))


def his_lines(text, start=0, end=None):
    """The `ela:` lines in text[start:end] that are his word: ela's own stubs and dated front-matter records left out."""
    front = body_start(text)
    return [m for m in GUIDE.finditer(text, start, len(text) if end is None else end) if not ela_own(m.group(1), m.start() < front)]


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


def release_note_merge(disk, fresh, services):
    """A held build note (source vault) with ela's part rewritten: `fresh` (title, source, one section per service,
    Notes, Jira gaps, rendered from the record) in place of what stands above the first section ela does not write;
    every other section (Afterwards, one he added) kept in its order, the front matter kept. None when ela's part on
    disk carries his words (a box or an `ela:` line): the note is then left as it is."""
    fl, body = split_front(disk)
    ours = {"notes", "jira gaps"} | {str(s).lower() for s in services}
    parts = re.split(r"(?m)^(?=## )", body)
    mine, kept = [parts[0]], []
    for sec in parts[1:]:
        head = sec.split("\n", 1)[0][3:].strip().lower()
        (mine if head in ours and not kept else kept).append(sec)
    if re.search(r"(?m)^\s*[-*] \[[ xX]\]|^\s*ela:", "".join(mine)):
        return None
    new = fresh.rstrip("\n") + "\n" + ("\n" + "".join(kept).rstrip("\n") + "\n" if kept else "")
    return ("---\n" + "\n".join(fl) + "\n---\n" if fl else "") + new


def release_body(rec, props, title, reports, runtime, linker=None, helm=None):
    """A build note's body as the vault shows it: the record rendered with its tickets from the fact store and the
    reading reconcile kept, the meta line under the title, keys linked."""
    R = release_mod()
    keys = [k for v in rec["services"] for k in v.get("keys") or []]
    body = R.build_note(rec, R.reconcile_mod().saved_reading(reports, rec), R.facts_tickets(runtime, keys), R.helm_compare(rec, runtime, helm))
    body = unwrap(callouts(meta_line(Note("", title, tidy_title(body), props, []))))
    return linker(body) if linker else body


def release_notes_native(vault, reports, runtime, linker=None, dry_run=False, helm=None):
    """Each build's release note, once the vault holds it (source vault), keeps ela's part current from its record:
    the services with their tickets in words and the Jira gaps; Afterwards and his own sections stay. → paths changed."""
    R = release_mod()
    out = []
    for rec in build_records(reports):
        rel = f"{RELEASES}/{rec['line']}/{rec['name']}.md"
        p = os.path.join(vault, rel)
        try:
            text = open(p, encoding="utf-8").read()
        except OSError:
            continue
        fl, _ = split_front(text)
        if not any(re.match(r"^source:\s*['\"]?vault['\"]?\s*$", l) for l in fl):
            continue
        props = props_of(fl)
        if is_done(props):                                 # marked done: the copy on disk is the record, never written again
            continue
        fresh = release_body(rec, {"type": props.get("type") or "report", "date": rec["date"], "status": props.get("status") or "decided"},
                             R.build_title(rec), reports, runtime, linker, helm)
        new = release_note_merge(text, fresh, [v["service"] for v in rec["services"]])
        if new is not None and new != text:
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
    "agree": "ela builds it: the note stays here, live, and each step is written under Progress",
    "park": "parked: it waits on others; comes back when `wake` happens",
    "not-now": "done: not now", "reject": "done, as rejected",
    "make-plan": "ela writes a plan from the findings as a new note beside this one; this one is done",
    "draft-comment": "ela drafts the short Jira comment as `apply N`; nothing is posted",
    "confirm": "done, as confirmed", "accept": "done, as accepted",
    "not-done": "ela carries on; write what is missing as `ela:` lines first",
    "nudge": "ela drafts a short nudge to whoever the ticket waits on, as `apply N`; nothing is posted",
    "go-deep": "ela reads the ticket to its root cause in the code (`ela probe`) and writes what it finds under this page",
    "seen": "done: you have read where it stands",
    "resume": "live again, for your next decision",
    "reopen": "live again as built, for your accept or not-done: ela closed it, and that was wrong",
    "done": "done, nothing more; it stays where it is",
    "drop": "done and kept where it is, with next drop; nothing is deleted",
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
    and its `status` chooser its type's states (STATUS_BY_KIND): live or done, a case's own."""
    d = os.path.join(vault, MOVE_SETS_DIR)
    os.makedirs(d, exist_ok=True)
    sets = {k: move_props(k, in_to_read=k not in OUT_OF_TO_READ) for k in MOVE_PROPS}
    sets["read"] = list(MARKS)
    sets["closed"] = []                                    # an archived note: its status only, its next already written
    sets["case"] = []                                      # a case: its status only (open, answered, closed)


    def field(name, values):
        vals = "".join(f'\n        "{i}": {m}' for i, m in enumerate(values, 1))
        return (f"  - name: {name}\n    id: {name}\n    type: Select\n    path: \"\"\n    options:\n"
                f"      sourceType: ValuesList\n      valuesList:{vals}\n")
    for name, moves in sets.items():
        text = ("---\nfields:\n" + (field("next", moves) if moves else "")
                + field("status", STATUS_BY_KIND["case" if name == "case" else "work"]) + "---\n")
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
    kind = move_kind(rel, planned)
    keep = {}
    chosen = (disk.get(NEXT) or "").lower()
    if chosen and chosen != (planned.get(NEXT) or "") and chosen in move_props(kind, in_to_read=kind not in OUT_OF_TO_READ):
        keep[NEXT] = chosen
    st = disk.get("status")
    if st and st != planned.get("status") and st in STATUS_BY_KIND.get("case" if planned.get("type") == "case" else "work", ()):
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


def prop_value(v):
    """One front-matter value as written: a double-quoted value decoded the way front() encoded it, so a read and a
    write give back the same text (a stripped-quotes reading kept the escapes, and each pass doubled them)."""
    v = v.strip()
    if len(v) > 1 and v[0] == '"' and v[-1] == '"':
        try:
            d = json.loads(v)
            if isinstance(d, str):
                return d
        except ValueError:
            pass
    return v.strip("'\"")


def props_of(lines):
    """A note's front-matter lines → {key: value}, quotes taken off: the one reading every caller shares."""
    return {m.group(1): prop_value(m.group(2)) for m in (re.match(r"^([\w-]+):\s*(.*)$", l) for l in lines) if m}


def set_front(text, **props):
    """Set or remove (None) front-matter keys in a note's text, keeping the rest as written."""
    fl, body = split_front(text)
    fl = [l for l in fl if not any(re.match(rf"^{k}:", l) for k in props)]
    fl += [f"{k}: {json.dumps(v, ensure_ascii=False)}" if isinstance(v, list) else f'{k}: "{v}"' for k, v in props.items() if v is not None]
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
    """(vault path, file path) of a note named by its path, or exit 2. An old path (layout 4) is read as the note's new
    one while the migration's map lasts in the manifest (ADR 0015: 14 days)."""
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(vault)) if os.path.isabs(path) else path
    rel = rel.replace(os.sep, "/")
    if not os.path.isfile(os.path.join(vault, rel)):
        try:
            m = json.load(open(os.path.join(vault, MANIFEST)))
            rel = moved_paths({"map": m.get("moved"), "until": m.get("moved_until")}, datetime.date.today()).get(rel, rel)
        except (OSError, ValueError):
            pass
    p = os.path.join(vault, rel)
    if rel.startswith("..") or not rel.endswith(".md") or not os.path.isfile(p):
        print(f"not a note in the vault: {path}", file=sys.stderr); sys.exit(2)
    return rel, p


def release_review_name(name):
    """A release review's file name under the rule (RELEASE_REVIEW_NAME): a leading mh<major>-<minor>- or
    release-<major>-<minor>- and a <major>-<minor> after the kind word dropped, the line being the folder's; a name
    with no kind word becomes review-<what>. Any other name is returned as it is."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+)\.md$", name)
    if not m:
        return name
    kinds = "|".join(RELEASE_KINDS)
    rest = re.sub(r"^(?:mh-?|release-)\d+-\d+-", "", m.group(2))
    rest = re.sub(rf"^({kinds})-\d+-\d+-", r"\1-", rest)
    if not re.match(rf"^(?:{kinds})-", rest):
        rest = "review-" + rest
    return f"{m.group(1)}-{rest}.md"


def close_name(folder, kind, rel):
    """The name a note closes under in `folder`: its own, except a review of a release closing into mh/releases/,
    renamed to the rule when its name breaks it."""
    name = os.path.basename(rel)
    if kind != "review" or kept_home(folder) != RELEASES or re.match(rf"^{RELEASE_REVIEW_NAME}\.md$", name):
        return name
    return release_review_name(name)


def relink(vault, old, new, dry_run=False):
    """Rewrite each [[link]] (and each markdown link to <name>.md) naming the note `old` to `new` across the vault;
    returns the files changed (that would change, with dry_run). A link resolves by name, so its folder path, heading
    and alias are kept."""
    wiki = re.compile(r"(\[\[(?:[^\[\]|#]*/)?)" + re.escape(old) + r"(?=(?:\.md)?[\]|#])", re.I)
    md = re.compile(r"(\]\((?:[^()\s]*/)?)" + re.escape(old) + r"(?=\.md[)#])", re.I)
    changed = []
    for top_, dirs, fs in os.walk(vault):
        dirs[:] = [x for x in dirs if not x.startswith(".")]
        for f in fs:
            if not f.endswith((".md", ".base", ".canvas")):
                continue
            p = os.path.join(top_, f)
            try:
                text = open(p, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            out = md.sub(lambda m: m.group(1) + new, wiki.sub(lambda m: m.group(1) + new, text))
            if out != text:
                if not dry_run:
                    atomic_write(p, out)
                changed.append(os.path.relpath(p, vault).replace(os.sep, "/"))
    return changed


def with_alias(text, alias):
    """The note with `alias` added to its aliases (after the title), so the quick switcher still finds an old name."""
    fl, body = split_front(text)
    al = list_prop(fl, "aliases")
    if not fl or alias in al:
        return text
    return "---\n" + "\n".join(front_line(fl, "aliases", al + [alias])) + "\n---\n" + body.lstrip("\n")


MOVE_TO = {"in-progress": "building", "parked": "parked", "archive": DONE, "to-read": "ask", "readings": DONE,
           "live": "ask", "done": DONE, "building": "building"}   # layout 4's folder words, kept as input (ADR 0015)


def move_note(vault, reports, rel, to, status=None, waits_on=None, wake=None, next_=None):
    """A move on the owner's word, made where the note is (ADR 0015): the note's state changes, never its folder.
    building (he agreed: ela builds it, its acceptance moves follow), parked (it waits on others: who, since when, what
    brings it back), done (closed and kept, the move that ended it in next), ask (live again, waiting for his word). A
    note becomes a page whose source is the vault, so the sync never writes it again. Layout 4's folder words
    (in-progress, parked, archive, to-read, readings) are read as these. Returns the note's path."""
    p = os.path.join(vault, rel)
    if to in ("drop", "delete"):                           # closed as dropped and kept, never removed
        return finish(vault, reports, rel, "drop")
    life = MOVE_TO[to]
    text = open(p, encoding="utf-8").read()
    kind = props_of(split_front(text)[0]).get("type")
    text = clear_warn(PROP_RE.sub("", text))
    if kind == "case":
        text = set_front(text, source="vault", status="closed" if life == DONE else (status or "open"),
                         **{MOVE_SET: "case", NEXT: next_ or ""})
    elif life == "parked":
        old = props_of(split_front(text)[0])
        text = set_front(text, source="vault", status=LIVE, claimed=None, **{
            "waits-on": waits_on or old.get("waits-on") or "", "wake": wake or old.get("wake") or "",
            "parked": old.get("parked") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), MOVE_SET: "parked", NEXT: ""})
    elif life == DONE:
        _, _, nxt = settled_status(folder_of(rel), status, kind)
        text = set_front(text, source="vault", status=DONE, claimed=None, **{"waits-on": None, "wake": None, "parked": None,
                         MOVE_SET: "reopen" if next_ == "reopen" else "closed", NEXT: "" if next_ == "reopen" else (next_ or nxt or ""),
                         "closed-by": "ela" if next_ == "reopen" else None})
    elif life == "building":
        text = set_front(text, source="vault", status=LIVE, **{"waits-on": None, "wake": None, "parked": None,
                         MOVE_SET: "built", NEXT: "", "closed-by": None,
                         "built": None if (status or "") != "built" else props_of(split_front(text)[0]).get("built") or
                         datetime.datetime.now().strftime("%m-%d %H:%M")})
    else:                                                  # live again, its next decision his
        text = set_front(text, source="vault", status=LIVE, claimed=None, **{"waits-on": None, "wake": None, "parked": None,
                         MOVE_SET: move_set(kind), NEXT: "", "closed-by": None})
    fl, body = split_front(text)
    moves_kind = None if life == DONE else "parked" if life == "parked" else "built" if life == "building" else kind
    body = with_moves(body, rel, moves_kind) if moves_kind and MOVE_PROPS.get(moves_kind) else body
    atomic_write(p, "---\n" + "\n".join(fl) + "\n---\n" + body.lstrip("\n"))
    if life == DONE:
        try:
            src = (json.load(open(os.path.join(vault, MANIFEST))).get("sources") or {}).get(rel)
        except (OSError, ValueError):
            src = None
        record_removed(os.path.join(reports, "ela", "vault-removed.jsonl"), [rel], {rel: src} if src else {},
                       datetime.datetime.now(), {os.path.basename(rel).lower(): DONE}, by="owner")
    return rel


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
        text = progress_line(set_front(text, status=LIVE, claimed=None, built=stamp, progress=" ".join(a.text)[:120]),
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
    """A live work note ela wrote in place (source: vault) gets its next moves once, by kind, if it has none: the
    fields its `next` chooser needs and the section that explains them. A parked one gets only its fields."""
    for rel in (r for fo in THING_FOLDERS if fo != ARCHIVE for r in notes_under(vault, fo)):
        p = os.path.join(vault, rel)
        try:
            text = open(p, encoding="utf-8").read()
        except OSError:
            continue
        fl, body = split_front(text)
        props = props_of(fl)
        if props.get("source") != "vault" or family_of(props.get("type")) != "work" or is_done(props) or PROJECT_PAGE.match(rel):
            continue
        kind = move_kind(rel, props)
        wanted = [f'{MOVE_SET}: "{move_set(kind) if kind not in OUT_OF_TO_READ else kind}"', f'{NEXT}: ""']
        missing = [w for w in wanted if not any(l.startswith(w.split(":")[0] + ":") for l in fl)]
        has_moves = re.search(r"^" + re.escape(MOVES_HEAD), body, re.M)
        if kind == "parked":                               # its body is never rewritten: the fields only
            if fl and missing and not dry_run:
                atomic_write(p, "---\n" + "\n".join(fl + missing) + "\n---\n" + body)
            continue
        if MOVES.get(kind) and (not has_moves or missing) and not dry_run:
            body = body if has_moves else with_moves(body, rel, kind)
            atomic_write(p, "---\n" + "\n".join(fl + missing) + "\n---\n" + body.lstrip("\n"))


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
    asks_state = load_asks(reports)
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
                found = [(x, "line") for x in his_lines(text)] + [(x, "tick") for x in ticks]
                # a letter on today.md is the option's command; one the sync acts on itself is not the runner's
                letters = {x["pos"]: x for x in today_letters(text, asks_state)} if rel == TODAY else {}
                times = {}
                for m, kind in ((x, k) for x, k in found if x.group(1).strip('"\' ')):
                    # the same words written again in the note are a new instruction: the nth repeat has its own id, the
                    # first keeps the id it always had, so nothing already handled comes back
                    times[m.group(1)] = times.get(m.group(1), 0) + 1
                    gid = guidance_id(f, m.group(1), times[m.group(1)])
                    says = m.group(1).strip().strip('"').strip("'")
                    letter = letters.get(m.start())
                    if letter and sync_handles(letter["does"]):
                        continue
                    if letter:
                        says = letter["does"]
                    many = re.match(r"^apply[ \t]+(\d+(?:[ \t]*,[ \t]*\d+)+)\b(.*)$", says) if kind == "tick" or letter else None
                    # an ask on today.md that is several drafted writes on one ticket: the tick is his word on each
                    parts = ([(gid if i == 0 else f"{gid}-{n}", f"apply {n}{many.group(2)}")
                              for i, n in enumerate(re.findall(r"\d+", many.group(1)))] if many else [(gid, says)])
                    for pid, psays in parts:
                        if a.all or pid not in done:
                            lines.append(dict({"id": pid, "note": rel, "kind": kind, "says": psays, "section": section_at(text, m.start())},
                                              **({"ask": letter["id"], "letter": letter["letter"]} if letter else {})))
    r = {"guidance": lines,
         "handled_log": os.path.join(reports, "ela", "guidance-handled.jsonl")}
    if a.json:
        print(json.dumps(r, ensure_ascii=False)); return
    for g in lines:
        print(f"{g['id']}  {g['note']}: {g['says']}")
    print(f"{len(lines)} instructions")


def apply_marks(vault, reports, dry_run=False):
    """The move he chose in a note's `next` field. done and drop finish the note where it is; every other move is
    reported for the runner, which acts and empties the field. A value that is not a move for that note runs nothing,
    and the note says so. Returns [(path, move)]."""
    out = []
    found = [r for fo in THING_FOLDERS + (TO_READ, IN_PROGRESS, PARKED) for r in notes_under(vault, fo)]
    for rel in found:
        p = os.path.join(vault, rel)
        try:
            fl, _ = split_front(open(p, encoding="utf-8").read())
        except OSError:
            continue
        props = props_of(fl)
        if family_of(props.get("type")) != "work" and props.get(MOVE_SET) not in ("built", "parked", "reopen"):
            continue
        done = is_done(props) or top(rel) == ARCHIVE
        if done and props.get(MOVE_SET) != "reopen":
            continue                                        # the record: only a note ela closed offers a move back
        kind = move_kind(rel, props)
        allowed = move_props(kind, in_to_read=kind not in OUT_OF_TO_READ)
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
            move_note(vault, reports, rel, "live")
        elif move == "reopen" and not dry_run:      # ela closed it wrongly: back to building's end, his to accept
            move_note(vault, reports, rel, "building", "built")
    return out


def move_kind(rel, props):
    """The set of moves a note offers: reopen (done by ela), parked (it waits on others), built (built, his to accept),
    else its type's."""
    if is_done(props) or top(rel) == ARCHIVE:
        return "reopen"
    if props.get(MOVE_SET) in ("parked", "built") or top(rel) in (PARKED, IN_PROGRESS):
        return props.get(MOVE_SET) if props.get(MOVE_SET) in ("parked", "built") else "parked" if top(rel) == PARKED else "built"
    return props.get("type")


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
    """Close a note on the owner's word, where it is (ADR 0015): status done (a case closed) and the move that closed
    it in next. `to` "drop" (or the older "delete") closes it the same way with next drop: ela never deletes a note
    (working preferences, *No data is lost*, 2026-11-09). Logged as his. Returns the note's folder."""
    p = os.path.realpath(os.path.join(vault, rel))
    if to in ("drop", "delete"):
        move = "drop"
    try:
        src = (json.load(open(os.path.join(vault, MANIFEST))).get("sources") or {}).get(rel)
    except (OSError, ValueError):
        src = None
    text = clear_warn(PROP_RE.sub("", open(p, encoding="utf-8").read()))   # the move fields belong to a live note
    kind = props_of(split_front(text)[0]).get("type")
    text = set_front(text, source="vault", status="closed" if kind == "case" else DONE,
                     **{MOVE_SET: "case" if kind == "case" else "closed", NEXT: move or "done"})
    fl, body = split_front(text)
    body = re.split(r"^" + re.escape(MOVES_HEAD) + r"[ \t]*$", body, maxsplit=1, flags=re.M)[0].rstrip("\n") + "\n"
    atomic_write(p, "---\n" + "\n".join(fl) + "\n---\n" + body.lstrip("\n"))
    record_removed(os.path.join(reports, "ela", "vault-removed.jsonl"), [rel], {rel: src} if src else {},
                   datetime.datetime.now(), {os.path.basename(rel).lower(): DONE}, by="owner")
    return folder_of(rel)


def cmd_finish(a):
    """Finish with a note on the owner's word (an `ela:` line asking it): close it into archive/ or its subject home,
    as done or as dropped, kept where it is, and log it as his. Only a work note or a case; a living page is not his to
    finish, and the archive is already his. An old path (layout 4) is read as its new one for 14 days."""
    s = json.load(open(SITE))
    vault = s["vault"]
    rel, p = note_path(vault, a.path.replace("\\", "/").lstrip("/"))
    kind = props_of(split_front(open(p, encoding="utf-8").read())[0]).get("type")
    if top(rel) == ARCHIVE or not (family_of(kind) in ("work", "case") or deletable(rel)):
        print(f"not a note to finish (a work note or a case outside archive/): {a.path}", file=sys.stderr); sys.exit(2)
    folder = finish(vault, s.get("reports") or "", rel, a.to)
    print(f"{rel}: done in {folder}/ as {'dropped' if a.to in ('drop', 'delete') else 'done'}, kept; logged as the owner's")


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
    """Layout 5 moves nothing on closing (ADR 0015): a done note stays in its thing's home. What tidy did once is the
    migration's: `ela vault migrate` lists every note out of place."""
    print("tidy: nothing to do in layout 5, a done note stays where its thing lives; `ela vault migrate` lists any note "
          "out of place")


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
    if a.path in renames(s["vault"], s.get("reports")):
        print(f"{a.path} was renamed, not deleted: it is {renames(s['vault'], s.get('reports'))[a.path]}", file=sys.stderr); sys.exit(2)
    row = {"at": datetime.datetime.now().isoformat(timespec="seconds"), "path": a.path, "restored": True}
    if src:
        row["src"] = src
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    print(f"restored: {a.path}; the next sync writes it again")


def top(rel):
    return rel.split("/")[0]


LIVING = re.compile(r"^(?:today|home)\.md$|^reference/(?:dropped|one-thing)\.md$|^releases/(?:lanes|[^/]+/(?:train|dev-list|test-list)-[^/]+)\.md$"
                    r"|^releases/test-list-[^/]+\.md$")


def moved_paths(old_moved, today):
    """The migration's {old path: new path}, kept in the manifest while old paths are accepted (OLD_PATHS_DAYS), then
    dropped."""
    until = old_moved.get("until")
    return old_moved.get("map") or {} if until and today.isoformat() <= until else {}


def deletable(rel):
    """A generated note the owner may finish by deleting it: a dated note in a thing's home or the day pages, not a
    living page (today, the lists, a project's page), which is written again whatever happens to it."""
    return top(rel) in DELETABLE and not LIVING.match(rel) and not PROJECT_PAGE.match(rel)


def digest(text):
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def tmp_path(path):
    """The temporary file beside `path`, dot-prefixed: Obsidian does not list it in recent files or search."""
    d, name = os.path.split(path)
    return os.path.join(d, f".{name}.ela-tmp")


def atomic_write(path, text):
    """Write `text` to `path` through a dot-prefixed temporary file, only when the bytes change: the vault is
    file-synced to another machine and an unchanged note keeps its modification time. → whether it was written."""
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            if fh.read() == text:
                return False
    except (OSError, UnicodeDecodeError):
        pass
    tmp = tmp_path(path)
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)
    return True


WRITERS = ("sync", "questions", "marks", "finish", "note", "restore", "setup", "afterwards", "tidy", "lint", "migrate", "rename")   # guidance only reads; lint writes with --fix --apply


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


def cmd_questions(a):
    """`ela vault questions`: the open team questions, brought up to date the way the sync does (a dry run unless
    --apply); --seed adds meeting notes from outside the vault (the backup's copy of a note that is gone)."""
    s = json.load(open(SITE))
    env = s.get("env")
    jira_url = next((l.split("=", 1)[1].strip() for l in open(env) if l.startswith("JIRA_BASE_URL=")), "") \
        if env and os.path.isfile(env) else ""
    words = [tuple(w) for w in a.word or ()]
    if a.words:
        try:
            words += [(k, *v) for k, v in json.load(open(a.words, encoding="utf-8")).items()]
        except (OSError, ValueError, TypeError) as e:
            print(f"--words: {e}", file=sys.stderr); sys.exit(2)
    state, done = questions_pass(s["vault"], s.get("reports") or "", os.path.join(s.get("runtime") or "", "facts"),
                                 datetime.datetime.now().astimezone(), meeting_book()[0], jira_url, a.seed or (), dry_run=not a.apply,
                                 words=words)
    Q = questions_mod()
    recs = Q.open_records(state)
    if a.json:
        print(json.dumps({"open": recs, "closed": done["closed"], "new": done["new"], "refused": done["refused"],
                          "unworded": done["unworded"], "dry_run": not a.apply}, ensure_ascii=False))
        sys.exit(2 if done["refused"] else 0)
    for qi, why in done["refused"]:
        print(f"refused words for {qi}: {why}", file=sys.stderr)
    today = datetime.date.today()
    for r in recs:
        print(f"{r['id']} · {Q.answerer(r)[0]} · {Q.waited(r, today)} ({r.get('waiting', {}).get('why', '')}) · {Q.line(r)}" + (" · NEEDS WORDS" if Q.unworded(r) else ""))
    for qi, w in done["closed"]:
        print(f"closed {qi}: {w}")
    print(f"{len(recs)} open, {len(done['new'])} new, {len(done['unworded'])} need words" +
          ("" if a.apply else " · DRY RUN (--apply writes the records)") + f" · {today}")
    if done["refused"]:
        sys.exit(2)


STEM = re.compile(r"^[a-z0-9][a-z0-9._-]*$")           # an alias that reads as a file name, not a title


def renames(vault, reports):
    """{old path: new path} for each note renamed in the vault: the close log's rename rows (`renamed_to`, written by
    `ela vault rename` or by hand; a migration's `renamed_from`), then each note's aliases that read as a file name its
    folder no longer holds (an old name is kept as an alias). A chain a → b → c resolves to c."""
    out = {}
    try:
        for line in open(os.path.join(reports or "", "ela", "vault-removed.jsonl"), encoding="utf-8"):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("renamed_to") and row.get("path"):
                out[row["path"]] = row["renamed_to"]
            elif row.get("renamed_from") and row.get("path"):
                out[row["renamed_from"]] = row["path"]
    except OSError:
        pass
    for rel, text in vault_notes(vault) if vault and os.path.isdir(vault) else ():
        d = os.path.dirname(rel)
        for al in list_prop(split_front(text)[0], "aliases"):
            old = f"{d}/{al}.md" if d else f"{al}.md"
            if STEM.match(al) and old != rel and old not in out and not os.path.exists(os.path.join(vault, old)):
                out[old] = rel
    def last(p, seen=()):
        n = out.get(p)
        return p if n is None or n in seen else last(n, seen + (p,))
    return {o: last(o) for o in out if last(o) != o}


def follow_manifest(m, moved):
    """The manifest's paths followed through renames, in place: the files it wrote, the vault's own notes, and the
    path-keyed records. → the keys changed."""
    changed = []
    for key in ("files", "native"):
        if key in m:
            new = sorted({moved.get(p, p) for p in m.get(key) or []})
            if new != sorted(m.get(key) or []):
                m[key] = new
                changed.append(key)
    for key in ("sources", "seen", "generated"):
        d = m.get(key) or {}
        if any(k in moved for k in d):
            m[key] = {moved.get(k, k): v for k, v in d.items() if not (k in moved and moved[k] in d)}
            changed.append(key)
    return changed


def gone_by_hand(vault, old_native, native_paths, removed, backup=None, moved=None):
    """The notes of the vault's own (source: vault: meeting notes, plans, the owner's documents) the last sync saw and
    that are gone now without a verb: no deletion row, no rename (`moved`, from renames), no note of the same name
    elsewhere. On the first sync that keeps the list, the last backup's copy of the vault stands in for it. A note gone
    this way keeps its trace."""
    if old_native is None:
        old_native = [n.path for n in native_notes(backup)] if backup and os.path.isdir(backup) else []
    names = {}
    for top_, dirs, fs in os.walk(vault):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in fs:
            names.setdefault(f.lower(), True)
    return sorted(r for r in old_native if r not in native_paths and r not in removed and r not in (moved or {})
                  and not os.path.exists(os.path.join(vault, r)) and os.path.basename(r).lower() not in names)


def record_gone(path, rels, now):
    """One deletion row for each note gone by hand: fate `gone by hand`, and where its last copy is (the runner's
    nightly backup, branch backup/reports, under vault/)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for r in rels:
            fh.write(json.dumps({"at": now.isoformat(timespec="seconds"), "path": r,
                                 "title": sentence(re.sub(r"^\d{4}-\d{2}-\d{2}-", "", os.path.basename(r)[:-3]).replace("-", " ")),
                                 "fate": "gone by hand", "by": "owner", "backup": f"backup/reports:vault/{r}"}, ensure_ascii=False) + "\n")


def today_said(vault, today, said, answers, planned):
    """His `ela:` lines on today.md by the day each was written: the manifest's record, else the day its answer was
    asked, else today. → ({day page: [lines]} for an earlier day's lines, {line: day} for today's). today.md starts each
    day without yesterday's words; they stay on that day's page, reference/days/<year>/<date>-brief.md, with their
    answers (ADR 0014: today.md is today's page). A line whose day page is not written leaves today.md and stays in
    the answers' record."""
    try:
        text = open(os.path.join(vault, TODAY), encoding="utf-8").read()
    except OSError:
        return {}, {}
    asked = {}
    for r in answers:
        if r.get("note") == TODAY and r.get("at"):
            for x in r.get("lines") or []:
                asked[x.strip()] = min(asked.get(x.strip(), r["at"][:10]), r["at"][:10])
    stale, keep = {}, {}
    for m in GUIDE.finditer(text, body_start(text)):
        line = m.group(0).strip()
        day = said.get(line) or asked.get(m.group(1).strip().strip('"').strip("'")) or today.isoformat()
        if day >= today.isoformat():
            keep[line] = day
            continue
        page = f"{DAYS}/{day[:4]}/{day}-brief.md"
        if page in planned:
            stale.setdefault(page, []).append(line)
        else:
            stale.setdefault(None, []).append(line)
    return stale, keep


def cmd_sync(a):
    s = json.load(open(SITE))
    vault = s.get("vault")
    if not vault or not os.path.isdir(vault):
        print(f"site.json `vault` is not a folder: {vault}", file=sys.stderr); sys.exit(2)
    env = a.env_file or s.get("env")
    today, now = datetime.date.today(), datetime.datetime.now()
    mpath = os.path.join(vault, MANIFEST)
    old, old_src, old_layout, old_gen, old_seen, old_home = [], {}, None, {}, {}, {}
    old_moved = {"map": {}, "until": None}
    old_said, old_native = {}, None
    if os.path.exists(mpath):
        try:
            m = json.load(open(mpath))
            old, old_src, old_layout, old_gen, old_seen = (m["files"], m.get("sources") or {}, m.get("layout"), m.get("generated") or {},
                                                           m.get("seen") or {})
            old_home = m.get("home") or {}
            old_said = m.get("said") or {}
            old_native = m.get("native")
            old_moved = {"map": m.get("moved") or {}, "until": m.get("moved_until")}
        except (ValueError, KeyError):
            print("vault: the manifest is unreadable; not synced (remove it deliberately to start over)", file=sys.stderr); sys.exit(3)
    if old_layout and old_layout > LAYOUT:                 # a newer layout on disk: this sync would write the old one into it
        print(f"vault: not synced — the vault is in layout {old_layout}, this ela writes layout {LAYOUT}", file=sys.stderr); sys.exit(3)
    if old_layout and old_layout < LAYOUT and old:         # ADR 0015: the move is one pass on the owner's word, never the sync's
        print(f"vault: not synced — the vault is in layout {old_layout}, this ela writes layout {LAYOUT}: "
              "`ela vault migrate` lists the moves, `--apply` makes them", file=sys.stderr); sys.exit(3)
    # a note the sync wrote that is gone from disk was deleted by the owner: that is feedback, and it stays deleted
    removed_path = os.path.join(s.get("reports") or "", "ela", "vault-removed.jsonl")
    marked = [] if a.dry_run else apply_marks(vault, s.get("reports") or "")   # ticked boxes first: they are his moves
    answered = answered_readings(vault, s.get("reports") or "", a.dry_run)
    rolled = meeting_roll(vault, today, a.dry_run)
    jira_url = next((l.split("=", 1)[1].strip() for l in open(env) if l.startswith("JIRA_BASE_URL=")), "") \
        if env and os.path.isfile(env) else ""
    closed = meeting_close(vault, s.get("reports") or "", os.path.join(s.get("runtime") or "", "facts"),
                           datetime.datetime.now().astimezone(), *meeting_book(), dry_run=a.dry_run, jira=jira_url)
    qstate, qdone = (questions_pass(vault, s.get("reports") or "", os.path.join(s.get("runtime") or "", "facts"),
                                    datetime.datetime.now().astimezone(), meeting_book()[0], jira_url, dry_run=a.dry_run)
                     if os.path.isdir(s.get("reports") or "") else (None, {"consumed": [], "closed": [], "new": []}))   # no root: plan stops the sync
    for qi, words in qdone["closed"]:
        print(f"question {qi}: {words}", file=sys.stderr)
    for fix in settle_statuses(vault, a.dry_run):
        print(f"status: {fix}", file=sys.stderr)
    if not a.dry_run:
        write_move_sets(vault)                             # the choosers follow MOVE_PROPS without a setup run
    removed, removed_src = load_removed(removed_path)
    # only a dated note in a reading folder can be done with; a living page (Home, the board, the library index, how
    # ela runs) is rewritten whatever happens to it
    newly = sorted(r for r in old if r.endswith(".md") and r not in removed and deletable(r)
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
                                                                        since, a.dry_run, questions=qstate)
    except SourceError as e:
        print(f"vault: not synced — {e}", file=sys.stderr); sys.exit(3)
    if newly and not a.dry_run:
        record_removed(removed_path, newly, old_src, now, archived)
    by_hand = gone_by_hand(vault, old_native, native_paths, removed, os.path.join(s.get("runtime") or "", "backup", "work", "vault"),
                           renames(vault, s.get("reports")))      # a renamed note has not vanished
    if by_hand and not a.dry_run:
        record_gone(removed_path, by_hand, now)
    for r in by_hand:
        print(f"vault: {r} is gone without a verb; recorded, its last copy in the backup", file=sys.stderr)
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
    jb = next((l.split("=", 1)[1].strip().rstrip("/") for l in open(env) if l.startswith("JIRA_BASE_URL=")), "") \
        if env and os.path.isfile(env) else ""
    release_notes_native(vault, s.get("reports") or "", s.get("runtime") or "",       # a build's note: ela's part current
                         Linker({}, {}, jb, project_keys(env, s.get("runtime")) or [], s.get("reports")) if jb else None, a.dry_run,
                         s.get("helm_local_url"))
    ensure_native_moves(vault, a.dry_run)
    # a task its source already ticked is not his choice; recorded so the guidance verb tells the two apart
    source_ticks = {r: [m.group(1) for m in TICKED.finditer(t)] for r, t in planned.items() if r.endswith(".md") and TICKED.search(t)}
    done_on_disk = set()
    stale, said = today_said(vault, today, old_said, answers, planned)
    stale_lines = {l for ls in stale.values() for l in ls}
    for target, lines in stale.items():                    # yesterday's words on today.md go to that day's page, answers too
        if target is None:
            continue
        answers = answers + [dict(r, note=target) for r in answers if r.get("note") == TODAY
                             and {x.strip() for x in r.get("lines") or []} & {GUIDE.match(l).group(1).strip() for l in lines if GUIDE.match(l)}]
    for rel in [r for r in planned if r.endswith(".md")]:  # his `ela:` lines in a generated note outlive its rewrite
        try:
            disk = open(os.path.join(vault, rel), encoding="utf-8").read()
        except OSError:
            continue
        dfl, dbody = split_front(disk)
        if is_done(props_of(dfl)):                         # he marked it done: the copy on disk is the record
            done_on_disk.add(rel)
            continue
        planned[rel] = keep_choice(planned[rel], dfl, rel)   # the move he chose waits for the watcher, not for this rewrite
        for m in TICKED.finditer(dbody):                   # a choice he ticked stays ticked when the page is rewritten
            planned[rel] = re.sub(r"^(\s*" + QUOTE + r"[-*]\s+)\[ \](\s+" + re.escape(m.group(1)) + r"\s*)$", r"\1[x]\2", planned[rel], count=1, flags=re.M)
        mine = [(section_at(dbody, m.start()), m.group(0).strip()) for m in GUIDE.finditer(dbody) if m.group(0).strip() not in planned[rel]
                and not (rel == questions_mod().QUESTIONS_PAGE and m.group(0).strip() in qdone["consumed"])   # read: on the record now
                and not (rel == TODAY and m.group(0).strip() in stale_lines)]                                 # an earlier day's: on its page
        mine += [(None, l) for l in stale.get(rel, []) if l not in planned[rel] and l not in [x for _, x in mine]]
        # a word typed in the ela property, which the tables no longer offer, stays as a line in the note, written as
        # typed so its guidance id is the one already handled
        said = next((l.strip() for l in dfl if re.match(r'^ela:\s*\S', l) and not re.match(r'^ela:\s*""\s*$', l)), None)
        if said and said not in planned[rel] and said not in [l for _, l in mine]:
            mine.append((None, said))
        if mine:
            planned[rel] = place_lines(planned[rel], mine)
        planned[rel] = with_answers(planned[rel], rel, answers)   # each ask shows its answer under it
    for rel, text in planned.items():
        if rel in done_on_disk:                            # done: the record, never written again, not ela's any more
            continue
        if is_kept(rel):                                   # a kept note is the record: the sync never writes there
            warnings.append(f"{rel}: planned into a kept folder, not written (the vault copy is the record)")
            continue
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
            shutil.copy2(src, tmp_path(dst)); os.replace(tmp_path(dst), dst)
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
    # acted on: done where it is (ADR 0015), the record from now on, outside the manifest
    to_archive = sorted(r for r in set(old) - now_files if r.endswith(".md") and deletable(r) and acted(r)
                        and os.path.exists(os.path.join(vault, r)) and not is_kept(r, vault))
    if to_archive and not a.dry_run:
        for r in to_archive:
            p = os.path.join(vault, r)
            atomic_write(p, set_front(open(p, encoding="utf-8").read(), status=DONE, **{MOVE_SET: "closed", NEXT: "done", "closed-by": "ela"}))
        record_removed(removed_path, to_archive, old_src, now, {os.path.basename(r).lower(): DONE for r in to_archive}, by="ela")
    keep_dirs = archive_refs(vault)
    gone = sorted(r for r in set(old) - now_files if not r.startswith(".obsidian") and r.lower() not in lower
                  and r.lower() not in native_lower and not any(r.lower().startswith(d + "/") for d in keep_dirs)
                  and top(r) not in RETIRED and r not in {f for f, _ in moved} and r not in to_archive
                  and not is_kept(r, vault))               # a done note is the record: his, never removed
    left = sorted(r for r in set(old) - now_files if top(r) in RETIRED)   # the owner's now; never removed by the sync
    if not a.dry_run:
        # the manifest first: a crash before the removals leaves files it no longer lists, never removals it would
        # later read as the owner's deletions
        atomic_write(mpath, json.dumps({"synced": now.isoformat(timespec="seconds"), "layout": LAYOUT, "files": sorted(now_files - done_on_disk),
                                        "sources": {n.path: n.src_rel for n in notes if n.src_rel},
                                        "generated": {r: digest(t) for r, t in planned.items() if r.endswith(".base")},
                                        "seen": {r: d for r, d in seen.items() if r in planned},
                                        "home": {"open": is_open, "looked": looked, "before": before},
                                        "moved": moved_paths(old_moved, today), "moved_until": old_moved.get("until"),
                                        "source_ticks": source_ticks, "said": said, "native": sorted(native_paths)}, indent=0))
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
    for c in append_source_changes(vault, s.get("reports") or "", s.get("elak"), a.dry_run):
        warnings.append(f"{c['note']}: its source {c['src']} changed after the note closed; noted under Afterwards")
    held = [{"note": n.path, "problems": n.held} for n in notes if n.held]
    in_archive = len(kept_notes(vault))
    counts = {"generated": len(planned), "in_place": len(native_paths), "archived": in_archive}
    r = {**counts, "dry_run": a.dry_run, "deleted_by_owner": newly, "archived_by_ela": to_archive, "moved": [{"from": f, "to": t} for f, t in moved],
         "answered": [{"from": f, "to": t} for f, t in answered],
         "rolled": [{"note": f, "date": d, "to": t} for f, d, t in rolled], "closed": closed,
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
        print(f"  acted on, done by ela where it is: {d}")
    for f, d, t in rolled:
        print(f"  ruled {d}, over {MEETING_RULED_DAYS} days: {f} → {t}")
    for c in closed:
        print(f"  closed {c['note']} ({c['day']}): {len(c['outcome'])} outcomes, {len(c['rolled'])} rolled, {len(c['dropped'])} left the list")
    for d in newly:
        print(f"  deleted by the owner, recorded as read: {d}")
    for p_, k in inferred:
        print(f"  project {k} inferred from its keys: {p_}")
    for h in held:
        print(f"  warning {h['note']}: {'; '.join(h['problems'])}")
    for w in warnings:
        print(f"  note: {w}", file=sys.stderr)


# ── the migration to layout 5: things and angles (ADR 0015) ────────────────────────────────────────────
# One pass, on the owner's word: every note of layout 4 to its thing's home, old names kept as aliases, links
# rewritten, statuses brought to live and done. A dry run by default; the sync never runs it, and refuses to write a
# vault still in layout 4. The moves are kept in the manifest, so for OLD_PATHS_DAYS an old path given to a verb is
# read as its new one, and logged one row each in <reports>/ela/vault-migrated.jsonl (not the removal log, whose
# every row is a deletion the sync honours).
ROOTS5 = ("today.md", "meetings", "projects", "releases", "cases", "reference", "ela", "archive")
OLD_PATHS_DAYS = 14
LAYOUT4_FOLDERS = ("to-read", "in-progress", "parked", "readings", "days", "lanes", "mh", "sprints", "mediahub-bot", "library", "to-learn")
RETIRED_ANGLES = ("board.md", "recent.md", "constraints.md")   # generated daily, consumed by nobody (ADR 0015)
KIND_WORDS = ("decision", "plan", "sprint", "review", "verify", "verify-plan", "deep", "draft", "timeline", "case",
              "glossary", "record") + RELEASE_KINDS
KIND_OF_TYPE = {"decision": "decision", "plan": "plan", "sprint": "sprint", "review": "review", "ticket": "deep",
                "verify": "verify", "verify-plan": "verify-plan", "draft": "draft", "report": "review"}
LIVE_STATUSES = ("proposed", "blocked", "building", "built", "waiting", "parked")
MIGRATE_LOG = "vault-migrated.jsonl"


def dated_name(name, kind):
    """`<date>-<kind>-<what>.md`: a dated name whose first word after the date is not a kind gets its type's kind
    word inserted; an undated name, or one already under the rule, is returned as it is."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+)\.md$", name)
    word = KIND_OF_TYPE.get(kind or "")
    if not m or not word or any(m.group(2) == k or m.group(2).startswith(k + "-") for k in KIND_WORDS):
        return name
    rest = re.sub(rf"-{re.escape(word)}$", "", m.group(2))   # jira-four-week-review → review-jira-four-week
    return f"{m.group(1)}-{word}-{rest}.md"


def beside_name(name, props, project):
    """A note's name in its project's folder: `<date>-<kind>-<what>`, the folder carrying the subject, so the project's
    own key and the words of its name leave `what` (a sub-task's key stays: it is information). A `slug` property on
    the note is its `what`, by hand."""
    name = dated_name(name, props.get("type"))
    kinds = sorted(KIND_WORDS, key=len, reverse=True)
    m = next((re.match(rf"^(\d{{4}}-\d{{2}}-\d{{2}})-({k})-(.+)\.md$", name) for k in kinds
              if re.match(rf"^\d{{4}}-\d{{2}}-\d{{2}}-{k}-", name)), None)
    if not m:
        return name
    if props.get("slug") and re.fullmatch(SLUG, props["slug"]):
        return f"{m.group(1)}-{m.group(2)}-{props['slug']}.md"
    km = re.match(r"^([a-z][a-z0-9]*-\d+)-(.+)$", project)
    what = m.group(3)
    if km:
        what = re.sub(rf"(?:^|-){re.escape(km.group(1))}(?=-|$)", "", what).strip("-")
        subject = set(km.group(2).split("-"))
        words = what.split("-")
        kept, i = [], 0
        while i < len(words):                              # a key is two tokens (mh-3987): kept whole
            if i + 1 < len(words) and re.fullmatch(r"[a-z][a-z0-9]*", words[i]) and words[i + 1].isdigit():
                kept += words[i:i + 2]; i += 2; continue
            if words[i] not in subject:
                kept.append(words[i])
            i += 1
        what = "-".join(kept) or what
    return f"{m.group(1)}-{m.group(2)}-{what}.md"


def old_project_key(key, summary):
    """The page name the first generator gave a Jira project: the key and the summary's slug cut at 32 characters,
    which is how a generated page is told from one the desk named by hand."""
    out = []
    for w in slug(summary).split("-"):
        if len("-".join(out + [w])) > 32:
            break
        out.append(w)
    return f"{key.lower()}-{'-'.join(out)}".rstrip("-")


def lane_lines():
    """{lane: line} from the release map's lines (each line's qa, daily and prod lanes); {} when it cannot be read."""
    try:
        sys.path.insert(0, os.path.join(HERE, "..", "release"))
        import release as R  # noqa: E402
        lines = R.rmap("lines") or {}
    except (Exception, SystemExit):
        return {}
    out = {}
    for line, cfg in lines.items():                        # the newest line that runs a lane (the map lists newest first)
        for lane in ((cfg or {}).get("lanes") or {}).values():
            if lane:
                out.setdefault(lane, line)
    try:
        regions = R.rmap("regions") or {}
    except (Exception, SystemExit):
        regions = {}
    for reg in regions.values():                           # a region's lane runs the line the map names, else its aligned lane's
        for lane, cfg in ((reg or {}).get("lanes") or {}).items():
            line = (cfg or {}).get("line") or out.get((reg or {}).get("aligns_with") or "")
            if line and not (cfg or {}).get("retiring"):
                out[lane] = line
    return out


def list_home(name, lanes=None):
    """A line's list page in layout 5, from its layout-4 name in lanes/, the name kept so no two notes share one:
    train-<line> and dev-list-<line> → that line's folder; test-list-<lane> → the folder of the line the lane carries
    (a China lane's from the map's regions), else releases/."""
    m = re.match(r"^(train|dev-list)-(\d+\.\d+)\.md$", name)
    if m:                                                  # the line stays in the name: [[train-2.1]] resolves to one note
        return f"{RELEASES5}/{m.group(2)}/{name}"
    m = re.match(r"^test-list-(.+)\.md$", name)
    if m:
        line = (lanes if lanes is not None else lane_lines()).get(m.group(1))
        return f"{RELEASES5}/{line}/{name}" if line else f"{RELEASES5}/{name}"
    return f"{RELEASES5}/{name}"


def thing_of(props, pages, subtasks):
    """The project page key a note serves: its own `project:`, else the one page whose keys (and their tickets'
    sub-tasks) take in the note's keys; None when none or more than one does."""
    if props.get("project") and props["project"] in pages:
        return props["project"]
    keys = {k for k in KEY_RX.findall(str(props.get("keys") or "") + " " + str(props.get("title") or "")) if not NOT_KEYS.match(k)}
    hits = set()
    for key, ks in pages.items():
        own = set(ks) | {s for k in ks for s in subtasks.get(k, ())}
        if keys & own:
            hits.add(key)
    return hits.pop() if len(hits) == 1 else None


def status5(kind, status, old_top):
    """A note's status in layout 5: a work note live or done; a case, a report and a project keep their own."""
    s = (status or "").strip().lower()
    if kind in ("case", "report", "project", "meeting") or kind not in WORK_TYPES:
        return status or None
    if s in ("closed", "done") or old_top in ("archive", "sprints") or (old_top == "mh" and s == "closed"):
        return "done"
    if s in LIVE_STATUSES or s == "live" or old_top in ("to-read", "in-progress", "parked"):
        return "live"
    return status or None


def migrate_plan(vault, slugs=None, lanes=None, runtime=None):
    """Every change the migration makes, nothing written: {moves: [{from, to, why}], retire: [{path, why}], props:
    {path: {key: value}}, aliases: {new path: old name}, keep: [path], dirs: [dir], layout}. A move's `to` is the
    note's place in layout 5; a page renamed keeps its old name as an alias. `slugs`: {KEY: words} naming a project
    page by hand (`--slug MH-3983=csc-over-mqtt`), as a `slug` property on the page does."""
    slugs = {k.upper(): v for k, v in (slugs or {}).items()}
    lanes = lane_lines() if lanes is None else lanes
    try:
        manifest = json.load(open(os.path.join(vault, MANIFEST)))
    except (OSError, ValueError):
        manifest = {}
    generated = set(manifest.get("files") or [])
    files = []
    for top_, dirs, fs in os.walk(vault):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        files += [os.path.relpath(os.path.join(top_, f), vault).replace(os.sep, "/") for f in sorted(fs) if not f.startswith(".")]
    text_of, props = {}, {}
    for r in files:
        if r.endswith(".md"):
            try:
                text_of[r] = open(os.path.join(vault, r), encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                text_of[r] = ""
            props[r] = props_of(split_front(text_of[r])[0])
    # the project pages, by key, and the keys each one's notes may name
    pages = {}
    for r in files:
        m = PROJECT_PAGE.match(r)
        if m and r.endswith(".md"):
            pages[os.path.basename(r)[:-3]] = r
    page_keys = {k: [x for x in KEY_RX.findall(props[r].get("keys") or "") if not NOT_KEYS.match(x)] for k, r in pages.items()}
    subtasks = {t["key"]: [x[0] for x in t["subtasks"]] for t in jira_projects(runtime)} if runtime else {}
    moves, retire, prop_changes = {}, [], {}

    def move(r, to, why):
        if to != r:
            moves[r] = (to, why)

    # a project page: renamed to its slug (the --slug word, its `slug` property, else the rule for a generated page)
    page_to = {}
    for key, r in pages.items():
        lead = (page_keys.get(key) or [None])[0]
        words = slugs.get(lead or "") or props[r].get("slug")
        title = re.sub(r"^[A-Z][A-Z0-9]+-\d+ · ", "", props[r].get("title") or "")
        if not words and lead and title and key == old_project_key(lead, title):   # named by the old cut, not by hand
            words = project_slug(title)
        new = f"{lead.lower()}-{words}" if lead and words else key
        page_to[key] = new
    # notes that serve a project go beside its page, and the page into its folder
    beside = {}
    for r in files:
        t = top(r)
        if not r.endswith(".md") or t not in ("to-read", "in-progress", "parked", "readings", "mh") or r.startswith("mh/releases/"):
            continue
        if props[r].get("type") in ("program",):
            continue
        k = thing_of(props[r], page_keys, subtasks)
        if not k:                                          # linked from exactly one project page: it serves that one
            stem = os.path.basename(r)[:-3].lower()
            hits = [pk for pk, pr in pages.items() if re.search(r"\[\[(?:[^\]|#]*/)?" + re.escape(stem) + r"(?:\.md)?[\]|#]", text_of[pr].lower())]
            k = hits[0] if len(hits) == 1 else None
        if k:
            beside.setdefault(k, []).append(r)
    for key, r in pages.items():
        new = page_to[key]
        if r.count("/") == 2:                              # already a folder: the page and its folder follow the name
            if new != key:
                for f in files:
                    if f.startswith(f"{PROJECTS}/{key}/"):
                        rest = f[len(f"{PROJECTS}/{key}/"):]
                        move(f, f"{PROJECTS}/{new}/" + (f"{new}.md" if rest == f"{key}.md" else rest), "the project's name")
        elif beside.get(key) or os.path.isdir(os.path.join(vault, PROJECTS, key)):
            move(r, f"{PROJECTS}/{new}/{new}.md", "its notes sit beside it: the page into the project's folder")
        else:
            move(r, f"{PROJECTS}/{new}.md", "the project's name: its key and two to four whole words")
    for key, rs in beside.items():
        new = page_to[key]
        for r in rs:
            move(r, f"{PROJECTS}/{new}/{beside_name(os.path.basename(r), props[r], new)}", f"serves the {new} project")
    for r in files:
        if r in moves:
            continue
        t, name, kind = top(r), os.path.basename(r), (props.get(r) or {}).get("type")
        if r in RETIRED_ANGLES:
            if r in generated:
                retire.append({"path": r, "why": "an angle nothing consumes; its source stays under the reports root"})
            else:
                move(r, f"{ARCHIVE}/{name}", "an angle nothing consumes, kept")
        elif r == "one-thing.md":
            move(r, f"{REF}/one-thing.md", "One Thing rows: the runner reads its pasted ticks")
        elif r == "lanes.md":
            move(r, f"{RELEASES5}/lanes.md", "the overview across release lines")
        elif t == "lanes":
            move(r, list_home(name, lanes), "a line's list lives with the line")
        elif t == "days":
            move(r, f"{REF}/{r}", "the day pages, kept as the record of what ela said")
        elif r.startswith(f"{ELA}/review/") and re.match(r"^\d{4}-\d{2}-\d{2}-reader\.md$", name):
            if r in generated:
                retire.append({"path": r, "why": "a reader page nothing consumes; its source stays under <reports>/review/"})
        elif r.startswith("mh/releases/"):
            rest = r[len("mh/releases/"):]
            line_dir, _, base = rest.rpartition("/")
            if base.endswith(".md"):                       # release-2-1-record keeps its line: one record.md per line would collide
                base = release_review_name(base) if re.match(r"^\d{4}-\d{2}-\d{2}-", base) and kind == "review" else base
            move(r, f"{RELEASES5}/{line_dir + '/' if line_dir else ''}{base}", "a release line's folder")
        elif t == "mh":
            to = f"{REF}/{dated_name(name, kind) if r.endswith('.md') else name}"
            move(r, to, "a product reading that serves no project" if kind != "program" else "the program's page")
        elif t == "mediahub-bot":
            move(r, f"{PROJECTS}/{r}", "bounded outside work: a project")
        elif t == "parked" and r.endswith(".md"):
            stem = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", name[:-3])
            move(r, f"{PROJECTS}/{stem}.md", "a parked plan is a project, status parked")
            prop_changes.setdefault(r, {}).update({"type": "project", "status": "parked", MOVE_SET: None, NEXT: None})
        elif t == "sprints" and re.match(r"^\d{4}-[sS](\d+)\.md$", name):
            day = (props[r].get("end") or props[r].get("date") or "")[:10]
            n = int(re.match(r"^\d{4}-[sS](\d+)", name).group(1))
            move(r, f"{ARCHIVE}/{day}-sprint-{n}.md" if day else f"{ARCHIVE}/{name.lower()}", "a closed sprint, dated by its end")
        elif t in ("sprints", "in-progress", "to-read", "readings") and r.endswith(".md"):
            home = home_for(r, props[r])
            folder = ARCHIVE if t == "sprints" else home
            move(r, f"{folder}/{dated_name(name, kind)}", "its thing's home" if folder != REF else "serves no project")
    # statuses: a work note live or done, wherever it now sits; a `project:` follows its page's new name
    for r, p in props.items():
        old_top = top(r)
        want = status5(p.get("type"), p.get("status"), old_top)
        ch = prop_changes.setdefault(r, {})
        if p.get("project") in page_to and page_to[p["project"]] != p["project"]:
            ch["project"] = page_to[p["project"]]
        if want and want != p.get("status") and "status" not in ch:
            ch["status"] = want
        if p.get("type") == "readme" and moves.get(r, ("",))[0].startswith(f"{PROJECTS}/") and PROJECT_PAGE.match(moves[r][0]):
            ch["type"] = "project"                         # a folder's readme that becomes its project page
        if not ch:
            prop_changes.pop(r)
    aliases = {}
    for r, (to, _) in moves.items():
        if r.endswith(".md") and os.path.basename(r) != os.path.basename(to):
            aliases[to] = os.path.basename(r)[:-3]
    gone_dirs = sorted({d for d in LAYOUT4_FOLDERS if os.path.isdir(os.path.join(vault, d))
                        and all(f in moves or f in {x["path"] for x in retire} for f in files if f.startswith(d + "/"))})
    out_moves = [{"from": r, "to": t, "why": w} for r, (t, w) in sorted(moves.items())]
    gone = {x["path"] for x in retire}
    names = {}
    for r in files:                                        # a bare [[name]] must resolve to one note after the move
        if r.endswith(".md") and r not in gone:
            to = moves.get(r, (r,))[0]
            names.setdefault(os.path.basename(to).lower(), []).append(to)
    clashes = {n: sorted(v) for n, v in names.items() if len(v) > 1}
    return {"moves": out_moves, "retire": retire, "props": prop_changes, "aliases": aliases, "dirs": gone_dirs,
            "clashes": clashes, "layout": {"from": manifest.get("layout"), "to": LAYOUT5}}


WIKI = re.compile(r"(!?\[\[)([^\]|#\n]+?)(\.md)?((?:#[^\]|\n]*)?(?:\|[^\]\n]*)?\]\])")
MDLINK = re.compile(r"(\]\()([^)\s#]+?\.md)((?:#[^)\s]*)?\))")


def rewrite_links(text, by_path, by_name):
    """The text with every wikilink and markdown link to a moved note pointed at its new place: a link with a folder
    path gets the new path, a bare name the new name when it changed. → (text, count)."""
    n = [0]

    def wiki(m):
        target = m.group(2).strip()
        low = target.lower()
        new = by_path.get(low) if "/" in target else by_name.get(low)
        if not new:
            return m.group(0)
        n[0] += 1
        return m.group(1) + new + m.group(4)

    def md(m):
        t = m.group(2)
        new = by_path.get(t[:-3].lower())
        if not new:
            return m.group(0)
        n[0] += 1
        return m.group(1) + new + ".md" + m.group(3)
    return MDLINK.sub(md, WIKI.sub(wiki, text)), n[0]


def link_maps(moves, vault=None):
    """({old path: new path}, {old name: new link target}) without .md, lowercase keys. A bare name link to a renamed
    note gets the new name, or the new path when the new name is not unique after the move (each line's record.md); a
    name two moved notes shared is left to the alias, never guessed."""
    by_path = {m["from"][:-3].lower(): m["to"][:-3] for m in moves if m["from"].endswith(".md")}
    where = {m["from"]: m["to"] for m in moves}
    count = {}
    if vault:
        for top_, dirs, fs in os.walk(vault):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in fs:
                if f.endswith(".md"):
                    r = os.path.relpath(os.path.join(top_, f), vault).replace(os.sep, "/")
                    n = os.path.basename(where.get(r, r))[:-3].lower()
                    count[n] = count.get(n, 0) + 1
    names = {}
    for m in moves:
        if m["from"].endswith(".md"):
            o, nw = os.path.basename(m["from"])[:-3], os.path.basename(m["to"])[:-3]
            if o != nw:
                names.setdefault(o.lower(), set()).add(m["to"][:-3] if count.get(nw.lower(), 1) > 1 else nw)
    return by_path, {o: next(iter(v)) for o, v in names.items() if len(v) == 1}


def link_changes(vault, plan):
    """{path after the move: links rewritten} for every note the rewrite touches; read only."""
    by_path, by_name = link_maps(plan["moves"], vault)
    where = {m["from"]: m["to"] for m in plan["moves"]}
    gone = {x["path"] for x in plan["retire"]}
    out = {}
    for top_, dirs, fs in os.walk(vault):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in fs:
            if not f.endswith((".md", ".base", ".canvas")):
                continue
            r = os.path.relpath(os.path.join(top_, f), vault).replace(os.sep, "/")
            if r in gone:
                continue
            try:
                _, n = rewrite_links(open(os.path.join(top_, f), encoding="utf-8").read(), by_path, by_name)
            except (OSError, UnicodeDecodeError):
                continue
            if n:
                out[where.get(r, r)] = n
    return out


def migrate_apply(vault, reports, plan, today):
    """Carry out a plan from migrate_plan under the vault lock (the caller holds it): moves, aliases and statuses, the
    retired angles removed, links rewritten, emptied folders removed, the bookmarks and the manifest brought to layout
    5, each move logged. → the number of links rewritten."""
    by_path, by_name = link_maps(plan["moves"], vault)              # read before anything moves
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    log = os.path.join(reports or vault, "ela", MIGRATE_LOG)
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, "a", encoding="utf-8") as fh:
        for m in plan["moves"]:
            src, dst = os.path.join(vault, m["from"]), os.path.join(vault, m["to"])
            if not os.path.exists(src):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.exists(dst) and os.path.realpath(dst) != os.path.realpath(src):
                dst = free_path(os.path.dirname(dst), os.path.basename(dst))
                m["to"] = os.path.relpath(dst, vault).replace(os.sep, "/")
            if m["from"].endswith(".md"):
                text = open(src, encoding="utf-8").read()
                ch = plan["props"].get(m["from"]) or {}
                if ch:
                    text = set_front(text, **ch)
                if plan["aliases"].get(m["to"]):
                    text = with_alias(text, plan["aliases"][m["to"]])
                atomic_write(dst, text)
                if os.path.realpath(dst) != os.path.realpath(src):
                    os.remove(src)
            else:
                os.replace(src, dst)
            fh.write(json.dumps({"at": now, "path": m["to"], "renamed_from": m["from"], "why": m["why"], "by": "migrate"},
                                ensure_ascii=False) + "\n")
        for x in plan["retire"]:
            try:
                os.remove(os.path.join(vault, x["path"]))
            except OSError:
                continue
            fh.write(json.dumps({"at": now, "path": x["path"], "retired": True, "why": x["why"], "by": "migrate"}, ensure_ascii=False) + "\n")
    moved = {m["from"] for m in plan["moves"]}
    for r, ch in plan["props"].items():                   # statuses of the notes that stay where they are
        p = os.path.join(vault, r)
        if r not in moved and os.path.isfile(p):
            atomic_write(p, set_front(open(p, encoding="utf-8").read(), **ch))
    links = 0
    for top_, dirs, fs in os.walk(vault):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in fs:
            if f.endswith((".md", ".base", ".canvas")):
                p = os.path.join(top_, f)
                try:
                    text = open(p, encoding="utf-8").read()
                except (OSError, UnicodeDecodeError):
                    continue
                new, n = rewrite_links(text, by_path, by_name)
                if n:
                    atomic_write(p, new)
                    links += n
    for d in sorted({os.path.dirname(m["from"]) for m in plan["moves"]} | set(plan["dirs"]), key=lambda x: -x.count("/")):
        parts = d.split("/") if d else []
        for i in range(len(parts), 0, -1):
            try:
                os.rmdir(os.path.join(vault, *parts[:i]))
            except OSError:
                break
    bm = os.path.join(vault, ".obsidian", "bookmarks.json")
    try:
        items = json.load(open(bm)).get("items") or []
        where = {m["from"]: m["to"] for m in plan["moves"]}
        gone = {x["path"] for x in plan["retire"]}
        keep = []
        for b in items:
            p = b.get("path") if isinstance(b, dict) else None
            if p in gone or (p and top(p) in RETIRED) or (p and not os.path.exists(os.path.join(vault, where.get(p, p)))):
                continue
            keep.append(dict(b, path=where.get(p, p)) if p else b)
        atomic_write(bm, json.dumps({"items": keep}, indent=2))
    except (OSError, ValueError):
        pass
    mpath = os.path.join(vault, MANIFEST)
    try:
        man = json.load(open(mpath))
    except (OSError, ValueError):
        man = {}
    where = {m["from"]: m["to"] for m in plan["moves"]}
    gone = {x["path"] for x in plan["retire"]}
    unmanaged = {m["from"] for m in plan["moves"] if re.search(r"-week\.md$", m["from"])}   # the week is no longer written
    man["files"] = sorted(where.get(r, r) for r in man.get("files") or [] if r not in gone and r not in unmanaged)
    man["sources"] = {where.get(r, r): s_ for r, s_ in (man.get("sources") or {}).items() if r not in gone and r not in unmanaged}
    man["seen"] = {where.get(r, r): d for r, d in (man.get("seen") or {}).items() if r not in gone and r not in unmanaged}
    man["source_ticks"] = {where.get(r, r): t for r, t in (man.get("source_ticks") or {}).items() if r not in gone}
    man["layout"] = LAYOUT5
    man["moved"] = {**(man.get("moved") or {}), **where}
    man["moved_until"] = (today + datetime.timedelta(days=OLD_PATHS_DAYS)).isoformat()
    atomic_write(mpath, json.dumps(man, indent=0))
    return links


def cmd_migrate(a):
    """`ela vault migrate [--apply] [--slug KEY=WORDS]`: the one pass from layout 4 to layout 5 (ADR 0015)."""
    s = json.load(open(SITE))
    vault = s.get("vault")
    if not vault or not os.path.isdir(vault):
        print(f"site.json `vault` is not a folder: {vault}", file=sys.stderr); sys.exit(2)
    slugs = {}
    for x in a.slug or []:
        k, _, v = x.partition("=")
        if not KEY_RX.fullmatch(k.upper()) or not re.fullmatch(SLUG, v or ""):
            print(f"--slug takes KEY=words-joined-by-hyphens, not {x!r}", file=sys.stderr); sys.exit(2)
        slugs[k.upper()] = v
    plan = migrate_plan(vault, slugs, runtime=s.get("runtime"))
    links = link_changes(vault, plan)
    if plan["layout"]["from"] == LAYOUT5 and not plan["moves"] and not plan["retire"]:
        print("vault: already in layout 5; nothing to migrate"); return
    applied = None
    if a.apply:
        applied = migrate_apply(vault, s.get("reports") or "", plan, datetime.date.today())
    r = {**plan, "links": links, "applied": a.apply, "links_rewritten": applied}
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1)); return
    print(f"{'' if a.apply else 'DRY RUN — '}vault migrate: layout {plan['layout']['from']} → {plan['layout']['to']} · "
          f"{len(plan['moves'])} moves ({len(plan['aliases'])} renamed, old names kept as aliases) · {len(plan['retire'])} retired · "
          f"{sum(1 for v in plan['props'].values() if 'status' in v)} statuses · {sum(links.values())} links in {len(links)} notes")
    print("\nMoves:")
    for m in plan["moves"]:
        print(f"  {m['from']} → {m['to']}" + (f"  (alias {plan['aliases'][m['to']]})" if m["to"] in plan["aliases"] else "") + f"  · {m['why']}")
    if plan["retire"]:
        print("\nRetired from the vault (not generated any more; the source stays):")
        for x in plan["retire"]:
            print(f"  {x['path']}  · {x['why']}")
    print("\nProperties:")
    for r, ch in sorted(plan["props"].items()):
        print(f"  {r}: " + ", ".join(f"{k} → {v if v is not None else '—'}" for k, v in ch.items()))
    print("\nLinks rewritten (after the moves):")
    for r, n in sorted(links.items()):
        print(f"  {r}: {n}")
    print("\nNames two notes share after the move (a bare link to one is ambiguous): "
          + ("none" if not plan["clashes"] else "; ".join(f"{n}: {', '.join(v)}" for n, v in sorted(plan["clashes"].items()))))
    if plan["dirs"]:
        print("\nFolders emptied and removed: " + ", ".join(f"{d}/" for d in plan["dirs"]))
    print("\n" + (f"applied: {applied} links rewritten; moves logged in <reports>/ela/{MIGRATE_LOG}; the manifest says layout 5"
                  if a.apply else "Nothing written. `ela vault migrate --apply` carries this out under the vault lock."))


def follow_records(vault, reports, moved, apply):
    """The records that name a note by its path brought to its new name: the open questions' sources
    (<reports>/ela/questions.json) and the sync's manifest. → [(record, what changed)]; written only with apply."""
    out = []
    Q = questions_mod()
    state = Q.load(reports)
    ids = Q.follow(state, moved)
    if ids:
        out.append(("questions.json", f"{len(ids)} questions follow the rename: " + ", ".join(ids[:8]) + (", …" if len(ids) > 8 else "")))
        if apply:
            Q.save(reports, state, atomic_write)
    mpath = os.path.join(vault, MANIFEST)
    try:
        m = json.load(open(mpath))
    except (OSError, ValueError):
        m = None
    keys = follow_manifest(m, moved) if m is not None else []
    if keys:
        out.append((MANIFEST, "paths followed in " + ", ".join(keys)))
        if apply:
            atomic_write(mpath, json.dumps(m, indent=0))
    return out


def name_breaks(rel, text):
    """Why a note's name breaks the naming rule (ADR 0017), or None: a note with a date is named from it."""
    props = props_of(split_front(text)[0])
    d = (props.get("date") or "")[:10]
    if d and not undated(props.get("type"), rel, text) and not os.path.basename(rel).startswith(d + "-"):
        return f"dated {d} but named `{os.path.basename(rel)}`"
    return None


def rename_note(vault, reports, old, new, apply):
    """One note renamed in one step (ADR 0017): moved, its old name kept as an alias, links to it rewritten, a
    `renamed_to` row in the close log, the records followed. → {links: [files], records: [(record, what)], warn}."""
    p_old, p_new = os.path.join(vault, old), os.path.join(vault, new)
    text = open(p_old, encoding="utf-8").read()
    o, n = os.path.basename(old)[:-3], os.path.basename(new)[:-3]
    out = {"links": relink(vault, o, n, dry_run=True) if o != n else [], "warn": name_breaks(new, text)}
    if not apply:
        out["records"] = follow_records(vault, reports, {**renames(vault, reports), old: new}, False)
        return out
    os.makedirs(os.path.dirname(p_new) or vault, exist_ok=True)
    atomic_write(p_new, with_alias(text, o) if o != n else text)
    os.remove(p_old)
    if o != n:
        out["links"] = relink(vault, o, n)
    log = os.path.join(reports, "ela", "vault-removed.jsonl")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": datetime.datetime.now().isoformat(timespec="seconds"), "path": old, "fate": "renamed",
                             "by": "owner", "renamed_to": new}, ensure_ascii=False) + "\n")
    out["records"] = follow_records(vault, reports, renames(vault, reports), True)
    return out


def cmd_rename(a):
    """`ela vault rename OLD NEW [--apply]`: one note renamed in one step (ADR 0017); `--records [--apply]`: the
    records brought to the renames already made (the close log's rename rows, the old names kept as aliases). A dry
    run unless --apply; under the vault lock."""
    s = json.load(open(SITE))
    vault, reports = s.get("vault"), s.get("reports") or ""
    if not vault or not os.path.isdir(vault):
        print(f"site.json `vault` is not a folder: {vault}", file=sys.stderr); sys.exit(2)
    if a.paths:
        if len(a.paths) != 2 or a.records:
            print("rename takes OLD NEW, or --records alone", file=sys.stderr); sys.exit(2)
        old, _ = note_path(vault, a.paths[0])
        new = os.path.relpath(os.path.realpath(a.paths[1]), os.path.realpath(vault)).replace(os.sep, "/") \
            if os.path.isabs(a.paths[1]) else a.paths[1]
        if not new.endswith(".md") or new.startswith("..") or new.startswith("."):
            print(f"not a note path in the vault: {a.paths[1]}", file=sys.stderr); sys.exit(2)
        if os.path.exists(os.path.join(vault, new)):
            print(f"{new} exists; not renamed", file=sys.stderr); sys.exit(2)
        same = [x for x, _ in vault_notes(vault) if x != old and os.path.basename(x) == os.path.basename(old)]
        if same and os.path.basename(old) != os.path.basename(new):
            print(f"{os.path.basename(old)} is also {', '.join(same)}: a link by name is ambiguous; not renamed", file=sys.stderr); sys.exit(2)
        r = rename_note(vault, reports, old, new, a.apply)
        if a.json:
            print(json.dumps({"from": old, "to": new, **r, "dry_run": not a.apply}, ensure_ascii=False, indent=1)); return
        print(f"{'' if a.apply else 'DRY RUN — '}{old} → {new}" + (f", alias {os.path.basename(old)[:-3]}" if old.rsplit('/', 1)[-1] != new.rsplit('/', 1)[-1] else ""))
        print(f"links: {len(r['links'])} notes" + (": " + ", ".join(r["links"][:6]) + (", …" if len(r["links"]) > 6 else "") if r["links"] else ""))
        for rec, what in r["records"]:
            print(f"{rec}: {what}")
        if r["warn"]:
            print(f"warning: the new name still breaks the naming rule ({r['warn']})", file=sys.stderr)
        if not a.apply:
            print("Nothing written. --apply renames it under the vault lock and logs the rename.")
        return
    if not a.records:
        print("rename takes OLD NEW, or --records", file=sys.stderr); sys.exit(2)
    moved = renames(vault, reports)
    done = follow_records(vault, reports, moved, a.apply)
    if a.json:
        print(json.dumps({"renames": moved, "records": done, "dry_run": not a.apply}, ensure_ascii=False, indent=1)); return
    for o, n in sorted(moved.items()):
        print(f"  {o} → {n}")
    for rec, what in done:
        print(f"{rec}: {what}")
    print(f"{len(moved)} renames known · {len(done)} records to follow" + ("" if a.apply else " · DRY RUN (--apply writes them)"))


# ── the archive keeps listening: Afterwards ───────────────────────────────────────────────────────────
# A note that sent something out (`posted:` permalinks) or follows tickets (`keys:`) is watched for a window after it
# leaves to-read: the threads' replies and the keys' status changes and comments since `watched:` become one dated line
# per source per day under its own `## Afterwards`, append-only; nothing else in the note is rewritten (vault
# to-read/2026-10-30-vault-workflow-review.md, proposal 5). The reading is brief.py's parked watcher, pointed here.
AFTERWARDS_HEAD = "## Afterwards"
WATCH_FOLDERS = THING_FOLDERS    # a done note, a note written in place, a project page: whatever carries keys and threads
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
    for rel in kept_notes(vault):                         # archive/, and a done note wherever its thing lives
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
    try:
        generated = set(json.load(open(os.path.join(vault, MANIFEST))).get("files") or [])
    except (OSError, ValueError):
        generated = set()
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
                if rel in generated and not (is_done(props) or props.get("type") == "project"):
                    continue                               # a generated live note is rewritten each sync: nothing to append to
                props.update({k: v for k, v in ((stamps or {}).get(rel) or {}).items() if v is not None})
                keys = sorted({k for k in KEY_RX.findall(props.get("keys") or "") if not NOT_KEYS.match(k)})
                links = sorted(set(PERMALINK.findall((props.get("posted") or "") + " " + (props.get("channels") or ""))))
                until = watch_until(props)
                if (keys or links) and until and until >= today:
                    out.append({"note": rel, "props": props,
                                "keys": keys, "links": links, "until": until})
    return sorted(out, key=lambda w: (w["until"], w["note"]))[:WATCH_NOTES]


def status_runs(ws):
    """A day's status moves as `from → to (who)`, one person's consecutive moves collapsed to their first from and last
    to (Backlog → In Progress → Review by one hand reads Backlog → Review)."""
    runs = []
    for w in (w for w in ws if w.get("kind") == "status"):
        if runs and runs[-1]["who"] == w.get("who") and runs[-1]["to"] == w.get("from"):
            runs[-1]["to"] = w.get("to")
        else:
            runs.append({"from": w.get("from"), "to": w.get("to"), "who": w.get("who")})
    return [f"{r['from']} → {r['to']} ({r['who']})" for r in runs]


def afterwards_lines(woke, jira_base="", tickets=None):
    """brief.parked_row's wake events as dated lines, one per source per day, in ela's words: the ticket by key and
    title, who moved it where, who commented or replied, and the link; never what a colleague wrote.
    tickets: {key: release.ticket_facts}, the fact store's. [(ref, date, line)]"""
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
            bits = status_runs(ws)
            if names("comment"):
                bits.append(f"a comment from {names('comment')}")
            t = (tickets or {}).get(ref)
            title = f" {release_mod().ticket_title(t.get('summary'))}" if t and t.get("summary") else ""
            line = (f"[{ref}]({jira_base}/browse/{ref})" if jira_base else ref) + title + ": " + "; ".join(bits)
        out.append((ref, day, f"- {day[5:]} · {line}"))
    return out


def parse_at(s):
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.datetime.strptime(s or "", fmt)
        except ValueError:
            continue
    return None


def is_kept(rel, vault=None):
    """Whether a vault path is the record: in archive/, or (read from disk when `vault` is given) a note marked done or
    a case closed. The sync never writes there."""
    rel = rel.replace(os.sep, "/").strip("/")
    if top(rel) == ARCHIVE:
        return True
    if not vault or not rel.endswith(".md"):
        return False
    try:
        return is_done(props_of(split_front(open(os.path.join(vault, rel), encoding="utf-8").read(4000))[0]))
    except OSError:
        return False


def kept_notes(vault):
    """Every kept note's vault path: archive/, and each done note in the things' homes."""
    out = []
    for fo in THING_FOLDERS:
        for r in notes_under(vault, fo):
            if fo == ARCHIVE or is_kept(r, vault):
                out.append(r)
    return out


def kept_sources(vault, reports, elak=None):
    """{kept note path: (source file, source as logged, closed at)} for each note the owner closed into a kept folder
    whose generator had a source: the close log (<reports>/ela/vault-removed.jsonl) names the source and the moment,
    the note is found by its file name under the kept folders. The latest close of a name wins; a restore undoes it."""
    closes = {}
    try:
        for line in open(os.path.join(reports or "", "ela", "vault-removed.jsonl"), encoding="utf-8"):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            name = os.path.basename(str(row.get("path") or "")).lower()
            if row.get("restored"):
                closes.pop(name, None)
            elif row.get("fate") == "archived" and row.get("src") and row.get("at"):
                closes[name] = (row["src"], row["at"])
    except OSError:
        return {}
    out = {}
    for rel in kept_notes(vault):
        hit = closes.get(os.path.basename(rel).lower())
        if not hit:
            continue
        src, at = hit
        path = next((os.path.join(root, src) for root in (reports, elak) if root and os.path.isfile(os.path.join(root, src))),
                    None)
        if path:
            out[rel] = (path, src, at)
    return out


def source_changes(vault, reports, elak=None):
    """The kept notes whose source was written after the note closed: [{note, src, closed, changed}], times local.
    Once a note is in a kept folder the vault copy is the record; a later source change is reported, never synced. A
    note whose front matter says `source: "vault"` is written in place: its old source is superseded, not a newer copy."""
    out = []
    for rel, (path, src, at) in sorted(kept_sources(vault, reports, elak).items()):
        try:
            if props_of(split_front(open(os.path.join(vault, rel), encoding="utf-8").read())[0]).get("source") == "vault":
                continue
            closed = datetime.datetime.fromisoformat(at)
            changed = datetime.datetime.fromtimestamp(os.path.getmtime(path))
        except (OSError, ValueError):
            continue
        if closed.tzinfo:
            closed = closed.astimezone().replace(tzinfo=None)
        if changed > closed + datetime.timedelta(seconds=1):
            out.append({"note": rel, "src": src, "closed": closed.isoformat(timespec="seconds"),
                        "changed": changed.isoformat(timespec="seconds")})
    return out


def source_change_line(c):
    """One Afterwards line for a source changed after its note closed: (ref, day, line), the day the source changed."""
    day = c["changed"][:10]
    return (c["src"], day, f"- {day[5:]} · the source `{c['src']}` changed at {c['changed'][11:16]}, after this note "
                           f"closed ({c['closed'][5:16].replace('T', ' ')}); this copy stays the record: carry over by "
                           "hand what should be kept")


def append_source_changes(vault, reports, elak=None, dry_run=False):
    """Append under Afterwards, in each kept note whose source changed after it closed, one line per changed day; the
    note's text is otherwise untouched. Returns the changes found."""
    found = source_changes(vault, reports, elak)
    for c in found:
        p = os.path.join(vault, c["note"])
        text = open(p, encoding="utf-8").read()
        new, _ = with_afterwards(text, [source_change_line(c)])
        if new != text and not dry_run:
            atomic_write(p, new)
    return found


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
    titles = release_mod().facts_tickets(s.get("runtime"), keys)   # each ticket by its title, never a bare key
    for w in watched:
        n = {"note": w["note"], "title": w["props"].get("title") or w["note"], "waits_on": None,
             "parked": f"{w['since'].isoformat()} 00:00", "wake": " ".join(w["keys"] + w["links"])}
        lines = afterwards_lines(B.parked_row(n, jira_rows, threads, me, now)["woke"], jira_base, titles)
        p = os.path.join(vault, w["note"])
        text = open(p, encoding="utf-8").read()
        new_text, _ = with_afterwards(text, lines)
        if new_text != text:                               # a note that gained nothing is not touched: no new mtime
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
    p = sub.add_parser("answer", help="one letter on today's ask N (`2 B` from Slack or a session), resolved as a tick on today.md is; dry run unless --apply")
    p.add_argument("slot", type=int); p.add_argument("letter", choices=list("ABCabc"))
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_answer)
    p = sub.add_parser("marks", help="finish the to-read notes whose done or drop box is ticked (no session)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_marks)
    p = sub.add_parser("finish", help="on the owner's word: a note done where it is, kept (drop or done)")
    p.add_argument("path", help="the note's path in the vault, e.g. reference/2026-11-05-review-jira-four-week.md")
    p.add_argument("--to", choices=("drop", "archive", "delete"), default="drop", help="delete: the older name of drop; nothing is deleted")
    p.set_defaults(func=cmd_finish)
    p = sub.add_parser("note", help="a note's life: claim, release, progress TEXT, built TEXT, move --to building|parked|done|live|drop")
    p.add_argument("act", choices=("claim", "release", "progress", "built", "move"))
    p.add_argument("path", help="the note's path in the vault, e.g. projects/mh-3983-csc-over-mqtt/2026-11-10-plan-mh-3987-app-through-gateway.md")
    p.add_argument("text", nargs="*", help="progress or built: the line to record")
    p.add_argument("--to", choices=("building", "parked", "done", "live", "drop", "in-progress", "archive", "to-read", "readings", "delete"),
                   help="the note's new state, where it is: building, parked, done, live, drop (layout 4's folder words read as these)")
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
    p = sub.add_parser("tidy", help="retired with layout 5 (a done note stays where its thing lives); see migrate")
    p.add_argument("--apply", action="store_true", help="move them; without it, list the moves and what holds any back")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_tidy)
    p = sub.add_parser("migrate", help="the one pass to layout 5, things and angles (ADR 0015): every move, rename, link "
                                       "rewrite and alias; a dry run unless --apply")
    p.add_argument("--apply", action="store_true", help="carry it out under the vault lock; without it, list it")
    p.add_argument("--slug", action="append", metavar="KEY=WORDS", help="name a project page by hand: MH-3983=csc-over-mqtt")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_migrate)
    p = sub.add_parser("questions", help="the open team questions: each one record, closed by its outcome or his word, "
                                         "never by age (ADR 0016); a dry run unless --apply")
    p.add_argument("--seed", nargs="+", metavar="NOTE", help="meeting notes outside the vault to read too (a backup's copy)")
    p.add_argument("--word", nargs=3, action="append", metavar=("ID", "SUBJECT", "SENTENCE"),
                   help="a question's line in its own words: a subject and one whole sentence of at most 25 words")
    p.add_argument("--words", metavar="FILE", help='the same for many: a JSON file {"q-xxxxxx": ["subject", "sentence"]}')
    p.add_argument("--apply", action="store_true", help="write the records")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_questions)
    p = sub.add_parser("rename", help="OLD NEW: rename a note in one step (alias, links, log, records); --records brings "
                                      "questions.json and the manifest to renames already made; a dry run unless --apply")
    p.add_argument("paths", nargs="*", metavar="OLD NEW", help="the note's path and its new path in the vault")
    p.add_argument("--records", action="store_true", help="the records only, for renames already made")
    p.add_argument("--apply", action="store_true", help="write them, under the vault lock")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_rename)
    p = sub.add_parser("restore", help="bring back a note the owner deleted in the vault")
    p.add_argument("path", help="the note's path in the vault, as the deletion log lists it")
    p.set_defaults(func=cmd_restore)
    a = ap.parse_args()
    if a.cmd in WRITERS:                                   # every writer of the vault takes the same lock as the sync
        hold = vault_lock()                                # noqa: F841  (held until the process exits)
    a.func(a)


if __name__ == "__main__":
    main()
