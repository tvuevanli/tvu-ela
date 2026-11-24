#!/usr/bin/env python3
"""A note's file name stem is the last of its aliases, offline: with_stem puts it there and keeps the title first;
every note write carries it; `lint --fix` backfills a hand-written note; a rename moves it to the new name and keeps
the old one; the stem is never read as an old name; the sync's name index maps title, alias and stem to the path."""
import contextlib, io, json, os, sys, tempfile, types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import vault as V  # noqa: E402

failures = 0


def check(name, cond):
    global failures
    print(("ok   " if cond else "FAIL ") + name)
    failures += 0 if cond else 1


def aliases(text):
    return V.list_prop(V.split_front(text)[0], "aliases")


STEM = "2026-11-24-link-named-MH-3735"
plain = '---\ntitle: "Link named MH-3735"\naliases: ["Link named MH-3735"]\ntype: "dry"\n---\n\n# Link named MH-3735\n\nbody\n'
t, ch = V.with_stem(plain, f"ela/dry/{STEM}.md")
check("the stem goes last, the title stays first", ch and aliases(t) == ["Link named MH-3735", STEM])
check("the body is kept to the byte", t.split("\n---", 1)[1] == plain.split("\n---", 1)[1])
check("a second pass changes nothing", V.with_stem(t, f"ela/dry/{STEM}.md") == (t, False))
mid = plain.replace('["Link named MH-3735"]', f'["Link named MH-3735", "{STEM}", "old name"]')
check("a stem in the middle moves to the end, once", aliases(V.with_stem(mid, STEM + ".md")[0]) == ["Link named MH-3735", "old name", STEM])
none = '---\ntitle: "X"\ntype: "plan"\n---\n# X\n'
check("a note with no aliases gains them after the title", V.split_front(V.with_stem(none, "a/x-y.md")[0])[0][:2] == ['title: "X"', 'aliases: ["x-y"]'])
check("a text without front matter is left as it is", V.with_stem("# just text\n", "a/b.md") == ("# just text\n", False))
check("a file that is not a note is left as it is", V.with_stem(plain, "a/b.json") == (plain, False))

with tempfile.TemporaryDirectory() as tmp:
    vault, reports, runtime = (os.path.join(tmp, x) for x in ("vault", "reports", "runtime"))
    for d in ("ela/dry", "plans", "reference"):
        os.makedirs(os.path.join(vault, d))
    os.makedirs(os.path.join(reports, "ela"))
    p = os.path.join(vault, "ela", "dry", STEM + ".md")
    V.atomic_write(p, plain)
    check("every note write carries the stem (atomic_write)", aliases(open(p).read()) == ["Link named MH-3735", STEM])
    j = os.path.join(runtime, "x.json")
    os.makedirs(runtime)
    V.atomic_write(j, '{"a": 1}\n')
    check("a file that is not a note is written as given", open(j).read() == '{"a": 1}\n')

    hand = os.path.join(vault, "plans", "2026-11-23-plan-grid-source.md")
    open(hand, "w").write('---\ntitle: "Grid source"\naliases: ["Grid source"]\ntype: "plan"\ndate: "2026-11-23"\n---\n\n# Grid source\n')
    gen = os.path.join(vault, "reference", "one-thing.md")
    open(gen, "w").write('---\ntitle: "One Thing"\naliases: ["One Thing"]\ntype: "report"\n---\n\n# One Thing\n')
    json.dump({"files": ["reference/one-thing.md"]}, open(os.path.join(vault, V.MANIFEST), "w"))
    site = os.path.join(tmp, "site.json")
    json.dump({"vault": vault, "reports": reports, "runtime": runtime}, open(site, "w"))
    V.SITE = site
    lint = types.SimpleNamespace(env_file=os.path.join(tmp, "none.env"), fix=True, apply=False, json=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        V.cmd_lint(lint)
    fixed = {x["note"]: x["fixes"] for x in json.loads(buf.getvalue())["fixed"]}
    check("lint --fix names the backfill; a dry run writes nothing",
          "the file name last among the aliases" in fixed.get("plans/2026-11-23-plan-grid-source.md", [])
          and aliases(open(hand).read()) == ["Grid source"])
    check("a note the sync writes is left to its generator", "reference/one-thing.md" not in fixed)
    lint.apply = True
    with contextlib.redirect_stdout(io.StringIO()):
        V.cmd_lint(lint)
    check("lint --fix --apply backfills it", aliases(open(hand).read()) == ["Grid source", "2026-11-23-plan-grid-source"])

    old, new = "plans/2026-11-23-plan-grid-source.md", "plans/2026-11-23-plan-grid-input.md"
    V.rename_note(vault, reports, old, new, True)
    check("a rename keeps the old name and puts the new stem last",
          aliases(open(os.path.join(vault, new)).read()) == ["Grid source", "2026-11-23-plan-grid-source", "2026-11-23-plan-grid-input"])
    moved = V.renames(vault, reports)
    check("the current stem is never read as an old name", new not in moved and moved.get(old) == new)

    idx = json.load(open(V.write_name_index(vault, runtime)))["names"]
    check("the name index maps a title, an alias and a stem to the path",
          idx.get("Link named MH-3735") == [f"ela/dry/{STEM}.md"] and idx.get(STEM) == [f"ela/dry/{STEM}.md"]
          and idx.get("2026-11-23-plan-grid-source") == [new] and idx.get("Grid source") == [new])
    check("no runtime, no index", V.write_name_index(vault, "") is None)

sys.exit(1 if failures else 0)
