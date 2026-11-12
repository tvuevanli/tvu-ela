#!/usr/bin/env python3
"""The fact store: every source read once per pass into <runtime>/facts/, dated; the verbs read the store.

  facts.py [--env-file F] refresh [--source jira|slack|mail|lanes|builds]... [--fresh] [--json]
  facts.py status [--json]
  facts.py runtime refresh|show|prove <graph>|initconfig …   lane runtime facts (runtime.py)

The store is `<runtime>/facts/` (site.json `runtime`), one directory per source with a watermark file and the
content, every entry stamped with the time it was read:

  jira/     watermark.json · changes.json (the issues updated inside the horizon: a list of Jira-shaped issue
            objects, each with `changelog`, a top-level `comments` list and `read_at`; the runner reads it too)
            · issues/<KEY>.json (one issue read per key, keyed by its `updated`; re-read only when a sweep says the
            issue moved) · queries/<name>.json (the standing queries: the incidents umbrella) · owner.json
  slack/    <channel id>.json (top-level messages and thread replies: the one per-channel cache) · channels.json ·
            users.json · watermark.json
  mail/     index.json (the three standing searches over a rolling 21 days, ids newest first) · messages/<id>.json
            (fetched once per id; a message never changes) · threads/<id>.json · watermark.json
  lanes/    envs-<host>.json · gateway.json · watermark.json
  runtime/  lanes.json (per followed lane and service: the profile chain, how it was proven, the keys a one-profile
            read gets wrong) · proofs.json (a graph bound to its UR Caller instance and gateway) · initconfig-<lane>.json
  builds/   <job>.json (Jenkins, 80 builds) · bundles/<host>/<line>.json · bundles/detail/<id>.json · watermark.json

`refresh` is incremental and idempotent: each source reads forward from its watermark; a second refresh in the same
minute reads nothing new. After the sources, the links index (`ela links`, <runtime>/links/) re-reads what changed. A source that fails keeps its previous content and records a `gap` with the reason; the
verbs that serve that source then answer as the live read would have (the lanes' exit code, an empty list), naming
the last good read. `--fresh` ignores the watermarks and reads every source whole.

Serving rules (in the source scripts): a verb serves the store while its watermark is younger than
ELA_FACTS_MAX_AGE hours (default 6) and prints the read time; `--fresh` on the verb, or ELA_FACTS_FRESH=1 in the
environment, reads live and writes through. ELA_FACTS_TRACE=1 prints one `facts-trace <source> <what>` line on
stderr per live call; ELA_FACTS_TRACE=<path> appends it to that file across every process of a pass.

Exit codes: 0 ok · 2 usage · 5 no source could be read (a partial refresh is 0 with the gaps on stderr).
Decision: elak blueprint/decisions/2026-11-04-read-once-close-by-outcome-home-as-an-index.md (phase A).
"""
import argparse, datetime, json, os, sys, time

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
SITE = os.path.expanduser("~/.claude/ela/site.json")
SOURCES = ("jira", "slack", "mail", "lanes", "builds", "runtime")
EX_USAGE, EX_REMOTE = 2, 5
JIRA_HORIZON_DAYS = 14          # how far back the Jira sweep keeps changed issues (recent's 7 days, Monday's 72 hours)
SLACK_HORIZON_DAYS = 8          # the window of parents re-read each pass, so a reply to an older thread is seen
MAIL_DAYS = 21                  # the rolling window of the standing searches (the test list's 21 days)
BUILDS_LIMIT = 80               # the deepest Jenkins read a consumer asks for (fixed-in)
BUNDLES_LIMIT = 50


# ── paths and time ───────────────────────────────────────────────────────────────────────────────────

def site():
    try:
        return json.load(open(SITE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def runtime_root():
    s = site()
    root = os.environ.get("ELA_FACTS_RUNTIME") or s.get("runtime") or os.path.join(s.get("projects") or os.getcwd(), ".ela")
    return os.path.expanduser(root)


def store_dir(source, *parts):
    """<runtime>/facts/<source>/<parts>, created."""
    d = os.path.join(runtime_root(), "facts", source, *parts)
    os.makedirs(d, exist_ok=True)
    return d


def now():
    return datetime.datetime.now().astimezone()


def now_iso():
    return now().isoformat(timespec="seconds")


def parse_iso(s):
    try:
        t = datetime.datetime.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.astimezone()


def max_age_hours():
    try:
        return float(os.environ.get("ELA_FACTS_MAX_AGE") or 6)
    except ValueError:
        return 6.0


def fresh(at, max_age_h=None):
    """Whether a read stamped `at` (ISO) is young enough to serve."""
    t = parse_iso(at)
    if t is None:
        return False
    return (now() - t).total_seconds() <= (max_age_h if max_age_h is not None else max_age_hours()) * 3600


def forced_fresh():
    """ELA_FACTS_FRESH=1: every verb reads live (a consumer's --fresh is passed down this way)."""
    return bool(os.environ.get("ELA_FACTS_FRESH"))


def trace(source, what):
    """One line per live call when ELA_FACTS_TRACE is set, so a pass can count what it still reads: `1` prints to
    stderr; a path appends to that file, which is what a consumer's subprocesses (their stderr captured) need."""
    t = os.environ.get("ELA_FACTS_TRACE")
    if not t:
        return
    line = f"facts-trace {source} {what}"
    if t == "1":
        print(line, file=sys.stderr, flush=True); return
    try:
        with open(t, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        print(line, file=sys.stderr, flush=True)


def served(source, at, what=""):
    """Say on stderr that a verb answered from the store, with the read time: staleness shown, never hidden."""
    if os.environ.get("ELA_FACTS_QUIET"):
        return
    t = parse_iso(at)
    stamp = t.strftime("%Y-%m-%d %H:%M") if t else str(at)
    print(f"# facts: {source}{(' ' + what) if what else ''} as of {stamp} (--fresh re-reads)", file=sys.stderr)


# ── files ────────────────────────────────────────────────────────────────────────────────────────────

def read_json(path, default=None):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)
    os.replace(tmp, path)


def watermark(source):
    return read_json(os.path.join(store_dir(source), "watermark.json"), {}) or {}


def set_watermark(source, **fields):
    wm = watermark(source)
    wm.update(fields)
    write_json(os.path.join(store_dir(source), "watermark.json"), wm)
    return wm


def set_gap(source, why, **more):
    """A failed read keeps the previous content; the watermark carries the gap and when it was seen."""
    return set_watermark(source, gap={"at": now_iso(), "why": str(why)[:300], **more})


def clear_gap(source):
    wm = watermark(source)
    if "gap" in wm:
        wm.pop("gap")
        write_json(os.path.join(store_dir(source), "watermark.json"), wm)


def read_at():
    """{source: the watermark's read time} for every source that has one: what a page prints as its facts line."""
    out = {}
    for s in SOURCES:
        wm = watermark(s)
        if wm.get("at"):
            out[s] = wm["at"]
    return out


def read_at_line(extra=None):
    """One line for a page: `facts: jira 11-04 08:02 · slack 11-04 08:03 · …`, or `facts: none refreshed`."""
    parts = []
    for s, at in {**read_at(), **(extra or {})}.items():
        t = parse_iso(at)
        parts.append(f"{s} {t.strftime('%m-%d %H:%M') if t else at}")
    return "facts: " + (" · ".join(parts) if parts else "none refreshed")


# ── refresh, per source ──────────────────────────────────────────────────────────────────────────────

def refresh_jira(env_file, full):
    sys.path.insert(0, os.path.join(SKILLS, "jira"))
    import jira as J  # noqa: E402
    creds = J.load_env(env_file)
    wm = watermark("jira")
    t0 = time.time()
    since_t = None if full else parse_iso(wm.get("at"))
    if since_t is None:
        since_t = now() - datetime.timedelta(days=JIRA_HORIZON_DAYS)
    else:
        since_t -= datetime.timedelta(minutes=10)           # Jira's `updated` is minute-grained; overlap rather than miss
    earlier = parse_iso(wm.get("horizon"))
    horizon = since_t if (full or earlier is None or since_t < earlier) else earlier
    since = since_t.astimezone().strftime("%Y-%m-%d %H:%M")
    d = store_dir("jira")
    changed = {} if full else {i["key"]: i for i in (read_json(os.path.join(d, "changes.json"), []) or []) if i.get("key")}
    issues_dir = store_dir("jira", "issues")
    cached_keys = {f[:-5] for f in os.listdir(issues_dir) if f.endswith(".json")}
    projects = ["MH"] + sorted({k.split("-")[0] for k in cached_keys} - {"MH"})
    counts, reread = {}, 0
    at = now_iso()
    for proj in projects:
        issues = J.search_changed(creds, proj, since, limit=2000)
        counts[proj] = len(issues)
        for i in issues:
            changed[i["key"]] = J.sweep_issue(i, at)
    keep_after = (now() - datetime.timedelta(days=JIRA_HORIZON_DAYS)).isoformat()
    for k in list(changed):
        upd = J.updated_iso((changed[k].get("fields") or {}).get("updated"))
        if upd and upd < keep_after:
            changed.pop(k)
    write_json(os.path.join(d, "changes.json"), sorted(changed.values(), key=lambda i: str((i.get("fields") or {}).get("updated") or ""), reverse=True))
    # the key cache: a cached issue a sweep says moved is read again now, so the pass's readers find it warm
    for k in sorted(cached_keys):
        rec = changed.get(k)
        if not rec:
            continue
        cached = read_json(os.path.join(issues_dir, f"{k}.json"), {}) or {}
        if J.updated_iso((rec.get("fields") or {}).get("updated") or "") > str(cached.get("updated") or ""):
            J.issue_doc(creds, k, fresh=True)
            reread += 1
    J.standing_queries(creds)
    set_watermark("jira", at=at, since=since, horizon=horizon.isoformat(timespec="seconds"), projects=projects,
                  counts=counts, reread=reread, seconds=round(time.time() - t0, 1))
    clear_gap("jira")
    return f"jira: {sum(counts.values())} changed since {since} ({', '.join(f'{p} {n}' for p, n in counts.items())}), {reread} re-read, {time.time() - t0:.1f}s"


def refresh_slack(env_file, full):
    sys.path.insert(0, os.path.join(SKILLS, "slack"))
    import slack as S  # noqa: E402
    tok = S.token(env_file)
    t0 = time.time()
    chans = S.list_channels(tok, fresh=True)
    oldest = (now() - datetime.timedelta(days=SLACK_HORIZON_DAYS)).timestamp()
    msgs = replies = 0
    unread = []
    for c in chans:
        try:
            n, r = S.refresh_channel(tok, c["id"], oldest, full=full)
            msgs += n; replies += r
        except S.Transient as e:
            unread.append({"channel": c.get("name"), "id": c["id"], "why": str(e)[:200]})
    at = now_iso()
    set_watermark("slack", at=at, channels=len(chans), messages=msgs, replies=replies, unread=unread, seconds=round(time.time() - t0, 1))
    if unread:
        set_gap("slack", "channels not read whole: " + ", ".join(f"#{u['channel']}" for u in unread), partial=True)
    else:
        clear_gap("slack")
    return f"slack: {len(chans)} channels, {msgs} messages, {replies} threads read, {len(unread)} unread, {time.time() - t0:.1f}s"


def refresh_mail(env_file, full):
    sys.path.insert(0, os.path.join(SKILLS, "mail"))
    import mail as M  # noqa: E402
    t0 = time.time()
    g = M.Google(env_file); g.need(M.SCOPE)
    stats = M.refresh_standing(g, full=full)
    at = now_iso()
    set_watermark("mail", at=at, days=MAIL_DAYS, standing=stats, seconds=round(time.time() - t0, 1))
    clear_gap("mail")
    return "mail: " + ", ".join(f"{k} {v['count']} ids ({v['fetched']} new)" for k, v in stats.items()) + f", {time.time() - t0:.1f}s"


def refresh_lanes(env_file, full):
    sys.path.insert(0, os.path.join(SKILLS, "release"))
    import release as R  # noqa: E402
    t0 = time.time()
    parts, gaps = [], []
    for host in ("qa", "prod"):
        rows, gap = R.refresh_envs(env_file, host)
        parts.append(f"{host} {len(rows) if rows is not None else 'gap'}")
        if gap:
            gaps.append(f"{host}: {gap}")
    rows, gap = R.refresh_gateway()
    parts.append(f"gateway {len(rows) if rows is not None else 'gap'}")
    if gap:
        gaps.append(f"gateway: {gap}")
    set_watermark("lanes", at=now_iso(), seconds=round(time.time() - t0, 1))
    if gaps:
        set_gap("lanes", "; ".join(gaps), partial=True)
    else:
        clear_gap("lanes")
    return f"lanes: {', '.join(parts)}" + (f" — gaps: {'; '.join(gaps)}" if gaps else "") + f", {time.time() - t0:.1f}s"


def refresh_builds(env_file, full):
    sys.path.insert(0, os.path.join(SKILLS, "release"))
    import release as R  # noqa: E402
    t0 = time.time()
    jobs = R.rmap("jobs") or {}
    got, gaps = 0, []
    for job in jobs:
        rows, gap = R.refresh_builds(job, BUILDS_LIMIT)
        got += len(rows or [])
        if gap:
            gaps.append(f"{job}: {gap}")
    lines = R.rmap("lines") or {}
    wanted = {("qa", "mh2.1@"), ("prod", "mh2.1@")}
    for line, cfg in lines.items():
        if cfg.get("bundle_line"):
            wanted |= {("qa", cfg["bundle_line"]), ("prod", cfg["bundle_line"])}
        if (cfg.get("lanes") or {}).get("prod"):
            wanted.add(("prod", f"MediaHub {line}"))
    bundles = 0
    for host, line in sorted(wanted):
        rows, gap = R.refresh_bundles(env_file, host, line, BUNDLES_LIMIT)
        bundles += len(rows or [])
        if gap:
            gaps.append(f"bundles {host} {line}: {gap}")
    set_watermark("builds", at=now_iso(), jobs=len(jobs), builds=got, bundle_lists=len(wanted), bundles=bundles, seconds=round(time.time() - t0, 1))
    if gaps:
        set_gap("builds", "; ".join(gaps), partial=True)
    else:
        clear_gap("builds")
    return f"builds: {len(jobs)} jobs, {got} builds, {len(wanted)} bundle lists ({bundles} bundles)" + (f" — gaps: {'; '.join(gaps)[:300]}" if gaps else "") + f", {time.time() - t0:.1f}s"


def refresh_runtime(env_file, full):
    """Per followed lane and config-server service: the profile chain runtime evidence proves and the keys a
    one-profile read gets wrong (runtime.py). Read whole every pass: the chain is what runs now, not a history."""
    sys.path.insert(0, HERE)
    import runtime as RT  # noqa: E402
    t0 = time.time()
    out = RT.refresh(env_file or site().get("env"))
    n = sum(len(v) for v in out["lanes"].values())
    proven = sum(1 for v in out["lanes"].values() for r in v.values() if r.get("chain_status") == "proven")
    set_watermark("runtime", at=now_iso(), seconds=round(time.time() - t0, 1))
    if out["gaps"]:
        set_gap("runtime", "; ".join(out["gaps"])[:300], partial=True)
    else:
        clear_gap("runtime")
    return (f"runtime: {n} lane·service row(s), {proven} chain(s) proven by a graph"
            + (f" — gaps: {'; '.join(out['gaps'])}" if out["gaps"] else "") + f", {time.time() - t0:.1f}s")


REFRESH = {"jira": refresh_jira, "slack": refresh_slack, "mail": refresh_mail, "lanes": refresh_lanes, "builds": refresh_builds,
           "runtime": refresh_runtime}


def links_update():
    """The links index follows every refresh: the origins whose files changed are re-read (skills/links). Never fatal:
    a failure is one line, and the facts stand without it."""
    try:
        sys.path.insert(0, os.path.join(SKILLS, "links"))
        import links as L  # noqa: E402
        res = L.update()
        print(f"links: {len(res['read'])} origin(s) re-read, {res['edges']} edges, {res['seconds']}s", file=sys.stderr, flush=True)
        return {k: res[k] for k in ("read", "edges", "bytes", "seconds")}
    except Exception as e:  # noqa: BLE001
        print(f"links: not updated — {type(e).__name__}: {str(e)[:160]}", file=sys.stderr, flush=True)
        return {"error": f"{type(e).__name__}: {str(e)[:160]}"}


def cmd_refresh(a):
    sources = a.source or list(SOURCES)
    out, failed = {}, []
    for s in sources:
        try:
            line = REFRESH[s](a.env_file, a.fresh)
            out[s] = {"ok": True, "line": line, "watermark": watermark(s)}
        except SystemExit as e:                             # a source script's own exit: the gap, the previous content kept
            why = f"exit {e.code}" if isinstance(e.code, int) else str(e.code)
            set_gap(s, why)
            line = f"{s}: not read — {why}; previous content kept"
            out[s] = {"ok": False, "line": line, "watermark": watermark(s)}
            failed.append(s)
        except Exception as e:  # noqa: BLE001 — one source must not stop the others
            set_gap(s, f"{type(e).__name__}: {e}")
            line = f"{s}: not read — {type(e).__name__}: {str(e)[:160]}; previous content kept"
            out[s] = {"ok": False, "line": line, "watermark": watermark(s)}
            failed.append(s)
        print(line, file=sys.stderr, flush=True)
    links = links_update() if len(failed) < len(sources) else None
    if a.json:
        print(json.dumps({"at": now_iso(), "sources": out, "failed": failed, "links": links}, ensure_ascii=False))
    if failed and len(failed) == len(sources):
        sys.exit(EX_REMOTE)


def cmd_status(a):
    rows = {}
    for s in SOURCES:
        wm = watermark(s)
        d = store_dir(s)
        size = 0
        for top, _, files in os.walk(d):
            size += sum(os.path.getsize(os.path.join(top, f)) for f in files)
        rows[s] = {"at": wm.get("at"), "fresh": fresh(wm.get("at")) if wm.get("at") else False, "gap": wm.get("gap"),
                   "bytes": size, "seconds": wm.get("seconds")}
    if a.json:
        print(json.dumps({"runtime": runtime_root(), "max_age_hours": max_age_hours(), "sources": rows}, ensure_ascii=False)); return
    print(f"facts {os.path.join(runtime_root(), 'facts')}  (served while younger than {max_age_hours():g}h)")
    for s, r in rows.items():
        t = parse_iso(r["at"])
        stamp = t.strftime("%Y-%m-%d %H:%M") if t else "never"
        gap = f"  gap: {r['gap']['why'][:80]} ({r['gap']['at'][11:16]})" if r.get("gap") else ""
        print(f"  {s:<8} {stamp:<17} {'fresh' if r['fresh'] else 'stale':<6} {r['bytes'] / 1e6:6.1f} MB{gap}")


def main():
    ap = argparse.ArgumentParser(description="the fact store: every source read once per pass into <runtime>/facts/")
    ap.add_argument("--env-file", help="ela's env file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("refresh", help="read each source forward from its watermark")
    p.add_argument("--source", action="append", choices=SOURCES, help="one source (repeatable); default all")
    p.add_argument("--fresh", action="store_true", help="ignore the watermarks: read every source whole")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_refresh)
    p = sub.add_parser("status", help="each source's read time, freshness, size and gap")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)
    p = sub.add_parser("runtime", help="lane runtime facts: refresh|show|prove <graph>|initconfig (runtime.py)", add_help=False)
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p.set_defaults(func=lambda a: os.execvp("python3", ["python3", os.path.join(HERE, "runtime.py")]
                                            + (["--env-file", a.env_file] if a.env_file else []) + a.rest))
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
