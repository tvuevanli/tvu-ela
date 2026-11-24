#!/usr/bin/env python3
"""logs offline: a process-log or Loki read covers the last 5 minutes by default; a wider window passes only with
--wide "<reason>", and the reason is printed on the result (text and --json); an all-services Loki query is refused,
--wide or not. A stub transport stands in for tvulog and Observer: the real one raises if it is ever reached. No
network, no session, no credential."""
import datetime, io, json, os, sys, urllib.request
from contextlib import redirect_stderr, redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "logs"))
import logs as L  # noqa: E402

failures = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


# ── the stub transport ──────────────────────────────────────────────────────────────────────────────
def no_network(*a, **k):
    raise AssertionError("the real transport was reached")


urllib.request.urlopen = no_network
NOW = datetime.datetime(2026, 11, 24, 8, 0, 0, tzinfo=L.UTC)
L.now = lambda: NOW
sent = []                                      # (kind, params) of every read the stub answered


def stub_request(url, headers, params=None, body=None, timeout=40):
    sent.append(("loki", dict(params or {})))
    ns = str(int((NOW - datetime.timedelta(minutes=1)).timestamp() * 1e9))
    return 200, {"status": "success", "data": {"result": [
        {"stream": {"service_name": "copier", "process_id": "p1"}, "values": [[ns, "[20261124 07:59:00.000 I] up"]]}]}}


class StubUAS:
    def __init__(self, env_file):
        pass

    def pages(self, path, limit, params=None, body=None, size=100):
        sent.append(("uas", dict(params or {})))
        return [{"peerId": "t1", "serverName": "svc", "url": "/x", "method": "GET", "status": 200,
                 "startTime": int((NOW - datetime.timedelta(minutes=1)).timestamp() * 1000), "cost": 3}], 1


L.request = stub_request
L.UAS = StubUAS
L.R.env_value = lambda key, env_file=None: "stub-token" if key == "TVU_CC_BEARER_TOKEN" else None


def run(*argv):
    """→ (exit code, stdout, stderr) of `logs.py argv`."""
    out, err, code = io.StringIO(), io.StringIO(), 0
    sent.clear()
    sys.argv = ["logs.py", *argv]
    with redirect_stdout(out), redirect_stderr(err):
        try:
            L.main()
        except SystemExit as e:
            code = e.code or 0
    return code, out.getvalue(), err.getvalue()


def span(params, kind):
    if kind == "loki":
        return params["end"] - params["start"]
    return (params["endTime"] - params["startTime"]) / 1000


# ── the default read: the last 5 minutes ────────────────────────────────────────────────────────────
for argv, kind in [(["loki", "--pid", "p1"], "loki"), (["calls", "--server", "svc"], "uas"), (["chain", "t1"], "uas")]:
    code, out, err = run(*argv)
    check(f"{argv[0]}: default read succeeds", code == 0 and len(sent) == 1)
    check(f"{argv[0]}: default read is the last 5 minutes", sent and abs(span(sent[0][1], kind) - 300) <= 1)
    check(f"{argv[0]}: a narrow read prints no wide line", "wide read" not in out)

code, out, err = run("loki", "--service", "copier", "--at", "2026-11-24 07:00:00")
check("loki --at: default ±2m, under 5 minutes", code == 0 and abs(span(sent[0][1], "loki") - 241) <= 1)

# ── wider than 5 minutes: refused without --wide, before any read ───────────────────────────────────
for argv in (["loki", "--pid", "p1", "--since", "20m"], ["calls", "--email", "a@b", "--since", "1h"],
             ["chain", "t1", "--since", "1d"], ["loki", "--service", "copier", "--at", "2026-11-24 07:00:00", "--window", "3m"]):
    code, out, err = run(*argv)
    check(f"{' '.join(argv[:1] + argv[-2:])}: refused without --wide", code == L.EX_USAGE and not sent)
    check(f"{' '.join(argv[:1] + argv[-2:])}: the refusal names --wide", "--wide" in err)

code, out, err = run("loki", "--pid", "p1", "--since", "20m", "--wide", "  ")
check("--wide with an empty reason is refused", code == L.EX_USAGE and not sent and "reason" in err)

# ── wider with --wide: read, the reason printed ─────────────────────────────────────────────────────
WHY = "MH-4049: the hang began some time in the last hour"
for argv, kind, secs in [(["loki", "--pid", "p1", "--grep", "srt", "--since", "20m"], "loki", 1200),
                         (["calls", "--server", "svc", "--since", "1h"], "uas", 3600),
                         (["chain", "t1", "--since", "2d"], "uas", 172800)]:
    code, out, err = run(*argv, "--wide", WHY)
    check(f"{argv[0]} --wide: read", code == 0 and len(sent) == 1)
    check(f"{argv[0]} --wide: the window asked for is the window sent", sent and abs(span(sent[0][1], kind) - secs) <= 1)
    check(f"{argv[0]} --wide: the reason is printed on the result", f"wide read" in out and WHY in out)
    code, out, err = run(*argv, "--wide", WHY, "--json")
    check(f"{argv[0]} --wide --json: the reason is a field", code == 0 and json.loads(out).get("wide") == WHY)

code, out, err = run("chain", "t1", "--since", "10d", "--wide", WHY)
check("chain --wide over 7 days is read in 7-day slices", code == 0 and len(sent) == 2)
code, out, err = run("loki", "--pid", "p1", "--grep", "x", "--since", "5h", "--wide", WHY)
check("loki: the server's 4-hour ceiling holds with --wide", code == L.EX_USAGE and not sent)

# ── all services: refused, --wide or not ────────────────────────────────────────────────────────────
for q in ('{service_name=~".+"}', '{service_name=~".+"} |= `error`', '{host_name="box1"}', '{service_name=~"copier|decoder"}'):
    for extra in ([], ["--wide", WHY]):
        code, out, err = run("loki", "--query", q, *extra)
        check(f"all-services query refused{' with --wide' if extra else ''}: {q}",
              code == L.EX_USAGE and not sent and "all-services" in err)
for q in ('{service_name="copier"} |= `srt`', '{service_name=~".+"} | process_id = `p1`'):
    code, out, err = run("loki", "--query", q)
    check(f"one-source query passes: {q}", code == 0 and len(sent) == 1)

print(f"\n{len(failures)} failure(s)" if failures else "\nall passed")
sys.exit(1 if failures else 0)
