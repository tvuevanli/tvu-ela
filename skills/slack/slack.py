#!/usr/bin/env python3
"""Slack capability. L1: subcommands, --json, meaningful exit codes, stdlib only. Reads are first-hand;
the one write, `post`, is a dry run until --apply.

  read       <permalink>                 one message and its thread
  files      <permalink> [--out DIR]     download that message's or thread's files — a screenshot is evidence
  channels   [--all] [match]             channels the bot is in; --all every public channel in the workspace
  history    <channel> --since 48h       top-level messages (--threads adds replies; --humans drops bot AUTHORS,
                                         keeping a person's app-posted message — the daily reports arrive that way)
  mentions   --since 48h [--user me] [--channels a,b]   messages that mention a user, with whether they answered
  unanswered --since 7d  [--user me] [--channels a,b]   threads a user started that nobody else replied to
  whoami     [--email x]                 the user id behind an email (default: JIRA_EMAIL in the env file)
  post       <#channel|Cxxx|thread permalink> --text "…" | --file f.md [--dm me|email|Uxxx] [--apply]
             send a message as the bot (a permalink → reply in that thread). Dry run by default; refuses a
             duplicate of a message the bot already posted there; a DM needs --dm said explicitly.

Exit codes: 0 ok · 2 usage · 4 auth or refused · 5 remote error.
Credential resolution: $SLACK_BOT_TOKEN → --env-file → $SLACK_ENV_FILE → $ELA_ENV_FILE. The script never stores it.
"""
import argparse, html, json, os, re, shutil, signal, sys, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

API = "https://slack.com/api/"
EX_USAGE, EX_AUTH, EX_REMOTE = 2, 4, 5
# A large response body truncates on this link (IncompleteRead), and a retry at the same size
# truncates again — so a page that fails is refetched smaller, at the same cursor.
PAGE_STEPS = (200, 100, 50, 25, 10)


class Transient(Exception):
    """A call that failed for a reason a smaller page or another attempt may fix."""


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


def raw(method, tok, **params):
    """One Slack call, no retries, no exit — for probing before we can advise. Returns the payload."""
    url = API + method + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception as e:
        return {"ok": False, "error": repr(e)}


def not_in_channel_hint(tok, ch):
    """not_in_channel is a membership problem, not a failure: say which channel and what fixes it."""
    d = raw("conversations.info", tok, channel=ch)
    c = d.get("channel") or {}
    name = c.get("name")
    where = f"#{name} ({ch})" if name else ch
    if not d.get("ok"):
        return (f"the bot is not in {where}, and its metadata is not readable either.\n"
                f"  Ask someone in the channel to invite the bot, or check the channel id.")
    if c.get("is_private"):
        return (f"{where} is private — a bot cannot add itself.\n"
                f"  Ask a member to run  /invite @helm  in that channel.")
    return (f"{where} is public and the bot may join it.\n"
            f"  Joining is visible to the channel, so it is not automatic. To join and retry:\n"
            f"    slack.py join {ch}          # then rerun the command\n"
            f"    slack.py read <permalink> --join")


def call(method, tok, _soft=False, **params):
    """One Slack call with retries on 429 and transient network faults. Raises SystemExit(5) on failure,
    or Transient when `_soft` — the caller then decides between a smaller page and giving up on one channel."""
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
        if d.get("error") == "not_in_channel" and params.get("channel"):
            print(f"slack {method}: not_in_channel", file=sys.stderr)
            print(not_in_channel_hint(tok, params["channel"]), file=sys.stderr)
            sys.exit(EX_USAGE)
        print(f"slack {method} failed: {d.get('error')}", file=sys.stderr); sys.exit(EX_REMOTE)
    if _soft:
        raise Transient(f"{method}: {last}")
    print(f"slack {method}: gave up after retries ({last})", file=sys.stderr); sys.exit(EX_REMOTE)


def paged(method, tok, key, limit=200, **params):
    """Every page of a listing. A page that will not come down whole is refetched at half the size,
    at the same cursor, and the smaller size is kept for the rest of the walk. Raises Transient when
    even the smallest page fails — one unreadable channel must not decide a whole lane's fate."""
    out, cursor, steps, i = [], None, [s for s in PAGE_STEPS if s <= limit] or [limit], 0
    while True:
        try:
            d = call(method, tok, _soft=True, limit=steps[i], **params,
                     **({"cursor": cursor} if cursor else {}))
        except Transient:
            if i + 1 >= len(steps):
                raise
            i += 1
            continue
        out += d.get(key, [])
        cursor = (d.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return out
        time.sleep(0.3)  # conversations.list is tier 2: a 2500-channel walk must not trip the limiter


class Names:
    def __init__(self, tok):
        self.tok, self.cache, self.bots = tok, {}, {}

    def _load(self, uid):
        try:
            u = call("users.info", self.tok, user=uid)["user"]
        except SystemExit:
            self.cache[uid], self.bots[uid] = uid, False
            return
        self.cache[uid] = (u.get("profile", {}).get("real_name") or u.get("real_name")
                           or u.get("name") or uid)
        self.bots[uid] = bool(u.get("is_bot")) or uid == "USLACKBOT"

    def user(self, uid):
        if not uid:
            return "?"
        if uid not in self.cache:
            self._load(uid)
        return self.cache[uid]

    def is_bot(self, uid):
        if not uid:
            return True
        if uid not in self.bots:
            self._load(uid)
        return self.bots[uid]

    def render(self, text):
        """Ids become names, then Slack's entities become the characters they stand for — `&lt;` in a
        command line or a URL's `&amp;` is unreadable as it arrives. Mentions are substituted first,
        so unescaping can never manufacture one."""
        return html.unescape(re.sub(r"<@([A-Z0-9]+)>", lambda m: "@" + self.user(m.group(1)), text or ""))


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


JOIN_SUBTYPES = {"channel_join", "channel_leave", "group_join", "group_leave"}


def is_noise(m):
    """A join notice is not a message, and a body with no text, no file and no attachment cannot be
    read even if it is one. Both crowd out the content in a busy channel's window."""
    if m.get("subtype") in JOIN_SUBTYPES:
        return True
    return not (m.get("text") or "").strip() and not m.get("files") and not m.get("attachments")


def from_bot(m, names=None):
    """Whether a bot wrote this, which is a question about the AUTHOR, not about the message.

    A `bot_id` on the message is not the test: a person posting through an app or a workflow carries
    one too. The MediaHub daily reports are posted that way by a human QA engineer, so treating a
    bot_id as the mark would hide exactly the messages the reports lane exists to find. The user's
    own `is_bot` is the fact; only a message with no author at all is a bot's by shape."""
    uid = m.get("user")
    if not uid:
        return True
    return names.is_bot(uid) if names else False


def list_channels(tok):
    chans = paged("users.conversations", tok, "channels", types="public_channel,private_channel")
    return [{"id": c["id"], "name": c.get("name"), "members": c.get("num_members"), "member": True,
             "private": bool(c.get("is_private")), "purpose": (c.get("purpose") or {}).get("value", "")}
            for c in chans]


def list_public_channels(tok):
    """Every public channel in the workspace, joined or not. `users.conversations` knows only the ones
    the bot is in, so a channel it has never joined is undiscoverable through it — and a mention
    pointing into one is a dead end. Needs the `channels:read` scope."""
    chans = paged("conversations.list", tok, "channels", types="public_channel", exclude_archived="true")
    return [{"id": c["id"], "name": c.get("name"), "members": c.get("num_members"),
             "member": bool(c.get("is_member")), "private": False,
             "purpose": (c.get("purpose") or {}).get("value", "")} for c in chans]


def channel_missing_hint(tok, ch):
    """`channel_not_found` says nothing about which of the two cases it is. The public list decides:
    a public channel the bot can join, or one it cannot reach on its own."""
    hit = next((c for c in list_public_channels(tok) if c["id"] == ch), None)
    if hit:
        return (f"#{hit['name']} ({ch}) is public and the bot is not in it.\n"
                f"  Joining is visible to the channel, so it is never automatic:\n"
                f"    ela slack join {ch}          # then rerun")
    return (f"{ch} is not a public channel of this workspace — it is private, a DM, or archived.\n"
            f"  A bot cannot add itself to a private channel. Ask a member to run  /invite @helm  there.")


def resolve_channel(tok, ref):
    if re.fullmatch(r"[CG][A-Z0-9]{8,}", ref):
        return ref
    name = ref.lstrip("#")
    for c in list_channels(tok):
        if c["name"] == name:
            return c["id"]
    hit = next((c for c in list_public_channels(tok) if c["name"] == name), None)
    if hit:
        print(f"#{name} is public ({hit['id']}, {hit['members'] or 0} members) but the bot is not in it.\n"
              f"  Joining is visible to the channel:  ela slack join #{name}", file=sys.stderr)
        sys.exit(EX_USAGE)
    print(f"no channel #{name} the bot can see, and none by that name among the public channels",
          file=sys.stderr); sys.exit(EX_USAGE)


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

def join_channel(tok, ch):
    """conversations.join — public channels only; visible to the channel, so always explicit."""
    d = raw("conversations.join", tok, channel=ch)
    if d.get("ok"):
        return True
    print(f"slack conversations.join: {d.get('error')}", file=sys.stderr)
    print(not_in_channel_hint(tok, ch), file=sys.stderr)
    return False


def cmd_join(tok, a):
    ch = a.channel
    if ch.startswith("http"):
        ch, _ = parse_permalink(ch)
    elif ch.startswith("#"):
        ch = resolve_channel(tok, ch)
    if not join_channel(tok, ch):
        sys.exit(EX_USAGE)
    d = raw("conversations.info", tok, channel=ch)
    name = (d.get("channel") or {}).get("name", ch)
    print(f"joined #{name} ({ch})")


def thread_messages(tok, ch, ts):
    """A thread, with `channel_not_found` answered rather than repeated."""
    try:
        return call("conversations.replies", tok, channel=ch, ts=ts, limit=200)["messages"]
    except SystemExit:
        print(channel_missing_hint(tok, ch), file=sys.stderr)
        raise


def cmd_read(tok, a):
    ch, ts = parse_permalink(a.permalink)
    if getattr(a, "join", False) and not join_channel(tok, ch):
        sys.exit(EX_USAGE)
    names = Names(tok)
    try:
        chan = call("conversations.info", tok, channel=ch)["channel"].get("name", ch)
    except SystemExit:
        chan = ch
    msgs = thread_messages(tok, ch, ts)
    if a.json:
        print(json.dumps({"channel": chan, "channel_id": ch, "count": len(msgs), "messages": [{
            "ts": m.get("ts"), "user": names.user(m.get("user")) if m.get("user") else (m.get("bot_id") or "?"),
            "text": names.render(m.get("text")),
            "files": [{"id": f.get("id"), "name": f.get("name"), "type": f.get("filetype")}
                      for f in m.get("files", []) or []]}
            for m in msgs]}, ensure_ascii=False))
        return
    print(f"# #{chan}  ({len(msgs)} message(s))\n")
    for m in msgs:
        author = names.user(m.get("user")) if m.get("user") else (m.get("bot_id") or "?")
        print(f"--- {author}  ts={m.get('ts')}")
        print(names.render(m.get("text")))
        for f in m.get("files", []) or []:
            print(f"[file] {f.get('name')} ({f.get('filetype')})  id={f.get('id')}")
        print()
    if any(m.get("files") for m in msgs):
        print(f"# files: ela slack files {a.permalink} --out DIR")


def default_out_dir():
    """Downloads are working state, so they belong under <runtime> when the site names one.
    Nothing under <runtime> is a record — the tree can be deleted whenever no task is open."""
    try:
        with open(os.path.expanduser("~/.claude/ela/site.json")) as f:
            s = json.load(f)
        root = s.get("runtime") or (s.get("projects") and os.path.join(s["projects"], ".ela"))
        if root:
            return os.path.join(root, "slack-files")
    except (OSError, ValueError):
        pass
    return os.path.join(os.getcwd(), "slack-files")


def cmd_files(tok, a):
    """Download a message's or a thread's files. A screenshot is how most of the evidence in these
    channels arrives; named but unfetched, it is a fact ela cannot read. Writes only to disk."""
    ch, ts = parse_permalink(a.permalink)
    msgs = thread_messages(tok, ch, ts)
    if not a.thread:
        msgs = [m for m in msgs if m.get("ts") == ts] or msgs[:1]
    out = os.path.abspath(a.out or default_out_dir())
    os.makedirs(out, exist_ok=True)
    got, skipped = [], []
    for m in msgs:
        for f in m.get("files", []) or []:
            if a.id and f.get("id") != a.id:
                continue
            url = f.get("url_private_download") or f.get("url_private")
            if not url:
                skipped.append({"id": f.get("id"), "name": f.get("name"), "why": "no download url (external or tombstoned)"})
                continue
            name = f"{f.get('id')}-{re.sub(r'[^A-Za-z0-9._-]+', '_', f.get('name') or 'file')}"
            path = os.path.join(out, name)
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as fh:
                    shutil.copyfileobj(r, fh)
            except Exception as e:
                skipped.append({"id": f.get("id"), "name": f.get("name"), "why": repr(e)}); continue
            got.append({"id": f.get("id"), "name": f.get("name"), "type": f.get("filetype"),
                        "bytes": os.path.getsize(path), "path": path,
                        "by": Names(tok).user(m.get("user")) if m.get("user") else "bot", "ts": m.get("ts")})
    if a.json:
        print(json.dumps({"out": out, "count": len(got), "files": got, "skipped": skipped}, ensure_ascii=False)); return
    for g in got:
        print(f"{g['path']}  ({g['type']}, {g['bytes']} bytes, by {g['by']})")
    for s in skipped:
        print(f"skipped {s['name']}: {s['why']}", file=sys.stderr)
    if not got:
        print("no files on that message (add --thread for the whole thread)", file=sys.stderr)
        sys.exit(EX_USAGE if not skipped else EX_REMOTE)


def cmd_channels(tok, a):
    chans = list_public_channels(tok) if a.all else list_channels(tok)
    if a.match:
        m = a.match.lower()
        chans = [c for c in chans if m in (c["name"] or "").lower() or m in (c["purpose"] or "").lower()]
    chans.sort(key=lambda c: (not c["member"], -(c.get("members") or 0), c["name"] or ""))
    if a.json:
        print(json.dumps({"count": len(chans), "member_of": sum(1 for c in chans if c["member"]),
                          "scope": "public" if a.all else "joined", "channels": chans}, ensure_ascii=False)); return
    for c in chans:
        mark = "●" if c["member"] else "○"
        print(f"{mark} {c['id']:<14} #{(c['name'] or ''):<44} {c.get('members') or '':>5}  {(c['purpose'] or '')[:60]}")
    if a.all:
        print(f"\n# {len(chans)} public channel(s); ● = the bot is in it ({sum(1 for c in chans if c['member'])}). "
              f"Joining is visible to the channel: ela slack join #name")


def fetch_history(tok, ch, oldest):
    """Raises Transient when the channel will not come down. Callers over many channels catch it and
    name the channel as unread — a lane that dies on one channel reports nothing about the others."""
    return paged("conversations.history", tok, "messages", channel=ch, oldest=oldest)


def cmd_history(tok, a):
    ch = resolve_channel(tok, a.channel)
    names = Names(tok)
    try:
        msgs = fetch_history(tok, ch, since_ts(a.since))
    except Transient as e:
        print(f"slack history: {ch} did not come down whole ({e})", file=sys.stderr); sys.exit(EX_REMOTE)
    msgs = sorted((m for m in msgs if not is_noise(m)), key=lambda m: float(m["ts"]))
    if a.humans:
        msgs = [m for m in msgs if not from_bot(m, names)]
    rows = []
    for m in msgs:
        row = {"ts": m["ts"], "at": iso(m["ts"]), "permalink": permalink_of(ch, m["ts"]),
               "user": names.user(m.get("user")) if m.get("user") else (m.get("username") or m.get("bot_id") or "bot"),
               "is_bot": from_bot(m, names), "text": names.render(m.get("text")),
               "reply_count": m.get("reply_count", 0), "reply_users": [names.user(u) for u in m.get("reply_users", [])]}
        if a.threads and m.get("reply_count"):
            reps = call("conversations.replies", tok, channel=ch, ts=m["ts"], limit=200)["messages"][1:]
            row["replies"] = [{"ts": r["ts"], "user": names.user(r.get("user")) if r.get("user") else "bot",
                               "text": names.render(r.get("text"))} for r in reps]
        rows.append(row)
    if a.json:
        print(json.dumps({"channel_id": ch, "since": a.since, "count": len(rows), "messages": rows}, ensure_ascii=False)); return
    for r in rows:
        bot = " [bot]" if r["is_bot"] else ""
        print(f"--- {r['at']}  {r['user']}{bot}  replies={r['reply_count']}  {r['permalink']}")
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
        print(f"channels the bot is not in: {', '.join(missing)}"
              f"  — `ela slack channels --all <name>` says whether they are public, then `ela slack join`",
              file=sys.stderr)
    return picked


def replies_for(tok, ch, parents, workers=4):
    """Replies for many parents, a few at a time. Returns {ts: [replies]}. A thread that will not come
    down is empty rather than fatal — its parent still carries reply_count and reply_users."""
    def one(m):
        try:
            return m["ts"], call("conversations.replies", tok, _soft=True, channel=ch, ts=m["ts"], limit=200)["messages"][1:]
        except Transient:
            return m["ts"], []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return dict(ex.map(one, parents))


def cmd_mentions(tok, a):
    user = whoami(tok, a.env_file) if a.user in (None, "me") else a.user
    oldest = since_ts(a.since)
    names = Names(tok)
    tag = f"<@{user}>"
    out, unread = [], []
    for c in pick_channels(tok, a.channels):
        try:
            roots = fetch_history(tok, c["id"], oldest)
        except Transient as e:
            unread.append({"channel": c["name"], "id": c["id"], "why": str(e)}); continue
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
                          "unanswered": sum(1 for r in out if not r["answered"]),
                          "unread_channels": unread, "threads": out}, ensure_ascii=False)); return
    for r in out:
        flag = "WAITING" if not r["answered"] else "answered"
        print(f"[{flag}] #{r['channel']}  {r['last_mention_at']}  {r['permalink']}")
        print(f"   root by {r['root_by']}: {r['root'][:160]}")
        print(f"   last: {r['mentions'][-1]['by']}: {r['mentions'][-1]['text'][:200]}\n")
    report_unread(unread)


def report_unread(unread):
    """A lane that could not read a channel says so. A silent lane is a lie."""
    for u in unread:
        print(f"# not read: #{u['channel']} ({u['id']}) — {u['why']}", file=sys.stderr)


def cmd_unanswered(tok, a):
    """No replies fetched: a parent's reply_users tells who answered."""
    user = whoami(tok, a.env_file) if a.user in (None, "me") else a.user
    oldest = since_ts(a.since)
    names = Names(tok)
    out, unread = [], []
    for c in pick_channels(tok, a.channels):
        try:
            roots = fetch_history(tok, c["id"], oldest)
        except Transient as e:
            unread.append({"channel": c["name"], "id": c["id"], "why": str(e)}); continue
        for root in roots:
            if root.get("user") != user or is_noise(root):
                continue
            others = [u for u in root.get("reply_users", []) if u != user]
            if others:
                continue
            out.append({"channel": c["name"], "permalink": permalink_of(c["id"], root["ts"]), "at": iso(root["ts"]),
                        "root": names.render(root.get("text"))[:400], "own_replies": root.get("reply_count", 0)})
    out.sort(key=lambda r: r["at"])
    if a.json:
        print(json.dumps({"user": user, "since": a.since, "count": len(out),
                          "unread_channels": unread, "threads": out}, ensure_ascii=False)); return
    for r in out:
        print(f"#{r['channel']}  {r['at']}  own replies={r['own_replies']}  {r['permalink']}")
        print(f"   {r['root'][:200]}\n")
    report_unread(unread)


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


def list_users(tok):
    """Every human, non-deleted member of the workspace: id, real name, email, title. First-hand from users.list."""
    out = []
    for u in paged("users.list", tok, "members", limit=200):
        if u.get("deleted") or u.get("is_bot") or u.get("id") == "USLACKBOT":
            continue
        pr = u.get("profile") or {}
        out.append({"id": u["id"], "name": pr.get("real_name") or u.get("real_name") or u.get("name"),
                    "email": pr.get("email"), "title": pr.get("title") or "", "handle": u.get("name"),
                    "tz": u.get("tz"), "guest": bool(u.get("is_restricted") or u.get("is_ultra_restricted"))})
    return sorted(out, key=lambda x: (x["name"] or "").lower())


def cmd_users(tok, a):
    users = list_users(tok)
    if a.match:
        m = a.match.lower()
        users = [u for u in users if m in (u["name"] or "").lower() or m in (u["email"] or "").lower() or m in (u["handle"] or "").lower()]
    if a.json:
        print(json.dumps({"count": len(users), "users": users}, ensure_ascii=False)); return
    for u in users:
        print(f"{u['id']:<12} {(u['name'] or ''):<28} {(u['email'] or '-'):<36} {u['title']}")


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # `| head` must not traceback
    ap = argparse.ArgumentParser(description="Slack capability: reads first-hand; `post` writes, dry run until --apply.")
    ap.add_argument("--env-file", help="file with SLACK_BOT_TOKEN (and JIRA_EMAIL for whoami)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("read", help="one message and its thread, by permalink")
    p.add_argument("permalink"); p.add_argument("--json", action="store_true")
    p.add_argument("--join", action="store_true", help="join the channel first (public only; visible to the channel)")
    p = sub.add_parser("join", help="join a public channel — explicit, because the channel sees it")
    p.add_argument("channel", help="channel id, #name, or a permalink")
    p = sub.add_parser("files", help="download a message's or thread's files — a screenshot is evidence")
    p.add_argument("permalink"); p.add_argument("--out", help=f"directory (default {default_out_dir()})")
    p.add_argument("--thread", action="store_true", help="every file in the thread, not just that message")
    p.add_argument("--id", help="one file id (Fxxx) from `read`"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("channels", help="channels the bot is in; --all every public channel of the workspace")
    p.add_argument("match", nargs="?", help="substring of a channel name or purpose")
    p.add_argument("--all", action="store_true", help="every public channel, joined or not (needs channels:read)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("history", help="top-level messages in a channel since a point in time")
    p.add_argument("channel", help="channel id or #name"); p.add_argument("--since", required=True)
    p.add_argument("--threads", action="store_true", help="include replies")
    p.add_argument("--humans", action="store_true",
                   help="drop posts whose author is a bot user. A person posting through an app is kept — "
                        "the daily reports arrive that way, so this never hides them")
    p.add_argument("--json", action="store_true")
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
    p = sub.add_parser("users", help="workspace members — id, name, email, title; first-hand from users.list")
    p.add_argument("match", nargs="?", help="substring of a name, email or handle")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("post", help="send a message as the bot — dry run unless --apply")
    p.add_argument("target", nargs="?", help="#channel, channel id, or a thread permalink (reply there)")
    p.add_argument("--text"); p.add_argument("--file", help="markdown/text file, or - for stdin")
    p.add_argument("--dm", help="me · an email · a user id — a direct message instead of a channel")
    p.add_argument("--apply", action="store_true", help="actually send; without it nothing leaves the machine")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    tok = token(a.env_file)
    {"read": cmd_read, "channels": cmd_channels, "history": cmd_history, "mentions": cmd_mentions,
     "unanswered": cmd_unanswered, "whoami": cmd_whoami, "users": cmd_users, "post": cmd_post,
     "join": cmd_join, "files": cmd_files}[a.cmd](tok, a)


if __name__ == "__main__":
    main()
