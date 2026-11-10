#!/usr/bin/env python3
"""Every quoted section of an ela skill that elak cites (ela's `jira` skill § "A requirement is a project") is a
heading in that skill's SKILL.md: a citation into ela must not point at nothing. Skipped where elak is not on disk."""
import json, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
