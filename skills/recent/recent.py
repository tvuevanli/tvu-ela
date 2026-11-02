#!/usr/bin/env python3
"""Recent: the week's MH tickets placed by release line and by lane — the facts behind the vault's `recent` page.

L1, stdlib only, read-only. One Jira search (tickets created or updated in the window, changelog expanded) is joined
with what ela already reads: the line from the ticket's `release:mh-<line>` label (map/release.yaml § lines), where its
fix stands from the Fixed In field against the lanes' versions as the last lane read saved them (`ela changes`,
`ela matrix --page`), what QA said from the lane test lists' state on disk (`ela testlist`), the lane a ticket names in
its summary or description, and what moved on it in the window. Nothing is written to Jira; the "no line" section
names the label ela would infer and leaves the write to a drafted action.

Usage:
    recent.py [--env-file F] [--days 7]            the page as Markdown
    recent.py … --json                             the result
    recent.py … --write                            keep the result as <reports>/recent/<date>.json; the vault's sync
                                                   renders recent.md from the newest file there

Exit codes: 0 ok · 2 usage · 5 a remote read failed.
Design: vault to-read/2026-11-02-recent-tickets-by-line-and-lane.md (ruled a dashboard, not a report, 2026-11-02).
"""
import argparse, datetime, json, os, re, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
for d in ("jira", "release", "promote", "brief", "stage"):
    sys.path.insert(0, os.path.join(SKILLS, d))
import jira as J  # noqa: E402  — credentials, the search endpoint, rich text as plain text, the Fixed In field
import release as R  # noqa: E402  — the release map (lines, lanes, Fixed In grammar) and the version grammar
import promote as P  # noqa: E402  — version comparison within a slug's rules
import brief as B  # noqa: E402  — the saved lane reads and the matrix cell with the lanes page's marks
import stage as S  # noqa: E402  — the terminal statuses: a Done ticket is not under test

SITE = os.path.expanduser("~/.claude/ela/site.json")
EX_USAGE, EX_REMOTE = 2, 5
LINE_ORDER = ("2.1", "2.0", "2.2")             # the lines the page opens with, in this order; other lines follow, then no line
ROLES = ("qa", "daily", "prod")
ROLE_RANK = {"qa": 1, "daily": 2, "prod": 3}
TRAIN_SERVICES = ("mediahub-backend", "mediahub-frontend")   # the train row: the app's two deliverables, with the lanes page's marks
ROWS_OPEN, ROWS_MIN = 8, 3                     # table rows a section shows open; the rest fold; lowered until the page fits
LIST_OPEN = 6                                  # keys a by-lane list names before "+N"
BUDGET = 1200                                  # the vault's budget for the page, counted outside folds
TITLE = "Recent · 7 days"
FIELDS = "summary,status,assignee,reporter,issuetype,priority,labels,created,updated,duedate,description," + J.FIXED_IN_FIELD
CHANGE_FIELDS = ("status", "Fixed In", "assignee", "priority", "labels")
SEARCH_LIMIT = 600
DAILY_RX = re.compile(r"\bdaily[\s-]*(mon|tue|wed|thu|fri)\b", re.I)
QA_RX = re.compile(r"\b(?:aws[\s-]*cn|qa[\s-]*cn|qa[\s-]*aws)[\s-]*(\d)\b", re.I)
PROD_RX = re.compile(r"\b(?:cn[\s-]*|china[\s-]*)?prod[\s-]*\d+(?:[\s-]*china)?\b", re.I)
STAGE_RX = re.compile(r"\bstage\b|\bstaging\b", re.I)
TEST2_RX = re.compile(r"\btest[\s-]*2\b", re.I)


def site():
    try:
        return json.load(open(SITE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def roots(s):
    p = s.get("projects", "")
    return s.get("reports") or os.path.join(p, "reports"), s.get("runtime") or os.path.join(p, ".ela")


# ── Jira ─────────────────────────────────────────────────────────────────────────────────────────────

def read_issues(creds, days, limit=SEARCH_LIMIT):
    """Every MH ticket created or updated in the window, changelog expanded, newest update first."""
    jql = f"project = MH AND (created >= -{days}d OR updated >= -{days}d) ORDER BY updated DESC"
    issues, token = [], None
    while len(issues) < limit:
        params = {"jql": jql, "maxResults": min(100, limit - len(issues)), "fields": FIELDS, "expand": "changelog"}
        if token:
            params["nextPageToken"] = token
        data = J.api_get(creds, "/rest/api/3/search/jql", params)
        issues += data.get("issues") or []
        token = data.get("nextPageToken")
        if not token or data.get("isLast"):
            break
    return issues


def parse_at(s):
    """A Jira timestamp (2026-11-02T09:41:12.345+0800) as an aware datetime, or None."""
    raw = str(s or "")
    try:
        dt = datetime.datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    z = raw[-5:]
    off = datetime.timedelta(hours=int(z[1:3]), minutes=int(z[3:5])) * (1 if z[0] == "+" else -1) if re.fullmatch(r"[+-]\d{4}", z) else datetime.timedelta()
    return dt.replace(tzinfo=datetime.timezone(off))


def mmdd(s):
    t = parse_at(s)
    return f"{t.astimezone():%m-%d}" if t else ""


# ── the map ──────────────────────────────────────────────────────────────────────────────────────────

def lines_cfg():
    """{line: its map entry} from map/release.yaml § lines."""
    return {str(k): v for k, v in (R.rmap("lines") or {}).items()}


def line_order(cfg):
    return [l for l in LINE_ORDER if l in cfg] + sorted(l for l in cfg if l not in LINE_ORDER)


def line_of(labels, cfg):
    """The line a ticket's `release:mh-<line>` label names; None without one; "2.0+2.1" with two, which no section owns."""
    by_label = {v.get("label"): k for k, v in cfg.items() if v.get("label")}
    found = sorted({by_label[l] for l in labels or [] if l in by_label})
    return found[0] if len(found) == 1 else (None if not found else "+".join(found))


def fixed_in_entries(value):
    """[(slug, version)] from the Fixed In field, aliases resolved to the map's slugs; an entry without a version is
    kept with None so the page can say it is declared."""
    aliases = ((R.rmap("fixed_in") or {}).get("slug_aliases") or {})
    out = []
    for e in J.fixed_in_entries(J.body_text(value) if value else ""):   # the field is rich text on some tickets
        slug, _, ver = e.partition("@")
        slug = aliases.get(slug.strip(), slug.strip())
        out.append((slug, ver.strip() or None))
    return out


# ── lanes ────────────────────────────────────────────────────────────────────────────────────────────

def lane_versions(rows):
    """{(service, lane): version} from a saved lane read; the release mails' rows are requests, not lanes."""
    out = {}
    for r in rows or []:
        if r.get("lane") and r.get("version") and r.get("host") != "mail":
            out[(r["service"], r["lane"])] = r["version"]
    return out


def carries(versions, lane, slug, ver):
    """True when the lane's version of the slug is at or past the Fixed In version, False when below, None when the
    lane has no row for the slug or either version does not parse."""
    have, want = R.parse_version(versions.get((slug, lane))), R.parse_version(ver)
    if have is None or want is None:
        return None
    c = P.cmp_versions(slug, have, want)
    return None if c is None else c >= 0


def stands_at(entries, versions, cfg):
    """Where a ticket's fix stands on its line's train: the furthest lane whose versions carry every judged Fixed In
    entry. {text, role, lane, judged: [(slug, version)], unjudged: [(slug, version)]}. `dev` without a Fixed In;
    `declared` when no entry can be read against a lane (a docker image, a bundle-tracked slug); a China lane aligned
    with the prod lane that has not caught up adds `· CN behind`."""
    lanes = (cfg or {}).get("lanes") or {}
    if not entries:
        return {"text": "dev", "role": None, "lane": None, "judged": [], "unjudged": []}
    judged, unjudged, best = [], [], None
    for role in ROLES:
        lane = lanes.get(role)
        if not lane:
            continue
        verdicts = [(slug, ver, carries(versions, lane, slug, ver)) for slug, ver in entries]
        known = [v for _, _, v in verdicts if v is not None]
        if known and all(known):
            best = (role, lane)
        if not judged:
            judged = [(s, v) for s, v, c in verdicts if c is not None]
            unjudged = [(s, v) for s, v, c in verdicts if c is None]
    if not judged:
        return {"text": "declared", "role": None, "lane": None, "judged": [], "unjudged": entries}
    if not best:
        return {"text": "built, no lane yet", "role": None, "lane": None, "judged": judged, "unjudged": unjudged}
    role, lane = best
    text = lane
    if role == "qa":
        pv = R.parse_version(versions.get((judged[0][0], lane)))
        if pv and pv[4]:
            text += f" (build {pv[4]})"
    if role == "prod":
        cn = next((l for (s, l) in versions if s == judged[0][0] and l.endswith("-china")), None)
        if cn and any(carries(versions, cn, s, v) is False for s, v in judged):
            text += " · CN behind"
    return {"text": text, "role": role, "lane": lane, "judged": judged, "unjudged": unjudged}


def lane_words(text):
    """The lanes a ticket names in its words, canonical: prod-3, prod-2-china, qa-cn3, daily-wed, daily-stage."""
    t = str(text or "")
    out = []
    for m in PROD_RX.finditer(t):
        lane = R.prod_lane(m.group(0))
        if lane:
            out.append(lane)
    out += [f"qa-cn{m.group(1)}" for m in QA_RX.finditer(t)]
    out += [f"daily-{m.group(1).lower()}" for m in DAILY_RX.finditer(t)]
    if STAGE_RX.search(t):
        out.append("daily-stage")
    if TEST2_RX.search(t):
        out.append("daily-test2")
    return list(dict.fromkeys(out))


# ── QA ───────────────────────────────────────────────────────────────────────────────────────────────

def read_testlists(reports):
    """{lane: rows} from every <reports>/lanes/test-list-<lane>.json the testlist verb keeps."""
    d = os.path.join(reports or "", "lanes")
    out = {}
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        m = re.fullmatch(r"test-list-(.+)\.json", f)
        if not m:
            continue
        try:
            data = json.load(open(os.path.join(d, f), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = data.get("rows") or {}
        out[data.get("lane") or m.group(1)] = list(rows.values()) if isinstance(rows, dict) else rows
    return out


VERDICTS = {"pass": "pass", "fail": "fail", "n-a": "n/a"}   # a list row's other words (untested, pending) are no verdict


def qa_said(key, testlists):
    """The latest verdict a lane test list records for the key: {verdict, version, date, lane} or None."""
    found = []
    for lane, rows in (testlists or {}).items():
        for r in rows:
            if (r.get("ticket") == key or key in (r.get("also") or [])) and r.get("verdict") in VERDICTS:
                found.append({"verdict": VERDICTS[r["verdict"]], "version": r.get("verdict_version") or "", "date": r.get("verdict_date") or "", "lane": lane})
    return max(found, key=lambda x: x["date"], default=None)


def handles():
    """{Jira display name: roster name} for the people the roster names differently, read the team skill's way; a
    page written for the owner names people the roster's way. Empty when the roster cannot be read."""
    try:
        sys.path.insert(0, os.path.join(SKILLS, "team"))
        import team  # noqa: E402
        roster = team.read_roster(team.records())[1]
    except (SystemExit, ImportError, OSError, ValueError):
        return {}
    return {p["jira_name"]: p["name"] for p in roster if p.get("jira_name") and p.get("name") and p["jira_name"].lower() != p["name"].lower()}


# ── the window ───────────────────────────────────────────────────────────────────────────────────────

def changes(issue, since):
    """The field moves inside the window, oldest first: [{at, field, from, to, by}], and whether the ticket was created
    in it."""
    f = issue.get("fields") or {}
    out = []
    for h in (issue.get("changelog") or {}).get("histories") or []:
        at = parse_at(h.get("created"))
        if not at or at < since:
            continue
        for it in h.get("items") or []:
            if it.get("field") in CHANGE_FIELDS:
                out.append({"at": h.get("created"), "field": it["field"], "from": it.get("fromString"), "to": it.get("toString"),
                            "by": J.name_of(h.get("author"))})
    out.sort(key=lambda e: e["at"])
    created = parse_at(f.get("created"))
    return out, bool(created and created >= since)


def last_change(events, created_in_window, fields):
    """What moved last, in a few words: `created 10-31`, `Review 11-01`, `Fixed In 11-02`, `assigned 11-02`,
    `High 11-02`, `label 11-02`; `updated` when the window holds only edits the changelog does not class."""
    latest = events[-1] if events else None
    if created_in_window and (not latest or (fields.get("created") or "") >= latest["at"]):
        return f"created {mmdd(fields.get('created'))}"
    if not latest:
        return f"updated {mmdd(fields.get('updated'))}"
    d = mmdd(latest["at"])
    return {"status": f"{latest['to']} {d}", "Fixed In": f"Fixed In {d}", "assignee": f"assigned {d}",
            "priority": f"{latest['to']} {d}", "labels": f"label {d}"}.get(latest["field"], f"{latest['field']} {d}")


def infer_label(entries, versions, cfg):
    """The `release:mh-<line>` label a ticket's Fixed In supports: the one line whose lanes run the entry's slug in the
    same series (M.m). {label, line, from} or {label: None, from: why}."""
    if not entries:
        return {"label": None, "line": None, "from": "no Fixed In"}
    cands = {}
    for slug, ver in entries:
        pv = R.parse_version(ver)
        if not pv:
            continue
        for line, c in cfg.items():
            for role, lane in ((c.get("lanes") or {}).items()):
                lv = R.parse_version(versions.get((slug, lane)))
                if lv and lv[:2] == pv[:2]:
                    cands.setdefault(line, f"{slug}@{ver} is in the {line} series on {lane}")
    if len(cands) == 1:
        line, why = next(iter(cands.items()))
        return {"label": cfg[line].get("label"), "line": line, "from": why}
    if cands:
        return {"label": None, "line": None, "from": "ambiguous: " + " or ".join(sorted(cands))}
    return {"label": None, "line": None, "from": "no lane runs the Fixed In series"}


# ── collect ──────────────────────────────────────────────────────────────────────────────────────────

def ticket_row(issue, cfg, versions, testlists, since, jira_base="", names=None):
    f = issue.get("fields") or {}
    key = issue.get("key")
    assignee = J.name_of(f.get("assignee"))
    line = line_of(f.get("labels"), cfg)
    entries = fixed_in_entries(f.get(J.FIXED_IN_FIELD))
    events, created = changes(issue, since)
    text = (f.get("summary") or "") + "\n" + (J.body_text(f.get("description")) or "")[:4000]
    return {"key": key, "summary": f.get("summary") or "", "type": J.name_of(f.get("issuetype"), "name"),
            "status": J.name_of(f.get("status"), "name"), "assignee": (names or {}).get(assignee, assignee),
            "priority": J.name_of(f.get("priority"), "name"), "due": f.get("duedate"), "labels": f.get("labels") or [],
            "line": line, "fixed_in": [f"{s}@{v}" if v else s for s, v in entries],
            "stands": stands_at(entries, versions, cfg.get(line) if line in cfg else None),
            "seen_on": lane_words(text), "qa": qa_said(key, testlists), "last": last_change(events, created, f), "events": events,
            "created_in_window": created, "created": f.get("created"), "updated": f.get("updated"),
            "url": f"{jira_base}/browse/{key}" if jira_base else None}


def train(cfg, rows, before, tested):
    """The line's train in one row per deliverable: for each lane the version with the lanes page's marks."""
    lanes = (cfg or {}).get("lanes") or {}
    out = []
    for role in ROLES:
        lane = lanes.get(role)
        if not lane:
            continue
        cells = {}
        for svc in TRAIN_SERVICES:
            try:
                cells[svc] = B.matrix_cell(svc, lane, rows or [], before, tested or {}, {})["text"]
            except (KeyError, TypeError, ValueError):
                cells[svc] = "—"
        out.append({"role": role, "lane": lane, "shown": B.LANE_SHOWN.get(lane, lane), "cells": cells})
    return out


def by_lane(cfg, tickets, versions, before_versions):
    """Per lane of the line: fixes that arrived in the window (carried now and not by the oldest lane read of the window;
    with no older row to judge by nothing is claimed: a Fixed In filled in late is not an arrival), fixes under test
    there (the fix stands on it, the ticket is open, QA said nothing yet), bugs reported from it (the ticket names it)."""
    out = []
    for role in ROLES:
        lane = ((cfg or {}).get("lanes") or {}).get(role)
        if not lane:
            continue
        arrived, under, reported = [], [], []
        for t in tickets:
            st = t["stands"]
            if st.get("role") and ROLE_RANK[st["role"]] >= ROLE_RANK[role]:
                known = [w for w in (carries(before_versions or {}, lane, s, v) for s, v in st["judged"]) if w is not None]
                if known and not all(known):
                    arrived.append(t["key"])
            if st.get("role") == role and not t.get("qa") and t.get("status") not in S.TERMINAL:
                under.append(t["key"])
            if lane in t["seen_on"]:
                reported.append(t["key"])
        out.append({"role": role, "lane": lane, "shown": B.LANE_SHOWN.get(lane, lane), "arrived": arrived, "under_test": under, "reported": reported})
    return out


def collect(issues, cfg, rows, before, tested, testlists, now, days, jira_base="", names=None):
    """The result: tickets placed by line (the map's order), each line with its train and by-lane lists, and the
    tickets with no line and the label ela would infer. Pure: every input is given, nothing is read here."""
    since = now - datetime.timedelta(days=days)
    versions, before_versions = lane_versions(rows), (lane_versions(before) if before is not None else None)
    tickets = [ticket_row(i, cfg, versions, testlists, since, jira_base, names) for i in issues]
    tickets.sort(key=lambda t: t.get("updated") or "", reverse=True)
    lines = []
    for line in line_order(cfg):
        mine = [t for t in tickets if t["line"] == line]
        if not mine and line not in LINE_ORDER:
            continue
        c = cfg[line]
        lines.append({"line": line, "label": c.get("label"), "lanes": c.get("lanes") or {}, "note": c.get("note"),
                      "train": train(c, rows, before, tested), "tickets": mine, "by_lane": by_lane(c, mine, versions, before_versions)})
    no_line = [dict(t, infer=infer_label([(e.partition("@")[0], e.partition("@")[2] or None) for e in t["fixed_in"]], versions, cfg))
               for t in tickets if t["line"] is None or t["line"] not in cfg]
    counts = {l["line"]: len(l["tickets"]) for l in lines}
    counts["no line"] = len(no_line)
    return {"at": now.isoformat(timespec="minutes"), "days": days, "since": since.date().isoformat(), "count": len(tickets),
            "counts": counts, "lines": lines, "no_line": no_line,
            "sources": {"lane_read": bool(rows), "lane_read_before": before is not None, "qa_tested": bool(tested), "test_lists": sorted(testlists or {})}}


# ── the page ─────────────────────────────────────────────────────────────────────────────────────────

def units(text):
    """The vault's reading units: words plus two CJK characters per unit, links' targets and code left out."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"\]\([^)]*\)", "]", text)
    text = re.sub(r"https?://\S+", "", text)
    return len(re.findall(r"[A-Za-z0-9][\w'’.-]*", text)) + len(re.findall(r"[一-鿿]", text)) // 2


def open_units(page):
    """Units outside folded callouts, as the vault's gate counts them."""
    out, inside = [], False
    for line in page.splitlines():
        if inside and line.startswith(">"):
            continue
        inside = bool(re.match(r"^>\s*\[![\w-]+\]-", line))
        if not inside:
            out.append(line)
    return units("\n".join(out))


def cell(s, n=48):
    s = re.sub(r"\s+", " ", str(s or "")).replace("|", "/").strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def who(t):
    return " · ".join(x for x in (t.get("type"), t.get("status"), t.get("assignee") or "unassigned") if x)


def p_due(t):
    due = (t.get("due") or "")[5:]
    return " · ".join(x for x in (t.get("priority"), due) if x) or "—"


def shown(lane):
    return B.LANE_SHOWN.get(lane, lane)


def qa_cell(t, line_qa_lane=None):
    q = t.get("qa")
    if not q:
        return "—"
    s = f"{q['verdict']} on {q['version'] or '?'}"
    return s if q.get("lane") in (None, line_qa_lane) else f"{s} ({shown(q['lane'])})"


def folded_rows(head, rows, rows_open):
    L = head + rows[:rows_open]
    if len(rows) > rows_open:
        L += ["", f"> [!note]- {len(rows) - rows_open} more"] + ["> " + l for l in head + rows[rows_open:]]
    return L


def ticket_table(tickets, qa_lane, rows_open):
    head = ["| ticket | type · status · assignee | P / due | seen on | fix stands at | QA said | last change |", "|---|---|---|---|---|---|---|"]
    rows = [f"| {t['key']} · {cell(t['summary'])} | {cell(who(t), 60)} | {p_due(t)} | {', '.join(shown(l) for l in t['seen_on']) or '—'} "
            f"| {t['stands']['text']} | {qa_cell(t, qa_lane)} | {t['last']} |" for t in tickets]
    return folded_rows(head, rows, rows_open)


def keys_line(keys):
    if not keys:
        return "none"
    return ", ".join(keys[:LIST_OPEN]) + (f" +{len(keys) - LIST_OPEN}" if len(keys) > LIST_OPEN else "")


def lane_name(x):
    return x["lane"] + (f" ({x['shown']})" if x["shown"] != x["lane"] else "")


def train_lines(tr):
    if not tr:
        return []
    L = ["| | " + " | ".join(lane_name(x) for x in tr) + " |", "|---|" + "---|" * len(tr)]
    for svc, name in (("mediahub-backend", "backend"), ("mediahub-frontend", "frontend")):
        L.append(f"| {name} | " + " | ".join(x["cells"].get(svc, "—") for x in tr) + " |")
    return L


def render_page(res, rows_open=ROWS_OPEN, budget=BUDGET):
    """The vault's recent page from a result: the refresh box, one section per line (train, table, folded By lane),
    then the tickets with no line and the label ela would infer; the tables fold after `rows_open` rows, lowered
    until the open words fit the budget."""
    at = res.get("at") or ""
    hm = at[11:16]
    summary = " · ".join(f"{k}: {v}" for k, v in (res.get("counts") or {}).items())
    L = [f"# {TITLE}", "",
         f"*{at[:10]} {hm} · {res.get('count', 0)} tickets created or updated since {(res.get('since') or '')[5:]} · {summary}*", "",
         f"- [ ] refresh recent (last {hm}; the runner refreshes it at its passes)", ""]
    for ln in res.get("lines") or []:
        L += [f"## {ln['line']}", ""]
        if ln.get("train"):
            L += train_lines(ln["train"]) + [""]
        elif ln.get("note"):
            L += [f"*{ln['note']}*", ""]
        L += (ticket_table(ln["tickets"], (ln.get("lanes") or {}).get("qa"), rows_open) if ln["tickets"] else ["*No ticket on this line in the window.*"]) + [""]
        if ln.get("by_lane"):
            L += ["> [!note]- By lane"] + [f"> **{lane_name(x)}** — arrived: {keys_line(x['arrived'])} · under test: {keys_line(x['under_test'])} · "
                                           f"reported from it: {keys_line(x['reported'])}" for x in ln["by_lane"]] + [""]
    no_line = res.get("no_line") or []
    L += ["## No line", ""]
    if no_line:
        head = ["| ticket | type · status · assignee | last change | ela would label | from |", "|---|---|---|---|---|"]
        rows = [f"| {t['key']} · {cell(t['summary'])} | {cell(who(t), 60)} | {t['last']} | {(t.get('infer') or {}).get('label') or '—'} "
                f"| {cell((t.get('infer') or {}).get('from'), 70)} |" for t in no_line]
        L += folded_rows(head, rows, rows_open)
        L += ["", "*No label is written from here: the rule is not closed, so each label is a drafted action for your word.*", ""]
    else:
        L += ["*Every ticket in the window carries a line label.*", ""]
    src = res.get("sources") or {}
    gaps = [] if src.get("lane_read") else ["no lane read saved: fix stands at is dev or declared for every ticket"]
    if not src.get("test_lists"):
        gaps.append("no test list on disk: QA said is — for every ticket")
    L += ["*▲ moved since the last read · ✓ QA passed this exact version (date) · ◐ partly · ○ no QA report names it · "
          "fix stands at: the furthest lane of the line whose versions carry every Fixed In entry · QA said: the lane test list's verdict · "
          "seen on: the lane the ticket names*"]
    if gaps:
        L += ["", "*Not read: " + "; ".join(gaps) + ".*"]
    page = "\n".join(L) + "\n"
    if rows_open > ROWS_MIN and open_units(page) > budget:
        return render_page(res, rows_open - 1, budget)
    return page


# ── main ─────────────────────────────────────────────────────────────────────────────────────────────

def newest_result(reports):
    """(path, result) of the newest <reports>/recent/<date>.json, or (None, None)."""
    d = os.path.join(reports or "", "recent")
    files = sorted(f for f in (os.listdir(d) if os.path.isdir(d) else []) if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", f))
    if not files:
        return None, None
    p = os.path.join(d, files[-1])
    try:
        return p, json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return p, None


def main():
    ap = argparse.ArgumentParser(description="the week's MH tickets placed by release line and by lane; the vault's recent page")
    ap.add_argument("--env-file", help="file with JIRA_BASE_URL/EMAIL/TOKEN")
    ap.add_argument("--days", type=int, default=7, help="the window (default 7)")
    ap.add_argument("--json", action="store_true", help="the result instead of the page")
    ap.add_argument("--write", action="store_true", help="keep the result as <reports>/recent/<date>.json for the vault's sync")
    ap.add_argument("--limit", type=int, default=SEARCH_LIMIT, help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.days < 1 or a.days > 60:
        print("--days: 1 to 60", file=sys.stderr); sys.exit(EX_USAGE)
    creds = J.load_env(a.env_file)
    reports, runtime = roots(site())
    now = datetime.datetime.now().astimezone()
    try:
        issues = read_issues(creds, a.days, a.limit)
    except SystemExit as e:                                  # jira.py exits with the HTTP failure in its message
        print(f"recent: {e}", file=sys.stderr); sys.exit(EX_REMOTE)
    runner = os.path.join(runtime, "runner")
    reads = B.lane_reads(runner)
    rows = reads[-1][2] if reads else []
    since = (now - datetime.timedelta(days=a.days)).date().isoformat()
    window = [r for r in reads if r[0] >= since]
    before = window[0][2] if len(window) > 1 else (reads[-2][2] if len(reads) > 1 else None)
    try:
        tested = json.load(open(os.path.join(runner, "qa-tested.json"), encoding="utf-8"))
    except (OSError, ValueError):
        tested = {}
    res = collect(issues, lines_cfg(), rows, before, tested, read_testlists(reports), now, a.days, creds.get("JIRA_BASE_URL", ""), handles())
    if a.write:
        d = os.path.join(reports, "recent")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{now:%Y-%m-%d}.json")
        tmp = path + ".tmp"
        json.dump(res, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(tmp, path)
        res["written"] = path
        if not a.json:
            print(f"recent: {res['count']} tickets → {path}")
    if a.json:
        print(json.dumps(res, ensure_ascii=False)); return
    if not a.write:
        print(render_page(res), end="")


if __name__ == "__main__":
    main()
