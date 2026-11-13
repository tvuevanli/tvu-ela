#!/usr/bin/env python3
"""The site guard: a verb that takes a file from its caller refuses the site directory and the env file, before any
token is read or call made, and says why without the file's text. Offline: every case stops at the refusal."""
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
print("siteguard: " + ("FAILED" if fail else "passed"))
sys.exit(fail)
