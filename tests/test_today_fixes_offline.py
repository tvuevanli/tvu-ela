#!/usr/bin/env python3
"""today.md's "Since you last looked", offline (vault ela/2026-11-26-plan-fixes-followed-to-prod-one-home-per-fact.md,
phase 3): the fixes whose verdict changed since Home was last opened lead it, at most five lines in all, each linking
its row on the line page; a QA verdict is not told again as a fact; a your-call fix is a ruling ask, and rulings over
the ask cap are counted with their line page; the morning and changes pages link the row; his letter is kept."""
import datetime, json, os, sys, tempfile, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import vault as V  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

THU = datetime.date(2026, 11, 26)
LANES = [{"role": "qa", "lane": "qa-cn3", "shown": "QA-AWS3"}, {"role": "daily", "lane": "daily-wed", "shown": "daily-wed (UR test2)"},
         {"role": "prod", "lane": "prod-3", "shown": "prod-3 (UR/J2N Prod 3)"}]


def row(key, group, at, leaning=None):
    imp = {"group": group, "reason": "QA: the fix brought a regression (TC9)" if group == "blocks" else "unproven: the incidents were not read",
           "move": ["qa-cn3", "daily-wed"], "sig": f"s-{key}", "next": "a fix, then QA again", "kind": "App:partial",
           "leaning": leaning, "lean_reason": "QA: main fix works (14 Pass + 1 Fail); TC13: nothing puts it outside the fix" if leaning else None}
    return {"id": key, "key": key, "also": [], "title": f"title of {key}", "layer": "App", "priority": "P1", "position": "qa",
            "cells": {"qa-cn3": {"arrived": "100", "verdict": "fail", "version": "build 100", "at": at[:10],
                                 "history": [{"verdict": "fail", "version": "build 100", "at": at, "source": "QA report"}]}},
            "impact": imp}


train = {"line": "2.1", "at": "2026-11-26T09:00+08:00", "lanes": LANES,
         "rows": [row("MH-4097", "blocks", "2026-11-25T18:43"), row("MH-4100", "your-call", "2026-11-25T18:43", "does not block"),
                  row("MH-4101", "your-call", "2026-11-25T19:00", "blocks"), row("MH-4102", "your-call", "2026-11-25T19:10", "blocks"),
                  row("MH-4103", "your-call", "2026-11-25T19:20", "blocks"), row("MH-3000", "blocks", "2026-11-10T10:00")]}

lines = V.since_fixes([train], "2026-11-25T12:00:00+08:00")
check("only the fixes whose verdict changed since he looked, blocks first, each linking its row",
      len(lines) == 5 and lines[0].startswith("- MH-4097 fail on build 100 — blocks:") and "[[releases/2.1/2.1#^fix-mh-4097|its row]]" in lines[0]
      and not any("MH-3000" in l for l in lines))
check("before the first opening is recorded, no line", V.since_fixes([train], None) == [])


def note(path, props, body):
    return types.SimpleNamespace(path=path, props=props, body=body, title=path, front_lines=[])


changes = note("reference/days/2026/2026-11-26-changes.md", {"type": "day", "kind": "changes", "date": "2026-11-26"},
               "# What changed\n\n## Releases and versions\n\nThree lanes moved, all mediahub-frontend.\n\n"
               "## QA\n\nQA's verdict on build 100 is partial: MH-4097 failed a case.\n\n## Tickets\n\nMH-4097 went back to In Progress today.\n")
fcands = V.fix_asks([train], THU)
shown, more, _, state = V.settle_asks({}, fcands, THU)
desk = {"fixes": lines[:3], "fixes_waiting": V.fixes_waiting(fcands, shown, state)}
page = V.today_page(THU, [changes], desk, shown)
since = page.split("## Since you last looked", 1)[1].split("## Needs you", 1)[0]
check("Facts is now Since you last looked, the fixes leading it", "## Facts" not in page and since.strip().startswith("- **Fixes:** MH-4097 fail on build 100"))
check("a QA verdict is not told again as a fact once the fixes are there", "**QA:**" not in since and "partial: MH-4097" not in since)
check("at most five lines outside the fold", len([l for l in since.splitlines() if l.startswith("- ")]) <= V.SINCE_MAX)
needs = page.split("## Needs you", 1)[1].split("## Today", 1)[0]
check("a your-call fix is a ruling ask: ela's leaning as A with its reason, the other way as B, linking its row",
      "1. *ruling* · Does MH-4100's QA fail block QA-AWS3 → daily-wed (UR test2)? ela leans does not block" in needs
      and "- [ ] A (recommended): right: does not block" in needs and "- [ ] B: wrong: it blocks; say why under the ask" in needs
      and "→ [[releases/2.1/2.1#^fix-mh-4100|its row]]" in needs)
today = page.split("## Today", 1)[1]
check("rulings over the ask cap stay on the line page, and today.md says how many",
      "- 1 more deploy ruling waits on [[releases/2.1/2.1#Fixes on their way|the 2.1 line page]]" in today)

morning = "## FYI\n\n- [MH-4097](https://x/browse/MH-4097) preview stage bar failed on build 100.\n- MH-4200 unrelated.\n> - MH-4097 in a fold\n"
linked = V.link_fix_rows(morning, lines)
check("the morning and changes pages link a fix today.md tells to its row, once a line",
      "failed on build 100. → [[releases/2.1/2.1#^fix-mh-4097|its row]]" in linked and "MH-4200 unrelated.\n" in linked
      and "> - MH-4097 in a fold → [[releases/2.1/2.1#^fix-mh-4097|its row]]" in linked
      and V.link_fix_rows(linked, lines) == linked)

with tempfile.TemporaryDirectory() as reports:
    os.makedirs(os.path.join(reports, "train"))
    json.dump(train, open(os.path.join(reports, "train", "2.1.json"), "w"))
    check("the written trains are read", [t["line"] for t in V.written_trains(reports)] == ["2.1"])
    st = {"impact:MH-4100": {"first": "2026-11-26", "sig": "s-MH-4100", "slot": 1, "options": {"A": "ela train answer impact:MH-4100 A"}}}
    check("a letter on a ruling ask is the sync's to record", V.sync_handles("ela train answer impact:MH-4100 A"))
    acted = V.settle_one(reports, st, "impact:MH-4100", "A", "ela train answer impact:MH-4100 A", THU)
    kept = [json.loads(l) for l in open(os.path.join(reports, "train", "rulings.jsonl"))]
    check("his A is kept with its kind and ela's leaning as his ruling", acted and kept[0]["ruled"] == "does not block"
          and kept[0]["kind"] == "App:partial" and st["impact:MH-4100"]["answered"]["letter"] == "A")

if failures:
    print(f"\ntoday fixes: {len(failures)} failure(s)"); sys.exit(1)
print("\ntoday fixes: all offline checks passed")
