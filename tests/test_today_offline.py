#!/usr/bin/env python3
"""today.md, offline: at most three asks, each gone after three working mornings unanswered and written once to the
dropped page, back only when its evidence changes; an ask's identity is the tickets it acts on, whatever its form."""
import datetime, os, sys, types
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "vault"))
import vault as V  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

D = datetime.date
MON, TUE, WED, THU, FRI, NMON = D(2026, 11, 9), D(2026, 11, 10), D(2026, 11, 11), D(2026, 11, 12), D(2026, 11, 13), D(2026, 11, 16)
check("working mornings skip the weekend", V.working_mornings(FRI, NMON) == 2 and V.working_mornings(MON, FRI) == 5)
check("an ask first seen Monday is gone Thursday", V.drop_day(MON, MON) == THU and V.drop_day(THU, FRI) == NMON + datetime.timedelta(days=1))
check("one ticket is one ask, drafted as a comment or as an assignment",
      V.action_id({"kind": "comment", "command": "ela jira comment MH-2406 --text 'see MH-3962'"})
      == V.action_id({"kind": "assign", "command": "ela jira assign MH-2406 --assignee x"}) == "keys:MH-2406")

def act(n, key, day, ev="e", **kw):
    return dict({"n": n, "tier": 3, "command": f"ela jira comment {key}", "text": f"comment {key}", "evidence": ev, "day": day.isoformat()}, **kw)

week = [act(1, "MH-1", MON), act(1, "MH-1", THU), act(2, "MH-2", THU), act(3, "MH-3", THU), act(4, "MH-4", THU),
        act(5, "MH-5", THU, applied="x"), act(6, "MH-6", THU, tier=2), act(7, "MH-7", THU, send_box=True)]
cands = V.ask_candidates(THU, week, [])
check("candidates: today's tier-3 drafts not done, in order; first seen backfilled from the week",
      [c["id"] for c in cands] == ["keys:MH-1", "keys:MH-2", "keys:MH-3", "keys:MH-4"] and cands[0]["first"] == MON.isoformat())
shown, more, dropped, st = V.settle_asks({}, cands, THU)
check("an ask is aged from the first morning it is shown, not from its first draft",
      not dropped and [c["id"] for c in shown] == ["keys:MH-1", "keys:MH-2", "keys:MH-3"] and st["keys:MH-1"]["first"] == THU.isoformat())
check("below the cap: not stored, not aged", more == 1 and "keys:MH-4" not in st)
old = {"keys:MH-1": {"first": MON.isoformat(), "text": "x", "sig": "e", "dropped": None}}
shown1, _, dropped1, st1 = V.settle_asks(old, cands, THU)
check("shown since Monday, it drops on Thursday, once, into the state; the next one moves up",
      [c["id"] for c in dropped1] == ["keys:MH-1"] and st1["keys:MH-1"]["dropped"] == THU.isoformat()
      and [c["id"] for c in shown1] == ["keys:MH-2", "keys:MH-3", "keys:MH-4"])
shown2, _, dropped2, st2 = V.settle_asks(st1, V.ask_candidates(FRI, [dict(a, day=FRI.isoformat()) for a in week if a["day"] == THU.isoformat()], []), FRI)
check("a dropped ask stays off and is not dropped twice", "keys:MH-1" not in [c["id"] for c in shown2] and not dropped2)
back = V.ask_candidates(FRI, [act(1, "MH-1", FRI, ev="a new comment")], [])
shown3, _, _, st3 = V.settle_asks(st2, back, FRI)
check("new evidence brings it back, counted from today", [c["id"] for c in shown3] == ["keys:MH-1"] and st3["keys:MH-1"]["first"] == FRI.isoformat()
      and not st3["keys:MH-1"]["dropped"])
many = [act(i, f"MH-{i}", THU) for i in range(10, 16)]
s4, more4, _, _ = V.settle_asks({}, V.ask_candidates(THU, many, []), THU)
check("six fresh asks: three shown", len(s4) == 3 and more4 == 3)
page = V.today_page(THU, [], {"actions": many}, s4, more4, 1)
above = page.split("\n---\n")[0]
check("the page: three boxes with what happens if he does nothing, no count of the rest, within the word cap",
      above.count("- [ ] apply ") == 3 and above.count("*if not: nothing; gone ") == 3 and "more wait" not in above
      and len(V.plain(above).split()) <= V.TODAY_WORDS and "[[reference/dropped|dropped asks]] (1)" in page)
dp = V.dropped_page(st1)
check("the dropped page lists each drop once with its dates", dp.count("comment MH-1") == 1 and f"{THU} · comment MH-1 · asked since {MON}" in dp)
# the record of 2026-11-11: MH-3993 drafted as a comment and an assignment, one ask cut mid-phrase
two = [dict(act(2, "MH-3993", WED), text="MH-3993: hand the 4K WebRenderer crash to Fujian Fang with Summer Chen's findings and three checks on box .46"),
       dict(act(3, "MH-3993", WED), command="ela jira assign MH-3993 --assignee x", text="MH-3993: assign to Fujian Fang")]
c2 = V.ask_candidates(WED, two, [])
check("two writes on one ticket are one ask, its box naming both", len(c2) == 1 and c2[0]["box"] == "apply 2, 3" and c2[0]["ns"] == [2, 3])
p2 = V.today_page(WED, [], {}, c2)
check("the ask is the whole sentence, never cut",
      "- [ ] apply 2, 3 — MH-3993: hand the 4K WebRenderer crash to Fujian Fang with Summer Chen's findings and three checks on box .46." in p2
      and "…" not in p2.split("## Today")[0])
mp = "\n".join(["### 2. x", "- [ ] apply 2 — a", "- [ ] I handled it myself — not apply 2", "> [!note]- 6 more", "> ### 3. y",
                  "> - [ ] apply 4 — b", "> - [ ] I handled it myself — not apply 4", "> - [x] apply 5 — c · applied 09:12"])
q = V.also_noticed(mp, {4})
check("the morning page: a box only on the asks shown; the rest plain, under Also noticed",
      "- [ ] apply 2 — a" in q and "> - b" in q and "not apply 4" not in q and "> [!note]- Also noticed" in q and "[x] apply 5" in q)
check("Home is a pointer to today until its date", "[[today]]" in V.home_pointer() and V.HOME_POINTER_UNTIL.isoformat() in V.home_pointer())
check("a fact is a whole short sentence or nothing, never cut",
      V.short_sentence("Prod 3 took 2.1 on 11-09. The rest is long.") == "Prod 3 took 2.1 on 11-09."
      and V.short_sentence("x" * 200 + ". Short one.") == "Short one." and V.short_sentence("y" * 200 + ".") is None)
check("an ask that fits is whole; a long one is its first clause when that fits, never an ellipsis",
      V.ask_words("MH-1: set Fixed In a@1; b@2 (one image)") == "MH-1: set Fixed In a@1; b@2 (one image)."
      and V.ask_words("MH-1: " + "w " * 25 + "; tail") == "MH-1: " + " ".join(["w"] * 25) + " ; tail."
      and V.ask_words("MH-1: say yes; " + "w " * 25) == "MH-1: say yes.")
mt = types.SimpleNamespace(path="meetings/sync.md", title="MediaHub team sync · Thu 2026-11-12", props={"type": "meeting", "date": "2026-11-12"}, body="")
pg = V.today_page(THU, [mt], {"meetings": [{"key": "scrum", "time": "10:00", "name": "Scrum"}]})
check("the day's meeting note is listed under Today by its title", "- [[meetings/sync|MediaHub team sync · Thu 2026-11-12]]" in pg
      and "Scrum" not in pg)
check("a note's ask keeps its words outside the link", "→ [[to-read/x|the note]]" in V.today_page(THU, [], {}, [
      {"id": "note:x", "text": "MH-1 · a plan", "link": "to-read/x", "first": THU.isoformat()}]))
check("a send box (the Dev and QA day drafts) is not on today.md: those are made on demand",
      "send 9" not in V.today_page(THU, [], {"actions": [{"n": 9, "tier": 3, "send_box": True, "rule": "dev-today", "day": THU.isoformat(), "text": "Dev today"}]}))
print("today: all offline checks passed" if not failures else f"today: {len(failures)} failed")
sys.exit(1 if failures else 0)
