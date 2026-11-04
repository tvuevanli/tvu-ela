#!/usr/bin/env python3
"""Mail — Evan's Gmail, read-only, stdlib only. L1: subcommands, --json, exit codes.

  search <query> [--limit N] [--body]   Gmail search syntax, newest first: date · from · to · subject · id · thread (--body adds the text)
  read   <message id>            one message: headers and body as text (text/plain; HTML stripped when that is all there is)
  thread <thread id>             every message in a thread, oldest first

The fact store (<runtime>/facts/mail/, filled by `ela facts refresh`) holds the three standing searches over a rolling
21 days — `subject:Release`, `subject:("test report")`, `in:sent` — and every message ever fetched, by id. A `search`
whose clauses fall inside one standing search is answered from the store without a call while the store is fresh; any
other query lists ids live and fetches only the ids not yet stored. `read` serves a stored message (a message never
changes); `thread` serves the store while fresh. --fresh reads Gmail now.

Credentials: the same read-only Google OAuth token the gdoc capability uses (GOOGLE_TOKEN_FILE in the env
file); the token must carry gmail.readonly and nothing outside the read-only allowlist. Nothing here sends,
labels, archives or deletes — the API surface is messages.list / messages.get / threads.get.
Exit codes: 0 ok · 2 usage · 3 not found · 4 auth · 5 remote error.
"""
import argparse, base64, html, json, os, re, signal, sys, urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "gdoc"))
from gdoc import Google, EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE  # noqa: E402  (one auth implementation for every Google read)

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "facts"))
try:
    import facts as F  # noqa: E402 — the fact store: the standing searches and the message store
except ImportError:
    F = None
import datetime  # noqa: E402
STANDING = {"release": "subject:Release", "test-report": 'subject:("test report")', "sent": "in:sent"}
STANDING_CAP = 400


def _get(g, url, **params):
    if F:
        F.trace("mail", url.replace(API, "").split("?")[0])
    return g.get(url, **params)


def _headers(msg):
    return {h["name"].lower(): h["value"] for h in ((msg.get("payload") or {}).get("headers") or [])}


def _b64(data):
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def _html_to_text(s):
    s = re.sub(r"(?is)<(script|style).*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>|</h\d>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(re.sub(r"\n{3,}", "\n\n", s)).strip()


def _body(payload):
    plain, rich = [], []
    def walk(p):
        mt = (p.get("mimeType") or "").lower()
        data = (p.get("body") or {}).get("data")
        if data and mt.startswith("text/plain"):
            plain.append(_b64(data))
        elif data and mt.startswith("text/html"):
            rich.append(_b64(data))
        for c in p.get("parts") or []:
            walk(c)
    walk(payload or {})
    if plain:
        return re.sub(r"\n{3,}", "\n\n", "\n".join(plain)).strip()
    if rich:
        return _html_to_text("\n".join(rich))
    return ""


def _row(msg):
    h = _headers(msg)
    return {"id": msg.get("id"), "thread": msg.get("threadId"), "date": h.get("date", ""), "from": h.get("from", ""),
            "to": h.get("to", ""), "cc": h.get("cc", ""), "subject": h.get("subject", ""), "snippet": html.unescape(msg.get("snippet") or "")}


# ── the store: every message once, by id; the standing searches as id lists ──────────────────────────

def _msg_path(mid):
    return os.path.join(F.store_dir("mail", "messages"), f"{mid}.json")


def stored_message(mid):
    return F.read_json(_msg_path(mid)) if F else None


def fetch_message(g, mid, fresh=False):
    """The full message (row + body + internal_date + read_at), from the store when it is there — a message never
    changes — else one messages.get, written through. None when Gmail has no such id."""
    if not fresh and not (F and F.forced_fresh()):
        doc = stored_message(mid)
        if doc:
            return doc
    m = _get(g, f"{API}/messages/{urllib.parse.quote(mid)}", format="full")
    if not m:
        return None
    r = _row(m); r["body"] = _body(m.get("payload"))
    r["internal_date"] = int(m.get("internalDate") or 0) // 1000
    r["read_at"] = F.now_iso() if F else datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    if F:
        F.write_json(_msg_path(mid), r)
    return r


def list_ids(g, query, limit):
    """messages.list ids, newest first, paged to `limit`."""
    ids, token = [], None
    while len(ids) < limit:
        r = _get(g, f"{API}/messages", q=query, maxResults=min(100, limit - len(ids)), **({"pageToken": token} if token else {})) or {}
        ids += [m["id"] for m in r.get("messages") or []]
        token = r.get("nextPageToken")
        if not token or not r.get("messages"):
            break
    return ids


def refresh_standing(g, full=False):
    """The three standing searches over the rolling window: list their ids, fetch the ones not stored, keep the index.
    {name: {count, fetched}}. Messages no standing search names any more are dropped after 30 days."""
    idx = {} if full else (F.read_json(os.path.join(F.store_dir("mail"), "index.json"), {}) or {})
    stats = {}
    for name, q in STANDING.items():
        ids = list_ids(g, f"newer_than:{F.MAIL_DAYS}d {q}", STANDING_CAP)
        fetched = 0
        for mid in ids:
            if full or not os.path.exists(_msg_path(mid)):
                if fetch_message(g, mid, fresh=full):
                    fetched += 1
        idx[name] = {"query": q, "ids": ids, "at": F.now_iso(), "days": F.MAIL_DAYS}
        stats[name] = {"count": len(ids), "fetched": fetched}
    F.write_json(os.path.join(F.store_dir("mail"), "index.json"), idx)
    named = {mid for rec in idx.values() for mid in rec.get("ids") or []}
    cutoff = (F.now() - datetime.timedelta(days=30)).timestamp()
    d = F.store_dir("mail", "messages")
    for f in os.listdir(d):
        if f.endswith(".json") and f[:-5] not in named and os.path.getmtime(os.path.join(d, f)) < cutoff:
            os.remove(os.path.join(d, f))
    return stats


# ── which queries the store can answer ───────────────────────────────────────────────────────────────

TOKEN_RX = re.compile(r'(?:(\w+):)?("[^"]*"|\([^)]*\)|\S+)')


def _date_bound(v):
    """after:/before: value → epoch seconds: an epoch, YYYY/MM/DD or YYYY-MM-DD at local midnight."""
    if re.fullmatch(r"\d{9,}", v):
        return int(v)
    m = re.fullmatch(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", v)
    if m:
        return datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).astimezone().timestamp()
    raise ValueError(v)


def _span(v):
    m = re.fullmatch(r"(\d+)([dmy])", v)
    if not m:
        raise ValueError(v)
    return int(m.group(1)) * {"d": 1, "m": 30, "y": 365}[m.group(2)] * 86400


def _subject_terms(v):
    """subject:X → the terms, each a regex: a quoted phrase in sequence, a word by its start."""
    v = v.strip()
    if v.startswith("(") and v.endswith(")"):
        v = v[1:-1]
    out = []
    for m in re.finditer(r'"([^"]*)"|(\S+)', v):
        if m.group(1) is not None:
            words = m.group(1).split()
            out.append(re.compile(r"\b" + r"\W+".join(re.escape(w) for w in words), re.I) if words else re.compile(""))
        else:
            out.append(re.compile(r"\b" + re.escape(m.group(2)), re.I))
    return out


def servable(query):
    """(standing set name, predicate over a stored row) when every clause of the query is a date bound, a subject
    clause inside a standing search, or in:sent; None when any clause needs Gmail (from:, OR, bare words)."""
    preds, sets, subjects = [], set(), []
    now_s = datetime.datetime.now().timestamp()
    try:
        for m in TOKEN_RX.finditer(query):
            op, v = (m.group(1) or "").lower(), m.group(2)
            if op == "after":
                b = _date_bound(v); preds.append(lambda r, b=b: r.get("internal_date", 0) >= b)
            elif op == "before":
                b = _date_bound(v); preds.append(lambda r, b=b: r.get("internal_date", 0) < b)
            elif op == "newer_than":
                b = now_s - _span(v); preds.append(lambda r, b=b: r.get("internal_date", 0) >= b)
            elif op == "older_than":
                b = now_s - _span(v); preds.append(lambda r, b=b: r.get("internal_date", 0) < b)
            elif op == "in" and v.lower() == "sent":
                sets.add("sent")
            elif op == "subject":
                terms = _subject_terms(v)
                subjects += terms
                low = v.lower()
                if re.search(r"\btest\b", low) and re.search(r"\breport\b", low):
                    sets.add("test-report")
                elif re.search(r"\brelease\b", low):
                    sets.add("release")
                else:
                    return None
            else:
                return None
    except ValueError:
        return None
    if len(sets) != 1 and sets != {"test-report", "release"}:
        return None
    name = "test-report" if "test-report" in sets else sets.pop()
    return name, (lambda r: all(p(r) for p in preds) and all(t.search(r.get("subject") or "") for t in subjects))


def stored_search(query, limit):
    """(rows newest first, read time) from the store for a servable query while its index is fresh; else None."""
    if not F or F.forced_fresh():
        return None
    hit = servable(query)
    if not hit:
        return None
    name, pred = hit
    idx = (F.read_json(os.path.join(F.store_dir("mail"), "index.json"), {}) or {}).get(name)
    if not idx or not F.fresh(idx.get("at")):
        return None
    rows = [r for r in (stored_message(mid) for mid in idx.get("ids") or []) if r and pred(r)]
    rows.sort(key=lambda r: r.get("internal_date", 0), reverse=True)
    return rows[:limit], idx["at"]


def _print_row(r, body=None):
    print(f"[{r['date']}] {r['from']}")
    print(f"  to: {r['to'][:120]}" + (f"  cc: {r['cc'][:80]}" if r.get("cc") else ""))
    print(f"  subject: {r['subject']}")
    print(f"  id: {r['id']}  thread: {r['thread']}")
    if body is None:
        print(f"  {r['snippet'][:200]}")
    else:
        print(); print(body)


ROW_KEYS = ("id", "thread", "date", "from", "to", "cc", "subject", "snippet")


def cmd_search(g, a):
    stored = None if a.fresh else stored_search(a.query, a.limit)
    if stored is not None:
        full, read_at = stored
        F.served("mail", read_at, "search")
    else:
        read_at = F.now_iso() if F else datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        full = [m for m in (fetch_message(g, i, fresh=a.fresh) for i in list_ids(g, a.query, a.limit)) if m]
    rows = [{**{k: m.get(k, "") for k in ROW_KEYS}, **({"body": m.get("body", "")} if a.body else {}), "read_at": m.get("read_at")} for m in full]
    if a.json:
        print(json.dumps({"query": a.query, "count": len(rows), "messages": rows, "read_at": read_at}, ensure_ascii=False)); return
    if not rows:
        print(f"no messages for: {a.query}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    print(f"# {len(rows)} message(s) for: {a.query}")
    for r in rows:
        print("─" * 76); _print_row(r)


def cmd_read(g, a):
    m = fetch_message(g, a.id, fresh=a.fresh)
    if not m:
        print(f"message {a.id}: not found", file=sys.stderr); sys.exit(EX_NOTFOUND)
    r = {k: m.get(k, "") for k in ROW_KEYS}; body = m.get("body", "")
    if a.json:
        r["body"] = body; r["read_at"] = m.get("read_at"); print(json.dumps(r, ensure_ascii=False)); return
    _print_row(r, body)


def cmd_thread(g, a):
    path = os.path.join(F.store_dir("mail", "threads"), f"{a.id}.json") if F else None
    doc = F.read_json(path) if path else None
    if doc and not a.fresh and not F.forced_fresh() and F.fresh(doc.get("at")):
        F.served("mail", doc["at"], f"thread {a.id}")
        rows, read_at = doc["messages"], doc["at"]
    else:
        t = _get(g, f"{API}/threads/{urllib.parse.quote(a.id)}", format="full")
        if not t:
            print(f"thread {a.id}: not found", file=sys.stderr); sys.exit(EX_NOTFOUND)
        rows, read_at = [], (F.now_iso() if F else datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
        for m in t.get("messages") or []:
            r = _row(m); r["body"] = _body(m.get("payload")); r["internal_date"] = int(m.get("internalDate") or 0) // 1000; r["read_at"] = read_at
            rows.append(r)
            if F:
                F.write_json(_msg_path(r["id"]), r)
        if path:
            F.write_json(path, {"thread": a.id, "at": read_at, "messages": rows})
    rows = [{k: m.get(k, "") for k in ROW_KEYS + ("body",)} for m in rows]
    if a.json:
        print(json.dumps({"thread": a.id, "count": len(rows), "messages": rows, "read_at": read_at}, ensure_ascii=False)); return
    print(f"# thread {a.id}  ({len(rows)} message(s))")
    for r in rows:
        print("─" * 76); _print_row(r, r["body"])


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description="Gmail, read-only.")
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("search"); p.add_argument("query"); p.add_argument("--limit", type=int, default=25); p.add_argument("--body", action="store_true", help="include each message body (one process, one token)"); p.add_argument("--fresh", action="store_true", help="read Gmail now instead of the store"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("read"); p.add_argument("id"); p.add_argument("--fresh", action="store_true"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("thread"); p.add_argument("id"); p.add_argument("--fresh", action="store_true"); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    g = Google(a.env_file); g.need(SCOPE)
    {"search": cmd_search, "read": cmd_read, "thread": cmd_thread}[a.cmd](g, a)


if __name__ == "__main__":
    main()
