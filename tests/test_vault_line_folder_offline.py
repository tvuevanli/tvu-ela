#!/usr/bin/env python3
"""A release line's folder, offline: its root keeps the line page and the live promote notes. A build's note, the
hand-written record and a done note move to history/ under their own names; a promote note closes itself once its target
lane runs what its source ran that day, and moves; one that has not landed stays live where it is. Each move is a logged
rename, a link by the old path follows it, a link by name needs nothing, and nothing is deleted."""
import json, os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "release"))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import release as R  # noqa: E402
import vault as V  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

R._MAP = {"lines": {"2.1": {"lanes": {"qa": "qa-cn3", "daily": "daily-wed", "prod": "prod-3"}, "decided": "yes"}},
          "regions": {"china": {"lanes": {"prod-2-china": {"shown": "CN Prod2", "line": "2.1"}}}}}


def note(path, props, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fm = "\n".join(f'{k}: "{v}"' for k, v in props.items())
    open(path, "w", encoding="utf-8").write(f"---\n{fm}\n---\n{body}")


def snap(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump({"rows": [{"lane": l, "service": s, "version": v, "host": "prod"} for l, s, v in rows]}, open(path, "w"))


with tempfile.TemporaryDirectory() as t:
    vault, reports, runtime = (os.path.join(t, x) for x in ("vault", "reports", "runtime"))
    d = os.path.join(vault, "releases", "2.1")
    note(f"{d}/2.1.md", {"type": "line"}, "# MediaHub 2.1 · where the line stands\n")
    note(f"{d}/2026-11-10-build-90-to-qa-aws3.md", {"type": "report", "status": "decided", "source": "vault"}, "# build 90\n")
    note(f"{d}/release-2-1-record.md", {"type": "report", "status": "decided", "source": "vault"}, "# Release 2.1\n")
    note(f"{d}/2026-10-27-review-cannot-evaluate.md", {"type": "review", "status": "done", "source": "vault"}, "# a review\n")
    note(f"{d}/2026-11-17-promote-daily-wed-to-prod-3.md", {"type": "review", "status": "live", "source": "vault"}, "# landed\n")
    note(f"{d}/2026-11-19-promote-qa-cn3-to-daily-wed.md", {"type": "review", "status": "live", "source": "vault"}, "# waiting\n")
    note(f"{d}/lists/test-list-qa-cn3.md", {"type": "test-list"}, "# Test list\n")
    note(os.path.join(vault, "reference", "days", "2026", "2026-11-18-brief.md"), {"type": "day"},
         "see [[releases/2.1/2026-11-10-build-90-to-qa-aws3#UR Caller\\|2 more]], [[2026-11-10-build-90-to-qa-aws3]], "
         "[[releases/2.1/test-list-qa-cn3|QA]] and [the record](releases/2.1/release-2-1-record.md)\n")
    rr = os.path.join(runtime, "runner")
    snap(f"{rr}/versions-2026-11-17.json", [("daily-wed", "mediahub-backend", "v2.1.46 build278"), ("prod-3", "mediahub-backend", "v2.1.44 build276"),
                                             ("qa-cn3", "mediahub-backend", "v2.1.45 build277")])
    snap(f"{rr}/versions-2026-11-19.json", [("daily-wed", "mediahub-backend", "v2.1.45 build277"), ("prod-3", "mediahub-backend", "v2.1.47 build279"),
                                             ("qa-cn3", "mediahub-backend", "v2.1.48")])
    snap(f"{rr}/versions-2026-11-20.json", [("daily-wed", "mediahub-backend", "v2.1.46 build278"), ("prod-3", "mediahub-backend", "v2.1.47 build279"),
                                             ("qa-cn3", "mediahub-backend", "v2.1.48")])
    check("a promote note has landed when the target runs what the source ran that day, or newer",
          V.hop_promoted("2026-11-17-promote-daily-wed-to-prod-3.md", reports, runtime) == (True, "runs it"))
    check("one whose target still runs older versions has not",
          V.hop_promoted("2026-11-19-promote-qa-cn3-to-daily-wed.md", reports, runtime)[0] is False)
    check("a China lane is read by its MediaHub name in a file name", V.lane_by_words("cn-prod-2", {"prod-2-china", "prod-3"}) == "prod-2-china"
          and V.lane_by_words("daily-wed-with-overlay", {"daily-wed", "prod-3"}) == "daily-wed")
    before = sorted(f for _, _, fs in os.walk(vault) for f in fs)
    dry = V.tidy_releases(vault, reports, runtime, dry_run=True)
    check("a dry run lists the moves and moves nothing", len(dry) == 4 and os.path.exists(f"{d}/release-2-1-record.md"))
    moved = V.tidy_releases(vault, reports, runtime)
    root = sorted(os.listdir(d))
    check("the root keeps the line page, the live promote note and the folders only",
          root == ["2.1.md", "2026-11-19-promote-qa-cn3-to-daily-wed.md", "history", "lists"])
    check("the build note, the record, the done review and the landed promote note are in history/ under their names",
          sorted(os.listdir(f"{d}/history")) == ["2026-10-27-review-cannot-evaluate.md", "2026-11-10-build-90-to-qa-aws3.md",
                                                 "2026-11-17-promote-daily-wed-to-prod-3.md", "release-2-1-record.md"])
    closed = V.props_of(V.split_front(open(f"{d}/history/2026-11-17-promote-daily-wed-to-prod-3.md").read())[0])
    check("the landed promote note closed itself: done, next promoted, closed by ela",
          closed.get("status") == "done" and closed.get("next") == "promoted" and closed.get("closed-by") == "ela")
    check("nothing deleted", sorted(f for _, _, fs in os.walk(vault) for f in fs) == before)
    log = [json.loads(l) for l in open(os.path.join(reports, "ela", "vault-removed.jsonl"))]
    check("each move is a logged rename by ela, so renames() follows it",
          len(log) == 4 and all(r["fate"] == "renamed" and r["by"] == "ela" for r in log)
          and V.renames(vault, reports).get("releases/2.1/release-2-1-record.md") == "releases/2.1/history/release-2-1-record.md")
    changed = V.relocate_vault_links(vault)
    brief = open(os.path.join(vault, "reference", "days", "2026", "2026-11-18-brief.md")).read()
    check("a link by the old path follows the note to history/ or lists/, anchors and labels kept; a link by name is left",
          changed == ["reference/days/2026/2026-11-18-brief.md"]
          and "[[releases/2.1/history/2026-11-10-build-90-to-qa-aws3#UR Caller\\|2 more]]" in brief
          and "[[2026-11-10-build-90-to-qa-aws3]]" in brief and "[[releases/2.1/lists/test-list-qa-cn3|QA]]" in brief
          and "(releases/2.1/history/release-2-1-record.md)" in brief)
    check("a second pass moves and rewrites nothing", V.tidy_releases(vault, reports, runtime) == [] and V.relocate_vault_links(vault) == [])

print(f"\n{len(failures)} failure(s)" if failures else "\nall passed")
sys.exit(1 if failures else 0)
