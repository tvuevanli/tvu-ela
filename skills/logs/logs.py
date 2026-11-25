#!/usr/bin/env python3
"""Service logs, read first-hand — tvulog (UAS: the process-log and the java-log) and Loki through Observer.
L1: subcommands, --json, stdlib only, read-only. A sense: it reports what the logs say; which service owns the
failure is /ela:route's judgment.

  chain <traceId> [--at T | --since 5m]        process-log records of one trace, time-ordered, one line per HTTP
                                                hop (inbound and outbound): time, callee, method, path, status, ms,
                                                errorCode from the reply; the first failing hop is marked. -v: params
                                                and result
  java  --trace <id> [--date D | --days N]      java-log lines (each Java service's own slf4j lines and stacks)
  java  --app <appname> --at <time> [--window 5s] [--env E] [--level L] [--grep text]…
                                                one service's lines around a moment — the pivot when a trace breaks:
                                                a service the trace id did not reach still logged the failure second
  calls --server <serverName> | --email <addr>  [--at <time> [--window 10s] | --since 5m] [--grep text]…
                                                process-log records around a moment for one service or one user
  loki  --pid <processId> | --service S | --query LogQL  [--since 5m | --from T --to T | --at T --window W] [--grep text]…
                                                Loki lines through Observer (media services, by process id)
  status --pid P | --graph G  [--since 6h | --from T --to T]
                                                Observer status events per process (lifecycle, format descriptor,
                                                connection state, alerts), runs folded; with --graph also the
                                                graph-level J2N stages. Read where Loki has nothing: a site that
                                                ships no logs still reports status
  metrics --pid P | --graph G  [--kind frame|transport] [--since 30m] [--step 60]
                                                Observer per-step metrics per process: video fps and bitrate,
                                                jitter, audio; zero and missing points flagged. dockerType is
                                                docker_<node type>, looked up from the graph

Windows. A process-log or Loki read covers the last 5 minutes by default, or a few minutes around `--at`. A wider
window is read only with `--wide "<reason>"`, and the reason is printed on the result: the limits on the shared log
servers are mh-bot's to enforce, and ela reads wide when the case needs it and says why. A Loki read names one
process or one service; a query over every service is refused, `--wide` or not.

Times. `--at`, `--from`, `--to` take `YYYY-MM-DD HH:MM:SS[.fff]` (read as UTC unless an offset is given), ISO 8601,
or epoch seconds/milliseconds. Every line prints UTC and the machine's local time. The java-log stores UTC strings;
the process-log stores epoch milliseconds; Loki takes epoch seconds — the script converts.

Source quirks, verified 2026-09-29 and handled here so a caller need not know them:
  - the process-log keeps the trace id in `peerId`; its `traceId` field is null and its `traceId` filter is ignored
    (the call returns every row). `chain` filters on peerId.
  - the java-log filter key is `traceId` (camel case); `traceid` is ignored. Its `message` filter does not match ids,
    so `--grep` filters on the client.
  - process-log windows are at most 7 days per call; a wider `chain` is read in 7-day slices.
  - display names (`serverName`, `peerId`) sometimes arrive wrapped in HTML; tags are stripped.
  - Loki windows are at most 4 hours per call, the server's ceiling, `--wide` or not.

Hosts and credentials. tvulog: TVU_LOG_BASE (default the tvuuas API on tvulog.tvunetworks.com), the person's TVU
session from `ela login tvu` (~/.claude/ela/session.json) as the Authorization header and the SID cookie; a refusal
is recorded on the session and exits 4 naming the command. Observer: TVU_OBSERVER_BASE (default mma1.tvunetworks.com),
TVU_CC_BEARER_TOKEN. Both from the environment → --env-file → $ELA_ENV_FILE → site.json `env`.
Exit codes: 0 ok · 2 usage · 3 nothing found (what was searched is printed) · 4 auth · 5 remote error.
"""
import argparse, datetime, html, json, os, re, signal, sys, urllib.error, urllib.parse, urllib.request

SKILLS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(SKILLS, "release"))
import release as R  # noqa: E402  — the person's TVU session: reader, refusal record, the login hint

EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE = 2, 3, 4, 5
UAS_DEFAULT = "https://tvulog.tvunetworks.com/tvuuas"
OBSERVER_DEFAULT = "https://mma1.tvunetworks.com"
PROCESS_WINDOW = datetime.timedelta(days=7)        # the server's ceiling per call, not a window to ask for
LOKI_WINDOW = datetime.timedelta(hours=4)          # the server's ceiling per call, not a window to ask for
# A read is narrow by default and wide on a stated reason. The owner's ruling: the limits on the shared log servers
# are mh-bot's to enforce; ela stays flexible, and a wide read carries its reason on the result.
READ_WINDOW = datetime.timedelta(minutes=5)        # the default read, and the widest without --wide
LOKI_UNFILTERED = datetime.timedelta(minutes=30)   # the widest read without a server-side filter
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


def read_window(a, at_span):
    """The window of a process-log or Loki read → (start, end, wide reason or None). `--at`/`--from`/`--to`, else the
    last `--since` (default 5m). Wider than READ_WINDOW only with `--wide "<reason>"`."""
    w = window(a, at_span)
    if w:
        s, e = w
    else:
        e = now(); s = e - parse_span(a.since)
    reason = (a.wide or "").strip() or None
    if a.wide is not None and not reason:
        die('--wide needs a reason: --wide "<why this case needs more than 5 minutes>"', EX_USAGE)
    if e - s > READ_WINDOW and not reason:
        die(f"this read covers {span_text(e - s)}; a read is {span_text(READ_WINDOW)} by default. Narrow it around "
            f'the moment (--at T), or read wide with --wide "<reason>", which is printed on the result', EX_USAGE)
    return s, e, reason


def span_text(d):
    m = d.total_seconds() / 60
    return f"{m:g} minutes" if m < 120 else f"{m / 60:g} hours" if m < 2880 else f"{m / 1440:g} days"


def now():
    return datetime.datetime.now(UTC)


def wide_line(reason, s, e):
    return f"wide read ({span_text(e - s)}): {reason}" if reason else None


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
    start, end, reason = read_window(a, "2m")
    uas = UAS(a.env_file)
    recs, s = [], start
    while s < end:
        e = min(s + PROCESS_WINDOW, end)
        got, _ = uas.pages("/process/page-es", a.limit, params={"startTime": ms(s), "endTime": ms(e), "peerId": a.trace})
        recs += got; s = e
    searched = f"process-log peerId={a.trace} from {show_time(start)} to {show_time(end)}"
    if not recs:
        die(f"no process-log records — searched {searched}. The trace id may not have been propagated, or the call "
            f"ran outside the window: give the moment with --at", EX_NOTFOUND)
    hops = sorted((hop(r) for r in recs), key=lambda h: (h["time"] or start))
    first = first_failing(hops)
    if a.json:
        print(json.dumps({"trace": a.trace, "searched": searched, "wide": reason, "hops": [hop_json(h) for h in hops],
                          "first_failing": hops.index(first) if first else None}, ensure_ascii=False, indent=1, default=str))
        return
    if reason:
        print(wide_line(reason, start, end))
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
    s, e, reason = read_window(a, "10s")
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
        print(json.dumps({"searched": searched, "wide": reason, "total": total, "hops": [hop_json(h) for h in hops]},
                         ensure_ascii=False, indent=1, default=str))
        return
    if reason:
        print(wide_line(reason, s, e))
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

# A record that opens a multi-line body: the message ends with an opener and the body follows on the
# next lines of the file. The syncer ships only lines carrying the `[YYYYMMDD hh:mm:ss.mmm L]` prefix,
# so a body written without that prefix on each line (copier's `sent metrics json: {`, decoderMediaBox's
# `…,json:`) never reaches Loki; a body whose every line is prefixed (playeroftvu's `playerStatus:{`)
# does. Verified 2026-11-05 against the files on the box (copier 6f7dc1a6, decoderMediaBox f282537c).
BODY_OPENER = re.compile(r"(\{|\[|json:)\s*$", re.I)
LOG_PREFIX = re.compile(r"^\[\d{8} \d{2}:\d{2}:\d{2}\.\d{3} \w\] - ")
THREAD_TAG = re.compile(r"^\[t:\d+\]-")


def _message(line):
    """The message after the `[time L] - ` prefix and a playeroftvu `[t:N]-` thread tag."""
    return THREAD_TAG.sub("", LOG_PREFIX.sub("", line, count=1), count=1)


def _same_ms_key(l):
    m = LOG_PREFIX.match(l["line"])
    return (l["pid"], l["file"], l["line"][:m.end() - 6] if m else None)  # `[YYYYMMDD hh:mm:ss.mmm`


def mark_cut_bodies(lines, filtered):
    """Set `body_cut` on each line: True when it opens a multi-line body and no continuation line of the
    same file was read in the same millisecond (the body is not in Loki); None when the read was filtered,
    so the continuation may only have been filtered out; False otherwise. Returns how many were marked."""
    groups = {}
    for l in lines:
        groups.setdefault(_same_ms_key(l), []).append(l)
    n = 0
    for l in lines:
        l["body_cut"] = False
        if not BODY_OPENER.search(_message(l["line"])):
            continue
        continued = any(s is not l and (_message(s["line"])[:1].isspace() or _message(s["line"]).lstrip()[:1] in ("}", "]"))
                        for s in groups.get(_same_ms_key(l), []))
        if continued:
            continue
        l["body_cut"] = None if filtered else True
        n += 1
    return n


# One service or one process: an exact service_name, or a process_id filter. `service_name=~".+"` alone is every service.
ONE_SOURCE = re.compile(r'service_name\s*=\s*["`][^"`]+["`]|process_id\s*=\s*["`][^"`]+["`]')


def cmd_loki(a):
    if not (a.pid or a.service or a.query):
        die("loki needs --pid, --service or --query", EX_USAGE)
    if a.query and not ONE_SOURCE.search(a.query):
        die("a Loki read names one service or one process: an all-services query is refused, --wide or not. Use "
            '--service S or --pid P, or a --query with service_name="S" or process_id = `P`. Which services ship '
            "logs is read from code and config, not surveyed through Loki", EX_USAGE)
    tok = R.env_value("TVU_CC_BEARER_TOKEN", a.env_file)
    if not tok:
        die("no TVU_CC_BEARER_TOKEN (env, $ELA_ENV_FILE, or --env-file) — /ela:setup", EX_AUTH)
    base = (R.env_value("TVU_OBSERVER_BASE", a.env_file) or OBSERVER_DEFAULT).rstrip("/")
    s, e, reason = read_window(a, "2m")
    if e - s > LOKI_WINDOW:
        die("Loki answers at most 4 hours per call, --wide or not; narrow the window", EX_USAGE)
    # An unfiltered read pulls every line of a busy service: the costly one for the log server, and the one that
    # buries the line asked for. Without a server-side filter it is held to a short window (MH-4049, 2026-11-23).
    if not (a.grep or (a.query and "|=" in a.query)) and e - s > LOKI_UNFILTERED:
        die(f"an unfiltered Loki read is at most {int(LOKI_UNFILTERED.total_seconds() // 60)} minutes: add --grep (a filter "
            "on the server) or narrow the window around the moment", EX_USAGE)
    if a.query:
        q = a.query
    else:
        q = '{service_name="%s"}' % a.service if a.service else '{service_name=~".+"}'
        if a.pid:
            q += " | process_id = `%s`" % a.pid
    for g in a.grep or []:
        q += " |= `%s`" % g
    st, body = request(base + "/api/observer/v1/log", {"Authorization": f"Bearer {tok}"},
                       {"query": q, "start": int(s.timestamp()), "end": min(int(e.timestamp()) + 1, int(s.timestamp()) + int(LOKI_WINDOW.total_seconds())), "limit": a.limit,
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
    filtered = bool(a.grep) or bool(re.search(r"\|[=~]|![=~]", q))
    cut = mark_cut_bodies(lines, filtered)
    note = None
    if cut:
        note = (f"{cut} line(s) open a multi-line body that is not in Loki — the syncer ships only "
                f"[timestamp]-prefixed lines, so the body exists only in the file on the box"
                if not filtered else
                f"{cut} line(s) open a multi-line body not shown here — filtered out by this query, or not "
                f"synced to Loki; re-read the same moment without --grep or line filters to tell")
    if a.json:
        print(json.dumps({"searched": searched, "wide": reason, "body_cut_note": note,
                          "lines": [{**l, "time": l["time"].isoformat() if l["time"] else None} for l in lines]},
                         ensure_ascii=False, indent=1))
        return
    if reason:
        print(wide_line(reason, s, e))
    print(f"{len(lines)} line(s){' (limit reached)' if len(lines) >= a.limit else ''} · {searched}")
    for l in lines:
        mark = {True: "  ⟂ body not in Loki", None: "  ⟂? body not shown"}.get(l["body_cut"], "")
        print(f"{show_time(l['time'])}  {l['service']}/{l['file'] or '?'}  {l['level'] or ''}  "
              f"{l['line'] if a.verbose else l['line'][:a.width]}{mark}")
    if note:
        print(f"note: {note}")


# ── Observer: status events and frame / transport metrics ────────────────────
# The two reads that reach a process when Loki has nothing: a site whose boxes ship no logs still reports its status
# events and its per-minute frame metrics through statusReporter (verified 2026-11-25 on a customer's physical SDI
# boxes whose Loki read was empty). Surface and quirks: elak knowledge/platform/observability/observer.md.

STATUS_WINDOW = datetime.timedelta(hours=24)    # the widest status read per call: the server has no row cap
METRICS_WINDOW = datetime.timedelta(hours=6)    # all-keys reads over longer windows time out on the server
# The `…/status/container` codes are written by UR (Portal and background), not by the agent (observer.md).
KNOWN_CODES = {
    "0x80001010": "dispatched (UR sent the task)", "0x80001011": "task progress", "0x80001012": "task progress (image pulled)",
    "0x80001013": "task-run reply ok", "0x80001014": "task-run failed", "0x80001015": "stopped",
    "0x80001016": "terminated", "0x80001001": "start error", "0x82000070": "container init",
}


def observer(a):
    tok = R.env_value("TVU_CC_BEARER_TOKEN", a.env_file)
    if not tok:
        die("no TVU_CC_BEARER_TOKEN (env, $ELA_ENV_FILE, or --env-file) — /ela:setup", EX_AUTH)
    base = (R.env_value("TVU_OBSERVER_BASE", a.env_file) or OBSERVER_DEFAULT).rstrip("/")
    return base, {"Authorization": f"Bearer {tok}"}


def observer_post(a, route, body):
    base, h = observer(a)
    st, b = request(base + "/api/observer/v1/" + route, h, body=body, timeout=60)
    if st in (401, 403):
        die(f"Observer refused the bearer token (HTTP {st}) — TVU_CC_BEARER_TOKEN; /ela:setup", EX_AUTH)
    if st != 200 or not isinstance(b, dict):
        die(f"Observer {route}: HTTP {st} {str(b)[:200]}", EX_REMOTE)
    return b


def obs_window(a, default, cap):
    w = window(a, "30m")
    if w:
        s, e = w
    else:
        e = now(); s = e - parse_span(a.since or default)
    if e - s > cap:
        die(f"this read covers {span_text(e - s)}; Observer is read at most {span_text(cap)} per call here. Step "
            "back-dated windows (--from/--to) to go further", EX_USAGE)
    return s, e


def ela_json(*argv):
    """Another ela verb's --json answer, or None."""
    import shutil, subprocess
    exe = shutil.which("ela")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, *argv, "--json"], capture_output=True, text=True, timeout=120)
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def graph_processes(a):
    """(app, graph id, [{pid, type, name, box}]) for --graph, or for the graph of --pid. The node type gives the
    metrics' dockerType (`docker_<type>`); --graph with --type skips the lookups for one --pid."""
    gid, pid = a.graph, a.pid
    if pid and gid and a.type:
        return "MediaHub", gid, [{"pid": pid, "type": a.type, "name": None, "box": None}]
    if pid and not gid:
        p = ela_json("process", pid) or {}
        gid = p.get("graph_id")
        if not gid:
            die(f"process {pid}: no graph id from `ela process {pid}`; pass --graph G (and --type T)", EX_NOTFOUND)
    g = ela_json("graph", gid) or {}
    res = (g.get("results") or [{}])[0]
    nodes = [n for n in res.get("nodes") or [] if n.get("process_id")]
    if not nodes:
        die(f"graph {gid}: no processes from `ela graph {gid}`", EX_NOTFOUND)
    procs = [{"pid": n["process_id"], "type": n.get("type"), "name": n.get("name"),
              "box": f"{n.get('box_type') or '?'} {n.get('public_ip') or n.get('box_id') or '?'}"} for n in nodes]
    if pid:
        procs = [p for p in procs if p["pid"] == pid] or [{"pid": pid, "type": a.type, "name": None, "box": None}]
    if a.type:
        for p in procs:
            p["type"] = a.type
    return res.get("app") or "MediaHub", gid, procs


def parse_event(e):
    """One status row → {code, level, time, detail}. A row may arrive as a JSON string, its detail too."""
    if isinstance(e, str):
        try:
            e = json.loads(e)
        except ValueError:
            return {"code": None, "level": None, "time": None, "detail": e}
    if not isinstance(e, dict):
        return None
    d = e.get("detail")
    if isinstance(d, str) and d[:1] in "{[":
        try:
            d = json.loads(d)
        except ValueError:
            pass
    return {"code": e.get("code"), "level": e.get("level"), "time": from_ms(e.get("timestamp")), "detail": d}


def format_text(d):
    """A format descriptor (`programs[…]`) in one line: video WxH, scan, fps, depth; audio tracks; data streams."""
    out = []
    for p in d.get("programs") or []:
        v = p.get("video") or {}
        if v:
            scan = "i" if v.get("interlaced") or v.get("interlaceFlag") else "p"
            codec = v.get("codec") if v.get("codec") not in (None, "N/A") else "uncompressed"
            out.append(f"video {v.get('width')}x{v.get('height')}{scan}{v.get('fps')} {v.get('bitDepth')}-bit {codec}")
        tr = (p.get("audio") or {}).get("tracks") or []
        if tr:
            out.append(f"audio {len(tr)} track(s) × {tr[0].get('channels')}ch {tr[0].get('sampleRate')}Hz")
        n = (p.get("data") or {}).get("num")
        if n:
            out.append(f"data {n}")
    return "; ".join(out) or "format (empty)"


def describe(ev):
    d, code = ev["detail"], ev["code"] or "?"
    if isinstance(d, dict) and "programs" in d:
        return "format: " + format_text(d)
    if isinstance(d, dict) and ("peerIp" in d or "status" in d):
        return f"connection {d.get('status')} peer {d.get('peerIp')}:{d.get('peerPort')} local {d.get('localPort')}"
    name = KNOWN_CODES.get(code)
    text = d if isinstance(d, str) else json.dumps(d, ensure_ascii=False) if d is not None else ""
    if name:
        return name if not text or text == name else f"{name} — {text}"
    return text or "(no detail)"


def collapse(events):
    """Time-ordered events with runs of the same code and detail folded into one row (alerts re-emit ~every 21 s)."""
    rows = []
    for ev in sorted((e for e in events if e), key=lambda e: e["time"] or datetime.datetime.min.replace(tzinfo=UTC)):
        sig = (ev["code"], json.dumps(ev["detail"], sort_keys=True, default=str))
        if rows and rows[-1]["sig"] == sig:
            rows[-1]["n"] += 1; rows[-1]["last"] = ev["time"]
        else:
            rows.append({"sig": sig, "n": 1, "first": ev["time"], "last": ev["time"], **ev})
    return rows


def cmd_status(a):
    if not (a.pid or a.graph):
        die("status needs --pid or --graph", EX_USAGE)
    s, e = obs_window(a, "6h", STATUS_WINDOW)
    app, gid, procs = graph_processes(a)
    keys = {f"/ur/{app}/{gid}/{p['pid']}": p for p in procs}
    prefixes = list(keys) + ([f"/ur/{app}/{gid}/status"] if not a.pid else [])
    b = observer_post(a, "queryhistorybyprefix", {"prefixes": prefixes, "begintime": ms(s), "endtime": ms(e)})
    searched = f"Observer status {', '.join(prefixes)} written {show_time(s)} … {show_time(e)}"
    rows = {}
    for k in b.get("data") or []:
        key = k.get("key") or "?"
        own = next((p for p in keys if key == p or key.startswith(p + "/")), key)
        rows.setdefault(own, []).extend(parse_event(x) for x in k.get("data") or [])
    if a.json:
        print(json.dumps({"searched": searched, "graph": gid, "processes": [
            {**(keys.get(k) or {"key": k}), "events": [{**{x: r[x] for x in ("code", "level", "detail", "n")},
                                                        "first": r["first"].isoformat() if r["first"] else None,
                                                        "last": r["last"].isoformat() if r["last"] else None}
                                                       for r in collapse(v)]} for k, v in rows.items()]},
                         ensure_ascii=False, indent=1, default=str))
        return
    if not rows:
        die(f"no status events (code {b.get('code')}: nothing written in the window; the store lags 40–60 s) — "
            f"searched {searched}", EX_NOTFOUND)
    print(searched)
    for k in list(keys) + [k for k in rows if k not in keys]:
        p = keys.get(k) or {"pid": k, "type": "graph-level", "box": ""}
        evs = collapse(rows.get(k, []))
        print(f"\n{p['type'] or '?'}  {p['pid']}  {p.get('box') or ''}  — {len(evs) or 'no'} event(s)")
        for r in evs:
            rep = f" ×{r['n']} until {show_time(r['last'])}" if r["n"] > 1 else ""
            text = describe(r)
            print(f"  {show_time(r['first'])}  {r['code'] or '?'}  {r['level'] or '-':<7}  "
                  f"{text if a.verbose else text[:a.width]}{rep}")


def summarize_series(key, points, step_s, s, e):
    """One metric key → counts, last value, min/max, zeros, and missing buckets against the window and step."""
    pts = sorted((p for p in points if isinstance(p, dict) and p.get("value") is not None), key=lambda p: p.get("ts") or 0)
    vals = [p["value"] for p in pts]
    expected = max(1, int((e - s).total_seconds() // step_s))
    out = {"key": key, "n": len(vals), "expected": expected, "zeros": sum(1 for v in vals if v == 0)}
    if vals:
        out.update(last=vals[-1], last_at=from_ms(pts[-1].get("ts")), first_at=from_ms(pts[0].get("ts")),
                   min=min(vals), max=max(vals))
    return out


def num(v):
    """A metric value short: 1.99G, 1.54M, 59.94."""
    for div, unit in ((1e9, "G"), (1e6, "M"), (1e3, "k")):
        if abs(v) >= div:
            return f"{v / div:.3g}{unit}"
    return f"{v:g}"


def shown_key(key, all_keys):
    """Without --all-keys: the video keys, the first audio track, and every transport key."""
    return all_keys or not re.match(r"audio\.tracks\[[1-9]\d*\]", key)


def cmd_metrics(a):
    if not (a.pid or a.graph):
        die("metrics needs --pid or --graph", EX_USAGE)
    s, e = obs_window(a, "30m", METRICS_WINDOW)
    app, gid, procs = graph_processes(a)
    out = []
    for p in procs:
        if not p["type"]:
            out.append({**p, "error": "no node type; pass --type"}); continue
        for kind in a.kind:
            b = observer_post(a, "queryMetricsHistoryData", {
                "pid": p["pid"], "dockerType": "docker_" + p["type"], "metrics": kind, "beginTime": ms(s),
                "endTime": ms(e), "keys": [], "step": a.step, "order": "desc"})
            series = [summarize_series(k.get("key"), k.get("valueList") or [], a.step, s, e)
                      for k in b.get("data") or [] if k.get("key") and shown_key(k["key"], a.all_keys)]
            out.append({**p, "metrics": kind, "series": sorted(series, key=lambda x: x["key"])})
    searched = f"Observer {'/'.join(a.kind)} metrics, step {a.step}s, {show_time(s)} … {show_time(e)}"
    if a.json:
        print(json.dumps({"searched": searched, "graph": gid, "processes": out}, ensure_ascii=False, indent=1, default=str))
        return
    print(searched)
    print("note: a point is a sample per step, not a mean; frames arriving says nothing of the picture's content "
          "(a black frame counts); no points is unknown (no such pid, an image without metrics, no data), not healthy")
    for p in out:
        print(f"\n{p.get('type') or '?'}  {p['pid']}  {p.get('box') or ''}  {p.get('metrics', '')}")
        if p.get("error"):
            print(f"  {p['error']}"); continue
        if not p["series"]:
            print("  no points"); continue
        for x in p["series"]:
            if not x["n"]:
                print(f"  {x['key']:<34} no points"); continue
            flags = []
            if x["zeros"] and re.search(r"fps|bitRate", x["key"], re.I):
                flags.append(f"{x['zeros']} zero point(s)")
            if x["n"] < x["expected"] * 0.9:
                flags.append(f"{x['expected'] - x['n']} of {x['expected']} steps missing")
            print(f"  {x['key']:<34} last {num(x['last']):<8} at {show_time(x['last_at'])[11:19]}Z  "
                  f"min {num(x['min'])}  max {num(x['max'])}  n {x['n']}{'  ⚠ ' + '; '.join(flags) if flags else ''}")


def main():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "configserver"))
    import redact; redact.guard_output()  # a credential inside a remote payload never reaches the terminal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description="Service logs, first-hand and read-only: tvulog (process-log, java-log) and Loki.")
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, limit):
        p.add_argument("--limit", type=int, default=limit)
        p.add_argument("-v", "--verbose", action="store_true")
        p.add_argument("--width", type=int, default=240, help="characters of a line shown without -v")
        p.add_argument("--json", action="store_true")

    def moment(p, span, grep=True):
        p.add_argument("--at", help="the moment (UTC unless an offset is given)")
        p.add_argument("--window", help=f"± around --at (default {span})")
        p.add_argument("--from", dest="frm"); p.add_argument("--to")
        if grep:
            p.add_argument("--grep", action="append", help="keep lines containing this text (repeatable; all must match)")

    def recent(p):
        p.add_argument("--since", default="5m", help="the last N without --at (default 5m)")
        p.add_argument("--wide", metavar="REASON", help="read wider than 5 minutes; the reason is printed on the result")

    p = sub.add_parser("chain", help="process-log records of one trace, the first failing hop marked")
    p.add_argument("trace"); moment(p, "2m", grep=False); recent(p); common(p, 500)
    p = sub.add_parser("java", help="java-log lines by trace, or by app around a moment")
    p.add_argument("--trace"); p.add_argument("--app"); p.add_argument("--env"); p.add_argument("--level")
    p.add_argument("--date", help="a UTC day, YYYY-MM-DD"); p.add_argument("--days", type=int, default=1)
    p.add_argument("--stack", type=int, default=40, help="stack lines shown with -v"); moment(p, "5s"); common(p, 300)
    p = sub.add_parser("calls", help="process-log records around a moment for one service or user")
    p.add_argument("--server"); p.add_argument("--email"); moment(p, "10s"); recent(p); common(p, 300)
    p = sub.add_parser("loki", help="Loki lines through Observer")
    p.add_argument("--pid"); p.add_argument("--service"); p.add_argument("--query")
    moment(p, "2m"); recent(p); common(p, 500)

    def observed(p, since):
        p.add_argument("--pid"); p.add_argument("--graph")
        p.add_argument("--type", help="the node type (sdi_copier, sdi_decoder, …) when the graph lookup is skipped")
        p.add_argument("--at"); p.add_argument("--window", help="± around --at (default 30m)")
        p.add_argument("--from", dest="frm"); p.add_argument("--to")
        p.add_argument("--since", default=since, help=f"the last N without --at (default {since})")
        common(p, 0)

    p = sub.add_parser("status", help="Observer status events of a process or every process of a graph")
    observed(p, "6h")
    p = sub.add_parser("metrics", help="Observer frame / transport metrics of a process or every process of a graph")
    observed(p, "30m")
    p.add_argument("--kind", action="append", choices=("frame", "transport"),
                   help="frame (default) and/or transport; repeatable")
    p.add_argument("--step", type=int, default=60, help="seconds per point (default 60)")
    p.add_argument("--all-keys", action="store_true", help="every audio track, not only the first")
    a = ap.parse_args()
    if a.cmd == "metrics" and not a.kind:
        a.kind = ["frame"]
    {"chain": cmd_chain, "java": cmd_java, "calls": cmd_calls, "loki": cmd_loki,
     "status": cmd_status, "metrics": cmd_metrics}[a.cmd](a)


if __name__ == "__main__":
    main()
