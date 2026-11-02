#!/usr/bin/env python3
"""`jira.py fixed-in` appends to the Fixed In union and never removes an entry. Offline: only the pure helpers run."""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "jira"))
import jira as J  # noqa: E402 — the module under test

failures = []


def check(ok, label):
    print(("ok   " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


check(J.fixed_in_entries("a@1;  b@2 ;\nc@3; ") == ["a@1", "b@2", "c@3"], "entries split on ';' and newlines, blanks dropped")
cur, new, value = J.fixed_in_merge("a@1; b@2", ["b@2", "c@3", "c@3"])
check((cur, new, value) == (["a@1", "b@2"], ["c@3"], "a@1; b@2; c@3"), "present entries skipped, new ones appended once")
check(J.fixed_in_merge("a@1", ["a@1"])[1] == [], "nothing new → nothing to write")
check(J.fixed_in_merge("", ["x@2.1.72"])[2] == "x@2.1.72", "an empty field takes the entries as given")
check(J.fixed_in_merge("x@2.1.22", ["x@2.1.72"])[2] == "x@2.1.22; x@2.1.72", "an older build of the same slug is kept")
good = ["ur-portal@1.9.0+87", "unified-streaming@2.1.72", "mds-audio-card-capture@audio_card_capture:1.0.2"]
bad = ["unified streaming@2.1.72", "@1.0", "slug@", "Slug@1.0"]
check(all(J.FIXED_IN_ENTRY.match(e) for e in good), "the map's slug@version forms are accepted")
check(not any(J.FIXED_IN_ENTRY.match(e) for e in bad), "free text and malformed entries are refused")
known = {"unified-streaming", "ur-portal", "mds-ai-sender", "mds-audio-card-capture"}
rd = lambda body: [("mds-ai-sender", "output:v1.0.19")] if body.startswith("output:") else []
check(J.fixed_in_problem("output@v1.0.19", known, rd) == "a docker image is not a slug; write mds-ai-sender@output:v1.0.19",
      "MH-3829: an image name in the slug's place is refused, with the docker form suggested")
check(J.fixed_in_problem("mds-ai-sender@v1.0.19", known, rd) is not None, "a docker entry without its image is refused")
check(J.fixed_in_problem("unified-streaming@output:v1.0.19", known, rd) is not None, "an image:tag under a SaaS slug is refused")
check(J.fixed_in_problem("nosuch@1.0.0", known, rd) == "slug not in the release map", "an unknown slug is refused")
check(all(J.fixed_in_problem(e, known, rd) is None for e in good + ["mds-ai-sender@output:v1.0.19"]), "the map's forms pass")

sys.exit(1 if failures else 0)
