#!/usr/bin/env python3
"""The fixes on their way (train fixes.py), offline: each row's impact on its next move under the hiding bar, the line
page's block, today.md's lines and asks, and the owner's rulings. Shapes from the 2.1 train of 2026-11-26: a fix that
passed QA on build 99 and fails on build 100 (MH-4054), QA's "not fixed" (MH-4048), QA's main-fix-works with a
regression (MH-4097), a fail on build 100 with build 101 waiting for QA (MH-4065), and a failed case whose follow-up
fix passed (vault ela/2026-11-26-plan-fixes-followed-to-prod-one-home-per-fact.md, phases 2 and 3)."""
import datetime, json, os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "train"))
import fixes as FX  # noqa: E402

C, cur = {}, None
for ln in open(os.path.join(ROOT, "tests", "fixtures", "qajira", "comments.txt"), encoding="utf-8"):
    if ln.startswith("=== "):
        cur = ln[4:].strip(); C[cur] = ""
    elif cur:
        C[cur] += ln

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

QA = {"erin zhang"}
LANES = [{"role": "qa", "lane": "qa-cn3", "shown": "QA-AWS3"}, {"role": "daily", "lane": "daily-wed", "shown": "daily-wed (UR test2)"},
         {"role": "prod", "lane": "prod-3", "shown": "prod-3 (UR/J2N Prod 3)"}]


def issue(key, text, links=()):
    return {"key": key, "fields": {"status": {"name": "Review"}, "issuelinks": list(links)},
            "comments": [{"author": {"displayName": "Erin Zhang"}, "created": "2026-11-25T01:00", "body": text, "id": "300"}]}


def h(verdict, version, at, source="QA report"):
    return {"verdict": verdict, "version": version, "at": at, "source": source}


def row(key, verdict, arrived="100", history=(), position="qa", extra_cells=None, **kw):
    cells = {"qa-cn3": {"arrived": arrived, "verdict": verdict, "version": f"build {arrived}" if verdict != "untested" else None,
                        "at": "2026-11-25", "source": "QA report", "history": list(history)}}
    cells.update(extra_cells or {})
    return dict({"id": key, "key": key, "also": [], "title": f"title of {key}", "layer": "App", "priority": "P1", "position": position,
                 "regression": False, "cells": cells, "change": None, "qa_only": False}, **kw)


def judged(rows, issues, incidents=(), rulings=()):
    return {r["key"]: r for r in FX.enrich(rows, LANES, issues, [], QA, incidents, rulings)}


rows = [row("MH-4054", "fail", history=[h("pass", "build 99", "2026-11-20T18:48"), h("fail", "build 100", "2026-11-23T18:38")], qa_only=True),
        row("MH-4048", "fail", history=[h("fail", "build 100", "2026-11-23T18:38")]),
        row("MH-4097", "fail", history=[h("fail", "build 100", "2026-11-25T18:43")]),
        row("MH-4065", "untested", arrived="101", history=[h("fail", "build 100", "2026-11-25T18:43")]),
        row("MH-4100", "fail", history=[h("fail", "build 100", "2026-11-25T18:43")]),
        row("MH-4111", "pass", arrived="100", history=[h("pass", "build 100", "2026-11-25T18:43")]),
        row("MH-4200", "pass", position="prod")]
issues = {"MH-4048": issue("MH-4048", C["not-fixed"]), "MH-4097": issue("MH-4097", C["regressed"]),
          "MH-4065": issue("MH-4065", C["cases"]), "MH-4100": issue("MH-4100", C["follow-up"])}
got = judged([dict(r) for r in rows], issues)
g = {k: r["impact"]["group"] for k, r in got.items()}
check("passed QA on build 99, fails on build 100: blocks, first-hand (MH-4054)",
      g["MH-4054"] == "blocks" and got["MH-4054"]["impact"]["reason"] == "passed QA on build 99, fails on build 100")
check("QA's own verdict not fixed: blocks, naming the failed cases (MH-4048)",
      g["MH-4048"] == "blocks" and got["MH-4048"]["impact"]["reason"] == "QA: not fixed (TC7, TC9)")
check("QA's own words that the fix brought a regression: blocks (MH-4097)",
      g["MH-4097"] == "blocks" and "regression" in got["MH-4097"]["impact"]["reason"])
check("a fail on build 100 with build 101 not yet tested: not yet verified, the earlier fail and its cases named (MH-4065)",
      g["MH-4065"] == "unverified" and got["MH-4065"]["impact"]["reason"] == "failed build 100 (TC13, TC18); build 101 waits for QA")
check("a failed case whose follow-up fix passed QA on a build that moves, incidents read, no earlier pass: does not block",
      g["MH-4100"] == "no-block" and "follow-up MH-4111 passed QA on build 100" in got["MH-4100"]["impact"]["reason"])
check("a QA pass is ready; a fix on prod is not on its way", g["MH-4111"] == "ready" and g["MH-4200"] == "arrived")
check("the failed case is QA's own row and the verdict links QA's comment",
      FX.test_text(got["MH-4048"]).startswith("TC7 admin Off") and "focusedCommentId=300" in FX.verdict_text(got["MH-4048"], "qa-cn3"))

# every test fails closed
got = judged([dict(r) for r in rows], issues, incidents=None)
imp = got["MH-4100"]["impact"]
check("incidents not read: the same case is your call, ela leaning does not block with its reason drafted",
      imp["group"] == "your-call" and imp["leaning"] == "does not block" and "the incidents were not read" in imp["reason"]
      and "QA: main fix works (14 Pass + 1 Fail)" in imp["lean_reason"])
got = judged([dict(r) for r in rows], issues, incidents=[{"key": "MH-4300", "summary": "customer stream down, see MH-4100"}])
check("an incident naming the key: your call, never does not block", got["MH-4100"]["impact"]["group"] == "your-call")
early = [dict(r) for r in rows]
early[4] = row("MH-4100", "fail", history=[h("pass", "build 98", "2026-11-18T18:00"), h("fail", "build 100", "2026-11-25T18:43")])
got = judged(early, issues)
check("an earlier pass on record makes it blocks (passed before, fails now)", got["MH-4100"]["impact"]["group"] == "blocks")
same = [dict(r) for r in rows]
same[4] = row("MH-4100", "fail", history=[h("pass", "2.2.136 build 196", "2026-11-25T13:37", "comment by Erin Zhang"), h("fail", "build 100", "2026-11-25T18:43")])
got = judged(same, dict(issues, **{"MH-4100": issue("MH-4100", C["pass"])}))
check("QA's pass and QA's fail the same day are a conflict, not a regression: your call, leaning blocks (MH-4016 shape)",
      got["MH-4100"]["impact"]["group"] == "your-call" and got["MH-4100"]["impact"]["leaning"] == "blocks"
      and "says pass, a later QA word says fail" in got["MH-4100"]["impact"]["reason"])
late = [dict(r) for r in rows]
late[5] = row("MH-4111", "pass", arrived="102", history=[h("pass", "build 102", "2026-11-26T18:43")])
got = judged(late, issues)
check("a follow-up that passed only on a newer build than the one moving proves nothing: your call",
      got["MH-4100"]["impact"]["group"] == "your-call" and "follow-up MH-4111 has no QA pass on a build that moves" in got["MH-4100"]["impact"]["reason"])
bare = [dict(r) for r in rows]
got = judged(bare, {k: v for k, v in issues.items() if k != "MH-4100"})
check("a report-only fail (no QA comment in Jira) is your call, leaning blocks",
      got["MH-4100"]["impact"]["group"] == "your-call" and got["MH-4100"]["impact"]["leaning"] == "blocks"
      and got["MH-4100"]["impact"]["kind"] == "App:report-only")

# the owner's rulings: kept with their kind, his word on this very case decides it, a blocks ruling of the kind stops a firm call
with tempfile.TemporaryDirectory() as reports:
    got = judged([dict(r) for r in rows], issues, incidents=None)
    train = {"line": "2.1", "lanes": LANES, "rows": list(got.values())}
    now = datetime.datetime(2026, 11, 26, 10, 0, tzinfo=datetime.timezone.utc)
    rec = FX.answer(reports, "impact:MH-4100", "B", train, None, now)
    check("B rules the other way; without a cause it waits for one",
          rec["ruled"] == "blocks" and rec["kind"] == "App:case-follow-up" and rec["corpus"] == "waiting for a cause")
    again = judged([dict(r) for r in rows], issues, incidents=None, rulings=FX.read_rulings(reports))
    check("his ruling on the same case decides it, cited", again["MH-4100"]["impact"]["group"] == "blocks"
          and again["MH-4100"]["impact"]["reason"].startswith("your ruling 11-26"))
    other = [dict(r) for r in rows] + [row("MH-4101", "fail", history=[h("fail", "build 100", "2026-11-25T18:43")])]
    iss = dict(issues, **{"MH-4101": issue("MH-4101", C["follow-up"])})
    firm = judged(other, iss, incidents=[], rulings=FX.read_rulings(reports))
    check("a blocks ruling of the same kind keeps another key from a firm does-not-block (a precedent never replaces a proof)",
          firm["MH-4101"]["impact"]["group"] == "your-call" and "your ruling on MH-4100 of the same kind says blocks" in firm["MH-4101"]["impact"]["reason"])
    try:
        FX.answer(reports, "impact:MH-4048", "A", train)
        check("a row that is not your call takes no ruling", False)
    except KeyError:
        check("a row that is not your call takes no ruling", True)
    a = FX.asks([train], lambda l: f"releases/{l}/{l}")
    check("each your-call row is a ruling ask: ela's leaning as A, the other way as B, linking its row",
          [x["id"] for x in a] == ["impact:MH-4100"] and a[0]["text"].startswith("Does MH-4100's QA fail block QA-AWS3 → daily-wed (UR test2)? ela leans does not block")
          and a[0]["options"][0]["text"] == "right: does not block" and a[0]["options"][0]["recommended"]
          and a[0]["options"][1]["does"] == "ela train answer impact:MH-4100 B" and a[0]["link"] == "releases/2.1/2.1#^fix-mh-4100")

# a your-call ruling answered on the line page itself: boxes under the row, a tick or `ela: B because …`, words kept
yc = "\n".join(FX.block(dict(train, at="2026-11-26T09:00+08:00")))
check("a your-call row carries its two answers under it on the line page",
      "- [ ] A (recommended): right: does not block" in yc and "- [ ] B: wrong: it blocks; say why on the line below" in yc
      and yc.index("^fix-mh-4100") < yc.index("- [ ] A (recommended)"))
linked = yc.replace("- MH-4100 ", "- [MH-4100](https://x/browse/MH-4100) ")
ticked = linked.replace("    - [ ] B: wrong:", "    - [x] B: wrong:").replace(
    "say why on the line below", "say why on the line below\n    the stage bar is customer-facing", 1)
check("a tick under a row is read with the plain line below it as his words",
      FX.page_answers(ticked) == [("MH-4100", "B", "the stage bar is customer-facing")])
lined = linked.replace("    - [ ] B: wrong:", "    ela: B because TC13 is the main path\n    - [ ] B: wrong:")
check("`ela: B because …` under a row is read with its words", FX.page_answers(lined) == [("MH-4100", "B", "because TC13 is the main path")])
check("a line page with nothing ticked answers nothing", FX.page_answers(linked) == [])
with tempfile.TemporaryDirectory() as reports:
    first = FX.settle_page(reports, ticked, train)
    again = FX.settle_page(reports, ticked, train)
    kept = FX.read_rulings(reports)
    check("the sync records a line-page ruling once a case, with his words as the cause",
          first == [("impact:MH-4100", "B", "the stage bar is customer-facing")] and again == [] and len(kept) == 1
          and kept[0]["ruled"] == "blocks" and kept[0]["cause"] == "the stage bar is customer-facing" and kept[0]["corpus"] == "admitted")
    sys.path.insert(0, os.path.join(ROOT, "skills", "asks"))
    import asks as A  # noqa: E402
    check("a line-page ruling is a deploy-impact precedent", [p["target"] for p in A.precedents(reports, "deploy-impact")] == ["MH-4100"])

# the line page's block
many = [row(f"MH-5{n:03d}", "untested", arrived="101") for n in range(10)] + \
       [row(f"MH-6{n:03d}", "fail", history=[h("pass", "build 99", "2026-11-20T18:48"), h("fail", "build 100", "2026-11-25T18:43")]) for n in range(9)]
got = judged(many + [dict(r) for r in rows], issues)
train = {"line": "2.1", "at": "2026-11-26T09:00+08:00", "lanes": LANES, "rows": list(got.values())}
blk = "\n".join(FX.block(train))
visible = "\n".join(l for l in blk.splitlines() if not l.startswith(">"))
check("blocks are never folded, however many", all(f"MH-6{n:03d}" in visible for n in range(9)) and "**Blocks · 12**" in blk)
check("a long not-yet-verified group shows two and folds the rest", "**Not yet verified · 11**" in blk and "> [!note]- 9 more not yet verified" in blk)
check("a group's shared next step is said once, in its header", "**Blocks · 12** — each needs a fix, then QA again" in blk and "next: a fix" not in blk)
check("a does-not-block row is one visible line with its reason, never a count",
      any(l.startswith("- MH-4100 ") and "**does not block**:" in l and l.endswith("^fix-mh-4100") for l in visible.splitlines()))
check("groups in order: blocks, not yet verified, does not block, then Ready as a count",
      blk.index("**Blocks") < blk.index("**Not yet verified") < blk.index("**Does not block") < blk.index("**Ready:** 1 for QA-AWS3 → daily-wed (UR test2)")
      and "MH-4200" not in blk)

# today.md: since you last looked
lines = FX.since_lines([train], "2026-11-25T12:00", lambda l: f"releases/{l}/{l}")
check("since you last looked: at most five lines, blocks first, each linking its row on the line page",
      len(lines) == 5 and "— blocks:" in lines[0] and lines[0].endswith("|its row]]") and "[[releases/2.1/2.1#^fix-" in lines[0])
check("the rest is one count line linking the line's section", lines[-1].startswith("- ") and "more" in lines[-1]
      and "[[releases/2.1/2.1#Fixes on their way|the 2.1 line]]" in lines[-1])
check("nothing changed since he looked: no line", FX.since_lines([train], "2026-11-27T00:00", lambda l: l) == [])

if failures:
    print(f"\ntrain fixes: {len(failures)} failure(s)"); sys.exit(1)
print("\ntrain fixes: all offline checks passed")
