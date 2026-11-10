#!/usr/bin/env python3
"""ela vault migrate, offline: a layout-4 vault in a temporary folder brought to layout 5 (ADR 0015). The dry run lists
every move and writes nothing; --apply moves, renames with the old name as an alias, rewrites links, sets live and
done, retires the angles nothing consumes, and records layout 5 and the moves in the manifest."""
import datetime, io, json, os, sys, tempfile
from contextlib import redirect_stdout
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "vault"))
import vault as V  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

def note(v, rel, front, body):
    p = os.path.join(v, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write("---\n" + "\n".join(f'{k}: "{x}"' for k, x in front.items()) + "\n---\n" + body)

with tempfile.TemporaryDirectory() as t:
    v, reports = os.path.join(t, "v"), os.path.join(t, "r"); os.makedirs(reports)
    note(v, "projects/mh-1-csc-control-from-http-to-mqtt.md", {"title": "MH-1 · CSC control from HTTP to MQTT via mqtt-gateway", "type": "project", "keys": "MH-1"},
         "# MH-1 · CSC control\n\n## Open questions\n\n- [ ] the plan's questions: [[2026-11-10-mh-2-app-plan]]\n")
    note(v, "projects/mh-5-by-hand.md", {"title": "MH-5 · Something long enough to be cut by the old rule", "type": "project", "keys": "MH-5"}, "# MH-5\n")
    note(v, "to-read/2026-11-10-mh-2-app-plan.md", {"title": "MH-2 · the app plan", "type": "plan", "status": "proposed", "keys": "MH-2"}, "# MH-2 · the app plan\n")
    note(v, "mh/releases/2.1/release-2-1-record.md", {"title": "Release 2.1", "type": "report", "status": "decided"}, "# Release 2.1\n\nSee [[mh/releases/2.1/2026-11-09-deploy-daily-wed-to-prod-3|the deploy]].\n")
    note(v, "mh/releases/2.1/2026-11-09-deploy-daily-wed-to-prod-3.md", {"title": "Deploy", "type": "review", "status": "closed"}, "# Deploy\n")
    note(v, "mh/2026-11-05-jira-four-week-review.md", {"title": "Jira review", "type": "review", "status": "closed"}, "# Jira review\n")
    note(v, "lanes/train-2.1.md", {"type": "train"}, "# Train\n")
    note(v, "lanes/test-list-qa-cn3.md", {"type": "test-list"}, "# Test list\n")
    note(v, "lanes/test-list-elsewhere.md", {"type": "test-list"}, "# Test list\n")
    note(v, "days/2026/2026-11-10-brief.md", {"type": "day"}, "# Morning\n\n[[lanes/train-2.1|train]] · [[board|board]]\n")
    note(v, "board.md", {"type": "board"}, "# Board\n")
    note(v, "ela/review/2026-11-09-reader.md", {"type": "reader"}, "# The reader\n")
    note(v, "archive/2026-10-21-verify-mh-9.md", {"title": "MH-9 verify", "type": "verify", "status": "closed"}, "# MH-9\n")
    note(v, "cases/2026-11-05-sky-timeline.md", {"title": "Sky · x", "type": "case", "status": "closed"}, "# Sky\n")
    note(v, "parked/2026-10-27-v3-pack-rvf.md", {"title": "RVF", "type": "plan", "status": "parked", "moves": "parked", "next": ""}, "# RVF\n")
    note(v, "today.md", {"type": "today"}, "# Today\n\n[[to-read/2026-11-10-mh-2-app-plan|the plan]] · [[lanes|lanes]]\n")
    note(v, "lanes.md", {"type": "lanes"}, "# Lanes\n")
    note(v, "mh/releases/2.0/release-2-0-record.md", {"title": "Release 2.0", "type": "report", "status": "decided"}, "# Release 2.0\n\n[[release-2-1-record]]\n")
    os.makedirs(os.path.join(v, ".obsidian"))
    json.dump({"items": [{"path": "board.md", "title": "Board"}, {"path": "today.md", "title": "Today"}]}, open(os.path.join(v, ".obsidian", "bookmarks.json"), "w"))
    json.dump({"layout": 4, "files": ["board.md", "lanes.md", "lanes/train-2.1.md", "lanes/test-list-qa-cn3.md", "days/2026/2026-11-10-brief.md",
                                      "ela/review/2026-11-09-reader.md", "projects/mh-1-csc-control-from-http-to-mqtt.md", "today.md"],
               "sources": {"days/2026/2026-11-10-brief.md": "runner/2026-11-10-brief.md"}, "seen": {}}, open(os.path.join(v, V.MANIFEST), "w"))
    before = sorted(os.listdir(v))
    plan = V.migrate_plan(v, {"MH-1": "csc-over-mqtt"}, lanes={"qa-cn3": "2.1"}, runtime=None)
    to = {m["from"]: m["to"] for m in plan["moves"]}
    check("the dry run writes nothing", sorted(os.listdir(v)) == before)
    check("a note that serves a project goes beside its page, named <date>-<kind>-<what>, and the page into its folder",
          to.get("to-read/2026-11-10-mh-2-app-plan.md") == "projects/mh-1-csc-over-mqtt/2026-11-10-plan-mh-2-app.md"
          and to.get("projects/mh-1-csc-control-from-http-to-mqtt.md") == "projects/mh-1-csc-over-mqtt/mh-1-csc-over-mqtt.md")
    check("a page named by hand keeps its name", "projects/mh-5-by-hand.md" not in to)
    check("a release line's notes to releases/<line>/, its record named record.md",
          to.get("mh/releases/2.1/release-2-1-record.md") == "releases/2.1/record.md"
          and to.get("mh/releases/2.1/2026-11-09-deploy-daily-wed-to-prod-3.md") == "releases/2.1/2026-11-09-deploy-daily-wed-to-prod-3.md")
    check("a line's lists to its folder; a lane no line carries to releases/",
          to.get("lanes/train-2.1.md") == "releases/2.1/train.md" and to.get("lanes/test-list-qa-cn3.md") == "releases/2.1/test-list-qa-cn3.md"
          and to.get("lanes/test-list-elsewhere.md") == "releases/test-list-elsewhere.md" and to.get("lanes.md") == "releases/lanes.md")
    check("a review that serves no project to reference/, its kind first",
          to.get("mh/2026-11-05-jira-four-week-review.md") == "reference/2026-11-05-review-jira-four-week.md")
    check("the day pages to reference/days/; a parked plan becomes a project page",
          to.get("days/2026/2026-11-10-brief.md") == "reference/days/2026/2026-11-10-brief.md"
          and to.get("parked/2026-10-27-v3-pack-rvf.md") == "projects/v3-pack-rvf.md")
    check("the generated board and reader pages are retired; archive and cases stay",
          {x["path"] for x in plan["retire"]} == {"board.md", "ela/review/2026-11-09-reader.md"}
          and not any(r.startswith(("archive/", "cases/")) for r in to))
    check("statuses: live for what waited, done for what was closed; a case keeps its own",
          plan["props"]["to-read/2026-11-10-mh-2-app-plan.md"]["status"] == "live" and plan["props"]["archive/2026-10-21-verify-mh-9.md"]["status"] == "done"
          and "cases/2026-11-05-sky-timeline.md" not in plan["props"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        V.migrate_apply(v, reports, plan, datetime.date(2026, 11, 11))
    roots = sorted(x for x in os.listdir(v) if not x.startswith("."))
    check("after --apply the root holds only layout 5's entries", set(roots) <= set(V.ROOTS5) | {"home.md"} and "to-read" not in roots)
    moved_plan = open(os.path.join(v, "projects/mh-1-csc-over-mqtt/2026-11-10-plan-mh-2-app.md")).read()
    check("a renamed note keeps its old name as an alias and its status is live",
          "2026-11-10-mh-2-app-plan" in moved_plan.split("---")[1] and 'status: "live"' in moved_plan)
    today = open(os.path.join(v, "today.md")).read()
    check("links follow: a path link gets the new path, a name link the new name",
          "[[projects/mh-1-csc-over-mqtt/2026-11-10-plan-mh-2-app|the plan]]" in today and "[[lanes|lanes]]" in today
          and "[[2026-11-10-plan-mh-2-app]]" in open(os.path.join(v, "projects/mh-1-csc-over-mqtt/mh-1-csc-over-mqtt.md")).read())
    man = json.load(open(os.path.join(v, V.MANIFEST)))
    check("a renamed note whose new name another shares is linked by its path",
          "[[releases/2.1/record]]" in open(os.path.join(v, "releases/2.0/record.md")).read())
    check("the manifest says layout 5, keeps the moves for old paths, and follows the files",
          man["layout"] == 5 and man["moved"]["lanes/train-2.1.md"] == "releases/2.1/train.md" and man["moved_until"] == "2026-11-25"
          and "reference/days/2026/2026-11-10-brief.md" in man["files"] and "board.md" not in man["files"]
          and man["sources"] == {"reference/days/2026/2026-11-10-brief.md": "runner/2026-11-10-brief.md"})
    log = [json.loads(l) for l in open(os.path.join(reports, "ela", V.MIGRATE_LOG))]
    check("each move is logged with renamed_from, apart from the removal log",
          any(r["renamed_from"] == "lanes.md" and r["path"] == "releases/lanes.md" for r in log if "renamed_from" in r)
          and not os.path.exists(os.path.join(reports, "ela", "vault-removed.jsonl")))
    bm = json.load(open(os.path.join(v, ".obsidian", "bookmarks.json")))["items"]
    check("the bookmarks lose the retired board", [b["path"] for b in bm] == ["today.md"])
    check("a second plan finds nothing to move", not V.migrate_plan(v, lanes={"qa-cn3": "2.1"})["moves"])
print("vault migrate: all offline checks passed" if not failures else f"vault migrate: {len(failures)} failed")
sys.exit(1 if failures else 0)
