#!/usr/bin/env python3
"""Holds: a subject the owner parked, stored once and respected by every page ela writes. Stdlib only.

A module of the focus verb (`ela focus hold|resume|holds`), read by the brief, today.md, the focus board, its meeting
views and the project pages. The owner parks a subject with a line anywhere in the vault, or says it in a session:

    ela: hold <subject or key> [until <date or event>]
    ela: resume <subject or key>

A hold names its tickets by key (`MH-4061 (10-bit through the switcher)`) or only by words; a page leaves out every
item that names a held key, or whose text carries a key-less hold's subject. `until` a date (`2026-12-01`, `12-01`)
ends the hold that morning; `until` an event (`the 2.2 branch`) holds until `resume`. Each line is read once (its
path and text), so a line left in a note does not act again; lines are taken in the order they were written (the
note's modification time, then the line), so a resume after a hold ends it. Nothing is deleted: a resumed or expired
hold stays in the store with the day it ended.

Store: <reports>/ela/holds.json — {"holds": {id: {id, subject, keys, words, until, until_date, since, where, by,
ended, ended_by}}, "read": {line id: date}}.

Usage:
    hold.py --help      this text; the verbs are `ela focus hold SUBJECT [--until X] [--apply]`, `ela focus resume
                        SUBJECT [--apply]`, `ela focus holds [--json]`
"""
import datetime, hashlib, json, os, re, sys

STATE = ("ela", "holds.json")
KEY = re.compile(r"(?<![\w/#=.-])([A-Z][A-Z0-9]{1,9}-\d{1,6})(?![\w-])")
NOT_KEYS = re.compile(r"^(MPEG|AC|EAC|AES|HDR|SMPTE|ST|ITU|BT|SCTE|IEC|ISO|EBU|ATSC|DVB|IEEE|UTF|SHA|MD|RFC|CVE|HTTP|"
                      r"TLS|SSL|H|X|AV|AAC|MP|HEVC|AVC|UR|J2N|QA|AWS|CN|ENV|S|W)-")
# a word line, as the vault's `ela:` lines are written: bare, in a list, or quoted in a callout
WORD = re.compile(r"^[ \t>]*(?:[-*][ \t]+(?:\[[ xX]\][ \t]+)?)?ela:[ \t]*(hold|resume|up|down)\b[ \t]*(.*?)[ \t]*$", re.I | re.M)
UNTIL = re.compile(r"\s+until\s+(.+)$", re.I)
SKIP_DIRS = (".obsidian", ".trash", "attachments")
STOP = set("a an and are as at be by for from in is it of on or the to with".split())
# the seed: parked on the owner's word, 2026-11-20 (10-bit through the switcher is not urgent)
SEEDS = (("MH-4061 (10-bit through the switcher)", None, "2026-11-20", "seed: the owner's word, 2026-11-20 — not urgent"),)


def keys_in(text):
    return [k for k in dict.fromkeys(KEY.findall(text or "")) if not NOT_KEYS.match(k) and not k.split("-")[1].startswith("0")]


def norm_words(text):
    t = KEY.sub(" ", text or "")
    return [w for w in re.findall(r"[\w.+'-]+", t.lower()) if w not in STOP and len(w) > 1]


def parse_until(text, today):
    """(until as written, its date or None). `2026-12-01`, `12-01` (the next such day), `12/1`; anything else is an
    event, held until resumed."""
    t = (text or "").strip().rstrip(".")
    if not t:
        return None, None
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return t, datetime.date(*map(int, m.groups()))
    m = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})", t)
    if m:
        try:
            d = datetime.date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return t, None
        if d < today:
            d = d.replace(year=today.year + 1)
        return t, d
    return t, None


def split_subject(rest):
    """`<subject> [until X]` → (subject, until text or None)."""
    m = UNTIL.search(rest or "")
    if m:
        return rest[:m.start()].strip(), m.group(1).strip()
    return (rest or "").strip(), None


def hold_id(subject):
    ks = keys_in(subject)
    return ks[0] if ks else "w:" + " ".join(norm_words(subject))[:60]


def load(reports):
    try:
        st = json.load(open(os.path.join(reports or "", *STATE), encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    st.setdefault("holds", {})
    st.setdefault("read", {})
    return st


def save(reports, st):
    p = os.path.join(reports, *STATE)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(st, ensure_ascii=False, indent=1) + "\n")
    os.replace(tmp, p)


def put_hold(st, subject, until, today, where, by="owner"):
    """A hold on `subject`. Holding what is already held moves its `until`; a hold ended earlier starts again."""
    if not subject:
        return None
    hid = hold_id(subject)
    if not hid or hid == "w:":
        return None
    until_text, until_date = parse_until(until, today)
    h = st["holds"].get(hid)
    if h and not h.get("ended"):
        h.update(until=until_text, until_date=until_date.isoformat() if until_date else None)
        if len(subject) > len(h.get("subject") or ""):
            h["subject"] = subject
        return h
    h = {"id": hid, "subject": subject, "keys": keys_in(subject), "words": norm_words(subject), "until": until_text,
         "until_date": until_date.isoformat() if until_date else None, "since": today.isoformat(), "where": where, "by": by,
         "ended": None, "ended_by": None}
    if hid in st["holds"]:                                   # an ended hold is kept: the new one is the same id's next life
        st["holds"][hid].setdefault("history", [])
        h["history"] = st["holds"][hid]["history"] + [{k: st["holds"][hid].get(k) for k in ("since", "ended", "ended_by")}]
    st["holds"][hid] = h
    return h


def find(st, subject, live_only=True):
    """The hold `subject` names: by a key it carries, else by its words (all of the hold's words, or all of its own)."""
    ks, ws = set(keys_in(subject)), set(norm_words(subject))
    for h in st["holds"].values():
        if live_only and h.get("ended"):
            continue
        if ks & set(h.get("keys") or []):
            return h
        hw = set(h.get("words") or [])
        if not ks and ws and hw and (hw <= ws or ws <= hw):
            return h
    return None


def resume(st, subject, today, where, by="owner"):
    h = find(st, subject)
    if h:
        h.update(ended=today.isoformat(), ended_by=f"resume · {where}" if by == "owner" else by)
    return h


def expire(st, today):
    """A hold whose date has come ends that morning. → the holds ended."""
    out = []
    for h in st["holds"].values():
        if not h.get("ended") and h.get("until_date") and h["until_date"] <= today.isoformat():
            h.update(ended=today.isoformat(), ended_by=f"until {h['until']}")
            out.append(h)
    return out


def seed(st, today):
    for subject, until, since, why in SEEDS:
        sid = hold_id(subject)
        if sid in st["holds"]:
            continue
        h = put_hold(st, subject, until, datetime.date.fromisoformat(since), why)
        if h:
            h["since"] = since


def line_id(rel, text):
    """The id lines were read under before the vault watcher (2026-11-20); still honoured, so nothing acts twice."""
    return hashlib.sha1(f"{rel}|{' '.join(text.split())}".encode()).hexdigest()[:12]


# the vault watcher stamps each line it handled: `✓ 11:42`, `✗ 11:42`, or `queued`
STAMP = re.compile(r"\s*(?:[\u2713\u2717]\s*\d{1,2}:\d{2}|\bqueued\b).*$")


def unstamped(rest):
    return " ".join(STAMP.sub("", rest or "").split())


def word_key(rel, verb, rest):
    """One line's key, shared with the vault watcher (`--where <rel>#…`): the note, the verb and the rest of the line,
    spaces collapsed, any stamp stripped. Whoever reads a line first, the other finds it read."""
    return "w-" + hashlib.sha1(f"{rel.split('#', 1)[0]}|{verb.lower()}|{unstamped(rest)}".encode()).hexdigest()[:12]


def vault_words(vault, verbs=("hold", "resume", "up", "down")):
    """Every unstamped `ela: hold|resume|up|down` line in the vault, in the order written: [(mtime, rel, line no, verb,
    rest, key, old id)].
    The archive is read too: a note moved there keeps the word it carried."""
    out = []
    for top, dirs, files in os.walk(vault or ""):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS]
        for f in files:
            if not f.endswith(".md"):
                continue
            p = os.path.join(top, f)
            try:
                text = open(p, encoding="utf-8").read()
            except OSError:
                continue
            if "ela:" not in text:
                continue
            rel = os.path.relpath(p, vault).replace(os.sep, "/")
            mt = os.path.getmtime(p)
            for m in WORD.finditer(text):
                verb = m.group(1).lower()
                if verb in verbs and m.group(2).strip() and not STAMP.search(m.group(2)):   # stamped: the watcher's
                    out.append((mt, rel, text.count("\n", 0, m.start()), verb, m.group(2).strip(),
                                word_key(rel, verb, m.group(2)), line_id(rel, m.group(0))))
    return sorted(out)


def read_vault(st, vault, today):
    """His hold and resume lines not read before, applied in the order written. → [(verb, subject, hold or None, rel)]."""
    did = []
    for _, rel, _, verb, rest, lid, old in vault_words(vault, ("hold", "resume")):
        if lid in st["read"] or old in st["read"]:
            continue
        st["read"][lid] = today.isoformat()
        subject, until = split_subject(rest)
        h = put_hold(st, subject, until, today, rel) if verb == "hold" else resume(st, subject, today, rel)
        did.append((verb, subject, h, rel))
    return did


def refresh(reports, vault, today, write=True):
    """The store brought up to date: the seed, his lines in the vault, the dates that came. → (state, did)."""
    st = load(reports)
    seed(st, today)
    did = read_vault(st, vault, today) if vault and os.path.isdir(vault) else []
    did += [("expired", h["subject"], h, None) for h in expire(st, today)]
    if write and reports:
        save(reports, st)
    return st, did


def active(st, today=None):
    today = today or datetime.date.today()
    return [h for h in st.get("holds", {}).values()
            if not h.get("ended") and not (h.get("until_date") and h["until_date"] <= today.isoformat())]


def held_keys(st, today=None):
    return {k for h in active(st, today) for k in h.get("keys") or []}


def holding(st, keys=(), text="", today=None):
    """The active hold an item falls under: one of its keys is held, or a key-less hold's words are all in its text."""
    ks = set(keys) | set(keys_in(text))
    ws = set(norm_words(text))
    for h in active(st, today):
        if ks & set(h.get("keys") or []):
            return h
        if not h.get("keys") and h.get("words") and set(h["words"]) <= ws:
            return h
    return None


def label(h):
    return f"{h['subject']}, since {h['since'][5:]}" + (f", until {h['until']}" if h.get("until") else ", until resumed")


def for_reports(reports=None, today=None):
    """The store as read by a generator that does not write it (the brief, today.md, project pages): the seed applied in
    memory, nothing written. An unreadable store holds nothing."""
    try:
        st = load(reports)
        seed(st, today or datetime.date.today())
        return st
    except Exception:                                        # noqa: BLE001 — a broken store hides nothing
        return {"holds": {}, "read": {}}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    print(__doc__, file=sys.stderr)
    sys.exit(2)
