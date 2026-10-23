#!/usr/bin/env python3
"""The vault, offline: path names, the reading gate, and link conversion."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import vault as V  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

check("a slug is lowercase with hyphens", V.slug("The remote host retires; everything runs") == "the-remote-host-retires-everything-runs")
check("an apostrophe joins its word", V.slug("Evan's Work System") == "evans-work-system")
check("CJK is kept", V.slug("General Encoding Profile 参数合法性") == "general-encoding-profile-参数合法性")
check("a slug is cut at a word", not V.slug("word " * 30).endswith("-") and len(V.slug("word " * 30)) <= 60)
check("the date is not repeated in the title", V.undated("ela review — 2026-10-23", "2026-10-23") == "ela review")
check("the weekday after a date goes too", V.undated("MediaHub 全量复核 — 2026-09-07（周一）", "2026-09-07") == "MediaHub 全量复核")
n = V.Note("days/x.md", "x", "# Brief\n\n" + "word " * 1300, {"type": "day"})
check("a day page over budget is held", any("budget" in p for p in V.reading_gate(n)))
n = V.Note("days/x.md", "x", "no heading here", {"type": "day"})
check("a page without a title heading is held", "no title heading" in V.reading_gate(n))
n = V.Note("reviews/x.md", "x", "# R\n\nsee /home/u/a and /home/u/b and <runtime>/c", {"type": "review"})
check("machine paths hold a review", any("machine" in p for p in V.reading_gate(n)))
V.JIRA_BASE[0] = "https://jira.example"
out = V.link_text("Fixed by MH-12, see [MH-12](https://jira.example/browse/MH-12) and `code MH-12`.", {})
check("a bare key is a direct Jira link", out.startswith("Fixed by [MH-12](https://jira.example/browse/MH-12),"))
check("an existing link is left alone", out.count("](https://jira.example/browse/MH-12)") == 2)
check("a key inside code stays code", "`code MH-12`" in out)
check("a codec name is not a ticket", V.link_text("UTF-8 and AWS-3", {}) == "UTF-8 and AWS-3")
check("an address is redacted", "<address>" in V.redact("box " + ".".join(["10", "0", "0", "7"]) + ":8080 down"))
check("a version is not an address", V.redact("v1.0.622.2") == "v1.0.622.2")
sys.exit(1 if failures else 0)
