#!/usr/bin/env python3
"""team — the MediaHub roster, first-hand: who a name, email, Slack id or Jira account is.

L1 capability, stdlib only. Source: `<records>/knowledge/people/` — `people.yaml` (identity only) joined to `responsibilities.yaml`
(what each person is responsible for; a person holds several) by email. Nothing here guesses: a query that matches no
roster entry returns exit 3 and says so, and `check` re-reads Slack to confirm the roster is still true.

  team.py people [--area X] [--scope core|related] [--json]   every person: name · scope · areas · email · slack · jira
  team.py areas [--json]                  every area, and who to ask first about it
  team.py who <query> [--json]            one person by name fragment, email, Slack id or Jira accountId — exit 3 when unknown
  team.py emails [--json]                 the known emails, one per line (what a caller may look up)
  team.py check [--json]                  read Slack users.list and report any roster email/id/name that no longer matches

Exit codes: 0 ok · 2 usage · 3 not in the roster · 4 auth · 5 remote error.
"""
import argparse, json, os, re, sys

EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE = 2, 3, 4, 5
SITE = os.path.expanduser("~/.claude/ela/site.json")
PEOPLE_REL = os.path.join("knowledge", "people", "people.yaml")
RESP_REL = os.path.join("knowledge", "people", "responsibilities.yaml")
PERSON_FIELDS = ("email", "name", "slack", "jira", "jira_name", "review_means")
RESP_FIELDS = ("person", "scope", "area", "owns", "what", "first_contact", "routable", "origin", "source")
SCOPES = ("core", "related")          # nearest first; a person's membership is the nearest scope they hold


def site():
    try:
        return json.load(open(SITE))
    except Exception:
        print("no ~/.claude/ela/site.json — run /ela:setup", file=sys.stderr); sys.exit(EX_USAGE)


def records():
    rec = site().get("records")
    if not rec:
        print("site.json needs `records`", file=sys.stderr); sys.exit(EX_USAGE)
    return rec


def _scalar(v):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        return [_scalar(x) for x in v[1:-1].split(",") if x.strip()]
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        inner = v[1:-1]
        return inner.replace("''", "'") if v[0] == "'" else inner.replace('\\"', '"')
    if v in ("true", "false"):
        return v == "true"
    return v


def _read_table(path, key, fields):
    """The YAML subset both files use: top-level scalars, then `<key>:` as a list of flat maps."""
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError as e:
        print(f"cannot read {path}: {e}", file=sys.stderr); sys.exit(EX_USAGE)
    header, rows, cur, inside = {}, [], None, False
    for ln in lines:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        if not ln.startswith(" "):
            inside = ln.startswith(key + ":")
            if not inside and ":" in ln:
                k, v = ln.split(":", 1); header[k.strip()] = _scalar(v)
            continue
        if not inside:
            continue
        m = re.match(r"^\s*-\s+(\w+):\s*(.*)$", ln)
        if m:
            cur = {f: "" for f in fields}; rows.append(cur)
            cur[m.group(1)] = _scalar(m.group(2)); continue
        m = re.match(r"^\s+(\w+):\s*(.*)$", ln)
        if m and cur is not None:
            cur[m.group(1)] = _scalar(m.group(2))
    return header, rows


def read_roster(rec=None):
    """people.yaml joined to responsibilities.yaml, by email.

    A person carries identity only; scope, area and routability live on each responsibility, so one person
    holds several. The derived fields below are computed here so no caller re-implements the join:
      responsibilities · scope (nearest held) · area (the first_contact one, else the first) · areas · external
    Nothing derived is a rank: `first_contact` is per person-and-area and is not comparable across areas.
    """
    rec = rec or records()
    header, people = _read_table(os.path.join(rec, PEOPLE_REL), "people", PERSON_FIELDS)
    rheader, resp = _read_table(os.path.join(rec, RESP_REL), "responsibilities", RESP_FIELDS)
    by = {}
    for r in resp:
        if not isinstance(r.get("owns"), list):
            r["owns"] = [r["owns"]] if r.get("owns") else []
        by.setdefault(r.get("person") or "", []).append(r)
    orphans = sorted(set(by) - {p["email"] for p in people})
    for p in people:
        rs = by.get(p["email"], [])
        p["responsibilities"] = rs
        p["scope"] = min((r["scope"] for r in rs), key=lambda s: SCOPES.index(s) if s in SCOPES else 9) if rs else ""
        p["areas"] = list(dict.fromkeys(r["area"] for r in rs if r.get("area")))
        first = next((r for r in rs if r.get("first_contact") is True), None)
        p["area"] = (first or (rs[0] if rs else {})).get("area", "")
        p["layer"] = (first or (rs[0] if rs else {})).get("what", "")
        p["external"] = p["scope"] != "core"
    header["responsibilities_verified"] = rheader.get("verified", "")
    header["orphans"] = orphans
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


COLUMNS = ("name", "scope", "area", "email", "slack", "jira")
_WIDTHS = (18, 8, 22, 30, 12)


def head():
    """Column names above the rows — a row is six unlabelled fields otherwise."""
    w, c = _WIDTHS, [x.upper() for x in COLUMNS]
    return f"{c[0]:<{w[0]}} {c[1]:<{w[1]}} {c[2]:<{w[2]}} {c[3]:<{w[3]}} {c[4]:<{w[4]}} {c[5]}"


def fmt(p):
    w = _WIDTHS
    return (f"{p['name']:<{w[0]}} {p['scope']:<{w[1]}} {','.join(p['areas']):<{w[2]}} "
            f"{p['email']:<{w[3]}} {p['slack']:<{w[4]}} {p['jira'] or '-'}")


def cmd_people(a):
    header, people = read_roster()
    if a.area:
        people = [p for p in people if a.area in p["areas"]]
    if a.scope:
        people = [p for p in people if p["scope"] == a.scope]
    if a.json:
        print(json.dumps({"verified": header.get("verified"), "count": len(people), "people": people}, ensure_ascii=False)); return
    n = sum(len(p["responsibilities"]) for p in people)
    print(f"verified {header.get('verified')} · {len(people)} people · {n} responsibilities")
    print(head())
    for p in people:
        print(fmt(p))


def _show(p):
    """One person: identity, then every responsibility — the responsibilities are the substance."""
    print(fmt(p))
    if p.get("jira_name"):
        print(f"    jira displayName: {p['jira_name']}")
    if p.get("review_means"):
        print(f"    a Review ticket here reads as: {p['review_means']}")
    for r in p["responsibilities"]:
        mark = "*" if r.get("first_contact") is True else " "
        print(f"  {mark} [{r['scope']}/{r['area']}] {r['what']}")
        if r["owns"]:
            print(f"      owns: {', '.join(r['owns'])}")
        print(f"      routable: {str(r.get('routable')).lower()} · {r['origin']} · {r['source']}")
    if any(r.get("first_contact") is True for r in p["responsibilities"]):
        print("  * = ask this person first about that area when the specific owner is unknown")


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
    print(head())
    for p in hits:
        _show(p)


def cmd_areas(a):
    """Every area and who to ask first about it — the de-facto lead, which TVU has no title for."""
    _, people = read_roster()
    areas = {}
    for p in people:
        for r in p["responsibilities"]:
            e = areas.setdefault(r["area"], {"scope": r["scope"], "first": [], "people": []})
            e["people"].append(p["name"])
            if r.get("first_contact") is True:
                e["first"].append(p["name"])
    if a.json:
        print(json.dumps({"count": len(areas), "areas": areas}, ensure_ascii=False)); return
    print(f"{len(areas)} areas")
    print(f"{'AREA':<16} {'SCOPE':<8} {'ASK FIRST':<28} PEOPLE")
    for name in sorted(areas, key=lambda k: (areas[k]["scope"], k)):
        e = areas[name]
        print(f"{name:<16} {e['scope']:<8} {(', '.join(e['first']) or '—'):<28} {len(e['people'])}")


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
    p = sub.add_parser("people", help="everyone"); p.add_argument("--area"); p.add_argument("--scope", choices=SCOPES); p.add_argument("--json", action="store_true")
    p = sub.add_parser("areas", help="every area and who to ask first about it"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("who", help="one person by name, email, Slack id or Jira accountId"); p.add_argument("query"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("emails", help="the known emails"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("check", help="confirm the roster against Slack, read-only"); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    {"people": cmd_people, "areas": cmd_areas, "who": cmd_who, "emails": cmd_emails, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    main()
