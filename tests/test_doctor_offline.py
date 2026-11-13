#!/usr/bin/env python3
"""doctor offline: a sense probe's exit code read as ✓ / ! / ✗ (UR's exit 3, Sentry's exit 4 and the QA host not
admitting the account are states, a timeout is a failure), credential values masked in a probe's output, a fact source's gap or age, and a timer's next run —
calendar or monotonic — and its service's last result. No network, no systemctl."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "doctor"))
import doctor as D  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

# ── senses ──────────────────────────────────────────────────────────────────────────────────────────
check("exit 0 answers", D.classify("jira", 0, "MH-1 x", "")[0] == D.OK)
check("UR exit 3 (no graphs of mine) is ok", D.classify("ur", 3, "", "no graphs")[0] == D.OK)
check("Sentry exit 4 is a warn (no token yet)", D.classify("sentry", 4, "", "no SENTRY_TOKEN")[0] == D.WARN)
st, detail, action = D.classify("browser", 4, "", "no cookies")
check("browser exit 4 fails with the login action", st == D.FAIL and "ela login tvu --force" in action)
refusal = "tvutest login failed: HTTP 200 {'errorCode': '0x80060018', 'errorInfo': \"This account hasn't been activated\", 'result': None}"
st, detail, action = D.classify("lanes", 4, "", refusal)
check("the QA host not admitting the account is a warn that names the state and where QA versions come from, no action",
      st == D.WARN and "a state, not a fault" in detail and "2026-11-04" in detail and "report mails" in detail and action == "")
st, detail, action = D.classify("lanes", 4, "", "tvutest login failed: HTTP 200 {'errorCode': '0x80060004', 'errorInfo': 'wrong password', 'result': None}")
check("another error code from the QA login still fails, quotes the server and names the keys",
      st == D.FAIL and "0x80060004" in detail and "TVUTEST_ACCOUNT" in action)
check("the QA lanes probe with no account in the env file still fails",
      D.classify("lanes", 4, "", "no TVUTEST_ACCOUNT / TVUTEST_PASSWORD in the env file")[0] == D.FAIL)
check("the QA lanes probe failing remotely or timing out still fails",
      D.classify("lanes", 5, "", refusal)[0] == D.FAIL and D.classify("lanes", None, "", "", timeout=30)[0] == D.FAIL)
check("the same refusal on another host is a failure: only the QA host's is the known state",
      D.classify("lanes-cn", 4, "", refusal.replace("tvutest", "China"))[0] == D.FAIL)
st, detail, action = D.classify("lanes-cn", 2, "", "China host not configured: add site.json services.userservice-cn.url")
check("the China host not configured is a warn, never a failure", st == D.WARN and "not configured" in detail)
check("a China login refusal names its key", "TVU_CN_ACCOUNT" in D.classify("lanes-cn", 4, "", "China login failed")[2])
check("the QA lanes probe names its host, so the every-host default cannot pass for it", D.SENSES["lanes"][1][:3] == ["envs", "--host", "qa"])
cn = D.china_checks(["site.json services.userservice-cn.url", "TVU_CN_ACCOUNT / TVU_CN_PASSWORD in the env file"])
check("the China host's missing names are one line each, as warns", [c["status"] for c in cn] == [D.WARN, D.WARN]
      and "services.userservice-cn.url" in cn[0]["detail"] and "ela secret TVU_CN_ACCOUNT" in cn[1]["action"] and D.china_checks([]) == [])
check("slack auth refusal names its key", "SLACK_BOT_TOKEN" in D.classify("slack", 4, "", "invalid_auth")[2])
check("j2n auth refusal names the owner's sign-in", "TVU_PASSWORD" in D.classify("j2n", 4, "", "sign-in refused")[2])
check("a timeout is a failure", D.classify("kb", None, "", "", timeout=30)[0] == D.FAIL)
check("exit 5 is a remote failure", D.classify("jenkins", 5, "", "HTTP 502")[0] == D.FAIL)
value = "masked-value-0123456789"
check("a credential value in the output is masked",
      value not in D.classify("slack", 4, "", f"refused: {value}", secrets=[value])[1])

# ── facts ───────────────────────────────────────────────────────────────────────────────────────────
at = "2026-11-09T08:05:52+08:00"
check("fresh without a gap is ok", D.classify_fact("jira", {"at": at, "fresh": True, "gap": None})["status"] == D.OK)
c = D.classify_fact("lanes", {"at": at, "fresh": True, "gap": {"why": "qa: exit 4", "partial": True}})
check("a recorded gap warns with its why", c["status"] == D.WARN and "qa: exit 4" in c["detail"])
check("stale warns", D.classify_fact("mail", {"at": at, "fresh": False, "gap": None})["status"] == D.WARN)
check("never read warns", D.classify_fact("slack", {})["status"] == D.WARN)

# ── timers ──────────────────────────────────────────────────────────────────────────────────────────
base = {"UnitFileState": "enabled", "ActiveState": "active", "Unit": "ela-x.service"}
check("calendar next run is ok", D.classify_timer("ela-x.timer", {**base, "NextElapseUSecRealtime": "Tue 2026-11-10 02:00:00 CST"},
                                                  {"Result": "success"})["status"] == D.OK)
c = D.classify_timer("ela-k.timer", {**base, "NextElapseUSecRealtime": "", "NextElapseUSecMonotonic": "32min 21.97s"}, {})
check("monotonic next run is ok", c["status"] == D.OK and "32min 21s" in c["detail"])
check("no next run fails", D.classify_timer("ela-x.timer", {**base, "NextElapseUSecRealtime": ""}, {})["status"] == D.FAIL)
check("disabled fails", D.classify_timer("ela-x.timer", {**base, "UnitFileState": "disabled"}, {})["status"] == D.FAIL)
c = D.classify_timer("ela-x.timer", {**base, "NextElapseUSecRealtime": "Tue"}, {"Result": "exit-code"})
check("a failed last run fails with the journal", c["status"] == D.FAIL and "journalctl" in c["action"])

# ── summary ─────────────────────────────────────────────────────────────────────────────────────────
n, line = D.summary([D.check("senses", "lanes", D.FAIL), D.check("senses", "jira", D.OK), D.check("facts", "x", D.WARN)])
check("summary counts and names the failures", n == {D.OK: 1, D.WARN: 1, D.FAIL: 1} and "senses lanes" in line)

if failures:
    print(f"doctor offline: {len(failures)} failed"); sys.exit(1)
print("doctor offline: all passed")
