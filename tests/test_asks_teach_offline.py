#!/usr/bin/env python3
"""Asks that teach ela, offline (plan ela/2026-11-26-plan-ela-runs-on-its-own-asks-teach-it, round 2): the letter
grammar keeps his words as the note; a letter against ela's recommendation with no words waits for a cause, and the
next ask of its kind says so; an ask that expires says where it still lives; the board watch's topics carry kind and
confidence, are answerable on ela/watch.md, and keep their corrections with a cause; mention keeps its own; one reader
returns them as precedents; a fact he gave is not asked again. Every store is a temp dir; nothing reaches Jira or
Slack."""
import datetime, json, os, re, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ("vault", "watch", "mention", "asks", "dry"):
    sys.path.insert(0, os.path.join(ROOT, "skills", d))
FACTS_DIR = tempfile.mkdtemp()
os.environ["ELA_ASKS_FACTS_DIR"] = FACTS_DIR              # the site's fact file, in a temp dir
import vault as V  # noqa: E402
import watch as W  # noqa: E402
import mention as MN  # noqa: E402
import asks as A  # noqa: E402

fails = []


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


THU = datetime.date(2026, 11, 26)
NOW = datetime.datetime(2026, 11, 26, 9, 0, tzinfo=W.TZ)

# ── the letter grammar ─────────────────────────────────────────────────────────────────────────────────────────
def letter(line):
    m = V.LETTER_LINE.match(line)
    return None if not m else (m.group(1), m.group(2).upper(), (m.group(3) or m.group(4) or "").strip() or None)

check("a bare letter, a slot and a letter, and either with words after a separator or `because`",
      letter("A") == (None, "A", None) and letter("2 B") == ("2", "B", None)
      and letter("2 B because the owner is away") == ("2", "B", "because the owner is away")
      and letter("B — wrong lane") == (None, "B", "wrong lane") and letter("C: not his") == (None, "C", "not his"))
check("an ordinary line that starts with a capital A is not a letter",
      letter("Apply this to MH-1") is None and letter("A better way is to wait") is None and letter("as discussed") is None)

state = {"keys:MH-10": {"slot": 1, "options": {"A": "apply 10", "B": "drop"}, "rec": "A", "domain": "action", "kind": "ruling",
                        "sig": "e", "first": THU.isoformat(), "text": "comment MH-10"},
         "keys:MH-11": {"slot": 2, "options": {"A": "apply 11", "B": "drop"}, "rec": "A", "domain": "action", "kind": "ruling",
                        "sig": "e", "first": THU.isoformat(), "text": "comment MH-11"},
         "note:x.md": {"slot": 3, "options": {"A": None, "B": "drop"}, "domain": "note", "kind": "ruling", "sig": "e",
                       "first": THU.isoformat(), "text": "x"}}
page = "\n".join(["## Needs you", "", "1. *ruling* · comment MH-10", "    - [ ] A (recommended): apply as drafted",
                  "    - [x] B: drop it", "    the comment repeats what QA already said", "",
                  "2. *ruling* · comment MH-11", "    - [ ] A (recommended): apply as drafted", "    - [ ] B: drop it",
                  "ela: B", "", "3. *ruling* · x", "    - [ ] A (recommended): answer in the note", "    - [ ] B: drop it from today",
                  "ela: 3 B because it is settled", ""])
got = {x["slot"]: (x["letter"], x["note"]) for x in V.today_letters(page, state)}
check("a ticked option keeps the plain line under it as its note; `ela: 3 B because …` keeps the words",
      got == {1: ("B", "the comment repeats what QA already said"), 2: ("B", None), 3: ("B", "because it is settled")})

with tempfile.TemporaryDirectory() as vd:
    open(os.path.join(vd, "today.md"), "w").write(page)
    st = json.loads(json.dumps(state))
    V.settle_letters(vd, vd, st, THU, dry_run=True)
    a1, a2, a3 = (st[k]["answered"] for k in ("keys:MH-10", "keys:MH-11", "note:x.md"))
    check("a wrong letter with a note keeps the note; without one it waits for a cause; a note ask has no recommendation",
          a1.get("note", "").startswith("the comment repeats") and "cause" not in a1
          and a2.get("cause") == "waiting" and "cause" not in a3)
    check("the waiting answer is found by its kind", V.waiting_cause(st, "action")[0] == "keys:MH-11"
          and V.waiting_cause(st, "note") == (None, None))
    # the next morning: an ask of the same kind says, in one line, that an answer waits for its cause
    nxt = [{"id": "keys:MH-12", "text": "comment MH-12", "first": THU.isoformat(), "ns": [12], "sig": "f", "reason": "MH-12 asked twice"},
           {"id": "keys:MH-13", "text": "comment MH-13", "first": THU.isoformat(), "ns": [13], "sig": "g", "reason": "e"}]
    tp = V.today_page(THU, [], {}, nxt, asks_state=st)
    asks = tp.split("## Needs you")[1].split("## Today")[0]
    check("the next ask of that kind says it once; ela's reason is in option A; the ask names its kind",
          asks.count("waits for a cause: write `ela: because …` under this ask") == 1 and "Your B on “comment MH-11”" in asks
          and "apply as drafted — ela's reason: MH-12 asked twice" in asks and "1. *ruling* · comment MH-12" in asks)
    st["keys:MH-12"] = {"slot": 1, "options": {"A": "apply 12", "B": "drop"}, "rec": "A", "domain": "action"}
    open(os.path.join(vd, "today.md"), "w").write(tp.replace("under this ask.", "under this ask.\nela: because QA had said it", 1))
    V.settle_letters(vd, vd, st, THU, dry_run=True)
    check("`ela: because …` under that ask gives the cause to the waiting answer",
          st["keys:MH-11"]["answered"].get("cause") == "given" and st["keys:MH-11"]["answered"]["note"] == "QA had said it")

# ── an ask that expires says so, and where it still lives; outcomes count it on its own ─────────────────────
exp = {"note:projects/x/a.md": {"first": "2026-11-21", "text": "the open question on a", "sig": "s", "dropped": THU.isoformat(),
                                "link": "projects/x/a"},
       "keys:MH-1": {"first": "2026-11-21", "text": "comment MH-1", "sig": "s", "dropped": THU.isoformat(), "by": "owner",
                     "answered": {"letter": "B", "at": THU.isoformat()}},
       "keys:MH-2": {"first": "2026-11-20", "text": "old", "sig": "s", "dropped": "2026-11-25"},
       "keys:MH-3": {"first": THU.isoformat(), "text": "c", "sig": "s", "dropped": None, "rec": "A",
                     "answered": {"letter": "B", "at": THU.isoformat(), "cause": "waiting"}},
       "keys:MH-4": {"first": THU.isoformat(), "text": "d", "sig": "s", "dropped": None}}
lines = V.expired_lines(exp, THU)
check("an ask that expired this morning gets one line naming where it still lives; one dropped by his word does not",
      len(lines) == 1 and "the open question on a" in lines[0] and "[[projects/x/a|its note]]" in lines[0]
      and "[[reference/dropped|dropped asks]]" in lines[0])
check("outcomes: an expired ask is its own outcome", V.ask_outcomes(exp) == {"answered": 1, "wrong": 1, "waiting_cause": 1,
                                                                             "dropped_by_word": 1, "expired": 2, "open": 1})

# ── the board watch: kinds, the page, corrections, precedents, facts ──────────────────────────────────────────
src = open(os.path.join(ROOT, "skills", "watch", "watch.py"), encoding="utf-8").read()
raised = set(re.findall(r'(?:append\(\(|\[\()"([a-z-]+)", f?"', src))
check("every trigger the scan raises is in the watch's closed list of kinds", raised and raised <= set(W.KINDS))

with tempfile.TemporaryDirectory() as R:
    facts = os.path.join(R, "facts")
    os.makedirs(os.path.join(R, "ela"))
    due = {"triggered": [{"key": "MH-1", "summary": "one", "triggers": [{"kind": "unanswered", "says": "x"}]},
                         {"key": "MH-2", "summary": "two", "triggers": [{"kind": "owner-held", "says": "y"}]}]}
    dec = {"decisions": [{"key": "MH-1", "verdict": "ask", "kind": "ruling", "confidence": "medium", "why": "the reporter asked QA",
                          "question": "Hand it to QA?", "options": [{"letter": "A", "text": "assign to QA"}, {"letter": "B", "text": "leave it"}]},
                         {"key": "MH-2", "verdict": "ask", "kind": "fact", "confidence": "low", "fact": {"kind": "owner", "key": "WebRenderer"},
                          "question": "Who owns the WebRenderer?", "options": [{"letter": "A", "text": "tell ela"}]}]}
    out = W.decide(dec, due, facts, R, NOW, apply=True)
    tp = W.load_topics(R)["topics"]
    t1, t2 = tp["watch:MH-1"], tp["watch:MH-2"]
    check("a topic carries its class, kind and confidence; a ruling's reason sits in option A",
          (t1["class"], t1["kind"], t1["confidence"]) == ("unanswered", "ruling", "medium")
          and t1["options"][0]["text"] == "assign to QA — ela's reason: the reporter asked QA" and t2["kind"] == "fact")
    pg = W.page(R, THU)
    check("ela/watch.md: boxes to tick, the kind and confidence, and how to answer on the page",
          "- [ ] A (recommended): assign to QA — ela's reason: the reporter asked QA" in pg and "*ruling* · confidence medium" in pg
          and "*fact* · confidence low" in pg and "tick a letter, or write `ela: B because …`" in pg)
    said = pg.replace("- [ ] B: leave it", "- [x] B: leave it", 1).replace(
        "CLI: `ela watch answer watch:MH-2", "ela: A — the media team's web lead\nCLI: `ela watch answer watch:MH-2", 1)
    check("the page's answers: a ticked B with no note under it, and an `ela:` letter with its words",
          sorted(W.page_answers(said)) == [("watch:MH-1", "B", None), ("watch:MH-2", "A", "the media team's web lead")])
    V.settle_watch_page.__globals__["watch_mod"] = lambda: W
    vd = os.path.join(R, "vault")
    os.makedirs(os.path.join(vd, "ela"))
    open(os.path.join(vd, W.WATCH_PAGE), "w").write(said)
    done = V.settle_watch_page(vd, R)
    tp = W.load_topics(R)["topics"]
    check("the vault's sync records them as `ela watch answer` does", len(done) == 2 and tp["watch:MH-1"]["closed"]["letter"] == "B"
          and tp["watch:MH-2"]["closed"]["note"] == "the media team's web lead" and V.settle_watch_page(vd, R) == [])
    c = W.corrections(R)
    check("B on a ruling is a correction, waiting for a cause; a fact's answer is not a correction",
          len(c) == 1 and c[0]["act"] == "watch:MH-1" and c[0]["corpus"] == "waiting for a cause" and c[0]["class"] == "unanswered")
    check("precedents: one still waiting is not cited", A.precedents(R, "watch") == []
          and len(A.precedents(R, "watch", waiting=True)) == 1)
    W.cause(R, "watch:MH-1", "QA is not the owner of reporter questions", NOW)
    p = A.precedents(R, "watch", "unanswered")
    check("a cause given later completes the correction and the reader cites it by domain and kind",
          len(p) == 1 and p[0]["cause"] == "QA is not the owner of reporter questions" and p[0]["verdict"] == "B"
          and "watch/unanswered MH-1: B — because QA is not the owner" in A.cite(p[0])
          and A.precedents(R, "watch", "owner-held") == [])
    try:
        A.precedents(R, "watch", "no-such-kind"); bad = False
    except ValueError:
        bad = True
    check("a kind outside the domain's closed list is refused", bad)
    check("the fact he gave is kept under its kind and key", (A.known("owner", "webrenderer") or {}).get("value") == "the media team's web lead")
    rows = [{"key": "MH-3", "summary": "three", "triggers": [{"kind": "unanswered", "says": "z"}]}]
    check("the watch's prompt cites a precedent of the same kind",
          "watch/unanswered MH-1: B — because QA is not the owner" in W.prompt_text({"date": "2026-11-26"}, [dict(r, status="Open", assignee=None, priority="Medium", owner_held=False, chinese=False, comments=[]) for r in rows], "f.json", A.precedents(R, "watch")))
    out2 = W.decide({"decisions": [{"key": "MH-3", "verdict": "ask", "kind": "fact", "confidence": "low",
                                    "fact": {"kind": "owner", "key": "  WebRenderer "}, "question": "Who owns the WebRenderer?"}]},
                    {"triggered": rows}, facts, R, NOW, apply=True)
    check("the same fact for a second ticket is not asked: the kept answer is returned instead",
          "watch:MH-3" not in W.load_topics(R)["topics"] and out2.get("known", [{}])[0].get("value") == "the media team's web lead")
    bad = W.decide({"decisions": [{"key": "MH-3", "verdict": "ask", "kind": "fact", "question": "?", "fact": {"kind": "mood", "key": "x"}}]},
                   {"triggered": rows}, facts, R, NOW)
    check("a fact ask outside the fact kinds is refused", bad["refused"] and "fact" in bad["refused"][0]["why"])
    check("watch outcomes count agreed, wrong and open", W.outcomes(R) == {"agreed": 1, "wrong": 1, "waiting_cause": 0, "open": 0})

# ── mention keeps its own corrections ────────────────────────────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as R:
    rec = {"id": "m1", "triage": "ask", "reason": "question", "state": "drafted", "draft": True, "reply": "r", "at": "2026-11-26T09:00:00+08:00",
           "by_name": "Q", "channel_name": "c", "first": "?", "mentions": [], "thread_ts": "1", "channel": "C1"}
    MN.save(R, {"m1": rec})
    MN.answer(R, "m1", "C", now=NOW, note="the lead answered it in the stand-up")
    rows_ = MN.corrections(R)
    check("mention: C against a drafted reply is a correction with its cause, filed under its triage reason",
          len(rows_) == 1 and rows_[0]["class"] == "question" and rows_[0]["cause"] == "the lead answered it in the stand-up"
          and A.precedents(R, "mention", "question")[0]["target"] == "m1")
    check("the tally does not count a cause as an outcome", "cause" not in MN.tally(R).get("question", {}))

print(f"asks teach: {len(fails)} failed" if fails else "asks teach: all ok")
sys.exit(1 if fails else 0)
