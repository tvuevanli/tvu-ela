#!/usr/bin/env python3
"""review reader, offline: the reader file's check against its page, and the same verdict two mornings running."""
import os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "review"))
import review as RV  # noqa: E402

failures = 0


def check(name, cond):
    global failures
    print(("ok   " if cond else "FAIL ") + name)
    failures += 0 if cond else 1


page = """## Needs you

### 1. MH-1: the train carries build 77
MH-1 · 1st morning
- **Do:**
- [ ] Hold the train

### 2. FloSports device APIs
MH-2 · MH-3 · 2nd morning
- **Do:**
- [ ] apply 1 — post the lanes
"""
check("the page's items with their keys", RV.page_items(page) == [{"n": 1, "title": "MH-1: the train carries build 77", "keys": ["MH-1"]},
                                                                  {"n": 2, "title": "FloSports device APIs", "keys": ["MH-2", "MH-3"]}])
good = """| item | verdict | line |
|---|---|---|
| 1. MH-1: the train carries build 77 | tickable | Hold the train |
| 2. FloSports device APIs (MH-2) | handed back | the owner lookup is a roster read: `ela team` |

- **Read first:** item 1, rightly.
- **Skipped:** the sprint table, restated from items.
- **Missing:** nothing.
"""
check("a full reader file passes", RV.reader_check(page, good) == [])
bad = good.replace("| tickable |", "| fine |").replace("- **Missing:** nothing.\n", "") \
          .replace("| 2. FloSports", "| 3. Other | noise |  |\n| 2. FloSports")
f = RV.reader_check(page, bad)
check("a verdict outside the set, an item not on the page, an empty line and a missing page line each fail",
      "item 1: verdict 'fine' is not one of wrong, handed back, question, noise, tickable" in f and "item 3: not on the page" in f
      and "item 3: a verdict without its line" in f and "the page line **Missing:** is missing" in f)
check("an item with no verdict fails", "item 2: no verdict" in RV.reader_check(page, good.replace("| 2. FloSports device APIs (MH-2) | handed back | the owner lookup is a roster read: `ela team` |\n", "")))
with tempfile.TemporaryDirectory() as t:
    os.makedirs(os.path.join(t, "review"))
    open(os.path.join(t, "review", "2026-10-27-reader.md"), "w").write(good)
    open(os.path.join(t, "review", "2026-10-28-reader.md"), "w").write(good.replace("| tickable |", "| question |"))
    check("the same verdict on a key two mornings running is a repeat; tickable never is",
          RV.repeated_verdicts(t, "2026-10-28") == {"MH-2": "handed back"})
    check("one reader file is no repeat", RV.repeated_verdicts(t, "2026-10-27") == {})
sys.exit(1 if failures else 0)
