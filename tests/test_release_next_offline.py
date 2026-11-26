#!/usr/bin/env python3
"""`ela release next`, offline: the document built from fixture inputs, the state, the must decision, the joins, the
stale time, and the publish (redacted, guarded, atomic, README beside it). No source is read."""
import datetime, json, os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "release"))
import nextrel as N  # noqa: E402
import release as R  # noqa: E402
# The release map pinned to a fixture: a fact added to the live map (a lane's declared UR environment) never moves an expectation.
R._MAP = R._yaml_subset(open(os.path.join(ROOT, "tests", "fixtures", "release-map.yaml")).read())

TZ = datetime.timezone(datetime.timedelta(hours=8))
NOW = datetime.datetime(2026, 11, 25, 17, 40, tzinfo=TZ)           # a Wednesday, after the 17:30 pass
CFG = {"lanes": {"qa": "qa-cn3", "daily": "daily-wed", "prod": "prod-3"}, "bundle_line": "mh2.1@", "ships_as": ["2.2"], "ships_as_since": "2026-11-30"}
BASE = {"name": "MediaHub 2.1.19", "id": "1572291615228403712", "created": "2026-11-17 16:45", "rule": "the newest plain official bundle"}
CAND = {"name": "mh2.1@daily-wed-s2-d57", "id": "1573277690348318720", "created": "2026-11-20 10:03", "rule": "prefix"}
TICKETS = {"tickets": [
    {"key": "MH-3925", "exists": True, "summary": "Media Analyzer decode info panel does not show Scan Type", "status": "Done", "assignee": "A",
     "priority": "High", "updated": "2026-11-24T17:55:11.994-0800",
     "type": "Bug", "parent": None, "services_in_delta": ["mediahub-frontend"], "docker": [], "url": "https://tvunetworks.atlassian.net/browse/MH-3925"},
    {"key": "BM-1272", "exists": True, "summary": "[topbar] 接入方升级 tvu-common-ui", "status": "DOING", "assignee": "B", "type": "Task",
     "parent": {"key": "BM-735", "type": "Epic"}, "services_in_delta": ["mediahub-frontend"], "docker": [{"slug": "mds-switcher", "entry": "x"}]},
    {"key": "MH-9999", "exists": False}],
    "docker": [{"service": "Docker Switcher", "slug": "mds-switcher", "from": "1.0.35", "to": "1.0.36", "relation": "to_ahead", "tickets": []}],
    "epics": [{"key": "BM-735", "summary": "Top Bar", "status": "DOING", "children": ["BM-1272"]}],
    "gaps": [{"kind": "saas_rows_are_the_tag_now", "detail": "…"}]}
REPORT = {"generated_at": "2026-11-25T03:03:33Z",
          "evidence": {"keys": {"MH-3925": {"verdict": "pass", "source": "mail", "items": [{"when": "2026-11-19T11:10", "quote": "MH-3925 通过"}, {"when": "2026-11-20T09:00"}]},
                                "MH-4097": {"verdict": "fail", "source": "jira", "items": []}}},
          "lanes": {"services": [{"service": "mediahub-backend", "from_lane": "daily-wed", "to_lane": "prod-3", "from": {"version": "v2.1.48 build280"},
                                  "to": {"version": "v2.1.47 build279"}, "relation": "from_ahead"}]},
          "prereqs": {"unbuilt": [{"service": "mediahub-backend", "repo": "web/tvu-media-hub", "branch": "origin/release2.1", "build": "2.1.48",
                                   "commits": [{"sha": "62ea93de", "date": "2026-11-24", "author": "X", "subject": "fix(source): an empty page still sends empty sourceObjectIds to mx"}]},
                                  {"service": "mediahub-frontend", "branch": "origin/feature/MH-4013", "commits": [], "error": None},
                                  {"service": "unified-media-backend", "branch": None, "commits": [], "error": "no checkout"}]}}
TRAIN = {"at": "2026-11-25T13:05:00+08:00", "lanes": [{"role": "qa", "lane": "qa-cn3", "shown": "QA-AWS3"}, {"role": "daily", "lane": "daily-wed", "shown": "daily-wed"}],
         "rows": [{"key": "MH-4100", "also": [], "position": "qa", "cells": {"qa-cn3": {"arrived": "98", "verdict": "pass"}}},
                  {"key": "MH-3800", "also": ["MH-3925"], "position": "daily", "cells": {}}]}
MUST = [{"key": "MH-3925", "summary": "Media Analyzer decode info panel does not show Scan Type", "status": "Done", "type": "Bug",
         "priority": "Highest", "updated": "2026-11-25T09:00:00.000+0800"},
        {"key": "MH-4100", "summary": "A must ticket not yet on daily", "status": "Review", "type": "Bug"}]
INDEV = [{"key": "MH-4097", "summary": "Source preview stage bar", "status": "Review", "updated": "2026-11-24T10:00:00.000+0800"},
         {"key": "MH-3925", "summary": "on the candidate already", "status": "Review", "updated": "2026-11-24"}]
HIST = [{"created": "2026-11-26T10:00:00.000+0800", "items": [{"field": "labels", "fromString": "release:mh-2.1 release:must", "toString": "release:mh-2.1 release:must x"}]},
        {"created": "2026-11-25T09:00:00.000+0800", "items": [{"field": "labels", "fromString": "release:mh-2.1", "toString": "release:mh-2.1 release:must"}]}]


def inp(**kw):
    d = {"line": "2.1", "cfg": CFG, "base": BASE, "candidate": CAND, "candidate_source": "newest", "released": False, "released_bundle": None,
         "tickets": TICKETS, "report": REPORT, "train": TRAIN, "must_rows": MUST, "must_since": {"MH-3925": N.label_added(HIST)},
         "indev_rows": INDEV, "sources": {"tickets": {"what": "t", "at": "x"}}, "gaps": []}
    d.update(kw)
    return d


fails = []


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        fails.append(what)


doc = N.build(inp(), NOW)
check(doc["schema"] == 3 and doc["generated_at"] == "2026-11-25T17:40:00+08:00", "schema 3 and generated_at with its offset")
check(doc["stale_after"] == "2026-11-26T10:00:00+08:00", "after 17:30: stale after the next morning run (08:00) plus two hours")
noon = N.build(inp(), datetime.datetime(2026, 11, 25, 9, 0, tzinfo=TZ))
check(noon["stale_after"] == "2026-11-25T14:30:00+08:00", "after the morning run: stale after the 12:30 run plus two hours")
fri = N.build(inp(), datetime.datetime(2026, 11, 27, 19, 30, tzinfo=TZ))
check(fri["stale_after"] == "2026-11-30T10:00:00+08:00", "Friday evening: stale only after Monday's morning run")
check(doc["state"] == "planned" and doc["headline"] == "MediaHub 2.2.0, planned for prod-3 (UR/J2N Prod 3) on Monday 30 Nov", "planned: the headline names 2.2.0, prod-3, Monday 30 Nov")
check(doc["release"] == {"name": "MediaHub 2.2.0", "lane": "prod-3", "planned_for": "2026-11-30", "released_bundle": None}, "release block")
check(N.release_name("MediaHub 2.1.19", []) == "MediaHub 2.1.20" and N.release_name("MediaHub 2.2.0", ["2.2"]) == "MediaHub 2.2.1", "no newer ships-as number: the next patch")
check(doc["candidate"]["source"] == "newest" and doc["base"]["name"] == "MediaHub 2.1.19", "base and candidate as given")
keys = [t["key"] for t in doc["on_candidate"]]
check(keys == ["MH-3925", "BM-1272"], "on the candidate: every existing ticket of the range, a missing one left out")
bm = doc["on_candidate"][1]
check(bm["parent"] == "BM-735" and bm["docker"] == ["mds-switcher"] and bm["qa"] is None, "a parent object becomes its key; docker slugs; no QA reading is null")
check(doc["on_candidate"][0]["qa"] == {"verdict": "pass", "source": "mail", "when": "2026-11-20T09:00"}, "QA's verdict joined, its newest time, no quotation")
m1, m2 = doc["must"]
check(m1["on_candidate"] and m1["decision"] is None and m1["position"] == "daily" and m1["tracked_since"] == "2026-11-25T09:00:00.000+0800",
      "a must ticket on the candidate: no decision; train row found by alias; tracked from when the label was added")
check(not m2["on_candidate"] and m2["decision"] == "hold or defer" and m2["cells"] == {"qa-cn3": {"arrived": "98", "verdict": "pass"}} and m2["tracked_since"] is None,
      "a must ticket not on the candidate asks hold or defer; its lane cells from the train")
when = lambda v: v and datetime.datetime.fromisoformat(v)  # noqa: E731
check([t["key"] for t in doc["in_dev"]] == ["MH-4097"] and when(doc["in_dev"][0]["updated"]) == datetime.datetime(2026, 11, 24, 10, 0, tzinfo=TZ)
      and doc["in_dev"][0]["qa"]["verdict"] == "fail", "in development: not on the candidate, updated as an ISO time, QA joined")
oc = doc["on_candidate"][0]
check(oc["priority"] == "High" and when(oc["updated"]) == datetime.datetime(2026, 11, 25, 9, 55, 11, tzinfo=TZ) and doc["on_candidate"][1]["priority"] is None
      and doc["on_candidate"][1]["updated"] is None, "every ticket carries priority and updated (ISO), null when the store has none")
check(doc["must"][0]["priority"] == "Highest" and when(doc["must"][0]["updated"]) == datetime.datetime(2026, 11, 25, 9, 0, tzinfo=TZ)
      and all({"priority", "updated"} <= set(t) for k in ("must", "on_candidate", "in_dev") for t in doc[k]), "must rows too; the keys are always present")
dk = doc["docker"]
check(dk["bundle_diff"][0]["slug"] == "mds-switcher" and dk["lanes"][0]["from"] == {"lane": "daily-wed", "version": "v2.1.48 build280"}, "docker diff and lane versions")
check([b["kind"] for b in dk["branches"]] == ["release", "feature", None] and dk["branches"][0]["commits"][0]["sha"] == "62ea93de", "branches: release or feature, commits not built")
check(doc["counts"] == {"must": 2, "must_missing": 1, "must_shipped": 0, "must_cleared": 0, "on_candidate": 2, "in_dev": 1, "docker_changed": 1, "unbuilt_commits": 1, "not_on_candidate": 0}, "counts")
check(doc["lanes"] == TRAIN["lanes"] and any(g["kind"] == "saas_rows_are_the_tag_now" for g in doc["gaps"]), "lane headings from the train; promote's gaps carried")
check(any(g["kind"] == "branch_unread" and "(no branch)" in g["detail"] for g in doc["gaps"]), "a branch the report could not read is a gap")
check("quote" not in json.dumps(doc), "no QA quotation is carried")

rel = N.build(inp(released=True, released_bundle={"name": "MediaHub 2.2.0", "id": "9", "created": "2026-11-30 10:00"}), datetime.datetime(2026, 11, 30, 13, 5, tzinfo=TZ))
check(rel["state"] == "released" and rel["headline"] == "MediaHub 2.2.0, released" and rel["release"]["planned_for"] is None
      and rel["release"]["released_bundle"]["name"] == "MediaHub 2.2.0", "released: the headline, the bundle, no planned date")
check(all(m["decision"] is None for m in rel["must"]), "released: no must ticket asks a decision")

# the head: words a reader renders as given
h = doc["head"]
check(h["title"] == "MediaHub 2.2.0 → prod-3 (UR/J2N Prod 3), Monday 30 Nov", "head.title: the lane by its MediaHub name, the UR environment in brackets, the day")
check(h["lede"] == "2 tickets must ship, 2 are on the candidate (1 QA pass, 1 fail or no verdict) and 1 is in development; "
      "the candidate is provisional until pinned.", "head.lede: the counts in one sentence, provisional until pinned")
check(h["read"] == "Computed Wednesday 25 Nov 17:40; the fact store names no read time", "head.read: no facts time is said, never invented")
check(doc["candidate"]["provisional"] is True, "candidate.provisional: true while no pin holds it")
check(doc["candidate_verdicts"] == [{"key": "BM-1272", "verdict": "none", "url": "https://tvunetworks.atlassian.net/browse/BM-1272"},
                                    {"key": "MH-3925", "verdict": "pass", "url": "https://tvunetworks.atlassian.net/browse/MH-3925"}],
      "candidate_verdicts: one per candidate ticket, no reading is none, sorted fail → none → partial → n-a → pass")
pinned = N.build(inp(candidate_source="pin", sources={"facts": {"what": "f", "at": "2026-11-25T08:02:00+00:00"}}), NOW)
check(pinned["candidate"]["provisional"] is False and "provisional" not in pinned["head"]["lede"], "a pinned candidate is not provisional")
check(pinned["head"]["read"] == "Facts as of Wednesday 25 Nov 16:02, computed Wednesday 25 Nov 17:40", "head.read: the oldest fact's time, in the file's offset")
check(rel["head"]["title"] == "MediaHub 2.2.0 → prod-3 (UR/J2N Prod 3), released" and rel["candidate"]["provisional"] is False, "released: the title says released")
check([N.verdict_of({"verdict": v}) for v in ("accepted", "dev-declared", "partial", "fail")] + [N.verdict_of(None)] == ["n-a", "none", "partial", "fail", "none"],
      "promote's verdicts fold into the five: accepted ships nothing (n-a), a developer's word is no verdict")
check(N.lane_label("prod-3") == "prod-3 (UR/J2N Prod 3)" and N.lane_label("qa-cn3") == "QA-AWS3",
      "a lane's label: the UR environment in brackets where the map names one, MediaHub's name alone where it does not")
one = N.head("planned", "MediaHub 2.1.20", "prod-9", None, {"must": 1, "on_candidate": 1, "in_dev": 1}, [{"verdict": "fail"}], False, None, NOW)
check(one["title"] == "MediaHub 2.1.20 → prod-9 (UR/J2N Prod 9)" and one["lede"].startswith("1 ticket must ship, 1 is on the candidate (0 QA pass, 1 fail or no verdict) and 1 is in development."),
      "no planned date: no day in the title; one of each reads in the singular")

ADDR = ".".join(["10", "12", "13", "14"])               # built here: a literal address in a tracked file is refused
SECRET = "tok" + "en: " + "q" * 20
with tempfile.TemporaryDirectory() as d:
    path, flags = N.publish(doc, d)
    got = json.load(open(path, encoding="utf-8"))
    check(flags is None and got == json.loads(json.dumps(doc, ensure_ascii=False)) and os.path.isfile(os.path.join(d, "releases", "README.md"))
          and not [f for f in os.listdir(os.path.join(d, "releases")) if f.endswith(".tmp")], "publish: next.json and README.md, no temp file left")
    bad = N.build(inp(gaps=[{"kind": "x", "detail": f"seen at {ADDR} and {SECRET}"}]), NOW)
    before = open(path, encoding="utf-8").read()
    p2, flags = N.publish(bad, d)
    check(p2 is None and flags and open(path, encoding="utf-8").read() == before, "a credential refuses the file; the published copy is unchanged")
    nb = N.build(inp(gaps=[{"kind": "x", "detail": f"box at {ADDR}"}]), NOW)
    N.publish(nb, d)
    check(ADDR not in open(path, encoding="utf-8").read(), "an address is redacted")

# --sync: releases/ alone carried to the remote root, stale files removed there, nothing else touched
with tempfile.TemporaryDirectory() as pub, tempfile.TemporaryDirectory() as remote:
    N.publish(doc, pub)
    os.makedirs(os.path.join(remote, "releases")); open(os.path.join(remote, "releases", "old.json"), "w").write("{}")
    os.makedirs(os.path.join(remote, "lanes")); open(os.path.join(remote, "lanes", "lanes.md"), "w").write("kept")
    out = N.sync(pub, remote)
    got = sorted(os.listdir(os.path.join(remote, "releases")))
    check(out == "synced releases/ to <published_remote>" and got == ["README.md", "next.json"]
          and open(os.path.join(remote, "lanes", "lanes.md")).read() == "kept", "sync: releases/ carried, its stale file removed, lanes/ untouched")
    check(json.load(open(os.path.join(remote, "releases", "next.json"), encoding="utf-8"))["schema"] == 3, "sync: the remote copy is the published, redacted file")
    bad = N.sync(pub, os.path.join(remote, "no", "such", "parent", "x"))
    check(bad.startswith("not synced: rsync"), "sync: a failure is one line, never an exit")

# A candidate build off the release branch (2026-11-26: mediahub-frontend 2.2.160 from feature/MH-4013 lacked MH-4093 and MH-4081)
import subprocess  # noqa: E402
with tempfile.TemporaryDirectory() as repo:
    g = lambda *a: subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, check=True).stdout.strip()  # noqa: E731
    g("init", "-q", "-b", "release2.1"); g("config", "user.email", "t@example.invalid"); g("config", "user.name", "T")
    def commit(name, msg):
        open(os.path.join(repo, name), "w").write(msg); g("add", name); g("commit", "-q", "-m", msg)
    commit("a", "base")
    g("checkout", "-q", "-b", "feature/MH-4013"); commit("f", "feat(MH-4013): the feature")
    g("checkout", "-q", "release2.1"); commit("b", "fix(MH-4093): stream page"); commit("c", "fix(MH-4081): NOC card"); commit("d", "fix(MH-4100): picked too")
    picked = g("rev-parse", "HEAD")
    g("update-ref", "refs/remotes/origin/release2.1", "release2.1")
    g("checkout", "-q", "feature/MH-4013"); g("cherry-pick", picked)
    sha = g("rev-parse", "HEAD")
    rep = {"delta": {"services": [
        {"service": "mediahub-frontend", "repo": "web/media-hub-front", "from_build": {"number": 226, "version": "2.2.160", "branch": "feature/MH-4013", "sha": sha}},
        {"service": "mediahub-backend", "repo": "web/tvu-media-hub", "from_build": {"number": 280, "version": "2.1.48", "branch": "release2.1", "sha": sha}},
        {"service": "unified-media-frontend", "repo": "web/mx-service-front", "from_build": {"number": 206, "version": "3.0.49", "branch": "feature/MH3.0-develop-no-s3", "sha": sha}},
        {"service": "unified-streaming", "repo": "web/mx-service", "from_build": {"number": 1, "version": "2.1.1", "branch": "feature/x", "sha": sha}}]}}
    trains = [{"slug": "unified-media-frontend", "kind": "built-from-feature-branch", "branches": {"feature/MH3.0-develop-no-s3": "3.0.22 and up"}}]
    off = N.off_release_of("2.1", CFG, rep, trains, lambda r: repo if r == "web/media-hub-front" else None)
check([o["service"] for o in off] == ["mediahub-frontend", "unified-streaming"],
      "off the release branch: a feature-branch build; the release branch and a branch the map declares the service's line are not")
fe = off[0]
check(fe["keys"] == ["MH-4081", "MH-4093"] and len(fe["commits"]) == 2 and fe["branch"] == "feature/MH-4013" and fe["release_branch"] == "release2.1" and fe["error"] is None,
      "the release-branch commits the build lacks, a fix cherry-picked onto the feature branch not counted")
check(off[1]["error"] == "repo not on disk" and off[1]["commits"] == [], "a service whose checkout is missing is said, never judged")
must_lack = [{"key": "MH-4093", "summary": "Stream page", "status": "Review", "type": "Bug"}]
tk_lack = dict(TICKETS, tickets=TICKETS["tickets"] + [{"key": "MH-4093", "exists": True, "summary": "Stream page", "status": "Review", "services_in_delta": ["mediahub-backend"]}])
od = N.build(inp(off_release=off, must_rows=must_lack, tickets=tk_lack, indev_rows=[{"key": "MH-4081", "summary": "NOC card", "status": "Review"}]), NOW)
m = od["must"][0]
where = [{"service": "mediahub-frontend", "build": "2.2.160", "branch": "feature/MH-4013"}]
check(m["on_candidate"] is False and m["decision"] == "hold or defer" and m["not_on_candidate"] == where,
      "a must ticket the candidate's build lacks is not on the candidate, whatever the range carries")
check(next(t for t in od["on_candidate"] if t["key"] == "MH-4093")["not_on_candidate"] == where and od["in_dev"][0]["not_on_candidate"] == where
      and doc["on_candidate"][0]["not_on_candidate"] is None, "each listed ticket names the build that lacks it; null otherwise")
gap = next(g for g in od["gaps"] if g["kind"] == "candidate_off_release_branch")
check(gap["detail"] == "mediahub-frontend 2.2.160 (#226) is built from feature/MH-4013, not release2.1; it lacks 2 commits of release2.1: MH-4081, MH-4093 not on the candidate",
      "the gap names the build, its branch and the keys it lacks")
check(any(g["kind"] == "release_branch_unread" for g in od["gaps"]) and od["counts"]["not_on_candidate"] == 2 and od["docker"]["off_release"] == off,
      "an unread service is a gap; the count and docker.off_release carried")
check("mediahub-frontend 2.2.160 is built from feature/MH-4013, without MH-4081, MH-4093;" in od["head"]["lede"], "head.lede names the build and the keys it lacks")
rel = N.build(inp(off_release=off, released=True, released_bundle={"name": "MediaHub 2.2.0", "id": "9", "created": "2026-11-30 10:00"}), NOW)
check(rel["docker"]["off_release"] == [] and rel["counts"]["not_on_candidate"] == 0, "released: no candidate left to judge")

try:
    N.main(["--sync"]); code = 0
except SystemExit as e:
    code = e.code
check(code == 2, "--sync without --write is a usage error, before any read")

sys.exit(1 if fails else 0)
