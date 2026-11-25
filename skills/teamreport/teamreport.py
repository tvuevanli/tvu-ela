#!/usr/bin/env python3
"""The team's daily and weekly report narrative, from the fact store; Helm renders the page and posts it to Slack.

  teamreport.py prompt daily [--date D] [--json]          the writing rules and the day's data, as one prompt
  teamreport.py prompt weekly [--week YYYY-Www] [--json]  the same for an ISO week (default: the last full week)
  teamreport.py write daily|weekly [--date D | --week W] [--narrative FILE|-] [--json]
                                                          check the narrative and publish it
  teamreport.py compare daily|weekly [--date D | --week W] [--helm DIR] [--json]
                                                          a side-by-side note of Helm's report and ela's
  teamreport.py show daily|weekly [--date D | --week W] [--json]   the published file

`prompt` reads only <runtime>/facts/ (`ela facts refresh` fills it): the day's MH tickets updated and created (the
sweep, by its changelog and comments as well as its `updated`), the tickets Blocked and In Progress now (the standing
query `board-state`), every human message in the channels the bot is in, and the day's mail from the `release`,
`test-report` and `team` standing searches, kept to MediaHub's senders and subjects. It writes the prompt and the input
(the Jira keys the data holds, the counts per source) to <runtime>/drafts/team-report/<kind>-<id>/. A day with no
activity in any source needs no model: `state` is `quiet` (or `incomplete` when a source has a gap) and `write` with
no narrative publishes the stub.

The writing rules are daily.md and weekly.md beside this script, ported from Helm's own prompts. The narrative is the
model's; every check on it is here: a section Helm owns (Release & QA, the Sources line; for the week the Shipped,
Numbers, Blocked and Carry-over sections and any per-day section) is removed, a Jira key the input does not hold is
removed, and in the weekly a version, build or bundle-shaped token is removed. Then the publish guard (redaction, the
content guard) runs, and the file goes to <published>/reports/daily/<date>.json or reports/weekly/<week>.json, with
report.md beside this script published as reports/README.md (the schema Helm reads).

`compare` reads Helm's own report for the same day or week (<projects>/helm/data/reports/<date>.md or
data/weekly_reports/<week>.md, or --helm DIR) and writes <runtime>/drafts/report-compare/<kind>-<id>.md: both texts,
the keys each cites and the keys only one cites. It is the side-by-side week before Helm's writer goes.

Nothing here posts anywhere or calls a model: the runner (or a session following SKILL.md) passes the prompt to a
model and hands the text to `write`. Stdlib only.
Exit codes: 0 ok · 2 usage · 3 not found (no prompt input for `write`, no published file for `show`) · 4 the
narrative is empty after the checks, or the publish guard refused it (the published copy is unchanged).
"""
import argparse, datetime, json, os, re, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
SITE = os.path.expanduser("~/.claude/ela/site.json")
EX_USAGE, EX_NOTFOUND, EX_REFUSED = 2, 3, 4
SCHEMA = 1
sys.path.insert(0, os.path.join(SKILLS, "facts"))
import facts as F  # noqa: E402

PROJECT = "MH"
PRJ_CHANNEL = "prj_dev_mediahub"
MAX_UPDATED, MAX_CREATED, MAX_PRJ, MAX_OTHER = 80, 40, 100, 80      # Helm's prompt caps, per section
MAX_SLACK = 200                                                      # Helm's collection cap: the project channel first, then the latest
MAX_SLACK_TEXT = 300
MAX_MAIL, MAIL_BODY_CAP, MAIL_SNIPPET_CAP = 30, 1200, 200
LONG_BLOCKED_DAYS = 60                                               # Helm weekly.py LONG_BLOCKED_DAYS
MAX_LISTED = 10
MAX_DAILY_BODY, MAX_TOTAL_DAILY = 8000, 40000
TERMINAL = {"done", "cancelled", "failed", "closed ambigous"}
KEY_RX = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{1,6}\b")
STUB_QUIET = "**Summary**\n\n- Quiet day — no tracked activity in Jira, Slack or mail."
STUB_INCOMPLETE = "**Summary**\n\n- No activity came back, and a source was not read whole; this is not a claim that the day was quiet."
# MediaHub's own release and service mail; the inbox carries every product's release mail, so the subject net is narrowed
MH_SUBJECT = re.compile(r"(?i)mediahub|unified ?resource|unifiedmediaservice|\bj2n\b|orchestration|instance manage|docker|"
                        r"mediabox|copier|encoder|decoder|bridge|\bsrt\b|playeroftvu|meshadapter|\bmh-\d")
# the environment deployments Helm's Release & QA block parses (report_blocks: a `[Release MediaHub …]` or `[J2N … Deploy]`
# bracket, or `deploy vX to <env>`); a QA verdict on one of them is the block's too
ENV_DEPLOY = re.compile(r"(?i)\[(?:release\s+mediahub[^\]]*|j2n[^\]]*deploy[^\]]*)\]|deploy\s+v?[\d.]+\S*\s+to\s+[\w.\-]+")
QA_REPORT = re.compile(r"(?i)test repor|\bverification\b|\bqa report\b")
RELEASE = re.compile(r"(?i)\brelease|\bdeploy|\bbuild\b|\d+\.\d+\.\d+")
DOCKER = re.compile(r"\b([A-Za-z0-9][A-Za-z0-9_\-]*):(\d+\.\d+\.\d+(?:\.\d+)?)\b")     # Helm's image:version shape


# ── site and paths ───────────────────────────────────────────────────────────────────────────────────

def site():
    try:
        return json.load(open(SITE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def runtime():
    return F.runtime_root()


def published_root():
    return os.environ.get("ELA_TEAMREPORT_PUBLISHED") or site().get("published") or ""


def helm_data():
    s = site()
    return os.path.join(s.get("projects") or os.path.expanduser("~/projects"), "helm", "data")


def draft_dir(kind, ident):
    d = os.path.join(runtime(), "drafts", "team-report", f"{kind}-{ident}")
    os.makedirs(d, exist_ok=True)
    return d


def compare_path(kind, ident):
    d = os.path.join(runtime(), "drafts", "report-compare")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{kind}-{ident}.md")


def published_path(kind, ident, root=None):
    return os.path.join(root or published_root(), "reports", kind, f"{ident}.json")


def facts_file(*parts):
    return os.path.join(runtime(), "facts", *parts)


# ── time ─────────────────────────────────────────────────────────────────────────────────────────────

def local_tz():
    return datetime.datetime.now().astimezone().tzinfo


def day_window(date_str, now=None):
    """[local midnight, the next one or now) for a YYYY-MM-DD day."""
    d = datetime.date.fromisoformat(date_str)
    start = datetime.datetime(d.year, d.month, d.day, tzinfo=local_tz())
    end = start + datetime.timedelta(days=1)
    now = now or F.now()
    return start, min(end, max(now, start))


def week_bounds(week):
    m = re.fullmatch(r"(\d{4})-W(\d{2})", week or "")
    if not m:
        raise ValueError(f"not an ISO week (YYYY-Www): {week!r}")
    monday = datetime.date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    return monday, monday + datetime.timedelta(days=6)


def last_full_week(today=None):
    today = today or F.now().date()
    y, w, _ = (today - datetime.timedelta(days=7)).isocalendar()
    return f"{y}-W{w:02d}"


def week_window(week, now=None):
    monday, _ = week_bounds(week)
    start = datetime.datetime(monday.year, monday.month, monday.day, tzinfo=local_tz())
    end = start + datetime.timedelta(days=7)
    now = now or F.now()
    return start, min(end, max(now, start))


def jira_time(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.datetime.fromisoformat(s)
    except ValueError:
        return None


def age_label(hours):
    return f"{int(hours // 24)}d" if hours >= 24 else f"{int(hours)}h"


# ── facts: Jira ──────────────────────────────────────────────────────────────────────────────────────

def _f(issue):
    return issue.get("fields") or {}


def _name(person, default="Unassigned"):
    return (person or {}).get("displayName") or default


def touched_in(issue, start, end):
    """Whether the issue moved inside [start, end): its `updated`, a changelog entry, a comment or its creation. The
    sweep keeps an issue's latest state, so a day in the past is read from the history, not from `updated` alone."""
    def inside(s):
        t = jira_time(s)
        return t is not None and start <= t < end
    f = _f(issue)
    if inside(f.get("updated")) or inside(f.get("created")):
        return True
    for h in (issue.get("changelog") or {}).get("histories") or []:
        if inside(h.get("created")):
            return True
    for c in (issue.get("comments") or ((f.get("comment") or {}).get("comments")) or []):
        if inside(c.get("created")) or inside(c.get("updated")):
            return True
    return False


def jira_window(start, end):
    """(updated, created, read_at, gap): the MH issues that moved, and those created, inside the window."""
    rows = F.read_json(facts_file("jira", "changes.json"), []) or []
    wm = F.read_json(facts_file("jira", "watermark.json"), {}) or {}
    mh = [i for i in rows if str(i.get("key", "")).startswith(PROJECT + "-")]
    created = [i for i in mh if (lambda t: t is not None and start <= t < end)(jira_time(_f(i).get("created")))]
    updated = [i for i in mh if touched_in(i, start, end)]
    return updated, created, wm.get("at"), (wm.get("gap") or {}).get("why")


def board_state(now=None):
    """(blocked rows, in-progress rows, read_at): the standing query, each row with its hours since update."""
    doc = F.read_json(facts_file("jira", "queries", "board-state.json"), {}) or {}
    now = now or F.now()
    blocked, inprog = [], []
    for i in doc.get("issues") or []:
        f = _f(i)
        t = jira_time(f.get("updated"))
        hours = max(0.0, (now - t).total_seconds() / 3600) if t else 0.0
        row = {"key": i.get("key"), "summary": f.get("summary") or "", "assignee": _name(f.get("assignee")),
               "priority": (f.get("priority") or {}).get("name") or "?", "status": (f.get("status") or {}).get("name") or "?",
               "hours": hours}
        (blocked if row["status"].lower() == "blocked" else inprog).append(row)
    blocked.sort(key=lambda r: -r["hours"])
    return blocked, inprog, doc.get("at")


def issue_line(i, with_status=True):
    f = _f(i)
    parts = [f"- [{i['key']}] {f.get('summary') or ''}", f"assignee={_name(f.get('assignee'))}"]
    if with_status:
        parts.append(f"status={(f.get('status') or {}).get('name') or '?'}")
    parts.append(f"priority={(f.get('priority') or {}).get('name') or '?'}")
    return " | ".join(parts)


# ── facts: Slack ─────────────────────────────────────────────────────────────────────────────────────

def roster():
    """{slack id: name}, {email: name} of the core scope, [(area, [names])] from the published roster; empty when it
    cannot be read."""
    try:
        sys.path.insert(0, os.path.join(SKILLS, "team"))
        import team as T  # noqa: E402
        _, people = T.read_roster()
    except (Exception, SystemExit):
        return {}, {}, []
    by_slack = {p["slack"]: p["name"] for p in people if p.get("slack") and p.get("name")}
    # mail is kept by its sender only for MediaHub's own people: a related person's release mail is another product's
    by_email = {p["email"].lower(): p["name"] for p in people if p.get("email") and p.get("name") and p.get("scope") == "core"}
    areas = {}
    for p in people:
        for r in p.get("responsibilities") or []:
            if r.get("scope") == "core" and r.get("area"):
                areas.setdefault(r["area"], [])
                if p["name"] not in areas[r["area"]]:
                    areas[r["area"]].append(p["name"])
    return by_slack, by_email, sorted(areas.items())


def permalink(channel, ts):
    return f"https://tvunetworks.slack.com/archives/{channel}/p{ts.replace('.', '')}"


def _human(m):
    return not m.get("subtype") and not m.get("bot_id") and m.get("user")


def _clip(text, n=MAX_SLACK_TEXT):
    text = (text or "").strip()
    return text[:n] + "..." if len(text) > n else text


def slack_window(start, end, names=None):
    """(messages, read_at, gap): every human post and reply inside the window, in the channels the store holds."""
    d = facts_file("slack")
    wm = F.read_json(os.path.join(d, "watermark.json"), {}) or {}
    chans = {c["id"]: c.get("name") or c["id"] for c in (F.read_json(os.path.join(d, "channels.json"), {}) or {}).get("channels") or []}
    users = {u: (v or {}).get("name") for u, v in ((F.read_json(os.path.join(d, "users.json"), {}) or {}).get("users") or {}).items()}
    names = names or {}
    lo, hi = start.timestamp(), end.timestamp()
    out = []
    files = sorted(f for f in os.listdir(d) if re.fullmatch(r"[A-Z0-9]+\.json", f) and f not in ("channels.json", "users.json")) if os.path.isdir(d) else []
    for fn in files:
        ch = fn[:-5]
        doc = F.read_json(os.path.join(d, fn), {}) or {}
        name = chans.get(ch, ch)
        parents = doc.get("messages") or {}
        def rec(m, kind, parent=None):
            r = {"channel": ch, "channel_name": name, "author": names.get(m["user"]) or users.get(m["user"]) or m["user"],
                 "text": _clip(m.get("text")), "ts": m["ts"], "kind": kind,
                 "permalink": permalink(ch, m.get("thread_ts") or m["ts"])}
            if parent is not None:
                r["parent_text"] = _clip(parent.get("text"))
            return r
        for ts, m in parents.items():
            if _human(m) and lo <= float(ts) < hi:
                out.append(rec(m, "post"))
        for root, th in (doc.get("replies") or {}).items():
            for m in th.get("messages") or []:
                if m.get("ts") == root or not _human(m) or not (lo <= float(m.get("ts") or 0) < hi):
                    continue
                out.append(rec(m, "reply", parents.get(root) or {}))
    out.sort(key=lambda r: float(r["ts"]))
    return out, wm.get("at"), (wm.get("gap") or {}).get("why")


# ── facts: mail ──────────────────────────────────────────────────────────────────────────────────────

def _sender(frm):
    m = re.match(r'\s*"?([^"<]+?)"?\s*<([^>]+)>', frm or "")
    return (m.group(1).strip(), m.group(2).strip().lower()) if m else ((frm or "").strip(), (frm or "").strip().lower())


def mail_kind(subject, body):
    """block (an environment deployment, or a QA verdict on one: Helm's Release & QA block owns its facts) · qa (a QA
    report on anything else: the narrative cites its counts) · docker (an image or module release, the narrative's
    own) · other."""
    subject = subject or ""
    if ENV_DEPLOY.search(subject):
        return "block"
    if QA_REPORT.search(subject):
        return "qa"
    if DOCKER.search(subject) or re.search(r"(?i)docker", subject) or RELEASE.search(subject):
        return "docker"
    return "other"


def mail_window(start, end, by_email=None):
    """(messages, read_at, gap): the day's mail from the release, test-report and team standing searches, MediaHub's
    only (a roster sender, or a MediaHub subject), newest last, deduplicated by id."""
    idx = F.read_json(facts_file("mail", "index.json"), {}) or {}
    wm = F.read_json(facts_file("mail", "watermark.json"), {}) or {}
    by_email = by_email or {}
    lo, hi = start.timestamp(), end.timestamp()
    seen, out = set(), []
    for name in ("release", "test-report", "team"):
        for mid in (idx.get(name) or {}).get("ids") or []:
            if mid in seen:
                continue
            seen.add(mid)
            m = F.read_json(facts_file("mail", "messages", f"{mid}.json"))
            if not m or not (lo <= int(m.get("internal_date") or 0) < hi):
                continue
            display, addr = _sender(m.get("from"))
            subject = m.get("subject") or ""
            if addr not in by_email and not MH_SUBJECT.search(subject):
                continue
            body = re.sub(r"\s+", " ", (m.get("body") or m.get("snippet") or "")).strip()
            out.append({"id": mid, "subject": subject, "from": by_email.get(addr) or display, "date": m.get("date") or "",
                        "internal_date": int(m.get("internal_date") or 0), "body": body,
                        "kind": mail_kind(subject, body), "keys": sorted(set(KEY_RX.findall(subject + " " + body)))})
    out.sort(key=lambda r: r["internal_date"])
    return out, wm.get("at"), (wm.get("gap") or {}).get("why")


# ── the daily input ──────────────────────────────────────────────────────────────────────────────────

def source_state(count, read_at, gap):
    return {"status": "gap" if gap else ("ok" if read_at else "unread"), "count": count, "read_at": read_at,
            **({"gap": gap} if gap else {})}


def team_section(areas):
    if not areas:
        return "## Team routing reference\n(the roster could not be read)"
    return "## Team routing reference (who holds each area, from the roster)\n" + "\n".join(
        f"- {a}: {', '.join(n)}" for a, n in areas)


def slack_line(m, with_parent=False, prefix=""):
    ref = f"[#{m['channel_name']}]({m['permalink']})"
    text = m["text"].replace("\n", " ")
    keys = sorted(set(KEY_RX.findall(text + " " + (m.get("parent_text") or ""))))
    tag = f" [refs: {', '.join(keys)}]" if keys else ""
    pre = f"[{prefix}] " if prefix else ""
    if with_parent and m.get("parent_text"):
        return f"- {pre}@{m['author']} in {ref}, replying to \"{m['parent_text'].replace(chr(10), ' ')}\": \"{text}\"{tag}"
    return f"- {pre}@{m['author']} in {ref}: \"{text}\"{tag}"


def mail_line(m):
    refs = f" [refs: {', '.join(m['keys'][:5])}]" if m["keys"] else ""
    if m["kind"] == "block":
        body = _clip(m["body"], MAIL_BODY_CAP)
        return (f"- [release/QA — Helm's block; do NOT restate any version, env, build, bundle or count from it] "
                f"\"{m['subject']}\" — from {m['from']} ({m['date']}){refs}: {body}")
    if m["kind"] == "qa":
        return f"- [QA report] \"{m['subject']}\" — from {m['from']} ({m['date']}){refs}: {_clip(m['body'], MAIL_BODY_CAP)}"
    if m["kind"] == "docker":
        imgs = ", ".join(f"{a}:{b}" for a, b in DOCKER.findall(m["subject"] + " " + m["body"][:600])) or m["subject"]
        return f"- [docker release] {imgs} — \"{m['subject']}\" (by {m['from']}, {m['date']}){refs}: {_clip(m['body'], MAIL_BODY_CAP)}"
    return f"- [other] \"{m['subject']}\" — from {m['from']} ({m['date']}){refs}: {_clip(m['body'], MAIL_SNIPPET_CAP)}"


def daily_input(date_str, now=None):
    """The day's data, read from the store → {state, prompt, keys, sources, counts}."""
    now = now or F.now()
    start, end = day_window(date_str, now)
    by_slack, by_email, areas = roster()
    updated, created, jira_at, jira_gap = jira_window(start, end)
    blocked, _, board_at = board_state(now)
    slack, slack_at, slack_gap = slack_window(start, end, by_slack)
    seen = len(slack)
    if seen > MAX_SLACK:
        prj_first = [m for m in slack if m["channel_name"] == PRJ_CHANNEL][:MAX_SLACK]
        rest = [m for m in slack if m["channel_name"] != PRJ_CHANNEL][-(MAX_SLACK - len(prj_first)):] if len(prj_first) < MAX_SLACK else []
        slack = sorted(prj_first + rest, key=lambda r: float(r["ts"]))
    mail, mail_at, mail_gap = mail_window(start, end, by_email)
    sources = {"jira": source_state(len(updated) + len(created) - len({i["key"] for i in created} & {i["key"] for i in updated}), jira_at, jira_gap),
               "slack": {**source_state(len(slack), slack_at, slack_gap), **({"cap_hit": True, "seen": seen} if seen > MAX_SLACK else {})},
               "mail": source_state(len(mail), mail_at, mail_gap)}
    sources["jira"]["board_read_at"] = board_at
    if not updated and not created and not slack and not mail:
        state = "incomplete" if any(s["status"] != "ok" for s in sources.values()) else "quiet"
        return {"kind": "daily", "id": date_str, "state": state, "prompt": "", "keys": [], "sources": sources,
                "window": [start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")]}

    prj = [m for m in slack if m["channel_name"] == PRJ_CHANNEL]
    other = [m for m in slack if m["channel_name"] != PRJ_CHANNEL]
    posts = [m for m in slack if m["kind"] == "post"]
    replies = [m for m in slack if m["kind"] == "reply"]
    per_channel, mentions = {}, {}
    for m in slack:
        per_channel[m["channel_name"]] = per_channel.get(m["channel_name"], 0) + 1
        for k in KEY_RX.findall(m["text"] + " " + (m.get("parent_text") or "")):
            mentions[k] = mentions.get(k, 0) + 1
    glance = [f"- Jira updated today: {len(updated)} tickets", f"- Jira created today: {len(created)} tickets",
              f"- Currently blocked: {len(blocked)} tickets",
              f"- Slack: {len(posts)} posts, {len(replies)} replies across {len(per_channel)} channel(s)"]
    if prj:
        glance.append(f"- #{PRJ_CHANNEL} today: {len(prj)} message(s)  ← primary item-centric signal")
    if mentions:
        glance.append("- Slack ↔ Jira cross-references: " + ", ".join(f"{k}×{c}" for k, c in sorted(mentions.items(), key=lambda x: -x[1])[:8]))
    if per_channel:
        glance.append("- Top Slack channels by volume: " + ", ".join(f"#{c}×{n}" for c, n in sorted(per_channel.items(), key=lambda x: -x[1])[:5]))
    if sources["slack"]["status"] != "ok":
        glance.append("- NOTE: Slack capture incomplete — synthesize from available signal.")
    if mail:
        glance.append(f"- Mail: {len(mail)} message(s) (QA / docker release / deploy mail)")
    rq = [m for m in mail if m["kind"] == "block"]
    if rq:
        glance.append(f"- Release & QA mail (Helm parses it into its own block below your Summary): {len(rq)} message(s)")

    S = ["## Day at a glance\n" + "\n".join(glance)]
    S.append(f"## Tickets updated today ({len(updated)} total — treat as raw signal, do not list verbatim)\n"
             "Look for themes: same component, same customer, paired BE+UI tickets, sequential keys, same feature.\n"
             + ("\n".join(issue_line(i) for i in updated[:MAX_UPDATED]) or "(none)"))
    S.append(f"## Tickets created today ({len(created)} total)\n"
             "Group paired/related tickets (BE+UI pairs, sequential keys, same component/feature).\n"
             + ("\n".join(issue_line(i, with_status=False) for i in created[:MAX_CREATED]) or "(none)"))
    S.append(f"## Currently blocked ({len(blocked)} total)\n"
             + ("\n".join(f"- [{r['key']}] {r['summary']} | assignee={r['assignee']} | blocked for={age_label(r['hours'])}" for r in blocked) or "(none)"))
    if mail:
        S.append(f"## Mail — {len(mail)} message(s)\n" + "\n".join(mail_line(m) for m in mail[:MAX_MAIL])
                 + ("\n\n(NOTE: mail capture incomplete — synthesize from available signal.)" if sources["mail"]["status"] != "ok" else ""))
    else:
        S.append("## Mail\n(no MediaHub mail today)")
    if prj:
        S.append(f"## Project channel — #{PRJ_CHANNEL}  ({len(prj)} message(s) — PRIMARY signal for today's items)\n"
                 "This is the team's main project channel. Treat its content as the authoritative source for today's\n"
                 "in-flight items — many of these do not have a Jira ticket yet. Group by topic; cross-link to Jira when\n"
                 "keys match or summaries align.\n"
                 + "\n".join(slack_line(m, m["kind"] == "reply", m["kind"]) for m in prj[:MAX_PRJ]))
    op = [m for m in other if m["kind"] == "post"]
    orp = [m for m in other if m["kind"] == "reply"]
    S.append(f"## Other Slack — Posts ({len(op)} total)\n" + "\n".join(slack_line(m) for m in op[:MAX_OTHER]) if op else "## Other Slack — Posts\n(none captured)")
    S.append(f"## Other Slack — Replies ({len(orp)} total)\n" + "\n".join(slack_line(m, True) for m in orp[:MAX_OTHER]) if orp else "## Other Slack — Replies\n(none captured)")
    S.append(team_section(areas))
    data = "\n\n".join(S)
    rules = open(os.path.join(HERE, "daily.md"), encoding="utf-8").read().replace("{date}", date_str)
    prompt = rules.rstrip() + "\n\n--- BEGIN DATA ---\n" + data + "\n--- END DATA ---\n"
    return {"kind": "daily", "id": date_str, "state": "ok", "prompt": prompt, "keys": sorted(set(KEY_RX.findall(data))),
            "sources": sources, "window": [start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")]}


# ── the weekly input ─────────────────────────────────────────────────────────────────────────────────

def week_metrics(start, end, now=None):
    """The week's numbers from the store: created, closed, actively updated, carry-over, Blocked and In Progress now."""
    now = now or F.now()
    rows = [i for i in (F.read_json(facts_file("jira", "changes.json"), []) or []) if str(i.get("key", "")).startswith(PROJECT + "-")]
    inside = lambda s: (lambda t: t is not None and start <= t < end)(jira_time(s))  # noqa: E731
    created = [i for i in rows if inside(_f(i).get("created"))]
    closed = [i for i in rows if inside(_f(i).get("resolutiondate")) or any(
        inside(h.get("created")) and any(it.get("field") == "status" and str(it.get("toString") or "").lower() in TERMINAL for it in h.get("items") or [])
        for h in (i.get("changelog") or {}).get("histories") or [])]
    active = [i for i in rows if touched_in(i, start, end) and not inside(_f(i).get("created"))]
    blocked, inprog, board_at = board_state(now)
    carry = {}
    for i in created + active:
        if i["key"] not in carry and str((_f(i).get("status") or {}).get("name") or "").lower() not in TERMINAL:
            carry[i["key"]] = i
    def hours(i):
        t = jira_time(_f(i).get("updated"))
        return max(0.0, (now - t).total_seconds() / 3600) if t else 0.0
    tally = {}
    for i in created + closed + active:
        n = _name(_f(i).get("assignee"), "")
        if n:
            tally[n] = tally.get(n, 0) + 1
    long_blocked = [r for r in blocked if r["hours"] >= LONG_BLOCKED_DAYS * 24]
    return {"counts": {"created": len(created), "closed": len(closed), "active_updated": len(active), "in_progress": len(inprog),
                       "blocked": len(blocked), "long_blocked": len(long_blocked),
                       "stale_red": sum(1 for r in inprog if r["hours"] >= 48), "stale_yellow": sum(1 for r in inprog if 24 <= r["hours"] < 48),
                       "carry_over": len(carry)},
            "per_assignee": sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))[:8],
            "blocked": blocked[:MAX_LISTED], "long_blocked": long_blocked[:MAX_LISTED],
            "carry_over": [{"key": i["key"], "summary": _f(i).get("summary") or "", "assignee": _name(_f(i).get("assignee")),
                            "status": (_f(i).get("status") or {}).get("name") or "?", "hours": hours(i)}
                           for i in sorted(carry.values(), key=lambda i: -hours(i))[:MAX_LISTED]],
            "keys": sorted({i["key"] for i in created + closed + active}), "board_read_at": board_at}


def weekly_input(week, now=None):
    now = now or F.now()
    start, end = week_window(week, now)
    monday, sunday = week_bounds(week)
    m = week_metrics(start, end, now)
    _, by_email, _ = roster()
    mail, mail_at, mail_gap = mail_window(start, end, by_email)
    shipped = [x for x in mail if x["kind"] in ("block", "qa", "docker")]
    dailies, index, total, cap_hit = [], {}, 0, False
    for n in range(7):
        d = (monday + datetime.timedelta(days=n)).isoformat()
        doc = F.read_json(published_path("daily", d))
        body = ((doc or {}).get("narrative") or "").strip()
        if not body:
            continue
        for k in sorted(set(KEY_RX.findall(body))):
            index.setdefault(k, []).append(d)
        if len(body) > MAX_DAILY_BODY:
            body, cap_hit = body[:MAX_DAILY_BODY] + "\n[... truncated by the prompt cap ...]", True
        if total + len(body) > MAX_TOTAL_DAILY:
            cap_hit = True
            break
        total += len(body)
        dailies.append((d, body))
    jira_wm = F.read_json(facts_file("jira", "watermark.json"), {}) or {}
    sources = {"jira": {**source_state(m["counts"]["created"] + m["counts"]["active_updated"], jira_wm.get("at"), (jira_wm.get("gap") or {}).get("why")),
                        "board_read_at": m["board_read_at"]},
               "mail": source_state(len(mail), mail_at, mail_gap),
               "dailies": {"status": "ok" if dailies else "missing", "count": len(dailies), "dates": [d for d, _ in dailies],
                           "cap_hit": cap_hit}}
    arcs = [f"- {k}: written about on {', '.join(v)} ({len(v)} days)" for k, v in index.items() if len(v) >= 2]
    arcs += [f"- {k}: {v[0]} only" for k, v in index.items() if len(v) == 1]
    c = m["counts"]
    sections = [
        "**Shipped this week** (the week's release, deploy, QA and image mail; Helm renders the parsed facts)\n"
        + ("\n".join(f"- \"{x['subject']}\" — {x['from']}" + (f" [refs: {', '.join(x['keys'][:5])}]" if x["keys"] else "") for x in shipped[:MAX_MAIL]) or "- (none)"),
        "**Numbers**\n" + "\n".join([f"- Created {c['created']} · closed {c['closed']} · actively updated {c['active_updated']}",
                                     f"- In Progress now {c['in_progress']} (stale over 48h {c['stale_red']}, 24–48h {c['stale_yellow']})",
                                     f"- Blocked now {c['blocked']} (over {LONG_BLOCKED_DAYS} days {c['long_blocked']}) · carry-over {c['carry_over']}",
                                     "- Most active: " + (", ".join(f"{n} {k}" for n, k in m["per_assignee"]) or "(none)")]),
        "**Blocked & at risk**\n" + ("\n".join(f"- {r['key']} {r['summary']} — {r['assignee']}, {age_label(r['hours'])} since update" for r in m["blocked"]) or "- (none)"),
        "**Carry-over into next week**\n" + ("\n".join(f"- {r['key']} {r['summary']} — {r['assignee']}, {r['status']}" for r in m["carry_over"]) or "- (none)"),
    ]
    rules = (open(os.path.join(HERE, "weekly.md"), encoding="utf-8").read()
             .replace("{week}", week).replace("{start}", monday.isoformat()).replace("{end}", sunday.isoformat()))
    parts = [rules.rstrip(), "",
             "## Ticket arcs — which days each ticket was written about (DATA)\n"
             "This index is what makes an arc computable: a key discussed on four days is one initiative that moved through\n"
             "the week. Use it to decide what is an arc and what is a one-off.\n--- BEGIN ARC INDEX ---\n"
             + ("\n".join(arcs) or "(no ticket keys found in this week's dailies)") + "\n--- END ARC INDEX ---\n",
             "## The sections the report carries below yours (DATA)\n"
             "You are shown them so you do not duplicate them and so you can react to them in prose WITHOUT restating any\n"
             "of their numbers.\n--- BEGIN SECTIONS ---\n" + "\n\n".join(sections) + "\n--- END SECTIONS ---\n"]
    if dailies:
        parts.append(f"## The week's daily reports ({len(dailies)} of 5 weekdays present) — RAW MATERIAL (DATA)\n"
                     "Read all of them, then write about the WEEK. Do not summarise them one by one.\n")
        parts += [f"--- BEGIN DAILY DATA {d} ---\n{b}\n--- END DAILY DATA {d} ---\n" for d, b in dailies]
    else:
        parts.append("## The week's daily reports — NONE AVAILABLE\n"
                     "No daily report exists for any weekday of this week, so you have no narrative raw material. Write the two\n"
                     "sections from the sections above alone, and say plainly in the paragraph that the week's narrative record\n"
                     "is missing and this report is therefore thin. Do NOT invent activity to fill it.\n")
    prompt = "\n".join(parts)
    keys = sorted(set(KEY_RX.findall(prompt)) | set(m["keys"]))
    return {"kind": "weekly", "id": week, "state": "ok", "prompt": prompt, "keys": keys, "sources": sources,
            "range": [monday.isoformat(), sunday.isoformat()],
            "window": [start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")], "counts": c}


# ── the checks on a narrative ────────────────────────────────────────────────────────────────────────

HEADING_RX = re.compile(r"^\s{0,3}\*\*(?P<text>[^*]{1,80})\*\*\s*:?\s*$")
MD_HEADING_RX = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
DAILY_OWNED = {"release & qa", "release and qa", "releases", "release", "qa", "qa verdict", "deployments", "deploys", "sources"}
WEEKLY_OWNED = DAILY_OWNED | {"shipped this week", "shipped", "numbers", "the numbers", "by the numbers", "metrics",
                              "blocked & at risk", "blocked and at risk", "blocked", "at risk", "blockers",
                              "blockers & escalations", "blockers and escalations", "carry-over into next week",
                              "carry over into next week", "carry-over", "carry over", "carryover"}
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "mon", "tue", "tues", "wed",
            "thu", "thur", "thurs", "fri", "sat", "sun")
VERSION_RX = re.compile(r"\bmh\d{1,4}(?:\.\d{1,4}){0,4}@[A-Za-z0-9][\w.@\-]{0,40}"
                        r"|\b(?:builds?|bundles?|versions?|ver)\s+v?\d[\w.\-]{0,40}"
                        r"|(?<![\w.])v?\d{1,6}(?:\.\d{1,6}){1,5}%?(?!\d)", re.I)


def heading_key(line):
    m = HEADING_RX.match(line or "")
    return re.sub(r"\s+", " ", m.group("text")).strip().rstrip(":").strip().lower() if m else ""


def owned(key, kind):
    if not key:
        return False
    if key in (WEEKLY_OWNED if kind == "weekly" else DAILY_OWNED):
        return True
    if kind == "weekly":
        if re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}", key):
            return True
        first = key.replace(",", " ").split()
        return bool(first) and first[0] in WEEKDAYS
    return False


def tidy(text):
    """The punctuation an excision leaves: an emptied parenthesis, a run of separators, a dangling one."""
    out = re.sub(r"\(\s*(?:[,;/]\s*)*\)", "", text)
    out = re.sub(r"(?:[,;]\s*){2,}", ", ", out)
    out = re.sub(r"\s*[,;]\s*\)", ")", out)
    out = re.sub(r"\(\s*[,;]\s*", "(", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return re.sub(r" +([,.;:])", r"\1", out)


def check_narrative(text, kind, allowed):
    """(clean text, what was removed): headings to bold, the sections Helm owns out, the Sources line out, unknown
    keys out, and in the weekly the version-shaped tokens."""
    removed = {"sections": [], "keys": [], "tokens": [], "lines": []}
    lines = []
    for ln in (text or "").replace("\r\n", "\n").strip().split("\n"):
        m = MD_HEADING_RX.match(ln)
        lines.append(f"**{m.group(1).strip('*').strip()}**" if m else ln)
    while lines and re.search(r"(?i)\breport\b", lines[0]) and HEADING_RX.match(lines[0]) and heading_key(lines[0]) not in ("summary",):
        removed["lines"].append(lines.pop(0).strip())                     # a document title the model added
    kept, i = [], 0
    while i < len(lines):
        if owned(heading_key(lines[i]), kind):
            removed["sections"].append(lines[i].strip())
            i += 1
            while i < len(lines) and not HEADING_RX.match(lines[i]):
                i += 1
            continue
        if re.match(r"^\s*_?sources:", lines[i], re.I):
            removed["lines"].append(lines[i].strip())
            i += 1
            continue
        kept.append(lines[i])
        i += 1
    while kept and (not kept[-1].strip() or kept[-1].strip() in ("---", "***", "___")):
        kept.pop()
    out = "\n".join(kept)
    allow = set(allowed or ())
    def key_sub(mt):
        if mt.group(0) in allow:
            return mt.group(0)
        removed["keys"].append(mt.group(0))
        return ""
    out = KEY_RX.sub(key_sub, out)
    if kind == "weekly":
        def ver_sub(mt):
            removed["tokens"].append(mt.group(0))
            return ""
        out = VERSION_RX.sub(ver_sub, out)
    if removed["keys"] or removed["tokens"]:
        out = tidy(out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out, {k: sorted(set(v)) for k, v in removed.items() if v}


def missing_sections(text, kind):
    need = ["summary"] if kind == "daily" else ["week in one paragraph", "themes"]
    have = {heading_key(ln) for ln in text.split("\n")}
    return [n for n in need if n not in have]


# ── publish ──────────────────────────────────────────────────────────────────────────────────────────

def publish(doc, root=None):
    """The report through the publish redaction and guard, then report.md as reports/README.md, each atomically.
    → (path, None) or (None, the guard's flags) with the published copy unchanged."""
    sys.path.insert(0, os.path.join(SKILLS, "publish"))
    import publish as P  # noqa: E402
    root = root or published_root()
    name = f"{doc['id']}.json"
    text = P.redact(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    flags = P.guard_flags(text, name)
    if flags:
        return None, [f"{n}: {why}: {line}" for n, why, line in flags[:5]]
    out = os.path.join(root, "reports", doc["kind"])
    os.makedirs(out, exist_ok=True)
    for d, fname, body in ((out, name, text), (os.path.join(root, "reports"), "README.md", open(os.path.join(HERE, "report.md"), encoding="utf-8").read())):
        tmp = os.path.join(d, f".{fname}.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp, os.path.join(d, fname))
    return os.path.join(out, name), None


def build_doc(inp, narrative, removed, model):
    doc = {"schema": SCHEMA, "kind": inp["kind"], "id": inp["id"], "state": inp["state"],
           "generated_at": F.now_iso(), "writer": "ela teamreport", "model": model,
           "narrative": narrative, "keys": sorted(set(KEY_RX.findall(narrative))), "sources": inp["sources"],
           "window": inp.get("window"), "removed": removed}
    if inp["kind"] == "daily":
        doc["date"] = inp["id"]
    else:
        doc["week"], doc["range"] = inp["id"], inp.get("range")
    return doc


# ── compare ──────────────────────────────────────────────────────────────────────────────────────────

def read_helm(path):
    """Helm's report .md → (front matter dict of raw strings, body); (None, None) when absent."""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return None, None
    front = {}
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if m:
        for ln in m.group(1).split("\n"):
            if ":" in ln:
                k, v = ln.split(":", 1)
                front[k.strip()] = v.strip()
        text = text[m.end():]
    text = re.sub(r"^\s*#\s+[^\n]*\n", "", text, count=1)
    return front, text.strip()


def helm_narrative(body, kind):
    """Helm's body without the parts ela does not write (Release & QA, the Sources line, the weekly's computed
    sections), so the two narratives are compared like for like."""
    clean, _ = check_narrative(body, kind, KEY_RX.findall(body))
    return clean


def words(text):
    return len(re.findall(r"\w+", text or ""))


def compare(kind, ident, helm_dir=None):
    sub = "reports" if kind == "daily" else "weekly_reports"
    hpath = os.path.join(helm_dir or helm_data(), sub, f"{ident}.md")
    front, hbody = read_helm(hpath)
    ela_doc = F.read_json(published_path(kind, ident))
    L = [f"# Team report, side by side — {kind} {ident}", ""]
    hn = helm_narrative(hbody, kind) if hbody else ""
    en = (ela_doc or {}).get("narrative") or ""
    hk, ek = set(KEY_RX.findall(hn)), set(KEY_RX.findall(en))
    L += ["| | Helm | ela |", "|---|---|---|",
          f"| written | {(front or {}).get('generated_at') or 'not written'} | {(ela_doc or {}).get('generated_at') or 'not written'} |",
          f"| words (narrative) | {words(hn)} | {words(en)} |",
          f"| keys cited | {len(hk)} | {len(ek)} |",
          f"| sections | {', '.join(h for h in (heading_key(x) for x in hn.split(chr(10))) if h) or '—'} | {', '.join(h for h in (heading_key(x) for x in en.split(chr(10))) if h) or '—'} |"]
    if ela_doc:
        src = " · ".join("{} {}({})".format(k, v.get("status"), v.get("count")) for k, v in (ela_doc.get("sources") or {}).items())
        L.append(f"| ela's sources | | {src} |")
    if front and front.get("legs"):
        L.append(f"| Helm's legs | {front['legs'][:300]} | |")
    L += ["", f"- Keys only Helm cites: {', '.join(sorted(hk - ek)) or 'none'}",
          f"- Keys only ela cites: {', '.join(sorted(ek - hk)) or 'none'}",
          f"- Keys both cite: {len(hk & ek)}"]
    if ela_doc and ela_doc.get("removed"):
        L.append(f"- Removed from ela's text by the checks: {json.dumps(ela_doc['removed'], ensure_ascii=False)}")
    L += ["", "## Helm", "", hbody or f"_Helm has not written {hpath} yet._", "", "## ela", "",
          en or f"_ela has not published {kind} {ident} yet._", ""]
    path = compare_path(kind, ident)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    return {"path": path, "helm": bool(hbody), "ela": bool(en), "helm_only": sorted(hk - ek), "ela_only": sorted(ek - hk),
            "both": len(hk & ek), "words": {"helm": words(hn), "ela": words(en)}}


# ── commands ─────────────────────────────────────────────────────────────────────────────────────────

def ident_of(a):
    if a.kind == "daily":
        d = a.date or F.now().date().isoformat()
        datetime.date.fromisoformat(d)
        return d
    w = a.week or last_full_week()
    week_bounds(w)
    return w


def cmd_prompt(a):
    ident = ident_of(a)
    inp = daily_input(ident) if a.kind == "daily" else weekly_input(ident)
    d = draft_dir(a.kind, ident)
    ppath = os.path.join(d, "prompt.md")
    if inp["prompt"]:
        with open(ppath, "w", encoding="utf-8") as fh:
            fh.write(inp["prompt"])
    elif os.path.exists(ppath):
        os.remove(ppath)
    meta = {k: v for k, v in inp.items() if k != "prompt"}
    meta["read_at"] = F.now_iso()
    F.write_json(os.path.join(d, "input.json"), meta)
    out = {**meta, "prompt": ppath if inp["prompt"] else None, "model_needed": bool(inp["prompt"])}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        src = " · ".join(f"{k} {v.get('status')}({v.get('count')})" for k, v in inp["sources"].items())
        print(f"{a.kind} {ident}: {inp['state']} · {src}")
        print(f"prompt: {ppath}" if inp["prompt"] else "no model needed: `write` publishes the stub")


def cmd_write(a):
    ident = ident_of(a)
    d = draft_dir(a.kind, ident)
    inp = F.read_json(os.path.join(d, "input.json"))
    if not inp:
        print(f"teamreport: no input for {a.kind} {ident}; run `ela teamreport prompt {a.kind}` first", file=sys.stderr)
        sys.exit(EX_NOTFOUND)
    if inp["state"] in ("quiet", "incomplete") and not a.narrative:
        narrative, removed, model = (STUB_QUIET if inp["state"] == "quiet" else STUB_INCOMPLETE), {}, False
    else:
        if not a.narrative:
            print("teamreport: --narrative FILE (or -) is needed: this input carries activity", file=sys.stderr)
            sys.exit(EX_USAGE)
        raw = sys.stdin.read() if a.narrative == "-" else open(a.narrative, encoding="utf-8").read()
        with open(os.path.join(d, "narrative.raw.md"), "w", encoding="utf-8") as fh:
            fh.write(raw)
        narrative, removed = check_narrative(raw, a.kind, inp.get("keys"))
        model = True
        if not narrative.strip():
            print("teamreport: the narrative is empty after the checks; nothing published", file=sys.stderr)
            sys.exit(EX_REFUSED)
        miss = missing_sections(narrative, a.kind)
        if miss:
            removed["missing_sections"] = miss
    doc = build_doc(inp, narrative, removed, model)
    path, flags = publish(doc)
    if flags:
        print("teamreport: the publish guard refused the report; the published copy is unchanged:\n  " + "\n  ".join(flags), file=sys.stderr)
        sys.exit(EX_REFUSED)
    sys.path.insert(0, os.path.join(SKILLS, "publish"))
    import mirror as M                       # noqa: E402 — the read-only Obsidian mirror of <published>, refreshed after the write
    M.after_publish(site(), published_root())
    if a.json:
        print(json.dumps({"path": path, "kind": a.kind, "id": ident, "state": doc["state"], "model": model,
                          "keys": len(doc["keys"]), "removed": removed}, ensure_ascii=False))
    else:
        print(f"wrote <published>/reports/{a.kind}/{ident}.json ({doc['state']}, {words(narrative)} words"
              + (f", removed {json.dumps(removed, ensure_ascii=False)}" if removed else "") + ")")


def cmd_compare(a):
    r = compare(a.kind, ident_of(a), a.helm)
    if a.json:
        print(json.dumps(r, ensure_ascii=False))
    else:
        print(f"{r['path']} · Helm {'written' if r['helm'] else 'not yet'} · ela {'written' if r['ela'] else 'not yet'}"
              f" · keys both {r['both']}, only Helm {len(r['helm_only'])}, only ela {len(r['ela_only'])}")


def cmd_show(a):
    ident = ident_of(a)
    doc = F.read_json(published_path(a.kind, ident))
    if not doc:
        print(f"teamreport: no published {a.kind} report for {ident}", file=sys.stderr)
        sys.exit(EX_NOTFOUND)
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print(f"{a.kind} {ident} · {doc.get('state')} · written {doc.get('generated_at')}\n")
        print(doc.get("narrative") or "")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ela teamreport", description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="Schema: report.md beside this script, published as <published>/reports/README.md.")
    ap.add_argument("--env-file", help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, hlp in (("prompt", cmd_prompt, "the writing rules and the data, as one prompt file"),
                          ("write", cmd_write, "check a narrative and publish it"),
                          ("compare", cmd_compare, "Helm's report and ela's, side by side"),
                          ("show", cmd_show, "the published report")):
        p = sub.add_parser(name, help=hlp)
        p.add_argument("kind", choices=("daily", "weekly"))
        p.add_argument("--date", help="daily: YYYY-MM-DD (default today)")
        p.add_argument("--week", help="weekly: YYYY-Www (default the last full week)")
        p.add_argument("--json", action="store_true")
        if name == "write":
            p.add_argument("--narrative", help="the model's text, a file or - for stdin; none for a quiet day's stub")
        if name == "compare":
            p.add_argument("--helm", help="Helm's data directory (default <projects>/helm/data)")
        p.set_defaults(fn=fn)
    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except ValueError as e:
        print(f"teamreport: {e}", file=sys.stderr)
        sys.exit(EX_USAGE)


if __name__ == "__main__":
    main()
