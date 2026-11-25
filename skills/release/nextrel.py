#!/usr/bin/env python3
"""The next MediaHub release, as data: `ela release next` → <published>/releases/next.json (schema: next.md beside this file).

  ela release next [--line 2.1] [--candidate REF] [--write [--sync]] [--json]
      base         the newest plain official bundle of the train (release.release_base)
      candidate    the newest daily bundle of the line, or the held one (--pin), or --candidate REF (name, id or prefix)
      must         tickets labelled release:must: status, when the label was added, a cell per lane from the train
      on_candidate `ela promote tickets <line> <base> <candidate> --scope all`, each joined to QA's latest verdict as
                   promote's evidence reads it in the latest saved promotion report (<reports>/promote/<line>-daily-prod.json)
      in_dev       MH tickets In Progress or Review, updated within 14 days, not on the candidate
      docker       the bundles' docker diff, the daily and prod lanes' versions, commits on branches not yet built
    When a plain official bundle was cut after the candidate, the state is `released` and the range is recomputed on
    that bundle (from the official before it). Without --write the document is printed (--json) or summarised; --write
    publishes it atomically through the publish redaction and copies next.md as releases/README.md.
    --sync then carries releases/ alone to site.json `published_remote`, where the remote Helm reads it (as `publish
    lanes --sync` carries lanes/; typing it is the confirm); the outcome is one line, `synced` in --json, never a failure.
  ela release next --pin REF --why "…" [--apply]   hold the candidate on one bundle; dry run unless --apply
  ela release next --unpin [--apply]                 the newest daily bundle again

Read-only on every source (userservice, Jira, the reports); writes only <published>/releases/ and, with --pin --apply,
<reports>/releases/next-pin.json. Stdlib only.
Exit codes: 0 ok · 2 usage · 3 a bundle is not found or the prod host is unreadable · 4 the publish guard refused the
file (the published copy is left as it was) · 5 a source failed.
"""
import argparse, datetime, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
SCHEMA = 1
EX_USAGE, EX_NOTFOUND, EX_GUARD, EX_REMOTE = 2, 3, 4, 5
PASSES = ("13:00", "17:30", "19:00")            # the runner's weekday passes that refresh the file
STALE_GRACE_H = 2
IN_DEV_JQL = 'project = MH AND status in ("In Progress", Review) AND updated >= -14d ORDER BY updated DESC'
MUST_LABEL = "release:must"
MUST_JQL = f'labels = "{MUST_LABEL}" ORDER BY key'
BROWSE = "https://tvunetworks.atlassian.net/browse/"
QA_REPORT_MAX_H = 36


def R():
    sys.path.insert(0, HERE)
    import release                               # noqa: E402 — the bundles, the map, the pins
    return release


# ── pure: the document from its inputs ────────────────────────────────────────

def stale_after(now):
    """The next scheduled pass after `now` (weekdays at PASSES) plus the grace: when a reader calls the file stale."""
    day = now
    for _ in range(8):
        if day.weekday() < 5:
            for hm in PASSES:
                h, m = map(int, hm.split(":"))
                t = day.replace(hour=h, minute=m, second=0, microsecond=0)
                if t > now:
                    return (t + datetime.timedelta(hours=STALE_GRACE_H)).isoformat(timespec="seconds")
        day = (day + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (now + datetime.timedelta(days=3)).isoformat(timespec="seconds")


def mm_of(name):
    m = re.match(r"^MediaHub (\d+)\.(\d+)\.(\d+)", str(name or ""))
    return tuple(int(x) for x in m.groups()) if m else None


def release_name(base_name, ships_as):
    """The release's product name: the train's newest ships-as number when it is above the base's (`MediaHub 2.2.0`
    after 2.1.19 on a train shipping as 2.2), else the base's next patch."""
    b = mm_of(base_name)
    ships = sorted((tuple(int(x) for x in str(v).split(".")[:2]) for v in ships_as or [] if re.fullmatch(r"\d+\.\d+", str(v))), reverse=True)
    if b and ships and ships[0] > b[:2]:
        return f"MediaHub {ships[0][0]}.{ships[0][1]}.0"
    return f"MediaHub {b[0]}.{b[1]}.{b[2] + 1}" if b else None


def headline(state, name, lane, planned_for):
    if state == "released":
        return f"{name}, released"
    if planned_for:
        d = datetime.date.fromisoformat(planned_for)
        return f"{name}, planned for {lane} on {d.strftime('%A')} {d.day} {d.strftime('%b')}"
    return f"{name}, planned for {lane}"


def bundle(b, rule=None, source=None):
    if not b:
        return None
    out = {"name": b.get("name") or b.get("bundleName"), "id": str(b.get("id") or b.get("bundleId") or ""),
           "created": b.get("created"), "rule": rule if rule is not None else b.get("rule")}
    if source:
        out["source"] = source
    return out


def qa_of(ev):
    """{verdict, source, when} from one key of promote's evidence; None when the report holds no reading of it."""
    if not ev:
        return None
    whens = [str(i.get("when")) for i in ev.get("items") or [] if i.get("when")]
    return {"verdict": ev.get("verdict") or "none", "source": ev.get("source") or "report", "when": max(whens) if whens else None}


def train_rows(train):
    """{key: train row} for the key and every alias the row carries."""
    out = {}
    for r in (train or {}).get("rows") or []:
        for k in [r.get("key")] + list(r.get("also") or []):
            if k:
                out.setdefault(k, r)
    return out


def label_added(histories, label=MUST_LABEL):
    """The first changelog time the label entered `labels`; None when the changelog does not show it."""
    hits = []
    for h in histories or []:
        for i in h.get("items") or []:
            if (i.get("field") or "").lower() != "labels":
                continue
            was, now = set(str(i.get("fromString") or "").split()), set(str(i.get("toString") or "").split())
            if label in now and label not in was:
                hits.append(str(h.get("created") or ""))
    return min(hits) if hits else None


def ticket(row, qa=None, **more):
    key, parent = row.get("key"), row.get("parent")
    parent = parent.get("key") if isinstance(parent, dict) else parent
    return dict({"key": key, "url": row.get("url") or BROWSE + str(key), "summary": row.get("summary") or "",
                 "type": row.get("type"), "status": row.get("status"), "assignee": row.get("assignee"),
                 "parent": parent or None, "qa": qa}, **more)


def branch_kind(branch):
    """release · feature · None when the report names no branch (no checkout, no build sha)."""
    if not branch:
        return None
    return "release" if re.search(r"(?:^|/)release", str(branch)) else "feature"


def build(inp, now):
    """The document from its inputs (gather's dict, or a test's fixture). No reads here."""
    line, cfg = inp["line"], inp.get("cfg") or {}
    state = "released" if inp.get("released") else "planned"
    gaps = list(inp.get("gaps") or [])
    tk = inp.get("tickets") or {}
    report = inp.get("report") or {}
    ev = ((report.get("evidence") or {}).get("keys")) or {}
    lanes_cfg = cfg.get("lanes") or {}
    prod_lane = lanes_cfg.get("prod")
    rel_bundle = bundle(inp.get("released_bundle"), rule="the plain official cut after the candidate") if state == "released" else None
    name = rel_bundle["name"] if rel_bundle else release_name((inp.get("base") or {}).get("name"), cfg.get("ships_as"))
    since = cfg.get("ships_as_since")
    planned_for = since if state == "planned" and since and since >= now.date().isoformat() else None

    on = []
    for r in tk.get("tickets") or []:
        if r.get("exists") is False:
            continue
        on.append(ticket(r, qa_of(ev.get(r.get("key"))), services=list(r.get("services_in_delta") or []),
                         docker=sorted({d.get("slug") for d in r.get("docker") or [] if isinstance(d, dict) and d.get("slug")})))
    on_keys = {t["key"] for t in on}

    trows = train_rows(inp.get("train"))
    must = []
    for r in inp.get("must_rows") or []:
        k = r.get("key")
        tr = trows.get(k) or {}
        carried = k in on_keys
        must.append(ticket(r, qa_of(ev.get(k)), tracked_since=(inp.get("must_since") or {}).get(k), on_candidate=carried,
                           position=tr.get("position"), cells=tr.get("cells") or {},
                           decision="hold or defer" if state == "planned" and not carried else None))

    in_dev = []
    for r in inp.get("indev_rows") or []:
        if r.get("key") in on_keys:
            continue
        in_dev.append(ticket(r, qa_of(ev.get(r.get("key"))), updated=str(r.get("updated") or "")[:10] or None))

    lanes = []
    for s in (report.get("lanes") or {}).get("services") or []:
        f, t = s.get("from") or {}, s.get("to") or {}
        lanes.append({"service": s.get("service"), "from": {"lane": s.get("from_lane"), "version": f.get("version")},
                      "to": {"lane": s.get("to_lane"), "version": t.get("version")}, "relation": s.get("relation")})
    branches = []
    for u in (report.get("prereqs") or {}).get("unbuilt") or []:
        branches.append({"service": u.get("service"), "repo": u.get("repo"), "branch": u.get("branch"), "kind": branch_kind(u.get("branch")),
                         "build": u.get("build"), "commits": [{k: c.get(k) for k in ("sha", "date", "author", "subject")} for c in u.get("commits") or []]})
        if u.get("error"):
            gaps.append({"kind": "branch_unread", "detail": f"{u.get('service')} {u.get('branch') or '(no branch)'}: {u.get('error')}"})
    diff = [{k: d.get(k) for k in ("service", "slug", "from", "to", "relation")} | {"tickets": list(d.get("tickets") or [])}
            for d in tk.get("docker") or []]
    epics = [{"key": e.get("key"), "url": BROWSE + str(e.get("key")), "summary": e.get("summary"), "status": e.get("status"),
              "children": list(e.get("children") or [])} for e in tk.get("epics") or []]
    gaps += [g for g in tk.get("gaps") or [] if isinstance(g, dict)]

    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(timespec="seconds"),
        "stale_after": stale_after(now),
        "line": line,
        "state": state,
        "headline": headline(state, name, prod_lane, planned_for),
        "release": {"name": name, "lane": prod_lane, "planned_for": planned_for, "released_bundle": rel_bundle},
        "base": bundle(inp.get("base")),
        "candidate": bundle(inp.get("candidate"), source=inp.get("candidate_source") or "newest"),
        "lanes": list((inp.get("train") or {}).get("lanes") or []),
        "must": must,
        "on_candidate": on,
        "epics": epics,
        "in_dev": in_dev,
        "docker": {"bundle_diff": diff, "lanes": lanes, "branches": branches},
        "counts": {"must": len(must), "must_missing": sum(1 for m in must if not m["on_candidate"]), "on_candidate": len(on),
                   "in_dev": len(in_dev), "docker_changed": len(diff), "unbuilt_commits": sum(len(b["commits"]) for b in branches)},
        "sources": inp.get("sources") or {},
        "gaps": gaps,
    }


def facts_of(doc):
    """The strings the document cites as fields (titles, commit subjects): the publish guard passes a quotation in one."""
    out = [t.get("summary") or "" for k in ("must", "on_candidate", "in_dev", "epics") for t in doc.get(k) or []]
    out += [c.get("subject") or "" for b in (doc.get("docker") or {}).get("branches") or [] for c in b.get("commits") or []]
    return [s for s in out if s]


# ── reads ─────────────────────────────────────────────────────────────────────

def run_json(argv, timeout):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"timeout after {timeout}s"
    except OSError as e:
        return None, str(e)
    if p.returncode != 0 or not p.stdout.strip():
        return None, ((p.stderr or p.stdout).strip().splitlines() or [f"exit {p.returncode}"])[-1][:300]
    try:
        return json.loads(p.stdout), None
    except ValueError:
        return None, "not json"


def jql(env_file, q, limit):
    argv = ["python3", os.path.join(SKILLS, "jira", "jira.py")] + (["--env-file", env_file] if env_file else []) + ["jql", q, "--limit", str(limit), "--fresh", "--json"]
    got, err = run_json(argv, 180)
    return ((got or {}).get("issues") or []), (got or {}).get("read_at"), err


def changelog(env_file, key):
    sys.path.insert(0, os.path.join(SKILLS, "jira"))
    import jira as J                                  # noqa: E402 — the changelog read the jira verbs use
    creds, start, out = J.load_env(env_file), 0, []
    while True:
        page = J.api_get(creds, f"/rest/api/3/issue/{key}/changelog", {"startAt": start, "maxResults": 100})
        vals = page.get("values") or []
        out += vals
        start += len(vals)
        if page.get("isLast", True) or not vals:
            return out


def pin_path(s):
    return os.path.join(s.get("reports") or os.path.join(s.get("projects", ""), "reports"), "releases", "next-pin.json")


def read_pin(s, line):
    try:
        return (json.load(open(pin_path(s), encoding="utf-8")) or {}).get(str(line))
    except (OSError, ValueError, AttributeError):
        return None


def qa_report(s, line):
    """(the latest saved daily → prod promotion report, its name) under <reports>/promote/; (None, None) when none."""
    d = os.path.join(s.get("reports") or os.path.join(s.get("projects", ""), "reports"), "promote")
    cfg = (R().rmap("lines") or {}).get(str(line)) or {}
    names = [f"{line}-daily-prod.json", f"{line}-{(cfg.get('lanes') or {}).get('daily')}-{(cfg.get('lanes') or {}).get('prod')}.json"]
    paths = [os.path.join(d, n) for n in names if os.path.isfile(os.path.join(d, n))]
    if not paths:
        return None, None
    p = max(paths, key=os.path.getmtime)
    try:
        return json.load(open(p, encoding="utf-8")), os.path.basename(p)
    except (OSError, ValueError):
        return None, None


def row_of(us, Rm, bid, name):
    return next((b for b in Rm.bundle_list(us, name, 50) if str(b.get("bundleId")) == str(bid)), {"bundleId": bid, "bundleName": name})


def b_of(Rm, row, rule):
    return {"name": row.get("bundleName"), "id": str(row.get("bundleId")), "created": Rm.when(row.get("createTime")) if row.get("createTime") else None, "rule": rule}


def gather(line, candidate_ref, env_file, quiet=False):
    """Every input `build` needs, read now. Exits 3 when the prod host cannot name the bundles."""
    Rm = R()
    s = Rm.site()
    env_file = env_file or s.get("env")
    cfg = (Rm.rmap("lines") or {}).get(str(line))
    if not cfg:
        print(f"unknown release line {line!r}", file=sys.stderr); sys.exit(EX_USAGE)
    gaps, sources = [], {}

    def say(m):
        if not quiet:
            print(f"· {m}", file=sys.stderr, flush=True)
    us = Rm.LazyUS(env_file, "prod")
    pin = read_pin(s, line)
    ref, source = (candidate_ref, "argument") if candidate_ref else ((pin.get("bundle"), "pin") if pin and pin.get("bundle") else
                                                                     (f"{cfg.get('bundle_line') or f'mh{line}@'}{(cfg.get('lanes') or {}).get('daily')}", "newest"))
    try:
        bid, bname, rule = Rm.resolve_bundle_loose(us, ref)
        cand_row = row_of(us, Rm, bid, bname)
        newest = Rm.release_base(us, line)
    except SystemExit as e:
        if e.code == EX_USAGE:
            raise
        print("next: the prod host cannot name the bundles — run: ela login tvu", file=sys.stderr); sys.exit(EX_NOTFOUND)
    if not newest:
        print(f"next: no plain official MediaHub {line} bundle", file=sys.stderr); sys.exit(EX_NOTFOUND)
    released = str(newest.get("createTime") or "") > str(cand_row.get("createTime") or "~")
    if released:                                       # the official was cut after the candidate: recompute on it
        base_row = Rm.release_base(us, line, before=newest)
        to_ref = str(newest.get("bundleName"))
        say(f"released: {to_ref} was cut after {bname}")
    else:
        base_row, to_ref = newest, bname
    if not base_row:
        print(f"next: no plain official bundle before {to_ref}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    base = b_of(Rm, base_row, "the newest plain official bundle" + (" before the release" if released else ""))
    cand = b_of(Rm, cand_row, rule if source != "pin" else f"held: {pin.get('why') or 'no reason given'}")

    say(f"tickets {base['name']} → {to_ref}")
    argv = ["python3", os.path.join(SKILLS, "promote", "promote.py")] + (["--env-file", env_file] if env_file else []) + \
        ["--quiet", "tickets", str(line), base["name"], to_ref, "--scope", "all", "--json"]
    tickets, err = run_json(argv, 1200)
    if err:
        print(f"next: promote tickets failed: {err}", file=sys.stderr); sys.exit(EX_REMOTE)
    sources["tickets"] = {"what": f"ela promote tickets {line} \"{base['name']}\" \"{to_ref}\" --scope all", "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}

    report, rname = qa_report(s, line)
    if report:
        sources["qa_report"] = {"what": f"<reports>/promote/{rname}", "at": report.get("generated_at")}
        try:
            age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.strptime(report.get("generated_at") or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
            if age.total_seconds() > QA_REPORT_MAX_H * 3600:
                gaps.append({"kind": "qa_report_old", "detail": f"the latest promotion report ({rname}) is {int(age.total_seconds() // 3600)}h old; QA verdicts, lane versions and unbuilt commits are as of then"})
        except ValueError:
            pass
    else:
        gaps.append({"kind": "qa_report_missing", "detail": "no saved daily → prod promotion report under <reports>/promote/; no QA verdicts, lane versions or unbuilt commits"})

    sys.path.insert(0, os.path.join(SKILLS, "train"))
    import train as T                                  # noqa: E402 — the written train, the lane cells
    train = T.read_train(s, str(line))
    if train:
        sources["train"] = {"what": f"<reports>/train/{line}.json", "at": train.get("at")}
    else:
        gaps.append({"kind": "train_missing", "detail": f"no written train for {line} (ela train --line {line} --write); must tickets have no lane cells"})

    say("jira: release:must, in development")
    must_rows, at, err = jql(env_file, MUST_JQL, 100)
    if err:
        gaps.append({"kind": "jira_unread", "detail": f"release:must search: {err}"})
    must_since = {}
    for r in must_rows:
        try:
            must_since[r["key"]] = label_added(changelog(env_file, r["key"]))
        except Exception as e:                         # one changelog unread is a gap, never a stop
            must_since[r["key"]] = None
            gaps.append({"kind": "changelog_unread", "detail": f"{r['key']}: {str(e)[:120]}"})
    indev_rows, at2, err = jql(env_file, IN_DEV_JQL, 200)
    if err:
        gaps.append({"kind": "jira_unread", "detail": f"in-development search: {err}"})
    sources["jira"] = {"what": f"{MUST_JQL} · {IN_DEV_JQL}", "at": at2 or at}
    return {"line": str(line), "cfg": cfg, "base": base, "candidate": cand, "candidate_source": source, "released": released,
            "released_bundle": b_of(Rm, newest, "") if released else None, "tickets": tickets, "report": report, "train": train,
            "must_rows": must_rows, "must_since": must_since, "indev_rows": indev_rows, "sources": sources, "gaps": gaps}


# ── write ─────────────────────────────────────────────────────────────────────

def publish(doc, published):
    """next.json through the publish redaction and guard, then next.md as README.md, each atomically. → (path, None)
    or (None, the guard's flags) with the published copy left as it was."""
    sys.path.insert(0, os.path.join(SKILLS, "publish"))
    import publish as P                                # noqa: E402 — redact and the content guard of every published file
    text = P.redact(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    flags = P.guard_flags(text, "next.json", facts_of(doc))
    if flags:
        return None, [f"{n}: {why}: {line}" for n, why, line in flags[:5]]
    d = os.path.join(published, "releases")
    os.makedirs(d, exist_ok=True)
    for name, body in (("next.json", text), ("README.md", open(os.path.join(HERE, "next.md"), encoding="utf-8").read())):
        tmp = os.path.join(d, f".{name}.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp, os.path.join(d, name))
    return os.path.join(d, "next.json"), None


def sync(published, target=None):
    """<published>/releases/ to the remote site, the way lanes/ goes (publish.sync_dir) → its one-line outcome."""
    sys.path.insert(0, os.path.join(SKILLS, "publish"))
    import publish as P                                # noqa: E402
    return P.sync_dir(os.path.join(published, "releases"), "releases", target)


def summary(doc):
    c = doc["counts"]
    L = [doc["headline"],
         f"  base {doc['base']['name']} → candidate {doc['candidate']['name']} ({doc['candidate']['source']})"
         + (f" · released as {doc['release']['released_bundle']['name']}" if doc["release"]["released_bundle"] else ""),
         f"  must {c['must']} ({c['must_missing']} not on the candidate) · on the candidate {c['on_candidate']} · in development {c['in_dev']}"
         f" · docker changed {c['docker_changed']} · unbuilt commits {c['unbuilt_commits']}"]
    L += [f"  must {m['key']} {m['status']} — {m['decision']}" for m in doc["must"] if m.get("decision")]
    L += [f"  gap: {g['detail']}" for g in doc["gaps"]]
    return "\n".join(L)


def cmd_pin(a):
    Rm = R()
    s = Rm.site()
    p = pin_path(s)
    try:
        pins = json.load(open(p, encoding="utf-8")) or {}
    except (OSError, ValueError):
        pins = {}
    if a.unpin:
        if str(a.line) not in pins:
            print(f"nothing held for {a.line}: the candidate is the newest daily bundle"); return
        pins.pop(str(a.line))
        what = f"unpin {a.line}: the candidate follows the newest daily bundle again"
    else:
        if not a.why:
            print("--pin needs --why", file=sys.stderr); sys.exit(EX_USAGE)
        us = Rm.LazyUS(a.env_file or s.get("env"), "prod")
        try:
            bid, name, _ = Rm.resolve_bundle_loose(us, a.pin)
        except SystemExit as e:
            sys.exit(e.code if e.code == EX_USAGE else EX_NOTFOUND)
        pins[str(a.line)] = {"bundle": name, "id": bid, "why": " ".join(a.why.split()), "set": datetime.date.today().isoformat()}
        what = f"pin {a.line}: the candidate is held on {name} ({' '.join(a.why.split())})"
    if not a.apply:
        print(f"DRY RUN — {what}\npass --apply to write {p}"); return
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + f".{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(pins, ensure_ascii=False, indent=1) + "\n")
    os.replace(tmp, p)
    print(f"{what} — written; the next `ela release next --write` uses it")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ela release next", description=__doc__.split("\n\n")[0],
                                 epilog="Schema: next.md beside this script, published as <published>/releases/README.md.")
    ap.add_argument("--env-file")
    ap.add_argument("--line", default="2.1", help="the release train, a key of map release.yaml lines (default 2.1)")
    ap.add_argument("--candidate", help="a bundle name, id or prefix instead of the newest daily bundle, for this run")
    ap.add_argument("--write", action="store_true", help="publish <published>/releases/next.json (atomic, redacted) and its README.md")
    ap.add_argument("--sync", action="store_true", help="with --write: carry releases/ to published_remote for the remote Helm")
    ap.add_argument("--json", action="store_true", help="print the document")
    ap.add_argument("--pin", metavar="REF", help="hold the candidate on this bundle (name, id or prefix); with --why; dry run unless --apply")
    ap.add_argument("--why", help="why the candidate is held")
    ap.add_argument("--unpin", action="store_true", help="the newest daily bundle again; dry run unless --apply")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="no progress lines on stderr")
    a = ap.parse_args(argv)
    if a.pin or a.unpin:
        return cmd_pin(a)
    if a.apply:
        print("--apply goes with --pin or --unpin; --write publishes the document", file=sys.stderr); sys.exit(EX_USAGE)
    if a.sync and not a.write:
        print("--sync goes with --write: it carries the file just written", file=sys.stderr); sys.exit(EX_USAGE)
    now = datetime.datetime.now().astimezone()
    doc = build(gather(a.line, a.candidate, a.env_file, quiet=a.quiet), now)
    if a.write:
        published = R().site().get("published")
        if not published:
            print("next: site.json names no `published` root", file=sys.stderr); sys.exit(EX_USAGE)
        path, flags = publish(doc, published)
        if flags:
            print("next: the publish guard refused next.json; the published copy is unchanged:\n  " + "\n  ".join(flags), file=sys.stderr)
            sys.exit(EX_GUARD)
        synced = sync(published) if a.sync else None
        if not a.json:
            print(f"wrote <published>/releases/next.json (schema {SCHEMA}, {doc['state']})" + (f" · {synced}" if synced else ""))
    if a.json:                                         # `synced` is this run's outcome, never a field of the file
        print(json.dumps(dict(doc, synced=synced) if a.write and a.sync else doc, ensure_ascii=False))
    else:
        print(summary(doc))


if __name__ == "__main__":
    main()
