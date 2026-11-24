#!/usr/bin/env python3
"""A fenced `|` table in a Slack post as Slack's table block, offline: header bold, status marked, long columns wrapped;
a fence that is no table, or past Slack's limits, stays a fence. No token is read and nothing is called."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "slack"))
import slack as S  # noqa: E402

failures = []
def check(name, cond, got=None):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)
        if got is not None:
            print("     ", got)

T = ("Before the table.\n```\nUTC                  | event                                         | source      | status\n"
     "---------------------|-----------------------------------------------|-------------|-------\n"
     "2026-11-23T06:00:28Z | copier SendByte=1978218547004, Status running | es_search   | checked\n"
     "2026-11-24 06:40     | copier sends ~9 B/s over the whole day so far | two samples | checked (rate inferred)\n"
     "any time             | copier container log                          | obs_logs    | NOT checked\n```\n• after")
b = S.with_table(T)
check("text, table, text", [x["type"] for x in b or []] == ["section", "table", "section"], b)
t = (b or [{}, {}])[1]
check("the header is bold", t.get("rows", [[{}]])[0][0].get("elements", [{}])[0].get("elements", [{}])[0].get("style") == {"bold": True})
check("a status cell leads with its mark, worst word first",
      [r[3]["text"] for r in t.get("rows", [])[1:]] == ["✅ checked", "✅ checked (rate inferred)", "⬜ NOT checked"])
check("a long column wraps, a short one does not", [c["is_wrapped"] for c in t.get("column_settings", [])] == [False, True, False, False])
check("a bordered table needs no divider", len((S.table_block("| a | b |\n| 1 | 2 |") or {}).get("rows", [])) == 2)
check("a psql divider counts", len((S.table_block("a | b\n---+---\n1 | 2") or {}).get("rows", [])) == 2)
check("a divider row is dropped", len(S.table_block("a | b\n---|---\n1 | 2").get("rows")) == 2)
for name, body in (("a log excerpt", "```\nTraceback: x | y\n---|---\n  line two\n```"), ("one row", "```\n| only | one |\n```"),
                   ("over 100 rows", "```\na | b\n---|---\n" + "a | b\n" * 100 + "```"), ("past 10,000 characters", "```\na | b\n---|---\n" + ("x" * 6000 + " | y\n") * 2 + "```"),
                   ("no fence", "a | b\n1 | 2"), ("a shell pipeline", "```\nps aux | grep copier\nls | wc -l\n```")):
    check(f"{name} stays as written", S.with_table(body) is None)
sys.exit(1 if failures else 0)
