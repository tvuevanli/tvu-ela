#!/usr/bin/env python3
"""A train shipped under a second product name, offline: the 2.1 train's bundles named "MediaHub 2.2.N" (prod) and
"mh2.2@…" (daily, QA) read as the line's own (map release.yaml lines.<line>.ships_as), the release note's base is the
newest plain official bundle, and the bundle-to-bundle ticket diff takes tickets from docker Fixed In entries and lists
the epics its tickets sit under. The release map is a fixed dict and every host and Jira read is a fake."""
import os, sys, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ("promote", "brief", "release"):
    sys.path.insert(0, os.path.join(ROOT, "skills", d))
import promote as P  # noqa: E402
R, B = P.R, P.B

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


R._MAP = {
    "lines": {"2.1": {"label": "release:mh-2.1", "bundle_line": "mh2.1@", "ships_as": ["2.2"],
                      "lanes": {"qa": "qa-cn3", "daily": "daily-wed", "prod": "prod-3"}, "bundle_lanes": {"qa": "qa", "daily": "daily-wed"}},
              "2.0": {"bundle_line": "mh2.0@", "lanes": {"daily": "daily-stage", "prod": "prod-8"}, "bundle_lanes": {"daily": "stage"}},
              "2.2": {"label": "release:mh-2.2"}},
    "fixed_in": {"field": "customfield_11252"},
    "version_rules": {"semver_build": {"patch_only": ["ur-portal", "j2n"]}},
}

# ── the names a train ships under ───────────────────────────────────────────
check("2.1 ships as 2.1 and 2.2", R.train_versions("2.1") == ["2.1", "2.2"])
check("2.2 reads as the 2.1 train", R.train_versions("mh2.2@") == ["2.1", "2.2"] and R.train_of("2.2") == "2.1")
check("a line without ships_as is itself", R.train_versions("2.0") == ["2.0"])
check("the prod query widens", R.train_queries("MediaHub 2.1") == ["MediaHub 2.1", "MediaHub 2.2"])
check("the daily query widens with its token", R.train_queries("mh2.1@daily-wed") == ["mh2.1@daily-wed", "mh2.2@daily-wed"])
check("a full name, a dev prefix and the China line stay as typed",
      R.train_queries("MediaHub 2.1.19") == ["MediaHub 2.1.19"] and R.train_queries("mh2.1@dev-d") == ["mh2.1@dev-d"]
      and R.train_queries("MediaHub 2.1 CN") == ["MediaHub 2.1 CN"])
check("prefixes", R.train_prefixes("mh2.1@") == ["mh2.1@", "mh2.2@"])

check("MediaHub 2.2.0 is an official 2.1 release", R.is_official("MediaHub 2.2.0", "2.1") and R.is_official("MediaHub 2.2.0", "mh2.1@"))
check("mh2.2@daily-wed-s1-d1 is a 2.1 daily bundle", R.name_class("mh2.2@daily-wed-s1-d1", "2.1") == "daily")
check("dev bundles keep the line's own name", R.name_class("mh2.1@dev-d3", "2.1") == "dev" and R.name_class("mh2.2@dev-d3", "2.1") is None)
check("a China bundle is still not the .com official", not R.is_official("MediaHub 2.2.1 (CN Prod2)", "2.1"))
for n, want in (("MediaHub 2.1.19", True), ("MediaHub 2.2.0", True), ("MediaHub 2.1.20 (POC)", False),
                ("MediaHub 2.1.19 (UR/J2N Prod 9)", False), ("MediaHub 2.1.19 Televisa", False), ("MediaHub 2.1 rc3", False)):
    check(f"plain official: {n} → {want}", R.is_plain_official(n, "2.1") is want)

check("lane token under either prefix", R.lane_token_match("mh2.2@daily-wed-s1-d1", "mh2.1@", "daily-wed")
      and R.lane_token_match("mh2.1@daily-wed-s2-d57", "mh2.1@", "daily-wed")
      and not R.lane_token_match("mh2.2@daily-wedx-s1", "mh2.1@", "daily-wed") and not R.lane_token_match("mh2.0@stage-s1-d2", "mh2.1@", "stage"))

# ── bundle_list merges the train's queries ────────────────────────────────
HOST = {"MediaHub 2.1": [{"bundleId": 1, "bundleName": "MediaHub 2.1.19", "createTime": "2026-11-17 16:45"},
                         {"bundleId": 2, "bundleName": "MediaHub 2.1.20 (POC)", "createTime": "2026-11-19 17:20"},
                         {"bundleId": 3, "bundleName": "MediaHub 2.1.19 (UR/J2N Prod 9)", "createTime": "2026-11-23 13:50"},
                         {"bundleId": 4, "bundleName": "MediaHub 2.1.18", "createTime": "2026-11-10 09:28"}],
        "MediaHub 2.2": [{"bundleId": 5, "bundleName": "MediaHub 2.2.0", "createTime": "2026-11-27 18:00"}]}
asked = []
R._bundle_list = lambda us, q, limit=50, fresh=False: asked.append(q) or list(HOST.get(q, []))
rows = R.bundle_list(None, "MediaHub 2.1")
check("both names read", asked == ["MediaHub 2.1", "MediaHub 2.2"])
check("merged newest first", [b["bundleId"] for b in rows] == [5, 3, 2, 1, 4])
R.read_pins = lambda: {}
check("the official bundle is the newest, 2.2.0", R.official_bundle(None, "2.1")["bundleName"] == "MediaHub 2.2.0")
check("the release base before 2.2.0 is 2.1.19, not POC or UR/J2N",
      R.release_base(None, "2.1", before=HOST["MediaHub 2.2"][0])["bundleName"] == "MediaHub 2.1.19")
check("the release base with no bound is the newest plain one", R.release_base(None, "2.1")["bundleName"] == "MediaHub 2.2.0")

# ── the brief reads a 2.2-named daily bundle as the line's lane ─────────────
cfgs = {"2.1": R._MAP["lines"]["2.1"], "2.0": R._MAP["lines"]["2.0"]}
check("brief: mh2.2@daily-wed → daily-wed", B.bundle_lane("mh2.2@daily-wed-s1-d1", cfgs) == "daily-wed")
check("brief: mh2.0@stage → daily-stage", B.bundle_lane("mh2.0@stage-s3-d12", cfgs) == "daily-stage")

# ── bundle to bundle: refs, docker Fixed In, epics ───────────────────────────
check("bundle refs", all(P.is_bundle_ref(x) for x in ("base", "MediaHub 2.2.0", "mh2.2@daily-wed-s1-d1", "1572291615228403712"))
      and not any(P.is_bundle_ref(x) for x in ("daily", "prod-3", "qa-cn3")))
check("docker range by version", P.in_docker_range("1.0.88", "1.0.87", "1.0.90") and P.in_docker_range("1.0.90", "1.0.87", "1.0.90")
      and not P.in_docker_range("1.0.87", "1.0.87", "1.0.90") and not P.in_docker_range("1.0.91", "1.0.87", "1.0.90"))
check("docker range: a named tag matches only the new tag", P.in_docker_range("1.0.7", "Production2", "1.0.7")
      and not P.in_docker_range("1.0.6", "Production2", "1.0.7"))
check("docker range: an added image", P.in_docker_range("1.0.7", None, "1.0.7"))

doc = lambda t: {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": t}]}]}  # noqa: E731
JQL = {"issues": [{"key": "MH-1", "extra": {"customfield_11252": doc("mds-hls-copier@copier:1.0.88; mediahub-backend@2.1.47")}},
                  {"key": "MH-2", "extra": {"customfield_11252": doc("mds-hls-copier@copier:1.0.80")}},
                  {"key": "MH-3", "extra": {"customfield_11252": doc("mds-blackframe-detector@bs_detector:1.0.7")}},
                  {"key": "MH-4", "extra": {"customfield_11252": doc("mds-srt-copier@1.0.90")}}]}
P.l1 = lambda cap, *args, **kw: (True, JQL, "")
P.QUIET = True
dock = [{"service": "Docker Hls Copier", "slug": "mds-hls-copier", "from": "1.0.87", "to": "1.0.90", "relation": "to_ahead"},
        {"service": "Docker Blackframe Detector TermProcessor", "slug": "mds-blackframe-detector", "from": "Production2", "to": "1.0.7", "relation": "named_tags_not_comparable"},
        {"service": "Docker Srt Copier", "slug": "mds-srt-copier", "from": "1.0.87", "to": "1.0.90", "relation": "to_ahead"}]
gaps = []
hits = P.docker_tickets(types.SimpleNamespace(env_file=None), dock, gaps)
check("docker Fixed In: in range, named tag, image-less entry", sorted(hits) == ["MH-1", "MH-3", "MH-4"] and not gaps)
check("docker hit carries its entry", hits["MH-1"][0]["entry"] == "mds-hls-copier@copier:1.0.88")

ep = P.epics_of([{"key": "MH-10", "services_in_delta": ["mediahub-backend"], "parent": {"key": "MH-9", "type": "Epic", "summary": "E", "status": "Done"}},
                 {"key": "MH-11", "services_in_delta": [], "docker": [{"slug": "mds-hls-copier"}], "parent": {"key": "MH-9", "type": "Epic"}},
                 {"key": "MH-12", "parent": {"key": "MH-10", "type": "Task"}}])
check("an epic takes its children's services", ep == [{"key": "MH-9", "summary": "E", "status": "Done", "children": ["MH-10", "MH-11"],
                                                       "services": ["mds-hls-copier", "mediahub-backend"]}])
check("parent_of reads the parent's type", P.parent_of({"parent": {"key": "MH-9", "fields": {"issuetype": {"name": "Epic"}, "summary": "E", "status": {"name": "Done"}}}})
      == {"key": "MH-9", "type": "Epic", "summary": "E", "status": "Done"})

# the from bundle's tag as the saved lane reads had it when the to bundle was made
B.lane_reads = lambda runner, since="": [("2026-11-26", "0000", [{"service": "mediahub-backend", "tag": "MediaHubProd3", "host": "prod", "version": "v2.1.47 build279"}]),
                                          ("2026-11-27", "1700", [{"service": "mediahub-backend", "tag": "MediaHubProd3", "host": "prod", "version": "v2.1.48 build281"}]),
                                          ("2026-11-30", "1200", [{"service": "mediahub-backend", "tag": "MediaHubProd3", "host": "prod", "version": "v2.1.52 build290"}])]
R.site = lambda: {"runtime": "/nowhere"}
check("tag version at the to bundle's creation", P.tag_version_at("mediahub-backend", "MediaHubProd3", "2026-11-27 18:00") == ("v2.1.48 build281", "2026-11-27 1700"))
check("no read of the tag", P.tag_version_at("mediahub-backend", "MediaHubWednesday", "2026-11-27 18:00") == (None, None))

print(f"\n{len(failures)} failure(s)" if failures else "\nall ok")
sys.exit(1 if failures else 0)
