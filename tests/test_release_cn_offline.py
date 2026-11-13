#!/usr/bin/env python3
"""The China host beside the .com ones, offline: recorded answers per host in userservice's shape (invented names, no
address, no login). The site without the China names still answers for .com and says once what to add; a name from the
China host means a lane only where the map says so and is otherwise shown as read, unmapped; "Prod2" on the China host
never becomes the .com prod-2; a China read that fails leaves the .com rows whole; the store keeps the hosts apart."""
import contextlib, io, json, os, sys, tempfile, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="ela-release-cn-")
os.environ["ELA_FACTS_RUNTIME"] = TMP
os.environ["ELA_FACTS_QUIET"] = "1"
for k in ("ELA_FACTS_FRESH", "ELA_ENV_FILE", "TVU_CN_ACCOUNT", "TVU_CN_PASSWORD", "TVU_CN_SID", "TVUTEST_SID", "TVUTEST_ACCOUNT", "TVUTEST_PASSWORD"):
    os.environ.pop(k, None)
sys.path.insert(0, os.path.join(ROOT, "skills", "release"))
import release as R  # noqa: E402

REC = json.load(open(os.path.join(ROOT, "tests", "fixtures", "release-cn", "hosts.json"), encoding="utf-8"))
URL = {"prod": "https://us.invalid", "qa": "https://us-qa.invalid", "cn": "https://us-cn.invalid"}
ENV = os.path.join(TMP, "env")
open(ENV, "w").close()
SITE = {"env": ENV, "services": {"userservice": {"url": URL["prod"]}, "userservice-test": {"url": URL["qa"]}}}
R.site = lambda: SITE
R.SESSION_FILE = os.path.join(TMP, "session.json")
json.dump({"tvu": {"sid": "s", "obtained_at": "2026-11-13T00:00:00Z", "rejected_at": None}}, open(R.SESSION_FILE, "w"))
LANES = {"prod-2-china": {"shown": "CN Prod2", "line": "2.1"}, "prod-1-china": {"shown": "CN Prod1", "retiring": True}}
BASE = {"hosts": {"prod": {"match": "endswith", "tag_suffix_to_lane": {"Prod2": "prod-2", "Prod3": "prod-3"}}, "qa": {"match": "exact", "tag_to_lane": {}}},
        "service_ids": {"svc-com-backend": [["mediahub-backend", "backendVersion"]]}, "qa_service_ids": {},
        "regions": {"china": {"aligns_with": "prod-3", "userservice": None, "lanes": LANES}}}
MAPPED = {"service_ids": {"svc-cn-backend": [["mediahub-backend", "backendVersion"]]}, "match": "endswith",
          "tag_suffix_to_lane": {"Prod2": "prod-2-china"}, "bundle_line": "",
          "bundles": [{"match": r"^MH 2\.1\.\d+ CN2$", "lane": "prod-2-china", "line": "2.1"}]}
down, asked = set(), []


def set_map(cn=None):
    R._MAP = json.loads(json.dumps(BASE))
    R._MAP["regions"]["china"]["userservice"] = cn


def http(url, payload=None, cookie=None, timeout=20):
    asked.append(url)
    host = next(k for k, v in URL.items() if url.startswith(v + "/"))
    if host in down or host == "qa":                        # QA admits no account, as since 2026-11-04
        return 401, {"errorCode": "401", "errorInfo": "no login"}
    path = url[len(URL[host]):]
    if path.startswith("/userAuth/token/getToken"):
        return 200, {"result": {"token": "fixture-session"}}
    if path.startswith("/userGroup/user-group/tagBundle/page"):
        rows = [b for b in REC[host]["bundles"] if (payload or {}).get("bundleName", "") in b["bundleName"]]
        return 200, {"result": {"list": rows}}
    if path.startswith("/userGroup/user-group/service/list"):
        return 200, {"result": REC[host]["services"]}
    if path.startswith("/userGroup/user-group/tag/getTagVersionList"):
        return 200, {"result": REC[host]["tags"].get(path.split("serviceId=")[1], [])}
    return 404, "no such path"


R.http = http
failures = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


def run(cmd, **kw):
    """(exit, stdout, stderr) of one verb with the parser's defaults."""
    a = types.SimpleNamespace(env_file=ENV, host=None, line=None, limit=50, fresh=True, raw=False, json=True, service=None)
    a.__dict__.update(kw)
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cmd(a)
    except SystemExit as e:
        code = e.code
    return code, out.getvalue(), err.getvalue()


# ── the site without the China names ─────────────────────────────────────────────────────────────────
set_map()
check("an unconfigured site names both things to add", R.cn_missing(ENV) == ["site.json services.userservice-cn.url", "TVU_CN_ACCOUNT / TVU_CN_PASSWORD in the env file"])
code, out, err = run(R.cmd_bundles)
j = json.loads(out)
check("unconfigured: the .com answer stands, exit 0", code == 0 and {b["host"] for b in j["bundles"]} == {"prod"} and j["count"] == 1)
check("unconfigured: said once, as a note, never a gap", err.count("China host not configured") == 1 and len(j["notes"]) == 1
      and all(g["host"] != "cn" for g in j["gaps"]) and "services.userservice-cn.url" in j["notes"][0] and "TVU_CN_ACCOUNT" in j["notes"][0])
check("unconfigured: the China host is never called", not any(u.startswith(URL["cn"]) for u in asked))
check("a .com host that refuses is a gap beside whole rows", [g["host"] for g in j["gaps"]] == ["qa"] and "not read: qa" in err)
check("every row says its host and when it was read", all(b.get("host") and b.get("read_at") for b in j["bundles"]))
code, out, err = run(R.cmd_bundles, host="cn")
check("unconfigured: --host cn exits 2 with the same line", code == R.EX_USAGE and err.startswith("China host not configured: add ") and not out)
code, out, err = run(R.cmd_envs)
check("unconfigured: versions answer for .com", code == 0 and {r["lane"] for r in json.loads(out)["rows"]} == {"prod-2", "prod-3"} and err.count("China host not configured") == 1)
code, out, err = run(R.cmd_bundles, host="prod", line="MediaHub 2.1")
check("a named host keeps its shape", code == 0 and json.loads(out)["host"] == "prod" and "gaps" not in json.loads(out) and not err)
sys.path.insert(0, os.path.join(ROOT, "skills", "facts"))
import facts as FA  # noqa: E402
check("the facts pass skips an unconfigured China host as a state", FA.cn_state(R, ENV) == "not configured")
SITE["services"]["userservice-cn"] = {"url": URL["cn"]}
check("the address alone leaves the login missing", R.cn_missing(ENV) == ["TVU_CN_ACCOUNT / TVU_CN_PASSWORD in the env file"])
open(ENV, "w").write("TVU_CN_ACCOUNT=fixture@example.invalid\nTVU_CN_PASSWORD=fixture\n")
check("address and login: configured", R.cn_missing(ENV) == [])

# ── configured, the map still silent: names shown as read ─────────────────────────────────────────────
code, out, err = run(R.cmd_bundles)
j = json.loads(out)
cn = [b for b in j["bundles"] if b["host"] == "cn"]
check("the China rows come from the China host, all of them", code == 0 and [b["bundleName"] for b in cn] == ["MH 2.1.13 CN2", "MediaHub 2.1.13（CN Prod2）", "mh1.5@ga-s1-d3"])
check("with no map rule every China name is unmapped, none dropped", all(b["mapped"] is False and b["lane"] is None for b in cn))
check("a name in a .com shape is not read as one", R.cn_bundle_lane("MediaHub 2.1.13 (CN Prod2)") == (None, None)
      and R.bundle_lane("MediaHub 2.1.13 (CN Prod2)") == "prod-2-china")
check("the China host is asked its own default query, not the .com line", [h["query"] for h in j["hosts"]] == [R.DEFAULT_LINE, ""])
code, out, err = run(R.cmd_bundles, host="cn", raw=True, json=False)
check("--raw quotes the names as read and maps nothing", code == 0 and '"MediaHub 2.1.13（CN Prod2）"' in out and "unmapped" not in out and "prod-2-china" not in out)
code, out, err = run(R.cmd_bundles, raw=True)
check("--raw needs a host", code == R.EX_USAGE)
code, out, err = run(R.cmd_envs)
j = json.loads(out)
check("unmapped service ids are a note; .com versions whole", code == 0 and not any(r["host"] == "cn" for r in j["rows"])
      and j["notes"] == [R.cn_unmapped_note()] and not any(g["host"] == "cn" for g in j["gaps"]))
code, out, err = run(R.cmd_envs, host="cn")
check("--host cn says which map lines are missing", code == R.EX_USAGE and "service_ids" in err and "--raw" in err)
code, out, err = run(R.cmd_envs, host="cn", raw=True)
check("envs --raw lists the host's services as named", code == 0 and [s["serviceId"] for s in json.loads(out)["services"]] == ["svc-cn-backend", "svc-cn-streaming"])
code, out, err = run(R.cmd_envs, host="cn", raw=True, service="MediaHub")
check("envs --raw with a service shows its tag records", [t["tagName"] for t in json.loads(out)["services"][0]["tags"]] == ["MediaHubProd2", "MediaHubGray"])

check("the facts pass reads its bundles while its lanes are unmapped", FA.cn_state(R, ENV) == "lanes not mapped")

# ── the map names the China host's ids, tags and bundles ─────────────────────────────────────────────
set_map(MAPPED)
check("the facts pass reads it whole once the map names its ids", FA.cn_state(R, ENV) is None)
code, out, err = run(R.cmd_envs)
rows = json.loads(out)["rows"]
cn = {r["tag"]: r for r in rows if r["host"] == "cn"}
check("Prod2 on the China host is prod-2-china, read from cn", cn["MediaHubProd2"]["lane"] == "prod-2-china" and cn["MediaHubProd2"]["region"] == "china")
check("Prod2 on the .com host stays prod-2: two rows, never merged", sorted((r["host"], r["lane"]) for r in rows if r["tag"] == "MediaHubProd2")
      == [("cn", "prod-2-china"), ("prod", "prod-2")])
check("a China tag the map does not name stays, unmapped", cn["MediaHubGray"]["lane"] is None and cn["MediaHubGray"]["mapped"] is False)
code, out, err = run(R.cmd_envs, json=False)
check("the text names host and read time per block, and the unmapped tag", "[cn · read " in out and "[prod · read " in out and "unmapped" in out)
set_map(dict(MAPPED, tag_suffix_to_lane={"Prod2": "prod-2"}))
check("a map line that points a China tag at a .com lane is refused", R.lane_of("cn", "MediaHubProd2") is None)
set_map(MAPPED)
code, out, err = run(R.cmd_bundles)
cn = {b["bundleName"]: b for b in json.loads(out)["bundles"] if b["host"] == "cn"}
check("a mapped China bundle shows its lane and the team's name for it", cn["MH 2.1.13 CN2"]["lane"] == "prod-2-china" and cn["MH 2.1.13 CN2"]["shown"] == "CN Prod2"
      and cn["MH 2.1.13 CN2"]["line"] == "2.1")
check("the others stay unmapped", not cn["mh1.5@ga-s1-d3"]["mapped"] and not cn["MediaHub 2.1.13（CN Prod2）"]["mapped"])
code, out, err = run(R.cmd_bundles, json=False)
check("the text gives a block per host with its read time", "# prod — 1 bundle(s), read " in out and "# cn — 3 bundle(s), read " in out
      and "CN Prod2 (prod-2-china)" in out and out.count("unmapped") == 2)

# ── the store keeps the hosts apart ──────────────────────────────────────────────────────────────────
F = R.F
check("lane reads are one file per host", os.path.isfile(os.path.join(TMP, "facts", "lanes", "envs-cn.json")) and os.path.isfile(os.path.join(TMP, "facts", "lanes", "envs-prod.json"))
      and all(r["lane"] != "prod-2" for r in F.read_json(os.path.join(TMP, "facts", "lanes", "envs-cn.json"))["rows"]))
check("bundle lists are one directory per host", os.path.isfile(os.path.join(TMP, "facts", "builds", "bundles", "cn", "_all.json"))
      and os.path.isfile(os.path.join(TMP, "facts", "builds", "bundles", "prod", "mh2.1@.json")))
R.http = lambda url, payload=None, cookie=None, timeout=20: (200, {"result": {"bundleName": url.split("//")[1].split(".")[0], "serviceTagList": []}}) \
    if "getDetail" in url else http(url, payload, cookie, timeout)
same = "1900000000000000015"                                # one id, two hosts, two bundles
d_cn, d_com = R.bundle_detail(R.US(ENV, "cn"), same, fresh=True), R.bundle_detail(R.US(ENV, "prod"), same, fresh=True)
check("the same bundle id on two hosts is two stored details", d_cn["bundleName"] == "us-cn" and d_com["bundleName"] == "us"
      and R.bundle_detail(R.US(ENV, "cn"), same)["bundleName"] == "us-cn" and R.bundle_detail(R.US(ENV, "prod"), same)["bundleName"] == "us")
R.http = http

# ── a China read that fails ──────────────────────────────────────────────────────────────────────────
down.add("cn")
code, out, err = run(R.cmd_bundles)
j = json.loads(out)
check("a failed China read leaves the .com rows whole and says so", code == 0 and [b["bundleName"] for b in j["bundles"]] == ["mh2.1@daily-wed-s1-d60"]
      and [g["host"] for g in j["gaps"]] == ["qa", "cn"] and "not read: cn — " in err and "the other hosts' rows are whole" in err)
code, out, err = run(R.cmd_envs)
check("the same for versions", code == 0 and {r["host"] for r in json.loads(out)["rows"]} == {"prod"} and "not read: cn" in err)
code, out, err = run(R.cmd_bundles, host="cn")
check("--host cn alone exits 4 on a refused login", code == R.EX_AUTH)
down.discard("cn")
check("no write reaches the China host", R.write_refused("/userGroup/user-group/tagBundle/create", "cn") is not None)
check("the fixture session never reaches the output", "fixture-session" not in out + err)
sys.exit(1 if failures else 0)
