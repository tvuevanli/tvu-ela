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
check("a status cell leads with its mark, only for the exact word",
      [r[3]["text"] for r in t.get("rows", [])[1:]] == ["✅ checked", "checked (rate inferred)", "⬜ NOT checked"])
check("a long column wraps, a short one does not", [c["is_wrapped"] for c in t.get("column_settings", [])] == [False, True, False, False])
check("a bordered table needs no divider", len((S.table_block("| a | b |\n| 1 | 2 |") or {}).get("rows", [])) == 2)
check("a psql divider counts", len((S.table_block("a | b\n---+---\n1 | 2") or {}).get("rows", [])) == 2)
check("a data row of dashes is kept, only the header's divider dropped",
      [[c["text"] for c in r] for r in (S.table_block("a | b\n---|---\n- | -\n1 | 2") or {}).get("rows", [])[1:]] == [["-", "-"], ["1", "2"]])
long = "x" * 7000
tb = S.text_blocks("head\n" + long + "\ntail")
check("a line over a section's limit is split, not cut",
      all(len(x["text"]["text"]) <= 3000 for x in tb) and "".join(x["text"]["text"] for x in tb).replace("\n", "") == "head" + long + "tail",
      [len(x["text"]["text"]) for x in tb])
check("a divider row is dropped", len(S.table_block("a | b\n---|---\n1 | 2").get("rows")) == 2)
for name, body in (("a log excerpt", "```\nTraceback: x | y\n---|---\n  line two\n```"), ("one row", "```\n| only | one |\n```"),
                   ("over 100 rows", "```\na | b\n---|---\n" + "a | b\n" * 100 + "```"), ("past 10,000 characters", "```\na | b\n---|---\n" + ("x" * 6000 + " | y\n") * 2 + "```"),
                   ("no fence", "a | b\n1 | 2"), ("a shell pipeline", "```\nps aux | grep copier\nls | wc -l\n```")):
    check(f"{name} stays as written", S.with_table(body) is None)
# send: only Slack's own refusal resends without the table; a lost answer is never resent (it may have posted)
import io, json  # noqa: E402
calls = []
def fake(answers):
    def urlopen(req, timeout=None):
        calls.append(json.loads(req.data))
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return io.BytesIO(json.dumps(a).encode())
    return urlopen
S.urllib.request.urlopen = fake([{"ok": False, "error": "invalid_blocks"}, {"ok": True, "ts": "1"}])
d = S.send("t", {"channel": "C", "text": T})
check("a refused table is resent as the fence", d.get("ok") and len(calls) == 2 and "blocks" in calls[0] and "blocks" not in calls[1], calls)
calls.clear()
S.urllib.request.urlopen = fake([TimeoutError("timed out"), {"ok": True, "ts": "2"}])
try:
    S.send("t", {"channel": "C", "text": T}); code = None
except SystemExit as e:
    code = e.code
check("a timeout is not resent", code == S.EX_REMOTE and len(calls) == 1, (code, len(calls)))
sys.exit(1 if failures else 0)
