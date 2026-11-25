#!/usr/bin/env python3
"""graph.py candidates, offline: a search by name or window that leaves one graph answers it; two to five are
listed a line each (name, graph, owner, created) with the checks to run; more than five are not walked, the
window is narrowed instead (the owner's rule, 2026-11-25). The window keeps a graph that lived during it."""
import argparse, contextlib, io, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "graph"))
import graph as G  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

def v2(gid, name, created, deleted="", email="ops@fox.example"):
    return {"id": gid, "email": email, "phase": "Stopped" if deleted else "Running", "createdAt": created,
            "deletedAt": deleted or "0001-01-01T00:00:00Z", "processes": {},
            "annotations": {"businessName": name, "businessType": "live", "objectId": "O" + gid}}

class FakeUR:
    order = ["prod3"]
    def __init__(self, ents):
        self.ents = ents
    def get(self, env, path):
        return 200, {"value": {"entities": self.ents}}

def run(ents, **kw):
    a = argparse.Namespace(email="ops@fox.example", env=None, all=False, object=None, any=True, deleted=False,
                           pages=1, limit=200, json=kw.pop("json", False), env_file=None,
                           name=kw.pop("name", None), since=kw.pop("since", None), until=kw.pop("until", None))
    buf, code = io.StringIO(), 0
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        try:
            G.cmd_graphs(FakeUR(ents), a)
        except SystemExit as e:
            code = e.code
    return buf.getvalue(), code

# the verdict
rows = [{"graph_id": f"G{i}"} for i in range(7)]
check("no row is none", G.candidates([])["verdict"] == "none")
check("one row is the answer, its check is itself", G.candidates(rows[:1]) == {"count": 1, "cap": 5, "verdict": "one", "check": ["G0"]})
check("two to five are asked, each to check", G.candidates(rows[:5])["verdict"] == "ask" and len(G.candidates(rows[:5])["check"]) == 5)
check("six are narrowed, none checked", G.candidates(rows[:6])["verdict"] == "narrow" and G.candidates(rows[:6])["check"] == [])

# the window
since, until = G._when("2026-11-24 15:00"), G._when("2026-11-24T16:00:00+00:00")
check("a moment without a zone is UTC", since.utcoffset().total_seconds() == 0)
check("a zone is honoured", G._when("2026-11-24T23:00:00+08:00") == since)
check("a graph running through the window is in it", G.in_window({"created_at": "2026-11-24T10:00:00Z"}, since, until))
check("a graph stopped before the window is out", not G.in_window({"created_at": "2026-11-24T10:00:00Z", "deleted_at": "2026-11-24T14:59:00Z"}, since, until))
check("a graph created after the window is out", not G.in_window({"created_at": "2026-11-24T16:01:00Z"}, since, until))
check("a graph with no creation time is kept", G.in_window({"created_at": ""}, since, until))

# through the verb
ents = [v2("G1", "KTVU to ckt 4327", "2026-11-24T14:00:00Z"),
        v2("G2", "ktvu backup", "2026-11-24T15:30:00Z", "2026-11-24T18:00:00Z"),
        v2("G3", "WFLD main", "2026-11-24T14:00:00Z"),
        v2("G4", "KTVU old", "2026-11-20T10:00:00Z", "2026-11-21T10:00:00Z")]
out, code = run(ents, name="ktvu", since="2026-11-24 15:00", until="2026-11-24 16:00")
check("the name matches without case and the window drops the old one", "G1" in out and "G2" in out and "G3" not in out and "G4" not in out)
check("several matches print as candidates with the checks", out.startswith("# 2 candidate(s)") and "graph G1  graph G2" in out)
check("several candidates exit EX_CHOOSE, not 0", code == G.EX_CHOOSE == 6)
check("a candidate line carries name, graph, owner and created",
      any("KTVU to ckt 4327" in l and "G1" in l and "ops@fox.example" in l and "created 2026-11-24 14:00" in l for l in out.splitlines()))

out, code = run(ents, name="wfld")
check("one match prints the ordinary listing", out.startswith("# ops@fox.example") and "candidate" not in out and code == 0)

many = [v2(f"K{i}", f"KTVU {i}", "2026-11-24T14:00:00Z") for i in range(6)]
out, code = run(many, name="ktvu")
check("more than five are not walked", "do not walk them" in out and "graph K0" not in out and code == G.EX_CHOOSE)

out, code = run(many, name="ktvu", json=True)
body = json.loads(out)
check("--json carries the verdict, and exits EX_CHOOSE", body["candidates"]["verdict"] == "narrow" and body["candidates"]["count"] == 6 and code == G.EX_CHOOSE)
out, code = run(ents, json=True)
body = json.loads(out)
check("a plain listing carries no candidates block and exits 0", body["results"] and "candidates" not in body and code == 0)

out, code = run(ents, since="yesterday")
check("a window that is not ISO is a usage error", code == G.EX_USAGE)
out, code = run(ents, name="nothing like it")
check("no match is not-found", code == G.EX_NOTFOUND)

sys.exit(1 if failures else 0)
