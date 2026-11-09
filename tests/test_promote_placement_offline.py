#!/usr/bin/env python3
"""Per-ticket placement (promote's placement.py), offline, against prod-3's versions of 2026-11-09: a ticket whose
Fixed In is at or below the target is already there; one with a part above it is partly new; a commit scoped to
another key or citing the key in its body does not make it new; test-only commits ship nothing; QA's pass build
places a ticket only when nothing else does."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "promote"))
import placement as P  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

TARGET = {"unified-streaming": {"parsed": [2, 1, 78, 0, 368], "version": "v2.1.78 build368"},
          "mediahub-frontend": {"parsed": [2, 2, 116, 1, 182], "version": "v2.2.116.1 build182"},
          "unified-media-frontend": {"parsed": [3, 0, 38, 0, 195], "version": "v3.0.38 build195"}}
def fi(slug, v, parsed): return {"slug": slug, "version": v, "parsed": parsed, "docker": False}
def cm(svc, kind, subject, body=False): return {"service": svc, "kind": kind, "sha": "x", "subject": subject, "only_in_body": body}

p = P.place({"key": "MH-3579", "fixed_in_entries": [fi("unified-streaming", "2.1.59", [2, 1, 59, 0, 0])], "commits": []}, TARGET)
check("Fixed In below the target, no commit: on-target", p["placement"] == "on-target")
p = P.place({"key": "MH-3800", "fixed_in_entries": [fi("unified-streaming", "2.1.75", [2, 1, 75, 0, 0]), fi("mediahub-frontend", "2.2.117", [2, 2, 117, 0, 0]),
                                                    fi("unified-media-frontend", "3.0.37", [3, 0, 37, 0, 0])],
             "commits": [cm("mediahub-frontend", "feat", "feat(MH-3800): start confirmation")]}, TARGET)
check("a part above the target and two below: partly-new, the part named", p["placement"] == "partly-new" and p["new_parts"] == ["mediahub-frontend"])
p = P.place({"key": "MH-3582", "fixed_in_entries": [fi("mediahub-frontend", "2.2.104", [2, 2, 104, 0, 0])],
             "commits": [cm("mediahub-frontend", "fix", "fix(MH-1860): label goes through MH-3582's tag")]}, TARGET)
check("a commit scoped to another key cites it, it does not make it new", p["placement"] == "on-target" and "cite" in P.words(p))
p = P.place({"key": "MH-3163", "fixed_in_entries": [fi("unified-streaming", "2.1.55", [2, 1, 55, 0, 0])],
             "commits": [cm("unified-streaming", "fix", "fix(copier): null guard [nightly]", body=True)]}, TARGET)
check("a body-only citation (a nightly guard) leaves the ticket on the target", p["placement"] == "on-target")
p = P.place({"key": "MH-3503", "fixed_in_entries": [fi("mediahub-frontend", "2.2.94", [2, 2, 94, 0, 0])],
             "commits": [cm("mediahub-frontend", "test", "test(MH-3503): assertions")]}, TARGET)
check("test-only commits ship nothing", p["placement"] == "on-target")
p = P.place({"key": "MH-3909", "fixed_in_entries": [fi("unified-streaming", "2.1.84", [2, 1, 84, 0, 0])],
             "commits": [cm("unified-streaming", "fix", "fix(MH-3909): MXL DR backup")]}, TARGET)
check("an owned commit in the range is new", p["placement"] == "new")
p = P.place({"key": "MH-3668", "fixed_in_entries": [], "commits": [cm("mediahub-frontend", "test", "test: stale assertions", body=True)]},
            TARGET, {"mediahub-frontend": "v2.2.111 build170"})
check("no Fixed In, no owned commit: QA's pass build at or below the target places it", p["placement"] == "on-target")
p = P.place({"key": "MH-9", "fixed_in_entries": [], "commits": []}, TARGET, {"mediahub-frontend": "v2.2.128 build185"})
check("QA's build above the target says nothing: unknown, never new", p["placement"] == "unknown")
p = P.place({"key": "MH-8", "fixed_in_entries": [fi("unified-media-backend", "1.0.287", [1, 0, 287, 0, 0])], "commits": []}, TARGET)
check("a service the target does not report is unknown", p["placement"] == "unknown")

if failures:
    print(f"placement: {len(failures)} failure(s)"); sys.exit(1)
print("placement: all offline checks passed")
