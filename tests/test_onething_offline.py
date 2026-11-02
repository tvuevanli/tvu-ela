#!/usr/bin/env python3
"""ela onething, offline: the owner's own Jira and Slack facts per Asia/Shanghai day, the note's rows and the pick, the
sheet's plain text, the xlsx reader, the render → read round trip, and the lines post writes into the note for the owner
to copy. No network; nothing is written to the sheet, Jira or Slack."""
import argparse, datetime, io, json, os, sys, tempfile, zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "onething")
for k in [k for k in os.environ if k.startswith("ONETHING_") or k == "ELA_ENV_FILE"]:
    del os.environ[k]                                   # the site env must not leak into the cases
sys.path.insert(0, os.path.join(ROOT, "skills", "onething"))
import onething as O  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


def exit_code(fn, *args):
    try:
        fn(*args)
    except SystemExit as e:
        return e.code
    return None


def load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


D19 = datetime.date(2026, 10, 19)

# ---- jira_facts
jf = O.jira_facts(load("jira-changes.json"), "The Owner", D19, D19)
day = {t["key"]: t for t in jf.get("2026-10-19", [])}
check("jira: a -0700 stamp of 10-18 20:17 lands on 10-19 in Asia/Shanghai",
      "status: Open → In Progress" in (day.get("MH-101") or {}).get("moves", []))
check("jira: nothing of the owner's falls on 10-18", "2026-10-18" not in jf)
check("jira: bookkeeping fields (labels, Fixed In) are not work",
      not any(m.startswith(("labels", "Fixed In")) for m in day["MH-101"]["moves"]))
check("jira: only the owner's own comments", day["MH-101"]["comments"] == [
      "Assessed the 2.1 impact: JPEG-XS is blocked; the fix scope is the copier's parser."])
check("jira: another person's move is left out", not any("assignee" in m for m in day["MH-101"]["moves"]))
check("jira: a move Helm wrote under the owner's account, and its comment, are left out", "MH-102" not in day)
check("jira: a ticket only others touched is left out", "MH-103" not in day)
check("jira: a day outside the window is cut", O.jira_facts(load("jira-changes.json"), "The Owner",
      datetime.date(2026, 10, 20), datetime.date(2026, 10, 20)) == {})

# ---- slack_facts
sf = O.slack_facts(load("slack-search.json"), "The Owner", D19, D19)
msgs = sf.get("2026-10-19", [])
check("slack: a reply that is also a hit is counted once", [m["ts"] for m in msgs].count("1792375800.000200") == 1)
check("slack: the owner's top-level message and reply, nobody else's", len(msgs) == 2)
check("slack: in time order", [m["ts"] for m in msgs] == sorted((m["ts"] for m in msgs), key=float))

# ---- note_rows
NOTE = """---
date: "2026-11-02"
---
## Waiting for your word

| # | date | Content Overview (edit freely) |
|---|---|---|
| 1 | 10-12 | VoIP devices: three ways to query them ([MH-3279](https://jira.example/browse/MH-3279)) |
| 2 | 2026-10-13 | a \\| b split / ran the sync |

After the table.
| 9 | 10-30 | a table later in the note is not a row |
"""
rows = O.note_rows(NOTE, "2026")
check("note: MM-DD takes the year", rows[0][:2] == (1, "2026-10-12"))
check("note: YYYY-MM-DD kept", rows[1][:2] == (2, "2026-10-13"))
check("note: an escaped pipe stays inside the cell", rows[1][2] == "a \\| b split / ran the sync")
check("note: the table ends at its first non-table line", len(rows) == 2)

# ---- pick
four = [(n, f"2026-10-1{n}", f"row {n}") for n in range(1, 5)]
nums = lambda spec: [r[0] for r in O.pick(four, spec)]   # noqa: E731
check('pick: "1, 3"', nums("1, 3") == [1, 3])
check('pick: "1 & 3"', nums("1 & 3") == [1, 3])
check('pick: "2-4"', nums("2-4") == [2, 3, 4])
check('pick: "all"', nums("all") == [1, 2, 3, 4])
check("pick: an unknown row exits 3", exit_code(O.pick, four, "1, 7") == 3)
check("pick: a word that is not a number exits 2", exit_code(O.pick, four, "first") == 2)

# ---- plain and link_keys
check("plain: Markdown links to their text", O.plain("fix ([MH-1](https://j/browse/MH-1))") == "fix (MH-1)")
check("plain: wiki links to their name", O.plain("see [[2026-11-02-x|the plan]] and [[note]]") == "see the plan and note")
check("plain: table escapes undone", O.plain("a \\| b") == "a | b")
linked = O.link_keys("MH-1 and [MH-2](https://j/browse/MH-2)", "https://j")
check("link_keys: a bare key is linked", "[MH-1](https://j/browse/MH-1)" in linked)
check("link_keys: a linked key is not linked twice", linked.count("MH-2](") == 1 and "[[MH-2]" not in linked)

# ---- cell_date
check("cell_date: serial 46305 is 2026-10-10", O.cell_date("46305") == "2026-10-10")
check("cell_date: 2026/10/12 text", O.cell_date("2026/10/12") == "2026-10-12")


# ---- xlsx_rows on a tiny in-memory workbook
def tiny_xlsx():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook><sheets><sheet name="2026.9月" sheetId="1" r:id="rId1"/>'
                   '<sheet name="2026.10月" sheetId="2" r:id="rId2"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships>'
                   '<Relationship Id="rId1" Type="ws" Target="worksheets/sheet1.xml"/>'
                   '<Relationship Id="rId2" Type="ws" Target="/xl/worksheets/sheet2.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", "<sst><si><t>Project</t></si><si><t>Whom</t></si><si><t>MH</t></si>"
                   "<si><t>Owner</t></si><si><r><t>fixed </t></r><r><t>A &amp; B</t></r></si></sst>")
        z.writestr("xl/worksheets/sheet1.xml", "<worksheet><sheetData/></worksheet>")
        z.writestr("xl/worksheets/sheet2.xml", '<worksheet><sheetData>'
                   '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                   '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2" t="s"><v>3</v></c><c r="C2" s="1"><v>46305</v></c>'
                   '<c r="D2" t="s"><v>4</v></c><c r="E2" s="2"/></row>'
                   '<row r="3"><c r="A3" t="inlineStr"><is><t>MH</t></is></c><c r="D3" t="inlineStr"><is><t>inline</t></is></c></row>'
                   '</sheetData></worksheet>')
    return b.getvalue()


xr = O.xlsx_rows(tiny_xlsx(), "2026.10月")
check("xlsx: the named tab through an absolute relationship target", xr is not None and len(xr) == 3)
check("xlsx: shared strings, rich text runs joined and unescaped", xr[1].get("D") == "fixed A & B")
check("xlsx: a serial date read as its number", O.cell_date(xr[1].get("C")) == "2026-10-10")
check("xlsx: an empty self-closed cell is absent", "E" not in xr[1])
check("xlsx: an inline string", xr[2].get("D") == "inline")
check("xlsx: an absent tab is None", O.xlsx_rows(tiny_xlsx(), "2026.11月") is None)
check("tab_name: 2026-10 → 2026.10月", O.tab_name("2026-10") == "2026.10月")

# ---- render → note_rows round trip
spec = {"rows": [{"date": "2026-10-20", "text": "Assessed MH-3797 / a | b split"},
                 {"date": "2026-10-19", "text": "Verified [MH-3721](https://j/browse/MH-3721) on QA 2"}],
        "left_out": [{"date": "2026-10-18", "why": "nothing of yours in Jira or Slack"}]}
note = O.render(spec, "https://j", "2026-11-02")
back = O.note_rows(note, "2026")
check("render: rows numbered in date order", [(n, d) for n, d, _ in back] == [(1, "2026-10-19"), (2, "2026-10-20")])
check("render: keys linked in the vault", "[MH-3797](https://j/browse/MH-3797)" in back[1][2])
check("render → plain: the sheet gets the text as drafted", O.plain(back[1][2]) == "Assessed MH-3797 / a | b split"
      and O.plain(back[0][2]) == "Verified MH-3721 on QA 2")
check("render: the days left out are named", "2026-10-18 (nothing of yours in Jira or Slack)" in note)
check("render: the tab is named", "tab 2026.10月" in note)

# ---- post: the lines he copies, written into the note; nothing goes to Google
A = argparse.Namespace(env_file=None)
check("whom: no ONETHING_WHOM exits 2", exit_code(O.whom, A) == 2)
check("no write path is left in the script", not any(hasattr(O, n) for n in
      ("write_token", "write_grant", "append", "WRITE_SCOPE", "cmd_login")))
lines = O.copy_lines("MH", "Owner", [(1, "2026-10-19", O.plain(back[0][2]))])
check("copy: Project, Whom, YYYY/MM/DD, plain content, tab-separated",
      lines == ["MH\tOwner\t2026/10/19\tVerified MH-3721 on QA 2"])
once = O.copy_section(note, ["2026.10月"], "1, 2", lines)
check("copy: a section with the tab and the rows above a fenced block",
      "## Copy to the sheet\n\nTab 2026.10月, rows 1, 2." in once and "```\nMH\tOwner\t2026/10/19\t" in once)
twice = O.copy_section(once, ["2026.10月"], "2", ["MH\tOwner\t2026/10/20\tsecond"])
check("copy: a section already there is replaced, not added", twice.count("## Copy to the sheet") == 1
      and "second" in twice and "2026/10/19" not in twice.split("## Copy to the sheet")[1])
mid = O.copy_section(note + "\n## Copy to the sheet\n\nold\n\n## Later\nkept\n", ["2026.10月"], "1", ["new"])
check("copy: a heading after the section is kept", mid.endswith("## Later\nkept\n") and "old" not in mid)
check("copy: the table still reads after the section is written", O.note_rows(twice, "2026") == back)
check("progress: set to rows N ready to copy",
      'progress: "2026-11-02 10:00: rows 1 ready to copy"' in O.set_progress(note, "2026-11-02 10:00: rows 1 ready to copy"))

print(f"\nonething offline: {'FAILED ' + str(len(failures)) if failures else 'all passed'}")
sys.exit(1 if failures else 0)
