#!/usr/bin/env python3
"""A build a lane took, offline: the record is checked (whole, at most 15 words of purpose, keys apart), read back,
rendered as at most four service lines on today.md and as the release note, and printed by `release changes`."""
import datetime, json, os, shutil, subprocess, sys, tempfile, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "release"))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import release as R  # noqa: E402
import vault as V  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

FIX = os.path.join(ROOT, "tests", "fixtures", "releases")
rec = json.load(open(os.path.join(FIX, "2.1", "2026-11-10-build-90-to-qa-aws3.json"), encoding="utf-8"))
check("build 90's record is whole", R.build_check(rec, "2026-11-10-build-90-to-qa-aws3.json") == [])
bad = json.loads(json.dumps(rec))
bad["services"][0]["for"] = "MH-3887 " + " ".join(["word"] * 16) + " …"
probs = R.build_check(bad)
check("a long, cut purpose with a key in it is named three ways",
      any("18 words" in p for p in probs) and any("cut" in p for p in probs) and any("ticket key" in p for p in probs))
lines = R.build_lines(rec)
check("one line per service, at most four, purpose then keys",
      len(lines) == 4 and lines[1] == "MediaHub backend 2.1.42 → 2.1.43: FloSports public API: six endpoints "
      "(MH-3881 MH-3903 MH-3883 MH-3887 MH-3907 MH-3795)")
five = dict(rec, services=rec["services"] + [dict(rec["services"][0], service="Orchestration")])
check("five services: three lines and a count", len(R.build_lines(five)) == 4 and R.build_lines(five)[-1].startswith("2 more services"))
note = R.build_note(rec)
check("the release note: title, source, a table of service, version and what for",
      note.startswith("# MediaHub 2.1 build 90 → QA-AWS3 · what changed") and "| UR Caller | 2.1.89 → **2.1.90** |" in note
      and "What you should do" not in note)

with tempfile.TemporaryDirectory() as tmp:
    shutil.copytree(FIX, os.path.join(tmp, "releases"))
    recs = R.build_records(tmp)
    check("records are read back by name", [r["name"] for r in recs] == ["2026-11-10-build-90-to-qa-aws3"])
    day = lambda d: types.SimpleNamespace(path=f"reference/days/2026/{d}-changes.md", title="x", body="## Releases and versions\n\nProd 3 caught up.\n",  # noqa: E731
                                         props={"type": "day", "kind": "changes", "date": d})
    WED = datetime.date(2026, 11, 11)
    page = V.today_page(WED, [day("2026-11-10"), day("2026-11-11")], {"builds": recs})
    facts = page.split("## Facts")[1].split("## Needs you")[0]
    rows = [l for l in facts.splitlines() if l.startswith("  - ")]
    check("today.md: the Releases fact is build 90, four service lines, linking its note",
          "QA-AWS3 took build 90 ([[releases/2.1/2026-11-10-build-90-to-qa-aws3|release note]])" in facts and len(rows) == 4
          and "Prod 3 caught up" not in facts)
    full = types.SimpleNamespace(path="reference/days/2026/2026-11-11-changes.md", title="x", props={"type": "day", "kind": "changes", "date": "2026-11-11"},
                                 body="## Releases and versions\n\nProd 3 caught up.\n\n## Docker services\n\nQA's 1.0.26 report clears tvu_live_transmit.\n\n"
                                      "## QA\n\nBuild 85 is the verdict build.\n\n## Tickets\n\nTwo new tickets came in.\n")
    asks = [{"id": f"keys:MH-{i}", "box": f"apply {i}", "text": f"MH-{i}: " + " ".join(["word"] * 17) + ".", "first": "2026-11-11"} for i in (1, 2, 3)]
    crowded = V.today_page(WED, [day("2026-11-10"), full], {"builds": recs}, asks).split("## Needs you")[0]
    check("with the build block and three asks the page keeps three facts, each one line, the build first",
          crowded.count("\n- **") == 3 and "- **Releases:** QA-AWS3 took build 90" in crowded and "- **Docker:**" in crowded)
    later = V.today_page(datetime.date(2026, 11, 13), [day("2026-11-12"), day("2026-11-13")], {"builds": recs})
    check("a build before the last page is not shown again", "took build" not in later)
    env = dict(os.environ)
    site = os.path.join(tmp, "site.json")
    json.dump({"reports": tmp}, open(site, "w"))
    R.SITE = site
    import io, contextlib, argparse
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        R.cmd_changes(argparse.Namespace(check=None, lane="QA-AWS3", json=False))
    check("`release changes QA-AWS3` prints the build by service", out.getvalue().startswith("QA-AWS3 took build 90 (2.1, 2026-11-10):")
          and out.getvalue().count("\n  ") == 4)

if failures:
    print(f"release changes: {len(failures)} failed"); sys.exit(1)
print("release changes offline: all passed")
