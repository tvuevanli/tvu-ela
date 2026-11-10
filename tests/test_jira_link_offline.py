#!/usr/bin/env python3
"""jira.py link, offline: the phrase decides the direction for every type, the POST puts the phrase's subject in
inwardIssue (Jira reads 'inwardIssue <outward> outwardIssue'), and the dry run's sentence reads from both sides."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "jira"))
import jira as J  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

TYPES = [{"name": "Blocks", "outward": "blocks", "inward": "is blocked by"},
         {"name": "Relates", "outward": "relates to", "inward": "relates to"},
         {"name": "Hierarchy link (WBSGantt)", "outward": "contains", "inward": "is contained in"}]

def plan(phrase, key="MH-3990", other="MH-3735"):
    t, d = J.resolve_link(TYPES, phrase)
    return t, d, J.link_plan(t, d, key, other)

# 'A <outward> B' is POSTed as inwardIssue A, outwardIssue B
for phrase, src, dst, reads, back in [
        ("is contained in", "MH-3735", "MH-3990", "MH-3990 is contained in MH-3735", "MH-3735 contains MH-3990"),
        ("contains", "MH-3990", "MH-3735", "MH-3990 contains MH-3735", "MH-3735 is contained in MH-3990"),
        ("blocks", "MH-3990", "MH-3735", "MH-3990 blocks MH-3735", "MH-3735 is blocked by MH-3990"),
        ("is blocked by", "MH-3735", "MH-3990", "MH-3990 is blocked by MH-3735", "MH-3735 blocks MH-3990")]:
    t, d, p = plan(phrase)
    check(f"{phrase!r}: posts {src} as inwardIssue, {dst} as outwardIssue",
          p["payload"]["inwardIssue"] == {"key": src} and p["payload"]["outwardIssue"] == {"key": dst})
    check(f"{phrase!r}: reads {reads!r}", p["reads"] == reads)
    check(f"{phrase!r}: the target shows {back!r}", p["target_reads"] == back)

check("a type name links outward", J.resolve_link(TYPES, "Blocks")[1] == "outward")
check("the phrase decides, case and spacing aside", J.resolve_link(TYPES, "Is  Contained in")[1] == "inward")
check("an unknown phrase resolves to nothing", J.resolve_link(TYPES, "owns") == (None, None))

# idempotency reads the GET form: on MH-3990, an inwardIssue MH-3735 of Hierarchy reads 'is contained in'
t, d = J.resolve_link(TYPES, "is contained in")
got = [{"id": "1", "type": {"name": "Hierarchy link (WBSGantt)"}, "inwardIssue": {"key": "MH-3735"}}]
check("an existing link in that direction is found", (J.link_exists(got, t, d, "MH-3735") or {}).get("id") == "1")
check("the reverse link is not taken for it", J.link_exists(got, *J.resolve_link(TYPES, "contains"), "MH-3735") is None)

print("jira link: all offline checks passed" if not failures else f"jira link: {len(failures)} failed")
sys.exit(1 if failures else 0)
