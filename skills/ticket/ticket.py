#!/usr/bin/env python3
"""A tracked ticket's living record: each change since the last pass, read as understood or unsure.

    ticket.py refresh KEY [KEY…] [--dry-run] [--json]
    ticket.py refresh --all [--dry-run] [--json]

A ticket is tracked when it has a probe `fix` page (<reports>/ela/*-deep-<KEY>.md), is in the active sprint, was
routed by the owner (he set its assignee in the last 14 days), or has a drafted `apply N` pending. Each change on it
since its watermark is read against the closed list in skills/probe/SKILL.md (§fix — a change on a tracked ticket):
a match is `sure N`, anything else `unsure`. A ticket with a page gets one Timeline row per change (the fourth column
is the reading), its Real status facts refreshed and `seen-until` in its front matter; the rest of the page stays as
written. A ticket without a page keeps its watermark in <runtime>/ticket/seen.json. The findings list is the brief's
input: an unsure change, or one addressed to the owner, is an item; a sure one is a row only.

Jira reads only; nothing is posted. Exit 3 when Jira could not be read.
"""
import argparse, datetime, glob, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "brief"))
import brief as B  # noqa: E402  — Jira, git, the sprint note and the owner's identity, read the brief's way
sys.path.insert(0, os.path.join(HERE, "..", "team"))
sys.path.insert(0, os.path.join(HERE, "..", "jira"))
import jira as J  # noqa: E402  — a comment's rich text as plain text

FIXEDIN = os.path.join(HERE, "..", "fixedin", "fixedin.py")
ROUTED_DAYS = 14
COMMIT_DAYS = 60                                       # a branch naming the key, for rule 1
VERSION_RX = re.compile(r"(?<![\w.])v?(\d+\.\d+\.\d+(?:\.\d+)?)(?:[-+]\w+)?(?!\w|\.\d)")   # 2.2.121, v2.1.76
VERDICT_RX = re.compile(r"\b(pass(?:ed)?|fail(?:ed)?|verified|not fixed)\b|\u901a\u8fc7|\u5df2\u4fee\u590d|\u672a\u4fee\u590d|\u5931\u8d25", re.I)
STILL_FAILS_RX = re.compile(r"\bstill (?:fails?|failing|happens|broken)\b|\bnot (?:fixed|working)\b|\bfail(?:s|ed|ing)?\b|"
                            r"\u4ecd\u7136|\u672a\u4fee\u590d|\u5931\u8d25", re.I)
NO_REPRO_RX = re.compile(r"\b(?:does ?n[o']t|cannot|can't|could ?n[o']t|unable to) reproduce\b|\bno longer reproduces?\b|"
                         r"\u65e0\u6cd5\u590d\u73b0|\u4e0d\u80fd\u590d\u73b0", re.I)   # the bug no longer shows: not a failure, not evidence
FAIL_RX = re.compile(r"\bfail(?:ed)?\b|\bnot fixed\b|\u672a\u4fee\u590d|\u5931\u8d25", re.I)
REVIEW = ("review", "in review")
DONE = ("done", "closed", "resolved")
OPEN = ("to do", "open", "reopened", "in progress", "backlog")
QUIET_FIELDS = ("resolution", "Sprint")                 # they move with a status or a board, not on their own
EX_REMOTE = 3


# ── which tickets are tracked ─────────────────────────────────────────────────────────────────────────

def pages(reports):
    """{KEY: path} of the probe fix pages, the latest per key."""
    out = {}
    for p in sorted(glob.glob(os.path.join(reports, "ela", "*-deep-*.md"))):
        m = re.search(r"-deep-([A-Z][A-Z0-9]+-\d+)\.md$", p)
        if m:
            out[m.group(1)] = p
    return out


def pending_action_keys(reports):
    """Keys named by today's or the latest drafted actions not yet applied nor handled by the owner."""
    files = sorted(glob.glob(os.path.join(reports, "runner", "*-actions.json")))
    try:
        acts = json.load(open(files[-1], encoding="utf-8")) if files else []
    except (OSError, ValueError):
        acts = []
    return {k for a in acts if not a.get("applied") and not a.get("by_owner")
            for k in B.keys_in(f"{a.get('text', '')} {a.get('command', '')}")}


def routed_keys(rows, me):
    return {r["key"] for r in rows for e in r["events"]
            if e["field"] == "assignee" and e["by"] == me and e.get("to") and e["to"] != me}


def tracked(site, e, me, gaps):
    """{KEY: why} for --all."""
    reports = site.get("reports") or os.path.join(site.get("projects", ""), "reports")
    out = {k: "page" for k in pages(reports)}
    try:
        sprint = B.read_sprint(site.get("vault"), site.get("runtime"), datetime.date.today()).get("active") or {}
        for it in sprint.get("items") or []:
            for k in it.get("keys") or []:
                out.setdefault(k, "sprint")
    except (OSError, ValueError, KeyError) as x:
        gaps.append({"source": "sprint", "error": str(x)[:200]})
    try:
        ch = B.run_json(["python3", B.JIRA, *e, "changes", f"--since=-{ROUTED_DAYS}d", "--limit", "400", "--json"])
        for k in routed_keys(ch["issues"], me):
            out.setdefault(k, "routed")
    except (B.LaneError, subprocess.TimeoutExpired, ValueError) as x:
        gaps.append({"source": "jira routed", "error": str(x)[:200]})
    for k in pending_action_keys(reports):
        out.setdefault(k, "apply pending")
    return out


# ── the closed list ───────────────────────────────────────────────────────────────────────────────────

def first(name):
    return (name or "").strip().split(" ")[0].lower()


def awaited(page_text):
    """First names the page says it waits on (its Real status and Next), lowercase: an answer from one of them can
    close a question the timeline holds (rule 4)."""
    m = re.search(r"\*\*Real status\.\*\*(.*?)(?=^## |\Z)", page_text or "", re.S | re.M)
    nxt = re.search(r"^## Next[ \t]*\n(.*?)(?=^## |\Z)", page_text or "", re.S | re.M)
    text = (m.group(1) if m else "") + (nxt.group(1) if nxt else "")
    names = re.findall(r"(?:waiting on|waits on|asked|ask|confirm(?:ed)? by|answer from|nudge)\s+\**([A-Z]?[a-z]+)", text, re.I)
    return {n.lower() for n in names if n.lower() not in ("the", "him", "her", "them", "you", "qa")}


def ledger(runtime, key):
    """What the release ledger says about the key: the builds whose commits name it ({service, version, build, lanes})
    and every lane a commit naming it reached, from the daily `ela changes` files."""
    builds, lanes = [], set()
    for f in sorted(glob.glob(os.path.join(runtime, "runner", "*-changes.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        shas = set()
        for repo in (d.get("code") or {}).get("repos") or []:
            for t in repo.get("tickets") or []:
                if t.get("key") == key:
                    for c in t.get("commits") or []:
                        shas.add(c["sha"][:8]); lanes.update(c.get("lanes") or [])
        for b in d.get("builds") or []:
            if any(str(c)[:8] in shas for c in b.get("commits") or []):
                builds.append({"service": b.get("service"), "version": str(b.get("version") or ""), "build": b.get("build"),
                               "lanes": b.get("deployed_to") or []})
                lanes.update(b.get("deployed_to") or [])
    return {"builds": builds, "lanes": lanes}


def drafted_builds(e, key, gaps):
    """The carrying builds the Fixed In drafter reads from Jenkins (`svc@2.1.76+366`), as ledger rows: asked only when
    a developer names a version the daily ledger does not hold, since it costs seconds per ticket."""
    try:
        got = B.run_json(["python3", FIXEDIN, *e, "draft", key, "--json"], timeout=300)["keys"]
    except (B.LaneError, subprocess.TimeoutExpired, ValueError) as x:
        gaps.append({"source": f"fixedin {key}", "error": str(x)[:200]}); return []
    out = []
    for d in (got[0].get("draft") or []) if got else []:
        m = re.match(r"^([\w-]+)@v?([\d.]+)(?:\+(\d+))?", d.get("value") or "")
        if m:
            out.append({"service": m.group(1), "version": m.group(2), "build": int(m.group(3)) if m.group(3) else None, "lanes": []})
    return out


LANE_RX = re.compile(r"\b(qa-[a-z0-9]+|prod-\d+|daily-[a-z0-9-]+|stage)\b", re.I)


def lanes_named(text):
    """Lanes a comment names, by id or by the name the team uses (QA-AWS3)."""
    shown = {v.lower(): k for k, v in B.LANE_SHOWN.items()}
    return {shown.get(m.lower(), m.lower()) for m in LANE_RX.findall(text or "")} | \
           {k for v, k in shown.items() if re.search(r"\b" + re.escape(v) + r"\b", text or "", re.I)}


def carrying(text, led):
    """The ledger build a comment names by version or build number, or None."""
    named = set(VERSION_RX.findall(text))
    for b in led["builds"]:
        if b["version"] in named or (b.get("build") and re.search(rf"(?:build|#)\s*{b['build']}\b", text, re.I)):
            return b
    return None


def lane_mismatch(lanes, status, qa_verdict=None):
    """The furthest lane carrying the fix (prod over daily and stage over QA) against the ticket's status: on QA while
    Backlog or To Do, on prod while In Progress, or on prod while Review with no QA verdict on the timeline. Then the
    status and where the code runs disagree, and that is the reason he reads first."""
    st = (status or "").lower()
    rank = lambda l: 2 if l.startswith("prod") else 1 if l.startswith(("daily", "stage")) else 0 if l.startswith("qa") else -1  # noqa: E731
    known = sorted((l for l in lanes if rank(l) >= 0), key=lambda l: (-rank(l), l))
    if not known:
        return None
    far = known[0]
    shown = f"fix on {B.LANE_SHOWN.get(far, far)}, ticket {status}"
    if rank(far) == 0 and st in ("backlog", "to do"):
        return shown
    if rank(far) == 2 and (st == "in progress" or (st in REVIEW and not qa_verdict)):
        return shown + (" with no QA verdict" if st in REVIEW else "")
    return None


def first_sentence(text, limit=200):
    m = re.match(r"(.+?[.!?\u3002\uff01\uff1f])(?:\s|$)", text)
    s = m.group(1) if m else text
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0] + " …"


def addressed(text, me):
    """A comment naming the owner (display name, first name or an @-mention of either)."""
    if not me or not text:
        return False
    return bool(re.search(r"(?<![\w])@?(" + re.escape(me) + r"|" + re.escape(me.split(" ")[0]) + r")\b", text, re.I))


def read_change(ch, ctx):
    """(change, reading, sure, addressed_to_owner) for one event or comment; None for a change not worth a row
    (a machine's edit other than Fixed In, a field that moves with a status)."""
    me, who = ctx["me"], ch.get("by") or "?"
    machine = bool(B.MACHINES.search(who))
    if ch["type"] == "comment":
        text = re.sub(r"\s+", " ", ch.get("text") or "").strip()
        if machine:
            return None
        to_me = addressed(text, me) or (ctx["assignee"] == me and "?" in text)
        what = f"{who}: {first_sentence(text)}"
        if who == me:
            return what, "yours", True, False
        version, verdict = VERSION_RX.search(text), VERDICT_RX.search(text)
        if who.lower() in ctx["qa"] and version and verdict:
            word = "fail" if FAIL_RX.search(text) else "pass"
            return what, f"sure 2: QA {word} on {version.group(1)}", True, to_me
        dev = who.lower() not in ctx["qa"] and (who == ctx["assignee"] or who.lower() in ctx["devs"])
        if dev and NO_REPRO_RX.search(text):                 # neither progress nor evidence, and not a failure either
            return what, "unsure: a developer cannot reproduce it", False, to_me
        if dev and STILL_FAILS_RX.search(text):              # a failure report is neither progress nor evidence
            return what, "unsure: a developer reports it still fails", False, to_me
        if version and dev:
            b = carrying(text, ctx["ledger"])
            if b:
                return what, f"sure 8: {b['version']} carries the fix, ledger agrees", True, to_me
            return what, f"unsure: {who} names {version.group(1)}, a version not in the ledger", False, to_me
        asks, new_link = "?" in text or "\uff1f" in text, [k for k in B.keys_in(text) if k != ctx["key"]]
        if first(who) in ctx["awaited"] and not asks and not new_link:
            return what, f"sure 4: answer from {who}", True, to_me
        if (ctx["status"].lower() == "in progress" and (who == ctx["assignee"] or who.lower() in ctx["devs"])
                and not asks and not version and not new_link):
            return what, f"sure 6: progress from {who}", True, to_me
        why = ("a question" if asks else f"links {', '.join(new_link)}" if new_link else
               "a version without a verdict" if version else "no rule places it")
        return what, f"unsure: comment from {who}, {why}", False, to_me
    field, frm, to = ch["field"], ch.get("from") or "—", ch.get("to") or "—"
    if field in QUIET_FIELDS:
        return None
    if machine and field != "Fixed In":
        return None
    what = f"{field}: {frm} → {to} by {who}"
    if who == me:
        return what, "yours", True, False
    if field == "status":
        f, t = frm.lower(), to.lower()
        if t in REVIEW and ctx["key"] in ctx["commit_keys"] and who.lower() not in ctx["qa"]:
            return what, "sure 1: Review on a branch naming the key", True, False
        if t in DONE and ctx["qa_pass"]:
            return what, f"sure 5: Done after QA pass on {ctx['qa_pass']}", True, False
        if (f in DONE or f in REVIEW) and t in OPEN:
            return what, f"unsure: moved back from {frm} to {to}", False, False
        if t in REVIEW:
            return what, "unsure: Review with no commit naming the key", False, False
        return what, f"unsure: {frm} → {to}, no rule covers it", False, False
    if field == "assignee":
        st, tl = (ch.get("status_at") or ctx["status"]).lower(), to.lower()
        if to == me:
            return what, "unsure: reassigned to you", False, True
        if tl in ctx["qa"] and st in REVIEW:
            return what, "sure 7: to QA in Review", True, False
        if tl in ctx["devs"] and tl not in ctx["qa"] and st in ("to do", "open", "backlog", "in progress"):
            return what, f"sure 7: to a developer in {ch.get('status_at') or ctx['status']}", True, False
        if to == ctx.get("reporter") and st in DONE:
            return what, "sure 7: back to the reporter on Done", True, False
        return what, f"unsure: reassigned to {to}", False, False
    if field == "Fixed In":
        if ctx["fixed_in"] == "same":
            return what, f"sure 3: Fixed In {to} is the carrying build", True, False
        return what, f"unsure: Fixed In {to} not matched to a carrying build", False, False
    if field == "Link":
        return what, f"unsure: new linked ticket {to}", False, False
    return what, f"unsure: {field} changed", False, False


# ── the page ──────────────────────────────────────────────────────────────────────────────────────────

def split_page(text):
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    return (m.group(1).split("\n"), text[m.end():]) if m else ([], text)


def watermark(path, text):
    fl, _ = split_page(text)
    v = next((l.split(":", 1)[1].strip().strip("'\"") for l in fl if l.startswith("seen-until:")), None)
    try:
        return datetime.datetime.fromisoformat(v) if v else datetime.datetime.fromtimestamp(os.path.getmtime(path)).astimezone()
    except ValueError:
        return datetime.datetime.fromtimestamp(os.path.getmtime(path)).astimezone()


def cell(s):
    return (s or "").replace("|", "\\|").replace("\n", " ")


def update_page(text, rows, facts, seen_until, now):
    """The page with its Timeline rows appended (a reading column added to an older table), the Real status facts
    sentence refreshed, and seen-until set; every other line as it was."""
    fl, body = split_page(text)
    fl = [l for l in fl if not l.startswith("seen-until:")] + [f'seen-until: "{seen_until.isoformat(timespec="seconds")}"']
    lines = body.split("\n")
    try:
        i = next(n for n, l in enumerate(lines) if re.match(r"^## Timeline\b", l))
        h = next(n for n in range(i + 1, len(lines)) if lines[n].startswith("|"))
    except StopIteration:
        i = h = None
    if h is not None:
        end = h
        while end < len(lines) and lines[end].startswith("|"):
            end += 1
        if lines[h].count("|") == 4:                        # | date | what happened | source |
            lines[h] = lines[h].rstrip() + " reading |"
            lines[h + 1] = lines[h + 1].rstrip() + "---|"
            for n in range(h + 2, end):
                lines[n] = lines[n].rstrip() + "  |"
        new = [f"| {r['date']} | {cell(r['change'])} | {cell(r['source'])} | {cell(r['reading'])} |" for r in rows]
        lines[end:end] = new
    elif rows:
        lines += ["", "## Timeline", "", "| date | what happened | source | reading |", "|---|---|---|---|"] + \
                 [f"| {r['date']} | {cell(r['change'])} | {cell(r['source'])} | {cell(r['reading'])} |" for r in rows]
    body = "\n".join(lines)
    m = re.search(r"^\*\*Real status\.\*\*[ \t]*(.*)$", body, re.M)
    if m:
        para = re.sub(r"\s*\*\(refreshed [^)]*\)\*", "", m.group(1))
        para = re.sub(r"^Jira says [^.]*\.\s*", "", para)
        unsure = [r for r in rows if not r["sure"]]
        note = f" *(refreshed {now:%m-%d %H:%M}: {len(rows)} change{'s' if len(rows) != 1 else ''}" + \
               (f", {len(unsure)} unsure)*" if unsure else ")*")
        body = body[:m.start()] + f"**Real status.** {facts} " + para + note + body[m.end():]
    return ("---\n" + "\n".join(fl) + "\n---\n" if fl else "") + body


# ── one pass ──────────────────────────────────────────────────────────────────────────────────────────

def qa_names():
    try:
        import team as T  # noqa: E402
        roster = T.read_roster(T.records())[1]
    except (SystemExit, ImportError, OSError, ValueError):
        return set(), set()
    names = lambda p: {str(p.get(k) or "").lower() for k in ("name", "jira_name")} - {""}  # noqa: E731
    qa = {n for p in roster if (p.get("area") or "") == "qa" for n in names(p)}
    devs = {n for p in roster if (p.get("area") or "") not in ("qa", "") for n in names(p)}
    return qa, devs


def qa_pass(comments, qa):
    """The version of the latest QA pass in the ticket's comments, or None."""
    found = None
    for c in comments:
        text = c.get("text") if "text" in c else J.body_text(c.get("body"))
        who = c.get("by") if "by" in c else J.name_of(c.get("author"))
        v = VERSION_RX.search(text or "")
        if who.lower() in qa and v and VERDICT_RX.search(text) and not FAIL_RX.search(text):
            found = v.group(1)
        elif who.lower() in qa and v and FAIL_RX.search(text or ""):
            found = None
    return found


def qa_verdict_any(comments, qa):
    """Whether any QA person gave a verdict with a version on the ticket, pass or fail."""
    for c in comments:
        text = c.get("text") if "text" in c else J.body_text(c.get("body"))
        who = c.get("by") if "by" in c else J.name_of(c.get("author"))
        if (who or "").lower() in qa and VERSION_RX.search(text or "") and VERDICT_RX.search(text or ""):
            return True
    return False


def changes_of(row, since):
    out = []
    for ev in row["events"]:
        at = B.parse_ts(ev["at"])
        if at and at > since:
            out.append(dict(ev, type="event", at_dt=at))
    for c in row["comments"]:
        at = B.parse_ts(c["at"])
        if at and at > since:
            out.append(dict(c, type="comment", at_dt=at))
    return sorted(out, key=lambda c: c["at_dt"])


def prod_or_customer(key, fields):
    labels = [str(l).lower() for l in fields.get("labels") or []]
    summary = (fields.get("summary") or "").lower()
    return key.startswith("FB-") or any("prod" in l or "customer" in l for l in labels) or bool(re.search(r"\bprod\b|customer", summary))


def refresh(keys, site, e, me, dry_run=False, now=None):
    now = now or datetime.datetime.now().astimezone()
    reports = site.get("reports") or os.path.join(site.get("projects", ""), "reports")
    runtime = site.get("runtime") or os.path.join(site.get("projects", ""), ".ela")
    state_path = os.path.join(runtime, "ticket", "seen.json")
    try:
        state = json.load(open(state_path, encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    page_of, gaps = pages(reports), []
    marks = {}
    for k in keys:
        if k in page_of:
            marks[k] = watermark(page_of[k], open(page_of[k], encoding="utf-8").read())
        else:
            try:
                marks[k] = datetime.datetime.fromisoformat(state[k])
            except (KeyError, ValueError):
                marks[k] = now - datetime.timedelta(days=1)
    rows = {}
    for proj in sorted({k.split("-")[0] for k in keys}):
        since = min(m for k, m in marks.items() if k.startswith(proj + "-"))
        try:
            got = B.run_json(["python3", B.JIRA, *e, "changes", "--project", proj, "--since",
                              since.astimezone().strftime("%Y-%m-%d %H:%M"), "--limit", "400", "--json"])
            rows.update({r["key"]: r for r in got["issues"] if r["key"] in keys})
        except (B.LaneError, subprocess.TimeoutExpired, ValueError) as x:
            gaps.append({"source": f"jira {proj}", "error": str(x)[:200]})
    qa, devs = qa_names()
    code_root = site.get("code") or os.path.join(site.get("projects", ""), "code")
    commit_keys = None
    tickets, findings = [], []
    for k in keys:
        chs = changes_of(rows[k], marks[k]) if k in rows else []
        rec = {"key": k, "page": page_of.get(k), "since": marks[k].isoformat(timespec="seconds"), "changes": len(chs)}
        tickets.append(rec)
        if not chs:
            continue
        try:
            issue = B.run_json(["python3", B.JIRA, *e, "read", k, "--json"])
        except (B.LaneError, subprocess.TimeoutExpired, ValueError) as x:
            gaps.append({"source": f"jira read {k}", "error": str(x)[:200]}); continue
        f = issue.get("fields") or {}
        name = lambda v, a="displayName": (v or {}).get(a) if isinstance(v, dict) else v  # noqa: E731
        if commit_keys is None and any(c.get("field") == "status" for c in chs):
            commit_keys = {x for c in B.git_window(code_root, COMMIT_DAYS * 24)[0] for x in c["keys"]}
        fixed = None
        if any(c.get("field") == "Fixed In" for c in chs):
            try:
                fixed = (B.run_json(["python3", FIXEDIN, *e, "draft", k, "--json"])["keys"] or [{}])[0].get("compare")
            except (B.LaneError, subprocess.TimeoutExpired, ValueError, IndexError) as x:
                gaps.append({"source": f"fixedin {k}", "error": str(x)[:200]})
        page_text = open(page_of[k], encoding="utf-8").read() if k in page_of else ""
        status_now = name(f.get("status"), "name") or ""
        running = next((c.get("from") for c in chs if c.get("field") == "status"), None) or status_now
        for c in chs:                                       # the status each change happened under
            later = [x for x in chs if x.get("field") == "status" and x["at_dt"] <= c["at_dt"]]
            c["status_at"] = later[-1].get("to") if later else running
        led = ledger(site.get("runtime") or os.path.join(site.get("projects", ""), ".ela"), k)
        named = [c for c in chs if c["type"] == "comment" and VERSION_RX.search(c.get("text") or "")]
        if any(not carrying(c["text"], led) for c in named):
            led["builds"] += drafted_builds(e, k, gaps)
        for c in named:                                     # where a developer says the fix runs, for the cross-check
            led["lanes"] |= lanes_named(c["text"])
        ctx = {"key": k, "me": me, "qa": qa, "devs": devs, "assignee": name(f.get("assignee")) or "",
               "reporter": name(f.get("reporter")) or "", "ledger": led,
               "status": name(f.get("status"), "name") or "", "awaited": awaited(page_text),
               "commit_keys": commit_keys or set(), "qa_pass": qa_pass(issue.get("comments") or [], qa), "fixed_in": fixed}
        pc = prod_or_customer(k, f)
        mismatch = lane_mismatch(led["lanes"], ctx["status"], ctx["qa_pass"] or qa_verdict_any(issue.get("comments") or [], qa))
        read = []
        for c in chs:
            got = read_change(c, ctx)
            if got:
                read.append((c, *got))
        # two or more reassignments in one day are one unsure row: the ticket is looking for its owner
        moves = [r for r in read if r[0].get("field") == "assignee" and r[0].get("by") != me and r[0].get("to") != me]
        while moves:
            same = [r for r in moves if r[0]["at_dt"] - moves[0][0]["at_dt"] < datetime.timedelta(hours=24)]
            moves = moves[len(same):]
            if len(same) > 1:
                chain = " → ".join([same[0][0].get("from") or "—"] + [r[0].get("to") or "—" for r in same])
                keep = read.index(same[0])
                read = [r for r in read if r not in same[1:]]
                read[keep] = (same[0][0], f"assignee: {chain}", f"unsure: reassigned {len(same)} times in a day", False, False)
        trows = []
        for c, change, reading, sure, to_me in read:
            if mismatch and reading != "yours" and (sure or reading.endswith(("no rule places it", "no rule covers it"))):
                reading, sure = f"unsure: {mismatch}", False
            src = "comment" if c["type"] == "comment" else "changelog"
            trows.append({"date": c["at_dt"].astimezone().strftime("%m-%d"), "change": change, "source": src,
                          "reading": reading, "sure": sure})
            ev = re.match(r"sure 8: (\S+) carries", reading)
            findings.append({"key": k, "change": change, "reading": reading, "sure": sure, "addressed_to_owner": to_me,
                             "prod_or_customer": pc, "at": c["at"], "by": c.get("by"), "page": page_of.get(k),
                             "fixed_in_evidence": ev.group(1) if ev else None})
        rec.update(rows=len(trows), unsure=sum(not r["sure"] for r in trows), status=ctx["status"], assignee=ctx["assignee"])
        if k in page_of and not dry_run:
            facts = f"Jira says {ctx['status']}, assigned to {ctx['assignee'] or 'nobody'}."
            atomic_write(page_of[k], update_page(page_text, trows, facts, now, now))
    if not dry_run:
        for k in keys:
            if k not in page_of and not any(g["source"].endswith(k.split("-")[0]) for g in gaps):
                state[k] = now.isoformat(timespec="seconds")
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        atomic_write(state_path, json.dumps(state, indent=1, sort_keys=True))
    return {"at": now.isoformat(timespec="seconds"), "tickets": tickets, "findings": one_per_link(findings, keys), "gaps": gaps}


def key_order(k):
    p, _, n = k.partition("-")
    return (p, int(n) if n.isdigit() else 0)


def one_per_link(findings, keys):
    """One Link finding per pair of tickets. Jira records a link on both sides, and a link added twice from the same
    side reads twice, so MH-3800's links to MH-3829 and MH-3830 came back as three findings (2026-10-28 brief). The
    finding stays on the tracked side, the older ticket when both are tracked, with the other key as `linked`."""
    pairs = {}
    for i, f in enumerate(findings):
        other = [k for k in B.keys_in(f["change"]) if k != f["key"]] if f["change"].startswith("Link:") else []
        if other:
            pairs.setdefault(frozenset((f["key"], other[0])), []).append((f["key"] not in keys, key_order(f["key"]), i, other[0]))
    keep = {min(c)[2]: min(c)[3] for c in pairs.values()}
    drop = {c[2] for cs in pairs.values() for c in cs} - set(keep)
    return [dict(f, linked=keep[i]) if i in keep else f for i, f in enumerate(findings) if i not in drop]


def atomic_write(path, text):
    tmp = path + ".tmp"
    open(tmp, "w", encoding="utf-8").write(text)
    os.replace(tmp, path)


def cmd_refresh(a):
    site = json.load(open(B.SITE))
    e = ["--env-file", a.env_file] if a.env_file else []
    me = B.owner_jira_name(e)
    gaps = []
    if a.all:
        why = tracked(site, e, me, gaps)
        keys = sorted(why)
    else:
        bad = [k for k in a.keys if not re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", k)]
        if bad or not a.keys:
            print(f"refresh needs ticket keys or --all{'; not a key: ' + ', '.join(bad) if bad else ''}", file=sys.stderr)
            sys.exit(2)
        keys, why = a.keys, {k: "asked" for k in a.keys}
    out = refresh(keys, site, e, me, a.dry_run)
    out["gaps"] = gaps + out["gaps"]
    for t in out["tickets"]:
        t["tracked"] = why.get(t["key"])
    if a.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        for t in out["tickets"]:
            print(f"{t['key']:<10} {t['tracked'] or '':<14} {t['changes']} change(s)"
                  + (f", {t.get('unsure', 0)} unsure" if t["changes"] else "") + ("  page" if t["page"] else ""))
        for f in out["findings"]:
            if not f["sure"] or f["addressed_to_owner"]:
                print(f"  {f['key']}: {f['reading']}{' · to you' if f['addressed_to_owner'] else ''}{' · prod/customer' if f['prod_or_customer'] else ''}")
        for g in out["gaps"]:
            print(f"  not read: {g['source']}: {g['error'][:100]}")
    if any(g["source"].startswith("jira") for g in out["gaps"]):
        sys.exit(EX_REMOTE)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", help="ela's env file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("refresh", help="read each change on tracked tickets since the last pass; append it to the ticket's page")
    p.add_argument("keys", nargs="*", help="ticket keys (MH-2406)")
    p.add_argument("--all", action="store_true", help="every tracked ticket: a fix page, the sprint, routed by the owner, an apply pending")
    p.add_argument("--dry-run", action="store_true", help="read and print; write no page and no watermark")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_refresh)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
