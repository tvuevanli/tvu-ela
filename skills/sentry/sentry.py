#!/usr/bin/env python3
"""Sentry capability. L1: subcommands, --json, meaningful exit codes, stdlib only. Read-only —
this script has no write path and none is to be added: resolving or ignoring an issue is the
owning team's call, made in their own tool.

  projects [match]                       the org's projects: slug, platform, and whether it is silent
  issues   [project] [--query Q] [--since 24h] [--limit N]   the issue table, worst first
  issue    <id>                          one issue in full: counts, first/last seen, and the latest
                                         event's exception, stack and tags
  events   <id> [--limit N]              recent events of one issue — when it happens, on which box

A crash is a class of fact ela otherwise cannot see. MH-3571 states the shape: a module crashes
leaving a minidump, neither recovers nor reports it, and none of the three control planes (J2N,
MediaHub, Observer) shows anything wrong. Sentry is where that crash already is. The alert mails Evan
gets are one event each; this reads the issue — how often, since when, on which boxes, still open.

Credentials, from $SENTRY_URL / $SENTRY_TOKEN → --env-file → $SENTRY_ENV_FILE → $ELA_ENV_FILE:
  SENTRY_URL    the deployment's base url          SENTRY_TOKEN  an auth token with project:read
  SENTRY_ORG    the organisation slug (default: read from the url path when it names one)
No address is written here: the host lives in ela's site config, never in a tracked file.

Exit codes: 0 ok · 2 usage · 3 not found · 4 auth or no credential · 5 remote error.
"""
import argparse, json, os, re, signal, sys, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE = 2, 3, 4, 5
LEVELS = {"fatal": 0, "error": 1, "warning": 2, "info": 3, "debug": 4}


def env_value(key, env_file=None):
    v = os.environ.get(key)
    if v:
        return v
    for path in filter(None, [env_file, os.environ.get("SENTRY_ENV_FILE"), os.environ.get("ELA_ENV_FILE")]):
        try:
            for line in open(path):
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return None


def creds(env_file):
    url, tok = env_value("SENTRY_URL", env_file), env_value("SENTRY_TOKEN", env_file)
    if not url or not tok:
        missing = " and ".join(x for x in ["SENTRY_URL" if not url else "", "SENTRY_TOKEN" if not tok else ""] if x)
        print(f"no {missing} (env, $SENTRY_ENV_FILE, or --env-file).\n"
              f"  A token is made in Sentry under the account's own API keys, and needs project:read\n"
              f"  (org:read as well, for `projects`). Put it in ela's env file; run /ela:setup to check.",
              file=sys.stderr)
        sys.exit(EX_AUTH)
    org = env_value("SENTRY_ORG", env_file) or "sentry"
    return url.rstrip("/"), tok, org


def call(base, tok, path, params=None, soft=False):
    url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            print(f"sentry {path}: HTTP {e.code} — the token is rejected or lacks the scope "
                  f"(project:read, org:read for projects)", file=sys.stderr)
            sys.exit(EX_AUTH)
        if e.code == 404:
            if soft:
                return None
            print(f"sentry {path}: not found", file=sys.stderr); sys.exit(EX_NOTFOUND)
        print(f"sentry {path}: HTTP {e.code} {e.read()[:300].decode('utf-8', 'replace')}", file=sys.stderr)
        sys.exit(EX_REMOTE)
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        print(f"sentry {path}: {e!r}", file=sys.stderr); sys.exit(EX_REMOTE)


def since_period(spec):
    """Sentry takes a statsPeriod, not a timestamp: 24h · 14d are its own vocabulary."""
    if not spec:
        return "24h"
    if re.fullmatch(r"\d+[hd]", spec):
        return spec
    print("--since takes Sentry's own periods: 24h, 48h, 7d, 14d (90d is the usual maximum)", file=sys.stderr)
    sys.exit(EX_USAGE)


def iso(s):
    return (s or "")[:19].replace("T", " ")


def _age(s):
    try:
        d = datetime.now(timezone.utc) - datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    if d < timedelta(hours=1):
        return f"{int(d.total_seconds() // 60)}m"
    if d < timedelta(days=1):
        return f"{int(d.total_seconds() // 3600)}h"
    return f"{d.days}d"


# ── subcommands ──────────────────────────────────────────────────────────────

def cmd_projects(a):
    base, tok, org = creds(a.env_file)
    rows = call(base, tok, f"/api/0/organizations/{org}/projects/") or []
    out = [{"slug": p.get("slug"), "name": p.get("name"), "platform": p.get("platform") or "",
            "last_event": p.get("firstEvent") and "" or "", "id": p.get("id")} for p in rows]
    if a.match:
        m = a.match.lower()
        out = [p for p in out if m in (p["slug"] or "").lower() or m in (p["name"] or "").lower()]
    out.sort(key=lambda p: (p["slug"] or "").lower())
    if a.json:
        print(json.dumps({"org": org, "count": len(out), "projects": out}, ensure_ascii=False)); return
    for p in out:
        print(f"{(p['slug'] or ''):<28} {(p['platform'] or '-'):<14} {p['name'] or ''}")
    print(f"\n# {len(out)} project(s) in org {org}")


def issue_rows(base, tok, org, project, query, period, limit):
    rows = call(base, tok, f"/api/0/projects/{org}/{project}/issues/",
                {"query": query, "statsPeriod": period, "limit": limit}, soft=True)
    if rows is None:
        return None
    return [{"id": i.get("id"), "short_id": i.get("shortId") or "", "title": i.get("title") or "",
             "culprit": i.get("culprit") or "", "level": i.get("level") or "", "status": i.get("status") or "",
             "count": int(i.get("count") or 0), "users": int(i.get("userCount") or 0),
             "first_seen": i.get("firstSeen") or "", "last_seen": i.get("lastSeen") or "",
             "project": (i.get("project") or {}).get("slug") or project,
             "type": (i.get("metadata") or {}).get("type") or "", "permalink": i.get("permalink") or ""}
            for i in rows]


def cmd_issues(a):
    base, tok, org = creds(a.env_file)
    period, query = since_period(a.since), a.query or "is:unresolved"
    projects = [a.project] if a.project else [p.get("slug") for p in (call(base, tok, f"/api/0/organizations/{org}/projects/") or [])]
    out, unread = [], []
    for slug in filter(None, projects):
        rows = issue_rows(base, tok, org, slug, query, period, a.limit)
        if rows is None:
            unread.append(slug); continue
        out += rows
    # Worst first: a fatal that fires a thousand times outranks an error that fired twice, and
    # frequency is the only ranking Sentry itself is sure of.
    out.sort(key=lambda i: (LEVELS.get(i["level"], 9), -i["count"]))
    out = out[:a.limit]
    if a.json:
        print(json.dumps({"org": org, "query": query, "period": period, "count": len(out),
                          "unread_projects": unread, "issues": out}, ensure_ascii=False)); return
    for i in out:
        print(f"{i['id']:<9} {i['level']:<8} {i['count']:>7}× {i['users']:>4}u  last {_age(i['last_seen']):>4} ago  "
              f"{i['project']:<20} {i['title'][:80]}")
        if i["culprit"]:
            print(f"{'':<9} {i['culprit'][:110]}")
    print(f"\n# {len(out)} issue(s), {query!r} over {period}, worst first")
    for s in unread:
        print(f"# not read: project {s}", file=sys.stderr)


def latest_event(base, tok, issue_id):
    return call(base, tok, f"/api/0/issues/{issue_id}/events/latest/", soft=True) or {}


def exception_of(ev):
    """The exception entry of an event: type, value and the frames, innermost last as Sentry stores them."""
    for entry in ev.get("entries") or []:
        if entry.get("type") != "exception":
            continue
        vals = ((entry.get("data") or {}).get("values")) or []
        if not vals:
            continue
        v = vals[-1]
        st = (v.get("stacktrace") or {}).get("frames") or []
        return {"type": v.get("type") or "", "value": v.get("value") or "",
                "frames": [{"module": f.get("module") or f.get("filename") or "",
                            "function": f.get("function") or "", "line": f.get("lineNo")} for f in st]}
    return {}


def cmd_issue(a):
    base, tok, org = creds(a.env_file)
    i = call(base, tok, f"/api/0/issues/{a.issue_id}/")
    ev = latest_event(base, tok, a.issue_id)
    exc = exception_of(ev)
    tags = {t.get("key"): t.get("value") for t in (ev.get("tags") or [])}
    rec = {"id": i.get("id"), "short_id": i.get("shortId") or "", "title": i.get("title") or "",
           "culprit": i.get("culprit") or "", "level": i.get("level") or "", "status": i.get("status") or "",
           "count": int(i.get("count") or 0), "users": int(i.get("userCount") or 0),
           "first_seen": i.get("firstSeen") or "", "last_seen": i.get("lastSeen") or "",
           "project": (i.get("project") or {}).get("slug") or "", "permalink": i.get("permalink") or "",
           "latest_event": {"id": ev.get("id") or "", "at": ev.get("dateCreated") or "", "tags": tags,
                            "exception": exc}}
    if a.json:
        print(json.dumps(rec, ensure_ascii=False)); return
    print(f"# {rec['short_id'] or rec['id']}  [{rec['level']}]  {rec['status']}   project {rec['project']}")
    print(rec["title"])
    if rec["culprit"]:
        print(f"culprit  {rec['culprit']}")
    print(f"seen     {rec['count']}× ({rec['users']} user(s))   first {iso(rec['first_seen'])}   "
          f"last {iso(rec['last_seen'])} ({_age(rec['last_seen'])} ago)")
    if rec["permalink"]:
        print(f"link     {rec['permalink']}")
    if tags:
        print("\n--- tags of the latest event ---")
        for k in sorted(tags):
            print(f"  {k:<18} {tags[k]}")
    if exc:
        print(f"\n--- {exc['type']} ---")
        print(exc["value"])
        for f in exc["frames"][-a.frames:]:
            where = " ".join(x for x in (f["module"], f["function"]) if x)
            print(f"  {where}" + (f"  :{f['line']}" if f["line"] else ""))
        if len(exc["frames"]) > a.frames:
            print(f"  … {len(exc['frames']) - a.frames} more frame(s); --frames N for more")


def cmd_events(a):
    base, tok, org = creds(a.env_file)
    rows = call(base, tok, f"/api/0/issues/{a.issue_id}/events/", {"limit": a.limit}) or []
    out = []
    for e in rows[:a.limit]:
        tags = {t.get("key"): t.get("value") for t in (e.get("tags") or [])}
        out.append({"id": e.get("id") or "", "at": e.get("dateCreated") or "",
                    "server": tags.get("server_name") or "", "environment": tags.get("environment") or "",
                    "version": tags.get("Version") or tags.get("version") or "",
                    "peer": tags.get("PeerID") or "", "message": (e.get("message") or "")[:120]})
    if a.json:
        print(json.dumps({"issue": a.issue_id, "count": len(out), "events": out}, ensure_ascii=False)); return
    for e in out:
        print(f"{iso(e['at'])}  {e['server']:<14} {e['environment']:<12} v{e['version']:<8} {e['peer']:<18} {e['message']}")
    print(f"\n# {len(out)} event(s). The server and version columns are what say whether one box is "
          f"the whole issue.")


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description="Sentry capability: crashes and errors, read-only.")
    ap.add_argument("--env-file", help="file with SENTRY_URL, SENTRY_TOKEN, SENTRY_ORG")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("projects", help="the org's projects")
    p.add_argument("match", nargs="?"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("issues", help="the issue table, worst first")
    p.add_argument("project", nargs="?", help="a project slug; omitted = every project in the org")
    p.add_argument("--query", help="Sentry search, default is:unresolved")
    p.add_argument("--since", help="Sentry statsPeriod: 24h (default), 7d, 14d")
    p.add_argument("--limit", type=int, default=25); p.add_argument("--json", action="store_true")
    p = sub.add_parser("issue", help="one issue with its latest event's exception and tags")
    p.add_argument("issue_id"); p.add_argument("--frames", type=int, default=12)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("events", help="recent events of one issue — when, which box, which version")
    p.add_argument("issue_id"); p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    {"projects": cmd_projects, "issues": cmd_issues, "issue": cmd_issue, "events": cmd_events}[a.cmd](a)


if __name__ == "__main__":
    main()
