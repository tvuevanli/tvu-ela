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
    vault.py setup                   apply the Obsidian settings kept in obsidian/ (after a reset or on a new machine)

Layout. Names are lowercase with hyphens and no spaces, taken from the source's file name, never from its heading,
so editing a title renames nothing. Top folders are numbered by range so a new kind takes a free number:
10–19 by time · 20–39 reports and evidence · 40–59 records · 60–79 reserved · 80–99 system. A dated archive is
split by year, a high-volume one (days, verifications) by month.
    home.md, readme.md                          the entry point; what the vault is
    10-days/<year-month>/<date>-brief.md        the morning page, kept; -learned and -intake beside it for 14 days
    15-weeks/<year>/<year>-w<nn>.md             reserved for the owner's weekly page (not generated yet)
    18-sprints/<year>/<year>-s<nn>.md           sprint commitments from elak
    20-reviews/<year>/<date>-<slug>.md          reviews and reports; a report with no date in its name: undated/
    25-board/board.md                           the board's debt, one living page; its daily counts stay in the reports root
    30-verify/<year-month>/<key>-<date>.md      a verification, for 14 days: the report, the technical record linked
    40-decisions/<year>/<date>-<slug>.md
    50-plans/<year>/<date>-<slug>.md
    80-views/*.base                             Bases tables over the notes' properties
    85-assistant/how-ela-runs.md                every scheduled job, here and on the remote host, read from the machines
    90-attachments/verify/<year-month>/<record>/   each record copied whole, so its own page still opens

The reading gate. The vault is how ela reports to the owner, so a note over its reading budget, mostly code, or
carrying machine paths is still written, under a warning that names the problem, and Home lists it for 30 days
as a rewrite ela owes. Nothing readable is withheld; nothing unreadable passes unmarked.

Safety. A missing or unreadable source, or a folder that shrinks by more than half since the last sync, stops
the sync before anything is written (--force overrides after a deliberate removal). Removal is limited to files
this script recorded in its manifest. Writes are atomic and a lock serialises concurrent syncs.

Exit codes: 0 ok · 2 usage or site · 3 a source could not be read or shrank (nothing written).
"""
import argparse, datetime, fcntl, json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
JIRA = os.path.join(HERE, "..", "jira", "jira.py")
SITE = os.path.expanduser("~/.claude/ela/site.json")
MANIFEST = ".ela-sync.json"
DAYS_KEPT, HELD_LISTED_DAYS, NEW_DAYS = 14, 30, 7
KEEP_FOREVER = ("brief",)   # the morning page is the record of what ela told the owner; the rest expires
PROPS = ("title", "type", "date", "kind", "status")   # the whole vocabulary; no tags (folders, type and the views classify)
BUDGET = {"guide": 1200, "board": 1000, "day": 1200, "review": 2500, "decision": 1200, "plan": 2500, "sprint": 800}
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

ela writes this vault for Evan to read. Every note is generated from a first-hand source and rewritten on each
sync, after the morning and the evening job. Nothing here is edited by hand: an edit is overwritten. To change
something, ask ela in a session or in Slack.

Start at [[home]]: today's page, what waits for your word, what is new this week, and what ela owes a rewrite.

## Layout

| folder | holds | grows |
|---|---|---|
| `10-days/` | the morning page, kept; the evening learning draft, 14 days | by month |
| `15-weeks/` | reserved for a weekly page, from the first sprint week | by year |
| `18-sprints/` | sprint commitments | by year |
| `20-reviews/` | reviews and reports written for Evan | by year |
| `25-board/` | the board's debt: open tickets by shape, each shape's next move, what waits on Evan | one page, rewritten each morning |
| `30-verify/` | verification results to review: verdict, checks, screenshots, the technical record | 14 days; then on the Jira ticket |
| `40-decisions/` | decisions, with what they superseded | by year |
| `50-plans/` | plans, decided or proposed | by year |
| `60-` to `79-` | reserved for new kinds | |
| `80-views/` | one table view with tabs: recent, to review, decisions and plans, morning pages, reviews | |
| `85-assistant/` | working with ela day to day, and how ela runs: every scheduled job, its last run and result | rewritten each sync |
| `90-attachments/` | the records and images the notes embed | by month |

Folder numbers run by range, so a new kind takes a free number in its range and nothing is renamed:
10–19 by time, 20–39 reports and evidence, 40–59 records, 60–79 new kinds, 80–99 system.

## Names and properties

- Names are lowercase, words joined by hyphens, no spaces, taken from the source file's name:
  `2026-10-23-review`, `mh-3103-2026-10-23`, `2026-s01`. The readable title is the note's first heading.
- Properties are `title` and `type`, plus `date` where the source is dated, `kind` on a day page and `status` on a
  decision or plan; they feed the tables and stay hidden while you read. Nothing else.
- No tags, by design: folders, `type` and the tables already classify every note, and a second vocabulary would
  drift from the first.
- A ticket key is a link to Jira, one click in reading mode.

## Reading budgets

A note is written for a person: a title heading, within its budget (day page 1,200 words, review 2,500,
decision 1,200, plan 2,500, sprint 800), mostly prose, no machine paths. A note that misses is still here, under
a warning, and Home lists it for 30 days as a rewrite ela owes.

## Deleting a note

Deleting a note is feedback. ela does not write it again, and reads the deletion as a sign that the note was not
worth your time, so the writer changes. `ela vault restore <path>` brings one back.

## What is not here

ela's own knowledge, status table and working rules, which are written for ela; a decision not yet committed
to elak; Helm's team reports, which stay in Slack and Helm. Internal addresses and credentials are redacted from
the text; screenshots are copied as they are.

## How Obsidian is set up

Set by ela; the sync never changes these settings. ela keeps a copy, and `ela vault setup` reapplies them after a reset or on another machine.

- Notes open in reading view, without the file-name title or the properties panel, at a readable width; the
  `ela` style sheet tidies tables and callouts.
- Core plugins on: search, quick switcher, file explorer, backlinks, outgoing links, page preview, outline,
  bookmarks, properties, Bases, Web viewer (on request only). Off: everything made for writing (templates, daily notes, note
  composer, canvas, slash commands) and tags, which this vault does not use.
- Two community plugins: **Homepage** opens `home` in reading view when Obsidian starts; **HTML Reader** opens a
  verification's full record (a self-contained `.html`) in a tab. A click on a web link opens the default browser;
  right-click a link and choose *Open in web viewer* to read it inside Obsidian (Jira works there, Slack does not).
"""

VIEWS = {
    "index": """filters:
  and:
    - 'type != "home"'
    - 'type != "readme"'
views:
  - type: table
    name: Recent
    order: [date, title, type]
    sort:
      - property: date
        direction: DESC
    limit: 60
  - type: table
    name: To review
    filters:
      or:
        - 'type == "verify"'
        - 'status == "proposed"'
    order: [date, title, type, status]
    sort:
      - property: date
        direction: DESC
  - type: table
    name: Decisions and plans
    filters:
      or:
        - 'type == "decision"'
        - 'type == "plan"'
        - 'type == "sprint"'
    order: [date, title, type, status]
    sort:
      - property: date
        direction: DESC
  - type: table
    name: Morning pages
    filters:
      and:
        - 'type == "day"'
    order: [date, title, kind]
    sort:
      - property: date
        direction: DESC
  - type: table
    name: Reviews
    filters:
      and:
        - 'type == "review"'
    order: [date, title]
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


def h1(body):
    m = re.search(r"^#\s+(.+?)\s*$", body, re.M)
    return re.sub(r"[`*_]", "", m.group(1)).strip() if m else None


def sentence(title):
    return title if re.match(r"^(ela|elak)\b", title) else title[:1].upper() + title[1:]


def front(existing, props):
    """Properties from the fixed vocabulary only; a source's own status, decided or written date fills a gap."""
    src = {}
    for l in existing:
        m = re.match(r"^(status|decided|written):\s*['\"]?([^'\"]*)['\"]?\s*$", l)
        if m:
            src[m.group(1)] = m.group(2).strip()
    props = dict(props)
    if src.get("status") and not props.get("status"):
        props["status"] = src["status"].split(" — ")[0].split(" (")[0][:40]
    if not props.get("date") and (src.get("decided") or src.get("written")):
        props["date"] = (src.get("decided") or src.get("written"))[:10]
    lines = [f"{k}: {json.dumps(props[k], ensure_ascii=False)}" for k in PROPS if props.get(k)]
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
        # most decisions record how ela is built; only those marked `reader: owner` are written for Evan
        if kind != "sprint" and not any(re.match(r"^reader:\s*owner\b", l) for l in fl):
            continue
        folder = {"decision": "40-decisions", "plan": "50-plans", "sprint": "18-sprints"}[kind]
        title = sentence(h1(body) or base.replace("-", " "))
        titles[rel] = title
        sp = re.match(r"^(\d{4})-[sS](\d{2})$", base)
        dm = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+)$", base)
        if sp:
            path, date = f"18-sprints/{sp.group(1)}/{sp.group(1)}-s{sp.group(2)}.md", None
        elif dm:
            path, date = f"{folder}/{dm.group(1)[:4]}/{dm.group(1)}-{slug(dm.group(2))}.md", dm.group(1)
        else:
            path, date = f"{folder}/undated/{slug(base)}.md", None
        notes.append(Note(path, title, body, {"type": kind, "date": date}, fl, src_rel=rel))
    # pages at the top of elak's blueprint marked for the owner (the routine, the overview) go to 85-assistant
    top_files = subprocess.run(["git", "-C", elak, "ls-files", "-z", "--", "blueprint/*.md"], capture_output=True, text=True).stdout.split("\0")
    for rel in (r for r in top_files if r.count("/") == 1 and r.endswith(".md")):
        p = os.path.join(elak, rel)
        if not os.path.isfile(p):
            continue
        fl, body = split_front(open(p, encoding="utf-8").read())
        if not any(re.match(r"^reader:\s*owner\b", l) for l in fl):
            continue
        title = sentence(h1(body) or os.path.basename(rel)[:-3].replace("-", " "))
        notes.append(Note(f"85-assistant/{slug(os.path.basename(rel)[:-3])}.md", title, body, {"type": "guide"}, fl, src_rel=rel))
        titles[rel] = title
    return notes, titles


def report_notes(reports, today):
    if not reports or not os.path.isdir(reports):
        raise SourceError(f"the reports root is missing: {reports}")
    notes = []
    rd = os.path.join(reports, "runner")
    for f in sorted(os.listdir(rd)) if os.path.isdir(rd) else []:
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-(brief|learned)\.md$", f)
        if not m or (m.group(2) not in KEEP_FOREVER and (today - datetime.date.fromisoformat(m.group(1))).days >= DAYS_KEPT):
            continue
        d = datetime.date.fromisoformat(m.group(1))
        fl, body = split_front(open(os.path.join(rd, f), encoding="utf-8").read())
        label = {"brief": "Morning brief", "learned": "What the day taught"}[m.group(2)]
        notes.append(Note(f"10-days/{m.group(1)[:7]}/{m.group(1)}-{m.group(2)}.md", f"{label} · {d:%a} {m.group(1)}", body,
                          {"type": "day", "date": m.group(1), "kind": m.group(2)}, fl, src_rel=f"runner/{f}"))
    bp = os.path.join(reports, "board", "board.md")
    if os.path.isfile(bp):                                 # the board's debt, one living page, rewritten each morning
        fl, body = split_front(open(bp, encoding="utf-8").read())
        dm = re.search(r"\*(\d{4}-\d{2}-\d{2})", body)
        notes.append(Note("25-board/board.md", "The board's debt", body,
                          {"type": "board", "date": dm.group(1) if dm else None}, fl, src_rel="board/board.md"))
    sp = os.path.join(reports, "system", "how-ela-runs.md")
    if os.path.isfile(sp):                                 # what is scheduled where, read from the machines
        fl, body = split_front(open(sp, encoding="utf-8").read())
        notes.append(Note("85-assistant/how-ela-runs.md", "How ela runs", body, {"type": "system"}, fl, src_rel="system/how-ela-runs.md"))
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
                path = f"20-reviews/{m.group(1)[:4]}/{m.group(1)}-{rest}.md"
            else:
                path = f"20-reviews/undated/{rest}.md"
            notes.append(Note(path, title, body, {"type": "review", "date": m.group(1) if m else None}, fl,
                              src_rel=f"{sub + '/' if sub else ''}{f}"))
    return notes


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


def verify_notes(reports, today=None):
    """One note per verification record. A record folder is copied whole into the attachments, so its own page,
    which refers to its images by relative path, still opens from the vault."""
    notes, files = [], []
    vd = os.path.join(reports, "verify")
    for name in sorted(os.listdir(vd)) if os.path.isdir(vd) else []:
        m = re.match(r"^([A-Z][A-Z0-9]+-\d+)-(\d{4}-\d{2}-\d{2})(-[a-z0-9-]+)?(\.html)?$", name)
        if not m:
            continue
        key, date, extra, single = m.group(1), m.group(2), (m.group(3) or ""), bool(m.group(4))
        # a verification is in the vault while it needs the owner's eyes; afterwards it lives on its Jira ticket,
        # in the reports root and in the backup
        if today and (today - datetime.date.fromisoformat(date)).days >= DAYS_KEPT:
            continue
        p = os.path.join(vd, name)
        record = f"90-attachments/verify/{date[:7]}/{name.lower()}"
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
            title = f"{key} · {vm.group(1)}" if vm else f"{key} verification {date}"
            notes.append(Note(f"30-verify/{date[:7]}/{key.lower()}-{date}{extra}.md", title + (f" ({extra.strip('-')})" if extra else ""),
                              body, {"type": "verify", "date": date}))
            continue
        verdict = record_verdict(os.path.join(vd, name) if single else os.path.join(p, os.path.basename(page or "index.html")))
        body = [f"# {key} verification · {date}{' · ' + extra.strip('-') if extra else ''}", ""]
        if not verdict:
            body += ["> [!info] The record states no single verdict; open it for the per-ticket results.", ""]
        elif verdict:
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
        notes.append(Note(f"30-verify/{date[:7]}/{key.lower()}-{date}{extra}.md", f"{key} verification {date}",
                          "\n".join(body) + "\n", {"type": "verify", "date": date}))
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
    except (OSError, ValueError, KeyError):
        pass
    cmd = ["python3", JIRA] + (["--env-file", env] if env else []) + [
        "jql", "(assignee was currentUser() OR reporter = currentUser() OR watcher = currentUser()) AND updated >= -180d",
        "--limit", "3000", "--json"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        keys = sorted({i["key"].split("-")[0] for i in json.loads(r.stdout)["issues"]}) if r.returncode == 0 else []
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        keys = []
    if keys:
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


# ── home ──────────────────────────────────────────────────────────────────────────────────────────────

def link(n):
    return f"[[{n.path[:-3]}|{n.title}]]"


def home(today, now, notes):
    def newest(kind):
        return sorted((n for n in notes if n.props.get("type") == "day" and n.props.get("kind") == kind),
                      key=lambda n: n.props["date"], reverse=True)
    brief, intake, learned = (next(iter(newest(k)), None) for k in ("brief", "intake", "learned"))
    iso = today.isoformat()
    L = [f"# ela · {today:%Y-%m-%d %a}", "", f"*Generated by ela, last synced {now:%Y-%m-%d %H:%M}. Change things through ela, not here.*", ""]
    guides = {n.path: n for n in notes if n.props.get("type") == "guide"}
    routine, overview = guides.get("85-assistant/workflow.md"), guides.get("85-assistant/overview.md")
    guide = routine
    if routine or overview:
        L += [" · ".join(x for x in (f"How ela works: {link(overview)}" if overview else "",
                                     f"your routine: {link(routine)}" if routine else "") if x)
              + ". Say `feedback …` in Slack when something does not fit.", ""]
    if brief and brief.props["date"] == iso:
        L += [f"## Today · {link(brief)}", ""]
        if intake and intake.props["date"] >= (today - datetime.timedelta(days=1)).isoformat():
            L += [f"New tickets read: {link(intake)}", ""]
        L += [f"![[{brief.path[:-3]}]]", ""]
    else:
        L += ["## Today", "", "No morning page yet today" + (f"; the latest is {link(brief)}." if brief else "."), ""]
    board = next((n for n in notes if n.props.get("type") == "board"), None)
    if board:
        L += [f"Board: {link(board)}" + (f", as of {board.props['date']}" if board.props.get("date") else ""), ""]
    wait = []
    if learned and learned.props["date"] >= (today - datetime.timedelta(days=2)).isoformat():
        wait.append(f"- {link(learned)}: what the day taught; say which entries to keep")
    for n in notes:
        if n.props.get("type") == "plan" and any(re.match(r"^status:\s*proposed", l) for l in n.front_lines):
            wait.append(f"- {link(n)}: a plan with decisions for you")
    if board:
        wait.append(f"- {link(board)}: ticket batches waiting for one confirm each")
    if wait:
        L += ["## Waiting for your word", ""] + wait + [""]
    since = (today - datetime.timedelta(days=NEW_DAYS)).isoformat()
    new = sorted((n for n in notes if n.props.get("type") in ("verify", "review", "decision", "plan", "sprint")
                  and (n.props.get("date") or "") >= since), key=lambda n: (n.props.get("date") or "", n.path), reverse=True)
    if new:
        L += [f"## New in the last {NEW_DAYS} days", ""] + [f"- {n.props['date']} · {n.props['type']} · {link(n)}" for n in new] + [""]
    owed_since = (today - datetime.timedelta(days=HELD_LISTED_DAYS)).isoformat()
    owed = [n for n in notes if n.held and (n.props.get("date") or iso) >= owed_since]
    if owed:
        L += ["## ela owes a shorter version", ""] + [f"- {link(n)}: {'; '.join(n.held)}" for n in owed] + [""]
    L += ["## Browse", "", "[[80-views/index.base|All notes, as tables]] · [[85-assistant/how-ela-runs|How ela runs]] · "
          "[[readme|About this vault]]", ""]
    return "\n".join(L)


# ── the sync ──────────────────────────────────────────────────────────────────────────────────────────

def plan(s, env, today, now, removed=frozenset()):
    reports = s.get("reports")
    enotes, titles = elak_notes(s.get("elak"))
    notes = report_notes(reports, today) + enotes
    vnotes, files = verify_notes(reports, today)
    notes += vnotes
    notes = [n for n in notes if n.path not in removed]   # what the owner deleted is not written, linked or listed
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
    warnings = [] if jira_base and projects else ["ticket keys are not linked: no Jira base URL or project list"]
    reps = {n.src_rel: n for n in notes if n.src_rel and n.props.get("type") in ("day", "review")}
    linker = Linker({n.src_rel: n for n in enotes}, titles, jira_base, projects, reports, reps)
    planned = {}
    for n in notes:
        n.held = reading_gate(n)
        body = linker(unwrap(callouts(tidy_title(n.body))))
        planned[n.path] = redact(front(n.front_lines, dict(n.props, title=n.title)) + (with_warning(body, n.held) if n.held else body))
    planned["home.md"] = redact(front([], {"type": "home", "date": today.isoformat()}) + linker(home(today, now, notes)))
    planned["readme.md"] = unwrap(README)
    for name, text in VIEWS.items():
        planned[f"80-views/{name}.base"] = text
    return planned, files, notes, warnings


def load_removed(path):
    out = set()
    try:
        for line in open(path, encoding="utf-8"):
            try:
                row = json.loads(line)
                (out.discard if row.get("restored") else out.add)(row["path"])
            except (ValueError, KeyError):
                pass
    except OSError:
        pass
    return out


def record_removed(path, feedback, rels, planned, now):
    """Log each note the owner deleted, and the same as a feedback line the evening run reads."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh, open(feedback, "a", encoding="utf-8") as fb:
        for r in rels:
            m = re.search(r"^#\s+(.+)$", planned.get(r, ""), re.M)
            title = m.group(1) if m else sentence(re.sub(r"^\d{4}-\d{2}-\d{2}-", "", os.path.basename(r)[:-3]).replace("-", " "))
            fh.write(json.dumps({"at": now.isoformat(timespec="seconds"), "path": r, "title": title}, ensure_ascii=False) + "\n")
            fb.write(json.dumps({"at": now.isoformat(timespec="seconds"), "from": "vault", "text":
                                 f"deleted from the vault: {title} ({r}); not worth reading as written"}, ensure_ascii=False) + "\n")


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
    merge("appearance.json", cfg["appearance"])
    try:
        core = json.load(open(os.path.join(o, "core-plugins.json")))
    except (OSError, ValueError):
        core = {}
    core = {k: (k in cfg["core_on"]) for k in set(core) | set(cfg["core_on"])}
    atomic_write(os.path.join(o, "core-plugins.json"), json.dumps(core, indent=2))
    atomic_write(os.path.join(o, "community-plugins.json"), json.dumps(cfg["community"]))
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
    now = int(datetime.datetime.now().timestamp() * 1000)
    atomic_write(os.path.join(o, "bookmarks.json"), json.dumps({"items": [dict(b, type="file", ctime=now) for b in cfg["bookmarks"]]}, indent=2))
    print("vault settings applied; restart Obsidian to load them")


def cmd_restore(a):
    """Bring back a note the owner deleted: the next sync writes it again."""
    s = json.load(open(SITE))
    path = os.path.join(s.get("reports") or "", "ela", "vault-removed.jsonl")
    if a.path not in load_removed(path):
        print(f"not among the deleted notes: {a.path}", file=sys.stderr); sys.exit(2)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": datetime.datetime.now().isoformat(timespec="seconds"), "path": a.path, "restored": True}) + "\n")
    print(f"restored: {a.path}; the next sync writes it again")


def top(rel):
    return rel.split("/")[0]


def atomic_write(path, text):
    tmp = path + ".ela-tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def cmd_sync(a):
    s = json.load(open(SITE))
    vault = s.get("vault")
    if not vault or not os.path.isdir(vault):
        print(f"site.json `vault` is not a folder: {vault}", file=sys.stderr); sys.exit(2)
    env = a.env_file or s.get("env")
    runtime = s.get("runtime") or "/tmp"
    os.makedirs(runtime, exist_ok=True)
    lock = open(os.path.join(runtime, "vault-sync.lock"), "w")
    fcntl.flock(lock, fcntl.LOCK_EX)                       # one sync at a time
    today, now = datetime.date.today(), datetime.datetime.now()
    mpath = os.path.join(vault, MANIFEST)
    old = []
    if os.path.exists(mpath):
        try:
            old = json.load(open(mpath))["files"]
        except (ValueError, KeyError):
            print("vault: the manifest is unreadable; not synced (remove it deliberately to start over)", file=sys.stderr); sys.exit(3)
    # a note the sync wrote that is gone from disk was deleted by the owner: that is feedback, and it stays deleted
    removed_path = os.path.join(s.get("reports") or "", "ela", "vault-removed.jsonl")
    removed = load_removed(removed_path)
    newly = sorted(r for r in old if r.endswith(".md") and r not in removed and r not in ("home.md", "readme.md")
                   and not os.path.exists(os.path.join(vault, r)))
    try:
        planned, files, notes, warnings = plan(s, env, today, now, removed | set(newly))
    except SourceError as e:
        print(f"vault: not synced — {e}", file=sys.stderr); sys.exit(3)
    if newly and not a.dry_run:
        record_removed(removed_path, os.path.join(s.get("reports") or "", "ela", "feedback.jsonl"), newly, {}, now)
    removed |= set(newly)
    now_files = set(planned) | {dst for src, dst in files}
    if not a.force:                                        # a folder that halves is a failure until shown to be a removal
        kept_old = [r for r in old if r not in removed]       # the owner's deletions are not a source failing
        for t in sorted({top(r) for r in kept_old if "/" in r}):
            before = sum(1 for r in kept_old if top(r) == t)
            after = sum(1 for r in now_files if top(r) == t)
            if before >= 5 and after < before / 2:
                print(f"vault: not synced — {t} would shrink from {before} to {after} files; --force if that is intended", file=sys.stderr)
                sys.exit(3)
    listing = {}

    def names_in(d):
        if d not in listing:
            listing[d] = set(os.listdir(d)) if os.path.isdir(d) else set()
        return listing[d]
    wrote, same = [], 0
    for rel, text in planned.items():
        p = os.path.join(vault, rel)
        d, name = os.path.split(p)
        present = names_in(d)
        if name in present:
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
    gone = sorted(r for r in set(old) - now_files if not r.startswith(".obsidian") and r.lower() not in lower)
    if not a.dry_run:
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
        atomic_write(mpath, json.dumps({"synced": now.isoformat(timespec="seconds"), "files": sorted(now_files)}, indent=0))
    held = [{"note": n.path, "problems": n.held} for n in notes if n.held]
    r = {"dry_run": a.dry_run, "deleted_by_owner": newly, "notes": len(planned), "written": len(wrote), "unchanged": same, "files_copied": copied,
         "removed": gone, "held": held, "warnings": warnings}
    if a.json:
        print(json.dumps(r, ensure_ascii=False)); return
    print(f"{'DRY RUN — ' if a.dry_run else ''}vault: {len(planned)} notes ({len(wrote)} written, {same} unchanged), "
          f"{copied} files copied, {len(gone)} removed, {len(held)} under a warning")
    for g in gone[:20]:
        print(f"  removed {g}")
    for d in newly:
        print(f"  deleted by the owner, kept deleted and logged as feedback: {d}")
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
    p.add_argument("--force", action="store_true", help="sync although a folder shrinks by more than half")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_sync)
    p = sub.add_parser("setup", help="apply the vault's Obsidian settings from ela's versioned copy, then restart Obsidian")
    p.set_defaults(func=cmd_setup)
    p = sub.add_parser("restore", help="bring back a note the owner deleted in the vault")
    p.add_argument("path", help="the note's path in the vault, as the deletion log lists it")
    p.set_defaults(func=cmd_restore)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
