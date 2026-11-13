#!/usr/bin/env python3
"""A mention of the owner in Slack: he goes first, ela follows through (ADR 0021). Stdlib only. Every verb is
read-only toward Slack and Jira; what it writes is its own store, a local draft, and dry-run batches through dry.py.

A mention is triaged as an ask (a question, a request, a decision put to him), an incident (a prod failure addressed to
him) or a notice (a bot's "ready to test", an FYI, a cc, an announcement to many that asks him nothing alone). On an ask ela reads the thread, gathers the facts and waits:
he usually answers himself. A reply of his closes the mention, and what that reply commits to is prepared as dry runs
under the action classes of `ela dry`. Unanswered after the wait window, the mention earns one message to him: the ask
in a sentence, the facts, a reply drafted for him to paste, and A use this draft · B I will write it · C nothing
needed. ela never posts the reply. An incident sends its facts at once and drafts nothing; a notice is recorded and
never raised. Outside his hours nothing is sent: the mention takes an ask slot on today.md. When a mention closes, a
drafted Slack action aimed at the same thread in the runner's actions file is marked superseded.

  scan    [--since 24h] [--json]          the Slack fact store read for mentions of him: new ones recorded and
                                          triaged, his replies noticed, what is now to do listed (the pass calls this)
  note    <permalink> [--fresh] [--json]  the same for one thread (the watcher calls this on a mention of him and on
                                          a message of his in a thread; --fresh reads the thread from Slack now)
  due     [--json]                        what is to do now: a draft to write, a message to send him, a timer to set
  list    [--all] [--json]                the open mentions (--all: every one on record)
  show    <id|permalink> [--json]         one mention: thread, triage and reason, his reply, what was prepared, his letter
  triage  <permalink> [--fresh] [--json]  how one message would be triaged, with the reason; nothing is recorded
  facts   <id|permalink> [--fresh] [--json]  the tickets the thread names (state, owner, Fixed In) and the related
                                          threads from the links index, five lines at most
  draft   <id|permalink> --ask "…" --reply-file F [--json]
                                          the message for him, written to the store: the ask, the facts, the reply to
                                          paste, the dry runs it implies, A / B / C. Nothing is sent
  sent    <id> [--ts T]                   the runner's word that the message reached him
  answer  <id|dm ts> <A|B|C> [--json]     his letter: A prepares the draft's dry runs by class, B leaves it to him,
                                          C closes it and counts against the triage of that kind of message
  supersede <id> [--why T] [--json]       the drafted, unapplied Slack actions aimed at this mention's thread in
                                          <reports>/runner/*-actions.json, marked superseded (the closes do it too)
  follow  <id> [--fresh] [--json]         his reply read again for what it commits to (a session's second look)
  close   <id> [--why T]                  closed on his word
  asks    [--json]                        the mentions that take an ask slot on today.md (held outside his hours)
  waiting [--json]                        the open asks as lines for a meeting note's Waiting on you
  tally   [--json]                        each triage reason: how often it fired and how it ended; a C is a miss

Store: <reports>/ela/mentions/ — mentions.json (one record a mention: thread, triage, his reply, what was prepared,
his letter), triage.jsonl (every triage with its reason, every outcome), drafts/<id>.txt, tickets/<id>.md.
The wait is one setting, MENTION_WAIT_MIN below (`day.mention_wait_min` in <elak>/blueprint/meetings.yaml overrides
it); his hours are that file's `day.dm_hours`.
Exit codes: 0 ok · 2 usage · 3 not found · 5 remote.
"""
import argparse, datetime, glob, html, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.expanduser("~/.claude/ela/site.json")
TZ = datetime.timezone(datetime.timedelta(hours=8))
EX_USAGE, EX_NOTFOUND, EX_REMOTE = 2, 3, 5
MENTION_WAIT_MIN = 30                          # the wait before ela tells him (his choice of 2026-11-12)
DM_HOURS = ("08:30", "19:00")                  # the default when the day file names none
FACT_LINES = 5
BROADCAST_MIN = 6                              # people tagged in one message from which it reads as an announcement
KEY_RX = re.compile(r"(?<![A-Za-z0-9_-])([A-Z][A-Z0-9]{1,9}-[1-9]\d{0,5})(?![0-9])")
TAG = r"<@[A-Z0-9]+(?:\|[^>]*)?>"
PERMALINK_RX = re.compile(r"/archives/([A-Z0-9]+)/p(\d{10})(\d{6})(?:\?[^\s>|]*?thread_ts=(\d+\.\d+))?")
OPEN = ("waiting", "incident", "drafted")
EXPIRE_DAYS = 3                                # an ask nobody answered leaves after three working days (ADR 0014's span)

# ── triage: a closed vocabulary, erring toward telling him ────────────────────────────────────────────────────
# A reason is the kind of message the tally counts: a C from him on an ask of that kind is a miss against it.
ASK_RX = re.compile(r'[?？]|吗|是否|怎么|如何|能否|可否|请|帮忙|麻烦|确认|拍板|看下|看一下|\bplease\b|\bpls\b|\bcan you\b|'
                    r'\bcould you\b|\bwould you\b|\badvise\b|\bneed you(?:r)?\b|\bconfirm\b|\bdecide\b|\bapprove\b|'
                    r'\bthoughts\b|\bwhat do you think\b', re.I)
FYI_TAIL = re.compile(r"((?:" + TAG + r"[ \t,，、]*)+)[ \t]*(?:FYI|for your info\w*|知悉|供参考)", re.I)
CC_TAIL = re.compile(r"(?:\bcc|抄送|\bcopy)[ \t:：]*((?:" + TAG + r"[ \t,，、]*)+)", re.I)
PROD_RX = re.compile(r'\bprod(?:uction)?(?:[- ]?\d)?\b|线上|生产环境|现网', re.I)
INCIDENT_RX = re.compile(r'\b(?:down|outage|incident|urgent|emergency|sev[ -]?[012]|not working|broken|crash(?:ed|ing)?)\b|'
                         r'故障|宕机|挂了|中断|不可用|紧急|事故|崩了', re.I)
REASONS = {
    "incident": "names prod and a failure, and is addressed to him",
    "question": "asks or requests something of him",
    "bare-mention": "names him with no words of its own (a file or the message above is the ask)",
    "addressed": "names him in a statement; no rule calls it a notice",
    "broadcast": "tags many people and puts no question to him alone",
    "bot-notice": "a bot's announcement that asks nothing",
    "fyi-tail": "names him only in the tags before an FYI",
    "cc-tail": "names him only in a cc",
}
KIND_OF = {"incident": "incident", "question": "ask", "bare-mention": "ask", "addressed": "ask", "broadcast": "notice",
           "bot-notice": "notice", "fyi-tail": "notice", "cc-tail": "notice"}
RANK = {"notice": 0, "ask": 1, "incident": 2}


def triage(text, me, bot=False, channel=""):
    """(kind, reason) of one message that mentions `me`."""
    text = text or ""
    tag = re.compile(r"<@" + re.escape(me) + r"(?:\|[^>]*)?>")
    total = len(tag.findall(text))
    tail = None
    for rx, name in ((FYI_TAIL, "fyi-tail"), (CC_TAIL, "cc-tail")):
        inside = sum(len(tag.findall(m.group(1))) for m in rx.finditer(text))
        if inside and inside == total:                    # every mention of him sits in the tail
            tail = name
    if tail:
        return "notice", tail
    text = re.sub(r"<(?:https?|mailto)[^>]*>|https?://\S+", " ", text)   # a link's own `?` asks nothing
    if (PROD_RX.search(text) or (channel or "").lower().startswith("prod")) and INCIDENT_RX.search(text):
        return "incident", "incident"
    if len(set(re.findall(r"<@([A-Z0-9]+)", text))) >= BROADCAST_MIN and not asked_alone(text, me):
        return "notice", "broadcast"                      # an announcement to many: its "please" is not put to him
    if ASK_RX.search(text):
        return "ask", "question"
    if bot:
        return "notice", "bot-notice"
    if not re.sub(TAG + r"|<[^>]+>|\s", "", text):
        return "ask", "bare-mention"
    return "ask", "addressed"


def asked_alone(text, me):
    """Whether a message puts a question to him alone: a stretch of it (a sentence that tags someone, with the
    untagged sentences after it) tags nobody but him and asks."""
    scopes = []
    for s in sentences(text):
        tags = set(re.findall(r"<@([A-Z0-9]+)", s))
        if tags or not scopes:
            scopes.append([tags, s])
        else:
            scopes[-1][1] += "\n" + s
    return any(tags == {me} and ASK_RX.search(s) for tags, s in scopes)


# ── the site, the day, the stores ─────────────────────────────────────────────────────────────────────────────
def site():
    try:
        return json.load(open(SITE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def roots(a=None):
    s = site()
    runtime = os.path.expanduser(os.environ.get("ELA_FACTS_RUNTIME") or s.get("runtime") or os.path.join(s.get("projects") or os.getcwd(), ".ela"))
    return {"reports": getattr(a, "reports", None) or s.get("reports") or "", "runtime": runtime,
            "slack": getattr(a, "slack_dir", None) or os.path.join(runtime, "facts", "slack"),
            "jira": os.path.join(runtime, "facts", "jira", "issues"),
            "env": getattr(a, "env_file", None) or os.environ.get("ELA_ENV_FILE") or s.get("env")}


def day_settings(doc=None):
    """{wait (minutes), hours (HH:MM, HH:MM), holidays}: the owner's day file, else the defaults."""
    if doc is None:
        try:
            sys.path.insert(0, os.path.join(HERE, "..", "brief"))
            import brief as B                              # noqa: E402 — the one reader of the day file
            d = B.owner_day()
            doc = dict(d.get("day") or {}, holidays=d.get("holidays") or [])
        except Exception:                                  # noqa: BLE001 — a bad day file costs the override only
            doc = {}
    hours = [str(x) for x in (doc.get("dm_hours") or [])]
    try:
        wait = int(str(doc.get("mention_wait_min") or MENTION_WAIT_MIN))
    except ValueError:
        wait = MENTION_WAIT_MIN
    return {"wait": wait, "hours": tuple(hours) if len(hours) == 2 else DM_HOURS, "holidays": list(doc.get("holidays") or [])}


def working(day, d):
    return d.weekday() < 5 and d.isoformat() not in day["holidays"]


def bounds(day, d):
    (h1, m1), (h2, m2) = (map(int, x.split(":")) for x in day["hours"])
    at = datetime.datetime(d.year, d.month, d.day, tzinfo=TZ)
    return at.replace(hour=h1, minute=m1), at.replace(hour=h2, minute=m2)


def in_hours(day, t):
    lo, hi = bounds(day, t.date())
    return working(day, t.date()) and lo <= t < hi


def window(day, at):
    """(due, hold) for a mention at `at`: the wait runs in his working time only. Inside his hours with the whole wait
    before they end, it is due after the wait and a message may go; otherwise the rest of the wait runs from the next
    opening and the mention is held for today.md (no message outside his hours)."""
    wait = datetime.timedelta(minutes=day["wait"])
    if in_hours(day, at):
        hi = bounds(day, at.date())[1]
        if at + wait <= hi:
            return at + wait, False
        wait -= hi - at
    d = at.date() + datetime.timedelta(days=1) if (working(day, at.date()) and at >= bounds(day, at.date())[0]) else at.date()
    while not working(day, d):
        d += datetime.timedelta(days=1)
    return bounds(day, d)[0] + wait, True


def store(reports):
    return os.path.join(reports, "ela", "mentions")


def atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def load(reports):
    try:
        return json.load(open(os.path.join(store(reports), "mentions.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(reports, recs):
    atomic_write(os.path.join(store(reports), "mentions.json"), json.dumps(recs, ensure_ascii=False, indent=1) + "\n")


def log(reports, row):
    p = os.path.join(store(reports), "triage.jsonl")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_log(reports):
    out = []
    try:
        for line in open(os.path.join(store(reports), "triage.jsonl"), encoding="utf-8"):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return out


def iso(t):
    return t.isoformat(timespec="seconds")


def at_of(ts):
    return datetime.datetime.fromtimestamp(float(ts), TZ)


def parse(s):
    return datetime.datetime.fromisoformat(s)


def read_json(path, default=None):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return default


class Names:
    """User ids → names and bot flags, and the owner's id, from the fact store's users.json."""
    def __init__(self, slack_dir, env_file=None, user=None):
        doc = read_json(os.path.join(slack_dir, "users.json"), {}) or {}
        self.users, emails = doc.get("users") or {}, doc.get("emails") or {}
        self.channels = {c.get("id"): c.get("name") for c in (read_json(os.path.join(slack_dir, "channels.json"), {}) or {}).get("channels") or []}
        mail = os.environ.get("JIRA_EMAIL") or env_value(env_file, "JIRA_EMAIL")
        self.me = user or (emails.get(mail) or {}).get("id") or (next(iter(emails.values()))["id"] if len(emails) == 1 else None)

    def name(self, uid):
        return (self.users.get(uid) or {}).get("name") or uid or "a bot"

    def bot(self, uid):
        return not uid or bool((self.users.get(uid) or {}).get("is_bot"))

    def render(self, text):
        return html.unescape(re.sub(r"<@([A-Z0-9]+)(?:\|[^>]*)?>", lambda m: "@" + self.name(m.group(1)), text or ""))


def env_value(path, name):
    try:
        for line in open(path or "", encoding="utf-8"):
            k, sep, v = line.strip().partition("=")
            if sep and k.strip() == name and not line.lstrip().startswith("#"):
                return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def permalink(channel, ts, root=None):
    base = f"https://tvunetworks.slack.com/archives/{channel}/p{ts.replace('.', '')}"
    return base + (f"?thread_ts={root}&cid={channel}" if root and root != ts else "")


def parse_permalink(link):
    m = PERMALINK_RX.search(link or "")
    return (m.group(1), f"{m.group(2)}.{m.group(3)}", m.group(4)) if m else None


def first_line(text, n=140):
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


# ── threads, from the fact store or from Slack now ────────────────────────────────────────────────────────────
def store_threads(slack_dir, since=None):
    """(channel id, [root + replies]) for every thread in the store that moved since `since` (epoch seconds)."""
    for path in sorted(glob.glob(os.path.join(slack_dir, "[CG]*.json"))):
        doc = read_json(path, {}) or {}
        ch = os.path.basename(path)[:-5]
        for ts, root in sorted((doc.get("messages") or {}).items()):
            thread = [root] + (((doc.get("replies") or {}).get(ts) or {}).get("messages") or [])
            if since is None or max(float(m["ts"]) for m in thread) >= since:
                yield ch, thread, doc.get("messages") or {}


def store_thread(slack_dir, channel, root_ts):
    doc = read_json(os.path.join(slack_dir, f"{channel}.json"), {}) or {}
    root = (doc.get("messages") or {}).get(root_ts)
    if not root:
        for ts, rec in (doc.get("replies") or {}).items():   # the permalink of a reply given without its thread_ts
            if any(m.get("ts") == root_ts for m in rec.get("messages") or []):
                return [doc["messages"][ts]] + rec["messages"] if ts in (doc.get("messages") or {}) else None
        return None
    return [root] + (((doc.get("replies") or {}).get(root_ts) or {}).get("messages") or [])


def live_thread(env_file, channel, root_ts):
    sys.path.insert(0, os.path.join(HERE, "..", "slack"))
    import slack as S                                      # noqa: E402 — the one Slack reader; conversations.replies only
    return S.thread_messages(S.token(env_file), channel, root_ts)


def thread_of(r, channel, ts, root=None, fresh=False):
    msgs = live_thread(r["env"], channel, root or ts) if fresh else store_thread(r["slack"], channel, root or ts)
    if not msgs:
        print(f"{channel}/{root or ts}: not in the Slack fact store; --fresh reads it from Slack now", file=sys.stderr)
        sys.exit(EX_NOTFOUND)
    return msgs


# ── one thread into the store ─────────────────────────────────────────────────────────────────────────────────
def live(r):
    """Whether a later mention in the thread joins this record: he has not replied and nothing closed it."""
    return not r.get("replied_at") and r["state"] in OPEN + ("notice",)


def reacted(m, me):
    return any(me in (x.get("users") or []) for x in m.get("reactions") or [])


def process(recs, reports, channel, thread, names, day, now, since=None, top=None):
    """Walk one thread in time order: a message that mentions him opens a mention (or joins the open one), a message
    or a reaction of his after it is his reply. → the ids touched. `top`: the channel's top-level messages, where a
    reply of his outside the thread (one that tags the asker) also counts."""
    me, root_ts = names.me, thread[0]["ts"]
    tag = re.compile(r"<@" + re.escape(me) + r"(?:\|[^>]*)?>")
    known = {m["ts"]: rid for rid, r in recs.items() if r["channel"] == channel and r["thread_ts"] == root_ts for m in r["mentions"]}
    touched, cur = [], None
    for m in sorted(thread, key=lambda m: float(m["ts"])):
        ts, text = m["ts"], m.get("text") or ""
        if m.get("user") == me:
            if cur and not recs[cur].get("replied_at"):
                replied(recs, reports, cur, ts, text, "message", now); touched.append(cur)
            cur = None
            continue
        if not tag.search(text):
            continue
        if ts in known:
            r = recs[known[ts]]
            cur = known[ts] if live(r) else None
            if cur is None and r.get("replied_at") and r.get("reply_how") != "reaction" and not r.get("follow"):
                touched.append(known[ts])                  # replied on an earlier walk; its follow-through is still owed
            if cur and reacted(m, me):
                replied(recs, reports, cur, ts, "", "reaction", now); touched.append(cur); cur = None
            continue
        if since is not None and float(ts) < since:
            continue
        kind, reason = triage(text, me, names.bot(m.get("user")), names.channels.get(channel) or "")
        one = {"ts": ts, "by": m.get("user"), "triage": kind, "reason": reason}
        if cur:                                            # a second mention before he replied: the same wait
            r = recs[cur]
            r["mentions"].append(one)
            if RANK[kind] > RANK[r["triage"]]:               # a notice, then an ask: the wait starts at the ask
                due, hold = (now, False) if kind == "incident" else window(day, at_of(ts))
                r.update(triage=kind, reason=reason, state="incident" if kind == "incident" else "waiting", due_at=iso(due), hold=hold,
                         by=m.get("user"), by_name=names.name(m.get("user")), at=iso(at_of(ts)), first=first_line(names.render(text)),
                         permalink=permalink(channel, ts, root_ts))   # the record now reads as the message that asks
        else:
            cur = f"{channel}-{ts}"
            due, hold = (at_of(ts), False) if kind == "incident" else window(day, at_of(ts))
            recs[cur] = {"id": cur, "channel": channel, "channel_name": names.channels.get(channel) or channel, "thread_ts": root_ts,
                         "ts": ts, "permalink": permalink(channel, ts, root_ts), "by": m.get("user"), "by_name": names.name(m.get("user")),
                         "at": iso(at_of(ts)), "first": first_line(names.render(text)), "triage": kind, "reason": reason,
                         "mentions": [one], "state": {"notice": "notice", "incident": "incident"}.get(kind, "waiting"),
                         "due_at": None if kind == "notice" else iso(due), "hold": hold if kind == "ask" else False,
                         "recorded_at": iso(now)}
        log(reports, {"at": iso(now), "id": cur, "ts": ts, "triage": kind, "reason": reason, "why": REASONS[reason]})
        known[ts] = cur
        touched.append(cur)
        if reacted(m, me):
            replied(recs, reports, cur, ts, "", "reaction", now); cur = None
    if cur and top and len(thread) == 1:                   # he answered beside the message, not under it
        asker = recs[cur]["by"]
        for ts, m in sorted(top.items()):
            if m.get("user") == me and float(ts) > float(recs[cur]["ts"]) and asker and f"<@{asker}" in (m.get("text") or ""):
                replied(recs, reports, cur, ts, m.get("text") or "", "channel", now); touched.append(cur); break
    return list(dict.fromkeys(touched))


def replied(recs, reports, rid, ts, text, how, now):
    """His reply: the mention is closed for ela. A message waiting for his letter is withdrawn, without a word."""
    r = recs[rid]
    r.update(replied_at=iso(at_of(ts)), reply_ts=ts, reply_how=how,
             in_window=bool(r.get("due_at")) and at_of(ts) <= parse(r["due_at"]))
    if r["state"] == "drafted" and not r.get("answer"):
        r.update(state="withdrawn", withdrawn_at=iso(now))
        log(reports, {"at": iso(now), "id": rid, "reason": r["reason"], "outcome": "withdrawn"})
    elif r["state"] in ("waiting", "incident"):
        r["state"] = "replied"
    log(reports, {"at": iso(now), "id": rid, "reason": r["reason"], "outcome": "replied", "how": how})
    supersede(reports, r, f"the owner's own reply in the thread at {r['replied_at'][5:16].replace('T', ' ')} (mention {rid})", now)


# ── a closed mention withdraws what was drafted for its thread ────────────────────────────────────────────────
ACTION_DONE = ("applied", "by_owner", "vetoed", "failed", "dry_run", "superseded", "cancelled")


def supersede(reports, r, why, now):
    """Mark `superseded` ({by, at}) each drafted, unapplied Slack action in the runner's actions files that is aimed
    at this mention's thread: once the mention is closed, a reply drafted for the same thread would post twice. The
    file is read again and replaced whole, as the runner does. → [{file, n}], also kept on the record."""
    keys, out = {r["thread_ts"]} | {m["ts"] for m in r.get("mentions") or []}, []
    if not reports:
        return out
    for path in sorted(glob.glob(os.path.join(reports, "runner", "*-actions.json"))):
        acts = read_json(path)
        hit = []
        for a in acts if isinstance(acts, list) else []:
            cmd = a.get("command") or "" if isinstance(a, dict) else ""
            if not cmd or not (a.get("kind") == "slack" or " slack post " in f" {cmd}") or any(a.get(k) for k in ACTION_DONE):
                continue
            pl = parse_permalink(cmd)
            if pl and pl[0] == r["channel"] and {pl[1], pl[2]} & keys:
                a["superseded"] = {"by": why, "at": iso(now)}
                hit.append(a.get("n"))
        if hit:
            atomic_write(path, json.dumps(acts, ensure_ascii=False, indent=1))
            out += [{"file": os.path.basename(path), "n": n} for n in hit]
    if out:
        r.setdefault("superseded", []).extend(out)
    return out



# ── what is to do now ─────────────────────────────────────────────────────────────────────────────────────────
def todo(recs, day, now):
    """The runner's list, one entry a mention: `timer` (call `due` again at `at`), `draft` (a session writes the ask
    and the reply, then `ela mention draft`), `dm` (send him the text file, then `ela mention sent`), `today` (held:
    today.md shows it, nothing to send)."""
    out = []
    for r in sorted(recs.values(), key=lambda r: r["at"]):
        if r["state"] not in OPEN or r.get("replied_at") or r.get("answer") or r.get("dm_at"):
            continue
        base = {"id": r["id"], "permalink": r["permalink"], "triage": r["triage"]}
        if r["triage"] == "incident":
            out.append(dict(base, do="dm", kind="incident", text=r.get("draft")))
        elif r.get("hold") or (now >= parse(r["due_at"]) and not in_hours(day, now)):
            out.append(dict(base, do="today" if r.get("draft") else "draft", route="today"))
        elif now < parse(r["due_at"]):
            out.append(dict(base, do="timer", at=r["due_at"]))
        elif not r.get("draft"):
            out.append(dict(base, do="draft", route="dm"))
        else:
            out.append(dict(base, do="dm", kind="ask", text=r["draft"]))
    return out


def settle_hours(recs, day, now, reports=None):
    """A mention that fell due after his hours ended is held: it takes a slot on today.md instead of a message. One
    left open for EXPIRE_DAYS working days is closed as expired, kept on record."""
    for r in recs.values():
        if not r.get("replied_at") and (r["state"] in OPEN and not r.get("answer") or r["state"] == "answered" and r["answer"]["letter"] == "B"):
            d, n = parse(r["at"]).date(), 0
            while d < now.date():
                d += datetime.timedelta(days=1)
                n += working(day, d)
            if n > EXPIRE_DAYS:
                r.update(state="closed", closed={"at": iso(now), "why": f"expired: open {n} working days"})
                if reports:
                    log(reports, {"at": iso(now), "id": r["id"], "reason": r["reason"], "outcome": "expired"})
                continue
        if (r["state"] in ("waiting", "drafted") and not r.get("hold") and not r.get("dm_at") and not r.get("replied_at")
                and not r.get("answer") and now >= parse(r["due_at"]) and not in_hours(day, now)):
            r["hold"] = True


# ── facts ─────────────────────────────────────────────────────────────────────────────────────────────────────
def keys_in(text):
    out = []
    for k in KEY_RX.findall(text or ""):
        if k not in out:
            out.append(k)
    return out


def stored_issue(jira_dir, key):
    return read_json(os.path.join(jira_dir, f"{key}.json"))


def fixed_in(issue):
    v = (issue.get("fields") or {}).get("customfield_11252")
    return v if isinstance(v, str) and v.strip() else None


def related_threads(key, skip):
    """The threads the links index holds for a key, newest first, this one left out; [] when there is no index."""
    try:
        sys.path.insert(0, os.path.join(HERE, "..", "links"))
        import links as L                                  # noqa: E402 — the index's one reader
        path = L.roots()["store"]
        if not os.path.exists(path):
            return []
        return [t for t in reversed(L.lookup_key(L.connect(path), key)["threads"]) if skip not in (t.get("id") or "")]
    except Exception:                                      # noqa: BLE001 — the facts stand without the index
        return []


def gather(r, thread, names, issue, related=related_threads):
    """{keys: [{key, url, status, assignee, fixed_in, summary}], threads, gaps, lines (FACT_LINES at most, Slack links)}."""
    text = "\n".join(m.get("text") or "" for m in thread)
    out = {"keys": [], "threads": [], "gaps": [], "lines": [], "at": iso(datetime.datetime.now(TZ))}
    for k in keys_in(text):
        i = issue(k)
        if not i:
            out["gaps"].append(k); continue
        f = i.get("fields") or {}
        out["keys"].append({"key": k, "url": i.get("url"), "status": (f.get("status") or {}).get("name"),
                            "assignee": (f.get("assignee") or {}).get("displayName") or "unassigned",
                            "fixed_in": fixed_in(i), "summary": f.get("summary") or ""})
    seen = set()
    for k in [x["key"] for x in out["keys"]][:3]:
        for t in related(k, f"{r['channel']}/{r['thread_ts']}")[:2]:
            if t.get("link") and t["link"] not in seen:
                seen.add(t["link"])
                out["threads"].append({"key": k, "link": t["link"], "channel": t.get("channel"), "date": str(t.get("date") or "")[:10],
                                       "first": first_line(t.get("first") or "", 80)})
    for x in out["keys"][:3]:
        out["lines"].append(f"<{x['url']}|{x['key']}> {x['status']} · {x['assignee']}"
                            + (f" · Fixed In {x['fixed_in']}" if x["fixed_in"] else " · no Fixed In") + f" · {first_line(x['summary'], 60)}")
    for t in out["threads"][:FACT_LINES - len(out["lines"])]:
        out["lines"].append(f"<{t['link']}|#{t['channel']} {t['date'][5:]}> names {t['key']}: {t['first']}")
    more = len(out["keys"]) - 3
    if more > 0 and len(out["lines"]) < FACT_LINES:
        out["lines"].append(f"{more} more ticket{'s' if more > 1 else ''} named: " + ", ".join(f"<{x['url']}|{x['key']}>" for x in out["keys"][3:8]))
    if out["gaps"] and len(out["lines"]) < FACT_LINES:
        out["lines"].append("not read (not in the Jira fact store): " + ", ".join(out["gaps"][:6]))
    if not out["lines"]:
        out["lines"].append("The thread names no ticket.")
    out["lines"] = out["lines"][:FACT_LINES]
    return out


# ── the message for him ───────────────────────────────────────────────────────────────────────────────────────
def head(r, now):
    mins = int((now - parse(r["at"])).total_seconds() // 60)
    ago = f"{mins} min" if mins < 120 else f"{mins // 60} h"
    return f"*{r['by_name']} in #{r['channel_name']}* · <{r['permalink']}|{r['at'][5:16].replace('T', ' ')}> · {ago} ago"


def incident_text(r, facts, now):
    """A prod incident addressed to him: the facts at once, no reply drafted, no letters."""
    return "\n".join([head(r, now) + " · reads as a prod incident addressed to you", r["first"], "", "*Facts*"]
                     + [f"• {l}" for l in facts["lines"]] + ["", "No reply is drafted for an incident."]) + "\n"


def ask_text(r, facts, ask, reply, implied, now):
    L = [head(r, now) + " · no reply from you yet", ask.strip(), "", "*Facts*"] + [f"• {l}" for l in facts["lines"]]
    L += ["", "*Draft reply* (paste it yourself; ela posts nothing)", "```", reply.strip(), "```"]
    if implied:
        L += ["", "*Jira it implies* (dry runs by class, prepared on A or when you reply)"] + [f"• {x}" for x in implied]
    L += ["", "*A* use this draft · *B* I will write it · *C* nothing needed",
          "Reply with the letter. No answer: nothing happens; a reply of yours in the thread withdraws this."]
    return "\n".join(L) + "\n"


def make_draft(r, reports, ask, reply, now):
    """The message for him on an unanswered ask, written to the store (nothing is sent). → (path, text)."""
    r.update(ask=" ".join(ask.split()), reply=reply.strip(), implied=implied(reply, [x["key"] for x in r["facts"]["keys"]]))
    text = ask_text(r, r["facts"], r["ask"], reply, r["implied"], now)
    path = os.path.join(store(reports), "drafts", f"{r['id']}.txt")
    atomic_write(path, text)
    r.update(draft=path, drafted_at=iso(now), state="drafted")
    return path, text


def make_incident(r, reports, thread, names, issue, now, related=related_threads):
    """An incident's message: its facts, written to the store at once."""
    r["facts"] = gather(r, thread, names, issue, related)
    path = os.path.join(store(reports), "drafts", f"{r['id']}.txt")
    atomic_write(path, incident_text(r, r["facts"], now))
    r["draft"] = path
    return path


# ── follow-through: what his reply commits to, by action class ────────────────────────────────────────────────
# A commitment is a sentence of his that carries one of these verbs. Each maps to one class of `ela dry` (its
# closed vocabulary), or to a ticket draft; a sentence that promises something no class covers is listed in his
# words' place by a pointer and a few words, never acted on.
COMMIT = (
    ("link-named", re.compile(r'\blink(?:ed|ing|s)?\b|关联|链接到|链到|挂到|挂在', re.I)),
    ("parent-status", re.compile(r'\bupdat(?:e|ed|ing) (?:the )?(?:parent|umbrella|epic|status)\b|\bstatus (?:comment|update)\b|'
                                 r'更新(?:一下)?(?:父票|parent|umbrella|epic|状态|进度)|同步(?:一下)?(?:状态|进度)', re.I)),
    ("assign-by-rule", re.compile(r'\b(?:re)?assign(?:ed|ing)?\b|交给|分给|指派|转给|来负责|来跟进|\bplease take\b|\btakes? (?:it|this) over\b', re.I)),
    ("ticket-draft", re.compile(r'\b(?:file|open|create|raise|log)(?: a| an| the| one)? (?:new )?(?:ticket|bug|issue|jira)\b|'
                                r'[建开提](?:一?[个张])?(?:新)?(?:票|单|ticket|bug|jira)', re.I)),
)
PROMISE = re.compile(r"\bI(?:'ll| will| am going to)\b|\blet me\b|\bwill (?:check|look|follow|confirm|test|verify|ask|send|sync|add|fix)\b|"
                     r'我(?:来|会|去|再|稍后|晚点|回头)|稍后|回头', re.I)


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?。！？；;])\s+|\n+|(?<=[。！？；])", text or "") if s and s.strip()]


def commitments(text):
    """[{class, sentence, keys, users}] and the promises no class covers."""
    found, loose = [], []
    for s in sentences(text):
        hit = [c for c, rx in COMMIT if rx.search(s)]
        for c in hit:
            found.append({"class": c, "sentence": s, "keys": keys_in(s), "users": re.findall(r"<@([A-Z0-9]+)", s)})
        if not hit and PROMISE.search(s):
            loose.append(s)
    return found, loose


def implied(text, thread_keys):
    """The dry runs a drafted reply implies, in words, for the message to him (nothing is prepared yet)."""
    out = []
    for c in commitments(text)[0]:
        ks = c["keys"] or thread_keys[:1]
        out.append({"link-named": "links", "parent-status": "a status comment", "assign-by-rule": "an assignment",
                    "ticket-draft": "a ticket draft from this thread"}[c["class"]]
                   + (" · " + ", ".join(ks) if ks and c["class"] != "ticket-draft" else "") + f" ({c['class']})")
    return list(dict.fromkeys(out))


def dry_mod():
    sys.path.insert(0, os.path.join(HERE, "..", "dry"))
    import dry as D                                        # noqa: E402 — the classes' one reader and writer
    return D


def roster_email(uid, name):
    """The roster's email for a Slack user, None when the roster does not hold exactly one."""
    for q in (uid, name):
        try:
            p = subprocess.run(["python3", os.path.join(HERE, "..", "team", "team.py"), "who", q, "--json"], capture_output=True, text=True, timeout=30)
            d = json.loads(p.stdout or "{}")
            if d.get("count") == 1 and d["people"][0].get("email"):
                return d["people"][0]["email"]
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return None


def follow(r, text, thread_keys, ctx, source="reply"):
    """Prepare what `text` (his reply, or the draft he chose) commits to: one dry-run batch per class and parent through
    dry.py, a ticket draft file for "file a ticket", the rest listed. ctx: {reports, owner, read(key), who(uid, name),
    names, today, runtime}. → the record's `follow`."""
    D = dry_mod()
    found, loose = commitments(text)
    out = {"at": iso(datetime.datetime.now(TZ)), "source": source, "by_class": {}, "tickets": [], "unmapped": []}
    def words(s):
        return first_line(ctx["names"].render(s), 100)
    for c in found:
        cls, cand = c["class"], (c["keys"] or thread_keys)
        if cls in ("link-named", "parent-status"):
            mine = [(k, i) for k, i in ((k, ctx["read"](k)) for k in cand) if i and D.owns(i, ctx["owner"])]
            if not mine:
                out["unmapped"].append(f"{cls}: names no parent of yours ({words(c['sentence'])})"); continue
            for k, parent in mine:
                if cls == "link-named":
                    text_keys = keys_in(json.dumps((parent.get("fields") or {}).get("comment")) + json.dumps((parent.get("fields") or {}).get("description")))
                    kids = {x: i for x, i in ((x, ctx["read"](x)) for x in text_keys if x != k) if i}
                    writes, left = D.select_link_named(parent, kids)
                else:
                    writes, left = D.select_parent_status(parent, ctx["owner"], ctx["today"], os.path.join(ctx["runtime"], "dry", ctx["today"].isoformat()))
                b = D.make_batch(ctx["reports"], cls, k, writes, left, ctx["today"])
                out["by_class"].setdefault(cls, []).append({"key": k, "batch": b["id"] if b else None, "writes": len(writes), "left_out": left})
        elif cls == "assign-by-rule":
            who = next((u for u in c["users"] if u != ctx["names"].me), None)
            key = (c["keys"] or (thread_keys if len(thread_keys) == 1 else []) or [None])[0]
            mail = ctx["who"](who, ctx["names"].name(who)) if who else None
            if not (key and mail):
                out["unmapped"].append("assign: " + ("no ticket named" if not key else "no person named" if not who else
                                                     f"{ctx['names'].name(who)} is not in the roster") + f" ({words(c['sentence'])})"); continue
            w = [{"n": 1, "target": key, "command": f"ela jira assign {key} --assignee {mail}",
                  "why": f"your reply of {r.get('replied_at', '')[5:16].replace('T', ' ') or 'the draft'} names {ctx['names'].name(who)}"}]
            b = D.make_batch(ctx["reports"], cls, key, w, [], ctx["today"])
            out["by_class"].setdefault(cls, []).append({"key": key, "batch": b["id"] if b else None, "writes": 1, "left_out": []})
        else:                                              # a ticket is filed on his word only: the draft waits for it
            path = os.path.join(store(ctx["reports"]), "tickets", f"{r['id']}.md")
            if not os.path.exists(path):
                atomic_write(path, "\n".join([f"# Ticket draft from {r['by_name']}'s thread in #{r['channel_name']}", "",
                                              f"- thread: {r['permalink']}", f"- tickets it names: {', '.join(thread_keys) or 'none'}",
                                              "- summary: (a session writes it from the thread)", "- description: (what was reported, what was confirmed, what done looks like)",
                                              "", "Filed only on the owner's word: `ela jira create … --apply`."]) + "\n")
            out["tickets"].append(path)
    out["unmapped"] += [f"no class covers: {words(s)}" for s in loose]
    r["follow"] = out
    return out


def follow_lines(f):
    L = []
    for cls, rows in (f.get("by_class") or {}).items():
        for x in rows:
            L.append(f"  {cls}: {x['key']} — " + (f"{x['writes']} dry run(s), batch {x['batch']}" if x["batch"] else
                                                   "nothing to write" + (f" ({'; '.join(x['left_out'])})" if x["left_out"] else "")))
    L += [f"  ticket draft: {p}" for p in f.get("tickets") or []]
    L += [f"  not acted on — {u}" for u in f.get("unmapped") or []]
    return L


def context(r_, names):
    D = dry_mod()
    cache = {}
    def read(k):
        if k not in cache:
            cache[k] = stored_issue(r_["jira"], k) or D.read_issue(k, r_["env"])
        return cache[k]
    return {"reports": r_["reports"], "owner": D.owner_of(None, r_["env"]), "read": read, "who": roster_email, "names": names,
            "today": datetime.datetime.now(TZ).date(), "runtime": r_["runtime"]}


def site_context(reports):
    """The follow-through's readers on this machine, for a caller that holds only the reports root (the vault's sync)."""
    r_ = dict(roots(), reports=reports)
    return context(r_, Names(r_["slack"], r_["env"]))


def follow_replies(recs, ids, r_, names, threads, ctx=None):
    """After a walk: each mention he has just replied to gets its follow-through, once."""
    for rid in ids:
        r = recs[rid]
        if r.get("replied_at") and r.get("reply_how") != "reaction" and not (r.get("follow") or {}).get("source") == "reply":
            thread = threads.get((r["channel"], r["thread_ts"])) or []
            text = next((m.get("text") or "" for m in thread if m["ts"] == r.get("reply_ts")), "")
            if not text and r.get("reply_how") == "channel":
                text = ((read_json(os.path.join(r_["slack"], f"{r['channel']}.json"), {}) or {}).get("messages") or {}).get(r["reply_ts"], {}).get("text") or ""
            follow(r, text, keys_in("\n".join(m.get("text") or "" for m in thread)), ctx or context(r_, names))


# ── renderings for the vault ──────────────────────────────────────────────────────────────────────────────────
def note_rel(rid):
    return f"ela/mentions/{rid}"


def asks(reports, now=None):
    """The mentions that take an ordinary ask slot on today.md: an ask held outside his hours, unanswered. The options
    are his: A use this draft (when a session has drafted one) · B I will write it · C nothing needed."""
    out = []
    for r in sorted(load(reports).values(), key=lambda r: r["at"]):
        if r["triage"] != "ask" or r["state"] not in ("waiting", "drafted") or not r.get("hold") or r.get("replied_at") or r.get("answer") or r.get("dm_at"):
            continue
        aid = f"mention:{r['id']}"
        opts = ([{"letter": "A", "text": "use this draft", "does": f"ela mention answer {r['id']} A", "recommended": True}] if r.get("draft") else []) + [
            {"letter": "B", "text": "I will write it", "does": f"ela mention answer {r['id']} B", "recommended": False},
            {"letter": "C", "text": "nothing needed", "does": f"ela mention answer {r['id']} C", "recommended": False}]
        out.append({"id": aid, "question": f"{r['by_name']} asked you in #{r['channel_name']} on {r['at'][5:16].replace('T', ' ')}, no reply yet: "
                                           f"{r.get('ask') or r['first']}", "link": note_rel(r["id"]), "options": opts,
                    "sig": f"{r['id']}:{'drafted' if r.get('draft') else 'bare'}"})
    return out


def md_links(line):
    return re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"[\2](\1)", line)


def page(r):
    """ela/mentions/<id>.md, what a today.md ask links: the ask, the facts, the reply to paste."""
    f = r.get("facts") or {"lines": []}
    L = [f"# {r['by_name']} in #{r['channel_name']} · {r['at'][:10]}", "", f"[The thread]({r['permalink']}) · {r['at'][5:16].replace('T', ' ')} · "
         f"triaged as an {r['triage']} ({REASONS[r['reason']]})", "", r.get("ask") or r["first"], "", "## Facts", ""]
    L += [f"- {md_links(l)}" for l in f["lines"]] + [""]
    if r.get("reply"):
        L += ["## Draft reply", "", "Paste it yourself; ela posts nothing.", "", "```", r["reply"].strip(), "```", ""]
    if r.get("implied"):
        L += ["## Jira it implies", ""] + [f"- {x}" for x in r["implied"]] + [""]
    return "\n".join(L).rstrip("\n") + "\n"


def waiting(reports):
    """The open asks and incidents, oldest first, one line each for a meeting note's Waiting on you."""
    out = []
    for r in sorted(load(reports).values(), key=lambda r: r["at"]):
        letter = (r.get("answer") or {}).get("letter")
        if r["triage"] == "notice" or r.get("replied_at") or not (r["state"] in OPEN and not letter or r["state"] == "answered" and letter == "B"):
            continue                                       # B: the reply is his to write, and is not there yet
        keys = [x for x in (r.get("facts") or {}).get("keys") or []][:3]
        out.append({"id": r["id"], "line": f"**{r['by_name']}, {r['at'][5:10]}** ([thread]({r['permalink']})"
                                           + "".join(f", [{x['key']}]({x['url']})" for x in keys) + f"): {r.get('ask') or r['first']}"})
    return out


def tally(reports):
    by = {}
    for row in read_log(reports):
        t = by.setdefault(row.get("reason") or "?", {"kind": KIND_OF.get(row.get("reason")), "fired": 0, "replied": 0, "withdrawn": 0, "A": 0, "B": 0, "C": 0, "closed": 0, "expired": 0})
        if row.get("outcome"):
            t[row["outcome"]] = t.get(row["outcome"], 0) + 1
        else:
            t["fired"] += 1
    return by


# ── the answer ────────────────────────────────────────────────────────────────────────────────────────────────
def answer(reports, ref, letter, ctx=None, now=None):
    """His letter on a mention's ask. A: the draft is his to paste, and what it commits to is prepared by class. B: he
    writes it. C: nothing was needed; closed, and counted against the triage reason. Raises KeyError, ValueError."""
    recs, now = load(reports), now or datetime.datetime.now(TZ)
    rid = ref if ref in recs else next((k for k, r in recs.items() if r.get("dm_ts") == ref), None)
    if rid is None:
        raise KeyError(ref)
    r, letter = recs[rid], letter.upper()
    if r["state"] == "withdrawn" or r.get("replied_at"):
        raise ValueError(f"{rid}: withdrawn, he replied in the thread at {r.get('replied_at')}")
    if r.get("answer"):
        raise ValueError(f"{rid}: already answered {r['answer']['letter']}")
    if letter == "A" and not r.get("draft"):
        raise ValueError(f"{rid}: no draft to use; B or C")
    r["answer"] = {"letter": letter, "at": iso(now)}
    if letter == "C":
        r.update(state="closed", closed={"at": iso(now), "why": "nothing needed (his C)"})
        supersede(reports, r, f"the owner's C on mention {rid}: nothing needed", now)
    else:
        r["state"] = "answered"
        if letter == "A" and ctx:
            ctx = ctx() if callable(ctx) else ctx
            follow(r, r.get("reply") or "", [x["key"] for x in (r.get("facts") or {}).get("keys") or []], ctx, source="draft")
    log(reports, {"at": iso(now), "id": rid, "reason": r["reason"], "outcome": letter})
    save(reports, recs)
    return r


# ── verbs ─────────────────────────────────────────────────────────────────────────────────────────────────────
def emit(a, obj, lines):
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str) if getattr(a, "json", False) else "\n".join(lines))


def now_of(a):
    return parse(a.now).astimezone(TZ) if getattr(a, "now", None) else datetime.datetime.now(TZ)


def setup(a):
    r_ = roots(a)
    names = Names(r_["slack"], r_["env"], getattr(a, "user", None))
    if not names.me:
        print("the owner's Slack id is not in the fact store (users.json): run `ela slack whoami`, or pass --user", file=sys.stderr)
        sys.exit(EX_USAGE)
    return r_, names, day_settings(), now_of(a)


def line_of(r):
    what = {"notice": f"notice ({r['reason']})", "waiting": f"waiting, due {(r.get('due_at') or '')[5:16].replace('T', ' ')}" + (" · held for today.md" if r.get("hold") else ""),
            "incident": "incident: facts at once", "drafted": "drafted" + (", sent" if r.get("dm_at") else ""),
            "replied": f"he replied {r.get('replied_at', '')[5:16].replace('T', ' ')}", "withdrawn": "draft withdrawn: he replied",
            "answered": f"answered {(r.get('answer') or {}).get('letter')}", "closed": f"closed: {(r.get('closed') or {}).get('why')}"}[r["state"]]
    return f"{r['id']}  #{r['channel_name']}  {r['at'][5:16].replace('T', ' ')}  {r['by_name']}: {r['triage']} ({r['reason']}) · {what}"


def run(a, pairs, r_, names, day, now, since=None, tops=None):
    """Walk the given threads, save, prepare the incidents' facts and the replies' follow-through, print what is to do."""
    recs = load(r_["reports"])
    threads, touched = {}, []
    for ch, thread in pairs:
        threads[(ch, thread[0]["ts"])] = thread
        touched += process(recs, r_["reports"], ch, thread, names, day, now, since, (tops or {}).get(ch))
    settle_hours(recs, day, now, r_["reports"])
    for rid in touched:
        r = recs[rid]
        if r["state"] == "incident" and not r.get("draft"):
            make_incident(r, r_["reports"], threads[(r["channel"], r["thread_ts"])], names, lambda k: stored_issue(r_["jira"], k), now)
    follow_replies(recs, touched, r_, names, threads)
    save(r_["reports"], recs)
    do = todo(recs, day, now)
    emit(a, {"now": iso(now), "touched": [recs[x] for x in dict.fromkeys(touched)], "do": do},
         [l for x in dict.fromkeys(touched) for l in [line_of(recs[x])] + follow_lines(recs[x].get("follow") or {})]
         + [f"to do: {d['do']} {d['id']}" + (f" at {d['at'][5:16].replace('T', ' ')}" if d.get("at") else "") + (f" → {d['text']}" if d.get("text") else "") for d in do]
         or ["nothing new"])


def cmd_scan(a):
    r_, names, day, now = setup(a)
    m = re.fullmatch(r"(\d+)([hd])", a.since)
    if not m:
        print("--since takes 24h or 7d", file=sys.stderr); sys.exit(EX_USAGE)
    since = (now - datetime.timedelta(**{"hours" if m.group(2) == "h" else "days": int(m.group(1))})).timestamp()
    pairs, tops = [], {}
    for ch, thread, top in store_threads(r_["slack"], since):
        pairs.append((ch, thread)); tops[ch] = top
    run(a, pairs, r_, names, day, now, since, tops)


def cmd_note(a):
    r_, names, day, now = setup(a)
    pl = parse_permalink(a.permalink)
    if not pl:
        print("not a Slack permalink", file=sys.stderr); sys.exit(EX_USAGE)
    run(a, [(pl[0], thread_of(r_, pl[0], pl[1], pl[2], a.fresh))], r_, names, day, now)


def cmd_due(a):
    r_ = roots(a)
    recs, day, now = load(r_["reports"]), day_settings(), now_of(a)
    settle_hours(recs, day, now, r_["reports"])
    save(r_["reports"], recs)
    do = todo(recs, day, now)
    emit(a, {"now": iso(now), "do": do}, [f"{d['do']:6} {d['id']}  {d['permalink']}" + (f"  at {d['at']}" if d.get("at") else "")
                                           + (f"  {d['text']}" if d.get("text") else "") for d in do] or ["nothing is due"])


def find(recs, ref):
    if ref in recs:
        return recs[ref]
    pl = parse_permalink(ref)
    if pl:
        for r in recs.values():
            if r["channel"] == pl[0] and (any(m["ts"] == pl[1] for m in r["mentions"]) or r["thread_ts"] == pl[1]):
                return r
    print(f"{ref}: no mention on record (`ela mention note <permalink>` records one)", file=sys.stderr); sys.exit(EX_NOTFOUND)


def cmd_list(a):
    recs = load(roots(a)["reports"])
    rows = [r for r in sorted(recs.values(), key=lambda r: r["at"]) if a.all or r["state"] in OPEN]
    emit(a, rows, [line_of(r) for r in rows] or ["no open mention"])


def cmd_show(a):
    r = find(load(roots(a)["reports"]), a.ref)
    L = [line_of(r), f"  {r['permalink']}", f"  {r['first']}", f"  triage: {r['triage']} — {REASONS[r['reason']]}"]
    L += [f"  fact: {l}" for l in (r.get("facts") or {}).get("lines") or []]
    L += [f"  draft: {r['draft']}"] if r.get("draft") else []
    L += follow_lines(r["follow"]) if r.get("follow") else []
    emit(a, r, L)


def cmd_triage(a):
    r_, names, _, _ = setup(a)
    pl = parse_permalink(a.permalink)
    if not pl:
        print("not a Slack permalink", file=sys.stderr); sys.exit(EX_USAGE)
    m = next((m for m in thread_of(r_, pl[0], pl[1], pl[2], a.fresh) if m["ts"] == pl[1]), None)
    if not m or f"<@{names.me}" not in (m.get("text") or ""):
        print("that message does not mention him", file=sys.stderr); sys.exit(EX_NOTFOUND)
    kind, reason = triage(m.get("text"), names.me, names.bot(m.get("user")), names.channels.get(pl[0]) or "")
    emit(a, {"triage": kind, "reason": reason, "why": REASONS[reason]}, [f"{kind} ({reason}): {REASONS[reason]}"])


def cmd_facts(a):
    r_ = roots(a)
    recs = load(r_["reports"])
    r = find(recs, a.ref)
    names = Names(r_["slack"], r_["env"])
    r["facts"] = gather(r, thread_of(r_, r["channel"], r["thread_ts"], None, a.fresh), names, lambda k: stored_issue(r_["jira"], k))
    save(r_["reports"], recs)
    emit(a, r["facts"], r["facts"]["lines"])


def cmd_draft(a):
    r_ = roots(a)
    recs, now = load(r_["reports"]), now_of(a)
    r = find(recs, a.ref)
    if r["triage"] != "ask" or r.get("replied_at") or r["state"] not in ("waiting", "drafted"):
        print(f"{r['id']}: no draft is owed ({line_of(r)})", file=sys.stderr); sys.exit(EX_USAGE)
    try:
        reply = open(a.reply_file, encoding="utf-8").read()
    except OSError as e:
        print(f"--reply-file: {e}", file=sys.stderr); sys.exit(EX_USAGE)
    if not r.get("facts"):
        r["facts"] = gather(r, thread_of(r_, r["channel"], r["thread_ts"], None, a.fresh), Names(r_["slack"], r_["env"]), lambda k: stored_issue(r_["jira"], k))
    path, text = make_draft(r, r_["reports"], a.ask, reply, now)
    save(r_["reports"], recs)
    emit(a, {"id": r["id"], "draft": path, "hold": bool(r.get("hold")), "text": text}, [text, f"# written to {path}; nothing was sent"])


def cmd_sent(a):
    r_ = roots(a)
    recs = load(r_["reports"])
    r = find(recs, a.ref)
    r.update(dm_at=iso(now_of(a)), dm_ts=a.ts)
    save(r_["reports"], recs)
    print(f"{r['id']}: the message to him is recorded" + (f" ({a.ts})" if a.ts else ""))


def cmd_answer(a):
    r_ = roots(a)
    try:
        r = answer(r_["reports"], a.ref, a.letter, context(r_, Names(r_["slack"], r_["env"])), now_of(a))
    except KeyError:
        print(f"{a.ref}: no mention on record", file=sys.stderr); sys.exit(EX_NOTFOUND)
    except ValueError as e:
        print(str(e), file=sys.stderr); sys.exit(EX_USAGE)
    emit(a, r, [line_of(r)] + follow_lines(r.get("follow") or {}))


def cmd_follow(a):
    r_ = roots(a)
    recs = load(r_["reports"])
    r = find(recs, a.ref)
    if not r.get("replied_at") or r.get("reply_how") == "reaction":
        print(f"{r['id']}: no reply of his in words to read", file=sys.stderr); sys.exit(EX_USAGE)
    names = Names(r_["slack"], r_["env"])
    thread = thread_of(r_, r["channel"], r["thread_ts"], None, a.fresh)
    r.pop("follow", None)
    follow_replies(recs, [r["id"]], r_, names, {(r["channel"], r["thread_ts"]): thread})
    save(r_["reports"], recs)
    emit(a, r.get("follow"), [line_of(r)] + (follow_lines(r.get("follow") or {}) or ["  his reply commits to nothing ela prepares"]))


def cmd_close(a):
    r_ = roots(a)
    recs, now = load(r_["reports"]), now_of(a)
    r = find(recs, a.ref)
    r.update(state="closed", closed={"at": iso(now), "why": a.why or "his word"})
    log(r_["reports"], {"at": iso(now), "id": r["id"], "reason": r["reason"], "outcome": "closed"})
    supersede(r_["reports"], r, f"mention {r['id']} closed on the owner's word" + (f": {a.why}" if a.why else ""), now)
    save(r_["reports"], recs)
    print(line_of(r))


def cmd_supersede(a):
    r_ = roots(a)
    recs, now = load(r_["reports"]), now_of(a)
    r = find(recs, a.ref)
    got = supersede(r_["reports"], r, a.why or f"mention {r['id']} is closed ({line_of(r).rsplit(' · ', 1)[-1]})", now)
    save(r_["reports"], recs)
    emit(a, {"id": r["id"], "thread": f"{r['channel']}/{r['thread_ts']}", "superseded": got},
         [f"{x['file']} action {x['n']}: superseded" for x in got] or ["no drafted Slack action is aimed at that thread"])


def cmd_asks(a):
    got = asks(roots(a)["reports"])
    emit(a, got, [f"{x['id']}: {x['question']}\n  " + " · ".join(f"{o['letter']} {o['text']}" for o in x["options"]) for x in got] or ["no mention is held for today.md"])


def cmd_waiting(a):
    got = waiting(roots(a)["reports"])
    emit(a, got, [f"- {x['line']}" for x in got] or ["nothing waits on him"])


def cmd_tally(a):
    by = tally(roots(a)["reports"])
    emit(a, by, [f"{k:13} {v['kind'] or '?':8} fired {v['fired']:3} · he replied {v['replied']} · A {v['A']} · B {v['B']} · C {v['C']} (miss) · withdrawn {v['withdrawn']}"
                 for k, v in sorted(by.items())] or ["no triage on record"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file"); ap.add_argument("--reports", help="the reports root (default: site.json)")
    ap.add_argument("--slack-dir", help="the Slack fact store (default: <runtime>/facts/slack)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    def verb(name, func, *args, json_=True, now=False):
        s = sub.add_parser(name)
        for x in args:
            s.add_argument(x) if isinstance(x, str) else s.add_argument(*x[0], **x[1])
        if json_:
            s.add_argument("--json", action="store_true")
        if now:
            s.add_argument("--now", help="an ISO time read as now (a replay)")
        s.set_defaults(func=func)
    fresh = (("--fresh",), {"action": "store_true", "help": "read the thread from Slack now"})
    user = (("--user",), {"help": "his Slack id (default: the fact store's)"})
    verb("scan", cmd_scan, (("--since",), {"default": "24h"}), user, now=True)
    verb("note", cmd_note, "permalink", fresh, user, now=True)
    verb("due", cmd_due, now=True)
    verb("list", cmd_list, (("--all",), {"action": "store_true"}))
    verb("show", cmd_show, "ref")
    verb("triage", cmd_triage, "permalink", fresh, user)
    verb("facts", cmd_facts, "ref", fresh)
    verb("draft", cmd_draft, "ref", (("--ask",), {"required": True}), (("--reply-file",), {"required": True}), fresh, now=True)
    verb("sent", cmd_sent, "ref", (("--ts",), {}), json_=False, now=True)
    verb("answer", cmd_answer, "ref", (("letter",), {"choices": list("ABCabc")}), now=True)
    verb("follow", cmd_follow, "ref", fresh)
    verb("supersede", cmd_supersede, "ref", (("--why",), {}), now=True)
    verb("close", cmd_close, "ref", (("--why",), {}), json_=False, now=True)
    verb("asks", cmd_asks)
    verb("waiting", cmd_waiting)
    verb("tally", cmd_tally)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
