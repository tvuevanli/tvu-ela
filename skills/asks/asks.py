#!/usr/bin/env python3
"""asks — what the owner taught ela by answering its asks: the facts he gave, and his corrections as precedents.
Stdlib only.

ela runs on its own; the owner gives a fact ela cannot read anywhere and rules on what ela is not sure of (plan
ela/2026-11-26-plan-ela-runs-on-its-own-asks-teach-it). Each answer is kept so that the same question is not put to him
twice: a fact under its kind and key, a correction with its cause in the store of the domain that asked.

  precedents [--domain D] [--kind K] [--waiting] [--json]
                                the corrections kept with a cause, read from each domain's own store: dry's corpus
                                (his did.md `wrong: <why>`), the board watch's corrections, mention's triage log. A
                                judge cites one of the same domain and kind. --waiting adds those still waiting for a
                                cause. A kind outside the domain's closed list is refused (exit 2)
  fact get KIND KEY [--json]    the fact he gave for this kind and key, or exit 3 when none
  fact list [--json]            every fact given, by kind
  fact give KIND KEY VALUE --source S [--durable] [--apply]
                                keep a fact he gave; a dry run unless --apply. In the site directory by default;
                                --durable writes elak's knowledge/facts-given.json, on his word only (elak is written
                                on his word and committed by the session that wrote it)

Fact kinds are a closed list (FACT_KINDS). A key is matched case- and space-insensitively. An ask for a fact looks the
store up before it is raised (`known`): the board watch refuses a fact ask whose answer is already kept.

Stores: the site's facts-given.json beside site.json (ELA_ASKS_FACTS_DIR stands in for it in tests); <elak>/knowledge/facts-given.json; the domains' own stores under
<reports>/ela/ (dry/record.jsonl, watch/corrections.jsonl, mentions/triage.jsonl).
"""
import argparse, datetime, json, os, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
SITE_DIR = os.path.expanduser("~/.claude/ela")
SITE = os.path.join(SITE_DIR, "site.json")
FACTS_FILE = "facts-given.json"
EX_USAGE, EX_NOTFOUND = 2, 3

# What a fact ask may ask for: the kinds of fact no source carries. Closed, so a key means one thing.
FACT_KINDS = {
    "owner": "who owns an area, a component or a repository (a role, its roster name)",
    "account": "which person or team an account, a name or an address in a source stands for",
    "lane": "which lane or environment something runs on, or is meant for",
    "date": "a date no source carries: a leave, a release window, a customer's deadline",
    "scope": "whether a case is in a release's or a ticket's scope",
}
DOMAINS = ("dry", "watch", "mention")


def site():
    try:
        return json.load(open(SITE))
    except (OSError, ValueError):
        return {}


def norm(key):
    return " ".join(str(key or "").lower().split())


def read_json(path):
    try:
        got = json.load(open(path, encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def paths(site_dir=None, elak=None):
    """(site file, elak file or None). ELA_ASKS_FACTS_DIR stands in for the site directory and leaves elak out (tests)."""
    site_dir = site_dir or os.environ.get("ELA_ASKS_FACTS_DIR") or None
    s = site() if site_dir is None and elak is None else {}
    elak = elak if elak is not None else s.get("elak")
    return (os.path.join(site_dir or SITE_DIR, FACTS_FILE),
            os.path.join(os.path.expanduser(elak), "knowledge", FACTS_FILE) if elak else None)


def facts(site_dir=None, elak=None):
    """Every fact given: {kind: {key: {value, at, source, durable}}}; elak's override the site's."""
    local, durable = paths(site_dir, elak)
    out = {}
    for path, d in ((local, False), (durable, True)):
        for kind, rows in read_json(path).items() if path else ():
            for k, v in (rows or {}).items():
                if isinstance(v, dict):
                    out.setdefault(kind, {})[norm(k)] = dict(v, durable=d)
    return out


def known(kind, key, site_dir=None, elak=None):
    """The fact kept for this kind and key, or None. An ask for a fact calls this before it is raised."""
    if kind not in FACT_KINDS:
        raise ValueError(f"fact kind {kind!r}: one of {', '.join(FACT_KINDS)}")
    return facts(site_dir, elak).get(kind, {}).get(norm(key))


def give(kind, key, value, source, durable=False, apply=False, site_dir=None, elak=None, now=None):
    """Keep one fact. → {kind, key, value, path, applied}. A dry run unless apply."""
    if kind not in FACT_KINDS:
        raise ValueError(f"fact kind {kind!r}: one of {', '.join(FACT_KINDS)}")
    if not norm(key) or not str(value or "").strip():
        raise ValueError("a fact has a key and a value")
    local, lasting = paths(site_dir, elak)
    path = lasting if durable else local
    if not path:
        raise ValueError("no elak root in site.json for a durable fact")
    row = {"value": " ".join(str(value).split()), "at": (now or datetime.datetime.now()).isoformat(timespec="seconds"),
           "source": source or ""}
    if apply:
        d = read_json(path)
        d.setdefault(kind, {})[norm(key)] = row
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    return {"kind": kind, "key": norm(key), "value": row["value"], "path": path, "applied": apply}


# ── precedents: each domain keeps its own store; this reads them in one row shape ───────────────────────────────
def mod(name):
    sys.path.insert(0, os.path.join(SKILLS, name))
    return __import__(name)


def kinds(domain):
    """The domain's closed list of kinds a precedent is filed under."""
    if domain == "dry":
        return tuple(mod("dry").CLASSES)
    if domain == "watch":
        return tuple(mod("watch").KINDS)
    if domain == "mention":
        return tuple(mod("mention").REASONS)
    raise ValueError(f"domain {domain!r}: one of {', '.join(DOMAINS)}")


def rows(reports, domain):
    """One domain's corrections as {domain, kind, target, act, verdict, cause, corpus, at}."""
    if domain == "dry":
        got = [dict(r, corpus="admitted") for r in mod("dry").corpus_cases(reports)]
        got += [{"class": r.get("class"), "target": r.get("target"), "act": r.get("act"), "cause": None, "at": r.get("at"),
                 "corpus": "waiting for a cause"}
                for r in mod("dry").record(reports) if r.get("review") and r.get("corpus") == "waiting for a cause"]
    elif domain == "watch":
        got = mod("watch").corrections(reports)
    elif domain == "mention":
        got = mod("mention").corrections(reports)
    else:
        raise ValueError(f"domain {domain!r}: one of {', '.join(DOMAINS)}")
    return [{"domain": domain, "kind": r.get("class"), "target": r.get("target"), "act": r.get("act"),
             "verdict": r.get("verdict") or ("wrong" if domain == "dry" else None), "cause": r.get("cause"),
             "corpus": r.get("corpus"), "at": r.get("at")} for r in got]


def precedents(reports, domain=None, kind=None, waiting=False):
    """The corrections a judge may cite: those with a cause, of one domain and kind when given, newest first. A kind
    outside the domain's closed list raises ValueError: a precedent filed under no kind cannot be matched to a case."""
    if kind and not domain:
        raise ValueError("a kind is read within its domain: give --domain")
    if kind and kind not in kinds(domain):
        raise ValueError(f"{domain} kind {kind!r}: one of {', '.join(kinds(domain))}")
    out = []
    for d in ([domain] if domain else DOMAINS):
        try:
            out += rows(reports, d)
        except (OSError, ImportError):
            continue
    out = [r for r in out if (not kind or r["kind"] == kind) and (waiting or r["corpus"] == "admitted" and r["cause"])]
    return sorted(out, key=lambda r: str(r.get("at") or ""), reverse=True)


def cite(p):
    """One precedent as a line a judge can quote."""
    return (f"{p['domain']}/{p['kind']} {p['target']}: {p['verdict'] or 'wrong'} — "
            + (f"because {p['cause']}" if p.get("cause") else "waiting for a cause") + f" ({str(p.get('at') or '')[:10]})")


# ── the command line ────────────────────────────────────────────────────────────────────────────────────────────
def reports_root():
    s = site()
    return s.get("reports") or os.path.join(s.get("projects") or os.path.expanduser("~/projects"), "reports")


def cmd_precedents(a):
    try:
        got = precedents(reports_root(), a.domain, a.kind, a.waiting)
    except ValueError as e:
        print(str(e), file=sys.stderr); sys.exit(EX_USAGE)
    if a.json:
        print(json.dumps(got, ensure_ascii=False, indent=1)); return
    print("\n".join(cite(p) for p in got) or "no precedent kept")


def cmd_fact(a):
    try:
        if a.verb == "get":
            got = known(a.kind, a.key)
            if not got:
                print(f"no {a.kind} fact for {a.key!r}", file=sys.stderr); sys.exit(EX_NOTFOUND)
            print(json.dumps(got, ensure_ascii=False) if a.json else got["value"]); return
        if a.verb == "list":
            got = facts()
            if a.json:
                print(json.dumps(got, ensure_ascii=False, indent=1)); return
            print("\n".join(f"{k} · {key}: {v['value']}" + (" (elak)" if v.get("durable") else "")
                            for k, rows_ in sorted(got.items()) for key, v in sorted(rows_.items())) or "no fact given yet")
            return
        got = give(a.kind, a.key, a.value, a.source, a.durable, a.apply)
        print(json.dumps(got, ensure_ascii=False) if a.json else
              f"{'kept' if got['applied'] else 'would keep'} {got['kind']} · {got['key']}: {got['value']} in {got['path']}"
              + ("" if got["applied"] else " (dry run; --apply keeps it)"))
    except ValueError as e:
        print(str(e), file=sys.stderr); sys.exit(EX_USAGE)


def main():
    ap = argparse.ArgumentParser(prog="ela asks", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", help="accepted from bin/ela; this verb reads no credential")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("precedents", help="the corrections kept with a cause, by domain and kind")
    p.add_argument("--domain", choices=DOMAINS); p.add_argument("--kind"); p.add_argument("--waiting", action="store_true")
    p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_precedents)
    p = sub.add_parser("fact", help="the facts he gave: get, list, give")
    fs = p.add_subparsers(dest="verb", required=True)
    q = fs.add_parser("get"); q.add_argument("kind", choices=list(FACT_KINDS)); q.add_argument("key")
    q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_fact)
    q = fs.add_parser("list"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_fact)
    q = fs.add_parser("give"); q.add_argument("kind", choices=list(FACT_KINDS)); q.add_argument("key"); q.add_argument("value")
    q.add_argument("--source", required=True, help="where he gave it: a topic id, a ticket key, a date")
    q.add_argument("--durable", action="store_true", help="elak's knowledge/facts-given.json, on his word only")
    q.add_argument("--apply", action="store_true"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_fact)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
