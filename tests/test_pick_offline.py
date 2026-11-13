#!/usr/bin/env python3
"""pick: fields out of JSON without an interpreter. The shape, dotted paths, an index, a run, [] over a list and a
dict, ** at any depth, rows of several fields, --where and --count; a file in the site directory, the env file and a
link to either are refused; text that is not JSON is named by position and never echoed."""
import json, os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "pick", "pick.py")
fail = 0
DOC = {"generated": "2026-11-13", "errors": [], "a.b": 7,
       "lanes": {"cadence": {"count": 2, "rows": [{"key": "MH-1", "status": "In Progress", "who": {"name": "A"}, "labels": ["x", "y"], "note": "one\ttwo\nthree"},
                                                   {"key": "MH-2", "status": "Done", "who": None, "labels": []}]},
                 "triage": {"count": 1, "rows": [{"key": "MH-3", "status": "Open", "who": {"name": "B"}, "labels": ["x"]}]}}}


def run(*args, stdin=None, doc=DOC):
    e = dict(os.environ, HOME=home); e.pop("ELA_ENV_FILE", None)
    r = subprocess.run(["python3", SCRIPT, *args], input=json.dumps(doc) if stdin is None else stdin, capture_output=True, text=True, env=e)
    return r.returncode, r.stdout, r.stderr


def check(ok, what, got=None):
    global fail
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        fail = 1
        print("     ", got)


with tempfile.TemporaryDirectory() as tmp:
    home = os.path.join(tmp, "home"); sited = os.path.join(home, ".claude", "ela"); os.makedirs(sited)
    outside = os.path.join(tmp, "elsewhere.env")
    SECRET = "-".join(["decoy", "value", "never", "printed"])   # stands for a credential; assembled so no literal looks like one
    json.dump({"env": outside, "token_hint": SECRET}, open(os.path.join(sited, "site.json"), "w"))
    open(outside, "w").write(f"SLACK_BOT_TOKEN={SECRET}\n")
    open(os.path.join(sited, ".env"), "w").write(f"OLD={SECRET}\n")
    f = os.path.join(tmp, "doc.json"); json.dump(DOC, open(f, "w"))

    c, o, _ = run()
    check(c == 0 and o.splitlines()[0] == "generated\tstr\t2026-11-13" and "lanes\tdict(2)\tcadence, triage" in o and "errors\tlist(0)\tempty" in o, "no path: the shape, not the document", o)
    check(run("lanes.cadence.count")[1] == "2\n" and run("generated", "--file", f)[1] == "2026-11-13\n", "a dotted path, from stdin and from a file")
    check(run('["a.b"]')[1] == "7\n" and run(".lanes.triage.count")[1] == "1\n", "a key with a dot in brackets; a leading dot is the root")
    check(run("lanes.cadence.rows[1].key")[1] == "MH-2\n" and run("lanes.cadence.rows[-1].key")[1] == "MH-2\n", "an index, from either end")
    check(run("lanes.cadence.rows[].key")[1] == "MH-1\nMH-2\n", "[] over a list")
    check(run("lanes[].@key", ".count")[1] == "cadence\t2\ntriage\t1\n", "[] over a dict, with the key each value sits under")
    check(run("lanes.cadence.rows[].key", ".status", ".who.name")[1] == "MH-1\tIn Progress\tA\nMH-2\tDone\t\n", "several fields, one tab-separated line per row; a missing field is empty")
    check(run("lanes.cadence.rows[].key", "lanes.cadence.rows[].labels[]")[1] == "MH-1\tx, y\nMH-2\t\n", "a full path through the same list is the same row")
    check(run("lanes.cadence.rows[1:].key")[1] == "MH-2\n" and run("lanes.cadence.rows[:1].key")[1] == "MH-1\n", "a run of items")
    check(run("**.key", ".status", "--where", "key=MH-3")[1] == "MH-3\tOpen\n", "** finds an object at any depth")
    check(run("lanes.cadence.rows[].key", "--where", "status=Done")[1] == "MH-2\n" and run("lanes.cadence.rows[].key", "--where", "status!=Done")[1] == "MH-1\n", "--where K=V and K!=V")
    check(run("**.key", "--where", "status=Done", "--where", "status=Open")[1] == "MH-2\nMH-3\n", "the same key twice is either value")
    check(run("**.key", "--where", "labels~X", "--where", "who.name=B")[1] == "MH-3\n" and run("**.key", "--where", ".~three")[1] == "MH-1\n", "different keys are all; ~ contains, case ignored; `.` is the row")
    c, o, _ = run("lanes.cadence.rows", "--where", "key=MH-2")
    check(c == 0 and json.loads(o)["status"] == "Done", "--where with no []: the list the path names is filtered, one row whole", o)
    check(run("lanes.cadence.rows", "--count")[1] == "2\n" and run("**", "--where", "labels~x", "--count")[1] == "2\n" and run("errors", "--count")[1] == "0\n", "--count")
    check(run("lanes.cadence.rows[0].note")[1] == "one two three\n" and run("lanes.cadence.rows[0].note", "--max", "5")[1] == "one t…\n", "a tab or newline in a field is a space; --max cuts")
    check(run("lanes.cadence", "--shape")[1] == "count\tint\t2\nrows\tlist(2)\tof dict: key, status, who, labels, note\n", "--shape of what a path names")
    check(json.loads(run("lanes.cadence.rows[].key", ".labels", "--json")[1]) == [["MH-1", ["x", "y"]], ["MH-2", []]], "--json: the rows as JSON")
    c, o, e = run("lanes.zzz")
    check(c == 3 and o == "" and "no zzz under lanes; keys there: cadence, triage" in e, "a path that names nothing: exit 3 and the keys that are there", e)
    check(run("**.key", "--where", "key=MH-9")[0] == 3, "no row matches: exit 3")
    c, _, e = run("lanes.cadence.rows[].key", "generated")
    check(c == 2 and "does not go through" in e, "a second path through another list is refused, not guessed", e)
    check(run(stdin='[{"n": 1}\n')[0] == 2 and run("[].n", stdin='{"n": 1}\n{"n": 2}\n')[1] == "1\n2\n", "JSON lines are one list")
    c, o, e = run("x", stdin=f"SLACK_BOT_TOKEN={SECRET}\n")
    check(c == 2 and "not JSON (line 1" in e and SECRET not in o + e, "text that is not JSON: the position, never the text", e)
    link = os.path.join(tmp, "link.json"); os.symlink(os.path.join(sited, "site.json"), link)
    for name, path in (("a file in the site directory", os.path.join(sited, "site.json")), ("the env file, wherever site.json puts it", outside),
                       ("the default env file", os.path.join(sited, ".env")), ("a link into the site directory", link),
                       ("a path that climbs back into it", os.path.join(tmp, "home", ".claude", "x", "..", "ela", "site.json")), ("the home-relative form", "~/.claude/ela/site.json")):
        c, o, e = run("--file", path)
        check(c == 2 and "refused" in e and SECRET not in o + e, f"refused: {name}", (c, o, e))
    src = open(SCRIPT).read()
    check(not any(w in src for w in ("eval(", "exec(", "subprocess", "os.system", ", \"w\")", "'w')")), "the script evaluates nothing, starts nothing, writes nothing")
print("pick: " + ("FAILED" if fail else "passed"))
sys.exit(fail)
