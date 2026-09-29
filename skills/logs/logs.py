#!/usr/bin/env python3
"""Service logs, read first-hand — tvulog (UAS: the process-log and the java-log) and Loki through Observer.
L1: subcommands, --json, stdlib only, read-only. A sense: it reports what the logs say; which service owns the
failure is /ela:route's judgment.

  chain <traceId> [--days N]                    process-log records of one trace, time-ordered, one line per HTTP
                                                hop (inbound and outbound): time, callee, method, path, status, ms,
                                                errorCode from the reply; the first failing hop is marked. -v: params
                                                and result
  java  --trace <id> [--date D | --days N]      java-log lines (each Java service's own slf4j lines and stacks)
  java  --app <appname> --at <time> [--window 5s] [--env E] [--level L] [--grep text]…
                                                one service's lines around a moment — the pivot when a trace breaks:
                                                a service the trace id did not reach still logged the failure second
  calls --server <serverName> | --email <addr>  --at <time> [--window 10s] [--grep text]…
                                                process-log records around a moment for one service or one user
  loki  --pid <processId> | --service S | --query LogQL  [--since 1h | --from T --to T | --at T --window W] [--grep text]…
                                                Loki lines through Observer (media services, by process id)

Times. `--at`, `--from`, `--to` take `YYYY-MM-DD HH:MM:SS[.fff]` (read as UTC unless an offset is given), ISO 8601,
or epoch seconds/milliseconds. Every line prints UTC and the machine's local time. The java-log stores UTC strings;
the process-log stores epoch milliseconds; Loki takes epoch seconds — the script converts.

Source quirks, verified 2026-09-29 and handled here so a caller need not know them:
  - the process-log keeps the trace id in `peerId`; its `traceId` field is null and its `traceId` filter is ignored
    (the call returns every row). `chain` filters on peerId.
  - the java-log filter key is `traceId` (camel case); `traceid` is ignored. Its `message` filter does not match ids,
    so `--grep` filters on the client.
  - process-log windows are at most 7 days per call; `chain --days` over 7 is read in 7-day slices.
  - display names (`serverName`, `peerId`) sometimes arrive wrapped in HTML; tags are stripped.
  - Loki windows are at most 4 hours.

Hosts and credentials. tvulog: TVU_LOG_BASE (default the tvuuas API on tvulog.tvunetworks.com), the person's TVU
session from `ela login tvu` (~/.claude/ela/session.json) as the Authorization header and the SID cookie; a refusal
is recorded on the session and exits 4 naming the command. Observer: TVU_OBSERVER_BASE (default mma1.tvunetworks.com),
TVU_CC_BEARER_TOKEN. Both from the environment → --env-file → $ELA_ENV_FILE.
Exit codes: 0 ok · 2 usage · 3 nothing found (what was searched is printed) · 4 auth · 5 remote error.
"""
import argparse, datetime, html, json, os, re, signal, sys, urllib.error, urllib.parse, urllib.request

SKILLS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(SKILLS, "release"))
import release as R  # noqa: E402  — the person's TVU session: reader, refusal record, the login hint

EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE = 2, 3, 4, 5
UAS_DEFAULT = "https://tvulog.tvunetworks.com/tvuuas"
OBSERVER_DEFAULT = "https://mma1.tvunetworks.com"
PROCESS_WINDOW = datetime.timedelta(days=7)
LOKI_WINDOW = datetime.timedelta(hours=4)
UTC = datetime.timezone.utc
OK_CODES = {"0x0", "0", "200", "0x00"}
UNITS = {"ms": "milliseconds", "s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


def die(msg, code):
    print(msg, file=sys.stderr); sys.exit(code)


# ── time ─────────────────────────────────────────────────────────────────────

def parse_time(s):
    """A moment → aware UTC datetime. Bare wall-clock strings are UTC: the java-log's own clock."""
    s = str(s).strip()
    if re.fullmatch(r"\d{13}", s):
        return datetime.datetime.fromtimestamp(int(s) / 1000, UTC)
    if re.fullmatch(r"\d{10}", s):
        return datetime.datetime.fromtimestamp(int(s), UTC)
    t = s.replace("Z", "+00:00")
    try:
        d = datetime.datetime.fromisoformat(t)
    except ValueError:
        die(f"unreadable time {s!r} — use 'YYYY-MM-DD HH:MM:SS' (UTC), ISO 8601 or epoch seconds/ms", EX_USAGE)
    return d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)


def parse_span(s):
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)", str(s).strip())
    if not m:
        die(f"unreadable duration {s!r} — e.g. 500ms, 5s, 2m, 1h, 3d", EX_USAGE)
    n, unit = float(m.group(1)), m.group(2)
    return datetime.timedelta(**{UNITS[unit]: n})


def ms(d):
    return int(d.timestamp() * 1000)


def uas_str(d):
    return d.strftime("%Y-%m-%d %H:%M:%S.") + f"{d.microsecond // 1000:03d}"


def show_time(d):
    """UTC first — the logs' clock — and the machine's local time beside it."""
    if d is None:
        return "?"
    return f"{d.strftime('%Y-%m-%d %H:%M:%S.')}{d.microsecond // 1000:03d}Z ({d.astimezone().strftime('%H:%M:%S')} local)"


def from_ms(v):
    try:
        return datetime.datetime.fromtimestamp(int(v) / 1000, UTC)
    except (TypeError, ValueError):
        return None


def from_uas(v):
    try:
        return datetime.datetime.strptime(str(v)[:23], "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=UTC)
    except ValueError:
        try:
            return datetime.datetime.strptime(str(v)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        except ValueError:
            return None


def window(a, default_span):
    """--at/--window, or --from/--to → (start, end) in UTC."""
    if getattr(a, "frm", None) or getattr(a, "to", None):
        if not (a.frm and a.to):
            die("--from and --to go together", EX_USAGE)
        s, e = parse_time(a.frm), parse_time(a.to)
    elif getattr(a, "at", None):
        at, w = parse_time(a.at), parse_span(a.window or default_span)
        s, e = at - w, at + w
    else:
        return None
    if e <= s:
        die("the window ends before it starts", EX_USAGE)
    return s, e


# ── transport ────────────────────────────────────────────────────────────────

def strip(v):
    return html.unescape(re.sub(r"<[^>]+>", "", v)) if isinstance(v, str) else v


def request(url, headers, params=None, body=None, timeout=40):
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    h = {"Accept": "application/json", **headers}
    if body is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=h,
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw)
            except ValueError:
                return r.status, raw.decode("utf-8", "replace")[:300]
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw[:300]
    except Exception as e:
        return 0, str(e)[:200]


class UAS:
    """tvulog's API, under the person's TVU session. A refusal is recorded like release.py records it."""
    def __init__(self, env_file):
        self.base = (R.env_value("TVU_LOG_BASE", env_file) or UAS_DEFAULT).rstrip("/")
        s = R._load_sessions().get("tvu") or {}
        self.sid = s.get("sid") if not s.get("rejected_at") else None
        if not self.sid:
            R._need_login("tvu", "missing" if not s.get("sid") else f"refused at {s.get('rejected_at')}")

    def call(self, path, params=None, body=None):
        st, res = request(self.base + path, {"Authorization": self.sid, "Cookie": f"SID={self.sid}"}, params, body)
        if R._auth_failed(st, res):
            R._mark_rejected("tvu"); R._need_login("tvu", f"refused by tvulog (HTTP {st})")
        if st != 200 or not isinstance(res, dict):
            die(f"tvulog {path}: HTTP {st} {str(res)[:200]}", EX_REMOTE)
        if str(res.get("errorCode")) not in OK_CODES:
            die(f"tvulog {path}: {res.get('errorCode')} {res.get('errorInfo')}", EX_REMOTE)
        return res.get("result") or {}

    def pages(self, path, limit, params=None, body=None, size=100):
        """Page through a PageHelper envelope (list · hasNextPage) until `limit` records."""
        out, n = [], 1
        while len(out) < limit:
            if body is not None:
                r = self.call(path, body={**body, "pageNum": n, "pageSize": size})
            else:
                r = self.call(path, params={**params, "pageNum": n, "pageSize": size})
            out += r.get("list") or []
            if not r.get("hasNextPage"):
                return out, int(r.get("total") or len(out))
            n += 1
        return out[:limit], None


# ── process-log ──────────────────────────────────────────────────────────────

def reply_code(result):
    """errorCode and errorInfo of a TVU envelope in the recorded reply; (None, None) when the reply is not one."""
    if not isinstance(result, str) or "errorCode" not in result:
        return None, None
    try:
        j = json.loads(result)
        if isinstance(j, dict) and "errorCode" in j:
            return str(j.get("errorCode")), j.get("errorInfo")
    except ValueError:
        pass
    c = re.search(r'"errorCode"\s*:\s*"?([^",}\s]+)', result)
    i = re.search(r'"errorInfo"\s*:\s*"([^"]*)"', result)
    return (c.group(1) if c else None), (i.group(1) if i else None)


def hop(r):
    code, info = reply_code(r.get("result"))
    try:
        status = int(r.get("status") or 0)
    except ValueError:
        status = 0
    ua = strip(r.get("userAgent") or "")
    uri = strip(r.get("requestUri") or "")
    return {
        "time": from_ms(r.get("requestTime")), "answered": from_ms(r.get("responseTime")),
        "server": strip(r.get("serverName") or ""), "method": r.get("method"), "uri": uri,
        "path": urllib.parse.urlparse(uri).path or uri, "status": status, "ms": r.get("consumeTime"),
        "error_code": code, "error_info": info,
        "failed": status >= 400 or (code is not None and code not in OK_CODES),
        "caller": "browser" if ua.startswith("Mozilla") else ua, "trace": strip(r.get("peerId")),
        "email": r.get("email"), "user": r.get("user"), "ip": r.get("ip"), "kind": r.get("dpi"),
        "params": r.get("params"), "result": r.get("result"),
    }


def hop_json(h):
    return {**h, "time": h["time"].isoformat() if h["time"] else None,
            "answered": h["answered"].isoformat() if h["answered"] else None,
            "time_ms": ms(h["time"]) if h["time"] else None}


def print_hops(hops, verbose, first=None):
    for h in hops:
        mark = "✗" if h["failed"] else " "
        err = f"{h['error_code']} {h['error_info'] or ''}".strip() if h["error_code"] and h["error_code"] not in OK_CODES else ""
        tail = "   ◀ first failing hop" if h is first else ""
        print(f"{mark} {show_time(h['time'])}  {h['server']}  {h['method']} {h['path']}  {h['status']}  {h['ms']}ms"
              f"{('  ' + err) if err else ''}  ← {h['caller'][:40] or '?'}{tail}")
        if verbose:
            print(f"      uri    {h['uri']}")
            print(f"      params {str(h['params'] or '')[:2000]}")
            print(f"      result {str(h['result'] or '')[:2000]}")


def first_failing(hops):
    """The innermost error: of the failing hops, the one that answered first. An outer hop forwards the same
    code later, so answering order — not start order — points at where the error entered the chain."""
    bad = [h for h in hops if h["failed"]]
    return min(bad, key=lambda h: (h["answered"] or h["time"] or datetime.datetime.max.replace(tzinfo=UTC))) if bad else None


def cmd_chain(a):
    uas = UAS(a.env_file)
    end = datetime.datetime.now(UTC); start = end - datetime.timedelta(days=a.days)
    recs, s = [], start
    while s < end:
        e = min(s + PROCESS_WINDOW, end)
        got, _ = uas.pages("/process/page-es", a.limit, params={"startTime": ms(s), "endTime": ms(e), "peerId": a.trace})
        recs += got; s = e
    searched = f"process-log peerId={a.trace} from {show_time(start)} to {show_time(end)}"
    if not recs:
        die(f"no process-log records — searched {searched}. The trace id may not have been propagated, "
            f"or the call is older than --days {a.days}", EX_NOTFOUND)
    hops = sorted((hop(r) for r in recs), key=lambda h: (h["time"] or start))
    first = first_failing(hops)
    if a.json:
        print(json.dumps({"trace": a.trace, "searched": searched, "hops": [hop_json(h) for h in hops],
                          "first_failing": hops.index(first) if first else None}, ensure_ascii=False, indent=1, default=str))
        return
    print(f"trace {a.trace} · {len(hops)} hop(s) · ✗ failed (status ≥ 400 or a non-0x0 errorCode in the reply)")
    print_hops(hops, a.verbose, first)
    if first:
        day = first["time"].strftime("%Y-%m-%d")
        print(f"\nnext: ela logs java --trace {a.trace} --date {day}   (the services' own lines under this trace)")
    else:
        print("\nno failing hop in the process-log; the failure, if any, is below the recorded calls")


def cmd_calls(a):
    if not (a.server or a.email):
        die("calls needs --server <serverName> or --email <address>", EX_USAGE)
    s, e = window(a, "10s") or die("calls needs --at <time> (or --from/--to)", EX_USAGE)
    if e - s > PROCESS_WINDOW:
        die("the process-log answers at most 7 days per call; narrow the window", EX_USAGE)
    uas = UAS(a.env_file)
    recs, total = uas.pages("/process/page-es", a.limit, params={"startTime": ms(s), "endTime": ms(e),
                                                                  "serverName": a.server, "email": a.email})
    hops = [h for h in (hop(r) for r in recs) if all(g.lower() in json.dumps(h, default=str).lower() for g in a.grep or [])]
    hops.sort(key=lambda h: (h["time"] or s))
    who = " ".join(f"{k}={v}" for k, v in (("serverName", a.server), ("email", a.email)) if v)
    searched = f"process-log {who} from {show_time(s)} to {show_time(e)}" + (f" grep {a.grep}" if a.grep else "")
    if not hops:
        die(f"no process-log records — searched {searched}", EX_NOTFOUND)
    if a.json:
        print(json.dumps({"searched": searched, "total": total, "hops": [hop_json(h) for h in hops]}, ensure_ascii=False, indent=1, default=str))
        return
    print(f"{len(hops)} record(s){'' if total is not None else ' (limit reached — narrow the window)'} · {searched}")
    print_hops(hops, a.verbose)


# ── java-log ─────────────────────────────────────────────────────────────────

FRAME = re.compile(r"^\s*at\s+(com\.tvu\S+)", re.M)


def jline(r):
    msg = r.get("message") or ""
    return {"time": from_uas(r.get("logtime")), "logtime": r.get("logtime"), "app": strip(r.get("appname")),
            "env": r.get("env"), "level": r.get("loglevel"), "trace": r.get("traceid"), "thread": r.get("thread"),
            "host": r.get("hostIP"), "region": r.get("region"), "message": msg,
            "frame": (FRAME.search(msg).group(1) if FRAME.search(msg) else None)}


def cmd_java(a):
    if not (a.trace or a.app):
        die("java needs --trace <id> or --app <appname>: unfiltered, the java-log is every service's every line", EX_USAGE)
    w = window(a, "5s")
    if w:
        s, e = w
    elif a.date:
        s = parse_time(a.date + " 00:00:00"); e = s + datetime.timedelta(days=1)
    elif a.trace:
        e = datetime.datetime.now(UTC); s = e - datetime.timedelta(days=a.days)
    else:
        die("java --app needs --at <time> (or --from/--to, or --date)", EX_USAGE)
    body = {"startTime": uas_str(s), "endTime": uas_str(e), "traceId": a.trace, "appName": a.app, "env": a.env,
            "logLevel": a.level}
    body = {k: v for k, v in body.items() if v}
    recs, total = UAS(a.env_file).pages("/log/selectAllJavaLog", a.limit, body=body)
    lines = [jline(r) for r in recs]
    lines = [l for l in lines if all(g.lower() in l["message"].lower() for g in a.grep or [])]
    lines.sort(key=lambda l: (l["time"] or s))
    filt = " ".join(f"{k}={v}" for k, v in body.items() if k not in ("startTime", "endTime"))
    searched = f"java-log {filt} from {show_time(s)} to {show_time(e)}" + (f" grep {a.grep}" if a.grep else "")
    if not lines:
        die(f"no java-log lines — searched {searched}" + (". A service the trace id did not reach logs under its own "
            "trace id: read it by --app and --at" if a.trace else ""), EX_NOTFOUND)
    if a.json:
        print(json.dumps({"searched": searched, "total": total,
                          "lines": [{**l, "time": l["time"].isoformat() if l["time"] else None} for l in lines]},
                         ensure_ascii=False, indent=1))
        return
    print(f"{len(lines)} line(s){'' if total is not None else ' (limit reached — narrow the window)'} · {searched}")
    for l in lines:
        first = l["message"].split("\n", 1)[0]
        shown = first if a.verbose else first[:a.width]
        for g in a.grep or []:                    # a match cut off by --width is shown in context, not lost
            i = l["message"].lower().find(g.lower())
            if i >= 0 and g.lower() not in shown.lower():
                shown += " … " + l["message"][max(0, i - 80):i + len(g) + 80].replace("\n", " ⏎ ")
        print(f"{show_time(l['time'])}  {l['app']}[{l['env']}]  {l['level']:<5}  trace={l['trace']}  {shown}")
        if a.verbose and "\n" in l["message"]:
            for x in l["message"].split("\n")[1:a.stack + 1]:
                print(f"      {x}")
        elif l["frame"]:
            print(f"      ↳ at {l['frame']}")


# ── Loki through Observer ────────────────────────────────────────────────────

def cmd_loki(a):
    if not (a.pid or a.service or a.query):
        die("loki needs --pid, --service or --query", EX_USAGE)
    tok = R.env_value("TVU_CC_BEARER_TOKEN", a.env_file)
    if not tok:
        die("no TVU_CC_BEARER_TOKEN (env, $ELA_ENV_FILE, or --env-file) — /ela:setup", EX_AUTH)
    base = (R.env_value("TVU_OBSERVER_BASE", a.env_file) or OBSERVER_DEFAULT).rstrip("/")
    w = window(a, "5m")
    if w:
        s, e = w
    else:
        e = datetime.datetime.now(UTC); s = e - parse_span(a.since)
    if e - s > LOKI_WINDOW:
        die("Loki answers at most 4 hours per call; narrow the window", EX_USAGE)
    if a.query:
        q = a.query
    else:
        q = '{service_name="%s"}' % a.service if a.service else '{service_name=~".+"}'
        if a.pid:
            q += " | process_id = `%s`" % a.pid
    for g in a.grep or []:
        q += " |= `%s`" % g
    st, body = request(base + "/api/observer/v1/log", {"Authorization": f"Bearer {tok}"},
                       {"query": q, "start": int(s.timestamp()), "end": int(e.timestamp()) + 1, "limit": a.limit,
                        "direction": "backward"})
    if st in (401, 403):
        die(f"Observer refused the bearer token (HTTP {st}) — TVU_CC_BEARER_TOKEN; /ela:setup", EX_AUTH)
    if st != 200 or not isinstance(body, dict):
        die(f"Observer log: HTTP {st} {str(body)[:200]}", EX_REMOTE)
    env = body
    while isinstance(env, dict) and "result" not in env and isinstance(env.get("data"), dict):
        env = env["data"]
    if isinstance(body, dict) and body.get("status") not in (None, "success"):
        die(f"Observer log: {str(body)[:300]}", EX_REMOTE)
    lines = []
    for stream in (env or {}).get("result") or []:
        lab = stream.get("stream") or {}
        for pair in stream.get("values") or []:
            if len(pair) < 2:
                continue
            try:
                t = datetime.datetime.fromtimestamp(int(pair[0]) / 1e9, UTC)
            except (TypeError, ValueError):
                t = None
            lines.append({"time": t, "line": str(pair[1]), "service": lab.get("service_name"), "pid": lab.get("process_id"),
                          "host": lab.get("host_name"), "file": lab.get("log_file_name"), "level": lab.get("level")})
    lines.sort(key=lambda l: (l["time"] or s))
    searched = f"Loki {q} from {show_time(s)} to {show_time(e)}"
    if not lines:
        die(f"no Loki lines — searched {searched}", EX_NOTFOUND)
    if a.json:
        print(json.dumps({"searched": searched, "lines": [{**l, "time": l["time"].isoformat() if l["time"] else None} for l in lines]},
                         ensure_ascii=False, indent=1))
        return
    print(f"{len(lines)} line(s){' (limit reached)' if len(lines) >= a.limit else ''} · {searched}")
    for l in lines:
        print(f"{show_time(l['time'])}  {l['service']}/{l['file'] or '?'}  {l['level'] or ''}  "
              f"{l['line'] if a.verbose else l['line'][:a.width]}")


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description="Service logs, first-hand and read-only: tvulog (process-log, java-log) and Loki.")
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, limit):
        p.add_argument("--limit", type=int, default=limit)
        p.add_argument("-v", "--verbose", action="store_true")
        p.add_argument("--width", type=int, default=240, help="characters of a line shown without -v")
        p.add_argument("--json", action="store_true")

    def moment(p, span):
        p.add_argument("--at", help="the moment (UTC unless an offset is given)")
        p.add_argument("--window", help=f"± around --at (default {span})")
        p.add_argument("--from", dest="frm"); p.add_argument("--to")
        p.add_argument("--grep", action="append", help="keep lines containing this text (repeatable; all must match)")

    p = sub.add_parser("chain", help="process-log records of one trace, the first failing hop marked")
    p.add_argument("trace"); p.add_argument("--days", type=int, default=7, help="how far back (default 7)"); common(p, 500)
    p = sub.add_parser("java", help="java-log lines by trace, or by app around a moment")
    p.add_argument("--trace"); p.add_argument("--app"); p.add_argument("--env"); p.add_argument("--level")
    p.add_argument("--date", help="a UTC day, YYYY-MM-DD"); p.add_argument("--days", type=int, default=1)
    p.add_argument("--stack", type=int, default=40, help="stack lines shown with -v"); moment(p, "5s"); common(p, 300)
    p = sub.add_parser("calls", help="process-log records around a moment for one service or user")
    p.add_argument("--server"); p.add_argument("--email"); moment(p, "10s"); common(p, 300)
    p = sub.add_parser("loki", help="Loki lines through Observer")
    p.add_argument("--pid"); p.add_argument("--service"); p.add_argument("--query")
    p.add_argument("--since", default="1h"); moment(p, "5m"); common(p, 500)
    a = ap.parse_args()
    {"chain": cmd_chain, "java": cmd_java, "calls": cmd_calls, "loki": cmd_loki}[a.cmd](a)


if __name__ == "__main__":
    main()
