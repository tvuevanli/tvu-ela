#!/usr/bin/env python3
"""docs/manual.md names every CLI verb and every skill — the manual cannot fall behind the code."""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
manual = open(os.path.join(ROOT, "docs", "manual.md"), encoding="utf-8").read()
verbs = set(re.findall(r'"([a-z-]+)": \(', open(os.path.join(ROOT, "bin", "ela")).read()))
skills = {d for d in os.listdir(os.path.join(ROOT, "skills")) if os.path.isdir(os.path.join(ROOT, "skills", d)) and not d.startswith("_")}
missing = sorted(n for n in verbs | skills if not re.search(r"`(?:ela |/ela:)?" + re.escape(n) + r"\b", manual))
if missing:
    print("manual does not mention:", ", ".join(missing)); sys.exit(1)
print(f"manual covers {len(verbs)} verbs and {len(skills)} skills")
