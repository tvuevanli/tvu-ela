#!/usr/bin/env python3
"""The SessionStart hook's outputs stay under Claude Code's per-command cap, or say loudly that they do not.

Claude Code injects a hook command's output only up to 10,000 characters; past that the session sees a 2KB preview
(measured on 2.1.332, 2026-11-25). The working preferences therefore come as `prefs I/K` parts, each its own command:
together they are the section whole, and a section that needs more parts than hooks.json runs is named on the last
part's first line. Every output from 9,000 characters on starts with a warning. Offline: a temp HOME, no network.
"""
import json, os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "session-start.sh")
CAP, WARN = 10000, 9000
fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)


def bullets(n, width=200):
    return "".join(f"- rule {i}: " + "w" * width + "\n  continued line of rule " + str(i) + "\n" for i in range(n))


def run(home, *args, root=ROOT, env=None):
    e = {k: v for k, v in os.environ.items() if k not in ("ELA_GUEST", "ELA_RUNNER_JOB")}
    e.update(HOME=home, CLAUDE_PLUGIN_ROOT=root, CLAUDE_PROJECT_DIR=home)
    e.update(env or {})
    return subprocess.run(["bash", HOOK, *args], input="", capture_output=True, text=True, env=e, timeout=60).stdout


def home_with(prefs):
    h = tempfile.mkdtemp(prefix="ela-ss-")
    os.makedirs(os.path.join(h, ".claude", "ela"))
    json.dump({"elak": "<elak>"}, open(os.path.join(h, ".claude", "ela", "site.json"), "w"))
    open(os.path.join(h, ".claude", "ela", "working-with-evan.md"), "w", encoding="utf-8").write(prefs)
    return h


# 1. A ~15K preferences section comes whole in two parts, each under the warning line; a later section is a pointer.
section = "## Working preferences (test)\n" + bullets(60)
later = "## His day (test)\n- a later section, only pointed at\n"
h = home_with(section + "\n" + later)
p1, p2 = run(h, "prefs", "1/2"), run(h, "prefs", "2/2")
ctx = run(h)
check(len(section) > CAP, f"fixture too small: {len(section)}")
for name, out in (("part 1", p1), ("part 2", p2), ("context", ctx)):
    check(0 < len(out) < WARN, f"{name}: {len(out)} characters, expected 1..{WARN - 1}")
    check(not out.startswith("ela: WARNING"), f"{name}: unexpected warning")
body = "".join(o.split("\n", 1)[1] for o in (p1, p2))
check(body.rstrip() == section.rstrip(), "the two parts are not the preferences section whole")
check("a later section" not in p1 + p2 + ctx, "a later section was injected")
check('"His day (test)"' in ctx and "line " in ctx, "context lacks the pointer to the later section")
shutil.rmtree(h)

# 2. A section that needs three parts when hooks.json runs two: the last part names the lines that did not arrive.
h = home_with("## Working preferences (test)\n" + bullets(100))
p2 = run(h, "prefs", "2/2")
check(p2.startswith("ela: WARNING") and "need 3 parts" in p2 and "did not reach this session" in p2,
      f"overrun not named on the last part's first line: {p2[:200]!r}")
check(len(p2) <= CAP, f"overrun part itself over the cap: {len(p2)}")
check(not run(h, "prefs", "1/2").startswith("ela: WARNING"), "part 1 warned; only the last part names the overrun")
shutil.rmtree(h)

# 3. A guest session gets no preferences.
h = home_with(section)
check(run(h, "prefs", "1/2", env={"ELA_GUEST": "1"}) == "", "a guest session got the owner's preferences")
shutil.rmtree(h)

# 4. The default part warns on its first line near the cap and over it (an oversized context/evan.md).
for size, word in ((WARN + 200, "near the cap"), (CAP + 2000, "OVER the cap")):
    root = tempfile.mkdtemp(prefix="ela-ss-root-")
    os.makedirs(os.path.join(root, "context"))
    open(os.path.join(root, "context", "evan.md"), "w").write("x" * size + "\n")
    h = home_with(section)
    out = run(h, root=root)
    first = out.split("\n", 1)[0]
    check(first.startswith("ela: WARNING") and word in first, f"{size} characters: first line {first[:120]!r}")
    check(len(first) < 2000, "the warning does not fit the 2KB preview")
    shutil.rmtree(h); shutil.rmtree(root)

# 5. The repository's own context/evan.md leaves the default part room under the warning line.
check(len(open(os.path.join(ROOT, "context", "evan.md"), encoding="utf-8").read()) < WARN - 1500,
      "context/evan.md leaves under 1,500 characters for the knowledge-base and cwd lines")

# 6. hooks.json runs prefs 1/K .. K/K beside the default part under every SessionStart matcher.
hj = json.load(open(os.path.join(ROOT, "hooks", "hooks.json")))
for entry in hj["hooks"]["SessionStart"]:
    cmds = [x["command"].split("session-start.sh", 1)[1].split() for x in entry["hooks"] if "session-start.sh" in x["command"]]
    parts = [c[1] for c in cmds if c and c[0] == "prefs"]
    k = len(parts)
    check(k >= 1 and sorted(parts) == [f"{i}/{k}" for i in range(1, k + 1)], f"{entry['matcher']}: prefs parts {parts}")
    check([] in cmds, f"{entry['matcher']}: no default part")

if fails:
    print("session-start offline: FAILED"); [print("  " + f) for f in fails]; sys.exit(1)
print("session-start offline: ok")
