#!/usr/bin/env python3
"""promote offline: the qa host does not admit ela, so the from-lane rows are the brief's mail rows (QA's report, the
release thread) from the last saved lane read; the gap says the source; the version table carries a source column; no
stop. With nothing naming the lanes the host is unreadable as before."""
import datetime, json, os, sys, tempfile, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "promote"))
import promote as P  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

P.R._MAP = {"lines": {"2.1": {"lanes": {"qa": "qa-cn3", "daily": "daily-wed", "prod": "prod-3"}}},
            "hosts": {"lane_classes": {"qa": ["qa-cn3"], "daily": ["daily-wed"], "prod": ["prod-3"]}},
            "version_rules": {"app_layer": {"slugs": ["mediahub-backend", "unified-streaming"]}, "semver_build": {}}}
P.B.R._MAP = P.R._MAP
REPORTED = {"service": "mediahub-backend", "tag": None, "lane": "qa-cn3", "version": "v2.1.39 build271 2026-11-02 09:39:26", "host": "mail",
            "state": "reported", "at": "2026-11-03T19:07:07+08:00", "source": "QA report", "subject": "Daily Test Report on 11-3"}
BUILT = {"service": "unified-streaming", "tag": None, "lane": "qa-cn3", "version": "v2.1.82 build372", "host": "mail", "state": "built",
         "at": "2026-11-04T17:40:00+08:00", "source": "release thread"}
PROD = [{"service": "mediahub-backend", "tag": "MediaHubWednesday", "lane": "daily-wed", "version": "v2.1.38 build270 2026-10-30 09:45:26", "updated": ""},
        {"service": "unified-streaming", "tag": "UnifiedResourcesWednesday", "lane": "daily-wed", "version": "v2.1.80 build370 2026-10-30 09:45:15", "updated": ""}]

class NoQA(Exception):
    pass

def fake_us(env_file, host):
    if host == "qa":
        sys.exit(4)
    return types.SimpleNamespace(kind="prod")

with tempfile.TemporaryDirectory() as d:
    os.makedirs(os.path.join(d, "runner"))
    json.dump({"date": "2026-11-04", "at": "2026-11-04T08:10:45+08:00", "read": {"prod": True}, "rows": [REPORTED, BUILT]},
              open(os.path.join(d, "runner", "versions-2026-11-04.json"), "w"))
    json.dump({"qa-cn3|mediahub-backend|2.1.39 build 271": {"lane": "qa-cn3", "service": "mediahub-backend", "version": REPORTED["version"],
                                                            "at": REPORTED["at"], "verdict": "pass", "subject": REPORTED["subject"]}},
              open(os.path.join(d, "runner", "qa-tested.json"), "w"))
    real = (P.R.US, P.R.lane_versions, P.R.site)
    P.R.US, P.R.lane_versions, P.R.site = fake_us, lambda us: list(PROD), lambda: {"runtime": d}
    try:
        gaps = []
        a = types.SimpleNamespace(line="2.1", src="qa", dst="daily", scope="app", env_file=None)
        res = P.collect_lanes(a, gaps)
        be = next(s for s in res["services"] if s["service"] == "mediahub-backend")
        ur = next(s for s in res["services"] if s["service"] == "unified-streaming")
        check("the qa host's login failure is a gap that names the source, not an unreadable host",
              [g["kind"] for g in gaps] == ["host_from_mail"] and "qa login failed" in gaps[0]["detail"] and "newest 2026-11-04 17:40" in gaps[0]["detail"])
        check("the from-lane rows are QA's report and the release, each with its source and time",
              be["from"]["host"] == "mail" and be["from"]["source"] == "QA reported 11-03 19:07" and be["from"]["at"] == REPORTED["at"]
              and ur["from"]["source"] == "built 11-04 17:40 (release thread), no QA report" and be["relation"] == "from_ahead")
        check("the to-lane is a live read", be["to"]["source"] == "live" and res["hosts_read"] == {"prod": True, "qa": "mail"})
        check("the source column names the lane and the source", P.source_cell(be) == "qa-cn3: QA reported 11-03 19:07" and P.source_cell({"from": be["to"], "to": be["to"], "from_lane": "x", "to_lane": "y"}) == "live")
        F = P.assess(types.SimpleNamespace(purpose="regular", scope="app"), res, {"services": []}, {"tickets": [], "label": "", "referenced_only": {}}, {"keys": {}}, None, gaps)
        check("the gap is a medium finding, never a stop",
              [f["severity"] for f in F if f["kind"] == "lane_from_mail"] == ["medium"] and not [f for f in F if f["severity"] == "stop"])
        md = P.render_md({"line": "2.1", "from": "qa-cn3", "to": "daily-wed", "purpose": "regular", "scope": "app", "generated_at": "t", "lanes": res,
                          "delta": {"services": []}, "tickets": {"tickets": []}, "evidence": {"since": None, "keys": {}}, "findings": F, "gaps": gaps,
                          "counts": {"commits": 0, "tickets": 0, "findings": {k: 0 for k in P.SEV}}, "bundles": None})
        check("the review's version table carries the source column and the hosts line says the qa lanes are from mail",
              "| service | qa-cn3 | daily-wed | relation | source |" in md and "| mediahub-backend | 2.1.39+271 | 2.1.38+270 | from_ahead | qa-cn3: QA reported 11-03 19:07 |" in md
              and "hosts read: prod ok, qa from mail" in md)
        os.remove(os.path.join(d, "runner", "versions-2026-11-04.json"))
        os.remove(os.path.join(d, "runner", "qa-tested.json"))
        gaps = []
        res = P.collect_lanes(a, gaps)
        check("with no report or release naming the lanes, the host is unreadable as before",
              [g["kind"] for g in gaps] == ["host_unreadable"] and res["hosts_read"]["qa"] is False and "no QA report" in gaps[0]["detail"])
    finally:
        P.R.US, P.R.lane_versions, P.R.site = real

sys.exit(1 if failures else 0)
