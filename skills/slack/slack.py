#!/usr/bin/env python3
"""Slack capability. L1: subcommands, --json, meaningful exit codes, stdlib only. Reads are first-hand;
the one write, `post`, is a dry run until --apply.

  read       <permalink>                 one message and its thread
  channels                               channels the bot can see
  history    <channel> --since 48h       top-level messages in a window (--threads adds replies)
  mentions   --since 48h [--user me] [--channels a,b]   messages that mention a user, with whether they answered
  unanswered --since 7d  [--user me] [--channels a,b]   threads a user started that nobody else replied to
  whoami     [--email x]                 the user id behind an email (default: JIRA_EMAIL in the env file)
  post       <#channel|Cxxx|thread permalink> --text "…" | --file f.md [--dm me|email|Uxxx] [--apply]
             send a message as the bot (a permalink → reply in that thread). Dry run by default; refuses a
             duplicate of a message the bot already posted there; a DM needs --dm said explicitly.

Exit codes: 0 ok · 2 usage · 4 auth or refused · 5 remote error.
Credential resolution: $SLACK_BOT_TOKEN → --env-file → $SLACK_ENV_FILE → $ELA_ENV_FILE. The script never stores it.
"""
import argparse, json, os, re, signal, sys, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

API = "https://slack.com/api/"
EX_USAGE, EX_AUTH, EX_REMOTE = 2, 4, 5


def env_value(key, env_file=None):
    v = os.environ.get(key)
    if v:
        return v
    for path in filter(None, [env_file, os.environ.get("SLACK_ENV_FILE"), os.environ.get("ELA_ENV_FILE")]):
        try:
            for line in open(path):
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return None


def token(env_file=None):
    t = env_value("SLACK_BOT_TOKEN", env_file)
    if not t:
        sys.exit(EX_AUTH if print("no SLACK_BOT_TOKEN (env, $SLACK_ENV_FILE, or --env-file)", file=sys.stderr) is None else EX_AUTH)
    return t


def call(method, tok, **params):
    """One Slack call with retries on 429 and transient network faults. Raises SystemExit(5) on failure."""
    url = API + method + "?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(6):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(int(e.headers.get("Retry-After", "5"))); continue
            last = f"http {e.code}"; time.sleep(2 * (attempt + 1)); continue
        except Exception as e:  # truncated reads, resets
            last = repr(e); time.sleep(2 * (attempt + 1)); continue
        if d.get("ok"):
            return d
        if d.get("error") == "ratelimited":
            time.sleep(5); continue
        if d.get("error") in ("invalid_auth", "not_authed", "token_revoked", "account_inactive"):
            print(f"slack {method}: {d.get('error')}", file=sys.stderr); sys.exit(EX_AUTH)
        print(f"slack {method} failed: {d.get('error')}", file=sys.stderr); sys.exit(EX_REMOTE)
    print(f"slack {method}: gave up after retries ({last})", file=sys.stderr); sys.exit(EX_REMOTE)


def paged(method, tok, key, **params):
    out, cursor = [], None
    while True:
        d = call(method, tok, **params, **({"cursor": cursor} if cursor else {}))
        out += d.get(key, [])
        cursor = (d.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return out


class Names:
    def __init__(self, tok):
        self.tok, self.cache = tok, {}

    def user(self, uid):
        if not uid:
            return "?"
        if uid not in self.cache:
            try:
                u = call("users.info", self.tok, user=uid)["user"]
                self.cache[uid] = (u.get("profile", {}).get("real_name") or u.get("real_name")
                                   or u.get("name") or uid)
            except SystemExit:
                self.cache[uid] = uid
        return self.cache[uid]

    def render(self, text):
        return re.sub(r"<@([A-Z0-9]+)>", lambda m: "@" + self.user(m.group(1)), text or "")


def parse_permalink(link):
    m = re.search(r"/archives/([A-Z0-9]+)/p(\d{10})(\d{6})", link)
    if not m:
        print("not a Slack permalink", file=sys.stderr); sys.exit(EX_USAGE)
    return m.group(1), f"{m.group(2)}.{m.group(3)}"


def since_ts(spec):
    """'48h' | '7d' | 'YYYY-MM-DD' → epoch seconds as a string."""
    m = re.fullmatch(r"(\d+)([hd])", spec or "")
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = timedelta(hours=n) if unit == "h" else timedelta(days=n)
        return f"{(datetime.now(timezone.utc) - delta).timestamp():.6f}"
    try:
        return f"{datetime.strptime(spec, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp():.6f}"
    except (TypeError, ValueError):
        print("--since takes 48h, 7d, or YYYY-MM-DD", file=sys.stderr); sys.exit(EX_USAGE)


def list_channels(tok):
    chans = paged("users.conversations", tok, "channels", types="public_channel,private_channel", limit=200)
    return [{"id": c["id"], "name": c.get("name"), "members": c.get("num_members")} for c in chans]


def resolve_channel(tok, ref):
    if re.fullmatch(r"[CG][A-Z0-9]{8,}", ref):
        return ref
    for c in list_channels(tok):
        if c["name"] == ref.lstrip("#"):
            return c["id"]
    print(f"channel not found or bot not a member: {ref}", file=sys.stderr); sys.exit(EX_USAGE)


def whoami(tok, env_file, email=None):
    email = email or env_value("JIRA_EMAIL", env_file)
    if not email:
        print("no email: pass --email or put JIRA_EMAIL in the env file", file=sys.stderr); sys.exit(EX_USAGE)
    d = call("users.lookupByEmail", tok, email=email)
    return d["user"]["id"]


def iso(ts):
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def permalink_of(channel, ts):
    return f"https://tvunetworks.slack.com/archives/{channel}/p{ts.replace('.', '')}"


# ── subcommands ──────────────────────────────────────────────────────────────

def cmd_read(tok, a):
    ch, ts = parse_permalink(a.permalink)
    names = Names(tok)
    try:
        chan = call("conversations.info", tok, channel=ch)["channel"].get("name", ch)
    except SystemExit:
        chan = ch
    msgs = call("conversations.replies", tok, channel=ch, ts=ts, limit=200)["messages"]
    if a.json:
        print(json.dumps({"channel": chan, "channel_id": ch, "count": len(msgs), "messages": [{
            "ts": m.get("ts"), "user": names.user(m.get("user")) if m.get("user") else (m.get("bot_id") or "?"),
            "text": names.render(m.get("text")), "files": [f.get("name") for f in m.get("files", []) or []]}
            for m in msgs]}, ensure_ascii=False))
        return
    print(f"# #{chan}  ({len(msgs)} message(s))\n")
    for m in msgs:
        author = names.user(m.get("user")) if m.get("user") else (m.get("bot_id") or "?")
        print(f"--- {author}  ts={m.get('ts')}")
        print(names.render(m.get("text")))
        for f in m.get("files", []) or []:
            print(f"[file] {f.get('name')} ({f.get('filetype')})")
        print()


def cmd_channels(tok, a):
    chans = list_channels(tok)
    if a.json:
        print(json.dumps({"count": len(chans), "channels": chans}, ensure_ascii=False)); return
    for c in chans:
        print(f"{c['id']:<14} #{c['name']:<40} {c.get('members') or ''}")


def fetch_history(tok, ch, oldest):
    return paged("conversations.history", tok, "messages", channel=ch, oldest=oldest, limit=200)


def cmd_history(tok, a):
    ch = resolve_channel(tok, a.channel)
    names = Names(tok)
    msgs = sorted(fetch_history(tok, ch, since_ts(a.since)), key=lambda m: float(m["ts"]))
    rows = []
    for m in msgs:
        row = {"ts": m["ts"], "at": iso(m["ts"]), "permalink": permalink_of(ch, m["ts"]),
               "user": names.user(m.get("user")) if m.get("user") else (m.get("username") or m.get("bot_id") or "bot"),
               "is_bot": not m.get("user"), "text": names.render(m.get("text")),
               "reply_count": m.get("reply_count", 0), "reply_users": [names.user(u) for u in m.get("reply_users", [])]}
        if a.threads and m.get("reply_count"):
            reps = call("conversations.replies", tok, channel=ch, ts=m["ts"], limit=200)["messages"][1:]
            row["replies"] = [{"ts": r["ts"], "user": names.user(r.get("user")) if r.get("user") else "bot",
                               "text": names.render(r.get("text"))} for r in reps]
        rows.append(row)
    if a.json:
        print(json.dumps({"channel_id": ch, "since": a.since, "count": len(rows), "messages": rows}, ensure_ascii=False)); return
    for r in rows:
        print(f"--- {r['at']}  {r['user']}  replies={r['reply_count']}  {r['permalink']}")
        print(r["text"][:600]); print()


def pick_channels(tok, spec):
    """--channels a,b,#name → the channel dicts; None → every channel the bot can see."""
    chans = list_channels(tok)
    if not spec:
        return chans
    wanted = [x.strip().lstrip("#") for x in spec.split(",") if x.strip()]
    picked = [c for c in chans if c["id"] in wanted or c["name"] in wanted]
    missing = [w for w in wanted if not any(c["id"] == w or c["name"] == w for c in chans)]
    if missing:
        print(f"channels not visible to the bot: {', '.join(missing)}", file=sys.stderr)
    return picked


def replies_for(tok, ch, parents, workers=4):
    """Replies for many parents, a few at a time. Returns {ts: [replies]}."""
    def one(m):
        return m["ts"], call("conversations.replies", tok, channel=ch, ts=m["ts"], limit=200)["messages"][1:]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return dict(ex.map(one, parents))


def cmd_mentions(tok, a):
    user = whoami(tok, a.env_file) if a.user in (None, "me") else a.user
    oldest = since_ts(a.since)
    names = Names(tok)
    tag = f"<@{user}>"
    out = []
    for c in pick_channels(tok, a.channels):
        roots = fetch_history(tok, c["id"], oldest)
        # replies are fetched only for threads that were active inside the window
        active = [m for m in roots if m.get("reply_count") and float(m.get("latest_reply") or m["ts"]) >= float(oldest)]
        reps_by = replies_for(tok, c["id"], active)
        for root in roots:
            thread = [root] + reps_by.get(root["ts"], [])
            hits = [m for m in thread if tag in (m.get("text") or "") and m.get("user") != user and float(m["ts"]) >= float(oldest)]
            if not hits:
                continue
            last_hit = max(float(m["ts"]) for m in hits)
            answered = any(m.get("user") == user and float(m["ts"]) > last_hit for m in thread)
            out.append({"channel": c["name"], "permalink": permalink_of(c["id"], root["ts"]),
                        "root_by": names.user(root.get("user")) if root.get("user") else "bot",
                        "root": names.render(root.get("text"))[:300],
                        "mentions": [{"at": iso(m["ts"]), "by": names.user(m.get("user")), "text": names.render(m.get("text"))[:300]} for m in hits],
                        "last_mention_at": iso(f"{last_hit:.6f}"), "answered": answered})
    out.sort(key=lambda r: (r["answered"], r["last_mention_at"]))
    if a.json:
        print(json.dumps({"user": user, "since": a.since, "count": len(out),
                          "unanswered": sum(1 for r in out if not r["answered"]), "threads": out}, ensure_ascii=False)); return
    for r in out:
        flag = "WAITING" if not r["answered"] else "answered"
        print(f"[{flag}] #{r['channel']}  {r['last_mention_at']}  {r['permalink']}")
        print(f"   root by {r['root_by']}: {r['root'][:160]}")
        print(f"   last: {r['mentions'][-1]['by']}: {r['mentions'][-1]['text'][:200]}\n")


def cmd_unanswered(tok, a):
    """No replies fetched: a parent's reply_users tells who answered."""
    user = whoami(tok, a.env_file) if a.user in (None, "me") else a.user
    oldest = since_ts(a.since)
    names = Names(tok)
    out = []
    for c in pick_channels(tok, a.channels):
        for root in fetch_history(tok, c["id"], oldest):
            if root.get("user") != user:
                continue
            others = [u for u in root.get("reply_users", []) if u != user]
            if others:
                continue
            out.append({"channel": c["name"], "permalink": permalink_of(c["id"], root["ts"]), "at": iso(root["ts"]),
                        "root": names.render(root.get("text"))[:400], "own_replies": root.get("reply_count", 0)})
    out.sort(key=lambda r: r["at"])
    if a.json:
        print(json.dumps({"user": user, "since": a.since, "count": len(out), "threads": out}, ensure_ascii=False)); return
    for r in out:
        print(f"#{r['channel']}  {r['at']}  own replies={r['own_replies']}  {r['permalink']}")
        print(f"   {r['root'][:200]}\n")


def post_json(method, tok, payload):
    req = urllib.request.Request(API + method, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
    except Exception as e:
        print(f"slack {method}: {e!r}", file=sys.stderr); sys.exit(EX_REMOTE)
    if not d.get("ok"):
        print(f"slack {method} failed: {d.get('error')}", file=sys.stderr); sys.exit(EX_AUTH if d.get("error") in ("invalid_auth", "not_authed", "missing_scope") else EX_REMOTE)
    return d


def cmd_post(tok, a):
    """The one write. Target by shape: a thread permalink (reply there), #name / Cxxx (top level), or --dm."""
    text = open(a.file).read() if a.file and a.file != "-" else (sys.stdin.read() if a.file == "-" else a.text)
    if not text or not text.strip():
        print("nothing to post: pass --text or --file", file=sys.stderr); sys.exit(EX_USAGE)
    text = text.rstrip("\n")
    thread_ts, where = None, ""
    if a.dm:
        if a.target:
            print("--dm takes no target; the person is the target", file=sys.stderr); sys.exit(EX_USAGE)
        uid = whoami(tok, a.env_file) if a.dm == "me" else (a.dm if re.fullmatch(r"[UW][A-Z0-9]{8,}", a.dm) else whoami(tok, a.env_file, a.dm))
        ch = call("conversations.open", tok, users=uid)["channel"]["id"]
        where = f"DM to {Names(tok).user(uid)} ({uid})"
    elif not a.target:
        print("post needs a target: #channel, a channel id, a thread permalink, or --dm", file=sys.stderr); sys.exit(EX_USAGE)
    elif "/archives/" in a.target:
        ch, ts = parse_permalink(a.target)
        root = call("conversations.replies", tok, channel=ch, ts=ts, limit=1)["messages"][0]
        thread_ts = root.get("thread_ts") or root["ts"]
        where = f"reply in thread {permalink_of(ch, thread_ts)}  (root: {Names(tok).render(root.get('text', ''))[:80]!r})"
    else:
        ch = resolve_channel(tok, a.target)
        where = f"top level in #{next((c['name'] for c in list_channels(tok) if c['id'] == ch), ch)}"
    me = call("auth.test", tok)
    # idempotency: the same text from this bot already in the last 20 messages of the target → refuse
    recent = (call("conversations.replies", tok, channel=ch, ts=thread_ts, limit=20) if thread_ts
              else call("conversations.history", tok, channel=ch, limit=20))["messages"]
    dup = next((m for m in recent if m.get("bot_id") == me.get("bot_id") and (m.get("text") or "").strip() == text.strip()), None)
    if dup:
        print(f"refused: this exact message is already there — {permalink_of(ch, dup['ts'])}", file=sys.stderr); sys.exit(EX_AUTH)
    if not a.apply:
        out = {"dry_run": True, "as": me.get("user"), "where": where, "channel": ch, "thread_ts": thread_ts, "chars": len(text), "text": text}
        if a.json:
            print(json.dumps(out, ensure_ascii=False)); return
        print(f"DRY RUN — would post as @{me.get('user')}  {where}\n{'─' * 76}\n{text}\n{'─' * 76}\npass --apply to send")
        return
    payload = {"channel": ch, "text": text, "unfurl_links": False, "unfurl_media": False}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    d = post_json("chat.postMessage", tok, payload)
    link = permalink_of(d["channel"], d["ts"])
    print(json.dumps({"posted": True, "as": me.get("user"), "channel": d["channel"], "ts": d["ts"], "permalink": link}) if a.json else f"posted as @{me.get('user')}  {link}")


def cmd_whoami(tok, a):
    uid = whoami(tok, a.env_file, a.email)
    print(json.dumps({"user": uid}) if a.json else uid)


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # `| head` must not traceback
    ap = argparse.ArgumentParser(description="Slack capability: reads first-hand; `post` writes, dry run until --apply.")
    ap.add_argument("--env-file", help="file with SLACK_BOT_TOKEN (and JIRA_EMAIL for whoami)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("read", help="one message and its thread, by permalink")
    p.add_argument("permalink"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("channels", help="channels the bot can see")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("history", help="top-level messages in a channel since a point in time")
    p.add_argument("channel", help="channel id or #name"); p.add_argument("--since", required=True)
    p.add_argument("--threads", action="store_true", help="include replies"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("mentions", help="messages mentioning a user, and whether they answered")
    p.add_argument("--since", required=True); p.add_argument("--user", default="me")
    p.add_argument("--channels", help="comma-separated ids or #names; default every channel the bot sees")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("unanswered", help="threads a user started that nobody else replied to")
    p.add_argument("--since", required=True); p.add_argument("--user", default="me")
    p.add_argument("--channels", help="comma-separated ids or #names; default every channel the bot sees")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("whoami", help="user id behind an email")
    p.add_argument("--email"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("post", help="send a message as the bot — dry run unless --apply")
    p.add_argument("target", nargs="?", help="#channel, channel id, or a thread permalink (reply there)")
    p.add_argument("--text"); p.add_argument("--file", help="markdown/text file, or - for stdin")
    p.add_argument("--dm", help="me · an email · a user id — a direct message instead of a channel")
    p.add_argument("--apply", action="store_true", help="actually send; without it nothing leaves the machine")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    tok = token(a.env_file)
    {"read": cmd_read, "channels": cmd_channels, "history": cmd_history, "mentions": cmd_mentions,
     "unanswered": cmd_unanswered, "whoami": cmd_whoami, "post": cmd_post}[a.cmd](tok, a)


if __name__ == "__main__":
    main()
