#!/usr/bin/env python3
"""Morning brief, Jira lanes — the facts the brief ranks, computed here instead of by a session. Stdlib only.

L1: deterministic, read-only, no LLM. Every Jira read goes through the jira capability as a subprocess
(`jira/jira.py jql … --json`), which owns auth and paging; this script only composes the JQL and does the
arithmetic on the timestamps. Judgment — clustering incidents, who spoke last, a backlog verdict, the rank
across lanes — stays in the SKILL.md.

Usage:
    brief.py [--env-file F] lanes [--lane cadence|triage|breakdown|incidents|backlog|yours] [--json] [--limit 300]
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
LANES = ("intake", "cadence", "triage", "breakdown", "incidents", "backlog", "yours", "waiting")

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
    """What the owner waits on (the F lane): his routed tickets and his unanswered asks in Jira, Slack and mail."""
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
    rows.sort(key=lambda r: -(r["working_days_silent"] or 0))
    return {"rows": rows, "count": len(rows), "due": sum(r["due"] for r in rows), "owner": me, "gaps": gaps}


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
    if name == "waiting":
        for r in lane["rows"]:
            print(f"  {r['kind']:<6} {'DUE' if r['due'] else '':<4} {r['working_days_silent']}/{r['threshold']}d  {str(r['who'] or '—')[:18]:<18} "
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
           "waiting": lane_waiting}
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
        print(json.dumps({"generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "lanes": lanes, "errors": errors},
                         ensure_ascii=False))
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
    releases, qa = [], []
    try:
        by_thread = {}
        for m in run_json(["python3", MAIL, *env, "search", f"{span} subject:Release", "--limit", "40", "--body", "--json"], timeout=300)["messages"]:
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
    pending = read_pending(site)
    cand = (pending or {}).get("candidate") or {}
    out["pending"] = pending
    out["findings"] = findings_of(out, rows, tested, env, errors, candidate=frozenset(cand.get("versions") or {})) + out.pop("findings_extra")
    for service, c in (cand.get("versions") or {}).items():
        if isinstance(c, dict) and c.get("awaiting"):
            out["findings"].append({"kind": "candidate_awaiting_owner", "lane": pending["to"], "service": service,
                                    "what": f"{cand.get('label')}: {LABEL.get(service, service)} awaits your choice — {c.get('why') or ''}".rstrip(" —"),
                                    "options": c.get("options") or [], "evidence": [pending.get("report") or ""], "at": pending.get("refreshed"),
                                    "rank": RANKS["candidate_awaiting_owner"]})
    return out


def pin_findings(named, pin):
    """The newest release-named bundle on prod against the owner's pin: newer, or no pin at all, is his decision; the
    option is the pin command as he would run it (ela ADR 0012)."""
    rel = [x for x in named if RELEASE_NAME(LINE).match(str(x.get("bundleName", "")))]
    newest = max(rel, key=lambda x: str(x.get("createTime") or ""), default=None)
    if not newest or (pin and str(pin.get("id")) == str(newest.get("bundleId"))):
        return []
    pinned = next((x for x in rel if pin and str(x.get("bundleId")) == str(pin.get("id"))), None)
    if pinned and str(pinned.get("createTime") or "") >= str(newest.get("createTime") or ""):
        return []
    name = newest["bundleName"]
    return [{"kind": "release_newer_than_pin", "lane": "prod", "service": None,
             "what": (f"{name} ({R.when(newest.get('createTime'))[:10]}) is newer than the official pin {pin.get('official')}" if pin
                      else f"no official bundle is pinned for {LINE}; the newest release is {name} ({R.when(newest.get('createTime'))[:10]})"),
             "options": [f'ela release pin {LINE} "{name}" --apply'], "evidence": [f"bundle {newest.get('bundleId')}"],
             "at": R.when(newest.get("createTime")), "rank": RANKS["candidate_awaiting_owner"]}]


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


def RELEASE_NAME(line):
    return re.compile(r"^MediaHub " + re.escape(line) + r"\.\d+\b")


def bundle_cell(b, how, newest_build, unconfirmed):
    """The bundle row's cell: name and date, "unconfirmed" for a prod bundle inferred from the list, "list stale" when the
    lane's newest build is younger than the bundle."""
    if not b:
        return {"text": "—"}
    made = R.when(b.get("createTime"))[:10]
    stale = made < (newest_build or "")[:10]
    return {"text": f"{b['bundleName']} ({made})" + (" unconfirmed" if unconfirmed else "") + (" (list stale)" if stale else ""),
            "name": b["bundleName"], "source": how, "stale": stale}


def cmd_matrix(args):
    site = json.load(open(SITE))
    env = ["--env-file", args.env_file] if args.env_file else []
    date = datetime.date.today().isoformat()
    runner = os.path.join(site.get("runtime") or os.path.join(site.get("projects", ""), ".ela"), "runner")
    errors = []
    today, before = snapshots(runner, date)
    if today is None:                                       # no `changes` run yet today: read the lanes now, not saved
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
    pins = {}
    try:
        r = subprocess.run(["python3", PROMOTE, *env, "--quiet", "constraints", "--json"], capture_output=True, text=True, timeout=300)
        for c in (json.loads(r.stdout) if r.returncode in (0, 3) else {}).get("active") or []:
            for p in c.get("pins") or []:
                pins[(p.get("service"), p.get("lane"))] = p.get("state")
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
                    b = max((x for x in named if RELEASE_NAME(LINE).match(str(x.get("bundleName", "")))), key=lambda x: str(x.get("createTime") or ""), default=None)
                    how = "by name"
            if b is None:
                got = run_json(["python3", RELEASE, *env, "bundles", cfg.get("bundle_line") or "", "--host", host, "--limit", "50", "--json"], timeout=120)["bundles"]
                pre = (cfg.get("bundle_line") or "") + toks.get(role, "")
                got = [x for x in got if str(x.get("bundleName", "")) == pre or str(x.get("bundleName", "")).startswith(pre + "-")]
                b, how = max(got, key=lambda x: str(x.get("createTime") or ""), default=None), "token"
            bundle[lane] = bundle_cell(b, how, newest, role == "prod" and how != "official")
        except (LaneError, subprocess.TimeoutExpired, ValueError) as e:
            bundle[lane] = {"text": "not read"}
            errors.append({"source": f"bundles {host}", "error": str(e)[:200]})
    prev = (before or {}).get("rows")
    table = [{"row": "media bundle", "cells": [bundle.get(l, {"text": "—"}) for l in lanes]}]
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
           "rows": table, "same": same, "gate": gate, "errors": errors}
    if args.json:
        print(json.dumps(out, ensure_ascii=False)); return
    print(render_matrix(out))
    for e in errors:
        print(f"not read: {e['source']}: {e['error']}", file=sys.stderr)


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


def working_days(a, b):
    """Weekdays from a to b, both included; 0 when b is before a."""
    n, d = 0, a
    while d <= b:
        n += d.weekday() < 5
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
    p.set_defaults(func=cmd_matrix)
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
