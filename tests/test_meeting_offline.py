#!/usr/bin/env python3
"""ela meeting, offline: the meeting note's shape, the 140-character lint, the 30-day roll, and each verb flag
(--raise, --propose, --rule, --slack, --json, --dry-run) against a throwaway vault and meetings file."""
import contextlib, datetime, io, json, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "brief"))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import brief as B  # noqa: E402
import vault as V  # noqa: E402

failures = 0


def check(name, cond):
    global failures
    print(("ok   " if cond else "FAIL ") + name)
    failures += 0 if cond else 1


YAML = """meetings:
  - name: "Scrum with the PM"
    key: scrum-pm
    weekdays: [Mon, Wed, Fri]
    time: "10:00"
    audience: product
    enabled: true
    channel: "prj_dev_mediahub"
    post: true
"""

# the shape: parse and render keep every line, Ruled newest first
NOTE = """---
title: "Scrum with the PM · Mon Wed Fri 10:00"
type: "meeting"
source: "vault"
---
# Scrum with the PM · Mon Wed Fri 10:00

- [x] send — the list goes to #prj_dev_mediahub at 10:00 on your tick

## To raise

- [ ] [MH-2406](https://j.example/browse/MH-2406) — notice for 0x81004009 too? · you decide with the PM · since 10-29
  - detail folded
- [ ] release cadence — the 2.1 train's day · since 10-26 · ela proposes

## Ruled

### 2026-09-01

- MH-1 — old · ruled: yes

### 2026-10-28

- MH-2 — newer · ruled by your tick

## Notes

his own section
"""
n = V.meeting_parse(NOTE)
check("the note parses: send ticked, two items, a detail under the first, two ruled dates, his section",
      n["send"]["ticked"] and len(n["items"]) == 2 and n["items"][0]["under"] == ["  - detail folded"]
      and [d for d, _ in n["ruled"]] == ["2026-09-01", "2026-10-28"] and n["others"][0][0] == "Notes")
out = V.meeting_render(n, "Scrum with the PM · Mon Wed Fri 10:00", "the list goes to #prj_dev_mediahub at 10:00 on your tick",
                       datetime.date(2026, 10, 30))
check("a render keeps every line and puts Ruled newest first",
      all(x in out for x in ("- [x] send", "  - detail folded", "his own section", "ela proposes"))
      and out.index("### 2026-10-28") < out.index("### 2026-09-01") and 'source: "vault"' in out)
check("parse ∘ render is stable", V.meeting_render(V.meeting_parse(out), "Scrum with the PM · Mon Wed Fri 10:00",
                                                   "the list goes to #prj_dev_mediahub at 10:00 on your tick", datetime.date(2026, 10, 30)) == out)
f = V.meeting_fields(n["items"][0]["text"])
check("an item's fields: its key, since, whether ela proposed it", f["key"] == "MH-2406" and f["since"] == "10-29" and not f["proposed"]
      and V.meeting_fields(n["items"][1]["text"])["proposed"])

# the lint: an item over 140 characters as reading mode shows it, a missing box or section
check("a note in shape has no lint", V.meeting_lint("meetings/scrum-pm.md", NOTE) == [])
long_ = NOTE.replace("notice for 0x81004009 too?", "x" * 120)
check("an item over 140 characters is a lint line; the link's URL is not counted",
      any("item 1 is" in x and "over 140" in x for x in V.meeting_lint("m.md", long_)) and len(V.visible(n["items"][0]["text"])) < 140)
check("no send box, no Ruled: two lint lines", len(V.meeting_lint("m.md", "# M\n\n## To raise\n")) == 2)

with tempfile.TemporaryDirectory() as t:
    vault, elak, reports = (os.path.join(t, x) for x in ("vault", "elak", "reports"))
    os.makedirs(os.path.join(elak, "blueprint")); os.makedirs(os.path.join(vault, "meetings"))
    open(os.path.join(elak, "blueprint", "meetings.yaml"), "w").write(YAML)
    env = os.path.join(t, ".env")
    open(env, "w").write("JIRA_BASE_URL=https://j.example\n")
    site = os.path.join(t, "site.json")
    json.dump({"vault": vault, "elak": elak, "reports": reports, "runtime": os.path.join(t, "runtime"), "env": env}, open(site, "w"))
    B.SITE = V.SITE = site
    B._DAY = None
    note = os.path.join(vault, "meetings", "scrum-pm.md")

    def run(*argv):
        so, se, code = io.StringIO(), io.StringIO(), 0
        sys.argv = ["brief.py", "meeting", "--key", "scrum-pm", *argv]
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            try:
                B.main()
            except SystemExit as e:
                code = e.code or 0
        return so.getvalue(), se.getvalue(), code

    # --raise: his item, the key a link, since today; the note made in shape on first use; twice is once
    o, _, c = run("--raise", "MH-2406 — friendly notice for 0x81004009 too?", "--decides", "you decide with the PM",
                  "--detail", "the pool has no usable box", "--now", "2026-10-29T09:00")
    text = open(note).read()
    check("--raise makes the note in shape and adds the item, the key a Jira link, since today, its detail folded",
          c == 0 and V.meeting_lint("meetings/scrum-pm.md", text) == []
          and "- [ ] [MH-2406](https://j.example/browse/MH-2406) — friendly notice for 0x81004009 too? · you decide with the PM · since 10-29" in text
          and "  - the pool has no usable box" in text and "- [ ] send — the list goes to #prj_dev_mediahub at 10:00 on your tick" in text)
    run("--raise", "MH-2406 — friendly notice for 0x81004009 too?", "--now", "2026-10-30T08:00")
    check("--raise again is idempotent", open(note).read().count("friendly notice") == 1)
    o, e, c = run("--raise", "MH-1 — " + "y" * 150, "--now", "2026-10-30T08:00")
    check("--raise over 140 characters is refused, exit 4, nothing written", c == 4 and "over 140" in e and "yyyy" not in open(note).read())

    # --propose: ela's item, marked; --dry-run writes nothing
    before = open(note).read()
    o, _, c = run("--propose", "MH-3820 — ship on build 79 or hold for QA?", "--now", "2026-10-30T08:00", "--dry-run")
    check("--dry-run reports and writes nothing", c == 0 and "DRY RUN" in o and open(note).read() == before)
    run("--propose", "MH-3820 — ship on build 79 or hold for QA?", "--now", "2026-10-30T08:00")
    check("--propose adds an item marked ela proposes", "ship on build 79 or hold for QA? · since 10-30 · ela proposes" in open(note).read())

    # --json: what the runner needs; the pointer line and today's new items
    o, _, c = run("--json", "--now", "2026-10-30T08:00")
    j = json.loads(o)
    check("--json carries the send box, the channel, the pointer line and today's new items",
          c == 0 and j["send_ticked"] is False and j["channel"] == "prj_dev_mediahub" and j["post"] is True and j["date"] == "2026-10-30"
          and j["pointer"] == "Scrum with the PM at 10:00 · 2 items on [[meetings/scrum-pm]] · 1 new today"
          and len(j["new"]) == 1 and "MH-3820" in j["new"][0] and j["lint"] == [])

    # --slack: the unticked items, a 'first' line on top, ela's mark off, links as Slack writes them
    t2 = open(note).read().replace("ship on build 79 or hold for QA? · since 10-30 · ela proposes",
                                   "ship on build 79 or hold for QA? · since 10-30 · ela proposes\n  ela: first")
    open(note, "w").write(t2)
    o, _, c = run("--slack", "--now", "2026-10-30T08:00")
    lines = o.strip().splitlines()
    check("--slack: a header with the meeting's day, his 'first' item on top, Slack links, no ela mark",
          c == 0 and lines[0] == "*Scrum with the PM · Fri 10-30 10:00*" and "MH-3820" in lines[1]
          and "<https://j.example/browse/MH-2406|MH-2406>" in lines[2] and "ela proposes" not in o and lines[1].startswith("• "))

    # --rule before the meeting: a ticked proposal is dropped; an ela: line waits for the meeting
    t3 = open(note).read().replace("- [ ] [MH-3820]", "- [x] [MH-3820]").replace(
        "  - the pool has no usable box", "  - the pool has no usable box\n  ela: ruled — yes, same notice")
    t3 = t3.replace("- [ ] send", "- [x] send")
    open(note, "w").write(t3)
    o, _, c = run("--rule", "--json", "--now", "2026-10-30T09:00")
    j = json.loads(o)
    check("--rule before the meeting: a proposal he ticked is dropped; his ruling line waits; the send tick stays",
          [r["outcome"] for r in j["ruled"]] == ["dropped"] and "MH-3820" in j["ruled"][0]["key"]
          and "### 2026-10-30" in open(note).read() and "· dropped" in open(note).read() and len(j["items"]) == 1 and j["send_ticked"])

    # --rule after it: his ela: line rules the item, with a follow-up draft; the send box is unticked for the next one
    o, _, c = run("--rule", "--json", "--now", "2026-10-30T11:00")
    j = json.loads(o)
    text = open(note).read()
    check("--rule after the meeting: his line rules the item under today's date, with a tier-3 follow-up draft",
          [r["outcome"] for r in j["ruled"]] == ["ruled"] and j["ruled"][0]["words"] == "yes, same notice"
          and j["follow_ups"] == [{"key": "MH-2406", "tier": 3, "draft": "Scrum with the PM, 2026-10-30: yes, same notice"}]
          and "· ruled: yes, same notice" in text and "since 10-29 · ruled" not in text and j["items"] == [])
    check("after the meeting the send box is unticked and the next meeting is Monday",
          not j["send_ticked"] and "- [ ] send" in text and j["date"] == "2026-11-02")
    check("a ruled item's detail stays folded under it; his ela: line does not", "  - the pool has no usable box" in text
          and "ela: ruled" not in text)

    # the 30-day roll: an old Ruled date leaves for archive/meetings-<key>-<yyyy-mm>.md, once
    t4 = open(note).read().replace("## Ruled\n", "## Ruled\n\n### 2026-09-15\n\n- MH-9 — old · ruled: no\n")
    open(note, "w").write(t4)
    moved = V.meeting_roll(vault, datetime.date(2026, 10, 30))
    arch = os.path.join(vault, "archive", "meetings-scrum-pm-2026-09.md")
    check("the roll moves a date older than 30 days to the month's archive note and keeps the rest",
          moved == [("meetings/scrum-pm.md", "2026-09-15", "archive/meetings-scrum-pm-2026-09.md")]
          and "### 2026-09-15" in open(arch).read() and "MH-9 — old" in open(arch).read()
          and "2026-09-15" not in open(note).read() and "### 2026-10-30" in open(note).read())
    check("a second roll moves nothing", V.meeting_roll(vault, datetime.date(2026, 10, 30)) == [])

    # an unknown key is exit 3
    sys.argv = ["brief.py", "meeting", "--key", "nope"]
    with contextlib.redirect_stderr(io.StringIO()):
        try:
            B.main(); code = 0
        except SystemExit as e:
            code = e.code
    check("a key meetings.yaml does not name is exit 3", code == 3)

sys.exit(1 if failures else 0)
