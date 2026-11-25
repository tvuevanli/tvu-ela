#!/usr/bin/env python3
"""The release guard (`publish.release_flags`) and the release scope (`write_release_files`'s .gitignore): an owner's
word or name cited as a source is refused, a yaml label in CJK and a role are not; git sees knowledge/platform,
knowledge/products, map/ and the README, never people/, lanes/, reports/ or releases/. Offline: a temporary directory
and a throwaway git repository. Phrases under test are joined at run time, so the commit guard reading this file sees
no attribution."""
import os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "publish"))
import publish  # noqa: E402 — the module under test

failures = []


def check(ok, label):
    print(("ok   " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


def whys(text, name="x.md", first="Alex"):
    return [w for _, w, _ in publish.release_flags(text, name, first)]


OWN = "owner" + "'s"
check("the owner's word as a source" in whys(f"source: the {OWN} word, 2026-11-24"), "the owner's word as a source is refused")
check("the owner's word as a source" in whys(f"(2026-10-27, owner{chr(39)}{OWN[5:]} ruling)", "x.yaml"),
      "yaml's doubled apostrophe is read as one")
check("the owner by name" in whys("added on " + "Alex" + "'s say-so"), "the owner's first name is refused")
check(whys("closed Done by the product owner with no Fixed In") == [], "a role is not refused")
check(whys('  - value: "' + "辽宁电视台" + "_东北超项目" + '"', "map/jira-labels.yaml") == [],
      "a yaml label in CJK is syntax, not a quotation")
q = chr(34)
check("a quotation attributed to a person" in whys(f"{q}this is how it should work{q} (Sam, 2026-09-04)"),
      "an English quotation attributed to a person is refused")

with tempfile.TemporaryDirectory() as d:
    publish.write_release_files(d)
    for rel in ("knowledge/platform/a.md", "knowledge/products/b.md", "knowledge/people/people.yaml",
                "knowledge/engineering/c.md", "map/services.yaml", "lanes/lanes.md", "reports/daily/x.json",
                "releases/next.json", "MANIFEST.md", "map/.x.yaml.1.tmp"):
        os.makedirs(os.path.dirname(os.path.join(d, rel)) or d, exist_ok=True)
        open(os.path.join(d, rel), "w").write("x\n")
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    seen = subprocess.run(["git", "-C", d, "status", "--porcelain", "--untracked-files=all"],
                          capture_output=True, text=True).stdout.split("\n")
    seen = sorted(l[3:] for l in seen if l)
    check(seen == [".gitignore", "README.md", "knowledge/platform/a.md", "knowledge/products/b.md", "map/services.yaml"],
          f"git sees the release scope only: {seen}")

print(f"{len(failures)} failure(s)" if failures else "release guard: all cases pass")
sys.exit(1 if failures else 0)
