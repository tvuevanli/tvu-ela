#!/usr/bin/env python3
"""`ela slack mentions`, offline: Slack is a fake behind urlopen and the store is a temp directory. A mention written
as a reply is found whether or not its thread started inside the window: under a parent a day older than the window,
and under a parent an earlier read had already stored without replies. A thread with no mention inside the window is
left out, and the read of an old parent costs one conversations.replies call, for the thread that moved."""
import argparse, contextlib, io, json, os, sys, tempfile, time, urllib.parse
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

ME, ASKER, PEER, CH = "U0ME", "U0ASK", "U0PEER", "C0DEV"
NOW = time.time()
def ago(hours, n=0):
    return f"{NOW - hours * 3600:.0f}.{n:06d}"
def msg(t, user, text):
    return {"ts": t, "user": user, "text": text}


class Fake:
    """threads: root ts → [root, replies…]; a parent is served as Slack serves it, with its reply marks."""
    def __init__(self):
        self.threads, self.calls = {}, []
    def parent(self, root):
        ms = self.threads[root]
        return dict(ms[0], **({"reply_count": len(ms) - 1, "latest_reply": ms[-1]["ts"], "thread_ts": root} if len(ms) > 1 else {}))
    def urlopen(self, req, timeout=None):
        url = urllib.parse.urlparse(req.full_url)
        method, q = url.path.rsplit("/", 1)[-1], {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        self.calls.append((method, q.get("ts") or q.get("oldest")))
        if method == "conversations.history":
            return io.BytesIO(json.dumps({"ok": True, "messages": [self.parent(r) for r in self.threads if float(r) > float(q["oldest"])]}).encode())
        if method == "conversations.replies":
            return io.BytesIO(json.dumps({"ok": True, "messages": [dict(m) for m in self.threads[q["ts"]]]}).encode())
        if method == "users.info":
            return io.BytesIO(json.dumps({"ok": True, "user": {"real_name": q["user"], "is_bot": False}}).encode())
        raise AssertionError(f"unexpected Slack call {method}")


def mentions(since, fresh=True):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        S.cmd_mentions("xoxb-test", argparse.Namespace(user=ME, since=since, channels=None, fresh=fresh, json=True, env_file=None))
    return json.loads(out.getvalue())


with tempfile.TemporaryDirectory() as tmp:
    fake = Fake()
    S.urllib.request.urlopen = fake.urlopen
    S.F = None                                              # no fact store: every read is live, the cache is the temp directory
    S._cache_dir = lambda: tmp
    S.pick_channels = lambda tok, spec: [{"id": CH, "name": "dev"}]

    OLD, NEW, QUIET = ago(27), ago(3), ago(30)
    fake.threads = {OLD: [msg(OLD, ME, "the plan for the sync"), msg(ago(1.1), ASKER, "the release note")],
                    QUIET: [msg(QUIET, ASKER, f"<@{ME}> an older ask"), msg(ago(29), ME, "answered")],
                    NEW: [msg(NEW, PEER, "a new topic")]}
    got = mentions("2h")
    check("no mention inside the window: nothing listed, an older mention left out", got["count"] == 0 and not got["unread_channels"], got)

    # a reply that names him, under the parent written 27 hours ago
    fake.threads[OLD].append(msg(ago(1), ASKER, f"<@{ME}> <@{PEER}> please confirm"))
    fake.threads[OLD].append(msg(ago(0.9), PEER, "Confirm"))
    fake.calls.clear()
    got = mentions("2h")
    t = (got["threads"] or [{}])[0]
    check("a mention in a reply under a parent older than the window is found",
          got["count"] == 1 and t.get("permalink") == S.permalink_of(CH, OLD) and t.get("answered") is False and len(t.get("mentions") or []) == 1, got)
    check("it costs the parents' read and one replies call, for the thread that moved",
          [c for c in fake.calls if c[0] == "conversations.replies"] == [("conversations.replies", OLD)], fake.calls)

    # a reply under a parent the store already holds from an earlier read, inside the window
    fake.threads[NEW].append(msg(ago(0.5), ASKER, f"<@{ME}> can you check this?"))
    got = mentions("4h")
    check("a mention in a reply under a parent stored earlier without replies is found",
          {x["permalink"] for x in got["threads"]} == {S.permalink_of(CH, OLD), S.permalink_of(CH, NEW)}, got)

    fake.threads[OLD].append(msg(ago(0.2), ME, "Confirmed."))
    got = mentions("2h")
    check("his reply after the mention reads as answered", [x["answered"] for x in got["threads"] if x["permalink"] == S.permalink_of(CH, OLD)] == [True], got)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
