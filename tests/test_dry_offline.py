#!/usr/bin/env python3
"""Dry runs by class, offline, on a temp reports root: the MH-3735 links of 2026-11-12 replayed as one class batch with
its review note; the record seeded from history; a class driven to ten clean runs earns exactly one grant ask, yes moves
its tier, a correction moves it back; a class tier 3 names by rule never earns the ask. Nothing reaches Jira: the
writes go to a fake runner."""
import datetime, json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "dry"))
import dry as D  # noqa: E402

# the site points at a temp runtime: no note in this test reads the real fact store
RT = tempfile.TemporaryDirectory()
D.site = lambda: {"runtime": RT.name}

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
                           "Mixer: Prod 3 still needs the Audio Mixer's MQTT setting turned on (blocked by EDPP-3311).",
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
    sp = dict(parent, key="MH-3568", fields=dict(parent["fields"], issuelinks=[], comment={"comments": []},
              description={"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text",
              "text": "SCTE-35 PID 500 declared with no SCTE-35 injected; SCTE-104 too. See MH-3998."}]}]}))
    sw, sl = D.select_link_named(sp, {"SCTE-35": issue("SCTE-35"), "MH-3998": issue("MH-3998")})
    check("a standard's name (SCTE-35, SCTE-104) is not a ticket named, even when a Jira ticket carries it",
          [w["target"] for w in sw] == ["MH-3998"] and not any("SCTE" in x for x in sl))
    bare = dict(parent, fields=dict(parent["fields"], comment={"comments": [dict(parent["fields"]["comment"]["comments"][1], body={
        "type": "doc", "content": [para("Mixer: Prod 3 still needs the Audio Mixer's MQTT setting turned on (EDPP-3311).")]})]}))
    bw, bl = D.select_link_named(bare, children)
    check("another project's key with no link verb on its line is not proposed, and is named as left out",
          bw == [] and any(x.startswith("EDPP-3311 — another project's key") for x in bl))
    # MH-3997 on 2026-11-24 (batch 2026-11-24-link-named-MH-3997, dropped with B): Jira's smart-link made a standard's
    # name look like a reference, and a Figma file named after a ticket sat in a URL path
    def card(url):
        return {"type": "inlineCard", "attrs": {"url": url}}
    p97 = issue("MH-3997", issuelinks=[], comment={"comments": []}, description={"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "Mux carries "}, card("https://tvunetworks.atlassian.net/browse/SCTE-35#icft=SCTE-35"),
                                          {"type": "text", "text": " markers as today."}]},
        para("Design: https://www.figma.com/design/AbC123xyz/MH-2026?node-id=12-345&t=k"),
        para("Scope as in https://tvunetworks.atlassian.net/browse/MH-3998 and MH-3999.")]})
    kids97 = {"SCTE-35": issue("SCTE-35", status="Done"), "MH-2026": issue("MH-2026", status="Done"),
              "MH-3998": issue("MH-3998"), "MH-3999": issue("MH-3999")}
    w97, l97 = D.select_link_named(p97, kids97)
    check("MH-3997: an #icft= smart-link and a Figma file name in a URL path name no ticket; a plain browse link and prose do",
          [w["target"] for w in w97] == ["MH-3998", "MH-3999"] and not any("SCTE" in x or "MH-2026" in x for x in l97))
    check("strip_urls keeps a plain browse link's key and drops the rest",
          D.ticket_keys("see https://x.atlassian.net/browse/MH-1 and https://x.atlassian.net/browse/MH-2#icft=MH-2 "
                        "https://www.figma.com/design/a/MH-3?node-id=1") == ["MH-1"])
    pd = issue("MH-3984", issuelinks=[], comment={"comments": []}, description={"type": "doc", "content": [
        para("Same symptom as FB-10748, see there."), para("Related: FB-10749.")]})
    wd, ld = D.select_link_named(pd, {"FB-10748": issue("FB-10748", status="Done"), "FB-10749": issue("FB-10749", status="Done")})
    check("another project's Done ticket named once is never proposed as contains; a related one still relates",
          [(w["target"], w["command"].split("--type ")[1]) for w in wd] == [("FB-10749", '"relates to"')]
          and any(x.startswith("FB-10748 — another project's Done ticket") for x in ld))
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
    check("seed: handled himself is an edit, a veto cancelled; a single Fixed In drafted before its rule counts in totals only",
          {("release-reconcile", "applied", None), ("assign-by-rule", "edited", False), ("close", "cancelled", None)} <= by)
    check("seed: the write its applied action accounts for is not counted twice; a log-only write's draft is unknown",
          sum(1 for r in rows if r["class"] == "release-reconcile") == 1 and ("link-named", "applied", None) in by
          and ("message-to-person", "applied", None) in by)
    check("seed: comments are not attributed to a class", not any(r.get("target") in ("MH-4", "MH-9") for r in rows))

# The grant machinery is replayed on link-named as it stood before the decision of 2026-11-24 made it tier 1: at confirm,
# earning its way up (the path it takes again after a correction returns it to confirm).
DECIDED, D.DECIDED = D.DECIDED, {}
def at_confirm(R, cls):
    st = D.load_state(R)
    st[cls]["tier"] = 3
    D.save_state(R, st)

def drive(R, cls, n, start=datetime.date(2026, 11, 2), per_day=4):
    for i in range(n):
        d = start + datetime.timedelta(days=i // per_day)
        D.append(R, {"at": f"{d.isoformat()}T09:{i % 60:02d}:00+08:00", "class": cls, "verdict": "applied", "as_drafted": True,
                     "letter": "A", "target": f"MH-{100 + i}", "source": "batch"})

with tempfile.TemporaryDirectory() as R:
    at_confirm(R, "link-named")
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
    drive(R, "release-reconcile", 10)
    D.append(R, {"at": "2026-11-04T12:00:00+08:00", "class": "release-reconcile", "verdict": "edited", "as_drafted": False, "target": "MH-9", "source": "batch"})
    check("an edit in the last ten blocks maturity", not D.judged("release-reconcile", D.record(R), D.load_state(R)["release-reconcile"])["mature"])
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
    drive(R, "release-reconcile", 10)
    g = [x for x in D.asks(R, datetime.date(2026, 11, 6), commit=True, ask_state={}) if x["kind"] == "grant"]
    D.asks(R, datetime.date(2026, 11, 11), commit=True, ask_state={g[0]["id"]: {"dropped": "2026-11-11"}})
    check("no answer changes nothing; the ask stays away", D.load_state(R)["release-reconcile"]["tier"] == 3
          and not [x for x in D.asks(R, datetime.date(2026, 11, 12), ask_state={}) if x["kind"] == "grant"])
    drive(R, "release-reconcile", 9, start=datetime.date(2026, 11, 12))
    check("nine more: still away", not [x for x in D.asks(R, datetime.date(2026, 11, 16), ask_state={}) if x["kind"] == "grant"])
    drive(R, "release-reconcile", 1, start=datetime.date(2026, 11, 16))
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
    at_confirm(R, "link-named")
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
          f"1. *ruling* · 4 links ready for MH-3735: link a child to a parent you own when a comment on the parent names it. → [[ela/dry/{b['id']}|the note]]" in page
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

D.DECIDED = DECIDED

# MH-3998, 2026-11-25: a Figma file named by a ticket key is not the ticket, and an older ticket named is a reference.
check("a Figma file's name in prose names no ticket",
      D.ticket_keys("Output Profile, design in Figma MH-2026 node 4119-5823.") == []
      and D.ticket_keys("the Figma file: MH-2026") == [] and D.ticket_keys("see MH-2026 and MH-3997") == ["MH-2026", "MH-3997"])
check("a ticket older than the parent is linked as related, never contained",
      D.older({"key": "MH-3800"}, {"key": "MH-3998"}) and not D.older({"key": "MH-4001"}, {"key": "MH-3998"})
      and D.older({"key": "MH-9", "fields": {"created": "2026-01-01T00:00:00.000+0800"}},
                  {"key": "MH-1", "fields": {"created": "2026-02-01T00:00:00.000+0800"}})
      and not D.older({"key": "EDPP-1"}, {"key": "MH-3998"}))
check("a Done ticket older than the parent is related; an older open one may still be a child",
      D.older({"key": "MH-3800"}, {"key": "MH-3998"}) and D.is_done({"fields": {"status": {"name": "Done"}}}))
check("a Figma file named with a quote or in Chinese names no ticket; a key before 'node' in prose still does",
      D.ticket_keys('Figma file "MH-2026"') == [] and D.ticket_keys("\u8bbe\u8ba1\u7a3f MH-2026") == []
      and D.ticket_keys("MH-4123 node list crash") == ["MH-4123"])

# Vault plan 2026-11-24 step 3, under the decision of 2026-11-24 (ela watches the MH board and acts on Jira, signing each
# write): link-named and parent-status are ela's own writes, not asks; a correction returns them to confirm.
with tempfile.TemporaryDirectory() as R, tempfile.TemporaryDirectory() as out:
    os.makedirs(os.path.join(R, "ela", "dry"), exist_ok=True)
    json.dump({"link-named": {"tier": 3, "history": []}, "parent-status": {"tier": 3, "history": []}},
              open(os.path.join(R, "ela", "dry", "classes.json"), "w"))
    st = D.load_state(R)
    check("the decision moves a stored tier 3 to tier 1 once, with its event",
          st["link-named"]["tier"] == 1 and st["parent-status"]["tier"] == 1
          and st["link-named"]["history"][-1]["event"] == "decided" and not D.grant_due("link-named", [], st["link-named"]))
    THU = datetime.date(2026, 11, 12)
    old = D.make_batch(R, "link-named", "MH-3735", [{"n": 1, "target": "MH-1", "command": "ela jira link MH-3735 MH-1 --type contains", "why": "w"}], [], THU)
    writes, left = D.select_link_named(parent, children, before="2026-11-12T13:18:00+08:00")
    ran = []
    def fake(cmd, apply):
        ran.append((cmd, apply)); return 0, "ok"
    TUE = datetime.date(2026, 11, 24)
    at = lambda d: datetime.datetime.combine(d, datetime.time(10, 0), D.TZ)   # the pass's clock on that day
    r = D.place(R, "link-named", "MH-3735", writes, left, TUE, apply=True, out_dir=out, runner=fake, now=at(TUE))
    check("tier 1: the set is written, not asked; yesterday's open batch for the scope settles",
          r["state"] == "applied" and len(ran) == 4 and all(a for _, a in ran)
          and D.load_batch(R, old["id"])["state"] == "settled" and not [x for x in D.asks(R, TUE, ask_state={}) if x["kind"] == "batch"])
    check("each link its own write and act, a command the class admits; no comment on the ticket (MH's Automation "
          "would copy it to the linked tickets)",
          all(__import__("re").match(D.CLASSES["link-named"]["command"], c) for c, _ in ran)
          and not [c for c, _ in ran if c.startswith("ela jira comment")])
    ran2 = []
    def half(cmd, apply):
        ran2.append(cmd); return (1, "boom") if " MH-3983 " in cmd + " " else (0, "ok")
    with tempfile.TemporaryDirectory() as R2:
        os.makedirs(os.path.join(R2, "ela", "dry"), exist_ok=True)
        r2 = D.place(R2, "link-named", "MH-3735", writes, left, TUE, apply=True, out_dir=out, runner=half, now=at(TUE))
        check("a set that fails part way stops there and posts nothing",
              r2["state"] == "failed" and not [c for c in ran2 if c.startswith("ela jira comment")])
    _, lst = D.did(R, TUE.isoformat())
    check("listed for ela/dry/did.md, each act by its batch and line", [a for a, _, _, _ in lst] == [f"{TUE}-link-named-MH-3735#{n}" for n in range(1, 5)])
    check("one set a scope a day: a second pass the same day writes nothing",
          D.place(R, "link-named", "MH-3735", writes, left, TUE, apply=True, out_dir=out, runner=fake, now=at(TUE))["state"] == "refused" and len(ran) == 4)
    n = D.correct(R, "link-named", "correction", "MH-3735", "a reply disputing a link", now=datetime.datetime(2026, 11, 24, 16, tzinfo=D.TZ))
    WED = datetime.date(2026, 11, 25)
    r = D.place(R, "link-named", "MH-3735", writes, left, WED, apply=True, out_dir=out, runner=fake, now=at(WED))
    check("a correction returns the class to confirm and the decision does not undo the fall: the next set is asked",
          "back to your confirm" in n and D.load_state(R)["link-named"]["tier"] == 3 and r["state"] == "open" and len(ran) == 4
          and [x["id"] for x in D.asks(R, WED, ask_state={}) if x["kind"] == "batch"] == [f"dry:{r['batch']}"])
    p = issue("MH-3735", issuelinks=[link(1, "contains", "MH-3983", "Review")], comment={"comments": []})
    w, _ = D.select_parent_status(p, OWNER, TUE, out)
    r = D.place(R, "parent-status", "MH-3735", w, [], TUE, apply=False, runner=fake)
    check("parent-status at tier 1: its comment goes through the act path (a dry run without --apply), no batch asked",
          r["state"] == "dry run" and ran[-1] == (w[0]["command"], False) and not D.load_batch(R, f"{TUE}-parent-status-MH-3735"))

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "brief"))
import brief as B  # noqa: E402
check("release-reconcile is the release work's own rule: the same command shape as the page check's",
      D.CLASSES["release-reconcile"]["command"] == B.PENDING_RULES["release-reconcile"])

# the owner from the env file bin/ela loads, not only from the environment
with tempfile.TemporaryDirectory() as T:
    envf = os.path.join(T, ".env")
    open(envf, "w").write("# site\nJIRA_BASE_URL=https://example.invalid\nJIRA_EMAIL='owner@example.com'\n")
    saved = os.environ.pop("JIRA_EMAIL", None)
    try:
        check("the owner is read from the env file when the environment has none", D.owner_of(None, envf) == OWNER)
        os.environ["JIRA_EMAIL"] = "env@example.com"
        check("the environment wins over the file, --owner over both",
              D.owner_of(None, envf) == "env@example.com" and D.owner_of("x@y", envf) == "x@y")
        os.environ.pop("JIRA_EMAIL")
        check("no file, no environment: no owner", D.owner_of(None, os.path.join(T, "missing")) == "")
    finally:
        if saved is not None:
            os.environ["JIRA_EMAIL"] = saved

# an unanswered batch is carried across mornings: same writes keep one batch; changed writes supersede the old one
with tempfile.TemporaryDirectory() as R:
    THU, FRI, MON = datetime.date(2026, 11, 12), datetime.date(2026, 11, 13), datetime.date(2026, 11, 16)
    writes, left = D.select_link_named(parent, children, before="2026-11-12T13:18:00+08:00")
    b1 = D.make_batch(R, "link-named", "MH-3735", writes, left, THU)
    b2 = D.make_batch(R, "link-named", "MH-3735", list(reversed(writes)), left, FRI)
    check("two days, the same writes: one batch, carried under its first id, one ask",
          b2["id"] == b1["id"] and len(D.batches(R)) == 1 and [x["id"] for x in D.asks(R, FRI, ask_state={})] == [f"dry:{b1['id']}"])
    b3 = D.make_batch(R, "link-named", "MH-3735", writes[:2], left, MON)
    old = D.load_batch(R, b1["id"])
    check("changed writes: the old batch is superseded by the new one, and only the new one is asked",
          b3["id"] != b1["id"] and old["state"] == "superseded" and old["superseded_by"] == b3["id"]
          and [x["id"] for x in D.asks(R, MON, ask_state={})] == [f"dry:{b3['id']}"])
    check("a superseded batch is not open to an answer, nor to the vault's notes",
          D.answer(R, f"dry:{b1['id']}", "A", apply=True, runner=lambda c, a: (0, ""))["did"] == [f"already superseded by {b3['id']}"]
          and sorted(V.dry_pages(R, R, MON)) == sorted(["ela/dry/did.md", f"ela/dry/{b3['id']}.md"]))
    check("another scope is not touched", D.make_batch(R, "link-named", "MH-1", writes, left, MON)["id"] != b3["id"]
          and D.load_batch(R, b3["id"])["state"] == "open")
    check("nothing left to write: the open batch closes as settled, one record line, and its ask leaves today.md",
          D.make_batch(R, "link-named", "MH-3735", [], [], MON) is None and D.load_batch(R, b3["id"])["state"] == "settled"
          and [r["batch"] for r in D.record(R) if r.get("verdict") == "settled"] == [b3["id"]]
          and not any(x.get("batch") == b3["id"] for x in D.asks(R, MON))
          and D.answer(R, f"dry:{b3['id']}", "A", apply=True, runner=lambda c, a: (0, ""))["did"] == ["already settled"])

# the review note says what each ticket is and what a --from-file comment says; the context lines are never writes
with tempfile.TemporaryDirectory() as R:
    idir = os.path.join(RT.name, "facts", "jira", "issues")
    os.makedirs(idir, exist_ok=True)
    json.dump({"key": "MH-3842", "fields": {"summary": "White Balance fix", "status": {"name": "Review"},
                                             "assignee": {"displayName": "A Dev"}, "priority": {"name": "High"}}},
              open(os.path.join(idir, "MH-3842.json"), "w"))
    txt = os.path.join(R, "c.md")
    open(txt, "w").write("UR fix is on QA.\n1. `not a write`\n")
    ws = [{"n": 1, "target": "MH-3842", "command": "ela jira link MH-3735 MH-3842 --type contains", "why": "named"},
          {"n": 2, "target": "MH-3842", "command": f"ela jira comment MH-3842 --from-file {txt}", "why": "status"},
          {"n": 3, "target": "MH-1", "command": "ela jira comment MH-1 --from-file /nonexistent/x.md", "why": "gone"}]
    b = {"id": "t", "class": "link-named", "scope": "MH-3735", "writes": ws}
    note = D.review_note(b)
    check("the note links each key with summary, status, assignee and priority from the fact store",
          "    - [MH-3842](https://tvunetworks.atlassian.net/browse/MH-3842) White Balance fix · Review · A Dev · priority High" in note
          and "    - [MH-3735](https://tvunetworks.atlassian.net/browse/MH-3735) (not in the fact store)" in note)
    check("a --from-file write carries the file's text quoted; a missing file says so",
          "    > UR fix is on QA.\n    > 1. `not a write`" in note and "    > (/nonexistent/x.md is missing)" in note)
    check("the context lines are not writes: read_note on the untouched note applies all three",
          [v for _, v, _ in D.read_note(b, note)] == ["applied", "applied", "applied"])
    hand = note.replace("1. `ela jira link", "~~1. `ela jira link", 1).replace("— named", "— named~~", 1).replace(
        "3. `ela jira comment MH-1 --from-file", "3. `ela jira comment MH-1 --text x --from-file", 1)
    check("one struck, one edited: the same verdicts as a note without context",
          [(w["n"], v) for w, v, _ in D.read_note(b, hand)] == [(1, "cancelled"), (2, "applied"), (3, "edited")])

# a batch whose writes failed is `failed`, not `applied`, and stays answerable: A again retries only what did not land
with tempfile.TemporaryDirectory() as R:
    ws = [{"n": 1, "target": "q:1", "command": "ela jira create --project MH --type Task --summary one", "why": "row"},
          {"n": 2, "target": "q:2", "command": "ela jira create --project MH --type Task --summary two", "why": "row"},
          {"n": 3, "target": "q:3", "command": "ela jira create --project MH --type Task --summary three", "why": "row"}]
    b = D.make_batch(R, "focus-moves", "mediahub-focus", ws, [], THU)
    aid = f"dry:{b['id']}"
    res = D.answer(R, aid, "A", apply=True, runner=lambda c, ap: (2, "refused: a Task ela creates carries Goal"))
    check("every write failed: the batch is failed, nothing recorded as applied",
          D.load_batch(R, b["id"])["state"] == "failed" and not D.record(R) and any("1 applied: failed" in d for d in res["did"]))
    res = D.answer(R, aid, "A", apply=True, runner=lambda c, ap: (0, "created MH-1") if "two" in c else (2, "refused"))
    st = D.load_batch(R, b["id"])
    check("a re-answer retries it, not 'already applied'; one lands, the batch stays failed for the other two",
          not any(d.startswith("already") for d in res["did"]) and st["state"] == "failed"
          and [w.get("outcome") for w in st["writes"]] == ["failed", "landed", "failed"]
          and [r["target"] for r in D.record(R)] == ["q:2"])
    calls = []
    D.answer(R, aid, "A", apply=True, runner=lambda c, ap: (calls.append(c) or (0, "created")))
    st = D.load_batch(R, b["id"])
    check("the third answer runs only the two that failed; then the batch is applied and settled",
          calls == [ws[0]["command"], ws[2]["command"]] and st["state"] == "applied"
          and sorted(r["target"] for r in D.record(R)) == ["q:1", "q:2", "q:3"]
          and D.answer(R, aid, "A", apply=True, runner=lambda c, ap: (0, ""))["did"] == ["already applied"])
    b2 = D.make_batch(R, "focus-moves", "other", ws[:2], [], THU)
    D.answer(R, f"dry:{b2['id']}", "A", apply=True, runner=lambda c, ap: (0, "") if "one" in c else (2, "no"))
    res = D.answer(R, f"dry:{b2['id']}", "B")
    check("B on a partly failed batch drops only the write that failed; the landed one stays applied",
          res["did"] == ["dropped 1"] and D.load_batch(R, b2["id"])["state"] == "dropped"
          and [(r["target"], r["verdict"]) for r in D.record(R) if r.get("batch") == b2["id"]] == [("q:1", "applied"), ("q:2", "cancelled")])

# a failed batch reaches him: one ask on today.md naming the writes that failed and why; A retries only those
with tempfile.TemporaryDirectory() as R:
    ws = [{"n": i, "target": f"q:{i}", "command": f"ela jira create --project MH --type Task --summary s{i}", "why": "row"} for i in (1, 2, 3)]
    b = D.make_batch(R, "focus-moves", "mediahub-focus", ws, [], THU)
    D.answer(R, f"dry:{b['id']}", "A", apply=True,
             runner=lambda c, ap: (0, "created MH-9") if "s2" in c else (2, "DRY RUN\nrefused: a Task ela creates carries Goal"))
    a = D.asks(R, THU, ask_state={})
    x = a[0] if len(a) == 1 else {}
    check("a failed batch is one ask: its own id, the class, which writes failed, each with its reason",
          x.get("id") == f"dry:{b['id']}:retry" and x["question"].startswith("2 of 3 board moves for mediahub-focus failed (focus-moves")
          and x["record"] == "1 q:1: refused: a Task ela creates carries Goal; 3 q:3: refused: a Task ela creates carries Goal")
    check("its options: A retry the failed writes (recommended), B drop them",
          [(o["letter"], o["text"], o["recommended"]) for o in x["options"]] == [("A", "retry the failed writes", True), ("B", "drop them", False)]
          and x["options"][0]["does"] == f"ela dry answer dry:{b['id']}:retry A --apply"
          and x["options"][1]["does"] == f"ela dry answer dry:{b['id']}:retry B")
    calls = []
    D.answer(R, x["id"], "A", apply=True, runner=lambda c, ap: (calls.append(c) or (0, "created")))
    check("A on the retry ask runs only the failed writes; the batch is applied and leaves today.md",
          calls == [ws[0]["command"], ws[2]["command"]] and D.load_batch(R, b["id"])["state"] == "applied" and D.asks(R, THU, ask_state={}) == [])
    b2 = D.make_batch(R, "focus-moves", "other", ws[:2], [], THU)
    D.answer(R, f"dry:{b2['id']}", "A", apply=True, runner=lambda c, ap: (0, "") if "s1" in c else (2, "no"))
    D.asks(R, THU, commit=True, ask_state={f"dry:{b2['id']}:retry": {"dropped": "2026-11-28"}})
    check("three mornings unanswered: the failed batch expires like an open one, the unlanded write recorded expired",
          D.load_batch(R, b2["id"])["state"] == "expired"
          and [(r["target"], r["verdict"]) for r in D.record(R) if r.get("batch") == b2["id"]] == [("q:1", "applied"), ("q:2", "expired")])

print(f"{len(failures)} failed" if failures else "all passed")
sys.exit(1 if failures else 0)
