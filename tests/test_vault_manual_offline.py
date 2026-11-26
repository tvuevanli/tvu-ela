#!/usr/bin/env python3
"""The owner's manual, offline: its source lints clean, the lint names an ela plan of MANUAL_FROM or later that
its `covers` leaves out (never a baseline plan), today.md's foot links it, and it names every tag hooks/lang-tag.sh recognises; test_vault_offline checks the sync writes it."""
import datetime, os, re, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import vault as V  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


src = open(V.MANUAL_SRC, encoding="utf-8").read()
fl, body = V.split_front(src)
check("the manual's source is a page: type manual, in the page family",
      V.props_of(fl).get("type") == "manual" and V.TYPE_FAMILY.get("manual") == "page")
check("the manual names the plans it covers", len(V.list_prop(fl, "covers")) >= 1)
check("no line of the manual reads as an instruction to the watcher", not V.GUIDE.search(body))
check("the manual meets its own lint: no spec line, head within budget",
      V.spec_lint(V.MANUAL, src, True) == [] and V.present_lint(V.MANUAL, src, True) == [])


hook = open(os.path.join(ROOT, "hooks", "lang-tag.sh"), encoding="utf-8").read()
tags = set(re.findall(r'\btagged\("([a-z]+)"\)', hook))
check("the hook recognises tags (the check below has something to compare)", {"zh", "send"} <= tags)
missing = sorted(t for t in tags if not re.search(r"`#" + t + r"`", body))
check(f"every tag hooks/lang-tag.sh recognises is in the manual's In a session (missing: {missing or 'none'})",
      not missing and "## In a session" in body)


def plan(vault, name, date, status="live", target="ela"):
    os.makedirs(os.path.join(vault, "ela"), exist_ok=True)
    open(os.path.join(vault, "ela", name + ".md"), "w").write(
        f'---\ntitle: "A plan"\naliases: ["A plan", "{name}"]\ntype: "plan"\ndate: "{date}"\nstatus: "{status}"\n'
        f'target: "{target}"\n---\n# A plan\n\n## What you should do\n\nNothing.\n')


with tempfile.TemporaryDirectory() as vault:
    check("no manual in the vault, no manual lines", V.manual_lint(vault) == [])
    open(os.path.join(vault, V.MANUAL), "w").write('---\ntype: "manual"\ncovers: ["2026-11-26-plan-covered"]\n---\n# How you use this vault\n')
    plan(vault, "2026-11-20-plan-baseline", "2026-11-20")
    plan(vault, "2026-11-26-plan-covered", "2026-11-26", "done")
    plan(vault, "2026-11-27-plan-new", "2026-11-27", "building")
    plan(vault, "2026-11-27-plan-proposed", "2026-11-27", "proposed")
    plan(vault, "2026-11-27-plan-helm", "2026-11-27", target="helm")
    lines = V.manual_lint(vault)
    check("a new ela plan the manual does not cover is named, with where to fix it",
          lines == ["manual.md does not cover plan 2026-11-27-plan-new: update skills/vault/manual.md (its text, updated, covers)"])
    check("a baseline plan, a covered one, a proposed one and another target's are not",
          not any(x in " ".join(lines) for x in ("baseline", "plan-covered", "proposed", "plan-helm")))
    found = {r: l for r, _, l in V.lint_notes(vault)}
    check("lint_notes carries the line on manual.md", any("plan-new" in x for x in found.get(V.MANUAL, [])))

page = V.today_page(datetime.date(2026, 11, 26), [], {}, [])
foot = page.rstrip().splitlines()[-1]
check("today.md's foot links the manual first", foot.startswith("[[manual|manual]] · "))

if failures:
    print(f"{len(failures)} failed"); sys.exit(1)
print("vault manual offline: all passed")
