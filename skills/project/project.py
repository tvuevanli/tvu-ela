#!/usr/bin/env python3
"""project — the owner's projects in the vault: bounded work with a deadline and parties outside the program (a
customer PoC, a trial, a demo), one folder projects/<key>/ each with its page projects/<key>/<key>.md. Stdlib only.

L1: deterministic, no LLM. The page's head is the desk's text (goal, deadline, parties, what is known, next step)
until the owner rules it settled; its tail is written by `ela vault sync` from the notes that name the project, its
keys and threads (the archive's Afterwards watch) and the days to the deadline. This script creates the folder and
the page's skeleton, keeps the keys the page watches, and reads the pages as data. The rules: elak
blueprint/decisions/2026-11-04-projects-are-bounded-work-with-one-page-each.md.

Usage:
    project.py [--env-file F] list [--json]                        each project: key, deadline, days left, open asks
    project.py [--env-file F] show <key> [--json]                  one project: its facts, asks, notes, keys and threads
    project.py [--env-file F] new <key> --deadline YYYY-MM-DD [--title T]   the folder and an empty page with the head skeleton
    project.py [--env-file F] keys <key> --add KEY... [--json]     add Jira keys to the page's `keys`

Exit codes: 0 ok · 2 usage or site · 3 no such project, or the project already exists.
"""
import argparse, datetime, json, os, re, sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "vault"))
import vault as V  # noqa: E402

SITE = os.path.expanduser("~/.claude/ela/site.json")
KEY = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")          # a project's key: a folder name, lowercase with hyphens
HEAD_SECTIONS = ("Goal", "Dates", "Parties", "What is known", "Next step")   # never one of the sync's tail headings


def site():
    try:
        s = json.load(open(SITE))
    except (OSError, ValueError):
        print("no site.json; run /ela:setup in a Claude session", file=sys.stderr); sys.exit(2)
    if not s.get("vault") or not os.path.isdir(s["vault"]):
        print(f"site.json `vault` is not a folder: {s.get('vault')}", file=sys.stderr); sys.exit(2)
    return s


def jira_base(env):
    try:
        return next((l.split("=", 1)[1].strip().rstrip("/") for l in open(env) if l.startswith("JIRA_BASE_URL=")), "")
    except (OSError, TypeError):
        return ""


def page_path(vault, key):
    return os.path.join(vault, V.project_path(vault, key))


def one(vault, key, today):
    """(facts, rows) of project `key`, or exit 3."""
    pages = V.project_pages(vault)
    if key not in pages:
        print(f"no project {key!r}: " + (", ".join(sorted(pages)) if pages else "none yet; `ela project new <key> --deadline YYYY-MM-DD`"),
              file=sys.stderr); sys.exit(3)
    facts = V.project_facts(key, pages[key], today, V.project_path(vault, key))
    return facts, V.project_rows(vault, key, page=facts["path"])


def asks_of(rows):
    return [r for r in rows if (r.get("status") or "").lower() in (V.LIVE,) + V.LEGACY_LIVE]


def as_json(facts, rows):
    return {"key": facts["key"], "title": facts["title"], "path": facts["path"],
            "deadline": facts["deadline"].isoformat() if facts["deadline"] else None, "days": facts["days"],
            "step": facts["step"], "step_due": facts["step_due"].isoformat() if facts["step_due"] else None, "overdue": facts["overdue"],
            "keys": facts["keys"], "threads": facts["links"], "watch": facts["props"].get("watch"),
            "asks": [{k: r.get(k) for k in ("path", "title", "type", "status", "next")} for r in asks_of(rows)],
            "notes": [{k: r.get(k) for k in ("path", "title", "type", "date", "status")} for r in rows]}


def cmd_list(a):
    s = site()
    today = datetime.date.today()
    out = []
    for key, text in V.project_pages(s["vault"]).items():
        facts = V.project_facts(key, text, today, V.project_path(s["vault"], key))
        out.append(as_json(facts, V.project_rows(s["vault"], key, page=facts["path"])))
    out.sort(key=lambda f: (f["days"] is None, f["days"] if f["days"] is not None else 0, f["key"]))
    if a.json:
        print(json.dumps(out, ensure_ascii=False)); return
    if not out:
        print("no projects yet: `ela project new <key> --deadline YYYY-MM-DD`"); return
    w = max(len(f["key"]) for f in out)
    print(f"{'key':<{w}}  deadline    days left  open asks  title")
    for f in out:
        print(f"{f['key']:<{w}}  {f['deadline'] or '—':<10}  {V.days_words(f['days']):<9}  {len(f['asks']):>9}  {f['title']}")


def cmd_show(a):
    s = site()
    today = datetime.date.today()
    facts, rows = one(s["vault"], a.key, today)
    if a.json:
        print(json.dumps(as_json(facts, rows), ensure_ascii=False)); return
    print(f"{facts['key']} — {facts['title']}  ({facts['path']})")
    print(f"deadline {facts['deadline'].isoformat() if facts['deadline'] else '—'} · {V.days_words(facts['days'])}"
          + (f" · next step: {facts['step']}" + (" (overdue)" if facts["overdue"] else "") if facts["step"] else ""))
    print(f"keys {' '.join(facts['keys']) or '—'} · threads {len(facts['links'])} · watch {facts['props'].get('watch') or '—'}")
    asks = asks_of(rows)
    print(f"waiting for your word: {len(asks)}")
    for r in asks:
        print(f"  {r['path']} · {r.get('type') or '?'} · {r.get('status') or '—'}" + (f" · next: {r['next']}" if r.get("next") else ""))
    print(f"notes: {len(rows)}")
    for r in rows:
        print(f"  {r['path']} · {r.get('type') or '?'}" + (f" · {r['date']}" if r.get("date") else ""))


def skeleton(key, title, deadline, today):
    """The page's front matter and head: the desk's sections, empty, above the marker the sync writes below."""
    fm = V.front([], {"title": title, "type": "project", "date": today.isoformat(), "deadline": deadline, "source": "vault"})
    body = [f"# {title}", "",
            "*The head is the desk's text until you write `ela: keep this` and its facts go to elak; the sync writes everything "
            f"from *{V.PROJECT_HEAD_END[3:]}* down on each pass. Fill the sections in your own words; the first unticked box under "
            "*Next step* is the step Home may name, or set `next-step` in the properties.*", ""]
    hints = {"Goal": "What TVU must prove, in one paragraph.", "Dates": f"{deadline} — what happens on that day, and the dates before it.",
             "Parties": "- customer: \n- others: \n- TVU: who does what", "What is known": "- ", "Next step": "- [ ] "}
    for h in HEAD_SECTIONS:
        body += [f"## {h}", "", hints[h], ""]
    return fm, "\n".join(body)


def cmd_new(a):
    s = site()
    today = datetime.date.today()
    key = a.key.strip().lower()
    if not KEY.match(key):
        print(f"not a project key: {a.key!r} (lowercase letters, digits and hyphens)", file=sys.stderr); sys.exit(2)
    try:
        deadline = datetime.date.fromisoformat(a.deadline)
    except (TypeError, ValueError):
        print(f"--deadline takes YYYY-MM-DD, not {a.deadline!r}", file=sys.stderr); sys.exit(2)
    folder = os.path.join(s["vault"], V.PROJECTS, key)
    if os.path.exists(folder):
        print(f"project {key!r} exists: {V.PROJECTS}/{key}/", file=sys.stderr); sys.exit(3)
    title = (a.title or key.replace("-", " ")).strip()
    fm, head = skeleton(key, title, deadline.isoformat(), today)
    os.makedirs(folder)
    n = V.project_note(key, fm + head, s["vault"], [], today, jira_base(a.env_file or s.get("env")))
    V.atomic_write(page_path(s["vault"], key), n.front_text + n.head + n.tail)
    print(f"{V.PROJECTS}/{key}/{key}.md: written, deadline {deadline.isoformat()} ({V.days_words((deadline - today).days)}); "
          "fill its head, then `ela project keys` for the tickets it watches")


def cmd_keys(a):
    s = site()
    p = page_path(s["vault"], a.key)
    if not os.path.isfile(p):
        print(f"no project {a.key!r}", file=sys.stderr); sys.exit(3)
    text = open(p, encoding="utf-8").read()
    props = V.props_of(V.split_front(text)[0])
    have = [k for k in V.KEY_RX.findall(props.get("keys") or "") if not V.NOT_KEYS.match(k)]
    bad = [k for k in a.add if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,9}-\d{1,6}", k)]
    if bad:
        print(f"not a ticket key: {', '.join(bad)}", file=sys.stderr); sys.exit(2)
    keys = list(dict.fromkeys(have + [k.upper() for k in a.add]))
    if keys != have:
        V.atomic_write(p, V.set_front(text, keys=" ".join(keys)))
    if a.json:
        print(json.dumps({"key": a.key, "keys": keys, "added": [k for k in keys if k not in have]})); return
    print(f"{a.key}: keys {' '.join(keys)}" + ("" if keys != have else " (nothing new)"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", help="ela's env file; its Jira base URL links the keys on a new page")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="each project: key, deadline, days left, open asks")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("show", help="one project: its facts, what waits on your word, its notes, keys and threads")
    p.add_argument("key")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_show)
    p = sub.add_parser("new", help="create projects/<key>/ and the page's head skeleton")
    p.add_argument("key")
    p.add_argument("--deadline", required=True, help="YYYY-MM-DD")
    p.add_argument("--title", help="the page's title; the key with spaces when absent")
    p.set_defaults(func=cmd_new)
    p = sub.add_parser("keys", help="add Jira keys to a project's page, which the afterwards pass then watches")
    p.add_argument("key")
    p.add_argument("--add", nargs="+", required=True, metavar="KEY")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_keys)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
