#!/usr/bin/env python3
"""graph.py usage, offline: a graph counts once when it holds the process type, the owner falls back from the
graph's email to a process's x-tvu-email, the internal-domain filter ignores case, the walk stops at the cutoff
without reading further pages, and an environment without J2N v2 is said, not failed."""
import argparse, contextlib, io, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "graph"))
import graph as G  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

def graph(gid, created, email="", types=("encoder",), pemail=None, app="MediaHub"):
    procs = {f"n{i}": {"type": t, "image": f"registry.example/team/{t}img:1.0",
                       "options": ({"x-tvu-email": pemail} if pemail else {})} for i, t in enumerate(types)}
    return {"id": gid, "email": email, "appName": app, "createdAt": created, "processes": procs,
            "annotations": {"businessType": "live"}}

DOMAINS = ("tvunetworks.com", "tvu.com")
G.internal_domains = lambda: DOMAINS            # the site file is not read offline
rows = [G.usage_row(g) for g in (
    graph("G1", "2026-11-12T10:00:00Z", "Ann@Customer.COM", ("youtube_decoder", "encoder")),
    graph("G2", "2026-11-11T10:00:00Z", "ann@customer.com", ("youtube_decoder", "youtube_decoder")),
    graph("G3", "2026-11-10T10:00:00Z", "dev@TVUnetworks.COM", ("youtube_decoder",)),
    graph("G4", "2026-11-04T10:00:00Z", "", ("youtube_decoder",), pemail="Bob@Other.org"),
    graph("G5", "2026-11-03T10:00:00Z", "", ("youtube_decoder",)),
    graph("G6", "2026-11-03T09:00:00Z", "cat@customer.com", ("encoder", "youtube_decoder_v2")),
    graph("G7", "2026-11-02T09:00:00Z", "ops@sub.tvu.com", ("youtube_decoder",)),
    graph("G8", "2026-11-02T08:00:00Z", "eve@nottvu.com", ("youtube_decoder",)),
)]

# the type match
s = G.usage_summary(rows, "youtube_decoder", DOMAINS)
check("a graph is counted when one of its processes has the type", s["held"] == 7)
check("the match is the whole type, not a substring", "G6" not in [r["graph_id"] for r in s["rows"]])
check("two processes of the type in one graph count one graph",
      [u["graphs"] for u in s["by_user"] if u["email"].lower() == "ann@customer.com"] == [2])
check("the youtube alias names youtube_decoder", G.USAGE_ALIASES["youtube"] == "youtube_decoder")
check("no type counts graphs per process type, with the image that names it",
      G.usage_summary(rows, None, DOMAINS)["types"]["encoder"] == 2
      and G.usage_summary(rows, None, DOMAINS)["images"]["youtube_decoder"] == "youtube_decoderimg")

# the email fallback
check("an empty graph email falls back to the process's x-tvu-email", rows[3]["email"] == "Bob@Other.org" and rows[3]["domain"] == "other.org")
check("a graph with neither is counted aside, never attributed", s["no_email"] == 1 and all(r["email"] for r in s["rows"]))

# the domain filter's case
x = G.usage_summary(rows, "youtube_decoder", DOMAINS, external=True)
kept = sorted(r["graph_id"] for r in x["rows"])
check("--external drops an internal owner whatever the case of the address", "G3" not in kept and x["internal_dropped"] == 2)
check("a subdomain of an internal domain is internal; a look-alike domain is not", "G7" not in kept and "G8" in kept)
check("one person in two spellings is one user", len([u for u in x["by_user"] if u["domain"] == "customer.com"]) == 1)
check("the per-week trend is keyed by the Monday", x["by_week"] == {"2026-11-02": 2, "2026-11-09": 2})

# the cutoff stop
pages = {0: [graph("A", "2026-11-13T05:00:00Z"), graph("B", "2026-11-13T04:00:00Z")],
         1: [graph("B", "2026-11-13T04:00:00Z"), graph("C", "2026-11-12T04:00:00Z")],
         2: [graph("D", "2026-11-01T00:00:00Z"), graph("E", "2026-10-31T00:00:00Z")],
         3: [graph("F", "2026-10-30T00:00:00Z"), graph("H", "2026-10-29T00:00:00Z")]}
asked = []
def fetch(page):
    asked.append(page)
    return 200, pages.get(page, [])
got, meta = G.usage_walk(fetch, "2026-11-10T00:00:00", limit=2, batch=2)
check("the walk keeps the rows newer than the cutoff, deduplicated", [r["graph_id"] for r in got] == ["A", "B", "C"])
check("it stops at the first row older than the cutoff and is complete", meta["complete"] and meta["pages"] == 3)
check("no batch past the cutoff is asked for", max(asked) <= 3)
got, meta = G.usage_walk(lambda p: (200, pages[0][:1]) if p == 0 else (200, []), "2026-01-01T00:00:00", limit=2, batch=2)
check("a short page ends the walk", meta["complete"] and len(got) == 1)
got, meta = G.usage_walk(lambda p: (200, pages[0]) if p == 0 else (502, []), "2026-01-01T00:00:00", limit=2, batch=2)
check("a failed page leaves the walk incomplete, with what was read", not meta["complete"] and meta["status"] == 502 and len(got) == 2)

# an env without v2, and the command end to end
class FakeUR:
    order = ["prod3", "prod2", "test2"]
    def __init__(self, answer): self.answer = answer
    def get(self, env, path): return self.answer(env, path)
def run(ur, **kw):
    a = argparse.Namespace(**{"type": "youtube", "types": False, "days": 30, "env": None, "external": False, "by": "week", "json": False, **kw})
    out, code = io.StringIO(), 0
    with contextlib.redirect_stdout(out):
        try:
            G.cmd_usage(ur, a)
        except SystemExit as e:
            code = e.code
    return code, out.getvalue()
code, out = run(FakeUR(lambda e, p: (404, None)), env="prod2")
check("an env without v2 exits 0 and says the list cannot be read", code == 0 and "prod2 has no J2N v2" in out)
code, out = run(FakeUR(lambda e, p: (404, None)), env="prod2", json=True)
check("…and --json carries v2: false", code == 0 and json.loads(out)["v2"] is False)
now = G.datetime.datetime.now(G.datetime.timezone.utc)
recent = lambda h: (now - G.datetime.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
live = [graph("L1", recent(1), "Ann@Customer.COM", ("youtube_decoder",)), graph("L2", recent(2), "dev@tvunetworks.com", ("youtube_decoder",)),
        graph("L3", recent(3), "", ("encoder",), pemail="x@y.z"), graph("L4", "2020-01-01T00:00:00Z", "old@customer.com", ("youtube_decoder",))]
seen_paths = []
def answer(env, path):
    seen_paths.append((env, path))
    return 200, {"value": {"entities": live if "page=0&" in path else []}}
code, out = run(FakeUR(answer), external=True)
check("the default env is prod3 and the list is asked with stopped graphs, newest first, no email",
      seen_paths[0][0] == "prod3" and "query_mode=any" in seen_paths[0][1] and "CreatedAt%20DESC" in seen_paths[0][1] and "email=" not in seen_paths[0][1])
check("the answer counts the external graph inside the window only", code == 0 and "1 graphs · 1 users" in out and "Ann@Customer.COM" in out and "old@customer.com" not in out)
check("every answer says what it cannot see", "prod2 has no J2N v2" in out and "counted once, when it was created" in out)
code, out = run(FakeUR(answer), json=True)
j = json.loads(out)
check("--json carries every row with email, domain, graph id, created_at, app and business type",
      [set(r) for r in j["rows"]] == [{"graph_id", "email", "domain", "created_at", "app", "business_type"}] * 2 and j["graphs"] == 2 and j["cannot_see"])
code, out = run(FakeUR(answer), type=None)
check("no type lists the process types seen", code == 0 and "youtube_decoder" in out and "encoder" in out and "3 graphs · 2 types" in out)
code, out = run(FakeUR(answer), days=61)
check("--days beyond the cap is a usage error", code == G.EX_USAGE)

if failures:
    print(f"{len(failures)} failing"); sys.exit(1)
print("graph usage offline: all checks pass")
