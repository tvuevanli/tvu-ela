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
    vault.py finish <path> [--to delete|archive|learn]   on his word: finish with a note as he would in Obsidian
    vault.py setup                   apply the Obsidian settings kept in obsidian/ (after a reset or on a new machine)

Layout, by what the owner does with a note (ela ADR 0010). Names are lowercase with hyphens and no spaces, taken
from the source's file name, never from its heading, so editing a title renames nothing; a dated name starts with
its date, so a folder sorts by time. Folders carry no numbers: Home and the bookmarks are the way in.
    home.md, board.md                           the entry point; the board's debt, one living page
    constraints.md                              the standing constraints, each pin read on its lane
    lanes.md                                    the lanes, what each carries that the next does not, two weeks of moves
    ela/review/<date>-reader.md                 the evening reader's verdict on each item of that morning's page, 30 days
    days/<year>/<date>-brief.md                 the morning page, kept, with -changes (what changed); -learned for 14 days
    to-read/<date>-<slug>.md                    reviews and verifications to read; deleted when read; a verification
    to-read/<date>-verify-<key>.md              leaves once its record is on the Jira ticket, or a pass after 14 days
    to-read/<date>-<slug>.md                    also a decision or plan from elak while it waits for his ruling
    in-progress/<name>.md                       a note he agreed to, while ela builds it and until he accepts it
    parked/<name>.md                            a note that waits on others, with who and what brings it back
    to-learn/, archive/                         where he drags a note: to distil it, or to keep it
    library/                                    topic pages (the vault is their source), the index, the sources
    ela/                                        about this vault, how ela works and runs, the table view, and
    ela/attachments/verify/<year-month>/<record>/   each verification record copied whole, hidden in the explorer

The reading gate. The vault is how ela reports to the owner, so a note over its reading budget, mostly code, or
carrying machine paths is still written, under a warning that names the problem, and Home lists it for 30 days
as a rewrite ela owes. Nothing readable is withheld; nothing unreadable passes unmarked.

Safety. A missing or unreadable source, or the notes as a whole shrinking by more than half since the last sync
(counted from ten notes up), stops the sync before anything is written (--force overrides after a deliberate removal).
The count is the vault's total, not each folder's as ADR 0008 first described: to-read empties by design as he reads.
In archive/ and to-learn/ ela never rewrites a note's text; it keeps their front matter's status current. Removal is limited to files
this script recorded in its manifest. Writes are atomic and a lock serialises concurrent syncs.

Exit codes: 0 ok · 2 usage or site · 3 a source could not be read or shrank (nothing written).
"""
import argparse, datetime, fcntl, glob, json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
JIRA = os.path.join(HERE, "..", "jira", "jira.py")
PROMOTE = os.path.join(HERE, "..", "promote", "promote.py")
SITE = os.path.expanduser("~/.claude/ela/site.json")
MANIFEST = ".ela-sync.json"
DAYS_KEPT, HELD_LISTED_DAYS, NEW_DAYS, MASS_DELETE, UNREAD_DAYS = 14, 30, 7, 8, 30
READER_DAYS = 30                                    # a reader page is evidence for the review of ela itself, then expires
CONSTRAINTS_FRESH = 1800    # seconds a read of the pins stands; each read asks the lane hosts, and the sync runs every minute
LAYOUT = 3                  # the manifest records it; a sync across a change of layout guards the total, not each folder
DAYS, TO_READ, LIBRARY, ELA, ARCHIVE, TO_LEARN = "days", "to-read", "library", "ela", "archive", "to-learn"
IN_PROGRESS = "in-progress"   # a note he agreed to, while ela builds it and until he accepts the result
PARKED = "parked"             # a live note nobody in ela works on: it waits on others (a draft he sent out, an answer pending)
# status is ela's field and the folder says the lifecycle, so each lifecycle folder allows only its own values;
# the owner sets `next`, never status. A note elsewhere (a sprint, a library page) keeps the status its kind defines.
STATUS_BY_FOLDER = {
    TO_READ: ("proposed", "blocked"),                       # waits on his word; only he can unblock
    IN_PROGRESS: ("building", "built", "waiting", "blocked"),   # waiting: an unattended loop that cannot finish
    PARKED: ("parked",),
    ARCHIVE: ("closed",),                                   # the outcome is in `next`, not repeated here
}
STATUSES = tuple(dict.fromkeys(v for vs in STATUS_BY_FOLDER.values() for v in vs))
CLOSED_NEXT = {"accepted": "accept", "rejected": "reject", "not now": "not-now", "not-now": "not-now", "parked": "not-now",
               "confirmed": "confirm", "planned": "make-plan", "nudged": "nudge", "drafted": "draft-comment"}
# an archived note's old outcome status, as the move that made it; the runner names the move itself with --next
OWNER_FOLDERS = (TO_LEARN, ARCHIVE)   # where the owner drags a note to say what he wants; ela never rewrites their text
ATTACH = "ela/attachments"
DELETABLE = (DAYS, TO_READ)
KEEP_FOREVER = ("brief", "week", "changes")   # the morning pages are the record of what ela told the owner; the rest expires
PROPS = ("title", "aliases", "type", "date", "kind", "status", "result", "moves", "next")   # the whole vocabulary; no tags (ADR 0010)
MARKS = {"done": ARCHIVE, "learn": TO_LEARN, "drop": None}   # a ticked box in a to-read table row: archive, distil, delete
BUDGET = {"ticket": 700, "topic": 800, "guide": 1200, "board": 1000, "day": 1200, "review": 2500, "decision": 1200, "plan": 2500, "sprint": 800}
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
the library's topics, plans for your decision.

Start at [[home]]: what waits for your word, today's page, and what there is to read.

## Layout

| folder | holds | what you do |
|---|---|---|
| `home`, `board` | today, and the board's debt | look at them each morning |
| `constraints` | the standing constraints you confirmed: what each holds, whether its lane still keeps it, when it lifts | look when Home says one is over |
| `days/<year>/` | the morning pages and what changed the day before, kept; the evening learning draft, 14 days | look back |
| `to-read/` | reviews, verification results, and plans or decisions waiting for your ruling, newest first | read, then delete |
| `in-progress/` | what you agreed to, while ela builds it, until you accept it | accept or say what is missing |
| `parked/` | what waits on others, with who it waits on and what brings it back | resume or drop |
| `lanes` | the lanes, what each carries that the next does not, two weeks of moves | look before a promotion |
| `library/` | one summary page per topic, with links to the originals | look up |
| `ela/` | how ela works and runs, this page, the table view; attachments, hidden | rarely |
| `to-learn/` | what you want distilled into knowledge | drag a note in |
| `archive/` | what was acted on or you chose to keep; ela adds to it and keeps its status current, never its text | look back; ask ela to tidy it |

Folders are named for what you do with a note and carry no numbers: Home and the bookmarks are the way in, and
the file explorer is rarely needed.

## Names and properties

- Names are lowercase, words joined by hyphens, taken from the source file's name; a dated note starts with its
  date. The readable title is the note's first heading, and an alias, so the quick switcher (Ctrl+O) finds a
  note by its title.
- Properties are `title`, `aliases` and `type`, plus `date`, `kind` on a day page, `status`, and `result` on a
  verification (pass or fail); a page ela writes in place also carries `source: "vault"`. status is ela's, never
  yours to set, and follows the folder: to-read *proposed* (waits on your word) or *blocked* (only you can unblock);
  in-progress *building*, *built* (waits on your accept), *waiting* (a loop that cannot finish; Progress says why) or
  *blocked*; parked *parked*; archive *closed*, with the outcome in `next`. Home's *Waiting for your word* holds only
  what blocks something until you answer: a plan or decision proposed, a build to accept, something blocked, a failed
  verification, a verification plan, the evening's learnings. Reviews and ticket pages carry no status and stay in
  *To read*.
  They feed the tables and show at the top of each note: a status to read, and `next`, the move you choose. A
  hidden `moves` property names the note's set of moves, so the chooser lists only those.
- No tags: a keyword-guessed tag would be wrong often enough to cost trust. A note about one topic links to its
  library page, and that page's backlinks are the cross-cut.
- A ticket key is a link to Jira, one click in reading mode.

## Reading budgets

A note is written for a person: a title heading, within its budget (day page 1,200 words, review 2,500,
decision 1,200, plan 2,500, sprint 800), mostly prose, no machine paths. A note that misses is still here, under
a warning, and Home lists it for 30 days as a rewrite ela owes.

## Finishing with a note

| you want | do | ela does |
|---|---|---|
| what it says kept as knowledge | drag it into `to-learn/` | that evening's draft proposes the conclusion and where it goes (a library page, or ela's own knowledge); on your keep it is written and the note moves to `archive/` |
| to keep it, nothing more | drag it into `archive/` | nothing: it is never written again, and the copy, with its screenshots, is yours |
| it gone | delete it | nothing: its source stays in the reports and the backup |
| nothing yet | leave it | it stays, or ela moves it on (below) |

The same three moves are choices of the note's `next` field: `done` (archive), `learn` (to-learn) or `drop`
(delete), and within a minute the note goes there; no session.

Every note to read carries one field for its next move, **next**, at its top. The button beside it lists only
that note's choices, by kind: a plan *agree*, *park*, *not-now*, *reject*; a review *make-plan*; a verification *draft-comment*; all of
them *done*, *learn*, *drop*. A ticket page (one ticket read in depth) offers only *nudge*, *go-deep*, *seen* and *drop*;
a verification plan (a run waiting for your word on its goals) only *run*, *not-now* and *drop*; the evening's page of
what the day taught only *learn* (distilled that night) and *drop*. The note's **Next moves** section says what each does. Choose one, and it is done
within a minute; ela empties the field once it has acted, and a value that is not a move for the note runs nothing
and is pointed out under the title. An agreed note moves to `in-progress/`, ela writes each step under its Progress
heading, and when it is built the note offers *accept* or *not-done*. A plan lists each ruling it needs with ela's
proposed answer and no boxes: *agree* accepts them as proposed, and to differ on one you write an `ela:` line under
it. Beside that life (to-read → in-progress → archive) sits `parked/`: a plan, decision or review you *park* waits
on others, with who (`waits-on`) and what brings it back (`wake`); ela watches the wake each morning, and the note
offers *resume* or *drop*. You can also answer a note with `ela:` lines,
or continue it in any Claude session by naming its path; a session that claims a note keeps it, and records its
conclusions there.

To tell ela what you want of a note, or to answer what it waits for, write a line starting `ela:` into the note,
below its properties (the end is easiest: Ctrl+E, Ctrl+End, write, Ctrl+E), in your own words. Any note: a
rewrite keeps your lines. Two minutes after you stop typing, a session takes the lines up, and its answer appears
folded under the last of them. A place can be named ("write this to the KB", "into elak"); without one, ela
chooses between a library page here, its own knowledge in elak and the team's knowledge base (drafted, published
on your word).

Ask ela now and then to tidy the archive.

Do it on the desktop; the laptop only receives. A living page (Home, the board, the library, how ela runs) is
written again whatever happens to it. Finishing is never a verdict: deleting a decision does not revoke it; to
change one, tell ela. `ela vault restore <path>` brings back a generated note; a page ela writes in place comes
back from the nightly backup.

## What ela moves on by itself

What ela knows was acted on, it archives: a verification once its record is on the Jira ticket, a decision or plan
once you have ruled on it (what it settled is written into a living page, `ela/` or `library/`). What merely
expired, it removes: a passed verification nobody posted, after 14 days. A review you leave untouched for 30 days it
archives, so `to-read/` does not pile up. What waits for your word (a failed verification, a plan to rule on) stays
until you give it, and the morning page reminds you; only the evening draft expires, after 14 days.

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
- Bookmarks: Home, the board, the library, all notes as tables, how ela runs, this page.
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
properties:
  formula.note:
    displayName: Note
"""

WAITING = """      or:
        - 'status == "built"'
        - 'status == "proposed"'
        - 'result == "fail"'
        - 'status == "blocked"'
        - 'kind == "learned"'
"""

VIEWS = {
    "all-notes": """filters:
  and:
    - 'file.ext == "md"'
    - not:
        - file.inFolder("archive")
        - file.inFolder("to-learn")
        - file.inFolder("ela/moves")
    - 'type != "home"'
    - 'type != "readme"'
""" + FORMULAS + """views:
  - type: table
    name: Waiting for your word
    filters:
""" + WAITING + """    order: [date, formula.note, type, status, next]
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
    name: In progress
    filters:
      and:
        - file.inFolder("in-progress")
    order: [date, formula.note, status, progress, built, next, claimed]
    sort:
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
    if folder == LIBRARY:                                  # a topic page is reference, not a step in a life
        return None, None, None
    if folder not in STATUS_BY_FOLDER:
        return status, None, None
    if folder == ARCHIVE:
        return "closed", result, CLOSED_NEXT.get(s)
    if folder == PARKED:
        return "parked", result, None
    if folder == IN_PROGRESS:
        return s if s in STATUS_BY_FOLDER[IN_PROGRESS] else "building", result, None
    if result:
        return ("proposed" if result == "fail" else None), result, None
    return (s if s in STATUS_BY_FOLDER[TO_READ] else "proposed") if s else None, None, None


def settle_statuses(vault, dry_run=False):
    """Bring every note in a lifecycle folder to its folder's statuses, and take status off library pages, front
    matter only (archive included: the body stays his). Returns one line per fix."""
    fixes = []
    for folder in tuple(STATUS_BY_FOLDER) + (LIBRARY,):
        d = os.path.join(vault, folder)
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if not f.endswith(".md"):
                continue
            p = os.path.join(d, f)
            try:
                text = open(p, encoding="utf-8").read()
            except OSError:
                continue
            fl, body = split_front(text)
            if not fl:
                continue
            props = props_of(fl)
            st, result, nxt = settled_status(folder, props.get("status"), props.get("type"))
            want = {"status": st, "result": result or props.get("result") or None}
            if nxt and not props.get(NEXT):
                want[NEXT] = nxt
            if folder in (IN_PROGRESS, ARCHIVE):            # the set its status chooser lists
                want[MOVE_SET] = "closed" if folder == ARCHIVE else props.get(MOVE_SET) or "built"
            changed = {k: v for k, v in want.items() if (v or None) != (props.get(k) or None)}
            if not changed:
                continue
            fixes.append(f"{folder}/{f}: " + ", ".join(f"{k} {props.get(k) or '—'} → {v or '—'}" for k, v in changed.items()))
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
        # `status: proposed`); once decided, what it settled is written into a living page (ela/, library/) and the
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
    for f in sorted(os.listdir(rd)) if os.path.isdir(rd) else []:
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-(brief|learned|week|changes)\.md$", f)
        if not m or (m.group(2) not in KEEP_FOREVER and (today - datetime.date.fromisoformat(m.group(1))).days >= DAYS_KEPT):
            continue
        d = datetime.date.fromisoformat(m.group(1))
        fl, body = split_front(open(os.path.join(rd, f), encoding="utf-8").read())
        if m.group(2) == "brief":
            body = action_states(body, os.path.join(rd, f"{m.group(1)}-actions.json"))
        label = {"brief": "Morning brief", "learned": "What the day taught", "week": "The week", "changes": "What changed"}[m.group(2)]
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
    rv = os.path.join(reports, "review")
    for f in sorted(os.listdir(rv)) if os.path.isdir(rv) else []:   # the evening reader's verdicts on a morning page
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-reader\.md$", f)
        if not m or (today - datetime.date.fromisoformat(m.group(1))).days >= READER_DAYS:
            continue
        fl, body = split_front(open(os.path.join(rv, f), encoding="utf-8").read())
        notes.append(Note(f"{ELA}/review/{f}", f"The reader · {m.group(1)}", body, {"type": "reader", "date": m.group(1)}, fl,
                          src_rel=f"review/{f}"))
    # the library: one page per topic, written by ela from the sources it read, and an index; the source lists are an
    # appendix. Pointers and syntheses only: the originals stay where they live.
    lp = os.path.join(reports, "library", "library.md")
    if os.path.isfile(lp):
        fl, body = split_front(open(lp, encoding="utf-8").read())
        body = re.sub(r"^# Library\b", "# Library sources", body, count=1, flags=re.M)
        notes.append(Note(f"{LIBRARY}/sources.md", "Library sources", body, {"type": "library"}, fl, src_rel="library/library.md"))
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
            if m:
                title = re.sub(r"\s*[—–,-]?\s*[（(]?" + m.group(1) + r"[)）]?(\s*[（(][^)）]{1,6}[)）])?", "", title).strip() or title
                path = f"{TO_READ}/{m.group(1)}-{rest}.md"
            else:
                path = f"{TO_READ}/{rest}.md"
            # a deep reading of one ticket (`ela-runner deep`) is a ticket page: real status, timeline, next
            kind = "ticket" if re.match(r"^\d{4}-\d{2}-\d{2}-deep-", base) else "review"
            notes.append(Note(path, title, body, {"type": kind, "date": m.group(1) if m else None}, fl,
                              src_rel=f"{sub + '/' if sub else ''}{f}"))
    return notes


APPLY_BOX = re.compile(r"^([ \t]*[-*][ \t]+)\[[ xX]\]([ \t]+apply[ \t]+(\d+)\b.*?)[ \t]*$", re.M)


def action_states(body, actions_path):
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
            return f"{lead}[x]{rest} · applied {a['applied'][11:16]}"
        o = a.get("by_owner")
        if not o:
            return f"{lead}[ ]{rest}\n{lead}[ ] I handled it myself — not apply {n}"
        how = f"you commented in Jira {o['at'][11:16]}" if o.get("comment") else f"marked {o['at'][11:16]}"
        return f"{lead}[ ]{rest}\n{lead}[x] I handled it myself — not apply {n} · {how}"
    return APPLY_BOX.sub(one, body)


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
    """One note per verification plan waiting for the owner's word (`ela verify-plan`, written when no one is at the
    terminal to confirm the plan): its goals table, the lane and version, how long. A result for the same ticket on or
    after the plan's date replaces it."""
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
        notes.append(Note(f"{TO_READ}/{m.group(1)}-verify-plan-{m.group(2).lower()}.md", f"{m.group(2)} · verify plan", body,
                          {"type": "verify-plan", "date": m.group(1), "status": "proposed"}, [], src_rel=f"verify/plans/{f}"))
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


def reading_gate(n):
    kind = n.props.get("type")
    if kind not in BUDGET:
        return []
    problems = []
    if not h1(n.body):
        problems.append("no title heading")
    units = reading_units(n.body)
    if units > BUDGET[kind] * TOLERANCE:
        problems.append(f"{units:,} words, budget {BUDGET[kind]:,}")
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


# ── home ──────────────────────────────────────────────────────────────────────────────────────────────

def link(n):
    return f"[[{n.path[:-3]}|{n.title}]]"


def home(today, now, notes, saw=None):
    """Home, short: what waits for his word, today's "Needs you" (the whole page when it has no such section), a live
    table of what there is to read (a Bases block, so a deleted note leaves it at once), and what ela owes."""
    def newest(kind):
        return sorted((n for n in notes if n.props.get("type") == "day" and n.props.get("kind") == kind),
                      key=lambda n: n.props["date"], reverse=True)
    brief = next(iter(newest("brief")), None)
    changes = next(iter(newest("changes")), None)
    iso = today.isoformat()
    L = [f"# {today:%a %Y-%m-%d}", ""]
    board = next((n for n in notes if n.props.get("type") == "board"), None)
    wait = []
    waiting = re.search(r"^## (?:Proposed closes assigned to you|Waiting for your close) \((\d+)\)", board.body, re.M) if board else None
    if waiting and int(waiting.group(1)):
        wait.append(f"{link(board)}: {waiting.group(1)} proposed closes assigned to you")
    # everything that needs his word, from typed state: a failed or blocked verification, a plan proposed to him, the
    # evening draft (a live view, so it leaves when he deletes the note), and proposed closes from the board
    # the same rules as the views, so an empty table is a sentence instead
    waiting = [n for n in notes if note_status(n) in ("proposed", "blocked", "built") or n.props.get("result") == "fail"
               or n.props.get("kind") == "learned"]
    L += ["## Waiting for your word", ""] + [f"- {w}" for w in wait] + ([""] if wait else [])
    if waiting:
        L += [f"![[{ELA}/all-notes.base#Waiting for your word]]", "",
              "*Choose a move in a row's next field and ela takes it up within a minute; to differ on one point, write a "
              "line `ela: …` in the note, taken up two minutes after you stop typing, with the answer under it.*", ""]
    elif not wait:
        L += ["Nothing waits for your word.", ""]
    if brief and brief.props["date"] == iso:
        head = re.split(r"^## ", re.sub(r"^#[ \t]+.*$", "", brief.body, count=1, flags=re.M), maxsplit=1, flags=re.M)[0].strip()
        # the jump to the page is the section's first line, under a plain heading
        L += ["## Today", "", f"[[{brief.path[:-3]}|→ Open the morning page]]", ""]
        if changes and changes.props["date"] == iso:     # the day's changes in code, lanes and QA, beside the brief
            L += [f"[[{changes.path[:-3]}|→ What changed yesterday]]", ""]
        L += [head, ""] if head else []
        if re.search(r"^## Needs you[ \t]*$", brief.body, re.M):
            # the day's meetings first (`## <name> at HH:MM`, from <elak>/blueprint/meetings.yaml), each the meeting's agenda
            for sec in re.findall(r"^## (.+ at \d{2}:\d{2})[ \t]*$", brief.body, re.M):
                L += [f"![[{brief.path[:-3]}#{sec.replace(':', ' ')}]]", ""]   # Obsidian links a heading's colon as a space
            L += [f"![[{brief.path[:-3]}#Needs you]]", ""]
            # the lanes table: the standing lanes page when there is one (rewritten each pass), else the brief's copy
            lanes = next((n for n in notes if n.props.get("type") == "lanes"), None)
            if lanes:
                L += ["![[lanes#The lanes this morning]]", "[[lanes|→ Differences and two weeks of moves]]", ""]
            elif re.search(r"^## The lanes this morning[ \t]*$", brief.body, re.M):
                L += [f"![[{brief.path[:-3]}#The lanes this morning]]", ""]
            L += [f"*The rest of the page (yesterday, new tickets, the Jira lanes, the backlog): {link(brief)}.*", ""]
        else:
            L += [f"![[{brief.path[:-3]}]]", ""]
    else:
        L += ["## Today", "", "No morning page yet today" + (f"; the latest is {link(brief)}." if brief else "."), ""]
        if changes and changes.props["date"] == iso:
            L += [f"[[{changes.path[:-3]}|→ What changed yesterday]]", ""]
    sprint = next((n for n in sorted(notes, key=lambda n: n.props.get("date") or "", reverse=True)
                   if n.props.get("type") == "sprint" and note_status(n) == "active"), None)
    cons = next((n for n in notes if n.props.get("type") == "constraints"), None)
    held = getattr(cons, "counts", None) or {}
    cline = (f"[[{cons.path[:-3]}|{held['active']} standing constraint{'s' if held['active'] != 1 else ''}]] · {held['over']} over"
             + (f" · {held['expired']} expired" if held["expired"] else "")) if held.get("active") or held.get("expired") else ""
    # today's page states the sprint in one line ("Sprint · day N of M · …"); Home shows that line, linked to the page's
    # table, and the bare link to the sprint note only when the page has not said it
    said = re.search(r"^## Sprint[ \t]*\n+(Sprint · [^\n]+)", brief.body, re.M) if brief and brief.props["date"] == iso else None
    if said:
        L += ["## Sprint", "", f"[[{brief.path[:-3]}#Sprint|{said.group(1).strip()}]]", ""] + ([cline, ""] if cline else [])
    elif sprint:                                           # the two-week commitment, one click from Home
        L += ["## Sprint", "", f"{link(sprint)}", ""] + ([cline, ""] if cline else [])
    elif cline:                                            # what holds a lane back, under the sprint it constrains
        L += ["## Sprint", "", "No active sprint.", "", cline, ""]
    building = [n for n in notes if top(n.path) == IN_PROGRESS]
    if building:
        L += ["## In progress", "", f"![[{ELA}/all-notes.base#In progress]]", ""]
    if any(top(n.path) == PARKED for n in notes):        # a base cannot hide an empty view, so the block goes instead
        L += ["## Parked", "", f"![[{ELA}/all-notes.base#Parked]]", ""]
    reading = [n for n in notes if top(n.path) == TO_READ and note_status(n) not in ("proposed", "blocked", "built")
               and n.props.get("result") != "fail"]
    L += ["## To read", "", f"![[{ELA}/all-notes.base#To read]]" if reading else "Nothing to read.", ""]
    if reading:                                            # the table shows five; say what is beyond and what is new
        # new against the notes to read when he last opened Home; before Home was ever seen open, against today
        new = sum(1 for n in reading if (n.path not in saw if saw is not None else n.props.get("date") == iso))
        said_new = (f"{new} new since you last opened Home" if saw is not None else f"{new} new today") if new else ""
        more = f"+{len(reading) - 5} more in [[{ELA}/all-notes.base|all notes]]" if len(reading) > 5 else ""
        L += ["*" + " · ".join(x for x in (said_new, more) if x) + "*", ""] if new or more else []
    owed_since = (today - datetime.timedelta(days=HELD_LISTED_DAYS)).isoformat()
    owed = [n for n in notes if n.held and (n.props.get("date") or iso) >= owed_since]
    if owed:
        L += ["> [!warning]- ela owes a shorter version of " + str(len(owed))] + [f"> - {link(n)}: {'; '.join(n.held)}" for n in owed] + [""]
    return "\n".join(L)


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


def meta_line(n, topics):
    """One muted line under a record's or a review's title: what it is, when, its status, and the library topic it
    is about when its source names one (`area:` in its front matter). Properties are hidden while reading."""
    if n.props.get("type") not in ("review", "decision", "plan", "sprint"):
        return n.body
    area = next((re.match(r"^area:\s*['\"]?([\w-]+)", l).group(1) for l in n.front_lines if re.match(r"^area:\s*['\"]?[\w-]+", l)), None)
    t = topics.get(area)
    st = note_status(n)
    bits = [n.props["type"], n.props.get("date"), st, f"about {link(t)}" if t else None]
    line = "*" + " · ".join(b for b in bits if b) + "*"
    m = re.search(r"^#[ \t]+.*$", n.body, re.M)
    return n.body[:m.end()] + "\n\n" + line + n.body[m.end():] if m else n.body


# ── the sync ──────────────────────────────────────────────────────────────────────────────────────────

def native_notes(vault):
    """Notes whose source is the vault itself (front matter `source: "vault"`): the owner's documents ela writes in
    place (the overview, the workflow, plans for his decision, the library's topic pages). Read, never written."""
    out = []
    for top_, dirs, fs in os.walk(vault):
        dirs[:] = [d for d in dirs if not d.startswith(".") and os.path.relpath(os.path.join(top_, d), vault).replace(os.sep, "/") not in (ATTACH,) + OWNER_FOLDERS]
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
                m = re.match(r"^(type|date|kind|status|title):\s*['\"]?([^'\"]*)['\"]?\s*$", l)
                if m:
                    props[m.group(1)] = m.group(2)
            rel = os.path.relpath(p, vault).replace(os.sep, "/")
            out.append(Note(rel, props.pop("title", None) or h1(body) or f[:-3], body, props, fl))
    return out


def vocabulary_note(elak):
    """The Jira vocabulary ela enforces (<elak>/map/jira-labels.yaml), rendered for the owner: one section per
    namespace, headed by its prefix so a design page can embed one (`![[library/jira-vocabulary#proto]]`). The data
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
         f"{d.get('open', '?')} open); {d.get('status') or 'in force'}. The rules: [[{LIBRARY}/jira-labels-and-components|Labels and components]].*", ""]
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
    return Note(f"{LIBRARY}/jira-vocabulary.md", "Jira vocabulary for MH", "\n".join(L), {"type": "vocabulary", "date": d.get("read")},
                src_rel="elak:map/jira-labels.yaml")


def library_index(topics):
    """The library's index: one row per topic page (native to the vault), its first sentence, as of when."""
    L = ["# Library", "", f"*What ela knows, by topic: each page is a summary with links to the originals. "
         f"The [[{LIBRARY}/sources|full list of sources]] is the appendix.*", "", "| topic | where it stands |", "|---|---|"]
    for n in sorted(topics, key=lambda n: n.title):
        para = next((p for p in re.split(r"\n\s*\n", re.sub(r"^#.*$", "", n.body, count=1, flags=re.M))
                     if p.strip() and not p.strip().startswith(("*", "|", "#", "-"))), "")
        first = re.split(r"(?<=[.!?])\s", " ".join(para.split()), maxsplit=1)[0]
        if len(first) > 200:
            first = first[:200].rsplit(" ", 1)[0].rstrip(",;:") + " …"
        L.append(f"| [[{n.path[:-3]}|{n.title}]] | {first.replace('|', '/')} |")
    return Note(f"{LIBRARY}/library.md", "Library", "\n".join(L) + "\n", {"type": "library"})


def plan(s, env, today, now, removed=frozenset(), removed_src=frozenset(), saw=None):
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
    topics = [n for n in native if n.props.get("type") == "topic"]
    by_topic = {os.path.basename(n.path)[:-3]: n for n in topics}
    if topics:
        notes.append(library_index(topics))
    vocab = vocabulary_note(s.get("elak"))
    if vocab:
        notes.append(vocab)
    taken = set()
    for n in notes:                                        # one note per path; a namesake gets -2, never an overwrite
        stem, i = n.path[:-3], 2
        while n.path.lower() in taken:
            n.path = f"{stem}-{i}.md"; i += 1
        taken.add(n.path.lower())
    jira_base = ""
    if env and os.path.isfile(env):
        jira_base = next((l.split("=", 1)[1].strip().rstrip("/") for l in open(env) if l.startswith("JIRA_BASE_URL=")), "")
    projects = project_keys(env, s.get("runtime")) if jira_base else set()
    warnings = native_warn + ([] if jira_base and projects else ["ticket keys are not linked: no Jira base URL or project list"])
    reps = {n.src_rel: n for n in notes if n.src_rel and n.props.get("type") in ("day", "review", "reader")}
    linker = Linker({n.src_rel: n for n in enotes}, titles, jira_base, projects, reports, reps)
    planned = {}
    for n in notes:
        if top(n.path) in tuple(STATUS_BY_FOLDER) + (LIBRARY,):
            st, result, _ = settled_status(top(n.path), note_status(n), n.props.get("type"))
            n.props.update(status=st, result=n.props.get("result") or result)
            n.front_lines = [l for l in n.front_lines if not l.startswith("status:")]   # the source's own word is settled
        learned = n.props.get("kind") == "learned"         # a day page that waits for his word, like a note to read
        if top(n.path) == TO_READ or learned:
            n.props.update({NEXT: "", MOVE_SET: move_set("learned" if learned else n.props.get("type"))})
        n.held = reading_gate(n)
        body = linker(unwrap(callouts(meta_line(Note(n.path, n.title, tidy_title(n.body), n.props, n.front_lines), by_topic))))
        if top(n.path) == TO_READ or learned:
            body = with_moves(body, n.path, "learned" if learned else n.props.get("type"))
        planned[n.path] = redact(front(n.front_lines, dict(n.props, title=n.title)) + (with_warning(body, n.held) if n.held else body))
    planned["home.md"] = redact(front([], {"type": "home", "date": today.isoformat()}) + linker(home(today, now, notes + native, saw)))
    planned[f"{ELA}/about-this-vault.md"] = unwrap(README)
    for name, text in VIEWS.items():
        planned[f"{ELA}/{name}.base"] = text
    return planned, files, notes, warnings, {n.path for n in native}


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
    """{file name, lowercased: folder} under to-learn/ and archive/: a generated note that left its folder and
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
    """Log each note the owner finished with: dragged into to-learn/ (distil it), into archive/ (keep it, nothing to
    do) or deleted (drop it). Each way he has read it, so it stays out of the generated folders. None is criticism or
    a verdict on a decision; feedback comes as a message (Slack `feedback`, a session)."""
    archived = archived or {}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for r in rels:
            title = sentence(re.sub(r"^\d{4}-\d{2}-\d{2}-", "", os.path.basename(r)[:-3]).replace("-", " "))
            row = {"at": now.isoformat(timespec="seconds"), "path": r, "title": title,
                   "fate": {TO_LEARN: "to-learn", ARCHIVE: "archived", IN_PROGRESS: "in-progress", PARKED: "parked",
                            TO_READ: "to-read"}.get(archived.get(os.path.basename(r).lower()), "deleted"), "by": by}
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


TICKED = re.compile(r"^[ \t]*[-*][ \t]+\[[xX]\][ \t]+(\S.*?)[ \t]*$", re.M)   # a choice he ticked in a note: a click, not typing
# horizontal whitespace only: an empty `ela:` property must not reach across the line break to the next line
GUIDE = re.compile(r"^[ \t]*(?:[-*>][ \t]*)*ela[ \t]*[:：][ \t]*(\S.*?)[ \t]*$", re.I | re.M)
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


def answer_block(row):
    """One answer as a folded callout. A line of the answer that reads as an instruction (`ela: …`) is defused, so
    the answer is never taken for a new ask."""
    head = "ela answered" if row.get("status") == "done" else "ela could not finish"
    body = [re.sub(r"^(\s*(?:[-*>]\s*)*)ela(\s*[:：])", r"\1ela —", l) for l in (row.get("answer") or "").strip().splitlines()]
    lines = [f"> [!note]- {head} · {(row.get('at') or '')[11:16]} · job {row.get('job')}"] + [f"> {l}" if l.strip() else ">" for l in body]
    return "\n".join(lines)


def with_answers(text, rel, answers):
    """Each answer placed under the last of the `ela:` lines it answers, once (the job id marks it)."""
    for row in (r for r in answers if r.get("note") == rel and r.get("job") and r["job"] not in text):
        says = {x.strip() for x in row.get("lines") or []}
        hits = [m for m in GUIDE.finditer(text) if m.group(1).strip().strip('"').strip("'") in says]
        if hits:
            at = hits[-1].end()
            text = text[:at] + "\n\n" + answer_block(row) + "\n" + text[at:]
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
MOVE_PROPS = {                   # by kind, beyond done, learn and drop, which every note to read carries
    "plan": ["agree", "park", "not-now", "reject"],
    "sprint": ["agree", "not-now"],
    "review": ["make-plan", "park"],
    "verify": ["draft-comment"],
    "decision": ["confirm", "park"],
    "built": ["accept", "not-done"],
    "ticket": ["nudge", "go-deep", "seen", "drop"],   # a ticket's moves only: "done" would read as the ticket's Jira Done
    "parked": ["resume", "drop"],          # a parked note's only moves: it comes back, or it ends
    "verify-plan": ["run", "not-now", "drop"],   # the plan gate of a run nobody was at the terminal for
    "learned": ["learn", "drop"],          # the evening's draft of what the day taught: distil it, or let it go
}
OUT_OF_TO_READ = ("built", "parked")       # kinds whose moves are their own, without done, learn and drop
ALL_MOVE_PROPS = ("agree", "park", "not-now", "reject", "make-plan", "draft-comment", "confirm", "accept", "not-done", "nudge", "go-deep",
                  "seen", "resume", "run")
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
    "run": "ela runs the verification as planned; its result replaces this note",
    "done": "archived, nothing more", "learn": "distilled into knowledge that evening", "drop": "deleted",
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
    """The checkbox properties a note carries for its next moves: its kind's own, then done, learn and drop."""
    if kind in ("ticket", "verify-plan", "learned"):   # their moves only: "done" would read as the ticket's or the run's
        return list(MOVE_PROPS[kind])
    return list(MOVE_PROPS.get(kind) or []) + (list(MARKS) if in_to_read else [])


def move_set(kind, in_to_read=True):
    """The name of the moves a note offers: its kind's when it has its own, else the plain to-read three."""
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
    folder_of = {"built": IN_PROGRESS, "parked": PARKED, "closed": ARCHIVE}

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
    if st and st != planned.get("status") and st in STATUS_BY_FOLDER.get(top(rel), ()):
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
    if to == "delete":
        return finish(vault, reports, rel, "delete") or None
    folder = {"in-progress": IN_PROGRESS, "archive": ARCHIVE, "to-read": TO_READ, "parked": PARKED}[to]
    text = open(p, encoding="utf-8").read()
    kind = props_of(split_front(text)[0]).get("type")
    text = clear_warn(PROP_RE.sub("", text))
    st, result, nxt = settled_status(folder, status, kind)
    nxt = next_ or nxt                                     # the move that ended it, as the runner names it
    if folder == PARKED:
        old = dict(m.groups() for m in (re.match(r"^([\w-]+):\s*['\"]?(.*?)['\"]?\s*$", l) for l in split_front(text)[0]) if m)
        text = set_front(text, source="vault", status=st, claimed=None, **{
            "waits-on": waits_on or old.get("waits-on") or "", "wake": wake or old.get("wake") or "",
            "parked": old.get("parked") if top(rel) == PARKED and old.get("parked") else datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            MOVE_SET: "parked", NEXT: ""})
    else:
        text = set_front(text, source="vault", status=st, claimed=None, **{"waits-on": None, "wake": None, "parked": None})
        if folder == ARCHIVE:                              # the outcome stays in next; status says only that it is closed
            text = set_front(text, **{MOVE_SET: "closed", NEXT: nxt or ""})
        elif folder == IN_PROGRESS:
            text = set_front(text, **{MOVE_SET: "built", NEXT: ""})
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
        print(f"{rel} → {move_note(vault, reports, rel, a.to, a.status, a.waits_on, a.wake, a.next) or 'deleted'}")


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
    guidance-handled.jsonl are left out unless --all), and every to-learn note, guided or not."""
    import hashlib
    s = json.load(open(SITE))
    vault, reports = s["vault"], s.get("reports") or ""
    try:
        done = {json.loads(l).get("id") for l in open(os.path.join(reports, "ela", "guidance-handled.jsonl"), encoding="utf-8")}
    except (OSError, ValueError):
        done = set()
    lines, notes = [], []
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
                if top(rel) == TO_LEARN:
                    notes.append({"note": rel, "title": h1(split_front(text)[1]) or f[:-3]})
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
    r = {"guidance": lines, "to_learn": notes,
         "handled_log": os.path.join(reports, "ela", "guidance-handled.jsonl")}
    if a.json:
        print(json.dumps(r, ensure_ascii=False)); return
    for g in lines:
        print(f"{g['id']}  {g['note']}: {g['says']}")
    print(f"{len(lines)} instructions; {len(notes)} notes in to-learn")


def apply_marks(vault, reports, dry_run=False):
    """The move he chose in a note's `next` field. done, learn and drop finish the note here, as if he had dragged or
    deleted it; every other move is reported for the runner, which acts and empties the field. A value that is not a
    move for that note runs nothing, and the note says so. Returns [(path, move)]."""
    out = []
    found = [(folder, f"{folder}/{f}") for folder in (TO_READ, IN_PROGRESS, PARKED)
             for f in (sorted(os.listdir(os.path.join(vault, folder))) if os.path.isdir(os.path.join(vault, folder)) else [])]
    found += [(DAYS, os.path.relpath(x, vault).replace(os.sep, "/")) for x in sorted(glob.glob(os.path.join(vault, DAYS, "*", "*-learned.md")))]
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
        kind = "parked" if folder == PARKED else "learned" if folder == DAYS else "built" if props.get("status") == "built" else props.get("type")
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
            finish(vault, reports, rel, {"done": "archive", "seen": "archive", "learn": "learn", "drop": "delete"}[move], move)
        elif move == "resume" and not dry_run:      # a script move: the note's next decision is his again
            move_note(vault, reports, rel, "to-read", "proposed")
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


def finish(vault, reports, rel, to, move=None):
    p = os.path.realpath(os.path.join(vault, rel))
    try:
        src = (json.load(open(os.path.join(vault, MANIFEST))).get("sources") or {}).get(rel)
    except (OSError, ValueError):
        src = None
    folder = {"archive": ARCHIVE, "learn": TO_LEARN}.get(to)
    if folder:
        os.makedirs(os.path.join(vault, folder), exist_ok=True)
        dst = free_path(os.path.join(vault, folder), os.path.basename(rel))
        os.replace(p, dst)
        text = clear_warn(PROP_RE.sub("", open(dst, encoding="utf-8").read()))   # the boxes belong to to-read
        if folder == ARCHIVE:                              # closed, and the move that closed it kept in next
            text = set_front(text, status="closed", **{MOVE_SET: "closed", NEXT: move or "done"})
        open(dst, "w", encoding="utf-8").write(text)
    else:
        os.remove(p)
    record_removed(os.path.join(reports, "ela", "vault-removed.jsonl"), [rel], {rel: src} if src else {},
                   datetime.datetime.now(), {os.path.basename(rel).lower(): folder} if folder else {}, by="owner")
    return folder


def cmd_finish(a):
    """Finish with a note on the owner's word (an `ela:` line asking it): delete it, or move it into archive/ or
    to-learn/, and log it as his, exactly as if he had done it in Obsidian. Only a note in days/ or to-read/; a living
    page is not his to finish, and his own folders are already his."""
    s = json.load(open(SITE))
    vault = s["vault"]
    rel = a.path.replace("\\", "/").lstrip("/")
    p = os.path.realpath(os.path.join(vault, rel))
    if not p.startswith(os.path.realpath(vault) + os.sep) or top(rel) not in DELETABLE or not rel.endswith(".md") or not os.path.isfile(p):
        print(f"not a note in days/ or to-read/: {a.path}", file=sys.stderr); sys.exit(2)
    folder = finish(vault, s.get("reports") or "", rel, a.to)
    print(f"{rel}: {'moved to ' + folder + '/' if folder else 'deleted'}; logged as the owner's")


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


WRITERS = ("sync", "marks", "finish", "note", "restore", "setup")   # guidance only reads


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
    # "new since you last opened Home": the notes to read are remembered at each opening of Home (a sync that finds it
    # open after one that did not); while it is open, new counts against the opening before, so the count he sees
    # stays put until he comes back
    is_open = home_open(vault)
    opening = is_open and not old_home.get("open")
    # an older vault.py wrote a count here, not a list: such a value reads as no baseline, and the next write is a list
    saw = old_home.get("saw") if isinstance(old_home.get("saw"), list) else None
    before = saw if opening else old_home.get("before") if isinstance(old_home.get("before"), list) else None
    baseline = before if is_open else saw
    try:
        planned, files, notes, warnings, native_paths = plan(s, env, today, now, removed | set(newly),
                                                              removed_src | {old_src[r] for r in newly if old_src.get(r)},
                                                              set(baseline) if baseline is not None else None)
    except SourceError as e:
        print(f"vault: not synced — {e}", file=sys.stderr); sys.exit(3)
    if newly and not a.dry_run:
        record_removed(removed_path, newly, old_src, now, archived)
    removed |= set(newly)
    # a review left untouched in to-read for 30 days is archived by ela: kept, out of the way, never a decision taken
    # for him (what waits for his word stays until he gives it)
    # counted from the day the note entered the vault (the manifest's `seen`), not from the day its source was written
    seen = {r: old_seen.get(r) or today.isoformat() for r in planned if r.endswith(".md")}
    unread = [n for n in notes if top(n.path) == TO_READ and n.props.get("type") == "review" and n.path in seen
              and (today - datetime.date.fromisoformat(seen[n.path])).days >= UNREAD_DAYS and os.path.exists(os.path.join(vault, n.path))]
    if unread and not a.dry_run:
        os.makedirs(os.path.join(vault, ARCHIVE), exist_ok=True)
        for n in unread:
            os.replace(os.path.join(vault, n.path), free_path(os.path.join(vault, ARCHIVE), os.path.basename(n.path)))
            planned.pop(n.path, None)
        record_removed(removed_path, [n.path for n in unread], {n.path: n.src_rel for n in unread}, now,
                       {os.path.basename(n.path).lower(): ARCHIVE for n in unread}, by="ela")
    now_files = set(planned) | {dst for src, dst in files}
    if not a.force:
        # the notes as a whole halving is a failure until shown to be a removal (a source that read empty, a broken
        # path); the owner's own finishing and the archive are already out of the count, and single folders shrink by
        # design (to-read empties as he reads)
        native_lower = {p.lower() for p in native_paths}
        before = sum(1 for r in old if r.endswith(".md") and r not in removed and r.lower() not in native_lower)
        after = sum(1 for r in planned if r.endswith(".md"))
        if before >= 10 and after < before / 2:
            print(f"vault: not synced — the notes would shrink from {before} to {after}; --force if that is intended", file=sys.stderr)
            sys.exit(3)
    listing = {}

    def names_in(d):
        if d not in listing:
            listing[d] = set(os.listdir(d)) if os.path.isdir(d) else set()
        return listing[d]
    wrote, same = [], 0
    answers = load_answers(s.get("reports") or "")
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
            planned[rel] = re.sub(r"^(\s*[-*]\s+)\[ \](\s+" + re.escape(m.group(1)) + r"\s*)$", r"\1[x]\2", planned[rel], count=1, flags=re.M)
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
    if to_archive and not a.dry_run:
        os.makedirs(os.path.join(vault, ARCHIVE), exist_ok=True)
        for r in to_archive:
            os.replace(os.path.join(vault, r), free_path(os.path.join(vault, ARCHIVE), os.path.basename(r)))
        record_removed(removed_path, to_archive, old_src, now, {os.path.basename(r).lower(): ARCHIVE for r in to_archive}, by="ela")
    keep_dirs = archive_refs(vault)
    gone = sorted(r for r in set(old) - now_files if not r.startswith(".obsidian") and r.lower() not in lower
                  and r.lower() not in native_lower and not any(r.lower().startswith(d + "/") for d in keep_dirs))
    if not a.dry_run:
        # the manifest first: a crash before the removals leaves files it no longer lists, never removals it would
        # later read as the owner's deletions
        atomic_write(mpath, json.dumps({"synced": now.isoformat(timespec="seconds"), "layout": LAYOUT, "files": sorted(now_files),
                                        "sources": {n.path: n.src_rel for n in notes if n.src_rel},
                                        "generated": {r: digest(t) for r, t in planned.items() if r.endswith(".base")},
                                        "seen": {r: d for r, d in seen.items() if r in planned},
                                        "home": {"open": is_open, "before": before,
                                                 "saw": sorted(r for r in planned if top(r) == TO_READ) if opening else saw},
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
    r = {"dry_run": a.dry_run, "deleted_by_owner": newly, "archived_by_ela": to_archive + [n.path for n in unread], "notes": len(planned), "written": len(wrote), "unchanged": same, "files_copied": copied,
         "removed": gone, "held": held, "warnings": warnings}
    if a.json:
        print(json.dumps(r, ensure_ascii=False)); return
    print(f"{'DRY RUN — ' if a.dry_run else ''}vault: {len(planned)} notes ({len(wrote)} written, {same} unchanged), "
          f"{copied} files copied, {len(gone)} removed, {len(held)} under a warning")
    for g in gone[:20]:
        print(f"  removed {g}")
    if len(gone) > 20:
        print(f"  … and {len(gone) - 20} more (--json lists them all)")
    for d in to_archive:
        print(f"  acted on, archived by ela: {d}")
    for d in newly:
        print(f"  deleted by the owner, recorded as read: {d}")
    for h in held:
        print(f"  warning {h['note']}: {'; '.join(h['problems'])}")
    for w in warnings:
        print(f"  note: {w}", file=sys.stderr)


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
    p = sub.add_parser("guidance", help="the owner's `ela:` lines anywhere in the vault, and the notes in to-learn")
    p.add_argument("--all", action="store_true", help="include instructions already handled")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_guidance)
    p = sub.add_parser("marks", help="finish the to-read notes whose done, learn or drop box is ticked (no session)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_marks)
    p = sub.add_parser("finish", help="on the owner's word: delete a note, or move it into archive/ or to-learn/")
    p.add_argument("path", help="the note's path in the vault, e.g. to-read/2026-09-07-mh-review.md")
    p.add_argument("--to", choices=("delete", "archive", "learn"), default="delete")
    p.set_defaults(func=cmd_finish)
    p = sub.add_parser("note", help="a note's life: claim, release, progress TEXT, built TEXT, move --to in-progress|parked|archive|to-read|delete")
    p.add_argument("act", choices=("claim", "release", "progress", "built", "move"))
    p.add_argument("path", help="the note's path in the vault, e.g. to-read/2026-10-26-system-plan.md")
    p.add_argument("text", nargs="*", help="progress or built: the line to record")
    p.add_argument("--to", choices=("in-progress", "parked", "archive", "to-read", "delete"))
    p.add_argument("--status", help="move: the status the note carries after it, settled to its folder's own (an archived "
                                    "outcome such as accepted goes to next)")
    p.add_argument("--next", help="move --to archive: the move that ended the note (make-plan, nudge, draft-comment, …), "
                                  "kept in its next field; without it an outcome --status is read as one")
    p.add_argument("--waits-on", help="move --to parked: who it waits on, and where")
    p.add_argument("--wake", help="move --to parked: what brings it back (a Slack thread, a ticket key)")
    p.set_defaults(func=cmd_note)
    p = sub.add_parser("restore", help="bring back a note the owner deleted in the vault")
    p.add_argument("path", help="the note's path in the vault, as the deletion log lists it")
    p.set_defaults(func=cmd_restore)
    a = ap.parse_args()
    if a.cmd in WRITERS:                                   # every writer of the vault takes the same lock as the sync
        hold = vault_lock()                                # noqa: F841  (held until the process exits)
    a.func(a)


if __name__ == "__main__":
    main()
