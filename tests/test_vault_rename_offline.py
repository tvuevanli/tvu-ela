#!/usr/bin/env python3
"""A renamed note is followed, offline: the close log's rename row and an old name kept as an alias both map the old
path to the new; the questions' sources and the manifest follow it; the gone-by-hand pass does not report it."""
import json, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
sys.path.insert(0, os.path.join(ROOT, "skills", "brief"))
import questions as Q  # noqa: E402
import vault as V  # noqa: E402

failures = 0


def check(name, cond):
    global failures
    print(("ok   " if cond else "FAIL ") + name)
    failures += 0 if cond else 1


def note(path, aliases, kind="meeting", date="2026-11-12"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(f'---\ntitle: "T"\naliases: {json.dumps(aliases)}\ntype: "{kind}"\ndate: "{date}"\nsource: "vault"\n---\n\n# T\n')


with tempfile.TemporaryDirectory() as tmp:
    vault, reports = os.path.join(tmp, "vault"), os.path.join(tmp, "reports")
    note(os.path.join(vault, "meetings", "2026-11-12-sync-eng-qa.md"), ["T", "20261112-sync-eng-qa"])
    note(os.path.join(vault, "releases", "2.1", "2026-11-09-plan-cn-test.md"), ["T"], "plan", "2026-11-09")
    os.makedirs(os.path.join(reports, "ela"))
    open(os.path.join(reports, "ela", "vault-removed.jsonl"), "w").write(json.dumps(
        {"path": "releases/2.1/release-2-1-cn-test-plan.md", "fate": "renamed", "by": "owner",
         "renamed_to": "releases/2.1/2026-11-09-plan-cn-test.md"}) + "\n")
    moved = V.renames(vault, reports)
    check("a rename row maps the old path", moved.get("releases/2.1/release-2-1-cn-test-plan.md") == "releases/2.1/2026-11-09-plan-cn-test.md")
    check("an old name kept as an alias maps the old path", moved.get("meetings/20261112-sync-eng-qa.md") == "meetings/2026-11-12-sync-eng-qa.md")
    check("a title alias maps nothing", not any(k.endswith("/T.md") for k in moved))

    import datetime
    now = datetime.datetime(2026, 11, 12, 18, 0).astimezone()
    text = '---\ntype: "meeting"\ndate: "2026-11-12"\n---\n\n- [ ] [MH-3975](https://j/browse/MH-3975) who re-tests 1.0.25? · PM lead\n'
    state = {"questions": {}, "built": {}}
    Q.harvest(state, Q.meeting_candidates("meetings/20261112-sync-eng-qa.md", text, ["sync-eng-qa"]), now, lambda k: None,
              keys=["sync-eng-qa"])
    (qid, r), = state["questions"].items()
    ids = Q.follow(state, moved)
    check("the record follows the rename", ids == [qid] and r["sources"][0].startswith("meetings/2026-11-12-sync-eng-qa.md#")
          and r["first"]["where"] == "meetings/2026-11-12-sync-eng-qa.md")
    check("following twice changes nothing", Q.follow(state, moved) == [])
    Q.harvest(state, Q.meeting_candidates("meetings/2026-11-12-sync-eng-qa.md", text, ["sync-eng-qa"]), now, lambda k: None,
              keys=["sync-eng-qa"])
    check("the renamed note's box is its record, not a new one", list(state["questions"]) == [qid] and len(r["sources"]) == 1)

    m = {"files": ["today.md"], "native": ["meetings/20261112-sync-eng-qa.md", "releases/2.1/release-2-1-cn-test-plan.md"],
         "sources": {}, "seen": {}}
    check("the manifest follows", V.follow_manifest(m, moved) == ["native"]
          and m["native"] == ["meetings/2026-11-12-sync-eng-qa.md", "releases/2.1/2026-11-09-plan-cn-test.md"])

    old_native = ["meetings/20261112-sync-eng-qa.md", "releases/2.1/release-2-1-cn-test-plan.md", "reference/gone.md"]
    native_now = {"meetings/2026-11-12-sync-eng-qa.md", "releases/2.1/2026-11-09-plan-cn-test.md"}
    check("a renamed note has not gone by hand; a vanished one has",
          V.gone_by_hand(vault, old_native, native_now, set(), None, moved) == ["reference/gone.md"])

sys.exit(1 if failures else 0)
