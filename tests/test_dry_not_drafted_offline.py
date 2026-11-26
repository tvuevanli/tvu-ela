#!/usr/bin/env python3
"""The dry classes that stopped drafting (dry.NOT_DRAFTED: link-named, focus-moves), offline on a temp reports root:
neither stores a batch nor writes a set through any of its callers (dry.py's own verb, the mention follow-through, the
focus board), nothing of it is asked on today.md, the class keeps its place in the vocabulary and its ladder, and what
it already did stays readable and reversible (`ela dry did`, `ela dry undo`). Nothing reaches Jira: a fake runner."""
import contextlib, datetime, io, json, os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ("dry", "focus", "mention"):
    sys.path.insert(0, os.path.join(ROOT, "skills", d))
import dry as D  # noqa: E402
import focus as F  # noqa: E402
import mention as M  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

TUE, WED = datetime.date(2026, 11, 24), datetime.date(2026, 11, 26)
OWNER = "owner@example.com"
LINK = [{"n": 1, "target": "MH-2", "command": "ela jira link MH-1 MH-2 --type contains", "why": "named in a comment"}]
MOVE = [{"n": 1, "target": "MH-4", "command": "ela jira priority MH-4 --to High --why demo", "why": "his word"}]
ran = []
def fake(cmd, apply):
    ran.append((cmd, apply)); return 0, "ok"
def stored(R):
    return sorted(os.listdir(os.path.join(R, "ela", "dry", "batches"))) if os.path.isdir(os.path.join(R, "ela", "dry", "batches")) else []

check("the two classes are the ones named, and stay in the vocabulary with their ladders",
      sorted(D.NOT_DRAFTED) == ["focus-moves", "link-named"] and not D.drafted("link-named") and not D.drafted("focus-moves")
      and D.CLASSES["link-named"]["ladder"] == (3, 1) and D.CLASSES["focus-moves"]["ladder"] == (3,) and D.drafted("parent-status"))

with tempfile.TemporaryDirectory() as R:
    # ── dry.py: no batch, no set, no ask ────────────────────────────────────────────────────────────────────
    check("make_batch stores nothing for either class",
          D.make_batch(R, "link-named", "MH-1", LINK, [], WED) is None
          and D.make_batch(R, "focus-moves", "mediahub-focus", MOVE, [], WED) is None and stored(R) == [])
    r = D.place(R, "link-named", "MH-1", LINK, ["left"], WED, apply=True, runner=fake, now=datetime.datetime(2026, 11, 26, 10, tzinfo=D.TZ))
    check("place writes nothing at tier 1, --apply or not, and says why",
          r["state"] == "not drafted" and r["batch"] is None and r["left_out"] == ["left"] and "not drafted" in r["did"][0]
          and D.load_state(R)["link-named"]["tier"] == 1 and ran == [])
    r = D.act(R, "link-named", "MH-1", LINK, WED, apply=True, runner=fake)
    check("act writes no set", r["state"] == "not drafted" and r["ok"] and ran == [] and stored(R) == [] and D.record(R) == [])
    D.correct(R, "link-named", "correction", "MH-1", "back at confirm", now=datetime.datetime(2026, 11, 26, 11, tzinfo=D.TZ))
    r = D.place(R, "link-named", "MH-1", LINK, [], WED, apply=True, runner=fake)
    check("back at confirm (tier 3) it is still not drafted: no batch is asked",
          D.load_state(R)["link-named"]["tier"] == 3 and r["state"] == "not drafted" and stored(R) == [])
    check("nothing of either class is asked on today.md", D.asks(R, WED, ask_state={}) == [])
    child = os.path.join(R, "c.json"); parent = os.path.join(R, "p.json")
    json.dump({"key": "MH-2", "fields": {"summary": "s", "status": {"name": "Backlog"}}}, open(child, "w"))
    json.dump({"key": "MH-1", "fields": {"summary": "s", "status": {"name": "Backlog"}, "assignee": {"emailAddress": OWNER},
                                         "issuelinks": [], "description": "children: MH-2", "comment": {"comments": []}}}, open(parent, "w"))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        D.cmd_draft(type("A", (), dict(cls="link-named", key="MH-1", issue_file=parent, child_file=[child], env_file=None, owner=OWNER,
                                       date="2026-11-26", out_dir=os.path.join(R, "out"), before=None, apply=True, json=True, reports=R))())
    check("`ela dry draft link-named … --apply` answers not drafted", json.loads(out.getvalue())["state"] == "not drafted" and stored(R) == [])

    # ── the callers: the focus board and the mention follow-through ───────────────────────────────────────────
    st = {"words": {"w1": {"key": "MH-4"}}}
    comment = os.path.join(R, "runtime", "c.md")
    b = F.store_batch({"reports": R}, [dict(MOVE[0], file=comment, text="t")], [], WED, st)
    check("the focus board stores no batch, writes no comment file and marks no word batched",
          b is None and stored(R) == [] and not os.path.exists(comment) and "batched" not in st["words"]["w1"])
    mine = {"key": "MH-1", "fields": {"assignee": {"emailAddress": OWNER}, "issuelinks": [], "description": "children: MH-2",
                                      "comment": {"comments": []}}}
    names = type("N", (), {"render": staticmethod(lambda s: s), "me": "U1", "name": staticmethod(lambda u: u)})()
    ctx = {"reports": R, "owner": OWNER, "read": lambda k: mine if k == "MH-1" else {"key": k, "fields": {}}, "who": lambda u, n: None,
           "names": names, "today": WED, "runtime": os.path.join(R, "runtime")}
    f = M.follow({"id": "x"}, "I'll link these to MH-1.", ["MH-1"], ctx)
    check("a reply that promises links prepares nothing: listed as not acted on, with the reason",
          "link-named" not in f["by_class"] and len(f["unmapped"]) == 1 and f["unmapped"][0].startswith("link-named: not drafted")
          and stored(R) == [])
    check("a drafted reply implies no links; a class still drafted is implied as before",
          M.implied("I'll link these to MH-1 and update the parent.", ["MH-1"]) == ["a status comment · MH-1"])

with tempfile.TemporaryDirectory() as R:
    # ── what the classes already did stays readable and reversible ────────────────────────────────────────────
    os.makedirs(os.path.join(R, "ela", "dry", "batches"))
    bid = f"{TUE}-link-named-MH-1"
    D.append(R, {"at": "2026-11-24T10:00:00+08:00", "class": "link-named", "verdict": "applied", "as_drafted": True, "target": "MH-2",
                 "command": LINK[0]["command"], "why": "named in a comment", "batch": bid, "act": f"{bid}#1", "source": "tier1"})
    with open(D.acts_path(R), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": "2026-11-24T10:00:00+08:00", "act": f"{bid}#1", "class": "link-named", "key": "MH-1", "verb": "link",
                             "before": {}, "undo": ["ela", "jira", "unlink", "MH-1", "--id", "901"]}) + "\n")
    old = {"id": f"{TUE}-focus-moves-mediahub-focus", "class": "focus-moves", "scope": "mediahub-focus", "made": "2026-11-24T10:00:00+08:00",
           "state": "open", "writes": MOVE, "left_out": []}
    D.save_batch(R, old)
    line, lst = D.did(R, TUE.isoformat())
    check("`ela dry did` still lists a past link with its undo",
          line == "ela did: 1 link" and [(a, u) for a, _, u, _ in lst] == [(f"{bid}#1", f"ela dry undo {bid}#1 --apply")])
    check("its record row and its act stay readable", [r["class"] for r in D.record(R)] == ["link-named"]
          and [a["act"] for a in D.acts(R, bid)] == [f"{bid}#1"])
    ran.clear()
    r = D.undo(R, f"{bid}#1", apply=True, runner=fake, now=datetime.datetime(2026, 11, 26, 12, tzinfo=D.TZ))
    check("`ela dry undo` still reverses it and marks the act undone",
          r["ok"] and ran == [(["ela", "jira", "unlink", "MH-1", "--id", "901"], True)] and D.acts(R, bid)[0]["undone"])
    check("a batch opened before the class stopped is left open and answerable; a later pass adds nothing to it",
          D.make_batch(R, "focus-moves", "mediahub-focus", MOVE + [dict(MOVE[0], n=2, target="MH-5")], [], WED) is None
          and D.load_batch(R, old["id"])["state"] == "open" and [x["id"] for x in D.asks(R, WED, ask_state={})] == [f"dry:{old['id']}"]
          and D.answer(R, f"dry:{old['id']}", "B")["did"] == ["dropped 1"] and D.load_batch(R, old["id"])["state"] == "dropped")

if failures:
    print(f"dry not drafted: {len(failures)} FAILED"); sys.exit(1)
print("dry not drafted: all offline checks passed")
