#!/usr/bin/env python3
"""The next MediaHub release, as data: `ela release next` → <published>/releases/next.json (schema: next.md beside this file).

  ela release next [--line 2.1] [--candidate REF] [--write [--sync]] [--json]
      base         the newest plain official bundle of the train (release.release_base)
      candidate    the newest daily bundle of the line, or the held one (--pin), or --candidate REF (name, id or prefix)
      must         tickets labelled release:must: status, when the label was added, a cell per lane from the train;
                   `shipped` once a plain official bundle carrying it is on the prod lane, and its history line
      must_cleared tickets whose release:must was cleared on his approve, the clear on their history line
      on_candidate `ela promote tickets <line> <base> <candidate> --scope all`, each joined to QA's latest verdict as
                   promote's evidence reads it in the latest saved promotion report (<reports>/promote/<line>-daily-prod.json)
      in_dev       MH tickets In Progress or Review, updated within 14 days, not on the candidate
      docker       the bundles' docker diff, the daily and prod lanes' versions, commits on branches not yet built
    When a plain official bundle was cut after the candidate, the state is `released` and the range is recomputed on
    that bundle (from the official before it). Without --write the document is printed (--json) or summarised; --write
    publishes it atomically through the publish redaction and copies next.md as releases/README.md.
    --sync then carries releases/ alone to site.json `published_remote`, where Helm Akamai reads it (as `publish
    lanes --sync` carries lanes/; typing it is the confirm); the outcome is one line, `synced` in --json, never a failure.
  ela release next --pin REF --why "…" [--apply]   hold the candidate on one bundle; dry run unless --apply
  ela release next --unpin [--apply]                 the newest daily bundle again

Reads facts only: the fact store the passes refresh at their head (`ela facts refresh`: the Jira sweep and its standing
release:must and Fixed In queries, the bundle lists and details, Jenkins, the fetched code) and ela's own files (the
train, the promotion report, the pin). It runs under ELA_FACTS_ONLY, so a read the store cannot answer is a gap in the
file, never a live call; it starts no model session. --pin resolves its bundle live (an interactive write, not a pass).
With --write, the clears of release:must on shipped tickets are proposed as one dry-run batch of the
release-must-clear class (ela dry; <reports>/ela/dry/), asked on today.md and applied only on his A; nothing here writes
to Jira. Writes only <published>/releases/, that batch and, with --pin --apply, <reports>/releases/next-pin.json.

  ela release next --slack [--json]   the Friday summary of the published next.json in Slack mrkdwn, for the owner's
                                      direct message as a dry run (the runner sends it at the Friday 17:30 pass); it
                                      reads only that file and writes nothing
Stdlib only.
Exit codes: 0 ok · 2 usage · 3 the store cannot name the bundles · 4 the publish guard refused the file (the published
copy is left as it was) · 5 a source failed.
"""
import argparse, datetime, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
SCHEMA = 3                                       # 3: head, candidate.provisional, candidate_verdicts · 2: priority and updated on every ticket
EX_USAGE, EX_NOTFOUND, EX_GUARD, EX_REMOTE = 2, 3, 4, 5
PASSES = ("08:00", "12:30", "17:30")            # the runner's weekday runs that refresh the file: the morning run, midday, afternoon
STALE_GRACE_H = 2
IN_DEV_STATUSES = ("In Progress", "Review")
MUST_LABEL = "release:must"
CLEAR_CLASS = "release-must-clear"               # ela dry's class: the clears wait for his A (vault releases/release-naming.md rule 6)
CLEARED_KEEP_DAYS = 14                            # a cleared ticket stays in must_cleared this long, its clear on its history line
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
        return f"{name}, planned for {lane_label(lane)} on {day_text(d)}"
    return f"{name}, planned for {lane_label(lane)}"


def lane_label(lane):
    """The lane's display label, MediaHub's name first and the UR / J2N environment in brackets (line.py lane_label,
    the one place it is derived from the map): prod-3 → prod-3 (UR/J2N Prod 3)."""
    sys.path.insert(0, HERE)
    import line as LP                            # noqa: E402
    return LP.lane_label(lane) if lane else str(lane)


def day_text(d):
    return f"{d.strftime('%A')} {d.day} {d.strftime('%b')}"


VERDICT_ORDER = ("fail", "none", "partial", "n-a", "pass")       # the page's order: what needs attention first


def verdict_of(qa):
    """QA's reading as one of the page's five verdicts: accepted ships nothing, so not applicable; a developer's own
    word or no reading is no verdict."""
    v = (qa or {}).get("verdict") or "none"
    return "n-a" if v == "accepted" else v if v in VERDICT_ORDER else "none"


def candidate_verdicts(on):
    rows = [{"key": t["key"], "verdict": verdict_of(t.get("qa")), "url": t["url"]} for t in on]
    return sorted(rows, key=lambda r: (VERDICT_ORDER.index(r["verdict"]), r["key"]))


def n_of(n, one, many):
    return f"{n} {one if n == 1 else many}"


def head(state, name, lane, planned_for, counts, verdicts, provisional, facts_at, now):
    """The page's head as words, so a reader renders it without judgment: the title (the lane by its MediaHub name, the
    UR environment in brackets), one sentence of counts, and the facts' time."""
    where = lane_label(lane)
    if state == "released":
        title = f"{name} → {where}, released"
    elif planned_for:
        title = f"{name} → {where}, {day_text(datetime.date.fromisoformat(planned_for))}"
    else:
        title = f"{name} → {where}"
    c = {v: sum(1 for r in verdicts if r["verdict"] == v) for v in VERDICT_ORDER}
    on, must, dev = counts["on_candidate"], counts["must"], counts["in_dev"]
    shipped = counts.get("must_shipped") or 0
    lede = (f"{n_of(must, 'ticket must', 'tickets must')} ship" + (f" ({shipped} shipped, the label's clear waiting on your A)" if shipped else "")
            + f", {on} {'is' if on == 1 else 'are'} on the candidate "
            f"({c['pass']} QA pass, {c['fail'] + c['none']} fail or no verdict) and {dev} {'is' if dev == 1 else 'are'} in development"
            + ("; the candidate is provisional until pinned." if provisional else "."))
    t = None
    try:
        t = datetime.datetime.fromisoformat(str(facts_at)) if facts_at else None
    except ValueError:
        t = None
    t = (t if t and t.tzinfo else t.replace(tzinfo=now.tzinfo) if t else None)
    stamp = lambda x: f"{day_text(x)} {x.strftime('%H:%M')}"  # noqa: E731
    read = (f"Facts as of {stamp(t.astimezone(now.tzinfo))}, computed {stamp(now)}" if t else
            f"Computed {stamp(now)}; the fact store names no read time")
    return {"title": title, "lede": lede, "read": read}


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


def iso_time(ts):
    """A Jira stamp (2026-11-24T17:55:11.994-0800) or an ISO time as ISO-8601 with this machine's offset; None when
    there is none."""
    t = None
    try:
        t = datetime.datetime.strptime(str(ts or ""), "%Y-%m-%dT%H:%M:%S.%f%z")
    except ValueError:
        try:
            t = datetime.datetime.fromisoformat(str(ts or ""))
        except ValueError:
            return None
    return (t if t.tzinfo else t.astimezone()).astimezone().isoformat(timespec="seconds")


def ticket(row, qa=None, **more):
    key, parent = row.get("key"), row.get("parent")
    parent = parent.get("key") if isinstance(parent, dict) else parent
    return dict({"key": key, "url": row.get("url") or BROWSE + str(key), "summary": row.get("summary") or "",
                 "type": row.get("type"), "status": row.get("status"), "assignee": row.get("assignee"),
                 "priority": row.get("priority") or None, "updated": iso_time(row.get("updated")),
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
    cleared_rec = cleared_of(inp.get("clear_records"), now)
    proposed = proposed_of(inp.get("clear_batches"))
    ship_name = rel_bundle["name"] if rel_bundle else (inp.get("base") or {}).get("name")
    must, must_cleared = [], []
    for r in inp.get("must_rows") or []:
        k = r.get("key")
        tr = trows.get(k) or {}
        carried = k in on_keys
        m = ticket(r, qa_of(ev.get(k)), tracked_since=(inp.get("must_since") or {}).get(k), on_candidate=carried,
                   position=tr.get("position"), cells=tr.get("cells") or {},
                   decision="hold or defer" if state == "planned" and not carried else None)
        m["shipped"] = shipped_of(m, state, prod_lane, ship_name)
        c = cleared_rec.get(k)
        if c and (iso_time(m.get("tracked_since")) or "") > c["at"]:
            c = None                                   # labelled again after the clear: owed again
        m["history"] = history_of(m, proposed.get(k), c)
        (must_cleared if c else must).append(m)        # the store still shows a label his A removed: cleared
    prev = {x.get("key"): x for x in ((inp.get("previous") or {}).get("must") or []) + ((inp.get("previous") or {}).get("must_cleared") or [])}
    have = {m["key"] for m in must_cleared + must}
    for k, c in sorted(cleared_rec.items()):
        if k in have:
            continue
        p = dict(prev.get(k) or ticket({"key": k}))
        p["history"] = history_of(p, None, c)
        p["decision"] = None
        must_cleared.append(p)

    in_dev = []
    for r in inp.get("indev_rows") or []:
        if r.get("key") in on_keys:
            continue
        in_dev.append(ticket(r, qa_of(ev.get(r.get("key")))))

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

    source = inp.get("candidate_source") or "newest"
    candidate = bundle(inp.get("candidate"), source=source)
    provisional = state == "planned" and source != "pin"
    if candidate is not None:
        candidate["provisional"] = provisional
    verdicts = candidate_verdicts(on)
    counts = {"must": len(must), "must_missing": sum(1 for m in must if not m["on_candidate"]),
              "must_shipped": sum(1 for m in must if m.get("shipped")), "must_cleared": len(must_cleared), "on_candidate": len(on),
              "in_dev": len(in_dev), "docker_changed": len(diff), "unbuilt_commits": sum(len(b["commits"]) for b in branches)}
    sources = inp.get("sources") or {}

    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(timespec="seconds"),
        "stale_after": stale_after(now),
        "line": line,
        "state": state,
        "headline": headline(state, name, prod_lane, planned_for),
        "head": head(state, name, prod_lane, planned_for, counts, verdicts, provisional, (sources.get("facts") or {}).get("at"), now),
        "release": {"name": name, "lane": prod_lane, "planned_for": planned_for, "released_bundle": rel_bundle},
        "base": bundle(inp.get("base")),
        "candidate": candidate,
        "candidate_verdicts": verdicts,
        "lanes": list((inp.get("train") or {}).get("lanes") or []),
        "must": must,
        "must_cleared": must_cleared,
        "on_candidate": on,
        "epics": epics,
        "in_dev": in_dev,
        "docker": {"bundle_diff": diff, "lanes": lanes, "branches": branches},
        "counts": counts,
        "sources": sources,
        "gaps": gaps,
    }


def shipped_of(m, state, prod_lane, bundle_name):
    """{bundle, lane, arrived, since} when the ticket has shipped, else None. Shipped: the plain official bundle it
    reached carries it (the released bundle's content in the released state; the base, so not the candidate, while
    planned) and the line's prod lane carries its fix by the train's cell (Fixed In against the lane's own version, so
    the bundle has been deployed). The candidate's content alone is never shipped: it is not an official bundle yet."""
    cell = (m.get("cells") or {}).get(prod_lane) or {}
    if not prod_lane or not bundle_name or not cell.get("arrived"):
        return None
    if (state == "released") != bool(m.get("on_candidate")):
        return None
    return {"bundle": bundle_name, "lane": prod_lane, "arrived": cell.get("arrived"), "since": cell.get("since")}


def proposed_of(batches):
    """{key: {at, batch}} for each ticket an open release-must-clear batch asks to clear."""
    out = {}
    for b in batches or []:
        if b.get("class") != CLEAR_CLASS or b.get("state") not in ("open", "failed"):
            continue
        for w in b.get("writes") or []:
            if w.get("outcome") not in ("landed", "struck"):
                out[w.get("target")] = {"at": iso_time(b.get("carried_at") or b.get("made")), "batch": b.get("id")}
    return out


def cleared_of(rows, now, days=CLEARED_KEEP_DAYS):
    """{key: {at, batch, act}}: release:must clears applied on his A (ela dry's record) within `days`."""
    out = {}
    cutoff = now - datetime.timedelta(days=days)
    for r in rows or []:
        if r.get("class") != CLEAR_CLASS or r.get("verdict") not in ("applied", "edited") or not r.get("target"):
            continue
        at = iso_time(r.get("at"))
        if not at or datetime.datetime.fromisoformat(at) < cutoff:
            continue
        if r["target"] not in out or at > out[r["target"]]["at"]:
            out[r["target"]] = {"at": at, "batch": r.get("batch"), "act": r.get("act")}
    return out


def history_of(m, proposed, cleared):
    """The ticket's history line: [{at, event, …}] oldest first — labelled, shipped, clear proposed, cleared."""
    h = [x for x in (m.get("history") or []) if x.get("event") not in ("clear proposed", "cleared")]
    if not any(x.get("event") == "labelled" for x in h) and iso_time(m.get("tracked_since")):
        h.append({"at": iso_time(m["tracked_since"]), "event": "labelled"})
    s = m.get("shipped")
    if s and not any(x.get("event") == "shipped" for x in h):
        h.append({"at": iso_time(s.get("since")) if s.get("since") else None, "event": "shipped", "bundle": s["bundle"], "lane": s["lane"]})
    if proposed and not cleared:
        h.append({"at": proposed["at"], "event": "clear proposed", "batch": proposed["batch"]})
    if cleared:
        h.append({"at": cleared["at"], "event": "cleared", "batch": cleared["batch"], "by": "the owner's approve"})
    return sorted(h, key=lambda x: x.get("at") or "")


def clear_writes(doc):
    """The release-must-clear batch's writes: one label removal per must ticket that has shipped."""
    out = []
    for m in doc.get("must") or []:
        s = m.get("shipped")
        if s:
            out.append({"n": len(out) + 1, "target": m["key"], "command": f"ela jira label {m['key']} --remove {MUST_LABEL}",
                        "why": f"shipped: {s['bundle']} is on {s['lane']} (fix arrived {s.get('arrived')}); release:must means still owed"})
    return out


def dry_module():
    sys.path.insert(0, os.path.join(SKILLS, "dry"))
    import dry as D                               # noqa: E402 — the batches' one reader and writer
    return D


def propose_clears(doc, reports, today):
    """Place the clears as one batch of the release-must-clear class (open until his A; a batch with nothing left to
    clear settles). → the batch id, or None when there is nothing to clear."""
    b = dry_module().make_batch(reports, CLEAR_CLASS, f"mh-{doc['line']}", clear_writes(doc), [], today)
    return b["id"] if b else None


def facts_of(doc):
    """The strings the document cites as fields (titles, commit subjects): the publish guard passes a quotation in one."""
    out = [t.get("summary") or "" for k in ("must", "must_cleared", "on_candidate", "in_dev", "epics") for t in doc.get(k) or []]
    out += [c.get("subject") or "" for b in (doc.get("docker") or {}).get("branches") or [] for c in b.get("commits") or []]
    return [s for s in out if s]


# ── reads: the fact store only ─────────────────────────────────────────────────
# Every input comes from what the passes already read (<runtime>/facts/, refreshed at the head of each pass) and from
# files ela wrote (the train, the promotion report, the pin). ELA_FACTS_ONLY is set before any read, so a source the
# store lacks is refused and becomes a gap, never a live call; nothing here starts a model session.

FACT_SOURCES = ("jira", "builds", "code")       # the store's sources this document is computed from


def jira_module():
    sys.path.insert(0, os.path.join(SKILLS, "jira"))
    import jira as J                              # noqa: E402 — the Jira store's readers
    return J


def facts_module():
    sys.path.insert(0, os.path.join(SKILLS, "facts"))
    import facts as F                             # noqa: E402
    return F


def row_of_raw(i):
    """A stored raw issue (the sweep's or a standing query's) as the row `ticket` reads."""
    f = i.get("fields") or {}
    name = lambda o, k="name": (o or {}).get(k)  # noqa: E731
    return {"key": i.get("key"), "summary": f.get("summary") or "", "status": name(f.get("status")), "type": name(f.get("issuetype")),
            "assignee": name(f.get("assignee"), "displayName"), "priority": name(f.get("priority")), "parent": (f.get("parent") or {}).get("key"), "updated": f.get("updated")}


def sweep_issues():
    """The Jira sweep's raw issues (facts/jira/changes.json): MH issues updated within its horizon, with changelog."""
    F = facts_module()
    return F.read_json(os.path.join(F.store_dir("jira"), "changes.json"), []) or []


def must_from_store(gaps):
    """(rows, read_at) of the standing `release-must` query; ([], None) and a gap when the store lacks it."""
    F, J = facts_module(), jira_module()
    doc = F.read_json(os.path.join(F.store_dir("jira", "queries"), "release-must.json")) or {}
    if not doc.get("at"):
        gaps.append({"kind": "jira_not_in_facts", "detail": "no stored release:must query (the next `ela facts refresh` reads it)"})
        return [], None
    if doc.get("jql") != J.STANDING["release-must"][0]:
        gaps.append({"kind": "jira_not_in_facts", "detail": "the stored release:must query predates its current text"})
    return [row_of_raw(i) for i in doc.get("issues") or []], doc.get("at")


def must_since_of(keys, sweep, previous):
    """{key: when release:must was added}: the sweep's changelog (a label added inside its horizon moved the issue, so the
    sweep holds it), else the time the previous next.json carried for the key, else None."""
    hist = {i.get("key"): ((i.get("changelog") or {}).get("histories") or []) for i in sweep}
    prev = {m.get("key"): m.get("tracked_since") for m in (previous or {}).get("must") or []}
    return {k: label_added(hist.get(k)) or prev.get(k) for k in keys}


def in_dev_from_sweep(sweep, now, days=14):
    """MH tickets In Progress or Review updated within `days`, newest first, from the sweep (its horizon is 14 days)."""
    cutoff = (now - datetime.timedelta(days=days)).astimezone(datetime.timezone.utc)
    J = jira_module()
    out = []
    for i in sweep:
        r = row_of_raw(i)
        if not str(r["key"] or "").startswith("MH-") or r["status"] not in IN_DEV_STATUSES:
            continue
        upd = J.updated_iso(r.get("updated") or "")
        if upd and datetime.datetime.fromisoformat(upd).astimezone(datetime.timezone.utc) < cutoff:
            continue
        out.append(r)
    return sorted(out, key=lambda r: J.updated_iso(r.get("updated") or ""), reverse=True)


def facts_read(gaps, now):
    """{source: read time} of the store's sources this document uses; a source older than the store's max age, or
    never read, is a gap: the page states the age, it never hides it."""
    F = facts_module()
    out = {}
    for src in FACT_SOURCES:
        wm = F.watermark(src)
        at, t = wm.get("at"), F.parse_iso(wm.get("at"))
        out[src] = at
        if t is None:
            gaps.append({"kind": "facts_missing", "detail": f"facts {src}: never refreshed (ela facts refresh --source {src})"})
        elif (now - t).total_seconds() > F.max_age_hours() * 3600:
            gaps.append({"kind": "facts_old", "detail": f"facts {src}: read {t.strftime('%m-%d %H:%M')}, older than {F.max_age_hours():g}h"})
        if wm.get("gap"):
            gaps.append({"kind": "facts_gap", "detail": f"facts {src}: {str((wm.get('gap') or {}).get('why'))[:160]}"})
    return out


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


def previous_doc(s):
    try:
        return json.load(open(os.path.join(s.get("published") or "", "releases", "next.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None


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
    """Every input `build` needs, from the fact store and ela's own files; no source is read live (ELA_FACTS_ONLY).
    Exits 3 when the store cannot name the bundles."""
    os.environ["ELA_FACTS_ONLY"] = "1"
    os.environ.pop("ELA_FACTS_FRESH", None)
    Rm = R()
    s = Rm.site()
    env_file = env_file or s.get("env")
    cfg = (Rm.rmap("lines") or {}).get(str(line))
    if not cfg:
        print(f"unknown release line {line!r}", file=sys.stderr); sys.exit(EX_USAGE)
    gaps, sources = [], {}
    now = datetime.datetime.now().astimezone()

    def say(m):
        if not quiet:
            print(f"· {m}", file=sys.stderr, flush=True)
    read = facts_read(gaps, now)
    stamps = {k: (facts_module().parse_iso(v).strftime("%m-%d %H:%M") if facts_module().parse_iso(v) else "never") for k, v in read.items()}
    sources["facts"] = {"what": "<runtime>/facts/: " + " · ".join(f"{k} {v}" for k, v in stamps.items()),
                        "at": min((v for v in read.values() if v), default=None)}     # the oldest source the file stands on
    us = Rm.LazyUS(env_file, "prod")                    # under ELA_FACTS_ONLY a call is refused, never made
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
        print("next: the fact store cannot name the bundles — run: ela facts refresh --source builds", file=sys.stderr); sys.exit(EX_NOTFOUND)
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

    say(f"tickets {base['name']} → {to_ref} (from the fact store)")
    argv = ["python3", os.path.join(SKILLS, "promote", "promote.py")] + (["--env-file", env_file] if env_file else []) + \
        ["--quiet", "tickets", str(line), base["name"], to_ref, "--scope", "all", "--json"]
    tickets, err = run_json(argv, 1200)
    if err:
        print(f"next: promote tickets failed: {err}", file=sys.stderr); sys.exit(EX_REMOTE)
    sources["tickets"] = {"what": f"ela promote tickets {line} \"{base['name']}\" \"{to_ref}\" --scope all, from the fact store",
                          "at": now.isoformat(timespec="seconds")}

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

    say("jira: release:must, in development (from the fact store)")
    must_rows, must_at = must_from_store(gaps)
    sweep = sweep_issues()
    previous = previous_doc(s)
    must_since = must_since_of([r["key"] for r in must_rows], sweep, previous)
    reports = s.get("reports") or os.path.join(s.get("projects", ""), "reports")
    try:
        D = dry_module()
        clear_batches, clear_records = [b for b in D.batches(reports) if b.get("class") == CLEAR_CLASS], D.record(reports)
    except Exception as e:                             # noqa: BLE001 — the dry store unread: clears are not judged
        clear_batches, clear_records = [], []
        gaps.append({"kind": "dry_store_unread", "detail": f"ela dry's store: {str(e)[:160]}; release:must clears not shown"})
    indev_rows = in_dev_from_sweep(sweep, now)
    sources["jira"] = {"what": f"the standing release:must query · the sweep's {' / '.join(IN_DEV_STATUSES)} tickets updated within 14 days",
                       "at": must_at or read.get("jira")}
    return {"line": str(line), "cfg": cfg, "base": base, "candidate": cand, "candidate_source": source, "released": released,
            "released_bundle": b_of(Rm, newest, "") if released else None, "tickets": tickets, "report": report, "train": train,
            "must_rows": must_rows, "must_since": must_since, "indev_rows": indev_rows, "sources": sources, "gaps": gaps,
            "previous": previous, "clear_batches": clear_batches, "clear_records": clear_records}


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
    """<published>/releases/ to Helm Akamai, the way lanes/ goes (publish.sync_dir) → its one-line outcome."""
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
    L += [f"  must {m['key']} shipped in {m['shipped']['bundle']} on {m['shipped']['lane']}: clear release:must, on your A"
          for m in doc["must"] if m.get("shipped")]
    L += [f"  cleared {m['key']} {next((h['at'][:10] for h in m.get('history') or [] if h.get('event') == 'cleared' and h.get('at')), '')}"
          for m in doc.get("must_cleared") or []]
    L += [f"  gap: {g['detail']}" for g in doc["gaps"]]
    return "\n".join(L)


SLACK_LIST_MAX = 15                               # tickets per section of the Friday summary; the rest counted


def slack_escape(s):
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def slack_ticket(t):
    who = f" · {slack_escape(t['assignee'])}" if t.get("assignee") else ""
    summ = slack_escape((t.get("summary") or "").strip())
    summ = summ if len(summ) <= 90 else summ[:89].rstrip() + "…"
    return f"• <{t.get('url') or BROWSE + str(t['key'])}|{t['key']}> {summ}{who}"


def slack_section(title, rows):
    if not rows:
        return []
    L = [f"*{title} ({len(rows)})*"] + [slack_ticket(t) for t in rows[:SLACK_LIST_MAX]]
    if len(rows) > SLACK_LIST_MAX:
        L.append(f"• … and {len(rows) - SLACK_LIST_MAX} more on /release/next")
    return L + [""]


def no_verdict(t):
    return not t.get("qa") or (t["qa"].get("verdict") or "none") in ("none", "dev-declared")


def slack_summary(doc, now=None):
    """The Friday summary of the candidate in Slack mrkdwn (never Markdown: `*bold*`, `•`, `<url|label>`), for the
    owner's direct message as a dry run: the release, its date and lane, the key figures, the must tickets the
    candidate lacks, and the tickets QA failed or has given no verdict on. Pure: reads only the document."""
    rel, c = doc.get("release") or {}, doc.get("counts") or {}
    when = ""
    if rel.get("planned_for"):
        d = datetime.date.fromisoformat(rel["planned_for"])
        when = f", planned for {d.strftime('%A')} {d.day} {d.strftime('%b')}"
    elif doc.get("state") == "released":
        when = ", released"
    on = doc.get("on_candidate") or []
    fail = [t for t in on if (t.get("qa") or {}).get("verdict") == "fail"]
    none = [t for t in on if no_verdict(t)]
    missing = [m for m in doc.get("must") or [] if not m.get("on_candidate")]
    cand, base = doc.get("candidate") or {}, doc.get("base") or {}
    L = ["_Dry run, to you only: the candidate summary. Nothing is posted anywhere else._", "",
         f"*{slack_escape(rel.get('name') or doc.get('headline'))}* → {slack_escape(lane_label(rel.get('lane')) if rel.get('lane') else '?')}{when}",
         f"Candidate `{cand.get('name')}` ({cand.get('source')}) · base `{base.get('name')}`",
         f"• must {c.get('must', 0)}, {c.get('must_missing', 0)} not on the candidate"
         + (f", {c['must_shipped']} shipped" if c.get("must_shipped") else ""),
         f"• on the candidate {c.get('on_candidate', 0)}: QA fail {len(fail)} · no QA verdict {len(none)}",
         f"• in development {c.get('in_dev', 0)} · docker changed {c.get('docker_changed', 0)} · unbuilt commits {c.get('unbuilt_commits', 0)}",
         ""]
    L += slack_section("Must, not on the candidate: hold or defer", missing)
    L += slack_section("QA fail", fail)
    L += slack_section("No QA verdict", none)
    stamp = str(doc.get("generated_at") or "")[:16].replace("T", " ")
    stale = now is not None and doc.get("stale_after") and now.isoformat(timespec="seconds") > str(doc["stale_after"])
    gaps = len(doc.get("gaps") or [])
    L.append(f"_From next.json computed {stamp}" + (" (stale)" if stale else "") + (f" · {gaps} gap{'s' if gaps != 1 else ''}" if gaps else "") + "._")
    return "\n".join(L)


def cmd_slack(a):
    """Print the Friday summary of the published next.json; exit 3 when there is none."""
    published = R().site().get("published")
    doc = previous_doc({"published": published})
    if not doc:
        print("next: no published releases/next.json to summarise (ela release next --write)", file=sys.stderr); sys.exit(EX_NOTFOUND)
    text = slack_summary(doc, datetime.datetime.now().astimezone())
    print(json.dumps({"text": text, "generated_at": doc.get("generated_at")}, ensure_ascii=False) if a.json else text)


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
    ap.add_argument("--sync", action="store_true", help="with --write: carry releases/ to published_remote for Helm Akamai")
    ap.add_argument("--json", action="store_true", help="print the document")
    ap.add_argument("--pin", metavar="REF", help="hold the candidate on this bundle (name, id or prefix); with --why; dry run unless --apply")
    ap.add_argument("--why", help="why the candidate is held")
    ap.add_argument("--unpin", action="store_true", help="the newest daily bundle again; dry run unless --apply")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="no progress lines on stderr")
    ap.add_argument("--slack", action="store_true", help="the Friday summary of the published next.json in Slack mrkdwn, "
                    "for the owner's direct message as a dry run; reads only that file, writes nothing")
    a = ap.parse_args(argv)
    if a.slack:
        return cmd_slack(a)
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
        s = R().site()
        try:                                           # the clears wait for his A on today.md; nothing written to Jira
            doc_batch = propose_clears(doc, s.get("reports") or os.path.join(s.get("projects", ""), "reports"), now.date())
        except Exception as e:                         # noqa: BLE001 — the file is written; the batch is said missing
            doc_batch = None
            print(f"next: the release:must clears were not proposed: {e}", file=sys.stderr)
        if not a.json:
            print(f"wrote <published>/releases/next.json (schema {SCHEMA}, {doc['state']})" + (f" · {synced}" if synced else "")
                  + (f" · clears asked as dry:{doc_batch}" if doc_batch else ""))
    if a.json:                                         # `synced` is this run's outcome, never a field of the file
        print(json.dumps(dict(doc, synced=synced) if a.write and a.sync else doc, ensure_ascii=False))
    else:
        print(summary(doc))


if __name__ == "__main__":
    main()
