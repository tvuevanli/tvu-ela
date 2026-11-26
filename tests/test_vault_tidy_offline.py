#!/usr/bin/env python3
"""The vault tidy, offline (ADR 0025): a done work note at the top of ela/ or reference/ that is quiet moves to that
home's history/ by a rename row tagged with the pass and its batch, its path links rewritten in the notes the vault
owns; a live note, a permanent page, a report, a project's note, one closed today or unstamped, one edited since the
sync wrote it, one open in Obsidian and one with a namesake in history/ stay; the sync does nothing until armed and
moves at most its cap; a failed batch is put back whole and logged; an undo replays a batch backwards and appends its
rows; the rename map resolves an undone move to the original; broken links are repaired from the rename history, in
owned notes only."""
import datetime, json, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import vault as V  # noqa: E402

failures = 0


def check(name, cond):
    global failures
    print(("ok   " if cond else "FAIL ") + name)
    failures += 0 if cond else 1


def note(vault, rel, kind, status=None, archived="2026-11-20", body=""):
    p = os.path.join(vault, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fl = [f'title: "{os.path.basename(rel)[:-3]}"', f'type: "{kind}"', 'date: "2026-11-10"'] + \
         ([f'status: "{status}"'] if status else []) + ([f'archived: "{archived}"'] if archived and status == "done" else [])
    text = "---\n" + "\n".join(fl) + "\n---\n\n# T\n\n" + body
    open(p, "w").write(text)
    return text


def read(vault, rel):
    return open(os.path.join(vault, rel)).read()


def log(reports):
    try:
        return [json.loads(l) for l in open(os.path.join(reports, "ela", "vault-removed.jsonl"))]
    except OSError:
        return []


NOW = datetime.datetime(2026, 11, 27, 18, 0)

with tempfile.TemporaryDirectory() as tmp:
    vault, reports = os.path.join(tmp, "vault"), os.path.join(tmp, "reports")
    note(vault, "ela/2026-11-20-plan-done.md", "plan", "done")
    note(vault, "ela/2026-11-21-plan-live.md", "plan", "live")
    note(vault, "ela/2026-11-22-plan-today.md", "plan", "done", archived="2026-11-27")
    note(vault, "ela/2026-11-22-plan-unstamped.md", "plan", "done", archived=None)
    note(vault, "ela/2026-11-23-plan-twin.md", "plan", "done")
    note(vault, "ela/history/2026-11-23-plan-twin.md", "plan", "done")
    note(vault, "ela/2026-11-24-plan-open.md", "plan", "done")
    gen = note(vault, "reference/2026-11-24-deep-mh-2.md", "ticket", "done")
    open(os.path.join(vault, "reference/2026-11-24-deep-mh-2.md"), "a").write("his line\n")
    note(vault, "ela/overview.md", "guide")
    note(vault, "ela/working-picture.md", "report", "superseded")
    note(vault, "reference/2026-11-11-deep-mh-1.md", "ticket", "done")
    note(vault, "projects/p1/2026-11-10-review-x.md", "review", "done")
    note(vault, "projects/p1/p1.md", "project",
         body="| a | [[ela/2026-11-20-plan-done\\|the plan]] |\n- [[ela/2026-11-20-plan-done#^b1]]\n")
    note(vault, "today.md", "today", body="[[ela/2026-11-20-plan-done|the plan]]\n")
    os.makedirs(os.path.join(vault, ".obsidian"))
    json.dump({"main": {"type": "split", "children": [{"type": "leaf", "state": {"state": {"file": "ela/2026-11-24-plan-open.md"}}}]}},
              open(os.path.join(vault, ".obsidian", "workspace.json"), "w"))
    json.dump({"files": ["today.md"], "wrote": {"reference/2026-11-24-deep-mh-2.md": V.digest(gen)}},
              open(os.path.join(vault, V.MANIFEST), "w"))

    moves, held = V.tidy_plan(vault, NOW)
    check("only quiet done work notes in ela/ and reference/ move",
          sorted(m["note"] for m in moves) == ["ela/2026-11-20-plan-done.md", "reference/2026-11-11-deep-mh-1.md"])
    check("each to its home's history/, the name kept",
          {m["to"] for m in moves} == {"ela/history/2026-11-20-plan-done.md", "reference/history/2026-11-11-deep-mh-1.md"})
    why = {h["note"]: h["why"] for h in held}
    check("closed today waits", why.get("ela/2026-11-22-plan-today.md") == "closed today")
    check("unstamped waits for its stamp", why.get("ela/2026-11-22-plan-unstamped.md") == "no archived stamp yet")
    check("a namesake in history/ is his word, never a silent skip", "your word" in why.get("ela/2026-11-23-plan-twin.md", ""))
    check("open in Obsidian waits", why.get("ela/2026-11-24-plan-open.md") == "open in Obsidian")
    check("edited since the sync wrote it waits", why.get("reference/2026-11-24-deep-mh-2.md") == "edited since the sync wrote it")
    check("the cap holds the rest", len(V.tidy_plan(vault, NOW, cap=1)[0]) == 1
          and any(h["why"] == "over this run's cap" for h in V.tidy_plan(vault, NOW, cap=1)[1]))

    check("the sync does nothing until armed", V.tidy_pass(vault, reports, NOW) == ([], []) and not log(reports))
    V.arm_tidy(reports, NOW)
    moved, held = V.tidy_pass(vault, reports, NOW)
    check("armed, the sync moves them", len(moved) == 2 and os.path.isfile(os.path.join(vault, "ela/history/2026-11-20-plan-done.md"))
          and not os.path.exists(os.path.join(vault, "ela/2026-11-20-plan-done.md")))
    check("and stamps the unstamped one for tomorrow", '"2026-11-27"' in read(vault, "ela/2026-11-22-plan-unstamped.md"))
    p1 = read(vault, "projects/p1/p1.md")
    check("a path link in a table keeps its escaped pipe", "[[ela/history/2026-11-20-plan-done\\|the plan]]" in p1)
    check("a block link keeps its block", "[[ela/history/2026-11-20-plan-done#^b1]]" in p1)
    check("a generated page is not rewritten in place", "[[ela/2026-11-20-plan-done|the plan]]" in read(vault, "today.md"))
    rows = log(reports)
    check("each move is a rename row by ela tagged with the pass and one batch",
          len(rows) == 2 and all(r["fate"] == "renamed" and r["by"] == "ela" and r["pass"] == "tidy" for r in rows)
          and len({r["batch"] for r in rows}) == 1)
    m = V.renames(vault, reports)
    check("the rename map follows the moves", m.get("ela/2026-11-20-plan-done.md") == "ela/history/2026-11-20-plan-done.md")
    check("the gone-by-hand pass does not report a moved note",
          V.gone_by_hand(vault, ["ela/2026-11-20-plan-done.md"], set(), set(), moved=m) == [])
    check("a second run moves nothing", V.tidy_plan(vault, NOW)[0] == [])

    dry = V.tidy_undo(vault, reports, "2026-11-27", now=NOW)
    check("the undo dry run lists the batch and writes nothing", len(dry["back"]) == 2 and len(log(reports)) == 2)
    V.tidy_undo(vault, reports, "2026-11-27", apply=True, now=NOW + datetime.timedelta(minutes=5))
    check("undo puts the notes back", os.path.isfile(os.path.join(vault, "ela/2026-11-20-plan-done.md"))
          and os.path.isfile(os.path.join(vault, "reference/2026-11-11-deep-mh-1.md")))
    check("undo rewrites the owned links back", "[[ela/2026-11-20-plan-done\\|the plan]]" in read(vault, "projects/p1/p1.md"))
    rows = log(reports)
    check("undo appends rows tagged undo_of, nothing taken out", len(rows) == 4 and all(r.get("undo_of") for r in rows[2:]))
    check("an undone move resolves to the original", "ela/2026-11-20-plan-done.md" not in V.renames(vault, reports)
          and V.renames(vault, reports).get("ela/history/2026-11-20-plan-done.md") in (None, "ela/2026-11-20-plan-done.md"))
    check("an undone batch is not undone twice", V.tidy_undo(vault, reports, "2026-11-27")["back"] == [])

    real = os.replace
    calls = [0]

    def flaky(a, b):
        calls[0] += 1
        if calls[0] == 2:
            raise OSError("disk")
        return real(a, b)
    V.os.replace = flaky
    try:
        V.tidy_apply(vault, reports, V.tidy_plan(vault, NOW)[0], NOW + datetime.timedelta(minutes=9))
        failed = False
    except OSError:
        failed = True
    finally:
        V.os.replace = real
    check("a failed batch raises and leaves every note where it was", failed
          and os.path.isfile(os.path.join(vault, "ela/2026-11-20-plan-done.md"))
          and os.path.isfile(os.path.join(vault, "reference/2026-11-11-deep-mh-1.md")))
    check("its rows are answered by rolled_back rows, and the map is back", any(r.get("rolled_back") for r in log(reports))
          and "ela/2026-11-20-plan-done.md" not in V.renames(vault, reports))

with tempfile.TemporaryDirectory() as tmp:
    vault, reports = os.path.join(tmp, "vault"), os.path.join(tmp, "reports")
    os.makedirs(os.path.join(reports, "ela"))
    open(os.path.join(reports, "ela", "vault-removed.jsonl"), "w").write("".join(json.dumps(r) + "\n" for r in (
        {"path": "a.md", "renamed_to": "b.md"}, {"path": "b.md", "renamed_to": "a.md"}, {"path": "a.md", "renamed_to": "b.md"})))
    os.makedirs(vault)
    check("a → b → a → b resolves to b", V.renames(vault, reports) == {"a.md": "b.md"})

with tempfile.TemporaryDirectory() as tmp:
    vault, reports = os.path.join(tmp, "vault"), os.path.join(tmp, "reports")
    note(vault, "releases/media-docker-services.md", "docker")
    note(vault, "projects/bot/history/answer.md", "report", "superseded")
    note(vault, "projects/bot/history/kept/readme.md", "readme", body="[[projects/bot/answer]] · [[bot/answer\\|the answer]] · [[gone/nowhere]]\n")
    note(vault, "reference/days/2026/2026-11-12-brief.md", "day", body="[[releases/docker|Docker]]\n")
    note(vault, "reference/x.md", "guide", body="[[2026-10-01-old]] and [[releases/docker]]\n")
    note(vault, "releases/2.1/history/2026-10-01-new.md", "review", "done")
    json.dump({"files": ["reference/days/2026/2026-11-12-brief.md"]}, open(os.path.join(vault, V.MANIFEST), "w"))
    os.makedirs(os.path.join(reports, "ela"))
    open(os.path.join(reports, "ela", "vault-removed.jsonl"), "w").write(
        json.dumps({"path": "releases/docker.md", "fate": "renamed", "by": "owner", "renamed_to": "releases/media-docker-services.md"}) + "\n"
        + json.dumps({"path": "releases/2.1/2026-10-01-old.md", "fate": "renamed", "by": "ela", "renamed_to": "releases/2.1/history/2026-10-01-new.md"}) + "\n")
    fixes, unresolved, generated = V.link_repairs(vault, reports)
    check("a renamed page's old path is repaired from the close log", ("releases/docker", "releases/media-docker-services") in fixes.get("reference/x.md", []))
    check("a bare old name follows its rename", ("2026-10-01-old", "2026-10-01-new") in fixes.get("reference/x.md", []))
    check("a folder path finds the one note of that name in the same project",
          ("projects/bot/answer", "projects/bot/history/answer") in fixes.get("projects/bot/history/kept/readme.md", [])
          and ("bot/answer", "projects/bot/history/answer") in fixes.get("projects/bot/history/kept/readme.md", []))
    check("a generated page is listed for its generator, never fixed in place",
          "reference/days/2026/2026-11-12-brief.md" in generated and "reference/days/2026/2026-11-12-brief.md" not in fixes)
    check("a link the record cannot place is named, never guessed", ("projects/bot/history/kept/readme.md", "gone/nowhere") in unresolved)
    V.repair_links(vault, fixes)
    check("the repair keeps a table's escaped pipe", "[[projects/bot/history/answer\\|the answer]]" in read(vault, "projects/bot/history/kept/readme.md"))
    check("a second repair finds nothing to fix in owned notes", V.link_repairs(vault, reports)[0] == {})

check("a project page's Notes link a note in ela/ by name", "[[2026-11-20-plan-x|" in V.project_tail(
    {"deadline": None, "keys": [], "links": [], "props": {}, "afterwards": [], "ticket": None},
    [{"inside": False, "path": "ela/history/2026-11-20-plan-x.md", "title": "X", "type": "plan", "date": "2026-11-20", "status": "done"}],
    datetime.date(2026, 11, 27)))

sys.exit(1 if failures else 0)
