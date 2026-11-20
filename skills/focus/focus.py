#!/usr/bin/env python3
"""focus — MediaHub's focus as one board; a meeting is a view of it; rulings become drafted Jira moves. Stdlib only.

L1 capability. The board is meetings/focus.md in the vault, rewritten on every sync: one row per item MediaHub is
pushing now, Jira priority first, then due date. A row is an open MH ticket at High or Highest that is being worked,
a project page, or an open team question (meetings/open-questions.md stays, linked, as the questions' full list; it is
no longer a page to start from). Every row carries a Jira key or says `no ticket yet`; ela's own work and the owner's
personal items stay in the vault and never become tickets. A meeting (blueprint/meetings.yaml, enabled, on its
weekdays) is a filter of the board: at most VIEW_MAX rows that need that audience, written as a section of the board,
never a page of its own (ADR 0015). Held subjects (hold.py) leave every row and view and sit in one folded line.

A row in a meeting's view that the meeting did not move (its ticket's status, priority, assignee and due date and its
open questions the same after the meeting) is carried; carried through CARRY_MAX meetings it gets a proposed Jira
move in the next batch. The after-scrum import (scrum.py) reads the meeting's Read AI report from mail and drafts the
moves its action items imply. Every move goes out as one dry-run batch (class focus-moves, `ela dry`), asked A/B on
today.md; nothing reaches Jira before his A.

  board   [--json] [--write]          the board and its views; --write writes meetings/focus.md and the store
  hold    SUBJECT [--until X] [--apply]   park a subject everywhere (the session form of `ela: hold`)
  resume  SUBJECT [--apply]           end a hold
  holds   [--json]                    every hold, live first
  up      KEY [--why W] [--highest] [--apply]   ask for a priority raise (the session form of `ela: up`)
  down    KEY [--apply]               ask for the priority back to Medium
  moves   [--apply] [--json]          draft the batch: carried rows, up/down words, rows without a ticket; --apply
                                      stores it as a dry-run batch (Jira is untouched until his A)
  scrum   [--date D] [--mail-file F] [--apply] [--json]
                                      after the scrum: read its Read AI report from mail, map decisions and action
                                      items to rows, draft the moves into the same batch

Store: <reports>/ela/focus.json (rows first seen, carried meetings, views, up/down words), <reports>/ela/holds.json.
Exit codes: 0 ok · 2 usage · 3 not found.
"""
import argparse, datetime, hashlib, json, os, re, shlex, sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hold as H  # noqa: E402

SITE = os.path.expanduser("~/.claude/ela/site.json")
BOARD = "meetings/focus.md"
QUESTIONS_PAGE = "meetings/open-questions.md"
STATE = ("ela", "focus.json")
VIEW_MAX = 7                     # a meeting's view: at most this many rows
CARRY_MAX = 2                    # carried through this many meetings: a proposed Jira move instead of a third carry
SHOWN = 10                       # the board's head, one screen: the rows that need a push now; the rest fold
ITEM_CHARS, NEXT_CHARS = 60, 70  # a row is one line: the item and the next step clipped, the whole folded under it
CREATES_MAX = 3                  # tickets drafted for rows without one, per batch, oldest first
FRESH_DAYS = 30                  # a High ticket untouched this long is not being pushed
PARKED_STATES = ("Backlog", "On Hold", "Blocked")
PRIORITIES = ("Highest", "High", "Medium", "Low", "Lowest")
CLASS, SCOPE = "focus-moves", "mediahub-focus"
EX_USAGE, EX_NOTFOUND = 2, 3
KEY = H.KEY
OWN_SOURCES = ("ela/", "releases/agents/")   # a question raised on ela's own pages is ela's work: never a ticket


def site():
    try:
        return json.load(open(SITE))
    except (OSError, ValueError):
        return {}


def jira_base(s=None):
    env = (s or site()).get("env")
    try:
        return next((l.split("=", 1)[1].strip().rstrip("/") for l in open(env) if l.startswith("JIRA_BASE_URL=")), "")
    except (OSError, TypeError):
        return ""


def link(k, jira):
    return f"[{k}]({jira}/browse/{k})" if jira else k


def linked(text, jira):
    return KEY.sub(lambda m: link(m.group(1), jira) if H.keys_in(m.group(1)) else m.group(1), text or "") if jira else (text or "")


def questions_mod():
    sys.path.insert(0, os.path.join(HERE, "..", "vault"))
    import questions as Q                                    # noqa: E402 — the team questions' one reader and writer
    return Q


def brief_mod():
    sys.path.insert(0, os.path.join(HERE, "..", "brief"))
    import brief as B                                        # noqa: E402 — the owner's day (meetings.yaml)
    return B


def dry_mod():
    sys.path.insert(0, os.path.join(HERE, "..", "dry"))
    import dry as D                                          # noqa: E402 — the batches' one reader and writer
    return D


# ── the store ─────────────────────────────────────────────────────────────────────────────────────────────────────
def load(reports):
    try:
        st = json.load(open(os.path.join(reports or "", *STATE), encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    for k in ("rows", "views", "words"):
        st.setdefault(k, {})
    return st


def save(reports, st):
    p = os.path.join(reports, *STATE)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        f.write(json.dumps(st, ensure_ascii=False, indent=1) + "\n")
    os.replace(p + ".tmp", p)


# ── reading the sources ───────────────────────────────────────────────────────────────────────────────────────────
def field(issue, name):
    f = (issue or {}).get("fields") or {}
    v = f.get(name)
    if isinstance(v, dict):
        return v.get("displayName") or v.get("name") or v.get("value")
    return v


def is_open(issue):
    f = (issue or {}).get("fields") or {}
    if f.get("resolution"):
        return False
    cat = ((f.get("status") or {}).get("statusCategory") or {}).get("key")
    return cat != "done" and (field(issue, "status") or "") not in ("Done", "Cancelled", "Closed", "Failed", "Closed Ambigous")


def facts_issue(facts, key):
    try:
        return json.load(open(os.path.join(facts or "", "jira", "issues", f"{key}.json"), encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def focus_tickets(facts, today, project="MH"):
    """The open tickets MediaHub is pushing, from the fact store: High or Highest (Jira priority says it; no label repeats it), out of the
    backlog and moved in the last FRESH_DAYS days (a High ticket nobody touched since spring is not being pushed)."""
    out, d = [], os.path.join(facts or "", "jira", "issues")
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not f.startswith(project + "-") or not f.endswith(".json"):
            continue
        try:
            iss = json.load(open(os.path.join(d, f), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not is_open(iss):
            continue
        moved = str((iss.get("fields") or {}).get("updated") or iss.get("updated") or "")[:10]
        if (field(iss, "priority") in ("Highest", "High") and field(iss, "status") not in PARKED_STATES
                and moved >= (today - datetime.timedelta(days=FRESH_DAYS)).isoformat()):
            out.append(iss)
    return out


def split_front(text):
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end > 0:
            return text[4:end].splitlines(), text[end + 4:].lstrip("\n")
    return [], text


def prop(lines, name):
    for l in lines:
        m = re.match(rf"^{re.escape(name)}:\s*(.*)$", l)
        if m:
            v = m.group(1).strip()
            return v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else v
    return ""


def project_pages(vault):
    """[{path, slug, title, keys, deadline, channels, next, status}] for each project page in the vault."""
    out, d = [], os.path.join(vault or "", "projects")
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if name.startswith("."):
            continue
        slug = name[:-3] if name.endswith(".md") else name
        p = os.path.join(d, name) if name.endswith(".md") else os.path.join(d, name, name + ".md")
        try:
            text = open(p, encoding="utf-8").read()
        except OSError:
            continue
        fl, body = split_front(text)
        if prop(fl, "type") not in ("project", ""):
            continue
        nxt = re.search(r"^##\s+Next step\s*\n+(?:[-*]\s+)?(.+)$", body, re.M)
        out.append({"path": os.path.relpath(p, vault).replace(os.sep, "/"), "slug": slug,
                    "title": prop(fl, "title") or slug, "keys": H.keys_in(prop(fl, "keys")),
                    "deadline": prop(fl, "deadline") or None, "channels": prop(fl, "channels") not in ("", "[]"),
                    "status": prop(fl, "status") or "live", "next": (nxt.group(1).strip() if nxt else "")})
    return out


# ── rows ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def prio_rank(p):
    return PRIORITIES.index(p) if p in PRIORITIES else len(PRIORITIES)


def snap(row):
    """What a meeting can move on a row: its ticket's fields and its open questions."""
    return [row.get("state"), row.get("priority"), row.get("owner"), row.get("due"), sorted(row.get("questions") or [])]


def ticket_row(iss, today):
    f = iss.get("fields") or {}
    return {"id": iss["key"], "key": iss["key"], "kind": "ticket", "title": field(iss, "summary") or "",
            "owner": field(iss, "assignee") or "", "state": field(iss, "status") or "", "priority": field(iss, "priority") or "",
            "due": f.get("duedate") or None, "labels": f.get("labels") or [], "questions": [], "asks": [], "audiences": [],
            "next": "", "own": False, "project": None}


def build_rows(vault, reports, facts, today, qstate=None, owner=""):
    """Every row of the board, before holds: tickets, projects, questions merged by key."""
    rows = {}
    for iss in focus_tickets(facts, today):
        rows[iss["key"]] = ticket_row(iss, today)
    for p in project_pages(vault):
        if p["status"] in ("done", "closed"):
            continue
        k = p["keys"][0] if p["keys"] else None
        if k and k in rows:
            rows[k]["project"] = p["path"]
            rows[k]["next"] = rows[k]["next"] or p["next"]
            rows[k]["deadline"] = p["deadline"]
            continue
        iss = facts_issue(facts, k) if k else None
        r = ticket_row(iss, today) if iss else {
            "id": k or f"p:{p['slug']}", "key": k, "kind": "project", "title": p["title"], "owner": owner, "state": "",
            "priority": "", "due": None, "labels": [], "questions": [], "asks": [], "audiences": [], "next": "", "project": None,
            # a project with no team thread is the owner's own: it stays in the vault
            "own": not p["channels"]}
        r.update(kind="project", project=p["path"], next=p["next"], deadline=p["deadline"], title=r["title"] or p["title"])
        if r["id"] in rows:
            continue
        rows[r["id"]] = r
    Q = questions_mod() if qstate else None
    for q in (Q.open_records(qstate) if qstate else []):
        lead = (q.get("lead") or q.get("keys") or H.keys_in(f"{Q.subject_line(q) or ''} {q.get('text') or ''}") or [None])[0]
        if lead and lead not in rows:
            iss = facts_issue(facts, lead)
            if iss and is_open(iss):
                rows[lead] = ticket_row(iss, today)
        if lead and lead in rows:
            r = rows[lead]
        else:
            srcs = q.get("sources") or []
            own = (bool(srcs) and all(any(s.startswith(o) for o in OWN_SOURCES) for s in srcs)) or \
                (owner and (q.get("who") or "").strip().lower() in (owner.lower(), owner.split()[0].lower()))
            r = rows.setdefault(f"q:{q['id']}", {"id": f"q:{q['id']}", "key": None, "kind": "question", "title": q.get("text") or "",
                                                  "owner": Q.answerer(q)[0], "state": "", "priority": "", "due": None, "labels": [],
                                                  "questions": [], "asks": [], "audiences": [], "next": "", "own": bool(own), "project": None,
                                                  "since": (q.get("first") or {}).get("date")})
        r["questions"].append(q["id"])
        said = Q.counted(Q.sentence(q), q)                    # a run of keys reads as its count, linking its note
        if lead:                                              # the row already names its ticket: the key is not said again
            said = re.sub(r"^" + re.escape(lead) + r"\s*(?:—|:|-)?\s*", "", said)
        r["asks"].append(dict(q, said=said[:1].upper() + said[1:]))
        if r["kind"] == "question":
            r["title"] = (Q.subject_line(q) or said) if not r.get("_titled") else r["title"]
            r["_titled"] = True
        if q.get("audience") and q["audience"] not in r["audiences"]:
            r["audiences"].append(q["audience"])
    return rows


def order(rows):
    """Jira priority first, then due date (none last), then the oldest first."""
    return sorted(rows, key=lambda r: (prio_rank(r.get("priority")), r.get("due") or "9999", r.get("since") or "9999", r["id"]))


# ── meetings: views of the board ──────────────────────────────────────────────────────────────────────────────────
def audiences(m):
    a = m.get("audience")
    return [str(x) for x in a] if isinstance(a, list) else re.findall(r"[\w-]+", str(a or ""))


def window(m, day):
    t = str(m.get("time") or "").strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", t):
        return None, None
    h, mi = map(int, t.split(":"))
    start = datetime.datetime.combine(day, datetime.time(h, mi))
    return start, start + datetime.timedelta(minutes=int(m.get("minutes") or 60))


def next_slot(m, doc, now):
    """The meeting's next day: today while it has not ended, else the next on its weekdays."""
    B = brief_mod()
    for d in B.meeting_slots(m, doc, now.date(), 1):
        _, end = window(m, d)
        if end is None or end > now:
            return d
    return None


def wants(row, m):
    """How much a row needs this meeting's audience: its questions for this meeting, carried meetings, and for the
    product audience projects and the top priority; 0 is not in the view."""
    aud, score = audiences(m), 0
    if m.get("key") in row.get("audiences") or []:
        score += 5
    if row.get("carried"):
        score += 4 * len(row["carried"])
    if "product" in aud and row.get("kind") == "project":
        score += 3
    if "product" in aud and row.get("priority") == "Highest":
        score += 2
    if any(a in aud for a in ("engineering", "qa")) and row.get("state") in ("Review", "In Progress", "Reopened"):
        score += 1
    if row.get("due") and score:
        score += 1
    return score


def view_rows(rows, m):
    """At most VIEW_MAX rows the meeting needs most; ties by priority, then due date."""
    scored = [(wants(r, m), r) for r in rows]
    return [r for _, r in sorted(((s, r) for s, r in scored if s > 0),
                                 key=lambda x: (-x[0], prio_rank(x[1].get("priority")), x[1].get("due") or "9999", x[1]["id"]))][:VIEW_MAX]


def settle_views(st, rows, now):
    """Each stored view whose meeting has ended is judged once: a row it did not move is carried one more meeting; a
    row it moved (or the scrum import ruled) starts again. → [(row id, carried count)] carried."""
    out = []
    for key, v in st["views"].items():
        if v.get("settled") or not v.get("end") or v["end"] > now.isoformat(timespec="minutes"):
            continue
        ruled = set(v.get("ruled") or [])
        for rid in v.get("rows") or []:
            rec = st["rows"].setdefault(rid, {"first": v["date"], "carried": []})
            row = rows.get(rid)
            if row is None:                                   # gone from the board: answered or closed
                rec["carried"] = []
                continue
            if rid not in ruled and snap(row) == v.get("snaps", {}).get(rid):
                if v["date"] not in rec["carried"]:
                    rec["carried"].append(v["date"])
                rec["snap"] = snap(row)                       # what it was when carried: a change after this is movement
                out.append((rid, len(rec["carried"])))
            else:
                rec["carried"] = []
        v["settled"] = now.isoformat(timespec="minutes")
    return out


def make_views(st, rows, meetings, doc, now):
    """{meeting key: {name, date, rows}} for each enabled meeting's next day; the stored view is fixed once the meeting
    has begun, so what it is judged on is what it was shown."""
    out = []
    for m in meetings or []:
        if not isinstance(m, dict) or not m.get("key") or m.get("enabled") is not True:
            continue
        day = next_slot(m, doc, now)
        if not day:
            continue
        start, end = window(m, day)
        v = st["views"].get(m["key"])
        if v and v.get("date") == day.isoformat() and start and now >= start:
            ids = v.get("rows") or []                        # begun: the view as shown
        else:
            ids = [r["id"] for r in view_rows(list(rows.values()), m)]
            st["views"][m["key"]] = {"date": day.isoformat(), "end": end.isoformat(timespec="minutes") if end else None,
                                     "rows": ids, "snaps": {i: snap(rows[i]) for i in ids}, "settled": None,
                                     "ruled": (v or {}).get("ruled") if v and v.get("date") == day.isoformat() else []}
        out.append({"key": m["key"], "name": m.get("name") or m["key"], "date": day, "time": m.get("time"),
                    "rows": [rows[i] for i in ids if i in rows]})
    return out


def view_heading(v):
    return f"{v['name']} · {v['date']:%a %m-%d}"


def view_anchor(v):
    """The Obsidian link target of a view's heading (`meetings/focus#Scrum with the PM · Mon 11-23`)."""
    return f"{BOARD[:-3]}#{view_heading(v)}"


# ── the page ──────────────────────────────────────────────────────────────────────────────────────────────────────
def clip(text, n):
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + " …"


def row_line(r, jira, today, short=False):
    """One row as one line (the item, owner, state, next step) and its detail folded under it: the ticket's summary,
    priority and dates, how long it has waited, every question it asks (presentation standard, 2026-11-20)."""
    k = link(r["key"], jira) if r.get("key") else ("*ela's own*" if r.get("own") else "**no ticket yet**")
    item = clip(r.get("title") or "", ITEM_CHARS)
    if r.get("project"):
        item = f"[[{r['project'][:-3]}|{item}]]"
    asks = r.get("asks") or []
    nxt = "" if r.get("kind") == "question" else \
        f"asks: {clip(asks[0].get('said') or asks[0].get('text'), NEXT_CHARS)}" if asks else clip(r.get("next") or "", NEXT_CHARS)
    state = r.get("state") or ("deadline " + r["deadline"][5:] if r.get("deadline") else "")
    if r.get("carried"):
        state = (state + " · " if state else "") + f"carried {len(r['carried'])}×"
    head = f"- {k} {item} — " + " · ".join(x for x in (r.get("owner") or "nobody", state, nxt) if x)
    if short:
        return [head]
    detail = [x for x in (linked(r.get("title") or "", jira) if len(r.get("title") or "") > ITEM_CHARS else None,
                          " · ".join(x for x in (r.get("priority"), f"due {r['due']}" if r.get("due") else None,
                                                 f"deadline {r['deadline']}" if r.get("deadline") else None,
                                                 f"on the board since {r['since']}" if r.get("since") else None,
                                                 ("carried at " + ", ".join(r["carried"])) if r.get("carried") else None) if x))
              if x]
    detail += [f"asks: {linked(q.get('said') or q.get('text'), jira)} · {q.get('who') or 'not named'} [[{QUESTIONS_PAGE[:-3]}#^{q['id']}|↗]]" for q in asks]
    return [head] + (["  > [!note]- detail"] + [f"  > {x}" for x in detail] if detail else [])


def render(rows, views, holds_on, today, jira, held_rows=()):
    L = [f"# MediaHub focus · {today:%a %Y-%m-%d}", "",
         "*One row per item MediaHub is pushing: Jira priority first, then due date; each row's detail is folded under it. "
         "A meeting is a view of this board. `ela: hold <subject or key> [until <date>]` parks a subject on every page, "
         "`ela: resume <subject>` brings it back; `ela: up <key> [why]` and `ela: down <key>` draft its Jira priority.*", ""]
    for v in views:
        L += [f"## {view_heading(v)}", ""]
        L += [l for r in v["rows"] for l in row_line(r, jira, today, short=True)] or ["Nothing on the board needs this meeting."]
        L.append("")
    shown = order(rows)
    L += ["## Now", ""]
    L += [l for r in shown[:SHOWN] for l in row_line(r, jira, today)] or ["Nothing is in focus."]
    if len(shown) > SHOWN:
        L += ["", f"## The rest ({len(shown) - SHOWN})", "", f"> [!note]- {len(shown) - SHOWN} more rows"]
        L += ["> " + l for r in shown[SHOWN:] for l in row_line(r, jira, today, short=True)]
    L.append("")
    if holds_on:
        L += [f"> [!note]- Held ({len(holds_on)}): " + " · ".join(linked(H.label(h), jira) for h in holds_on)
              + (f" — {len(held_rows)} row{'s' if len(held_rows) != 1 else ''} left out" if held_rows else ""), ""]
    L += ["---", "", f"Every team question, with its draft: [[{QUESTIONS_PAGE[:-3]}|open questions]] · moves wait as one batch "
          "on [[today]] · how this board is made: [[ela/about-this-vault|about this vault]]", ""]
    return "\n".join(L)


def front(props):
    return "---\n" + "".join(f'{k}: "{v}"\n' for k, v in props.items() if v) + "---\n\n"


def board(s, now=None, write=False, qstate=None, holds=None, meetings=None, doc=None, ruled=None):
    """The board as data and text. → {rows, views, held, text, carried}. With write, the store and meetings/focus.md."""
    now = now or datetime.datetime.now()
    today = now.date()
    vault, reports = s.get("vault") or "", s.get("reports") or ""
    facts = os.path.join(s.get("runtime") or "", "facts")
    jira = jira_base(s)
    if qstate is None:
        try:
            qstate = questions_mod().load(reports)
        except Exception:                                      # noqa: BLE001 — the board is written without them
            qstate = None
    if holds is None:
        holds, _ = H.refresh(reports, vault, today, write=write)
    if doc is None:
        try:
            doc = brief_mod().owner_day()
        except Exception:                                      # noqa: BLE001
            doc = {"meetings": [], "holidays": []}
    meetings = doc.get("meetings") if meetings is None else meetings
    st = load(reports)
    owner = owner_name(facts)
    allrows = build_rows(vault, reports, facts, today, qstate, owner)
    for rid, r in allrows.items():
        rec = st["rows"].setdefault(rid, {"first": r.get("since") or today.isoformat(), "carried": []})
        r["since"] = r.get("since") or rec["first"]
        r["carried"] = rec.get("carried") or []
    if ruled:                                                 # rows the meeting's report settled: an outcome, not a carry
        key, day, ids = ruled
        v = st["views"].get(key)
        if v and v.get("date") == day:
            v["ruled"] = sorted(set(v.get("ruled") or []) | set(ids))
    carried = settle_views(st, allrows, now)
    for rid, r in allrows.items():
        rec = st["rows"].get(rid, {})
        if rec.get("carried") and rec.get("snap") is not None and rec["snap"] != snap(r):
            rec["carried"], rec["snap"] = [], None            # it moved between meetings: carried no longer
        r["carried"] = rec.get("carried") or []
    held = {rid: H.holding(holds, [r["key"]] if r.get("key") else [], r.get("title") or "", today) for rid, r in allrows.items()}
    rows = {rid: r for rid, r in allrows.items() if not held[rid]}
    views = make_views(st, rows, meetings, doc, now)
    text = front({"type": "board", "date": today.isoformat()}) + render(list(rows.values()), views, H.active(holds, today), today, jira,
                                                                       [rid for rid, h in held.items() if h])
    if write:
        save(reports, st)
        if vault and os.path.isdir(vault):
            p = os.path.join(vault, BOARD)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            try:
                same = open(p, encoding="utf-8").read() == text
            except OSError:
                same = False
            if not same:
                with open(p + ".tmp", "w", encoding="utf-8") as f:
                    f.write(text)
                os.replace(p + ".tmp", p)
    return {"rows": rows, "all": allrows, "views": views, "held": {k: v for k, v in held.items() if v}, "text": text,
            "carried": carried, "state": st, "holds": holds}


def owner_name(facts):
    try:
        d = json.load(open(os.path.join(facts or "", "jira", "owner.json"), encoding="utf-8"))
        return ((((d.get("issues") or [{}])[0].get("fields") or {}).get("assignee")) or {}).get("displayName") or ""
    except (OSError, ValueError, AttributeError, IndexError):
        return ""


# ── words: up and down ────────────────────────────────────────────────────────────────────────────────────────────
def read_words(st, vault, today):
    """His `ela: up KEY [why]` and `ela: down KEY` lines, each stored once. → the new ones."""
    new = []
    for _, rel, _, verb, rest, lid, old in H.vault_words(vault, ("up", "down")):
        if lid in st["words"] or old in st["words"]:
            continue
        w = word(verb, rest, today, rel)
        if w:
            st["words"][lid] = w
            new.append(w)
    return new


def word(verb, rest, today, where):
    """An up or down line's word: its first key, its reason, `highest` when it says so; None without a key."""
    ks = H.keys_in(rest)
    if not ks:
        return None
    rest = H.unstamped(rest)
    return {"verb": verb, "key": ks[0], "why": KEY.sub("", re.sub(r"\bhighest\b", "", rest, flags=re.I)).strip(" -—:·"),
            "highest": bool(re.search(r"\bhighest\b", rest, re.I)), "at": today.isoformat(), "where": where}


# ── moves: the one batch ──────────────────────────────────────────────────────────────────────────────────────────
def roster_email(name):
    """A person's email from the roster by name; None when the roster does not know them."""
    if not name:
        return None
    try:
        sys.path.insert(0, os.path.join(HERE, "..", "team"))
        import team as T                                     # noqa: E402
        _, people = T.read_roster()
        hits = T.find(people, name)
        return hits[0].get("email") if len(hits) == 1 else None   # two people of that name: nobody is guessed
    except Exception:                                          # noqa: BLE001 — unknown: no assignment is drafted
        return None


def q(s):
    return shlex.quote(s)


def one_line(text):
    """A write's text on one line: the review note shows each write as one line, and a line break would split it."""
    return " — ".join(p.strip() for p in re.split(r"\n\s*\n|\n", text or "") if p.strip())


def drafts_dir(reports):
    return os.path.join(reports, "ela", "drafts", "focus")


def comment_write(reports, key, text, why, n_hint):
    """A Jira comment as a batch write: its text in a file the command names."""
    p = os.path.join(drafts_dir(reports), f"{key}-{hashlib.sha1(text.encode()).hexdigest()[:8]}.txt")
    return {"target": key, "command": f"ela jira comment {key} --from-file {p}", "why": why, "file": p, "text": text}


def answered_commands(reports):
    """Commands of this class already put to him and answered (applied, dropped or expired): never proposed again."""
    try:
        D = dry_mod()
        return {" ".join(w["command"].split()) for b in D.batches(reports) if b.get("class") == CLASS
                and b.get("state") in ("applied", "dropped", "expired") for w in b.get("writes") or []}
    except Exception:                                          # noqa: BLE001
        return set()


def raise_one(p):
    i = prio_rank(p)
    return PRIORITIES[max(0, min(i, 2) - 1)]              # Medium or below → High; High → Highest


def moves(s, b, today, scrum=None):
    """The writes the board asks for, before the answered ones are taken out: (writes, left out).
    `scrum`: scrum.py's drafted writes from the meeting's report."""
    reports = s.get("reports") or ""
    rows, allrows, st = b["rows"], b["all"], b["state"]
    W, left = [], []
    for w in sorted(st["words"].values(), key=lambda w: w["at"]):   # his up and down words, the plainest
        if w.get("batched"):
            continue
        k = w["key"]
        r = allrows.get(k) or {}
        iss = facts_issue(os.path.join(s.get("runtime") or "", "facts"), k)
        if w["verb"] == "up":
            to = "Highest" if w.get("highest") else "High"
            why = f"raised on the owner's word ({w['at']}{': ' + w['why'] if w.get('why') else ''})"
            W.append({"target": k, "command": f"ela jira priority {k} --to {to} --why {q(why)}", "why": why})
            if iss and not field(iss, "duedate"):
                due = today + datetime.timedelta(days=7)
                W.append({"target": k, "command": f"ela jira due {k} --date {due.isoformat()} --why {q('a raised ticket carries a date: one week, change it here before A')}",
                          "why": "raised with no due date: a week from today, edit before A"})
            if iss and not field(iss, "assignee"):
                email = roster_email((r.get("asks") or [{}])[0].get("who")) if r.get("asks") else None
                if email:
                    W.append({"target": k, "command": f"ela jira assign {k} --assignee {email}",
                              "why": "raised with nobody on it: who its question names"})
                else:
                    left.append(f"{k}: raised with no assignee; name one in the review note (`ela jira assign {k} --assignee <email>`)")
        else:
            W.append({"target": k, "command": f"ela jira priority {k} --to Medium --why {q('lowered on the owner word ' + w['at'])}",
                      "why": f"down on the owner's word ({w['at']})"})
    for x in scrum or []:                                     # the scrum's action items, mapped to rows
        W.append(x)
    for rid, r in rows.items():                               # carried through two meetings: push, not a third carry
        if len(r.get("carried") or []) < CARRY_MAX:
            continue
        times = len(r["carried"])
        if not r.get("key"):
            continue                                          # its ticket is drafted below
        email = None if r.get("owner") else roster_email((r.get("asks") or [{}])[0].get("who") if r.get("asks") else None)
        if not r.get("owner") and email:
            W.append({"target": r["key"], "command": f"ela jira assign {r['key']} --assignee {email}",
                      "why": f"carried through {times} meetings with nobody on it: assign who the question names"})
        else:
            to = raise_one(r.get("priority"))
            why = f"carried through {times} meetings with no ruling ({', '.join(d[5:] for d in r['carried'])})"
            if to != r.get("priority"):
                W.append({"target": r["key"], "command": f"ela jira priority {r['key']} --to {to} --why {q(why)}", "why": why})
            else:
                text = (f"This has been on the MediaHub board through {times} meetings without a decision "
                        f"({', '.join(d[5:] for d in r['carried'])}). Can we settle the next step here?")
                W.append(comment_write(reports, r["key"], text, why, 0))
    creates = sorted((r for r in rows.values() if not r.get("key") and not r.get("own")),
                     key=lambda r: (-len(r.get("carried") or []), r.get("since") or "9999"))
    for r in creates[:CREATES_MAX]:
        q0 = (r.get("asks") or [{}])[0]
        said = q0.get("said") or q0.get("text") or ""
        summary = clip(f"{r.get('title')}: {said}" if r.get("title") and r.get("title") not in said else said or r.get("title") or "", 150)
        desc = one_line("Raised on the MediaHub focus board"
                + (f" ({(q0.get('first') or {}).get('where')}, {(q0.get('first') or {}).get('date')})" if q0.get("first") else "")
                + ". It has no ticket yet; this one tracks it.\n\n"
                + (f"Question: {said}\n" if said else "")
                + "".join(f"\nThread: {u}" for u in re.findall(r"https://[\w.-]+\.slack\.com/archives/\S+", " ".join(q0.get("sources") or []) + " " + (q0.get("raw") or ""))))
        email = roster_email(r.get("owner"))
        W.append({"target": r["id"], "command": f"ela jira create --project MH --type Task --summary {q(summary)} --description {q(desc)}"
                  + (f" --assignee {email}" if email else ""), "why": "a board row with no ticket: Jira is where MH items are tracked"})
    if len(creates) > CREATES_MAX:
        left.append(f"{len(creates) - CREATES_MAX} more rows without a ticket wait for the next batch")
    try:                                                      # what the open batch already asks stays in it: one batch, added to
        D = dry_mod()
        W = [{k: w[k] for k in ("target", "command", "why")} for bt in D.batches(reports) if bt.get("class") == CLASS
             and bt.get("scope") == SCOPE and bt.get("state") == "open" for w in bt.get("writes") or []] + W
    except Exception:                                          # noqa: BLE001
        pass
    done = answered_commands(reports)
    out, seen = [], set()
    for w in W:
        c = " ".join(w["command"].split())
        if c in done or c in seen:
            continue
        seen.add(c)
        out.append(w)
    for i, w in enumerate(out, 1):
        w["n"] = i
    return out, left


def store_batch(s, writes, left, today, st=None):
    """The writes as one dry-run batch (the comment files written first); his up/down words marked batched."""
    reports = s.get("reports") or ""
    if not writes:
        return dry_mod().make_batch(reports, CLASS, SCOPE, [], left, today)   # nothing left: an open batch settles
    for w in writes:
        if w.get("file"):
            os.makedirs(os.path.dirname(w["file"]), exist_ok=True)
            with open(w["file"], "w", encoding="utf-8") as f:
                f.write(w["text"] + "\n")
    clean = [{k: w[k] for k in ("n", "target", "command", "why")} for w in writes]
    b = dry_mod().make_batch(reports, CLASS, SCOPE, clean, left, today)
    if st is not None:
        for w in st["words"].values():
            if not w.get("batched") and any(x["target"] == w["key"] for x in clean):
                w["batched"] = b["id"] if b else None
    return b


# ── the verb ──────────────────────────────────────────────────────────────────────────────────────────────────────
def emit(a, obj, lines):
    if getattr(a, "json", False):
        print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))
    else:
        print("\n".join(lines))


def cmd_board(a):
    s = site()
    b = board(s, write=a.write)
    obj = {"rows": len(b["rows"]), "held": sorted(b["held"]), "views": [{"key": v["key"], "date": v["date"].isoformat(),
           "rows": [r["id"] for r in v["rows"]]} for v in b["views"]], "carried": b["carried"]}
    emit(a, obj, [b["text"]] if not a.write else [f"{BOARD}: {len(b['rows'])} rows, {len(b['held'])} held, "
                                                  + ", ".join(f"{v['key']} {v['date']:%m-%d} {len(v['rows'])} rows" for v in b["views"])])


def said(a, out, lines):
    """A verb's answer: the JSON the vault watcher reads (ok:false is exit 0, its `why` the reason), else a line."""
    if getattr(a, "json", False):
        print(json.dumps(out, ensure_ascii=False))
    else:
        print("\n".join(lines), file=sys.stdout if out.get("ok") else sys.stderr)
        if not out.get("ok"):
            sys.exit(EX_NOTFOUND)


def cmd_hold(a):
    """`ela focus hold|resume <rest of the line> [--until X] [--where <rel>#…] [--apply] [--json]`."""
    s = site()
    today = datetime.date.today()
    rest = " ".join(a.subject)
    st = H.load(s.get("reports"))
    H.seed(st, today)
    key = H.word_key(a.where, a.cmd, rest) if a.where else None
    if key and key in st["read"]:
        return said(a, {"ok": True, "already": True, "verb": a.cmd, "subject": rest}, [f"{a.cmd}: already read ({a.where})"])
    subject, until = H.split_subject(H.unstamped(rest))
    until = a.until or until
    where = a.where.split("#", 1)[0] if a.where else "session"
    h = H.put_hold(st, subject, until, today, where) if a.cmd == "hold" else H.resume(st, subject, today, where)
    if not h:
        why = f"nothing {'to hold' if a.cmd == 'hold' else 'held'} by {subject!r}"
        return said(a, {"ok": False, "already": False, "verb": a.cmd, "subject": subject, "why": why}, [f"{a.cmd}: {why}"])
    if key:
        st["read"][key] = today.isoformat()
    if a.apply:
        H.save(s.get("reports"), st)
    return said(a, {"ok": True, "already": False, "verb": a.cmd, "subject": h["subject"], "until": h.get("until"), "applied": a.apply},
                [f"{'held' if a.cmd == 'hold' else 'resumed'}: {H.label(h)}" + ("" if a.apply else " (dry run; --apply stores it)")])


def cmd_holds(a):
    s = site()
    st = H.for_reports(s.get("reports"))
    hs = sorted(st["holds"].values(), key=lambda h: (bool(h.get("ended")), h.get("since") or ""))
    emit(a, hs, [f"{'ended ' + h['ended'] if h.get('ended') else 'held'} · {H.label(h)}" for h in hs] or ["nothing held"])


def cmd_word(a):
    """`ela focus up|down <KEY and reason> [--why W] [--highest] [--where <rel>#…] [--apply] [--json]`: the word is stored and,
    with --apply, the batch is drafted at once, so today.md asks it on the next sync."""
    s = site()
    today = datetime.date.today()
    rest = " ".join(a.key)
    st = load(s.get("reports"))
    key = H.word_key(a.where, a.cmd, rest) if a.where else None
    if key and key in st["words"]:
        return said(a, {"ok": True, "already": True, "verb": a.cmd, "key": st["words"][key]["key"], "batch": st["words"][key].get("batched")},
                    [f"{a.cmd}: already read ({a.where})"])
    w = word(a.cmd, rest + (" " + a.why if getattr(a, "why", "") else "") + (" highest" if getattr(a, "highest", False) else ""),
             today, a.where.split("#", 1)[0] if a.where else "session")
    if not w:
        return said(a, {"ok": False, "already": False, "verb": a.cmd, "why": f"no ticket key in {rest!r}"}, [f"{a.cmd}: no ticket key in {rest!r}"])
    st["words"][key or hashlib.sha1(f"session|{a.cmd}|{rest}|{today}".encode()).hexdigest()[:12]] = w
    batch = None
    if a.apply:
        save(s.get("reports"), st)
        batch = run_moves(s, True)["batch"]
    return said(a, {"ok": True, "already": False, "verb": a.cmd, "key": w["key"], "batch": batch, "applied": a.apply},
                [f"{a.cmd} {w['key']}: " + (f"in batch {batch}, asked on today.md" if batch else "dry run; --apply stores it and drafts the batch")])


def run_moves(s, apply, scrum=None, now=None, ruled=None):
    now = now or datetime.datetime.now()
    b = board(s, now=now, write=apply, ruled=ruled)
    st = b["state"]
    new = read_words(st, s.get("vault"), now.date())
    writes, left = moves(s, b, now.date(), scrum)
    batch = store_batch(s, writes, left, now.date(), st) if apply else None
    if apply:
        save(s.get("reports") or "", st)
    return {"writes": writes, "left_out": left, "batch": batch["id"] if batch else None, "words": new}


def cmd_moves(a):
    r = run_moves(site(), a.apply)
    emit(a, r, [f"{w['n']}. {w['command']} — {w['why']}" for w in r["writes"]] + [f"- {x}" for x in r["left_out"]]
         + [f"batch: {r['batch']}" if r["batch"] else ("nothing to move" if not r["writes"] else "dry run; --apply stores the batch")])


def cmd_scrum(a):
    import scrum as S                                          # noqa: E402
    sys.exit(S.cmd(a))


def main():
    ap = argparse.ArgumentParser(prog="ela focus", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", help="the site's env file (bin/ela passes it; the Jira base URL is read from site.json's)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("board", help="the board and its meeting views; --write writes meetings/focus.md")
    p.add_argument("--write", action="store_true"); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_board)
    WHERE = "the vault watcher's `<note rel>#<line>`: the line read once, whoever reads it first"
    p = sub.add_parser("hold", help="park a subject on every page: SUBJECT [until DATE|EVENT]; a dry run unless --apply")
    p.add_argument("subject", nargs="+"); p.add_argument("--until"); p.add_argument("--where", help=WHERE)
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_hold)
    p = sub.add_parser("resume", help="end a hold; a dry run unless --apply")
    p.add_argument("subject", nargs="+"); p.add_argument("--where", help=WHERE)
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_hold, until=None)
    p = sub.add_parser("holds", help="every hold, live first")
    p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_holds)
    p = sub.add_parser("up", help="ask for a priority raise on KEY (High, --highest Highest), a due date and an assignee when missing; a dry run unless --apply")
    p.add_argument("key", nargs="+"); p.add_argument("--why", default=""); p.add_argument("--highest", action="store_true")
    p.add_argument("--where", help=WHERE); p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_word)
    p = sub.add_parser("down", help="ask for KEY's priority back to Medium; a dry run unless --apply")
    p.add_argument("key", nargs="+"); p.add_argument("--where", help=WHERE); p.add_argument("--apply", action="store_true")
    p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_word)
    p = sub.add_parser("moves", help="draft the batch of Jira moves the board asks for; --apply stores it as a dry-run batch")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_moves)
    p = sub.add_parser("scrum", help="after the scrum: its Read AI report from mail, mapped to rows, drafted into the batch")
    p.add_argument("--date", help="the meeting's day (default today)")
    p.add_argument("--mail-file", help="a message as `ela mail read --json` prints it, instead of reading mail")
    p.add_argument("--apply", action="store_true", help="store the batch (Jira is untouched until his A)")
    p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_scrum)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
