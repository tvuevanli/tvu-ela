#!/usr/bin/env python3
"""`slack post --preview` offline: the preview the owner reads in his DM says in words where the text would go (a
direct message, a reply in a named thread behind a link, a new message in a channel) and as whom, with no user id,
no bare URL and no "dry run" plumbing; the thread every preview of a topic joins opens with a plain first line. Slack
is a fake behind urlopen; HOME is a temp dir, so nothing is read from or written to the site."""
import argparse, io, json, os, sys, tempfile, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "slack"))

failures = []
def check(name, cond, got=None):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)
        if got is not None:
            print("     ", got)

ME, CH, DM = "U0ME12345", "C0DEV1234", "D0OWN1234"
ROOT_TS = "1700000000.000100"
posts = []

def urlopen(req, timeout=None):
    url = urllib.parse.urlparse(req.full_url)
    method, q = url.path.rsplit("/", 1)[-1], {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
    body = json.loads(req.data) if req.data else None
    ans = {"auth.test": {"ok": True, "user": "ela", "user_id": "U0BOT", "bot_id": "B0ELA"},
           "users.lookupByEmail": {"ok": True, "user": {"id": ME}},
           "users.info": {"ok": True, "user": {"real_name": "Owner Name"}},
           "conversations.open": {"ok": True, "channel": {"id": DM}},
           "conversations.history": {"ok": True, "messages": []},
           "users.conversations": {"ok": True, "channels": [{"id": CH, "name": "dev"}], "response_metadata": {}},
           "conversations.replies": {"ok": True, "messages": [{"ts": ROOT_TS, "user": "U0ASK", "text": "Can someone check <the> MH-1997 fix on prod-3 before the release goes out tomorrow morning?"}]},
           }.get(method)
    if method == "chat.postMessage":
        posts.append(body)
        ans = {"ok": True, "channel": body["channel"], "ts": f"1700000100.{len(posts):06d}"}
    if ans is None:
        raise AssertionError(f"unexpected Slack call {method}")
    return io.BytesIO(json.dumps(ans).encode())

with tempfile.TemporaryDirectory() as tmp:
    os.environ["HOME"] = tmp
    os.chdir(tmp)
    for k in ("SLACK_USER_TOKEN", "SLACK_ENV_FILE", "ELA_ENV_FILE", "ELA_NO_APPLY"):
        os.environ.pop(k, None)
    os.environ.update(SLACK_BOT_TOKEN="xoxb-test", JIRA_EMAIL="owner@example.com")
    import slack as S  # noqa: E402
    S.urllib.request.urlopen = urlopen
    S.F = None
    S.log_write = lambda *a, **k: None

    def preview(target=None, dm=None, topic=None):
        posts.clear()
        a = argparse.Namespace(target=target, text="It is in build 90.", file=None, dm=dm, apply=False, no_cc=True,
                               as_owner=False, preview=True, topic=topic, team_thread=False, team_day_post=False,
                               json=True, env_file=None, mention=None)
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            S.cmd_post("xoxb-test", a)
        return [p["text"] for p in posts]

    def human(t):
        bare = __import__("re").sub(r"<[^>|]+\|[^>]*>", "", t)        # ids inside a labelled link are not shown
        return S.mrkdwn_check(t) == [] and "http" not in bare and ME not in bare and CH not in bare and "dry run" not in t.lower() and "DM to" not in t

    link = f"https://tvunetworks.slack.com/archives/{CH}/p{ROOT_TS.replace('.', '')}"
    got = preview(target=link, topic="MH-1997")
    root, head = (got + ["", ""])[:2]
    first = head.split("\n")[0]
    check("the thread a topic's previews join opens with a plain line naming the topic",
          root.startswith("*Previews:* MH-1997\n") and human(root), root)
    check("a reply's preview: the thread behind a link, its channel, its first words cut at a word, as whom",
          first.startswith(f"*Preview, not sent yet:* a reply in <{link}|the thread> in #dev: “Can someone check &lt;the&gt; MH-1997")
          and first.endswith("…”, as @ela") and human(head) and head.endswith("\n\nIt is in build 90."), first)
    got = preview(dm="me")
    check("a direct message's preview names it in words, no user id; with no topic the thread is named the same way",
          got[1].split("\n")[0] == "*Preview, not sent yet:* a direct message to you, as @ela" and human(got[1])
          and got[0].startswith("*Previews:* a direct message to you\n") and human(got[0]), got)
    got = preview(target="#dev", topic="T-2")
    check("a channel's preview: a new message in #dev", got[-1].split("\n")[0] == "*Preview, not sent yet:* a new message in #dev, as @ela", got)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
