#!/usr/bin/env python3
"""The site guard: a verb that takes a file from its caller refuses the site directory and the env file, before any
token is read or call made, and says why without the file's text; `slack post` refuses a text that carries a
credential of the env file, naming the variable. Offline: every case stops at the refusal."""
import json, os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fail = 0


def check(ok, what, got=None):
    global fail
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        fail = 1
        print("     ", got)


with tempfile.TemporaryDirectory() as tmp:
    home = os.path.join(tmp, "home"); sited = os.path.join(home, ".claude", "ela"); os.makedirs(sited)
    env = os.path.join(tmp, "kept-elsewhere.env")
    DECOY = "-".join(["decoy", "value", "never", "printed"])
    json.dump({"env": env, "note": DECOY}, open(os.path.join(sited, "site.json"), "w"))
    open(env, "w").write(f"JIRA_BASE_URL=https://jira.invalid\nJIRA_EMAIL=owner@example.invalid\nJIRA_TOKEN={DECOY}\nSHORT=abc\n")
    site_json = os.path.join(sited, "site.json")
    link = os.path.join(tmp, "notes.md"); os.symlink(env, link)

    def run(skill, script, *args):
        e = dict(os.environ, HOME=home); e.pop("ELA_ENV_FILE", None)
        r = subprocess.run(["python3", os.path.join(ROOT, "skills", skill, script), *args], input="", capture_output=True, text=True, env=e)
        return r.returncode, r.stdout + r.stderr

    CASES = (("slack check --file", "slack", "slack.py", ["check", "--fix", "--file", "{}"]),
             ("slack post --file", "slack", "slack.py", ["--env-file", env, "post", "#x", "--file", "{}"]),
             ("jira comment --from-file", "jira", "jira.py", ["--env-file", env, "comment", "MH-1", "--from-file", "{}"]),
             ("jira attach", "jira", "jira.py", ["--env-file", env, "attach", "MH-1", "{}"]),
             ("kb write --file", "kb", "kb.py", ["--env-file", env, "write", "t", "--collection", "c", "--file", "{}"]),
             ("promote note lint", "promote", "note.py", ["lint", "{}"]),
             ("promote envproof", "promote", "envproof.py", ["--env-file", env, "text", "{}", "--lane", "qa"]),
             ("onething render --rows", "onething", "onething.py", ["--env-file", env, "render", "--rows", "{}"]),
             ("verify-plan --plan", "verify", "verify.py", ["--env-file", env, "plan", "--key", "MH-1", "--plan", "{}", "--lane", "qa", "--version", "1"]))
    for name, skill, script, argv in CASES:
        for what, path in (("the site directory", site_json), ("the env file", env), ("a link to the env file", link)):
            c, out = run(skill, script, *[a.format(path) if a == "{}" else a for a in argv])
            check(c == 2 and "refused: " in out and "not read" in out and DECOY not in out, f"{name}: {what} is refused", (c, out[-300:]))

    sys.path.insert(0, os.path.join(ROOT, "skills", "setup"))
    os.environ["HOME"] = home; os.environ.pop("ELA_ENV_FILE", None)
    import siteguard as G  # noqa: E402
    check(G.refused(os.path.join(tmp, "plain.md")) is None and G.guard("-") == "-" and G.guard(None) is None, "any other file, stdin and no file pass")
    check(G.credentials() == {DECOY: "JIRA_TOKEN"}, "a credential is a value of 8 characters or more that is not a URL, an email or a path", G.credentials().values())
    check(G.carried(f"see https://jira.invalid/browse/MH-1, from owner@example.invalid, {DECOY}!") == ["JIRA_TOKEN"] and G.carried("https://jira.invalid/browse/MH-1") == [],
          "carried names the variable; a ticket link and the owner's email carry nothing")
    # the post scrub: refused before any call, in the dry run, the preview and --apply, from --text and from --file
    open(env, "a").write("SLACK_BOT_TOKEN=" + "-".join(["another", "decoy", "token"]) + "\n")
    body = os.path.join(tmp, "reply.md"); open(body, "w").write(f"the build is on QA\ntoken: {DECOY}\n")
    for name, argv in (("the dry run", ["--text", f"use {DECOY} to sign in"]), ("--apply", ["--text", f"use {DECOY}", "--apply"]),
                       ("--preview", ["--text", f"use {DECOY}", "--preview"]), ("a --file", ["--file", body])):
        c, out = run("slack", "slack.py", "--env-file", env, "post", "#x", *argv)
        check(c == 2 and "refused" in out and "JIRA_TOKEN" in out and DECOY not in out, f"slack post, {name}: a text carrying a credential is refused, the variable named, the value never", (c, out[-300:]))
    # addresses: a service host of the env file and a local address go to the owner's DM only
    # BOX is a public address: the documentation ranges count as private
    BOX = ".".join(["34", "120", "5", "9"]); PRIV = ".".join(["192", "168", "1", "20"]); LOOP = ".".join(["127", "0", "0", "1"])
    open(env, "a").write(f"UR_BASE_HOST=https://ur.svc.invalid:8443/api\nTVU_BOX={BOX}:22\nOUTLINE_URL=https://kb.invalid\nMIRROR_URL=https://kb.invalid/m\n")
    check(G.service_hosts() == {"ur.svc.invalid": "UR_BASE_HOST", BOX: "TVU_BOX"}, "service hosts: a URL's host and a bare IP; the Jira site and the KB are allowed, by variable", G.service_hosts())
    check(G.outward("see https://jira.invalid/browse/MH-1 and https://kb.invalid/doc/x, owner@example.invalid, build 2.1.0.92") == [], "a ticket link, a KB link, the owner's email and a version carry nothing")
    check(len(G.outward(f"curl https://UR.svc.invalid/v1/graphs and ssh {BOX}")) == 1 and "UR_BASE_HOST" in G.outward("at ur.svc.invalid:8443")[0] and "ur.svc" not in G.outward("at ur.svc.invalid:8443")[0],
          "a service host is found by hostname in any case, with or without a port, and named by its variable")
    check(G.local_lines(f"ok\nopen http://localhost:3000/x\nor {LOOP}:8080\nbox {PRIV}\nlocalhostess 1.2.3") == [2, 3, 4], "localhost, a loopback and a private-range IP, by line", G.local_lines(f"http://localhost:3000\n{LOOP}\n{PRIV}"))
    for name, text, word in (("a service host", "the graph is on ur.svc.invalid", "UR_BASE_HOST"), ("a box IP", f"ssh {BOX}", "TVU_BOX"),
                             ("localhost", "open http://localhost:3000/page", "local address"), ("a private-range IP", f"it runs on {PRIV}", "local address")):
        for where, argv in (("a channel", ["#x"]), ("a thread", ["https://w.invalid/archives/C0123456789/p1700000000000100"]), ("a channel preview", ["#x", "--preview"])):
            c, out = run("slack", "slack.py", "--env-file", env, "post", *argv, "--text", text)
            check(c == 2 and "refused" in out and word in out and "--dm me" in out and "svc.invalid" not in out and BOX not in out, f"slack post to {where}: {name} is refused, before any call", (c, out[-300:]))
    c, out = run("slack", "slack.py", "--env-file", env, "post", "--dm", "me", "--text", "the graph is on ur.svc.invalid, page at http://localhost:3000")
    check("refused" not in out, "the owner's own DM is not refused for an address (the run goes on to Slack, which this test does not reach)", (c, out[-300:]))
    c, out = run("slack", "slack.py", "--env-file", env, "post", "--dm", "me", "--text", f"use {DECOY}")
    check(c == 2 and "JIRA_TOKEN" in out, "a credential is refused in the owner's own DM too", (c, out[-200:]))
print("siteguard: " + ("FAILED" if fail else "passed"))
sys.exit(fail)
