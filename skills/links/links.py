#!/usr/bin/env python3
"""The links index: the edges between what the fact store already holds, so the history around a ticket, a thread or
a build is one lookup. Derived and rebuildable; no second copy of content.

  links.py show <KEY|thread permalink|build> [--json]   one screen, grouped; every line carries its source pointer
  links.py update [--json]                               re-read the origins that changed since the last build
  links.py rebuild [--json]                              drop the index and read every origin whole
  links.py status [--json]                               the index's age, size and counts per kind

The store is `<runtime>/links/links.db` (sqlite). An edge is (from, to, kind, source pointer, date) with a short
qualifier (the link's wording, the service's version step); a node holds a label of one line at most (a ticket's
summary and status, a thread's channel, first line and reply count). Nothing else is copied.

What is read, all mechanical, only MH-related (an edge is kept when one end is an MH key, or it comes from a thread,
mail or ticket that names one):

  jira     facts/jira/issues/*.json and changes.json: issue links, parent and sub-tasks (kind `link`, `parent`), a key
           named in the description or a comment (`names`, from the naming ticket, the comment's link and date), a
           Slack permalink in the ticket (`slack-ref`, ticket → thread)
  slack    facts/slack/<channel>.json: a thread (or a lone message) that names a key (`thread-names`, the first
           message naming it); a message in such a thread that says a deploy happened (`deploy`, thread → message)
  mail     facts/mail/messages/*.json: a mail whose subject or body names a key (`mail-names`)
  builds   <reports>/releases/<line>/*-build-*.json, the build records: a build that carries a key (`carries`,
           the service and version step as the qualifier)
  lanes    <reports>/train/<line>.json, the fixed-in evidence the train already computed: a lane the fix reached
           (`reached`, key → lane; arrived, since, verdict), never recomputed here
  vault    projects/, meetings/, releases/, cases/ in the owner's vault (`in-note`), and the open-questions records
           <reports>/ela/questions.json (`question`)
  writes   <reports>/ela/writes.jsonl (`wrote`, write → key): when, what, who and on whose word. A row written
           before writes carried `session`/`job`/`action`/`word` is attributed from the runner's actions files when
           an applied action matches it (same key and verb, within two minutes); otherwise its attribution is unknown

The index is updated after every `ela facts refresh` (an origin whose files did not change is not re-read) and
rebuilt whole by `rebuild`. It makes no claim about cause: "named in the same thread" is not "fixed by".

Exit codes: 0 ok · 2 usage · 3 not in the index.
Brief: <runtime>/drafts/2026-11-12-links-index-brief.md.
"""
import argparse, datetime, glob, hashlib, json, os, re, sqlite3, sys, time

HERE = os.path.dirname(os.path.realpath(__file__))
SITE = os.path.expanduser("~/.claude/ela/site.json")
EX_USAGE, EX_NOTFOUND = 2, 3
KEY_RX = re.compile(r"(?<![A-Za-z0-9_-])([A-Z][A-Z0-9]{1,9})-(\d{1,6})(?![0-9])")
PERMALINK_RX = re.compile(r"https://[a-z0-9-]+\.slack\.com/archives/([A-Z0-9]+)/p(\d{10})(\d{6})(?:\?[^\s>|\"'\\)]*)?")
THREAD_TS_RX = re.compile(r"thread_ts=(\d+\.\d+)")
# a deploy said done: the words the team's deploy replies use (MH-3870's thread, 2026-11-04); vocabulary, not speech
DEPLOY_RX = re.compile(r'(部署了|已部署|部署完成|部署完毕|已上线|上线了|升级前|\bdeployed\b|\bdeployment (?:is )?done\b|\brolled out\b)', re.I)
VAULT_DIRS = ("projects", "meetings", "releases", "cases")
WRITE_MATCH_S = 120
SCHEMA = """
CREATE TABLE IF NOT EXISTS edges (src TEXT NOT NULL, dst TEXT NOT NULL, kind TEXT NOT NULL, source TEXT, at TEXT,
                                  note TEXT, origin TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst);
CREATE INDEX IF NOT EXISTS edges_origin ON edges(origin);
CREATE TABLE IF NOT EXISTS nodes (id TEXT NOT NULL, kind TEXT, label TEXT, meta TEXT, origin TEXT NOT NULL,
                                  PRIMARY KEY (id, origin));
CREATE INDEX IF NOT EXISTS nodes_origin ON nodes(origin);
CREATE TABLE IF NOT EXISTS origins (origin TEXT PRIMARY KEY, sig TEXT, at TEXT, seconds REAL);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


# ── roots ────────────────────────────────────────────────────────────────────────────────────────────

def site():
    try:
        return json.load(open(SITE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def roots():
    """{runtime, facts, reports, vault, store}: ELA_LINKS_* override each (the tests' fixtures)."""
    s = site()
    runtime = os.path.expanduser(os.environ.get("ELA_FACTS_RUNTIME") or s.get("runtime")
                                 or os.path.join(s.get("projects") or os.getcwd(), ".ela"))
    reports = os.path.expanduser(os.environ.get("ELA_LINKS_REPORTS") or s.get("reports")
                                 or os.path.join(s.get("projects") or "", "reports"))
    vault = os.environ.get("ELA_LINKS_VAULT", s.get("vault") or "")
    return {"runtime": runtime, "facts": os.path.join(runtime, "facts"), "reports": reports,
            "vault": os.path.expanduser(vault) if vault else "",
            "store": os.environ.get("ELA_LINKS_STORE") or os.path.join(runtime, "links", "links.db")}


def now():
    return datetime.datetime.now().astimezone()


def now_iso():
    return now().isoformat(timespec="seconds")


def read_json(path, default=None):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return default


def first_line(text, n=100):
    t = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"\2", str(text or ""))
    t = re.sub(r"<@[A-Z0-9]+>", "@", t)
    t = re.sub(r"<(https?://[^>]+)>", r"\1", t)
    t = next((l.strip(" *_>•-") for l in t.splitlines() if l.strip(" *_>•-")), "")
    return t if len(t) <= n else t[:n - 1] + "…"


# ── keys ─────────────────────────────────────────────────────────────────────────────────────────────

class Keys:
    """The key shape restricted to Jira's project keys (facts/jira/projects.json), so `UTF-8` or `H-264` is not one."""

    def __init__(self, facts):
        pj = read_json(os.path.join(facts, "jira", "projects.json"), {}) or {}
        self.projects = {p.get("key") for p in pj.get("projects") or [] if p.get("key")} or set()
        if not self.projects:                               # no project list read yet: the keys the cache holds
            self.projects = {f.split("-")[0] for f in os.listdir(os.path.join(facts, "jira", "issues"))
                             if f.endswith(".json")} if os.path.isdir(os.path.join(facts, "jira", "issues")) else set()
            self.projects |= {"MH", "UR"}

    def find(self, text):
        out = []
        for p, n in KEY_RX.findall(str(text or "")):
            k = f"{p}-{int(n)}" if not n.startswith("0") else None   # a leading zero is not a key (MH-0123)
            if k and p in self.projects and k not in out:
                out.append(k)
        return out


def is_mh(k):
    return k.startswith("MH-")


def thread_id(channel, ts):
    return f"slack:{channel}/{ts}"


def permalink(channel, ts, parent=None, domain="tvunetworks"):
    link = f"https://{domain}.slack.com/archives/{channel}/p{ts.replace('.', '')}"
    return link + (f"?thread_ts={parent}&cid={channel}" if parent and parent != ts else "")


def parse_permalink(text):
    """A Slack permalink → (channel, ts, thread_ts or None)."""
    m = PERMALINK_RX.search(text or "")
    if not m:
        return None
    t = THREAD_TS_RX.search(m.group(0))
    return m.group(1), f"{m.group(2)}.{m.group(3)}", t.group(1) if t else None


def ts_date(ts):
    try:
        return datetime.datetime.fromtimestamp(float(ts)).astimezone().isoformat(timespec="minutes")
    except (TypeError, ValueError):
        return None


# ── the store ────────────────────────────────────────────────────────────────────────────────────────

def connect(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


class Batch:
    """The edges and nodes one origin yields; written in one transaction that first drops the origin's old rows."""

    def __init__(self, origin):
        self.origin, self.edges, self.nodes = origin, [], {}

    def edge(self, src, dst, kind, source=None, at=None, note=None):
        if src and dst and src != dst:
            self.edges.append((src, dst, kind, source, at, note, self.origin))

    def node(self, nid, kind, label=None, **meta):
        old = self.nodes.get(nid)
        if old and not label:
            return
        self.nodes[nid] = (nid, kind, label, json.dumps(meta, ensure_ascii=False) if meta else None, self.origin)


def save(db, batch, sig, seconds):
    with db:
        db.execute("DELETE FROM edges WHERE origin = ?", (batch.origin,))
        db.execute("DELETE FROM nodes WHERE origin = ?", (batch.origin,))
        db.executemany("INSERT INTO edges VALUES (?,?,?,?,?,?,?)", list(dict.fromkeys(batch.edges)))
        db.executemany("INSERT OR REPLACE INTO nodes VALUES (?,?,?,?,?)", batch.nodes.values())
        db.execute("INSERT OR REPLACE INTO origins VALUES (?,?,?,?)", (batch.origin, sig, now_iso(), round(seconds, 2)))


def signature(paths):
    """What decides whether an origin is re-read: every file's size and mtime."""
    parts = []
    for p in sorted(paths):
        try:
            st = os.stat(p)
            parts.append(f"{p}:{st.st_size}:{int(st.st_mtime)}")
        except OSError:
            pass
    return hashlib.sha1("\n".join(parts).encode()).hexdigest()[:16] + f":{len(parts)}"


# ── origins: jira ────────────────────────────────────────────────────────────────────────────────────

def jira_issues(facts):
    """Every issue the store holds, one per key, the most recently updated copy."""
    d = os.path.join(facts, "jira")
    best = {}
    for i in read_json(os.path.join(d, "changes.json"), []) or []:
        if i.get("key"):
            best[i["key"]] = i
    for p in glob.glob(os.path.join(d, "issues", "*.json")):
        i = read_json(p)
        if not i or not i.get("key"):
            continue
        cur = best.get(i["key"])
        if cur is None or str((i.get("fields") or {}).get("updated") or "") >= str((cur.get("fields") or {}).get("updated") or ""):
            best[i["key"]] = i
    return best


def issue_comments(i):
    f = i.get("fields") or {}
    return i.get("comments") or (f.get("comment") or {}).get("comments") or []


def jira_iso(s):
    """Jira's `2026-11-02T18:44:06.456-0800` → ISO in local time, minutes."""
    try:
        t = datetime.datetime.strptime(str(s)[:19] + str(s)[23:], "%Y-%m-%dT%H:%M:%S%z")
        return t.astimezone().isoformat(timespec="minutes")
    except (TypeError, ValueError):
        return None


def read_jira(facts, keys, b):
    for k, i in jira_issues(facts).items():
        f = i.get("fields") or {}
        url = i.get("url") or f"https://tvunetworks.atlassian.net/browse/{k}"
        base = url.split("/browse/")[0]
        mh = is_mh(k)
        b.node(k, "ticket", first_line(f.get("summary"), 120), status=(f.get("status") or {}).get("name"), url=url,
               assignee=(f.get("assignee") or {}).get("displayName"))
        for l in f.get("issuelinks") or []:
            o = l.get("outwardIssue") or l.get("inwardIssue") or {}
            t = l.get("type") or {}
            if o.get("key") and (mh or is_mh(o["key"])):
                reads, back = (t.get("outward"), t.get("inward")) if l.get("outwardIssue") else (t.get("inward"), t.get("outward"))
                b.edge(k, o["key"], "link", url, None, f"{reads}\t{back}")   # read from this end, then from the other
                b.node(o["key"], "ticket", first_line((o.get("fields") or {}).get("summary"), 120),
                       status=((o.get("fields") or {}).get("status") or {}).get("name"), url=f"{base}/browse/{o['key']}")
        par = (f.get("parent") or {}).get("key")
        if par and (mh or is_mh(par)):
            b.edge(k, par, "parent", url, None, "sub-task of")
        for s in f.get("subtasks") or []:
            if s.get("key") and (mh or is_mh(s["key"])):
                b.edge(s["key"], k, "parent", url, None, "sub-task of")
        texts = [(url, jira_iso(f.get("created")), (f.get("reporter") or {}).get("displayName"), "description",
                  json.dumps(f.get("description"), ensure_ascii=False))]
        for c in issue_comments(i):
            texts.append((f"{url}?focusedCommentId={c.get('id')}", jira_iso(c.get("created")),
                          (c.get("author") or {}).get("displayName"), "comment",
                          json.dumps(c.get("body"), ensure_ascii=False)))
        for src, at, who, where, text in texts:
            named = [x for x in keys.find(text) if x != k]
            if mh or any(is_mh(x) for x in named):
                for x in named:
                    b.edge(k, x, "names", src, at, f"{where} by {who or '?'}")
            for m in PERMALINK_RX.finditer(text):
                p = parse_permalink(m.group(0))
                if p and (mh or any(is_mh(x) for x in named)):
                    ch, ts, parent = p
                    b.edge(k, thread_id(ch, parent or ts), "slack-ref", src, at,
                           f"{where} by {who or '?'}" + (f" · reply {ts}" if parent else ""))


# ── origins: slack ───────────────────────────────────────────────────────────────────────────────────

def channel_names(facts):
    c = read_json(os.path.join(facts, "slack", "channels.json"), {}) or {}
    return {x["id"]: x.get("name") for x in c.get("channels") or [] if x.get("id")}


def read_slack_channel(path, names, keys, b):
    ch = os.path.basename(path)[:-5]
    d = read_json(path, {}) or {}
    msgs, replies = d.get("messages") or {}, d.get("replies") or {}
    threads = {}
    for ts, m in msgs.items():
        threads[ts] = [m]
    for pts, r in replies.items():
        rs = r.get("messages") or []
        threads[pts] = ([msgs[pts]] if pts in msgs else []) + [x for x in rs if x.get("ts") != pts]
    for pts, ms in threads.items():
        named = {}
        for m in ms:
            for k in keys.find(m.get("text")):
                named.setdefault(k, m)
        if not any(is_mh(k) for k in named):
            continue
        tid = thread_id(ch, pts)
        parent = next((m for m in ms if m.get("ts") == pts), ms[0] if ms else {})
        n = len(ms) - 1 if parent.get("ts") == pts else len(ms)
        b.node(tid, "thread", first_line(parent.get("text")), channel=names.get(ch) or ch, date=ts_date(pts),
               replies=max(n, int(parent.get("reply_count") or 0)), link=permalink(ch, pts))
        for k, m in named.items():
            b.edge(tid, k, "thread-names", permalink(ch, m["ts"], pts), ts_date(m["ts"]))
        for m in ms:
            if DEPLOY_RX.search(first_line(m.get("text"), 200)):    # said in its first line, not a word deep in an analysis
                mid = f"slackmsg:{ch}/{m['ts']}"
                b.node(mid, "message", first_line(m.get("text"), 80), date=ts_date(m["ts"]))
                b.edge(tid, mid, "deploy", permalink(ch, m["ts"], pts), ts_date(m["ts"]))


# ── origins: mail, builds, lanes ─────────────────────────────────────────────────────────────────────

def read_mail(facts, keys, b):
    for p in glob.glob(os.path.join(facts, "mail", "messages", "*.json")):
        m = read_json(p, {}) or {}
        named = keys.find(f"{m.get('subject') or ''}\n{m.get('body') or m.get('snippet') or ''}")
        if not any(is_mh(k) for k in named):
            continue
        mid = f"mail:{m.get('id')}"
        try:
            sec = int(m.get("internal_date"))
            at = datetime.datetime.fromtimestamp(sec / 1000 if sec > 1e11 else sec).astimezone().isoformat(timespec="minutes")
        except (TypeError, ValueError):
            at = None
        link = f"https://mail.google.com/mail/u/0/#all/{m.get('thread') or m.get('id')}"
        b.node(mid, "mail", first_line(m.get("subject"), 120), date=at, link=link)
        for k in named:
            b.edge(mid, k, "mail-names", link, at)


def build_records(reports):
    return [p for p in glob.glob(os.path.join(reports, "releases", "*", "*-build-*.json"))
            if not p.endswith(".reconcile.json")]


def read_builds(reports, b):
    for p in build_records(reports):
        r = read_json(p, {}) or {}
        if not r.get("build"):
            continue
        bid = f"build:{r.get('line')}/{r.get('lane')}/{r.get('build')}"
        b.node(bid, "build", f"build {r.get('build')} → {r.get('lane_name') or r.get('lane')} ({r.get('line')}, {r.get('date')})",
               date=r.get("date"), lane=r.get("lane"), line=r.get("line"), path=p)
        for s in r.get("services") or []:
            for k in s.get("keys") or []:
                b.edge(bid, k, "carries", p, r.get("date"), f"{s.get('service')} {s.get('from')}→{s.get('to')}")


def train_files(reports):
    return glob.glob(os.path.join(reports, "train", "*.json"))


def read_lanes(reports, b):
    for p in train_files(reports):
        t = read_json(p, {}) or {}
        for row in t.get("rows") or []:
            for k in [row.get("key")] + list(row.get("also") or []):
                if not k:
                    continue
                for lane, c in (row.get("cells") or {}).items():
                    note = f"arrived {c.get('arrived') or '?'}" + (f" · verdict {c['verdict']}" if c.get("verdict") else "") \
                           + (f" on {c['version']}" if c.get("version") else "") + (f" ({c['source']}, {c['at']})" if c.get("source") else "")
                    b.edge(k, f"lane:{lane}", "reached", p, c.get("since"), note)
                    b.node(f"lane:{lane}", "lane", lane)


# ── origins: vault, questions ────────────────────────────────────────────────────────────────────────

def vault_files(vault):
    out = []
    for d in VAULT_DIRS:
        out += glob.glob(os.path.join(vault, d, "**", "*.md"), recursive=True)
    return out


def read_vault(vault, keys, b):
    for p in vault_files(vault):
        try:
            text = open(p, encoding="utf-8").read()
        except OSError:
            continue
        named = keys.find(text)
        if not named:
            continue
        rel = os.path.relpath(p, vault)
        title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), os.path.basename(p)[:-3])
        nid = f"vault:{rel}"
        b.node(nid, "note", first_line(title, 100), folder=rel.split(os.sep)[0], path=p)
        for k in named:
            b.edge(nid, k, "in-note", p, None)


def read_questions(reports, keys, b):
    p = os.path.join(reports, "ela", "questions.json")
    st = read_json(p, {}) or {}
    for qid, r in (st.get("questions") or {}).items():
        ks = list(dict.fromkeys(list(r.get("keys") or []) + list(r.get("lead") or [])))
        if not ks:
            continue
        nid = f"question:{qid}"
        b.node(nid, "question", first_line(r.get("text"), 100), status=r.get("status"),
               first=(r.get("first") or {}).get("date"), where=(r.get("first") or {}).get("where"))
        for k in ks:
            b.edge(nid, k, "question", f"{p}#{qid}", (r.get("first") or {}).get("date"))


# ── origins: writes ──────────────────────────────────────────────────────────────────────────────────

def action_files(reports):
    return glob.glob(os.path.join(reports, "runner", "*-actions.json"))


def applied_actions(reports, keys):
    """Every applied action across the runner's actions files: (applied time, verb, keys, pointer, word)."""
    out = []
    for p in action_files(reports):
        for a in read_json(p, []) or []:
            if not isinstance(a, dict) or not a.get("applied"):
                continue
            words = str(a.get("command") or "").split()
            verb = words[2] if len(words) > 2 and words[:1] == ["ela"] else None
            t = parse_ts(a["applied"])
            if t and verb:
                out.append({"at": t, "verb": verb, "keys": keys.find(" ".join(words[3:5])),
                            "action": f"{os.path.basename(p)}#{a.get('n')}", "word": f"{a.get('by') or 'apply'} (runner)"})
    return out


def parse_ts(s):
    s = str(s or "")
    for fmt in (None, "%Y-%m-%dT%H:%M:%S%z"):
        try:
            t = datetime.datetime.fromisoformat(s) if fmt is None else datetime.datetime.strptime(s, fmt)
            return t if t.tzinfo else t.astimezone()
        except ValueError:
            continue
    return None


def attribute(row, actions):
    """Who made a write and on whose word: the row's own fields (written since 2026-11-12), or the one applied action
    matching it; else unknown. Never a guess between two candidates."""
    if row.get("session") or row.get("job") or row.get("action"):
        return {"session": row.get("session"), "job": row.get("job"), "action": row.get("action"),
                "word": row.get("word"), "how": "recorded"}
    t = parse_ts(row.get("at"))
    k = row.get("key")
    cands = [a for a in actions if t and a["verb"] == row.get("verb") and (not k or k in a["keys"])
             and -5 <= (t - a["at"]).total_seconds() <= WRITE_MATCH_S]
    if len(cands) == 1:
        a = cands[0]
        return {"session": None, "job": None, "action": a["action"], "word": a["word"], "how": "matched to its action"}
    return {"session": None, "job": None, "action": None, "word": None,
            "how": "unknown" + (f" ({len(cands)} actions match)" if len(cands) > 1 else "")}


def read_writes(reports, keys, b):
    p = os.path.join(reports, "ela", "writes.jsonl")
    actions = applied_actions(reports, keys)
    try:
        lines = open(p, encoding="utf-8").read().splitlines()
    except OSError:
        return
    for n, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        ks = list(dict.fromkeys(([row["key"]] if row.get("key") else []) + list(row.get("keys") or [])))
        if row.get("permalink"):
            pl = parse_permalink(row["permalink"])
        else:
            pl = None
        if not ks and not pl:
            continue
        who = attribute(row, actions)
        wid = f"write:{n}"
        b.node(wid, "write", f"{row.get('system')} {row.get('verb')}", at=row.get("at"), ok=row.get("ok"),
               unattended=row.get("unattended"), **who)
        for k in ks:
            b.edge(wid, k, "wrote", f"{p}:{n}", row.get("at"))
        if pl:
            ch, ts, parent = pl
            b.edge(wid, thread_id(ch, parent or ts), "wrote", f"{p}:{n}", row.get("at"))


# ── build and update ─────────────────────────────────────────────────────────────────────────────────

def plan(r, keys):
    """origin → (files whose change re-reads it, reader). Slack and the vault are one origin per file."""
    f, rep, v = r["facts"], r["reports"], r["vault"]
    out = {"jira": ([os.path.join(f, "jira", "changes.json"), os.path.join(f, "jira", "projects.json")]
                    + glob.glob(os.path.join(f, "jira", "issues", "*.json")), lambda b: read_jira(f, keys, b)),
           "mail": (glob.glob(os.path.join(f, "mail", "messages", "*.json")), lambda b: read_mail(f, keys, b)),
           "builds": (build_records(rep), lambda b: read_builds(rep, b)),
           "lanes": (train_files(rep), lambda b: read_lanes(rep, b)),
           "questions": ([os.path.join(rep, "ela", "questions.json")], lambda b: read_questions(rep, keys, b)),
           "writes": ([os.path.join(rep, "ela", "writes.jsonl")] + action_files(rep), lambda b: read_writes(rep, keys, b))}
    names = channel_names(f)
    for p in glob.glob(os.path.join(f, "slack", "*.json")):
        base = os.path.basename(p)
        if re.fullmatch(r"[CDG][A-Z0-9]+\.json", base):
            out[f"slack/{base[:-5]}"] = ([p, os.path.join(f, "slack", "channels.json")],
                                         lambda b, p=p: read_slack_channel(p, names, keys, b))
    if v and os.path.isdir(v):
        out["vault"] = (vault_files(v), lambda b: read_vault(v, keys, b))
    return out


def update(full=False):
    r = roots()
    t0 = time.time()
    if full and os.path.exists(r["store"]):
        os.remove(r["store"])
    db = connect(r["store"])
    keys = Keys(r["facts"])
    known = dict(db.execute("SELECT origin, sig FROM origins"))
    p = plan(r, keys)
    read, kept = [], []
    for origin, (files, reader) in p.items():
        sig = signature(files)
        if not full and known.get(origin) == sig:
            kept.append(origin); continue
        t1 = time.time()
        b = Batch(origin)
        reader(b)
        save(db, b, sig, time.time() - t1)
        read.append(origin)
    gone = [o for o in known if o not in p]
    with db:
        for o in gone:
            db.execute("DELETE FROM edges WHERE origin = ?", (o,))
            db.execute("DELETE FROM nodes WHERE origin = ?", (o,))
            db.execute("DELETE FROM origins WHERE origin = ?", (o,))
        db.execute("INSERT OR REPLACE INTO meta VALUES ('built_at', ?)", (now_iso(),))
        if full:
            db.execute("INSERT OR REPLACE INTO meta VALUES ('rebuilt_at', ?)", (now_iso(),))
        db.execute("INSERT OR REPLACE INTO meta VALUES ('facts', ?)", (json.dumps(facts_read_at(r["facts"])),))
    n = db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    db.close()
    return {"store": r["store"], "full": full, "read": read, "kept": len(kept), "removed": gone, "edges": n,
            "bytes": os.path.getsize(r["store"]), "seconds": round(time.time() - t0, 1)}


def facts_read_at(facts):
    out = {}
    for s in ("jira", "slack", "mail", "builds", "lanes"):
        wm = read_json(os.path.join(facts, s, "watermark.json"), {}) or {}
        if wm.get("at"):
            out[s] = wm["at"]
    return out


# ── the lookup ───────────────────────────────────────────────────────────────────────────────────────

def node(db, nid):
    rows = db.execute("SELECT kind, label, meta FROM nodes WHERE id = ?", (nid,)).fetchall()
    best = {"id": nid, "kind": None, "label": None}
    for kind, label, meta in rows:
        best["kind"] = best["kind"] or kind
        if label and not best.get("label"):
            best["label"] = label
        for k, v in (json.loads(meta) if meta else {}).items():
            if v is not None and best.get(k) is None:
                best[k] = v
    return best


def out_edges(db, nid, kinds):
    q = f"SELECT src, dst, kind, source, at, note FROM edges WHERE src = ? AND kind IN ({','.join('?' * len(kinds))})"
    return [dict(zip(("src", "dst", "kind", "source", "at", "note"), r)) for r in db.execute(q, (nid, *kinds))]


def in_edges(db, nid, kinds):
    q = f"SELECT src, dst, kind, source, at, note FROM edges WHERE dst = ? AND kind IN ({','.join('?' * len(kinds))})"
    return [dict(zip(("src", "dst", "kind", "source", "at", "note"), r)) for r in db.execute(q, (nid, *kinds))]


def thread_view(db, tid, via=None):
    n = node(db, tid)
    names = sorted({e["dst"] for e in out_edges(db, tid, ("thread-names",))})
    deploys = [dict(e, label=node(db, e["dst"]).get("label")) for e in out_edges(db, tid, ("deploy",))]
    ch, ts = tid[6:].split("/", 1)
    return {"id": tid, "channel": n.get("channel") or ch, "date": n.get("date") or ts_date(ts), "first": n.get("label"),
            "replies": n.get("replies"), "link": n.get("link") or permalink(ch, ts), "names": names,
            "deploys": sorted(deploys, key=lambda e: e.get("at") or ""), "via": via, "indexed": n.get("kind") is not None}


def lookup_key(db, k):
    me = node(db, k)
    linked = []
    for e in out_edges(db, k, ("link", "parent")):
        linked.append(dict(e, other=e["dst"], reads=(e["note"] or "").split("\t")[0]))
    for e in in_edges(db, k, ("link", "parent")):           # the same link read from the other ticket: its inverse words
        note = e["note"] or ""
        reads = "parent of" if note == "sub-task of" else (note.split("\t") + [note])[1]
        linked.append(dict(e, other=e["src"], reads=reads))
    seen, uniq = set(), []
    for l in linked:
        if (l["other"], l["reads"]) not in seen:
            seen.add((l["other"], l["reads"])); uniq.append(dict(l, ticket=node(db, l["other"])))
    # threads: the ones the ticket links to, the ones that name it
    tids = {}
    for e in out_edges(db, k, ("slack-ref",)):
        tids.setdefault(e["dst"], f"linked from the ticket's {e['note']}")
    for e in in_edges(db, k, ("thread-names",)):
        tids.setdefault(e["src"], "names it")
    threads = [thread_view(db, t, via) for t, via in tids.items()]
    threads.sort(key=lambda t: t["date"] or "")
    # named with it: keys the same thread names, keys its text names, tickets whose text names it
    named = {}

    def add(other, where, source, at):
        if other != k:
            named.setdefault(other, []).append({"where": where, "source": source, "at": at})
    for t in threads:
        for o in t["names"]:
            add(o, f"thread #{t['channel']} {str(t['date'] or '')[:10]}", t["link"], t["date"])
    for e in out_edges(db, k, ("names",)):
        add(e["dst"], f"named in its {e['note']}", e["source"], e["at"])
    for e in in_edges(db, k, ("names",)):
        add(e["src"], f"names it in its {e['note']}", e["source"], e["at"])
    linked_keys = {l["other"] for l in uniq}
    named_list = [{"key": o, "ticket": node(db, o), "where": w, "linked": o in linked_keys}
                  for o, w in sorted(named.items(), key=lambda x: (x[0] not in linked_keys, -len(x[1]), x[0]))]
    builds = [dict(e, build=node(db, e["src"])) for e in in_edges(db, k, ("carries",))]
    mails = [dict(e, mail=node(db, e["src"])) for e in in_edges(db, k, ("mail-names",))]
    lanes = [dict(e, lane=e["dst"][5:]) for e in out_edges(db, k, ("reached",))]
    writes = [dict(e, write=node(db, e["src"])) for e in in_edges(db, k, ("wrote",))]
    notes = [dict(e, note=node(db, e["src"])) for e in in_edges(db, k, ("in-note", "question"))]
    return {"key": k, "ticket": me, "linked": uniq, "named_with": named_list, "threads": threads,
            "builds": sorted(builds, key=lambda e: e.get("at") or ""), "mails": sorted(mails, key=lambda e: e.get("at") or ""),
            "lanes": lanes, "writes": sorted(writes, key=lambda e: e.get("at") or ""),
            "notes": sorted(notes, key=lambda e: e["src"])}


def lookup_thread(db, ch, ts, parent):
    tid = thread_id(ch, parent or ts)
    t = thread_view(db, tid)
    t["tickets"] = [dict(e, ticket=node(db, e["src"])) for e in in_edges(db, tid, ("slack-ref",))]
    t["writes"] = [dict(e, write=node(db, e["src"])) for e in in_edges(db, tid, ("wrote",))]
    t["keys"] = [{"key": x, "ticket": node(db, x)} for x in t["names"]]
    return t


def lookup_build(db, ref):
    """A build by `build:<line>/<lane>/<n>`, `<lane>/<n>` or `<line>/<lane>/<n>`."""
    ref = ref[6:] if ref.startswith("build:") else ref
    parts = ref.split("/")
    rows = db.execute("SELECT DISTINCT id FROM nodes WHERE kind = 'build'").fetchall()
    hits = [r[0] for r in rows if r[0][6:].split("/")[-len(parts):] == parts]
    if not hits:
        return None
    bid = sorted(hits)[-1]
    return {"build": node(db, bid), "keys": [dict(e, ticket=node(db, e["dst"])) for e in out_edges(db, bid, ("carries",))]}


def index_age(db):
    m = dict(db.execute("SELECT k, v FROM meta"))
    return {"built_at": m.get("built_at"), "rebuilt_at": m.get("rebuilt_at"), "facts": json.loads(m.get("facts") or "{}")}


def age_line(age):
    t = parse_ts(age.get("built_at"))
    if not t:
        return "index: never built (ela links rebuild)"
    mins = int((now() - t).total_seconds() // 60)
    ago = f"{mins} min ago" if mins < 120 else f"{mins // 60} h ago"
    facts = " · ".join(f"{s} {str(at)[5:16].replace('T', ' ')}" for s, at in age.get("facts", {}).items())
    return f"index built {t.strftime('%m-%d %H:%M')} ({ago}) from facts {facts or 'none'}"


def short(at):
    return str(at or "")[5:16].replace("T", " ") or "—"


def ticket_words(t):
    return " · ".join(x for x in (t.get("label"), t.get("status")) if x) or "(not in the fact store)"


def who_words(w):
    if w.get("how") == "recorded":
        bits = [f"session {w['session']}" if w.get("session") else None, f"job {w['job']}" if w.get("job") else None,
                f"action {w['action']}" if w.get("action") else None]
        by = ", ".join(b for b in bits if b) or "recorded"
        return f"by {by}" + (f" on {w['word']}" if w.get("word") else "")
    if w.get("action"):
        return f"by the runner, action {w['action']}, on {w.get('word') or '?'} (matched to its action)"
    return "who: " + (w.get("how") or "unknown") + " (written before writes carried their session)"


def render_key(v, age):
    k, t = v["key"], v["ticket"]
    out = [f"{k} · {ticket_words(t)}" + (f"  {t['url']}" if t.get("url") else ""), age_line(age),
           "Edges only; co-occurrence is not cause: \"named in the same thread\" is not \"fixed by\"."]
    out.append("\nlinked in Jira")
    out += [f"  {l['reads']} {l['other']} · {ticket_words(l['ticket'])}  {l['source']}" for l in v["linked"]] or ["  none"]
    out.append("\nnamed with it")
    for n in v["named_with"]:
        where = n["where"][0]
        more = f" (+{len(n['where']) - 1} more)" if len(n["where"]) > 1 else ""
        out.append(f"  {n['key']} · {ticket_words(n['ticket'])}{' · linked' if n['linked'] else ''}")
        out.append(f"      {where['where']}{more}  {where['source']}")
    if not v["named_with"]:
        out.append("  none")
    out.append("\nthreads")
    for th in v["threads"]:
        if not th["indexed"]:
            out.append(f"  {th['via']}: not in the Slack store (a channel the bot does not read, or older than its window)  {th['link']}")
            continue
        out.append(f"  #{th['channel']} {short(th['date'])} · {th['replies'] or 0} replies · \"{th['first']}\" ({th['via']})  {th['link']}")
        others = [x for x in th["names"] if x != k]
        if others:
            out.append(f"      names {', '.join(others)}")
        for d in th["deploys"]:
            out.append(f"      deploy post {short(d['at'])} \"{d['label']}\"  {d['source']}")
    if not v["threads"]:
        out.append("  none")
    out.append("\nbuilds and lanes")
    rows = [f"  {e['build'].get('label')} · {e['note']}  {e['source']}" for e in v["builds"]]
    rows += [f"  {e['lane']}: {e['note']}" + (f" since {e['at']}" if e.get("at") else "") + f"  {e['source']}" for e in v["lanes"]]
    rows += [f"  mail {short(e['at'])} \"{e['mail'].get('label')}\"  {e['source']}" for e in v["mails"]]
    out += rows or ["  none"]
    out.append("\nela's writes")
    out += [f"  {short(e['at'])} {e['write'].get('label')}{'' if e['write'].get('ok', True) else ' (failed)'} · {who_words(e['write'])}  {e['source']}"
            for e in v["writes"]] or ["  none"]
    out.append("\nvault notes")
    for e in v["notes"]:
        n = e["note"]
        if e["kind"] == "question":
            out.append(f"  question ({n.get('status')}, since {n.get('first')}) \"{n.get('label')}\"  {n.get('where') or e['source']}")
        else:
            out.append(f"  {n['id'][6:]} \"{n.get('label')}\"  {e['source']}")
    if not v["notes"]:
        out.append("  none")
    return "\n".join(out)


def render_thread(t, age):
    out = [f"#{t['channel']} {short(t['date'])} · {t['replies'] or 0} replies · \"{t['first']}\"  {t['link']}", age_line(age)]
    if not t["indexed"]:
        out.append("not in the index: the thread names no MH key, or it is outside the Slack store's channels and window")
    out.append("\nkeys it names")
    out += [f"  {x['key']} · {ticket_words(x['ticket'])}" for x in t["keys"]] or ["  none"]
    out.append("\ndeploy posts")
    out += [f"  {short(d['at'])} \"{d['label']}\"  {d['source']}" for d in t["deploys"]] or ["  none"]
    out.append("\ntickets that link to it")
    out += [f"  {e['src']} · {ticket_words(e['ticket'])} ({e['note']})  {e['source']}" for e in t["tickets"]] or ["  none"]
    out.append("\nela's writes")
    out += [f"  {short(e['at'])} {e['write'].get('label')} · {who_words(e['write'])}  {e['source']}" for e in t["writes"]] or ["  none"]
    return "\n".join(out)


def render_build(v, age):
    b = v["build"]
    out = [f"{b.get('label')}  {b.get('path')}", age_line(age), "\ntickets it carries"]
    out += [f"  {e['dst']} · {ticket_words(e['ticket'])} · {e['note']}" for e in v["keys"]] or ["  none"]
    return "\n".join(out)


# ── commands ─────────────────────────────────────────────────────────────────────────────────────────

def open_index():
    r = roots()
    if not os.path.exists(r["store"]):
        print(f"no links index at {r['store']}: run `ela links rebuild`", file=sys.stderr); sys.exit(EX_NOTFOUND)
    return connect(r["store"])


def cmd_show(a):
    db = open_index()
    age = index_age(db)
    ref = a.ref.strip()
    pl = parse_permalink(ref)
    keyish = re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", ref.upper()) or "/browse/" in ref
    if pl:
        v = lookup_thread(db, *pl)
        text = render_thread(v, age)
    elif keyish:
        k = (re.search(r"[A-Z][A-Z0-9]+-\d+", ref.upper()) or [ref])[0]
        v = lookup_key(db, k)
        if v["ticket"]["kind"] is None and not any(v[x] for x in ("linked", "named_with", "threads", "builds", "lanes", "writes", "notes", "mails")):
            print(f"{k}: not in the index ({age_line(age)})", file=sys.stderr); sys.exit(EX_NOTFOUND)
        text = render_key(v, age)
    else:
        v = lookup_build(db, ref)
        if not v:
            print(f"{ref}: not a key, a thread permalink or a build the index holds (a build is <lane>/<n>, e.g. qa-cn3/91)",
                  file=sys.stderr); sys.exit(EX_NOTFOUND)
        text = render_build(v, age)
    if a.json:
        print(json.dumps({"index": age, "result": v}, ensure_ascii=False, default=str))
    else:
        print(text)


def cmd_update(a, full=False):
    res = update(full=full or getattr(a, "full", False))
    if a.json:
        print(json.dumps(res, ensure_ascii=False)); return
    print(f"links: {'rebuilt' if res['full'] else 'updated'} {len(res['read'])} origin(s), {res['kept']} unchanged, "
          f"{res['edges']} edges, {res['bytes'] / 1e6:.1f} MB, {res['seconds']}s")


def cmd_status(a):
    db = open_index()
    age = index_age(db)
    kinds = dict(db.execute("SELECT kind, COUNT(*) FROM edges GROUP BY kind"))
    r = roots()
    res = {"index": age, "store": r["store"], "bytes": os.path.getsize(r["store"]), "edges": kinds,
           "origins": db.execute("SELECT COUNT(*) FROM origins").fetchone()[0]}
    if a.json:
        print(json.dumps(res, ensure_ascii=False)); return
    print(age_line(age))
    print(f"  {r['store']} · {res['bytes'] / 1e6:.1f} MB · {res['origins']} origins")
    for k, n in sorted(kinds.items()):
        print(f"  {k:<13} {n}")


def main():
    ap = argparse.ArgumentParser(description="the links index: edges between the facts, one lookup per ticket, thread or build")
    ap.add_argument("--env-file", help="ignored (the index reads no live source)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("show", help="what links to a key, a thread permalink or a build (<lane>/<n>)")
    p.add_argument("ref"); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_show)
    p = sub.add_parser("update", help="re-read the origins that changed (after a facts refresh)")
    p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_update)
    p = sub.add_parser("rebuild", help="drop the index and read every origin whole")
    p.add_argument("--json", action="store_true"); p.set_defaults(func=lambda a: cmd_update(a, full=True))
    p = sub.add_parser("status", help="the index's age, size and edges per kind")
    p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_status)
    argv = sys.argv[1:]
    i = 2 if argv[:1] == ["--env-file"] else 0
    if len(argv) > i and argv[i] not in ("show", "update", "rebuild", "status", "-h", "--help"):
        argv.insert(i, "show")                              # `ela links MH-3870`: the lookup is the default
    a = ap.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
