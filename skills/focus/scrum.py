#!/usr/bin/env python3
"""The after-scrum import: the meeting's Read AI report, read from mail, mapped to the focus board. Stdlib only.

A module of the focus verb (`ela focus scrum`), run by the runner after the scrum (Mon and Fri, after 11:00). Read AI
mails a "MediaHub Scrum on <date> | Read Meeting Report" after each session; its body carries the summary and, as
data, the action items (`action_items:[…]`) and each chapter's topics (`topics:[…]`, the decisions). The import:

  - finds the report for the day (`ela mail search`), or reads one message given as a file;
  - splits the action items by person and the topics into decisions;
  - maps each to a board row: a ticket key it names, else enough distinctive words shared with the row;
  - drafts the Jira moves they imply: a comment carrying the item, an assignee when the row has none and the roster
    knows the person, a due date when the item names one and the ticket has none; an item or decision for the team
    that maps to no row becomes a drafted ticket; the owner's own items are his, listed and never ticketed;
  - marks the rows it settled as ruled at that meeting (no carry), and hands the writes to the one focus batch.

A summary is a report, not evidence: nothing here writes to Jira. The batch is asked A/B on today.md and applied only
on his A (`ela dry answer`). The Read AI connector replaces the mail read once it is authorised; the parsing below
is the mail body's.

Usage:
    scrum.py --help      this text; the verb is `ela focus scrum [--date D] [--mail-file F] [--apply] [--json]`
"""
import datetime, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import focus as F  # noqa: E402
import hold as H  # noqa: E402

MAIL = os.path.join(HERE, "..", "mail", "mail.py")
QUERY = 'subject:"MediaHub Scrum" subject:"Read Meeting Report" newer_than:5d'
MATCH_MIN = 4                      # two shared Latin words, or four shared Chinese runs
SCRUM_CREATES = 5                  # tickets drafted from one report; the rest are listed
GROUP = ("\u4f1a\u8bae\u53c2\u4e0e\u8005", "\u53c2\u4f1a\u8005", "participants", "meeting participants", "team", "\u56e2\u961f")
MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"), 1)}
WEEKDAYS_ZH = {"\u4e00": 0, "\u4e8c": 1, "\u4e09": 2, "\u56db": 3, "\u4e94": 4, "\u516d": 5, "\u65e5": 6, "\u5929": 6}
WEEKDAYS_EN = {d: i for i, d in enumerate(("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"))}
COMMON = set("mediahub mh the and for with from into that this will team meeting about media hub tvu".split())
PERSON = re.compile(r"(?:(?<=\s)|^)((?:[A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)?)|\u4f1a\u8bae\u53c2\u4e0e\u8005|\u53c2\u4f1a\u8005)\s*[\uff1a:]\s*")


# ── the report ────────────────────────────────────────────────────────────────────────────────────────────────────
def meeting_day(subject):
    """The day a report's subject names (`MediaHub Scrum on November 18, 2026 | …`), or None."""
    m = re.search(r"\bon\s+([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", subject or "")
    if not m or m.group(1).lower() not in MONTHS:
        return None
    return datetime.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))


def bracket(body, name):
    """The text inside `name:[ … ]` in the report's data, brackets balanced; '' when absent."""
    i = (body or "").find(name + ":[")
    if i < 0:
        return ""
    i += len(name) + 2
    depth, j = 1, i
    while j < len(body) and depth:
        depth += {"[": 1, "]": -1}.get(body[j], 0)
        j += 1
    return body[i:j - 1]


def action_items(body):
    """[(person, text)] from `action_items:[…]`: each item starts at a name followed by a colon."""
    raw = " ".join(bracket(body, "action_items").split())
    parts = PERSON.split(raw)
    out = []
    for i in range(1, len(parts) - 1, 2):
        text = parts[i + 1].strip(" \u3002.;\uff1b")
        if text:
            out.append((parts[i].strip(), text))
    return out


def decisions(body):
    """The chapters' topics: what the meeting settled or found, one sentence each."""
    out = []
    for m in re.finditer(r"topics:\[([^\[\]]*)\]", body or ""):
        for t in re.split(r"(?<=[\u3002.!?\uff01\uff1f])\s*", m.group(1).strip()):
            if t.strip() and t.strip() not in out:           # the report repeats its chapters: each once
                out.append(t.strip())
    return out


DECIDED = re.compile(r"\u83b7\u51c6|\u51b3\u5b9a|\u786e\u5b9a(?!.*(?:\u672a|\u5c1a\u672a|\u6ca1\u6709))|\u540c\u610f|\u6279\u51c6|\b(?:agreed|decided|approved|will ship|goes to)\b", re.I)


def is_decision(text):
    """A topic that settles something (approved, decided, agreed), not one that only reports the discussion."""
    return bool(DECIDED.search(text or "")) and not re.search(r"\u5c1a\u672a|\u4ecd\u5728|\u672a\u786e\u5b9a|not yet|still", text or "", re.I)


def find_report(day, runner=None):
    """The report mail for `day`: (message as `mail read --json` prints it) or None. The reminder mails Read AI sends
    later carry the same report; the first one for the day is read."""
    run = runner or (lambda argv: subprocess.run(["python3", MAIL] + argv, capture_output=True, text=True, timeout=180))
    p = run(["search", QUERY, "--limit", "10", "--json"])
    if p.returncode != 0:
        raise RuntimeError(f"mail search: {(p.stderr or p.stdout).strip()[:200]}")
    msgs = [m for m in json.loads(p.stdout).get("messages") or [] if meeting_day(m.get("subject")) == day]
    for m in sorted(msgs, key=lambda m: m.get("date") or ""):
        r = run(["read", m["id"], "--json"])
        if r.returncode == 0:
            msg = json.loads(r.stdout)
            if "action_items:[" in (msg.get("body") or "") or "topics:[" in (msg.get("body") or ""):
                return msg
    return None


# ── mapping to the board ──────────────────────────────────────────────────────────────────────────────────────────
def tokens(text):
    """Distinctive words: Latin words of three letters or more and numbers with a letter (weight 2 each when matched),
    and Chinese three-character runs (weight 1): a two-character run matches nearly anything."""
    t = (text or "").lower()
    out = {w for w in re.findall(r"[a-z][a-z0-9_.-]{2,}|\d+[a-z]+[a-z0-9]*", t) if w not in COMMON}
    for run in re.findall(r"[\u4e00-\u9fff]{3,}", t):
        out |= {run[i:i + 3] for i in range(len(run) - 2)}
    return out


def overlap(a, b):
    both = a & b
    return sum(1 if re.match(r"[\u4e00-\u9fff]", w) else 2 for w in both)


def match(text, rows):
    """The row an item is about: one whose key it names, else the single row sharing the most distinctive words (a
    weight of MATCH_MIN at least, and more than any other row)."""
    for k in H.keys_in(text):
        if k in rows:
            return rows[k]
    tw = tokens(text)
    scored = []
    for r in rows.values():
        n = overlap(tw, tokens(" ".join([r.get("title") or ""] + [a.get("text") or "" for a in r.get("asks") or []])))
        if n >= MATCH_MIN:
            scored.append((n, r))
    scored.sort(key=lambda x: -x[0])
    if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    return None


def due_in(text, day):
    """A due date an item names, read against the meeting day: this or next week's weekday in Chinese (with or
    without a closing 'before'), tomorrow, today, `by Friday`, `next Wednesday`, `11/25`, a Chinese month-day. None when
    it names none."""
    t = text or ""
    m = re.search(r"(\u4e0b)?(?:\u672c|\u8fd9)?(?:\u5468|\u661f\u671f|\u793c\u62dc)([\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u65e5\u5929])", t)
    if m:
        wd = WEEKDAYS_ZH[m.group(2)]
        monday = day - datetime.timedelta(days=day.weekday())
        d = monday + datetime.timedelta(days=wd + (7 if m.group(1) else 0))
        return d if d >= day else d + datetime.timedelta(days=7)
    if "\u660e\u5929" in t:
        return day + datetime.timedelta(days=1)
    if "\u4eca\u5929" in t or "\u5f53\u5929" in t:
        return day
    m = re.search(r"\b(next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", t, re.I)
    if m and re.search(r"\b(by|before|until|on|next)\b", t, re.I):
        d = day + datetime.timedelta(days=(WEEKDAYS_EN[m.group(2).lower()] - day.weekday()) % 7 or 7)
        return d + datetime.timedelta(days=7) if m.group(1) and d - day < datetime.timedelta(days=7) and d.weekday() >= day.weekday() else d
    m = re.search(r"(\d{1,2})\s*\u6708\s*(\d{1,2})\s*[\u65e5\u53f7]|(?<![\d.])(\d{1,2})/(\d{1,2})(?![\d/])", t)
    if m:
        mo, dd = (int(m.group(1)), int(m.group(2))) if m.group(1) else (int(m.group(3)), int(m.group(4)))
        try:
            d = datetime.date(day.year, mo, dd)
        except ValueError:
            return None
        return d if d >= day - datetime.timedelta(days=31) else d.replace(year=day.year + 1)
    return None


def is_owner(person, owner):
    p = (person or "").strip().lower()
    return bool(owner) and (p == owner.lower() or p == owner.split()[0].lower())


def drafts(report, rows, day, owner, reports, facts):
    """(writes, left out, ruled row ids) for one report."""
    body = report.get("body") or ""
    W, left, ruled, creates = [], [], [], []
    tag = f"MediaHub scrum {day.isoformat()} (Read AI report)"
    for person, text in action_items(body):
        r = match(text, rows)
        if is_owner(person, owner):
            left.append(f"yours, not ticketed: {text}" + (f" (row {r['id']})" if r else ""))
            continue
        if r and r.get("key"):
            k = r["key"]
            ruled.append(r["id"])
            W.append(F.comment_write(reports, k, f"Action from the {tag}, for {person}: {text}", f"the scrum's action item for {person}", 0))
            iss = F.facts_issue(facts, k)
            email = F.roster_email(person) if person.lower() not in GROUP else None
            if email and not r.get("owner"):
                W.append({"target": k, "command": f"ela jira assign {k} --assignee {email}", "why": f"the scrum gave it to {person}; it had nobody"})
            due = due_in(text, day)
            if due and iss and not F.field(iss, "duedate"):
                W.append({"target": k, "command": f"ela jira due {k} --date {due.isoformat()} --why {F.q('the date set at the ' + tag)}",
                          "why": f"the scrum named {due:%a %m-%d}"})
        elif person.lower() in GROUP:
            left.append(f"for the whole team, no row: {text}")
        else:
            creates.append((person, text, r))
    for text in decisions(body):
        r = match(text, rows)
        if r and r.get("key"):
            ruled.append(r["id"])
            W.append(F.comment_write(reports, r["key"], f"Decided at the {tag}: {text}", "the scrum's decision on this row", 0))
        elif is_decision(text) and not any(tokens(text) and overlap(tokens(text), tokens(c[1])) >= MATCH_MIN for c in creates):
            creates.append((None, text, r))                   # a decision no row carries, and no action item already says
        else:
            left.append(f"discussed, no row: {text}")
    for person, text, r in creates[:SCRUM_CREATES]:
        summary = F.clip(f"[Scrum {day:%m-%d}] " + re.sub(r"\s+", " ", text), 120)
        desc = F.one_line(f"From the {tag}" + (f", an action item for {person}" if person else ", a decision") + f":\n\n{text}\n\n"
                "It maps to no ticket on the MediaHub focus board; this one tracks it.")
        email = F.roster_email(person) if person else None
        W.append({"target": (r or {}).get("id") or f"scrum:{summary[:40]}",
                  "command": f"ela jira create --project MH --type Task --summary {F.q(summary)} --description {F.q(desc)}"
                  + (f" --assignee {email}" if email else ""),
                  "why": "from the scrum, no ticket to move: Jira is where MH items are tracked"})
    for person, text, _ in creates[SCRUM_CREATES:]:
        left.append(f"not drafted this batch ({person or 'decision'}): {text}")
    return W, left, sorted(set(ruled))


def scrum_meeting(doc):
    return next((m for m in doc.get("meetings") or [] if isinstance(m, dict) and
                 (str(m.get("key") or "").startswith("scrum") or "product" in F.audiences(m))), None)


def cmd(a):
    s = F.site()
    now = datetime.datetime.now()
    day = datetime.date.fromisoformat(a.date) if a.date else now.date()
    if a.mail_file:
        report = json.load(open(a.mail_file, encoding="utf-8"))
    else:
        try:
            report = find_report(day)
        except (RuntimeError, ValueError) as e:
            print(f"scrum: {e}", file=sys.stderr)
            return 5
    if not report:
        print(f"scrum: no Read AI report for {day.isoformat()} in mail yet", file=sys.stderr)
        return F.EX_NOTFOUND
    facts = os.path.join(s.get("runtime") or "", "facts")
    b = F.board(s, now=now, write=False)
    owner = F.owner_name(facts)
    writes, left, ruled = drafts(report, b["all"], day, owner, s.get("reports") or "", facts)
    try:
        m = scrum_meeting(F.brief_mod().owner_day())
    except Exception:                                          # noqa: BLE001
        m = None
    r = F.run_moves(s, a.apply, scrum=writes, now=now, ruled=(m["key"], day.isoformat(), ruled) if m else None)
    r["left_out"] = left + r["left_out"]
    r["ruled"] = ruled
    r["report"] = report.get("subject")
    F.emit(a, r, [f"report: {r['report']}"] + [f"{w['n']}. {w['command']} — {w['why']}" for w in r["writes"]]
           + [f"- {x}" for x in r["left_out"]]
           + [f"batch: {r['batch']} (asked A/B on today.md)" if r["batch"] else "dry run; --apply stores the batch"])
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    print(__doc__, file=sys.stderr)
    sys.exit(2)
