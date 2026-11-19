#!/usr/bin/env python3
"""The lanes read and China's line with the China host, offline (invented rows, no call): the host joins the read only
when the site names it and the map its ids; a tag the map does not name stays out of the lanes and is counted; a row
read from the host outranks QA's report and says where and when it was read; the lane's bundle is the newest the map
places on it, and unmapped names are shown as read; a host that is not configured or not read leaves the report's
line standing and says which."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "brief"))
import brief as B  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

R = B.R
R._MAP = {"regions": {"china": {"aligns_with": "prod-3", "userservice": None,
                                "lanes": {"prod-2-china": {"shown": "CN Prod2", "line": "2.1"}}}}}
missing = ["site.json services.userservice-cn.url"]
R.cn_missing = lambda env_file=None: list(missing)

# ── which hosts a lanes read asks ────────────────────────────────────────────────────────────────────
check("an unconfigured site reads prod only: the QA host is not read", B.lane_hosts([]) == ("prod",))
missing.clear()
check("configured but no ids in the map: still prod only", B.lane_hosts([]) == ("prod",))
R._MAP["regions"]["china"]["userservice"] = {"service_ids": {"svc": [["mediahub-backend", "backendVersion"]]}}
check("configured and mapped: the China host joins", B.lane_hosts(["--env-file", "x"]) == ("prod", "cn"))

CN_ROWS = [{"service": "mediahub-backend", "tag": "MediaHubProd2", "lane": "prod-2-china", "version": "v2.1.26 build256 2026-10-20 08:00:00", "updated": "2026-10-21 09:00"},
           {"service": "mediahub-backend", "tag": "MediaHubGray", "lane": None, "version": "v2.1.30 build260 2026-10-28 08:00:00", "updated": "2026-10-28 09:00"}]
COM_ROWS = [{"service": "mediahub-backend", "tag": "MediaHubProd2", "lane": "prod-2", "version": "v1.5.9 build11 2026-09-01 08:00:00", "updated": "2026-09-01 08:00"},
            {"service": "mediahub-backend", "tag": "MediaHubProd3", "lane": "prod-3", "version": "v2.1.33 build263 2026-10-26 08:00:00", "updated": "2026-10-26 08:00"}]
asked = []


def run_json(cmd, timeout=None):
    asked.append(cmd[2:])
    host = cmd[cmd.index("--host") + 1]
    if host == "qa":
        raise B.LaneError({"exit": 4})
    return {"rows": CN_ROWS if host == "cn" else COM_ROWS}


B.run_json = run_json
rows, read, errors = B.read_lanes_live(["--env-file", "x"], None)
by = {(r["host"], r.get("lane")): r for r in rows}
check("Prod2 is two rows, one per host, never one", by[("prod", "prod-2")]["version"].startswith("v1.5.9") and by[("cn", "prod-2-china")]["version"].startswith("v2.1.26"))
check("a China tag the map does not name is kept out of the lanes and counted", ("cn", None) not in by
      and any(e["source"] == "versions cn" and "1 tag(s)" in e["error"] for e in errors))
check("the QA host is never asked", read == {"prod": True, "cn": True} and not any(c[c.index("--host") + 1] == "qa" for c in asked))
carried = B.merge_lane_rows([], {}, rows, [], "2026-11-13T10:00:00+08:00")
check("a China row the next read misses is carried, like the other hosts'", [r["state"] for r in carried if r["host"] == "cn"] == ["carried"])

# ── China's line ─────────────────────────────────────────────────────────────────────────────────────
REPORT = {"k": {"lane": "prod-2-china", "service": "mediahub-backend", "version": "v2.1.20 build250 2026-10-10", "at": "2026-10-12T19:00:00+08:00"}}
READ = {"state": "read", "at": "2026-11-13T10:02:00+08:00", "bundles": [
    {"bundleName": "MH 2.1.12 CN2", "bundleId": "1", "createTime": "2026-10-01 09:00:00", "lane": "prod-2-china", "mapped": True},
    {"bundleName": "MH 2.1.13 CN2", "bundleId": "2", "createTime": "2026-10-21 09:00:00", "lane": "prod-2-china", "mapped": True},
    {"bundleName": "MediaHub 2.1.13（CN Prod2）", "bundleId": "3", "createTime": "2026-10-22 09:00:00", "lane": None, "mapped": False}]}
g = B.region_reading("prod-2-china", REPORT, rows, READ)
line = B.region_line(g)
check("the host's row outranks the report", g["source"] == "host" and g["versions"]["mediahub-backend"].startswith("2.1.26"))
check("the difference is taken against the aligned .com lane, not the .com Prod2", [(d["service"], d["behind"]) for d in g["differences"]] == [("mediahub-backend", 7)])
check("the line says the host and the time of the read", "· .cn host " in line and "QA report" not in line)
check("the bundle is the newest the map places on the lane, with its host and time", g["bundle"]["name"] == "MH 2.1.13 CN2"
      and "bundle MH 2.1.13 CN2 (2026-10-21), .cn host 11-13 10:02" in line)
g = B.region_reading("prod-2-china", REPORT, rows, dict(READ, bundles=READ["bundles"][2:]))
check("with none mapped, the newest name is shown as read, unmapped", g["bundle"] is None and g["unmapped"] == 1
      and '"MediaHub 2.1.13（CN Prod2）", unmapped' in B.region_line(g))
com_only = [r for r in rows if r["host"] != "cn"]
g = B.region_reading("prod-2-china", REPORT, com_only, {"state": "not configured", "bundles": [], "at": None})
check("not configured: the report's line stands and says so", g["source"] == "report" and "QA report 2026-10-12 (.cn host not configured)" in B.region_line(g)
      and "bundle" not in B.region_line(g))
g = B.region_reading("prod-2-china", REPORT, com_only, {"state": "not read", "bundles": [], "at": None})
check("not read: the report's line stands and says so", "(.cn host not read)" in B.region_line(g))
g = B.region_reading("prod-2-china", REPORT, com_only, READ)
check("bundles read, lanes not mapped: both are said", "(.cn host: lanes not mapped)" in B.region_line(g) and "bundle MH 2.1.13 CN2" in B.region_line(g))
g = B.region_reading("prod-2-china", {}, com_only, {"state": "not configured", "bundles": [], "at": None})
check("no report and no host: the line still names the lane and why", "no QA report names its versions yet (.cn host not configured)" in B.region_line(g))
g = B.region_reading("prod-2-china", REPORT, com_only)
check("a reading made without asking the host renders as it did", B.region_line(g).endswith("· QA report 2026-10-12 · differs: mediahub-backend 2.1.20 build 250 vs 2.1.33 build 263"))

# ── the bundle read is asked once per run and a failure is one error ─────────────────────────────────
B._CHINA.clear(); asked.clear(); errs = []
B.run_json = lambda cmd, timeout=None: asked.append(cmd[2:]) or {"bundles": READ["bundles"], "read_at": READ["at"]}
a, b = B.china_read(["--env-file", "x"], errs), B.china_read(["--env-file", "x"], errs)
check("one bundle read per run, from the China host by name", len(asked) == 1 and asked[0][2:6] == ["bundles", "--host", "cn", "--limit"] and a is b)
B._CHINA.clear()
def down(cmd, timeout=None):
    raise B.LaneError({"exit": 4})
B.run_json = down
c = B.china_read(["--env-file", "x"], errs)
check("a failed bundle read is a state and one error, never an exception", c["state"] == "not read" and [e["source"] for e in errs] == ["bundles cn"])
B._CHINA.clear(); missing.append("x")
check("not configured asks nothing", B.china_read([], errs)["state"] == "not configured" and len(errs) == 1)
sys.exit(1 if failures else 0)
