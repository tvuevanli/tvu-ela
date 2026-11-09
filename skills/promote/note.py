#!/usr/bin/env python3
"""The promotion note's two gates: the claims two independent checkers verify before anything is shown, and the format
the note and its Slack text must hold.

  note.py claims <report.json> [--json]           every checkable claim in a promote report, split by checker:
                                                  `jira` (QA verdicts, splits, Fixed In placement, ticket prerequisites)
                                                  and `system` (lane versions, config chains, code and branch state,
                                                  live dependencies, shipped versions), each with the read that settles it
  note.py lint <note.md> [--slack <file>] [--json]
                                                  the note: full service names, every Jira key a link, a `## Checked`
                                                  record, no machine path or address; the Slack text: two parts split by
                                                  a line `---`, part 1 without ticket ids, no `<url|key>` or [x](y) links

Why: on 2026-11-09 two reviewer agents found about 45 errors in the promote note only after the owner had read it
(gap 8: no self-review), and the note used mx/hub/FE/BE, bare keys and Slack links that break when pasted (gap 10).
Exit 0 clean, 1 lint findings, 2 usage.
"""
import argparse, json, re, sys

KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,5}-(?!0)\d{2,6}\b")   # a leading zero is an item id (MH-030), not a Jira key
SHORT = re.compile(r"(?<![\w`/.\-])(mx|hub|FE|BE|mx-service|tvu-media-hub)(?![\w`/.\-])")
PATH_RE = re.compile(r"(/home/|/mnt/|/Users/|[A-Z]:\\\\)")
ADDR_RE = re.compile(r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?::\d+)?\b(?!\.\d)")   # private hosts; 2.0.108.23 is a version
SLACK_LINK = re.compile(r"<https?://[^>|]+\|[^>]+>")
MD_LINK = re.compile(r"\[[^\]]+\]\(https?://[^)]+\)")


def _name(slug):
    try:
        import shipcheck as SC  # noqa: E402 — same skill
        return SC.name(slug)
    except ImportError:
        return slug


def claims(r):
    """[{checker, kind, claim, settle}] from a promote report's JSON."""
    out = []
    add = lambda checker, kind, claim, settle: out.append({"checker": checker, "kind": kind, "claim": claim, "settle": settle})
    for s in (r.get("lanes") or {}).get("services") or []:
        for side in ("from", "to"):
            v = s.get(side) or {}
            if v.get("version"):
                add("system", "lane_version", f"{_name(s['service'])} on {s.get(side + '_lane')} is {v['version']} (source {v.get('source')}, read {v.get('at') or r.get('generated_at')})",
                    f"promote proof lane {s.get(side + '_lane')}  # the lane's own /base/version, read now")
    for g in r.get("ships") or []:
        if g.get("ship"):
            add("system", "ship_gap", f"{g['name']} ships {g['ship']['version']}; {r.get('from')} runs {g['source']['version']}; between: "
                + ", ".join(t["key"] for t in g["tickets"]), f"git log {g['source']['sha'][:10]}..{g['ship']['sha'][:10]} in the service's checkout; jira read each key")
    ev = (r.get("evidence") or {}).get("keys") or {}
    for k, e in sorted(ev.items()):
        if e.get("verdict") not in (None, "none"):
            add("jira", "qa_verdict", f"{k}: QA {e['verdict']}" + (f" — {e['jira_line']}" if e.get("jira_line") else ""),
                f"jira read {k} --comments  # QA's latest comment, its counts and environment block; follow splits")
        for sp in e.get("splits") or []:
            add("jira", "split", f"{k} split into {sp.get('key')} ({sp.get('verdict')}, {sp.get('status')})", f"jira read {sp.get('key')}")
    for k, p in sorted((r.get("placement") or {}).items()):
        add("jira", "placement", f"{k} is {p.get('placement')} on {r.get('to')}" + (f": {p.get('why') or ''}" if p.get("why") else ""),
            f"jira read {k} (Fixed In) and git merge-base --is-ancestor <commit> <target build sha>")
    pre = r.get("prereqs") or {}
    for it in pre.get("items") or []:
        add("jira" if it.get("key") else "system", "prerequisite", f"[{it.get('category')}] {it.get('line', '')[:120]} — {it.get('where')}",
            f"jira read {it['key']} --comments" if it.get("key") else f"read {it.get('where')}")
    for u in pre.get("unbuilt") or []:
        if u.get("commits"):
            add("system", "unbuilt", f"{_name(u.get('service'))}: {len(u['commits'])} commit(s) on {u.get('branch')} after build {u.get('build')}",
                f"git fetch; git log <build sha>..origin/{u.get('branch')}")
    for b in pre.get("branches") or []:
        add("system", "branch", f"{b.get('repo')} {b.get('branch')}: " + ("merges clean" if (b.get("against_release") or {}).get("clean") else "conflicts or not tried"),
            f"git merge-tree --write-tree origin/release{r.get('line')} origin/{b.get('branch')}")
    for d in (r.get("live_deps") or {}).get("deps") or []:
        add("system", "live_dependency", f"{_name(d.get('caller'))} → {d.get('to')} on {r.get('to')}: " + (d.get("unread") or d.get("routing") or ""),
            f"configserver effective <app> {'+'.join(p for p in d.get('chain') or [] if p != 'default') or 'default'} --key {d.get('key')}; GET <instance>/base/version")
    for f in r.get("findings") or []:
        if f.get("kind") in ("config_chain", "chain_unproven", "profile_chain"):
            add("system", "config", f["what"][:200], "facts runtime show --lane <lane>; configserver effective <app> <chain>")
    return out


def _strip_code(text):
    keep_lines = lambda m: "\n" * m.group(0).count("\n")     # line numbers survive the cut
    text = re.sub(r"(?ms)^(```|~~~~?).*?^\1", keep_lines, text)
    return re.sub(r"`[^`\n]*`", "", text)


def lint_note(text):
    f = []
    fm = re.match(r"(?s)\A---\n.*?\n---\n", text)
    off = fm.group(0).count("\n") if fm else 0            # line numbers are the file's
    body = text[fm.end():] if fm else text
    plain = re.sub(r"\]\(https?://[^)\s]*\)", "](url)", _strip_code(body))   # a link's target is not prose
    for m in SHORT.finditer(plain):
        f.append(f"short service name '{m.group(1)}': write the full name (UR Caller, MediaHub backend, MediaHub frontend)")
    linked = {m.start() for m in re.finditer(r"\[(" + KEY_RE.pattern + r")\]\(url\)", plain)}
    for m in KEY_RE.finditer(plain):
        if m.start() - 1 not in linked:
            line = plain[:m.start()].count("\n") + 1 + off
            f.append(f"line {line}: {m.group(0)} is not a link — write [{m.group(0)}](<jira>/browse/{m.group(0)})")
    if not re.search(r"(?m)^#{2,3} .*\bChecked\b", body):
        f.append("no `## Checked` section: the note must record what the two checkers verified and what they corrected")
    if PATH_RE.search(body):
        f.append("a machine path: name roots, never a path on this machine")
    if ADDR_RE.search(_strip_code(body)):
        f.append("an IP address outside code: the note names services, never hosts")
    return sorted(set(f), key=f.index)


def lint_slack(text):
    f = []
    parts = re.split(r"(?m)^---\s*$", text)
    if len(parts) != 2:
        f.append(f"the Slack text has {len(parts)} part(s): two are required, split by a line `---` — (1) what the release brings, (2) what we set for prod")
    if parts and KEY_RE.search(parts[0]):
        f.append("part 1 carries ticket ids (" + ", ".join(sorted(set(KEY_RE.findall(parts[0])))[:4]) + "): it is for everyone, no ticket ids")
    if SLACK_LINK.search(text):
        f.append("a <url|text> link: it breaks when pasted; write the plain key or the full URL")
    if MD_LINK.search(text):
        f.append("a Markdown [x](y) link: Slack shows it raw when pasted; write the plain key or the full URL")
    for m in SHORT.finditer(_strip_code(text)):
        f.append(f"short service name '{m.group(1)}' in the Slack text")
    return sorted(set(f), key=f.index)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("claims"); p.add_argument("report"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("lint"); p.add_argument("note"); p.add_argument("--slack"); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.cmd == "claims":
        cs = claims(json.load(open(a.report)))
        if a.json:
            print(json.dumps(cs, ensure_ascii=False, indent=1)); return
        for checker in ("jira", "system"):
            mine = [c for c in cs if c["checker"] == checker]
            print(f"## {checker} checker — {len(mine)} claim(s)")
            for c in mine:
                print(f"- [{c['kind']}] {c['claim']}\n    settle: {c['settle']}")
        return
    res = {"note": lint_note(open(a.note).read())}
    if a.slack:
        res["slack"] = lint_slack(open(a.slack).read())
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        for k, v in res.items():
            print(f"{k}: " + ("clean" if not v else f"{len(v)} finding(s)"))
            for x in v:
                print(f"  - {x}")
    sys.exit(1 if any(res.values()) else 0)


if __name__ == "__main__":
    main()
