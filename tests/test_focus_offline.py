#!/usr/bin/env python3
"""The focus board offline: holds, rows, meeting views, carries, the up/down words, the scrum import and the one batch.
Nothing here reads or writes Jira, Slack or mail: the fact store, the vault and the report are files in a temp dir."""
import datetime, json, os, re, shlex, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "focus"))
import focus as F  # noqa: E402
import hold as H  # noqa: E402
import scrum as S  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "skills", "dry"))
import dry as D  # noqa: E402
# The ladder's machinery is replayed here on the classes that stopped drafting (dry.NOT_DRAFTED): the ladder stays in
# place, dormant, so its tests stay; tests/test_dry_not_drafted_offline.py holds that neither class drafts.
D.NOT_DRAFTED.clear()

fails = []


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


TODAY = datetime.date(2026, 11, 20)

# ── holds ─────────────────────────────────────────────────────────────────────────────────────────────────────────
st = {"holds": {}, "read": {}}
H.seed(st, TODAY)
check("the seed holds MH-4061 from the owner's word of 2026-11-20, until resumed",
      H.held_keys(st, TODAY) == {"MH-4061"} and st["holds"]["MH-4061"]["since"] == "2026-11-20" and not st["holds"]["MH-4061"]["until"])
check("a seed already in the store is not added again", (H.seed(st, TODAY), len(st["holds"]))[1] == 1)
h = H.put_hold(st, "SCTE-35 copier rework", "12-01", TODAY, "today.md")
check("a hold by words carries no key; `until 12-01` is a date", h["keys"] == [] and h["until_date"] == "2026-12-01")
check("a key-less hold holds an item whose text carries all its words",
      H.holding(st, text="Media queue: SCTE-35 copier rework order", today=TODAY) and not H.holding(st, text="SCTE-35 passthrough", today=TODAY))
check("a hold by key holds the item by its key, whatever its words", H.holding(st, ["MH-4061"], "", TODAY))
check("its date ends it that morning, kept with the day it ended",
      not H.holding(st, text="SCTE-35 copier rework", today=datetime.date(2026, 12, 1))
      and [x["id"] for x in H.expire(st, datetime.date(2026, 12, 1))] == [h["id"]] and st["holds"][h["id"]]["ended"] == "2026-12-01")
ev = H.put_hold(st, "MH-3997 output profile", "the 2.2 branch", TODAY, "x")
check("`until` an event holds until resumed", ev["until"] == "the 2.2 branch" and ev["until_date"] is None and H.holding(st, ["MH-3997"], "", TODAY + datetime.timedelta(days=90)))

with tempfile.TemporaryDirectory() as t:
    vault, reports = os.path.join(t, "vault"), os.path.join(t, "reports")
    os.makedirs(os.path.join(vault, "projects")); os.makedirs(os.path.join(vault, "reference"))
    a = os.path.join(vault, "reference", "a.md")
    open(a, "w").write("# A\n\n- ela: hold MH-3510 (HTML module API) until 2026-12-15\n> ela: hold the Grafana panel\n")
    os.utime(a, (1, 1))
    b = os.path.join(vault, "today.md")
    open(b, "w").write("# Today\n\nela: resume MH-3510\n")
    os.utime(b, (2, 2))
    got, did = H.refresh(reports, vault, TODAY)
    check("his hold and resume lines anywhere in the vault, in the order written: the resume after the hold ends it",
          [d[0] for d in did] == ["hold", "hold", "resume"] and "MH-3510" not in H.held_keys(got, TODAY)
          and H.holding(got, text="the grafana panel is flaky", today=TODAY) and got["holds"]["MH-3510"]["ended_by"].startswith("resume"))
    _, again = H.refresh(reports, vault, TODAY)
    check("each line is read once: a second pass does nothing", again == [] and os.path.exists(os.path.join(reports, "ela", "holds.json")))

# ── the board ─────────────────────────────────────────────────────────────────────────────────────────────────────
DOC = {"meetings": [{"name": "Scrum with the PM", "key": "scrum-pm", "weekdays": ["Mon", "Fri"], "time": "10:00", "audience": "product", "enabled": True},
                    {"name": "Engineering + QA + UX sync", "key": "sync-eng-qa-ux", "weekdays": ["Tue", "Thu"], "time": "", "enabled": False}],
       "holidays": [], "day": {}}


def issue(facts, key, summary, prio, status="In Progress", who="Dev One", due=None, labels=(), updated="2026-11-19T10:00:00.000+0800"):
    json.dump({"key": key, "fields": {"summary": summary, "priority": {"name": prio}, "status": {"name": status, "statusCategory": {"key": "indeterminate"}},
                                      "assignee": {"displayName": who} if who else None, "duedate": due, "labels": list(labels),
                                      "resolution": None, "updated": updated}},
              open(os.path.join(facts, "jira", "issues", f"{key}.json"), "w"))


def question(qid, text, who, lead=(), audience="scrum-pm", first="2026-11-10", where="archive/meetings/2026-11-10-scrum-pm.md"):
    return {"id": qid, "text": text, "raw": text, "who": who, "keys": list(lead), "lead": list(lead), "audience": audience,
            "first": {"date": first, "where": where}, "meetings": [], "sources": [f"{where}#{text.lower()}"], "status": "open",
            "thing": {"kind": "topic", "name": "Other"}}


with tempfile.TemporaryDirectory() as t:
    vault, reports, facts = (os.path.join(t, x) for x in ("vault", "reports", "facts"))
    for d in (os.path.join(vault, "projects", "sb"), os.path.join(vault, "projects", "mine"), os.path.join(facts, "jira", "issues"), os.path.join(reports, "ela")):
        os.makedirs(d)
    env = os.path.join(t, ".env"); open(env, "w").write("JIRA_BASE_URL=https://j\n")
    s = {"vault": vault, "reports": reports, "runtime": t, "env": env}
    os.rename(facts, os.path.join(t, "facts")); facts = os.path.join(t, "facts")
    json.dump({"issues": [{"fields": {"assignee": {"displayName": "The Owner"}}}]}, open(os.path.join(facts, "jira", "owner.json"), "w"))
    issue(facts, "MH-1", "Highest and due soon", "Highest", due="2026-11-25")
    issue(facts, "MH-2", "High, due later", "High", due="2026-12-20")
    issue(facts, "MH-3", "High, no due date " + "x" * 80, "High", who=None)
    issue(facts, "MH-4", "High, labelled", "High", labels=["mh-focus"])
    issue(facts, "MH-5", "High in the backlog", "High", status="Backlog")
    issue(facts, "MH-6", "High untouched since spring", "High", updated="2026-04-01T10:00:00.000+0800")
    issue(facts, "MH-4061", "Seamless switching turns 10-bit into 8-bit", "Highest")
    issue(facts, "MH-7", "Medium, asked about", "Medium", who=None)
    open(os.path.join(vault, "projects", "sb", "sb.md"), "w").write('---\ntitle: "Super Bowl"\ntype: "project"\ndeadline: "2027-02-14"\n'
                                                                    'channels: ["https://x.slack.com/archives/C1/p1"]\nkeys: []\n---\n\n# Super Bowl\n\n## Next step\n\nBook the encoder.\n')
    open(os.path.join(vault, "projects", "mine", "mine.md"), "w").write('---\ntitle: "My own tidy-up"\ntype: "project"\nkeys: []\n---\n\n# Mine\n')
    qs = {"questions": {
        "q-aaaaaa": question("q-aaaaaa", "MH-7 — who takes it, and by when?", "Dev Two", ["MH-7"]),
        "q-bbbbbb": question("q-bbbbbb", "Amazon DR: add a freeze-frame failover trigger?", "Dev Two"),
        "q-cccccc": question("q-cccccc", "andyBot left no Fixed In: can its release step cover it?", "andyzhao", where="releases/agents/andybot"),
    }}
    json.dump(qs, open(os.path.join(reports, "ela", "questions.json"), "w"))
    before = datetime.datetime(2026, 11, 20, 9, 0)
    b = F.board(s, now=before, write=True, doc=DOC)
    rows = b["rows"]
    check("tickets: High or Highest out of the backlog and moved in thirty days; a label adds nothing",
          {"MH-1", "MH-2", "MH-3", "MH-4"} <= set(rows) and not {"MH-5", "MH-6"} & set(rows))
    check("a held ticket leaves the board and its views", "MH-4061" not in rows and "MH-4061" in b["held"])
    ids = [r["id"] for r in F.order(list(rows.values()))]
    check("order: Jira priority first, then due date", ids.index("MH-1") < ids.index("MH-2") < ids.index("MH-3") < ids.index("MH-4"))
    check("a question with a ticket joins that ticket's row; one without is a row with no ticket yet",
          rows["MH-7"]["questions"] == ["q-aaaaaa"] and "q:q-bbbbbb" in rows and rows["q:q-bbbbbb"]["key"] is None)
    check("a project with a team thread is a row; one without is the owner's own; a question on ela's own pages is ela's",
          rows["p:sb"]["own"] is False and rows["p:mine"]["own"] is True and rows["q:q-cccccc"]["own"] is True)
    page = open(os.path.join(vault, "meetings", "focus.md")).read()
    row3 = next(l for l in page.splitlines() if l.startswith("- [MH-3]"))
    check("a row is one line: the item clipped, owner, state, next step; the detail folded under it",
          "…" in row3 and " — nobody · In Progress" in row3 and "> [!note]- detail" in page and "x" * 80 in page)
    check("the board: views first, then Now, a held line folded, open questions linked",
          page.index("## Scrum with the PM · Fri 11-20") < page.index("## Now") and "> [!note]- Held (1): [MH-4061](https://j/browse/MH-4061)" in page
          and "[[meetings/open-questions|open questions]]" in page and 'type: "board"' in page)
    v = b["views"]
    check("a view per enabled meeting with a time, at most seven rows; the disabled sync has none",
          [x["key"] for x in v] == ["scrum-pm"] and 0 < len(v[0]["rows"]) <= F.VIEW_MAX
          and "MH-7" in [r["id"] for r in v[0]["rows"]] and "p:sb" in [r["id"] for r in v[0]["rows"]])
    check("a view's link target is the board's heading", F.view_anchor(v[0]) == "meetings/focus#Scrum with the PM · Fri 11-20")

    # carried: only a row the meeting's report shows raised and left without a ruling (decision 2026-11-24)
    after = datetime.datetime(2026, 11, 20, 12, 0)
    b2 = F.board(s, now=after, write=True, doc=DOC)
    check("after the meeting, before its report: nothing is carried, the view waits in the store for it",
          b2["carried"] == [] and not b2["all"]["MH-7"]["carried"] and "scrum-pm@2026-11-20" in b2["state"]["past"])
    check("the next view is the next meeting's", b2["views"][0]["date"] == datetime.date(2026, 11, 23))
    b2 = F.board(s, now=after, write=True, doc=DOC, ruled=("scrum-pm", "2026-11-20", ["MH-2"], ["MH-7", "MH-1", "MH-2"]))
    check("the report raised MH-7 and MH-1 without a ruling: each carried once",
          ("MH-7", 1) in b2["carried"] and b2["all"]["MH-7"]["carried"] == ["2026-11-20"] and b2["all"]["MH-1"]["carried"] == ["2026-11-20"])
    check("a row on the view the report never names was not reached: not carried; a row it ruled is not either",
          not b2["all"]["p:sb"]["carried"] and not b2["all"]["MH-2"]["carried"] and "scrum-pm@2026-11-20" not in b2["state"]["past"])
    st0 = {"rows": {}, "views": {}, "words": {}, "past": {"m@2026-11-01": {"date": "2026-11-01", "end": "2026-11-01T11:00",
                                                                            "rows": ["MH-7"], "snaps": {"MH-7": F.snap(b2["all"]["MH-7"])}}}}
    got = F.settle_views(st0, b2["all"], datetime.datetime(2026, 11, 20, 12, 0))
    check("a meeting whose report never came, past the wait, is settled with nothing carried", got == [] and st0["past"] == {})
    issue(facts, "MH-1", "Highest and due soon", "Highest", due="2026-11-25", who="Dev Three")   # moved between meetings
    F.board(s, now=datetime.datetime(2026, 11, 23, 9, 0), write=True, doc=DOC)
    b3 = F.board(s, now=datetime.datetime(2026, 11, 23, 12, 0), write=True, doc=DOC, ruled=("scrum-pm", "2026-11-23", [], ["MH-7", "MH-1"]))
    check("carried through two meetings; a row that moved since its last carry starts again",
          b3["all"]["MH-7"]["carried"] == ["2026-11-20", "2026-11-23"] and b3["all"]["MH-1"]["carried"] == ["2026-11-23"])

    # the assignee: the roster's Jira accountId, the email only when it has none
    check("an assignee is the roster's accountId; the email only without one",
          F.assignee_of({"jira": "5e53aaaa", "email": "a@example.com"}) == "5e53aaaa"
          and F.assignee_of({"jira": "", "email": "a@example.com"}) == "a@example.com" and F.assignee_of(None) is None)

    # moves: carried rows, up/down words, rows without a ticket; one batch
    F.roster_assignee = lambda name: {"Dev Two": "acc-dev2"}.get(name)
    open(os.path.join(vault, "projects", "sb", "notes.md"), "w").write("- ela: up MH-2 the customer demo moved up\nela: down MH-4\n")
    st3 = b3["state"]
    new = F.read_words(st3, vault, TODAY)
    check("his up and down lines are read once each", [(w["verb"], w["key"]) for w in new] == [("up", "MH-2"), ("down", "MH-4")]
          and F.read_words(st3, vault, TODAY) == [])
    writes, left = F.moves(s, b3, TODAY)
    cmds = [w["command"] for w in writes]
    check("up: priority High with the reason; no label; a due date only when it has none (MH-2 has one)",
          any(c.startswith("ela jira priority MH-2 --to High --why") and "customer demo" in c for c in cmds)
          and not any(c.startswith("ela jira label") for c in cmds) and not any(c.startswith("ela jira due MH-2") for c in cmds))
    check("down: priority back to Medium, nothing else",
          any(c.startswith("ela jira priority MH-4 --to Medium") for c in cmds) and [c for c in cmds if " MH-4 " in c + " "][1:] == [])
    check("a row carried through two meetings with nobody on it: assigned to who its question names",
          "ela jira assign MH-7 --assignee acc-dev2" in cmds)
    creates = [c for c in cmds if c.startswith("ela jira create")]
    check("a row with no ticket gets a drafted ticket, its question in the description; ela's own and his own never do",
          len(creates) == 2 and any("freeze-frame" in c and "--assignee acc-dev2" in c for c in creates)
          and any("Super Bowl" in c for c in creates) and not any("andyBot" in c or "tidy-up" in c for c in creates))
    check("a row's ticket is a tracking ticket: the create says --nonstandard and why, so the standard does not refuse it",
          all(shlex.split(c)[-2:] == ["--nonstandard", F.TRACKING] for c in creates))
    rx = re.compile(D.CLASSES["focus-moves"]["command"])
    check("every write is one line the class admits, and parses as a shell command",
          all(rx.match(c) and "\n" not in c and shlex.split(c)[:2] == ["ela", "jira"] for c in cmds))
    bt = F.store_batch(s, writes, left, TODAY, st3)
    check("the writes are one open dry-run batch of class focus-moves; his words are marked batched",
          bt["class"] == "focus-moves" and bt["state"] == "open" and all(w.get("batched") == bt["id"] for w in st3["words"].values()))
    ask = next(x for x in D.asks(reports, TODAY) if x.get("batch") == bt["id"])
    check("it is asked A/B on today.md through the dry asks: A applies, B drops",
          [o["letter"] for o in ask["options"]] == ["A", "B"] and ask["options"][0]["does"].endswith("A --apply"))
    w2, _ = F.moves(s, b3, TODAY)
    check("a second pass keeps the open batch's writes, nothing twice", sorted(x["command"] for x in w2) == sorted(cmds))
    D.answer(reports, ask["id"], "B")
    w3, _ = F.moves(s, b3, TODAY)
    check("what he answered is never proposed again", not ({x["command"] for x in w3} & set(cmds)))

    # the scrum import
    body = ("Summary text.\n\nmap[action_items:[Dev Two\uff1a\u7ed9 MH-1 \u8865\u4e0a\u53d1\u5e03\u8bf4\u660e\uff0c\u672c\u5468\u4e94\u524d\u5b8c\u6210 Dev Four: write the Grafana alert runbook by Friday "
            "The Owner\uff1a\u6574\u7406\u6f14\u793a\u6750\u6599 \u4f1a\u8bae\u53c2\u4e0e\u8005\uff1a\u8c03\u7814\u63d2\u4ef6\u65b9\u6848] ask_read_prompts:[x] chapters:[map[chapter:A topics:[MH-2 \u7684\u4e0a\u7ebf\u65e5\u671f\u51b3\u5b9a\u63a8\u8fdf\u5230\u4e0b\u5468\u4e09\u3002 "
            "\u63d2\u4ef6\u65b9\u6848\u4ecd\u5728\u6bd4\u8f83\uff0c\u5c1a\u672a\u786e\u5b9a\u3002]] map[chapter:B topics:[MH-2 \u7684\u4e0a\u7ebf\u65e5\u671f\u51b3\u5b9a\u63a8\u8fdf\u5230\u4e0b\u5468\u4e09\u3002]]] key_questions:[y]")
    check("the report's day from its subject", S.meeting_day("🗓 MediaHub Scrum on November 20, 2026 | Read Meeting Report") == TODAY)
    items = S.action_items(body)
    check("action items split by person, Chinese and Latin colons alike",
          [p for p, _ in items] == ["Dev Two", "Dev Four", "The Owner", "\u4f1a\u8bae\u53c2\u4e0e\u8005"] and items[1][1] == "write the Grafana alert runbook by Friday")
    check("decisions: each topic once", S.decisions(body) == ["MH-2 \u7684\u4e0a\u7ebf\u65e5\u671f\u51b3\u5b9a\u63a8\u8fdf\u5230\u4e0b\u5468\u4e09\u3002", "\u63d2\u4ef6\u65b9\u6848\u4ecd\u5728\u6bd4\u8f83\uff0c\u5c1a\u672a\u786e\u5b9a\u3002"])
    check("a topic that settles something is a decision; one still open is not",
          S.is_decision("MH-2 \u7684\u4e0a\u7ebf\u65e5\u671f\u51b3\u5b9a\u63a8\u8fdf\u5230\u4e0b\u5468\u4e09\u3002") and not S.is_decision("\u63d2\u4ef6\u65b9\u6848\u4ecd\u5728\u6bd4\u8f83\uff0c\u5c1a\u672a\u786e\u5b9a\u3002"))
    fri = datetime.date(2026, 11, 20)
    check("dates: this Friday on a Friday is that day; next Wednesday is next week's; by Friday from Monday is that Friday; a Chinese month-day",
          S.due_in("\u672c\u5468\u4e94\u524d\u5b8c\u6210", fri) == fri and S.due_in("\u4e0b\u5468\u4e09", fri) == datetime.date(2026, 11, 25)
          and S.due_in("by Friday", datetime.date(2026, 11, 23)) == datetime.date(2026, 11, 27)
          and S.due_in("11\u670825\u65e5\u4ea4\u4ed8", fri) == datetime.date(2026, 11, 25) and S.due_in("no date", fri) is None)
    check("an item maps to the row whose key it names, else to the one row sharing distinctive words, else none",
          S.match("\u7ed9 MH-1 \u8865\u4e0a", b3["all"])["id"] == "MH-1" and S.match("Book the encoder for Super Bowl", b3["all"])["id"] == "p:sb"
          and S.match("something else entirely", b3["all"]) is None)
    W, left, ruled, raised = S.drafts({"body": body}, b3["all"], TODAY, "The Owner", reports, facts)
    wc = [w["command"] for w in W]
    check("a mapped item: a comment carrying it; a due date it names when the ticket has none (MH-1 has one)",
          any(c.startswith("ela jira comment MH-1 --from-file") for c in wc) and not any(c.startswith("ela jira due MH-1") for c in wc)
          and "Dev Two" in next(w["text"] for w in W if w["target"] == "MH-1"))
    check("a decision on a row: a comment on its ticket; the rows it settled are ruled, not carried",
          any(c.startswith("ela jira comment MH-2 --from-file") for c in wc) and ruled == ["MH-1", "MH-2"])
    check("a team item with no row becomes a drafted ticket; his own item and the whole team's are listed, never ticketed",
          any(c.startswith("ela jira create") and "Grafana alert runbook" in c for c in wc)
          and any(x.startswith("yours, not ticketed: \u6574\u7406\u6f14\u793a\u6750\u6599") for x in left) and any(x.startswith("for the whole team") for x in left)
          and not any("\u6574\u7406\u6f14\u793a\u6750\u6599" in c for c in wc))
    check("the scrum's writes are admitted by the class too", all(rx.match(c) for c in wc))
    talk = "map[action_items:[] chapters:[map[chapter:A topics:[MH-4 \u7684\u6807\u7b7e\u8fd8\u5728\u8ba8\u8bba\uff0c\u5c1a\u672a\u786e\u5b9a\u3002]]]]"
    W2, _, ruled2, raised2 = S.drafts({"body": talk}, b3["all"], TODAY, "The Owner", reports, facts)
    check("a topic that names a row and settles nothing: the row is raised, no write; the rows never named are neither",
          raised2 == ["MH-4"] and ruled2 == [] and W2 == [] and raised == [])
    mail = os.path.join(t, "mail.json")
    json.dump({"subject": "MediaHub Scrum on November 20, 2026 | Read Meeting Report", "body": body}, open(mail, "w"))
    found = S.find_report(TODAY, runner=lambda argv: type("P", (), {"returncode": 0, "stderr": "", "stdout": json.dumps(
        {"messages": [{"id": "m1", "subject": "MediaHub Scrum on November 20, 2026 | Read Meeting Report", "date": "x"}]} if argv[0] == "search"
        else {"subject": "s", "body": body})})())
    check("the report is found by its day through `ela mail` (a stub here: no mail is read)", found and "action_items:[" in found["body"])

# ── the vault watcher's calls: `ela focus <verb> <rest> --where <rel>#… --json` ──────────────────────────────────
import contextlib, io, types  # noqa: E402
with tempfile.TemporaryDirectory() as t:
    reports, vault = os.path.join(t, "reports"), os.path.join(t, "vault")
    os.makedirs(os.path.join(vault, "reference"))
    F.site = lambda: {"reports": reports, "vault": vault, "runtime": t}

    def call(fn, cmd, words, where=None, apply=True, **kw):
        a = types.SimpleNamespace(cmd=cmd, subject=words, key=words, until=None, where=where, apply=apply, json=True, why="", highest=False, **kw)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn(a)
        return json.loads(buf.getvalue())
    r1 = call(F.cmd_hold, "hold", ["MH-3510", "(HTML", "module)", "until", "2026-12-15"], "reference/a.md#L3")
    r2 = call(F.cmd_hold, "hold", ["MH-3510", "(HTML", "module)", "until", "2026-12-15", "\u2713", "11:42"], "reference/a.md#x9")
    check("hold through the watcher: taken once; the same line again (stamped, another anchor) is already read",
          r1["ok"] and not r1["already"] and r1["until"] == "2026-12-15" and r2 == {"ok": True, "already": True, "verb": "hold", "subject": "MH-3510 (HTML module) until 2026-12-15 \u2713 11:42"})
    r3 = call(F.cmd_hold, "resume", ["nothing", "like", "this"], "reference/a.md#L4")
    check("resume of nothing held: ok false with its reason, not an error", r3["ok"] is False and "nothing held" in r3["why"])
    open(os.path.join(vault, "reference", "a.md"), "w").write("- ela: hold MH-3510 (HTML module) until 2026-12-15\n- ela: hold MH-9 stamped \u2713 11:40\n")
    st, did = H.refresh(reports, vault, TODAY)
    check("the sync's own scan finds the watcher's line already read, and skips a stamped one", did == [] and "MH-9" not in H.held_keys(st, TODAY))
    r4 = call(F.cmd_word, "up", ["MH-77", "the", "demo", "moved", "highest"], "reference/a.md#L5", apply=False)
    check("up through the watcher: the key, the reason and highest read from the line", r4["ok"] and r4["key"] == "MH-77" and r4["batch"] is None)
    r5 = call(F.cmd_word, "down", ["no", "key", "here"], "reference/a.md#L6", apply=False)
    check("a line with no ticket key: ok false", r5["ok"] is False and "no ticket key" in r5["why"])

# ── the brief and today.md leave held subjects out ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(ROOT, "skills", "brief"))
import brief as B  # noqa: E402
hs = {"holds": {}, "read": {}}
H.seed(hs, TODAY)
lanes, held = B.unheld_lanes({"overdue": {"rows": [{"key": "MH-4061", "summary": "10-bit"}, {"key": "MH-1"}], "count": 2},
                              "carried": {"rows": [{"item": "MH-4061 10-bit through the switcher"}], "count": 1}}, hs, TODAY)
check("the brief's lanes leave a held ticket out and say where it was",
      lanes["overdue"]["count"] == 1 and lanes["carried"]["rows"] == [] and held[0]["key"] == "MH-4061" and held[0]["lanes"] == ["overdue", "carried"])
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import vault as V  # noqa: E402
check("today.md's asks leave a held subject out",
      [c["id"] for c in V.unheld([{"id": "a", "text": "MH-4061: who checks?"}, {"id": "b", "text": "MH-1: who?"}], hs, TODAY)] == ["b"])

print("all passed" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
