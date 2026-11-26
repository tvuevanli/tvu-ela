#!/usr/bin/env python3
"""Dead links, offline: a link written inside code is not a link; a dead link in a generated page is settled by the
sync (a successor from the rename history, a project's folder note, a build's line page; else plain text keeping its
label); `tidy --links --unlink` does the same to a note the vault owns and logs each one."""
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

print(f"{failures} failure(s)")
sys.exit(1 if failures else 0)
