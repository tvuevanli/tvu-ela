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
  draft   <class> <KEY> [--issue-file F] [--child-file F …] [--json]
                                         read the parent (or the given files), select the targets by the class's rule,
                                         store one batch; nothing is written anywhere else
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
import argparse, datetime, glob, hashlib, json, os, re, subprocess, sys
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "setup"))
import siteguard  # noqa: E402  a file in the site directory is never read for a caller

HERE = os.path.dirname(os.path.abspath(__file__))
JIRA = os.path.join(HERE, "..", "jira", "jira.py")
SITE = os.path.expanduser("~/.claude/ela/site.json")
TZ = datetime.timezone(datetime.timedelta(hours=8))
KEY = r"[A-Z][A-Z0-9]+-\d+"
KEY_RX = re.compile(r"\b" + KEY + r"\b")
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
        "atom": ("jira", "link"), "noun": ("link", "links"), "ladder": (3, 1), "base": 3,
        "rule": "a ticket named in the parent's description or comments, not linked to it yet, and not a subtask of a "
                "ticket linked or proposed; `contains`, or `relates to` when the naming line says related",
        "command": r"^ela jira link " + KEY + r" " + KEY + r" --type (?:contains|\"?relates to\"?)\s*$",
        "case": "MH-3735, 2026-11-12: links approved as a kind in one sentence",
        "reverse": (("unlink", "--id"),),
    },
    "parent-status": {
        "says": "a status comment on a parent you own, from its children's states",
        "atom": ("jira", "comment"), "noun": ("status comment", "status comments"), "ladder": (3, 1), "base": 3,
        "rule": "the parent's contained children, one line each with its status, when a status differs from his last "
                "status comment on the parent",
        "command": r"^ela jira comment " + KEY + r" --from-file \S+\s*$",
        "case": "MH-3735, 2026-11-12: 'update the parent' after the links",
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
}
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

VERDICTS = ("applied", "edited", "cancelled", "expired", "corrected", "reverted")


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


def batch_ask(b):
    d = CLASSES[b["class"]]
    n = len(b["writes"])
    noun = d["noun"][0] if n == 1 else d["noun"][1]
    aid = f"dry:{b['id']}"
    return {"id": aid, "kind": "batch", "class": b["class"], "batch": b["id"],
            "question": f"{n} {noun} ready for {b['scope']}: {d['says']}.",
            "link": note_rel(b["id"]),
            "options": [option("A", f"apply all {n}" + (" (strike a line in the note to leave it out)" if n > 1 else ""),
                               f"ela dry answer {aid} A --apply", True),
                        option("B", "drop them", f"ela dry answer {aid} B")],
            "sig": hashlib.sha256(json.dumps(b["writes"], sort_keys=True).encode()).hexdigest()[:12]}


def asks(reports, today=None, commit=False, ask_state=None):
    """The asks for today.md, batches first (work waiting), then grant asks. With commit, an expired or dropped ask is
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
    out = [batch_ask(b) for b in batches(reports) if b.get("state") == "open"]
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
    """An ask the vault dropped after three mornings with no answer: a batch is recorded expired unanswered, once per
    write; a grant ask is marked expired, which lets it return after ten more clean runs."""
    for b in batches(reports):
        s = ask_state.get(f"dry:{b['id']}") or {}
        if b.get("state") == "open" and s.get("dropped"):
            b["state"] = "expired"
            if commit:
                for w in b["writes"]:
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


def review_note(b):
    """The note that shows each exact write of a batch: one numbered line per write, the command in backticks and why.
    Striking a line (~~ … ~~) or deleting it leaves the write out; editing the command applies it as edited and records
    an edit. The ask on today.md carries the letters."""
    d = CLASSES[b["class"]]
    L = [f"# {len(b['writes'])} {d['noun'][1] if len(b['writes']) != 1 else d['noun'][0]} for {b['scope']}", "",
         f"Class: **{b['class']}** — {d['says']}. Rule: {d['rule']}.", "",
         "Each line is the exact write. Strike a line (`~~ ~~`) or delete it to leave it out; edit the command to change "
         "it. Then answer the ask on today.md: A applies what is here, B drops the batch.", ""]
    for w in b["writes"]:
        L.append(f"{w['n']}. `{w['command']}` — {w['why']}")
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
            t += (node.get("attrs") or {}).get("url") or ""
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


def select_link_named(parent, children, before=None):
    """The links a parent's own text names but Jira lacks: [(write)], [left out with why]. `children` {key: issue} for
    the named tickets (a key that could not be read is left out, named). `before` an ISO time: comments after it are not
    read (a replay of a past morning)."""
    pk = parent["key"]
    f = parent.get("fields") or {}
    texts = [("description", None, adf_text(f.get("description")))]
    for c in (f.get("comment") or {}).get("comments") or []:
        if before and str(c.get("created") or "") and parse_ts(c["created"]) > parse_ts(before):
            continue
        texts.append(((c.get("author") or {}).get("displayName") or "?", c.get("created"), adf_text(c.get("body"))))
    linked = {l["key"] for l in links_of(parent)}
    named, order = {}, []
    for who, at, text in texts:
        for line in (text or "").split("\n"):
            for k in KEY_RX.findall(line):
                if k == pk or k in named:
                    continue
                rel = bool(re.search(r"\brelate[sd]?\b|相关", line, re.I))
                named[k] = {"who": who, "at": (at or "")[:10], "relates": rel}
                order.append(k)
    proposed, left = [], []
    for k in order:
        if k in linked:
            continue
        ch = children.get(k)
        if ch is None:
            left.append(f"{k} — named by {named[k]['who']}, could not be read"); continue
        par = (((ch.get("fields") or {}).get("parent") or {}).get("key"))
        if par and (par in linked or par in order):
            left.append(f"{k} — a subtask of {par}, which carries it"); continue
        proposed.append(k)
    writes = []
    for i, k in enumerate(proposed, 1):
        ch = children[k].get("fields") or {}
        t = "relates to" if named[k]["relates"] else "contains"
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
             "why": "moved since your last status comment: " + ", ".join(f"{k} → {now[k]}" for k in moved)}], []


def parse_ts(s):
    try:
        t = datetime.datetime.fromisoformat(re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", str(s).replace("Z", "+00:00")))
        return t if t.tzinfo else t.replace(tzinfo=TZ)
    except ValueError:
        return datetime.datetime.min.replace(tzinfo=TZ)


def make_batch(reports, cls, scope, writes, left, today):
    if not writes:
        return None
    bid = f"{today.isoformat()}-{cls}-{scope}"
    old = load_batch(reports, bid)
    if old and old.get("state") != "open":
        return old                                         # answered today already: the same batch is not asked twice
    b = {"id": bid, "class": cls, "scope": scope, "made": now_iso(), "state": "open", "writes": writes, "left_out": left}
    save_batch(reports, b)
    return b


# ── the answer ────────────────────────────────────────────────────────────────────────────────────────────────
def run_write(command, apply, action=None, word=None, cls=None):
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
               **({"ELA_CLASS": cls} if cls else {}))
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
    return p.returncode, (p.stdout + p.stderr).strip()


def answer(reports, aid, letter, note_text=None, apply=False, runner=run_write, now=None):
    """His letter on one ask. → {ask, letter, did: [...]}; raises KeyError for an unknown ask, ValueError for a letter
    the ask does not offer."""
    letter = letter.upper()
    st = load_state(reports)
    if aid.startswith("dry:"):
        b = load_batch(reports, aid[4:])
        if not b:
            raise KeyError(aid)
        if letter not in "AB":
            raise ValueError(f"{aid} offers A or B, not {letter}")
        if b.get("state") != "open":
            return {"ask": aid, "letter": letter, "did": [f"already {b['state']}"]}
        did = []
        if letter == "B":
            for w in b["writes"]:
                append(reports, {"at": now_iso(now), "class": b["class"], "verdict": "cancelled", "letter": "B", "target": w["target"],
                                 "command": w["command"], "batch": b["id"], "source": "batch"})
            b["state"] = "dropped"
            did.append(f"dropped {len(b['writes'])}")
        else:
            plan = read_note(b, note_text) if note_text is not None else [(w, "applied", w["command"]) for w in b["writes"]]
            for w, verdict, cmd in plan:
                if verdict == "cancelled":
                    if apply:
                        append(reports, {"at": now_iso(now), "class": b["class"], "verdict": "cancelled", "letter": "A", "target": w["target"],
                                         "command": w["command"], "batch": b["id"], "source": "batch", "how": "struck"})
                    did.append(f"{w['n']} left out"); continue
                code, out = (run_write(cmd, apply, action=act_id(b["id"], w["n"]), word=f"answer {aid} {letter}", cls=b["class"])
                             if runner is run_write else runner(cmd, apply))
                did.append(f"{w['n']} {'applied' if apply else 'dry run'}{' as edited' if verdict == 'edited' else ''}: "
                           f"{'ok' if code == 0 else 'failed'} — {out.splitlines()[-1] if out else ''}"[:200])
                if apply and code == 0:
                    append(reports, {"at": now_iso(now), "class": b["class"], "verdict": verdict, "letter": "A", "target": w["target"],
                                     "command": cmd, "drafted": w["command"], "as_drafted": verdict == "applied",
                                     "batch": b["id"], "act": act_id(b["id"], w["n"]), "source": "batch"})
            if apply:
                b["state"] = "applied"
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


def correct(reports, cls, how, ref=None, note=None, now=None):
    """A correction after the fact (a revert, a reply against it, his `ela:` line). A class above its base tier returns
    to confirm (tier 3) and the fall is noted for today.md. → the notice, or None when the class was at confirm."""
    if cls not in CLASSES:
        raise KeyError(cls)
    st = load_state(reports)
    x = st[cls]
    append(reports, {"at": now_iso(now), "class": cls, "verdict": "reverted" if how == "revert" else "corrected", "how": how,
                     "target": ref, "note": note, "source": "correction"})
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
                correct(reports, r["rule"], r.get("how") or "correction", r.get("key"), (r.get("now") or "")[:120],
                        now=datetime.datetime.fromisoformat(day + "T21:00:00+08:00"))


def did(reports, day):
    """What granted classes did without confirm on a day, from the runner's actions files: tier-1 actions under a class
    rule, applied. → (Facts line or None, [(n, text, undo)])."""
    try:
        acts = json.load(open(os.path.join(reports, "runner", f"{day}-actions.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None, []
    acts = acts.get("actions") if isinstance(acts, dict) else acts
    rows = [a for a in acts or [] if a.get("rule") in CLASSES and a.get("tier") in (1, 2) and a.get("applied")]
    if not rows:
        return None, []
    counts = {}
    for a in rows:
        counts[a["rule"]] = counts.get(a["rule"], 0) + 1
    words = ", ".join(f"{n} {CLASSES[c]['noun'][0] if n == 1 else CLASSES[c]['noun'][1]}" for c, n in counts.items())
    return f"ela did: {words}", [(a["n"], a.get("text") or a.get("command"), f"ela: undo {a['n']}") for a in rows]


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
    if a.cls == "link-named":
        children = {}
        for p in a.child_file or []:
            c = json.load(open(p, encoding="utf-8"))
            children[c["key"]] = c
        if not a.issue_file:
            for k in sorted(set(KEY_RX.findall(json.dumps((parent.get("fields") or {}).get("comment"))))
                            | set(KEY_RX.findall(json.dumps((parent.get("fields") or {}).get("description"))))):
                if k != parent["key"] and k not in children:
                    c = read_issue(k, env)
                    if c:
                        children[k] = c
        writes, left = select_link_named(parent, children, before=a.before)
    else:
        runtime = site().get("runtime") or os.path.join(r, "..", ".ela")
        writes, left = select_parent_status(parent, owner, today, os.path.join(a.out_dir or os.path.join(runtime, "dry"), today.isoformat()))
    b = make_batch(r, a.cls, parent["key"], writes, left, today)
    emit(a, {"batch": b, "left_out": left},
         [f"batch {b['id']}: {len(b['writes'])} write(s), state {b['state']}"] + [f"  {w['n']}. {w['command']} — {w['why']}" for w in b["writes"]]
         + [f"  left out: {x}" for x in left] if b else [f"{a.key}: nothing to draft"] + [f"  left out: {x}" for x in left])


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
    a.func(a)


if __name__ == "__main__":
    main()
