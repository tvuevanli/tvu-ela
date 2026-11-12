#!/usr/bin/env python3
"""Acts can be undone, offline, against a fake Jira on a temp reports root: each applied write of a dry-run class keeps
its before-state and its reverse atom with the act (a link's id, a comment's id, the Fixed In and labels before a
reconcile batch, the prior assignee); the reverse atoms are dry runs until --apply and restore the before-state;
comment-delete takes only ela's own comment; `ela dry undo` runs them and records the correction; a class without its
reverse atom never earns a grant ask. Nothing reaches Jira or Slack."""
import argparse, copy, datetime, json, os, re, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ("jira", "dry", "release"):
    sys.path.insert(0, os.path.join(ROOT, "skills", d))
import jira as J  # noqa: E402
import dry as D  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

ME, OTHER = "acc-me", "acc-other"
LINKTYPE = {"name": "Hierarchy link (WBSGantt)", "outward": "contains", "inward": "is contained in"}


class FakeJira:
    """Issues in memory; the REST paths the write atoms use, nothing else."""
    def __init__(self):
        self.issues = {
            "MH-1": {"summary": "parent", "labels": ["keep"], J.FIXED_IN_FIELD: "mh-app@1.0", "issuelinks": [],
                     "assignee": None, "comments": []},
            "MH-2": {"summary": "child", "labels": [], J.FIXED_IN_FIELD: None, "issuelinks": [], "assignee": None, "comments": []},
        }
        self.calls, self.next_id = [], 900

    def __call__(self, creds, path, params=None, payload=None, method="GET"):
        self.calls.append((method, path))
        if path == "/rest/api/3/myself":
            return {"accountId": ME, "displayName": "Owner"}
        if path == "/rest/api/3/issueLinkType":
            return {"issueLinkTypes": [LINKTYPE]}
        if path == "/rest/api/3/issueLink" and method == "POST":
            self.next_id += 1
            src, dst = payload["inwardIssue"]["key"], payload["outwardIssue"]["key"]
            self.issues[src]["issuelinks"].append({"id": str(self.next_id), "type": LINKTYPE, "outwardIssue": {"key": dst}})
            self.issues[dst]["issuelinks"].append({"id": str(self.next_id), "type": LINKTYPE, "inwardIssue": {"key": src}})
            return {}
        m = re.fullmatch(r"/rest/api/3/issueLink/(\d+)", path)
        if m and method == "DELETE":
            for i in self.issues.values():
                i["issuelinks"] = [l for l in i["issuelinks"] if l["id"] != m.group(1)]
            return {}
        m = re.fullmatch(r"/rest/api/3/issue/([A-Z]+-\d+)(/.*)?", path)
        key, rest = m.group(1), m.group(2) or ""
        i = self.issues[key]
        if rest == "/comment" and method == "GET":
            return {"comments": copy.deepcopy(i["comments"])}
        if rest == "/comment" and method == "POST":
            self.next_id += 1
            i["comments"].append({"id": str(self.next_id), "author": {"accountId": ME, "displayName": "Owner"}, "body": payload["body"], "created": "2026-11-12T10:00"})
            return {"id": str(self.next_id)}
        m2 = re.fullmatch(r"/comment/(\d+)", rest)
        if m2 and method == "DELETE":
            i["comments"] = [c for c in i["comments"] if c["id"] != m2.group(1)]
            return {}
        if rest == "/assignee" and method == "PUT":
            i["assignee"] = {"accountId": payload["accountId"], "displayName": payload["accountId"]} if payload["accountId"] else None
            return {}
        if rest == "" and method == "PUT":
            for op in (payload.get("update") or {}).get("labels") or []:
                if "add" in op and op["add"] not in i["labels"]:
                    i["labels"].append(op["add"])
                if "remove" in op:
                    i["labels"] = [x for x in i["labels"] if x != op["remove"]]
            for k, v in (payload.get("fields") or {}).items():
                i[k] = v
            return {}
        if rest == "" and method == "GET":
            return {"key": key, "fields": {k: copy.deepcopy(v) for k, v in i.items() if k != "comments"}}
        raise AssertionError(f"unexpected {method} {path}")


def ns(**kw):
    return argparse.Namespace(**dict({"apply": False, "json": True}, **kw))


def run(fn, fake, **kw):
    """One jira verb against the fake, its JSON result; SystemExit text when it refuses."""
    import io, contextlib
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            fn({}, ns(**kw))
    except SystemExit as e:
        return {"exit": str(e.code)}
    out = buf.getvalue().strip()
    return json.loads(out) if out.startswith("{") else {"text": out}


def jira_runner(fake):
    """dry.py's runner: an `ela jira …` argv run against the fake, in process; → (rc, text)."""
    verbs = {"unlink": (J.cmd_unlink, lambda a: dict(target=a[0], id=a[2])),
             "comment-delete": (J.cmd_comment_delete, lambda a: dict(target=a[0], id=a[2])),
             "fixed-in": (J.cmd_fixed_in, lambda a: dict(targets=[a[0]], add=dict(zip(a[1::2], a[2::2])).get("--add"),
                                                         remove=dict(zip(a[1::2], a[2::2])).get("--remove"), clear=False)),
             "label": (J.cmd_label, lambda a: dict(targets=[a[0]], add=dict(zip(a[1::2], a[2::2])).get("--add"),
                                                   remove=dict(zip(a[1::2], a[2::2])).get("--remove"),
                                                   nonstandard=dict(zip(a[1::2], a[2::2])).get("--nonstandard"))),
             "assign": (J.cmd_assign, lambda a: dict(target=a[0], assignee=a[2]))}
    def go(argv, apply):
        fn, parse = verbs[argv[2]]
        r = run(fn, fake, apply=apply, **parse(argv[3:]))
        return (1 if "exit" in r else 0), json.dumps(r)
    return go


with tempfile.TemporaryDirectory() as R:
    os.environ["ELA_REPORTS"] = R
    os.environ.pop("ELA_NO_APPLY", None)
    fake = FakeJira()
    J._request_raw = fake
    J.vocabulary = lambda: None                              # the published label vocabulary is not this test's
    J._fixed_in_vocabulary = lambda: None
    J.resolve_mentions = lambda text: ({}, [])

    # ── the acts: each applied write keeps its before-state and its undo ──────────────────────────────────
    os.environ.update(ELA_ACT="2026-11-12-link-named-MH-1#1", ELA_CLASS="link-named")
    r = run(J.cmd_link, fake, target="MH-1", other="MH-2", type="contains", apply=True)
    check("link: the act carries the link id and its undo, unlink by that id",
          r.get("link_id") == "901" and r.get("undo") == ["ela", "jira", "unlink", "MH-1", "--id", "901"])
    os.environ.update(ELA_ACT="2026-11-12-parent-status-MH-1#1", ELA_CLASS="parent-status")
    r = run(J.cmd_comment, fake, targets=["MH-1"], text="Status — children as Jira shows them", from_file=None, no_mention=True, edit=None, apply=True)
    check("comment: the act carries the comment id and its undo", r.get("undo") == ["ela", "jira", "comment-delete", "MH-1", "--id", "902"])
    os.environ.update(ELA_ACT="2026-11-12-release-reconcile-qa-aws3-b90#1", ELA_CLASS="release-reconcile")
    r = run(J.cmd_fixed_in, fake, targets=["MH-1"], add="mh-app@2.0", remove=None, clear=False, apply=True)
    check("fixed-in: the act keeps the value before and takes out exactly what it added",
          r.get("undo") == ["ela", "jira", "fixed-in", "MH-1", "--remove", "mh-app@2.0"] and r.get("current") == "mh-app@1.0")
    os.environ.update(ELA_ACT="2026-11-12-release-reconcile-qa-aws3-b90#2")
    r = run(J.cmd_label, fake, targets=["MH-1"], add="release-2.1", remove=None, nonstandard=None, apply=True)
    check("label: the act keeps the labels before and takes out exactly what it added",
          r.get("undo") == ["ela", "jira", "label", "MH-1", "--remove", "release-2.1"] and r.get("labels") == ["keep"])
    os.environ.update(ELA_ACT="2026-11-12-assign-by-rule-MH-2#1", ELA_CLASS="assign-by-rule")
    J.resolve_assignee = (lambda real: lambda creds, who: (OTHER, "Engineer") if who == OTHER else real(creds, who))(J.resolve_assignee)
    r = run(J.cmd_assign, fake, target="MH-2", assignee=OTHER, apply=True)
    check("assign: the act keeps the prior assignee; nobody before reverses to none",
          r.get("undo") == ["ela", "jira", "assign", "MH-2", "--assignee", "none"] and r["before"]["assignee"] is None)
    for k in ("ELA_ACT", "ELA_CLASS"):
        os.environ.pop(k)
    rows = D.acts(R)
    check("five acts on record, each with its class, before-state and undo",
          [(x["class"], x["verb"]) for x in rows] == [("link-named", "link"), ("parent-status", "comment"),
                                                       ("release-reconcile", "fixed-in"), ("release-reconcile", "label"),
                                                       ("assign-by-rule", "assign")]
          and rows[2]["before"] == {"fixed_in": "mh-app@1.0"} and rows[3]["before"] == {"labels": ["keep"]})

    # ── the reverse atoms: dry run by default, refusals ──────────────────────────────────────────────────
    n = len(fake.calls)
    r = run(J.cmd_unlink, fake, target="MH-1", id="901")
    check("unlink: a dry run reads the link and writes nothing",
          r.get("reads") == "MH-1 contains MH-2" and not r["removed"] and not any(m != "GET" for m, _ in fake.calls[n:]))
    check("unlink: an id already gone is a no-op", "already gone" in run(J.cmd_unlink, fake, target="MH-1", id="999").get("text", "") + json.dumps(run(J.cmd_unlink, fake, target="MH-1", id="999", json=False)))
    fake.issues["MH-2"]["comments"].append({"id": "500", "author": {"accountId": OTHER, "displayName": "Engineer"}, "body": "theirs"})
    fake.issues["MH-2"]["comments"].append({"id": "501", "author": {"accountId": ME, "displayName": "Owner"}, "body": "typed by him"})
    check("comment-delete: anyone else's comment is refused", "refused" in run(J.cmd_comment_delete, fake, target="MH-2", id="500", apply=True).get("exit", ""))
    check("comment-delete: his own comment ela did not post is refused", "no act on record" in run(J.cmd_comment_delete, fake, target="MH-2", id="501", apply=True).get("exit", ""))
    check("both stay", len(fake.issues["MH-2"]["comments"]) == 2)

    # ── ela dry undo: dry run, then applied, then the correction ────────────────────────────────────────
    D.save_state(R, dict(D.load_state(R), **{"release-reconcile": {"tier": 1, "history": []}}))
    before = (fake.issues["MH-1"][J.FIXED_IN_FIELD], list(fake.issues["MH-1"]["labels"]))
    res = D.undo(R, "2026-11-12-release-reconcile-qa-aws3-b90", runner=jira_runner(fake))
    check("undo of a batch: a dry run by default, both writes shown, nothing changed",
          len(res["did"]) == 2 and all("dry run" in d for d in res["did"]) and fake.issues["MH-1"]["labels"] == ["keep", "release-2.1"])
    res = D.undo(R, "2026-11-12-release-reconcile-qa-aws3-b90", apply=True, runner=jira_runner(fake))
    fi = J.body_text(fake.issues["MH-1"][J.FIXED_IN_FIELD]) if fake.issues["MH-1"][J.FIXED_IN_FIELD] else ""
    check("undo applied: Fixed In and labels are as they were before the batch",
          res["ok"] and fi == "mh-app@1.0" and fake.issues["MH-1"]["labels"] == ["keep"])
    st = D.load_state(R)["release-reconcile"]
    check("undo records the correction: a granted class returns to confirm",
          st["tier"] == 3 and any(r.get("verdict") == "reverted" and r.get("class") == "release-reconcile" for r in D.record(R)))
    check("an undone act is not undone twice", all("already undone" in d for d in D.undo(R, "2026-11-12-release-reconcile-qa-aws3-b90", apply=True, runner=jira_runner(fake))["did"]))
    D.undo(R, "2026-11-12-link-named-MH-1#1", apply=True, runner=jira_runner(fake))
    check("undo a link: Jira no longer shows it on either side", not fake.issues["MH-1"]["issuelinks"] and not fake.issues["MH-2"]["issuelinks"])
    D.undo(R, "2026-11-12-parent-status-MH-1", apply=True, runner=jira_runner(fake))
    check("undo a status comment: ela's own comment is deleted", not fake.issues["MH-1"]["comments"])
    D.undo(R, "2026-11-12-assign-by-rule-MH-2#1", apply=True, runner=jira_runner(fake))
    check("undo an assignment: back to nobody", fake.issues["MH-2"]["assignee"] is None)
    try:
        D.undo(R, "no-such-act"); check("an unknown act is not found", False)
    except KeyError:
        check("an unknown act is not found", True)

    # ── the check: no grant ask until a class can be undone ─────────────────────────────────────────────
    for c, d in D.CLASSES.items():
        if not d.get("never"):
            ok, missing = D.reversible(c)
            check(f"{c}: its reverse atom is in jira.py ({', '.join(v + ' ' + f for v, f in d['reverse'])})", ok and not missing)
    rows = [{"class": "link-named", "verdict": "applied", "as_drafted": True, "at": f"2026-11-0{2 + i // 4}T1{i % 4}:00:00+08:00"} for i in range(12)]
    st = {"tier": 3, "history": []}
    check("a mature, reversible class earns its grant ask", D.grant_due("link-named", rows, st))
    saved = D.CLASSES["link-named"]["reverse"]
    D.CLASSES["link-named"]["reverse"] = (("relink-never", "--id"),)
    check("the same class without its reverse atom does not", not D.grant_due("link-named", rows, st)
          and D.reversible("link-named")[1] == ["jira relink-never --id"])
    try:
        D.answer(R, "grant:link-named:12", "A"); check("nor can a grant be answered yes", False)
    except ValueError as e:
        check("nor can a grant be answered yes", "undone" in str(e))
    D.CLASSES["link-named"]["reverse"] = saved

    # ── a dry answer's writes run as acts of their batch ───────────────────────────────────────────────
    seen = []
    D.subprocess = type("S", (), {"run": staticmethod(lambda cmd, **kw: seen.append(kw["env"]) or type("P", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()),
                                  "TimeoutExpired": Exception})
    D.run_write("ela jira link MH-1 MH-2 --type contains", False, action="2026-11-12-link-named-MH-1#3", word="answer", cls="link-named")
    check("a dry answer's write carries its act and class to jira.py", seen and seen[0].get("ELA_ACT") == "2026-11-12-link-named-MH-1#3"
          and seen[0].get("ELA_CLASS") == "link-named")
    import reconcile as RC  # noqa: E402
    envs = []
    RC.run_batch([{"lane": "qa-aws3", "build": "90", "rows": [{"key": "MH-7", "add": ["mh-app@3"], "label": "release-2.1"}]}],
                 today=datetime.date(2026, 11, 12), run=lambda argv, env=None: envs.append(env) or (0, "ok", ""))
    check("a reconcile batch's writes are acts of it, numbered, classed release-reconcile",
          [e["ELA_ACT"] for e in envs] == ["2026-11-12-release-reconcile-qa-aws3-b90#1", "2026-11-12-release-reconcile-qa-aws3-b90#2"]
          and {e["ELA_CLASS"] for e in envs} == {"release-reconcile"})

print(f"{len(failures)} failures" if failures else "dry undo: all offline checks passed")
sys.exit(1 if failures else 0)
