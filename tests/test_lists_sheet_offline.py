#!/usr/bin/env python3
"""The test and dev list pages as a sheet: one head table with the decided columns, and a folded callout for each row
that has more to say. Over a fixture json; no Jira, no roster."""
import json, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "testlist"))
import testlist as TL  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

TL._ROSTER = {"dev one": "Dev One (roster)"}            # the roster, as page_name reads it
FIX = os.path.join(ROOT, "tests", "fixtures")


def table(page):
    """The head table: [header cells], [[row cells]]; a cell's escaped pipe is not a column."""
    rows = [l for l in page.splitlines() if l.startswith("| ")]
    split = lambda l: [c.strip() for c in re.split(r"(?<!\\)\|", l)[1:-1]]  # noqa: E731
    return split(rows[0]), [split(l) for l in rows[1:]]


page = TL.render_page(json.load(open(os.path.join(FIX, "test-list-sheet.json"), encoding="utf-8")))
head, rows = table(page)
check("the test list's eight columns, in order", head == ["P", "ticket", "title", "status", "assignee", "verdict", "builds", "auto"])
check("every row has eight cells", rows and all(len(r) == 8 for r in rows))
check("a title is cut to 60 characters with …", len(rows[0][2]) <= 60 and rows[0][2].endswith("…"))
check("the status reads as Jira writes it", rows[0][3] == "Review")
check("the assignee as the roster writes it", rows[0][4] == "Dev One (roster)")
check("the verdict names the build", rows[0][5] == "❌ fail 2.1.78")
check("builds first → now", rows[0][6] == "78 → 80")
check("a row with no ticket: no ticket, status —", rows[1][1] == "no ticket" and rows[1][3] == "—")
check("auto reads yes", rows[2][7] == "yes")
check("a ticket whose page is missing shows —", rows[3][3] == "—" and rows[3][4] == "—")
check("three callouts: the steps-unknown row without ela saw has none", page.count("> [!note]- ") == 3 and "MH-1004 · how to verify" not in page)
check("a callout holds how to verify in full and ela saw", "> The volume slider in the Quick Edit dialog is disabled until the source task is running." in page
      and "> *ela saw*: slider disabled" in page)
check("the counts line stays", "4 open · P1 1 · P2 1 · P3 2 · 1 auto · 1 no ticket" in page)
check("the lead paragraph stays", "What QA should verify on QA-CN3" in page)

dev = TL.render_dev(json.load(open(os.path.join(FIX, "dev-list-sheet.json"), encoding="utf-8")))
head, rows = table(dev)
check("the dev list's eight columns, in order", head == ["P", "ticket", "title", "status", "developer", "due", "train", "blocked"])
check("every dev row has eight cells", rows and all(len(r) == 8 for r in rows))
check("a long title is cut to 60 characters with …", len(rows[0][2]) <= 60 and rows[0][2].endswith("…"))
check("a CJK title, with no space to cut at, is cut too", len(TL.short("\u4e1a" * 70)) == 60)
check("a past due date reads overdue since", rows[0][5] == "overdue since 2026-10-28")
check("the train is the Fix Version, else —", rows[0][6] == "MH 2.1" and rows[1][6] == "—")
check("blocked names its reason; the developer as the roster writes it, else —",
      rows[1][7] == "by MH-2003" and rows[0][4] == "Dev One (roster)" and rows[1][4] == "—")
check("one callout: the row with nothing more to say has none", dev.count("> [!note]- ") == 1 and "> - gap: Fixed In without a verdict" in dev)
check("held_by reads an open blocker before the status",
      TL.held_by("Blocked", {"issuelinks": [{"type": {"inward": "is blocked by"}, "inwardIssue": {"key": "MH-9", "fields": {"status": {"statusCategory": {"key": "indeterminate"}}}}}]}) == "by MH-9"
      and TL.held_by("On Hold", {"issuelinks": [{"type": {"inward": "is blocked by"}, "inwardIssue": {"key": "MH-9", "fields": {"status": {"statusCategory": {"key": "done"}}}}}]}) == "on hold"
      and TL.held_by("Review", {}) is None)
sys.exit(1 if failures else 0)
