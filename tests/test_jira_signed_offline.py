#!/usr/bin/env python3
"""jira.py's signed writes, offline (decision 2026-11-24, ela watches the MH board): a comment ela writes on its own
initiative ends with the signature line and follows the language rule; a field change it makes goes out only with the
comment that announces it, posted after the change; a terminal status is refused. The Jira API is a stub here."""
import contextlib, io, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "jira"))
import jira as J  # noqa: E402

failures = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


LINE = "— ela, Dana Owner's assistant, writing on his account. If this is wrong, reply here or message Dana."
check("the signature names the account the write is made on, and its first name", J.signature("Dana Owner") == LINE)
s = J.signed("Assigned to the UI owner: the bug is in the player.", "Dana Owner")
check("signed: the line is the last one, after a blank line", s.endswith("\n\n" + LINE) and J.is_signed(s))
check("signing a signed text changes nothing", J.signed(s, "Dana Owner") == s)
check("unsigned gives the body back", J.unsigned(s) == "Assigned to the UI owner: the bug is in the player.")

ZH = "\u64ad\u653e\u5668\u5728\u5207\u6362\u540e\u9ed1\u5c4f\uff0c\u91cd\u542f\u540e\u6062\u590d"
check("a ticket whose text is mostly CJK is Chinese; an English one with a CJK word is not",
      J.chinese(ZH + " MH") and not J.chinese("The player goes black after a switch (\u9ed1\u5c4f)"))
check("English on an English ticket passes", J.language_problem(s, "Player black screen") is None)
check("English only on a Chinese ticket: refused, bilingual is the rule",
      "bilingual" in (J.language_problem(s, ZH) or ""))
both = J.signed("Assigned to the UI owner: the bug is in the player.\n\n" + ZH, "Dana Owner")
check("bilingual, English first, on a Chinese ticket passes", J.language_problem(both, ZH) is None)
check("Chinese first: refused", "opens in English" in (J.language_problem(J.signed(ZH + "\n\nEnglish after.", "D O"), ZH) or ""))
check("a signature alone says nothing: refused", "says nothing" in (J.language_problem(LINE, "x") or ""))

check("a field change of ela's own without its comment is refused", "--note-file" in (J.note_problem("assign", None, True) or ""))
check("the same change on the owner's word needs none", J.note_problem("assign", None, False) is None)
check("with its comment it passes", J.note_problem("priority", "Raised: …", True) is None)
check("a terminal status of ela's own is refused, comment or not",
      "terminal" in (J.note_problem("transition", "x", True, "Done") or "") and J.note_problem("transition", "x", True, "Review") is None)
check("a comment is not a field change", J.note_problem("comment", None, True) is None)
check("ela's own is its class", J.own_initiative({"ELA_CLASS": "board-watch"}) and not J.own_initiative({"ELA_CLASS": "focus-moves"}))

# the gate end to end, the API a stub: nothing leaves this process
calls = []
ISSUE = {"summary": "Player black screen", "description": None, "assignee": None, "status": {"name": "In Progress"}}


def api_get(creds, path, params=None):
    calls.append(("GET", path))
    if path.endswith("/myself"):
        return {"displayName": "Dana Owner", "accountId": "acc-me"}
    if path.startswith("/rest/api/3/user"):
        return {"accountId": params["accountId"], "displayName": "Dev One"}
    if path.endswith("/comment"):
        return {"comments": []}
    return {"fields": ISSUE}


J.api_get = api_get
J._request = lambda creds, path, params=None, payload=None, method="GET": calls.append((method, path, payload)) or {}
J.api_post = lambda creds, path, payload: calls.append(("POST", path, payload)) or {"id": "c1"}
J.fetch_comments = lambda creds, key: []
J.load_env = lambda env_file: {"JIRA_BASE_URL": "https://j"}


def run(argv, env):
    calls.clear()
    J._ACCOUNT.clear()
    old = dict(os.environ)
    os.environ.update(env)
    out, err = io.StringIO(), io.StringIO()
    code = 0
    sys.argv = ["jira.py"] + argv
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            J.main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    finally:
        os.environ.clear(); os.environ.update(old)
    return code, out.getvalue(), err.getvalue()


with tempfile.TemporaryDirectory() as t:
    WATCH = {"ELA_CLASS": "board-watch", "ELA_REPORTS": t}
    code, out, err = run(["assign", "MH-1", "--assignee", "acc-dev1", "--apply"], WATCH)
    check("the watch's assign with no comment: refused before any read or write", code == 2 and "--note-file" in err and calls == [])
    note = os.path.join(t, "note.txt")
    open(note, "w").write("Assigned to Dev One, who owns the player: the trace ends in their service.")
    code, out, err = run(["assign", "MH-1", "--assignee", "acc-dev1", "--note-file", note], WATCH)
    check("its dry run shows the change and its signed comment, and writes nothing",
          code == 0 and "DRY RUN — MH-1" in out and "DRY RUN — comment on MH-1" in out and LINE in out
          and not [c for c in calls if c[0] in ("PUT", "POST")])
    code, out, err = run(["assign", "MH-1", "--assignee", "acc-dev1", "--note-file", note, "--apply"], WATCH)
    puts = [c for c in calls if c[0] in ("PUT", "POST")]
    check("applied (a stub): the change first, then the signed comment",
          code == 0 and [c[0] for c in puts] == ["PUT", "POST"] and puts[0][1].endswith("/assignee") and puts[1][1].endswith("/comment")
          and LINE in J.body_text(puts[1][2]["body"]))
    code, out, err = run(["transition", "MH-1", "--to", "Done", "--terminal", "--note-file", note, "--apply"], WATCH)
    check("the watch's terminal transition: refused, nothing written", code == 2 and "terminal" in err and not [c for c in calls if c[0] != "GET"])
    code, out, err = run(["comment", "MH-1", "--text", "The fix is on daily; QA can test it there."], WATCH)
    check("the watch's comment is signed in its dry run", code == 0 and LINE in out)
    code, out, err = run(["comment", "MH-1", "--text", "The fix is on daily."], {"ELA_REPORTS": t})
    check("a comment on the owner's word is not signed", code == 0 and LINE not in out)
    ISSUE["summary"], ISSUE["description"] = ZH, None
    code, out, err = run(["comment", "MH-1", "--text", "The fix is on daily."], WATCH)
    check("the watch's English-only comment on a Chinese ticket: refused", code == 2 and "bilingual" in out)
    code, out, err = run(["priority", "MH-1", "--to", "High", "--note-file", note], WATCH)
    check("a change whose comment breaks the language rule is refused before the change", code == 2 and "bilingual" in err
          and not [c for c in calls if c[0] in ("PUT", "POST")])

print("jira signed: all offline checks passed" if not failures else f"jira signed: {len(failures)} failed")
sys.exit(1 if failures else 0)
