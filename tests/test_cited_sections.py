#!/usr/bin/env python3
"""Every quoted section of an ela skill that elak cites (ela's `jira` skill § "A requirement is a project") is a
heading in that skill's SKILL.md: a citation into ela must not point at nothing. Skipped where elak is not on disk.
Before that, the skills that dispatch by mode are checked (below); that part needs no elak."""
import json, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
"""
A skill that dispatches by mode has a core SKILL.md and parts beside it, read only by the mode that needs them (vault
plan ela/2026-11-26-plan-context-budget). Three checks, none needing elak: every part exists, is named in the core, and
no unlisted .md sits beside it; the core stays under its character ceiling (a ratchet: lowered when it shrinks, raised
only with a date and a reason here); and the phrases the skill's rules rest on are still somewhere in the skill, with
the ones a session needs before any part is read in the core itself. A phrase list is written before its skill is cut.
"""
squash = lambda t: " ".join(t.split())
SKILLS = {
    "brief": {
        "parts": ["unattended.md", "page.md", "files.md", "meetings.md", "reader.md"],
        "ceiling": 37242,   # 2026-11-26: 83,958 before the split by mode
        "headings": ["3b — when the runner asked (unattended): the page and the numbered actions, written to files",
                     "§reader — the evening read of the morning page"],   # cited by review.py, brief.py and the runner
        "core": ["Read-only: this skill never posts, transitions, comments or creates", "A held subject asks nothing",
                 "a silent lane is a lie", "never an interpreter one-liner", "fills at most one per page",
                 "Never batch", "the pile is the item", "Being tagged does not make a thread his",
                 "A key that comes from several sources is **one item**", "At most eight items",
                 "His own work is a sprint row, never an item", "Review is never read as verified",
                 "A ticket is called silent only when Slack and mail are silent too",
                 "\"Deployed\" is a fact, never a status", "A field is Jira's value",
                 "a write that would change nothing is not drafted", "leaves only on his word",
                 "then commits and pushes it under elak's commit rules (ADR 0026)",
                 "With `--page`, Read `unattended.md` first", "Read `reader.md` first"],
        "anywhere": ["never \"untested\", \"no QA report yet\"", "keep their number and text",
                     "Counts come from one file", "The session itself applies nothing", "`ELA_NO_APPLY`",
                     "A number is minted only when its drafted write is in `<date>-actions.json`",
                     "never a terminal status, a close, a transition or a customer-facing field",
                     "Tier 2 is retired", "leaves only on his approve", "At most three `apply` boxes stand open",
                     "An item never ends in a question to him", "No Do line without a box",
                     "A verification outranks a close", "A key never stands in a run", "Under 900 words in all",
                     "Services by their slug", "People by their roster display name", "A ticket appears once",
                     "is one line, never an item", "The morning count", "it only raises, never lowers what a person set",
                     "never moves a date", "Nothing is posted in the release thread", "It carries no actions",
                     "The page drafts no actions", "It ticks nothing, posts nothing and edits no page",
                     "the order wrong, handed back, question, noise, tickable", "the check fails an unjudged one",
                     "the check fails an unaudited one", "the verb refuses a longer one", "No dated meeting note is written"],
    },
    "watch": {
        "parts": ["judge.md", "second-reading.md"],
        "ceiling": 13579,   # 2026-11-26: 18,796 before judge mode and the second reading became parts
        "headings": ["The second reading", "Judge mode: a ticket that reaches the owner arrives judged"],   # the runner's prompts name them
        "core": ["An act you would not defend to the assignee is an ask", "Comment sparingly", "never a close",
                 "Do not answer the reply yourself", "Do not sign it", "Read `judge.md` first", "Read `second-reading.md` first"],
        "anywhere": ["A letter he gave binds the verdict", "an unattended session never writes elak (ADR 0026)",
                     "Agreeing with the decider is not a source", "not read twice"],
    },
    "jira": {
        "parts": ["atoms.md"],
        "ceiling": 15321,   # 2026-11-26: 20,969 before the field atoms' table became a part
        "headings": ["A requirement is a project", "Classifying a ticket ela processes"],
        "core": ["is refused unless `--terminal` is passed", "`close` is a proposal, never a status change",
                 "never reach the Jira API another way to get past it", "never pass `--apply` until Evan has",
                 "one ticket's bundle", "Read `atoms.md` beside this file", "carries no comment"],
        "anywhere": ["append-only union", "`@name` is a real mention", "lowering is refused", "a date already there is never moved",
                     "a reporter's evidence is refused"],
    },
    "promote": {
        "parts": ["release-note.md", "pending.md", "checkers.md", "slack-body.md"],
        "ceiling": 20055,   # 2026-11-26: 24,010 before the four parts
        "core": ["A partial is never shown as a pass", "never infer a pass from silence", "Read-only until his word",
                 "A stop is lifted only by the owner", "Nothing from a run reaches the owner until two independent checkers",
                 "two sends, two confirms", "never `--apply` without his word per key", "Read `checkers.md` before spawning them"],
        "anywhere": ["A release note compares two bundles, never a lane", "never the drafting session's conclusions",
                     "`note.py lint` refuses a note without it", "never blanks a filled candidate", "*Open points* — numbered questions"],
    },
}
bad = []
for skill, spec in sorted(SKILLS.items()):
    d = os.path.join(ROOT, "skills", skill)
    core = open(os.path.join(d, "SKILL.md"), encoding="utf-8").read()
    for part in spec["parts"]:
        if not os.path.isfile(os.path.join(d, part)):
            bad.append(f"{skill}: SKILL.md dispatches to {part}, which is not in the skill's folder")
        if f"`{part}`" not in core:
            bad.append(f"{skill}: {part} is a part no line of SKILL.md names, so no mode reads it")
    for f in sorted(os.listdir(d)):
        if f.endswith(".md") and f != "SKILL.md" and f not in spec["parts"] and f not in spec.get("other", ()):
            bad.append(f"{skill}: {f} sits beside SKILL.md and is not a listed part")
    if len(core) > spec["ceiling"]:
        bad.append(f"{skill}: SKILL.md is {len(core):,} characters, over its ceiling of {spec['ceiling']:,}: move the "
                   f"text to the part whose mode needs it, or raise the ceiling here with the date and the reason")
    heads = re.findall(r"^#{2,3}\s+(.+?)\s*$", core, re.M)
    bad += [f"{skill}: the cited heading is gone from SKILL.md: {h!r}" for h in spec.get("headings", ()) if h not in heads]
    whole = squash(core + "".join(open(os.path.join(d, p_), encoding="utf-8").read() for p_ in spec["parts"]
                                  if os.path.isfile(os.path.join(d, p_))))
    bad += [f"{skill}: required phrase gone from SKILL.md (the core): {ph!r}" for ph in spec["core"] if squash(ph) not in squash(core)]
    bad += [f"{skill}: required phrase gone from the skill: {ph!r}" for ph in spec["anywhere"] if squash(ph) not in whole]
for b in bad:
    print("FAIL " + b)
print(f"skill parts: {len(SKILLS)} dispatching skills checked, {len(bad)} failed")
if bad:
    sys.exit(1)

try:
    site = json.load(open(os.path.expanduser("~/.claude/ela/site.json")))
    elak = site.get("elak") or os.path.join(site.get("projects") or "", "elak")
except (OSError, ValueError):
    elak = ""
if not elak or not os.path.isdir(elak):
    print("cited sections: no elak on this machine, skipped"); sys.exit(0)
CITE = re.compile(r"ela's\s+`([a-z-]+)`\s+skill\s+§\s+\"([^\"]+)\"")
missing, seen = [], 0
for top, dirs, fs in os.walk(elak):
    dirs[:] = [d for d in dirs if not d.startswith(".")]
    for f in fs:
        if not f.endswith(".md"):
            continue
        p = os.path.join(top, f)
        for skill, sec in CITE.findall(open(p, encoding="utf-8").read()):
            seen += 1
            sk = os.path.join(ROOT, "skills", skill, "SKILL.md")
            heads = re.findall(r"^#{2,3}\s+(.+?)\s*$", open(sk, encoding="utf-8").read(), re.M) if os.path.isfile(sk) else []
            if sec not in heads:
                missing.append(f"{os.path.relpath(p, elak)}: {skill} § \"{sec}\"")
for m in missing:
    print("FAIL cited section not in the skill:", m)
print(f"cited sections: {seen} checked, {len(missing)} missing")
sys.exit(1 if missing else 0)
