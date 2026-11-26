#!/usr/bin/env python3
"""today.md's head and the meaning of its facts: what the day is about and what to do first. Stdlib only.

L1, a module of the vault verb (`ela vault head`, and every `ela vault sync`). The owner's rule for the page
(2026-11-24): a fact alone is not enough. Every line on today.md says what the fact means for him and what to do,
with one link to the evidence (vault ela/2026-11-24-plan-today-opens-with-what-the-day-is-about.md, steps 1 and 2).

    ## In short     at most HEAD_MAX judged lines ordered by urgency, then one line "Start with …"
    ## Since you last looked  each line a judgment of what changed, or folded under "N facts not judged"; the
                    fixes whose verdict changed lead it, each linking its row on the line page (train fixes.py)

The head's candidates are the morning page's ranked items, the focus board's Now rows, the project deadlines and the
KPI breaches (a new ticket nobody owns after 4 hours, an In Progress ticket on him not updated for 24 hours). Every
sync keeps what it saw in <reports>/ela/head-inputs.json. A judgment that needs reading (the ticket, a config value)
comes from one unattended model session the runner starts when those inputs change, as it does for the open
questions' words; this verb is the judge of what that session writes: a line without a meaning, a Do or its link, or
one that only repeats its fact, is refused. The accepted lines live in <reports>/ela/head.json for the day. With none,
the head is ela's own, from the candidates that carry their Do (the morning page's items, the KPI breaches, the project
steps), and every fact is folded.

Usage:
    head.py --help    this text; the verb is `ela vault head [--lines FILE] [--apply] [--json]`
"""
import datetime, hashlib, json, os, re, sys

HEAD_MAX = 4                    # judged lines; with "Start with …" the head is five lines at most
HEAD_WORDS, FACT_WORDS, START_WORDS = 45, 80, 30
MEANING_MIN, DO_MIN = 4, 2      # words before "Do:" and after it
ROUTE_H, UPDATE_H = 4, 24       # the KPIs: ticket → engineers within 4h; In Progress updated within 24h
BOARD_ROWS = 3                  # the board's Now rows offered to the judge
STATE, INPUTS = ("ela", "head.json"), ("ela", "head-inputs.json")
KEY = re.compile(r"(?<![\w/#=.-])([A-Z][A-Z0-9]{1,9}-\d{1,6})(?![\w-])")
MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
WIKI = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
BARE = re.compile(r"(?<![(\[<])https?://\S+")
DO = re.compile(r"\bDo:\s*")
BOX = re.compile(r"^\[[ xX]\][ \t]+(?:apply|don't)[ \t]+\d+[ \t]*(?:—[ \t]*)?")   # the morning page's box: not words

RULES = (
    "The owner's rule for today.md: a fact alone is not enough. Each line says what the fact means for him and what to "
    "do, with one link to the evidence. A line reads `<what it means, with the reason read first-hand>. Do: <what he "
    "does, and when>.` and carries exactly one link: a Markdown link or an Obsidian [[link]], or, with neither, the "
    "ticket key the line turns on (the page links it). Read what the meaning needs (the ticket, its comments, a config "
    "value, the build) with ela's read verbs; never guess, and say `not read` where a source could not be read.\n"
    f"- A head line: at most {HEAD_WORDS} words. A fact line: at most {FACT_WORDS} words. One line each, no line break.\n"
    "- The meaning is not the fact again: say whether it changes his options (can a build move, is a promise at risk, "
    "who is waiting) and why.\n"
    f"- The head is at most {HEAD_MAX} ids, most urgent first: a KPI breach and a deadline at risk before an item that "
    f"can wait. Then `start`: one line beginning `Start with ` naming the single first step, at most {START_WORDS} words.\n"
    "- A fact that does not change his options gets null: it is folded on the page. So does a head candidate you leave out.\n"
    "Worked example. The fact: \"QA's verdict build, QA-AWS3 build 100, is partial: 10 pass and 2 fail, both in MH-4048.\" "
    "Its line: \"Build 100 can still move: its 2 failures are MH-4048 (a destination with a saved CSC preset will not "
    "start when destination CSC is switched off), and the switch is on everywhere (mx-service default "
    "csc.destination.enabled=true). Do: move build 100 when the rest is ready; keep the switch on until the owner's fix "
    "lands (they plan to drop the switch).\"\n"
    "Answer with one JSON object only, no prose around it: {\"head\": [{\"id\": \"<id>\", \"line\": \"<line>\"}, ...], "
    "\"start\": \"Start with …\", \"facts\": {\"<fact id>\": \"<line>\" or null, ...}}, a value for every fact id.")


# ── reading a line ────────────────────────────────────────────────────────────────────────────────────

def plain(text):
    t = MD_LINK.sub(r"\1", text or "")
    t = WIKI.sub(lambda m: m.group(2) or m.group(1), t)
    return " ".join(re.sub(r"[*_`]", "", t).split())


def words(text):
    return len(plain(text).split())


def norm(text):
    return re.sub(r"[^a-z0-9]+", " ", plain(text).lower()).strip()


def lid(kind, text):
    return f"{kind}-" + hashlib.sha256(" ".join((text or "").split()).encode()).hexdigest()[:8]


def links(line):
    """The explicit links on a line: Markdown, Obsidian and bare URLs."""
    return len(MD_LINK.findall(line)) + len(WIKI.findall(line)) + len(BARE.findall(MD_LINK.sub("", line)))


def check_line(line, limit, fact=None):
    """Why `line` is refused as a judged line, or None: one line, a meaning and a Do, one link to the evidence (an
    explicit link, else a ticket key the page links), within `limit` words, and not the fact again."""
    if not isinstance(line, str) or not line.strip():
        return "empty"
    if "\n" in line.strip():
        return "more than one line"
    m = DO.search(line)
    if not m:
        return "no `Do:`: a fact alone is not enough, say what he does"
    meaning, do = line[:m.start()], line[m.end():]
    if words(meaning) < MEANING_MIN:
        return f"the meaning before `Do:` is under {MEANING_MIN} words"
    if words(do) < DO_MIN:
        return f"the Do is under {DO_MIN} words"
    n = links(line)
    if n > 1:
        return f"{n} links: one link to the evidence"
    if n == 0 and not KEY.search(line):
        return "no link to the evidence"
    if words(line) > limit:
        return f"{words(line)} words, at most {limit}"
    if fact and norm(meaning).rstrip(" .") and norm(meaning) in norm(fact):
        return "the meaning repeats the fact: say what it means for him"
    return None


def check_start(line):
    if not isinstance(line, str) or not line.strip().startswith("Start with "):
        return "it does not begin `Start with `"
    if "\n" in line.strip():
        return "more than one line"
    if words(line) > START_WORDS:
        return f"{words(line)} words, at most {START_WORDS}"
    if links(line) > 1:
        return "more than one link"
    return None


# ── the candidates ────────────────────────────────────────────────────────────────────────────────────

def brief_items(path, body):
    """The morning page's ranked items above its fold: [{n, head, do, link}]; the Do is the first line under `**Do:**`."""
    out, cur, in_do = [], None, False
    sec = re.search(r"^##[ \t]+Needs you[ \t]*\n(.*?)(?=^##[ \t]|\Z)", body or "", re.M | re.S)
    for line in (sec.group(1) if sec else "").splitlines():
        if line.startswith(">"):                         # the fold: Also noticed is not ranked for the head
            break
        h = re.match(r"^###[ \t]+(\d+)\.[ \t]+(.+?)[ \t]*$", line)
        if h:
            cur = {"n": int(h.group(1)), "head": h.group(2), "do": None,
                   "link": f"[[{path[:-3]}#{h.group(1)}. {h.group(2)}|the morning page]]" if path else None}
            out.append(cur); in_do = False
            continue
        if cur and re.match(r"^-[ \t]+\*\*Do:\*\*", line):
            rest = BOX.sub("", re.sub(r"^-[ \t]+\*\*Do:\*\*[ \t]*", "", line).strip())
            if rest:
                cur["do"] = cur["do"] or rest
            in_do = True
            continue
        if cur and in_do and not cur["do"] and re.match(r"^-[ \t]+\S", line):
            cur["do"] = BOX.sub("", line[1:].strip())
    return out


def board_rows(text, n=BOARD_ROWS):
    """The focus board's Now rows, the first n: [{key, text}]."""
    sec = re.search(r"^##[ \t]+Now[ \t]*\n(.*?)(?=^##[ \t]|\Z)", text or "", re.M | re.S)
    out = []
    for line in (sec.group(1) if sec else "").splitlines():
        if re.match(r"^-[ \t]+\S", line):
            k = KEY.search(line)
            out.append({"key": k.group(1) if k else None, "text": plain(line[1:].strip())})
            if len(out) >= n:
                break
    return out


def hours_since(stamp, now):
    try:
        t = datetime.datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")
        off = re.search(r"([+-])(\d{2}):?(\d{2})$", stamp)
        if off:
            t = t.replace(tzinfo=datetime.timezone((1 if off.group(1) == "+" else -1) * datetime.timedelta(hours=int(off.group(2)), minutes=int(off.group(3)))))
            now = now if now.tzinfo else now.astimezone()
        return (now - t).total_seconds() / 3600
    except (TypeError, ValueError):
        return None


def kpi_rows(runtime, now=None):
    """The KPI breaches from the fact store's lane queries (brief.py Q["triage"], Q["yours"]), as last read:
    [{kind: route|update, key, title, hours}]. Read from disk only; [] when the store has not read them."""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "brief"))
        import brief as B
        want = {" ".join((B.PROJECT + B.Q[k]).split()): k for k in ("triage", "yours")}
    except Exception:                                      # noqa: BLE001 — no lanes, no KPI lines
        return []
    now = now or datetime.datetime.now().astimezone()
    d = os.path.join(runtime or "", "facts", "jira", "queries")
    out = []
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        try:
            doc = json.load(open(os.path.join(d, name), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        lane = want.get(" ".join((doc.get("jql") or "").split()))
        for i in doc.get("issues") or [] if lane else []:
            f = i.get("fields") or {}
            if lane == "triage":
                h = hours_since(f.get("created"), now)
                if h is not None and h > ROUTE_H:
                    out.append({"kind": "route", "key": i.get("key"), "title": f.get("summary") or "", "hours": int(h)})
            elif (f.get("status") or {}).get("name") == "In Progress":
                h = hours_since(f.get("updated"), now)
                if h is not None and h > UPDATE_H:
                    out.append({"kind": "update", "key": i.get("key"), "title": f.get("summary") or "", "hours": int(h)})
    return out


def age(h):
    return f"{h} hours" if h < 48 else f"{h // 24} days"


def candidates(brief=None, projects=(), board="", kpi=(), soon_days=14):
    """The head's candidates, each {id, kind, rank, text, do, link}; a lower rank is more urgent. `brief` is (path,
    body) of today's morning page, `projects` the project facts, `board` the focus board's text, `kpi` kpi_rows()."""
    out = []
    for r in kpi or []:
        if r["kind"] == "route":
            out.append({"id": f"kpi-route-{r['key']}", "kind": "kpi", "rank": 10,
                        "text": f"{r['key']} ({r['title']}) has had no owner for {age(r['hours'])}, past the 4-hour routing promise.",
                        "do": f"route {r['key']} to its owner now.", "link": None})
        else:
            out.append({"id": f"kpi-update-{r['key']}", "kind": "kpi", "rank": 20,
                        "text": f"{r['key']} ({r['title']}) is In Progress on you and has not moved for {age(r['hours'])}, past the 24-hour promise.",
                        "do": f"update {r['key']} today, or move it out of In Progress.", "link": None})
    for f in projects or []:
        days = f.get("days")
        if days is None or not 0 <= days <= soon_days:
            continue
        step = (f.get("step") or "").strip().rstrip(".")
        out.append({"id": f"project-{f['key']}", "kind": "project", "rank": 15 if days <= 3 else 40 + days,
                    "text": f"{f['key']} has {days} day{'s' if days != 1 else ''} left to {f['deadline']}" + (" and its step is overdue." if f.get("overdue") else "."),
                    "do": f"next step: {step}." if step else "name its next step on its page.",
                    "link": f"[[{f['path'][:-3]}|{f['key']}]]" if f.get("path") else None})
    path, body = brief or (None, None)
    for it in brief_items(path, body):
        out.append({"id": lid("brief", it["head"]), "kind": "brief", "rank": 30 + it["n"], "text": it["head"].rstrip(".") + ".",
                    "do": it["do"], "link": it["link"]})
    for k, r in enumerate(board_rows(board)):
        out.append({"id": f"board-{r['key']}" if r["key"] else lid("board", r["text"]), "kind": "board", "rank": 60 + k,
                    "text": r["text"], "do": None, "link": None})
    seen, uniq = set(), []
    for c in sorted(out, key=lambda c: c["rank"]):
        if c["id"] not in seen:
            seen.add(c["id"]); uniq.append(c)
    return uniq


def inputs(today, facts, cands, pages=None):
    """What the head is judged from: {date, sig, facts: [{id, label, line}], candidates, pages}. The sig changes when
    a fact or a candidate comes or goes, never with an age."""
    fs = [{"id": lid("fact", line), "label": label, "line": line} for label, line in facts]
    sig = hashlib.sha256(json.dumps(sorted([f["id"] for f in fs] + [c["id"] for c in cands])).encode()).hexdigest()[:12]
    return {"date": today.isoformat(), "sig": sig, "facts": fs, "candidates": cands, "pages": pages or {}}


# ── the stored judgment ───────────────────────────────────────────────────────────────────────────────

def load(reports, name=STATE):
    try:
        return json.load(open(os.path.join(reports or "", *name), encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(reports, data, name=STATE):
    p = os.path.join(reports, *name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    json.dump(data, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def stale(inp, state):
    """Whether the inputs have changed since the last judgment of the day."""
    return not state or state.get("date") != inp.get("date") or state.get("sig") != inp.get("sig")


def judge(inp, answer, state=None):
    """The verb as the judge of a session's answer: (state to store, {id: why refused}). Accepted lines merge onto the
    day's state; a refused one is left out, and its fact stays folded."""
    state = dict(state or {}) if (state or {}).get("date") == inp["date"] else {}
    judged = dict(state.get("judged") or {})
    facts = {f["id"]: f for f in inp["facts"]}
    known = set(facts) | {c["id"] for c in inp["candidates"]}
    refused = {}
    for fid, line in ((answer or {}).get("facts") or {}).items():
        if fid not in facts:
            refused[fid] = "not a fact id of today's inputs"
        elif line is None:
            judged[fid] = None
        else:
            why = check_line(line, FACT_WORDS, facts[fid]["line"])
            if why:
                refused[fid] = why
            else:
                judged[fid] = " ".join(line.split())
    head = []
    for h in (answer or {}).get("head") or []:
        hid, line = (h or {}).get("id"), (h or {}).get("line")
        fact = facts.get(hid, {}).get("line")
        why = "not an id of today's inputs" if hid not in known else check_line(line, HEAD_WORDS, fact)
        if why:
            refused[hid or "?"] = why
        elif len(head) < HEAD_MAX:
            head.append({"id": hid, "line": " ".join(line.split())})
        else:
            refused[hid] = f"more than {HEAD_MAX} head lines"
    start = (answer or {}).get("start")
    if start is not None:
        why = check_start(start)
        if why:
            refused["start"] = why
    out = {"date": inp["date"], "sig": inp["sig"], "judged": judged,
           "head": head or state.get("head") or [], "start": (" ".join(start.split()) if start and "start" not in refused else state.get("start")),
           "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
    return out, refused


# ── the page ──────────────────────────────────────────────────────────────────────────────────────────

def own_line(c):
    return f"{c['text']} Do: {c['do']}" + (f" → {c['link']}" if c.get("link") else "")


def lower_first(s):
    return s[:1].lower() + s[1:] if s and not KEY.match(s) else s


def render(inp, state=None):
    """(head lines, judged fact lines, folded fact lines) for today.md. The head is the stored judgment of the day for
    ids still present; else ela's own, from the candidates that carry their Do. A fact is its judged line, or folded."""
    ok = (state or {}).get("date") == inp["date"]
    present = {f["id"] for f in inp["facts"]} | {c["id"] for c in inp["candidates"]}
    head = [h["line"] for h in (state or {}).get("head") or [] if ok and h.get("id") in present][:HEAD_MAX]
    start = (state or {}).get("start") if ok and head else None
    if not head:
        own = [c for c in inp["candidates"] if c.get("do")][:HEAD_MAX]
        head = [own_line(c) for c in own]
        start = f"Start with {lower_first(own[0]['do'].rstrip('.'))}." if own else None
    lines = [f"- {h}" for h in head] + [start or "Start with [[meetings/focus|the focus board]]: nothing else presses today."]
    judged = ((state or {}).get("judged") or {}) if ok else {}
    shown, folded = [], []
    for f in inp["facts"]:
        (shown if judged.get(f["id"]) else folded).append((f["label"], judged.get(f["id"]) or f["line"]))
    return lines, shown, folded


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return
    print(__doc__)


if __name__ == "__main__":
    main()
