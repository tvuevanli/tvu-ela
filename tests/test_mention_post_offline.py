#!/usr/bin/env python3
"""His A on a mention card posts the draft (ADR 0022), offline: Slack is a fake behind urlopen, so slack.py's own post
path runs (its duplicate refusal, its --as-owner checks, its mrkdwn check) and nothing reaches the network or the
site's write log. Under `off` A leaves the draft to him; under `ela` a postable draft goes out once as the bot with
the signature line; under `owner` it goes out under his name or is refused with the fix, never as the bot. A reply of
his found on the fresh read closes the mention instead; a changed draft, a changed setting, an A with words and an
unattended session post nothing. The post closes the mention and marks the drafted Slack action for its thread
superseded."""
import datetime, io, json, os, sys, tempfile, urllib.parse
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ("mention", "vault", "slack"):
    sys.path.insert(0, os.path.join(ROOT, "skills", d))
import mention as M  # noqa: E402
import slack as S  # noqa: E402
import vault as V  # noqa: E402

failures = []
def check(name, cond, got=None):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)
        if got is not None:
            print("     ", got)

ME, ASKER, OTHER, CH, BOT_ID = "U0ME", "U0ASK", "U0OTHER", "C0DEV", "B0ELA"
OWNER = "owner@example.com"
DAY = {"wait": 30, "hours": ("08:30", "19:00"), "holidays": []}
def at(h, m, d=12):
    return datetime.datetime(2026, 11, d, h, m, tzinfo=M.TZ)
def ts(h, m, d=12, n=0):
    return f"{at(h, m, d).timestamp():.0f}.{n:06d}"
def msg(t, user, text, **more):
    return dict({"ts": t, "user": user, "text": text}, **more)

# ── the fake Slack: every call slack.py makes lands here ─────────────────────────────────────────────────────
class Fake:
    def __init__(self):
        self.threads, self.posts, self.n = {}, [], 0
    def thread(self, root):
        return [dict(m) for m in self.threads[root]]
    def root_of(self, t):
        return next(r for r, ms in self.threads.items() if any(m["ts"] == t for m in ms))
    def urlopen(self, req, timeout=None):
        url = urllib.parse.urlparse(req.full_url)
        method, q = url.path.rsplit("/", 1)[-1], {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        tok = req.get_header("Authorization").split()[-1]
        return io.BytesIO(json.dumps(self.answer(method, tok, q, json.loads(req.data) if req.data else None)).encode())
    def answer(self, method, tok, q, body):
        if method == "auth.test":
            return {"xoxb-test": {"ok": True, "user": "ela", "user_id": "U0BOT", "bot_id": BOT_ID}, "xoxp-owner": {"ok": True, "user": "owner", "user_id": ME},
                    "xoxp-noscope": {"ok": True, "user": "owner", "user_id": ME}, "xoxp-other": {"ok": True, "user": "someone", "user_id": OTHER}}.get(tok, {"ok": False, "error": "invalid_auth"})
        if method == "users.lookupByEmail":
            return {"ok": True, "user": {"id": ME}}
        if method == "users.info":
            return {"ok": True, "user": {"real_name": q["user"], "is_bot": False}}
        if method == "conversations.replies":
            root = self.root_of(q["ts"])
            ms = self.thread(root)
            for m in ms[1:]:
                m["thread_ts"] = root
            return {"ok": True, "messages": [m for m in ms if m["ts"] == q["ts"]] if q.get("limit") == "1" else ms[-int(q.get("limit", 200)):]}
        if method == "chat.postMessage":
            if tok == "xoxp-noscope":
                return {"ok": False, "error": "missing_scope", "needed": "chat:write"}
            self.n += 1
            m = {"ts": f"{float(body['thread_ts']) + 5000 + self.n:.6f}", "text": body["text"]}
            m.update({"bot_id": BOT_ID} if tok == "xoxb-test" else {"user": ME})
            self.threads[body["thread_ts"]].append(m); self.posts.append((tok, body))
            return {"ok": True, "channel": body["channel"], "ts": m["ts"]}
        raise AssertionError(f"unexpected Slack call {method}")

fake, writes = Fake(), []
S.urllib.request.urlopen = fake.urlopen
S.F = None                                                  # no fact store: names and ids come from the fake
S.log_write = lambda where, link, chars, sent_as=None, mention=None: writes.append({"permalink": link, "as": sent_as, "mention": mention})
for k in ("SLACK_USER_TOKEN", "ELA_NO_APPLY", "SLACK_ENV_FILE", "ELA_ENV_FILE"):
    os.environ.pop(k, None)
os.environ.update(SLACK_BOT_TOKEN="xoxb-test", JIRA_EMAIL=OWNER)

with tempfile.TemporaryDirectory() as tmp:
    R, SL = os.path.join(tmp, "reports"), os.path.join(tmp, "slack")
    os.makedirs(SL); os.makedirs(os.path.join(R, "runner"))
    json.dump({"users": {ME: {"name": "Owner Name", "is_bot": False}, ASKER: {"name": "Asker", "is_bot": False}}, "emails": {OWNER: {"id": ME}}},
              open(os.path.join(SL, "users.json"), "w"))
    json.dump({"channels": [{"id": CH, "name": "dev"}]}, open(os.path.join(SL, "channels.json"), "w"))
    names = M.Names(SL, None)
    SIG = "_ela, for Owner · approved by him · replies here reach Owner_"
    check("the signature names him by first name, one fixed line", M.signature("Owner Name") == SIG and M.signature("") == "")
    def post(mode):
        return {"mode": mode, "names": names, "day": DAY, "read": lambda ch, root: fake.thread(root),
                "send": lambda link, text, as_owner, mention: M.slack_send(None, link, text, as_owner, mention)}
    def card(h, m, mode, reply, postable=False, text=None, sent=True):
        """A mention at h:m, unanswered, drafted under `mode`, its card recorded as sent. → (id, card text)."""
        t = ts(h, m)
        fake.threads[t] = [msg(t, ASKER, text or f"<@{ME}> the kit is installed on qa2, can you ack?")]
        recs = M.load(R)
        M.process(recs, R, CH, fake.thread(t), names, DAY, at(h, m + 1))
        rid = f"{CH}-{t}"
        recs[rid]["facts"] = {"keys": [], "lines": ["The thread names no ticket."]}
        _, body = M.make_draft(recs[rid], R, "Asker asks for an ack.", reply, at(h, m + 31), mode, postable, names.name(ME))
        if sent:
            recs[rid].update(dm_at=M.iso(at(h, m + 32)), dm_ts=f"1794.{h:02d}{m:02d}00", shown=M.digest(recs[rid]["post_text"]))
        M.save(R, recs)
        return rid, body
    def refused(fn):
        try:
            fn()
        except M.Refused as e:
            return str(e)
        return None
    rec = lambda rid: M.load(R)[rid]

    # off: the card says paste, A posts nothing
    a1, c1 = card(9, 0, "off", "Got it, thanks.", postable=True)
    check("off: the card says to paste and offers A use this draft", "paste it yourself; ela posts nothing" in c1 and "*A* use this draft · *B* I will write it · *C* nothing needed" in c1
          and rec(a1)["offer"] == "off")
    check("the card is Slack mrkdwn", S.mrkdwn_check(c1) == [], S.mrkdwn_check(c1))
    r = M.answer(R, a1, "A", None, at(9, 40), post("off"))
    check("off: A leaves the draft to him; nothing is posted", r["state"] == "answered" and not fake.posts and not r.get("posted") and r["said"] == "A: the draft is yours to paste.")

    # ela: only a postable draft is offered; it goes out once, signed
    a2, c2 = card(10, 0, "ela", "Got it, thanks.", postable=True)
    check("ela: the card offers A post this draft as @ela and shows the text with the signature",
          "*A* post this draft as @ela" in c2 and f"```\nGot it, thanks.\n{SIG}\n```" in c2 and "your A posts exactly this as @ela" in c2 and S.mrkdwn_check(c2) == [])
    b2, cb = card(10, 5, "ela", "Got it, thanks.")
    check("ela: a draft not marked postable is his to send", rec(b2)["offer"] == "off" and "*A* use this draft" in cb and SIG not in cb)
    b3, _ = card(10, 6, "ela", "Got it. I'll link MH-1 to MH-2.", postable=True)
    b4, _ = card(10, 7, "ela", "Got it. I will ask the PM about the date.", postable=True)
    check("ela: a draft that commits to or promises something is never offered, whatever the mark", rec(b3)["offer"] == rec(b4)["offer"] == "off")
    json.dump([{"n": 1, "kind": "slack", "command": f"ela slack post '{M.permalink(CH, ts(10, 0))}' --text 'Got it.'", "drafted": "x"},
               {"n": 2, "kind": "slack", "command": f"ela slack post {M.permalink(CH, ts(10, 0))} --text 'sent'", "applied": "2026-11-12T10:10:00+08:00"},
               {"n": 3, "kind": "slack", "command": f"ela slack post {M.permalink(CH, ts(8, 0))} --text 'elsewhere'"},
               {"n": 4, "kind": "comment", "command": "ela jira comment MH-1 --from-file x"}], open(os.path.join(R, "runner", "2026-11-12-actions.json"), "w"))
    os.environ["ELA_NO_APPLY"] = "1"
    why = refused(lambda: M.answer(R, a2, "A", None, at(10, 40), post("ela")))
    del os.environ["ELA_NO_APPLY"]
    check("an unattended session posts nothing", why and "unattended" in why and not fake.posts)
    check("a caller that cannot post (the vault's sync) is refused, not recorded", "offers a post" in (refused(lambda: M.answer(R, a2, "A", None, at(10, 40))) or "") and not rec(a2).get("answer"))
    check("the setting changed after the card: refused", "mention_post_as is now owner" in (refused(lambda: M.answer(R, a2, "A", None, at(10, 40), post("owner"))) or ""))
    r = M.answer(R, "1794.100000", "a", None, at(10, 41), post("ela"))
    sent_text = fake.threads[ts(10, 0)][-1]
    check("ela: A posts the card's text once, in the thread, as the bot", len(fake.posts) == 1 and fake.posts[0][0] == "xoxb-test" and fake.posts[0][1]["thread_ts"] == ts(10, 0)
          and sent_text["text"] == f"Got it, thanks.\n{SIG}" and M.digest(sent_text["text"]) == r["shown"] == r["posted"]["hash"])
    check("it is read back, its permalink recorded, the mention closed", r["posted"]["read_back"] and r["posted"]["permalink"] == M.permalink(CH, sent_text["ts"], ts(10, 0))
          and r["state"] == "closed" and "posted as @ela" in r["closed"]["why"] and r["answer"]["letter"] == "A")
    check("the line after A says where it went, with the permalink, in mrkdwn", r["said"] == f"Posted as @ela in #dev: <{r['posted']['permalink']}|the reply>" and S.mrkdwn_check(r["said"]) == [])
    check("the write log row carries the mention id and the identity", writes == [{"permalink": S.permalink_of(CH, sent_text["ts"]), "as": "ela", "mention": a2}])
    acts = {x["n"]: x for x in json.load(open(os.path.join(R, "runner", "2026-11-12-actions.json")))}
    check("the drafted action for that thread is superseded, with why; applied, other-thread and Jira actions are left",
          a2 in acts[1]["superseded"]["by"] and "posted" in acts[1]["superseded"]["by"] and not any("superseded" in acts[n] for n in (2, 3, 4)) and r["superseded"] == [{"file": "2026-11-12-actions.json", "n": 1}])
    try:
        M.answer(R, a2, "A", None, at(10, 50), post("ela")); again = False
    except ValueError:
        again = True
    check("a second A posts nothing", again and len(fake.posts) == 1)
    recs = M.load(R)
    M.process(recs, R, CH, fake.thread(ts(10, 0)), names, DAY, at(11, 0))
    check("the posted reply does not reopen or re-count the mention on the next walk", recs[a2]["state"] == "closed" and not recs[a2].get("replied_at"))

    # an earlier A that posted and was cut off: the text is found there, not posted again
    a3, _ = card(11, 0, "ela", "Noted, thanks.", postable=True)
    fake.threads[ts(11, 0)].append({"ts": ts(11, 35), "bot_id": BOT_ID, "text": f"Noted, thanks.\n{SIG}"})
    r = M.answer(R, a3, "A", None, at(11, 40), post("ela"))
    check("the same text already there from the bot is taken as the post", len(fake.posts) == 1 and r["posted"]["found_there"] and r["posted"]["ts"] == ts(11, 35) and r["state"] == "closed")

    # the text must be the text the card showed
    a4, _ = card(12, 0, "ela", "Got it.", postable=True)
    recs = M.load(R)
    old = recs[a4]["shown"]
    M.make_draft(recs[a4], R, "Asker asks for an ack.", "Got it, will do.", at(12, 40), "ela", True, names.name(ME))
    M.save(R, recs)
    check("a draft made again after its card owes a new card", not rec(a4).get("dm_at") and M.todo(M.load(R), DAY, at(12, 41))[-1]["do"] == "dm" and rec(a4)["cards"][0]["shown"] == old)
    check("an A that carries the old card's hash is refused", "changed after the card" in (refused(lambda: M.answer(R, a4, "A", None, at(12, 42), post("ela"), old[:16])) or ""))
    check("with no card on record nothing is posted unseen", "no card on record" in (refused(lambda: M.answer(R, a4, "A", None, at(12, 42), post("ela"))) or "") and len(fake.posts) == 1)

    # his reply found on the fresh read: closed by it, nothing posted
    a5, _ = card(13, 0, "ela", "Got it, thanks.", postable=True)
    fake.threads[ts(13, 0)].append(msg(ts(13, 36), ME, "Thanks, seen."))
    r = M.answer(R, a5, "A", None, at(13, 40), post("ela"))
    check("a reply of his after the mention closes it and posts nothing", len(fake.posts) == 1 and r["state"] == "withdrawn" and not r.get("answer") and not r.get("posted")
          and r["said"].startswith("Nothing posted: you replied in the thread at 13:36"))

    # A with words is not an approve
    a6, _ = card(14, 0, "ela", "Got it, thanks.", postable=True)
    r = M.answer(R, a6, "A but thank the QA lead too", None, at(14, 40), post("ela"))
    d = [x for x in M.todo(M.load(R), DAY, at(14, 41)) if x["id"] == a6]
    check("A with words posts nothing: a new draft is owed, with his words", len(fake.posts) == 1 and not r.get("answer") and "not an approve" in r["said"]
          and d == [{"id": a6, "permalink": r["permalink"], "triage": "ask", "revise": "but thank the QA lead too", "do": "draft", "route": "dm"}])
    try:
        M.answer(R, a6, "AB", None, at(14, 41), post("ela")); bad = False
    except ValueError:
        bad = True
    check("a word that is not a letter is refused", bad)

    # owner: under his name or not at all
    a7, c7 = card(15, 0, "owner", "Got it. I'll link MH-1 to MH-2.")
    check("owner: any draft is offered under his name, with no signature", "*A* post this draft under your name" in c7 and SIG not in c7 and rec(a7)["post_text"] == "Got it. I'll link MH-1 to MH-2."
          and S.mrkdwn_check(c7) == [])
    why = refused(lambda: M.answer(R, a7, "A", None, at(15, 40), post("owner")))
    check("owner: no user token is a refusal with the fix, never the bot", why and "SLACK_USER_TOKEN" in why and "fix:" in why and len(fake.posts) == 1 and not rec(a7).get("answer"))
    os.environ["SLACK_USER_TOKEN"] = "xoxp-other"
    why = refused(lambda: M.answer(R, a7, "A", None, at(15, 40), post("owner")))
    check("owner: a token that is not his is refused", why and "not to the owner" in why and len(fake.posts) == 1)
    os.environ["SLACK_USER_TOKEN"] = "xoxp-noscope"
    why = refused(lambda: M.answer(R, a7, "A", None, at(15, 40), post("owner")))
    check("owner: a token lacking the scope is refused with the fix", why and "missing_scope" in why and "chat:write" in why and len(fake.posts) == 1 and not rec(a7).get("answer"))
    os.environ["SLACK_USER_TOKEN"] = "xoxp-owner"
    r = M.answer(R, a7, "A", None, at(15, 41), post("owner"))
    check("owner: A posts the exact draft once under his name", len(fake.posts) == 2 and fake.posts[1][0] == "xoxp-owner" and fake.posts[1][1]["text"] == "Got it. I'll link MH-1 to MH-2."
          and fake.threads[ts(15, 0)][-1].get("user") == ME and r["state"] == "closed" and r["posted"]["as"] == "owner" and r["posted"]["read_back"])
    check("owner: the line after A", r["said"] == f"Posted under your name in #dev: <{r['posted']['permalink']}|the reply>" and writes[-1] == {"permalink": S.permalink_of(CH, r["posted"]["ts"]), "as": "owner", "mention": a7})
    a8, _ = card(15, 10, "owner", "Got it. I'll link MH-1 to MH-2.")
    fake.threads[ts(15, 10)].append(msg(ts(15, 45), ME, "Got it. I'll link MH-1 to MH-2."))
    r = M.answer(R, a8, "A", None, at(15, 50), post("owner"))
    check("owner: the same words already there from him are his reply; nothing is posted twice", len(fake.posts) == 2 and r["state"] == "withdrawn")
    del os.environ["SLACK_USER_TOKEN"]

    # today.md: an A that posts carries the card's hash and is the runner's to run
    recs = M.load(R)
    t = ts(21, 0)
    fake.threads[t] = [msg(t, ASKER, f"<@{ME}> the kit is on qa2, can you ack?")]
    M.process(recs, R, CH, fake.thread(t), names, DAY, at(21, 1))
    h1 = f"{CH}-{t}"
    recs[h1]["facts"] = {"keys": [], "lines": ["The thread names no ticket."]}
    M.make_draft(recs[h1], R, "Asker asks for an ack.", "Got it, thanks.", at(7, 50, 13), "ela", True, names.name(ME))
    M.save(R, recs)
    opt = [x for x in M.asks(R) if x["id"] == f"mention:{h1}"][0]["options"][0]
    check("a held mention's A names the post and carries the hash of the text its page shows",
          opt["text"] == "post this draft as @ela" and opt["does"] == f"ela mention answer {h1} A --shown {M.digest(recs[h1]['post_text'])[:16]}"
          and f"Got it, thanks.\n{SIG}" in M.page(recs[h1]) and "Your A posts exactly this as @ela." in M.page(recs[h1]))
    check("the vault's sync does not settle that letter itself", not V.sync_handles(opt["does"]) and V.sync_handles(f"ela mention answer {h1} B"))
    r = M.answer(R, h1, "A", None, at(8, 40, 13), post("ela"), opt["does"].split()[-1])
    check("run with that hash, it posts", len(fake.posts) == 3 and r["posted"]["read_back"] and r["state"] == "closed")
    tl = M.tally(R)
    check("the tally counts each end", tl["question"]["A"] == 5 and tl["question"]["withdrawn"] == 2 and tl["question"]["revise"] == 1)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
