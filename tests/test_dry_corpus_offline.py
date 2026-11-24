#!/usr/bin/env python3
"""The selectors' replay corpus (tests/corpus/README.md), offline: each case, one wrong proposal the owner rejected,
replayed through its class's selector; the test fails if the pinned proposal is made again, if a case is malformed, or
if a case names a class no selector covers. Nothing reaches Jira."""
import datetime, glob, json, os, re, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "dry"))
import dry as D  # noqa: E402

CORPUS = os.path.join(ROOT, "tests", "corpus")
OUT = tempfile.TemporaryDirectory()


def link_named(i):
    return D.select_link_named(i["parent"], i.get("children") or {}, before=i.get("before"))


def parent_status(i):
    return D.select_parent_status(i["parent"], i.get("owner"), datetime.date.fromisoformat(i["today"]), OUT.name)


SELECTORS = {"link-named": link_named, "parent-status": parent_status}
failures = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


def repeats(case, writes):
    r = case["rejected"]
    for w in writes:
        if w.get("target") != r["target"]:
            continue
        typ = (re.search(r"--type (\"[^\"]+\"|\S+)", w["command"]) or [None, ""])[1].strip('"')
        if not r.get("type") or r["type"] == typ:
            return w["command"]
    return None


cases = sorted(glob.glob(os.path.join(CORPUS, "*", "*.json")))
check("the corpus directory has a folder per selector", all(os.path.isdir(os.path.join(CORPUS, c)) for c in SELECTORS))
for p in cases:
    name = os.path.relpath(p, CORPUS)
    try:
        case = json.load(open(p, encoding="utf-8"))
    except ValueError as e:
        check(f"{name}: parses ({e})", False); continue
    cls = case.get("class")
    if not (cls in SELECTORS and os.path.basename(os.path.dirname(p)) == cls and (case.get("rejected") or {}).get("target")
            and (case.get("cause") or "").strip() and (case.get("word") or "").strip() and case.get("input")):
        check(f"{name}: a case names its class (its folder), one rejected target, its cause and the owner's word", False)
        continue
    writes, _ = SELECTORS[cls](case["input"])
    hit = repeats(case, writes)
    check(f"{name}: not proposed again ({case['cause']})" + (f" — proposed: {hit}" if hit else ""), hit is None)
check("the corpus holds at least the seed cases", len(cases) >= 2)

print(f"\n{len(failures)} failure(s)" if failures else "\nall passed")
sys.exit(1 if failures else 0)
