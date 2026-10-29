#!/usr/bin/env python3
"""The test list: what QA should verify on a lane, ranked, one row per behaviour; and the dev list beside it.

    testlist.py list --lane qa-cn3 [--days N] [--json] [--page] [--new-rows [--date YYYY-MM-DD]]
    testlist.py list --lane qa-cn3 --saw KEY "ela saw … on V at HH:MM"
    testlist.py dev --line 2.1 [--json] [--page]

list  The lane's release mails (Test Focus and Change Log) give the rows: one per owner ticket a build names, and one
      "no ticket" row per change-log item that names no key (flagged). Two keys in one Test Focus item are one
      behaviour: the owner is the parent, or the one the other implements, else the first named; the rest ride as
      `also`. A row carries the ticket, its title and layer, the build it first arrived in and the build on the lane
      now, how to verify it (the Test Focus sentence, else the ticket's acceptance line, else "steps unknown"), auto
      (visible in the browser UI: a page, a list, a dialog, a field; never media quality, streams, audio or timing),
      the priority with its reason, QA's verdict (a QA person's ticket comment naming a version and a verdict, or the
      key's line in a QA report mail, after the row's first build), its age and what the night run saw.
      Priority, first rule that holds: P1 a customer incident (label or component), a fix on the next train (the
      pending promotion from this lane), a re-test after a fail; P2 in the sprint, or Highest/High; P3 the rest. A
      row two or more builds older than the lane's moves up one.
      State: <reports>/lanes/test-list-<lane>.json keeps each row's first build and verdict across builds; a new build
      adds rows and re-stamps lane_build; a row leaves only on a pass (or N/A) or when its ticket is withdrawn (closed
      won't do). --page writes <reports>/lanes/test-list-<lane>.md; the vault sync places it at lanes/.
      --new-rows: the rows each build released on --date (default today) added, Slack-formatted, with the day's
      release thread in #mediahub-qa-release, for the runner's tier-2 post (rule test-list).
      --saw: writes the night run's line on the row (a local write; no --apply), stamped with the lane build.

dev   One row per owner ticket in development on the line (labelled for it, not Done, and In Progress, Review, Blocked,
      On Hold or Reopened, or named by a commit, or on the lane's test list): layer, assignee and the commits' authors,
      branch state (on a lane build · merged to the release branch · on a branch · no commit), the lane build, QA's
      verdict, train readiness (ticket ✓, Fixed In ✓/–, verdict ✓/–) and the gaps: QA assigned on a secondary ticket
      (one the test list rides under another owner), Fixed In without a verdict; the build changes with no ticket
      are listed under the table. --page writes <reports>/lanes/dev-list-<line>.md.

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
SEED_DAYS = 10                                         # a lane with no state starts from the builds of this window
JIRA_URL = "https://tvunetworks.atlassian.net/browse/"
SECTIONS = ("Service add", "Database Change", "Properties Change", "Test Focus", "Change Log", "Other Service Dependencies",
            "Rollback Plan", "Note")
SECTION_RX = re.compile(r"^\s*(" + "|".join(SECTIONS) + r")\s*$", re.M)
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
    """qa-cn3 · qa-aws3 · QA-AWS3 → qa-cn3 (ela's name); the mails' name for it."""
    lane = B.mail_lane(raw) or raw.strip().lower()
    return lane, B.LANE_SHOWN.get(lane, lane.upper())


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


def parse_build_mail(m):
    """One release mail → {build, at, id, subject, focus: [{text, keys}], log: [{text, keys, layer}]}."""
    b = re.search(r"build\s*(\d+)", m["subject"], re.I)
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
    return {"build": b.group(1) if b else None, "at": B.mail_time(m["date"]), "id": m["id"], "subject": m["subject"],
            "focus": focus, "log": log}


def mail_search(env, query, limit=40):
    return B.run_json(["python3", B.MAIL, *env, "search", query, "--limit", str(limit), "--body", "--json"], timeout=300)["messages"]


def build_mails(env, shown, days):
    """The lane's release mails, oldest first; replies and test reports left out."""
    out = []
    for m in mail_search(env, f'newer_than:{days}d subject:("Release Mediahub {shown}")'):
        if re.match(r"^\s*\[Release\s+Mediahub\s+" + re.escape(shown) + r"\]", m["subject"], re.I):
            b = parse_build_mail(m)
            if b["build"]:
                out.append(b)
    return sorted(out, key=lambda b: int(b["build"]))


def report_mails(env, shown, days):
    """QA's test reports for the lane: [{at, build, text, subject}]."""
    out = []
    for m in mail_search(env, f'newer_than:{days}d subject:("Test Report" "{shown}")'):
        if re.search(r"test report", m["subject"], re.I):
            b = re.search(r"build\s*(\d+)", m["subject"], re.I)
            out.append({"at": B.mail_time(m["date"]), "build": b.group(1) if b else None, "summary": bool(re.match(r"^\s*summary", m["subject"], re.I)),
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


# ── the list ─────────────────────────────────────────────────────────────────────────────────────────

def train_keys(s, lane):
    """Keys on the next train: the pending promotion from this lane, while it is open."""
    pending = B.read_pending(s)
    if not pending or pending.get("from") != lane:
        return set()
    try:
        rep = json.load(open(pending.get("report") or ""))
    except (OSError, ValueError, TypeError):
        return set()
    return {t["key"] for t in (rep.get("tickets") or {}).get("tickets") or [] if t.get("exists", True)}


def sprint_keys(s):
    try:
        sp = B.read_sprint(s.get("vault"), s.get("runtime"), datetime.date.today()).get("active") or {}
    except (OSError, ValueError, KeyError):
        return set()
    return {k for it in sp.get("items") or [] for k in it.get("keys") or []}


def priority(row, fields, train, sprint, builds_after):
    labels = " ".join([*(fields.get("labels") or []), *[c.get("name", "") for c in fields.get("components") or []]])
    prio = ((fields.get("priority") or {}).get("name") or "")
    parent = (fields.get("parent") or {}).get("key")
    t = row["ticket"]
    if t and (CUSTOMER_RX.search(labels) or t.startswith("FB-") or parent == B.UMBRELLA):
        p, why = 1, "customer incident"
    elif row["verdict"] == "fail":
        p, why = 1, f"re-test: failed on {row.get('verdict_version') or '?'}"
    elif t and t in train:
        p, why = 1, "on the next train"
    elif t and t in sprint:
        p, why = 2, "in the sprint"
    elif prio in ("Highest", "High"):
        p, why = 2, f"Jira {prio}"
    else:
        p, why = 3, "the rest"
    if builds_after >= 2 and p > 1:
        p, why = p - 1, f"{why}, {builds_after} builds old"
    return f"P{p}", why


def collect(a, s, env):
    lane, shown = lane_name(a.lane)
    path = state_path(s, lane)
    st = load_state(path, lane)
    gaps, cache = [], {}
    days = a.days or (SEED_DAYS if not st["builds"] else 45)
    try:
        mails = build_mails(env, shown, days)
    except (B.LaneError, subprocess.TimeoutExpired, ValueError) as x:
        print(f"release mails not read: {str(x)[:200]}", file=sys.stderr)
        sys.exit(EX_REMOTE)
    try:
        reports = report_mails(env, shown, days)
    except (B.LaneError, subprocess.TimeoutExpired, ValueError) as x:
        reports = []
        gaps.append({"source": "QA report mails", "error": str(x)[:200]})
    if not st["builds"]:                                   # a new list starts after the newest build QA summarised
        closed = [int(r["build"]) for r in reports if r["summary"] and r["build"]]
        st["seed_after"] = str(max(closed)) if closed else None
    floor = int(st.get("seed_after") or 0)
    first_seen = min((int(b) for b in st["builds"]), default=None)
    for b in mails:
        if b["build"] in st["builds"] or int(b["build"]) <= floor or (first_seen and int(b["build"]) < first_seen):
            continue
        st["builds"][b["build"]] = {"at": b["at"], "mail": b["id"], "subject": b["subject"]}
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
    train, sprint = train_keys(s, lane), sprint_keys(s)
    rows, at = [], now()
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
        if not t:                                           # a change with no ticket has no verdict of its own; QA's
            summ = [x for x in reports if x["summary"] and x["build"] and int(x["build"]) >= int(r.get("last_build") or r["first_build"])]
            if summ:                                        # summary report on its build closes the round it rode in
                found.append((summ[-1]["at"][:16], "n-a", f"build {summ[-1]['build']}", "QA summary report"))
        found.sort()
        verdict, vv, vd, vs = ("untested", None, None, None) if not found else (found[-1][1], found[-1][2], found[-1][0][:10], found[-1][3])
        after = [b for b in builds if int(b) > int(r["first_build"])]
        row = {"id": rid, "ticket": t, "url": JIRA_URL + t if t else None, "also": r.get("also", []), "title": title,
               "layer": layer, "first_build": r["first_build"], "lane_build": st["lane_build"], "how_to_verify": how,
               "auto": auto_of(f"{title} {how}", bool(t)), "verdict": verdict, "verdict_version": vv, "verdict_date": vd,
               "verdict_source": vs, "age_days": (at - datetime.datetime.fromisoformat(r["first_at"])).days if r.get("first_at") else None,
               "ela_saw": r.get("ela_saw"), "flag": None if t else "no ticket", "status": (f.get("status") or {}).get("name"),
               "assignee": J.name_of(f.get("assignee")) if f.get("assignee") else None}
        row["priority"], row["priority_reason"] = priority(row, f, train, sprint, len(after))
        if verdict in ("pass", "n-a"):
            st["left"][rid] = dict(r, left_at=at.isoformat(timespec="minutes"), why=f"{verdict} on {vv} ({vd}, {vs})")
            del st["rows"][rid]
            continue
        st["rows"][rid].update(title=title, verdict=verdict, verdict_version=vv, verdict_date=vd)
        rows.append(row)
    rows.sort(key=lambda r: (r["priority"], r["verdict"] != "fail", -(r["age_days"] or 0), r["id"]))
    st["updated"] = at.isoformat(timespec="minutes")
    save(path, json.dumps(st, ensure_ascii=False, indent=1))
    recent = (at - datetime.timedelta(days=7)).isoformat()
    left = [dict(v, id=k) for k, v in st["left"].items() if (v.get("left_at") or "") >= recent]
    return {"lane": lane, "shown": shown, "lane_build": st["lane_build"], "generated": at.isoformat(timespec="minutes"),
            "builds": {b: st["builds"][b] for b in builds}, "rows": rows, "left": left, "gaps": [f"{g['source']}: {g['error']}" for g in gaps],
            "train": bool(train), "path": path}


# ── output ───────────────────────────────────────────────────────────────────────────────────────────

MARK = {"pass": "✅", "fail": "❌", "untested": "·"}


def link(r):
    return f"[{r['ticket']}]({r['url']})" + "".join(f" / [{k}]({JIRA_URL}{k})" for k in r["also"]) if r["ticket"] else "**no ticket**"


def cell(text, n=220):
    t = " ".join(str(text or "").split()).replace("|", "\\|")
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + " …"


def render_page(out):
    at = datetime.datetime.fromisoformat(out["generated"])
    L = ["# Test list · " + out["shown"], "", f"*{at:%Y-%m-%d %H:%M} · lane {out['lane']} · build {out['lane_build'] or '?'} now*", "",
         f"What QA should verify on {out['shown']}, highest priority first. One row per behaviour; a row stays until it has a "
         "verdict (QA's ticket comment with version and pass/fail, or the report mail) or its ticket is withdrawn. "
         "*ela saw* is a read-only browser check overnight; QA's verdict overrules it.", "",
         f"{len(out['rows'])} open · " + " · ".join(f"{p} {sum(r['priority'] == p for r in out['rows'])}" for p in ("P1", "P2", "P3"))
         + f" · {sum(r['auto'] for r in out['rows'])} auto · {sum(not r['ticket'] for r in out['rows'])} no ticket", "",
         "| | ticket | what | layer | how to verify | auto | verdict | builds | age | ela saw |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in out["rows"]:
        v = MARK.get(r["verdict"], "·") + (f" {r['verdict']} {r['verdict_version']} {r['verdict_date']}" if r["verdict"] != "untested" else " untested")
        L.append(f"| **{r['priority']}** {cell(r['priority_reason'], 60)} | {link(r)} | {cell(r['title'], 90)} | {r['layer']} | "
                 f"{cell(r['how_to_verify'])} | {'yes' if r['auto'] else '–'} | {v} | {r['first_build']} → {r['lane_build']} | "
                 f"{r['age_days'] if r['age_days'] is not None else '?'}d | {cell((r['ela_saw'] or {}).get('line') if r['ela_saw'] else '', 120)} |")
    if out["left"]:
        L += ["", "## Left the list this week", ""]
        for r in sorted(out["left"], key=lambda r: r.get("left_at") or ""):
            name = f"[{r['ticket']}]({JIRA_URL}{r['ticket']})" if r.get("ticket") else "no ticket"
            L.append(f"- {name} {cell(r.get('title') or (r.get('log') or [''])[0], 90)} — {r.get('why')}, {(r.get('left_at') or '')[:10]}")
    L += ["", "## Builds", ""] + [f"- build {b} · {(v.get('at') or '')[:16].replace('T', ' ')} · {v.get('subject')}" for b, v in
                                  sorted(out["builds"].items(), key=lambda kv: -int(kv[0]))[:6]]
    if out["gaps"]:
        L += ["", "## Not read", ""] + [f"- {g[:200]}" for g in out["gaps"]]
    L += ["", "*Priority: P1 a customer incident, a fix on the next train, a re-test after a fail · P2 the sprint, Jira "
          "Highest/High · P3 the rest · a row two builds older than the lane moves up one. Generated by `ela testlist --lane "
          f"{out['lane']} --page`.*"]
    return "\n".join(L) + "\n"


def release_thread(env, date, gaps):
    """The day's release thread in #mediahub-qa-release: the bot's `<date>_Release` message."""
    try:
        for m in B.slack_rows(env, B.QA_RELEASE, date, gaps, threads=False):
            if f"{date}_Release" in (m.get("text") or ""):
                return m.get("permalink")
    except Exception as x:  # noqa: BLE001 — a missing thread is a skipped post, never a failed list
        gaps.append({"source": "slack release thread", "error": str(x)[:200]})
    return None


def slack_text(out, build, rows):
    head = f"*Test list · {out['shown']} build {build}* — {len(rows)} new row(s), highest priority first. Verdicts go in the ticket comment (version + pass/fail); the lane's open list carries the rest."
    lines = [head]
    for r in rows:
        name = f"<{r['url']}|{r['ticket']}>" + "".join(f" / <{JIRA_URL}{k}|{k}>" for k in r["also"]) if r["ticket"] else "*no ticket* ⚠"
        lines.append(f"• *{r['priority']}* ({r['priority_reason']}) {name} {cell(r['title'], 80)}\n    how: {cell(r['how_to_verify'], 260)}"
                     + ("  · ela checks it in the browser overnight" if r["auto"] else ""))
    return "\n".join(lines)


def new_rows(out, env, date):
    builds, gaps = [], []
    thread = None
    for b, v in sorted(out["builds"].items(), key=lambda kv: int(kv[0])):
        if (v.get("at") or "")[:10] != date:
            continue
        rows = [r for r in out["rows"] if r["first_build"] == b]
        if not rows:
            continue
        thread = thread or release_thread(env, date, gaps)
        builds.append({"build": b, "mail_at": v.get("at"), "thread": thread, "channel": B.QA_RELEASE,
                       "text": slack_text(out, b, rows), "rows": [r["id"] for r in rows]})
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


def cmd_list(a):
    s = site()
    if a.saw:
        return cmd_saw(a, s)
    env = ["--env-file", a.env_file] if a.env_file else []
    out = collect(a, s, env)
    if a.page:
        page = os.path.join(reports_root(s), "lanes", f"test-list-{out['lane']}.md")
        save(page, render_page(out))
        out["page"] = page
    if a.new_rows:
        builds = new_rows(out, env, a.date or now().date().isoformat())
        if a.json:
            print(json.dumps({"lane": out["lane"], "builds": builds, "gaps": out["gaps"]}, ensure_ascii=False))
        else:
            for b in builds:
                print(f"# build {b['build']} → {b['thread'] or 'no release thread found'}\n{b['text']}\n")
            print(f"{len(builds)} build(s) with new rows")
        return
    if a.json:
        print(json.dumps(out, ensure_ascii=False))
        return
    print(f"# test list · {out['shown']} ({out['lane']}) · build {out['lane_build']} · {len(out['rows'])} open")
    for r in out["rows"]:
        print(f"  {r['priority']} {(r['ticket'] or 'no ticket'):<10} {r['layer']:<7} {'auto' if r['auto'] else '    '} "
              f"{r['verdict']:<8} b{r['first_build']}→{r['lane_build']} {str(r['age_days']) + 'd':>4}  {cell(r['title'], 60)}  · {r['priority_reason']}")
    for r in out["left"]:
        print(f"  left: {r.get('ticket') or r['id']} — {r.get('why')}")
    for g in out["gaps"]:
        print(f"  not read: {g[:120]}")
    if a.page:
        print(f"page: {out['page']}")



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


def collect_dev(a, s, env):
    import release as R  # noqa: E402 — on the path through brief
    cfg = (R.rmap("lines") or {}).get(str(a.line))
    if not cfg:
        print(f"unknown release line {a.line!r}; known: {', '.join(R.rmap('lines') or {})}", file=sys.stderr)
        sys.exit(EX_USAGE)
    lane = (cfg.get("lanes") or {}).get("qa")
    gaps, cache = [], {}
    tl = load_state(state_path(s, lane), lane) if lane else {"rows": {}, "left": {}, "builds": {}}
    try:
        found = B.run_json(["python3", B.JIRA, *env, "jql", f'project = MH AND labels = "{cfg["label"]}" AND statusCategory != Done ORDER BY key',
                            "--limit", "300", "--json"], timeout=180)["issues"]
    except (B.LaneError, subprocess.TimeoutExpired, ValueError) as x:
        print(f"jira not read: {str(x)[:200]}", file=sys.stderr)
        sys.exit(EX_REMOTE)
    code_root = s.get("code") or os.path.join(s.get("projects", ""), "code")
    commits = B.git_window(code_root, COMMIT_DAYS * 24)[0]
    by_key = {}
    for c in commits:
        for k in c["keys"]:
            by_key.setdefault(k, []).append(c)
    tl_rows = {**{k: dict(v, open=False) for k, v in tl.get("left", {}).items()}, **{k: dict(v, open=True) for k, v in tl["rows"].items()}}
    secondary = {k: r["ticket"] for r in tl_rows.values() if r.get("ticket") for k in r.get("also") or []}
    qa, _ = T.qa_names()
    fid = (R.rmap("fixed_in") or {}).get("field") or "customfield_11252"
    runtime = s.get("runtime") or os.path.join(s.get("projects", ""), ".ela")
    rows = []
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
        if fixed_in and verdict in ("untested", None):
            flags.append("Fixed In without a verdict")
        rows.append({"key": k, "url": JIRA_URL + k, "title": i["summary"], "layer": layer, "status": i["status"],
                     "assignee": assignee or None, "implementers": sorted({c["author"] for c in cs}),
                     "branch": branch_state(cs, led["lanes"]), "refs": sorted({c["ref"] for c in cs})[:4],
                     "lane_build": (t.get("builds") or [None])[-1], "owner_of": secondary.get(k),
                     "verdict": verdict, "fixed_in": fixed_in or None,
                     "ready": {"ticket": True, "fixed_in": bool(fixed_in), "verdict": verdict in ("pass", "n-a")}, "gaps": flags})
    unticketed = [{"build": r["first_build"], "text": (r.get("log") or [r.get("focus") or ""])[0]}
                  for r in tl_rows.values() if not r.get("ticket")]
    rows.sort(key=lambda r: (not r["gaps"], r["layer"], r["key"]))
    return {"line": str(a.line), "lane": lane, "generated": now().isoformat(timespec="minutes"), "rows": rows,
            "unticketed": unticketed, "gaps": [f"{g['source']}: {g['error']}" for g in gaps]}


def render_dev(out):
    at = datetime.datetime.fromisoformat(out["generated"])
    tick = lambda b: "✓" if b else "–"  # noqa: E731
    L = [f"# Dev list · {out['line']}", "", f"*{at:%Y-%m-%d %H:%M} · line {out['line']} · QA lane {out['lane']}*", "",
         f"Every owner ticket in development on {out['line']}: where its commits are, what QA said, and what the next train "
         "still needs from it (ticket, Fixed In, verdict). Rows with a gap come first.", "",
         f"{len(out['rows'])} ticket(s) · {sum(bool(r['gaps']) for r in out['rows'])} with a gap · "
         f"{len(out['unticketed'])} build change(s) with no ticket", "",
         "| ticket | what | layer | assignee | branch | build | QA | train: ticket · Fixed In · verdict | gaps |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in out["rows"]:
        who = r["assignee"] or "—"
        if r["implementers"] and r["assignee"] not in r["implementers"]:
            who += f" (commits: {', '.join(r['implementers'][:2])})"
        L.append(f"| [{r['key']}]({r['url']}) | {cell(r['title'], 80)} | {r['layer']} | {cell(who, 60)} | {r['branch']} | "
                 f"{r['lane_build'] or '–'} | {MARK.get(r['verdict'], '·')} {r['verdict']} | ✓ · {tick(r['ready']['fixed_in'])} · "
                 f"{tick(r['ready']['verdict'])} | {cell('; '.join(r['gaps']), 120)} |")
    if out["unticketed"]:
        L += ["", "## Build changes with no ticket", ""] + [f"- build {u['build']}: {cell(u['text'], 160)}" for u in out["unticketed"]]
    if out["gaps"]:
        L += ["", "## Not read", ""] + [f"- {g[:200]}" for g in out["gaps"]]
    L += ["", f"*Generated by `ela devlist --line {out['line']} --page`.*"]
    return "\n".join(L) + "\n"


def cmd_dev(a):
    s = site()
    env = ["--env-file", a.env_file] if a.env_file else []
    out = collect_dev(a, s, env)
    if a.page:
        page = os.path.join(reports_root(s), "lanes", f"dev-list-{out['line']}.md")
        save(page, render_dev(out))
        out["page"] = page
    if a.json:
        print(json.dumps(out, ensure_ascii=False))
        return
    print(f"# dev list · {out['line']} · {len(out['rows'])} ticket(s)")
    for r in out["rows"]:
        print(f"  {r['key']:<9} {r['layer']:<6} {str(r['assignee'] or '—')[:14]:<14} {r['branch'][:22]:<22} {r['verdict']:<8} "
              f"FI {'✓' if r['fixed_in'] else '–'}  {cell(r['title'], 50)}" + (f"\n            ! {'; '.join(r['gaps'])}" if r["gaps"] else ""))
    for u in out["unticketed"]:
        print(f"  no ticket (build {u['build']}): {cell(u['text'], 100)}")
    if a.page:
        print(f"page: {out['page']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", help="ela's env file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="the lane's test list: one row per behaviour, ranked, with QA's verdict")
    p.add_argument("--lane", required=True, help="qa-cn3 (QA-AWS3)")
    p.add_argument("--days", type=int, help="how far back to read the release mails (default: 10 on a new lane, 45 after)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--page", action="store_true", help="also write <reports>/lanes/test-list-<lane>.md")
    p.add_argument("--new-rows", action="store_true", help="only the rows the builds released on --date added, Slack-formatted")
    p.add_argument("--date", help="YYYY-MM-DD for --new-rows (default today)")
    p.add_argument("--saw", nargs=2, metavar=("KEY", "LINE"), help="write the night run's line on the row; a local write")
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("dev", help="the line's dev list: one row per owner ticket in development, with its gaps")
    p.add_argument("--line", required=True, help="the release line (2.1)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--page", action="store_true", help="also write <reports>/lanes/dev-list-<line>.md")
    p.set_defaults(func=cmd_dev)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
