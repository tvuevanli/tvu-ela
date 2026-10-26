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
LANES = ("intake", "cadence", "triage", "breakdown", "incidents", "backlog", "yours")

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
    fns = {"intake": lane_intake, "triage": lane_triage, "breakdown": lane_breakdown, "incidents": lane_incidents, "backlog": lane_backlog}
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


def cmd_yesterday(args):
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
           "ela": {"jobs": jobs, "writes": writes, "helm_autowrites": machine}, "stale_checkouts": stale, "errors": errors}
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
    args = ap.parse_args()
    if not args.cmd:
        ap.print_usage(sys.stderr)
        sys.exit(EX_USAGE)
    args.func(args)


if __name__ == "__main__":
    main()
