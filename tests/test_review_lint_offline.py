#!/usr/bin/env python3
"""review lint, offline: each mechanical check on a page ela writes, passing and failing."""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "review"))
import review as RV  # noqa: E402

failures = 0


def check(name, cond):
    global failures
    print(("ok   " if cond else "FAIL ") + name)
    failures += 0 if cond else 1


good = """# Morning brief · Wed 2026-10-28

## Needs you

### 1. MH-1: the train carries build 77
MH-1 · on QA-AWS3 · 1st morning
- facts
- **Do:**
- [ ] Hold the train · decide at the 10:00 scrum
- [ ] apply 1 — ask the release thread which ticket carries the fixes

### 2. MH-2: a QA bug
MH-2 · Backlog · 1st morning
- **Do:**
- [ ] apply 2 — assign MH-2 to the app layer

## FYI

Counts (24 h): 39 commits · 30 close-ready · 8 commits on feature/x · commits, 7 days: 120 commits, 7 days
"""
acts = [{"n": 1}, {"n": 2}]
counts = {"commits": 39, "close_ready": 30}
check("a clean page passes", RV.lint(good, acts, counts, {"mh2.1@qa-q28"}) == [])
bad = good.replace("- [ ] Hold the train · decide at the 10:00 scrum", "- Hold the train\n- [ ] /ela:breakdown MH-1\n- [ ] draft the hand-off") \
          .replace("MH-2 · Backlog", "MH-1 · MH-2 · Backlog").replace("39 commits", "41 commits") + "\nSee apply 3 and the frontend.\n"
f = RV.lint(bad, acts, counts, {"mh2.1@qa-q28"})
check("a Do line without a box fails", any("a Do line without a box" in x for x in f))
check("a slash command or a draft left for him fails", sum("left for him to do" in x for x in f) == 2)
check("apply N with no action and no box fails twice", "apply 3: no such action in the actions file" in f
      and "apply 3: named without its box on the page" in f)
check("a key that is two items fails", any(x.startswith("MH-1: an item 2 times") for x in f))
check("a count other than the day's fails; a scoped count does not", f.count("commits: the page says 41, the day's counts say 39") == 1
      and not any("says 8" in x or "says 120" in x for x in f))
check("a box with no apply number and no place of decision fails; 'your call' passes",
      any("does not say where it is decided: Promote" in x for x in RV.lint(good.replace("- [ ] apply 1", "- [ ] Promote build 77\n- [ ] apply 1")))
      and RV.lint(good.replace(" · decide at the 10:00 scrum", " · your call, no write"), acts, counts) == [])
order = good.replace("- [ ] apply 1 — ask", "- [ ] apply 3 — ask").replace("- [ ] Hold the train · decide at the 10:00 scrum", "- [ ] apply 4 — x\n- [ ] apply 1 — y")
check("apply numbers that descend within an item fail; a gap does not",
      [x for x in RV.lint(order) if "descend" in x] == ["1. MH-1: the train carries build 77: action numbers descend: 4, 1, 3"]
      and not any("descend" in x for x in RV.lint(good.replace("apply 2 —", "apply 9 —"))))
check("'the frontend' fails", any('"the frontend"' in x for x in f))
check("a bundle no read holds fails, an official is not checked",
      RV.lint("on mh2.1@qa-q26 and MediaHub 2.1.15", None, None, {"mh2.1@qa-q28"}) == ["mh2.1@qa-q26: a bundle no read of the last 14 days holds"])
check("a status outside the closed set fails", any("not in the closed set" in x for x in RV.lint('---\nstatus: "doing"\n---\n# x\n')))
check("a status in the set passes", RV.lint('---\nstatus: "parked"\n---\n# x\n') == [])
check("in the vault a bare key fails and a linked one passes",
      RV.lint("MH-5 and [MH-6](https://j/browse/MH-6)", in_vault=True) == ["MH-5: a ticket key that is not a link"])
check("in a reports source the vault links keys, except in code spans",
      RV.lint("MH-5 and `MH-7`") == ["MH-7: a ticket key that is not a link"])
check("a roster person written by their Jira name fails; the display name and a code span pass",
      RV.lint("assign MH-1 to Andyzhao; Andy Zhao drives; `Andyzhao`", handles={"Andyzhao": "Andy Zhao"})
      == ["Andyzhao: a Jira name; the page writes Andy Zhao"]
      and RV.lint("Andy Zhao drives", handles={"Andyzhao": "Andy Zhao"}) == [])
sm = "# B\n\nFour drafts are on their fifth morning.\n\n## Needs you\n\n" + "".join(
    f"### {i}. x\nMH-{i} · y · {o} morning\n\n" for i, o in enumerate(["5th", "5th", "4th", "5th", "1st"], 1))
check("a summary's carried count that the items do not bear out fails; one that matches passes",
      [x for x in RV.lint(sm) if x.startswith("summary")] == ['summary: "Four drafts are on their fifth morning", but 3 items say so']
      and not any(x.startswith("summary") for x in RV.lint(sm.replace("Four drafts", "Three drafts"))))
import tempfile  # noqa: E402
with tempfile.TemporaryDirectory() as t:
    os.makedirs(os.path.join(t, "actions", "2026-10-29"))
    for f in ("MH-1-a.txt", "MH-2-assign.txt"):
        open(os.path.join(t, "actions", "2026-10-29", f), "w").write("x")
    ap = os.path.join(t, "2026-10-29-actions.json")
    check("an action file no drafted command names is stray",
          RV.stray_action_files(ap, [{"command": f"ela jira comment MH-1 --from-file {t}/actions/2026-10-29/MH-1-a.txt"}]) == ["MH-2-assign.txt"]
          and RV.stray_action_files(os.path.join(t, "2026-10-30-actions.json"), []) == [])
ut = {"build": "78", "due": "2026-10-29"}
check("the build under test called untested or unreported fails; the verdict build and a due time pass",
      [x[:52] for x in RV.lint("Build 78 is untested. Build 77 has no QA report. Build 78's verdict is due 17:00.", testing=ut)]
      == ["build 78 is under test, its report due 10-29 evening"])
long = "# Morning brief\n\n" + "word " * 1400
check("a day page over the vault's reading budget gives the vault's line; within it, or not a day page, nothing",
      RV.budget("/r/runner/2026-10-28-brief.md", long, "/no/actions.json") == "1,402 words, budget 1,200"
      and RV.budget("/r/runner/2026-10-28-brief.md", "# B\n\nshort", "/no/actions.json") is None
      and RV.budget("/r/review/2026-10-28-reader.md", long) is None)
sys.exit(1 if failures else 0)
