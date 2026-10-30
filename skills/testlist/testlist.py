#!/usr/bin/env python3
"""The test list: what QA should verify on a lane, ranked, one row per behaviour; and the dev list beside it.

    testlist.py list [--lane qa-cn3] [--days N] [--json] [--page] [--new-rows [--date YYYY-MM-DD]]
    testlist.py list --lane qa-cn3 --saw KEY "ela saw … on V at HH:MM"
    testlist.py list [--lane qa-cn3] --today [--budget N] [--guidance FILE] [--json]
    testlist.py dev [--line 2.1] [--json] [--page]
    testlist.py dev [--line 2.1] --today [--budget N] [--guidance FILE] [--json]

list  Without --lane, every lane with release mails ("[Release MediaHub <env>]") in the window or a list on disk;
      --json is then {"lists": [<one lane's shape>], "gaps"}. A QA lane lists what QA verifies on its builds; a prod
      lane (prod-3, prod-2-china for CN Prod2) is a release check: the tickets the last train or hotfix carried there, keyed
      by the release's day. A mail with no Test Focus and no Change Log is one row per key its subject names.
      The lane's release mails (Test Focus and Change Log) give the rows: one per owner ticket a build names, and one
      "no ticket" row per change-log item that names no key (flagged). Two keys in one Test Focus item are one
      behaviour: the owner is the parent, or the one the other implements, else the first named; the rest ride as
      `also`. A row carries the ticket, its title and layer, the build it first arrived in and the build on the lane
      now, how to verify it (the Test Focus sentence, else the ticket's acceptance line, else "steps unknown"), auto
      (visible in the browser UI: a page, a list, a dialog, a field; never media quality, streams, audio or timing),
      the priority with its reason, QA's verdict (a QA person's ticket comment naming a version and a verdict, or the
      key's line in a QA report mail, after the row's first build), its age and what the night run saw.
      Priority, first rule that holds: P1 a customer incident (a customer's bracket on the summary, a label or a
      component), a re-test after a fail, a hotfix; P2 in the sprint, or Highest/High; P3 the rest. A row two or more
      builds older than the lane's moves up one; so does a row without a verdict when the train leaves within a
      working day (the pending promotion's `departs`, once the cadence records it). Riding the next train ranks
      nothing: everything on QA rides it.
      State: <reports>/lanes/test-list-<lane>.json keeps each row's first build and verdict across builds; a new build
      adds rows and re-stamps lane_build; a row leaves only on a pass (or N/A) or when its ticket is withdrawn (closed
      won't do). --page writes <reports>/lanes/test-list-<lane>.md; the vault sync places it at lanes/.
      Rows carry a kind: version (the rows above, keyed by build) or env, an environment's own problem that no build
      carries, from three sources: a China lane's services that differ from the lane it aligns with (the lanes page's
      region reading), tickets labelled env:<lane>, and the newest QA report's lines naming the environment rather than
      a behaviour. An env row has its lane, since, owner (the roster responsibility owning env:<lane>, else
      "unowned"), state open or resolved, and the verdict "resolved on <lane> <date>"; it is kept under "env" in the
      state file and shown in its own section, "Environment, not code".
      --new-rows: the rows each build released on --date (default today) added, Slack-formatted, with the lane's
      release thread in #mediahub-qa-release, for the runner's tier-2 post (rule test-list). The thread is the one that
      day whose root or replies name the lane (its mail tag QA-AWS3, or the build bot's QA3 / qa2), the one naming the
      build first; ela's own posts never count. No thread names the lane: thread null, and the text says "no thread
      for <lane>".
      --saw: writes the night run's line on the row (a local write; no --apply), stamped with the lane build.
      A QA member's reply in the release thread, "<KEY or nt- id> pass|fail on <version>", is a verdict for the row;
      on a row with a ticket it also drafts the tier-1 fact comment (`drafts`, rule fact-comment) once per reply.
      --today: QA today, the day's plan for each QA lane: carried rows without a verdict (P1 first, oldest first), the
      newest build's new rows, then interruptions (tickets assigned to QA in no build; asks to QA in #mediahub-qa-
      release and #prj_dev_mediahub since the last evening run, 19:00 the previous working day), cut at --budget
      (10), each row with the reason it is in; --guidance applies his `ela:` lines (drop · first · add · KEY P1) first. The
      json carries the text for the 09:30 tier-2 post (rule qa-today) in the lane build's release thread, or, when the
      build has none, as the day post (`post`: "day post", `ela slack post #<channel> … --team-day-post`), and the
      overnight count (posts read, channels not read, asks placed).

dev   One row per owner ticket in development on the line (labelled for it, not Done, and In Progress, Review, Blocked,
      On Hold or Reopened, or named by a commit, or on the lane's test list): layer, assignee and the commits' authors,
      branch state (on a lane build · merged to the release branch · on a branch · no commit), the lane build, QA's
      verdict, train readiness (ticket ✓, Fixed In ✓/–, verdict ✓/–) and the gaps: QA assigned on a secondary ticket
      (one the test list rides under another owner), Fixed In without a verdict; the build changes with no ticket
      are listed under the table, and the line's open env rows under "Environment, not code" (a ticket labelled
      env:<lane> is never a dev row). --page writes <reports>/lanes/dev-list-<line>.md and .json. Without --line,
      every line release.yaml names with a Jira label that has a ticket in development; --json is then {"lists"}.
      --today: Dev today, by developer, at most 12 rows: moved since the last evening run, due today or overdue,
      blocked or on hold, the gaps and the build changes with no ticket, and asks to a developer from anyone else in
      the team channels since then; his `ela:` lines applied first. The json carries the text for the 10:00 tier-2
      post (rule dev-today), the day post in #prj_dev_mediahub (`post`: "day post", thread null): one top-level
      message a day, which becomes the day's thread.

Reads only Jira, mail, Slack, the release ledger and disk; writes only its own files under <reports>/lanes/.
Exit codes: 0 ok · 2 usage · 3 --saw names no row · 5 the release mails could not be read.
"""
import argparse, datetime, hashlib, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SKILLS, "brief"))
import brief as B  # noqa: E402  — mail, Jira and Slack the brief's way; keys; the sprint; the pending promotion
sys.path.insert(0, os.path.join(SKILLS, "ticket"))
import ticket as T  # noqa: E402  — the QA verdict rule (a QA person, a version, a verdict word)
sys.path.insert(0, os.path.join(SKILLS, "promote"))
import promote as P  # noqa: E402  — a report's verdict line for one key
sys.path.insert(0, os.path.join(SKILLS, "jira"))
import jira as J  # noqa: E402  — rich text as plain text

EX_USAGE, EX_NOROW, EX_REMOTE = 2, 3, 5
JIRA_URL = "https://tvunetworks.atlassian.net/browse/"
SECTIONS = ("Service add", "Database Change", "Properties Change", "Test Focus", "Change Log", "Other Service Dependencies",
            "Rollback Plan", "Note")
SECTION_RX = re.compile(r"^\s*\*?(" + "|".join(SECTIONS) + r")\*?(?:\s*\([^)\n]*\))?\s*$", re.M)
RELEASE_RX = re.compile(r"^\s*\[Release\s+MediaHub\s+([^\]]+)\]", re.I)        # a lane's release mail: [Release Mediahub QA-AWS3]
REPORT_RX = re.compile(r"test report.*\[Release\s+MediaHub\s+([^\]]+)\]", re.I)
GOOGLE_LINK_RX = re.compile(r"<https?://www\.google\.com/url\?[^>]*>;?")
# the change log's component prefix → the layer that builds it
LAYERS = (("ur caller", "UR"), ("unified resources", "UR"), ("mediahub admin frontend", "UI"), ("mediahub frontend", "UI"),
          ("unified media frontend", "UI"), ("mediahub backend", "App"), ("unified media backend", "App"), ("j2n", "J2N"),
          ("media", "Media"))
PREFIX_RX = re.compile(r"^\[(Infra|J2N|Media|App|UI|QA|Design|AI|UR)\]", re.I)
UI_RX = re.compile(r"\b(page|list|list view|dialog|popup|modal|field|dropdown|slider|button|switch|toggle|tab|menu|column|"
                   r"setting|settings|filter|quick edit|edit|shows?|displays?|disabled|enabled|click|placeholder|panel|"
                   r"tooltip|label|form|admin)\b|\u5f39\u7a97|\u9875\u9762|\u5217\u8868|\u6309\u94ae|\u4e0b\u62c9|\u663e\u793a", re.I)
MEDIA_RX = re.compile(r"\b(stream|streams|audio|volume level|video quality|bitrate|resolution|fps|frame|latency|delay|"
                      r"timing|sync|sender|receiver|issp|srt|udp|hls|rtmp|mpeg-?ts|codec|encod\w*|decod\w*|render|pid|pmt|"
                      r"outputurl|output format|multiprogram|copier|transcod\w*|graph)\b|POST\s+/|/api/|\u97f3\u9891|\u89c6\u9891|\u7801\u7387|\u5ef6\u8fdf", re.I)
CHORE_RX = re.compile(r"^\s*(CI|unit tests?|tests?|docs?)\b.*\bfix", re.I)
WITHDRAWN_RX = re.compile(r"won'?t|cancel|duplicate|reject|invalid|not a bug", re.I)
HOTFIX_RX = re.compile(r"hot-?fix|prod[-_ ]?patch", re.I)
CUSTOMER_RX = re.compile(r"customer|incident|prod[-_ ]?issue|escalat", re.I)
# a version a QA comment names: 2.2.123, v2.1.36 build267, build 75; never an address (10.12.64.45)
QA_VERSION_RX = re.compile(r"(?<![\d.])v?(\d+\.\d+\.\d+)(?!\d|\.\d)(?:\s*build\s*(\d+))?|\bbuild\s*(\d+)\b", re.I)
ACCEPT_RX = re.compile(r"(acceptance|accept criteria|expected|\u9a8c\u6536|\u671f\u671b|\u9884\u671f)[^:\uff1a\n]*[:\uff1a]\s*(.+)", re.I)


def now():
    return datetime.datetime.now().astimezone()


def site():
    return json.load(open(B.SITE))


def reports_root(s):
    return s.get("reports") or os.path.join(s.get("projects", ""), "reports")


def lane_name(raw):
    """qa-cn3 · qa-aws3 · QA-AWS3 → qa-cn3; Prod3 · prod-3 → prod-3; CN Prod2 → prod-2-china (ela's names); the mails' name."""
    lane = env_lane(raw) or raw.strip().lower()
    return lane, B.LANE_SHOWN.get(lane, raw.strip() if env_lane(raw) and raw.strip() != lane else lane)


EXTRA_LANES = (("qaaws2", "qa-cn2"), ("qaaws1", "qa-cn1"), ("stage", "daily-stage"))   # by the tags aws-cn2-env, aws-cn1-env


def env_lane(env):
    """A release mail's environment words → ela's lane: the brief's names, and the QA-AWS lanes and Stage it does not."""
    e = re.sub(r"[\s-]+", "", env or "").lower()
    return B.mail_lane(env) or next((lane for k, lane in EXTRA_LANES if e == k), None)


def is_qa(lane):
    return lane.startswith("qa-")


def state_path(s, lane):
    return os.path.join(reports_root(s), "lanes", f"test-list-{lane}.json")


def load_state(path, lane):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return {"lane": lane, "lane_build": None, "builds": {}, "rows": {}, "left": {}}


def save(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    T.atomic_write(path, text)


# ── the release mails ────────────────────────────────────────────────────────────────────────────────

def clean(text):
    return GOOGLE_LINK_RX.sub("", text or "")


def numbered(block):
    """A section's numbered items, continuation lines joined: ["MH-3833 / MH-3834 Change the Stream URL …", …]."""
    items, cur = [], None
    for line in block.splitlines():
        m = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if m:
            cur = [m.group(1)]
            items.append(cur)
        elif cur is not None and line.strip():
            cur.append(line.strip())
        elif not line.strip():
            cur = None if cur and len(cur) > 1 else cur
    return [re.sub(r"\s+", " ", " ".join(i)).replace("*", "").strip() for i in items]


def sections(body):
    """{section name: its text} of a release mail."""
    text, out = clean(body), {}
    marks = list(SECTION_RX.finditer(text))
    for i, m in enumerate(marks):
        out[m.group(1)] = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
    return out


def layer_of(text):
    t = (text or "").lower()
    return next((layer for k, layer in LAYERS if t.startswith(k)), None)


def build_key(subject, at, qa):
    """(key, label): a QA build is numbered (`Release build 78`); a prod release, or a QA build named only by its version
    (`build 2.0.10`), is keyed by its day and labelled by the version it names, else by the day."""
    b = re.search(r"build\s*(\d+)\b(?!\.)", subject, re.I) if qa else None
    if b:
        return b.group(1), b.group(1)
    v = re.search(r"build\s*(\d+\.\d+\.\d+)", subject, re.I)
    return (at[:10].replace("-", ""), v.group(1) if v else at[5:10]) if at else (None, None)


def parse_build_mail(m, qa=True):
    """One release mail → {build, label, at, id, subject, focus: [{text, keys}], log: [{text, keys, layer}]}. A mail with
    neither section (a prod upgrade under one ticket) is one behaviour per key its subject names."""
    at = B.mail_time(m["date"])
    key, label = build_key(m["subject"], at or "", qa)
    sec = sections(m.get("body") or "")
    focus = [{"text": t, "keys": B.keys_in(t)} for t in numbered(sec.get("Test Focus", ""))]
    log = []
    for item in numbered(sec.get("Change Log", "")):
        comp, _, rest = item.partition(":")
        layer = layer_of(comp) if rest else None
        for seg in (rest or item).split(";"):
            seg = seg.strip(" .;")
            if seg and not CHORE_RX.match(seg):
                log.append({"text": f"{comp.strip()}: {seg}" if rest else seg, "keys": B.keys_in(seg), "layer": layer})
    if not focus and not log:
        subject = RELEASE_RX.sub("", m["subject"]).strip()
        log = [{"text": subject, "keys": [k], "layer": None} for k in B.keys_in(subject)]
    return {"build": key, "label": label, "at": at, "id": m["id"], "subject": m["subject"], "focus": focus, "log": log}


def mail_search(env, query, limit=40):
    return B.run_json(["python3", B.MAIL, *env, "search", query, "--limit", str(limit), "--body", "--json"], timeout=300)["messages"]


def release_mails(env, days):
    """Every lane's release mails, oldest first, grouped by lane: {lane: {"shown", "mails"}}; replies and reports left
    out. An environment no lane name maps is returned under None with its names."""
    out = {}
    for m in mail_search(env, f'newer_than:{days}d subject:("Release Mediahub")', limit=80):
        r = RELEASE_RX.match(m["subject"])
        if not r or re.search(r"test report", m["subject"], re.I):
            continue
        shown = " ".join(r.group(1).split())
        lane = env_lane(shown)
        if not lane:
            out.setdefault(None, {"shown": set(), "mails": []})["shown"].add(shown)
            continue
        b = parse_build_mail(m, is_qa(lane))
        if b["build"]:
            out.setdefault(lane, {"shown": shown, "mails": []})["mails"].append(b)
    for v in out.values():
        v["mails"].sort(key=lambda b: int(b["build"]))
    return out


def report_mails(env, days):
    """QA's test reports per lane: {lane: [{at, build, summary, text, subject}]}; a prod report carries no build."""
    out = {}
    for m in mail_search(env, f'newer_than:{days}d subject:("Test Report" "Release Mediahub")', limit=60):
        r = REPORT_RX.search(m["subject"])
        lane = env_lane(r.group(1)) if r else None
        if not lane:
            continue
        b = re.search(r"build\s*(\d+)\b(?!\.)", m["subject"], re.I) if is_qa(lane) else None
        out.setdefault(lane, []).append({"at": B.mail_time(m["date"]), "build": b.group(1) if b else None,
                                         "summary": bool(re.match(r"^\s*summary", m["subject"], re.I)),
                                         "text": m["subject"] + "\n" + (m.get("body") or ""), "subject": m["subject"]})
    return out


# ── rows from a build ────────────────────────────────────────────────────────────────────────────────

def words(text):
    return {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9]{4,}", text or "")}


def behaviours(b):
    """A build's behaviours: [{keys, focus, log}]. Each Test Focus item with keys is one; a keyless focus item belongs
    to the keyless change-log line it shares a word with, else to the item before it; every change-log key not in
    the focus is a behaviour of its own; a keyless change-log line is a "no ticket" behaviour."""
    out, by_key = [], {}
    keyless_log = [l for l in b["log"] if not l["keys"]]
    owned_log = {id(l): None for l in keyless_log}
    for f in b["focus"]:
        if f["keys"]:
            beh = {"keys": f["keys"], "focus": [f["text"]], "log": []}
            out.append(beh)
            for k in f["keys"]:
                by_key[k] = beh
            continue
        match = next((l for l in keyless_log if owned_log[id(l)] is None and words(l["text"].split(":", 1)[-1]) & words(f["text"])), None)
        if match:
            beh = {"keys": [], "focus": [f["text"]], "log": [match]}
            owned_log[id(match)] = beh
            out.append(beh)
        elif out:
            out[-1]["focus"].append(f["text"])
    for l in b["log"]:
        if l["keys"]:
            known = [by_key[k] for k in l["keys"] if k in by_key]
            if known:
                known[0]["log"].append(l)
                continue
            beh = {"keys": l["keys"][:1], "focus": [], "log": [l]}
            out.append(beh)
            for k in l["keys"]:
                by_key[k] = beh
        elif owned_log[id(l)] is None:
            out.append({"keys": [], "focus": [], "log": [l]})
    return out


def owner_of(keys, issues):
    """The owner ticket among keys one behaviour names: the parent, or the one the others implement, else the first."""
    if len(keys) < 2:
        return keys[0] if keys else None
    for k in keys:
        f = (issues.get(k) or {}).get("fields") or {}
        parent = ((f.get("parent") or {}).get("key"))
        if parent in keys:
            return parent
        for link in f.get("issuelinks") or []:
            t = (link.get("type") or {})
            if "implement" in (t.get("outward") or "").lower() and (link.get("outwardIssue") or {}).get("key") in keys:
                return link["outwardIssue"]["key"]
    return keys[0]


def nt_id(text):
    return "nt-" + hashlib.sha1(re.sub(r"\W+", " ", text.lower()).strip().encode()).hexdigest()[:8]


def auto_of(text, keyed):
    """Visible in the browser UI on the lane: a page, a list, a dialog, a field. A media word wins: a browser cannot
    see a stream's quality, audio or timing; an API-only change is not on a page either."""
    return bool(keyed and UI_RX.search(text or "") and not MEDIA_RX.search(text or ""))


def acceptance(issue):
    desc = J.body_text(((issue or {}).get("fields") or {}).get("description")) or ""
    m = ACCEPT_RX.search(desc)
    return " ".join(m.group(2).split())[:300] if m else None


def jira_read(env, key, cache, gaps):
    if key not in cache:
        try:
            cache[key] = B.run_json(["python3", B.JIRA, *env, "read", key, "--json"], timeout=90)
        except (B.LaneError, subprocess.TimeoutExpired, ValueError) as x:
            cache[key] = None
            gaps.append({"source": f"jira read {key}", "error": str(x)[:200]})
    return cache[key]


def prefetch(env, keys, cache, gaps, workers=8):
    """Read every ticket the lists will need, eight at a time: one Jira read is a second, a list holds dozens."""
    import concurrent.futures
    errs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(lambda k: jira_read(env, k, cache, errs), [k for k in keys if k not in cache]))
    gaps += [f"{g['source']}: {g['error']}" for g in errs]


# ── verdicts ─────────────────────────────────────────────────────────────────────────────────────────

def comment_verdicts(issue, qa, since):
    """[(at, verdict, version, source)] from QA people's comments after since: a version and a verdict word (the
    rule ticket refresh reads as `sure 2`)."""
    out = []
    for c in (issue or {}).get("comments") or []:
        who = J.name_of(c.get("author")) if isinstance(c.get("author"), dict) else (c.get("author") or "")
        text = J.body_text(c.get("body")) or ""
        at = B.parse_ts(c.get("created") or "")
        at = at.astimezone() if at else None
        if who.lower() not in qa or not at or (since and at.isoformat() < since):
            continue
        v, w = QA_VERSION_RX.search(text), T.VERDICT_RX.search(text)
        if v and w and not T.NO_REPRO_RX.search(text):
            version = f"{v.group(1)} build {v.group(2)}" if v.group(2) else v.group(1) or f"build {v.group(3)}"
            out.append((at.isoformat(timespec="minutes"), "fail" if T.FAIL_RX.search(text) else "pass", version, f"comment by {who}"))
    return out


def report_verdicts(reports, key, since, build):
    """[(at, verdict, version, source)] from QA reports after since on a build no older than the one that last named
    the key: a report on build 75 says nothing about what build 78 changed."""
    out = []
    for r in reports:
        if not r["at"] or (since and r["at"] < since) or (r["build"] and build and int(r["build"]) < int(build)):
            continue
        for verdict, _ in P.key_verdicts(r["text"], key)[-1:]:
            if verdict in ("pass", "fail", "n-a"):
                out.append((r["at"][:16], verdict, f"build {r['build']}" if r["build"] else "", "QA report"))
    return out


# a QA member's reply in the list's thread: "MH-3833 pass on 2.1.78", "nt-1a2b3c4d fail on build 78"
THREAD_VERDICT_RX = re.compile(r"\b([A-Z][A-Z0-9]+-\d+|nt-[0-9a-f]{8})\b\s*[:：]?\s*(pass|fail)(?:ed)?\s+on\s+"
                               r"(v?\d+(?:\.\d+){1,3}(?:\s*build\s*\d+)?|build\s*\d+)", re.I)


def qa_people():
    """{name lower: name} and {slack id: name} of the roster's QA people."""
    try:
        import team as TM  # noqa: E402 — on the path through ticket
        roster = TM.read_roster(TM.records())[1]
    except (SystemExit, ImportError, OSError, ValueError):
        return {}, {}
    qa = [p for p in roster if (p.get("area") or "") == "qa"]
    return {p["name"].lower(): p["name"] for p in qa if p.get("name")}, {p["slack"]: p["name"] for p in qa if p.get("slack")}


def reply_link(thread, ts):
    """A reply's permalink from its thread's permalink and its ts."""
    m = re.match(r"^(https://\S+/archives/([CG][A-Z0-9]+))/p(\d+)", thread or "")
    if not m:
        return thread
    parent = m.group(3)[:10] + "." + m.group(3)[10:]
    return f"{m.group(1)}/p{ts.replace('.', '')}?thread_ts={parent}&cid={m.group(2)}"


def thread_verdicts(messages, qa_names):
    """[(at, key or row id, verdict, version, who, link)] from QA people's replies in the release threads."""
    out = []
    for m in messages:
        for r in m.get("replies") or []:
            who = r.get("user") or ""
            if who.lower() not in qa_names:
                continue
            for x in THREAD_VERDICT_RX.finditer(r.get("text") or ""):
                at = datetime.datetime.fromtimestamp(float(r["ts"])).astimezone().isoformat(timespec="minutes")
                out.append((at, x.group(1), x.group(2).lower(), " ".join(x.group(3).split()), qa_names[who.lower()],
                            reply_link(m.get("permalink"), r["ts"])))
    return out


# ── the list ─────────────────────────────────────────────────────────────────────────────────────────

def departs_soon(s, at):
    """Whether the next train leaves within one working day: the pending promotion's `departs` date, once the cadence
    records one; unknown (False) until then."""
    d = (B.read_pending(s) or {}).get("departs")
    try:
        day = datetime.date.fromisoformat(str(d)[:10])
    except ValueError:
        return False
    nxt = at.date() + datetime.timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += datetime.timedelta(days=1)
    return at.date() <= day <= nxt


def sprint_keys(s):
    try:
        sp = B.read_sprint(s.get("vault"), s.get("runtime"), datetime.date.today()).get("active") or {}
    except (OSError, ValueError, KeyError):
        return set()
    return {k for it in sp.get("items") or [] for k in it.get("keys") or []}


def priority(row, fields, sprint, builds_after, soon=False):
    """P1 a customer incident (a customer's bracket on the summary, a label or component), a re-test after a fail, a
    hotfix; P2 the sprint, Highest/High; P3 the rest. Two builds old lifts one level; so does a train leaving within a
    working day, for a row without a verdict. Everything on QA rides the next train, so riding it ranks nothing."""
    labels = " ".join([*(fields.get("labels") or []), *[c.get("name", "") for c in fields.get("components") or []]])
    prio = ((fields.get("priority") or {}).get("name") or "")
    parent = (fields.get("parent") or {}).get("key")
    t, summary = row["ticket"], fields.get("summary") or ""
    bracket = re.match(r"^\[([^\]]+)\]", summary)
    customer = bracket and not PREFIX_RX.match(summary)
    if t and (CUSTOMER_RX.search(labels) or customer or t.startswith("FB-") or parent == B.UMBRELLA):
        p, why = 1, f"customer incident ({bracket.group(1)})" if customer else "customer incident"
    elif row["verdict"] == "fail":
        p, why = 1, f"re-test: failed on {row.get('verdict_version') or '?'}"
    elif t and HOTFIX_RX.search(labels + " " + summary):
        p, why = 1, "hotfix"
    elif t and t in sprint:
        p, why = 2, "in the sprint"
    elif prio in ("Highest", "High"):
        p, why = 2, f"Jira {prio}"
    else:
        p, why = 3, "the rest"
    if builds_after >= 2 and p > 1:
        p, why = p - 1, f"{why}, {builds_after} builds old"
    if soon and p > 1 and row["verdict"] == "untested":
        p, why = p - 1, f"{why}, the train leaves within a working day"
    return f"P{p}", why


def collect_lane(lane, shown, mails, reports, s, env, cache, gaps, said=()):
    """One lane's list: the state brought up to the mails, every open row re-read, the state saved."""
    path = state_path(s, lane)
    st = load_state(path, lane)
    st["shown"] = shown = shown or st.get("shown") or lane
    if not st["builds"]:                                   # a new QA list starts after the newest build QA summarised;
        if is_qa(lane):                                    # a prod list, with the last release that reached it
            closed = [int(r["build"]) for r in reports if r["summary"] and r["build"]]
            st["seed_after"] = str(max(closed)) if closed else None
        elif len(mails) > 1:
            st["seed_after"] = mails[-2]["build"]
    floor = int(st.get("seed_after") or 0)
    first_seen = min((int(b) for b in st["builds"]), default=None)
    for b in mails:
        if b["build"] in st["builds"] or int(b["build"]) <= floor or (first_seen and int(b["build"]) < first_seen):
            continue
        st["builds"][b["build"]] = {"at": b["at"], "mail": b["id"], "subject": b["subject"], "label": b["label"]}
        for beh in behaviours(b):
            for k in beh["keys"]:
                jira_read(env, k, cache, gaps)
            owner = owner_of(beh["keys"], cache)
            text = " · ".join(beh["focus"]) or " · ".join(l["text"] for l in beh["log"])
            rid = owner or nt_id(beh["log"][0]["text"] if beh["log"] else text)
            left = st["left"].get(rid)
            if rid in st["rows"] or (left and int(left["first_build"]) >= int(b["build"])):
                if rid in st["rows"]:                       # named again: what QA said before this build no longer settles it
                    st["rows"][rid].update(builds=sorted(set(st["rows"][rid].get("builds", [])) | {b["build"]}, key=int),
                                           last_build=b["build"], last_at=b["at"])
                continue
            st["left"].pop(rid, None)
            layers = sorted({l["layer"] for l in beh["log"] if l["layer"]})
            st["rows"][rid] = {"id": rid, "ticket": owner, "also": [k for k in beh["keys"] if k != owner],
                               "focus": " · ".join(beh["focus"]) or None, "log": [l["text"] for l in beh["log"]],
                               "layers": layers, "first_build": b["build"], "first_at": b["at"], "builds": [b["build"]],
                               "last_build": b["build"], "last_at": b["at"],
                               "ela_saw": None}
    builds = sorted(st["builds"], key=int)
    st["lane_build"] = builds[-1] if builds else None
    qa, _ = T.qa_names()
    sprint = sprint_keys(s)
    soon = departs_soon(s, now()) and not B.R.lane_region(lane)    # China has no train of its own; the .com one ranks nothing there
    rows, at, drafts = [], now(), []
    for rid, r in list(st["rows"].items()):
        t = r["ticket"]
        issue = jira_read(env, t, cache, gaps) if t else None
        f = (issue or {}).get("fields") or {}
        if t and issue:
            res = ((f.get("resolution") or {}).get("name") or "")
            if WITHDRAWN_RX.search(res) or (f.get("status") or {}).get("name") in ("Cancelled",):
                st["left"][rid] = dict(r, left_at=at.isoformat(timespec="minutes"), why=f"withdrawn: {res or 'Cancelled'}")
                del st["rows"][rid]
                continue
        title = f.get("summary") or (r["log"][0] if r["log"] else r.get("focus") or "")
        pre = PREFIX_RX.match(title or "")
        layer = "+".join(r["layers"]) or (pre.group(1) if pre else "—")
        how = r.get("focus") or (acceptance(issue) if issue else None) or "steps unknown"
        found = []
        for k in [t, *r.get("also", [])] if t else []:
            found += comment_verdicts(cache.get(k) or (jira_read(env, k, cache, gaps) if k != t else issue), qa, r.get("last_at") or r["first_at"])
            found += report_verdicts(reports, k, r.get("last_at") or r["first_at"], r.get("last_build") or r["first_build"])
        for at_, k, v, ver, who, url in said:              # a QA member's reply in the list's thread, first-hand
            if k in ([t, *r.get("also", [])] if t else [rid]) and at_ >= (r.get("last_at") or r["first_at"])[:16]:
                found.append((at_, v, ver, f"release thread by {who}"))
                if t and (t, url) not in {tuple(d) for d in st.setdefault("drafted", [])}:
                    st["drafted"].append([t, url])
                    drafts.append({"tier": 1, "rule": "fact-comment", "key": t, "evidence": url,
                                   "command": f'ela jira comment {t} --text "QA reported {v} on {ver} in the release thread {url}"'})
        if not t:                                           # a change with no ticket has no verdict of its own; QA's
            summ = [x for x in reports if x["summary"] and x["build"] and int(x["build"]) >= int(r.get("last_build") or r["first_build"])]
            if summ:                                        # summary report on its build closes the round it rode in
                found.append((summ[-1]["at"][:16], "n-a", f"build {summ[-1]['build']}", "QA summary report"))
        found.sort()
        verdict, vv, vd, vs = ("untested", None, None, None) if not found else (found[-1][1], found[-1][2], found[-1][0][:10], found[-1][3])
        after = [b for b in builds if int(b) > int(r["first_build"])]
        row = {"kind": "version", "id": rid, "ticket": t, "url": JIRA_URL + t if t else None, "also": r.get("also", []), "title": title,
               "layer": layer, "first_build": r["first_build"], "lane_build": st["lane_build"], "how_to_verify": how,
               "auto": auto_of(f"{title} {how}", bool(t)), "verdict": verdict, "verdict_version": vv, "verdict_date": vd,
               "verdict_source": vs, "age_days": (at - datetime.datetime.fromisoformat(r["first_at"])).days if r.get("first_at") else None,
               "ela_saw": r.get("ela_saw"), "flag": None if t else "no ticket", "status": (f.get("status") or {}).get("name"),
               "assignee": J.name_of(f.get("assignee")) if f.get("assignee") else None}
        row["priority"], row["priority_reason"] = priority(row, f, sprint, len(after), soon)
        if verdict in ("pass", "n-a"):
            st["left"][rid] = dict(r, left_at=at.isoformat(timespec="minutes"), why=f"{verdict} on {vv} ({vd}, {vs})")
            del st["rows"][rid]
            continue
        st["rows"][rid].update(title=title, verdict=verdict, verdict_version=vv, verdict_date=vd,
                               priority=row["priority"], priority_reason=row["priority_reason"])
        rows.append(row)
    rows.sort(key=lambda r: (r["priority"], r["verdict"] != "fail", -(r["age_days"] or 0), r["id"]))
    for n, r in enumerate(rows, 1):                         # the order Helm renders, on the row and in the state file
        r["rank"] = st["rows"][r["id"]]["rank"] = n
    envs = env_rows(lane, st, s, env, reports, cache, gaps, sprint, at)
    st["updated"] = at.isoformat(timespec="minutes")
    save(path, json.dumps(st, ensure_ascii=False, indent=1))
    recent = (at - datetime.timedelta(days=7)).isoformat()
    left = [dict(v, id=k) for k, v in st["left"].items() if (v.get("left_at") or "") >= recent]
    return {"lane": lane, "shown": shown, "kind": "qa" if is_qa(lane) else "release check", "lane_build": st["lane_build"],
            "lane_label": (st["builds"].get(st["lane_build"]) or {}).get("label") or st["lane_build"],
            "generated": at.isoformat(timespec="minutes"), "builds": {b: st["builds"][b] for b in builds}, "rows": rows, "env": envs,
            "left": left, "gaps": [f"{g['source']}: {g['error']}" for g in gaps], "departs_soon": soon, "path": path,
            "drafts": drafts}


# ── environment rows: a problem on a lane that no build carries ──────────────────────────────────────

ENV_LABEL = "env:"
# a QA report line about the environment rather than a behaviour: a fault word, a problem word, and no ticket key
ENV_FAULT_RX = re.compile(r"\b(dns|domain|certificate|cert|config(?:uration)?|propert(?:y|ies)|network|firewall|proxy|nginx|etcd|"
                          r"powerjob|vendor|permission|quota|deploy(?:ment|ed)?)\b|\u57df\u540d|\u8bc1\u4e66|\u73af\u5883\u914d\u7f6e|"
                          r"\u914d\u7f6e\u4e2d\u5fc3|\u7f51\u7edc|\u9632\u706b\u5899|\u90e8\u7f72|\u6743\u9650|\u4e91\u5382\u5546", re.I)
# 域名 证书 环境配置 配置中心 网络 防火墙 部署 权限 云厂商; never a bare 配置, which in MediaHub is mostly an encoding profile (编码配置)
PROBLEM_RX = re.compile(r"\b(fail\w*|error|cannot|can't|missing|wrong|mismatch|unreachable|timeout|down)\b|\u5931\u8d25|\u4e0d\u901a|"
                        r"\u5f02\u5e38|\u9519\u8bef|\u65e0\u6cd5|\u62c9\u4e0d\u5230|\u672a\u751f\u6548", re.I)   # 失败 不通 异常 错误 无法 拉不到 未生效
ENV_RECENT_DAYS = 7


def env_owner(lane, roster=None):
    """The environment's owner: the roster responsibility that owns env:<lane>, else "unowned"."""
    try:
        if roster is None:
            import team as TM  # noqa: E402
            roster = TM.read_roster(TM.records())[1]
    except (SystemExit, ImportError, OSError, ValueError):
        roster = []
    return next((p["name"] for p in roster for r in p.get("responsibilities") or [] if ENV_LABEL + lane in (r.get("owns") or [])),
                "unowned")


def env_report_lines(report):
    """A report's Test Result lines that name the environment, not a behaviour: [text]."""
    body = report["text"].split("Test Result", 1)[-1] if "Test Result" in report["text"] else ""
    return [" ".join(l.split())[:200] for l in body.splitlines()
            if not l.lstrip().startswith(">") and ENV_FAULT_RX.search(l) and PROBLEM_RX.search(l) and not B.keys_in(l)]


def env_found(lane, s, env, reports, cache, gaps):
    """This run's environment problems on a lane, by source: ({id: {source, title, ticket, since}}, {sources read}).
    lane: a China lane's services that differ from the lane it aligns with (region_reading, the lanes page's own);
    label: tickets labelled env:<lane>, open or resolved in the last week; qa: the newest QA report's lines naming the
    environment. A source not read resolves nothing."""
    found, read = {}, set()
    if B.R.lane_region(lane):
        runner = os.path.join(s.get("runtime") or os.path.join(s.get("projects", ""), ".ela"), "runner")
        try:
            tested = json.load(open(os.path.join(runner, "qa-tested.json")))
            snaps = B.lane_reads(runner)
            g = B.region_reading(lane, tested, snaps[-1][2] if snaps else [])
            if snaps:
                read.add("lane")
            for d in g["differences"]:
                found[f"diff-{d['service']}"] = {"source": "lane", "ticket": None, "since": (g["at"] or "")[:10] or None,
                                                 "title": f"{d['service']} {d['version']} here, {d['reference']} on {g['aligns_with']}"
                                                          + (f" ({d['behind']} builds behind)" if d["behind"] else "")}
        except (OSError, ValueError) as x:
            gaps.append({"source": "lane differences", "error": str(x)[:200]})
    try:
        got = B.run_json(["python3", B.JIRA, *env, "jql", f'project = MH AND labels = "{ENV_LABEL}{lane}" AND '
                          f'(statusCategory != Done OR resolved >= -{ENV_RECENT_DAYS}d) ORDER BY key', "--limit", "50", "--json"], timeout=120)["issues"]
        read.add("label")
        for i in got:
            found[i["key"]] = {"source": "label", "ticket": i["key"], "title": i["summary"], "since": (i.get("created") or "")[:10] or None}
    except (B.LaneError, subprocess.TimeoutExpired, ValueError) as x:
        gaps.append({"source": f"jira {ENV_LABEL}{lane}", "error": str(x)[:200]})
    newest = max(reports, key=lambda r: r["at"] or "", default=None)
    if newest:
        read.add("qa")
        for line in env_report_lines(newest):
            found["qa-" + hashlib.sha1(line.encode()).hexdigest()[:8]] = {"source": "qa", "ticket": None, "title": line,
                                                                         "since": (newest["at"] or "")[:10] or None}
    return found, read


def env_rows(lane, st, s, env, reports, cache, gaps, sprint, at):
    """The lane's environment rows (kind env), kept in its state file under "env": open while a source still names
    it, resolved on the day it stops (a ticket: its resolution date). Open rows, and those resolved this week."""
    found, read = env_found(lane, s, env, reports, cache, gaps)
    kept, today = st.setdefault("env", {}), at.date().isoformat()
    for k, f in found.items():
        issue = jira_read(env, f["ticket"], cache, gaps) if f["ticket"] else None
        fields = (issue or {}).get("fields") or {}
        done = ((fields.get("status") or {}).get("statusCategory") or {}).get("key") == "done"
        was = kept.get(k) or {}
        kept[k] = dict(was, id=k, source=f["source"], ticket=f["ticket"], title=fields.get("summary") or f["title"],
                       since=was.get("since") or f["since"] or today, state="resolved" if done else "open",
                       resolved=(fields.get("resolutiondate") or today)[:10] if done else None)
    for k, r in kept.items():
        if k not in found and r["state"] == "open" and r["source"] in read:
            r.update(state="resolved", resolved=today)
    owner, recent = env_owner(lane), (at - datetime.timedelta(days=ENV_RECENT_DAYS)).date().isoformat()
    rows = []
    for r in kept.values():
        if r["state"] == "resolved" and (r["resolved"] or "") < recent:
            continue
        issue = cache.get(r["ticket"]) if r["ticket"] else None
        row = {"kind": "env", "id": r["id"], "lane": lane, "ticket": r["ticket"], "url": JIRA_URL + r["ticket"] if r["ticket"] else None,
               "also": [], "title": r["title"], "source": r["source"], "since": r["since"], "owner": owner, "state": r["state"],
               "resolved": r["resolved"], "verdict": f"resolved on {lane} {r['resolved']}" if r["state"] == "resolved" else "open"}
        row["priority"], row["priority_reason"] = priority(dict(row, verdict="untested"), (issue or {}).get("fields") or {}, sprint, 0)
        rows.append(row)
    rows.sort(key=lambda r: (r["state"] != "open", r["priority"], r["since"] or "", r["id"]))
    return rows


def collect(a, s, env):
    """Every lane's list, or the one --lane names: [out], and the gaps that belong to no lane."""
    want = lane_name(a.lane)[0] if a.lane else None
    days = a.days or 21
    try:
        by_lane = release_mails(env, days)
    except (B.LaneError, subprocess.TimeoutExpired, ValueError) as x:
        print(f"release mails not read: {str(x)[:200]}", file=sys.stderr)
        sys.exit(EX_REMOTE)
    gaps = []
    try:
        reports = report_mails(env, days)
    except (B.LaneError, subprocess.TimeoutExpired, ValueError) as x:
        reports = {}
        gaps.append(f"QA report mails: {str(x)[:200]}")
    unmapped = by_lane.pop(None, None)
    if unmapped:
        gaps.append("release mails for an environment no lane name maps: " + ", ".join(sorted(unmapped["shown"])))
    kept = {re.match(r"^test-list-(.+)\.json$", f).group(1) for f in os.listdir(os.path.join(reports_root(s), "lanes"))
            if re.match(r"^test-list-(.+)\.json$", f)} if os.path.isdir(os.path.join(reports_root(s), "lanes")) else set()
    lanes = [want] if want else sorted(set(by_lane) | kept)
    cache, outs = {}, []
    keys = {k for lane in lanes for b in (by_lane.get(lane) or {}).get("mails", []) for l in b["log"] + b["focus"] for k in l["keys"]}
    for lane in lanes:
        st = load_state(state_path(s, lane), lane)
        keys |= {k for r in st["rows"].values() for k in [r.get("ticket"), *r.get("also", [])] if k}
    prefetch(env, sorted(keys), cache, gaps)
    said = []
    if any(is_qa(l) for l in lanes):                       # QA's replies in the release threads the lists are posted to
        errs = []
        msgs = B.slack_rows(env, B.QA_RELEASE, (now() - datetime.timedelta(days=7)).date().isoformat(), errs)
        gaps += [f"{g['source']}: {g['error']}" for g in errs]
        said = thread_verdicts(msgs, qa_people()[0])
    for lane in lanes:
        got = by_lane.get(lane) or {}
        lgaps = []
        out = collect_lane(lane, got.get("shown") or (lane_name(a.lane)[1] if want else None), got.get("mails") or [],
                           reports.get(lane) or [], s, env, cache, lgaps, said if is_qa(lane) else ())
        outs.append(out)
    return outs, gaps


# ── output ───────────────────────────────────────────────────────────────────────────────────────────

MARK = {"pass": "✅", "fail": "❌", "untested": "·"}


def link(r):
    return f"[{r['ticket']}]({r['url']})" + "".join(f" / [{k}]({JIRA_URL}{k})" for k in r["also"]) if r["ticket"] else "**no ticket**"


def cell(text, n=220):
    t = " ".join(str(text or "").split()).replace("|", "\\|")
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + " …"


def short(text, n=60):
    """One line of at most n characters, cut with … (a CJK title has no space to cut at)."""
    t = " ".join(str(text or "").split()).replace("|", "\\|")
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


_ROSTER = None


def page_name(name):
    """A Jira display name as the roster writes it (its name, matched on the name or jira_name); unknown, as it came."""
    global _ROSTER
    if not name:
        return None
    if _ROSTER is None:
        try:
            import team as TM  # noqa: E402
            _ROSTER = {n.lower(): p["name"] for p in TM.read_roster(TM.records())[1]
                       for n in (p.get("name"), p.get("jira_name")) if n and p.get("name")}
        except (SystemExit, ImportError, OSError, ValueError):
            _ROSTER = {}
    return _ROSTER.get(name.lower(), name)


def callout(name, what, lines):
    """A folded Obsidian callout: closed until opened, so the sheet above stays one screen."""
    return ["", f"> [!note]- {name} · {what}"] + [f"> {l}" if l else ">" for l in lines]


def render_page(out):
    at = datetime.datetime.fromisoformat(out["generated"])
    unit = "build" if out["kind"] == "qa" else "release"
    L = ["# Test list · " + out["shown"], "", f"*{at:%Y-%m-%d %H:%M} · lane {out['lane']} · {unit} {out['lane_label'] or '?'} now*", "",
         ("" if out["kind"] == "qa" else "A release check: the tickets the last train or hotfix carried to this prod lane, "
          "verified on the lane (QA's smoke comment, or ela's read-only browser check). ") +
         f"What QA should verify on {out['shown']}, highest priority first. One row per behaviour; a row stays until it has a "
         "verdict (QA's ticket comment with version and pass/fail, or the report mail) or its ticket is withdrawn. "
         "*ela saw* is a read-only browser check overnight; QA's verdict overrules it.", "",
         f"{len(out['rows'])} open · " + " · ".join(f"{p} {sum(r['priority'] == p for r in out['rows'])}" for p in ("P1", "P2", "P3"))
         + f" · {sum(r['auto'] for r in out['rows'])} auto · {sum(not r['ticket'] for r in out['rows'])} no ticket", "",
         "| P | ticket | title | status | assignee | verdict | builds | auto |", "|---|---|---|---|---|---|---|---|"]
    notes = []
    for r in out["rows"]:
        v = MARK.get(r["verdict"], "·") + (f" {r['verdict']} {r['verdict_version'] or ''}".rstrip() if r["verdict"] != "untested" else " untested")
        L.append(f"| {r['priority']} | {link(r) if r['ticket'] else 'no ticket'} | {short(r['title'])} | "
                 f"{(r.get('status') or '—') if r['ticket'] else '—'} | {page_name(r.get('assignee')) or '—'} | {v} | "
                 f"{r['first_build']} → {r['lane_build']} | {'yes' if r['auto'] else '–'} |")
        saw = (r.get("ela_saw") or {}).get("line")
        if r["how_to_verify"] == "steps unknown" and not saw:
            continue
        notes += callout(r["ticket"] or f"no ticket: {short(r['title'], 40)}", "how to verify",
                         [f"**{r['priority']}** {r['priority_reason']} · layer {r['layer']} · {r['age_days'] if r['age_days'] is not None else '?'}d on the list", "",
                          " ".join(str(r["how_to_verify"]).split())] + (["", f"*ela saw*: {' '.join(saw.split())}"] if saw else []))
    L += notes
    L += env_section(out.get("env") or [])
    if out["left"]:
        L += ["", "## Left the list this week", ""]
        for r in sorted(out["left"], key=lambda r: r.get("left_at") or ""):
            name = f"[{r['ticket']}]({JIRA_URL}{r['ticket']})" if r.get("ticket") else "no ticket"
            L.append(f"- {name} {cell(r.get('title') or (r.get('log') or [''])[0], 90)} — {r.get('why')}, {(r.get('left_at') or '')[:10]}")
    L += ["", f"## {unit.capitalize()}s", ""] + [f"- {unit} {v.get('label') or b} · {(v.get('at') or '')[:16].replace('T', ' ')} · "
                                                 f"{v.get('subject')}" for b, v in sorted(out["builds"].items(), key=lambda kv: -int(kv[0]))[:6]]
    if out["gaps"]:
        L += ["", "## Not read", ""] + [f"- {g[:200]}" for g in out["gaps"]]
    L += ["", "*Priority: P1 a customer incident, a re-test after a fail, a hotfix · P2 the sprint, Jira Highest/High · "
          "P3 the rest · a row two builds older than the lane moves up one, and so does an untested row when the train "
          "leaves within a working day. Generated by `ela testlist --lane "
          f"{out['lane']} --page`.*"]
    return "\n".join(L) + "\n"


ENV_SOURCE = {"lane": "differs from the aligned lane", "label": "ticket labelled env:", "qa": "QA report"}


def env_section(rows):
    """Environment, not code: the problems on a lane that no build carries; nobody is asked to fix one in code."""
    if not rows:
        return []
    L = ["", "## Environment, not code", "", "Problems of the environment itself — a version that differs from the lane it "
         "aligns with, a config, DNS or region difference, an infra fault. No build carries them; the environment's owner "
         "resolves them.", "", "| | what | source | since | owner | state |", "|---|---|---|---|---|---|"]
    for r in rows:
        what = (f"[{r['ticket']}]({r['url']}) " if r["ticket"] else "") + cell(r["title"], 120)
        L.append(f"| **{r['priority']}** {cell(r['priority_reason'], 40)} | {what} | {ENV_SOURCE.get(r['source'], r['source'])} | "
                 f"{r['since'] or '?'} | {r['owner']} | {r['verdict']} |")
    return L


OWN_POSTERS = re.compile(r"^(helm|ela)$", re.I)          # ela's own posts name lanes too; they never make a thread a lane's


def lane_rx(lane):
    """The words a release thread uses for a lane: its mail tag (QA-AWS3) and the build bot's shorthand (QA3, qa2)."""
    shown = lane_name(lane)[1]
    n = re.fullmatch(r"qa-cn(\d+)", lane)
    alts = [re.escape(shown)] + ([rf"qa[-_ ]?(?:aws[-_ ]?)?{n.group(1)}"] if n else [])
    return re.compile(r"\b(?:" + "|".join(alts) + r")\b", re.I | re.A)


def pick_thread(messages, date, lane, build=None):
    """The release thread for `lane` among the channel's roots on `date`: one whose root or a reply (ela's own aside)
    names the lane; of those, one that names the build (`build 79`, `v2.0.11`), else the latest. None when no thread
    names the lane: the day's `<date>_Release` thread belongs to whichever lane it says, not to every lane."""
    rx = lane_rx(lane)
    brx = re.compile(rf"(?:build\s*|v){re.escape(str(build))}(?![\d.]*\d)", re.I) if build else None
    hits = []
    for m in messages:
        ts = m.get("ts")
        if not ts or datetime.datetime.fromtimestamp(float(ts)).astimezone().date().isoformat() != date:
            continue
        text = "\n".join(x.get("text") or "" for x in [m, *(m.get("replies") or [])] if not OWN_POSTERS.match(x.get("user") or ""))
        if rx.search(text):
            hits.append((bool(brx and brx.search(text)), float(ts), m.get("permalink")))
    return max(hits)[2] if hits else None


def release_thread(env, date, lane, build, gaps):
    """The lane's release thread on `date` in #mediahub-qa-release (pick_thread), or None."""
    try:
        return pick_thread(B.slack_rows(env, B.QA_RELEASE, date, gaps), date, lane, build)
    except Exception as x:  # noqa: BLE001 — a missing thread is a skipped post, never a failed list
        gaps.append({"source": "slack release thread", "error": str(x)[:200]})
    return None


def slack_text(out, build, rows):
    head = f"*Test list · {out['shown']} {'build' if out['kind'] == 'qa' else 'release'} {build}* — {len(rows)} new row(s), highest priority first. Verdicts go in the ticket comment (version + pass/fail), or as a reply here: `MH-1234 pass on 2.1.78` (a no-ticket row by its `nt-` id)."
    lines = [head]
    for r in rows:
        name = f"<{r['url']}|{r['ticket']}>" + "".join(f" / <{JIRA_URL}{k}|{k}>" for k in r["also"]) if r["ticket"] else f"*no ticket* ⚠ `{r['id']}`"
        lines.append(f"• *{r['priority']}* ({r['priority_reason']}) {name} {cell(r['title'], 80)}\n    how: {cell(r['how_to_verify'], 260)}"
                     + ("  · ela checks it in the browser overnight" if r["auto"] else ""))
    return "\n".join(lines)


def new_rows(out, env, date):
    builds, gaps = [], []
    for b, v in sorted(out["builds"].items(), key=lambda kv: int(kv[0])):
        if (v.get("at") or "")[:10] != date:
            continue
        rows = [r for r in out["rows"] if r["first_build"] == b]
        if not rows:
            continue
        if out["kind"] == "qa":                             # QA builds have the day's thread in the QA release channel
            thread = release_thread(env, date, out["lane"], v.get("label") or b, gaps)
        builds.append({"lane": out["lane"], "shown": out["shown"], "build": v.get("label") or b, "mail_at": v.get("at"),
                       "thread": thread if out["kind"] == "qa" else None, "channel": B.QA_RELEASE if out["kind"] == "qa" else None,
                       "text": slack_text(out, v.get("label") or b, rows), "rows": [r["id"] for r in rows]})
    out["gaps"] += [f"{g['source']}: {g['error']}" for g in gaps]
    return builds


def cmd_saw(a, s):
    lane, _ = lane_name(a.lane)
    path = state_path(s, lane)
    st = load_state(path, lane)
    key, line = a.saw
    row = st["rows"].get(key) or next((r for r in st["rows"].values() if key in r.get("also", [])), None)
    if not row:
        print(f"no open row {key} on {lane}", file=sys.stderr)
        sys.exit(EX_NOROW)
    row["ela_saw"] = {"line": line, "lane_build": st.get("lane_build"), "at": now().isoformat(timespec="minutes")}
    save(path, json.dumps(st, ensure_ascii=False, indent=1))
    print(f"{row['id']}: ela_saw written on build {st.get('lane_build')}")


# ── QA today: the day's plan cut from the list ───────────────────────────────────────────────────────

TODAY_BUDGET = 10
OVERNIGHT_CHANNELS = (B.QA_RELEASE, B.DEV_CHANNEL)
GUIDE_RX = re.compile(r"^\s*ela:\s*(.+)$", re.I)


def last_evening(at):
    """The last evening run before `at`: 19:00 on the previous working day."""
    d = at.date() - datetime.timedelta(days=1)
    while not B.is_working_day(d):
        d -= datetime.timedelta(days=1)
    return datetime.datetime.combine(d, datetime.time(19, 0)).astimezone()


BOT_RX = re.compile(r"bot$|^helm$|^slackbot$", re.I)


def owner_names():
    """The owner's names as Slack shows them (roster entry of site.json emails.me), lower."""
    try:
        import team as TM  # noqa: E402
        me = (site().get("emails") or {}).get("me")
        return {n.lower() for p in TM.read_roster(TM.records())[1] if p.get("email") == me
                for n in (p.get("name"), p["email"].split("@")[0]) if n}
    except (SystemExit, ImportError, OSError, ValueError):
        return set()


def overnight(env, since, who):
    """Posts in the team channels since `since` and the ones addressed to `who` ({name lower or slack id: name}):
    {posts, channels, not_read, asks: [{to, by, channel, text, link}]}. A channel the bot cannot read is not_read."""
    posts, read, not_read, asks = 0, [], [], []
    for ch in OVERNIGHT_CHANNELS:
        errs = []
        msgs = B.slack_rows(env, ch, since.date().isoformat(), errs)
        if errs:
            not_read.append(ch)
            continue
        read.append(ch)
        for m in msgs:
            items = [(m, m.get("permalink"))] + [(r, reply_link(m.get("permalink"), r["ts"])) for r in m.get("replies") or []]
            for x, link_ in items:
                ts = x.get("ts")
                if not ts or datetime.datetime.fromtimestamp(float(ts)).astimezone() < since:
                    continue
                posts += 1
                text = x.get("text") or ""
                to = sorted({name for k, name in who.items() if f"<@{k}>" in text or re.search(r"@" + re.escape(k) + r"\b", text, re.I)})
                by = (x.get("user") or "")
                if to and by.lower() not in who and not BOT_RX.search(by) and by.lower() not in owner_names():
                    asks.append({"to": to, "by": by, "channel": ch, "text": " ".join(text.split())[:200], "link": link_,
                                 "thread": m.get("permalink")})
    return {"posts": posts, "channels": read, "not_read": not_read, "asks": asks}


def apply_guidance(plan, lines, out):
    """His `ela:` lines under QA today or under a lane note's rows: `drop KEY`, `KEY first`, `add KEY [why]`, `KEY P1|P2|P3`
    (the row takes that priority and moves ahead of the first row ranked below it); anything else is returned unread."""
    unread = []
    for raw in lines:
        g = GUIDE_RX.match(raw)
        text = (g.group(1) if g else raw).strip()
        if not text:
            continue
        keys = B.keys_in(text) or re.findall(r"\bnt-[0-9a-f]{8}\b", text)
        if not keys:
            unread.append(text); continue
        if re.search(r"\b(drop|skip|remove|not today)\b", text, re.I):
            plan[:] = [p for p in plan if p["id"] not in keys and p.get("ticket") not in keys]
        elif re.search(r"\b(first|top|up)\b", text, re.I):
            hit = [p for p in plan if p["id"] in keys or p.get("ticket") in keys]
            plan[:] = hit + [p for p in plan if p not in hit]
            for p in hit:
                p["reason"] = "first, on your word; " + p["reason"]
        elif re.search(r"\bP[123]\b", text, re.I):
            to = re.search(r"\bP([123])\b", text, re.I).group(0).upper()
            rank = lambda p: p["priority"] if re.fullmatch(r"P[123]", str(p["priority"])) else "P9"  # noqa: E731
            for p in [p for p in plan if p["id"] in keys or p.get("ticket") in keys]:
                plan.remove(p)
                p["priority"], p["reason"] = to, f"{to} on your word; " + p["reason"]
                at = next((i for i, q in enumerate(plan) if rank(q) > to), len(plan))
                plan.insert(at, p)
        elif re.search(r"\badd\b", text, re.I):
            for k in keys:
                if not any(p.get("ticket") == k or p["id"] == k for p in plan):
                    row = next((r for r in out["rows"] if r["ticket"] == k or r["id"] == k), None)
                    plan.insert(0, dict(plan_row(row, "added on your word") if row else {"id": k, "ticket": k, "url": JIRA_URL + k,
                                        "title": "", "priority": "—", "how_to_verify": "", "auto": False, "reason": "added on your word"}))
        else:
            unread.append(text)
    return unread


def plan_row(r, reason):
    return {"id": r["id"], "ticket": r["ticket"], "url": r["url"], "also": r.get("also", []), "title": r["title"],
            "priority": r["priority"], "how_to_verify": r["how_to_verify"], "auto": r["auto"], "ela_saw": r.get("ela_saw"),
            "reason": reason}


def qa_today(out, env, at, budget, guidance, gaps):
    """The day's plan: carried rows without a verdict (P1 first, oldest first), then the newest build's new rows, then
    interruptions (tickets assigned to QA in no build, asks to QA in the team channels since the last evening run),
    his `ela:` lines applied, cut at the budget."""
    newest = out["lane_build"]
    rank = lambda r: (r["priority"], -(r["age_days"] or 0), r["id"])  # noqa: E731
    carried = sorted((r for r in out["rows"] if r["first_build"] != newest), key=rank)
    new = sorted((r for r in out["rows"] if r["first_build"] == newest), key=rank)
    plan = [plan_row(r, f"carried {r['age_days']}d: {r['verdict'] if r['verdict'] == 'fail' else r['priority_reason']}") for r in carried]
    plan += [plan_row(r, f"new in {out['lane_label']}: {r['priority_reason']}") for r in new]
    names, ids = qa_people()
    on_list = {k for r in out["rows"] for k in [r["ticket"], *r.get("also", [])] if k}
    try:
        accounts = qa_accounts()
        if accounts:
            got = B.run_json(["python3", B.JIRA, *env, "jql", f"assignee in ({', '.join(accounts)}) AND statusCategory != Done "
                              "ORDER BY priority DESC, updated DESC", "--limit", "50", "--json"], timeout=120)["issues"]
            plan += [{"id": i["key"], "ticket": i["key"], "url": JIRA_URL + i["key"], "also": [], "title": i["summary"],
                      "priority": "—", "how_to_verify": "", "auto": False, "ela_saw": None,
                      "reason": f"assigned to {i.get('assignee')} ({i['status']}), in no build"}
                     for i in got if i["key"] not in on_list]
    except (B.LaneError, subprocess.TimeoutExpired, ValueError) as x:
        gaps.append(f"jira QA assignments: {str(x)[:160]}")
    since = last_evening(at)
    night = overnight(env, since, {**names, **ids})
    for ask in night["asks"]:
        keys = B.keys_in(ask["text"])
        plan.append({"id": keys[0] if keys else ask["link"], "ticket": keys[0] if keys else None,
                     "url": JIRA_URL + keys[0] if keys else ask["link"], "also": [], "title": ask["text"][:120], "priority": "—",
                     "how_to_verify": "", "auto": False, "ela_saw": None,
                     "reason": f"ask from {ask['by']} to {', '.join(ask['to'])} in #{ask['channel']}"})
    unread = apply_guidance(plan, guidance, out)
    seen, cut = set(), []
    for p in plan:                                          # one row per ticket, the first reason kept
        if p["id"] not in seen:
            seen.add(p["id"]); cut.append(p)
    night["placed"] = sum(1 for p in cut[:budget] if p["reason"].startswith("ask from"))
    return {"rows": cut[:budget], "more": max(0, len(cut) - budget), "overnight": night, "since": since.isoformat(timespec="minutes"),
            "guidance_unread": unread}


def qa_accounts():
    try:
        import team as TM  # noqa: E402
        roster = TM.read_roster(TM.records())[1]
    except (SystemExit, ImportError, OSError, ValueError):
        return []
    return [f'"{p["jira"]}"' for p in roster if (p.get("area") or "") == "qa" and p.get("jira")]


def today_text(out, plan, at):
    L = [f"*QA today · {out['shown']} · {at:%a %m-%d}* — {out['lane_label']} on the lane. In this order; a verdict goes in the "
         "ticket comment (version + pass/fail) or as a reply here: `MH-1234 pass on 2.1.78`."]
    for n, p in enumerate(plan["rows"], 1):
        name = (f"<{p['url']}|{p['ticket']}>" if p["ticket"] else f"*no ticket* `{p['id']}`") + "".join(f" / <{JIRA_URL}{k}|{k}>" for k in p.get("also") or [])
        saw = f"\n    ela saw: {(p['ela_saw'] or {}).get('line')}" if p.get("ela_saw") else ""
        how = f"\n    how: {cell(p['how_to_verify'], 200)}" if p.get("how_to_verify") else ""
        L.append(f"{n}. *{p['priority']}* {name} {cell(p['title'], 80)} — {p['reason']}{how}{saw}")
    if plan["more"]:
        L.append(f"+{plan['more']} more on the lane's list.")
    return "\n".join(L)


def print_list(out, page):
    print(f"# test list · {out['shown']} ({out['lane']}) · {out['lane_label']} · {len(out['rows'])} open")
    for r in out["rows"]:
        print(f"  {r['priority']} {(r['ticket'] or 'no ticket'):<10} {r['layer']:<7} {'auto' if r['auto'] else '    '} "
              f"{r['verdict']:<8} {r['first_build']}→{r['lane_build']} {str(r['age_days']) + 'd':>4}  {cell(r['title'], 60)}  · {r['priority_reason']}")
    for r in out.get("env") or []:
        print(f"  env {r['priority']} {(r['ticket'] or r['source']):<10} {r['verdict']:<28} since {r['since']}  {cell(r['title'], 60)}  · {r['owner']}")
    for r in out["left"]:
        print(f"  left: {r.get('ticket') or r['id']} — {r.get('why')}")
    for g in out["gaps"]:
        print(f"  not read: {g[:120]}")
    if page:
        print(f"page: {out['page']}")


def cmd_list(a):
    s = site()
    if a.saw:
        if not a.lane:
            print("--saw needs --lane", file=sys.stderr)
            sys.exit(EX_USAGE)
        return cmd_saw(a, s)
    env = ["--env-file", a.env_file] if a.env_file else []
    outs, gaps = collect(a, s, env)
    if a.today:
        at = now()
        guidance = open(a.guidance, encoding="utf-8").read().splitlines() if a.guidance else []
        plans = []
        for out in (o for o in outs if o["kind"] == "qa"):
            plan = qa_today(out, env, at, a.budget, guidance, gaps)
            b = out["builds"].get(out["lane_build"]) or {}
            errs = []
            thread = release_thread(env, b["at"][:10], out["lane"], b.get("label") or out["lane_build"], errs) if b.get("at") else None
            plans.append({"date": at.date().isoformat(), "lane": out["lane"], "shown": out["shown"], "lane_build": out["lane_build"], "thread": thread,
                          "channel": B.QA_RELEASE, "post": "thread" if thread else "day post", "text": today_text(out, plan, at), **plan,
                          "gaps": out["gaps"] + [f"{g['source']}: {g['error']}" for g in errs]})
        if a.json:
            print(json.dumps(plans[0] if a.lane and plans else {"lists": plans, "gaps": gaps}, ensure_ascii=False))
        else:
            for p in plans:
                print(f"# {p['lane']} → {p['thread'] or 'no thread for ' + p['shown'] + '; the day post in #' + p['channel']}\n{p['text']}\n")
                o = p["overnight"]
                print(f"Overnight: {o['posts']} posts read in {', '.join('#' + c for c in o['channels']) or 'no channel'}, "
                      f"{o['placed']} asks placed above" + (f"; not read: {', '.join('#' + c for c in o['not_read'])}" if o["not_read"] else ""))
        return
    for out in outs:
        if a.page:
            out["page"] = os.path.join(reports_root(s), "lanes", f"test-list-{out['lane']}.md")
            save(out["page"], render_page(out))
    if a.new_rows:
        builds = [b for out in outs for b in new_rows(out, env, a.date or now().date().isoformat())]
        gaps += [g for out in outs for g in out["gaps"]]
        if a.json:
            print(json.dumps({"lane": outs[0]["lane"], "builds": builds, "gaps": gaps} if a.lane else {"builds": builds, "gaps": gaps},
                             ensure_ascii=False))
        else:
            for b in builds:
                print(f"# {b['lane']} {b['build']} → {b['thread'] or 'no thread for ' + b['shown']}\n{b['text']}\n")
            print(f"{len(builds)} build(s) with new rows")
        return
    if a.json:
        if a.lane:
            outs[0]["gaps"] += gaps
            print(json.dumps(outs[0], ensure_ascii=False))
        else:
            print(json.dumps({"lists": outs, "gaps": gaps}, ensure_ascii=False))
        return
    for out in outs:
        print_list(out, a.page)
    for g in gaps:
        print(f"not read: {g[:160]}")

# ── the dev list ─────────────────────────────────────────────────────────────────────────────────────

# a checkout under <code> → the layer that builds it, for a ticket whose summary carries no [Layer] prefix
REPO_LAYERS = (("web/media-hub-front", "UI"), ("web/mx-service-front", "UI"), ("web/tvu-media-hub", "App"),
               ("web/mx-service", "UR"), ("web/ur-streaming", "UR"), ("mx/", "J2N"), ("media/", "Media"))
DEV_STATUSES = ("In Progress", "Review", "Blocked", "On Hold", "Reopened")
COMMIT_DAYS = 60


def branch_state(commits, led_lanes):
    """on <lanes> · merged to release · on a branch · no commit."""
    if led_lanes:
        return "on " + ", ".join(sorted(led_lanes))
    if any(re.match(r"release", c["ref"]) for c in commits):
        return "merged to release"
    return "on a branch" if commits else "no commit"


def held_by(status, fields):
    """The reason word a ticket is held: an open ticket it is blocked by, else its status Blocked or On Hold."""
    for l in fields.get("issuelinks") or []:
        o = l.get("inwardIssue") or {}
        done = ((((o.get("fields") or {}).get("status") or {}).get("statusCategory") or {}).get("key")) == "done"
        if o.get("key") and "blocked by" in ((l.get("type") or {}).get("inward") or "").lower() and not done:
            return "by " + o["key"]
    return {"Blocked": "blocked", "On Hold": "on hold"}.get(status)


def collect_dev(line, s, env, shared):
    """One line's dev list. `shared` carries what every line reads once: the commits by key, the Jira cache."""
    import release as R  # noqa: E402 — on the path through brief
    cfg = (R.rmap("lines") or {}).get(str(line))
    lane = (cfg.get("lanes") or {}).get("qa")
    gaps, cache = [], shared.setdefault("cache", {})
    tl = load_state(state_path(s, lane), lane) if lane else {"rows": {}, "left": {}, "builds": {}}
    try:
        found = B.run_json(["python3", B.JIRA, *env, "jql", f'project = MH AND labels = "{cfg["label"]}" AND statusCategory != Done ORDER BY key',
                            "--limit", "300", "--json"], timeout=180)["issues"]
    except (B.LaneError, subprocess.TimeoutExpired, ValueError) as x:
        print(f"jira not read: {str(x)[:200]}", file=sys.stderr)
        sys.exit(EX_REMOTE)
    if "by_key" not in shared:
        code_root = s.get("code") or os.path.join(s.get("projects", ""), "code")
        shared["by_key"] = {}
        for c in B.git_window(code_root, COMMIT_DAYS * 24)[0]:
            for k in c["keys"]:
                shared["by_key"].setdefault(k, []).append(c)
    by_key = shared["by_key"]
    tl_rows = {**{k: dict(v, open=False) for k, v in tl.get("left", {}).items()}, **{k: dict(v, open=True) for k, v in tl["rows"].items()}}
    secondary = {k: r["ticket"] for r in tl_rows.values() if r.get("ticket") for k in r.get("also") or []}
    qa, _ = T.qa_names()
    sprint = shared["sprint"] = shared["sprint"] if "sprint" in shared else sprint_keys(s)
    fid = (R.rmap("fixed_in") or {}).get("field") or "customfield_11252"
    runtime = s.get("runtime") or os.path.join(s.get("projects", ""), ".ela")
    rows, errs = [], []
    env_tickets = {i["key"]: i for i in found if any(str(l).startswith(ENV_LABEL) for l in i.get("labels") or [])}
    found = [i for i in found if i["key"] not in env_tickets and                # an environment's problem asks no developer
             (i["status"] in DEV_STATUSES or i["key"] in by_key or i["key"] in tl_rows or i["key"] in secondary)]
    prefetch(env, [i["key"] for i in found], cache, errs)
    gaps += [{"source": g.split(": ", 1)[0], "error": g.split(": ", 1)[-1]} for g in errs]
    for i in found:
        k = i["key"]
        on_list = k in tl_rows or k in secondary
        if i["status"] not in DEV_STATUSES and k not in by_key and not on_list:
            continue                                        # not started: the board's queue, not development
        issue = jira_read(env, k, cache, gaps)
        f = (issue or {}).get("fields") or {}
        led = T.ledger(runtime, k)
        cs = by_key.get(k, [])
        fixed_in = J.body_text(f.get(fid)).strip() if f.get(fid) else ""
        fix_version = ", ".join(v.get("name") for v in f.get("fixVersions") or [] if v.get("name"))
        t = tl_rows.get(k) or tl_rows.get(secondary.get(k)) or {}
        found_v = comment_verdicts(issue, qa, None)
        verdict = t.get("verdict") or (sorted(found_v)[-1][1] if found_v else "untested")
        if not t.get("open", True) and t:
            verdict = (t.get("why") or "pass").split(" ")[0].rstrip(":")
        pre = PREFIX_RX.match(i["summary"] or "")
        repo_layers = {next((l for r, l in REPO_LAYERS if c["repo"].startswith(r)), None) for c in cs} - {None}
        layer = pre.group(1) if pre else ("+".join(t.get("layers") or sorted(repo_layers)) or "—")
        assignee = i.get("assignee") or ""
        flags = []
        if k in secondary and assignee.lower() in qa:
            flags.append(f"QA assigned on a secondary ticket; the owner is {secondary[k]}")
        if (fixed_in or fix_version) and verdict in ("untested", None):
            flags.append("Fixed In without a verdict")
        rows.append({"key": k, "url": JIRA_URL + k, "title": i["summary"], "layer": layer, "status": i["status"],
                     "assignee": assignee or None, "implementers": sorted({c["author"] for c in cs}),
                     "branch": branch_state(cs, led["lanes"]), "refs": sorted({c["ref"] for c in cs})[:4],
                     "lane_build": (t.get("builds") or [None])[-1], "owner_of": secondary.get(k),
                     "verdict": verdict, "fixed_in": fixed_in or None, "fix_version": fix_version or None,
                     "ready": {"ticket": True, "fixed_in": bool(fixed_in or fix_version), "verdict": verdict in ("pass", "n-a")}, "gaps": flags,
                     "due": f.get("duedate"), "blocked": held_by(i["status"], f)})
        rows[-1]["priority"], rows[-1]["priority_reason"] = priority({"ticket": k, "verdict": verdict}, f, sprint, 0)
    unticketed = [{"build": r["first_build"], "text": (r.get("log") or [r.get("focus") or ""])[0]}
                  for r in tl_rows.values() if not r.get("ticket")]
    rows.sort(key=lambda r: (not r["gaps"], r["layer"], r["key"]))
    for n, r in enumerate(rows, 1):
        r["rank"] = n
    return {"line": str(line), "lane": lane, "generated": now().isoformat(timespec="minutes"), "rows": rows,
            "unticketed": unticketed, "env": dev_env(cfg, s, env_tickets), "gaps": [f"{g['source']}: {g['error']}" for g in gaps]}


def dev_env(cfg, s, env_tickets):
    """The line's open environment rows: those its lanes' test lists keep (the China lanes aligned with its prod lane
    among them), and its tickets labelled env:<lane>; one row per ticket or difference."""
    lanes = list((cfg.get("lanes") or {}).values())
    lanes += B.region_lanes((cfg.get("lanes") or {}).get("prod"))
    out, seen = [], set()
    for lane in lanes:
        owner = None
        for r in (load_state(state_path(s, lane), lane).get("env") or {}).values():
            if r.get("state") == "open" and (r.get("ticket") or r["id"]) not in seen:
                seen.add(r.get("ticket") or r["id"])
                owner = owner or env_owner(lane)
                out.append({"lane": lane, "id": r["id"], "ticket": r.get("ticket"), "title": r["title"], "since": r.get("since"),
                            "owner": owner, "source": r["source"]})
    for k, i in env_tickets.items():
        if k not in seen:
            lane = next(l[len(ENV_LABEL):] for l in i["labels"] if str(l).startswith(ENV_LABEL))
            out.append({"lane": lane, "id": k, "ticket": k, "title": i["summary"], "since": (i.get("created") or "")[:10] or None,
                        "owner": env_owner(lane), "source": "label"})
    return out


def render_dev(out):
    at = datetime.datetime.fromisoformat(out["generated"])
    today = at.date().isoformat()
    L = [f"# Dev list · {out['line']}", "", f"*{at:%Y-%m-%d %H:%M} · line {out['line']} · QA lane {out['lane']}*", "",
         f"Every owner ticket in development on {out['line']}: where its commits are, what QA said, and what the next train "
         "still needs from it (ticket, Fixed In, verdict). Rows with a gap come first.", "",
         f"{len(out['rows'])} ticket(s) · {sum(bool(r['gaps']) for r in out['rows'])} with a gap · "
         f"{len(out['unticketed'])} build change(s) with no ticket", "",
         "| P | ticket | title | status | developer | due | train | blocked |", "|---|---|---|---|---|---|---|---|"]
    notes = []
    for r in out["rows"]:
        due = r.get("due")
        due = "—" if not due else f"overdue since {due}" if due < today else due
        L.append(f"| {r.get('priority') or '—'} | [{r['key']}]({r['url']}) | {short(r['title'])} | {r.get('status') or '—'} | "
                 f"{page_name(r.get('assignee')) or '—'} | {due} | {short(r.get('fix_version'), 30) if r.get('fix_version') else '—'} | "
                 f"{r.get('blocked') or '—'} |")
        said = []
        if r["implementers"] and r.get("assignee") not in r["implementers"]:
            said.append("commits by " + ", ".join(page_name(n) for n in r["implementers"][:3]))
        if r["branch"] != "no commit" or r.get("lane_build"):
            said.append(f"{r['branch']}" + (f" · build {r['lane_build']}" if r.get("lane_build") else ""))
        if r["verdict"] not in ("untested", None):
            said.append(f"QA {MARK.get(r['verdict'], '·')} {r['verdict']}")
        if r.get("fixed_in"):
            said.append(f"Fixed In {' '.join(r['fixed_in'].split())}")
        said += [f"gap: {g}" for g in r["gaps"]]
        if said:
            notes += callout(r["key"], "where it is", [f"**{r.get('priority') or '—'}** {r.get('priority_reason') or ''} · layer {r['layer']}".replace("  ", " "), ""]
                             + [f"- {x}" for x in said])
    L += notes
    if out["unticketed"]:
        L += ["", "## Build changes with no ticket", ""] + [f"- build {u['build']}: {cell(u['text'], 160)}" for u in out["unticketed"]]
    if out.get("env"):
        L += ["", "## Environment, not code", "", "Open problems of an environment, not of a build: no developer is asked to "
              "fix them; the environment's owner resolves them on the lane.", ""]
        L += [f"- {r['lane']}: " + (f"[{r['ticket']}]({JIRA_URL}{r['ticket']}) " if r["ticket"] else "") + f"{cell(r['title'], 140)} — "
              f"{ENV_SOURCE.get(r['source'], r['source'])}, since {r['since'] or '?'}, owner {r['owner']}" for r in out["env"]]
    if out["gaps"]:
        L += ["", "## Not read", ""] + [f"- {g[:200]}" for g in out["gaps"]]
    L += ["", f"*Generated by `ela devlist --line {out['line']} --page`.*"]
    return "\n".join(L) + "\n"


def print_dev(out, page):
    print(f"# dev list · {out['line']} · {len(out['rows'])} ticket(s)")
    for r in out["rows"]:
        print(f"  {r['key']:<9} {r['layer']:<6} {str(r['assignee'] or '—')[:14]:<14} {r['branch'][:22]:<22} {r['verdict']:<8} "
              f"FI {'✓' if r['fixed_in'] else '–'}  {cell(r['title'], 50)}" + (f"\n            ! {'; '.join(r['gaps'])}" if r["gaps"] else ""))
    for u in out["unticketed"]:
        print(f"  no ticket (build {u['build']}): {cell(u['text'], 100)}")
    for r in out.get("env") or []:
        print(f"  environment, not code ({r['lane']}): {r['ticket'] or r['source']} {cell(r['title'], 80)} · {r['owner']}")
    if page and out.get("page"):
        print(f"page: {out['page']}")


# ── Dev today: the developers' cut ───────────────────────────────────────────────────────────────────

DEV_BUDGET = 12


def developers():
    """{name lower or slack id: name} of the roster's builders (app, ui, ur, media), and their names lower."""
    try:
        import team as TM  # noqa: E402
        roster = TM.read_roster(TM.records())[1]
    except (SystemExit, ImportError, OSError, ValueError):
        return {}
    devs = [p for p in roster if (p.get("area") or "") in ("app", "ui", "ur", "media", "j2n", "infra")]
    return {**{p["name"].lower(): p["name"] for p in devs if p.get("name")}, **{p["slack"]: p["name"] for p in devs if p.get("slack")}}


def dev_today(outs, env, at, budget, guidance, cache, gaps):
    """By developer, at most `budget` rows: what moved since the last evening run (status, a build), what is due today
    or overdue, what is blocked or on hold, the gaps, and asks to a developer from anyone else since then."""
    since = last_evening(at)
    rows, today = [], at.date().isoformat()
    by_key = {r["key"]: r for out in outs for r in out["rows"]}
    qa_names_ = set(qa_people()[0])
    def dev_of(r):                                          # a ticket QA holds belongs, in the developers' cut, to its author
        if r.get("assignee") and r["assignee"].lower() not in qa_names_:
            return r["assignee"]
        return (r.get("implementers") or ["—"])[0]
    try:
        moved = B.run_json(["python3", B.JIRA, *env, "changes", "--since", since.strftime("%Y-%m-%d %H:%M"), "--json"], timeout=300)["issues"]
    except (B.LaneError, subprocess.TimeoutExpired, ValueError) as x:
        moved = []
        gaps.append(f"jira changes: {str(x)[:160]}")
    def add(key, who, reason, title=None):
        rows.append({"id": key, "ticket": key if re.match(r"^[A-Z][A-Z0-9]+-\d+$", key or "") else None,
                     "url": JIRA_URL + key if re.match(r"^[A-Z][A-Z0-9]+-\d+$", key or "") else key, "who": who or "—",
                     "title": title or (by_key.get(key) or {}).get("title") or "", "reason": reason})
    for i in moved:
        r = by_key.get(i["key"])
        st = [e for e in i.get("events") or [] if e.get("field") == "status"]
        if r and st and st[0].get("from") != st[-1].get("to"):
            add(i["key"], dev_of(r), f"moved {st[0].get('from')} → {st[-1].get('to')}")
    for r in by_key.values():
        f = ((cache.get(r["key"]) or {}).get("fields") or {})
        due = f.get("duedate")
        if due and due <= today:
            add(r["key"], dev_of(r), "overdue since " + due if due < today else "due today")
        if r["status"] in ("Blocked", "On Hold"):
            add(r["key"], dev_of(r), r["status"].lower())
        for g in r["gaps"]:
            add(r["key"], dev_of(r), g)
    for out in outs:
        for u in out["unticketed"]:
            add(nt_id(u["text"]), "—", f"build {u['build']} change with no ticket", u["text"])
    night = overnight(env, since, developers())
    threads = set()
    for ask in night["asks"]:                               # one row per thread: its first ask since the evening run
        if ask["thread"] in threads:
            continue
        threads.add(ask["thread"])
        keys = B.keys_in(ask["text"])
        add(keys[0] if keys else ask["link"], ", ".join(ask["to"]), f"ask from {ask['by']} in #{ask['channel']}", ask["text"][:120])
    order = ("ask from", "overdue", "due today", "blocked", "on hold", "moved", "QA assigned", "build", "Fixed In")
    rows.sort(key=lambda r: next((n for n, w in enumerate(order) if r["reason"].startswith(w)), len(order)))
    unread = apply_guidance(rows, guidance, {"rows": []})
    seen, cut = set(), []
    for r in rows:
        if r["id"] not in seen:
            seen.add(r["id"]); cut.append(r)
    night["placed"] = sum(1 for r in cut[:budget] if r["reason"].startswith("ask from"))
    return {"rows": cut[:budget], "more": max(0, len(cut) - budget), "overnight": night,
            "since": since.isoformat(timespec="minutes"), "guidance_unread": unread}


def dev_text(line, plan, at):
    L = [f"*Dev today · {line} · {at:%a %m-%d}* — by developer; reply here when a row is done or wrong."]
    who = {}
    for r in plan["rows"]:
        who.setdefault(r["who"], []).append(r)
    for name, rs in who.items():
        L.append(f"*{name}*")
        for r in rs:
            ref = f"<{r['url']}|{r['ticket']}>" if r["ticket"] else (f"<{r['url']}|thread>" if str(r["url"]).startswith("http") else f"`{r['id']}`")
            L.append(f"• {ref} {cell(r['title'], 70)} — {r['reason']}")
    if plan["more"]:
        L.append(f"+{plan['more']} more on the dev list.")
    return "\n".join(L)


def cmd_dev(a):
    """One line, or every line release.yaml names with a Jira label; a line with no ticket in development writes nothing.
    --page also writes <reports>/lanes/dev-list-<line>.json ({line, generated, rows, unticketed, env, gaps}) for the board."""
    import release as R  # noqa: E402 — on the path through brief
    s = site()
    env = ["--env-file", a.env_file] if a.env_file else []
    lines = R.rmap("lines") or {}
    if a.line and str(a.line) not in lines:
        print(f"unknown release line {a.line!r}; known: {', '.join(lines)}", file=sys.stderr)
        sys.exit(EX_USAGE)
    want = [str(a.line)] if a.line else [k for k, v in lines.items() if v.get("label")]
    shared, outs = {}, []
    for line in want:
        out = collect_dev(line, s, env, shared)
        if not out["rows"] and not a.line:
            continue
        if a.page:
            base = os.path.join(reports_root(s), "lanes", f"dev-list-{out['line']}")
            save(base + ".md", render_dev(out))
            save(base + ".json", json.dumps({k: out[k] for k in ("line", "lane", "generated", "rows", "unticketed", "env", "gaps")},
                                            ensure_ascii=False, indent=1))
            out["page"] = base + ".md"
        outs.append(out)
    if a.today:
        at, gaps = now(), []
        guidance = open(a.guidance, encoding="utf-8").read().splitlines() if a.guidance else []
        plan = dev_today(outs, env, at, a.budget, guidance, shared.get("cache", {}), gaps)
        line = ", ".join(o["line"] for o in outs) or "no line"
        res = {"date": at.date().isoformat(), "line": line, "thread": None, "channel": B.DEV_CHANNEL, "post": "day post",
               "text": dev_text(line, plan, at), **plan, "gaps": gaps}
        if a.json:
            print(json.dumps(res, ensure_ascii=False))
        else:
            print(f"# dev today → the day post in #{B.DEV_CHANNEL}\n{res['text']}\n")
            o = plan["overnight"]
            print(f"Overnight: {o['posts']} posts read in {', '.join('#' + c for c in o['channels']) or 'no channel'}, "
                  f"{o['placed']} asks placed above" + (f"; not read: {', '.join('#' + c for c in o['not_read'])}" if o["not_read"] else ""))
            for g in gaps:
                print(f"not read: {g[:160]}")
        return
    if a.json:
        print(json.dumps(outs[0] if a.line else {"lists": outs, "gaps": []}, ensure_ascii=False))
        return
    for out in outs:
        print_dev(out, a.page)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", help="ela's env file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="the lane's test list: one row per behaviour, ranked, with QA's verdict")
    p.add_argument("--lane", help="one lane: qa-cn3 (QA-AWS3), prod-3, prod-2-china (CN Prod2), prod-2 (.com Prod2); default every lane with release mails or a list")
    p.add_argument("--days", type=int, help="how far back to read the release mails (default 21)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--page", action="store_true", help="also write <reports>/lanes/test-list-<lane>.md")
    p.add_argument("--new-rows", action="store_true", help="only the rows the builds released on --date added, Slack-formatted")
    p.add_argument("--date", help="YYYY-MM-DD for --new-rows (default today)")
    p.add_argument("--saw", nargs=2, metavar=("KEY", "LINE"), help="write the night run's line on the row; a local write")
    p.add_argument("--today", action="store_true", help="QA today: the day's plan from the list, cut at --budget, Slack-formatted")
    p.add_argument("--budget", type=int, default=TODAY_BUDGET, help=f"rows in the day's plan (default {TODAY_BUDGET})")
    p.add_argument("--guidance", help="a file of his `ela:` lines from the morning page's QA today section: drop KEY · KEY first · add KEY · KEY P1")
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("dev", help="the line's dev list: one row per owner ticket in development, with its gaps")
    p.add_argument("--line", help="one release line (2.1); default every line release.yaml names with a Jira label")
    p.add_argument("--today", action="store_true", help="Dev today: by developer, the day's rows, Slack-formatted")
    p.add_argument("--budget", type=int, default=DEV_BUDGET, help=f"rows in the day's cut (default {DEV_BUDGET})")
    p.add_argument("--guidance", help="a file of his `ela:` lines from the morning page's Dev today section")
    p.add_argument("--json", action="store_true")
    p.add_argument("--page", action="store_true", help="also write <reports>/lanes/dev-list-<line>.md")
    p.set_defaults(func=cmd_dev)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
