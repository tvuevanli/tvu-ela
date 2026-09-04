#!/usr/bin/env python3
"""Mail — Evan's Gmail, read-only, stdlib only. L1: subcommands, --json, exit codes.

  search <query> [--limit N] [--body]   Gmail search syntax, newest first: date · from · to · subject · id · thread (--body adds the text)
  read   <message id>            one message: headers and body as text (text/plain; HTML stripped when that is all there is)
  thread <thread id>             every message in a thread, oldest first

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


def _print_row(r, body=None):
    print(f"[{r['date']}] {r['from']}")
    print(f"  to: {r['to'][:120]}" + (f"  cc: {r['cc'][:80]}" if r.get("cc") else ""))
    print(f"  subject: {r['subject']}")
    print(f"  id: {r['id']}  thread: {r['thread']}")
    if body is None:
        print(f"  {r['snippet'][:200]}")
    else:
        print(); print(body)


def cmd_search(g, a):
    r = g.get(f"{API}/messages", q=a.query, maxResults=a.limit) or {}
    ids = [m["id"] for m in r.get("messages") or []]
    rows = []                      # metadataHeaders is repeatable, so the query string is written by hand
    for i in ids:
        if a.body:
            m = g.get(f"{API}/messages/{i}", format="full") or {}
            r = _row(m); r["body"] = _body(m.get("payload")); rows.append(r)
        else:
            m = g.get(f"{API}/messages/{i}?format=metadata&metadataHeaders=Date&metadataHeaders=From&metadataHeaders=To&metadataHeaders=Cc&metadataHeaders=Subject") or {}
            rows.append(_row(m))
    if a.json:
        print(json.dumps({"query": a.query, "count": len(rows), "messages": rows}, ensure_ascii=False)); return
    if not rows:
        print(f"no messages for: {a.query}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    print(f"# {len(rows)} message(s) for: {a.query}")
    for r in rows:
        print("─" * 76); _print_row(r)


def cmd_read(g, a):
    m = g.get(f"{API}/messages/{urllib.parse.quote(a.id)}", format="full")
    if not m:
        print(f"message {a.id}: not found", file=sys.stderr); sys.exit(EX_NOTFOUND)
    r = _row(m); body = _body(m.get("payload"))
    if a.json:
        r["body"] = body; print(json.dumps(r, ensure_ascii=False)); return
    _print_row(r, body)


def cmd_thread(g, a):
    t = g.get(f"{API}/threads/{urllib.parse.quote(a.id)}", format="full")
    if not t:
        print(f"thread {a.id}: not found", file=sys.stderr); sys.exit(EX_NOTFOUND)
    msgs = t.get("messages") or []
    rows = []
    for m in msgs:
        r = _row(m); r["body"] = _body(m.get("payload")); rows.append(r)
    if a.json:
        print(json.dumps({"thread": a.id, "count": len(rows), "messages": rows}, ensure_ascii=False)); return
    print(f"# thread {a.id}  ({len(rows)} message(s))")
    for r in rows:
        print("─" * 76); _print_row(r, r["body"])


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description="Gmail, read-only.")
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("search"); p.add_argument("query"); p.add_argument("--limit", type=int, default=25); p.add_argument("--body", action="store_true", help="include each message body (one process, one token)"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("read"); p.add_argument("id"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("thread"); p.add_argument("id"); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    g = Google(a.env_file); g.need(SCOPE)
    {"search": cmd_search, "read": cmd_read, "thread": cmd_thread}[a.cmd](g, a)


if __name__ == "__main__":
    main()
