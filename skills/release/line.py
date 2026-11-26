#!/usr/bin/env python3
"""The line page: one release line read as one page. Stdlib only, local files only (no host is asked).

    line.py <line> [--json]        the page as Markdown (or its facts), from the reports root and the runtime

Where the line stands (each lane in MediaHub naming, the UR environment in brackets, its build, since when, QA's word,
and a lane ahead of its upstream said why), what can move next and what blocks it, the docker services that differ
between its lanes, one line per build with its detail folded, and one line per promotion or deploy note. One
`Can't read` line names each source that could not be read. The vault writes it as releases/<line>/<line>.md on every
sync; the build notes it replaces are history. Plan: vault ela/2026-11-20-plan-one-page-per-release-line.md.

Sources: the build records (<reports>/releases/<line>/*-build-*.json), the lane reads (<runtime>/runner/versions-*.json),
QA's reports per version (<runtime>/runner/qa-tested.json), the stored promote reports (<reports>/promote/<line>-*.json)
and pending promotions, the docker candidates and ledger, the fact store's tickets for titles, and the line's written
train (<reports>/train/<line>.json, `ela train --write`) for Fixes on their way: each fix by what it does to its next move.
Exit codes: 0 ok · 2 usage or site.
"""
import argparse, datetime, json, os, re, sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import release as R  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "train"))
import fixes as FX  # noqa: E402  — the train's rows as the deploy sees them: Fixes on their way

SERVICES = ("mediahub-backend", "mediahub-frontend", "unified-streaming", "unified-media-frontend", "unified-media-backend")
SERVICE_NAMES = {"mediahub-backend": "MediaHub Backend", "mediahub-frontend": "MediaHub Frontend", "unified-streaming": "UR Caller",
                 "unified-media-frontend": "Unified Media Frontend", "unified-media-backend": "Unified Media Backend",
                 "orchestration": "Orchestration"}
VERDICT_WORDS = {"none": "no QA verdict", "dev-declared": "Fixed In by its developer, no QA verdict", "n-a": "QA: not applicable",
                 "partial": "QA partial", "pass": "QA pass", "fail": "QA fail"}
VERDICT_RANK = {"fail": 0, "partial": 1, "n-a": 2, "pass": 3}
SHOWN_BUILDS_DAYS, SHOWN_HISTORY = 14, 6         # above the fold: builds of the last two weeks, the six newest notes
REPORT_FRESH_DAYS = 2                             # a stored promote report older than this is named as stale
TRAIN_FRESH_DAYS = 1                              # a written train older than this is named under Can't read
LIST_MAX = 4                                      # tickets named in words per bucket above the fold; the rest folded
REPORT_BUILD = re.compile(r"For (\d+\.\d+) Release build (\d+)", re.I)


def mh_name(lane):
    """The lane as MediaHub's people name it: a China lane by the map's `shown` (prod-2-china → CN Prod2), a .com QA
    lane by its AWS name (qa-cn3 → QA-AWS3), every other lane by its own name (daily-wed, prod-3, daily-stage)."""
    lane = str(lane or "")
    try:
        for reg in (R.rmap("regions") or {}).values():
            shown = (((reg or {}).get("lanes") or {}).get(lane) or {}).get("shown")
            if shown:
                return shown
    except (Exception, SystemExit):
        pass
    m = re.fullmatch(r"qa-cn(\d+)", lane)
    return f"QA-AWS{m.group(1)}" if m else lane


def ur_lane_text(ur):
    """A UR-side lane as the UR / J2N environment is said: daily-test2 → UR test2, prod-3 → UR/J2N Prod 3, daily-stage →
    UR/J2N Stage; None for a lane that names no UR environment."""
    ur = str(ur or "")
    m = re.fullmatch(r"daily-(test\d+)", ur)
    if m:
        return f"UR {m.group(1)}"
    m = re.fullmatch(r"prod-(\d+)", ur)
    if m:
        return f"UR/J2N Prod {m.group(1)}"
    return "UR/J2N Stage" if ur == "daily-stage" else None


def ur_env(lane):
    """The UR / J2N environment behind a MediaHub lane, from the map; None when the map does not say. In order: the
    map's `lane_ur_env` entry for the lane (the declared word wins); a region's lane by the region's UR environments
    (prod-2-china → UR/J2N cn2: its path prod2 is env cn2); a .com prod lane by its own number (prod-3 → UR/J2N Prod 3);
    a line's daily lane by where that line's UR services run (`lane_for_slug` of j2n and ur-portal: 2.1's daily-wed →
    daily-test2 → UR test2), only when every line that names the lane agrees. A QA lane has no derivation: which UR QA
    environment a line's QA lane uses is not in the map."""
    lane = str(lane or "")
    try:
        declared = (R.rmap("lane_ur_env") or {}).get(lane)
        if declared:
            return str(declared)
        for reg in (R.rmap("regions") or {}).values():
            if lane in ((reg or {}).get("lanes") or {}):
                m = re.fullmatch(r"prod-(\d+)-\w+", lane)
                envs = (((reg or {}).get("ur") or {}).get("envs") or {})
                env = next((e for e, path in envs.items() if m and path == f"prod{m.group(1)}"), None)
                return f"UR/J2N {env}" if env else None
        if re.fullmatch(r"prod-\d+", lane):
            return ur_lane_text(lane)
        found = set()
        for cfg in (R.rmap("lines") or {}).values():
            if ((cfg or {}).get("lanes") or {}).get("daily") == lane:
                slugs = (cfg.get("lane_for_slug") or {})
                found |= {slugs.get(s, lane) for s in ("j2n", "ur-portal")}
        return ur_lane_text(found.pop()) if len(found) == 1 else None
    except (Exception, SystemExit):
        return None


def lane_label(lane):
    """The one display label of a lane: MediaHub's name first, the UR / J2N environment in brackets when the map names
    it — `daily-wed (UR test2)`, `prod-3 (UR/J2N Prod 3)`, `CN Prod2 (UR/J2N cn2)`, `QA-AWS3` — never a UR environment
    alone and never the lane's file token in brackets (the owner's naming rule, 2026-11-16/17)."""
    n, env = mh_name(lane), ur_env(lane)
    return f"{n} ({env})" if env else n


def svc_name(slug):
    return SERVICE_NAMES.get(slug, slug)


def vkey(raw):
    p = R.parse_version(str(raw or ""))
    return tuple(p[:4]) if p else None


def vtext(raw):
    p = R.parse_version(str(raw or ""))
    if not p:
        return str(raw or "?")
    return f"{p[0]}.{p[1]}.{p[2]}" + (f".{p[3]}" if p[3] else "")


def load(path, default=None):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return default


def snapshots(runtime):
    """[(date, rows)] of the lane reads, oldest first."""
    d = os.path.join(runtime or "", "runner")
    out = []
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        m = re.fullmatch(r"versions-(\d{4}-\d{2}-\d{2})\.json", f)
        if m:
            doc = load(os.path.join(d, f))
            if isinstance(doc, dict):
                out.append((m.group(1), doc.get("rows") or []))
    return out


def lane_versions(rows, lane):
    """{slug: raw version} a lane runs in one read; a mail row only when it says the lane runs it (built or reported)."""
    out = {}
    for r in rows:
        if r.get("lane") != lane or r.get("service") not in SERVICES or not r.get("version"):
            continue
        if r.get("host") == "mail" and r.get("state") not in ("built", "reported"):
            continue
        out[r["service"]] = r["version"]
    return out


def tested_by_lane(tested, lane):
    """{slug: raw version} the newest QA report names for a lane (a China lane's only reading here)."""
    best = {}
    for x in (tested or {}).values():
        if x.get("lane") == lane and x.get("service") in SERVICES:
            if x["service"] not in best or (x.get("at") or "") > (best[x["service"]].get("at") or ""):
                best[x["service"]] = x
    return {s: x["version"] for s, x in best.items()}, max((x.get("at") or "" for x in best.values()), default="")


def record_slug(service):
    try:
        return R.reconcile_mod().slug_of(service)
    except Exception:
        return None


def build_index(recs):
    """{(slug, version key): record} — the build that brought each service version."""
    idx = {}
    for rec in sorted(recs, key=lambda r: int(re.sub(r"\D", "", str(r["build"])) or 0)):
        for v in rec.get("services") or []:
            s, k = record_slug(v.get("service")), vkey(v.get("to"))
            if s and k:
                idx.setdefault((s, k[:3]), rec)
    return idx


def lane_builds(vers, idx):
    """(base build, [(slug, build)] services from another build, [slug] in no build record): the base is the build most
    of the lane's services came from, the newest on a tie."""
    got, none = {}, []
    for s, raw in vers.items():
        k = vkey(raw)
        rec = idx.get((s, k[:3])) if k else None
        (got.__setitem__(s, str(rec["build"])) if rec else none.append(s))
    if not got:
        return None, [], none
    count = {}
    for b in got.values():
        count[b] = count.get(b, 0) + 1
    base = max(count, key=lambda b: (count[b], int(re.sub(r"\D", "", b) or 0)))
    return base, sorted((s, b) for s, b in got.items() if b != base), sorted(none)


def lane_since(snaps, lane, vers=None):
    """The date of the first read in which the lane ran what it runs now; None when no read holds it."""
    now = {s: vkey(v) for s, v in (vers or (lane_versions(snaps[-1][1], lane) if snaps else {})).items()}
    if not now:
        return None
    since = None
    for date, rows in snaps:
        cur = {s: vkey(v) for s, v in lane_versions(rows, lane).items()}
        since = (since or date) if cur == now else None
    return since


def build_reports(tested, cycle, line):
    """{build: {verdict, at, subject}} — QA's report for a build, only where its subject names that build."""
    out = {}
    rows = list((tested or {}).values()) + [b["report"] for b in (cycle or {}).get("builds") or [] if b.get("report")]
    for x in rows:
        m = REPORT_BUILD.search(x.get("subject") or "")
        if not m or m.group(1) != str(line) or not x.get("verdict"):
            continue
        b, cur = m.group(2), out.get(m.group(2))
        summary = "summary" in (x.get("subject") or "").lower()
        if cur is None or (summary, x.get("at") or "") > (cur["summary"], cur["at"] or ""):
            out[b] = {"verdict": x["verdict"], "at": x.get("at") or "", "subject": x.get("subject"), "summary": summary}
    return out


def version_qa(tested, slug, raw):
    """QA's newest word on this exact version on a .com lane: {verdict, at}; None when no report names it."""
    k = vkey(raw)
    hits = [x for x in (tested or {}).values() if x.get("service") == slug and vkey(x.get("version")) == k
            and not R.lane_region(x.get("lane"))]
    return max(hits, key=lambda x: x.get("at") or "", default=None)


def qa_cycle(today, runtime):
    try:
        sys.path.insert(0, os.path.join(HERE, "..", "brief"))
        import brief as B  # noqa: E402 — the QA cycle's one reader
        return B.qa_cycle(today, None, runtime)
    except Exception:
        return None


def ahead_tickets(rep):
    """From a stored promote report: [(key, summary, verdict, when)] the source lane carries that the target does not."""
    if not rep:
        return []
    verdicts = (rep.get("evidence") or {}).get("keys") or {}
    tickets = {t["key"]: t for t in (rep.get("tickets") or {}).get("tickets") or [] if t.get("exists")}
    keys = []
    for x in (rep.get("delta") or {}).get("services") or []:
        if x.get("relation") != "from_ahead":
            continue
        for c in x.get("commits") or []:
            keys += [k for k in (c.get("keys_in_subject") or c.get("keys") or []) if k in tickets and k not in keys]
    out = []
    for k in sorted(keys):
        ev = verdicts.get(k) or {}
        v = ev.get("verdict") or "none"
        when = max((str(i.get("when") or "")[:10] for i in ev.get("items") or [] if i.get("verdict") == v), default="")
        out.append((k, tickets[k].get("summary") or "", v, when))
    return out


def report_age(rep, today):
    t = str((rep or {}).get("generated_at") or "")[:10]
    try:
        return (today - datetime.date.fromisoformat(t)).days
    except ValueError:
        return None


def docker_rows(cands, ledger, line):
    """The docker images whose readable lanes of this line run different versions: [{image, gm, lanes: [(lane,
    version)], versions: {version: {released, reports, keys}}}]."""
    rel = {}
    for r in ledger:
        if not r.get("image") or not r.get("version"):
            continue
        v = rel.setdefault((r["image"], r["version"].lstrip("v")), {"released": None, "reports": [], "keys": []})
        subj = r.get("subject") or ""
        if re.search(r"report", subj, re.I):
            v["reports"].append({"at": r.get("at"), "by": r.get("by")})
        elif r.get("source", "").startswith("mail"):
            v["released"] = v["released"] or {"at": r.get("at"), "by": r.get("by")}
        v["keys"] += [c if isinstance(c, str) else c.get("key") for c in r.get("claims") or [] if (c if isinstance(c, str) else c.get("key")) not in v["keys"]]
    out, unread = [], set()
    for c in (cands or {}).get("candidates") or []:
        lanes = [x for x in c.get("lanes") or [] if str(x.get("line")) == str(line)]
        unread |= {x["lane"] for x in lanes if x.get("state") == "unread"}
        shown = [(x["lane"], "/".join(x.get("have") or []) if x.get("state") != "absent" else "—") for x in lanes if x.get("state") != "unread"]
        if len({v for _, v in shown}) < 2:
            continue
        gm = sorted({g for x in lanes for g in x.get("gm") or []})
        vers = {}
        for _, v in shown:
            for one in v.split("/"):
                if re.match(r"v?\d", one):
                    vers[one.lstrip("v")] = rel.get((c["image"], one.lstrip("v")), {"released": None, "reports": [], "keys": []})
        if c.get("report") and str(c.get("version") or "").lstrip("v") in vers:
            vers[str(c["version"]).lstrip("v")]["reports"].append({"at": c["report"].get("at"), "by": c["report"].get("by"), "verdict": c.get("verdict")})
        out.append({"image": c["image"], "gm": gm, "lanes": shown, "versions": vers, "verdict": c.get("verdict"), "newest": c.get("version")})
    return out, sorted(unread)


STATE_ORDER = ("In Progress", "Review", "QA", "Not started", "Done")
DONE_SHOWN = 40                                   # Done rows in the folded table, newest first; the rest are a Jira search


def state_group(status):
    """A Jira status as the release page groups it: In Progress, Review, QA, Not started, Done (Cancelled and the
    like are Done: nothing more ships)."""
    name = str((status or {}).get("name") or "")
    cat = str(((status or {}).get("statusCategory") or {}).get("key") or "")
    low = name.lower()
    if re.search(r"\bqa\b|test", low):
        return "QA"
    if low == "review":
        return "Review"
    if cat == "done":
        return "Done"
    if cat == "indeterminate":
        return "In Progress"
    return "Not started"


def ledger_links(path):
    """{key: [(service, version, env)]} the builds ledger ties to each ticket (service_change_ticket); {} unreadable."""
    try:
        import sqlite3
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        rows = c.execute("select t.ticket_key, s.service_key, s.version_norm, s.env from service_change_ticket t "
                         "join service_change s on s.change_uid = t.change_uid").fetchall()
        c.close()
    except Exception:
        return {}
    out = {}
    for k, svc, ver, env in rows:
        out.setdefault(k, []).append((svc, ver, env))
    return out


def ticket_table(line, runtime, rows, ledger=None, cfg=None):
    """The line's tickets as Helm's release page shows them, from the fact store's Jira issues (labelled
    release:mh-<line>) and the builds ledger: each with its state group, assignee, due date, Fixed In and the furthest
    lane its Fixed In runs on; and the fields-health figure of decision 2026-11-02 over the open tickets (one release
    label, an assignee, a due date once past Not started, a Fixed In once in Review or QA) and the Done ones (a Fixed
    In unless cancelled). → {tickets, health} or None when the fact store holds none."""
    cfg = cfg if cfg is not None else ((R.rmap("lines") or {}).get(str(line)) or {})
    label = cfg.get("label") or f"release:mh-{line}"
    d = os.path.join(runtime or "", "facts", "jira", "issues")
    try:
        sys.path.insert(0, os.path.join(HERE, "..", "recent"))
        import recent as RC  # noqa: E402 — the Fixed In field's entries and where they stand on a line
        import jira as J     # noqa: E402
    except Exception:
        return None
    versions = RC.lane_versions(rows)
    links = ledger_links(ledger) if ledger else {}
    out = []
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        issue = load(os.path.join(d, f))
        flds = (issue or {}).get("fields") or {}
        labels = flds.get("labels") or []
        if label not in labels:
            continue
        entries = RC.fixed_in_entries(flds.get(J.FIXED_IN_FIELD))
        stands = RC.stands_at(entries, versions, cfg)["text"] if entries else None
        if not stands and links.get(issue["key"]):
            svc, ver, env = links[issue["key"]][-1]
            stands = f"built: {svc} {ver}" + (f" on {env}" if env else "")
        group = state_group(flds.get("status"))
        status = str((flds.get("status") or {}).get("name") or "")
        lines_ = [l for l in labels if l.startswith("release:mh-")]
        misses = []
        if len(lines_) != 1:
            misses.append("label")
        if group != "Done" and not flds.get("assignee"):
            misses.append("assignee")
        if group in ("In Progress", "Review", "QA") and not flds.get("duedate"):
            misses.append("due date")
        if (group in ("Review", "QA") or (group == "Done" and status.lower() not in ("cancelled", "closed ambigous", "won't do"))) and not entries:
            misses.append("Fixed In")
        out.append({"key": issue["key"], "summary": flds.get("summary") or "", "group": group, "status": status,
                    "assignee": ((flds.get("assignee") or {}).get("displayName") if isinstance(flds.get("assignee"), dict) else flds.get("assignee")) or "",
                    "due": flds.get("duedate") or "", "fixed_in": [f"{s_}@{v}" if v else s_ for s_, v in entries],
                    "lane": stands or ("dev" if group != "Done" else "—"), "updated": str(issue.get("updated") or flds.get("updated") or ""),
                    "misses": misses})
    if not out:
        return None
    missed = {}
    for t in out:
        for m in t["misses"]:
            missed[m] = missed.get(m, 0) + 1
    ok = sum(1 for t in out if not t["misses"])
    return {"tickets": out, "label": label, "health": {"ok": ok, "of": len(out), "missed": missed}}


def gather(line, reports, runtime, today=None, notes=(), builds_ledger=None):
    """Every fact the page shows, read from local files; `notes` are the line's promotion and deploy notes in the vault
    as [{rel, title, date, status}]. → dict (the page is render(dict))."""
    today = today or datetime.date.today()
    line = str(line)
    gaps = []
    cfg = (R.rmap("lines") or {}).get(line) or {}
    roles = [r for r in ("qa", "daily", "prod") if (cfg.get("lanes") or {}).get(r)]
    lanes = [cfg["lanes"][r] for r in roles]
    regions = []
    for reg in (R.rmap("regions") or {}).values():
        for lane, rc in ((reg or {}).get("lanes") or {}).items():
            if str((rc or {}).get("line") or "") == line and not (rc or {}).get("retiring"):
                regions.append(lane)
    recs = [r for r in R.build_records(reports) if str(r.get("line")) == line]
    idx = build_index(recs)
    snaps = snapshots(runtime)
    tested = load(os.path.join(runtime or "", "runner", "qa-tested.json"), {}) or {}
    cycle = qa_cycle(today, runtime) if roles and roles[0] == "qa" else None
    reps = build_reports(tested, cycle, line)
    if not snaps:
        gaps.append(("lane reads", "no versions file under the runtime's runner"))
    elif snaps[-1][0] < today.isoformat():
        gaps.append(("today's lane read", f"the newest is {snaps[-1][0]}"))
    rows = snaps[-1][1] if snaps else []
    now, by_lane = [], {}
    for role, lane in zip(roles, lanes):
        vers = lane_versions(rows, lane)
        by_lane[lane] = vers
        base, other, none = lane_builds(vers, idx)
        if role == "qa":
            gaps.append((mh_name(lane), f"{lane_label(lane)}: the QA host is not read; its versions are what the release mail and QA's report name"))
        since = lane_since(snaps, lane, vers)
        if role == "qa" and base:                         # a QA lane is not read: it runs a build from the day it was sent
            since = next((r["date"] for r in recs if str(r["build"]) == base), since)
        now.append({"lane": lane, "role": role, "versions": vers, "build": base, "other": other, "none": none, "since": since})
    for lane in regions:
        vers, at = tested_by_lane(tested, lane)
        by_lane[lane] = vers
        base, other, none = lane_builds(vers, idx)
        now.append({"lane": lane, "role": "region", "versions": vers, "build": base, "other": other, "none": none,
                    "since": at[:10] or None, "source": f"QA's report {at[5:10]}" if at else None})
        gaps.append((mh_name(lane), f"{lane_label(lane)}: the .cn host's lanes are not mapped; its versions are what QA's last report names"))
    for n in now:                                        # QA's word on what each lane runs
        if n["role"] == "qa" and n["build"]:
            rp = reps.get(n["build"])
            due = next((b.get("due") for b in (cycle or {}).get("builds") or [] if str(b.get("build")) == n["build"]), None)
            n["qa"] = (f"{rp['verdict']} {rp['at'][5:10]}" if rp else
                       f"under test, due {due[5:]} evening" if due and due >= today.isoformat() else
                       f"no report on build {n['build']}" + (f", due {due[5:]}" if due else ""))
            n["qa_detail"] = [] if rp else [f"QA's report on build {n['build']}" + (f" is due the evening of {due[5:]}" if due else " was not read")]
            continue
        under = {b["build"] for b in (cycle or {}).get("builds") or [] if not reps.get(str(b.get("build")))}
        words, worst, last = [], None, ""
        for s, raw in sorted(n["versions"].items()):
            q = version_qa(tested, s, raw)
            from_build = None if s in n["none"] else next((b for x, b in n["other"] if x == s), n["build"])
            if q:
                if worst is None or VERDICT_RANK.get(q["verdict"], 1) < VERDICT_RANK.get(worst, 1):
                    worst = q["verdict"]
                last = max(last, q.get("at") or "")
            elif from_build in under:
                words.append(f"{svc_name(s)} {vtext(raw)} under test (build {from_build})")
            elif n["role"] != "region":
                words.append(f"no QA report names {svc_name(s)} {vtext(raw)}")
        n["qa_detail"] = words
        if n["role"] == "region":
            n["qa"] = n.get("source") or "no QA report read"
        else:                                             # six words at most; each service's exception is in the fold
            n["qa"] = ((f"{worst} {last[5:10]}" if worst else "no QA report")
                       + (f"; {len(words)} unreported" if words and worst else ""))
    # a lane ahead of its upstream: which services, and how they got there, one line per lane pair and source
    ahead = []
    order = [n for n in now if n["role"] != "region"]
    for lo, hi in zip(order[1:], order):                 # daily under qa, prod under daily
        groups = {}
        for s, raw in sorted(lo["versions"].items()):
            a, b = vkey(raw), vkey(hi["versions"].get(s))
            if not a or not b or a[:2] != b[:2] or a <= b:
                continue
            rec = idx.get((s, a[:3]))
            groups.setdefault(str(rec["build"]) if rec else None, []).append((s, raw, rec))
        for build, items in groups.items():
            rec = items[0][2]
            what = ", ".join(f"{svc_name(s)} {vtext(raw)} (theirs {vtext(hi['versions'].get(s))})" for s, raw, _ in items)
            if rec:
                how = f"taken straight from {rec.get('lane_name') or rec['lane']} build {rec['build']}" + \
                      (", past the daily lane (a hotfix to prod)" if lo["role"] == "prod" else "")
            else:
                how = "QA's report names an older version than the lane runs" if hi["role"] == "qa" else "no build record says how"
            short = (f"{mh_name(lo['lane'])} is ahead of {mh_name(hi['lane'])}: build {rec['build']} went straight to it"
                     + (" (a hotfix)." if lo["role"] == "prod" else ".")) if rec else \
                    f"{mh_name(lo['lane'])} is ahead of {mh_name(hi['lane'])} on {len(items)} service{'s' if len(items) != 1 else ''}."
            ahead.append({"short": short, "detail": f"{mh_name(lo['lane'])} is ahead of {mh_name(hi['lane'])} on {what}: {how}"
                          + (f"; first read so on {lo['since'][5:]}" if lo.get("since") else "") + "."})
    # lanes that run the same versions are one row
    rowsets = []
    for n in now:
        same = next((r for r in rowsets if r[0]["versions"] and {s: vkey(v) for s, v in r[0]["versions"].items()} ==
                     {s: vkey(v) for s, v in n["versions"].items()}), None)
        (same.append(n) if same else rowsets.append([n]))
    # the next promotion: the stored report of the nearest pair that carries anything
    nxt = None
    pairs = [("qa", "daily"), ("daily", "prod")]
    for a, b in pairs:
        if a not in roles or b not in roles:
            continue
        rep = load(os.path.join(reports, "promote", f"{line}-{a}-{b}.json"))
        age = report_age(rep, today)
        if rep is None:
            gaps.append((f"{a} → {b} promote report", f"none stored; `ela promote report {line} {a} {b}` writes it"))
            continue
        if age is not None and age > REPORT_FRESH_DAYS:
            gaps.append((f"fresh {a} → {b} report", f"the stored {a} → {b} promote report is {age} days old"))
        t = ahead_tickets(rep)
        frm, to = cfg["lanes"][a], cfg["lanes"][b]
        if nxt is None and t:
            src = next((n for n in now if n["lane"] == frm), {})
            nxt = {"from": frm, "to": to, "build": src.get("build"), "tickets": t, "qa": src.get("qa") or "",
                   "generated": str(rep.get("generated_at") or "")[:16].replace("T", " ")}
        elif t:
            nxt.setdefault("also", []).append({"from": frm, "to": to, "tickets": t})
    pend = load(os.path.join(reports, "promote", "pending.json"), {}) or {}
    pending = []
    for key, rec in pend.items():
        if not isinstance(rec, dict) or str(rec.get("line")) != line or rec.get("closed"):
            continue
        cand = (rec.get("candidate") or {}).get("versions") or {}
        tgt = by_lane.get(rec.get("to")) or {}
        past = bool(cand) and all(vkey(tgt.get(s)) and vkey((c or {}).get("version") if isinstance(c, dict) else c)
                                  and vkey(tgt.get(s)) >= vkey((c or {}).get("version") if isinstance(c, dict) else c)
                                  for s, c in cand.items() if s in SERVICES)
        pending.append({"label": (rec.get("candidate") or {}).get("label") or f"{rec.get('from')} → {rec.get('to')}", "to": rec.get("to"),
                        "past": past, "waiting": rec.get("waiting_on") if isinstance(rec.get("waiting_on"), dict) else None,
                        "plan": rec.get("plan")})
    cands = load(os.path.join(reports, "docker", "candidates.json"))
    ledger = []
    try:
        for l in open(os.path.join(reports, "releases", "docker-versions.jsonl"), encoding="utf-8"):
            try:
                ledger.append(json.loads(l))
            except ValueError:
                pass
    except OSError:
        gaps.append(("docker ledger", "releases/docker-versions.jsonl under the reports root is unreadable"))
    docker, unread = docker_rows(cands, ledger, line) if cands else ([], [])
    if cands is None:
        gaps.append(("docker candidates", "none kept; `ela docker --write` keeps them"))
    if unread:
        gaps.append(("docker on " + ", ".join(mh_name(l) for l in unread), "docker versions on " + ", ".join(lane_label(l) for l in unread) + ": the QA host is not read"))
    keys = sorted({k for r in recs for v in r["services"] for k in v.get("keys") or []}
                  | {k for t in ((nxt or {}).get("tickets") or []) for k in [t[0]]}
                  | {k for d in docker for v in d["versions"].values() for k in v["keys"]})
    facts = R.facts_tickets(runtime, keys)
    missing = [k for k in keys if k not in facts]
    if missing:
        gaps.append((f"titles of {len(missing)} ticket{'s' if len(missing) != 1 else ''}", f"not in the fact store: {', '.join(missing[:6])}{', …' if len(missing) > 6 else ''}"))
    builds = []
    for rec in sorted(recs, key=lambda r: (r["date"], int(re.sub(r"\D", "", str(r["build"])) or 0)), reverse=True):
        rp = reps.get(str(rec["build"]))
        due = next((b.get("due") for b in (cycle or {}).get("builds") or [] if str(b.get("build")) == str(rec["build"])), None)
        qa = (f"QA {rp['verdict']} {rp['at'][5:10]}" if rp else f"under test, report due {due[5:]} evening" if due and due >= today.isoformat()
              else "no QA report on this build read")
        builds.append({"rec": rec, "qa": qa})
    sent = {str(b.get("build")) for b in (cycle or {}).get("builds") or []}
    lost = sorted(sent - {str(r["build"]) for r in recs}, key=lambda b: int(re.sub(r"\D", "", b) or 0))
    if lost and recs:
        first = min(int(re.sub(r"\D", "", str(r["build"])) or 0) for r in recs)
        lost = [b for b in lost if int(re.sub(r"\D", "", b) or 0) > first]
        if lost:
            gaps.append((f"build{'s' if len(lost) != 1 else ''} {', '.join(lost)}", "sent to QA, no build record written"))
    train = load(os.path.join(reports, "train", f"{line}.json"))
    if train is None:
        gaps.append(("the train", f"none written; `ela train --line {line} --write` writes it"))
    elif str(train.get("at") or "")[:10] < (today - datetime.timedelta(days=TRAIN_FRESH_DAYS)).isoformat():
        gaps.append(("a fresh train", f"the written train is of {str(train.get('at'))[:10]}"))
    table = ticket_table(line, runtime, rows, builds_ledger, cfg)
    if table is None:
        gaps.append(("tickets", f"the fact store holds none labelled release:mh-{line}"))
    elif builds_ledger and not os.path.isfile(builds_ledger):
        gaps.append(("builds ledger", "the builds ledger the site names is not on disk"))
    return {"line": line, "today": today.isoformat(), "rowsets": rowsets, "train": train, "tickets": table, "ahead": ahead, "gaps": gaps, "next": nxt,
            "pending": pending, "docker": docker, "builds": builds, "facts": facts, "notes": list(notes),
            "read": snaps[-1][0] if snaps else None}


def ticket(k, facts, n=70):
    t = facts.get(k)
    return f"{k} {R.ticket_title(t.get('summary'), n)}" if t else f"{k} (not in the fact store)"


def block_id(build):
    return "build-" + re.sub(r"[^a-z0-9-]+", "-", str(build).lower()).strip("-")


def build_lines(rec, facts):
    """A build's folded detail: per service its move and purpose, then its tickets in words."""
    out = []
    for v in rec.get("services") or []:
        out.append((">\n" if out else "") + f"> **{v['service']}** {R.service_move(v)} · {' '.join(str(v.get('for') or '').split())}")
        out += [f"> - {ticket(k, facts)}" for k in v.get("keys") or []]
    if rec.get("notes"):
        out += [">", "> " + " ".join(str(rec["notes"]).split())]
    return out


def render(d):
    """The line page's body: heading, meta, Now, Next promotion, Docker, Fixes on their way, Builds, History."""
    line, facts, today = d["line"], d["facts"], d["today"]
    L = [f"# MediaHub {line} · where the line stands", "",
         f"*{today} · from the lane read of {d['read'] or '—'}, the build records, QA's reports and the stored promote reports*", "",
         "## Now", "", "| lane | build | since | QA |", "|---|---|---|---|"]
    detail = []
    for group in d["rowsets"]:
        n = group[0]
        name = " = ".join(lane_label(x["lane"]) for x in group)
        mixed = n["other"] or (n["none"] and n["build"])
        b = (f"build {n['build']}" + (" (mixed)" if mixed else "")) if n["build"] else ("before build records" if n["versions"] else "—")
        L.append(f"| {name} | {b} | {(n.get('since') or '—')[5:] or '—'} | {n.get('qa') or '—'} |")
        lines = [f"{svc_name(s)} from build {x}" for s, x in n["other"]] + \
                [f"{svc_name(s)} {vtext(n['versions'][s])} in no build record" for s in n["none"] if n["build"]] + list(n.get("qa_detail") or [])
        if lines:
            detail.append(f"> - **{mh_name(n['lane'])}**: " + "; ".join(lines))
    detail += [f"> - {a['detail']}" for a in d["ahead"]]
    L += [""] + [a["short"] for a in d["ahead"]] + ([""] if d["ahead"] else [])
    if detail:
        L += ["> [!note]- Per service: builds, QA and the lane ahead"] + detail + [""]
    gaps = d["gaps"]
    L += ["**Can't read:** " + (", ".join(g[0] for g in gaps) + "." if gaps else "nothing; every source was read."), ""]
    if gaps:
        L += ["> [!note]- Why each could not be read"] + [f"> - **{g[0]}**: {g[1]}" for g in gaps] + [""]
    L += ["## Next promotion", ""]
    nx = d["next"]
    if not nx:
        L += ["Nothing waits: no lane carries a ticket the next lane lacks, as the stored promote reports read it.", ""]
    else:
        t = nx["tickets"]
        ready = [x for x in t if x[2] == "pass"]
        block = [x for x in t if x[2] == "fail"]
        rest = [x for x in t if x[2] not in ("pass", "fail")]
        cand = f"{mh_name(nx['from'])} build {nx['build']}" if nx.get("build") else mh_name(nx["from"])
        L += [f"**{cand} → {lane_label(nx['to'])}:** {len(t)} ticket{'s' if len(t) != 1 else ''} {mh_name(nx['to'])} does not run; "
              f"{len(ready)} QA passed, {len(block)} failed, {len(rest)} without a QA pass (promote report {nx['generated']}).", ""]
        def named(xs, tail):
            shown = [f"{ticket(k, facts, 60)}" + tail(v, w) for k, _, v, w in xs[:LIST_MAX]]
            return "; ".join(shown) + (f"; and {len(xs) - LIST_MAX} more" if len(xs) > LIST_MAX else "")
        if ready:
            L.append(f"- **Ready:** {named(ready, lambda v, w: '')}")
        if block:
            L.append(f"- **Blocks:** {named(block, lambda v, w: f' — QA fail {w[5:]}' if w else ' — QA fail')}")
        if rest:
            L.append(f"- **Not yet passed:** {named(rest, lambda v, w: f' — {VERDICT_WORDS.get(v, v)}')}")
        under = "under test" in (nx.get("qa") or "")
        when = re.search(r"due ([\d-]+ evening)", nx.get("qa") or "")
        L.append(f"- **Decision:** move {cand} to {mh_name(nx['to'])}" +
                 (f" — after QA's report, due {when.group(1)}." if under and when else
                  " — once the failures are answered." if block else
                  f" — {len(rest)} ticket{'s' if len(rest) != 1 else ''} still without a QA pass: wait for QA or move without them." if rest
                  else " — QA passed every ticket; it is yours to call."))
        for o in nx.get("also") or []:
            ok = sum(1 for x in o["tickets"] if x[2] == "pass")
            L.append(f"- Behind it, {mh_name(o['from'])} → {lane_label(o['to'])}: {len(o['tickets'])} tickets, {ok} QA passed.")
        L.append("")
        L += [f"> [!note]- Every ticket {mh_name(nx['to'])} does not run yet"] + \
             [f"> - {ticket(k, facts, 80)} — {VERDICT_WORDS.get(v, v)}{(' ' + w[5:]) if w and v in ('pass', 'fail', 'partial') else ''}" for k, _, v, w in t] + [""]
    for p in d["pending"]:
        if not p["past"] and p.get("waiting") and p["waiting"].get("what"):
            w = p["waiting"]
            L += [f"*{p['label']}: waiting on {w['what']}" + (f" since {w['asked']}" if w.get("asked") else "")
                  + (f" ([thread]({w['thread']}))" if w.get("thread") else "") + "*", ""]
    L += ["## Docker", ""]
    if not d["docker"]:
        L += ["Every docker image QA has reported on runs the same version on this line's readable lanes.", ""]
    folded = []
    for x in d["docker"]:
        lanes = " vs ".join(f"{mh_name(l)} {v}" for l, v in x["lanes"])
        newest = max((v for v in x["versions"]), key=lambda v: vkey(v) or (0,), default=None)
        L.append(f"- **{x['image']}** · {lanes} · QA report on {newest}: {'yes' if newest and x['versions'][newest]['reports'] else 'no'}")
        parts = []
        for ver, info in sorted(x["versions"].items(), key=lambda kv: vkey(kv[0]) or (0,), reverse=True):
            rep = max(info["reports"], key=lambda r: r.get("at") or "", default=None)
            said = f"QA report {str(rep.get('at') or '')[5:10]}" if rep else "no QA report"
            what = ", ".join(ticket(k, facts, 50) for k in info["keys"][:2]) or \
                   (f"released {str(info['released'].get('at') or '')[5:10]}, no ticket named" if info.get("released") else "what it changed is not on record")
            parts.append(f"{ver}: {said}; {what}")
        folded.append(f"> - **{x['image']}** ({', '.join(x['gm'][:2])}{', …' if len(x['gm']) > 2 else ''}): " + " · ".join(parts))
    if d["docker"]:
        L += ["", "> [!note]- What each version changed, and its QA report"] + folded + [""]
    L += FX.block(d.get("train") or {}) if d.get("train") else []
    L += ["## Builds", ""]
    if not d["builds"]:
        L += ["No build record for this line.", ""]
    lo = (datetime.date.fromisoformat(today) - datetime.timedelta(days=SHOWN_BUILDS_DAYS)).isoformat()
    old = [b for b in d["builds"] if b["rec"]["date"] < lo]
    for b in [b for b in d["builds"] if b["rec"]["date"] >= lo]:
        rec = b["rec"]
        keys = {k for v in rec["services"] for k in v.get("keys") or []}
        L += [f"- {rec['date'][5:]} · build {rec['build']} → {lane_label(rec['lane'])} · {len(rec['services'])} service"
              f"{'s' if len(rec['services']) != 1 else ''} · {len(keys)} ticket{'s' if len(keys) != 1 else ''} · {b['qa']} ^{block_id(rec['build'])}", "",
              f"> [!note]- Build {rec['build']}: what each service carries"] + build_lines(rec, facts) + [""]
    if old:
        L += [f"> [!note]- {len(old)} older build{'s' if len(old) != 1 else ''}"] + \
             [f"> - {b['rec']['date'][5:]} · build {b['rec']['build']} → {lane_label(b['rec']['lane'])} · {b['qa']}" for b in old] + [""]
    tt = d.get("tickets")
    if tt:
        h = tt["health"]
        L += ["## Tickets", "", f"{h['of']} tickets labelled {tt['label']} · fields health {round(100 * h['ok'] / h['of'])}% "
              f"({h['ok']} of {h['of']} with every field right" + ("; missing: " + ", ".join(f"{k} {n}" for k, n in sorted(h["missed"].items(), key=lambda kv: -kv[1])) if h["missed"] else "")
              + ")", ""]
        for g in STATE_ORDER:
            rows_ = sorted((t for t in tt["tickets"] if t["group"] == g), key=lambda t: t["updated"], reverse=True)
            if not rows_:
                continue
            shown = rows_[:DONE_SHOWN] if g == "Done" else rows_
            L += [f"> [!note]- {g} · {len(rows_)}", "> | ticket | status | assignee | due | lane | Fixed In |", "> |---|---|---|---|---|---|"]
            L += [f"> | {ticket(t['key'], facts, 60) if t['key'] in facts else t['key'] + ' ' + R.ticket_title(t['summary'], 60)} | {t['status']} | "
                  f"{t['assignee'] or '**none**'} | {t['due'][5:] or ('**none**' if 'due date' in t['misses'] else '—')} | {t['lane']} | "
                  f"{', '.join(t['fixed_in']) or ('**none**' if 'Fixed In' in t['misses'] else '—')} |" for t in shown]
            if len(rows_) > len(shown):
                L.append(f"> *{len(rows_) - len(shown)} older Done tickets in Jira under the label {tt['label']}*")
            L.append("")
    L += ["## History", ""]
    past = [p for p in d["pending"] if p["past"]]
    L += [f"- The open promotion record “{p['label']}” is past: {mh_name(p['to'])} already runs its versions or newer." for p in past]
    if past:
        L.append("")
    notes = sorted(d["notes"], key=lambda n: (n.get("date") or "", n["rel"]), reverse=True)
    if not notes:
        L += ["No promotion or deploy note yet.", ""]
    for n in notes[:SHOWN_HISTORY]:
        L.append(f"- {(n.get('date') or '')[5:]} · [[{n['rel'][:-3]}|{n.get('title') or os.path.basename(n['rel'])[:-3]}]] · {n.get('status') or '?'}")
    if len(notes) > SHOWN_HISTORY:
        L += ["", f"> [!note]- {len(notes) - SHOWN_HISTORY} earlier notes"] + \
             [f"> - {(n.get('date') or '')[5:]} · [[{n['rel'][:-3]}|{n.get('title') or os.path.basename(n['rel'])[:-3]}]] · {n.get('status') or '?'}"
              for n in notes[SHOWN_HISTORY:]]
    return "\n".join(L).rstrip("\n") + "\n"


def main():
    ap = argparse.ArgumentParser(description="One release line as one page, from local files.")
    ap.add_argument("line")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        s = json.load(open(os.path.expanduser("~/.claude/ela/site.json")))
    except (OSError, ValueError) as e:
        print(f"site.json: {e}", file=sys.stderr); sys.exit(2)
    reports = s.get("reports") or os.path.join(s.get("projects", ""), "reports")
    d = gather(a.line, reports, s.get("runtime"), builds_ledger=s.get("builds_ledger"))
    if a.json:
        d = dict(d, builds=[{"build": b["rec"]["build"], "date": b["rec"]["date"], "qa": b["qa"]} for b in d["builds"]])
        print(json.dumps(d, ensure_ascii=False, indent=1, default=str)); return
    print(render(d), end="")


if __name__ == "__main__":
    main()
