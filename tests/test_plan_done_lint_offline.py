#!/usr/bin/env python3
"""The plan-status lint, offline: a plan not done whose every step a commit message names is a candidate for done,
named by the lint and never moved; a step no commit names, a done plan or a plan without steps gives no line
(plan 2026-11-26-review-autonomy-adversarial, item 10)."""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import vault as V  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


def plan(vault, name, status="live", steps=3, extra=""):
    os.makedirs(os.path.join(vault, "ela"), exist_ok=True)
    body = "\n".join(f"{i}. **Step {i}.** does a thing." for i in range(1, steps + 1))
    p = os.path.join(vault, "ela", name + ".md")
    open(p, "w").write(f'---\ntitle: "A plan"\ntype: "plan"\ndate: "2026-11-26"\nstatus: "{status}"\ntarget: "ela"\n---\n'
                       f'# A plan\n\n## The plan\n\n{body}\n{extra}\n## What you should do\n\n1. Nothing.\n2. Still nothing.\n')
    return p


check("a plan's steps are its first numbered run", V.plan_steps("x\n\n1. a\n2. b\n3. c\n\ntext\n\n1. other\n") == [1, 2, 3])
check("a folded list is not a step list", V.plan_steps("> [!note]-\n> 1. a\n> 2. b\n\n1. real\n") == [1])
check("ranges and lists of steps are read",
      V.step_refs("2026-11-26-plan-a", ["Plan: 2026-11-26-plan-a, steps 1-3.", "Plan: 2026-11-26-plan-a, items 4, 5 and 7.",
                                         "Plan: 2026-11-26-plan-b, step 9."]) == {1, 2, 3, 4, 5, 7})
check("a message that does not name the plan counts nothing", V.step_refs("2026-11-26-plan-a", ["step 1"]) == set())

with tempfile.TemporaryDirectory() as vault:
    built = plan(vault, "2026-11-26-plan-built")
    plan(vault, "2026-11-26-plan-half")
    plan(vault, "2026-11-26-plan-done", status="done")
    plan(vault, "2026-11-26-plan-none", steps=0)
    bodies = ["x: one\n\nPlan: vault ela/2026-11-26-plan-built.md, step 1.", "y\n\nPlan: 2026-11-26-plan-built, items 2 and 3.",
              "z\n\nPlan: 2026-11-26-plan-half, step 1.", "w\n\nPlan: 2026-11-26-plan-done, steps 1-3."]
    before = open(built).read()
    got = V.plan_done_lint(vault, bodies)
    check("only the plan whose every step a commit names is a candidate",
          [r for r, _ in got] == ["ela/2026-11-26-plan-built.md"] and "a candidate for done" in got[0][1])
    check("the lint never sets done", open(built).read() == before)

print("plan done lint: all offline checks passed" if not failures else f"plan done lint: {len(failures)} failed")
sys.exit(1 if failures else 0)
