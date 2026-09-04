#!/usr/bin/env python3
"""team — the MediaHub roster, first-hand: who a name, email, Slack id or Jira account is.

L1 capability, stdlib only. Source: `<records>/knowledge/products/mediahub/team/roster.yaml` (elak at the
office; the published copy on a remote site — same path). Nothing here guesses: a query that matches no
roster entry returns exit 3 and says so, and `check` re-reads Slack to confirm the roster is still true.

  team.py list [--area X] [--json]        every person: name · role · area · email · slack · jira
  team.py who <query> [--json]            one person by name fragment, email, Slack id or Jira accountId — exit 3 when unknown
  team.py emails [--json]                 the known emails, one per line (what a caller may look up)
  team.py check [--json]                  read Slack users.list and report any roster email/id/name that no longer matches

Exit codes: 0 ok · 2 usage · 3 not in the roster · 4 auth · 5 remote error.
"""
import argparse, json, os, re, sys

EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE = 2, 3, 4, 5
SITE = os.path.expanduser("~/.claude/ela/site.json")
ROSTER_REL = os.path.join("knowledge", "products", "mediahub", "team", "roster.yaml")
FIELDS = ("name", "role", "area", "layer", "reports_to", "email", "slack", "jira", "jira_name", "external")


def site():
    try:
        return json.load(open(SITE))
    except Exception:
        print("no ~/.claude/ela/site.json — run /ela:setup", file=sys.stderr); sys.exit(EX_USAGE)


def roster_path():
    rec = site().get("records")
    if not rec:
        print("site.json needs `records`", file=sys.stderr); sys.exit(EX_USAGE)
    return os.path.join(rec, ROSTER_REL)


def _scalar(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        inner = v[1:-1]
        return inner.replace("''", "'") if v[0] == "'" else inner.replace('\\"', '"')
    if v in ("true", "false"):
        return v == "true"
    return v


def read_roster(path=None):
    """The subset of YAML roster.yaml uses: top-level scalars, then `people:` as a list of flat maps."""
    path = path or roster_path()
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError as e:
        print(f"cannot read {path}: {e}", file=sys.stderr); sys.exit(EX_USAGE)
    header, people, cur, in_people = {}, [], None, False
    for ln in lines:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        if not ln.startswith(" "):
            in_people = ln.startswith("people:")
            if not in_people and ":" in ln:
                k, v = ln.split(":", 1); header[k.strip()] = _scalar(v)
            continue
        if not in_people:
            continue
        m = re.match(r"^\s*-\s+(\w+):\s*(.*)$", ln)
        if m:
            cur = {f: "" for f in FIELDS}; cur["external"] = False; people.append(cur)
            cur[m.group(1)] = _scalar(m.group(2)); continue
        m = re.match(r"^\s+(\w+):\s*(.*)$", ln)
        if m and cur is not None:
            cur[m.group(1)] = _scalar(m.group(2))
    return header, people


def _norm(s):
    return re.sub(r"[^a-z0-9@.]", "", (s or "").lower())


def find(people, q):
    """Exact on email / slack id / jira id first, then name (whole, then fragment, then squashed)."""
    ql, qn = q.strip().lower(), _norm(q)
    if not ql:
        return []
    for key in ("email", "slack", "jira"):
        hits = [p for p in people if p.get(key) and p[key].lower() == ql]
        if hits:
            return hits
    hits = [p for p in people if p["name"].lower() == ql or (p.get("jira_name") or "").lower() == ql]
    if hits:
        return hits
    # first names are the aliases people use (wilson, kris, robin, bom …); a first-name match outranks a substring
    hits = [p for p in people if p["name"].lower().split()[0] == ql]
    if hits:
        return hits
    hits = [p for p in people if ql in p["name"].lower() or ql in (p.get("jira_name") or "").lower()]
    if hits:
        return hits
    return [p for p in people if qn and (qn in _norm(p["name"]) or qn == _norm(p["email"].split("@")[0]))]


def fmt(p):
    ext = "  (external)" if p.get("external") else ""
    return f"{p['name']:<14} {p['role']:<28} {p['area']:<10} {p['email']:<30} {p['slack']:<12} {p['jira'] or '-'}{ext}"


def cmd_list(a):
    header, people = read_roster()
    if a.area:
        people = [p for p in people if p["area"] == a.area]
    if a.json:
        print(json.dumps({"verified": header.get("verified"), "count": len(people), "people": people}, ensure_ascii=False)); return
    print(f"roster verified {header.get('verified')} · {len(people)} people")
    for p in people:
        print(fmt(p))


def cmd_who(a):
    _, people = read_roster()
    hits = find(people, a.query)
    if not hits:
        if a.json:
            print(json.dumps({"query": a.query, "found": False, "error": "not in the roster"}))
        else:
            print(f"{a.query}: not in the roster — look them up first-hand (ela slack users '{a.query}') and add them; never compose an address", file=sys.stderr)
        sys.exit(EX_NOTFOUND)
    if a.json:
        print(json.dumps({"query": a.query, "found": True, "count": len(hits), "people": hits}, ensure_ascii=False)); return
    for p in hits:
        print(fmt(p))
        if p.get("layer"):
            print(f"    layer: {p['layer']}")
        if p.get("reports_to"):
            print(f"    reports to: {p['reports_to']}")
        if p.get("jira_name"):
            print(f"    jira displayName: {p['jira_name']}")


def cmd_emails(a):
    _, people = read_roster()
    emails = sorted(p["email"].lower() for p in people if p.get("email"))
    print(json.dumps({"count": len(emails), "emails": emails}) if a.json else "\n".join(emails))


def cmd_check(a):
    """Re-read Slack and confirm every roster line: same id for the email, same email for the id, a live account."""
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(here, "..", "slack"))
    import slack as sl  # noqa: E402 — the slack capability, same plugin
    _, people = read_roster()
    tok = sl.token(a.env_file)
    users = {u["id"]: u for u in sl.list_users(tok)}
    by_email = {(u["email"] or "").lower(): u for u in users.values()}
    problems, ok = [], 0
    for p in people:
        u = users.get(p["slack"])
        if not u:
            problems.append({"name": p["name"], "problem": f"slack id {p['slack']} not among live members"}); continue
        if (u["email"] or "").lower() != p["email"].lower():
            problems.append({"name": p["name"], "problem": f"slack {p['slack']} now carries email {u['email']}, roster says {p['email']}"}); continue
        if by_email.get(p["email"].lower(), {}).get("id") != p["slack"]:
            problems.append({"name": p["name"], "problem": f"email {p['email']} resolves to another id"}); continue
        if _norm(u["name"]) != _norm(p["name"]) and _norm(p["name"]) not in _norm(u["name"]):
            problems.append({"name": p["name"], "problem": f"Slack display name is now '{u['name']}'", "severity": "note"})
        ok += 1
    if a.json:
        print(json.dumps({"checked": len(people), "ok": ok, "problems": problems}, ensure_ascii=False))
    else:
        print(f"checked {len(people)} people against Slack: {ok} match")
        for pr in problems:
            print(f"  {pr['name']}: {pr['problem']}")
    sys.exit(0 if not [p for p in problems if p.get("severity") != "note"] else EX_NOTFOUND)


def main():
    ap = argparse.ArgumentParser(description="The MediaHub roster, first-hand.")
    ap.add_argument("--env-file", help="credential file (only `check` needs SLACK_BOT_TOKEN)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="everyone"); p.add_argument("--area"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("who", help="one person by name, email, Slack id or Jira accountId"); p.add_argument("query"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("emails", help="the known emails"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("check", help="confirm the roster against Slack, read-only"); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    {"list": cmd_list, "who": cmd_who, "emails": cmd_emails, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    main()
