#!/usr/bin/env python3
"""`publish roster` may not remove a file the manifest records as published.

The roster once lived at knowledge/products/mediahub/team/; that directory now also holds published
documents, which readers read live from <published>. A cleanup of the old location that removes the
directory takes those documents away from a running reader, so the cleanup is checked here against a
throwaway elak and a throwaway published directory: nothing outside the temporary tree is read or written.
"""
import argparse, contextlib, io, json, os, shutil, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "publish"))
import publish  # noqa: E402 — the module under test

PEOPLE = """verified: '2026-09-08'
people:
  - email: core@example.com
    name: Core Person
    slack: U0000000001
    jira: 5f0000000000000000000001
"""
RESPONSIBILITIES = """verified: '2026-09-08'
responsibilities:
  - person: core@example.com
    scope: core
    area: app
    what: the app layer
    first_contact: true
    owns: []
"""
MANIFEST = """---
verified: '2026-09-08'
source: publication manifest; a row is written at each publication
---

# Published

| source | published file | generated | source verified at publication | read by |
|---|---|---|---|---|
"""
DOC_REL = "products/mediahub/team/layer-classification.md"
DOC = """---
verified: '2026-09-08'
source: a fixture document, published into the roster's old neighbourhood
---

# Layer rules

A reader holds this file open.
"""

failures = []


def check(ok, label):
    print(("ok   " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(text)


tmp = tempfile.mkdtemp(prefix="ela-publish-test-")
try:
    elak, published = os.path.join(tmp, "elak"), os.path.join(tmp, "published")
    write(os.path.join(elak, "knowledge", "people", "people.yaml"), PEOPLE)
    write(os.path.join(elak, "knowledge", "people", "responsibilities.yaml"), RESPONSIBILITIES)
    write(os.path.join(elak, "map", "published-machines.md"), MANIFEST)
    write(os.path.join(elak, "knowledge", DOC_REL), DOC)
    os.makedirs(published)
    write(os.path.join(tmp, "site.json"), json.dumps({"elak": elak, "published": published}))
    publish.SITE = os.path.join(tmp, "site.json")

    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet):
        publish.cmd_doc(argparse.Namespace(rel=DOC_REL, reader="a fixture reader", json=True))
    doc_dest = os.path.join(published, "knowledge", DOC_REL)
    check(os.path.isfile(doc_dest), "the document is published into the roster's old directory")

    # the artefacts the cleanup exists for, in the same directories as the published document
    stale_old = os.path.join(published, "knowledge", "products", "mediahub", "team", "roster.md")
    stale_here = os.path.join(published, "knowledge", "people", "team-map.md")
    write(stale_old, "the roster, published here until 2026-09-04\n")
    write(stale_here, "the roster, published under Helm's filename until 2026-09-03\n")

    with contextlib.redirect_stdout(quiet):
        publish.cmd_roster(argparse.Namespace(json=True))

    check(os.path.isfile(doc_dest), "`publish roster` leaves a published document in the old directory alone")
    check(os.path.isfile(doc_dest) and open(doc_dest, encoding="utf-8").read() == DOC, "the published document is unchanged")
    check(not os.path.exists(stale_old), "the stale roster copy in the old directory is removed")
    check(not os.path.exists(stale_here), "the stale roster copy under Helm's filename is removed")
    check(os.path.isfile(os.path.join(published, "knowledge", "people", "roster.md")), "the roster is published")

    # nothing published left in the old directory: the directory itself goes
    if os.path.isfile(doc_dest):
        os.remove(doc_dest)
    write(stale_old,"the roster, published here until 2026-09-04\n")
    with contextlib.redirect_stdout(quiet):
        publish.cmd_roster(argparse.Namespace(json=True))
    check(not os.path.exists(os.path.dirname(stale_old)), "an old directory left empty is removed")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    print(f"publish stale-path cleanup: {len(failures)} failed"); sys.exit(1)
print("publish stale-path cleanup: all cases pass")
