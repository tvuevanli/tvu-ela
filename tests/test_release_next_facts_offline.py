#!/usr/bin/env python3
"""`ela release next` reads facts only, offline: under ELA_FACTS_ONLY the store serves whatever it holds and every live
read is refused (Jira, userservice, Jenkins), a Jira key the cache lacks is served from the sweep or a standing query,
promote's Fixed In lookups come from the stored standing query, the must and in-development rows come from the store,
and nothing on the path starts a model session (a static scan of every module it reaches, and gather run with its
subprocesses recorded). No source is read."""
import datetime, json, os, re, subprocess, sys, tempfile, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="ela-next-facts-")
os.environ["ELA_FACTS_RUNTIME"] = TMP
os.environ["ELA_FACTS_QUIET"] = "1"
os.environ.pop("ELA_FACTS_FRESH", None)
os.environ.pop("ELA_FACTS_ONLY", None)
for d in ("facts", "jira", "release", "promote"):
    sys.path.insert(0, os.path.join(ROOT, "skills", d))
import facts as F  # noqa: E402
import jira as J  # noqa: E402
import release as R  # noqa: E402
import nextrel as N  # noqa: E402

fails = []


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        fails.append(what)


def exit_code(fn):
    try:
        fn()
    except SystemExit as e:
        return e.code
    return None


def no_network(*a, **k):
    raise AssertionError("a live read was attempted")


urllib.request.urlopen = no_network
TZ = datetime.timezone(datetime.timedelta(hours=8))
NOW = datetime.datetime.now().astimezone()
OLD = (NOW - datetime.timedelta(days=2)).isoformat(timespec="seconds")

# ── the switch ────────────────────────────────────────────────────────────────
check(not F.fresh(OLD), "without the switch a two-day-old read is stale")
os.environ["ELA_FACTS_ONLY"] = "1"
check(F.facts_only() and F.fresh(OLD) and not F.fresh(None), "under ELA_FACTS_ONLY any stored read is served; no read is still none")
os.environ["ELA_FACTS_FRESH"] = "1"
check(not F.facts_only(), "--fresh (ELA_FACTS_FRESH) wins over facts-only")
del os.environ["ELA_FACTS_FRESH"]
check(exit_code(lambda: F.refuse("jira", "GET /x")) == F.EX_NOT_IN_STORE, "refuse exits 7")

# ── the chokepoints refuse before any network ─────────────────────────────────
CREDS = {"JIRA_BASE_URL": "https://jira.invalid", "JIRA_EMAIL": "e", "JIRA_TOKEN": "t"}
check(exit_code(lambda: J._request_raw(CREDS, "/rest/api/3/search/jql")) == 7, "jira: a live request is refused")
check(exit_code(lambda: R.http("https://jenkins.invalid/job/x/api/json?tree=y")) == 7, "release: Jenkins and every http read refused")
check(exit_code(lambda: R.LazyUS(None, "prod").call("/userGroup/user-group/tagBundle/page", {})) == 7, "release: userservice refused before any login")
check(exit_code(lambda: R._bundle_list(R.LazyUS(None, "prod"), "mh9.9@", 50)) == 7
      and not os.path.exists(R._bundles_path("prod", "mh9.9@")), "a refused bundle list writes no host gap into the store")

# ── the Jira store serves a key the cache lacks ───────────────────────────────
jd = F.store_dir("jira")
FI = J.FIXED_IN_FIELD
sweep = [{"key": "MH-1", "read_at": OLD, "fields": {"summary": "swept", "status": {"name": "Review"}, "updated": "2026-11-24T10:00:00.000+0800"},
          "changelog": {"histories": [{"created": "2026-11-24T09:00:00.000+0800", "items": [{"field": "labels", "fromString": "", "toString": "release:must"}]}]},
          "comments": [{"id": "1", "body": "c"}]}]
F.write_json(os.path.join(jd, "changes.json"), sweep)
fixed = {"jql": J.STANDING["fixed-in"][0], "limit": J.STANDING["fixed-in"][1], "extra": [FI], "at": OLD,
         "issues": [{"key": "MH-2", "fields": {"summary": "from the Fixed In query", "status": {"name": "Done"}, "labels": [],
                                               FI: {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "svc-a@2.1.5"}]}]}}}]}
F.write_json(os.path.join(F.store_dir("jira", "queries"), "fixed-in.json"), fixed)
F.set_watermark("jira", at=OLD, projects=["MH"])
d1 = J.issue_doc(CREDS, "MH-1")
check(d1["fields"]["summary"] == "swept" and d1["comments"] == [{"id": "1", "body": "c"}], "a key out of the cache: the sweep's issue, with its comments")
d2 = J.issue_doc(CREDS, "MH-2")
check(d2["fields"]["summary"] == "from the Fixed In query" and "comments" not in d2, "else the standing query's row, without comments")
check(exit_code(lambda: J.issue_doc(CREDS, "MH-3")) == 7, "a key the store holds nowhere is refused, not read")
got = J.stored_query(J.STANDING["fixed-in"][0], 3000, (FI,))
check(got and got["issues"][0]["key"] == "MH-2", "the standing Fixed In query is served with its extra field")
check(J.stored_query('labels = "release:must" ORDER BY key', 50) is None, "a standing query never stored is not served")

# ── promote: Fixed In from the store, a store miss is unknown, not absent ─────
import promote as P  # noqa: E402
calls = []


def fake_l1(cap, *args, env_file=None, timeout=180):
    calls.append((cap,) + args)
    if args[0] == "jql":
        return True, {"issues": [{"key": "MH-2", "labels": [], "extra": {FI: fixed["issues"][0]["fields"][FI]}},
                                 {"key": "MH-5", "labels": [], "extra": {FI: "svc-a@2.1.50"}}]}, ""
    if args[0] == "read" and args[1] == "MH-2":
        return True, {"key": "MH-2", "fields": {"summary": "s", "status": {"name": "Done"}, FI: "svc-a@2.1.5"}, "url": "u"}, ""
    return False, None, f"jira: GET /x: {F.NOT_IN_STORE} (ELA_FACTS_ONLY)"


P.l1, P.line_cfg, P.load_roster = fake_l1, (lambda line: {}), (lambda: [])
P.scope_slugs = lambda s: ["svc-a"]


class A: line = "2.1"; env_file = None; src = "MediaHub 2.1.1"; dst = "mh2.1@daily-wed-s1-d2"


delta = {"services": [{"service": "svc-a", "builds_between": [{"version": "2.1.5"}],
                       "commits": [{"sha": "abc", "kind": "fix", "subject": "fix: x MH-4", "owner_keys": ["MH-4"], "ref_keys": [], "keys_only_in_body": []}]}]}
gaps = []
res = P.collect_tickets(A(), delta, gaps)
by = {t["key"]: t for t in res["tickets"]}
check(by["MH-2"]["reverse"] == "fixed_in_names_a_delta_build" and "MH-5" not in by,
      "reverse lookup from the stored rows: a Fixed In naming a range build enters, 2.1.50 does not match 2.1.5")
check(by["MH-4"]["exists"] is None and by["MH-4"]["flags"] == ["not_in_facts"] and any(g["kind"] == "ticket_not_in_facts" for g in gaps),
      "a key the store lacks is unknown (exists null) and a gap, never 'not in Jira'")
check(all(c[1] != "jql" or c[2] == J.STANDING["fixed-in"][0] for c in calls), "the only search is the standing query's own text")
src = open(os.path.join(ROOT, "skills", "promote", "promote.py"), encoding="utf-8").read()
check(re.search(r"if not F\.facts_only\(\):[^\n]*\n\s+say\(f\"git fetch", src) is not None, "promote fetches no repository under facts-only")

# ── nextrel: must and in development from the store ───────────────────────────
g = []
check(N.must_from_store(g) == ([], None) and g[0]["kind"] == "jira_not_in_facts", "no stored release:must query is a gap")
F.write_json(os.path.join(F.store_dir("jira", "queries"), "release-must.json"),
             {"jql": J.STANDING["release-must"][0], "at": OLD, "issues": [{"key": "MH-1", "fields": {"summary": "m", "status": {"name": "Review"}}},
                                                                          {"key": "MH-9", "fields": {"summary": "n"}}]})
rows, at = N.must_from_store([])
check([r["key"] for r in rows] == ["MH-1", "MH-9"] and at == OLD, "the must rows and their read time")
since = N.must_since_of(["MH-1", "MH-9", "MH-10"], sweep, {"must": [{"key": "MH-9", "tracked_since": "2026-11-01T08:00:00.000+0800"}]})
check(since == {"MH-1": "2026-11-24T09:00:00.000+0800", "MH-9": "2026-11-01T08:00:00.000+0800", "MH-10": None},
      "tracked since: the sweep's changelog, else the previous file's time, else none")
now = datetime.datetime(2026, 11, 25, 13, 30, tzinfo=TZ)
sw = [{"key": "MH-7", "fields": {"status": {"name": "Review"}, "updated": "2026-11-11T05:00:29.266-0800"}},     # 21:00 +08, inside 14 days
      {"key": "MH-8", "fields": {"status": {"name": "In Progress"}, "updated": "2026-11-10T20:00:00.000-0800"}},  # 11-11 12:00 +08, outside
      {"key": "MH-6", "fields": {"status": {"name": "Done"}, "updated": "2026-11-24T10:00:00.000+0800"}},
      {"key": "BM-1", "fields": {"status": {"name": "Review"}, "updated": "2026-11-24T10:00:00.000+0800"}},
      {"key": "MH-3", "fields": {"status": {"name": "In Progress"}, "updated": "2026-11-24T10:00:00.000+0800"}}]
check([r["key"] for r in N.in_dev_from_sweep(sw, now)] == ["MH-3", "MH-7"], "in development: MH, In Progress or Review, 14 days by time not by text")
g = []
F.set_watermark("builds", at=NOW.isoformat(timespec="seconds"))
F.set_watermark("code", at=OLD)
read = N.facts_read(g, NOW)
check(set(read) == {"jira", "builds", "code"} and {x["kind"] for x in g} == {"facts_old"} and len(g) == 2,
      "a source older than the store's max age is a gap the page shows")

# ── no model tokens: nothing on the path starts claude ────────────────────────
CLAUDE = re.compile(r"""["'](?:[\w./-]*/)?claude["']|\bclaude\s+-p\b|api\.anthropic\.com|import\s+anthropic""")
path = ["release/nextrel.py", "release/release.py", "train/train.py", "publish/publish.py", "facts/facts.py", "jira/jira.py",
        "brief/brief.py"] + [f"promote/{f}" for f in os.listdir(os.path.join(ROOT, "skills", "promote")) if f.endswith(".py")]
hits = [f"{p}: {m.group(0)}" for p in path for m in CLAUDE.finditer(open(os.path.join(ROOT, "skills", p), encoding="utf-8").read())]
check(not hits, "no module the next-release path reaches starts a model session" + (f": {hits}" if hits else ""))

ran = []


def fake_run(argv, **kw):
    ran.append((list(argv), os.environ.get("ELA_FACTS_ONLY")))
    return subprocess.CompletedProcess(argv, 0, json.dumps({"tickets": [], "docker": [], "epics": [], "gaps": []}), "")


class FakeR:
    @staticmethod
    def site(): return {"published": TMP, "reports": TMP}
    @staticmethod
    def rmap(k): return {"2.1": {"lanes": {"daily": "daily-wed", "prod": "prod-3"}, "bundle_line": "mh2.1@"}} if k == "lines" else {}
    class LazyUS:
        def __init__(self, *a): self.kind = "prod"
    @staticmethod
    def resolve_bundle_loose(us, ref): return "2", "mh2.1@daily-wed-s1-d2", "prefix"
    @staticmethod
    def bundle_list(us, line, n): return [{"bundleId": "2", "bundleName": "mh2.1@daily-wed-s1-d2", "createTime": "2026-11-20"}]
    @staticmethod
    def release_base(us, line, before=None): return {"bundleId": "1", "bundleName": "MediaHub 2.1.19", "createTime": "2026-11-17"}
    @staticmethod
    def when(v): return str(v)


os.environ.pop("ELA_FACTS_ONLY", None)
real_run, N.R, N.subprocess.run = subprocess.run, (lambda: FakeR), fake_run
try:
    doc = N.build(N.gather("2.1", None, None, quiet=True), NOW)
finally:
    N.subprocess.run = real_run
check(len(ran) == 1 and os.path.basename(ran[0][0][1]) == "promote.py" and ran[0][1] == "1",
      "gather starts one subprocess, promote, with ELA_FACTS_ONLY set")
check(not any("claude" in " ".join(a) for a, _ in ran), "gather starts no claude")
check(doc["must"] and doc["sources"]["facts"]["at"] == OLD and "code" in doc["sources"]["facts"]["what"] and doc["base"]["name"] == "MediaHub 2.1.19",
      "the document is built from the store: must rows, the facts' read times, the bundles")

print(f"{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
