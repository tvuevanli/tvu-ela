#!/usr/bin/env python3
"""Morning brief, Jira lanes — the facts the brief ranks, computed here instead of by a session. Stdlib only.

L1: deterministic, read-only, no LLM. Every Jira read goes through the jira capability as a subprocess
(`jira/jira.py jql … --json`), which owns auth and paging; this script only composes the JQL and does the
arithmetic on the timestamps. Judgment — clustering incidents, who spoke last, a backlog verdict, the rank
across lanes — stays in the SKILL.md.

Usage:
    brief.py [--env-file F] lanes [--lane cadence|triage|breakdown|incidents|backlog|yours] [--json] [--limit 300]

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

Output: --json → {"generated", "lanes": {<lane>: {"rows", "count", …}}, "errors": [{lane, query, exit, stderr}]}.
A lane that could not be read is in `errors`, never an empty lane. No writes anywhere.

Exit codes: 0 ok · 2 usage · 5 a lane could not be read (the rest is still printed).
"""
import argparse
import datetime
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
LANES = ("cadence", "triage", "breakdown", "incidents", "backlog", "yours")

# JQL as SKILL.md §1 states it; `project = MH AND ` is prepended to each.
Q = {
    "cadence": 'status = "In Progress" AND updated <= -24h AND updated >= -14d ORDER BY updated ASC',
    "zombies": 'status = "In Progress" AND updated < -14d',
    "blocked": "status = Blocked ORDER BY updated ASC",
    "yours": ('assignee = currentUser() AND ((status = "In Progress" AND updated <= -24h AND updated >= -14d)'
              " OR status = Blocked)"),
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


def split_yours(env, limit, cadence):
    mine = {r["key"] for r in jql(env, Q["yours"], limit)}
    rows = [r for r in cadence["rows"] + cadence["blocked"] if r["key"] in mine]
    cadence["rows"] = [r for r in cadence["rows"] if r["key"] not in mine]
    cadence["blocked"] = [r for r in cadence["blocked"] if r["key"] not in mine]
    cadence["count"], cadence["blocked_count"] = len(cadence["rows"]), len(cadence["blocked"])
    cadence["red"] = sum(1 for r in cadence["rows"] if r["flag"] == "RED")
    cadence["yellow"] = sum(1 for r in cadence["rows"] if r["flag"] == "YELLOW")
    return {"rows": rows, "count": len(rows)}


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
    for r in lane["rows"] + lane.get("blocked", []):
        flag = r.get("flag") or ""
        if name == "triage" and not r.get("prefix_ok"):
            flag = (flag + " NOPREFIX").strip()
        print(f"  {r['key']:<10} {flag:<16} {age_of(r):>8}  {(r.get('assignee') or '—')[:18]:<18} "
              f"{(r.get('summary') or '')[:60]}")
    if name == "cadence":
        z = lane["zombies"]
        print(f"  zombies {z['count']}: " + ", ".join(f"{o['assignee']} ×{o['count']}" for o in z["owners"]))
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
    fns = {"triage": lane_triage, "breakdown": lane_breakdown, "incidents": lane_incidents, "backlog": lane_backlog}
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
    args = ap.parse_args()
    if not args.cmd:
        ap.print_usage(sys.stderr)
        sys.exit(EX_USAGE)
    args.func(args)


if __name__ == "__main__":
    main()
