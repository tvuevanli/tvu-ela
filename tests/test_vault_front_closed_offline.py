#!/usr/bin/env python3
"""A note's front matter stays closed, offline: every front-matter writer run twice over a dry note (ela/dry/, his copy
once written) leaves its closing `---` in place; atomic_write refuses a write that would leave a closed note's front
matter open, which is how a draft of with_stem on 2026-11-24 dropped the closing line of every note one sync wrote."""
import contextlib, io, json, os, sys, tempfile, types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import vault as V  # noqa: E402

failures = 0


def check(name, cond):
    global failures
    print(("ok   " if cond else "FAIL ") + name)
    failures += 0 if cond else 1


def closed(text):
    return text.startswith("---\n") and not V.front_open(text)


STEM = "2026-11-24-link-named-MH-3997"
REL = f"ela/dry/{STEM}.md"
BODY = ("# 2 links for MH-3997\n\nClass: **link-named** — link a child to a parent you own.\n\n"
        "1. `ela jira link MH-3997 MH-2026 --type contains` — named by the description\n"
        "    - [MH-2026](https://jira.example/browse/MH-2026) Grid · Done\n\n- [ ] apply 1\n\nela: why this one\n")
# the sync's first write of a dry note, and the same note with a rule in its body, which a lost close would let
# split_front take for the close
NOTES = {"plain": V.front([], {"type": "dry", "date": "2026-11-24"}) + BODY,
         "ruled": V.front([], {"type": "dry", "date": "2026-11-24"}) + BODY + "\n---\n\nafter the rule\n"}

check("front_open: a closed front, no front, one never closed, one whose close is a later rule",
      not V.front_open(NOTES["plain"]) and not V.front_open("# x\n") and V.front_open('---\ntype: "dry"\n\n# x\n')
      and V.front_open('---\ntype: "dry"\n\n# x\n\n---\n\ny\n'))

answer = [{"note": REL, "job": "j1", "status": "done", "lines": ["ela: why this one"], "answer": "because"}]
WRITERS = {
    "with_stem": lambda t: V.with_stem(t, REL)[0],
    "normalise": lambda t: V.normalise(t, "https://jira.example", ["MH"])[0],
    "set_front": lambda t: V.set_front(t, status="live"),
    "with_alias": lambda t: V.with_alias(t, "old name"),
    "keep_choice": lambda t: V.keep_choice(t, V.split_front(t)[0], REL),
    "place_lines": lambda t: V.place_lines(t, [(None, "ela: kept line")]),
    "with_answers": lambda t: V.with_answers(t, REL, answer),
    "stamp_text": lambda t: V.stamp_text(os.path.basename(REL), t, V.line_ids(os.path.basename(REL), t)[0][2], "✓ 15:07")[0],
    "merge_conflict": lambda t: V.merge_conflict(t + "\nela: from the copy\n", t)[0],
    "relocate_links": lambda t: V.relocate_links(t, "/nonexistent")[0],
}
for kind, note in NOTES.items():
    bad = []
    for name, w in WRITERS.items():
        t = note
        for _ in range(2):
            t = w(t)
            if not closed(t):
                bad.append(name)
                break
    check(f"every text writer, twice over a dry note ({kind}), leaves its front matter closed", not bad or print(bad))

with tempfile.TemporaryDirectory() as tmp:
    vault, reports, runtime = (os.path.join(tmp, x) for x in ("vault", "reports", "runtime"))
    for d in ("ela/dry", "plans"):
        os.makedirs(os.path.join(vault, d))
    for d in (os.path.join(reports, "ela"), runtime):
        os.makedirs(d)
    p = os.path.join(vault, REL)
    hand = os.path.join(vault, "plans", "2026-11-23-plan-x.md")
    site = os.path.join(tmp, "site.json")
    json.dump({"vault": vault, "reports": reports, "runtime": runtime}, open(site, "w"))
    V.SITE = site
    lint = types.SimpleNamespace(env_file=os.path.join(tmp, "none.env"), fix=True, apply=True, json=True)
    for kind, note in NOTES.items():
        V.atomic_write(p, note)
        V.atomic_write(hand, '---\ntitle: "X [MH-1](https://jira.example/browse/MH-1)"\ntype: "plan"\ndate: "2026-11-23"\n'
                             'source: "vault"\nstatus: "live"\n---\n\n# X\n\nbody MH-1\n')
        for _ in range(2):
            V.atomic_write(p, open(p).read())
            with contextlib.redirect_stdout(io.StringIO()):
                V.cmd_lint(lint)
            V.settle_statuses(vault)
            V.ensure_native_moves(vault)
        check(f"atomic_write, lint --fix --apply and the status and moves passes, twice, keep both fronts closed ({kind})",
              closed(open(p).read()) and closed(open(hand).read()))

    # the draft of with_stem that ran at 15:07 on 2026-11-24: the front lines, then the body, no closing line
    real = V.with_stem
    V.with_stem = lambda text, path: (("---\n" + "\n".join(V.front_line(V.split_front(text)[0], "aliases", [os.path.basename(path)[:-3]]))
                                       + text[text.find("\n---", 4) + 4:]), True) if V.split_front(text)[0] else (text, False)
    before = open(p).read()
    try:
        V.atomic_write(p, NOTES["plain"])
        refused = False
    except ValueError:
        refused = True
    check("a writer that drops the close is refused at the first note, and the note is left as it was",
          refused and open(p).read() == before)
    V.with_stem = real
    new = os.path.join(vault, "ela", "dry", "new.md")
    try:
        V.atomic_write(new, '---\ntype: "dry"\n\n# new\n')
        refused = False
    except ValueError:
        refused = True
    check("a new note with its front matter open is refused", refused and not os.path.exists(new))
    open(p, "w").write('---\ntype: "dry"\n\n# open already\n')
    V.atomic_write(p, '---\ntype: "dry"\n\n# open already ✓\n')
    check("a note already open on disk is still written (a stamp is not blocked by the old damage)",
          "✓" in open(p).read())

    # the lint names both shapes the bug left, and --fix leaves them to a person
    stacked = os.path.join(vault, "plans", "2026-11-24-plan-stacked.md")
    open(stacked, "w").write('---\ntitle: "S"\naliases: ["S", "2026-11-24-plan-stacked"]\ntype: "plan"\n---\n\n'
                             '---\ntitle: "S"\ntype: "plan"\ndate: "2026-11-10"\n\n# S\n')
    open(p, "w").write('---\naliases: ["' + STEM + '"]\ntype: "dry"\ndate: "2026-11-24"\n\n# 2 links for MH-3997\n')
    found = {r: lines for r, _, lines in V.lint_notes(vault)}
    check("lint names a note whose front matter is opened but not closed",
          any("opened but not closed" in l for l in found.get(REL, [])))
    check("lint names a second, unclosed block at the top of the body",
          any("second front-matter block" in l for l in found.get("plans/2026-11-24-plan-stacked.md", [])))
    check("a note whose front matter is whole has no such line", not any("front matter opened" in l or "second front-matter" in l
                                                                      for l in found.get("plans/2026-11-23-plan-x.md", [])))
    before = (open(p).read(), open(stacked).read())
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        V.cmd_lint(lint)
    fixed = {x["note"] for x in json.loads(buf.getvalue())["fixed"]}
    check("lint --fix --apply leaves both to a person", REL not in fixed and "plans/2026-11-24-plan-stacked.md" not in fixed
          and (open(p).read(), open(stacked).read()) == before)

print(f"vault front closed: {'all offline checks passed' if not failures else f'{failures} failed'}")
sys.exit(1 if failures else 0)
