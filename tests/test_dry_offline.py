#!/usr/bin/env python3
"""Dry runs by class, offline, on a temp reports root: the MH-3735 links of 2026-11-12 replayed as one class batch with
its review note; the record seeded from history; a class driven to ten clean runs earns exactly one grant ask, yes moves
its tier, a correction moves it back; a class tier 3 names by rule never earns the ask. Nothing reaches Jira: the
writes go to a fake runner."""
import datetime, json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "dry"))
import dry as D  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

OWNER = "owner@example.com"
def para(text):
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}
def comment(cid, who, at, *lines):
    return {"id": cid, "author": {"displayName": who}, "created": at, "body": {"type": "doc", "content": [para(l) for l in lines]}}
def link(lid, reads, key, status, outward=True):
    t = {"name": "Hierarchy", "outward": "contains", "inward": "is contained in"}
    other = {"key": key, "fields": {"status": {"name": status}, "summary": f"{key} summary"}}
    return {"id": lid, "type": t, ("outwardIssue" if outward else "inwardIssue"): other}
def issue(key, parent=None, status="Backlog", **f):
    return {"key": key, "fields": dict({"summary": f"{key} summary", "status": {"name": status}, "parent": {"key": parent} if parent else None}, **f)}

# MH-3735 as it stood at 13:00 on 2026-11-12, before the six links: the colleague's 11-11 update names the modules
parent = issue("MH-3735", assignee={"emailAddress": OWNER, "displayName": "Owner"},
               issuelinks=[link(61333, "is contained in", "TMM-1133", "Planned", outward=False), link(62312, "contains", "MH-3990", "Backlog")],
               comment={"comments": [
                   comment("290954", "Automation for Jira", "2026-11-10T18:36:27.776-0800", "Copied from MH-3990"),
                   comment("291320", "a colleague", "2026-11-11T12:10:14.614-0800",
                           "Mixer: Prod 3 still needs the Audio Mixer's MQTT setting turned on (EDPP-3311).",
                           "CSC: MQTT support is finished (MH-3983). UR change in review (MH-3986); app change on QA (MH-3987).",
                           "White Balance: UR needs a small fix before QA can test it (MH-3842).",
                           "Blackframe Detector: next workflow-engine deployment (MH-3990).",
                           "Related: MH-3869. YouTube Render JWT fix waits for a retest."),
                   comment("291655", "Owner", "2026-11-11T21:19:54.150-0800", "Children are now linked here: EDPP-2847, MH-3792.")]})
children = {k: issue(k) for k in ("EDPP-3311", "MH-3983", "MH-3842", "MH-3869", "MH-3990")}
children["MH-3986"] = issue("MH-3986", parent="MH-3983")
children["MH-3987"] = issue("MH-3987", parent="MH-3983")

with tempfile.TemporaryDirectory() as R:
    THU = datetime.date(2026, 11, 12)
    writes, left = D.select_link_named(parent, children, before="2026-11-12T13:18:00+08:00")
    got = [(w["target"], w["command"].split("--type ")[1]) for w in writes]
    check("MH-3735: the links its comment names and Jira lacks, in the order named; Related: reads relates to",
          got == [("EDPP-3311", "contains"), ("MH-3983", "contains"), ("MH-3842", "contains"), ("MH-3869", '"relates to"')])
    check("a subtask of a proposed ticket is left out, named; one already linked is not proposed; a later comment is not read",
          any("MH-3986" in x and "MH-3983" in x for x in left) and "MH-3990" not in [t for t, _ in got]
          and "EDPP-2847" not in [t for t, _ in got])
    check("every write is a command the class admits", all(__import__("re").match(D.CLASSES["link-named"]["command"], w["command"]) for w in writes))
    check("a parent he does not own is not the class's", not D.owns(dict(parent, fields=dict(parent["fields"], assignee={"emailAddress": "x@y"})), OWNER))
    b = D.make_batch(R, "link-named", "MH-3735", writes, left, THU)
    a = D.asks(R, THU, commit=True, ask_state={})
    check("one class ask for the batch, not one per link", [x["id"] for x in a] == [f"dry:{b['id']}"] and a[0]["question"].startswith("4 links ready for MH-3735"))
    check("the ask is A (recommended) apply all, B drop: two options, no invented middle",
          [(o["letter"], o["recommended"]) for o in a[0]["options"]] == [("A", True), ("B", False)]
          and a[0]["options"][0]["does"] == f"ela dry answer dry:{b['id']} A --apply")
    note = D.review_note(b)
    check("the review note shows each exact write", all(f"`{w['command']}`" in note for w in writes))
    edited = note.replace(f"4. `{writes[3]['command']}`", f"~~4. `{writes[3]['command']}`").replace(
        writes[3]["why"], writes[3]["why"] + "~~").replace("MH-3842 --type contains", 'MH-3842 --type "relates to"')
    calls = []
    res = D.answer(R, a[0]["id"], "A", edited, apply=False, runner=lambda c, ap: (calls.append((c, ap)) or (0, "DRY RUN")))
    check("A without --apply is a dry run of each kept write; nothing recorded, the batch stays open",
          all(not ap for _, ap in calls) and len(calls) == 3 and D.load_batch(R, b["id"])["state"] == "open" and not D.record(R))
    calls.clear()
    res = D.answer(R, a[0]["id"], "A", edited, apply=True, runner=lambda c, ap: (calls.append((c, ap)) or (0, "linked")))
    rec = D.record(R)
    check("A --apply: kept lines written, the struck one left out, the edit applied as edited",
          [c for c, _ in calls] == [writes[0]["command"], writes[1]["command"], 'ela jira link MH-3735 MH-3842 --type "relates to"'])
    check("the record: 2 applied as drafted, 1 edited, 1 cancelled, each with the letter A",
          sorted((r["verdict"], r.get("as_drafted")) for r in rec) == [("applied", True), ("applied", True), ("cancelled", None), ("edited", False)]
          and all(r.get("letter") == "A" for r in rec))
    check("an answered batch is not asked again", D.asks(R, THU, ask_state={}) == [] and D.answer(R, a[0]["id"], "A", None, True, lambda c, ap: (0, ""))["did"] == ["already applied"])

with tempfile.TemporaryDirectory() as R:
    # the record from history: an applied action is as drafted; a write the log alone shows has its draft unknown
    os.makedirs(os.path.join(R, "runner")); os.makedirs(os.path.join(R, "ela"))
    json.dump([{"n": 1, "kind": "fixed-in", "command": "ela jira fixed-in MH-1 --add a@1", "applied": "2026-11-02T09:00:00+0800"},
               {"n": 2, "kind": "assign", "command": "ela jira assign MH-2 --to x", "by_owner": {"at": "2026-11-02T11:00:00+0800"}},
               {"n": 3, "kind": "close", "command": "ela jira close MH-3", "vetoed": "2026-11-02T10:00:00+0800"},
               {"n": 4, "kind": "comment", "command": "ela jira comment MH-4 --text x", "applied": "2026-11-02T09:05:00+0800"}],
              open(os.path.join(R, "runner", "2026-11-02-actions.json"), "w"))
    open(os.path.join(R, "ela", "writes.jsonl"), "w").write("\n".join(json.dumps(w) for w in [
        {"at": "2026-11-02T09:00:30+08:00", "system": "jira", "verb": "fixed-in", "key": "MH-1", "ok": True},
        {"at": "2026-11-03T09:00:00+08:00", "system": "jira", "verb": "link", "key": None, "ok": True},
        {"at": "2026-11-03T09:10:00+08:00", "system": "slack", "verb": "post", "where": "DM to someone", "ok": True},
        {"at": "2026-11-03T09:20:00+08:00", "system": "jira", "verb": "comment", "key": "MH-9", "ok": True}]) + "\n")
    rows = D.seed(R)
    by = {(r["class"], r["verdict"], r.get("as_drafted")) for r in rows}
    check("seed: applied action as drafted, handled himself as an edit, a veto as cancelled",
          {("fixed-in-announced", "applied", True), ("assign-by-rule", "edited", False), ("close", "cancelled", None)} <= by)
    check("seed: the write its applied action accounts for is not counted twice; a log-only write's draft is unknown",
          sum(1 for r in rows if r["class"] == "fixed-in-announced") == 1 and ("link-named", "applied", None) in by
          and ("message-to-person", "applied", None) in by)
    check("seed: comments are not attributed to a class", not any(r.get("target") in ("MH-4", "MH-9") for r in rows))

def drive(R, cls, n, start=datetime.date(2026, 11, 2), per_day=4):
    for i in range(n):
        d = start + datetime.timedelta(days=i // per_day)
        D.append(R, {"at": f"{d.isoformat()}T09:{i % 60:02d}:00+08:00", "class": cls, "verdict": "applied", "as_drafted": True,
                     "letter": "A", "target": f"MH-{100 + i}", "source": "batch"})

with tempfile.TemporaryDirectory() as R:
    FRI = datetime.date(2026, 11, 13)
    drive(R, "link-named", 9)
    check("nine clean runs: no grant ask", not [x for x in D.asks(R, FRI, commit=True, ask_state={}) if x["kind"] == "grant"])
    drive(R, "link-named", 1, start=datetime.date(2026, 11, 5))
    g = [x for x in D.asks(R, FRI, commit=True, ask_state={}) if x["kind"] == "grant"]
    check("ten over three days: exactly one grant ask", len(g) == 1 and g[0]["class"] == "link-named")
    check("the grant ask: A grant, B keep confirming, C never again; the record in a line, three examples",
          [o["letter"] for o in g[0]["options"]] == ["A", "B", "C"] and g[0]["options"][0]["recommended"]
          and g[0]["record"].startswith("10 applied as drafted over 4 days") and g[0]["record"].count("MH-") == 3)
    check("asked again the same pass: no second ask while one is open", not [x for x in D.asks(R, FRI, commit=True, ask_state={}) if x["kind"] == "grant"])
    res = D.answer(R, g[0]["id"], "A")
    st = D.load_state(R)
    check("yes moves the class one step up its ladder (Jira: 3 → 1)", st["link-named"]["tier"] == 1 and "3 → 1" in res["did"][0])
    check("granted: no further ask", not [x for x in D.asks(R, FRI, ask_state={}) if x["kind"] == "grant"])
    n = D.correct(R, "link-named", "revert", "MH-3842", "link removed by a colleague", now=datetime.datetime(2026, 11, 16, 11, tzinfo=D.TZ))
    st = D.load_state(R)
    check("one revert returns it to confirm and says so for today.md",
          st["link-named"]["tier"] == 3 and "back to your confirm" in n and D.notices(R, "2026-11-16") == [n])
    check("after the fall the record starts over: no ask until ten new clean runs",
          not [x for x in D.asks(R, datetime.date(2026, 11, 16), ask_state={}) if x["kind"] == "grant"])

with tempfile.TemporaryDirectory() as R:
    drive(R, "release-label", 10)
    D.append(R, {"at": "2026-11-04T12:00:00+08:00", "class": "release-label", "verdict": "edited", "as_drafted": False, "target": "MH-9", "source": "batch"})
    check("an edit in the last ten blocks maturity", not D.judged("release-label", D.record(R), D.load_state(R)["release-label"])["mature"])
    drive(R, "close", 20)
    drive(R, "message-to-person", 20)
    check("a class tier 3 names by rule never earns the ask, however clean",
          not [x for x in D.asks(R, datetime.date(2026, 11, 20), ask_state={}) if x["kind"] == "grant"])
    try:
        D.answer(R, "grant:close:20", "A"); refused = False
    except ValueError:
        refused = True
    check("and cannot be granted by a letter", refused and D.load_state(R)["close"]["tier"] == 3)

with tempfile.TemporaryDirectory() as R:
    drive(R, "fixed-in-announced", 10)
    g = [x for x in D.asks(R, datetime.date(2026, 11, 6), commit=True, ask_state={}) if x["kind"] == "grant"]
    D.asks(R, datetime.date(2026, 11, 11), commit=True, ask_state={g[0]["id"]: {"dropped": "2026-11-11"}})
    check("no answer changes nothing; the ask stays away", D.load_state(R)["fixed-in-announced"]["tier"] == 3
          and not [x for x in D.asks(R, datetime.date(2026, 11, 12), ask_state={}) if x["kind"] == "grant"])
    drive(R, "fixed-in-announced", 9, start=datetime.date(2026, 11, 12))
    check("nine more: still away", not [x for x in D.asks(R, datetime.date(2026, 11, 16), ask_state={}) if x["kind"] == "grant"])
    drive(R, "fixed-in-announced", 1, start=datetime.date(2026, 11, 16))
    check("ten more clean runs: it returns", [x["kind"] for x in D.asks(R, datetime.date(2026, 11, 16), ask_state={})] == ["grant"])

with tempfile.TemporaryDirectory() as R, tempfile.TemporaryDirectory() as out:
    p = issue("MH-3735", assignee={"emailAddress": OWNER}, issuelinks=[link(1, "contains", "MH-3983", "Review"), link(2, "contains", "MH-3842", "Backlog")],
              comment={"comments": [{"id": "1", "author": {"emailAddress": OWNER}, "created": "2026-11-11T21:00:00.000-0800",
                                     "body": {"type": "doc", "content": [para("CSC (MH-3983, In Progress)"), para("White Balance (MH-3842, Backlog)")]}}]})
    w, _ = D.select_parent_status(p, OWNER, datetime.date(2026, 11, 13), out)
    check("parent status: drafted when a child moved since his last status comment, naming the move",
          len(w) == 1 and "MH-3983 → Review" in w[0]["why"] and __import__("re").match(D.CLASSES["parent-status"]["command"], w[0]["command"]))
    p["fields"]["comment"]["comments"][0]["body"]["content"][0] = para("CSC (MH-3983, Review)")
    check("nothing moved: nothing drafted", D.select_parent_status(p, OWNER, datetime.date(2026, 11, 13), out)[0] == [])

# today.md, end to end on a temp vault and reports root: the batch is one ask linking its review note; the letters
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "vault"))
import vault as V  # noqa: E402
with tempfile.TemporaryDirectory() as R, tempfile.TemporaryDirectory() as VT:
    THU = datetime.date(2026, 11, 12)
    writes, left = D.select_link_named(parent, children, before="2026-11-12T13:18:00+08:00")
    b = D.make_batch(R, "link-named", "MH-3735", writes, left, THU)
    st = {}
    dc, facts = V.dry_asks(R, THU, st)
    shown, more, _, st = V.settle_asks(st, dc + V.ask_candidates(THU, [{"n": 7, "tier": 3, "command": "ela jira comment MH-7", "text": "comment MH-7",
                                                                           "evidence": "e", "day": THU.isoformat()}], []), THU)
    for k, c in enumerate(shown, 1):
        st[c["id"]].update(slot=k, options={o["letter"]: o["does"] for o in V.ask_options(c)})
    page = V.today_page(THU, [], {"dry_facts": facts}, shown)
    pages = V.dry_pages(VT, R, THU)
    check("today.md: the six-link case is one ask with a review note, A applies the batch, B drops it",
          f"1. 4 links ready for MH-3735: link a child to a parent you own when a comment on the parent names it. → [[ela/dry/{b['id']}|the note]]" in page
          and "    - [ ] A (recommended): apply all 4 (strike a line in the note to leave it out)" in page and "    - [ ] B: drop them" in page
          and f"ela/dry/{b['id']}.md" in pages and all(f"`{w['command']}`" in pages[f"ela/dry/{b['id']}.md"] for w in writes))
    check("within today.md's word cap", len(V.plain(page.split("\n---\n")[0]).split()) <= V.TODAY_WORDS)
    os.makedirs(os.path.join(VT, "ela", "dry"))
    open(os.path.join(VT, f"ela/dry/{b['id']}.md"), "w").write(pages[f"ela/dry/{b['id']}.md"].replace("1. `", "~~1. `", 1))
    check("the review note on disk is his: a struck line survives the next sync", V.dry_pages(VT, R, THU)[f"ela/dry/{b['id']}.md"].count("~~1. `") == 1)
    lt = V.today_letters(page.replace("    - [ ] A (recommended): apply all 4", "    - [x] A (recommended): apply all 4"), st)
    check("a tick on A is the runner's: the batch applies with --apply, the struck line left out by the answer",
          [(x["id"], x["does"]) for x in lt] == [(f"dry:{b['id']}", f"ela dry answer dry:{b['id']} A --apply")] and not V.sync_handles(lt[0]["does"]))
    drive(R, "link-named", 10)
    dc, _ = V.dry_asks(R, datetime.date(2026, 11, 13), {})
    g = next(c for c in dc if c["id"].startswith("grant:"))
    st = {g["id"]: {"slot": 2, "options": {o["letter"]: o["does"] for o in g["options"]}, "sig": g["sig"], "first": "2026-11-13", "text": "g"}}
    open(os.path.join(VT, "today.md"), "w").write("## Needs you\n\n1. x\n2. grant\nela: A\n")
    done = V.settle_letters(VT, R, st, datetime.date(2026, 11, 13))
    check("`ela: A` under the grant ask: the sync grants it once (3 → 1), and remembers the letter",
          done == [(g["id"], "A")] and D.load_state(R)["link-named"]["tier"] == 1 and V.settle_letters(VT, R, st, datetime.date(2026, 11, 13)) == [])
    D.correct(R, "link-named", "word", note="the owner's ela: line against a link", now=datetime.datetime(2026, 11, 16, 9, tzinfo=D.TZ))
    _, facts = V.dry_asks(R, datetime.date(2026, 11, 16), {})
    page = V.today_page(datetime.date(2026, 11, 16), [], {"dry_facts": facts}, [])
    os.makedirs(os.path.join(R, "runner"))
    json.dump([{"n": 1, "tier": 1, "rule": "link-named", "text": "MH-3735 contains MH-1", "command": "ela jira link MH-3735 MH-1 --type contains",
                "applied": "2026-11-16T08:40:00+0800"}, {"n": 2, "tier": 3, "text": "comment MH-2", "applied": "2026-11-16T09:00:00+0800"}],
              open(os.path.join(R, "runner", "2026-11-16-actions.json"), "w"))
    _, facts = V.dry_asks(R, datetime.date(2026, 11, 16), {})
    check("what a granted class did without confirm is one Facts line linking the list; his own applies are not in it",
          facts[0] == "ela did: 1 link → [[ela/dry/did|the list, each undoable by a word]]"
          and "`ela: undo 1`" in V.dry_pages(VT, R, datetime.date(2026, 11, 16))["ela/dry/did.md"])
    page = V.today_page(datetime.date(2026, 11, 16), [], {"dry_facts": facts}, [])
    check("a fall is said on today.md under Facts", "- **Done by ela:** link-named is back to your confirm (word: the owner's ela: line against a link)." in page)

print(f"{len(failures)} failed" if failures else "all passed")
sys.exit(1 if failures else 0)
