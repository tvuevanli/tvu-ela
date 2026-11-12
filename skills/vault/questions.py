#!/usr/bin/env python3
"""Open team questions: one record each, kept until the world answers it or the owner drops it by word. Stdlib only.

L1, a module of the vault verb (`ela vault questions`, and every `ela vault sync`). A question is a box he lists at a
meeting or on a project page: something a team member answers about the product or the team. It is not an ask of
ela's (a write ela proposes): those expire after three working mornings (ADR 0014); a team question does not
(ADR 0016). The records live in <reports>/ela/questions.json:

    {"questions": {id: {id, text, raw, who, keys, lead, thing, audience, first: {date, where}, meetings: [date],
                        sources: [where#gist], base: {at, tickets: {KEY: {status, assignee, due, resolution}}},
                        status: open|closed|dropped, outcome, closed, by, draft}},
     "built": {meeting note: digest of the bytes ela last wrote}}

Each pass reads every meeting note and project page for boxes (a hand-written note is read, never written), merges the
same question by ticket and meaning, and closes an open one by outcome: its ticket assigned, moved, closed, re-dated,
answered in a comment by someone other than the owner, or split; its thread answered. His tick or `ela:` line closes it
too. Age never closes one. meetings/open-questions.md is the standing page; today.md carries one line.

Usage:
    questions.py --help      this text; the verb is `ela vault questions [--seed NOTE ...] [--apply] [--json]`
"""
import datetime, hashlib, json, os, re, sys

QUESTIONS_PAGE = "meetings/open-questions.md"
NUDGE_EVERY = 3                         # listed at this many meetings without an outcome: one ask on today.md
PAGE_LINES = 48                         # the standing page fits one screen
TEXT_CHARS = 110
STATE = ("ela", "questions.json")
BOX = re.compile(r"^([ \t]*)[-*][ \t]+\[([ xX])\][ \t]+(\S.*?)[ \t]*$")
BULLET = re.compile(r"^([ \t]*)[-*][ \t]+(?!\[[ xX]\])(\S.*?)[ \t]*$")
HEAD = re.compile(r"^(#{2,3})[ \t]+(.+?)[ \t]*$")
QID = re.compile(r"[ \t]\^(q-[0-9a-f]{6})[ \t]*$")
QREF = re.compile(r"#\^(q-[0-9a-f]{6})\b")
KEY = re.compile(r"(?<![\w/#=.-])([A-Z][A-Z0-9]{1,9}-\d{1,6})(?![\w-])")
SLACK = re.compile(r"https://[\w.-]+\.slack\.com/archives/[A-Z0-9]+/p\d{16}")
SINCE = re.compile(r"[ \t]*·[ \t]*since[ \t]+\d{2}-\d{2}\b")
DATED = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})-(.+)\.md$")    # meetings/<yyyy-mm-dd>-<key>.md, or his compact <yyyymmdd>-
BOT = re.compile(r"^(?:Automation\b|Slack$|Jira$|GitLab|GitHub|Jenkins)", re.I)
STOP = set("a an and are as at be by can do does for from has have how if in is it its of on or the then this to was "
           "what when where which who whom why will with".split())
GENERIC_WHO = re.compile(r"^(?:the team|each holder|qa|media lead|nobody|not named)$", re.I)


# ── reading a line ────────────────────────────────────────────────────────────────────────────────────

def visible(line):
    t = re.sub(r"\[\[[^\]|]*\|([^\]]+)\]\]", r"\1", line or "")
    t = re.sub(r"\[\[([^\]]+)\]\]", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    return " ".join(QID.sub("", t).split())


def split_who(vis):
    """(question, who) from a box's visible text: who is what follows the last ` · ` when it names people, not a
    proposal or an age (`ela proposes: …`, `since 11-11`)."""
    parts = [p.strip() for p in vis.split(" · ") if not re.match(r"^ela proposes\b", p.strip(), re.I)]
    tail = [p for p in parts[1:] if not re.match(r"^(?:since\b|listed at\b|ela proposes\b|\d{2}-\d{2}\b)", p, re.I)]
    if len(parts) > 1 and tail:
        who = tail[-1]
        if "?" not in who and len(who) <= 60 and not KEY.search(who):
            q = " · ".join(p for p in parts if p != who and not re.match(r"^(?:since\b|listed at\b)", p, re.I))
            return q, who
    return " · ".join(p for p in parts if not re.match(r"^(?:since\b|listed at\b)", p, re.I)), None


def keys_in(vis):
    return list(dict.fromkeys(KEY.findall(vis or "")))


def lead_keys(vis):
    """The tickets whose outcome answers the question: when the line opens with a list of three or more keys joined
    only by commas, slashes, `and`, `plus` or an aside in brackets (owners for these, past due in Review), every one;
    otherwise the first key (`MH-2564 …, which would fix A, B and C` is MH-2564's question)."""
    ms = list(KEY.finditer(vis or ""))
    best, run = [], []
    for i, m in enumerate(ms):
        sep = re.sub(r"\([^)]*\)", "", vis[ms[i - 1].end():m.start()]) if i else ""
        if run and re.fullmatch(r"[\s,/]*(?:and|plus)?[\s,/]*", sep):
            run.append(m.group(1))
        else:
            run = [m.group(1)]
        if len(run) > len(best):
            best = list(run)
    if len(best) >= 3 and best[0] == ms[0].group(1):
        return list(dict.fromkeys(best))
    return [ms[0].group(1)] if ms else []


def words(text):
    return {w for w in re.findall(r"[\w.+/-]+", visible(text).lower()) if w not in STOP and len(w) > 1}


def people(who):
    return {p.strip().lower() for p in re.split(r",|\+| and |/", who or "") if p.strip()}


def subject(text):
    """A question's subject: its words before the first ` — ` or `:`, when that is two to six words and not a key."""
    head = re.split(r" — |:", visible(text), 1)
    if len(head) < 2:
        return None
    w = re.findall(r"[\w'’.-]+", head[0].lower())
    return " ".join(w) if 2 <= len(w) <= 6 and not KEY.search(head[0]) else None


def gist(text):
    return re.sub(r"\s+", " ", visible(text)).strip().lower()


def qid(text, where):
    return "q-" + hashlib.sha1(f"{gist(text)}|{where}".encode()).hexdigest()[:6]


# ── reading a note ────────────────────────────────────────────────────────────────────────────────────

def note_date(rel, text):
    """A meeting note's date: its `date:` property, else the date its title ends in, else its file name's."""
    m = re.search(r"^date:\s*['\"]?(\d{4}-\d{2}-\d{2})", text or "", re.M)
    if m:
        return m.group(1)
    m = re.search(r"^#[ \t]+.*?(\d{4}-\d{2}-\d{2})[ \t]*$", text or "", re.M)
    if m:
        return m.group(1)
    m = DATED.match(os.path.basename(rel))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def audience(rel, keys=()):
    """The meeting a note is for: its file name less a leading date, matched to meetings.yaml's keys exactly or on a
    hyphen boundary either way (his `sync-eng-qa` is the book's `sync-eng-qa-ux`)."""
    name = os.path.basename(rel)[:-3]
    m = DATED.match(os.path.basename(rel))
    part = m.group(4) if m else name
    for k in keys:
        if k == part or k.startswith(part + "-") or part.startswith(k + "-"):
            return k
    return part


def boxes(text):
    """Every box in a note outside its Ruled section: [{raw, ticked, section, parent, id}]. section is the `## `
    heading it sits under, parent the bullet a nested box hangs from."""
    out, section, parents, skip = [], None, [], False
    body = text.split("\n---\n", 1)[1] if text.startswith("---\n") and "\n---\n" in text else text
    for line in body.splitlines():
        h = HEAD.match(line)
        if h:
            if len(h.group(1)) == 2:
                section = re.sub(r"^\d+\.[ \t]*", "", h.group(2)).strip()
                skip, parents = section.lower() == "ruled", []
            continue
        if skip:
            continue
        b = BOX.match(line)
        if b:
            ind = len(b.group(1).expandtabs(4))
            parent = next((t for i, t in reversed(parents) if i < ind), None)
            q = QID.search(line)
            out.append({"raw": QID.sub("", b.group(3)).strip(), "ticked": b.group(2) != " ", "section": section,
                        "parent": parent, "id": q.group(1) if q else None, "line": line})
            continue
        p = BULLET.match(line)
        if p:
            ind = len(p.group(1).expandtabs(4))
            parents = [(i, t) for i, t in parents if i < ind] + [(ind, p.group(2))]
    return out


def ruled_lines(text):
    """{date: [visible line]} under a note's `## Ruled` (the verb's form)."""
    out, day, on = {}, None, False
    for line in (text or "").splitlines():
        if re.match(r"^##[ \t]+", line):
            on, day = bool(re.match(r"^##[ \t]+Ruled[ \t]*$", line)), None
            continue
        d = re.match(r"^###[ \t]+(\d{4}-\d{2}-\d{2})", line)
        if on and d:
            day = d.group(1); continue
        if on and day and line.startswith("- "):
            out.setdefault(day, []).append(visible(line[2:]))
    return out


def ela_wrote(text):
    fl = text.split("\n---\n", 1)[0] if text.startswith("---\n") else ""
    return bool(re.search(r"^by:\s*['\"]?ela['\"]?\s*$", fl, re.M)) or bool(re.search(r"^##[ \t]+To raise[ \t]*$", text, re.M))


def meeting_candidates(rel, text, keys=(), mtime=None):
    """The open-question candidates a meeting note lists, each with where it was listed and when."""
    day = note_date(rel, text)
    aud = audience(rel, keys)
    out = []
    for b in boxes(text):
        if b["section"] and b["section"].lower() in ("where things stand",):
            continue
        out.append(dict(b, where=rel, date=day, audience=aud, kind="meeting", mtime=mtime, hand=not ela_wrote(text)))
    carried = {}
    for d, lines in ruled_lines(text).items():             # the verb's Ruled lines: "no change: raised again" was listed then
        for l in lines:
            if re.search(r"(?:no change|no ticket to read|not read)[^·]*$", l) or "raised again" in l or "· carried" in l:
                carried.setdefault(gist(re.split(r" · (?:no change|no ticket to read|not read|carried)", l)[0]), set()).add(d)
    for c in out:
        g = gist(re.sub(r"[ \t]*·[ \t]*since[ \t]+\d{2}-\d{2}\b", "", c["raw"]))
        c["ruled_dates"] = sorted(carried.get(g, ()))
    return out


def project_candidates(rel, head, section_at):
    """Unticked boxes under a project page's Open questions heading."""
    out = []
    for b in boxes(head):
        if (b["section"] or "").lower() != "open questions" or b["ticked"]:
            continue
        out.append(dict(b, where=rel, date=None, audience=None, kind="project", mtime=None, hand=True, ruled_dates=[]))
    return out


# ── the records ───────────────────────────────────────────────────────────────────────────────────────

def load(reports):
    try:
        d = json.load(open(os.path.join(reports or "", *STATE), encoding="utf-8"))
        return {"questions": d.get("questions") or {}, "built": d.get("built") or {}}
    except (OSError, ValueError, AttributeError):
        return {"questions": {}, "built": {}}


def save(reports, state, write):
    p = os.path.join(reports or "", *STATE)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    write(p, json.dumps(state, indent=1, ensure_ascii=False, sort_keys=True) + "\n")


def ticket_state(issue):
    f = (issue or {}).get("fields") or {}
    return {"status": (f.get("status") or {}).get("name"), "assignee": (f.get("assignee") or {}).get("displayName"),
            "due": f.get("duedate"), "resolution": (f.get("resolution") or {}).get("name")}


def same_question(rec, c, cvis):
    """Whether candidate c is record rec's question: never two boxes of one note; the same tickets (one set covering the
    other, or half the smaller with an answerer in common); else the same numbers (two or more) with an answerer in
    common; else most of the words."""
    if any(s.split("#", 1)[0] == c["where"] for s in rec["sources"]):
        return False
    a, b = set(rec["keys"]), set(keys_in(cvis))
    pa, pb = people(rec.get("who")), people(split_who(cvis)[1])
    common = bool(pa & pb) or not pa or not pb
    if a and b:
        if a <= b or b <= a:
            return True
        return len(a & b) * 2 >= min(len(a), len(b)) and common
    sa, sb = subject(rec["text"]), subject(split_who(cvis)[0])
    if sa and sa == sb and common:                       # `This week's deploy — …` and `This week's deploy: …`
        return True
    wa, wb = words(rec["text"]), words(cvis)
    nums = {w for w in wa & wb if re.search(r"\d", w) and not re.fullmatch(r"\d{2}-\d{2}", w)}
    if len(nums) >= 2 and common:
        return True
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= 0.6 and common


def same_audience(a, b):
    """One meeting's two names (his `sync-eng-qa`, the book's `sync-eng-qa-ux`), or either unknown."""
    return not a or not b or a == b or a.startswith(b + "-") or b.startswith(a + "-")


def listed_at(c, today, meeting_start):
    """When the candidate's note last said the question was open: an earlier meeting's start, else the note's write."""
    d = c.get("date")
    iso = today.isoformat()
    if d and d < iso:
        return meeting_start(c.get("audience"), datetime.date.fromisoformat(d))
    t = c.get("mtime")
    return datetime.datetime.fromtimestamp(t).astimezone() if t else None


GENERIC_SECTION = re.compile(r"^(?:to raise|carried|waiting on you|waiting on \w+\b.*|if time allows|open questions|other)$", re.I)


def thing_of(c, projects):
    """What a question belongs to: the project page whose key its section, parent bullet or own line names, else that
    ticket, else its section as a topic. projects: {ticket key: project page rel}."""
    if c["kind"] == "project":
        return {"kind": "project", "ref": c["where"]}
    for src in (c.get("section"), c.get("parent"), c["raw"]):
        ks = keys_in(visible(src or ""))
        for k in ks:
            if k in projects:
                return {"kind": "project", "ref": projects[k], "key": k}
        if ks and not (src is c.get("section") and GENERIC_SECTION.match(visible(src).strip())):
            name = visible(src).split(" — ")[0] if src is not c["raw"] else ks[0]
            return {"kind": "ticket", "key": ks[0], "name": re.sub(r"\*+", "", name)[:60]}
    sec = visible(c.get("section") or "").strip()
    return {"kind": "topic", "name": "Other" if not sec or GENERIC_SECTION.match(sec) else sec[:60]}


def raised(c, vis, today):
    """The day a candidate says its question was first raised: its note's date, a Ruled date it was carried at, its
    `since MM-DD`, whichever is earliest and not after today."""
    first = min([d for d in [c.get("date"), *c.get("ruled_dates", [])] if d and d <= today.isoformat()] or [today.isoformat()])
    since = re.search(r"·[ \t]*since[ \t]+(\d{2})-(\d{2})\b", vis)
    if since:
        sd = datetime.date(today.year, int(since.group(1)), int(since.group(2)))
        first = min(first, (sd if sd <= today else sd.replace(year=today.year - 1)).isoformat())
    return first


def harvest(state, cands, now, facts_issue, projects=None, snapshot=None, meeting_start=None, keys=()):
    """Candidates into records: a box with its id, or one already a source, is that record; else the same question by
    ticket and meaning across notes merges into an open record; else a new record. A ticked box closes it (his tick).
    A record each listing's meeting date is added to; a closed one is never reopened by an old box.
    → the ids touched."""
    qs = state["questions"]
    today = now.date()
    meeting_start = meeting_start or (lambda aud, d: datetime.datetime.combine(d, datetime.time(9)).astimezone())
    by_src = {s: i for i, r in qs.items() for s in r["sources"]}
    touched = []
    for c in sorted(cands, key=lambda c: (c.get("date") or "9999", c["where"])):
        vis = visible(c["raw"])
        src = c["where"] + "#" + gist(SINCE.sub("", c["raw"]))
        rid = c.get("id") if c.get("id") in qs else by_src.get(src)
        rec = qs.get(rid) if rid else None
        if rec is None:
            rec = next((r for r in sorted(qs.values(), key=lambda r: r["first"]["date"]) if r["status"] == "open"
                        and same_audience(r.get("audience"), c.get("audience")) and same_question(r, c, vis)), None)
        q, who = split_who(vis)
        if rec is None:
            if c["ticked"]:
                continue                                    # ticked before ela ever saw it: not a question to keep
            rec = {"id": qid(c["raw"], c["where"]), "text": q, "raw": c["raw"], "who": who, "keys": keys_in(vis),
                   "lead": lead_keys(vis), "thing": thing_of(c, projects or {}), "audience": c.get("audience"),
                   "first": {"date": today.isoformat(), "where": c["where"]}, "meetings": [], "sources": [], "status": "open",
                   "base": None}
            while rec["id"] in qs:
                rec["id"] = "q-" + hashlib.sha1(rec["id"].encode()).hexdigest()[:6]
            qs[rec["id"]] = rec
        first = raised(c, vis, today)                      # an older note read later moves the first raising back
        if first < rec["first"]["date"]:
            rec["first"] = {"date": first, "where": c["where"]}
        if src not in rec["sources"]:
            rec["sources"].append(src)
            by_src[src] = rec["id"]
        if rec["status"] != "open":
            continue                                        # closed stays closed: an old box does not reopen it
        if c["kind"] == "meeting":                         # each meeting held that listed it; a note for a later day counts then
            held = {c["date"]} if c.get("date") and c["date"] <= today.isoformat() else set()
            rec["meetings"] = sorted(set(rec["meetings"]) | held | set(c.get("ruled_dates") or []))
        if c["ticked"]:
            rec.update(status="closed", outcome=f"ticked on {c['where']}", closed=today.isoformat(), by="owner")
            touched.append(rec["id"]); continue
        if (c.get("date") or "") >= rec.get("worded", "") or not rec.get("who"):   # the newest listing words it
            rec.update(text=q, raw=c["raw"], who=who or rec.get("who"), worded=max(c.get("date") or "", rec.get("worded", "")))
            rec["keys"] = list(dict.fromkeys(rec["keys"] + keys_in(vis)))
            rec["lead"] = lead_keys(vis) or rec["lead"]
            if c.get("audience") and not rec.get("audience"):
                rec["audience"] = c["audience"]
        at = (listed_at(c, today, meeting_start) if c["kind"] == "meeting" else None) or now
        base = rec.get("base")
        # the base is the question's last listing as open: its first, or a later hand-written box (a change before that
        # box was written did not answer it); a listing ela wrote never moves it
        if base is None or c.get("hand") and at.isoformat(timespec="seconds") > base["at"]:
            old_note = c.get("date") and c["date"] < today.isoformat()
            snap = ((snapshot or {}).get(f"{c.get('audience')}@{c.get('date')}") or {}) if old_note else {}
            rec["base"] = {"at": at.isoformat(timespec="seconds"),
                           "tickets": {k: dict(ticket_state(facts_issue(k)), **snap.get(k, {})) for k in rec["lead"]}}
        touched.append(rec["id"])
    return touched


def ticket_change(issue, base, at, owner, linked_created):
    """What changed on one ticket after `at` against its state then: closed, moved, assigned, re-dated, answered in a
    comment by someone other than the owner, split. Words or None."""
    if not issue:
        return None
    cur, bits = ticket_state(issue), []
    if cur["resolution"] and not (base or {}).get("resolution"):
        bits.append(f"closed ({cur['resolution']})")
    elif cur["status"] and base and base.get("status") and cur["status"] != base["status"]:
        bits.append(f"moved to {cur['status']}")
    if cur["assignee"] and base is not None and cur["assignee"] != base.get("assignee"):
        bits.append(f"assigned to {cur['assignee']}")
    if cur["due"] and base is not None and cur["due"] != base.get("due"):
        bits.append(f"due {cur['due']}")
    authors = []
    f = issue.get("fields") or {}
    for c in issue.get("comments") or ((f.get("comment") or {}).get("comments") or []):
        a = (c.get("author") or {}).get("displayName") or ""
        t = when(c.get("created"))
        if t and t > at and a and a != owner and not BOT.match(a) and a not in authors:
            authors.append(a)
    if authors:
        bits.append("answered in a comment by " + ", ".join(authors))
    new = [k for k, created in linked_created if created and created > at]
    if new:
        bits.append("opened " + ", ".join(new))
    return "; ".join(bits) or None


def when(v):
    try:
        return datetime.datetime.fromisoformat(re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", str(v or "").replace("Z", "+00:00")))
    except ValueError:
        return None


def settle(state, now, facts_issue, owner="", thread=None):
    """Each open record against the world: its lead tickets (every one for a list) and its thread. An outcome closes it,
    written on it. → [(id, outcome)]."""
    out = []
    for r in state["questions"].values():
        if r["status"] != "open" or not r.get("base"):
            continue
        at = when(r["base"]["at"])
        said = {}
        for k in r["lead"]:
            d = facts_issue(k)
            if not d:
                continue
            f = d.get("fields") or {}
            linked = [((l.get("outwardIssue") or l.get("inwardIssue") or {}).get("key")) for l in f.get("issuelinks") or []] + \
                     [x.get("key") for x in f.get("subtasks") or []]
            created = [(x, when(((facts_issue(x) or {}).get("fields") or {}).get("created"))) for x in linked if x]
            w = ticket_change(d, r["base"]["tickets"].get(k), at, owner, created)
            if w:
                said[k] = w
        th = thread(r["raw"], at) if thread else None
        if r["lead"] and len(r["lead"]) >= 3:
            done = all(k in said for k in r["lead"])
            r["evidence"] = "; ".join(f"{k} {w}" for k, w in said.items()) or None
        else:
            done = bool(said) or bool(th)
        if done or th:
            words_ = "; ".join([(f"{k} {w}" if len(r["lead"]) > 1 else w) for k, w in said.items()] + ([th] if th else []))
            r.update(status="closed", outcome=words_, closed=now.date().isoformat(), by="world")
            out.append((r["id"], words_))
    return out


def by_word(state, page_text, today):
    """His ticks and `ela:` lines on the standing page: a ticked line closes its question; `ela: drop` under it drops
    it; other words under it close it with those words. → ([(id, outcome)], consumed `ela:` lines)."""
    out, consumed, cur = [], [], None
    qs = state["questions"]
    for line in (page_text or "").splitlines():
        b = BOX.match(line)
        if b:
            m = QID.search(line)
            cur = m.group(1) if m and m.group(1) in qs else None
            if cur and b.group(2) != " " and qs[cur]["status"] == "open":
                qs[cur].update(status="closed", outcome="closed by your tick", closed=today.isoformat(), by="owner")
                out.append((cur, "closed by your tick"))
            continue
        g = re.match(r"^[ \t]*(?:[-*+][ \t]+|>[ \t]*)*ela[ \t]*[:：][ \t]*(\S.*?)[ \t]*$", line, re.I)
        if g and cur and qs[cur]["status"] == "open":
            w = g.group(1)
            if re.match(r"^(?:drop|dropped|skip|remove)\b", w, re.I):
                qs[cur].update(status="dropped", outcome="dropped by your word", closed=today.isoformat(), by="owner")
            else:
                qs[cur].update(status="closed", outcome=w, closed=today.isoformat(), by="owner")
            out.append((cur, qs[cur]["outcome"]))
            consumed.append(line.strip())
        elif not line.startswith((" ", "\t", ">")) and line.strip():
            cur = None if not BOX.match(line) else cur
    return out, consumed


def gone_from_pages(state, project_srcs, today):
    """A question listed only on project pages whose box is no longer open there was answered on its page."""
    out = []
    for r in state["questions"].values():
        if r["status"] != "open" or not r["sources"] or not all(s.startswith("projects/") for s in r["sources"]):
            continue
        if not any(s in project_srcs for s in r["sources"]):
            r.update(status="closed", outcome="answered on its page", closed=today.isoformat(), by="owner")
            out.append((r["id"], r["outcome"]))
    return out


# ── the standing page and today's line ────────────────────────────────────────────────────────────────

def open_records(state):
    return sorted((r for r in state["questions"].values() if r["status"] == "open"),
                  key=lambda r: (r["first"]["date"], -len(r["meetings"]), not r["lead"], r["id"]))


def short(text, n=TEXT_CHARS):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + " …"


def answerer(r):
    ps = [p.strip() for p in re.split(r",|\+", r.get("who") or "") if p.strip()]
    return (ps[0] if ps else "Not named"), ps[1:]


def link(k, jira):
    return f"[{k}]({jira.rstrip('/')}/browse/{k})" if jira else k


def age(r, today):
    return (today - datetime.date.fromisoformat(r["first"]["date"])).days


def days(n):
    return "today" if n == 0 else f"{n} day{'s' if n != 1 else ''}"


def page(state, today, jira="", drafts=None):
    """meetings/open-questions.md, one screen: one line a question, grouped by who answers (the first named; the group
    with the oldest question first), each with its ticket, since when and at how many meetings it was listed."""
    recs = open_records(state)
    groups = {}
    for r in recs:
        groups.setdefault(answerer(r)[0], []).append(r)
    L = ["# Open team questions", "",
         f"*{len(recs)} open, by who answers, oldest first. Its ticket or thread answering it closes one, as does your tick "
         "or an `ela:` line under it (`ela: drop` drops it).*", ""]
    more = 0
    for name, rs in sorted(groups.items(), key=lambda g: (g[1][0]["first"]["date"], g[0])):
        for r in rs:                                       # one line each, its answerer first: the groups read down the page
            if len(L) >= PAGE_LINES:
                more += 1; continue
            co = answerer(r)[1]
            k = r["lead"][0] if r["lead"] else (r["keys"][0] if r["keys"] else None)
            n = len(r["meetings"])
            shown_text = re.sub(r"\*\*([^*]+)\*\*", r"\1", r["text"])
            if k and shown_text.startswith(k + " — "):
                shown_text = shown_text[len(k) + 3:]
            bits = [f"**{name}**" + (f" with {', '.join(co)}" if co else ""), short(shown_text, 90)] + ([link(k, jira)] if k else []) + \
                   [f"since {r['first']['date'][5:]} ({days(age(r, today))})", f"listed at {n} meeting{'s' if n != 1 else ''}"]
            L.append(f"- [ ] {' · '.join(bits)} ^{r['id']}")
            d = (drafts or {}).get(r["id"])
            if d:
                L += [f"  > [!note]- draft to {d['to']} ({d['via']})", *("  > " + x for x in d["text"].splitlines())]
    L.append("")
    if more:
        L += [f"{more} more in the record (`ela vault questions --json`).", ""]
    if not recs:
        L += ["No open team question.", ""]
    return "\n".join(L).rstrip("\n") + "\n"


def today_line(state, today, next_meeting=None, jira=""):
    """today.md's one line: N open team questions · oldest: <key>, <days> days · next sync <day>, linking the page."""
    recs = open_records(state)
    if not recs:
        return None
    o = recs[0]
    k = o["lead"][0] if o["lead"] else (o["keys"][0] if o["keys"] else short(o["text"], 40))
    bits = [f"[[{QUESTIONS_PAGE[:-3]}|{len(recs)} open team question{'s' if len(recs) != 1 else ''}]]",
            f"oldest: {link(k, jira) if KEY.fullmatch(k or '') else k}, {days(age(o, today))}"]
    if next_meeting:
        bits.append(f"next {next_meeting[0]} {next_meeting[1]:%a}")
    return "- " + " · ".join(bits)


def nudges(state, today):
    """The questions listed at NUDGE_EVERY meetings (and each NUDGE_EVERY more) without an outcome, oldest first:
    [{id, text, who, count, bucket}]."""
    out = []
    for r in open_records(state):
        n = len(r["meetings"])
        if n >= NUDGE_EVERY:
            out.append({"id": r["id"], "text": r["text"], "who": r.get("who"), "count": n, "bucket": n // NUDGE_EVERY})
    return out


def draft(r, owner_first=""):
    """The message under his name to whoever answers: on the lead ticket as a comment, else in the thread the box
    links. {to, via, text, target} or None when there is nowhere to send it."""
    to = answerer(r)[0]
    if to == "Not named" or GENERIC_WHO.match(to):
        to = None
    hi = f"Hi {to.split()[0]}, " if to else "Hi, "
    n = len(r["meetings"])
    text = (f"{hi}one open question from the MediaHub syncs, listed at {n} meetings since {r['first']['date'][5:]}: "
            f"{r['text'].rstrip('?. ')}? Could you answer here, or tell me who should?" + (f" — {owner_first}" if owner_first else ""))
    th = SLACK.search(r.get("raw") or "")
    if r["lead"]:
        return {"to": to or "its holder", "via": f"Jira comment on {r['lead'][0]}", "text": text,
                "command": ["jira", "comment", r["lead"][0]]}
    if th:
        return {"to": to or "the thread", "via": "a reply in its thread", "text": text, "command": ["slack", "post", th.group(0)]}
    return None


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)
