#!/usr/bin/env python3
"""Morning brief, Jira lanes — the facts the brief ranks, computed here instead of by a session. Stdlib only.

L1: deterministic, read-only, no LLM. Every Jira read goes through the jira capability as a subprocess
(`jira/jira.py jql … --json`), which owns auth and paging; this script only composes the JQL and does the
arithmetic on the timestamps. Judgment — clustering incidents, who spoke last, a backlog verdict, the rank
across lanes — stays in the SKILL.md.

Usage:
    brief.py [--env-file F] lanes [--lane cadence|triage|breakdown|incidents|backlog|yours|waiting|tracked] [--json] [--limit 300]
    brief.py sprint [--date YYYY-MM-DD] [--json]   the active sprint in <vault>/sprints/: items, keys, day N of M
    brief.py [--env-file F] changes [--hours 24] [--fetch] [--json]   the day's real changes for the Changes page; it
                                     snapshots lane versions to <runtime>/runner/versions-<date>.json and diffs the last one
    brief.py [--env-file F] matrix [--candidate F] [--promote-report F] [--json]   which version runs on which lane,
                                     from that snapshot, the QA versions kept by `changes`, and the standing pins

Lanes (project MH) and the flags computed per row, UTC now:
  cadence    In Progress, updated between 24h and 14d ago · hours_since_update: RED > 48h · YELLOW > 24h
             zombies (In Progress, updated > 14d ago): a count and the owners, never rows
             Blocked: always listed, with its age
  triage     created inside 2d, not Done, unassigned · hours_since_created: OVERDUE > 4h
             prefix_ok per row: summary starts with [Infra|J2N|Media|App|UI|QA|Design|AI]
             hygiene: every row created inside 2d and not Done whose summary lacks the prefix
  breakdown  Epic/Task/Improvement, Highest/High, not Review/Done/Cancelled, created inside 30d, with no
             sub-tasks and no children by parent link (one `parent in (…)` query) · age_days
  incidents  sub-tasks of the umbrella MH-2342, not Done · umbrella_moved when it returns nothing
  backlog    the current user's, not Done, updated > 30d ago · next_three oldest, the rest as a count
  yours      the cadence rows assigned to the current user, split out of cadence
  waiting    what the owner waits on, last 10 days: tickets he or ela assigned with no move by the assignee since, his
             last-word Jira comment, Slack thread or sent mail that asks something · working_days_silent, threshold
             (2 for a ticket he routed, 3 otherwise), due

Output: --json → {"generated", "lanes": {<lane>: {"rows", "count", …}}, "errors": [{lane, query, exit, stderr}]}.
A lane that could not be read is in `errors`, never an empty lane. No writes anywhere.

Exit codes: 0 ok · 2 usage · 5 a lane could not be read (the rest is still printed).
"""
import argparse
import datetime
import email.utils
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
JIRA = os.path.join(HERE, "..", "jira", "jira.py")
EX_USAGE, EX_REMOTE = 2, 5

PROJECT = "project = MH AND "
UMBRELLA = "MH-2342"
RED_H, YELLOW_H, OVERDUE_H = 48, 24, 4
PREFIX = re.compile(r"^\[(Infra|J2N|Media|App|UI|QA|Design|AI)\]")
LANES = ("intake", "cadence", "triage", "breakdown", "incidents", "backlog", "yours", "waiting", "tracked", "carried")

# JQL as SKILL.md §1 states it; `project = MH AND ` is prepended to each.
Q = {
    "cadence": 'status = "In Progress" AND updated <= -24h AND updated >= -14d ORDER BY updated ASC',
    "zombies": 'status = "In Progress" AND updated < -14d',
    "blocked": "status = Blocked ORDER BY updated ASC",
    "yours": ('assignee = currentUser() AND ((status = "In Progress" AND updated <= -24h AND updated >= -14d)'
              " OR status = Blocked)"),
    "intake": "created >= -1d ORDER BY created ASC",
    "triage": "created >= -2d AND statusCategory != Done AND assignee is EMPTY",
    "hygiene": "created >= -2d AND statusCategory != Done",
    "breakdown": ("issuetype in (Epic, Task, Improvement) AND priority in (Highest, High) "
                  "AND status not in (Review, Done, Cancelled) AND created >= -30d"),
    "incidents": f"parent = {UMBRELLA} AND statusCategory != Done ORDER BY updated ASC",
    "backlog": "assignee = currentUser() AND statusCategory != Done AND updated <= -30d ORDER BY updated ASC",
}


class LaneError(Exception):
    pass


def jql(env_file, query, limit, full=True):
    argv = ["python3", JIRA]
    if env_file:
        argv += ["--env-file", env_file]
    q = (PROJECT + query) if full else query
    argv += ["jql", q, "--json", "--limit", str(limit)]
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        raise LaneError({"query": q, "exit": None, "stderr": "timed out after 180s"})
    if p.returncode != 0:
        raise LaneError({"query": q, "exit": p.returncode, "stderr": (p.stderr or "").strip()[-500:]})
    try:
        return json.loads(p.stdout).get("issues") or []
    except ValueError:
        raise LaneError({"query": q, "exit": p.returncode, "stderr": "unparseable output: " + p.stdout[-300:]})


def parse_ts(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def hours_since(s, now):
    t = parse_ts(s)
    return None if t is None else round((now - t).total_seconds() / 3600, 1)


def cadence_flag(h):
    if h is None:
        return ""
    return "RED" if h > RED_H else "YELLOW" if h > YELLOW_H else ""


def lane_cadence(env, limit, now):
    rows = []
    for r in jql(env, Q["cadence"], limit):
        h = hours_since(r.get("updated"), now)
        rows.append({**r, "hours_since_update": h, "flag": cadence_flag(h)})
    blocked = []
    for r in jql(env, Q["blocked"], limit):
        blocked.append({**r, "hours_since_update": hours_since(r.get("updated"), now), "flag": "BLOCKED"})
    zombies = jql(env, Q["zombies"], limit)
    owners = {}
    for z in zombies:
        owners[z.get("assignee") or "—"] = owners.get(z.get("assignee") or "—", 0) + 1
    return {"rows": rows, "count": len(rows),
            "red": sum(1 for r in rows if r["flag"] == "RED"),
            "yellow": sum(1 for r in rows if r["flag"] == "YELLOW"),
            "blocked": blocked, "blocked_count": len(blocked),
            "zombies": {"count": len(zombies),
                        "owners": [{"assignee": k, "count": v}
                                   for k, v in sorted(owners.items(), key=lambda kv: -kv[1])]}}


WAIT_DAYS = 10
ROUTED_DAYS, OTHER_DAYS = 2, 3   # the 4-hour notify and 24-hour update promises, with room for another time zone
MACHINES = re.compile(r"Helm Lookout|Automation for Jira|\bela\b", re.I)   # their edits are not the other side answering
ASKS = re.compile(r"\?|\uff1f|\bplease\b|\bpls\b|\bcan you\b|\bcould you\b|\u8bf7|\u5417", re.I)


def to_date(ts):
    t = parse_ts(ts) if isinstance(ts, str) else ts
    return t.astimezone().date() if t else None


def waiting_row(kind, ref, who, since, what, now, routed=False):
    # the working days since the ask, the day of the ask not counted; no holiday table yet
    silent = working_days(to_date(since) + datetime.timedelta(days=1), now.astimezone().date()) if to_date(since) else None
    threshold = ROUTED_DAYS if routed else OTHER_DAYS
    return {"kind": kind, "ref": ref, "who": who, "since": since, "what": what[:200], "working_days_silent": silent,
            "threshold": threshold, "due": silent is not None and silent >= threshold}


def ticket_waits(issues, me, ela_assigned, commit_keys, now):
    """From `jira changes` rows: a ticket assigned by the owner (or ela) and left unmoved by its assignee since, and a
    ticket whose last human comment is the owner's ask."""
    rows = []
    for i in issues:
        assigned = [e for e in i["events"] if e["field"] == "assignee" and e.get("to") and e["to"] != me and
                    (e["by"] == me or i["key"] in ela_assigned) and not MACHINES.search(e.get("by") or "")]   # to himself is his own work
        if assigned:
            a = max(assigned, key=lambda e: e["at"])
            moved = [e for e in i["events"] if e["by"] == a["to"] and e["at"] > a["at"]] + \
                    [c for c in i["comments"] if c["by"] == a["to"] and c["at"] > a["at"]]
            if not moved and i["key"] not in commit_keys and i["assignee"] == a["to"] and i["status"] not in ("Done", "Closed", "Cancelled"):
                rows.append(waiting_row("ticket", i["key"], a["to"], a["at"], f"{i['summary']} ({i['status']})", now, routed=True))
                continue
        human = [c for c in i["comments"] if not MACHINES.search(c["by"] or "")]
        if human and human[-1]["by"] == me and ASKS.search(human[-1]["text"]):
            asked = ", ".join(re.findall(r"@([A-Z][\w.-]+(?: [A-Z][\w-]+)?)", human[-1]["text"])) or (i["assignee"] if i["assignee"] != me else None)
            if asked:                                       # an ask to nobody but himself waits on nobody
                rows.append(waiting_row("ticket", i["key"], asked, human[-1]["at"], f"{i['summary']}: {human[-1]['text']}", now))
    return rows


def lane_waiting(env, limit, now):
    """What the owner waits on (the F lane): his routed tickets, his unanswered asks in Jira, Slack and mail, and his
    parked notes in the vault."""
    e = ["--env-file", env] if env else []
    me = owner_jira_name(e)
    ch = run_json(["python3", JIRA, *e, "changes", f"--since=-{WAIT_DAYS}d", "--limit", str(max(limit, 300)), "--json"])
    site = json.load(open(SITE))
    reports = site.get("reports") or os.path.join(site.get("projects", ""), "reports")
    ela_assigned = set()
    try:
        for line in open(os.path.join(reports, "ela", "writes.jsonl"), encoding="utf-8"):
            w = json.loads(line)
            if w.get("verb") == "assign" and w.get("key") and w.get("ok"):
                ela_assigned.add(w["key"])
    except (OSError, ValueError):
        pass
    code_root = site.get("code") or os.path.join(site.get("projects", ""), "code")
    commits, _ = git_window(code_root, WAIT_DAYS * 24)
    commit_keys = {k for c in commits for k in c["keys"]}
    rows = ticket_waits(ch["issues"], me, ela_assigned, commit_keys, now)
    gaps = []
    try:
        for th in run_json(["python3", SLACK, *e, "unanswered", "--since", f"{WAIT_DAYS}d", "--json"], timeout=600)["threads"]:
            if ASKS.search(th["root"]):
                rows.append(waiting_row("slack", th["permalink"], " ".join(re.findall(r"@[\w.-]+(?: [A-Z][\w-]+)?", th["root"])) or None,
                                        th["at"], f"#{th['channel']}: {th['root']}", now))
    except (LaneError, subprocess.TimeoutExpired, ValueError) as x:
        gaps.append({"source": "slack", "error": str(x)[:200]})
    try:
        sent = run_json(["python3", MAIL, *e, "search", f"in:sent newer_than:{WAIT_DAYS}d", "--limit", "20", "--json"], timeout=300)["messages"]
        for m in {m["thread"]: m for m in reversed(sent)}.values():     # one row per thread
            msgs = read_thread(e, m["thread"], gaps)
            if msgs and msgs[-1]["id"] == m["id"] and ASKS.search(said_part(msgs[-1])):
                rows.append(waiting_row("mail", m["subject"], m["to"][:120], mail_time(m["date"]), m["subject"], now))
    except (LaneError, subprocess.TimeoutExpired, ValueError) as x:
        gaps.append({"source": "mail", "error": str(x)[:200]})
    rows += parked_waits(e, site.get("vault"), me, now, gaps)
    rows.sort(key=lambda r: -(r["working_days_silent"] or 0))
    return {"rows": rows, "count": len(rows), "due": sum(r["due"] for r in rows), "owner": me, "gaps": gaps}


PERMALINK_RX = re.compile(r"https://[\w.-]+\.slack\.com/archives/\S+?(?=[\s)>\]]|$)")


def parked_notes(vault):
    """The vault's parked/ notes, front matter only: a parked note waits on others, and its body is the owner's."""
    d = os.path.join(vault or "", "parked")
    out = []
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not f.endswith(".md"):
            continue
        try:
            text = open(os.path.join(d, f), encoding="utf-8").read()
        except OSError:
            continue
        m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
        props = {k: v.strip().strip("'\"") for k, v in re.findall(r"^([\w-]+):[ \t]*(.*)$", m.group(1) if m else "", re.M)}
        h1 = re.search(r"^#[ \t]+(.+)$", m.group(2) if m else text, re.M)
        out.append({"note": f"parked/{f}", "title": props.get("title") or (h1.group(1).strip() if h1 else f[:-3]),
                    "waits_on": props.get("waits-on") or None, "parked": props.get("parked"), "wake": props.get("wake") or ""})
    return out


def parked_since(value):
    """When the note was parked: a time as written, or a bare date read as that day's end, so nothing said on the
    day it was parked counts as waking it."""
    for fmt, end in (("%Y-%m-%d %H:%M", False), ("%Y-%m-%d", True)):
        try:
            t = datetime.datetime.strptime((value or "").strip(), fmt)
        except ValueError:
            continue
        return (t + datetime.timedelta(days=1) if end else t).astimezone()
    return None


def parked_row(n, jira_rows, threads, me, now):
    """One parked note in the F lane. It woke when its wake's ticket changed status or took a comment from someone
    other than the owner, or its thread took a reply from someone else, after it was parked; otherwise it counts
    silent working days from the later of the parking and the owner's own last word there."""
    since = parked_since(n["parked"])
    keys, links = keys_in(n["wake"]), PERMALINK_RX.findall(n["wake"])
    woke, last = [], since
    for r in (r for r in jira_rows if r["key"] in keys):
        for ev in r["events"]:
            at = parse_ts(ev["at"])
            if ev["field"] == "status" and at and since and at > since:
                woke.append({"source": "jira", "ref": r["key"], "at": ev["at"], "what": f"{ev.get('from')} → {ev.get('to')} by {ev['by']}"})
        for c in r["comments"]:
            at = parse_ts(c["at"])
            if not (at and since and at > since) or MACHINES.search(c["by"] or ""):
                continue
            if c["by"] == me:
                last = max(last, at)
            else:
                woke.append({"source": "jira", "ref": r["key"], "at": c["at"], "what": f"{c['by']}: {c['text'][:120]}"})
    for link in links:
        for m in (threads.get(link) or {}).get("messages", [])[1:]:
            at = datetime.datetime.fromtimestamp(float(m["ts"]), datetime.timezone.utc) if m.get("ts") else None
            if not (at and since and at > since) or MACHINES.search(m.get("user") or ""):
                continue
            if m.get("user") == me:
                last = max(last, at)
            else:
                woke.append({"source": "slack", "ref": link, "at": at.isoformat(timespec="seconds"), "what": f"{m['user']}: {m['text'][:120]}"})
    row = waiting_row("parked", n["note"], n["waits_on"], last, n["title"], now)
    row.update(since=last.isoformat(timespec="minutes") if last else None, note=n["note"], wake=n["wake"], woke=woke,
               checked=keys + links, due=row["due"] and not woke)
    return row


def parked_waits(e, vault, me, now, gaps):
    """The parked notes as F rows, each wake's ticket and thread read now; a wake that names neither is not checked
    and the row says so (`checked` empty)."""
    notes = parked_notes(vault)
    keys = sorted({k for n in notes for k in keys_in(n["wake"])})
    since = min((t for t in (parked_since(n["parked"]) for n in notes) if t), default=None)
    jira_rows, threads = [], {}
    for proj in sorted({k.split("-")[0] for k in keys}):
        try:
            got = run_json(["python3", JIRA, *e, "changes", "--project", proj, "--since", since.strftime("%Y-%m-%d %H:%M") if since else f"-{WAIT_DAYS}d",
                            "--limit", "400", "--json"])
            jira_rows += [r for r in got["issues"] if r["key"] in keys]
        except (LaneError, subprocess.TimeoutExpired, ValueError) as x:
            gaps.append({"source": f"parked: jira {proj}", "error": str(x)[:200]})
    for link in sorted({l for n in notes for l in PERMALINK_RX.findall(n["wake"])}):
        try:
            threads[link] = run_json(["python3", SLACK, *e, "read", link, "--json"], timeout=120)
        except (LaneError, subprocess.TimeoutExpired, ValueError) as x:
            gaps.append({"source": "parked: slack", "error": str(x)[:200]})
    return [parked_row(n, jira_rows, threads, me, now) for n in notes]


TICKET_LOG = "ticket-findings.jsonl"   # <runtime>/runner: every `ela ticket refresh` pass's findings, appended by the runner


def tracked_items(rows, since):
    """One item per tracked ticket from the refresh findings logged since `since`: class C when a change is addressed
    to the owner (its first line who said what), else D ("ela could not place: …"); sure rows stay off the page."""
    by_key = {}
    for f in rows:
        at = parse_ts(f.get("pass_at") or "") or parse_ts(f.get("at") or "")
        if not at or at < since or (f.get("sure") and not f.get("addressed_to_owner")):
            continue
        by_key.setdefault(f["key"], []).append(f)
    out = []
    for key, fs in by_key.items():
        to_me = [f for f in fs if f.get("addressed_to_owner")]
        unsure = [f["reading"].split(": ", 1)[-1] for f in fs if not f.get("sure")]
        first = (f"{to_me[-1].get('by') or '?'}: {to_me[-1]['change'].split(': ', 1)[-1]}" if to_me else
                 "ela could not place: " + "; ".join(dict.fromkeys(unsure)))
        out.append({"key": key, "class": "C" if to_me else "D", "first_line": first[:240], "rows": len(fs),
                    "prod_or_customer": any(f.get("prod_or_customer") for f in fs), "page": next((f.get("page") for f in fs if f.get("page")), None),
                    "moves": ["seen", "go-deep", "nudge"], "readings": [f["reading"] for f in fs]})
    return sorted(out, key=lambda i: (i["class"], i["key"]))


def lane_tracked(env, limit, now):
    """Changes on tracked tickets that need his word, from the runner's refresh log over the brief's window (24 hours, 72
    on a Monday). Read-only; the passes themselves are `ela ticket refresh --all`."""
    site = json.load(open(SITE))
    runtime = site.get("runtime") or os.path.join(site.get("projects", ""), ".ela")
    hours = 72 if now.astimezone().weekday() == 0 else 24
    rows = []
    try:
        for line in open(os.path.join(runtime, "runner", TICKET_LOG), encoding="utf-8"):
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    except OSError:
        pass
    items = tracked_items(rows, now - datetime.timedelta(hours=hours))
    return {"rows": items, "count": len(items), "hours": hours}


def needs_you(page):
    """The items under a brief page's Needs you: [(ticket keys of the heading and its facts line, heading words)].
    The facts line is the first non-empty line under the heading."""
    m = re.search(r"^## Needs you[ \t]*$(.*?)(?=^## |\Z)", page, re.M | re.S)
    out = []
    for h, facts in re.findall(r"^### (?:\d+\.\s*)?(.+)$\n(?:[ \t]*\n)*(.*)$", m.group(1) if m else "", re.M):
        if facts.startswith("#"):
            facts = ""
        out.append((frozenset(keys_in(h + "\n" + facts)), re.sub(r"\s+", " ", h.strip().lower())))
    return out


def carried(pages):
    """{first key or heading: mornings carried} over brief pages oldest first, counting back from the last page while
    the item stays under Needs you on each earlier page: 1 is a first morning. An item with ticket keys is the same
    item when an earlier one shares a key, whatever its heading says; heading words identify only items without one
    (a retitled item counted as new disagreed with the page's own count, 2026-10-28 brief)."""
    seen = [needs_you(p) for p in pages]
    if not seen:
        return {}
    out = {}
    for keys, head in seen[-1]:
        n = 1
        for earlier in reversed(seen[:-1]):
            if any((keys and keys & k) or (not keys and not k and h == head) for k, h in earlier):
                n += 1
            else:
                break
        out[min(keys) if keys else head] = n
    return out


def lane_carried(env, limit, now):
    """How many mornings each of the last brief page's items has been carried, read from the pages themselves: the
    third morning means the brief failed to make it tickable, and the evening rewrites or drops it."""
    site = json.load(open(SITE))
    runner = os.path.join(site.get("reports") or os.path.join(site.get("projects", ""), "reports"), "runner")
    files = sorted(f for f in (os.listdir(runner) if os.path.isdir(runner) else []) if re.fullmatch(r"\d{4}-\d{2}-\d{2}-brief\.md", f))[-10:]
    pages = []
    for f in files:
        try:
            pages.append(open(os.path.join(runner, f), encoding="utf-8").read())
        except OSError:
            pass
    sys.path.insert(0, os.path.join(HERE, "..", "review"))
    import review                                       # the evening reader's verdicts (brief SKILL §reader)
    reports = os.path.dirname(runner)
    repeated = review.repeated_verdicts(reports, files[-1][:10]) if files else {}
    rows = [{"item": k, "mornings": n, "third": n >= 3, "same_verdict": repeated.get(k)} for k, n in carried(pages).items()]
    return {"rows": rows, "count": len(rows), "third": sum(r["third"] for r in rows),
            "same_verdict": sum(bool(r["same_verdict"]) for r in rows), "page": files[-1] if files else None}


def owner_jira_name(env):
    """The owner's Jira display name, read from a ticket assigned to him; None when he has none."""
    try:
        me = run_json(["python3", JIRA, *env, "jql", "assignee = currentUser() ORDER BY updated DESC", "--limit", "1", "--json"])["issues"]
        return me[0].get("assignee") if me else None
    except (LaneError, subprocess.TimeoutExpired, ValueError):
        return None


def split_yours(env, limit, cadence):
    mine = {r["key"] for r in jql(env, Q["yours"], limit)}
    rows = [r for r in cadence["rows"] + cadence["blocked"] if r["key"] in mine]
    cadence["rows"] = [r for r in cadence["rows"] if r["key"] not in mine]
    cadence["blocked"] = [r for r in cadence["blocked"] if r["key"] not in mine]
    cadence["count"], cadence["blocked_count"] = len(cadence["rows"]), len(cadence["blocked"])
    cadence["red"] = sum(1 for r in cadence["rows"] if r["flag"] == "RED")
    cadence["yellow"] = sum(1 for r in cadence["rows"] if r["flag"] == "YELLOW")
    return {"rows": rows, "count": len(rows)}


def lane_intake(env, limit, now):
    """Every ticket created since yesterday, whatever its status: each gets one pass and one line on the page, even
    when nothing needs changing. The flags are the mechanical part of the pass; what the ticket is about is the
    session's reading. A new ticket the owner never saw is the failure this lane exists to prevent."""
    rows = []
    for r in jql(env, Q["intake"], limit):
        flags = []
        if not r.get("assignee"):
            flags.append("UNASSIGNED")
        if (r.get("type") or "") == "Sub-task" and not PREFIX.match(r.get("summary") or ""):
            flags.append("NOPREFIX")
        if (r.get("type") or "") == "Epic" and not r.get("subtasks") and not r.get("parent"):
            flags.append("EPIC-NO-CHILDREN")
        rows.append({**r, "hours_since_created": hours_since(r.get("created"), now), "flag": " ".join(flags)})
    return {"rows": rows, "count": len(rows), "flagged": sum(1 for r in rows if r["flag"])}


def lane_triage(env, limit, now):
    rows = []
    for r in jql(env, Q["triage"], limit):
        h = hours_since(r.get("created"), now)
        rows.append({**r, "hours_since_created": h, "flag": "OVERDUE" if h is not None and h > OVERDUE_H else "",
                     "prefix_ok": bool(PREFIX.match(r.get("summary") or ""))})
    missing = [r["key"] for r in jql(env, Q["hygiene"], limit) if not PREFIX.match(r.get("summary") or "")]
    return {"rows": rows, "count": len(rows),
            "overdue": sum(1 for r in rows if r["flag"] == "OVERDUE"),
            "hygiene": {"missing_prefix": missing, "count": len(missing)}}


def lane_breakdown(env, limit, now):
    candidates = [r for r in jql(env, Q["breakdown"], limit) if r.get("subtasks", 0) == 0]
    parents = set()
    if candidates:
        keys = ", ".join(r["key"] for r in candidates)
        parents = {c.get("parent") for c in jql(env, f"parent in ({keys})", max(limit, 1000), full=False)}
    rows = []
    for r in candidates:
        if r["key"] in parents:
            continue
        h = hours_since(r.get("created"), now)
        rows.append({**r, "age_days": None if h is None else round(h / 24, 1), "flag": ""})
    return {"rows": rows, "count": len(rows), "dropped_with_children": len(candidates) - len(rows)}


def lane_incidents(env, limit, now):
    rows = [{**r, "hours_since_update": hours_since(r.get("updated"), now), "flag": ""}
            for r in jql(env, Q["incidents"], limit)]
    out = {"rows": rows, "count": len(rows), "umbrella": UMBRELLA}
    if not rows:
        out["umbrella_moved"] = True
    return out


def lane_backlog(env, limit, now):
    rows = [{**r, "hours_since_update": hours_since(r.get("updated"), now), "flag": ""}
            for r in jql(env, Q["backlog"], limit)]
    rows.sort(key=lambda r: r.get("updated") or "")
    return {"rows": rows[:3], "next_three": [r["key"] for r in rows[:3]],
            "count": len(rows), "rest_count": max(0, len(rows) - 3)}


def age_of(r):
    if r.get("age_days") is not None:
        return f"{r['age_days']}d"
    h = r.get("hours_since_update", r.get("hours_since_created"))
    return "" if h is None else f"{h}h"


def print_table(name, lane):
    print(f"## {name} — {lane['count']}")
    if name == "carried":
        for r in lane["rows"]:
            print(f"  {r['mornings']} morning(s){'  THIRD' if r['third'] else ''}  {r['item'][:100]}")
        print(); return
    if name == "tracked":
        for r in lane["rows"]:
            print(f"  {r['key']:<10} {r['class']}  {r['first_line'][:110]}")
        print(); return
    if name == "waiting":
        for r in lane["rows"]:
            flag = "WOKE" if r.get("woke") else "DUE" if r["due"] else ""
            print(f"  {r['kind']:<6} {flag:<4} {r['working_days_silent']}/{r['threshold']}d  {str(r['who'] or '—')[:18]:<18} "
                  f"{r['ref'][:60]}  {r['what'][:60]}")
        for g in lane["gaps"]:
            print(f"  not read: {g['source']}: {g['error'][:100]}")
        print(); return
    for r in lane["rows"] + lane.get("blocked", []):
        flag = r.get("flag") or ""
        if name == "triage" and not r.get("prefix_ok"):
            flag = (flag + " NOPREFIX").strip()
        print(f"  {r['key']:<10} {flag:<16} {age_of(r):>8}  {(r.get('assignee') or '—')[:18]:<18} "
              f"{(r.get('summary') or '')[:60]}")
    if name == "cadence":
        z = lane["zombies"]
        print(f"  zombies {z['count']}: " + ", ".join(f"{o['assignee']} ×{o['count']}" for o in z["owners"]))
    if name == "intake":
        print(f"  every ticket above gets one pass today; {lane['flagged']} carry a flag, the rest are read and left as they are")
    if name == "triage":
        h = lane["hygiene"]
        print(f"  hygiene: {h['count']} without a layer prefix" + (f" ({', '.join(h['missing_prefix'])})" if h["count"] else ""))
    if name == "breakdown" and lane.get("dropped_with_children"):
        print(f"  ({lane['dropped_with_children']} dropped: children by parent link)")
    if name == "incidents" and lane.get("umbrella_moved"):
        print(f"  UMBRELLA MOVED: {UMBRELLA} returned no open sub-tasks — read it, do not report zero incidents")
    if name == "backlog":
        print(f"  next three: {', '.join(lane['next_three']) or '—'} · {lane['rest_count']} more")
    print()


def cmd_lanes(args):
    now = datetime.datetime.now(datetime.timezone.utc)
    want = [args.lane] if args.lane else list(LANES)
    fns = {"intake": lane_intake, "triage": lane_triage, "breakdown": lane_breakdown, "incidents": lane_incidents, "backlog": lane_backlog,
           "waiting": lane_waiting, "tracked": lane_tracked, "carried": lane_carried}
    lanes, errors = {}, []

    if "cadence" in want or "yours" in want:
        try:
            cadence = lane_cadence(args.env_file, args.limit, now)
            try:
                yours = split_yours(args.env_file, args.limit, cadence)
                if "yours" in want:
                    lanes["yours"] = yours
            except LaneError as exc:
                errors.append({"lane": "yours", **exc.args[0]})
            if "cadence" in want:
                lanes["cadence"] = cadence
        except LaneError as exc:
            for name in ("cadence", "yours"):
                if name in want:
                    errors.append({"lane": name, **exc.args[0]})
    for name in want:
        if name in fns:
            try:
                lanes[name] = fns[name](args.env_file, args.limit, now)
            except LaneError as exc:
                errors.append({"lane": name, **exc.args[0]})

    if args.json:
        print(json.dumps({"generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "day": day_plan(datetime.date.today()),
                          "lanes": lanes, "errors": errors}, ensure_ascii=False))
    else:
        print(f"# brief · jira lanes · {now.strftime('%Y-%m-%d %H:%M')}Z\n")
        for name in want:
            if name in lanes:
                print_table(name, lanes[name])
        for e in errors:
            print(f"## {e['lane']} — NOT READ (exit {e['exit']}): {e['stderr']}", file=sys.stderr)
    if errors:
        sys.exit(EX_REMOTE)


# ── yesterday: what changed, joined into cases by ticket key ──────────────────────────────────────────
# A case is one ticket key with whatever touched it in the window: its Jira moves and comments, the commits
# that name it (subject, body or branch), the Slack messages that name it. What names no ticket is listed
# apart: untracked commits (the owner's rule is that every change is tracked by a ticket) and Slack threads
# with a discussion but no key. ela's own work is the runner's jobs and the write log, plus Helm's
# auto-writes, which Jira shows under the owner's account. Read-only; the ranking prose is the SKILL's.
KEY_RX = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{1,6})\b")
NOT_KEYS = re.compile(r"^(UTF|ISO|SHA|MD|RFC|CVE|HTTP|TLS|SSL|H|X|AV|AAC|MP|PR|MR|ENV|AWS|CN|QA|UR|J2N)-")
SKIP_CHANNELS = ("alert", "helm-alerts")   # machine alarms: counted, never joined
BULK = 4   # a commit or message naming more keys is a list (release notes, agent docs): it joins existing cases only
SITE = os.path.expanduser("~/.claude/ela/site.json")
SLACK = os.path.join(HERE, "..", "slack", "slack.py")


def keys_in(text):
    return sorted({k for k in KEY_RX.findall(text or "") if not NOT_KEYS.match(k)})


def run_json(cmd, timeout=600):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise LaneError({"query": " ".join(cmd[2:5]), "exit": r.returncode, "stderr": (r.stderr or r.stdout).strip()[-300:]})
    return json.loads(r.stdout)


def checkouts(code_root):
    """Every checkout under the code root, at most five levels down, build and dependency trees skipped."""
    for top, dirs, _ in os.walk(code_root):
        if ".git" in dirs:
            dirs[:] = []
            yield top
            continue
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "vendor", "target", "build")]
        if top.count(os.sep) - code_root.count(os.sep) >= 5:
            dirs[:] = []


def fetch_all(code_root, workers=8, timeout=180):
    """Fetch every checkout, so the window sees what was pushed rather than what was last pulled by hand. Remote refs
    only; no working tree changes. Returns the repos that failed or timed out."""
    from concurrent.futures import ThreadPoolExecutor

    def one(top):
        try:
            r = subprocess.run(["git", "-C", top, "fetch", "--all", "--quiet", "--prune"], capture_output=True, text=True,
                               timeout=timeout, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
            return None if r.returncode == 0 else os.path.relpath(top, code_root)
        except subprocess.TimeoutExpired:
            return os.path.relpath(top, code_root)
    with ThreadPoolExecutor(workers) as ex:
        return [f for f in ex.map(one, list(checkouts(code_root))) if f]


def git_window(code_root, hours):
    """Commits of every checkout under the code root in the window, all refs, merges left out, one row per sha."""
    seen, rows, stale = set(), [], []
    for top in checkouts(code_root):
        repo = os.path.relpath(top, code_root)
        fh = os.path.join(top, ".git", "FETCH_HEAD")
        if os.path.exists(fh) and os.path.getmtime(fh) < datetime.datetime.now().timestamp() - 86400:
            stale.append(repo)
        r = subprocess.run(["git", "-C", top, "log", "--all", "--no-merges", f"--since={hours} hours ago", "--source",
                            "--format=%H%x1f%an%x1f%aI%x1f%S%x1f%s%x1f%b%x1e"], capture_output=True, text=True, timeout=60)
        for rec in r.stdout.split("\x1e"):
            p = rec.strip("\n").split("\x1f")
            if len(p) < 6 or p[0] in seen:
                continue
            seen.add(p[0])
            ref = p[3].replace("refs/remotes/origin/", "").replace("refs/heads/", "")
            rows.append({"repo": repo, "sha": p[0][:10], "author": p[1], "at": p[2], "ref": ref, "subject": p[4],
                         "keys": keys_in(p[4] + "\n" + p[5] + "\n" + ref)})
    return rows, stale


def yesterday_facts(args):
    """The window's facts joined into cases by ticket key; `errors` names every source not read."""
    site = json.load(open(SITE))
    hours = args.hours
    now = datetime.datetime.now(datetime.timezone.utc)
    env = ["--env-file", args.env_file] if args.env_file else []
    errors, cases = [], {}

    def case(k):
        return cases.setdefault(k, {"key": k, "summary": None, "status": None, "assignee": None, "jira": [], "comments": [],
                                    "created": False, "commits": [], "slack": []})
    # Jira
    machine = []
    try:
        ch = run_json(["python3", JIRA, *env, "changes", f"--since=-{hours}h", "--json"])
        for i in ch["issues"]:
            c = case(i["key"]); c.update(summary=i["summary"], status=i["status"], assignee=i["assignee"], created=i["created_in_window"])
            c["jira"] = i["events"]
            for cm in i["comments"]:
                (machine if "Helm Lookout" in cm["text"] else c["comments"]).append(dict(cm, key=i["key"]))
    except (LaneError, subprocess.TimeoutExpired, ValueError) as e:
        errors.append({"source": "jira", "error": str(e)[:300]})
    # git
    code_root = site.get("code") or os.path.join(site.get("projects", ""), "code")
    if args.fetch:
        for repo in fetch_all(code_root):
            errors.append({"source": "git", "error": f"fetch failed: {repo}"})
    commits, stale = git_window(code_root, hours)
    untracked, bulk = [], []
    for cm in commits:
        if len(cm["keys"]) > BULK:
            bulk.append(("commits", cm))
        elif cm["keys"]:
            for k in cm["keys"]:
                case(k)["commits"].append(cm)
        else:
            untracked.append(cm)
    # Slack
    threads = []
    try:
        chans = [c for c in run_json(["python3", SLACK, *env, "channels", "--json"])["channels"] if c["member"]]
        for c in chans:
            if (c["name"] or "").startswith(SKIP_CHANNELS):
                continue
            try:
                h = run_json(["python3", SLACK, *env, "history", c["id"], "--since", f"{hours}h", "--threads", "--json"], timeout=300)
            except (LaneError, subprocess.TimeoutExpired, ValueError) as e:
                errors.append({"source": f"slack #{c['name']}", "error": str(e)[:200]}); continue
            for m in h["messages"]:
                text = m["text"] + "\n" + "\n".join(r["text"] for r in m.get("replies") or [])
                row = {"channel": c["name"], "permalink": m["permalink"], "by": m["user"], "is_bot": m["is_bot"],
                       "text": re.sub(r"\s+", " ", m["text"])[:200], "replies": m.get("reply_count", 0)}
                ks = keys_in(text)
                if len(ks) > BULK:
                    bulk.append(("slack", dict(row, keys=ks)))
                else:
                    for k in ks:
                        case(k)["slack"].append(row)
                if not ks and not m["is_bot"] and m.get("reply_count", 0) >= 2:
                    threads.append(row)
    except (LaneError, subprocess.TimeoutExpired, ValueError) as e:
        errors.append({"source": "slack", "error": str(e)[:300]})
    for where, x in bulk:                                   # lists only reinforce cases another source opened
        for k in (x.get("keys") or []):
            if k in cases:
                cases[k][where].append(x)
    # keys seen only in commits or Slack: their summary and status. Jira refuses a whole `key in (…)` naming one
    # key it does not know, so a failed batch is retried key by key; a key no Jira knows stays bare.
    missing = [k for k, c in cases.items() if c["summary"] is None]

    def fill(keys):
        try:
            got = run_json(["python3", JIRA, *env, "jql", f"key in ({','.join(keys)})", "--limit", "100", "--json"])
        except (LaneError, subprocess.TimeoutExpired, ValueError):
            if len(keys) > 1:
                for k in keys:
                    fill([k])
            return
        for r in got["issues"]:
            if r["key"] in cases:
                cases[r["key"]].update(summary=r["summary"], status=r["status"], assignee=r["assignee"])
    for i in range(0, len(missing), 80):
        fill(missing[i:i + 80])
    # ela's own work
    reports = site.get("reports") or os.path.join(site.get("projects", ""), "reports")
    cutoff = now - datetime.timedelta(hours=hours)
    jobs, writes = [], []
    jd = os.path.join(reports, "runner", "jobs")
    for fn in sorted(os.listdir(jd)) if os.path.isdir(jd) else []:
        try:
            j = json.load(open(os.path.join(jd, fn)))
            t = datetime.datetime.fromisoformat(j.get("created") or j.get("started") or "1970-01-01T00:00:00+00:00")
            if t.astimezone(datetime.timezone.utc) >= cutoff:
                jobs.append({"id": j.get("id"), "prompt": j.get("prompt"), "status": j.get("status"), "summary": (j.get("summary") or "")[:160]})
        except (OSError, ValueError, TypeError):
            pass
    wl = os.path.join(reports, "ela", "writes.jsonl")
    if os.path.exists(wl):
        for line in open(wl, encoding="utf-8"):
            try:
                w = json.loads(line)
                if datetime.datetime.fromisoformat(w["at"]).astimezone(datetime.timezone.utc) >= cutoff:
                    writes.append(w)
            except (ValueError, KeyError):
                pass
    for c in cases.values():
        c["sources"] = sum(bool(x) for x in (c["jira"] or c["comments"] or c["created"], c["commits"], c["slack"]))
    ranked = sorted(cases.values(), key=lambda c: (-c["sources"], -(len(c["jira"]) + len(c["comments"]) + len(c["commits"]) + len(c["slack"]))))
    out = {"generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "hours": hours,
           "totals": {"cases": len(ranked), "jira_tickets": sum(1 for c in ranked if c["jira"] or c["comments"] or c["created"]),
                      "commits": len(commits), "untracked_commits": len(untracked), "slack_messages_with_key": sum(len(c["slack"]) for c in ranked),
                      "unticketed_threads": len(threads), "ela_jobs": len(jobs), "ela_writes": len(writes), "helm_autowrites": len(machine)},
           "cases": ranked, "untracked_commits": untracked, "unticketed_threads": sorted(threads, key=lambda t: -t["replies"]),
           "ela": {"jobs": jobs, "writes": writes, "helm_autowrites": machine}, "stale_checkouts": stale, "errors": errors,
           "bulk_commits": [x for where, x in bulk if where == "commits"]}
    return out


def cmd_yesterday(args):
    out = yesterday_facts(args)
    hours, ranked, errors = out["hours"], out["cases"], out["errors"]
    untracked, threads = out["untracked_commits"], out["unticketed_threads"]
    jobs, writes, machine = out["ela"]["jobs"], out["ela"]["writes"], out["ela"]["helm_autowrites"]
    if args.json:                       # a source not read is named in `errors`; the rest is still the answer
        print(json.dumps(out, ensure_ascii=False)); return
    t = out["totals"]
    print(f"# yesterday · last {hours}h · {t['cases']} cases · {t['commits']} commits ({t['untracked_commits']} without a ticket) · "
          f"{t['unticketed_threads']} threads without a ticket · ela {t['ela_jobs']} jobs, {t['ela_writes']} writes\n")
    for c in ranked[: args.top]:
        moves = "; ".join(f"{e['field']} {e['from'] or '—'}→{e['to'] or '—'}" for e in c["jira"][:3])
        repos = sorted({x["repo"].split("/")[-1] for x in c["commits"]})
        print(f"{c['key']:<10} [{c['status'] or '?':<11}] {(c['summary'] or '')[:60]}")
        print(f"           jira: {moves or ('created' if c['created'] else ('%d comment(s)' % len(c['comments']) if c['comments'] else '—'))}"
              f" · commits: {len(c['commits'])}{' (' + ', '.join(repos) + ')' if repos else ''} · slack: {len(c['slack'])}")
    if untracked:
        print(f"\n## commits without a ticket ({len(untracked)})")
        for cm in untracked[: args.top]:
            print(f"  {cm['repo']:<44} {cm['author']:<16} {cm['ref'][:24]:<24} {cm['subject'][:60]}")
    if threads:
        print(f"\n## threads without a ticket ({len(threads)})")
        for th in out["unticketed_threads"][: args.top]:
            print(f"  #{th['channel']:<28} {th['by']:<14} replies={th['replies']}  {th['text'][:70]}  {th['permalink']}")
    print(f"\n## ela: {len(jobs)} jobs, {len(writes)} writes, {len(machine)} Helm auto-writes")
    for e in errors:
        print(f"not read: {e['source']}: {e['error']}", file=sys.stderr)
    if errors:
        sys.exit(EX_REMOTE)


# ── changes: the day's real changes, for the Changes page ──────────────────────────────────────────

RELEASE = os.path.join(HERE, "..", "release", "release.py")
MAIL = os.path.join(HERE, "..", "mail", "mail.py")
PROMOTE = os.path.join(HERE, "..", "promote", "promote.py")
TEAM = os.path.join(HERE, "..", "team", "team.py")
sys.path.insert(0, os.path.join(HERE, "..", "release"))
import release as R  # noqa: E402  — the release map and the version grammar; reads still go through the CLI

QA_RELEASE, DEV_CHANNEL, REPORT_CHANNEL = "mediahub-qa-release", "prj_dev_mediahub", "helm-alerts"
TEAM_REPORTS = re.compile(r"Daily Report|MH Weekly Report", re.I)
# the owner's scope for the page: the MediaHub app and Orchestration, by service slug; their repos and Jenkins jobs come from
# map/release.yaml. Media, J2N and the other checkouts are other pages' business.
SCOPE = ("mediahub-backend", "mediahub-frontend", "unified-streaming", "unified-media-frontend", "orchestration")
IN_SCOPE_MAIL = re.compile(r"media\s*hub|\bMH\b|UR Caller|Unified Media|Orchestration", re.I)
LABEL = {"unified-streaming": "UR Caller (unified-streaming)"}            # the release mails say UR Caller
MOVE_RX = re.compile(r"^\s*-\s*(?P<name>[^:\n]+?)\s*(?:\((?P<branch>[^)]*)\))?\s*:\s*v?(?P<from>[\w.+-]+)\s*=>\s*v?(?P<to>[\w.+-]+)"
                     r"(?:\s*\(deployed to\s*(?P<env>[^)]+)\))?", re.M)
TAG_RX = re.compile(r"From:\s*(?P<from>\S+)\s*To:\s*(?P<to>\S+)", re.S)


def window_of(hours, now):
    end = now
    return {"start": (end - datetime.timedelta(hours=hours)).isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds"), "hours": hours}


def in_window(when, win):
    """A local 'YYYY-MM-DD HH:MM[:SS]' or ISO time inside the window."""
    try:
        t = datetime.datetime.fromisoformat(str(when).strip()[:19])
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.astimezone()
    return datetime.datetime.fromisoformat(win["start"]) <= t <= datetime.datetime.fromisoformat(win["end"])


def vkey(raw):
    """(version, build) of any version string the lanes, the builds and the mails write."""
    v = R.parse_version(raw)
    return (v[:4], v[4]) if v else None


def short_version(raw):
    v = R.parse_version(raw)
    return (R.vlabel(v[:4] + (0,)) + (f" build {v[4]}" if v[4] else "")) if v else str(raw or "")


def built_at(raw):
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*(\d{2}:\d{2}(?::\d{2})?)?", str(raw or ""))
    return f"{m.group(1)} {m.group(2) or '00:00'}" if m else None


def lane_moves(prev, rows, win):
    """Each (lane, service) whose version differs from the last snapshot; with no snapshot, those whose build is dated
    inside the window, `from` unknown."""
    old = {(r["host"], r.get("lane") or r.get("tag"), r["service"]): r["version"] for r in prev or []}
    out = []
    for r in rows:
        k = (r["host"], r.get("lane") or r.get("tag"), r["service"])
        was = old.get(k)
        if (prev is not None and k in old and vkey(was) != vkey(r["version"])) or (prev is None and in_window(built_at(r["version"]) or "", win)):
            v = R.parse_version(r["version"])
            out.append({"host": r["host"], "lane": k[1], "service": r["service"], "label": LABEL.get(r["service"], r["service"]),
                        "from": short_version(was) if was else None, "to": short_version(r["version"]),
                        "build": v[4] if v else None, "built": built_at(r["version"]), "patch": bool(v and v[3])})
    return out


def parse_release_mail(m):
    """A release mail's service moves (`Name (branch) : vA => vB (deployed to ENV)`) or a default-tag update."""
    moves = [{"service": x.group("name").strip(), "branch": (x.group("branch") or "").strip(), "from": x.group("from"),
              "to": x.group("to"), "env": " ".join((x.group("env") or "").split())} for x in MOVE_RX.finditer(m.get("body") or "")]
    tag = TAG_RX.search(m.get("body") or "")
    if not moves and tag:
        name = re.sub(r"^\s*\[Release\]\s*<?|>?\s*$", "", m["subject"])
        moves = [{"service": name, "branch": "", "from": tag.group("from"), "to": tag.group("to"), "env": "default tag"}]
    env = re.match(r"^\s*(?:Re:\s*)*\[Release\s*([^\]]*)\]", m["subject"], re.I)
    return {"subject": m["subject"], "from": m["from"], "date": m["date"], "id": m["id"], "thread": m["thread"],
            "env": (env.group(1).strip() if env else ""), "moves": moves, "text": None, "link": None}


def parse_qa_mail(m):
    """A QA test report: env, the build it tested, pass / fail / closed / new, and the cases that failed."""
    body = m.get("body") or ""
    head = re.split(r"Test Environment|Test Version|Test Condition", body, maxsplit=1)[0][:800]   # the summary, not a case table
    def num(rx):
        x = re.search(rx, head, re.I)
        return int(x.group(1)) if x else None
    env = re.search(r"\(ENV:\s*([^)]+)\)", body) or re.search(r"(?:for|on)\s+(?:TVU MediaHub\s+)?(?:on\s+)?([\w-]*(?:cn|aws|qa)[\w-]*)", m["subject"], re.I)
    build = re.search(r"build\s+(v[\d.]+\s*build\s*\d+)", body, re.I)
    failing = sorted({f"{x.group(1)}: {' '.join(x.group(2).split())[:140]}" for x in
                      re.finditer(r"\*?([A-Z][A-Z0-9]{1,9}-\d+)\*?\s+FAIL\b[:\s]*([^\n]*)", body)})
    # the other shape: numbered "new issue / reopened issue / close issue" lists of keys under Test Result
    listed = {}
    for x in re.finditer(r"\d\.\s*(new|reopened|close)d?\s+issues?:?\*?(.*?)(?=\*?\s*\d\.\s*(?:new|reopened|close)d?\s+issue|\n-{3,}|\Z)", body, re.I | re.S):
        listed[x.group(1).lower()] = keys_in(re.sub(r"<https?://[^>]*>", "", x.group(2)))
    def count(rx, key):
        n = num(rx)
        return n if n is not None or key not in listed else len(listed[key])
    return {"subject": m["subject"], "from": m["from"], "date": m["date"], "id": m["id"],
            "env": env.group(1).strip() if env else None, "build": " ".join(build.group(1).split()) if build else None,
            "pass": num(r"\*?(\d+)\s*Pass\b"), "fail": num(r"\*?(\d+)\s*Fail\b"), "closed": count(r"Closed\s*\*?(\d+)", "close"),
            "new": count(r"New\s*\*?(\d+)", "new"), "reopened": len(listed["reopened"]) if "reopened" in listed else None,
            "new_keys": listed.get("new", []), "reopened_keys": listed.get("reopened", []), "closed_keys": listed.get("close", []), "failing": failing, "mediahub": bool(re.search(r"media\s*hub", m["subject"] + head, re.I)),
            "results": [" ".join(l.split())[:160] for l in body.splitlines() if re.search(r"\b(PASS|FAIL|Pass|Fail)\b", l)][:10],
            "tested": tested_versions(body), "at": mail_time(m["date"]),
            "verdict": "partial" if failing or num(r"\*?(\d+)\s*Fail\b") or listed.get("reopened") else "pass"}


# a QA report's product header (`TVU MediaHub (ENV: aws-cn3-env)`) → its (frontend, backend) services
QA_PRODUCTS = {"TVU MediaHub": ("mediahub-frontend", "mediahub-backend"),
               "Unified Media Service": ("unified-media-frontend", "unified-media-backend"),
               "Unified Resources Caller": (None, "unified-streaming")}


def tested_versions(body):
    """The versions a QA report's environment block says it ran on: [{lane, service, version}]."""
    rows, cur = [], None
    for line in body.splitlines():
        h = re.match(r"^\s*(.+?)\s*\(ENV:\s*([^)]+)\)", line)
        v = re.match(r"^\s*(Frontend|Backend):\s*(v\S.*)$", line)
        if h:
            prod = next((s for k, s in QA_PRODUCTS.items() if h.group(1).strip().startswith(k)), None)
            cur = (prod, R.lane_of("qa", h.group(2).strip())) if prod else None
        elif v and cur and cur[1]:
            svc = cur[0][0 if v.group(1) == "Frontend" else 1]
            if svc:
                rows.append({"lane": cur[1], "service": svc, "version": " ".join(v.group(2).split())})
        elif line.strip() and not v:
            cur = None                                      # another product's block (Billing, Home) begins
    return rows


def mail_time(date):
    try:
        return email.utils.parsedate_to_datetime(date).astimezone().isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return None


# the release bot writes its build-result and release-done messages in Chinese; the markers, escaped
BUILD_RESULT, RELEASE_DONE, DEPLOYED = "\u6784\u5efa\u7ed3\u679c", "\u53d1\u7248\u5b8c\u6210", "\u90e8\u7f72"
DONE_RX = re.compile(r"^\s*[•*-]\s*(?P<job>[\w.-]+)\s+v(?P<to>[\d.]+)\s*\(#(?P<number>\d+)\)\s*(?:←\s*(?P<by>.+))?$")
BUILT_RX = re.compile(r"(?P<job>[\w.-]+)\s+v(?P<to>[\d.]+)\s*·.*?/job/[\w.-]+/(?P<number>\d+)/")


def parse_release_thread(texts):
    """The release thread's bot messages → one row per service: job, version, build number, the tickets and lines it
    carries. The release-done message lists what each build carries; the build-result one names where they went."""
    rows, deployed = {}, ""
    jobs = R.rmap("jobs")
    for text in texts:
        d = re.search(DEPLOYED + r"\s*([\w-]+)", text)
        deployed = d.group(1) if d else deployed
        cur = None
        for line in text.splitlines():
            m = DONE_RX.match(line) or BUILT_RX.search(line)
            if m:
                cur = rows.setdefault(m.group("job"), {"service": jobs.get(m.group("job"), m.group("job")), "job": m.group("job"),
                                                       "branch": "", "from": None, "to": m.group("to"), "number": int(m.group("number")),
                                                       "env": deployed, "items": []})
                continue
            item = re.match(r"^\s+-\s+(.+)$", line)
            if cur is not None and item:
                cur["items"].append({"text": item.group(1).strip(), "keys": keys_in(item.group(1))})
    for r in rows.values():
        r["env"] = r["env"] or deployed
    return [r for r in rows.values() if r["service"] in SCOPE]


def slack_rows(env, channel, since, errors, threads=True):
    try:
        cmd = ["python3", SLACK, *env, "history", channel, "--since", since, "--json"] + (["--threads"] if threads else [])
        return run_json(cmd, timeout=300)["messages"]
    except (LaneError, subprocess.TimeoutExpired, ValueError) as e:
        errors.append({"source": f"slack #{channel}", "error": str(e)[:200]}); return []


def ancestor(repo_dir, commit, tip):
    return subprocess.run(["git", "-C", repo_dir, "merge-base", "--is-ancestor", commit, tip], capture_output=True).returncode == 0


def changes_facts(args):
    site = json.load(open(SITE))
    now = datetime.datetime.now().astimezone()
    date = args.date or now.date().isoformat()
    win = window_of(args.hours, now)
    env = ["--env-file", args.env_file] if args.env_file else []
    errors = []
    y = yesterday_facts(argparse.Namespace(hours=args.hours, env_file=args.env_file, fetch=args.fetch))
    errors += y["errors"]
    # code: per repo, per ticket, from yesterday's case join; then what rode along without a ticket
    scoped = {R.rmap("repos")[s] for s in SCOPE if R.rmap("repos").get(s)}
    repos = {}
    for c in y["cases"]:
        threads = sorted({s["permalink"] for s in c["slack"] if s.get("permalink")})
        for cm in (x for x in c["commits"] if x["repo"] in scoped):
            r = repos.setdefault(cm["repo"], {"repo": cm["repo"], "tickets": {}, "untracked": []})
            t = r["tickets"].setdefault(c["key"], {"key": c["key"], "summary": c["summary"], "status": c["status"],
                                                   "assignee": c["assignee"], "commits": [], "threads": threads})
            t["commits"].append({k: cm[k] for k in ("sha", "subject", "author", "ref", "at")})
    for cm in (x for x in y["untracked_commits"] + y.get("bulk_commits", []) if x["repo"] in scoped):
        repos.setdefault(cm["repo"], {"repo": cm["repo"], "tickets": {}, "untracked": []})["untracked"].append(
            dict({k: cm[k] for k in ("sha", "subject", "author", "ref", "at")}, keys=cm.get("keys") or []))
    code = sorted(({**r, "tickets": list(r["tickets"].values())} for r in repos.values()),
                  key=lambda r: -(sum(len(t["commits"]) for t in r["tickets"]) + len(r["untracked"])))
    tickets = [{"key": c["key"], "summary": c["summary"], "status": c["status"], "assignee": c["assignee"], "created": c["created"],
                "moves": [f"{e['field']} {e['from'] or '—'} → {e['to'] or '—'}" + (f" ({e['by']})" if e.get("by") else "") for e in c["jira"]],
                "comments": len(c["comments"]), "commits": len(c["commits"]), "threads": len(c["slack"])}
               for c in y["cases"] if c["jira"] or c["comments"] or c["created"]]
    # lane versions: today's snapshot against the last one before it
    runner = os.path.join(site.get("runtime") or os.path.join(site.get("projects", ""), ".ela"), "runner")
    os.makedirs(runner, exist_ok=True)
    snaps = sorted(f for f in os.listdir(runner) if re.fullmatch(r"versions-\d{4}-\d{2}-\d{2}\.json", f) and f[9:19] < date)
    try:
        prev = json.load(open(os.path.join(runner, snaps[-1]))) if snaps else None
    except (OSError, ValueError):
        prev = None
    rows, read = [], {}
    for host in ("qa", "prod"):
        try:
            rows += [dict(r, host=host) for r in run_json(["python3", RELEASE, *env, "envs", "--host", host, "--json"], timeout=120)["rows"]]
            read[host] = True
        except (LaneError, subprocess.TimeoutExpired, ValueError) as e:
            errors.append({"source": f"versions {host}", "error": str(e)[:200]})
            rows += [r for r in (prev or {}).get("rows", []) if r["host"] == host]   # carried, so the next diff has a base
    versions = [m for m in lane_moves(prev["rows"] if prev else None, rows, win) if read.get(m["host"]) and m["service"] in SCOPE]
    if prev is None:
        errors.append({"source": "versions", "error": "no earlier snapshot: moves are the builds dated inside the window, `from` unknown"})
    # Jenkins builds in the window, each with the lanes running it and the window's commits it carries
    by_build = {}
    for r in rows:
        if vkey(r["version"]):
            by_build.setdefault((r["service"], vkey(r["version"])), []).append(r.get("lane") or r.get("tag"))
    code_root = site.get("code") or os.path.join(site.get("projects", ""), "code")
    window_commits = [cm for r in code for t in r["tickets"] for cm in t["commits"]] + [cm for r in code for cm in r["untracked"]]
    builds = []
    for job, service in ((j, s) for j, s in R.rmap("jobs").items() if s in SCOPE):
        try:
            got = run_json(["python3", RELEASE, *env, "builds", job, "--limit", "20", "--json"], timeout=60)["builds"]
        except (LaneError, subprocess.TimeoutExpired, ValueError) as e:
            errors.append({"source": f"jenkins {job}", "error": str(e)[:200]}); continue
        repo = R.rmap("repos").get(service)
        repo_dir = os.path.join(code_root, repo) if repo else None
        for b in got:
            if not in_window(b["time"], win):
                continue
            lanes = sorted(set(by_build.get((service, vkey(f"{b['version']} build{b['build']}")), [])), key=str)
            carried = []
            if repo_dir and os.path.isdir(repo_dir) and b.get("sha_full"):
                carried = [cm["sha"] for r in code if r["repo"] == repo for cm in
                           [x for t in r["tickets"] for x in t["commits"]] + r["untracked"] if ancestor(repo_dir, cm["sha"], b["sha_full"])]
            builds.append({"job": job, "service": service, "label": LABEL.get(service, service), "number": b["number"],
                           "version": b["version"], "build": b["build"], "result": b["result"], "branch": b["branch"],
                           "sha": b["sha"], "time": b["time"], "url": b["url"], "patch": "patch" in (b["branch"] or "").lower(),
                           "deployed_to": lanes, "commits": carried})
    reached = {sha: b["deployed_to"] for b in builds for sha in b["commits"]}
    for cm in window_commits:
        cm["lanes"] = reached.get(cm["sha"], [])
    # bundles created in the window
    bundles = []
    for host in ("qa", "prod"):
        try:
            for b in run_json(["python3", RELEASE, *env, "bundles", "--host", host, "--limit", "15", "--json"], timeout=120)["bundles"]:
                if in_window(R.when(b.get("createTime")), win):
                    bundles.append({"host": host, "name": b.get("bundleName"), "id": b.get("bundleId"), "created": R.when(b.get("createTime"))})
        except (LaneError, subprocess.TimeoutExpired, ValueError) as e:
            errors.append({"source": f"bundles {host}", "error": str(e)[:200]})
    # mail: release notices and QA reports, by subject, inside the window
    span = f"after:{int(datetime.datetime.fromisoformat(win['start']).timestamp())} before:{int(now.timestamp())}"
    releases, qa, mail_docker = [], [], []
    aliases = service_aliases()
    try:
        by_thread = {}
        for m in run_json(["python3", MAIL, *env, "search", f"{span} subject:Release", "--limit", "40", "--body", "--json"], timeout=300)["messages"]:
            if not re.match(r"^\s*Re:", m["subject"], re.I):
                mail_docker += docker_from_mail(m, aliases)
            if re.search(r"\[Release", m["subject"], re.I) and not re.search(r"test report", m["subject"], re.I):
                by_thread.setdefault(m["thread"], []).append(m)
        for msgs in by_thread.values():                     # a thread is one release: its first message, the replies counted
            first = next((m for m in msgs if not re.match(r"^\s*Re:", m["subject"], re.I)), msgs[-1])
            r = parse_release_mail(first)
            r["replies"] = len(msgs) - 1
            if IN_SCOPE_MAIL.search(r["subject"]):
                releases.append(r)
        for m in run_json(["python3", MAIL, *env, "search", f'{span} subject:("test report")', "--limit", "25", "--body", "--json"], timeout=300)["messages"]:
            if not re.match(r"^\s*Re:", m["subject"], re.I):
                mail_docker += docker_from_mail(m, aliases)
                q = parse_qa_mail(m)
                if q["mediahub"]:
                    qa.append(q)
                    if all(q[k] is None for k in ("pass", "fail", "closed", "new")):
                        errors.append({"source": f"qa mail {q['subject'][:60]}", "error": "no counts in a shape ela parses; read it by hand"})
    except (LaneError, subprocess.TimeoutExpired, ValueError) as e:
        errors.append({"source": "mail", "error": str(e)[:200]})
    for r in releases:                                      # Orchestration publishes no lane version; its mails name it
        o = re.search(r"Orchestration Service of version\s*v?([\d.]+)", r["subject"], re.I)
        lane = mail_lane(r["env"])
        if o and lane:                                      # a request until a reply in its thread says it was done
            msgs = read_thread(env, r.get("thread"), errors) if r.get("replies") else []
            rows = [x for x in rows if not (x["service"] == "orchestration" and x.get("lane") == lane)]
            rows.append({"host": "mail", "lane": lane, "tag": None, "service": "orchestration", "version": o.group(1), "updated": r["date"],
                         "state": release_state(msgs)})
    rows += [x for x in (prev or {}).get("rows", []) if x["host"] == "mail" and not any(
        y["host"] == "mail" and y["lane"] == x["lane"] and y["service"] == x["service"] for y in rows)]
    json.dump({"date": date, "at": now.isoformat(timespec="seconds"), "read": read, "rows": rows},
              open(os.path.join(runner, f"versions-{date}.json"), "w"), ensure_ascii=False)
    tested = keep_tested(runner, qa, now)
    # Slack by channel: the day's release thread, the dev channel's threads, the team report
    since = (now - datetime.timedelta(hours=args.hours + 24)).date().isoformat()
    for m in slack_rows(env, QA_RELEASE, since, errors):
        stamps = [m["at"]] + [datetime.datetime.fromtimestamp(float(r["ts"])).astimezone().isoformat() for r in m.get("replies") or []]
        if re.search(r"\d{4}-\d{2}-\d{2}_Release", m["text"]) and any(in_window(s, win) for s in stamps):
            done = [r["text"] for r in m.get("replies") or [] if re.search(f"{RELEASE_DONE}|{BUILD_RESULT}", r["text"])]
            releases.append({"subject": " ".join(m["text"].split())[:120], "from": m["user"], "date": m["at"], "env": "slack",
                             "moves": parse_release_thread(done), "text": "\n\n".join(done)[:3000],
                             "link": m["permalink"], "replies": m["reply_count"]})
    dev_threads = [{"by": m["user"], "at": m["at"], "text": " ".join(m["text"].split())[:200], "replies": m["reply_count"],
                    "keys": keys_in(m["text"]), "link": m["permalink"]}
                   for m in slack_rows(env, DEV_CHANNEL, f"{args.hours}h", errors, threads=False)]
    team_report = None
    for m in reversed(slack_rows(env, REPORT_CHANNEL, f"{args.hours + 24}h", errors, threads=False)):
        if TEAM_REPORTS.search(m["text"]):
            lines = [l for l in m["text"].splitlines() if l.strip()]
            team_report = {"title": lines[0][:120] if lines else "", "first_lines": lines[1:6], "link": m["permalink"], "at": m["at"]}
            break
    # the owner's own day: Jira moves and comments, commits, Slack messages, sent mail
    you = {"jira": [], "commits": [], "slack": [], "mail": []}
    names = set()
    try:
        me = run_json(["python3", JIRA, *env, "jql", "assignee = currentUser() ORDER BY updated DESC", "--limit", "1", "--json"])["issues"]
        names |= {me[0]["assignee"]} if me and me[0].get("assignee") else set()
    except (LaneError, subprocess.TimeoutExpired, ValueError) as e:
        errors.append({"source": "you: jira name", "error": str(e)[:200]})
    helm_keys = {h["key"] for h in y["ela"]["helm_autowrites"]}
    for c in y["cases"]:
        for e in c["jira"]:
            if e.get("by") in names and c["key"] in helm_keys and re.search(r"fix\s*(ed)?\s*in|fix version", e["field"] or "", re.I):
                y["ela"].setdefault("helm_fixed_in", []).append({"key": c["key"], "move": f"{e['field']} → {e['to'] or '—'}", "at": e["at"]})
            elif e.get("by") in names:
                you["jira"].append({"key": c["key"], "move": f"{e['field']} {e['from'] or '—'} → {e['to'] or '—'}", "at": e["at"]})
        for cm in c["comments"]:
            if cm.get("by") in names:
                you["jira"].append({"key": c["key"], "move": "comment", "at": cm["at"], "text": cm["text"][:160]})
        for s in c["slack"]:
            if s.get("by") in names:
                you["slack"].append({"key": c["key"], "channel": s["channel"], "text": s["text"], "link": s["permalink"]})
    you["commits"] = [dict(cm, repo=r["repo"]) for r in code for cm in [x for t in r["tickets"] for x in t["commits"]] + r["untracked"]
                      if cm["author"] in names]
    try:
        you["mail"] = [{"subject": m["subject"], "to": m["to"][:120], "date": m["date"]} for m in
                       run_json(["python3", MAIL, *env, "search", f"{span} in:sent", "--limit", "25", "--json"], timeout=120)["messages"]]
    except (LaneError, subprocess.TimeoutExpired, ValueError) as e:
        errors.append({"source": "you: sent mail", "error": str(e)[:200]})
    if not names:
        errors.append({"source": "you", "error": "the owner's Jira name was not read; Jira, commits and Slack by him are not split out"})
    out = {"date": date, "window": win, "releases": releases, "builds": builds, "versions": versions, "bundles": bundles,
            "qa": qa, "tickets": tickets, "code": {"repos": code, "unticketed_threads": y["unticketed_threads"]},
            "dev_threads": dev_threads, "you": you, "ela": y["ela"], "team_report": team_report,
            "stale_checkouts": y["stale_checkouts"], "errors": errors}
    try:
        named = run_json(["python3", RELEASE, *env, "bundles", f"MediaHub {LINE}", "--host", "prod", "--limit", "50", "--json"], timeout=120)["bundles"]
        out["findings_extra"] = pin_findings(named, R.read_pins().get(LINE))
    except (LaneError, subprocess.TimeoutExpired, ValueError) as e:
        out["findings_extra"] = []
        errors.append({"source": "bundles prod (release names)", "error": str(e)[:200]})
    out["docker"] = docker_moves(env, errors, win, site, extra=mail_docker)
    jira_claims(env, out["docker"], errors)
    pending = read_pending(site)
    cand = (pending or {}).get("candidate") or {}
    out["pending"] = pending
    out["findings"] = findings_of(out, rows, tested, env, errors, candidate=frozenset(cand.get("versions") or {})) + out.pop("findings_extra") \
        + docker_findings(out["docker"], fixed_in_targets(env, out["docker"], errors))
    for service, c in (cand.get("versions") or {}).items():
        if isinstance(c, dict) and c.get("awaiting"):
            out["findings"].append({"kind": "candidate_awaiting_owner", "lane": pending["to"], "service": service,
                                    "what": f"{cand.get('label')}: {LABEL.get(service, service)} awaits your choice — {c.get('why') or ''}".rstrip(" —"),
                                    "options": c.get("options") or [], "evidence": [pending.get("report") or ""], "at": pending.get("refreshed"),
                                    "rank": RANKS["candidate_awaiting_owner"]})
    out["counts"] = counts_of(out)
    out["counts"].update(close_counts(site, env, errors))
    return out


FULL_STAGE_DAYS = 10                    # a whole-board stage read older than this is not trusted for the close queue


def latest_verdicts(reports):
    """{key: (date, verdict)} from each ticket's newest verification on any lane; two on one day, a failure wins."""
    out, vd = {}, os.path.join(reports, "verify")
    for name in sorted(os.listdir(vd)) if os.path.isdir(vd) else []:
        m = re.match(r"^([A-Z][A-Z0-9]+-\d+)-(\d{4}-\d{2}-\d{2})", name)
        if not m:
            continue
        p = os.path.join(vd, name, "report.md") if os.path.isdir(os.path.join(vd, name)) else os.path.join(vd, name)
        try:
            v = re.search(r"\[!\w+\]\s+(PASS|FAIL|BLOCKED)\b|\bVerdict\s+(PASS|FAIL|BLOCKED)\b", open(p, encoding="utf-8").read())
        except OSError:
            continue
        if v and (m.group(1) not in out or m.group(2) >= out[m.group(1)][0]):
            if m.group(1) in out and m.group(2) == out[m.group(1)][0] and out[m.group(1)][1] != "PASS":
                continue
            out[m.group(1)] = (m.group(2), v.group(1) or v.group(2))
    return out


def close_queue(rows, open_keys, verdicts, page_says_no):
    """(close-ready, verified-not-fixed, page-disagrees) keys from stage rows: a close-notice row of a ticket still
    open, unless its newest verification failed or its own page contradicts the close."""
    cn = [r for r in rows.values() if r.get("action") in ("close-notice", "page-disagrees") and (open_keys is None or r["key"] in open_keys)]
    failing = [r["key"] for r in cn if verdicts.get(r["key"], ("", ""))[1] in ("FAIL", "BLOCKED")]
    disagree = [r["key"] for r in cn if r["key"] not in failing and (r.get("action") == "page-disagrees" or page_says_no(r["key"]))]
    ready = [r["key"] for r in cn if r["key"] not in failing and r["key"] not in disagree]
    return sorted(ready), sorted(failing), sorted(disagree)


def close_counts(site, env, errors):
    """close_ready and verified_not_fixed, counted once for every page: the board's stage rows (the newest whole-board
    read, today's overlaid), the tickets open in Jira now, the verifications' verdicts, and each ticket's own page."""
    runtime = site.get("runtime") or os.path.join(site.get("projects", ""), ".ela")
    reports = site.get("reports") or os.path.join(site.get("projects", ""), "reports")
    d, rows = os.path.join(runtime, "runner"), {}
    fulls = sorted(f for f in os.listdir(d) if f.endswith("-stage-full.json")) if os.path.isdir(d) else []
    read = None
    if fulls and (datetime.date.today() - datetime.date.fromisoformat(fulls[-1][:10])).days <= FULL_STAGE_DAYS:
        read = fulls[-1][:10]
        rows.update({r["key"]: r for r in json.load(open(os.path.join(d, fulls[-1]))).get("rows") or []})
    today = os.path.join(d, f"{datetime.date.today().isoformat()}-stage.json")
    if os.path.isfile(today):
        rows.update({r["key"]: r for r in json.load(open(today)).get("rows") or []})
    if not rows:
        errors.append({"source": "stage", "error": "no stage read within the last 10 days; close-ready not counted"})
        return {"close_ready": None, "verified_not_fixed": None}
    try:
        open_keys = {i["key"] for i in run_json(["python3", JIRA, *env, "jql", "project = MH AND statusCategory != Done",
                                                  "--limit", "3000", "--json"])["issues"]}
    except (LaneError, subprocess.TimeoutExpired, ValueError) as e:
        open_keys = None
        errors.append({"source": "jira open tickets", "error": str(e)[:200]})
    sys.path.insert(0, os.path.join(HERE, "..", "stage"))
    import stage as S                                       # noqa: E402  the same reading of a ticket page stage uses
    says_no = lambda k: (lambda pt: bool(pt[0] and S.page_disagrees(pt[1])))(S.ticket_page(k, reports))  # noqa: E731
    ready, failing, disagree = close_queue(rows, open_keys, latest_verdicts(reports), says_no)
    return {"close_ready": len(ready), "verified_not_fixed": len(failing), "page_disagrees": len(disagree),
            "close_read": {"stage_full": read, "open_tickets_read": open_keys is not None}}


def counts_of(out):
    """The day's counts, each with the window it covers, once: every page (the brief, Changes, the board, the sprint
    line, Home) reads these and never counts for itself, so one number never reads three ways."""
    repos = (out.get("code") or {}).get("repos") or []
    keyed = sum(len(t.get("commits") or []) for r in repos for t in r.get("tickets") or [])
    bare = sum(len(r.get("untracked") or []) for r in repos)
    return {"window": out.get("window"),
            "commits": keyed + bare, "commits_without_ticket": bare, "tickets_moved": len(out.get("tickets") or []),
            "builds": len(out.get("builds") or []), "lane_moves": len(out.get("versions") or []),
            "docker_moves": len(out.get("docker") or []), "qa_reports": len(out.get("qa") or []),
            "jobs": len((out.get("ela") or {}).get("jobs") or []), "ela_writes": len((out.get("ela") or {}).get("writes") or []),
            "findings": len(out.get("findings") or [])}


def pin_findings(named, pin):
    """Prod follows the newest official bundle; a pin only holds it on an older one, on purpose (ela ADR 0013). While a
    newer official exists the hold is his decision again: keep it, or unpin to follow the newest."""
    rel = [x for x in named if R.is_official(str(x.get("bundleName", "")), LINE)]
    newest = max(rel, key=lambda x: str(x.get("createTime") or ""), default=None)
    if not newest or not pin or str(pin.get("id")) == str(newest.get("bundleId")):
        return []
    pinned = next((x for x in rel if pin and str(x.get("bundleId")) == str(pin.get("id"))), None)
    if pinned and str(pinned.get("createTime") or "") >= str(newest.get("createTime") or ""):
        return []
    name = newest["bundleName"]
    return [{"kind": "release_newer_than_pin", "lane": "prod", "service": None,
             "what": f"prod is held on {pin.get('official')} by a pin ({pin.get('why') or 'no reason recorded'}); {name} "
                     f"({R.when(newest.get('createTime'))[:10]}) is newer",
             "options": [f"ela release unpin {LINE}"], "note": "the runner appends --apply on the owner's apply N", "evidence": [f"bundle {newest.get('bundleId')}"],
             "at": R.when(newest.get("createTime")), "rank": RANKS["candidate_awaiting_owner"]}]


DOCKER_LEDGER = os.path.join("releases", "docker-versions.jsonl")


def lane_bundles(env, line, role, host, cfg):
    """A lane's bundles, newest first. Prod's is the owner's pin when there is one (ADR 0012), then the release-named
    ones; the others follow the lane token."""
    if role == "prod":
        got = run_json(["python3", RELEASE, *env, "bundles", f"MediaHub {line}", "--host", host, "--limit", "50", "--json"], timeout=120)["bundles"]
        got = sorted((b for b in got if R.is_official(str(b.get("bundleName", "")), line)), key=lambda b: str(b.get("createTime") or ""), reverse=True)
        pin = R.read_pins().get(line) or {}
        pinned = next((b for b in got if str(b.get("bundleId")) == str(pin.get("id"))), None)
        return ([pinned] + [b for b in got if b is not pinned and str(b.get("createTime") or "") < str(pinned.get("createTime") or "")]) if pinned else got
    pre = (cfg.get("bundle_line") or "") + (cfg.get("bundle_lanes") or {}).get(role, "")
    got = run_json(["python3", RELEASE, *env, "bundles", cfg.get("bundle_line") or "", "--host", host, "--limit", "50", "--json"], timeout=120)["bundles"]
    got = [b for b in got if str(b.get("bundleName", "")) == pre or str(b.get("bundleName", "")).startswith(pre + "-")]
    return sorted(got, key=lambda b: str(b.get("createTime") or ""), reverse=True)


def is_version(v):
    """A tag that can be compared and written in Fixed In; `latest` and GM's named tags ("default Production2") cannot."""
    return bool(re.match(r"^v?\d+(\.\d+)+", str(v or "").strip()))


def norm(name):
    """Names compare case-insensitively, with `_`, `-` and spaces equal (live_transmit = live transmit = live-transmit)."""
    return re.sub(r"[\s_-]+", "-", str(name or "").strip().lower())


def service_aliases():
    """Every name a docker image or service goes by in the map → {image, slugs}: the image (the key under `images:`, which
    names its codebase) and the services the name reaches. An image's own name and its `aliases` reach all its services;
    a service's slug, GM name, process type, MQTT topic and row `aliases` reach that one."""
    out = {}
    try:
        text = open(os.path.join(json.load(open(SITE)).get("map", ""), "services.yaml"), encoding="utf-8").read()
    except (OSError, ValueError):
        return out
    image, slugs, names = None, [], []
    def close():
        if image:
            for n in [image] + names:
                out.setdefault(norm(n), {"image": image, "slugs": list(slugs)})
    for line in text.splitlines():
        h = re.match(r"^  ([\w.-]+):\s*$", line)
        if h:                                               # the next image begins
            close(); image, slugs, names = h.group(1), [], []
            continue
        lst = re.match(r"^    (slugs|aliases):\s*(\[.*\])\s*$", line)
        if lst:
            try:
                (slugs if lst.group(1) == "slugs" else names)[:] = json.loads(lst.group(2))
            except ValueError:
                pass
        m = re.match(r"^\s+- (\{.*\})\s*$", line)
        try:
            row = json.loads(m.group(1)) if m else None
        except ValueError:
            row = None
        if row and row.get("slug") and image:
            for n in [row.get(k) for k in ("slug", "gm_name", "process_type", "mqtt_topic")] + list(row.get("aliases") or []):
                if n:
                    out.setdefault(norm(n), {"image": image, "slugs": [row["slug"]]})
    close()
    return out


# a bare "decoder" or "encoder" names the main image of its kind unless the same line names another of that kind; still
# ambiguous, it is unresolved and drafts nothing (the MediaHub content session's rule, 2026-10-27; the map does not carry it)
BARE = {"decoder": ("playeroftvu", ("agoradecoder", "tvu_u_2004_capture", "video-decoder", "headlessr", "youtuberender", "zoomlinux")),
        "encoder": ("tvu264_all", ("agoraencoder", "peerclient", "video-encoder"))}


def resolve_bare(name, context):
    """A bare kind word → its main image, or None when the line names another image of that kind."""
    rule = BARE.get(norm(name))
    if not rule:
        return name
    word = lambda o: r"(?<![a-z0-9])" + r"[\s_-]+".join(map(re.escape, re.split(r"[\s_-]+", o))) + r"(?![a-z0-9])"
    others = [o for o in rule[1] if re.search(word(o), context.lower())]
    return None if others else rule[0]


def docker_entry(name, version, aliases, context=""):
    """The row's identity: what was seen, the image and slugs it reaches when the map knows the name."""
    resolved = resolve_bare(name, context)
    if resolved is None:
        return {"service": f"{name.strip()} (unresolved)", "seen": name.strip(), "image": None, "slugs": [], "mapped": False,
                "unresolved": True, "version": str(version).strip(), "comparable": is_version(version)}
    hit = aliases.get(norm(resolved))
    return {"service": (hit["slugs"][0] if hit and len(hit["slugs"]) == 1 else hit["image"]) if hit else name.strip(),
            "seen": name.strip(), "image": hit["image"] if hit else None, "slugs": hit["slugs"] if hit else [],
            "mapped": bool(hit), "version": str(version).strip(), "comparable": is_version(version)}


def docker_rows(diff, lane, newest, aliases, line):
    """A bundle-diff's added and changed docker services → one row each."""
    rows = []
    for r in diff.get("changed", []) + diff.get("added", []):
        if not str(r["service"]).lower().startswith("docker"):
            continue                                        # the SaaS rows mirror the lanes table; docker services only
        rows.append(dict(docker_entry(r["service"], r.get("to") or r.get("version"), aliases), gm_name=r["service"], line=line,
                         **{"from": r.get("from"), "at": R.when(newest.get("createTime")), "source": f"bundle {newest.get('bundleName')}",
                            "by": newest.get("operator") or None, "claims": [], "lane_or_bundle": f"{lane} · {newest.get('bundleName')}"}))
    return rows


def append_ledger(path, rows):
    """Append rows not yet in the ledger, one per service + version + source; returns how many were new."""
    seen = set()
    try:
        for line in open(path, encoding="utf-8"):
            try:
                r = json.loads(line)
                seen.add((r["service"], r["version"], r["source"]))
            except (ValueError, KeyError):
                pass
    except OSError:
        pass
    new = [r for r in rows if (r["service"], r["version"], r["source"]) not in seen]
    if new:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            for r in new:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(new)


IMAGE_RX = re.compile(r"[\w.-]+\.[a-z]{2,}/(?:[\w.-]+/)*([\w.-]+):v?([\w.+-]+)")   # matched on the image, the last path segment
QA_RELEASE_RX = re.compile(r"^\s*\[QA release\]\s*(.+?)\s+v?(\d[\w.+-]*)\s+for test", re.I)
BOX_RX = re.compile(r"Box images[^:]*:\s*(.+?)(?:\n\s*\n|\n[A-Z][\w ]+:|$)", re.S)


def docker_row(name, version, m, how, aliases, claims=(), context=""):
    return dict(docker_entry(name, version, aliases, context), line=None, **{
        "from": None, "at": (mail_time(m["date"]) or "")[:16].replace("T", " "), "source": f"mail {m['id']}",
        "by": email.utils.parseaddr(m["from"])[0] or m["from"], "subject": m["subject"],
        "claims": [{"key": k, "via": "mail", "ref": m["id"]} for k in claims], "lane_or_bundle": how})


def docker_from_mail(m, aliases):
    """Docker versions a mail announces: an image path in its subject (a trailing "- 20261026" is the report's date), a
    `[QA release] <service> <version> for test`, a default-tag update, and QA's "Box images" line. The tickets the mail
    names are its claims, except for the box line, which lists what the box ran, not what changed."""
    body, subj = m.get("body") or "", m["subject"]
    keys = [k for k in keys_in(body + " " + subj) if k.startswith("MH-")]   # Fixed In lives on MediaHub tickets; AC-3 is a codec
    rows = [docker_row(x.group(1), x.group(2), m, "image in a mail subject", aliases, keys) for x in IMAGE_RX.finditer(subj)]
    qa = QA_RELEASE_RX.match(subj)
    if qa:
        rows.append(docker_row(qa.group(1), qa.group(2), m, "QA release (for test)", aliases, keys, context=subj))
    tag = re.match(r"^\s*\[Release\]\s*<([^>]+)>", subj)
    if tag and TAG_RX.search(body):
        rows.append(docker_row(tag.group(1), TAG_RX.search(body).group("to"), m, "default tag update", aliases, keys))
    box = BOX_RX.search(body)
    for item in (box.group(1).replace("\n", " ").split(",") if box else []):
        v = re.match(r"^\s*(.+?)\s+v?(\d[\w.+-]*)\s*$", item)
        if v:                                               # "copier / tvu_live_transmit 1.0.23": the version is the last name's;
            rows.append(docker_row(v.group(1).split("/")[-1], v.group(2), m, "QA box images", aliases,   # the others are unversioned
                                   context=box.group(1)))
    return rows


def adf_text(node):
    if isinstance(node, dict):
        return (node.get("text") or "") + " ".join(adf_text(c) for c in node.get("content") or [])
    return " ".join(adf_text(c) for c in node) if isinstance(node, list) else ""


def jira_claims(env, rows, errors, days=30, read_max=8):
    """Tickets that name a docker version beside the service's name in a comment, last 30 days: claims via "jira" with
    the comment's id. Jira's text search splits versions into numbers, so it only narrows; each comment is read."""
    for r in (r for r in rows if r["comparable"]):
        words = {w for w in (r.get("seen"), r["service"], r.get("gm_name"), r.get("image")) if w}
        try:
            ver = {i["key"] for i in run_json(["python3", JIRA, *env, "jql", f'project = MH AND updated >= -{days}d AND text ~ "{r["version"]}"',
                                                 "--limit", "100", "--json"])["issues"]}
            named = set()
            for w in words:
                named |= {i["key"] for i in run_json(["python3", JIRA, *env, "jql", f'project = MH AND updated >= -{days}d AND text ~ "\\"{w}\\""',
                                                        "--limit", "100", "--json"])["issues"]}
        except (LaneError, subprocess.TimeoutExpired, ValueError) as e:
            errors.append({"source": f"jira claims {r['service']}", "error": str(e)[:200]}); continue
        near = re.compile("(" + "|".join(re.escape(w).replace(r"\_", "[ _-]").replace(r"\-", "[ _-]") for w in words) + r")\W{0,40}v?"
                          + re.escape(r["version"]) + r"\b", re.I)
        for key in sorted(ver & named)[:read_max]:
            try:
                issue = run_json(["python3", JIRA, *env, "read", key, "--json"])
            except (LaneError, subprocess.TimeoutExpired, ValueError):
                continue
            hit = next((c for c in issue.get("comments") or [] if near.search(adf_text(c.get("body")))), None)
            if hit and not any(c["key"] == key for c in r["claims"]):
                r["claims"].append({"key": key, "via": "jira", "ref": f"comment {hit.get('id')}"})


def fixed_in_targets(env, rows, errors):
    """{key: release label line or None} for the claimed keys whose Fixed In is empty."""
    keys = {c["key"] for r in rows for c in r["claims"]}
    if not keys:
        return {}
    try:
        got = run_json(["python3", JIRA, *env, "jql", f"key in ({','.join(sorted(keys))}) AND cf[11252] is EMPTY", "--limit", "100", "--json"])["issues"]
    except (LaneError, subprocess.TimeoutExpired, ValueError) as e:
        errors.append({"source": "jira fixed-in", "error": str(e)[:200]})
        return {}
    out = {}
    for i in got:
        labels = i.get("labels") or []
        out[i["key"]] = next((l.split("release:mh-", 1)[1] for l in labels if str(l).startswith("release:mh-")), None)
    return out


def fixed_in_entry(r):
    """The team's media Fixed In form, one entry per service: `<slug>@<image>:<version>` (47 MH tickets carry it)."""
    return "; ".join(f"{s}@{r['image']}:{r['version']}" for s in r["slugs"])


def docker_findings(rows, targets):
    """A docker version that names a ticket whose Fixed In is empty: the brief drafts the entry, citing the announcement.
    A bundle's version is drafted only for a ticket whose release label is the bundle's line; a name the map does not
    know, or a tag that is not a version, gets no command, and the finding says why."""
    F = []
    for r in rows:
        for c in r["claims"]:
            if c["key"] not in targets or (r.get("line") and targets[c["key"]] not in (None, r["line"])):
                continue
            why = ("" if r["mapped"] and r["comparable"] else
                   f"; {r['seen']} is ambiguous in its line (another image of that kind is named), so no entry is drafted" if r.get("unresolved") else
                   f"; the map has no image for {r['seen']}, so no entry is drafted" if not r["mapped"] else
                   f"; {r['version']} is a tag, not a version, so no entry is drafted")
            if not why and len(r["slugs"]) > 1:             # an image of several services: the ticket must say which (design review,
                why = (f"; {r['image']} carries {len(r['slugs'])} services and neither the announcement nor the ticket says which, "   # 2026-10-27)
                       "so no entry is drafted")
            F.append({"kind": "docker_version_names_ticket", "key": c["key"], "lane": r.get("lane_or_bundle"), "service": r["service"],
                      "what": f"{r['seen']} {r['version']} names {c['key']}, whose Fixed In is empty" + why,
                      "options": [f"ela jira fixed-in {c['key']} --add '{fixed_in_entry(r)}'"] if not why else [],
                      "evidence": [r["source"] if c["via"] != "jira" else f"{c['key']} {c['ref']}"], "at": r["at"],
                      "rank": RANKS["prod_fix_without_ticket"]})
    return F


def docker_moves(env, errors, win, site, extra=()):
    """Docker versions announced by the GM bundles, every release line: each lane's newest bundle against the one before
    it (prod's newest is the owner's pin). Every row goes to the ledger <reports>/releases/docker-versions.jsonl; the
    window's are returned, one per service, version and place. Media versions are announced, not built from tracked
    commits, so the bundle is their first-hand record."""
    aliases = service_aliases()
    rows = []
    for line, cfg in (R.rmap("lines") or {}).items():
        if not cfg.get("bundle_line") or not cfg.get("lanes"):
            continue
        for role in ("qa", "daily", "prod"):
            lane = cfg["lanes"].get(role)
            host = "qa" if role == "qa" else "prod"
            if not lane:
                continue
            try:
                got = lane_bundles(env, line, role, host, cfg)
                if len(got) < 2:
                    continue
                newest, before = got[0], got[1]
                diff = run_json(["python3", RELEASE, *env, "bundle-diff", str(before["bundleId"]), str(newest["bundleId"]),
                                 "--host-a", host, "--host-b", host, "--json"], timeout=180)
                rows += docker_rows(diff, lane, newest, aliases, line)
            except (LaneError, subprocess.TimeoutExpired, ValueError) as e:
                errors.append({"source": f"docker bundles {line} {role}", "error": str(e)[:200]})
    rows += list(extra)
    append_ledger(os.path.join(site.get("reports") or "", DOCKER_LEDGER), rows)
    merged = {}                                             # one row per service, version and where; sources and claims joined
    for r in (r for r in rows if in_window(r["at"], win)):
        k = (r["service"], r["version"], r["lane_or_bundle"])
        if k in merged:
            merged[k]["claims"] += [c for c in r["claims"] if c["key"] not in {x["key"] for x in merged[k]["claims"]}]
            merged[k]["also"] = merged[k].get("also", []) + [r["source"]]
        else:
            merged[k] = dict(r, claims=list(r["claims"]))
    return list(merged.values())


def read_pending(site):
    """<reports>/promote/pending.json while it is open (written by `ela promote report --out`), else None."""
    try:
        p = json.load(open(os.path.join(site.get("reports") or "", "promote", "pending.json")))
    except (OSError, ValueError):
        return None
    return None if p.get("closed") else p


def mail_lane(env):
    """A release mail's environment words → ela's lane name: Prod3 → prod-3, Daily WED → daily-wed, QA-AWS3 → qa-cn3."""
    e = re.sub(r"\s+", "", env or "").lower()
    m = re.search(r"prod-?(\d+)", e)
    if m:
        return f"prod-{m.group(1)}"
    return next((lane for k, lane in (("dailywed", "daily-wed"), ("qa-aws3", "qa-cn3"), ("qaaws3", "qa-cn3")) if k in e), None)


TESTED_KEPT_DAYS = 60


def keep_tested(runner, qa, now):
    """Every version a QA report says it ran on, kept across days in <runner>/qa-tested.json: {"lane|service|version":
    {at, verdict, subject}}, the newest report per version. A morning reads one day of mail; a verdict outlives it."""
    path = os.path.join(runner, "qa-tested.json")
    try:
        kept = json.load(open(path))
    except (OSError, ValueError):
        kept = {}
    for q in qa:
        for r in q["tested"]:
            k = f"{r['lane']}|{r['service']}|{short_version(r['version'])}"
            if q["at"] and (k not in kept or (kept[k].get("at") or "") < q["at"]):
                kept[k] = {"lane": r["lane"], "service": r["service"], "version": r["version"], "at": q["at"],
                           "verdict": q["verdict"], "subject": q["subject"]}
    cutoff = (now - datetime.timedelta(days=TESTED_KEPT_DAYS)).isoformat()
    kept = {k: v for k, v in kept.items() if (v.get("at") or "") >= cutoff}
    json.dump(kept, open(path, "w"), ensure_ascii=False)
    return kept


def newest_tested(tested, lane, service):
    rows = [v for v in tested.values() if v["lane"] == lane and v["service"] == service and vkey(v["version"])]
    return max(rows, key=lambda v: (vkey(v["version"]), v["at"] or ""), default=None)


NOT_A_CHANGE = re.compile(r"^(docs|test|chore|style)\b|\[arc-review\]", re.I)   # what rides along harmlessly
LINE = "2.1"   # the MediaHub release line the morning follows; its lanes come from map/release.yaml lines


def findings_of(out, rows, tested, env, errors, candidate=frozenset()):
    """What the facts say needs a judgment, by kind; the brief ranks them, the Changes page never does."""
    F = []
    lanes = (R.rmap("lines").get(LINE) or {}).get("lanes") or {}
    qa_lane = lanes.get("qa")
    moved = {(m["lane"], m["service"]): m for m in out["versions"]}
    for r in rows:
        if r.get("lane") != qa_lane or r["service"] not in SCOPE or not vkey(r["version"]):
            continue
        t = newest_tested(tested, qa_lane, r["service"])
        if t and vkey(r["version"]) <= vkey(t["version"]):
            continue
        what = (f"{qa_lane} runs {r['service']} {short_version(r['version'])}; the newest QA report on it tested "
                f"{short_version(t['version'])} ({(t['at'] or '')[:10]})" if t else f"{qa_lane} runs {r['service']} {short_version(r['version'])}; no QA report names it")
        F.append({"kind": "untested_build_on_lane", "lane": qa_lane, "service": r["service"], "what": what,
                  "evidence": [f"mail: {t['subject']}"] if t else [], "at": built_at(r["version"])})
        m = moved.get((qa_lane, r["service"]))
        if m and t and (m["built"] or "") > (t["at"] or "")[:16].replace("T", " "):
            F.append({"kind": "version_moved_after_qa_run", "lane": qa_lane, "service": r["service"],
                      "what": f"{r['service']} moved to {m['to']} on {qa_lane} after the QA run of {(t['at'] or '')[:16]}",
                      "evidence": [f"mail: {t['subject']}"], "at": m["built"]})
    ticketed = {cm["sha"] for r in out["code"]["repos"] for tk in r["tickets"] for cm in tk["commits"]}
    for b in out["builds"]:
        prod = [l for l in b["deployed_to"] if str(l).startswith("prod")]
        if b["patch"] and prod and not any(s in ticketed for s in b["commits"]):
            F.append({"kind": "prod_fix_without_ticket", "lane": prod[0], "service": b["service"],
                      "what": f"{b['label']} {b['version']} (#{b['number']}, {b['branch']}) runs on {', '.join(prod)} with no ticket",
                      "evidence": [b["url"]], "at": b["time"]})
    groups = {}
    for r in out["code"]["repos"]:
        for cm in r["untracked"]:
            if NOT_A_CHANGE.search(cm["subject"]) or not cm.get("lanes"):
                continue
            furthest = max(cm["lanes"], key=lambda l: (str(l).startswith("prod"), str(l).startswith("daily")))
            groups.setdefault((r["repo"], furthest), []).append(cm)   # once, at the lane nearest prod it reached
    for (repo, lane), cms in sorted(groups.items()):
        kind = "prod_fix_without_ticket" if str(lane).startswith("prod") else "unticketed_change_on_a_prod_path"
        F.append({"kind": kind, "lane": lane, "service": next((s for s, p in R.rmap("repos").items() if p == repo), repo),
                  "what": f"{len(cms)} commit(s) in {repo} with no ticket reached {lane}: " + "; ".join(c["subject"][:60] for c in cms[:3]),
                  "evidence": [f"{repo}@{c['sha']}" for c in cms[:5]], "at": max(c["at"] for c in cms)})
    for r in out["releases"]:                               # a prod change someone outside the team asked to hold
        lane = mail_lane(r["env"])
        if not (lane and lane.startswith("prod") and r.get("replies") and r.get("thread")):
            continue
        msgs = read_thread(env, r["thread"], errors)
        if not msgs:
            continue
        last = msgs[-1]
        sender = (email.utils.parseaddr(last["from"])[1] or "").lower()
        if not HOLD.search(said_part(last)):
            continue
        # outside the company's mail domains is a customer or partner, ranked first; a colleague off the MediaHub roster
        # is an internal word, ranked with the ordinary items; the roster's own people answer for themselves
        kind = ("lane_change_pending_external_word" if sender.split("@")[-1] not in company_domains()
                else "lane_change_pending_internal_word" if not on_roster(sender, env) else None)
        if kind:
            # whose answer it waits for: the owner's only when the ask is addressed to him; otherwise its first addressee
            # holds it, and the owner nudges after a working day (morning-package spec §2, amended 2026-10-27)
            to = email.utils.getaddresses([last.get("to") or ""])
            mine = (json.load(open(SITE)).get("emails") or {}).get("me", "").lower()
            to_owner = any(a.lower() == mine for _, a in to)
            holder = None if to_owner else next(((n or a) for n, a in to if a.lower() != mine), None)
            at = mail_time(last["date"])
            F.append({"kind": kind, "lane": lane, "service": None,
                      "what": f"{r['subject'][:90]}: the last word, from {email.utils.parseaddr(last['from'])[0] or sender}, asks "
                              f"{'you' if to_owner else holder or 'the thread'} to hold or confirm; no answer follows",
                      "to_owner": to_owner, "holder": holder,
                      "working_days_silent": working_days(to_date(at) + datetime.timedelta(days=1), now_date()) if at else None,
                      "evidence": [f"mail: {last['subject']}"], "at": at})
    try:
        r = subprocess.run(["python3", PROMOTE, *env, "--quiet", "constraints", "--json"], capture_output=True, text=True, timeout=300)
        cons = json.loads(r.stdout) if r.returncode in (0, 3) else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        cons = None
    if cons is None:
        errors.append({"source": "constraints", "error": "ela promote constraints did not answer; pins not checked"})
    for c in (cons or {}).get("active") or []:
        for pin in c.get("pins") or []:
            if pin.get("state") == "over":
                F.append({"kind": "constraint_over", "lane": pin.get("lane"), "service": pin.get("service"),
                          "what": f"{pin.get('service')} on {pin.get('lane')} runs {pin.get('version')}, over the pin {pin.get('max')}: {c.get('says')}",
                          "evidence": [c.get("source") or c["id"]], "at": None})
    errors.append({"source": "findings", "error": "customer_ask_unanswered is not computed: there is no customer and partner list to tell their messages apart"})
    for f in F:
        f["rank"] = finding_rank(f, candidate)
    return F


# the order the morning ranks findings in (morning-package spec §2); None = the lanes table only, not an item
RANKS = {"lane_change_pending_external_word": 1, "constraint_over": 2, "candidate_awaiting_owner": 3, "customer_ask_unanswered": 4,
         "prod_fix_without_ticket": 5, "lane_change_pending_internal_word": 6, "unticketed_change_on_a_prod_path": 9}


def now_date():
    return datetime.datetime.now().astimezone().date()


def finding_rank(f, candidate):
    """A build untested on a prod lane ranks with a prod fix; inside this week's candidate it ranks 7, a move after the
    QA run 8; outside it both stay in the lanes table."""
    if f["kind"] in RANKS:
        return RANKS[f["kind"]]
    if f["kind"] == "untested_build_on_lane" and str(f.get("lane")).startswith("prod"):
        return 5
    if f["kind"] in ("untested_build_on_lane", "version_moved_after_qa_run") and f.get("service") in candidate:
        return 7 if f["kind"] == "untested_build_on_lane" else 8
    return None


HOLD = re.compile(r"\b(hold|wait|stay|until|confirm|do not|don't|before)\b", re.I)
DONE = re.compile(r"\b(done|deployed|completed|finished|upgraded|released)\b", re.I)
_THREADS = {}


def read_thread(env, thread, errors):
    """A mail thread's messages, read once per run; [] and an error when it cannot be read."""
    if not thread:
        return []
    if thread not in _THREADS:
        try:
            _THREADS[thread] = run_json(["python3", MAIL, *env, "thread", thread, "--json"], timeout=120)["messages"]
        except (LaneError, subprocess.TimeoutExpired, ValueError) as e:
            errors.append({"source": f"mail thread {thread}", "error": str(e)[:200]})
            _THREADS[thread] = []
    return _THREADS[thread]


def said_part(m):
    """A mail's own words, the quoted thread below it cut off."""
    return re.split(r"\n\s*On .{5,80}wrote:", m.get("body") or "", maxsplit=1)[0]


def release_state(msgs):
    """A release mail asks for a deploy; it ran only when a reply says so and no hold follows that reply."""
    state = "requested"
    for m in msgs[1:]:
        said = said_part(m)
        if HOLD.search(said):
            state = "requested"
        elif DONE.search(said):
            state = "confirmed"
    return state


def company_domains():
    """The company's mail domains, from the owner's address in site.json, with its .cn twin."""
    try:
        me = (json.load(open(SITE)).get("emails") or {}).get("me") or ""
    except (OSError, ValueError):
        me = ""
    d = me.split("@")[-1].lower()
    return {d, d.rsplit(".", 1)[0] + ".cn"} if d else set()


def on_roster(addr, env):
    """True when the team roster knows the address; an unknown or unreadable roster counts as on it (no false alarm)."""
    if not addr:
        return True
    r = subprocess.run(["python3", TEAM, *env, "who", addr, "--json"], capture_output=True, text=True, timeout=60)
    return r.returncode != 3


def cmd_changes(args):
    today = datetime.date.today().isoformat()
    if args.date and args.date != today:
        print(f"changes reads the last {args.hours}h of each source; a past day ({args.date}) cannot be read again", file=sys.stderr)
        sys.exit(EX_USAGE)
    out = changes_facts(args)
    if args.json:                       # every source not read is in `errors`; the rest is still the answer
        print(json.dumps(out, ensure_ascii=False)); return
    w = out["window"]
    print(f"# changes · {out['date']} · {w['start'][:16]} → {w['end'][:16]}\n")
    print(f"## lanes ({len(out['versions'])} moves)")
    for v in out["versions"]:
        print(f"  {str(v['lane']):<12} {v['label']:<34} {v['from'] or '?'} → {v['to']}{'  (patch)' if v['patch'] else ''}")
    print(f"\n## builds ({len(out['builds'])})")
    for b in out["builds"]:
        print(f"  {b['label']:<34} #{b['number']:<5} {str(b['version']):<10} {b['branch'][:20]:<20} {b['time']}  "
              f"{', '.join(map(str, b['deployed_to'])) or 'built, not deployed'} · {len(b['commits'])} commits")
    print(f"\n## releases ({len(out['releases'])})")
    for r in out["releases"]:
        print(f"  {r['subject'][:90]}" + (f"  {r['link']}" if r.get("link") else ""))
        for m in r["moves"]:
            print(f"      {m['service']}: {m['from']} → {m['to']}  {m['env']}")
    print(f"\n## QA ({len(out['qa'])})")
    for q in out["qa"]:
        print(f"  {q['env'] or '?':<16} pass {q['pass']} · fail {q['fail']} · closed {q['closed']} · new {q['new']}  {q['subject'][:70]}")
    print("\n## code")
    for r in out["code"]["repos"]:
        print(f"  {r['repo']}: {len(r['tickets'])} tickets, {len(r['untracked'])} commits without one")
    tr = out["team_report"]
    print(f"\n## team report: {tr['title'] + '  ' + tr['link'] if tr else 'none in the window'}")
    for e in out["errors"]:
        print(f"not read: {e['source']}: {e['error']}", file=sys.stderr)

# ── matrix: which version runs on which lane, this morning ─────────────────────────────────────────

MATRIX_ROWS = ("mediahub-backend", "mediahub-frontend", "unified-streaming", "unified-media-frontend", "unified-media-backend",
               "orchestration")
LANE_SHOWN = {"qa-cn3": "QA-AWS3"}   # the name the release mails and the team use for the lane


def snapshots(runner, date):
    """(today's versions snapshot, the last one before it), either None."""
    names = sorted(f for f in os.listdir(runner) if re.fullmatch(r"versions-\d{4}-\d{2}-\d{2}\.json", f)) if os.path.isdir(runner) else []
    def load(f):
        try:
            return json.load(open(os.path.join(runner, f)))
        except (OSError, ValueError):
            return None
    today = load(f"versions-{date}.json") if f"versions-{date}.json" in names else None
    before = [f for f in names if f[9:19] < date]
    return today, (load(before[-1]) if before else None)


INTRADAY_RX = re.compile(r"(\d{4}-\d{2}-\d{2})-versions-(\d{4})\.json")


def lane_reads(runner, since=""):
    """Every saved lane read from a date on, in time order: [(date, HHMM, rows)]. The morning's
    `versions-<date>.json` (written by `ela changes`) and the reads `matrix --page` saves later in the day
    (`<date>-versions-HHMM.json`) when a lane moved since the last one."""
    out = []
    for f in sorted(os.listdir(runner)) if os.path.isdir(runner) else []:
        m = re.fullmatch(r"versions-(\d{4}-\d{2}-\d{2})\.json", f)
        d, hm = (m.group(1), "0000") if m else (INTRADAY_RX.fullmatch(f).groups() if INTRADAY_RX.fullmatch(f) else (None, None))
        if not d or d < since:
            continue
        try:
            rows = json.load(open(os.path.join(runner, f), encoding="utf-8")).get("rows") or []
        except (OSError, ValueError):
            continue
        out.append((d, hm, rows))
    return sorted(out, key=lambda x: (x[0], x[1]))


def read_lanes_live(env, base_rows):
    """The lanes as they run now, both hosts; a host that does not answer keeps its rows from the base read, and the
    mail-only rows (Orchestration) come from it too. (rows, {host: read}, errors)."""
    rows, read, errors = [], {}, []
    for host in ("qa", "prod"):
        try:
            rows += [dict(r, host=host) for r in run_json(["python3", RELEASE, *env, "envs", "--host", host, "--json"], timeout=120)["rows"]]
            read[host] = True
        except (LaneError, subprocess.TimeoutExpired, ValueError) as e:
            errors.append({"source": f"versions {host}", "error": str(e)[:200]})
            rows += [r for r in base_rows or [] if r.get("host") == host]
    return rows + [r for r in base_rows or [] if r.get("host") == "mail"], read, errors


def save_intraday(runner, now, rows, read, last_rows):
    """Keep a later read when a lane in scope moved since the last saved one, so the moves page and tomorrow's diff see
    a deploy between the morning reads. Returns the path, or None when nothing moved."""
    moved = [m for m in lane_moves(last_rows, rows, None) if read.get(m["host"]) and m["service"] in SCOPE]
    if not moved or last_rows is None:
        return None
    path = os.path.join(runner, f"{now:%Y-%m-%d}-versions-{now:%H%M}.json")
    tmp = path + ".tmp"
    json.dump({"date": now.date().isoformat(), "at": now.isoformat(timespec="seconds"), "read": read, "rows": rows},
              open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, path)
    return path


def matrix_cell(service, lane, rows, prev, tested, pins):
    """One cell: the version, ▲ and the old one when it moved since the last snapshot, QA's mark on that exact version,
    and the constraint's mark."""
    row = next((r for r in rows if r["service"] == service and r.get("lane") == lane), None)
    v = row["version"] if row else None
    if v is None:                                           # a service known only from its release mails has no lane row
        mail_only = any(r["service"] == service and r["host"] == "mail" for r in rows)
        return {"text": "no release mail" if mail_only else "—", "version": None}
    pv = R.parse_version(v)
    label = R.vlabel(pv) if pv else str(v)
    old = next((r["version"] for r in prev or [] if r["service"] == service and r.get("lane") == lane), None)
    moved = old is not None and vkey(old) != vkey(v)
    qa = [x for x in tested.values() if x["service"] == service and vkey(x["version"]) == vkey(v)]
    best = max(qa, key=lambda x: x["at"] or "", default=None)
    mark = ("✓ " if best["verdict"] == "pass" else "◐ ") + (best["at"] or "")[5:10] if best else "○"
    pin = pins.get((service, lane))
    if row.get("host") == "mail" and row.get("state") != "confirmed":
        return {"text": f"{label} requested", "version": label, "moved": False, "pin": pin}   # asked for, not known to run
    text = ("▲ " if moved else "") + label + (" patch" if pv and pv[3] else "") + (f" (was {R.vlabel(R.parse_version(old)) if R.parse_version(old) else old})" if moved else "") \
        + f" {mark}" + {"held": " 🔒", "over": " ⛔"}.get(pin, "")
    return {"text": text, "version": label, "moved": moved, "was": old if moved else None, "qa": mark, "pin": pin}


def bundle_cell(b, how, newest_build, pinned):
    """The bundle row's cell: name and date, "pinned" for a prod bundle a pin holds (ADR 0013), "list stale" when the
    lane's newest build is younger than the bundle."""
    if not b:
        return {"text": "—"}
    made = R.when(b.get("createTime"))[:10]
    stale = made < (newest_build or "")[:10]
    return {"text": f"{b['bundleName']} ({made})" + (" pinned" if pinned else "") + (" (list stale)" if stale else ""),
            "name": b["bundleName"], "source": how, "stale": stale}


def cmd_matrix(args):
    site = json.load(open(SITE))
    env = ["--env-file", args.env_file] if args.env_file else []
    date = datetime.date.today().isoformat()
    runner = os.path.join(site.get("runtime") or os.path.join(site.get("projects", ""), ".ela"), "runner")
    errors = []
    today, before = snapshots(runner, date)
    if getattr(args, "page", False) and today is not None:  # the page is right whenever it is built: read the lanes now
        last = (lane_reads(runner, date) or [(None, None, today["rows"])])[-1][2]
        rows, read, errs = read_lanes_live(env, last)
        errors += errs
        save_intraday(runner, datetime.datetime.now().astimezone(), rows, read, last)
    elif today is None:                                     # no `changes` run yet today: read the lanes now, not saved
        rows = []
        for host in ("qa", "prod"):
            try:
                rows += [dict(r, host=host) for r in run_json(["python3", RELEASE, *env, "envs", "--host", host, "--json"], timeout=120)["rows"]]
            except (LaneError, subprocess.TimeoutExpired, ValueError) as e:
                errors.append({"source": f"versions {host}", "error": str(e)[:200]})
        rows += [r for r in (before or {}).get("rows", []) if r["host"] == "mail"]
        errors.append({"source": "versions", "error": "no snapshot from `ela changes` today; read live, Orchestration as last known"})
    else:
        rows = today["rows"]
    try:
        tested = json.load(open(os.path.join(runner, "qa-tested.json")))
    except (OSError, ValueError):
        tested = {}
        errors.append({"source": "qa", "error": "no QA tested versions kept yet (`ela changes` writes them); every cell is ○"})
    pins, held = {}, []
    try:
        r = subprocess.run(["python3", PROMOTE, *env, "--quiet", "constraints", "--json"], capture_output=True, text=True, timeout=300)
        for c in (json.loads(r.stdout) if r.returncode in (0, 3) else {}).get("active") or []:
            for p in c.get("pins") or []:
                pins[(p.get("service"), p.get("lane"))] = p.get("state")
                held.append({"service": p.get("service"), "lane": p.get("lane"), "says": c.get("says") or c.get("id")})
    except (OSError, ValueError, subprocess.TimeoutExpired):
        errors.append({"source": "constraints", "error": "ela promote constraints did not answer; no pin marks"})
    cfg = R.rmap("lines").get(LINE) or {}
    roles = [r for r in ("prod", "daily", "qa") if (cfg.get("lanes") or {}).get(r)]
    lanes = [cfg["lanes"][r] for r in roles]
    cand = None
    if args.candidate:
        try:
            cand = json.load(open(args.candidate))
        except (OSError, ValueError) as e:
            errors.append({"source": "candidate", "error": str(e)[:200]})
        if cand and "candidate" in cand:                    # <reports>/promote/pending.json as it is
            args.promote_report = args.promote_report or cand.get("report")
            cand = None if cand.get("closed") else cand["candidate"]
    # the bundle each lane runs. GM records no deployment, so it is inferred: QA and daily bundles follow the lane-token
    # names (mh2.1@qa-q26); prod releases are named "MediaHub <line>.<n>", so prod takes the newest of those, and the
    # rc token only when none exists. Either is unconfirmed, and marked stale when the lane moved after it.
    bundle = {}
    toks = cfg.get("bundle_lanes") or {}
    for role, lane in zip(roles, lanes):
        host = "qa" if role == "qa" else "prod"
        newest = max((built_at(r["version"]) or "" for r in rows if r.get("lane") == lane and r["host"] != "mail"), default="")
        try:
            b, how = None, "token"
            if role == "prod":                              # the owner's pin first (ADR 0012), then the newest release name
                named = run_json(["python3", RELEASE, *env, "bundles", f"MediaHub {LINE}", "--host", host, "--limit", "50", "--json"], timeout=120)["bundles"]
                pin = R.read_pins().get(LINE) or {}
                b = next((x for x in named if pin and str(x.get("bundleId")) == str(pin.get("id"))), None)
                how = "official"
                if b is None:
                    b = max((x for x in named if R.is_official(str(x.get("bundleName", "")), LINE)), key=lambda x: str(x.get("createTime") or ""), default=None)
                    how = "by name"
            if b is None and role != "prod":                # prod has no token lane: an rc bundle is special-purpose (2026-10-27)
                got = run_json(["python3", RELEASE, *env, "bundles", cfg.get("bundle_line") or "", "--host", host, "--limit", "50", "--json"], timeout=120)["bundles"]
                pre = (cfg.get("bundle_line") or "") + toks.get(role, "")
                got = [x for x in got if str(x.get("bundleName", "")) == pre or str(x.get("bundleName", "")).startswith(pre + "-")]
                b, how = max(got, key=lambda x: str(x.get("createTime") or ""), default=None), "token"
            bundle[lane] = bundle_cell(b, how, newest, role == "prod" and how == "official")
        except (LaneError, subprocess.TimeoutExpired, ValueError) as e:
            bundle[lane] = {"text": "not read"}
            errors.append({"source": f"bundles {host}", "error": str(e)[:200]})
    prev = (before or {}).get("rows")
    table = [bundle_row(bundle, lanes, cand)]
    same = []
    for s in MATRIX_ROWS:
        cells = [matrix_cell(s, l, rows, prev, tested, pins) for l in lanes]
        if cand:
            cells.append(candidate_cell((cand.get("versions") or {}).get(s)))
        if len({c.get("version") for c in cells[:len(lanes)]}) == 1 and not any(c.get("moved") or c.get("pin") for c in cells):
            same.append(f"{LABEL.get(s, s)} {cells[0]['text']}")
            continue
        table.append({"row": LABEL.get(s, s), "service": s, "cells": cells})
    gate = None
    if args.promote_report and os.path.isfile(args.promote_report) and \
            datetime.datetime.now().timestamp() - os.path.getmtime(args.promote_report) < 86400:
        try:
            c = json.load(open(args.promote_report))["counts"]["findings"]
            age = int((datetime.datetime.now().timestamp() - os.path.getmtime(args.promote_report)) // 3600)
            gate = {"stop": c.get("stop", 0), "high": c.get("high", 0), "report": args.promote_report, "age_hours": age}
        except (OSError, ValueError, KeyError):
            errors.append({"source": "promote report", "error": f"unreadable: {args.promote_report}"})
    out = {"date": date, "lanes": [LANE_SHOWN.get(l, l) for l in lanes] + ([cand.get("label") or "next train"] if cand else []),
           "rows": table, "same": same, "gate": gate, "errors": errors, "held": held, "lane_ids": lanes}
    if args.page:
        path = write_lanes_page(out, site, env, runner, tested)
        print(f"written: {path}")
    elif args.json:
        print(json.dumps(out, ensure_ascii=False)); return
    else:
        print(render_matrix(out))
    for e in errors:
        print(f"not read: {e['source']}: {e['error']}", file=sys.stderr)


# ── the lanes page: a standing page the vault carries as lanes.md ─────────────────────────────────────

MOVES_DAYS = 14
PAIRS = (("qa", "daily"), ("daily", "prod"))       # what the next lane does not carry yet, nearest promotion first
NO_BEHAVIOUR = ("docs", "chore", "test", "style")   # the commit kinds that change no behaviour (promote's rule)
MAIL_SLUG = (("ur caller", "unified-streaming"), ("mediahub backend", "mediahub-backend"), ("mediahub frontend", "mediahub-frontend"),
             ("unified media frontend", "unified-media-frontend"), ("unified media backend", "unified-media-backend"),
             ("orchestration", "orchestration"))   # a release mail's service words → slug


def mail_slug(name):
    n = re.sub(r"\s+", " ", str(name or "")).lower()
    return next((slug for k, slug in MAIL_SLUG if k in n), str(name or "").strip())


def shown_service(slug):
    """One name per service on the page: the matrix's."""
    return LABEL.get(slug, slug)


def pair_report(env, a, b):
    """`ela promote report <line> a b --json`: the delta per service, its tickets and QA's verdict per key; read-only,
    no pending promotion recorded (that needs --out)."""
    return run_json(["python3", PROMOTE, *env, "--quiet", "report", LINE, a, b, "--purpose", "regular", "--json"], timeout=900)


def qa_said(ev):
    """A ticket's QA cell: a real verdict with its date, else the honest absence (a developer's Fixed In is not QA)."""
    v = (ev or {}).get("verdict")
    if v in ("pass", "fail"):
        when = max((str(i.get("when") or "")[:10] for i in (ev.get("items") or []) if i.get("verdict") == v), default="")
        return f"QA {v}" + (f" ({when[5:]})" if when else "")
    if v == "dev-declared":
        return "○ no QA verdict · Fixed In by developer"
    return "○ no QA verdict"


def differences(rep_, shown, held=()):
    """The section for one pair: a verdict line, then per service the tickets the next lane lacks, with QA's word and
    any standing constraint holding them, then the behaviour commits without a ticket, folded; docs and tests are one
    closing line."""
    frm, to = shown(rep_["lanes"]["from"]), shown(rep_["lanes"]["to"])
    verdicts = (rep_.get("evidence") or {}).get("keys") or {}
    tickets = {t["key"]: t for t in (rep_.get("tickets") or {}).get("tickets") or [] if t.get("exists")}
    ahead = [x for x in rep_["delta"]["services"] if x.get("relation") == "from_ahead"]
    keyed = lambda c: c.get("keys_in_subject") or c.get("keys") or []  # noqa: E731
    keys = sorted({k for x in ahead for c in x["commits"] for k in keyed(c) if k in tickets})
    verified = [k for k in keys if (verdicts.get(k) or {}).get("verdict") == "pass"]
    unfiled = [c for x in ahead for c in x["commits"] if not keyed(c) and c.get("kind") not in NO_BEHAVIOUR]
    L = [f"### {frm} ahead of {to}", ""]
    if not ahead:
        return L + [f"{to} carries everything {frm} runs.", ""]
    L += [f"**{frm} carries {len(keys)} ticket{'s' if len(keys) != 1 else ''} {to} does not; {len(verified)} verified, "
          f"{len(keys) - len(verified)} untested" + (f", {len(unfiled)} unfiled fix{'es' if len(unfiled) != 1 else ''}" if unfiled else "") + ".**", ""]
    for x in ahead:
        own = sorted({k for c in x["commits"] for k in keyed(c) if k in tickets})
        missing = sorted({k for c in x["commits"] for k in keyed(c) if k not in tickets})
        bare = [c for c in x["commits"] if not keyed(c) and c.get("kind") not in NO_BEHAVIOUR]
        quiet = [c for c in x["commits"] if not keyed(c) and c.get("kind") in NO_BEHAVIOUR]
        holds = [h for h in held if h["service"] == x["service"]]
        L += [f"**{shown_service(x['service'])}** {vlabel_of(x.get('to'))} → {vlabel_of(x.get('from'))}", ""]
        for k in own:
            t = tickets[k]
            lock = "".join(f" · 🔒 held off {h['lane']}: {h['says']}" for h in holds)
            L.append(f"- [{k}]({t.get('url') or ''}) {t.get('summary') or ''} — {qa_said(verdicts.get(k))} · {t.get('status') or '?'}{lock}")
        L += [f"- {k} — named in a commit, not in Jira" for k in missing]
        if bare:
            L += ["", f"> [!note]- {len(bare)} behaviour commit{'s' if len(bare) != 1 else ''} without a ticket"] + \
                 [f"> - `{c['sha']}` {c['subject'][:100]}" for c in bare]
        if quiet:
            kinds = {}
            for c in quiet:
                kinds[c.get("kind")] = kinds.get(c.get("kind"), 0) + 1
            L += ["", " and ".join(f"{n} {k} commit{'s' if n != 1 else ''}" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]))
                  + ", no behaviour."]
        if not (own or missing or bare or quiet):
            L.append("a rebuild with no new commits")
        L.append("")
    return L


def vlabel_of(raw):
    pv = R.parse_version(str(raw or ""))
    return R.vlabel(pv) if pv else str(raw or "—")


def version_text(raw):
    m = re.search(r"\d+\.\d+\.\d+(?:\.\d+)?", str(raw or ""))
    return m.group(0) if m else None


def out_of_order(out):
    """Versions run QA ≥ daily ≥ prod. Each app service whose lanes break that, within one series (M.m); a pair in
    two series or without a version is undetermined, never an inversion."""
    lanes = out["lanes"]
    lines, und = [], 0
    for r in out["rows"]:
        if not r.get("service"):
            continue
        vs = [c.get("version") for c in r["cells"][:3]]                    # prod, daily, qa as the matrix orders them
        for lo, hi in ((0, 1), (1, 2)):
            a, b = R.parse_version(vs[lo]), R.parse_version(vs[hi])
            if not vs[lo] or not vs[hi]:
                continue
            if not a or not b or a[:2] != b[:2]:
                und += vs[lo] != vs[hi]
                continue
            if a > b:
                lines.append(f"{r['row']}: {lanes[hi]} {vs[hi]} is below {lanes[lo]} {vs[lo]}")
    return lines, und


def movements(runtime, reports, tested, today, shown, bundles_now=None):
    """Every lane move of the last MOVES_DAYS days, newest first, from the daily changes files (lane versions, the
    release mails and threads with their tickets, new bundles) and the docker ledger (docker services as slug@image);
    today's bundles from the matrix when they moved since the last file. One row per lane, service and version."""
    runner = os.path.join(runtime, "runner")
    rows, first = {}, None
    images = {}
    for n, v in service_aliases().items():
        for slug in v["slugs"]:
            images.setdefault(slug, v["image"])
    since = (today - datetime.timedelta(days=MOVES_DAYS - 1)).isoformat()

    def add(at, lane, service, frm, to, keys=(), qa=None):
        if not lane or not to:
            return
        k = (at, lane, service, version_text(to) or str(to))
        r = rows.setdefault(k, {"at": at, "lane": lane, "service": service, "from": None, "to": to, "tickets": set(), "qa": qa})
        r["from"] = r["from"] or frm
        r["tickets"] |= set(keys)
        r["qa"] = r["qa"] or qa

    def qa_mark(service, to):
        qa = [x for x in tested.values() if x["service"] == service and version_text(x["version"]) == version_text(to)]
        best = max(qa, key=lambda x: x["at"] or "", default=None)
        return ("✓" if best["verdict"] == "pass" else "◐") if best else "○"

    last_bundle = {}
    for f in sorted(os.listdir(runner)) if os.path.isdir(runner) else []:
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})-changes\.json", f)
        if not m:
            continue
        try:
            d = json.load(open(os.path.join(runner, f), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        dnum = lambda b: int((re.search(r"-d(\d+)$", str(b.get("name") or "")) or [0, 0])[1])  # noqa: E731  (same minute: the counter orders)
        for b in sorted(d.get("bundles") or [], key=lambda b: (b.get("created") or "", dnum(b))):
            tok = re.match(r"^[\w.]+@([a-z]+(?:-[a-z]+)?)-", str(b.get("name") or ""))
            lane = {"daily-wed": "daily-wed", "stage": "daily-stage", "qa": "qa-cn3"}.get(tok.group(1) if tok else "")
            if lane:
                prev = last_bundle.get(lane)
                if (b.get("created") or "")[:10] >= since:
                    back = prev and dnum(b) < dnum({"name": prev})
                    add((b.get("created") or m.group(1))[:10], shown(lane), "media bundle", prev, b["name"] + (" (rolled back)" if back else ""))
                last_bundle[lane] = b["name"]
        if m.group(1) < since:
            continue
        first = first or m.group(1)
        keys_of = {c["sha"][:8]: t["key"] for r in (d.get("code") or {}).get("repos") or [] for t in r.get("tickets") or []
                   for c in t.get("commits") or []}
        for v in d.get("versions") or []:
            b = next((b for b in d.get("builds") or [] if b.get("service") == v["service"] and b.get("build") == v.get("build")), None)
            keys = {keys_of[str(c)[:8]] for c in (b or {}).get("commits") or [] if str(c)[:8] in keys_of}
            if v.get("from") and vkey(v["from"]) == vkey(v["to"]):
                continue
            add((v.get("built") or m.group(1))[:10], shown(v["lane"]), v["service"], v.get("from"), v["to"], keys, qa_mark(v["service"], v["to"]))
        qa_lane = ((R.rmap("lines") or {}).get(LINE) or {}).get("lanes", {}).get("qa")
        for b in d.get("builds") or []:
            if b.get("result") != "SUCCESS":
                continue
            lanes = b.get("deployed_to") or ([qa_lane] if b.get("branch") == f"release{LINE}" and qa_lane else [])
            keys = {keys_of[str(c)[:8]] for c in b.get("commits") or [] if str(c)[:8] in keys_of}
            to = f"{b['version']} build {b['build']}"
            pv = R.parse_version(b["version"])
            frm = (f"{pv[0]}.{pv[1]}.{pv[2]}" if pv[3] == 1 else f"{pv[0]}.{pv[1]}.{pv[2]}.{pv[3] - 1}") if pv and pv[3] else None   # a patch sits on its base
            for lane in lanes:
                add(str(b.get("time") or m.group(1))[:10], shown(lane), b["service"], frm, to, keys, qa_mark(b["service"], to))
        snap = None
        for rel in d.get("releases") or []:
            try:
                at = email.utils.parsedate_to_datetime(rel["date"]).astimezone().date().isoformat() if "," in str(rel.get("date")) else str(rel.get("date"))[:10]
            except (TypeError, ValueError):
                at = m.group(1)
            for mv in rel.get("moves") or []:
                lane = mail_lane(mv.get("env") or rel.get("env"))
                svc = mail_slug(mv.get("service"))
                keys = {k for it in mv.get("items") or [] for k in it.get("keys") or []}
                add(at, shown(lane) if lane else None, svc, mv.get("from"), mv.get("to"), keys, qa_mark(svc, mv.get("to")))
            subj = rel.get("subject") or ""
            o = re.search(r"Orchestration Service of version (\S+)", subj)
            if o and not rel.get("moves"):
                snap = snap or snapshot_on_or_after(runner, at)
                row = next((x for x in (snap or {}).get("rows") or [] if x["service"] == "orchestration" and x.get("version") == o.group(1)), None)
                landed = (row or {}).get("state") == "confirmed"
                add(at, shown(mail_lane(rel.get("env")) or "?"), "orchestration", None, o.group(1) + ("" if landed else " requested"))
            b = re.search(r"Release build (\S+) \(([^→)]+)→\s*([^)]+)\)", subj)
            if b and not rel.get("moves") and not subj.lower().startswith("re:"):
                src, dst = mail_lane(b.group(2)), mail_lane(b.group(3))
                add(at, shown(dst or b.group(3).strip()), "app bundle", f"from {shown(src or b.group(2).strip())}", f"build {b.group(1)}")
                try:
                    sent = email.utils.parsedate_to_datetime(rel["date"])
                except (TypeError, ValueError):
                    sent = None
                snap = snap or snapshot_on_or_after(runner, at)
                for r in (snap or {}).get("rows") or []:   # what the release carried: prod now equal to daily, built before the mail
                    if r.get("lane") != dst or r.get("host") == "mail" or r["service"] not in SCOPE:
                        continue
                    twin = next((x for x in snap["rows"] if x.get("lane") == src and x["service"] == r["service"]), None)
                    built = built_at(r["version"])
                    if twin and vkey(twin["version"]) == vkey(r["version"]) and sent and built and \
                            datetime.datetime.fromisoformat(built).replace(tzinfo=datetime.timezone.utc) <= sent:
                        add(at, shown(dst), r["service"], None, short_version(r["version"]), (), qa_mark(r["service"], r["version"]))
    reads = lane_reads(runner, since)
    for (d0, _, base), (d, hm, now_rows) in zip(reads, reads[1:]):   # a deploy between two reads of one day
        if hm == "0000" or d0 != d:
            continue
        for mv in lane_moves(base, now_rows, None):
            if mv["service"] in SCOPE and mv["host"] != "mail":
                first = min(first or d, d)
                add((mv.get("built") or d)[:10], shown(mv["lane"]), mv["service"], mv["from"], mv["to"], (), qa_mark(mv["service"], mv["to"]))
    for lane, name in (bundles_now or {}).items():         # a bundle made since the last daily read
        if name and last_bundle.get(lane) and last_bundle[lane] != name:
            add(today.isoformat(), shown(lane), "media bundle", last_bundle[lane], name)
    try:
        for line in open(os.path.join(reports, DOCKER_LEDGER), encoding="utf-8"):
            r = json.loads(line)
            if (r.get("at") or "")[:10] < since or not r.get("from"):
                continue
            lane = (r.get("lane_or_bundle") or "").split(" · ")[0]
            first = min(first or r["at"][:10], r["at"][:10])
            add(r["at"][:10], shown(lane), f"{r['service']}@{images.get(r['service'], '?')}", r["from"], r["version"],
                {c if isinstance(c, str) else c.get("key") for c in r.get("claims") or []} - {None}, "○")
    except (OSError, ValueError):
        pass
    order = lambda r: (r["at"], R.parse_version(version_text(r["to"]) or "") or (0,), str(r["to"]))  # noqa: E731
    chains = {}
    for r in sorted(rows.values(), key=order):              # one lane, one service, in time order: each from is the last to
        k = (r["lane"], r["service"])
        if not r["from"] and k in chains and r["service"] not in ("app bundle",):
            r["from"] = chains[k]
        chains[k] = re.sub(r" requested$", "", str(r["to"]))
    L = ["| date | lane | service | from → to | tickets | QA |", "|---|---|---|---|---|---|"]
    for day in (today - datetime.timedelta(days=i) for i in range(MOVES_DAYS)):
        iso = day.isoformat()
        if first and iso < first:
            break
        got = sorted((r for r in rows.values() if r["at"] == iso), key=lambda r: (r["lane"], r["service"]))
        if not got:
            L.append(f"| {iso[5:]} | | no movement | | | |")
        for r in got:
            plain = lambda v: short_version(v) if vkey(v) and re.fullmatch(r"v?[\d.]+(?:\+\d+| build \d+)?", str(v).strip()) else v  # noqa: E731
            move = f"{plain(r['from']) if r['from'] else '—'} → {plain(r['to'])}"
            L.append(f"| {iso[5:]} | {r['lane']} | {shown_service(r['service'])} | {move} | {', '.join(sorted(r['tickets'])) or '—'} | {r['qa'] or ''} |")
    note = f"*Kept since {first}; the table fills to {MOVES_DAYS} days as the daily reads accumulate.*" if first and first > since else ""
    return L + ([""] + [note] if note else [])


def snapshot_on_or_after(runner, date):
    """The first lane read (`versions-<date>.json`) on or after a date, or None."""
    names = sorted(f for f in os.listdir(runner) if re.fullmatch(r"versions-\d{4}-\d{2}-\d{2}\.json", f) and f[9:19] >= date) if os.path.isdir(runner) else []
    try:
        return json.load(open(os.path.join(runner, names[0]), encoding="utf-8")) if names else None
    except (OSError, ValueError):
        return None


def deploy_note(now, plan):
    """The line under the lanes table that places the read against the day's QA deploy (`ela day`: qa_deploy), so a
    page read at 13:00 is known to predate the build; none on a day off or when the hour is not set."""
    qa = str(plan.get("qa_deploy") or "")
    if not plan.get("working_day") or not re.fullmatch(r"\d{2}:\d{2}", qa):
        return None
    return f"*Read at {now:%H:%M}, {'before' if f'{now:%H:%M}' < qa else 'after'} today's {LANE_SHOWN.get('qa-cn3', 'QA')} deploy (~{qa})*"


def write_lanes_page(out, site, env, runner, tested):
    """<reports>/lanes/lanes.md, rewritten whole: the lanes table and any version out of order (QA ≥ daily ≥ prod),
    what each lane carries that the next does not, and the moves of the last two weeks. The vault carries it as
    lanes.md beside the board."""
    reports = site.get("reports") or os.path.join(site.get("projects", ""), "reports")
    runtime = site.get("runtime") or os.path.join(site.get("projects", ""), ".ela")
    now = datetime.datetime.now().astimezone()
    shown = lambda l: LANE_SHOWN.get(l, l)  # noqa: E731
    inv, und = out_of_order(out)
    order = (["", "**Out of order** (versions run QA ≥ daily ≥ prod):", ""] + [f"- {x}" for x in inv]) if inv else \
            ["", "*Every lane in order: QA ≥ daily ≥ prod*" + (f" *({und} pair{'s' if und != 1 else ''} in two series, not compared)*" if und else "")]
    note = deploy_note(now, day_plan(now.date()))
    L = ["# The lanes", "", f"*{now:%Y-%m-%d %H:%M} · line {LINE}*", "", "## The lanes this morning", "", render_matrix(out)] + order + \
        (["", note] if note else []) + ["", "## Differences", ""]
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(PAIRS)) as ex:
        futs = [(a, b, ex.submit(pair_report, env, a, b)) for a, b in PAIRS]
        for a, b, fu in futs:
            try:
                L += differences(fu.result(), shown, out.get("held") or [])
            except (LaneError, subprocess.TimeoutExpired, ValueError, KeyError) as e:
                L += [f"### {a} ahead of {b}", "", f"Not read: {str(e)[:200]}", ""]
    bundles_now = {lane: (c.get("name") if isinstance(c, dict) else None)
                   for lane, c in zip(out.get("lane_ids") or [], (out["rows"][0]["cells"] if out["rows"] else []))}
    L += ["## Movements, 14 days", ""] + movements(runtime, reports, tested, now.date(), shown, bundles_now) + [""]
    path = os.path.join(reports, "lanes", "lanes.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    open(tmp, "w", encoding="utf-8").write("\n".join(L))
    os.replace(tmp, path)
    return path


def bundle_row(bundle, lanes, cand):
    """The media-bundle row: one cell per lane, and one for the next train when there is a candidate (its bundle when
    it names one, a dash otherwise), so the row has as many cells as the table has columns."""
    cells = [bundle.get(l, {"text": "—"}) for l in lanes]
    if cand:
        cells.append({"text": str(cand.get("bundle") or "—")})
    return {"row": "media bundle", "cells": cells}


def candidate_cell(c):
    """A next-train cell: a version (a plain string in an older file), or a choice awaiting the owner."""
    if isinstance(c, dict) and c.get("awaiting"):
        return {"text": f"? ({len(c.get('options') or [])} options)", "awaiting": c}
    v = c.get("version") if isinstance(c, dict) else c
    return {"text": str(v or "—"), "version": v}


def render_matrix(out):
    L = ["| | " + " | ".join(out["lanes"]) + " |", "|---|" + "---|" * len(out["lanes"])]
    for r in out["rows"]:
        L.append(f"| {r['row']} | " + " | ".join(c["text"] for c in r["cells"]) + " |")
    if out["same"]:
        L += ["", f"*{len(out['same'])} more the same on every lane: " + "; ".join(out["same"]) + "*"]
    L += ["", "*▲ moved since yesterday · ✓ QA passed this exact version (date) · ◐ partly · ○ no QA report names it · 🔒 a pin held · ⛔ over*"]
    if out["gate"]:
        g = out["gate"]
        L += ["", f"prod candidate: {g['stop']} stop · {g['high']} high (promote report `{os.path.basename(g['report'])}`, "
                  f"{g.get('age_hours', 0)}h old)"]
    return "\n".join(L)


APPLY_RX = re.compile(r"\bapply\s+(\d+)\b", re.I)
APPLY_BOX_RX = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+apply\s+(\d+)\b", re.I | re.M)


def page_check(page, actions):
    """Every `apply N` on a page has its drafted action in the actions file and its box on the page: ([numbers
    with no action], [numbers named without a box]). A page with either is a failed page."""
    named = {int(n) for n in APPLY_RX.findall(page)}
    boxed = {int(n) for n in APPLY_BOX_RX.findall(page)}
    have = {int(a["n"]) for a in actions if str(a.get("n", "")).isdigit()}
    return sorted(named - have), sorted(named - boxed)


def cmd_page_check(args):
    try:
        page = open(args.page, encoding="utf-8").read()
        actions = json.load(open(args.actions, encoding="utf-8")) if args.actions else []
    except (OSError, ValueError) as e:
        print(f"page-check: {e}", file=sys.stderr); sys.exit(2)
    orphan, unboxed = page_check(page, actions)
    for n in orphan:
        print(f"apply {n}: no such action in {os.path.basename(args.actions or '(none)')}")
    for n in unboxed:
        print(f"apply {n}: named without its box on the page")
    sys.path.insert(0, os.path.join(HERE, "..", "review"))
    import review                                       # the rest of the page's mechanical checks (`ela review lint`)
    _, counts, bundles, in_vault, _ = review.context(args.page, page, args.actions)
    rest = review.lint(page, None, counts, bundles, in_vault)
    for line in rest:
        print(f"lint: {line}")
    # the runner holds back a page that still fails after one repair, and its repair covers apply N only: the other
    # checks fail the page under --strict, once the repair knows them; until then they are printed as advice
    sys.exit(1 if orphan or unboxed or (rest and args.strict) else 0)


def front_matter(text):
    """The `key: value` lines between the leading `---` fences; values tried as JSON (the vault writes them quoted)."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    out = {}
    for line in (m.group(1).splitlines() if m else []):
        k, sep, v = line.partition(":")
        if sep and re.match(r"^[A-Za-z_][\w-]*$", k.strip()):
            v = v.strip()
            try:
                out[k.strip()] = json.loads(v)
            except ValueError:
                out[k.strip()] = v
    return out


WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_DAY = None


def flow_list(v):
    """A YAML list the stdlib subset left as text ("[Mon, Wed]"), or a list as it is."""
    if isinstance(v, list):
        return [str(x) for x in v]
    v = str(v or "").strip()
    return [x.strip().strip("\"'") for x in v.strip("[]").split(",") if x.strip()] if v.startswith("[") else ([v] if v else [])


def owner_day(path=None):
    """The owner's day as data, <elak>/blueprint/meetings.yaml: {day: {at_desk, leaves, dm_hours, qa_deploy},
    holidays, meetings}. Empty parts when the file is absent; the owner writes it, ela only reads it."""
    global _DAY
    if _DAY is not None and path is None:
        return _DAY
    if path is None:
        try:
            path = os.path.join(json.load(open(SITE)).get("elak") or "", "blueprint", "meetings.yaml")
        except (OSError, ValueError):
            path = ""
    try:
        doc = R._yaml_subset(open(path, encoding="utf-8").read()) or {}
    except (OSError, ValueError):
        doc = {}
    day = dict(doc.get("day") or {})
    day["dm_hours"] = flow_list(day.get("dm_hours"))
    out = {"path": path, "day": day, "holidays": flow_list(doc.get("holidays")), "meetings": list(doc.get("meetings") or [])}
    if path and path.endswith(os.path.join("blueprint", "meetings.yaml")):
        _DAY = out
    return out


def is_working_day(d, doc=None):
    return d.weekday() < 5 and d.isoformat() not in (doc or owner_day())["holidays"]


def day_plan(date, doc=None):
    """One date as the owner lives it: working or not, his hours, and the meetings he has that day in time order, each
    with the heading its brief section takes (`<name> at HH:MM`). A meeting not enabled, or with no time, is none."""
    doc = doc or owner_day()
    wd = WEEKDAY_NAMES[date.weekday()]
    meetings = sorted(({"name": m.get("name"), "key": m.get("key"), "time": str(m.get("time")), "audience": flow_list(m.get("audience")),
                        "section": f"{m.get('name')} at {m.get('time')}"}
                       for m in doc["meetings"] if isinstance(m, dict) and m.get("enabled") is True and str(m.get("time") or "").strip()
                       and wd in flow_list(m.get("weekdays"))), key=lambda m: m["time"])
    return {"date": date.isoformat(), "weekday": wd, "working_day": is_working_day(date, doc),
            "holiday": date.isoformat() in doc["holidays"], **doc["day"], "holidays": doc["holidays"],
            "meetings": meetings if is_working_day(date, doc) else [], "source": doc["path"]}


def cmd_day(args):
    d = datetime.date.fromisoformat(args.date) if args.date else datetime.date.today()
    plan = day_plan(d)
    if args.json:
        print(json.dumps(plan, ensure_ascii=False)); return
    print(f"{plan['date']} {plan['weekday']} · {'working day' if plan['working_day'] else 'not a working day'}"
          + (f" · at desk {plan.get('at_desk')}, leaves {plan.get('leaves')} · DM {'–'.join(plan['dm_hours'])} · QA deploy {plan.get('qa_deploy')}"
             if plan.get("at_desk") else ""))
    for m in plan["meetings"]:
        print(f"  {m['section']} ({', '.join(m['audience'])})")


def working_days(a, b):
    """Working days from a to b, both included (weekdays less the owner's holidays); 0 when b is before a."""
    n, d = 0, a
    while d <= b:
        n += is_working_day(d)
        d += datetime.timedelta(days=1)
    return n


def plain(cell):
    cell = re.sub(r"\[\[[^\]|]*\\?\|([^\]]+)\]\]", r"\1", cell)          # [[note\|label]] → label
    cell = re.sub(r"\[\[([^\]]+)\]\]", r"\1", cell)
    cell = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cell)                 # [MH-1](url) → MH-1
    return re.sub(r"\s+", " ", cell.replace("**", "").replace("`", "")).strip()


def table_rows(body, heading):
    """The first table under `## <heading>`: (header cells, rows), the separator dropped, each row a list of cells."""
    m = re.search(r"^## " + re.escape(heading) + r"\s*$(.*?)(?=^## |\Z)", body, re.M | re.S)
    rows = [l.strip() for l in (m.group(1).splitlines() if m else []) if l.strip().startswith("|")]
    cells = [[c.strip() for c in re.split(r"(?<!\\)\|", r.strip("|"))] for r in rows]
    return (cells[0] if cells else []), [c for c in cells[1:] if not all(re.fullmatch(r":?-+:?", x) for x in c)]


def read_sprint(vault, runtime, today):
    """The active sprint note under <vault>/sprints/ (front matter type sprint, status active; the latest date wins),
    its goals and committed items, the working day it is on, and on a Friday the week's yesterday files."""
    d = os.path.join(vault or "", "sprints")
    notes = []
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if f.endswith(".md"):
            text = open(os.path.join(d, f), encoding="utf-8").read()
            fm = front_matter(text)
            if fm.get("type") == "sprint" and fm.get("status") == "active":
                notes.append((str(fm.get("date") or ""), f, fm, text))
    if not notes:
        return {"active": None}
    _, f, fm, text = max(notes)
    start = datetime.date.fromisoformat(str(fm.get("start") or fm.get("date")))
    end = datetime.date.fromisoformat(str(fm["end"])) if fm.get("end") else None
    items = []
    for section, heading in (("goal", "Sprint goals"), ("committed", "Committed")):
        head, rows = table_rows(text, heading)
        own = [i for i, h in enumerate(head) if "ticket" in h.lower()]     # a ticket column names the item's own keys;
        for c in rows:                                                     # a status column may cite others
            if len(c) < 3:
                continue
            middle = " ".join(c[i] for i in own if i < len(c)) if own else " ".join(c[1:-1])
            items.append({"section": section, "id": plain(c[0]), "item": plain(c[1]), "keys": keys_in(middle), "done_when": plain(c[-1])})
    monday = today - datetime.timedelta(days=today.weekday())
    week = [os.path.join(runtime or "", "runner", f"{(monday + datetime.timedelta(days=i)).isoformat()}-yesterday.json") for i in range(5)]
    return {"active": {"path": os.path.join(d, f), "title": fm.get("title"), "start": start.isoformat(), "end": end and end.isoformat(),
                       "day": min(working_days(start, today), working_days(start, end)) if end else working_days(start, today),
                       "days": end and working_days(start, end), "days_left": end and max(working_days(today + datetime.timedelta(days=1), end), 0),
                       "items": items},
            "friday": today.weekday() == 4,
            "week_yesterday_files": [p for p in week if os.path.isfile(p)]}


def cmd_sprint(args):
    site = json.load(open(SITE))
    today = datetime.date.fromisoformat(args.date) if args.date else datetime.date.today()
    out = read_sprint(site.get("vault"), site.get("runtime"), today)
    if args.json:
        print(json.dumps(out, ensure_ascii=False)); return
    s = out["active"]
    if not s:
        print("no active sprint"); return
    print(f"# {s['title']} · day {s['day']} of {s['days'] or '?'} · ends {s['end'] or '—'}")
    for i in s["items"]:
        print(f"  {i['section']:<9} {i['id']:<3} {', '.join(i['keys']) or '—':<18} {i['item'][:70]}")
        print(f"            done when: {i['done_when'][:110]}")
    if out["friday"]:
        print(f"  this week's yesterday files: {len(out['week_yesterday_files'])}")


def main():
    ap = argparse.ArgumentParser(
        description="Morning brief, Jira lanes: the facts computed, read-only. "
                    f"Lanes: {', '.join(LANES)}. Flags: cadence RED > {RED_H}h · YELLOW > {YELLOW_H}h since update; "
                    f"triage OVERDUE > {OVERDUE_H}h since created; zombies = In Progress untouched > 14d.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog="Lanes (project MH)" + __doc__.split("Lanes (project MH)")[1].split("Output:")[0])
    ap.add_argument("--env-file", help="file with JIRA_BASE_URL/EMAIL/TOKEN, passed to jira.py")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("lanes", help="run the Jira lanes and compute the flags")
    p.add_argument("--lane", choices=LANES, help="one lane only (default: all)")
    p.add_argument("--limit", type=int, default=300, help="max rows per query (default 300)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_lanes)
    p = sub.add_parser("yesterday", help="what changed in the window, joined into cases by ticket key: Jira moves, "
                                         "commits, Slack messages; untracked commits; unticketed threads; ela's own work")
    p.add_argument("--hours", type=int, default=24, help="window length (default 24; the runner passes 72 on Mondays)")
    p.add_argument("--top", type=int, default=15, help="rows per section in the text form (default 15)")
    p.add_argument("--fetch", action="store_true", help="fetch every checkout under the code root first (remote refs only)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_yesterday)
    p = sub.add_parser("changes", help="the day's real changes for the Changes page: lane moves, builds and the commits they "
                                       "carry, release and QA mail, the release thread, commits per repo and ticket, the owner's "
                                       "own day, the team report; every source not read named in errors")
    p.add_argument("--date", help="the page's date, today only (default today); names the versions snapshot")
    p.add_argument("--hours", type=int, default=24, help="window length (default 24; 72 on Mondays)")
    p.add_argument("--fetch", action="store_true", help="fetch every checkout under the code root first (remote refs only)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_changes)
    p = sub.add_parser("matrix", help="which version runs on which lane this morning: components by prod / daily / QA, a move "
                                      "since yesterday, QA's mark on the exact version, a pin's mark; markdown, or --json")
    p.add_argument("--candidate", help="a JSON file {label, versions: {service: version}}: the next train as a fourth column")
    p.add_argument("--promote-report", help="the promotion report JSON (ela promote report --out): its stop and high count, when under a day old")
    p.add_argument("--json", action="store_true")
    p.add_argument("--page", action="store_true", help="write the lanes page (<reports>/lanes/lanes.md, the vault's lanes.md): this table, "
                                                      "what each lane carries that the next does not, and 14 days of moves; minutes, it reads two promotions")
    p.set_defaults(func=cmd_matrix)
    p = sub.add_parser("page-check", help="every apply N on a brief page has its action in the actions file and its box, and the page passes `ela review lint`; exit 1 naming any failure")
    p.add_argument("page"); p.add_argument("--actions", help="<reports>/runner/<date>-actions.json")
    p.add_argument("--strict", action="store_true", help="a lint failure fails the page too (default: printed as `lint:` lines, exit unchanged)")
    p.set_defaults(func=cmd_page_check)
    p = sub.add_parser("day", help="the owner's day from <elak>/blueprint/meetings.yaml: working day, hours, DM window, QA deploy hour, "
                                   "and the meetings that day with their brief section headings")
    p.add_argument("--date", help="YYYY-MM-DD (default today)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_day)
    p = sub.add_parser("sprint", help="the active sprint note in the vault: goals and committed items with their keys and "
                                      "'done when', the working day it is on; on a Friday the week's yesterday files")
    p.add_argument("--date", help="read as of YYYY-MM-DD (default today)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_sprint)
    args = ap.parse_args()
    if not args.cmd:
        ap.print_usage(sys.stderr)
        sys.exit(EX_USAGE)
    args.func(args)


if __name__ == "__main__":
    main()
