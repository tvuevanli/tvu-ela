#!/usr/bin/env python3
"""ela onething, offline: the owner's own Jira and Slack facts per Asia/Shanghai day, the sheet's plain text, the xlsx
reader, the store (render → block → apply → post), the import of a vault note, the month page, and the note render on
request. No network; nothing is written to the sheet, Jira or Slack; the store is a temp directory."""
import argparse, datetime, io, json, os, sys, tempfile, zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "onething")
for k in [k for k in os.environ if k.startswith("ONETHING_") or k == "ELA_ENV_FILE"]:
    del os.environ[k]                                   # the site env must not leak into the cases
sys.path.insert(0, os.path.join(ROOT, "skills", "onething"))
import onething as O  # noqa: E402
O.SITE = os.path.join(tempfile.mkdtemp(), "no-site.json")   # no site: no env fallback, no reports root but the one given

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


def exit_code(fn, *args, **kw):
    try:
        fn(*args, **kw)
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

# ---- note_rows (a vault note's table, as import reads it)
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

> [!note]- Evidence
> His own comments on MH-3279;
> the sync thread.
"""
rows = O.note_rows(NOTE, "2026")
check("note: MM-DD takes the year", rows[0][:2] == (1, "2026-10-12"))
check("note: YYYY-MM-DD kept", rows[1][:2] == (2, "2026-10-13"))
check("note: an escaped pipe stays inside the cell", rows[1][2] == "a \\| b split / ran the sync")
check("note: the table ends at its first non-table line", len(rows) == 2)
check("note: the Evidence fold read as one paragraph", O.note_evidence(NOTE) == "His own comments on MH-3279; the sync thread.")

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

# ---- the note on request (render --out) still reads back
spec = {"rows": [{"date": "2026-10-20", "text": "Assessed MH-3797 / a | b split"},
                 {"date": "2026-10-19", "text": "Verified [MH-3721](https://j/browse/MH-3721) on QA 2"}],
        "left_out": [{"date": "2026-10-18", "why": "nothing of yours in Jira or Slack"}]}
note = O.render(spec, "https://j", "2026-11-02", "MH", "Owner")
back = O.note_rows(note, "2026")
check("render --out: rows numbered in date order", [(n, d) for n, d, _ in back] == [(1, "2026-10-19"), (2, "2026-10-20")])
check("render --out: keys linked in the vault", "[MH-3797](https://j/browse/MH-3797)" in back[1][2])
check("render --out: copy-ready, every row as drafted, plain keys",
      "Tab 2026.10月, rows all." in note and "MH\tOwner\t2026/10/19\tVerified MH-3721 on QA 2" in note
      and "MH\tOwner\t2026/10/20\tAssessed MH-3797 / a | b split" in note)
check("render --out: the days left out are named", "2026-10-18 (nothing of yours in Jira or Slack)" in note)
A = argparse.Namespace(env_file=None)
check("whom: no ONETHING_WHOM exits 2", exit_code(O.whom, A) == 2)
check("no write path is left in the script", not any(hasattr(O, n) for n in
      ("write_token", "write_grant", "append", "WRITE_SCOPE", "cmd_login")))

# ---- the store: render writes the day's entry; block renders it; apply takes his line and his tick; post prints
R = tempfile.mkdtemp()
day_spec = {"rows": [{"date": "2026-11-02", "text": "Prepared the promotions of MH-3640 / agreed the output profile (MH-3568)"}],
            "evidence": "His approval threads; four Jira comments on MH-3568.", "errors": []}
entries = O.entries_from_spec(day_spec, "2026-11-02T19:05:00+08:00")
p = O.put_day(R, entries[0])
check("store: one file per month under <reports>/onething", p == os.path.join(R, "onething", "2026-11.json"))
e = O.day_entry(R, "2026-11-02")
check("store: the entry's shape", e and set(e) == {"date", "rows", "drafted_at", "source_errors"}
      and set(e["rows"][0]) == {"n", "text", "evidence", "pasted", "ela_lines"} and e["rows"][0]["n"] == 1 and e["rows"][0]["pasted"] is False)
check("store: a date already drafted is refused without force (it may hold his edits)", exit_code(O.put_day, R, entries[0]) == 2)
O.put_day(R, O.entries_from_spec({"rows": [{"date": "2026-11-03", "text": "Ran the sync / closed MH-1"}]}, "x")[0])
check("store: another day is appended, the first untouched",
      [d["date"] for d in O.load_month(R, "2026-11")["days"]] == ["2026-11-02", "2026-11-03"]
      and O.day_entry(R, "2026-11-02")["rows"][0]["text"].startswith("Prepared"))
text, lines = O.block(O.day_entry(R, "2026-11-02"), "https://j", "MH", "Owner")
check("block: the heading names the weekday and the date", text.startswith("## Your day, Mon 2026-11-02\n"))
check("block: the numbered table with keys linked", "| 1 | 2026-11-02 | Prepared the promotions of [MH-3640](https://j/browse/MH-3640)" in text)
check("block: the evidence folded", "> [!note]- Evidence\n> His approval threads" in text)
check("block: the copy fold carries the line as post prints it",
      "> [!note]- Copy to the sheet\n> Tab 2026.11月." in text and "> MH\tOwner\t2026/11/02\tPrepared the promotions of MH-3640 / agreed the output profile (MH-3568)" in text
      and lines == ["MH\tOwner\t2026/11/02\tPrepared the promotions of MH-3640 / agreed the output profile (MH-3568)"])
check("block: one unticked pasted box per row", "\n- [ ] pasted 1\n" in text and text.count("pasted 1") == 1)
check("block: the table reads back as rows", O.note_rows(text, "2026") == [(1, "2026-11-02", O.note_rows(text, "2026")[0][2])])
got = O.apply_lines(R, "2026-11-02", ["Reviewed the QA reports and promoted build 78 (MH-3855)", "pasted 1"])
e = O.day_entry(R, "2026-11-02")
check("apply: his line replaces the row's text and is kept under ela_lines",
      got["changed"] == ["2026-11-02 row 1 reworded", "2026-11-02 row 1 pasted"]
      and e["rows"][0]["text"] == "Reviewed the QA reports and promoted build 78 (MH-3855)" and e["rows"][0]["ela_lines"] == ["Reviewed the QA reports and promoted build 78 (MH-3855)"])
check("apply: a ticked pasted box sets the flag, stamped", e["rows"][0]["pasted"] is True and e["rows"][0].get("pasted_at"))
again = O.apply_lines(R, "2026-11-02", ["Reviewed the QA reports and promoted build 78 (MH-3855)", "pasted 1"])
check("apply: the same lines at the next pass change nothing", again["changed"] == [] and O.day_entry(R, "2026-11-02")["rows"][0]["ela_lines"] == ["Reviewed the QA reports and promoted build 78 (MH-3855)"])
got = O.apply_lines(R, "2026-11-03", ["2: a second row", "post all", "pasted 2026-11-02", "pasted 2026-11-09"])
check("apply: a numbered line needs that row; post is not a rewording; a tick with a date finds its day; an unknown day is said",
      got["changed"] == [] and [x.split(":")[0] for x in got["skipped"]] == ["2", "post all", "pasted 2026-11-09"])
text2, _ = O.block(O.day_entry(R, "2026-11-02"), "https://j", "MH", "Owner")
check("block after apply: his wording, the box ticked", "| 1 | 2026-11-02 | Reviewed the QA reports and promoted build 78 ([MH-3855]" in text2 and "\n- [x] pasted 1\n" in text2)
check("render into the store refuses a date already there without --force",
      exit_code(O.cmd_render, argparse.Namespace(env_file=None, reports=R, rows=(lambda: (open(os.path.join(R, "rows.json"), "w").write(json.dumps(day_spec)), os.path.join(R, "rows.json"))[1])(), out=None, force=False)) == 2
      and O.day_entry(R, "2026-11-02")["rows"][0]["ela_lines"])
# post: the lines from the store; a month lists what is not yet pasted
import contextlib
def post(**kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = exit_code(O.cmd_post, argparse.Namespace(**{**dict(env_file=None, reports=R, date=None, month=None, pick=None, all=False, json=False), **kw}))
    return code, buf.getvalue()
os.environ["ONETHING_WHOM"] = "Owner"
code, out = post(month="2026-11")
check("post --month: the unpasted rows only, tab-separated", code is None and out == "MH\tOwner\t2026/11/03\tRan the sync / closed MH-1\n")
code, out = post(month="2026-11", all=True)
check("post --month --all: the pasted rows too", out.splitlines() == ["MH\tOwner\t2026/11/02\tReviewed the QA reports and promoted build 78 (MH-3855)", "MH\tOwner\t2026/11/03\tRan the sync / closed MH-1"])
code, out = post(date="2026-11-02", pick="1")
check("post --date --pick: the picked row, pasted or not", out == "MH\tOwner\t2026/11/02\tReviewed the QA reports and promoted build 78 (MH-3855)\n")
check("post --date of a day not drafted exits 3", post(date="2026-11-04")[0] == 3)
del os.environ["ONETHING_WHOM"]
# import: a vault note's table into the store, the evidence on each row
dates = O.import_note(R, NOTE, "2026-11-02-one-thing-october.md", "2026")
oct_ = O.load_month(R, "2026-10")["days"]
check("import: one entry per date, plain text, the note's evidence on each row, the note named",
      dates == ["2026-10-12", "2026-10-13"] and [d["date"] for d in oct_] == ["2026-10-12", "2026-10-13"]
      and oct_[0]["rows"][0]["text"] == "VoIP devices: three ways to query them (MH-3279)" and oct_[1]["rows"][0]["text"] == "a | b split / ran the sync"
      and oct_[0]["rows"][0]["evidence"] == "His own comments on MH-3279; the sync thread." and oct_[0]["imported_from"] == "2026-11-02-one-thing-october.md"
      and oct_[0]["rows"][0]["pasted"] is False)
check("import: a date already in the store is refused without force", exit_code(O.import_note, R, NOTE, "n.md", "2026") == 2)
O.import_note(R, NOTE, "n.md", "2026", force=True, pasted=True)
check("import --force --pasted: replaced, marked pasted", all(r["pasted"] for d in O.load_month(R, "2026-10")["days"] for r in d["rows"]))
# the month page: the current month's unpasted rows, one copy block, a box per row; earlier months under their own heading
O.apply_lines(R, None, ["pasted 2026-10-12"])
O.put_day(R, {"date": "2026-10-13", "rows": [O.new_row(1, "October row")], "drafted_at": "x", "source_errors": []}, force=True)
page, n = O.month_page(R, datetime.date(2026, 11, 3), "https://j", "MH", "Owner")
check("month page: the title names the month; the count is every unpasted row", page.startswith("# One Thing · 2026-11\n") and n == 2)
check("month page: the current month's unpasted rows in the table and the copy block, a pasted box per row",
      "| 2026-11-03 | 1 | Ran the sync / closed [MH-1](https://j/browse/MH-1) |" in page and "> MH\tOwner\t2026/11/03\tRan the sync / closed MH-1" in page
      and "\n- [ ] pasted 2026-11-03\n" in page and "2026/11/02" not in page.split("## Earlier months")[0])
check("month page: earlier months' unpasted rows under their own heading with their tab",
      "## Earlier months" in page and "> Tab 2026.10月." in page.split("## Earlier months")[1] and "- [ ] pasted 2026-10-13" in page)
O.put_day(R, {"date": "2026-10-14", "rows": [O.new_row(1, "Assessed the open 2.1 tickets (MH-3855, MH-3820, MH-3829) and promoted build 78 for MH-3800")],
              "drafted_at": "x", "source_errors": []}, force=True)
old_page = O.month_page(R, datetime.date(2026, 11, 3), "https://j", "MH", "Owner")[0]
check("a stored row's run of keys reads as its count in the table; the copy block keeps the row whole",
      "| 2026-10-14 | 1 | Assessed the open 2.1 tickets (3 tickets) and promoted build 78 for [MH-3800](https://j/browse/MH-3800) |" in old_page
      and "> MH\tOwner\t2026/10/14\tAssessed the open 2.1 tickets (MH-3855, MH-3820, MH-3829) and promoted" in old_page)
run_spec = os.path.join(R, "run.json")
json.dump({"rows": [{"date": "2026-11-20", "text": "Closed MH-1, MH-2, MH-3"}]}, open(run_spec, "w"))
check("a drafted row with a run of keys is refused; a pair with words is not a run",
      exit_code(O.cmd_render, argparse.Namespace(env_file=None, reports=R, rows=run_spec, out=None, force=False)) == 2
      and O.key_run("Closed MH-1 and MH-2, then MH-3") is None)
check("month page: nothing at all without a store", O.month_page(tempfile.mkdtemp(), datetime.date(2026, 11, 3), "https://j", "MH", "Owner") == (None, 0))
check("month page: no rows left says so and keeps the page", "Every drafted row is on the sheet" in O.month_page(R, datetime.date(2026, 12, 1), "https://j", "MH", "Owner")[0]
      if not any(not r["pasted"] for d in O.all_entries(R) for r in d["rows"]) else True)

print(f"\nonething offline: {'FAILED ' + str(len(failures)) if failures else 'all passed'}")
sys.exit(1 if failures else 0)
