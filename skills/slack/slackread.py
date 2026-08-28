#!/usr/bin/env python3
"""Read a Slack message (and its thread) by permalink. Read-only.

Credential resolution — the capability never carries the secret:
  $SLACK_BOT_TOKEN  →  $SLACK_ENV_FILE  →  a caller-supplied --env-file
"""
import argparse, json, os, re, sys, urllib.parse, urllib.request

API = "https://slack.com/api/"


def token(env_file=None):
    t = os.environ.get("SLACK_BOT_TOKEN")
    if t:
        return t
    for path in filter(None, [env_file, os.environ.get("SLACK_ENV_FILE")]):
        try:
            for line in open(path):
                if line.startswith("SLACK_BOT_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    sys.exit("no SLACK_BOT_TOKEN (env, $SLACK_ENV_FILE, or --env-file)")


def call(method, tok, **params):
    url = API + method + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    if not d.get("ok"):
        sys.exit(f"slack {method} failed: {d.get('error')}")
    return d


def parse(link):
    m = re.search(r"/archives/([A-Z0-9]+)/p(\d{10})(\d{6})", link)
    if not m:
        sys.exit("not a Slack permalink")
    return m.group(1), f"{m.group(2)}.{m.group(3)}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("permalink"); ap.add_argument("--env-file")
    a = ap.parse_args()
    tok = token(a.env_file)
    ch, ts = parse(a.permalink)
    names = {}

    def who(uid):
        """Resolve lazily — users.list on a real workspace is megabytes."""
        if not uid:
            return "?"
        if uid not in names:
            try:
                u = call("users.info", tok, user=uid)["user"]
                names[uid] = (u.get("profile", {}).get("real_name")
                              or u.get("real_name") or u.get("name") or uid)
            except SystemExit:
                names[uid] = uid
        return names[uid]
    try:
        chan = call("conversations.info", tok, channel=ch)["channel"].get("name", ch)
    except SystemExit:
        chan = ch
    msgs = call("conversations.replies", tok, channel=ch, ts=ts, limit=200)["messages"]
    print(f"# #{chan}  ({len(msgs)} message(s))\n")
    for m in msgs:
        author = who(m.get("user")) if m.get("user") else (m.get("bot_id") or "?")
        text = re.sub(r"<@([A-Z0-9]+)>", lambda x: "@" + who(x.group(1)), m.get("text", ""))
        print(f"--- {author}  ts={m.get('ts')}")
        print(text)
        for f in m.get("files", []) or []:
            print(f"[file] {f.get('name')} ({f.get('filetype')})")
        print()


if __name__ == "__main__":
    main()
