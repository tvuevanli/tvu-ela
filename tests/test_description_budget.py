#!/usr/bin/env python3
"""Skill descriptions stay within the budget of a session's context.

Every skill's front-matter `description:` is loaded into every session on the machine, whether or not
the skill is used. A description exists so the model recognises when to invoke the skill; the inventory
of what it can do belongs in the body and in `--help`. The check fails when the descriptions together
exceed TOTAL_BYTES or any one exceeds ONE_CHARS. `--table` prints each description's size.
"""
import glob, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOTAL_BYTES = 8000
ONE_CHARS = 800


def description(path):
    """The `description:` value of a SKILL.md front matter, continuation lines folded in."""
    lines = open(path, encoding="utf-8").read().split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    value, inside = None, False
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("description:"):
            value, inside = [line[len("description:"):].strip()], True
        elif inside and line[:1] in (" ", "\t"):
            value.append(line.strip())
        else:
            inside = False
    if value is None:
        return None
    text = " ".join(v for v in value if v)
    if text[:1] in (">", "|"):
        text = text[1:].lstrip("-+ ")
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    return text


failures, total, rows = [], 0, []
for path in sorted(glob.glob(os.path.join(ROOT, "skills", "*", "SKILL.md"))):
    rel = os.path.relpath(path, ROOT)
    text = description(path)
    if text is None:
        failures.append(f"{rel}: no description in the front matter")
        continue
    size = len(text.encode("utf-8"))
    total += size
    rows.append((len(text), size, rel))
    if len(text) > ONE_CHARS:
        failures.append(f"{rel}: description is {len(text)} characters (limit {ONE_CHARS})")

if "--table" in sys.argv:
    for chars, size, rel in rows:
        print(f"{chars:5} chars {size:5} bytes  {rel}")
if total > TOTAL_BYTES:
    failures.append(f"descriptions total {total} bytes (limit {TOTAL_BYTES})")

for f in failures:
    print("FAIL " + f)
if failures:
    print(f"description budget: {len(failures)} failed"); sys.exit(1)
print(f"description budget: {total} bytes over {len(rows)} skills, all within limits")
