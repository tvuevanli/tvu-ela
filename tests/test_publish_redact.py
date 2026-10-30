#!/usr/bin/env python3
"""`publish.redact` replaces an address that is the host of a URL even when the URL's path looks like a
version (`/v1/`), and keeps a dotted version number on a version line. Pure function; nothing is read or
written."""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "publish"))
import publish  # noqa: E402 — the module under test

failures = []


def check(ok, label):
    print(("ok   " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


check(publish.redact("default: https://10.1.2.3:4318/v1/traces") == "default: https://<ip>:4318/v1/traces",
      "a URL host is redacted although its path carries /v1/")
check(publish.redact("version: 1.0.0.12") == "version: 1.0.0.12",
      "a dotted version on a version line is kept")


# built at run time, so this file carries no quoted sentence or credential of its own (the guard reads it too)
cjk = lambda n: "".join(chr(0x4e00 + k) for k in range(n))  # noqa: E731
q = lambda t: "\u300c" + t + "\u300d"  # noqa: E731
check(publish.guard_flags("| [MH-3704](u) | " + cjk(12) + q(cjk(4)) + " |") == [],
      "a ticket title quoting a four-character button label passes the lanes guard")
check([w for _, w, _ in publish.guard_flags("line\n" + q(cjk(14)) + "\n")] == ["a quoted CJK sentence"],
      "a quoted sentence on a lanes page is refused")
check([w for _, w, _ in publish.guard_flags("tok" + "en = " + "a" * 26)] == ["credential assignment"],
      "a credential on a lanes page is refused")
lane = lambda title: publish.json.dumps({"rows": [{"key": "MH-1", "title": title}]}, ensure_ascii=False)  # noqa: E731
check(publish.guard_flags(lane(cjk(14)), "dev-list-2.1.json") == [],
      "a lanes json whose title is a CJK sentence passes: json quotes are syntax")
check([(n, w) for n, w, _ in publish.guard_flags(lane(cjk(4) + q(cjk(8))), "dev-list-2.1.json")]
      == [("$.rows[0].title", "a quoted CJK sentence")],
      "a lanes json whose title quotes an eight-character CJK sentence is refused, by key path")
check([w for _, w, _ in publish.guard_flags(lane("tok" + "en = " + "a" * 26), "dev-list-2.1.json")] == ["credential assignment"],
      "a credential in a lanes json is still refused on the raw text")
check([w for _, w, _ in publish.guard_flags('{"title": "' + cjk(14) + '",', "dev-list-2.1.json")] == ["a quoted CJK sentence"],
      "a lanes json that does not parse is read as text")
check(bool(publish.LANE_PAGE.match("test-list-qa-cn3.json")) and not publish.LANE_PAGE.match("notes.md"),
      "only the lanes page and the lists are published from <reports>/lanes/")
if failures:
    print(f"publish redact: {len(failures)} failed"); sys.exit(1)
print("publish redact: all cases pass")
