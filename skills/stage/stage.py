#!/usr/bin/env python3
"""The board against reality: where each ticket's fix actually is, and what the ticket still owes.

  queue <KEY>… [--jql Q] [--days N] [--json]
        one row per ticket (an Epic expands to its children): the stage its fix reached by ancestry — none · qa ·
        daily · prod — the fix's age, the ticket's status, assignee and implementer (the fix commits' authors),
        Fixed In declared and verified, QA's verdict; then the action the row owes, grouped so a batch of one
        shape is read once. Reads only: every write it names is a dry run for the owner to confirm.

Why: the owner carries every ticket on the MH board, across the hops a change makes (branch → QA lane → daily →
prod). A ticket says where its fix is only when someone moves it; the build does not. The board therefore drifts:
fixes long on prod sit in Backlog, fixes on a QA lane carry no Fixed In, QA is not told what reached daily. This
verb reads the fix's position from the builds (ela fixed-in, ancestry) and lists what each ticket owes, so the
owner confirms batches instead of finding them. Status rules follow elak knowledge/products/mediahub/jira/
status-spec.md: Review assigned to product is the sign-off gate, not a stale ticket; the implementer may differ from
the assignee, who is the person responsible — that difference is shown, never flagged.

Actions (the flag is the row's, the dry run is the owner's to confirm):
  close         fix on prod for --days or more, no QA refutation, ticket open → one jira close bundle
  reached-qa    fix on a QA lane, no Fixed In or status before Review → fixed-in --apply, transition Review, tell QA
  awaiting-qa   fix on daily or prod, Review, QA has not spoken → ask QA (comment, dry run)
  awaiting-product  Review, assignee in the product area → nothing; the gate is theirs
  declared-only Review or Done-bound with a developer's declared build, no lane's build carries it → ask for the sha
  no-fix        In Progress or Review, no commit names the key → ask the assignee where the change is
  epic          an Epic: its children's actions counted; it owes a close only when every child is closed or closable
  (none)        Backlog with no fix: the board's queue, nothing owed yet

Exit: 0 ok · 2 usage · 5 fixed-in failed.
"""
import argparse, datetime, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SKILLS, "promote"))
import promote as P  # noqa: E402 — roster, person_area, l1

EX_USAGE, EX_REMOTE = 2, 5
STAGE_ORDER = {"none": 0, "qa": 1, "daily": 2, "prod": 3}
OPEN_BEFORE_REVIEW = {"Backlog", "In Progress", "Blocked", "On Hold", "Reopened"}
TERMINAL = {"Done", "Cancelled", "Failed", "Closed Ambigous"}


def stage_of(lanes):
    """The furthest kind of lane whose build carries the fix: prod > daily > qa > none."""
    best = "none"
    for x in lanes or []:
        lane = (x.get("lane") or "")
        kind = "prod" if lane.startswith("prod") else "daily" if lane.startswith("daily") or lane == "stage" else "qa" if lane.startswith("qa") else None
        if kind and STAGE_ORDER[kind] > STAGE_ORDER[best]:
            best = kind
    return best


def fix_age_days(commits, today=None):
    """Days since the newest fix commit; None without commits."""
    dates = [c.get("date") for c in commits or [] if c.get("date")]
    if not dates:
        return None
    today = today or datetime.date.today()
    try:
        return (today - datetime.date.fromisoformat(max(dates))).days
    except ValueError:
        return None


def row_of(rec, roster, days, today=None):
    """One board row from a fixed-in record, with the action it owes."""
    lanes = rec.get("lanes") or []
    stage = stage_of(lanes)
    status = rec.get("status") or "?"
    ev = rec.get("evidence") or {}
    qa = (ev.get("verdict") or "") if isinstance(ev, dict) else ""
    declared = bool((rec.get("declared") or {}).get("declared"))
    verified = bool(rec.get("draft"))
    authors = sorted({c.get("author") for c in rec.get("commits") or [] if c.get("author")})
    assignee = rec.get("assignee")
    area = P.person_area(roster, assignee) if assignee else None
    age = fix_age_days(rec.get("commits"), today)
    row = {"key": rec.get("key"), "summary": rec.get("summary"), "type": rec.get("issuetype"), "parent": rec.get("parent"),
           "status": status, "assignee": assignee, "assignee_area": area, "implementers": authors,
           "stage": stage, "lanes": sorted({x.get("lane") for x in lanes if x.get("lane")}),
           "fix_age_days": age, "fixed_in": rec.get("current") or "", "declared": declared, "verified": verified,
           "qa": qa, "action": None, "why": None, "dry_run": None, "gaps": rec.get("gaps") or []}
    k = row["key"]
    if rec.get("exit"):
        row.update(action="unreadable", why="; ".join(row["gaps"])); return row
    if status in TERMINAL:
        row.update(action="done", why=f"{status}"); return row
    if status == "Review" and area == "product":
        row.update(action="awaiting-product", why="the product sign-off gate: Review assigned to product"); return row
    if stage == "prod" and (age is None or age >= days) and qa != "fail":
        row.update(action="close", why=f"fix on {', '.join(l for l in row['lanes'] if l.startswith('prod'))} for {age if age is not None else '?'} days, QA {qa or 'silent'}",
                   dry_run=f"ela jira close {k} --comment <where verified, build, commit>"); return row
    if stage == "qa" and (not row["fixed_in"] or status in OPEN_BEFORE_REVIEW):
        need = [] if row["fixed_in"] else ["fixed-in"]
        if status in OPEN_BEFORE_REVIEW:
            need.append("transition Review")
        row.update(action="reached-qa", why=f"fix on {', '.join(row['lanes'])}; {', '.join(need)} missing; QA not told",
                   dry_run=f"ela fixed-in {k}; ela jira transition {k} --path Review"); return row
    if stage in ("daily", "prod") and status == "Review" and not qa:
        row.update(action="awaiting-qa", why=f"fix on {', '.join(row['lanes'])}, QA has not spoken",
                   dry_run=f"ela jira comment {k} --mention <QA> '<build on daily; please verify>'"); return row
    if stage == "none" and declared and not verified:
        row.update(action="declared-only", why="a developer declared a build; no lane's build is shown to carry the fix",
                   dry_run=f"ela fixed-in declared {k}"); return row
    if stage == "none" and status in ("In Progress", "Review"):
        row.update(action="no-fix", why=f"{status} and no commit names {k}",
                   dry_run=f"ela jira comment {k} --mention <assignee> '<where is the change?>'"); return row
    row.update(action="none", why=f"{status}, fix {stage}"); return row


def expand_epics(env_file, keys):
    """Children of any Epic among the keys, so a feature is one queue."""
    if not keys:
        return keys
    ok, d, err = P.l1("jira", "jql", f"parent in ({', '.join(keys)}) ORDER BY created", "--limit", "300", env_file=env_file, timeout=120)
    if not ok:
        return keys
    kids = [i.get("key") for i in (d.get("issues") or []) if i.get("key")]
    return keys + [k for k in kids if k not in keys]


def fixedin(env_file, keys, jql):
    cmd = ["python3", os.path.join(SKILLS, "fixedin", "fixedin.py"), "--env-file", env_file or "", "draft", *keys, "--json"]
    if jql:
        cmd += ["--jql", jql]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    try:
        return json.loads(r.stdout).get("keys") or []
    except ValueError:
        print(f"fixed-in failed: {(r.stderr or r.stdout).strip()[-300:]}", file=sys.stderr); sys.exit(EX_REMOTE)


def roll_up_epics(rows):
    """An Epic has no fix of its own: its row carries its children's count by action, and owes a close when every child
    is terminal or a close candidate; otherwise it is the feature's queue head and owes nothing itself."""
    by_parent = {}
    for r in rows:
        if r.get("parent"):
            by_parent.setdefault(r["parent"], []).append(r)
    for r in rows:
        if r.get("type") != "Epic":
            continue
        kids = by_parent.get(r["key"], [])
        if not kids:
            r.update(action="epic", why="no child ticket read; pass the Epic alone to expand it", dry_run=None); continue
        counts = {}
        for k in kids:
            counts[k["action"]] = counts.get(k["action"], 0) + 1
        summary = ", ".join(f"{n} {act}" for act, n in sorted(counts.items(), key=lambda kv: -kv[1]))
        if all(k["action"] in ("done", "close") for k in kids):
            r.update(action="close", why=f"every child is terminal or a close candidate: {summary}",
                     dry_run=f"ela jira close {r['key']} --comment <children closed; feature on prod>")
        else:
            r.update(action="epic", why=f"children: {summary}", dry_run=None)
    return rows


ORDER = ["close", "reached-qa", "awaiting-qa", "declared-only", "no-fix", "awaiting-product", "epic", "none", "done", "unreadable"]


def print_queue(rows, days):
    by = {}
    for r in rows:
        by.setdefault(r["action"], []).append(r)
    print(f"# {len(rows)} ticket(s); fix age threshold for close: {days} days")
    for action in ORDER:
        rs = by.get(action)
        if not rs:
            continue
        print(f"\n## {action} ({len(rs)})")
        for r in rs:
            imp = ",".join(r["implementers"]) or "-"
            who = (r["assignee"] or "-") + (f" (impl {imp})" if imp != "-" and imp != r["assignee"] else "")
            print(f"  {r['key']:<8} {r['status']:<12} {r['stage']:<5} {str(r['fix_age_days'] if r['fix_age_days'] is not None else '-'):>4}d  {who:<34} {r['summary'] or ''}"[:160])
            print(f"           {r['why']}")
            if r["dry_run"]:
                print(f"           → {r['dry_run']}")


def cmd_queue(a):
    keys = [k for k in a.keys if re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", k)]
    if not keys and not a.jql:
        print("queue needs ticket keys or --jql", file=sys.stderr); sys.exit(EX_USAGE)
    keys = expand_epics(a.env_file, keys)
    recs = fixedin(a.env_file, keys, a.jql)
    roster = P.load_roster()
    rows = [row_of(r, roster, a.days) for r in recs]
    roll_up_epics(rows)
    rows.sort(key=lambda r: (ORDER.index(r["action"]) if r["action"] in ORDER else 99, -(r["fix_age_days"] or 0)))
    if a.json:
        print(json.dumps({"days": a.days, "rows": rows}, ensure_ascii=False))
    else:
        print_queue(rows, a.days)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("queue", help="the board rows and the action each owes")
    p.add_argument("keys", nargs="*"); p.add_argument("--jql"); p.add_argument("--days", type=int, default=30, help="fix on prod this long → close (default 30)")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    cmd_queue(a)


if __name__ == "__main__":
    main()
