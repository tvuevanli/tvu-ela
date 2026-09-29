#!/usr/bin/env python3
"""`fixed-in draft` places a commit on the build that carries it and writes the Fixed In in the map's grammar.

Offline: the git log output, the ancestry relation and the Jenkins builds list are fakes, and the release map is
a fixed dict, so nothing is read from the network, from a checkout or from the site's map."""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "fixedin"))
import fixedin as F  # noqa: E402 — the module under test

failures = []


def check(ok, label):
    print(("ok   " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


F.R._MAP = {
    "fixed_in": {"field": "customfield_11252", "slug_aliases": {"mh-backend": "mediahub-backend"}},
    "version_rules": {"semver_build": {"patch_only": ["ur-portal", "j2n"]}},
}

A, B, C = "a" * 40, "b" * 40, "c" * 40
LOG = (f"{A}\t2026-09-01\tfix(player): MH-3568 keep the seek position\n"
       f"{B}\t2026-09-03\tMH-3568 follow-up: null guard\n"
       f"{A}\t2026-09-01\tfix(player): MH-3568 keep the seek position\n"
       "not a log line\n")
commits = F.parse_log(LOG)
check([c["sha"] for c in commits] == [A, B], "git log: one row per sha, junk lines dropped")
check(commits[0] == {"sha": A, "date": "2026-09-01", "subject": "fix(player): MH-3568 keep the seek position"}, "git log: sha, date, subject")

check(bool(F.key_rx("MH-356").search("MH-356 fix")) and not F.key_rx("MH-356").search("MH-3568 fix"), "a key matches only as a whole token")

# history: A → B → C; build 311 is before A, 312 carries A, 313 (FAILURE) and 314 carry A and B
ANCESTORS = {(A, B), (A, C), (B, C)}
is_anc = lambda s, d: (s, d) in ANCESTORS
D = "d" * 40
BUILDS = [
    {"number": 314, "version": "1.0.399", "build": 14, "result": "SUCCESS", "sha_full": C},
    {"number": 311, "version": "1.0.398", "build": 11, "result": "SUCCESS", "sha_full": D},
    {"number": 313, "version": "1.0.399", "build": 13, "result": "FAILURE", "sha_full": B},
    {"number": 312, "version": "1.0.398", "build": 12, "result": "SUCCESS", "sha_full": A},
]
check(F.carrying_build(A, BUILDS, is_anc)["number"] == 312, "sha equal to a build's sha_full → that build")
check(F.carrying_build(B, BUILDS, is_anc)["number"] == 314, "a failed build is passed over for the first successful descendant")
check(F.carrying_build(B, [b for b in BUILDS if b["number"] != 314], is_anc)["number"] == 313, "no successful carrier → the failed one, not nothing")
check(F.carrying_build("e" * 40, BUILDS, is_anc) is None, "a sha no build descends from → None")

carriers = [F.carrying_build(A, BUILDS, is_anc), F.carrying_build(B, BUILDS, is_anc)]
draft = F.draft_values("mediahub-backend", carriers)
check(draft == [{"service": "mediahub-backend", "value": "mediahub-backend@1.0.399+14"}], "the draft is <slug>@M.m.p+BUILD, highest build in the series")
two = F.draft_values("mediahub-backend", carriers + [{"number": 50, "version": "1.1.2", "build": 3, "sha_full": D}])
check([d["value"] for d in two] == ["mediahub-backend@1.0.399+14", "mediahub-backend@1.1.2+3"], "one entry per M.m series")
check(F.draft_values("mediahub-backend", [{"number": 9, "version": "1.0.388.1", "build": 204, "sha_full": A}])[0]["value"]
      == "mediahub-backend@1.0.388.1+204", "a patch segment is kept")

check(F.compare("", draft) == "empty", "no current value → empty")
check(F.compare("mh-backend@1.0.399+14", draft) == "same", "a legacy slug alias → same")
check(F.compare("mediahub-backend@1.0.398+12", draft) == "differs", "an older build → differs")
check(F.compare("mediahub-backend@1.0.399+14; mds-copier@copier:2.3.1", draft) == "same", "a docker entry is not compared")

rows = [{"lane": "qa-cn3", "version": "v1.0.399 build15 2026-09-04 10:00:00"},
        {"lane": "daily-wed", "version": "v1.0.398 build12 2026-09-02 10:00:00"},
        {"lane": "prod-3", "version": "v1.1.0 build2 2026-09-02 10:00:00"},
        {"lane": None, "version": "v1.0.400 build1"}]
running, other = F.lanes_running("mediahub-backend", rows, (1, 0, 399, 0, 14))
check([x["lane"] for x in running] == ["qa-cn3"], "a lane at or above the carrying build runs the fix; a lower one does not")
check(other == ["prod-3"], "a lane on another M.m series is named, not compared")

print("fixedin: all offline checks passed" if not failures else f"fixedin: {len(failures)} check(s) failed")
sys.exit(1 if failures else 0)
