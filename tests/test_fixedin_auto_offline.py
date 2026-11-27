#!/usr/bin/env python3
"""`fixed-in draft` counts only the commits that fix a key, keeps to builds of a line, and says when a write may go
unread (`auto`).

Offline: commit subjects, builds and records are literals; the release map is a fixed dict."""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "fixedin"))
import fixedin as F  # noqa: E402 — the module under test

failures = []


def check(ok, label):
    print(("ok   " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


F.R._MAP = {"fixed_in": {"field": "customfield_11252"}, "version_rules": {"semver_build": {"patch_only": []}},
           "trains": [{"slug": "unified-media-frontend", "kind": "built-from-feature-branch", "branches": {"feature/MH3.0-develop-no-s3": "3.0.22 and up"}}]}
K = "MH-4114"
role = lambda subject, body="", merge=False: F.commit_role(K, subject, subject + "\n\n" + body, merge)[0]

check(role("fix(MH-4114): no offline flash") == "fix", "a commit naming the key in its subject is a fix")
check(role("Merge branch 'mr/MH-4114' into 'release2.1'", merge=True) == "fix", "a merge of the key's own branch is a fix")
check(role("Merge branch 'release2.1' into feature/MH-4013", "sync, with MH-4099/MH-4114", merge=True) == "no",
      "a sync merge that lists the key in its body is not counted")
check(F.commit_role("MH-4013", "Merge branch 'release2.1' into feature/MH-4013", "", True)[0] == "no",
      "a merge into the key's branch is not counted: the key names the destination")
check(role("docs(MH-4114,MH-4063): same root cause [skip ci]") == "no", "a docs commit is not counted")
check(role("chore(MH-4114): merge release2.1") == "no" and role("test(MH-4114): a case") == "no", "chore and test commits are not counted")
check(F.commit_role(K, 'Revert "fix(MH-4114): no offline flash"', "", False) == ("no", "revert"), "a revert is not counted, and is named")
check(role("fix(MH-4104): send the first frame", "also touches MH-4114") == "weak", "a body-only mention is weak")
check(not F.key_rx(K).search("MH-41140"), "the key is a whole token")

A = "a" * 40
BUILDS = [
    {"number": 238, "version": "2.2.172", "build": 238, "result": "SUCCESS", "sha_full": A, "branch": "feature/MH-4013"},
    {"number": 239, "version": "2.2.173", "build": 239, "result": "SUCCESS", "sha_full": A, "branch": "release2.1"},
]
anc = lambda s, d: s == d
check(F.carrying_build(A, BUILDS, anc)["number"] == 238, "without a key, the earliest build")
check(F.carrying_build(A, BUILDS, anc, K)["number"] == 239, "with a key, a build of another ticket's branch is passed over")
check(F.carrying_build(A, BUILDS, anc, "MH-4013")["number"] == 238, "the ticket's own branch is not foreign")
check(F.carrying_build(A, BUILDS[:1], anc, K) is None, "carried only by another ticket's branch → no carrier")

two = F.draft_values("mediahub-frontend", [
    {"number": 90, "version": "2.2.72.18", "build": 90, "branch": "release2.0"},
    {"number": 239, "version": "2.2.173", "build": 239, "branch": "release2.1"},
    {"number": 220, "version": "2.2.155", "build": 220, "branch": "release2.1"}])
check([d["value"] for d in two] == ["mediahub-frontend@2.2.72.18+90", "mediahub-frontend@2.2.173+239"],
      "one entry per branch in a series, the highest build on each")


check(F.is_line("release2.1") and F.is_line("release2.0-2.2.72.17") and F.is_line("patch/2.2.132-MH-4072") and F.is_line("prod9_patch"),
      "release, patch and prod-patch branches are lines")
check(not F.is_line("release_tvugo") and F.is_line("release1.0") and F.is_line("release2.1-v2.2.116.1"),
      "release_tvugo, another product's line, is not an MH line")
check(F.is_line("feature/MH3.0-develop-no-s3"), "a branch the map names for a line is a line")
check(not F.is_line("feature/summer-MH5.1") and not F.is_line("master") and not F.is_line("feature/ui-2.0") and not F.is_line(""),
      "any other branch is not a line, whatever its name")


def rec(**over):
    r = {"key": K, "status": "Review", "current": "", "subtasks": 0, "labels": [], "predated": 0, "unbuilt": [], "dropped": [], "gaps": [],
         "untestable": 0, "behind": [],
         "commits": [{"sha": A, "via": "message", "role": "fix", "service": "mediahub-frontend"}],
         "builds": [{"service": "mediahub-frontend", "sha": A, "number": 239, "result": "SUCCESS", "branch": "release2.1"}],
         "draft": [{"service": "mediahub-frontend", "value": "mediahub-frontend@2.2.173+239"}],
         "declared": {"declared": [{"service": "mediahub-frontend", "value": "mediahub-frontend@2.2.173", "date": "2026-11-26", "versions_in_comment": 1}]}}
    r.update(over)
    return r


ok = F.auto_verdict(rec())
check(ok == {"ok": True, "value": "mediahub-frontend@2.2.173+239", "why": []}, "commits on a line and the declaration agree → auto")
no = lambda label, **over: check(not F.auto_verdict(rec(**over))["ok"] and F.auto_verdict(rec(**over))["why"], label)
no("In Progress → no", status="In Progress")
no("a value already there → no", current="mediahub-frontend@2.2.100")
no("a parent with sub-tasks → no", subtasks=2)
no("flag:no-version → no", labels=["flag:no-version"])
no("no commit → no", commits=[], builds=[], draft=[])
no("a weak commit → no", commits=[{"sha": A, "via": "message", "role": "weak", "service": "mediahub-frontend"}])
no("a linked ticket's commit → no", commits=[{"sha": A, "via": "linked ticket MH-1", "role": "fix", "service": "mediahub-frontend"}])
no("a revert names the key → no", dropped=[{"sha": A, "why": "revert"}])
no("an unbuilt commit → no", unbuilt=[{"service": "mediahub-frontend", "sha": A}])
no("a failed carrier → no", builds=[{"service": "mediahub-frontend", "sha": A, "number": 239, "result": "FAILURE", "branch": "release2.1"}])
no("a carrier with no branch → no", builds=[{"service": "mediahub-frontend", "sha": A, "number": 239, "result": "SUCCESS", "branch": ""}])
no("a feature branch without a key as carrier → no", builds=[{"service": "mediahub-frontend", "sha": A, "number": 9, "result": "SUCCESS", "branch": "feature/summer-MH5.1"}])
no("an earlier build not checkable → no", untestable=1)
no("the checkout behind the builds → no", behind=["mediahub-frontend release2.1 #250"])
no("a comment naming two versions → no", declared={"declared": [{"service": "mediahub-frontend", "value": "mediahub-frontend@2.2.173", "date": "2026-11-26", "versions_in_comment": 2}]})
no("a declaration older than the last commit → no", declared={"declared": [{"service": "mediahub-frontend", "value": "mediahub-frontend@2.2.173", "date": "2026-11-20", "versions_in_comment": 1}]},
   commits=[{"sha": A, "via": "message", "role": "fix", "service": "mediahub-frontend", "date": "2026-11-26"}])
no("a declared build that differs → no", declared={"declared": [{"service": "mediahub-frontend", "value": "mediahub-frontend@2.2.173+240", "date": "2026-11-26", "versions_in_comment": 1}]})
no("a developer naming another service without a version → no",
   declared={"declared": [{"service": "mediahub-frontend", "value": "mediahub-frontend@2.2.173", "date": "2026-11-26", "versions_in_comment": 1}], "named_services": ["mediahub-backend"]})
no("a bare release line for another service → no",
   declared={"declared": [{"service": "mediahub-frontend", "value": "mediahub-frontend@2.2.173", "date": "2026-11-26", "versions_in_comment": 1}], "bare_release_lines": ["mediahub-backend@2.1"]})
no("the ticket's own feature branch as carrier → no", builds=[{"service": "mediahub-frontend", "sha": A, "number": 9, "result": "SUCCESS", "branch": "feature/MH-4114"}])
no("no declaration → no", declared={"declared": []})
no("a declaration that differs → no", declared={"declared": [{"service": "mediahub-frontend", "value": "mediahub-frontend@2.2.176"}]})
no("a declaration for a service the commits miss → no",
   declared={"declared": [{"service": "mediahub-frontend", "value": "mediahub-frontend@2.2.173"}, {"service": "mediahub-backend", "value": "mediahub-backend@2.1.48"}]})
no("two lines of one service → no", draft=[{"service": "mediahub-frontend", "value": "mediahub-frontend@2.2.72.18+90"},
                                             {"service": "mediahub-frontend", "value": "mediahub-frontend@2.2.173+239"}])
no("an unreadable job → no", gaps=["mediahub-frontend: Jenkins mediahub-front-docker unreadable: timeout"])

if failures:
    print(f"\n{len(failures)} failed")
    sys.exit(1)
print("\nall ok")
