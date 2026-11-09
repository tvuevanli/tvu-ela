#!/usr/bin/env python3
"""The fact store offline (fixtures, no network): a first refresh writes each source's watermark and content; a second
refresh reads forward from the watermark and fetches nothing already stored; a source that fails keeps its content
and records a gap; the serving rules of each source answer from the store and fall to live when it is stale."""
import datetime, json, os, shutil, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="ela-facts-")
os.environ["ELA_FACTS_RUNTIME"] = TMP
os.environ["ELA_FACTS_QUIET"] = "1"
os.environ.pop("ELA_FACTS_FRESH", None)
for d in ("facts", "jira", "slack", "mail", "release", "gdoc"):
    sys.path.insert(0, os.path.join(ROOT, "skills", d))
import facts as F  # noqa: E402
import jira as J  # noqa: E402
import slack as S  # noqa: E402
import mail as M  # noqa: E402
import release as R  # noqa: E402
import runtime as RT  # noqa: E402
RT.refresh = lambda env_file, lanes=None: {"lanes": {"prod-3": {"ur-caller": {"chain_status": "proven"}}}, "gaps": []}

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

calls = {"jira": 0, "slack": 0, "mail": 0, "release": 0}
NOW = datetime.datetime.now().astimezone()
STAMP = NOW.strftime("%Y-%m-%dT%H:%M:%S.000+0800")


# ── jira: a sweep of two issues, one cached key that moved ──────────────────────────────────────────
ISSUES = {"MH-1": {"key": "MH-1", "fields": {"summary": "one", "updated": STAMP, "comment": {"comments": [{"id": "9", "created": STAMP, "author": {"displayName": "QA"}, "body": "ok"}]}},
                   "changelog": {"histories": [{"created": STAMP, "author": {"displayName": "Dev"}, "items": [{"field": "status", "fromString": "Open", "toString": "Done"}]}]}},
          "MH-2": {"key": "MH-2", "fields": {"summary": "two", "updated": STAMP, "comment": {"comments": []}}, "changelog": {"histories": []}}}
def fake_search_changed(creds, project, since, limit=400, fields=None):
    calls["jira"] += 1
    return list(ISSUES.values()) if project == "MH" else []
def fake_api_get(creds, path, params=None):
    calls["jira"] += 1
    if path.endswith("/comment"):
        return {"comments": []}
    if "/search/jql" in path:
        return {"issues": [], "isLast": True}
    key = path.rsplit("/", 1)[-1]
    return {"key": key, "fields": {"summary": key, "updated": STAMP}}
J.search_changed, J.api_get = fake_search_changed, fake_api_get
J.load_env = lambda env_file: {"JIRA_BASE_URL": "https://jira.example", "JIRA_EMAIL": "x", "JIRA_TOKEN": "y"}
# a stale key in the cache: MH-1 read before it moved
F.write_json(os.path.join(F.store_dir("jira", "issues"), "MH-1.json"), {"key": "MH-1", "fields": {}, "updated": "2020-01-01T00:00:00+00:00",
                                                                        "read_at": "2020-01-01T00:00:00+00:00", "has_comments": True})

# ── slack: one channel, one thread ─────────────────────────────────────────────────────────────────
TS = f"{NOW.timestamp() - 3600:.6f}"
PARENT = {"ts": TS, "user": "U1", "text": "hello <@U2>", "reply_count": 1, "latest_reply": f"{NOW.timestamp() - 1800:.6f}", "reply_users": ["U2"]}
S.token = lambda env_file: "xoxb-test"
S.list_channels = lambda tok, fresh=False: [{"id": "C1", "name": "general", "member": True}]
def fake_fetch_history(tok, ch, oldest):
    calls["slack"] += 1
    return [dict(PARENT)]
S.fetch_history = fake_fetch_history
def fake_call(method, tok, _soft=False, **params):
    calls["slack"] += 1
    if method == "conversations.replies":
        return {"messages": [dict(PARENT), {"ts": PARENT["latest_reply"], "user": "U2", "text": "hi"}]}
    if method == "users.info":
        return {"user": {"id": params["user"], "profile": {"real_name": params["user"]}}}
    return {"ok": True}
S.call = fake_call

# ── mail: three standing searches, four messages ───────────────────────────────────────────────────
MAILS = {"m1": ("[Release Mediahub QA-AWS3] build 80", 0), "m2": ("Daily Test Report for TVU MediaHub AWS CN3", 1),
         "m3": ("Re: something sent", 2), "m4": ("[Release Mediahub daily-wed] build 12", 3)}
class FakeGoogle:
    def __init__(self, env_file=None): pass
    def need(self, scope): pass
    def get(self, url, raw=False, **params):
        calls["mail"] += 1
        if url.endswith("/messages"):
            q = params.get("q", "")
            if "subject:Release" in q: ids = ["m1", "m4"]
            elif "test report" in q: ids = ["m2"]
            else: ids = ["m3"]
            return {"messages": [{"id": i} for i in ids]}
        mid = url.rsplit("/", 1)[-1]
        subj, days = MAILS[mid]
        return {"id": mid, "threadId": "t" + mid, "snippet": "", "internalDate": str(int((NOW.timestamp() - days * 86400) * 1000)),
                "payload": {"headers": [{"name": "Subject", "value": subj}, {"name": "From", "value": "qa@example"}, {"name": "Date", "value": "x"}],
                            "mimeType": "text/plain", "body": {"data": "aGVsbG8"}}}
M.Google = FakeGoogle

# ── release: lanes on prod, a refused qa host, Jenkins and bundles ─────────────────────────────────
class FakeUS:
    def __init__(self, env_file, host="qa"):
        self.kind = "prod" if host == "prod" else "qa"
        if self.kind == "qa":
            raise SystemExit(4)
    def call(self, path, payload=None):
        calls["release"] += 1
        if "tagBundle/page" in path:
            return {"result": {"list": [{"bundleName": "mh2.1@qa-q1", "bundleId": "1", "createTime": 1}]}}
        return {"result": [{"tagName": "MediaHubProd3", "updateTime": 0, "version": "v2.1.36 build300 2026-11-01 00:00:00"}]}
R.US = FakeUS
R._MAP = {"service_ids": {"1": [["mediahub-backend", "version"]]}, "qa_service_ids": {"1": [["mediahub-backend", "version"]]},
          "lane_map": {"prod": {"MediaHubProd3": "prod-3"}}, "jobs": {"media-hub-v4": "mediahub-backend"}, "lines": {"2.1": {"bundle_line": "mh2.1@", "lanes": {"prod": "prod-3"}}},
          "gateway_versions": {}}
R.lane_of = lambda kind, tag: "prod-3"
def fake_http(url, payload=None, cookie=None, timeout=20):
    calls["release"] += 1
    return 200, {"builds": [{"number": 300, "displayName": "2.1.36 build300", "result": "SUCCESS", "timestamp": 0, "url": "u",
                             "actions": [{"lastBuiltRevision": {"branch": [{"name": "release", "SHA1": "abc123abc123abc"}]}}]}]}
R.http = fake_http

# ── the first refresh ───────────────────────────────────────────────────────────────────────────────
class A: env_file = None; source = None; fresh = False; json = False
F.cmd_refresh(A())
first = {s: dict(F.watermark(s)) for s in F.SOURCES}
check("every source has a watermark with a read time", all(first[s].get("at") for s in F.SOURCES))
changes = F.read_json(os.path.join(F.store_dir("jira"), "changes.json"))
check("the Jira sweep is a list of Jira-shaped issues with comments and read_at", isinstance(changes, list) and len(changes) == 2
      and changes[0].get("changelog") is not None and "comments" in changes[0] and changes[0].get("read_at"))
mh1 = F.read_json(os.path.join(F.store_dir("jira", "issues"), "MH-1.json"))
check("a cached key the sweep says moved is read again", mh1 and mh1["read_at"] != "2020-01-01T00:00:00+00:00")
check("the incidents query and the owner name are in the store", os.path.exists(os.path.join(F.store_dir("jira", "queries"), "incidents.json"))
      and os.path.exists(os.path.join(F.store_dir("jira"), "owner.json")))
chan = F.read_json(os.path.join(F.store_dir("slack"), "C1.json"))
check("the channel store holds the parent and its replies", chan and TS in chan["messages"] and TS in chan["replies"] and chan.get("read_at"))
idx = F.read_json(os.path.join(F.store_dir("mail"), "index.json"))
check("the three standing searches are indexed", set(idx) == {"release", "test-report", "sent"} and idx["release"]["ids"] == ["m1", "m4"])
check("every id is stored once", sorted(f[:-5] for f in os.listdir(F.store_dir("mail", "messages"))) == ["m1", "m2", "m3", "m4"])
lanes = F.read_json(os.path.join(F.store_dir("lanes"), "envs-prod.json"))
check("the prod lanes are stored with their read time", lanes and lanes["rows"][0]["lane"] == "prod-3" and lanes.get("at"))
qa = F.read_json(os.path.join(F.store_dir("lanes"), "envs-qa.json"))
check("the refused qa host is a gap with its exit code", qa and qa.get("gap", {}).get("exit") == 4 and "qa" in F.watermark("lanes").get("gap", {}).get("why", ""))
check("Jenkins and the bundles are stored", F.read_json(os.path.join(F.store_dir("builds"), "media-hub-v4.json"))["builds"][0]["number"] == 300
      and F.read_json(os.path.join(F.store_dir("builds", "bundles", "prod"), "mh2.1@.json"))["bundles"])

# ── the second refresh: forward from the watermark, nothing already stored fetched ──────────────────
before = dict(calls)
F.cmd_refresh(A())
second = {s: dict(F.watermark(s)) for s in F.SOURCES}
check("the Jira watermark moves forward (since follows the last read)", second["jira"]["since"] >= first["jira"]["since"] and second["jira"]["at"] >= first["jira"]["at"])
check("no key is re-read when nothing moved since the sweep", second["jira"]["reread"] == 0)
check("no stored mail is fetched again", calls["mail"] - before["mail"] == 3)
check("no thread is read again when its parent did not move", calls["slack"] - before["slack"] == 1)
check("the store's content is the same after the second refresh",
      F.read_json(os.path.join(F.store_dir("mail"), "index.json"))["release"]["ids"] == ["m1", "m4"]
      and len(F.read_json(os.path.join(F.store_dir("jira"), "changes.json"))) == 2)

# ── a failing source keeps its content and records a gap ──────────────────────────────────────────
def broken(*a, **k):
    raise SystemExit(5)
M.refresh_standing = broken
class OnlyMail(A): source = ["mail"]
try:
    F.cmd_refresh(OnlyMail()); code = 0
except SystemExit as e:
    code = e.code
wm = F.watermark("mail")
check("a refresh whose every source failed exits 5", code == 5)
check("the gap names the reason and the previous content stands", wm.get("gap", {}).get("why") == "exit 5"
      and F.read_json(os.path.join(F.store_dir("mail"), "index.json"))["release"]["ids"] == ["m1", "m4"])

# ── serving rules ─────────────────────────────────────────────────────────────────────────────────
cutoff = NOW - datetime.timedelta(days=1)
got = J.stored_changed("MH", cutoff)
check("jira changes serve from the sweep", got and {i["key"] for i in got["issues"]} == {"MH-1", "MH-2"})
check("the rows derived from the store carry the window's events and comments", J.changes_rows(got["issues"], cutoff)[0]["events"][0]["to"] == "Done")
check("a stale cached key is not served", not J.cache_holds("MH-1", {"updated": "2020-01-01T00:00:00+00:00", "read_at": "2020-01-01T00:00:00+00:00"}))
check("a fresh cached key after the sweep is served", J.cache_holds("MH-2", F.read_json(os.path.join(F.store_dir("jira", "issues"), "MH-2.json")) or
                                                             {"updated": J.updated_iso(STAMP), "read_at": F.now_iso()}))
check("the owner-name JQL is served from the store", J.stored_query("assignee = currentUser() ORDER BY updated DESC", 1) is not None)
rows, at = S.history_rows("tok", "C1", NOW.timestamp() - 7200)
check("slack history serves the channel store", rows and rows[0]["ts"] == TS and at == chan["read_at"])
n = calls["slack"]
reps = S.replies_rows("tok", "C1", PARENT)
check("thread replies serve the store without a call", len(reps) == 1 and calls["slack"] == n)
hit = M.stored_search('newer_than:21d subject:("Release Mediahub")', 80)
check("a standing mail query is answered from the store", hit and [r["id"] for r in hit[0]] == ["m1", "m4"])
hit = M.stored_search(f"after:{int(cutoff.timestamp())} before:{int(NOW.timestamp()) + 1} subject:Release", 40)
check("a date-bounded standing query filters by the message date", hit and [r["id"] for r in hit[0]] == ["m1"])
check("a from: query is not servable", M.servable("after:2026/10/01 (from:qa@example OR subject:(test report MediaHub))") is None)
check("in:sent is the third standing search", M.stored_search("in:sent newer_than:10d", 20)[0][0]["id"] == "m3")
check("the prod lanes serve the store", R.stored_envs("prod")["rows"][0]["version"].startswith("v2.1.36"))
check("the qa gap is served as the live read's exit", (R.stored_envs("qa") or {}).get("gap", {}).get("exit") == 4)
check("Jenkins serves the store at the stored depth, and deeper when the job has no more builds", R.stored_builds("media-hub-v4", 80) is not None and R.stored_builds("media-hub-v4", 81) is not None)
F.write_json(os.path.join(F.store_dir("builds"), "media-hub-v4.json"), {"at": F.now_iso(), "job": "media-hub-v4", "service": "x", "limit": 20, "builds": [{}] * 20})
check("a request deeper than a full stored read is not served", R.stored_builds("media-hub-v4", 21) is None and R.stored_builds("media-hub-v4", 20) is not None)
os.environ["ELA_FACTS_MAX_AGE"] = "0"
check("a stale store is not served", R.stored_envs("prod") is None and J.stored_changed("MH", cutoff) is None and M.stored_search("in:sent", 5) is None)
os.environ.pop("ELA_FACTS_MAX_AGE")
line = F.read_at_line()
check("the facts line names every source with its time", all(s in line for s in F.SOURCES))

shutil.rmtree(TMP, ignore_errors=True)
if failures:
    print(f"facts: {len(failures)} check(s) failed"); sys.exit(1)
print("facts: all offline checks passed")
