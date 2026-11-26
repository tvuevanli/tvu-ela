#!/usr/bin/env python3
"""Dead links and quiet notes, offline: a link written inside code is not a link; a dead link in a generated page is
settled by the sync (a successor from the rename history, a project's folder note, a build's line page; else plain
text keeping its label); `tidy --links --unlink` does the same to a note the vault owns and logs each one; a work
note's body date survives a property change and moves on a body change; Friday's quiet list names a live work note
quiet for two weeks with what it waits for, and leaves out a done one and one in history/."""
import datetime, json, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import vault as V  # noqa: E402

failures = 0


def check(name, cond):
    global failures
    print(("ok   " if cond else "FAIL ") + name)
    failures += 0 if cond else 1


def put(vault, rel, text):
    p = os.path.join(vault, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(text)


t = "a [[dead]] b [[dead|Label]] c [[dead#h\\|T]] `[[dead]]` [L](dead.md) [[live]] ![[dead]]\n```\n[[dead]]\n```\n"
check("a link inside a code span or fence is not a link", V.link_targets("`[[x]]`\n```\n[[y]]\n```\n[[z]]") == ["z"])
u = V.unlink_text(t, ["dead"])
check("unlinked: the label kept, the bare target as written, code untouched, other links kept",
      u.startswith("a dead b Label c T `[[dead]]` L [[live]] dead\n```\n[[dead]]\n```"))
check("repaired: heading, alias and a table's escaped pipe kept",
      "[[new/x#h\\|T]]" in V.repair_text(t, [("dead", "new/x")]) and "[L](new/x.md)" in V.repair_text(t, [("dead", "new/x")]))

with tempfile.TemporaryDirectory() as vault, tempfile.TemporaryDirectory() as reports:
    put(vault, "projects/p1/p1.md", "---\ntype: \"project\"\n---\n# P\n")
    put(vault, "releases/2.1/2.1.md", "---\ntype: \"line\"\n---\n# 2.1\n")
    put(vault, "archive/series-2026-11.md", "---\ntype: \"meeting\"\n---\n# S\n")
    os.makedirs(os.path.join(reports, "ela"))
    open(os.path.join(reports, "ela", "vault-removed.jsonl"), "w").write(json.dumps(
        {"path": "meetings/series.md", "renamed_to": "archive/series-2026-11.md"}) + "\n")
    planned = {"reference/days/2026/2026-11-23-brief.md":
               "[[releases/2.1/2026-11-20-build-100-to-qa-aws3|build 100]] [[projects/p1]] [[meetings/series]] "
               "[[gone|the old page]] [[today]] `[[x]]`\n", "today.md": "# today\n"}
    got, done = V.settle_links(dict(planned), vault, reports)
    page = got["reference/days/2026/2026-11-23-brief.md"]
    check("a generated page: a build's note → its line page, a project folder → its folder note, a renamed note → its successor",
          "[[releases/2.1/2.1|build 100]]" in page and "[[projects/p1/p1]]" in page and "[[archive/series-2026-11]]" in page)
    check("a generated page: no successor → plain text with its label; a page this sync writes still resolves; code kept",
          "the old page" in page and "[[gone" not in page and "[[today]]" in page and "`[[x]]`" in page)
    check("settle reports each act", sorted(x[2] for x in done) == ["", "archive/series-2026-11", "projects/p1/p1", "releases/2.1/2.1"])

    put(vault, "reference/owned.md", "---\ntype: \"review\"\n---\n# O\n\nSee [[gone|the old page]] and [[projects/p1]].\n")
    fixes, unresolved, gen = V.link_repairs(vault, reports)
    check("tidy --links: a folder link repaired, the dead one unresolved", fixes.get("reference/owned.md") == [("projects/p1", "projects/p1/p1")]
          and ("reference/owned.md", "gone") in unresolved)
    now = datetime.datetime(2026, 11, 26, 12)
    V.unlink_dead(vault, reports, [("reference/owned.md", "gone")], now)
    text = open(os.path.join(vault, "reference/owned.md")).read()
    rows = [json.loads(l) for l in open(os.path.join(reports, "ela", "vault-unlinked.jsonl"))]
    check("unlink_dead: plain text in the note, the link and its line logged first",
          "See the old page and" in text and rows[0]["target"] == "gone" and "[[gone|the old page]]" in rows[0]["lines"][0])

with tempfile.TemporaryDirectory() as vault:
    fri = datetime.date(2026, 11, 27)
    put(vault, "ela/2026-11-01-plan-a.md", "---\ntype: \"plan\"\nstatus: \"live\"\nwaits-on: \"the web team\"\n---\n# Plan A\n\nbody\n")
    put(vault, "ela/2026-11-01-plan-b.md", "---\ntype: \"plan\"\nstatus: \"live\"\n---\n# Plan B\n\n- [ ] A\n- [ ] B\n")
    put(vault, "ela/2026-11-01-plan-c.md", "---\ntype: \"plan\"\nstatus: \"done\"\n---\n# Plan C\n")
    put(vault, "ela/history/2026-11-01-plan-d.md", "---\ntype: \"plan\"\nstatus: \"live\"\n---\n# Plan D\n")
    put(vault, "ela/2026-11-20-plan-e.md", "---\ntype: \"plan\"\nstatus: \"live\"\n---\n# Plan E\n")
    put(vault, "ela/page.md", "---\ntype: \"system\"\n---\n# a page\n")
    first = V.body_dates(vault, None, fri)
    check("a first reading starts no later than today, pages left out", "ela/page.md" not in first and all(v[1] <= fri.isoformat() for v in first.values()))
    old = {r: [v[0], "2026-11-05"] for r, v in first.items()}
    old["ela/2026-11-20-plan-e.md"][1] = "2026-11-20"
    put(vault, "ela/2026-11-01-plan-a.md", "---\ntype: \"plan\"\nstatus: \"live\"\nwaits-on: \"the web team\"\nnext: \"x\"\n---\n# Plan A\n\nbody\n")
    b = V.body_dates(vault, old, fri)
    check("a property change keeps the body's date", b["ela/2026-11-01-plan-a.md"][1] == "2026-11-05")
    rows = V.quiet_notes(vault, b, fri)
    names = [r[0] for r in rows]
    check("quiet: live notes unchanged 14 days, not a done one, not history/, not a recent one",
          names == ["ela/2026-11-01-plan-a.md", "ela/2026-11-01-plan-b.md"])
    check("quiet: what each waits for, from its own properties",
          rows[0][3] == "the web team" and rows[1][3] == "your word (2 open boxes)")
    sec = V.quiet_section(rows, fri)
    check("the section: one plain line, the list folded, no box to tick", sec.startswith("## Quiet for two weeks")
          and "> [!note]-" in sec and "[ ]" not in sec)
    put(vault, "ela/2026-11-01-plan-b.md", "---\ntype: \"plan\"\nstatus: \"live\"\n---\n# Plan B\n\n- [ ] A\n")
    check("a body change moves the date to today", V.body_dates(vault, b, fri)["ela/2026-11-01-plan-b.md"][1] == fri.isoformat())

print(f"{failures} failure(s)")
sys.exit(1 if failures else 0)
