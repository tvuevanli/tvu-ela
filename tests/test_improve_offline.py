#!/usr/bin/env python3
"""The improvement loop, offline, on a temp reports root and a temp mediahub-bot data directory (ADR 0023): the digest
joins a bot task's accepted and done rows, links its thread and counts the runs the thread took, and counts ela's
follow-ups in one thread; `add` checks a day's items (at most three, a closed area and who, a known same_as) and
counts an item seen again instead of storing it twice; an item inside ela starts as go, one a colleague would see
waits for his letter; A is go, B drops it and keeps it, a second letter is refused; the section leads with his items;
only his open items are asks, and on today.md such an ask is a candidate whose letter the sync settles itself. Nothing
reaches Slack or Jira."""
import datetime, json, os, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "skills", "improve"))
sys.path.insert(0, os.path.join(HERE, "skills", "vault"))
import improve as I  # noqa: E402
import vault as V  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

DAY, NEXT = "2026-11-20", "2026-11-21"
TZ = datetime.datetime.now().astimezone().tzinfo
def stamp(h, m=0, day=DAY):
    return datetime.datetime.fromisoformat(f"{day}T{h:02d}:{m:02d}:00").replace(tzinfo=TZ).isoformat()

with tempfile.TemporaryDirectory() as tmp:
    R, RT, DATA = (os.path.join(tmp, d) for d in ("reports", "runtime", "mhbot"))
    for d in (R, RT, DATA, os.path.join(R, "runner", "jobs")):
        os.makedirs(d, exist_ok=True)

    # ---- the digest --------------------------------------------------------------------------------------------
    rows = [{"task": "t1", "at": stamp(10), "event": "accepted", "channel": "C0DEV", "thread_ts": "1763600000.000100",
             "lane": "prod-3", "mode": "probe", "asker": "U0ASK"},
            {"task": "t1", "at": stamp(10, 9), "event": "done", "verdict": "found", "confidence": "medium",
             "summary": "the copier drops the PID", "gaps": ["no log for the box"]},
            {"task": "t2", "at": stamp(11), "event": "accepted", "channel": "C0DEV", "thread_ts": "1763600000.000200"},
            {"task": "t2", "at": stamp(11, 5), "event": "failed", "error": "timeout reading UR"},
            {"task": "t0", "at": stamp(9, day="2026-11-19"), "event": "accepted", "channel": "C0DEV", "thread_ts": "1.0"}]
    with open(os.path.join(DATA, "runs.jsonl"), "w") as f:
        f.write("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    json.dump({"C0DEV:1763600000.000100": {"runs": 3, "askers": ["U0ASK", "U0PEER"]}}, open(os.path.join(DATA, "threads.json"), "w"))
    jobs = [("j1", "owner", "done", stamp(9), {"channel": "D0ME", "thread_ts": "1763600100.000001", "label": "why is prod-3 slow"}),
            ("j2", "owner", "done", stamp(9, 30), {"channel": "D0ME", "thread_ts": "1763600100.000001", "label": "and the box?"}),
            ("j3", "vault", "failed", stamp(12), {"label": "a vault line"}),
            ("j4", "owner", "running", stamp(8), {"label": "long one"}),
            ("j5", "owner", "done", stamp(9, day="2026-11-19"), {"label": "yesterday"})]
    for jid, kind, status, at, origin in jobs:
        json.dump({"id": jid, "kind": kind, "status": status, "created": at, "started": at, "origin": origin, "answer": "x"},
                  open(os.path.join(R, "runner", "jobs", f"{jid}.json"), "w"))
    os.makedirs(os.path.join(R, "ela"), exist_ok=True)
    with open(os.path.join(R, "ela", "feedback.jsonl"), "w") as f:
        f.write(json.dumps({"at": stamp(14), "from": "owner", "text": "the bot answer was too long"}) + "\n")

    d = I.digest(DAY, R, RT, DATA, now=datetime.datetime.fromisoformat(stamp(18)))
    bot = {t["task"]: t for t in d["mediahub_bot"]}
    check("digest: the day's bot tasks only, accepted and done joined by task", sorted(bot) == ["t1", "t2"]
          and bot["t1"]["lane"] == "prod-3" and bot["t1"]["verdict"] == "found" and bot["t1"]["gaps"] == ["no log for the box"])
    check("digest: the thread's permalink, the runs it took and its askers",
          bot["t1"]["permalink"] == "https://tvunetworks.slack.com/archives/C0DEV/p1763600000000100"
          and bot["t1"]["thread_runs"] == 3 and bot["t1"]["thread_askers"] == 2)
    check("digest: a failed run is kept as an event", bot["t2"]["events"] == [{"event": "failed", "error": "timeout reading UR"}])
    e = d["ela"]
    check("digest: two asks in one thread are one follow-up of two turns",
          e["follow_ups"] == [{"thread": "D0ME-1763600100.000001", "turns": 2}]
          and all(a["turns_in_thread"] == 2 for a in e["asks"] if a.get("thread")))
    check("digest: failed and stuck jobs, yesterday's left out", [x["id"] for x in e["failed"]] == ["j3"]
          and [x["id"] for x in e["stuck"]] == ["j4"] and "j5" not in {a["id"] for a in e["asks"]})
    check("digest: the day's feedback", [x["text"] for x in d["feedback"]] == ["the bot answer was too long"])

    # ---- add ---------------------------------------------------------------------------------------------------
    def item(area="ela", who="ela", problem="a thread needed two follow-ups", fix="answer the box in the first reply"):
        return {"area": area, "who": who, "problem": problem, "fix": fix, "evidence": ["D0ME-1763600100.000001: 2 turns"]}
    def refused(items):
        try:
            I.add(R, items, DAY)
        except ValueError as err:
            return str(err)
        return ""
    check("add: more than three items refused", "at most 3" in refused([item(problem=str(k)) for k in range(4)]))
    check("add: an unknown area refused", "area" in refused([item(area="helm")]))
    check("add: an unknown who refused", "who" in refused([item(who="team")]))
    check("add: an unknown same_as refused", "same_as" in refused([{"same_as": "ela-00000000"}]))
    check("add: a refused list stores nothing", I.load(R) == {})
    ids = I.add(R, [item(), item(area="mediahub-bot", who="owner", problem="answers run long", fix="cap the summary at five lines")], DAY)
    recs = I.load(R)
    a_ela, a_owner = ids
    check("add: an ela item starts go, an owner item open", recs[a_ela]["state"] == "go" and recs[a_owner]["state"] == "open")
    I.add(R, [{"same_as": a_ela, "evidence": ["seen again"]}], NEXT)
    I.add(R, [{"same_as": a_ela}], NEXT)
    recs = I.load(R)
    check("add: same_as appends the day once and the evidence, no second item",
          recs[a_ela]["seen"] == [DAY, NEXT] and recs[a_ela]["evidence"][-1] == "seen again" and len(recs) == 2)

    # ---- section, pending, asks --------------------------------------------------------------------------------
    sec = I.section(R, DAY)
    check("section: his item first, then ela's", len(sec) == 2 and "*mediahub-bot*" in sec[0] and "needs your word" in sec[0]
          and "ela carries it out" in sec[1])
    check("section: a day with nothing says so", I.section(R, "2026-11-01") == ["- Nothing to improve today."])
    check("pending: the go item for the desk", a_ela in I.pending(R) and a_owner not in I.pending(R))
    got = I.asks(R)
    check("asks: only his open item, A go and B drop", [x["id"] for x in got] == [f"improve:{a_owner}"]
          and [o["does"] for o in got[0]["options"]] == [f"ela improve answer {a_owner} A", f"ela improve answer {a_owner} B"])

    # ---- today.md: the ask is a candidate and the sync settles his letter --------------------------------------
    today = datetime.date(2026, 11, 20)
    cands = V.improve_asks(R, today)
    check("today.md: the improvement is an ordinary ask candidate, whole, with its letters",
          [c["id"] for c in cands] == [f"improve:{a_owner}"] and cands[0]["whole"] and len(cands[0]["options"]) == 2)
    shown, _, _, st = V.settle_asks({}, cands, today)
    c = shown[0]
    st[c["id"]].update(slot=1, options={o["letter"]: o["does"] for o in c["options"]})
    VT = os.path.join(tmp, "vault")
    os.makedirs(VT)
    open(os.path.join(VT, V.TODAY), "w").write("## Needs you\n\n1. mediahub-bot: answers run long\nela: B\n")
    done = V.settle_letters(VT, R, st, today)
    recs = I.load(R)
    check("today.md: his B is settled by the sync once, the item dropped and kept",
          done == [(c["id"], "B")] and recs[a_owner]["state"] == "dropped" and recs[a_owner]["answer"]["letter"] == "B"
          and V.settle_letters(VT, R, st, today) == [] and V.improve_asks(R, today) == [])
    BR = os.path.join(tmp, "broken")
    os.makedirs(os.path.join(BR, "ela"))
    open(I.store_path(BR), "w").write('["not", "a", "store"]')
    check("a broken store costs the improvement asks only", V.improve_asks(BR, today) == [])

    # ---- answer and done ---------------------------------------------------------------------------------------
    b = I.add(R, [item(area="vault", who="owner", problem="a vault line took two rounds", fix="read the note first")], NEXT)[0]
    check("answer: A is go", I.answer(R, b, "A")["state"] == "go")
    try:
        I.answer(R, b, "B"); second = False
    except ValueError:
        second = True
    check("answer: a second letter is refused", second and I.load(R)[b]["state"] == "go")
    try:
        I.answer(R, b, "Z"); bad = False
    except ValueError:
        bad = True
    check("answer: a letter other than A or B is refused", bad)
    check("done: an item carried out says what changed", I.done(R, b, "the vault reader reads the note first")["state"] == "done")
    try:
        I.done(R, a_owner, "x"); dropped = False
    except ValueError:
        dropped = True
    check("done: a dropped item cannot be done, and stays in the store", dropped and a_owner in I.load(R))

print("improve: all passed" if not failures else f"improve: {len(failures)} FAILED")
sys.exit(1 if failures else 0)
