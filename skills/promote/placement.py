#!/usr/bin/env python3
"""Where each ticket of a promotion already is: new, already on the target lane, or partly new (which part).

  placement.py <report.json> [--json]      place every ticket of a saved promote report (offline)

Why: on 2026-11-09 the promotion listed tickets as new that prod-3 already ran (MH-3579 since UR Caller 2.1.59,
MH-3503 / MH-3582 / MH-3668 in MediaHub frontend 2.2.94–2.2.111, MH-3886's behaviour verified on prod), and did not
split a ticket with a part on prod-3 and a part new (MH-3800: its UR Caller and Unified Media frontend parts on
prod-3, its MediaHub frontend 2.2.117 part new).

Per ticket and per service part, two first-hand facts, never the ticket's status:
- **Fixed In** (`slug@version`, the Jira field): a part whose version is at or below the version the target lane
  runs is on the target; above it, new.
- **Code commits in the range** (`from` lane's build ⊄ `to` lane's build): a part with a code commit owned by the key
  (its scope `fix(KEY)`, or the only key of its subject) is new whatever Fixed In says. A commit scoped to another key,
  or naming the key only in its body (a nightly guard citing MH-3163), cites it: counted, never "new". Commits of kind docs / test / chore / style / ci never make a part new — a test or a
  doc that cites the key ships nothing the user sees ("this release adds docs only").
The ticket is `new` (every part new), `on-target` (every part already there) or `partly-new` (the parts listed).
- **QA's pass environment**, only when neither of the above places anything: the build QA passed the ticket on, at or
  below the target lane, puts it on the target (MH-3668: QA passed on MediaHub frontend 2.2.111; prod-3 runs a later build).
A part whose service the target lane does not report is `unknown`, never assumed.
"""
import argparse, json, os, re, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SKILLS, "release"))
NON_SHIPPING = ("docs", "test", "chore", "style", "ci")


def cmp(a, b):
    """-1/0/1 on (major, minor, patch, hotfix); None when either is unparsed."""
    if not a or not b:
        return None
    x, y = list(a[:4]) + [0] * (4 - len(a[:4])), list(b[:4]) + [0] * (4 - len(b[:4]))
    return (x > y) - (x < y)


def target_versions(lanes):
    out = {}
    for s in (lanes or {}).get("services") or []:
        to = s.get("to") or {}
        if to.get("parsed"):
            out[s["service"]] = {"parsed": to["parsed"], "version": to.get("version"), "lane": s.get("to_lane")}
    return out


def place(ticket, target, qa_env=None):
    """qa_env: {slug: version} of the build QA passed the ticket on (its environment block), used only when neither
    Fixed In nor an owned commit places a part."""
    parts = {}
    for e in ticket.get("fixed_in_entries") or []:
        if e.get("docker"):
            continue
        tv = target.get(e["slug"])
        c = cmp(e.get("parsed"), (tv or {}).get("parsed"))
        state = "unknown" if c is None else ("on-target" if c <= 0 else "new")
        parts[e["slug"]] = {"state": state, "fixed_in": e["version"], "target": (tv or {}).get("version"),
                            "why": "Fixed In vs the target lane" if c is not None else "the target lane does not report this service"}
    code, cites = {}, {}
    for cm in ticket.get("commits") or []:
        if cm.get("kind") in NON_SHIPPING:
            continue
        scope = re.match(r"^\w+\(([A-Z][A-Z0-9]{1,5}-\d+)\)", cm.get("subject") or "")
        if cm.get("only_in_body") or (scope and scope.group(1) != ticket["key"]):
            cites.setdefault(cm["service"], []).append(cm["sha"])      # another ticket's commit, or a follow-up citing it
        else:
            code.setdefault(cm["service"], []).append(cm["sha"])
    for svc, shas in code.items():
        p = parts.get(svc) or {"fixed_in": None, "target": (target.get(svc) or {}).get("version")}
        p.update({"state": "new", "commits": len(shas),
                  "why": "code commits in the range" + (" (Fixed In names an earlier build)" if p.get("state") == "on-target" else "")})
        parts[svc] = p
    if not parts and qa_env:
        import release as R  # noqa: E402
        for slug, ver in qa_env.items():
            tv = target.get(slug)
            c = cmp(R.parse_version(str(ver)), (tv or {}).get("parsed"))
            if c is not None:
                parts[slug] = {"state": "on-target" if c <= 0 else "new", "fixed_in": str(ver).split()[0], "target": tv.get("version"),
                               "why": "QA passed it on this build; no Fixed In, no owned commit"}
        if parts and all(p["state"] == "new" for p in parts.values()):
            parts = {}                                  # QA's build being ahead says nothing about where the fix landed
    refs_only = sorted({cm["service"] for cm in ticket.get("commits") or []} - set(code))
    for svc, shas in cites.items():
        if svc in parts:
            parts[svc]["cited_by_later_commits"] = len(shas)
    states = {p["state"] for p in parts.values()}
    if not parts:
        overall = "unknown"
    elif states == {"new"}:
        overall = "new"
    elif states <= {"on-target"}:
        overall = "on-target"
    elif "new" in states:
        overall = "partly-new"
    else:
        overall = "unknown"
    return {"key": ticket["key"], "placement": overall, "parts": parts, "references_only_in": refs_only,
            "new_parts": sorted(s for s, p in parts.items() if p["state"] == "new"),
            "on_target_parts": sorted(s for s, p in parts.items() if p["state"] == "on-target")}


def qa_pass_env(evidence, key):
    for i in reversed(((evidence or {}).get("keys") or {}).get(key, {}).get("items") or []):
        if i.get("verdict") in ("pass", "accepted") and i.get("env_versions"):
            return i["env_versions"]
    return None


def place_all(tickets, lanes, evidence=None):
    target = target_versions(lanes)
    return {t["key"]: place(t, target, qa_pass_env(evidence, t["key"])) for t in (tickets or {}).get("tickets") or [] if t.get("exists")}


def words(p, names=None):
    cited = sum(x.get("cited_by_later_commits", 0) for x in p["parts"].values())
    base = _words(p, names)
    return base + (f" (+{cited} later commit(s) cite it)" if cited else "")


def _words(p, names=None):
    """One phrase for the page: 'already on prod-3 (UR Caller 2.1.75)', 'new', 'partly new: MediaHub frontend'."""
    names = names or {}
    nm = lambda s: names.get(s, s)  # noqa: E731
    if p["placement"] == "on-target":
        return "already on the target: " + ", ".join(f"{nm(s)} {p['parts'][s]['fixed_in']}" for s in p["on_target_parts"])
    if p["placement"] == "partly-new":
        return ("partly new: " + ", ".join(nm(s) for s in p["new_parts"]) + "; already on the target: " +
                ", ".join(f"{nm(s)} {p['parts'][s]['fixed_in']}" for s in p["on_target_parts"]))
    if p["placement"] == "new":
        return "new: " + ", ".join(nm(s) for s in p["new_parts"])
    return "placement unknown"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = json.load(open(a.report))
    out = place_all(r.get("tickets"), r.get("lanes"), r.get("evidence"))
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1)); return
    for k, p in sorted(out.items()):
        print(f"{k:<9} {p['placement']:<11} {words(p)}")


if __name__ == "__main__":
    main()
