#!/usr/bin/env python3
"""vault-name: a note's title, alias or file name stem in the owner's message adds `vault note: <path>`, at most
five; a one-word alias, a name inside a longer token, a missing index or a malformed input add nothing; never blocks."""
import json, os, subprocess, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "vault-name.sh")
fail = 0


def run(raw, site):
    p = subprocess.run(["bash", HOOK], input=raw, capture_output=True, text=True, env={**os.environ, "ELA_SITE": site})
    return p.returncode, p.stdout


def lines(prompt, site):
    rc, out = run(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": prompt}), site)
    if rc != 0:
        return None
    if not out.strip():
        return []
    ctx = json.loads(out)["hookSpecificOutput"]
    assert ctx["hookEventName"] == "UserPromptSubmit"
    return ctx["additionalContext"].split("\n")


def check(name, cond):
    global fail
    print(("ok   " if cond else "FAIL ") + name)
    fail |= not cond


DRY = "ela/dry/2026-11-24-link-named-MH-3735.md"
with tempfile.TemporaryDirectory() as tmp:
    runtime = os.path.join(tmp, "runtime")
    os.makedirs(runtime)
    site = os.path.join(tmp, "site.json")
    json.dump({"runtime": runtime}, open(site, "w"))
    names = {"Link named MH-3735": [DRY], "2026-11-24-link-named-MH-3735": [DRY],
             "Grid source": ["plans/2026-11-23-plan-grid-source.md"], "today": ["today.md"],
             "Today · Tue 2026-11-24": ["today.md"], "service-map": ["ela/service-map.md"],
             "Focus board": ["meetings/focus.md"], "Plan: grid source and more": ["plans/x.md"],
             "Same title twice": ["a/one.md", "b/two.md"]}
    names.update({f"2026-11-0{i}-note-{i}": [f"n/{i}.md"] for i in range(1, 8)})
    json.dump({"names": names}, open(os.path.join(runtime, "vault-index.json"), "w"))

    check("a stem pasted alone", lines("2026-11-24-link-named-MH-3735", site) == [f"vault note: {DRY}"])
    check("a title copied from Obsidian, any case, one line for one note",
          lines("look at link named mh-3735 and tell me what it wrote. Link named MH-3735", site) == [f"vault note: {DRY}"])
    check("an alias", lines("open the service-map please", site) == ["vault note: ela/service-map.md"])
    check("a path to the note still finds it", lines(f"see {DRY}", site) == [f"vault note: {DRY}"])
    check("two notes, in the order named",
          lines("compare Grid source with 2026-11-24-link-named-MH-3735", site)
          == ["vault note: plans/2026-11-23-plan-grid-source.md", f"vault note: {DRY}"])
    check("a name inside a longer one matched is not counted again",
          lines("Plan: grid source and more", site) == ["vault note: plans/x.md"])
    check("a title two notes share gives both", lines("Same title twice", site) == ["vault note: a/one.md", "vault note: b/two.md"])
    check("at most five", len(lines(" ".join(f"2026-11-0{i}-note-{i}" for i in range(1, 8)), site)) == 5)
    check("a one-word alias never matches prose", lines("what is on today", site) == [])
    check("a name inside a longer token does not match", lines("2026-11-24-link-named-MH-37350 and xservice-map", site) == [])
    check("no name, no output", lines("explain MH-3555", site) == [])
    for raw in ["not json", "{}", json.dumps({"prompt": None})]:
        rc, out = run(raw, site)
        check(f"malformed input passes: {raw!r}", rc == 0 and not out.strip())
    os.remove(os.path.join(runtime, "vault-index.json"))
    check("no index, nothing", lines("2026-11-24-link-named-MH-3735", site) == [])
    check("no site file, nothing", lines("2026-11-24-link-named-MH-3735", os.path.join(tmp, "none.json")) == [])

raise SystemExit(fail)
