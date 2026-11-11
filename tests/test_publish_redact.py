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
# the record of 2026-11-11: MH-3962's Jira title quotes a Chinese error message; the tickets pass failed twice on it
import tempfile, io, contextlib, argparse  # noqa: E402
title = "[cn2] Resource-pool allocation failure shows an unclear error prompt (0x81004009 / " + chr(34) + cjk(12) + chr(34) + ")"
doc = publish.json.dumps({"lane": "qa-cn3", "left": {"MH-3962": {"ticket": "MH-3962", "title": title,
                          "why": "QA said " + q(cjk(10))}}}, ensure_ascii=False, indent=1)
facts = {title}
check([p for p, _, _ in publish.guard_flags(doc, "test-list-qa-cn3.json", facts)] == ["$.left.MH-3962.why"],
      "a quotation inside a Jira title passes the guard; the same words elsewhere do not")
check(publish.guard_flags("- [MH-3962](u) " + title + " — in progress", "lanes.md", facts) == [],
      "the lanes page citing that title passes")
with tempfile.TemporaryDirectory() as tmp:
    src, pub = os.path.join(tmp, "reports", "lanes"), os.path.join(tmp, "published")
    os.makedirs(src); os.makedirs(pub)
    open(os.path.join(src, "test-list-qa-cn3.json"), "w", encoding="utf-8").write(doc)
    open(os.path.join(src, "lanes.md"), "w", encoding="utf-8").write("- [MH-3962](u) " + title + "\n")
    publish.site = lambda: {"reports": os.path.join(tmp, "reports")}
    publish.roots = lambda: (tmp, pub)
    out, code = io.StringIO(), 0
    with contextlib.redirect_stdout(out):
        try:
            publish.cmd_lanes(argparse.Namespace(sync=False, json=True))
        except SystemExit as e:
            code = e.code or 0
    r = publish.json.loads(out.getvalue())
    got = publish.json.load(open(os.path.join(pub, "lanes", "test-list-qa-cn3.json"), encoding="utf-8"))
    check(code == 0 and sorted(r["published"]) == ["lanes.md", "test-list-qa-cn3.json"] and r["refused"] == [],
          "the lanes pass completes with MH-3962 in the data, exit 0")
    check(got["left"]["MH-3962"]["title"] == title and got["left"]["MH-3962"]["why"] == "QA said " + publish.QUOTE_CUT
          and r["cut"][0]["file"] == "test-list-qa-cn3.json",
          "the title is kept whole; a quoted sentence in another field is cut out and reported")
if failures:
    print(f"publish redact: {len(failures)} failed"); sys.exit(1)
print("publish redact: all cases pass")
