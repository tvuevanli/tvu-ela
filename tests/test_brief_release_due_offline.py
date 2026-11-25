#!/usr/bin/env python3
"""brief release_due, offline: the morning page's one line when a release of <published> is due, read from
`publish.py release --json` at most once a day and kept in the runner directory; nothing when not due; a failed read
is not kept. The publish verb is faked; nothing is read or written outside a temporary directory."""
import os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "brief"))
import brief as B  # noqa: E402

failures = 0


def check(name, cond):
    global failures
    print(("ok   " if cond else "FAIL ") + name)
    failures += 0 if cond else 1


calls = []


def fake(report):
    def run(cmd, timeout=600):
        calls.append(cmd)
        if isinstance(report, Exception):
            raise report
        return report
    return run


due = {"elak_head": "abcdef123456", "last_release": "0123456789abcdef0123", "due": True,
       "elak_changed": ["map/services.yaml", "knowledge/platform/ur.md", "map/apis.yaml"], "would_commit": 4, "refused": 0}
with tempfile.TemporaryDirectory() as d:
    r = B.release_due("2026-11-26", d, fake(due))
    check("a due release is one line naming the changed paths and the last release",
          r["line"] == "elak-published: a release is due (3 paths changed since 0123456789ab)"
                       " → review in the mirror vault, then say publish")
    check("the publish verb is called as a dry run with --json", calls[-1][-2:] == ["release", "--json"] and "--apply" not in calls[-1])
    check("the verdict is kept for the day", os.path.exists(os.path.join(d, "release-due-2026-11-26.json")))
    n = len(calls)
    again = B.release_due("2026-11-26", d, fake({"due": False}))
    check("a second call the same day reads the kept verdict, not the verb", len(calls) == n and again["line"] == r["line"])
    nxt = B.release_due("2026-11-27", d, fake(dict(due, elak_changed=["map/services.yaml"])))
    check("the next day reads again, and the line stays while the release is due", len(calls) == n + 1 and "(1 paths changed" in nxt["line"])
    first = B.release_due("2026-11-28", d, fake({"due": True, "last_release": None, "elak_changed": None, "would_commit": 7, "refused": 2}))
    check("no release yet: the paths that would be committed, since none, and the guard's refusals",
          first["line"].startswith("elak-published: a release is due (7 paths changed since none); the release guard refuses 2 line(s)"))
    quiet = B.release_due("2026-11-29", d, fake({"due": False, "last_release": "0123456789ab", "elak_changed": [], "refused": 0}))
    check("not due: no line", quiet["line"] is None and quiet["due"] is False)
    bad = B.release_due("2026-11-30", d, fake(B.LaneError({"query": "release --json", "exit": 2, "stderr": "not a git repository"})))
    check("a failed read is an error, no line, and is not kept", bad["line"] is None and "error" in bad
          and not os.path.exists(os.path.join(d, "release-due-2026-11-30.json")))

print(f"{failures} failure(s)" if failures else "brief release_due: all cases pass")
sys.exit(1 if failures else 0)
