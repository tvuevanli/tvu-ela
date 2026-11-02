#!/usr/bin/env python3
"""The lanes page over several lines, offline: which lines the page follows, a bundle name's lane by line, one table
per line each with its own next train, the morning's table unchanged with a pointer to the others."""
import datetime, io, os, sys, tempfile, types, contextlib
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "brief"))
import brief as B  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

B.R._MAP = {"lines": {
    "2.1": {"lanes": {"qa": "qa-cn3", "daily": "daily-wed", "prod": "prod-3"}, "bundle_line": "mh2.1@", "bundle_lanes": {"qa": "qa", "daily": "daily-wed"}, "decided": "yes"},
    "2.0": {"lanes": {"qa": "qa-cn2", "daily": "daily-stage", "prod": "prod-8"}, "bundle_line": "mh2.0@", "bundle_lanes": {"qa": "qa", "daily": "stage"}, "decided": "yes"},
    "1.5": {"lanes": {"qa": "qa-cn1", "daily": "daily-fri", "prod": "prod-2"}, "bundle_line": "mh1.5@"},
    "1.1": {"lanes": {"qa": "qa-cn1", "daily": "daily-fri", "prod": "prod-9"}, "note": "prod tracking only"},
    "2.2": {"label": "release:mh-2.2", "note": "label only"}}, "regions": {}}
check("the page follows the lines whose lanes are decided, newest first; placeholders and a line without lanes are skipped",
      B.followed_lines() == ["2.1", "2.0"])
cfgs = {l: B.R.rmap("lines")[l] for l in B.followed_lines()}
check("a bundle name finds its lane through its line's tokens",
      (B.bundle_lane("mh2.0@stage-s3-d12", cfgs), B.bundle_lane("mh2.1@qa-q26", cfgs), B.bundle_lane("mh2.1@daily-wed-s2-d47", cfgs), B.bundle_lane("MediaHub 2.1.15", cfgs))
      == ("daily-stage", "qa-cn3", "daily-wed", None))

def row(service, lane, version, host="prod"):
    return {"service": service, "lane": lane, "version": version, "host": host, "tag": ""}
rows = [row("mediahub-backend", "prod-3", "v2.1.36 build267"), row("mediahub-backend", "daily-wed", "v2.1.36 build267"), row("mediahub-backend", "qa-cn3", "v2.1.38 build269", "qa"),
        row("mediahub-backend", "prod-8", "v2.0.10 build261"), row("mediahub-backend", "daily-stage", "v2.0.10 build261"), row("mediahub-backend", "qa-cn2", "v2.0.11 build268", "qa"),
        row("mediahub-frontend", "prod-8", "v2.2.72.18 build166"), row("mediahub-frontend", "daily-stage", "v2.2.72.16 build141"), row("mediahub-frontend", "qa-cn2", "v2.2.72.18 build166", "qa")]
def no_read(cmd, timeout=600):
    raise B.LaneError("offline")
B.run_json = no_read
pending = {"2.1|daily-wed|prod-3": {"line": "2.1", "from": "daily-wed", "to": "prod-3", "closed": False, "refreshed": "r", "report": "/r/a.json",
                                   "candidate": {"label": "Wednesday (build 78) → prod-3", "versions": {"mediahub-backend": {"version": "2.1.36+267"}}, "bundle": "mh2.1@daily-wed-s2-d47"}},
           "2.0|qa-cn2|prod-8": {"line": "2.0", "from": "qa-cn2", "to": "prod-8", "closed": False, "refreshed": "r", "report": "/r/b.json",
                                 "candidate": {"label": "hotfix backend 2.0.11 (MH-3640)", "versions": {"mediahub-backend": {"version": "2.0.11+268"}}}}}
args = types.SimpleNamespace(promote_report=None)
errors = []
outs = [B.line_matrix(l, args, [], rows, None, {}, {}, pending, errors) for l in B.followed_lines()]
check("each line's table has its own lanes and its own next train from its pending record",
      outs[0]["lanes"] == ["prod-3", "daily-wed", "QA-AWS3", "Wednesday (build 78) → prod-3"] and outs[1]["lanes"] == ["prod-8", "daily-stage", "qa-cn2", "hotfix backend 2.0.11 (MH-3640)"])
be = lambda o: next(r for r in o["rows"] if r.get("service") == "mediahub-backend")  # noqa: E731
check("the next-train cell is the record's version", be(outs[0])["cells"][3]["version"] == "2.1.36+267" and be(outs[1])["cells"][3]["version"] == "2.0.11+268")
check("the bundle row carries the candidate's bundle when it names one, a dash otherwise",
      outs[0]["rows"][0]["cells"][3]["text"] == "mh2.1@daily-wed-s2-d47" and outs[1]["rows"][0]["cells"][3]["text"] == "—")
check("an unreadable bundle list is 'not read', never blank", outs[1]["rows"][0]["cells"][0]["text"] == "not read" and any(e["source"].startswith("bundles") for e in errors))
check("a stage frontend behind prod is an inversion in 2.0's section only",
      B.out_of_order(outs[1])[0] == ["mediahub-frontend: daily-stage 2.2.72.16+141 is below prod-8 2.2.72.18+166"] and B.out_of_order(outs[0])[0] == [])
old_shape = {"line": "2.1", "from": "daily-wed", "to": "prod-3", "closed": False, "candidate": {"label": "next train → prod-3", "versions": {}}}
o = B.line_matrix("2.0", args, [], rows, None, {}, {}, old_shape, [])
check("the old single-record file gives another line no next train", o["lanes"] == ["prod-8", "daily-stage", "qa-cn2"] and o["pending"] is None)
plain = B.line_matrix("2.1", args, [], rows, None, {}, {}, {"label": "a plain file", "versions": {"mediahub-backend": "2.1.36+267"}}, [])
check("a plain {label, versions} file still names the morning's line", plain["lanes"][-1] == "a plain file")

# the page: one section per line, differences per line, one movements table
with tempfile.TemporaryDirectory() as d:
    site = {"reports": os.path.join(d, "reports"), "runtime": os.path.join(d, ".ela")}
    os.makedirs(os.path.join(d, ".ela", "runner"))
    B.day_plan = lambda date, doc=None: {}
    B.qa_cycle_block = lambda now, runtime: ["", "*QA cycle*"]
    calls = []
    def fake_pair(env, a, b, line=B.LINE):
        calls.append((line, a, b))
        return {"lanes": {"from": a, "to": b}, "delta": {"services": []}, "tickets": {"tickets": []}, "evidence": {}}
    B.pair_report = fake_pair
    path = B.write_lanes_page(outs, site, [], os.path.join(d, ".ela", "runner"), {})
    page = open(path, encoding="utf-8").read()
    check("the page heads with the lines it follows", "· lines 2.1, 2.0*" in page)
    check("one section per line, in order, each with its table",
          page.index("## Line 2.1 · prod-3 ← daily-wed ← QA-AWS3") < page.index("| | prod-3 | daily-wed | QA-AWS3 | Wednesday (build 78) → prod-3 |")
          < page.index("## Line 2.0 · prod-8 ← daily-stage ← qa-cn2") < page.index("| | prod-8 | daily-stage | qa-cn2 | hotfix backend 2.0.11 (MH-3640) |"))
    check("the QA cycle follows the first line only", page.count("*QA cycle*") == 1 and page.index("*QA cycle*") < page.index("## Line 2.0"))
    check("differences are read for each line's two pairs and headed by line",
          sorted(calls) == [("2.0", "daily", "prod"), ("2.0", "qa", "daily"), ("2.1", "daily", "prod"), ("2.1", "qa", "daily")]
          and "### 2.1 · daily ahead of prod" in page and "### 2.0 · qa ahead of daily" in page)
    check("one movements table", page.count("## Movements, 14 days") == 1)
# the morning's table: unchanged, with one pointer line to the other lines
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    print(B.render_matrix(dict(outs[0], same=[], gate=None)))
check("the morning's table is 2.1's", buf.getvalue().startswith("| | prod-3 | daily-wed | QA-AWS3 | Wednesday (build 78) → prod-3 |"))
sys.exit(1 if failures else 0)
