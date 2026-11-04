#!/usr/bin/env python3
"""The project verbs, offline: new makes the folder and the page's skeleton with a first tail, keys adds to the watch,
list and show read the pages as data."""
import contextlib, datetime, io, json, os, sys, tempfile, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "project"))
import project as P  # noqa: E402
V = P.V

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


def call(fn, **kw):
    """(exit code, stdout) of one verb."""
    buf = io.StringIO()
    a = types.SimpleNamespace(**{"env_file": None, "json": False, "title": None, **kw})
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        try:
            fn(a); code = 0
        except SystemExit as e:
            code = e.code or 0
    return code, buf.getvalue()


with tempfile.TemporaryDirectory() as t:
    vault = os.path.join(t, "v")
    os.makedirs(os.path.join(vault, "to-read"))
    P.SITE = os.path.join(t, "site.json")
    json.dump({"vault": vault}, open(P.SITE, "w"))
    today = datetime.date.today()
    dl = (today + datetime.timedelta(days=40)).isoformat()
    check("no projects yet: list says so, show exits 3", call(P.cmd_list)[1].startswith("no projects yet") and call(P.cmd_show, key="sb")[0] == 3)
    code, out = call(P.cmd_new, key="sb", deadline=dl, title="Super Bowl")
    page = os.path.join(vault, "projects", "sb", "sb.md")
    text = open(page).read() if os.path.isfile(page) else ""
    fl, body = V.split_front(text)
    check("new makes the folder and the page, says the days left", code == 0 and "projects/sb/sb.md: written" in out and "40 days left" in out)
    check("the page's properties: type project, date, deadline, source vault, watch from the deadline, the title as alias",
          'type: "project"' in text and f'deadline: "{dl}"' in text and f'date: "{today}"' in text and 'source: "vault"' in text
          and f'watch: "{(today + datetime.timedelta(days=54)).isoformat()}"' in text and 'aliases: ["Super Bowl"]' in text)
    check("the head is the skeleton, none of its headings the tail's, the tail a first render below it",
          body.startswith("# Super Bowl\n") and all(f"## {h}\n" in body for h in P.HEAD_SECTIONS) and not set(P.HEAD_SECTIONS) & set(V.TAIL_HEADS)
          and body.index("## Next step") < body.index("## Waiting for your word") < body.index("## Deadline")
          and "Nothing waits on you for this project." in body and "no keys yet" in body)
    check("new refuses an existing key, a bad key and a bad deadline",
          call(P.cmd_new, key="sb", deadline=dl)[0] == 3 and call(P.cmd_new, key="Bad Key", deadline=dl)[0] == 2
          and call(P.cmd_new, key="ok", deadline="next week")[0] == 2 and not os.path.exists(os.path.join(vault, "projects", "ok")))
    code, out = call(P.cmd_keys, key="sb", add=["MH-1", "mh-2"])
    check("keys adds to the page's keys, uppercased, deduplicated", code == 0 and 'keys: "MH-1 MH-2"' in open(page).read()
          and "nothing new" in call(P.cmd_keys, key="sb", add=["MH-2"])[1] and call(P.cmd_keys, key="sb", add=["bogus"])[0] == 2
          and call(P.cmd_keys, key="nope", add=["MH-1"])[0] == 3)
    check("keys --json names what was added", json.loads(call(P.cmd_keys, key="sb", add=["MH-3"], json=True)[1]) == {"key": "sb", "keys": ["MH-1", "MH-2", "MH-3"], "added": ["MH-3"]})
    open(os.path.join(vault, "to-read", "p.md"), "w").write('---\ntitle: "A plan"\ntype: "plan"\ndate: "2026-11-02"\nstatus: "proposed"\nnext: ""\nproject: "sb"\n---\n# A plan\n')
    rows = json.loads(call(P.cmd_list, json=True)[1])
    check("list gives each project's key, deadline, days left and open asks",
          [r["key"] for r in rows] == ["sb"] and rows[0]["deadline"] == dl and rows[0]["days"] == 40 and rows[0]["keys"] == ["MH-1", "MH-2", "MH-3"]
          and [a["path"] for a in rows[0]["asks"]] == ["to-read/p.md"] and rows[0]["asks"][0]["status"] == "proposed")
    text_out = call(P.cmd_list)[1]
    import re
    check("and as a table", "key  deadline    days left  open asks  title" in text_out and re.search(rf"^sb\s+{dl}\s+40 days left\s+1\s+Super Bowl$", text_out, re.M))
    code, out = call(P.cmd_show, key="sb")
    check("show prints the facts, what waits and the notes", code == 0 and out.startswith("sb — Super Bowl  (projects/sb/sb.md)")
          and f"deadline {dl} · 40 days left" in out and "keys MH-1 MH-2 MH-3" in out and "waiting for your word: 1\n  to-read/p.md · plan · proposed" in out
          and "notes: 1" in out)
    check("show --json is the same data", json.loads(call(P.cmd_show, key="sb", json=True)[1])["notes"][0]["path"] == "to-read/p.md")
sys.exit(1 if failures else 0)
