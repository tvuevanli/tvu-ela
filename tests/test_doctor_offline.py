#!/usr/bin/env python3
"""doctor offline: a sense probe's exit code read as ✓ / ! / ✗ (UR's exit 3 and Sentry's exit 4 are states, a timeout
is a failure), credential values masked in a probe's output, a fact source's gap or age, and a timer's next run —
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
st, detail, action = D.classify("lanes", 4, "", "tvutest login failed: 0x80060018 not activated")
check("lanes auth refusal fails and quotes the server", st == D.FAIL and "0x80060018" in detail and "tvutest" in action)
check("slack auth refusal names its key", "SLACK_BOT_TOKEN" in D.classify("slack", 4, "", "invalid_auth")[2])
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
