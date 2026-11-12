#!/usr/bin/env python3
"""A mention of the owner, offline, on a temp store (ADR 0021): a bot's notice and an FYI are recorded and never
raised; a thread he answers inside the wait produces no message and, where his reply commits to something, dry runs
by class; an ask left unanswered produces one message with the facts, a reply to paste and A / B / C; a prod incident
produces its facts at once and no draft; his reply while a draft is pending withdraws it; outside his hours the ask
takes a slot on today.md. Nothing reaches Slack or Jira: threads and tickets are fixtures."""
import datetime, json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "mention"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "vault"))
import mention as M  # noqa: E402
import vault as V  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

ME, ASKER, PEER, BOT, CH = "U0ME", "U0ASK", "U0PEER", "U0BOT", "C0DEV"
DAY = {"wait": 30, "hours": ("08:30", "19:00"), "holidays": []}
def at(h, m, d=12):
    return datetime.datetime(2026, 11, d, h, m, tzinfo=M.TZ)
def ts(h, m, d=12, n=0):
    return f"{at(h, m, d).timestamp():.0f}.{n:06d}"
def msg(t, user, text, **more):
    return dict({"ts": t, "user": user, "text": text}, **more)

# window: the wait runs in his working time only
check("an ask at 10:00 is due at 10:30 and may be sent", M.window(DAY, at(10, 0)) == (at(10, 30), False))
check("an ask at 03:39 is held, its wait running from 08:30", M.window(DAY, at(3, 39)) == (at(9, 0), True))
check("an ask at 18:50 is held, the rest of its wait next morning", M.window(DAY, at(18, 50)) == (at(8, 50, 13), True))
check("a Friday evening ask is held to Monday", M.window(DAY, at(18, 50, 13)) == (at(8, 50, 16), True))
check("a weekend ask is held to Monday", M.window(DAY, at(11, 0, 14)) == (at(9, 0, 16), True))
check("a holiday is not a working day", M.window(dict(DAY, holidays=["2026-11-12"]), at(10, 0)) == (at(9, 0, 13), True))

# triage: the closed vocabulary
T = lambda text, bot=False, ch="dev": M.triage(text, ME, bot, ch)
check("a bot's ready-to-test is a notice", T(f"build 91 sent <@U0QA> <@{ME}> QA can start", bot=True) == ("notice", "bot-notice"))
check("a link's own question mark asks nothing", T(f"<@{ME}> synced this thread with <https://x.example/browse/MH-1?focusedCommentId=2|MH-1>", bot=True) == ("notice", "bot-notice"))
check("a bot that asks is an ask", T(f"<@{ME}> can you decide whether this ships?", bot=True) == ("ask", "question"))
check("the tags before an FYI are a notice", T(f"<@U0X> use cn-north-1 <@U0Y> <@{ME}> FYI") == ("notice", "fyi-tail"))
check("a cc is a notice", T(f"<@U0X> retest result (cc <@{ME}>): it switches") == ("notice", "cc-tail"))
check("named first, another's FYI after: an ask", T(f"<@{ME}> <@U0X> is Prod4 deleted too? please confirm <@U0Y> FYI") == ("ask", "question"))
check("a bare mention is an ask", T(f"<@U0X> <@{ME}>") == ("ask", "bare-mention"))
check("a statement that names him is an ask", T(f"this customer is with <@{ME}>, a real use case") == ("ask", "addressed"))
check("prod and a failure, addressed to him: an incident", T(f"<@{ME}> prod-3 is down, every graph fails to start") == ("incident", "incident"))
check("a failure in a prod channel is an incident", T(f"<@{ME}> the encoder crashed for the customer", ch="prod-mediahub") == ("incident", "incident"))
check("an incident he is only copied on is a notice", T(f"prod-3 is down, <@U0X> is on it. cc <@{ME}>") == ("notice", "cc-tail"))

OWNER = "owner@example.com"
def para(text):
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}
def issue(key, parent=None, status="Backlog", **f):
    return {"key": key, "url": f"https://jira.example/browse/{key}",
            "fields": dict({"summary": f"{key} summary", "status": {"name": status}, "parent": {"key": parent} if parent else None}, **f)}
ISSUES = {k: issue(k) for k in ("MH-3983", "MH-3842", "MH-3869")}
ISSUES["MH-3735"] = issue("MH-3735", assignee={"emailAddress": OWNER, "displayName": "Owner"}, customfield_11252="ur-caller@2.1.90",
                          issuelinks=[{"id": 1, "type": {"outward": "contains", "inward": "is contained in"},
                                       "outwardIssue": {"key": "MH-3990", "fields": {"status": {"name": "Backlog"}, "summary": "MH-3990 summary"}}}],
                          comment={"comments": [{"id": "9", "author": {"displayName": "a colleague"}, "created": "2026-11-11T12:10:14.614-0800",
                                                 "body": {"type": "doc", "content": [para("CSC: MQTT support is finished (MH-3983)."),
                                                                                    para("White Balance: UR needs a small fix (MH-3842)."),
                                                                                    para("Related: MH-3869.")]}}]})

with tempfile.TemporaryDirectory() as tmp:
    R, SL = os.path.join(tmp, "reports"), os.path.join(tmp, "slack")
    os.makedirs(SL)
    json.dump({"users": {ME: {"name": "Owner", "is_bot": False}, ASKER: {"name": "Asker", "is_bot": False}, PEER: {"name": "Peer", "is_bot": False},
                         BOT: {"name": "relbot", "is_bot": True}}, "emails": {OWNER: {"id": ME}}}, open(os.path.join(SL, "users.json"), "w"))
    json.dump({"channels": [{"id": CH, "name": "dev"}, {"id": "C0PROD", "name": "prod-mediahub"}]}, open(os.path.join(SL, "channels.json"), "w"))
    names = M.Names(SL, None)
    check("the owner's id comes from the store's users file", names.me == ME)
    ctx = {"reports": R, "owner": OWNER, "read": ISSUES.get, "who": lambda uid, name: "peer@example.com" if uid == PEER else None,
           "names": names, "today": datetime.date(2026, 11, 12), "runtime": os.path.join(tmp, "runtime")}
    recs = {}
    def walk(channel, thread, now, top=None):
        ids = M.process(recs, R, channel, thread, names, DAY, now, None, top)
        M.settle_hours(recs, DAY, now, R)
        M.follow_replies(recs, ids, {"slack": SL}, names, {(channel, thread[0]["ts"]): thread}, ctx)
        return ids
    def todo(now):
        return {d["id"]: d for d in M.todo(recs, DAY, now)}

    # notices: recorded with their reason, never raised
    n1 = walk(CH, [msg(ts(9, 0), BOT, f"build 91 sent <@U0QA> <@{ME}> QA can start")], at(9, 1))[0]
    n2 = walk(CH, [msg(ts(9, 5), ASKER, f"<@{PEER}> all regions use cn-north-1 <@{ME}> FYI")], at(9, 6))[0]
    check("notices are on record", recs[n1]["state"] == recs[n2]["state"] == "notice" and recs[n2]["reason"] == "fyi-tail")
    check("a notice is never raised: nothing to do, days later", not todo(at(9, 40)) and not todo(at(12, 0, 13)) and not M.asks(R))

    # he answers inside the wait: no message; his reply's commitments are dry runs by class
    t1 = [msg(ts(10, 0), ASKER, f"<@{ME}> MH-3735 is missing the module tickets, can you link them?"),
          msg(ts(10, 10), ME, f"I'll link these to MH-3735 and update the parent. <@{PEER}> please take MH-3842. "
                              "Will open a ticket for the mixer setting. I will ask the PM about the date.")]
    walk(CH, t1[:1], at(10, 1))
    a1 = f"{CH}-{ts(10, 0)}"
    check("an ask waits: a timer, no draft, no message", recs[a1]["state"] == "waiting" and todo(at(10, 1))[a1]["do"] == "timer"
          and todo(at(10, 1))[a1]["at"] == M.iso(at(10, 30)))
    walk(CH, t1, at(10, 11))
    f = recs[a1].get("follow") or {}
    check("his reply closes the mention for ela, inside the window", recs[a1]["state"] == "replied" and recs[a1]["in_window"] and a1 not in todo(at(11, 0)))
    check("link-named: one batch on the parent he owns, from the tickets its text names",
          [(x["key"], x["writes"]) for x in f["by_class"].get("link-named", [])] == [("MH-3735", 3)])
    b = json.load(open(os.path.join(R, "ela", "dry", "batches", f"2026-11-12-link-named-MH-3735.json")))
    check("the batch is a dry run in dry's store, each write the exact command",
          b["state"] == "open" and [w["command"] for w in b["writes"]] == ["ela jira link MH-3735 MH-3983 --type contains",
                                                                          "ela jira link MH-3735 MH-3842 --type contains",
                                                                          'ela jira link MH-3735 MH-3869 --type "relates to"'])
    check("parent-status: a status comment batch on the same parent", [(x["key"], x["writes"]) for x in f["by_class"].get("parent-status", [])] == [("MH-3735", 1)])
    asg = f["by_class"].get("assign-by-rule", [])
    check("assign-by-rule: the person he named, by the roster's email",
          len(asg) == 1 and json.load(open(os.path.join(R, "ela", "dry", "batches", asg[0]["batch"] + ".json")))["writes"][0]["command"]
          == "ela jira assign MH-3842 --assignee peer@example.com")
    check("file a ticket: a local draft, nothing created", len(f["tickets"]) == 1 and "Filed only on the owner's word" in open(f["tickets"][0]).read())
    check("a promise no class covers is listed, not acted on", len(f["unmapped"]) == 1 and "ask the PM" in f["unmapped"][0])
    again = walk(CH, t1, at(10, 20))
    check("a second walk prepares nothing twice", again == [] and recs[a1]["follow"]["at"] == f["at"])

    # unanswered: one message with the facts, a reply to paste and A / B / C
    t2 = [msg(ts(11, 0), ASKER, f"<@{ME}> which build fixes MH-3735? MH-3842 too, and MH-7001")]
    walk(CH, t2, at(11, 1))
    a2 = f"{CH}-{ts(11, 0)}"
    check("before the wait ends: a timer", todo(at(11, 20))[a2]["do"] == "timer")
    check("the wait over, in his hours: a draft is owed, for a message", todo(at(11, 31))[a2] == {"id": a2, "permalink": recs[a2]["permalink"], "triage": "ask",
                                                                                                   "do": "draft", "route": "dm"})
    related = lambda k, skip: [{"link": "https://slack.example/archives/C0QA/p1", "channel": "qa", "date": "2026-11-10", "first": "build 90 carries it", "id": "x"}] if k == "MH-3735" else []
    recs[a2]["facts"] = M.gather(recs[a2], t2, names, ISSUES.get, related)
    lines = recs[a2]["facts"]["lines"]
    check("facts: each ticket with its state, owner and Fixed In, as a link; the related thread; what was not read",
          lines[0] == "<https://jira.example/browse/MH-3735|MH-3735> Backlog · Owner · Fixed In ur-caller@2.1.90 · MH-3735 summary"
          and "no Fixed In" in lines[1] and lines[2].startswith("<https://slack.example/archives/C0QA/p1|#qa 11-10> names MH-3735")
          and lines[3] == "not read (not in the Jira fact store): MH-7001" and len(lines) <= M.FACT_LINES)
    path, text = M.make_draft(recs[a2], R, "Asker asks which build carries the MH-3735 fix.", "It is in build 90. I'll link MH-3842 to MH-3735.", at(11, 32))
    check("the message: the ask, the facts, the reply to paste, the dry runs it implies, the three letters",
          "Asker asks which build" in text and "*Facts*" in text and "```\nIt is in build 90." in text
          and "links · MH-3842, MH-3735 (link-named)" in text
          and "*A* use this draft · *B* I will write it · *C* nothing needed" in text and "ela posts nothing" in text and open(path).read() == text)
    d = todo(at(11, 33))[a2]
    check("drafted: one message to send him", d["do"] == "dm" and d["kind"] == "ask" and d["text"] == path)
    recs[a2].update(dm_at=M.iso(at(11, 34)), dm_ts="1794.000100")
    check("sent: nothing more to do", a2 not in todo(at(12, 0)))
    M.save(R, recs)
    r = M.answer(R, "1794.000100", "a", ctx, at(11, 40))
    check("A by the message's ts: answered, and the draft's commitment is prepared by class",
          r["state"] == "answered" and r["answer"]["letter"] == "A" and r["follow"]["source"] == "draft" and "link-named" in r["follow"]["by_class"])
    recs = M.load(R)

    # his reply while a draft is pending withdraws it
    t3 = [msg(ts(14, 0), ASKER, f"<@{ME}> is overlay an admin control?")]
    walk(CH, t3, at(14, 1))
    a3 = f"{CH}-{ts(14, 0)}"
    recs[a3]["facts"] = M.gather(recs[a3], t3, names, ISSUES.get, lambda k, s: [])
    M.make_draft(recs[a3], R, "Asker asks whether overlay is an admin control.", "A deployment config for now.", at(14, 31))
    recs[a3].update(dm_at=M.iso(at(14, 32)), dm_ts="1794.000200")
    walk(CH, t3 + [msg(ts(14, 40), ME, "Deployment config, not an admin switch.")], at(14, 41))
    check("withdrawn without a word", recs[a3]["state"] == "withdrawn" and a3 not in todo(at(14, 42)) and recs[a3]["in_window"] is False)
    M.save(R, recs)
    try:
        M.answer(R, a3, "A", ctx, at(14, 50)); late = False
    except ValueError:
        late = True
    check("a letter on a withdrawn draft is refused", late)

    # a prod incident: the facts at once, at any hour, no draft
    t4 = [msg(ts(22, 0), ASKER, f"<@{ME}> prod-3 is down since 21:50, MH-3735 graphs fail to start")]
    i4 = walk("C0PROD", t4, at(22, 1))[0]
    M.make_incident(recs[i4], R, t4, names, ISSUES.get, at(22, 1), lambda k, s: [])
    d = todo(at(22, 2))[i4]
    itext = open(d["text"]).read()
    check("an incident is to send at once, outside his hours too", recs[i4]["state"] == "incident" and d["do"] == "dm" and d["kind"] == "incident")
    check("its message is the facts, with no reply drafted and no letters",
          "MH-3735" in itext and "*Facts*" in itext and "Draft reply" not in itext and "*A*" not in itext and "No reply is drafted" in itext)

    # outside his hours: no message; an ordinary ask slot on today.md
    t5 = [msg(ts(21, 0), ASKER, f"<@{ME}> can we ship MH-3842 on Friday?")]
    walk(CH, t5, at(21, 1))
    a5 = f"{CH}-{ts(21, 0)}"
    M.save(R, recs)
    check("held: a draft owed for today.md, never a message", recs[a5]["hold"] and todo(at(21, 5))[a5] == {"id": a5, "permalink": recs[a5]["permalink"],
                                                                                                         "triage": "ask", "do": "draft", "route": "today"}
          and todo(at(9, 30, 13))[a5]["route"] == "today")
    ask = [x for x in M.asks(R) if x["id"] == f"mention:{a5}"]
    check("before a draft the slot offers B and C under his letters", len(ask) == 1 and [o["letter"] for o in ask[0]["options"]] == ["B", "C"])
    recs[a5]["facts"] = M.gather(recs[a5], t5, names, ISSUES.get, lambda k, s: [])
    M.make_draft(recs[a5], R, "Asker asks whether MH-3842 can ship on Friday.", "Yes, once QA signs off.", at(7, 50, 13))
    M.save(R, recs)
    ask = [x for x in M.asks(R) if x["id"] == f"mention:{a5}"][0]
    check("drafted: A use this draft · B I will write it · C nothing needed, each a local answer",
          [(o["letter"], o["text"], o["does"]) for o in ask["options"]] == [("A", "use this draft", f"ela mention answer {a5} A"),
                                                                             ("B", "I will write it", f"ela mention answer {a5} B"),
                                                                             ("C", "nothing needed", f"ela mention answer {a5} C")]
          and ask["link"] == f"ela/mentions/{a5}" and todo(at(8, 0, 13))[a5]["do"] == "today")
    pg = M.page(recs[a5])
    check("its page: the thread, the facts as Markdown links, the reply in a fence",
          "[The thread](" in pg and "[MH-3842](https://jira.example/browse/MH-3842)" in pg and "```\nYes, once QA signs off.\n```" in pg)
    wl = [x["line"] for x in M.waiting(R)]
    check("Waiting on you: the open asks, with the thread and the tickets linked; answered and noticed ones left out",
          any(a5 in x["id"] for x in M.waiting(R)) and any("**Asker, 11-12** ([thread](" in l and "[MH-3842](" in l and "ship on Friday" in l for l in wl)
          and not any(x["id"] in (a1, a2, a3, n1, n2) for x in M.waiting(R)))
    # the vault: the slot, its page, and a letter the sync settles itself
    t10 = [msg(ts(21, 30), PEER, f"<@{ME}> who owns MH-3869?")]
    walk(CH, t10, at(21, 31))
    a10 = f"{CH}-{ts(21, 30)}"
    M.save(R, recs)
    FRI = datetime.date(2026, 11, 13)
    cands = {c["id"]: c for c in V.mention_asks(R, FRI)}
    c5, c10 = cands[f"mention:{a5}"], cands[f"mention:{a10}"]
    check("today.md: a held mention is an ordinary ask candidate, whole, linked to its page, his letters kept",
          c5["whole"] and c5["link"] == f"ela/mentions/{a5}" and [o["letter"] for o in V.ask_options(c5)] == ["A", "B", "C"]
          and [o["letter"] for o in V.ask_options(c10)] == ["B", "C"] and c5["text"].startswith("Asker asked you in #dev on 11-12 21:00, no reply yet: "))
    pages = V.mention_pages(R, FRI)
    check("the vault page of each held mention, typed", set(pages) == {f"ela/mentions/{a5}.md", f"ela/mentions/{a10}.md"}
          and 'type: "mention"' in pages[f"ela/mentions/{a5}.md"] and "## Draft reply" in pages[f"ela/mentions/{a5}.md"])
    st = {}
    does = V.ask_options(c10)[0]["does"]
    check("a letter on it is settled by the sync: nothing leaves ela", V.sync_handles(does) and V.settle_one(R, st, c10["id"], "B", does, FRI)
          and st[c10["id"]]["answered"]["letter"] == "B" and M.load(R)[a10]["answer"]["letter"] == "B")
    recs = M.load(R)
    check("B keeps it under Waiting on you until he replies; it leaves today.md", any(x["id"] == a10 for x in M.waiting(R))
          and f"mention:{a10}" not in {c["id"] for c in V.mention_asks(R, FRI)})
    Q = V.questions_mod()
    note = Q.meeting_note({"questions": {}}, "sync-eng-qa", "Team sync · Fri 2026-11-13", FRI, at(8, 0, 13), lambda k: None, "Owner", "", {}, None,
                          V.mention_waiting(R))
    check("a built meeting note's Waiting on you is the store's open mentions, each a line with its thread",
          "## Waiting on you\n\n- **Asker, 11-12** ([thread](" in note and note.count("([thread](") == len(M.waiting(R)) and "MH-3869" in note)
    VT = os.path.join(tmp, "vault")
    mt = [{"key": "sync-eng-qa", "name": "Team sync", "weekdays": ["Fri"], "time": "10:00", "audience": ["engineering", "qa"]},
          {"key": "scrum-pm", "name": "Scrum", "weekdays": ["Fri"], "time": "11:00", "audience": "product"}]
    built = V.build_meeting_notes(VT, {"questions": {}, "built": {}}, at(8, 0, 13), mt, lambda k: None, "Owner", "", waiting=V.mention_waiting(R))
    texts = {os.path.basename(p): open(os.path.join(VT, p)).read() for p in built}
    check("it goes to the note whose audience includes engineering, not to the product scrum",
          "Waiting on you" in texts["2026-11-13-sync-eng-qa.md"] and "Waiting on you" not in texts["2026-11-13-scrum-pm.md"])
    r = M.answer(R, a5, "C", ctx, at(9, 0, 13))
    tl = M.tally(R)
    check("C closes it and counts against that kind of message", r["state"] == "closed" and tl["question"]["C"] == 1 and tl["question"]["A"] == 1
          and tl["question"]["B"] == 1 and tl["question"]["withdrawn"] == 1 and tl["bot-notice"]["fired"] == 1 and tl["bot-notice"]["kind"] == "notice" and not M.asks(R))
    recs = M.load(R)

    # the thread walk: a second mention joins the open one, a mention after his reply opens another; a reaction is a reply
    t6 = [msg(ts(15, 0), ASKER, f"<@{PEER}> retest done <@{ME}> FYI"), msg(ts(15, 5), PEER, f"<@{ME}> does this block the release?"),
          msg(ts(15, 6), ASKER, f"<@{ME}> please advise")]
    ids = walk(CH, t6, at(15, 7))
    a6 = f"{CH}-{ts(15, 0)}"
    check("a notice, then an ask in the same thread: one record, waiting from the ask", ids == [a6] and recs[a6]["state"] == "waiting"
          and recs[a6]["due_at"] == M.iso(at(15, 35)) and len(recs[a6]["mentions"]) == 3 and recs[a6]["by_name"] == "Peer"
          and recs[a6]["first"].endswith("does this block the release?"))
    walk(CH, t6 + [msg(ts(15, 20), ME, "No."), msg(ts(16, 0), PEER, f"<@{ME}> and the CN lane?")], at(16, 1))
    a7 = f"{CH}-{ts(16, 0)}"
    check("after his reply, a new mention is a new wait", recs[a6]["state"] == "replied" and recs[a7]["state"] == "waiting")
    t8 = [msg(ts(16, 30), ASKER, f"<@{ME}> thoughts?", reactions=[{"name": "eyes", "users": [ME]}])]
    a8 = walk(CH, t8, at(16, 31))[0]
    check("his reaction is his reply; there are no words to read for commitments", recs[a8]["state"] == "replied" and recs[a8]["reply_how"] == "reaction" and not recs[a8].get("follow"))
    t9 = [msg(ts(16, 40), ASKER, f"<@{ME}> which pool?")]
    a9 = walk(CH, t9, at(16, 45), {ts(16, 40): t9[0], ts(16, 44): msg(ts(16, 44), ME, f"<@{ASKER}> the BYOR pool")})[0]
    check("an answer beside the message that tags the asker is his reply", recs[a9]["state"] == "replied" and recs[a9]["reply_how"] == "channel")
    check("an ask that fell due after hours is held from then on", (M.settle_hours(recs, DAY, at(20, 0), R), recs[a7]["hold"])[1] is True)
    M.settle_hours(recs, DAY, at(9, 0, 19), R)
    check("an ask open more than three working days is closed as expired, kept", recs[a7]["state"] == "closed" and "expired" in recs[a7]["closed"]["why"])

    # the commitments reader
    C = lambda s: [c["class"] for c in M.commitments(s)[0]]
    check("Chinese vocabulary maps to the same classes", C("我来关联到 MH-1。") == ["link-named"] and C("更新一下父票的状态") == ["parent-status"]
          and C(f"MH-2 交给 <@{PEER}>") == ["assign-by-rule"] and C("我建个票跟踪") == ["ticket-draft"])
    check("a plain answer commits to nothing", M.commitments("It is in build 90. Deployment config, not an admin switch.") == ([], []))

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
