#!/usr/bin/env python3
"""Needs you within its budget, offline: the vault counts the words outside folded callouts for every type, a box
behind a `> ` keeps its meaning for the vault, the brief and the review, and page-check fails a fourth open apply box
(vault to-read/2026-11-02-ela-and-vault-workflow-review.md, fix 4)."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ("vault", "brief", "review"):
    sys.path.insert(0, os.path.join(ROOT, "skills", d))
import vault as V  # noqa: E402
import brief as B  # noqa: E402
import review as RV  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

FOLD = "\n> [!note]- Evidence\n" + "\n".join("> " + "word " * 20 for _ in range(80)) + "\n"
day = V.Note("x", "x", "# B\n\n" + "word " * 1000 + FOLD + "\nAfter.\n", {"type": "day"})
check("a day page's folded words are not counted", V.reading_gate(day) == [])
check("outside_folds keeps what follows the fold", "After." in V.outside_folds(day.body) and "> word" not in V.outside_folds(day.body))
over = V.Note("x", "x", "# B\n\n" + "word " * 1400 + FOLD, {"type": "day"})
check("the open words still count, and the warning says what it left out",
      any(p.startswith("1,401 words, budget 1,200 (folded callouts not counted)") for p in V.reading_gate(over)))
check("a page with no fold keeps the plain warning", V.reading_gate(V.Note("x", "x", "# B\n\n" + "word " * 1400, {"type": "day"})) == ["1,401 words, budget 1,200"])
plan = V.Note("x", "x", "# P\n\n" + "word " * 500 + "\n> [!note]- Detail\n> " + "word " * 600 + "\n\n" + "word " * 200, {"type": "plan"})
check("a plan counts the words on both sides of a fold, not only above the first one", V.reading_gate(plan) == [])
opened = V.Note("x", "x", "# B\n\n> [!note] Open\n> " + "word " * 1400, {"type": "day"})
check("an open callout is read and counted", V.reading_gate(opened) != [])

PAGE = """# Morning brief

## Needs you

### 1. First
MH-1 · a thing · Dev Person · 1st morning
- a fact
- **Do:**
- [ ] apply 1 — comment on MH-1
- [ ] apply 2 — label MH-1

### 2. Second
MH-2 · another · Dev Person · 1st morning
- **Do:**
- [ ] apply 3 — assign MH-2

> [!note]- 2 more
> ### 3. Third
> MH-3 · third · Dev Person · 2nd morning
> - a fact
> - **Do:**
> - [ ] apply 4 — comment on MH-3
>
> ### 4. Fourth
> MH-4 · fourth · Dev Person · 1st morning
> - **Do:**
> - [x] apply 5 — post the status

## QA today

- [ ] send 6 — QA today on qa-cn3 (your ela: lines applied first)
"""
ACTS = [{"n": i, "tier": 3, "text": "t", "command": "ela jira comment MH-1 x"} for i in range(1, 6)] + \
       [{"n": 6, "tier": 3, "rule": "qa-today", "send_box": True, "command": "ela slack post https://x.slack.com/archives/C1/p1234567890123456 --team-thread"}]
check("page-check sees a folded box as a box", B.page_check(PAGE, ACTS) == ([], []))
check("three apply boxes stand open; the folded ones are not among them", B.unfolded_applies(PAGE) == [1, 2, 3])
four = PAGE.replace("> [!note]- 2 more\n> ### 3. Third", "### 3. Third").replace("> MH-3", "MH-3").replace("> - a fact", "- a fact") \
           .replace("> - **Do:**\n> - [ ] apply 4", "- **Do:**\n- [ ] apply 4")
check("a fourth open apply box is found", B.unfolded_applies(four)[3:] == [4])
check("the tier check reads a folded tier-3 box as written", B.tier_check(PAGE, ACTS) == [])
check("needs_you reads the folded items too", [sorted(k) for k, _ in B.needs_you(PAGE)] == [["MH-1"], ["MH-2"], ["MH-3"], ["MH-4"]])
check("carried counts a folded item", B.carried([PAGE, PAGE]).get("MH-3") == 2)
check("review finds the folded items with their titles", [RV.items(PAGE)[i][0].lstrip("> ") for i in range(4)] == ["### 1. First", "### 2. Second", "### 3. Third", "### 4. Fourth"])
fails = RV.lint(PAGE.split("## QA today")[0], ACTS[:5], brief=True)   # the send box section is not under test here
check("review lint passes the folded items: boxes behind `> ` are boxes, a lone `>` ends the Do lines" + (": " + "; ".join(fails) if fails else ""), fails == [])
check("a vault box behind `> ` is a box, ticked or not", V.APPLY_BOX.search("> - [ ] apply 4 — x") is not None and [m.group(1) for m in V.TICKED.finditer(PAGE)] == ["apply 5 — post the status"])
import json, tempfile
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
    json.dump([{"n": 4, "by_owner": {"at": "2026-11-02T09:40:00+0800", "comment": True}}, {"n": 5, "applied": "2026-11-02T10:18:00+0800"}], fh)
out = V.action_states(PAGE, fh.name)
os.unlink(fh.name)
check("action states keep the fold: the owner's own line is quoted under its box, the applied one ticked with its time",
      "> - [ ] apply 4 — comment on MH-3\n> - [x] I handled it myself — not apply 4 · you commented in Jira 09:40" in out
      and "> - [x] apply 5 — post the status · applied 10:18" in out)
print(f"{len(failures)} failures" if failures else "page fold: all checks passed")
sys.exit(1 if failures else 0)
