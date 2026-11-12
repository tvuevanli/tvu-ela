#!/usr/bin/env python3
"""ela meeting, offline: the meeting note's shape, the 140-character lint, the 30-day roll, and each verb flag
(--raise, --propose, --rule, --slack, --json, --dry-run) against a throwaway vault and meetings file."""
import re, contextlib, datetime, io, json, os, sys, tempfile

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

## Where things stand

- Prod 3 on 2.1.42
"""
n = V.meeting_parse(NOTE)
check("the note parses: two items, a detail under the first, two ruled dates, his section",
      not n["send"] and len(n["items"]) == 2 and n["items"][0]["under"] == ["  - detail folded"]
      and [d for d, _ in n["ruled"]] == ["2026-09-01", "2026-10-28"] and n["others"][0][0] == "Notes")
out = V.meeting_render(n, "Scrum with the PM · Mon Wed Fri 10:00", "the list goes to #prj_dev_mediahub at 10:00 on your tick",
                       datetime.date(2026, 10, 30))
check("a render keeps every line and puts Ruled newest first",
      all(x in out for x in ("  - detail folded", "his own section", "ela proposes"))
      and out.index("### 2026-10-28") < out.index("### 2026-09-01") and 'source: "vault"' in out)
check("the page shown to the team: Where things stand first, then To raise, Ruled, his sections; no send line",
      out.index("## Where things stand") < out.index("## To raise") < out.index("## Ruled") < out.index("## Notes")
      and "send" not in out.split("## Where")[0])
legacy = NOTE.replace(
    "# Scrum with the PM · Mon Wed Fri 10:00\n", "# Scrum with the PM · Mon Wed Fri 10:00\n\n- [x] send — on your tick\n", 1)
check("a send line left on a note is a lint line, and the render drops it",
      any("send line" in x for x in V.meeting_lint("m.md", legacy))
      and "- [x] send" not in V.meeting_render(V.meeting_parse(legacy), "Scrum with the PM · Fri 2026-10-30", None, datetime.date(2026, 10, 30)))
day_note = V.meeting_render(V.meeting_parse(NOTE.replace("since 10-29", "since 10-30")), "Scrum with the PM · Fri 2026-10-30", None,
                            datetime.date(2026, 10, 30))
check("since only when older than the meeting day; aliases hold only the title",
      "notice for 0x81004009 too? · you decide with the PM\n" in day_note and "since 10-26" in day_note
      and 'aliases: ["Scrum with the PM · Fri 2026-10-30"]' in day_note)
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
check("no Ruled: one lint line", len(V.meeting_lint("m.md", "# M\n\n## To raise\n")) == 1)

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

    # with no note in the verb's form, the list is the records' (ADR 0016): --raise adds a question, writes no note
    o, _, c = run("--raise", "MH-2406 — friendly notice for 0x81004009 too?", "--decides", "PM lead", "--now", "2026-10-29T09:00")
    qs = json.load(open(os.path.join(reports, "ela", "questions.json")))["questions"]
    check("no verb's note: --raise records a question for the meeting and writes no meetings/<key>.md",
          c == 0 and not os.path.exists(note) and len(qs) == 1 and list(qs.values())[0]["audience"] == "scrum-pm"
          and list(qs.values())[0]["who"] == "PM lead")
    built = os.path.join(vault, "meetings", "2026-10-30-scrum-pm.md")
    open(built, "w").write('---\ntitle: "Scrum with the PM · Fri 2026-10-30"\ntype: "meeting"\ndate: "2026-10-30"\nby: "ela"\n---\n\n'
                           "# Scrum with the PM · Fri 2026-10-30\n\n## Carried\n\n- [ ] friendly notice for 0x81004009 too? · PM lead ^q-abcdef\n")
    o, _, c = run("--json", "--now", "2026-10-29T09:00")
    j = json.loads(o)
    check("--json reads the dated note for the meeting: its boxes are the list, its path the note",
          j["note"] == "meetings/2026-10-30-scrum-pm.md" and len(j["items"]) == 1 and "^q-" not in j["items"][0]["text"]
          and "[[meetings/2026-10-30-scrum-pm]]" in j["pointer"])
    os.remove(built); os.remove(os.path.join(reports, "ela", "questions.json"))
    open(note, "w").write('---\ntitle: "Scrum with the PM · Fri 2026-10-30"\ntype: "meeting"\nsource: "vault"\n---\n\n'
                          "# Scrum with the PM · Fri 2026-10-30\n\n## To raise\n\n## Ruled\n")

    # --raise on the verb's note: his item, the key a link, since today; twice is once
    o, _, c = run("--raise", "MH-2406 — friendly notice for 0x81004009 too?", "--decides", "you decide with the PM",
                  "--detail", "the pool has no usable box", "--now", "2026-10-29T09:00")
    text = open(note).read()
    check("--raise keeps the verb's note in shape and adds the item, the key a Jira link, since today, its detail folded",
          c == 0 and V.meeting_lint("meetings/scrum-pm.md", text) == []
          and "- [ ] [MH-2406](https://j.example/browse/MH-2406) — friendly notice for 0x81004009 too? · you decide with the PM · since 10-29" in text
          and "  - the pool has no usable box" in text and "send" not in text
          and 'title: "Scrum with the PM · Fri 2026-10-30"' in text)
    run("--raise", "MH-2406 — friendly notice for 0x81004009 too?", "--now", "2026-10-30T08:00")
    check("--raise again is idempotent", open(note).read().count("friendly notice") == 1)
    o, e, c = run("--raise", "MH-1 — " + "y" * 150, "--now", "2026-10-30T08:00")
    check("--raise over 140 characters is refused, exit 4, nothing written", c == 4 and "over 140" in e and "yyyy" not in open(note).read())

    # --propose: ela's item, marked; --dry-run writes nothing
    before = open(note).read()
    o, _, c = run("--propose", "MH-3820 — ship on build 79 or hold for QA?", "--now", "2026-10-30T08:00", "--dry-run")
    check("--dry-run reports and writes nothing", c == 0 and "DRY RUN" in o and open(note).read() == before)
    run("--propose", "MH-3820 — ship on build 79 or hold for QA?", "--now", "2026-10-30T08:00")
    check("--propose adds an item, unmarked, no age on its own meeting day: the note is shown to the team",
          "ship on build 79 or hold for QA?\n" in open(note).read() and "since 10-30" not in open(note).read()
          and "ela proposes" not in open(note).read())

    # --json: what the runner needs; the pointer line and today's new items
    o, _, c = run("--json", "--now", "2026-10-30T08:00")
    j = json.loads(o)
    check("--json carries the send box, the channel, the pointer line and today's new items",
          c == 0 and j["send_ticked"] is False and j["channel"] == "prj_dev_mediahub" and j["post"] is True and j["date"] == "2026-10-30"
          and j["pointer"] == "Scrum with the PM at 10:00 · 2 items on [[meetings/scrum-pm]] · 1 new today"
          and len(j["new"]) == 1 and "MH-3820" in j["new"][0] and j["lint"] == [])

    # --slack: the unticked items, a 'first' line on top, ela's mark off, links as Slack writes them
    t2 = open(note).read().replace("ship on build 79 or hold for QA?\n", "ship on build 79 or hold for QA?\n  ela: first\n")
    open(note, "w").write(t2)
    o, _, c = run("--slack", "--now", "2026-10-30T08:00")
    lines = o.strip().splitlines()
    check("--slack: a header with the meeting's day, his 'first' item on top, Slack links, no ela mark",
          c == 0 and lines[0] == "*Scrum with the PM · Fri 10-30 10:00*" and "MH-3820" in lines[1]
          and "<https://j.example/browse/MH-2406|MH-2406>" in lines[2] and "ela proposes" not in o and lines[1].startswith("• "))

    # --rule before the meeting: a ticked proposal is dropped; an ela: line waits for the meeting
    t3 = open(note).read().replace("- [ ] [MH-3820]", "- [x] [MH-3820]").replace(
        "  - the pool has no usable box", "  - the pool has no usable box\n  ela: ruled — yes, same notice")
    open(note, "w").write(t3)
    o, _, c = run("--rule", "--json", "--now", "2026-10-30T09:00")
    j = json.loads(o)
    check("--rule before the meeting: a proposal he ticked is dropped; his ruling line waits",
          [r["outcome"] for r in j["ruled"]] == ["dropped"] and "MH-3820" in j["ruled"][0]["key"]
          and "### 2026-10-30" in open(note).read() and "· dropped" in open(note).read() and len(j["items"]) == 1)

    # --rule after it: his ela: line rules the item, with a follow-up draft; the send box is unticked for the next one
    o, _, c = run("--rule", "--json", "--now", "2026-10-30T11:00")
    j = json.loads(o)
    text = open(note).read()
    check("--rule after the meeting: his line rules the item under today's date, with a tier-3 follow-up draft",
          [r["outcome"] for r in j["ruled"]] == ["ruled"] and j["ruled"][0]["words"] == "yes, same notice"
          and j["follow_ups"] == [{"key": "MH-2406", "tier": 3, "draft": "Scrum with the PM, 2026-10-30: yes, same notice"}]
          and "· ruled: yes, same notice" in text and "since 10-29 · ruled" not in text and j["items"] == [])
    check("after the meeting no send line is written and the next meeting is Monday",
          not j["send_ticked"] and "send" not in text and j["date"] == "2026-11-02")
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

    # a name written by hand is kept; the date moves with the meeting; the old title stays an alias
    t1 = open(note).read()
    cur = re.search(r'^title: "([^"]+)"', t1, re.M).group(1)
    open(note, "w").write(t1.replace(f'title: "{cur}"', 'title: "MediaHub team sync · Fri 2026-10-30"'))
    run("--raise", "MH-7 — a hand-titled note", "--now", "2026-11-02T11:00")
    t1 = open(note).read()
    check("a name written by hand is kept, the date moves to the next meeting, aliases hold only the title",
          'title: "MediaHub team sync · Wed 2026-11-04"' in t1 and "Scrum with the PM" not in t1.split("---")[1]
          and 'aliases: ["MediaHub team sync · Wed 2026-11-04"]' in t1)

    # an unknown key is exit 3
    sys.argv = ["brief.py", "meeting", "--key", "nope"]
    with contextlib.redirect_stderr(io.StringIO()):
        try:
            B.main(); code = 0
        except SystemExit as e:
            code = e.code
    check("a key meetings.yaml does not name is exit 3", code == 3)

# a meeting closed by ela, after its end, without a tick: the record of 2026-11-11 (MH-3568 split the same day)
with tempfile.TemporaryDirectory() as t:
    vault, reports, facts = (os.path.join(t, x) for x in ("vault", "reports", "facts"))
    os.makedirs(os.path.join(vault, "meetings")); os.makedirs(os.path.join(facts, "jira", "issues")); os.makedirs(os.path.join(reports, "ela"))
    def issue(key, created, links=(), status="Review", who="Evan Li", comments=()):
        json.dump({"key": key, "fields": {"created": created, "status": {"name": status}, "assignee": {"displayName": who},
                   "statuscategorychangedate": "2026-11-01T10:00:00.000+0800",
                   "issuelinks": [{"type": {"name": "Relates"}, "inwardIssue": {"key": k}} for k in links]},
                   "comments": list(comments)}, open(os.path.join(facts, "jira", "issues", f"{key}.json"), "w"))
    issue("MH-3568", "2026-09-01T10:00:00.000+0800", links=["MH-3998", "MH-3997", "SEC-1"])
    issue("MH-3998", "2026-11-10T19:20:19.107-0800"); issue("MH-3997", "2026-11-10T19:19:12.169-0800"); issue("SEC-1", "2026-01-01T00:00:00.000+0800")
    issue("MH-3990", "2026-11-01T10:00:00.000+0800")
    issue("MH-3993", "2026-11-10T10:00:00.000+0800", who="Fujian Fang", comments=[{"author": {"displayName": "Summer Chen"}, "created": "2026-11-11T15:00:00.000+0800"}])
    note = os.path.join(vault, "meetings", "sync.md")
    open(note, "w").write("""---
title: "MediaHub team sync · Wed 2026-11-11"
aliases: ["MediaHub team sync · Wed 2026-11-11", "Engineering + QA + UX sync · Tue Thu not scheduled yet"]
type: "meeting"
date: "2026-11-11"
source: "vault"
---

# MediaHub team sync · Wed 2026-11-11

- [ ] send — no channel set yet

## To raise

- [ ] [MH-3568](https://j/browse/MH-3568) — optional SCTE-35: owners? · the team · since 11-11
  - rule: passthrough keeps SCTE-35
- [ ] [MH-3990](https://j/browse/MH-3990) — Black frame to MQTT: who? · Gabriel Liu · since 11-11
- [ ] [MH-3993](https://j/browse/MH-3993) — 4K overlay crash: mx or libshmmedia? · Summer Chen · since 11-11
- [ ] This week's deploy — what goes in? · Erin Zhang · since 11-11

## Ruled

## Where things stand

- Prod 3 on 2.1.42
""")
    meet = {"key": "sync", "name": "MediaHub team sync", "time": "", "enabled": False}
    tz = datetime.datetime.now().astimezone().tzinfo
    before = V.meeting_close(vault, reports, facts, datetime.datetime(2026, 11, 11, 8, 0, tzinfo=tz), [meet])
    snap = json.load(open(os.path.join(reports, "ela", "meetings.json")))
    check("before the meeting nothing is closed; each ticket's status and assignee is kept",
          before == [] and snap["sync@2026-11-11"]["MH-3993"] == {"status": "Review", "assignee": "Fujian Fang"})
    snap["sync@2026-11-11"]["MH-3993"]["assignee"] = "Evan Li"           # as it was when the meeting began
    json.dump(snap, open(os.path.join(reports, "ela", "meetings.json"), "w"))
    during = V.meeting_close(vault, reports, facts, datetime.datetime(2026, 11, 11, 12, 0, tzinfo=tz), [meet])
    check("during the meeting nothing is closed", during == [])
    nxt = lambda m, d: datetime.date(2026, 11, 13)  # noqa: E731
    r = V.meeting_close(vault, reports, facts, datetime.datetime(2026, 11, 11, 18, 30, tzinfo=tz), [meet], nxt, jira="https://j")
    text = open(note).read()
    ruled = text.split("## Ruled")[1]
    check("after its end, outcomes under Ruled without a tick: split, assigned and commented, no change",
          "MH-3568](https://j/browse/MH-3568) — optional SCTE-35: owners? · the team · split into [MH-3997](https://j/browse/MH-3997) and [MH-3998](https://j/browse/MH-3998)" in ruled
          and "assigned to Fujian Fang; comment by Summer Chen" in ruled and "  - rule: passthrough keeps SCTE-35" in ruled
          and "Black frame to MQTT: who? · Gabriel Liu · no change: carried to the next meeting" in ruled
          and "This week's deploy — what goes in? · Erin Zhang · no ticket to read: carried to the next meeting" in ruled
          and len(r) == 1 and len(r[0]["outcome"]) == 2 and len(r[0]["rolled"]) == 2)
    raise_ = text.split("## To raise")[1].split("## Ruled")[0]
    check("the unchanged items roll to the next meeting, their age shown; the note is titled for it, no send line",
          'title: "MediaHub team sync · Fri 2026-11-13"' in text and 'date: "2026-11-13"' in text and "Black frame to MQTT: who? · Gabriel Liu · since 11-11" in raise_
          and "MH-3568" not in raise_ and "send" not in text and "not scheduled yet" not in text)
    check("a second pass the same evening closes nothing again",
          V.meeting_close(vault, reports, facts, datetime.datetime(2026, 11, 11, 19, 0, tzinfo=tz), [meet], nxt) == [])
    r2 = V.meeting_close(vault, reports, facts, datetime.datetime(2026, 11, 13, 19, 0, tzinfo=tz), [meet], nxt)
    check("no change at the second meeting: a team question is carried again, never dropped (ADR 0016)",
          len(r2[0]["rolled"]) == 2 and "Black frame to MQTT: who? · Gabriel Liu · since 11-11" in open(note).read().split("## Ruled")[0]
          and not os.path.exists(os.path.join(reports, "ela", "asks.json")))
    mt = V.Note("meetings/sync.md", "MediaHub team sync", V.split_front(open(note).read())[1], {"type": "meeting"}, [])
    got = V.meeting_outcomes([mt], ["MH-3568"], datetime.date(2026, 11, 13))
    check("a project's page shows what its meetings ruled on its keys",
          len(got) == 1 and got[0][0] == "2026-11-11" and "split into [MH-3997](https://j/browse/MH-3997)" in got[0][3])

# a note he or a session wrote by hand is input: close and roll leave it byte-identical (the sync note of 2026-11-12)
with tempfile.TemporaryDirectory() as t:
    vault, reports, facts = (os.path.join(t, x) for x in ("vault", "reports", "facts"))
    os.makedirs(os.path.join(vault, "meetings")); os.makedirs(os.path.join(facts, "jira", "issues")); os.makedirs(os.path.join(reports, "ela"))
    hand = os.path.join(vault, "meetings", "20261112-sync-eng-qa.md")
    body = ("---\ntitle: \"MediaHub team sync · Thu 2026-11-12\"\ntype: \"meeting\"\ndate: \"2026-11-12\"\nsource: \"vault\"\n---\n\n"
            "# MediaHub team sync · Thu 2026-11-12\n\n## 1. Close HTTP ports\n\n- [ ] Close order: A or B? · Robin Wu, Evan\n\n"
            "## If time allows \n\n- [ ] [MH-2564](https://j/browse/MH-2564) async: when? · Evan, Yulong Lu\n")
    open(hand, "w").write(body)
    tz = datetime.datetime.now().astimezone().tzinfo
    r = V.meeting_close(vault, reports, facts, datetime.datetime(2026, 11, 12, 19, 0, tzinfo=tz), [])
    V.meeting_roll(vault, datetime.date(2026, 12, 30))
    check("a hand-written meeting note is never rewritten by close or roll", r == [] and open(hand).read() == body)

# the lint reads a dated meeting note, his compact date form too, and asks for no Ruled before the meeting
with tempfile.TemporaryDirectory() as t:
    hand = ("---\ntitle: \"MediaHub team sync · Thu 2026-11-12\"\naliases: [\"MediaHub team sync · Thu 2026-11-12\"]\ntype: \"meeting\"\n"
            "date: \"2026-11-12\"\nsource: \"vault\"\n---\n\n# MediaHub team sync · Thu 2026-11-12\n\n## 1. Close HTTP ports\n\n"
            "- [ ] " + "a long question " * 12 + "· Robin Wu\n")
    rel = "meetings/20261112-sync-eng-qa.md"
    check("a dated note by hand: no spec line, no meeting line", V.spec_lint(rel, hand) == [] and V.meeting_lint(rel, hand) == [])
    check("its compact date is still checked against its date",
          V.spec_lint(rel, hand.replace('date: "2026-11-12"', 'date: "2026-11-13"')) == ["date 2026-11-13 but the file name says 2026-11-12"])

sys.exit(1 if failures else 0)
