#!/usr/bin/env python3
"""Dry runs by class: a kind of write ela prepares unasked, the owner reviews as one batch, and that earns its way out
of the confirm on evidence, by his word given once. Stdlib only; it reads Jira through jira.py and writes nothing to
any live system except through jira.py's own `--apply`, on an answer that carries `--apply`.

An action class is one atom in one scope with a written rule that selects its targets (CLASSES). Every dry run shown to
the owner and its verdict is the class's track record: applied as drafted, applied after his edit, cancelled, expired
unanswered, and afterwards corrected or reverted by anyone. A class with at least MATURE_RUNS runs applied as drafted
over MATURE_DAYS days, none edited or cancelled in the last MATURE_RUNS and none corrected, earns one grant ask. Yes
moves it one step up its ladder; one correction, revert or `ela:` line against it returns it to confirm. A class tier 3
names by rule (NEVER) is recorded but never proposed.

  classes [--json]                       the closed vocabulary: each class, its rule, its ladder
  status  [--json]                       each class: its record, its tier, what is one step from maturity
  seed    [--apply] [--json]             the record from history: writes.jsonl, the runner's actions files, the ask
                                         state; dry run prints the counts, --apply writes record-seed.jsonl (idempotent)
  draft   <class> <KEY> [--issue-file F] [--child-file F …] [--apply] [--json]
                                         read the parent (or the given files), select the targets by the class's rule.
                                         link-named and parent-status are tier 1 by decision (2026-11-24): the set is
                                         ela's own write, a link with no comment on the ticket, a dry run unless --apply, and
                                         listed in ela/dry/did.md with its undo; after a correction returns the class
                                         to confirm, one batch is stored and asked on today.md instead
  batch   <id> [--json]                  one batch: its writes, each the exact command
  asks    [--date D] [--json]            the asks this pass puts on today.md: one per class with waiting writes, one
                                         grant ask per mature class, in the A/B/C shape
  answer  <ask-id> <A|B|C> [--note PATH] [--apply] [--json]
                                         his letter on an ask. A batch: A applies the batch (dry run of each write
                                         unless --apply; a struck line in the review note is left out, an edited one is
                                         applied as edited and recorded as an edit), B drops it. A grant: A grants, B
                                         keeps confirming, C never asks again
  correct <class> --how revert|correction|word [--ref R] [--note T] [--date D]
                                         a correction after the fact; a granted class returns to confirm
  did     [--date D] [--json]            what granted classes did without confirm: the Facts line and its list
  undo    <act|batch> [--apply] [--json] the reverse of an act, from the before-state it kept (<reports>/ela/acts.jsonl):
                                         each undo a dry run unless --apply; applied, it records the class's correction
  acts    [--class C] [--json]           the acts on record, each with its before-state and its undo

A class whose reverse atom jira.py does not carry is never proposed for a grant (`reversible`): what ela may do
without asking, it must be able to take back.

Store: <reports>/ela/dry/ — classes.json (tier, grants, asks), record.jsonl, record-seed.jsonl, batches/<id>.json;
<reports>/ela/acts.jsonl, written by jira.py at each applied write (the act, its before-state, its undo).
Exit codes: 0 ok · 2 usage · 3 not found · 5 remote.
"""
import argparse, datetime, glob, hashlib, json, os, re, shlex, subprocess, sys
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "setup"))
import siteguard  # noqa: E402  a file in the site directory is never read for a caller

HERE = os.path.dirname(os.path.abspath(__file__))
JIRA = os.path.join(HERE, "..", "jira", "jira.py")
SITE = os.path.expanduser("~/.claude/ela/site.json")
TZ = datetime.timezone(datetime.timedelta(hours=8))
KEY = r"[A-Z][A-Z0-9]+-\d+"
KEY_RX = re.compile(r"\b" + KEY + r"\b")
# A standard's name has a ticket key's shape: SCTE-35, SMPTE-2110, ISO-8601. A Jira project may carry the same
# letters (SCTE-35 is a real, unrelated ticket), so text naming one is never a ticket named (MH-3568, 2026-11-24).
STANDARDS = {"SCTE", "SMPTE", "ST", "ISO", "IEC", "RFC", "ITU", "AES", "EBU", "ETSI", "ATSC", "DVB", "IEEE", "CEA",
             "CTA", "ANSI", "MPEG", "HEVC", "AVC", "UTF", "SHA", "TLS", "HTTP", "IPV"}


# A URL's path is not prose: a Figma file named MH-2026 (figma.com/design/<id>/MH-2026?node-id=…) or Jira's smart-link
# (…/browse/SCTE-35#icft=SCTE-35, which Jira writes for any key-shaped text) names no ticket. A plain Jira browse link
# does: it keeps its key (batch 2026-11-24-link-named-MH-3997, dropped).
URL_RX = re.compile(r"(?:https?://|www\.)[^\s<>\"'`)\]]+")
BROWSE_RX = re.compile(r"^(?:https?://)?[\w.-]*atlassian\.net/browse/(" + KEY + r")(?![\w-])")


def strip_urls(text):
    """The text with every URL removed, except a Jira browse link that is not an #icft= smart-link, kept as its key."""
    def keep(m):
        b = BROWSE_RX.match(m.group(0))
        return f" {b.group(1)} " if b and "#icft=" not in m.group(0) else " "
    return URL_RX.sub(keep, text or "")


# A design file named in prose is not a ticket either: the design team names Figma files by the ticket they began for
# ("design in Figma MH-2026 node 4119-5823" in MH-3998 named a file, and ela linked an unrelated Done ticket,
# 2026-11-25). A key right after "Figma" or the Chinese for design draft / design file (an optional file/design word, colon or quote between) is
# a file. A key before "node" is not taken alone: "MH-4123 node list crash" names a ticket.
DESIGN_RX = re.compile(r"(?:\bfigma|\u8bbe\u8ba1\u7a3f|\u8bbe\u8ba1\u6587\u4ef6)(?:\s*(?:file|design|board|frame|page|doc|\u6587\u4ef6|\u8bbe\u8ba1|\u7a3f)\b)?\s*[:\uff1a#]?\s*"
                       r"[\"'\u201c\u300c]?" + KEY + r"\b", re.I)


def ticket_keys(text):
    """The ticket keys a text names: KEY_RX's matches outside URLs (a plain Jira browse link kept) and outside a design
    file's name (DESIGN_RX), less a standard's name."""
    return [k for k in KEY_RX.findall(DESIGN_RX.sub(" ", strip_urls(text))) if k.split("-")[0] not in STANDARDS]
EX_USAGE, EX_NOTFOUND, EX_REMOTE = 2, 3, 5
MATURE_RUNS, MATURE_DAYS = 10, 3              # ten clean runs over at least three days (the brief of 2026-11-12)
ASK_AGAIN_AFTER = 10                          # an unanswered or declined grant ask returns after ten more clean runs

# ── the closed vocabulary ─────────────────────────────────────────────────────────────────────────────────────
# A class: what it is in a sentence, the atom (system, verb), the rule that selects its targets, the commands it may
# issue (a regex the tier check also uses), its ladder (tier 3 is confirm; one step up is the next entry), the case in
# the record it came from. Tier 1 is Jira only and tier 2 is a team-channel post (decision 2026-10-29), so a Jira class
# climbs 3 → 1. `base` is the tier the class holds by a recorded decision before any grant.
CLASSES = {
    "link-named": {
        "says": "link a child to a parent you own when a comment on the parent names it",
        "atom": ("jira", "link"), "noun": ("link", "links"), "ladder": (3, 1), "base": 1,
        "rule": "a ticket named in the parent's description or comments, not linked to it yet, and not a subtask of a "
                "ticket linked or proposed; `contains`, or `relates to` when the naming line says related",
        "command": r"^ela jira link " + KEY + r" " + KEY + r" --type (?:contains|\"?relates to\"?)\s*$",
        "case": "MH-3735, 2026-11-12: links approved as a kind in one sentence; tier 1 by the decision of 2026-11-24 "
                "(ela watches the MH board and acts on Jira); since 2026-11-25 a link carries no comment (MH's Automation "
                "copies each comment to the linked tickets), its reason and undo in ela/dry/did.md",
        "reverse": (("unlink", "--id"),),
    },
    "parent-status": {
        "says": "a status comment on a parent you own, from its children's states",
        "atom": ("jira", "comment"), "noun": ("status comment", "status comments"), "ladder": (3, 1), "base": 1,
        "rule": "the parent's contained children, one line each with its status, when a status differs from his last "
                "status comment on the parent",
        "command": r"^ela jira comment " + KEY + r" --from-file \S+\s*$",
        "case": "MH-3735, 2026-11-12: 'update the parent' after the links; tier 1 by the decision of 2026-11-24, the "
                "comment signed",
        "reverse": (("comment-delete", "--id"),),
    },
    "release-reconcile": {
        "says": "add the missing Fixed In and release label to the tickets of a build a lane took",
        "atom": ("jira", "fixed-in+label"), "noun": ("build's Jira gaps", "builds' Jira gaps"), "ladder": (3, 1), "base": 3,
        "rule": "the release-reconcile work's: each ticket a build's announcement names, read against Jira after the "
                "release thread is quiet; Fixed In appended from the builds ledger, the build's label added; one batch "
                "for every build in the window",
        # kept equal to brief.py's PENDING_RULES["release-reconcile"] (a test holds them together)
        "command": r"^ela release reconcile [\w-]+(?:\s+--build\s+\d+)*\s+--batch\s*$",
        "case": "39 fixed-in and 3 label writes in writes.jsonl, all attended; the rule landed 2026-11-12",
        "reverse": (("fixed-in", "--remove"), ("label", "--remove")),
    },
    "assign-by-rule": {
        "says": "assign by a written routing rule",
        "atom": ("jira", "assign"), "noun": ("assignment", "assignments"), "ladder": (3, 1), "base": 1,
        "rule": "a routing rule written in elak names the owner of the ticket's area",
        "command": r"^ela jira assign " + KEY + r"\s",
        "case": "tier 1 by the decision of 2026-10-29 (assign-by-rule); 5 assign writes, all attended",
        "reverse": (("assign", "--assignee"),),
    },
    "focus-moves": {
        "says": "move tickets on the MediaHub focus board: priority, assignee, due date, a comment, "
                "or a ticket for a row that has none",
        "atom": ("jira", "priority+assign+due+comment+create"), "noun": ("board move", "board moves"), "ladder": (3,), "base": 3,
        "rule": "the focus board's (ela focus moves, ela focus scrum): his `ela: up` and `ela: down` words; what the scrum's "
                "Read AI report decided or gave someone, mapped to a row; a row carried through two meetings with no "
                "ruling; a row with no ticket (never ela's own work or his personal items); one batch, added to until answered",
        "command": r"^ela jira (?:priority " + KEY + r" --to (?:Highest|High|Medium|Low|Lowest)(?: --why .+)?"
                   r"|assign " + KEY + r" --assignee \S+"
                   r"|due " + KEY + r" --date \d{4}-\d{2}-\d{2}(?: --why .+)?"
                   r"|comment " + KEY + r" --from-file \S+"
                   r"|create --project MH --type Task --summary .+)\s*$",
        "case": "the focus board, 2026-11-20 (vault plan 2026-11-20-plan-one-focus-board-meetings-as-views): a summary is a "
                "report, not evidence; every move is confirmed; a created ticket has no reverse, so the class never climbs",
        "reverse": (),
    },
    "board-watch": {
        "says": "act on an MH ticket the board watch found due: assign, a non-terminal status, priority, due date, a "
                "link, a comment; each field change announced on the ticket by a signed comment, a link by none",
        "atom": ("jira", "assign+transition+priority+due+link+comment"), "noun": ("ticket set", "ticket sets"),
        "ladder": (1,), "base": 1,
        "rule": "the board watch's (ela watch): a trigger on a tracked MH ticket (a change calling for a response, a "
                "question answered or past its wait, a wrong assignee or status, a stall), a model session's decision "
                "to act, at most one set per ticket a day, never a repeated comment; what it cannot decide is an ask",
        "command": r"^ela jira (?:assign " + KEY + r" --assignee \S+"
                   r"|transition " + KEY + r" --to (?:\"[A-Za-z ]+\"|'[A-Za-z ]+'|[A-Za-z]+)"
                   r"|priority " + KEY + r" --to (?:Highest|High|Medium|Low|Lowest)"
                   r"|due " + KEY + r" --date \d{4}-\d{2}-\d{2}"
                   r") --note-file \S+\s*$"
                   r"|^ela jira link " + KEY + r" " + KEY + r" --type (?:\"[A-Za-z ]+\"|'[A-Za-z ]+'|[A-Za-z]+)\s*$"
                   r"|^ela jira comment " + KEY + r" --from-file \S+\s*$",
        "case": "tier 1 by the decision of 2026-11-24 (ela watches the MH board and acts on Jira, signing each write); "
                "reviewed afterwards in ela/dry/did.md, a disputing reply on the ticket a correction",
        "reverse": (("assign", "--assignee"), ("comment-delete", "--id"), ("unlink", "--id")),
    },
}
TIER1_BY_DECISION = ("board-watch", "link-named", "parent-status")   # written at the pass that decides them, each act on record with its undo
# The decision that moved a class to tier 1 after it had a stored tier: applied once (a `decided` event), so a later
# correction's fall to confirm stands (vault plan 2026-11-24-plan-today-opens-with-what-the-day-is-about, step 3).
DECIDED = {"link-named": ("2026-11-24T00:00:00+08:00", "decision 2026-11-24-ela-watches-the-mh-board-and-acts-on-jira-signing-each-write"),
           "parent-status": ("2026-11-24T00:00:00+08:00", "decision 2026-11-24-ela-watches-the-mh-board-and-acts-on-jira-signing-each-write")}
# tier 3 by rule (decision 2026-10-29): recorded, never proposed for a grant
NEVER = {
    "message-to-person": "a message to a person",
    "customer-channel": "anything to a customer channel",
    "prod-approval": "a prod approval",
    "about-people": "anything about people",
    "close": "any close",
}
for _c, _why in NEVER.items():
    CLASSES[_c] = {"says": _why, "atom": None, "noun": ("write", "writes"), "ladder": (3,), "base": 3, "rule": "tier 3 by rule",
                   "command": None, "case": "decision 2026-10-29, tier 3", "never": _why}

VERDICTS = ("applied", "edited", "cancelled", "expired", "corrected", "reverted", "confirmed")   # confirmed: his `ok` in did.md


# ── the store ─────────────────────────────────────────────────────────────────────────────────────────────────
def site():
    try:
        return json.load(open(SITE))
    except (OSError, ValueError):
        return {}


def store(reports):
    return os.path.join(reports, "ela", "dry")


def atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def read_jsonl(path):
    out = []
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def append(reports, row):
    p = os.path.join(store(reports), "record.jsonl")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def record(reports):
    """Every row, seeded and live, oldest first."""
    rows = read_jsonl(os.path.join(store(reports), "record-seed.jsonl")) + read_jsonl(os.path.join(store(reports), "record.jsonl"))
    return sorted(rows, key=lambda r: r.get("at") or "")


def load_state(reports):
    try:
        st = json.load(open(os.path.join(store(reports), "classes.json"), encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    for c, d in CLASSES.items():
        x = st.setdefault(c, {})
        x.setdefault("tier", d["base"])
        x.setdefault("history", [])
        if c in DECIDED and not any(h.get("event") in ("decided", "fell") and h.get("at", "") >= DECIDED[c][0] for h in x["history"]):
            was, x["tier"] = x["tier"], d["base"]
            x["history"].append({"at": DECIDED[c][0], "event": "decided", "from": was, "to": d["base"], "why": DECIDED[c][1]})
    return st


def save_state(reports, st):
    atomic_write(os.path.join(store(reports), "classes.json"), json.dumps(st, ensure_ascii=False, indent=1) + "\n")


def now_iso(now=None):
    return (now or datetime.datetime.now(TZ)).isoformat(timespec="seconds")


# ── maturity ──────────────────────────────────────────────────────────────────────────────────────────────────
def since_last_reset(st_c):
    """The time of the class's last fall, grant or answered ask: the record before it does not count again."""
    resets = [h["at"] for h in st_c.get("history") or [] if h.get("event") in ("fell", "granted")]
    return max(resets) if resets else ""


def clean(rows):
    """Runs applied as drafted: applied, as_drafted true (a write the log shows without its draft is not)."""
    return [r for r in rows if r.get("verdict") == "applied" and r.get("as_drafted") is True]


def judged(cls, rows, st_c):
    """The class's record counted: totals by verdict (all history) and the maturity test on the rows since the last
    reset. → dict."""
    mine = [r for r in rows if r.get("class") == cls]
    totals = {v: sum(1 for r in mine if r.get("verdict") == v) for v in VERDICTS}
    unknown = sum(1 for r in mine if r.get("verdict") == "applied" and r.get("as_drafted") is None)
    cut = since_last_reset(st_c)
    live = [r for r in mine if (r.get("at") or "") > cut]
    ok = clean(live)
    days = sorted({(r.get("at") or "")[:10] for r in ok})
    decided = [r for r in live if r.get("verdict") in ("edited", "cancelled")
               or (r.get("verdict") == "applied" and r.get("as_drafted") is True)]   # his answers on drafts he saw
    last = decided[-MATURE_RUNS:]
    spoiled = [r for r in last if r.get("verdict") in ("edited", "cancelled")]
    corrected = [r for r in live if r.get("verdict") in ("corrected", "reverted")]
    mature = len(ok) >= MATURE_RUNS and len(days) >= MATURE_DAYS and not spoiled and not corrected
    need = []
    if len(ok) < MATURE_RUNS:
        need.append(f"{MATURE_RUNS - len(ok)} more applied as drafted")
    if len(days) < MATURE_DAYS:
        need.append(f"{MATURE_DAYS - len(days)} more day{'s' if MATURE_DAYS - len(days) != 1 else ''}")
    if spoiled:
        need.append(f"{len(spoiled)} edited or cancelled in the last {MATURE_RUNS} must age out")
    if corrected:
        need.append(f"{len(corrected)} correction{'s' if len(corrected) != 1 else ''} since the last reset")
    return {"class": cls, "totals": totals, "applied_unknown_draft": unknown, "clean": len(ok), "days": len(days),
            "mature": mature, "needs": need, "examples": ok[-3:]}


def can_rise(cls, st_c):
    d = CLASSES[cls]
    return not d.get("never") and st_c["tier"] != d["ladder"][-1] and not st_c.get("never_ask")


def next_tier(cls, tier):
    lad = CLASSES[cls]["ladder"]
    return lad[min(lad.index(tier) + 1, len(lad) - 1)] if tier in lad else tier


_HELP = {}


def atom_help(verb):
    """jira.py's own --help for one verb ('' when it has no such verb): the reverse atoms are checked against the
    capability as it is, not against a list kept here."""
    if verb not in _HELP:
        try:
            p = subprocess.run(["python3", JIRA, verb, "--help"], capture_output=True, text=True, timeout=60)
            _HELP[verb] = p.stdout if p.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            _HELP[verb] = ""
    return _HELP[verb]


def reversible(cls):
    """Whether every write the class makes has its reverse atom in jira.py (each named verb answers --help and takes
    the named flag). → (bool, [what is missing])."""
    rev = CLASSES[cls].get("reverse") or ()
    if not rev:
        return False, ["no reverse atom named"]
    missing = [f"jira {v} {flag}" for v, flag in rev if flag not in atom_help(v)]
    return not missing, missing


def grant_due(cls, rows, st_c):
    """Whether this pass may put a grant ask for the class: mature, able to rise, reversible (what ela may do unasked
    it must be able to take back), no ask open, and when an earlier ask went unanswered or was declined,
    ASK_AGAIN_AFTER more clean runs since it."""
    if not can_rise(cls, st_c):
        return False
    if not reversible(cls)[0]:
        return False
    j = judged(cls, rows, st_c)
    if not j["mature"]:
        return False
    ask = st_c.get("ask")
    if ask and not ask.get("answered") and not ask.get("expired"):
        return False                                      # one open at a time; settled by the vault's ask state
    if ask:
        return j["clean"] >= (ask.get("clean_at") or 0) + ASK_AGAIN_AFTER
    return True


# ── the asks: one shape everywhere (the desk's addition, 2026-11-12) ──────────────────────────────────────────
def option(letter, text, does, recommended=False):
    return {"letter": letter, "text": text, "does": does, "recommended": recommended}


def grant_ask(cls, j, st_c):
    d = CLASSES[cls]
    to = next_tier(cls, st_c["tier"])
    ex = "; ".join(f"{(r.get('target') or '?')} {r.get('at', '')[:10]}" for r in j["examples"])
    aid = f"grant:{cls}:{j['clean']}"
    return {"id": aid, "kind": "grant", "class": cls,
            "question": f"Let ela {d['says']} without asking, and tell you on today.md?",
            "record": f"{j['clean']} applied as drafted over {j['days']} days, none edited, cancelled or corrected · {ex}",
            "options": [option("A", "grant: ela does these and tells you", f"ela dry answer {aid} A", True),
                        option("B", "keep confirming", f"ela dry answer {aid} B"),
                        option("C", "never ask again for this kind", f"ela dry answer {aid} C")],
            "to_tier": to, "sig": hashlib.sha256(aid.encode()).hexdigest()[:12]}


def unsettled(b):
    """The writes an answer still has to make: all of an open batch's; of a failed batch, those that did not land and
    were not struck."""
    return [w for w in b["writes"] if b.get("state") == "open" or w.get("outcome") not in ("landed", "struck")]


def ask_id(b):
    """A batch's ask: `dry:<batch>` while open; `dry:<batch>:retry` once failed, a new ask on today.md whose three
    mornings start when it first shows, not when the batch was first asked."""
    return f"dry:{b['id']}" + (":retry" if b.get("state") == "failed" else "")


def batch_ask(b):
    d = CLASSES[b["class"]]
    n = len(b["writes"])
    noun = d["noun"][0] if n == 1 else d["noun"][1]
    aid = ask_id(b)
    if b.get("state") == "failed":                         # the writes that failed reach him: retry or drop them
        bad = unsettled(b)
        return {"id": aid, "kind": "batch", "class": b["class"], "batch": b["id"],
                "question": f"{len(bad)} of {n} {noun} for {b['scope']} failed ({b['class']}: {d['says']}).",
                "record": "; ".join(f"{w['n']} {w['target']}: {w.get('reason') or 'no reason kept'}" for w in bad),
                "link": note_rel(b["id"]),
                "options": [option("A", "retry the failed writes", f"ela dry answer {aid} A --apply", True),
                            option("B", "drop them", f"ela dry answer {aid} B")],
                "sig": hashlib.sha256(json.dumps(bad, sort_keys=True).encode()).hexdigest()[:12]}
    return {"id": aid, "kind": "batch", "class": b["class"], "batch": b["id"],
            "question": f"{n} {noun} ready for {b['scope']}: {d['says']}.",
            "link": note_rel(b["id"]),
            "options": [option("A", f"apply all {n}" + (" (strike a line in the note to leave it out)" if n > 1 else ""),
                               f"ela dry answer {aid} A --apply", True),
                        option("B", "drop them", f"ela dry answer {aid} B")],
            "sig": hashlib.sha256(json.dumps(b["writes"], sort_keys=True).encode()).hexdigest()[:12]}


def asks(reports, today=None, commit=False, ask_state=None):
    """The asks for today.md, batches first (work waiting: an open batch, or a failed one asked as retry or drop),
    then grant asks. With commit, an expired or dropped ask is
    recorded (a batch: expired unanswered; a grant: the ask returns after ten more clean runs) and each new grant ask is
    stored as open. `ask_state` is the vault's <reports>/ela/asks.json, read when not given."""
    today = today or datetime.datetime.now(TZ).date()
    st = load_state(reports)
    if ask_state is None:
        try:
            ask_state = json.load(open(os.path.join(reports, "ela", "asks.json"), encoding="utf-8"))
        except (OSError, ValueError):
            ask_state = {}
    settle_expired(reports, st, ask_state, commit)
    rows = record(reports)
    out = [batch_ask(b) for b in batches(reports) if b.get("state") in ("open", "failed")]
    for cls in CLASSES:
        if grant_due(cls, rows, st[cls]):
            j = judged(cls, rows, st[cls])
            a = grant_ask(cls, j, st[cls])
            out.append(a)
            if commit:
                st[cls]["ask"] = {"id": a["id"], "at": today.isoformat(), "clean_at": j["clean"]}
                st[cls]["history"].append({"at": now_iso(), "event": "asked", "id": a["id"]})
    if commit:
        save_state(reports, st)
    return out


def settle_expired(reports, st, ask_state, commit):
    """An ask the vault dropped after three mornings with no answer: a batch, open or failed, is recorded expired
    unanswered, once per write it still had to make; a grant ask is marked expired, which lets it return after ten more clean runs."""
    for b in batches(reports):
        s = ask_state.get(ask_id(b)) or {}
        if b.get("state") in ("open", "failed") and s.get("dropped"):
            left = unsettled(b)
            b["state"] = "expired"
            if commit:
                for w in left:
                    append(reports, {"at": now_iso(), "class": b["class"], "verdict": "expired", "target": w["target"],
                                     "command": w["command"], "batch": b["id"], "source": "batch"})
                save_batch(reports, b)
    for cls, x in st.items():
        a = x.get("ask")
        if a and not a.get("answered") and not a.get("expired") and (ask_state.get(a["id"]) or {}).get("dropped"):
            a["expired"] = ask_state[a["id"]]["dropped"]
            x["history"].append({"at": now_iso(), "event": "ask-expired", "id": a["id"]})


# ── batches and the review note ───────────────────────────────────────────────────────────────────────────────
def batches(reports):
    out = []
    for p in sorted(glob.glob(os.path.join(store(reports), "batches", "*.json"))):
        try:
            out.append(json.load(open(p, encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def load_batch(reports, bid):
    try:
        return json.load(open(os.path.join(store(reports), "batches", f"{bid}.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_batch(reports, b):
    atomic_write(os.path.join(store(reports), "batches", f"{b['id']}.json"), json.dumps(b, ensure_ascii=False, indent=1) + "\n")


def note_rel(bid):
    """The review note's place in the vault, beside ela's own pages."""
    return f"ela/dry/{bid}"


WRITE_LINE = re.compile(r"^(?P<lead>[ \t]*(?:[-*][ \t]+)?)(?P<strike>~~)?(?P<n>\d+)\.[ \t]+`(?P<cmd>[^`]+)`(?P<rest>.*?)(?:~~)?[ \t]*$", re.M)


JIRA_KEY = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
JIRA_BROWSE = "https://tvunetworks.atlassian.net/browse/"


def from_file_of(command):
    """The path a command's --from-file names, or None."""
    try:
        toks = shlex.split(command)
    except ValueError:
        toks = command.split()
    for i, t in enumerate(toks):
        if t == "--from-file" and i + 1 < len(toks):
            return toks[i + 1]
        if t.startswith("--from-file="):
            return t.split("=", 1)[1]
    return None


def write_context(w, facts):
    """The indented lines under a numbered write that make it judgeable: per Jira key, a link with summary, status,
    assignee and priority from the fact store; for --from-file, the file's text quoted. A command shows what changes, not
    which ticket it lands on, and a bare key or a path cannot be judged without opening something else. Indented four
    spaces, so WRITE_LINE never reads them as writes and striking or deleting the numbered line still drops the write."""
    out = []
    for key in dict.fromkeys(JIRA_KEY.findall(w["command"])):
        try:
            f = json.load(open(os.path.join(facts, "jira", "issues", f"{key}.json"), encoding="utf-8")).get("fields") or {}
        except (OSError, ValueError, TypeError):
            out.append(f"    - [{key}]({JIRA_BROWSE}{key}) (not in the fact store)")
            continue
        who = (f.get("assignee") or {}).get("displayName") or "unassigned"
        out.append(f"    - [{key}]({JIRA_BROWSE}{key}) {f.get('summary') or ''} · {(f.get('status') or {}).get('name') or '?'}"
                   f" · {who} · priority {(f.get('priority') or {}).get('name') or '?'}")
    path = from_file_of(w["command"])
    if path:
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            out.append(f"    > ({path} is missing)")
        else:
            out += [f"    > {x}".rstrip() for x in text.rstrip("\n").split("\n")]
    return out


def review_note(b, facts=None):
    """The note that shows each exact write of a batch: one numbered line per write, the command in backticks and why,
    and under it the context write_context reads. Striking a line (~~ … ~~) or deleting it leaves the write out; editing
    the command applies it as edited and records an edit. The ask on today.md carries the letters."""
    if facts is None:
        rt = site().get("runtime")
        facts = os.path.join(rt, "facts") if rt else ""
    d = CLASSES[b["class"]]
    L = [f"# {len(b['writes'])} {d['noun'][1] if len(b['writes']) != 1 else d['noun'][0]} for {b['scope']}", "",
         f"Class: **{b['class']}** — {d['says']}. Rule: {d['rule']}.", "",
         "Each line is the exact write. Strike a line (`~~ ~~`) or delete it to leave it out; edit the command to change "
         "it. Then answer the ask on today.md: A applies what is here, B drops the batch.", ""]
    for w in b["writes"]:
        L.append(f"{w['n']}. `{w['command']}` — {w['why']}")
        L += write_context(w, facts)
    if b.get("left_out"):
        L += ["", "Named but not proposed:", ""] + [f"- {x}" for x in b["left_out"]]
    return "\n".join(L) + "\n"


def note_digest(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def read_note(b, text):
    """What the review note says now, against the batch: [(write, verdict, command)] with verdict applied (as drafted),
    edited (the command as it now reads) or cancelled (struck or deleted)."""
    seen = {}
    for m in WRITE_LINE.finditer(text or ""):
        seen[int(m.group("n"))] = (bool(m.group("strike")), m.group("cmd").strip())
    out = []
    for w in b["writes"]:
        if w["n"] not in seen or seen[w["n"]][0]:
            out.append((w, "cancelled", None))
        elif " ".join(seen[w["n"]][1].split()) != " ".join(w["command"].split()):
            out.append((w, "edited", seen[w["n"]][1]))
        else:
            out.append((w, "applied", w["command"]))
    return out


# ── selection: the classes today's case shows ─────────────────────────────────────────────────────────────────
def adf_text(node):
    if isinstance(node, dict):
        t = node.get("text") or ""
        if node.get("type") == "inlineCard":
            t += " " + ((node.get("attrs") or {}).get("url") or "") + " "
        inner = "".join(adf_text(c) for c in node.get("content") or [])
        return t + inner + ("\n" if node.get("type") in ("paragraph", "listItem", "heading") else "")
    if isinstance(node, list):
        return "".join(adf_text(c) for c in node)
    return node if isinstance(node, str) else ""


def links_of(issue):
    out = []
    for l in (issue.get("fields") or {}).get("issuelinks") or []:
        o = l.get("outwardIssue") or l.get("inwardIssue") or {}
        t = l.get("type") or {}
        out.append({"key": o.get("key"), "reads": t.get("outward") if l.get("outwardIssue") else t.get("inward"),
                    "status": ((o.get("fields") or {}).get("status") or {}).get("name"),
                    "summary": (o.get("fields") or {}).get("summary") or ""})
    return out


def owns(issue, owner):
    a = (issue.get("fields") or {}).get("assignee") or {}
    return bool(owner) and owner.lower() in {str(a.get("emailAddress") or "").lower(), str(a.get("displayName") or "").lower(),
                                             str(a.get("accountId") or "").lower()}


# A line that links on purpose: a key from another project counts only on such a line (the parent's own project's keys
# count wherever its text names them).
LINK_VERB = re.compile(r"\bsee\b|\bper\b|\bblock(?:ed|s|ing)? by\b|\bfollow[- ]?up (?:of|to|on)\b|\brelate[sd]?\b|相关", re.I)
DONE = {"done", "closed", "resolved", "cancelled"}


def is_done(issue):
    f = (issue or {}).get("fields") or {}
    st = f.get("status") or {}
    return ((st.get("statusCategory") or {}).get("key") == "done") or (st.get("name") or "").lower() in DONE


def older(child, parent):
    """Whether `child` existed before `parent`. An older ticket that is already Done is a precedent or a reference,
    not a child (MH-3998 named MH-3800, Done, as the path to follow, and ela linked it as contained, 2026-11-25); an
    older open one may be a child an umbrella gathered, so `older` alone decides nothing. By the created times, else by the key's number within one project; unknown → False."""
    a, b = ((child.get("fields") or {}).get("created"), (parent.get("fields") or {}).get("created"))
    if a and b:
        try:
            return parse_ts(a) < parse_ts(b)
        except (TypeError, ValueError):
            pass
    ck, pk = child.get("key") or "", parent.get("key") or ""
    if ck.split("-")[0] == pk.split("-")[0] and ck[len(ck.split("-")[0]) + 1:].isdigit() and pk[len(pk.split("-")[0]) + 1:].isdigit():
        return int(ck.split("-")[1]) < int(pk.split("-")[1])
    return False


def select_link_named(parent, children, before=None):
    """The links a parent's own text names but Jira lacks: [(write)], [left out with why]. `children` {key: issue} for
    the named tickets (a key that could not be read is left out, named). `before` an ISO time: comments after it are not
    read (a replay of a past morning). URLs are not read (ticket_keys); a key from another project counts only on a line
    with a link verb (LINK_VERB); a Done ticket from another project named once is never proposed as `contains`."""
    pk = parent["key"]
    proj = pk.split("-")[0]
    f = parent.get("fields") or {}
    texts = [("description", None, adf_text(f.get("description")))]
    for c in (f.get("comment") or {}).get("comments") or []:
        if before and str(c.get("created") or "") and parse_ts(c["created"]) > parse_ts(before):
            continue
        texts.append(((c.get("author") or {}).get("displayName") or "?", c.get("created"), adf_text(c.get("body"))))
    linked = {l["key"] for l in links_of(parent)}
    named, order, times, loose = {}, [], {}, {}
    for who, at, text in texts:
        for line in (text or "").split("\n"):
            verb = bool(LINK_VERB.search(strip_urls(line)))
            for k in ticket_keys(line):
                if k == pk:
                    continue
                times[k] = times.get(k, 0) + 1
                if k in named:
                    continue
                if k.split("-")[0] != proj and not verb:
                    loose.setdefault(k, who); continue
                rel = bool(re.search(r"\brelate[sd]?\b|相关", line, re.I))
                named[k] = {"who": who, "at": (at or "")[:10], "relates": rel}
                order.append(k)
    left = [f"{k} — another project's key named by {who} with no link verb on its line" for k, who in loose.items()
            if k not in named and k not in linked]
    proposed = []
    for k in order:
        if k in linked:
            continue
        ch = children.get(k)
        if ch is None:
            left.append(f"{k} — named by {named[k]['who']}, could not be read"); continue
        par = (((ch.get("fields") or {}).get("parent") or {}).get("key"))
        if par and (par in linked or par in order):
            left.append(f"{k} — a subtask of {par}, which carries it"); continue
        if k.split("-")[0] != proj and is_done(ch) and times[k] == 1 and not named[k]["relates"]:
            left.append(f"{k} — another project's Done ticket named once: a mention, not a child"); continue
        proposed.append(k)
    writes = []
    for i, k in enumerate(proposed, 1):
        ch = children[k].get("fields") or {}
        t = "relates to" if named[k]["relates"] or (older(children[k], parent) and is_done(children[k])) else "contains"
        cmd = f"ela jira link {pk} {k} --type " + ("\"relates to\"" if t == "relates to" else "contains")
        writes.append({"n": i, "target": k, "command": cmd,
                       "why": f"{(ch.get('summary') or '')[:60]} ({(ch.get('status') or {}).get('name') or '?'}) · named by "
                              f"{named[k]['who']}" + (f", {named[k]['at']}" if named[k]["at"] else "")})
    return writes, left


STATUS_LINE = re.compile(r"\b(" + KEY + r")\b(?:,[ \t]*|[ \t]*\()([A-Za-z][A-Za-z ]*?)[),]")   # "MH-1 (Review" or "(MH-1, Review)"


def select_parent_status(parent, owner, today, out_dir):
    """A status comment from the parent's contained children: one line each, when a status differs from his last
    comment that names them. → ([write], [left out]); the comment's text is written to out_dir."""
    pk = parent["key"]
    kids = [l for l in links_of(parent) if (l["reads"] or "").lower() == "contains"]
    if not kids:
        return [], [f"{pk} — contains no child"]
    mine = [c for c in ((parent.get("fields") or {}).get("comment") or {}).get("comments") or []
            if owner and owner.lower() in {str((c.get("author") or {}).get(x) or "").lower() for x in ("emailAddress", "displayName", "accountId")}]
    said = {}
    for c in mine:
        for k, s in STATUS_LINE.findall(adf_text(c.get("body"))):
            said[k] = s.strip()
    now = {l["key"]: l["status"] for l in kids}
    moved = [k for k in now if said.get(k, "").lower() != (now[k] or "").lower()]
    if not moved:
        return [], [f"{pk} — every child's status is as your last comment says"]
    text = [f"Status — {today:%b} {today.day}. Children of {pk} as Jira shows them:", ""]
    text += [f"- {l['key']} ({l['status']}) {l['summary'][:70]}" for l in kids]
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{pk}-status.txt")
    atomic_write(path, "\n".join(text) + "\n")
    return [{"n": 1, "target": pk, "command": f"ela jira comment {pk} --from-file {path}",
             "why": "moved since your last status comment: " + ", ".join(f"{k} → {now[k]}" for k in moved)
                    + f"; MH's Automation may copy the comment to its {len(kids)} linked children"}], []


def parse_ts(s):
    try:
        t = datetime.datetime.fromisoformat(re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", str(s).replace("Z", "+00:00")))
        return t if t.tzinfo else t.replace(tzinfo=TZ)
    except ValueError:
        return datetime.datetime.min.replace(tzinfo=TZ)


def commands_of(b):
    return sorted(" ".join(w["command"].split()) for w in b.get("writes") or [])


def make_batch(reports, cls, scope, writes, left, today):
    """The batch for one class and scope. An unanswered batch from an earlier day is carried, not asked again: the
    same writes return it under its own id (its note keeps his strikes); different writes supersede it, and the new
    batch is the one asked. Either way one batch per class and scope stays open. A selection with nothing left to write
    (the links were made by hand, say) closes the open batch for that class and scope as `settled`, with a record line,
    so its ask leaves today.md: every reader compares the state to `open`, as for a superseded one."""
    if not writes:
        for p in batches(reports):
            if p.get("state") == "open" and p.get("class") == cls and p.get("scope") == scope:
                p.update(state="settled", settled_at=now_iso())
                save_batch(reports, p)
                append(reports, {"at": now_iso(), "class": cls, "verdict": "settled", "target": scope, "batch": p["id"],
                                 "source": "batch", "how": "the day's selection found nothing left to write"})
        return None
    bid = f"{today.isoformat()}-{cls}-{scope}"
    old = load_batch(reports, bid)
    if old and old.get("state") != "open":
        return old                                         # answered today already: the same batch is not asked twice
    prior = [b for b in batches(reports) if b.get("state") == "open" and b.get("class") == cls and b.get("scope") == scope
             and b["id"] != bid]
    want = sorted(" ".join(w["command"].split()) for w in writes)
    carry = next((b for b in reversed(prior) if commands_of(b) == want), None)
    if carry:
        carry.update(carried=today.isoformat(), left_out=left)
        save_batch(reports, carry)
        b = carry
    else:
        b = {"id": bid, "class": cls, "scope": scope, "made": now_iso(), "state": "open", "writes": writes, "left_out": left}
        save_batch(reports, b)
    for p in prior:
        if p is not carry:
            p.update(state="superseded", superseded_by=b["id"], superseded_at=now_iso())
            save_batch(reports, p)
    return b


# ── tier 1 by decision: written at the pass, kept on record ───────────────────────────────────────────────────
def act(reports, cls, scope, writes, today, apply=False, runner=None, now=None):
    """One set of writes a tier-1 class makes without asking (TIER1_BY_DECISION), run in order through jira.py and kept
    as an applied batch: each write an act with its before-state and undo (jira.py's acts.jsonl, ELA_ACT), a record row
    each, and ela/dry/did.md lists them. A write that fails stops the set. The batch id is the class, the scope and the
    day, so a scope gets at most one set a day: a second is refused. A class a correction returned to confirm (tier 3)
    is not written: the set becomes an ordinary open batch, asked on today.md. Each write must match the class's
    commands. → {batch, state, did: [...], ok}; raises ValueError for a class outside TIER1_BY_DECISION or a write the
    class does not admit."""
    if cls not in TIER1_BY_DECISION:
        raise ValueError(f"{cls} is not a tier-1 class by decision")
    rx = re.compile(CLASSES[cls]["command"])
    for w in writes:
        if not rx.match(" ".join(w["command"].split())):
            raise ValueError(f"{cls} does not admit: {w['command']}")
    bid = f"{today.isoformat()}-{cls}-{scope}"
    old = load_batch(reports, bid)
    if old and old.get("state") in ("applied", "open"):
        return {"batch": bid, "state": "refused", "ok": False, "did": [f"{scope}: one set a day; {bid} is already {old['state']}"]}
    writes = [dict(w, n=i) for i, w in enumerate(writes, 1)]
    if load_state(reports)[cls]["tier"] != 1:
        if not apply:
            return {"batch": bid, "state": "would ask", "ok": True, "did": [f"{cls} is back at your confirm: the set is asked on today.md"]}
        b = make_batch(reports, cls, scope, [{k: w[k] for k in ("n", "target", "command", "why")} for w in writes], [], today)
        return {"batch": b["id"], "state": "open", "ok": True, "did": [f"{cls} is back at your confirm: asked as {b['id']}"]}
    did, ok = [], True
    for w in writes:
        if not ok:
            w["outcome"] = "skipped"
            did.append(f"{w['n']} skipped: an earlier write of the set failed"); continue
        a_id = act_id(bid, w["n"])
        code, out = (runner(w["command"], apply) if runner else
                     run_write(w["command"], apply, action=a_id, word=f"{cls} (tier 1 by decision)", cls=cls, own=True))
        ok = code == 0
        w["outcome"] = "landed" if ok else "failed"
        if not ok:
            w["reason"] = (out.splitlines() or ["no output"])[-1][:200]
        did.append(f"{w['n']} {'applied' if apply else 'dry run'}: {'ok' if ok else 'failed'} — "
                   f"{(out.splitlines() or [''])[-1]}"[:300])
        if apply and ok:
            append(reports, {"at": now_iso(now), "class": cls, "verdict": "applied", "as_drafted": True, "target": w["target"],
                             "command": w["command"], "why": w.get("why"), "batch": bid, "act": a_id, "source": "tier1"})
    if apply:
        save_batch(reports, {"id": bid, "class": cls, "scope": scope, "made": now_iso(now), "state": "applied" if ok else "failed",
                             "writes": [{k: w[k] for k in ("n", "target", "command", "why", "outcome", "reason") if k in w} for w in writes],
                             "left_out": [],
                             "answered": {"letter": None, "at": now_iso(now), "by": "tier 1 by decision"}})
    return {"batch": bid, "state": ("applied" if ok else "failed") if apply else "dry run", "ok": ok, "did": did}


def place(reports, cls, scope, writes, left, today, apply=False, out_dir=None, runner=None, now=None):
    """Where a selection goes (link-named, parent-status; vault plan 2026-11-24 step 3). At tier 1 by decision it is
    ela's own set: an open batch of the class and scope settles, and `act` writes it (a dry run unless `apply`), each
    link its own act with its own undo and no comment on the ticket (jira.py NOTE_VERBS); listed in ela/dry/did.md. Back at confirm after a correction (tier 3),
    it is an ordinary batch, asked on today.md. → {"batch": id or None, "state", "did": [...], "left_out"}."""
    if cls in TIER1_BY_DECISION and load_state(reports)[cls]["tier"] == 1:
        if apply:
            make_batch(reports, cls, scope, [], left, today)          # yesterday's open ask for this scope leaves today.md
        if not writes:
            return {"batch": None, "state": "nothing to write", "did": [], "left_out": left}
        r = act(reports, cls, scope, writes, today, apply=apply, runner=runner, now=now)
        return dict(r, left_out=left)
    b = make_batch(reports, cls, scope, writes, left, today)
    return {"batch": b["id"] if b else None, "state": b["state"] if b else "nothing to write",
            "did": [f"{len(b['writes'])} write(s) asked on today.md"] if b else [], "left_out": left}


def tier1_done(reports, day):
    """The tier-1 acts written on `day` (record rows from `act`): [(act id, text, undo)], the undo the reverse atom
    jira.py kept for it (`ela dry undo <act> --apply`), or a note when the verb has none."""
    rows = [r for r in record(reports) if r.get("source") == "tier1" and (r.get("at") or "")[:10] == day]
    kept = {a.get("act") for a in acts(reports)}
    out = []
    for r in rows:
        undo = f"ela dry undo {r['act']} --apply" if r.get("act") in kept else "no reverse atom: undo it on the ticket"
        out.append((r["act"], f"{r.get('target')}: {r.get('why') or r.get('command')}", undo))
    return out


# ── the answer ────────────────────────────────────────────────────────────────────────────────────────────────
def run_write(command, apply, action=None, word=None, cls=None, own=False):
    """One write through its own capability: `ela jira …` becomes jira.py; --apply only when the answer carried it.
    The write log records the batch and the answer it ran under (ELA_ACTION, ELA_WORD); the act (ELA_ACT, the same
    id) and its class (ELA_CLASS) go with the before-state jira.py keeps, so `ela dry undo` can find it. `command`
    is a string or an argv list."""
    import shlex
    argv = shlex.split(command) if isinstance(command, str) else list(command)
    if argv[:2] != ["ela", "jira"]:
        raise ValueError(f"not a Jira write: {command}")
    env = os.environ.get("ELA_ENV_FILE") or site().get("env")
    cmd = ["python3", JIRA] + (["--env-file", env] if env else []) + argv[2:] + (["--apply"] if apply else [])
    env = dict(os.environ, **({"ELA_ACTION": action, "ELA_ACT": action} if action else {}), **({"ELA_WORD": word} if word else {}),
               **({"ELA_CLASS": cls} if cls else {}), **({"ELA_OWN": "1"} if own else {}))
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
    return p.returncode, (p.stdout + p.stderr).strip()


def answer(reports, aid, letter, note_text=None, apply=False, runner=run_write, now=None):
    """His letter on one ask. → {ask, letter, did: [...]}; raises KeyError for an unknown ask, ValueError for a letter
    the ask does not offer."""
    letter = letter.upper()
    st = load_state(reports)
    if aid.startswith("dry:"):
        b = load_batch(reports, aid[4:].removesuffix(":retry"))
        if not b:
            raise KeyError(aid)
        if letter not in "AB":
            raise ValueError(f"{aid} offers A or B, not {letter}")
        if b.get("state") not in ("open", "failed"):
            return {"ask": aid, "letter": letter, "did": [f"already {b['state']}"
                                                          + (f" by {b['superseded_by']}" if b.get("superseded_by") else "")]}
        did = []
        # a failed batch is answered again for the writes that failed; what landed or was struck is settled
        pending = unsettled(b)
        if letter == "B":
            for w in pending:
                append(reports, {"at": now_iso(now), "class": b["class"], "verdict": "cancelled", "letter": "B", "target": w["target"],
                                 "command": w["command"], "batch": b["id"], "source": "batch"})
            b["state"] = "dropped"
            did.append(f"dropped {len(pending)}")
        else:
            plan = read_note(b, note_text) if note_text is not None else [(w, "applied", w["command"]) for w in b["writes"]]
            plan = [(w, v, c) for w, v, c in plan if w in pending]
            failed = 0
            for w, verdict, cmd in plan:
                if verdict == "cancelled":
                    if apply:
                        append(reports, {"at": now_iso(now), "class": b["class"], "verdict": "cancelled", "letter": "A", "target": w["target"],
                                         "command": w["command"], "batch": b["id"], "source": "batch", "how": "struck"})
                        w["outcome"] = "struck"
                    did.append(f"{w['n']} left out"); continue
                code, out = (run_write(cmd, apply, action=act_id(b["id"], w["n"]), word=f"answer {aid} {letter}", cls=b["class"])
                             if runner is run_write else runner(cmd, apply))
                failed += code != 0
                did.append(f"{w['n']} {'applied' if apply else 'dry run'}{' as edited' if verdict == 'edited' else ''}: "
                           f"{'ok' if code == 0 else 'failed'} — {out.splitlines()[-1] if out else ''}"[:200])
                if apply:
                    w["outcome"] = "landed" if code == 0 else "failed"
                    if code:
                        w["reason"] = (out.splitlines() or ["no output"])[-1][:200]
                    else:
                        w.pop("reason", None)
                if apply and code == 0:
                    append(reports, {"at": now_iso(now), "class": b["class"], "verdict": verdict, "letter": "A", "target": w["target"],
                                     "command": cmd, "drafted": w["command"], "as_drafted": verdict == "applied",
                                     "batch": b["id"], "act": act_id(b["id"], w["n"]), "source": "batch"})
            if apply:
                # a write that failed keeps the batch answerable: `failed`, and a later A retries only those writes
                b["state"] = "failed" if failed else "applied"
                if failed:
                    did.append(f"{failed} failed: the batch stays answerable, and A again retries only those")
        if apply or letter == "B":
            b["answered"] = {"letter": letter, "at": now_iso(now)}
            save_batch(reports, b)
        return {"ask": aid, "letter": letter, "did": did}
    m = re.fullmatch(r"grant:([a-z-]+):(\d+)", aid)
    if not m or m.group(1) not in CLASSES:
        raise KeyError(aid)
    cls, x = m.group(1), st[m.group(1)]
    if letter not in "ABC":
        raise ValueError(f"{aid} offers A, B or C, not {letter}")
    if CLASSES[cls].get("never"):
        raise ValueError(f"{cls} is tier 3 by rule ({CLASSES[cls]['never']}); it is never granted")
    if letter == "A" and not reversible(cls)[0]:
        raise ValueError(f"{cls} has no reverse atom ({', '.join(reversible(cls)[1])}); it is not granted until it can be undone")
    ask = x.get("ask") or {"id": aid, "clean_at": int(m.group(2))}
    ask["answered"] = {"letter": letter, "at": now_iso(now)}
    x["ask"] = ask
    did = []
    if letter == "A":
        was, x["tier"] = x["tier"], next_tier(cls, x["tier"])
        x["history"].append({"at": now_iso(now), "event": "granted", "from": was, "to": x["tier"], "id": aid})
        did.append(f"{cls}: tier {was} → {x['tier']}")
    elif letter == "B":
        x["history"].append({"at": now_iso(now), "event": "declined", "id": aid})
        did.append(f"{cls}: stays at tier {x['tier']}; asked again after {ASK_AGAIN_AFTER} more clean runs")
    else:
        x["never_ask"] = now_iso(now)
        x["history"].append({"at": now_iso(now), "event": "never", "id": aid})
        did.append(f"{cls}: never asked again")
    save_state(reports, st)
    return {"ask": aid, "letter": letter, "did": did}


# ── undo: an act's reverse, from the before-state it kept ─────────────────────────────────────────────────────
def act_id(batch, n):
    """An act's name: its batch and its line (`2026-11-12-link-named-MH-3735#2`); the write log's ELA_ACTION is the same."""
    return f"{batch}#{n}"


def acts_path(reports):
    return os.path.join(reports, "ela", "acts.jsonl")


def acts(reports, ref=None):
    """The acts on record, oldest first, each {act, class, key, verb, before, undo, at, undone}: `ref` an act id, or a
    batch id for every act of it. An act jira.py logged without a class is classed by its verb."""
    rows = read_jsonl(acts_path(reports))
    undone = {r["undone"]: r for r in rows if r.get("undone")}
    out = []
    for r in rows:
        if r.get("undone") or not r.get("undo"):
            continue
        a = r.get("act") or ""
        if ref and not (a == ref or a.startswith(ref + "#")):
            continue
        cls = r.get("class") or class_of_write({"system": "jira", "verb": r.get("verb")})
        out.append(dict(r, **{"class": cls, "undone": (undone.get(a) or {}).get("at") if a else None}))
    return out


def undo(reports, ref, apply=False, runner=None, now=None):
    """The reverse of an act (or of every act of a batch): each undo atom through jira.py, a dry run unless `apply`.
    Applied and all ok, the act is marked undone and its class takes the correction (a revert): a granted class returns
    to confirm. → {ref, did: [...], notice}; raises KeyError when no act on record matches."""
    found = acts(reports, ref)
    if not found:
        raise KeyError(ref)
    did, ok, done = [], True, set()
    for r in found:
        if r["undone"]:
            did.append(f"{r['act']} {r['key']}: already undone {r['undone'][:16]}"); continue
        word = f"undo {ref}"
        code, out = (runner(r["undo"], apply) if runner else
                     run_write(r["undo"], apply, action=f"undo:{r['act']}", word=word, cls=r["class"]))
        ok = ok and code == 0
        last = out.splitlines()[-1] if out else ""
        did.append(f"{r['act'] or '?'} {r['key']} {r['verb']}: {'undone' if apply and code == 0 else 'dry run' if code == 0 else 'failed'}"
                   f" — {' '.join(r['undo'][2:])}" + (f" · {last}" if last else ""))
        if apply and code == 0 and r.get("act"):
            done.add((r["act"], r["class"]))
    notice = None
    if apply:
        os.makedirs(os.path.dirname(acts_path(reports)), exist_ok=True)
        with open(acts_path(reports), "a", encoding="utf-8") as f:
            for a, _ in sorted(done):
                f.write(json.dumps({"at": now_iso(now), "undone": a}, ensure_ascii=False) + "\n")
        for cls in sorted({c for _, c in done if c in CLASSES}):
            notice = correct(reports, cls, "revert", ref=ref, note="undone by ela dry undo", now=now) or notice
    return {"ref": ref, "applied": apply, "ok": ok, "did": did, "notice": notice}


def correct(reports, cls, how, ref=None, note=None, now=None, extra=None):
    """A correction after the fact (a revert, a reply against it, his `ela:` line, his `wrong:` in did.md). A class
    above its base tier returns to confirm (tier 3) and the fall is noted for today.md. `extra` is merged into the
    record row (the act, the review source). → the notice, or None when the class was at confirm."""
    if cls not in CLASSES:
        raise KeyError(cls)
    st = load_state(reports)
    x = st[cls]
    append(reports, dict({"at": now_iso(now), "class": cls, "verdict": "reverted" if how == "revert" else "corrected", "how": how,
                          "target": ref, "note": note, "source": "correction"}, **(extra or {})))
    if x["tier"] == 3:
        save_state(reports, st)
        return None
    was, x["tier"] = x["tier"], 3
    why = f"{how}" + (f" on {ref}" if ref else "") + (f": {note}" if note else "")
    x["history"].append({"at": now_iso(now), "event": "fell", "from": was, "to": 3, "why": why})
    x["notice"] = {"at": now_iso(now), "text": f"{cls} is back to your confirm ({why})."}
    save_state(reports, st)
    return x["notice"]["text"]


def fold_corrections(reports):
    """The evening review's correction rows whose rule is a class (<reports>/review/*-replay.json, *-reader.json):
    each corrects its class once (by day, key, rule)."""
    seen = {(r.get("at", "")[:10], r.get("target"), r.get("class")) for r in record(reports) if r.get("source") == "correction"}
    for p in sorted(glob.glob(os.path.join(reports, "review", "*-replay.json")) + glob.glob(os.path.join(reports, "review", "*-reader.json"))):
        day = os.path.basename(p)[:10]
        try:
            j = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = j.get("rows") if isinstance(j, dict) else j
        for r in rows or []:
            if isinstance(r, dict) and r.get("kind") == "correction" and r.get("rule") in CLASSES and (day, r.get("key"), r["rule"]) not in seen:
                seen.add((day, r.get("key"), r["rule"]))
                correct(reports, r["rule"], r.get("how") or "correction", r.get("key"), (r.get("now") or r.get("what") or "")[:120],
                        now=datetime.datetime.fromisoformat(day + "T21:00:00+08:00"))


def did(reports, day):
    """What granted classes did without confirm on a day, from the runner's actions files: tier-1 actions under a class
    rule, applied. → (Facts line or None, [(n, text, undo)])."""
    try:
        ran = json.load(open(os.path.join(reports, "runner", f"{day}-actions.json"), encoding="utf-8"))
    except (OSError, ValueError):
        ran = []
    ran = ran.get("actions") if isinstance(ran, dict) else ran
    rows = [a for a in ran or [] if a.get("rule") in CLASSES and a.get("tier") in (1, 2) and a.get("applied")]
    own = tier1_done(reports, day)
    if not rows and not own:
        return None, []
    counts = {}
    for a in rows:
        counts[a["rule"]] = counts.get(a["rule"], 0) + 1
    sets = {(r["class"], r.get("batch")) for r in record(reports) if r.get("source") == "tier1" and (r.get("at") or "")[:10] == day}
    for c, _ in sets:                                      # a tier-1 class counts its sets, one per ticket
        counts[c] = counts.get(c, 0) + 1
    words = ", ".join(f"{n} {CLASSES[c]['noun'][0] if n == 1 else CLASSES[c]['noun'][1]}" for c, n in counts.items() if c in CLASSES)
    return f"ela did: {words}", [(a["n"], a.get("text") or a.get("command"), f"ela: undo {a['n']}") for a in rows] + own


# ── his review of did.md ───────────────────────────────────────────────────────────────────────────────────────
DID_LINE = re.compile(r"^\s*-\s+(?:~~)?(\S+?)\.\s.*?·\s*`[^`]*`(.*)$")
MARK = re.compile(r"(?:^|[\s—:·-])(ok|wrong)\b\s*(?::\s*(.*))?$", re.I)


def did_marks(text):
    """His marks in a did.md: beside a line's undo word (or on an indented line under it) `ok`, or `wrong: <why>`.
    → [(id, "ok"|"wrong", why or None)], one per line, the last mark winning. The undo word itself is read elsewhere."""
    out, cur = {}, None
    for line in (text or "").splitlines():
        m = DID_LINE.match(line)
        if m:
            cur, tail = m.group(1), m.group(2)
        elif cur and line.startswith((" ", "\t")) and line.strip():
            tail = line.strip()
        else:
            cur = None if not line.strip() == "" else cur
            continue
        k = MARK.search(tail.strip().strip("—·- ").strip())
        if k and k.group(1).lower() == "ok":
            out[cur] = ("ok", None)
        elif k and k.group(1).lower() == "wrong":
            why = (k.group(2) or "").strip().strip("<>") or None
            out[cur] = ("wrong", why[:300] if why else None)
    return [(i, m, w) for i, (m, w) in out.items()]


def reviewed(reports):
    """Each act he has marked in did.md: {id: (mark, why)}."""
    out = {}
    for r in record(reports):
        if r.get("review") and r.get("act"):
            out[r["act"]] = ("ok" if r.get("verdict") == "confirmed" else "wrong", r.get("note"))
    return out


def did_class(reports, ident, day):
    """The class of a did.md line: a tier-1 act's record row, else the runner action `n` of that day."""
    for r in record(reports):
        if r.get("act") == ident and r.get("class"):
            return r["class"], r.get("target")
    try:
        ran = json.load(open(os.path.join(reports, "runner", f"{day}-actions.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    for a in (ran.get("actions") if isinstance(ran, dict) else ran) or []:
        if str(a.get("n")) == str(ident) and a.get("rule") in CLASSES:
            return a["rule"], a.get("key") or a.get("command")
    return None, None


def review(reports, text, day, now=None):
    """His marks in did.md, recorded once each: `ok` a confirmed row; `wrong: <why>` a correction (the class returns to
    confirm) whose cause he gave, so the case is admitted to the class's corpus on his word (decision 2026-11-24,
    amendment on learning from ela's own writes). A runner action's bare number is read against `day`, the page's date;
    it is stored as `<day>#<n>` so another day's number does not collide. → [line done]."""
    seen, done = reviewed(reports), []
    for ident, mark, why in did_marks(text):
        key = ident if "#" in ident else f"{day}#{ident}"
        if key in seen:
            continue
        cls, target = did_class(reports, ident, day)
        if not cls:
            done.append(f"{ident}: no class on record, mark left unread"); continue
        if mark == "ok":
            append(reports, {"at": now_iso(now), "class": cls, "verdict": "confirmed", "target": target, "act": key,
                             "review": True, "source": "review"})
            done.append(f"{ident}: confirmed")
        else:
            correct(reports, cls, "correction", ref=target, note=why, now=now,
                    extra={"act": key, "review": True, "corpus": "admitted" if why else "waiting for a cause"})
            done.append(f"{ident}: wrong — {cls} back to confirm" + ("" if why else "; no cause given, the corpus waits for one"))
        seen[key] = (mark, why)
    return done


def corpus_cases(reports):
    """The wrong proposals admitted on his word, for the class corpus (tests/corpus/<class>/): his did.md `wrong: <why>`
    rows. Improve items he confirmed add theirs (`ela improve corpus`). → [{class, act, target, cause, at}]."""
    return [{"class": r["class"], "act": r.get("act"), "target": r.get("target"), "cause": r.get("note"), "at": r.get("at"),
             "source": "did.md"}
            for r in record(reports) if r.get("review") and r.get("corpus") == "admitted"]


def notices(reports, day):
    """Falls dated `day`: one line each for today.md."""
    st = load_state(reports)
    return [x["notice"]["text"] for x in st.values() if (x.get("notice") or {}).get("at", "")[:10] == day]


# ── seeding from history ──────────────────────────────────────────────────────────────────────────────────────
def class_of_action(a):
    """A runner action's class, as far as its own fields attribute it; None when nothing does."""
    if a.get("rule") in CLASSES:
        return a["rule"]
    kind, cmd = a.get("kind"), a.get("command") or ""
    if kind == "close" or re.search(r"\bjira (?:close|transition)\b.*--terminal", cmd):
        return "close"
    if kind == "slack" and re.search(r"\bslack post @|\bDM\b|archives/D[A-Z0-9]+", cmd):
        return "message-to-person"
    if kind in ("fixed-in", "label") or re.match(r"^ela jira (?:fixed-in|label)\b", cmd):
        return "release-reconcile"
    if kind == "assign" or re.match(r"^ela jira assign\b", cmd):
        return "assign-by-rule"
    if re.match(r"^ela jira link\b", cmd):
        return "link-named"
    return None


def class_of_write(w):
    verb = w.get("verb")
    if w.get("system") == "slack":
        return "message-to-person" if str(w.get("where") or "").startswith("DM to") else None
    return {"link": "link-named", "fixed-in": "release-reconcile", "label": "release-reconcile", "assign": "assign-by-rule",
            "close": "close"}.get(verb)


def seed(reports):
    """The record from history, as far as it can be attributed. → rows. Each runner action with a verdict is a row
    (applied by `apply N` is as drafted; handled himself is an edit; vetoed or cancelled is cancelled; an ask the vault
    dropped unanswered is expired). Each write in writes.jsonl no applied action accounts for is a row applied with its
    draft unknown: it counts in the totals, never toward maturity. Comments and team posts are not attributed to
    parent-status: nothing in the log tells a status comment from another."""
    rows, used = [], []
    try:
        ask_state = json.load(open(os.path.join(reports, "ela", "asks.json"), encoding="utf-8"))
    except (OSError, ValueError):
        ask_state = {}
    dropped_keys = {k for k, v in ask_state.items() if v.get("dropped")}
    for p in sorted(glob.glob(os.path.join(reports, "runner", "*-actions.json"))):
        day = os.path.basename(p)[:10]
        try:
            acts = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        acts = acts.get("actions") if isinstance(acts, dict) else acts
        for a in acts or []:
            cls = class_of_action(a)
            if not cls:
                continue
            keys = sorted(set(KEY_RX.findall(re.split(r"\s--", a.get("command") or "", 1)[0])))
            base = {"class": cls, "target": ",".join(keys) or None, "command": a.get("command"), "source": f"seed:actions {day} #{a.get('n')}"}
            # a single Fixed In or label drafted before the release-reconcile rule was not selected by it: totals only
            before_rule = cls == "release-reconcile" and a.get("rule") != "release-reconcile"
            if a.get("applied"):
                rows.append(dict(base, at=str(a["applied"]), verdict="applied", letter="A", as_drafted=None if before_rule else True))
                used.append((keys, parse_ts(a["applied"])))
            elif a.get("by_owner"):
                at = a["by_owner"].get("at") if isinstance(a["by_owner"], dict) else a["by_owner"]
                at = str(at) if str(at or "")[:2] == "20" else day + "T12:00:00+08:00"
                rows.append(dict(base, at=at, verdict="edited", as_drafted=False, how="handled it himself"))
                used.append((keys, None))
            elif a.get("vetoed") or a.get("cancelled"):
                rows.append(dict(base, at=day + "T10:00:00+08:00", verdict="cancelled", letter="B"))
            elif keys and "keys:" + ",".join(keys) in dropped_keys and ask_state["keys:" + ",".join(keys)]["dropped"] == day:
                rows.append(dict(base, at=day + "T09:00:00+08:00", verdict="expired"))
    for w in read_jsonl(os.path.join(reports, "ela", "writes.jsonl")):
        if not w.get("ok"):
            continue
        cls = class_of_write(w)
        if not cls:
            continue
        t = parse_ts(w.get("at"))
        if w.get("key") and any(w["key"] in k and (at is None or abs((t - at).total_seconds()) < 900) for k, at in used):
            continue                                       # the applied action above is this write
        rows.append({"class": cls, "at": w.get("at"), "verdict": "applied", "as_drafted": None, "target": w.get("key"),
                     "source": "seed:writes", "unattended": w.get("unattended")})
    rows.sort(key=lambda r: r.get("at") or "")
    return rows


# ── the commands ──────────────────────────────────────────────────────────────────────────────────────────────
def reports_root(a):
    return a.reports or site().get("reports") or ""


def emit(a, obj, lines):
    if getattr(a, "json", False):
        print(json.dumps(obj, ensure_ascii=False, indent=1))
    else:
        print("\n".join(lines))


def cmd_classes(a):
    emit(a, CLASSES, [f"{c:20} tier {CLASSES[c]['base']}  {CLASSES[c]['says']}" + ("  · never proposed" if CLASSES[c].get("never") else "")
                      for c in CLASSES])


def cmd_status(a):
    r = reports_root(a)
    fold_corrections(r)
    st, rows = load_state(r), record(r)
    out, lines = [], []
    for c in CLASSES:
        j = judged(c, rows, st[c])
        j.update(tier=st[c]["tier"], never=CLASSES[c].get("never"), ask=st[c].get("ask"), never_ask=st[c].get("never_ask"),
                 reversible=None if CLASSES[c].get("never") else reversible(c)[0])
        out.append(j)
        t = j["totals"]
        rec = " · ".join(f"{t[v]} {v}" for v in VERDICTS if t[v])
        state = ("never proposed (tier 3 by rule)" if j["never"] else
                 "never proposed until it can be undone: " + ", ".join(reversible(c)[1]) if not j["reversible"] else "at the top of its ladder" if not can_rise(c, st[c]) and not j["never_ask"]
                 else "never asked again (his word)" if j["never_ask"] else "mature: one grant ask" if j["mature"] else "needs " + "; ".join(j["needs"]))
        lines.append(f"{c:20} tier {j['tier']}  {rec or 'no record'}"
                     + (f" ({j['applied_unknown_draft']} applied, draft unknown)" if j["applied_unknown_draft"] else "")
                     + f"\n{'':20} {state}")
    waiting = [b for b in batches(r) if b.get("state") == "open"]
    lines.append(f"{len(waiting)} batch{'es' if len(waiting) != 1 else ''} waiting" + "".join(f"\n  {b['id']}: {len(b['writes'])}" for b in waiting))
    emit(a, {"classes": out, "waiting": [b["id"] for b in waiting]}, lines)


def cmd_seed(a):
    r = reports_root(a)
    rows = seed(r)
    by = {}
    for x in rows:
        k = by.setdefault(x["class"], {})
        k[x["verdict"]] = k.get(x["verdict"], 0) + 1
    if a.apply:
        atomic_write(os.path.join(store(r), "record-seed.jsonl"), "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows))
    emit(a, {"rows": len(rows), "by_class": by, "written": a.apply},
         [f"{c:20} " + " · ".join(f"{n} {v}" for v, n in sorted(v.items())) for c, v in sorted(by.items())]
         + [f"{len(rows)} rows " + ("written to record-seed.jsonl" if a.apply else "(dry run; --apply writes record-seed.jsonl)")])


def env_value(path, name):
    """One value from the site's env file (the file bin/ela passes as --env-file), '' when it is not there."""
    try:
        for line in open(path or "", encoding="utf-8"):
            k, sep, v = line.strip().partition("=")
            if sep and k.strip() == name and not line.lstrip().startswith("#"):
                return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def owner_of(a_owner=None, env_file=None):
    """The owner as the other skills find him: --owner, then JIRA_EMAIL in the environment, then JIRA_EMAIL in the
    env file bin/ela loads (--env-file, ELA_ENV_FILE, site.json `env`)."""
    return (a_owner or os.environ.get("JIRA_EMAIL")
            or env_value(env_file or os.environ.get("ELA_ENV_FILE") or site().get("env"), "JIRA_EMAIL") or "")


def read_issue(key, env):
    cmd = ["python3", JIRA] + (["--env-file", env] if env else []) + ["read", key, "--json"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode:
        return None
    text = "\n".join(l for l in p.stdout.splitlines() if not l.startswith("#"))
    try:
        return json.loads(text)
    except ValueError:
        return None


def cmd_draft(a):
    r = reports_root(a)
    if a.cls not in ("link-named", "parent-status"):
        print(f"no selector for {a.cls}: link-named and parent-status are drafted here; release-reconcile is drafted "
              "by `ela release reconcile`", file=sys.stderr); sys.exit(EX_USAGE)
    env = a.env_file or os.environ.get("ELA_ENV_FILE") or site().get("env")
    parent = json.load(open(siteguard.guard(a.issue_file), encoding="utf-8")) if a.issue_file else read_issue(a.key, env)
    if not parent:
        print(f"{a.key}: could not be read", file=sys.stderr); sys.exit(EX_REMOTE)
    owner = owner_of(a.owner, env)
    if not owns(parent, owner):
        emit(a, {"batch": None, "why": "not his"}, [f"{a.key}: not assigned to the owner; the class covers parents he owns"]); return
    today = datetime.date.fromisoformat(a.date) if a.date else datetime.datetime.now(TZ).date()
    od = os.path.join(a.out_dir or os.path.join(site().get("runtime") or os.path.join(r, "..", ".ela"), "dry"), today.isoformat())
    if a.cls == "link-named":
        children = {}
        for p in a.child_file or []:
            c = json.load(open(p, encoding="utf-8"))
            children[c["key"]] = c
        if not a.issue_file:
            for k in sorted(set(ticket_keys(json.dumps((parent.get("fields") or {}).get("comment"))))
                            | set(ticket_keys(json.dumps((parent.get("fields") or {}).get("description"))))):
                if k != parent["key"] and k not in children:
                    c = read_issue(k, env)
                    if c:
                        children[k] = c
        writes, left = select_link_named(parent, children, before=a.before)
    else:
        writes, left = select_parent_status(parent, owner, today, od)
    res = place(r, a.cls, parent["key"], writes, left, today, apply=a.apply, out_dir=od)
    emit(a, dict(res, writes=writes),
         [f"{a.cls} {parent['key']}: {res['state']}" + (f" ({res['batch']})" if res.get("batch") else "")]
         + [f"  {w['n']}. {w['command']} — {w['why']}" for w in writes] + [f"  {x}" for x in res.get("did") or []]
         + [f"  left out: {x}" for x in left])


def cmd_batch(a):
    b = load_batch(reports_root(a), a.id)
    if not b:
        print(f"no batch {a.id}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    emit(a, b, [review_note(b)])


def cmd_asks(a):
    today = datetime.date.fromisoformat(a.date) if a.date else None
    out = asks(reports_root(a), today)
    emit(a, out, [f"{x['id']}: {x['question']}\n" + "\n".join(f"  {o['letter']}{' (recommended)' if o['recommended'] else ''}: {o['text']}"
                                                            for o in x["options"]) for x in out] or ["no ask"])


def cmd_answer(a):
    r = reports_root(a)
    note = None
    if a.aid.startswith("dry:"):
        path = a.note or os.path.join(site().get("vault") or "", note_rel(a.aid[4:]) + ".md")
        try:
            note = open(path, encoding="utf-8").read()
        except OSError:
            note = None                                    # no note on disk: the batch as drafted
    try:
        res = answer(r, a.aid, a.letter, note, a.apply)
    except KeyError:
        print(f"no ask {a.aid}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    except ValueError as x:
        print(str(x), file=sys.stderr); sys.exit(EX_USAGE)
    emit(a, res, [f"{a.aid} {res['letter']}:"] + [f"  {d}" for d in res["did"]]
         + ([] if a.apply or not a.aid.startswith("dry:") or res["letter"] != "A" else ["dry run — pass --apply to write"]))


def cmd_correct(a):
    r = reports_root(a)
    now = datetime.datetime.fromisoformat(a.date + "T12:00:00+08:00") if a.date else None
    try:
        n = correct(r, a.cls, a.how, a.ref, a.note, now)
    except KeyError:
        print(f"no class {a.cls}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    emit(a, {"notice": n}, [n or f"{a.cls}: recorded; it was already at confirm"])


def cmd_undo(a):
    try:
        res = undo(reports_root(a), a.ref, a.apply)
    except KeyError:
        print(f"no act {a.ref} on record (<reports>/ela/acts.jsonl)", file=sys.stderr); sys.exit(EX_NOTFOUND)
    emit(a, res, [f"undo {a.ref}:"] + [f"  {d}" for d in res["did"]] + ([res["notice"]] if res["notice"] else [])
         + ([] if a.apply else ["dry run — pass --apply to undo"]))
    if not res["ok"]:
        sys.exit(EX_REMOTE)


def cmd_acts(a):
    rows = [r for r in acts(reports_root(a)) if not a.cls or r["class"] == a.cls]
    emit(a, rows, [f"{r['at'][:16]}  {r['act'] or '(no act)'}  {r['class'] or '?'}  {r['key']} {r['verb']}  before {json.dumps(r['before'], ensure_ascii=False)}"
                   + (f"  undone {r['undone'][:16]}" if r["undone"] else f"  · ela dry undo {r['act']}" if r["act"] else "") for r in rows] or ["no act on record"])


def cmd_did(a):
    day = a.date or datetime.datetime.now(TZ).date().isoformat()
    line, rows = did(reports_root(a), day)
    emit(a, {"line": line, "rows": rows}, [line or "ela did nothing without confirm"] + [f"  {n}. {t} · {u}" for n, t, u in rows])


def main():
    p = argparse.ArgumentParser(description="Dry runs by class: the record, the grant and the fall.",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("--env-file"); p.add_argument("--reports", help="the reports root (default: site.json)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("classes"); s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_classes)
    s = sub.add_parser("status"); s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_status)
    s = sub.add_parser("seed"); s.add_argument("--apply", action="store_true"); s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_seed)
    s = sub.add_parser("draft"); s.add_argument("cls", choices=sorted(CLASSES)); s.add_argument("key")
    s.add_argument("--issue-file"); s.add_argument("--child-file", nargs="*"); s.add_argument("--owner", help="the owner's Jira email or name (default JIRA_EMAIL, from the environment or the env file)")
    s.add_argument("--before", help="read only comments before this ISO time (a replay)"); s.add_argument("--date"); s.add_argument("--out-dir")
    s.add_argument("--apply", action="store_true", help="at tier 1 (by decision) write the set, each link signed; otherwise a dry run")
    s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_draft)
    s = sub.add_parser("batch"); s.add_argument("id"); s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_batch)
    s = sub.add_parser("asks"); s.add_argument("--date"); s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_asks)
    s = sub.add_parser("answer"); s.add_argument("aid"); s.add_argument("letter", choices=list("ABCabc"))
    s.add_argument("--note", help="the review note (default: the vault's copy)"); s.add_argument("--apply", action="store_true")
    s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_answer)
    s = sub.add_parser("correct"); s.add_argument("cls"); s.add_argument("--how", choices=("revert", "correction", "word"), required=True)
    s.add_argument("--ref"); s.add_argument("--note"); s.add_argument("--date"); s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_correct)
    s = sub.add_parser("did"); s.add_argument("--date"); s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_did)
    s = sub.add_parser("undo"); s.add_argument("ref", help="an act id (batch#n) or a batch id"); s.add_argument("--apply", action="store_true")
    s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_undo)
    s = sub.add_parser("acts"); s.add_argument("--class", dest="cls"); s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_acts)
    a = p.parse_args()
    # A grant, a seed, a correction or an undo moves what ela may later do on its own: the owner's word, carried by the
    # runner, never an unattended session's (ELA_NO_APPLY), which could otherwise raise its own autonomy.
    if a.cmd in ("answer", "seed", "correct", "undo") and os.environ.get("ELA_NO_APPLY"):
        print(f"refused: dry {a.cmd} inside an unattended session (ELA_NO_APPLY); it is the owner's word, run by the runner",
              file=sys.stderr)
        sys.exit(2)
    a.func(a)


if __name__ == "__main__":
    main()
