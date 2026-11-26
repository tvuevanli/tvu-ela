#!/usr/bin/env python3
"""The train: one object per release line, one row per fix riding the line's path — the facts behind the QA test list,
the status between lanes and the promotion.

    train.py [--env-file F] --line 2.1 [--days 21]        the page as Markdown
    train.py … --json                                      the train
    train.py … --write                                     keep it as <reports>/train/<line>.json
    train.py … --page                                      also write <reports>/lanes/train-<line>.md (the vault places it)
    train.py … --parity                                    the train's QA view against today's test-list-<qa lane>.json;
                                                           exit 0 when equal, 1 with the differences printed
    train.py answer impact:<KEY> A|B [--why TEXT]          his ruling on a your-call row, kept with its kind

A row is an owner ticket (or a no-ticket change-log item, flagged) with its title, layer, owner, priority and the
reason (the test list's rules, called, not copied), how to verify, the auto flag, and one cell per lane of the line:
qa, daily, prod, and the aligned China prod lane as a fourth where the line has one. A cell holds the build or
release that carried the fix there and since when, and the lane's verdict: pass / fail with its source and date (a
QA person's ticket comment, a QA report mail, a reply in the release thread), untested, incident (an open customer
incident naming the key after the fix arrived on a prod lane), n/a (the lane's list began after the fix passed
through). The row's position is the furthest of qa → daily → prod with an arrival, else dev. A fail or an incident on
daily or prod after a pass on qa is a regression: P1, with the reason naming both lanes and builds.

Sources, all read the way ela already reads them: the line's lanes from the published map (release.yaml § lines and
regions); the rows and arrivals per lane from the lanes' release mails (the testlist skill's parsing) joined with the
per-lane test-list state on disk, the migration source that holds each row's first build and verdict; verdicts from
QA's ticket comments, the report mails and the release threads (testlist's readers); the versions row from the saved
lane reads (the brief's matrix cell); incidents from the brief's incidents lane. Writes only under <reports>.
Exit codes: 0 ok · 1 parity differs · 2 usage · 5 the release mails could not be read.
Design: vault to-read/2026-11-02-the-train-one-object-behind-the-test-list-and-the-lane-status.md (phase 1).
"""
import argparse, datetime, json, os, re, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
for d in ("testlist", "brief", "release", "recent", "jira"):
    sys.path.insert(0, os.path.join(SKILLS, d))
import testlist as TL  # noqa: E402  — release mails, behaviours, owners, verdict readers, priority rules, the state files
import brief as B  # noqa: E402  — lane reads, the matrix cell, Slack rows, the incidents lane, lane names
import release as R  # noqa: E402  — the published map: lines and regions
import recent as RC  # noqa: E402  — the versions row renderer and the vault's reading units
import jira as J  # noqa: E402  — a name from a Jira user object
import fixes as FX  # noqa: E402  — each row as the deploy sees it: QA's word, the failed case, the impact on its next move

EX_PARITY, EX_USAGE, EX_REMOTE = 1, 2, 5
ROLES = ("qa", "daily", "prod")
ROLE_RANK = {"dev": 0, "qa": 1, "daily": 2, "prod": 3}
VERDICTS = ("pass", "fail", "untested", "incident", "n/a")
VERDICT_WORD = {"n-a": "n/a"}                  # testlist's word for a verdict → the train's
LEFT_RX = re.compile(r"^(pass|fail|n-a) on (.*?) \((\d{4}-\d{2}-\d{2}), (.*)\)$")   # a state file's left.why
ROWS_OPEN, ROWS_MIN = 8, 3
BUDGET = 1200
MARK = {"pass": "✓", "fail": "❌", "untested": "·"}


def now():
    return datetime.datetime.now().astimezone()


def title_of(line):
    return f"Train · {line}"


# ── the line ─────────────────────────────────────────────────────────────────────────────────────────

def line_lanes(line, cfg, regions=None):
    """[(role, lane)] for the line: qa, daily, prod from the map, then the China prod lane aligned with its prod lane
    (role cn) when the regions name one for this line."""
    lanes = [(role, (cfg.get("lanes") or {}).get(role)) for role in ROLES]
    lanes = [(r, l) for r, l in lanes if l]
    prod = dict(lanes).get("prod")
    for reg in (regions or {}).values():
        if reg.get("aligns_with") != prod:
            continue
        for lane, meta in (reg.get("lanes") or {}).items():
            if str(meta.get("line") or "") == str(line) and not meta.get("retiring"):
                lanes.append(("cn", lane))
    return lanes


def shown(lane):
    """The lane as every page and line names it: MediaHub's name first, the UR / J2N environment in brackets."""
    return B.lane_label(lane)


# ── one lane's rows ──────────────────────────────────────────────────────────────────────────────────

def left_verdict(why):
    """A state file's `why` for a row that left ("pass on build 75 (2026-10-28, QA report)") as (verdict, version,
    date, source); None for a withdrawal."""
    m = LEFT_RX.match(why or "")
    return (VERDICT_WORD.get(m.group(1), m.group(1)), m.group(2), m.group(3), m.group(4)) if m else None


def lane_rows(lane, state, mails, reports, issues):
    """{row id: row} for one lane: the state's rows and the rows that left it (the migration source), plus the rows of
    the builds the release mails carry that the state has not seen; each with its first arrival and its verdict. The
    lane-bound words (its report mails) are gathered here; the per-lane verdict is settled in `lane_verdicts`. A
    withdrawn ticket is left out. Returns (rows, the builds in order, the ids withdrawn)."""
    state = state or {}
    rows, withdrawn = {}, []
    for rid, r in (state.get("rows") or {}).items():
        rows[rid] = dict(r, _state_verdict=(r.get("verdict"), r.get("verdict_version"), r.get("verdict_date"), r.get("verdict_source"))
                         if r.get("verdict") and r.get("verdict") != "untested" else None)
    for rid, r in (state.get("left") or {}).items():
        if str(r.get("why") or "").startswith("withdrawn"):
            withdrawn.append(rid)
            continue
        rows.setdefault(rid, dict(r, _state_verdict=left_verdict(r.get("why"))))
    builds = {k: dict(v) for k, v in (state.get("builds") or {}).items()}
    floor = int(state.get("seed_after") or 0)
    for b in mails or []:
        fresh = TL.take_mail(builds, b, floor, mails)     # a build is its mail: a re-sent build is read again
        if fresh:
            TL.record_mail(builds, b)
        for beh in TL.behaviours(b):
            owner = TL.owner_of(beh["keys"], issues)
            text = " · ".join(beh["focus"]) or " · ".join(l["text"] for l in beh["log"])
            rid = owner or TL.nt_id(beh["log"][0]["text"] if beh["log"] else text)
            if rid in rows:                                 # every mail of the window, read or not: its keys join the row
                TL.merge_keys(rows[rid], beh["keys"])
                if fresh:
                    TL.merge_build(rows[rid], b)            # a re-send's rows merge with the first mail's
                continue
            if not fresh:
                continue
            rows[rid] = {"id": rid, "ticket": owner, "also": [k for k in beh["keys"] if k != owner],
                         "focus": " · ".join(beh["focus"]) or None, "log": [l["text"] for l in beh["log"]],
                         "layers": sorted({l["layer"] for l in beh["log"] if l["layer"]}), "first_build": b["build"], "first_at": b["at"],
                         "builds": [b["build"]], "last_build": b["build"], "last_at": b["at"], "_state_verdict": None}
    ordered = sorted(builds, key=lambda x: int(x))
    out = {}
    for rid, r in rows.items():
        t = r.get("ticket")
        issue = issues.get(t) if t else None
        f = (issue or {}).get("fields") or {}
        if t and issue:
            res = ((f.get("resolution") or {}).get("name") or "")
            if TL.WITHDRAWN_RX.search(res) or (f.get("status") or {}).get("name") in ("Cancelled",):
                withdrawn.append(rid)
                continue
        since, build = r.get("last_at") or r.get("first_at"), r.get("last_build") or r.get("first_build")
        found, heard = [], []                               # the lane-bound words: its QA report mails, and a summary report on a no-ticket row
        for k in [t, *(r.get("also") or [])] if t else []:
            found += TL.report_verdicts(reports, k, since, build)
            heard += TL.report_verdicts(reports, k, None, None)   # every report in the window, any build: the cell's history
        if not t:
            summ = [x for x in reports if x["summary"] and x["build"] and int(x["build"]) >= int(build)]
            if summ:
                found.append((summ[-1]["at"][:16], "n-a", f"build {summ[-1]['build']}", "QA summary report"))
        state_verdict = r.get("_state_verdict")
        verdict = (VERDICT_WORD.get(state_verdict[0], state_verdict[0]), *state_verdict[1:]) if state_verdict else None
        label = (builds.get(r.get("first_build")) or {}).get("label") or r.get("first_build")
        out[rid] = {"id": rid, "ticket": t, "also": r.get("also") or [], "focus": r.get("focus"), "log": r.get("log") or [],
                    "layers": r.get("layers") or [], "first_build": r.get("first_build"), "label": label, "first_at": r.get("first_at"),
                    "last_build": build, "last_at": since, "found": found, "heard": heard, "state_verdict": verdict,
                    "builds_after": len([x for x in ordered if int(x) > int(r.get("first_build") or 0)])}
    return out, ordered, withdrawn


def qa_only_rows(qa_lane, per_lane, reports, issues):
    """Rows for the keys the QA lane's report mails give a verdict (pass, fail, N/A) that no release mail named: a bug
    QA filed and closed or reopened mid-cycle, a customer task tested on the build it rode without a line in the build's
    mail. Each joins the QA lane's records marked `qa_only`, arrived on the build of the first report that judged it,
    its verdicts the reports'; a key whose parent has a row joins that row's `also` instead, and a withdrawn ticket is
    left out (returned). Only keys of a project the train's rows come from: QA's case ids share the key's shape. On
    2026-11-26 ten such keys in the 2.1 window (MH-4054 among them) had QA verdicts and no row."""
    recs, builds, withdrawn = per_lane[qa_lane]
    have = {k: (lane, rid) for lane, (rs, _, _) in per_lane.items() for rid, r in rs.items() for k in [r.get("ticket"), *(r.get("also") or [])] if k}
    projects = {k.split("-")[0] for k in have}
    gone = {w for _, _, ws in per_lane.values() for w in ws}
    out = []
    for rep in sorted(reports or [], key=lambda x: x.get("at") or ""):
        for k in B.keys_in(rep.get("text") or ""):
            if k in have or k in gone or k in out or k.split("-")[0] not in projects:
                continue
            if not any(v in ("pass", "fail", "n-a") for v, _ in TL.P.key_verdicts(rep.get("text") or "", k)):
                continue
            f = (issues.get(k) or {}).get("fields") or {}
            if TL.WITHDRAWN_RX.search(((f.get("resolution") or {}).get("name") or "")) or (f.get("status") or {}).get("name") == "Cancelled":
                out.append(k)
                continue
            parent = (f.get("parent") or {}).get("key")
            if parent in have:                              # a sub-task of a row: it rides as the row's also
                lane, rid = have[parent]
                TL.merge_keys(per_lane[lane][0][rid], [k])
                if lane == qa_lane:
                    r = recs[rid]
                    r["found"] = r["found"] + TL.report_verdicts(reports, k, r.get("last_at"), r.get("last_build"))
                    r["heard"] = r["heard"] + TL.report_verdicts(reports, k, None, None)
                have[k] = (lane, rid)
                continue
            build = rep.get("build")
            recs[k] = {"id": k, "ticket": k, "also": [], "focus": None, "log": [], "layers": [], "first_build": build,
                       "label": build or (rep.get("at") or "")[5:10], "first_at": rep.get("at"), "last_build": build, "last_at": rep.get("at"),
                       "found": TL.report_verdicts(reports, k, rep.get("at"), build), "heard": TL.report_verdicts(reports, k, None, None),
                       "state_verdict": None, "builds_after": len([x for x in builds if build and int(x) > int(build)]), "qa_only": True}
            have[k] = (qa_lane, k)
    return [k for k in out if k not in have]


def panel_lane(text):
    """The lane a pasted version panel (验证环境, ENV: …) in a comment proves, by the environment proof's parser; None
    when the comment pastes no panel or the panel names no lane."""
    if "ENV:" not in (text or ""):
        return None
    sys.path.insert(0, os.path.join(SKILLS, "promote"))
    import envproof as E  # noqa: E402  — the proof promote and qajira already use
    try:
        return (E.panel(text) or {}).get("lane")
    except (SystemExit, OSError, ValueError):
        return None


def comment_lanes(issue):
    """{comment time: {"words": [lanes], "panel": lane}} for the ticket's comments that name a lane in words (prod-3,
    CN Prod2, daily-wed, QA-AWS3) or paste a version panel whose ENV proves one, keyed the way `comment_verdicts`
    stamps its rows, so a verdict can be placed on the lane the comment names."""
    out = {}
    for c in (issue or {}).get("comments") or []:
        at = B.parse_ts(c.get("created") or "")
        text = J.body_text(c.get("body")) or ""
        lanes, panel = RC.lane_words(text), panel_lane(text)
        if at and (lanes or panel):
            out[at.astimezone().isoformat(timespec="minutes")] = {"words": lanes, "panel": panel}
    return out


def verdict_lane(lanes, recs, named=None):
    """The lane a QA person's comment judges: the QA lane, unless the comment proves another lane where the fix has a
    record — a pasted version panel whose ENV names it, or its own words naming it (and not the QA lane too). A
    version alone proves no lane: on 2026-11-25 QA's "2.2.148 build 212" on MH-4065 fell, by the version rules this
    replaces, to the nearest lane the fix had reached, and all nine daily and prod fails in the 2.1 train were QA
    comments placed that way. None when the fix has no record on the QA lane and the comment names no other."""
    qa_lane = dict(lanes).get("qa")
    named = named or {}
    if named.get("panel") in recs:
        return named["panel"]
    words = [lane for lane in named.get("words") or () if lane in recs]
    if words and qa_lane not in words:
        return words[0]
    return qa_lane if qa_lane in recs else None


def history_of(found, since):
    """A cell's verdict history: every word placed on the lane since the fix first arrived on the line's path, oldest
    first, one entry per word — {verdict, version, at, source}; so "passed before, fails now" can be computed from
    the cell. A word before the lane's own release mail named the fix counts: MH-4065 rode daily 2.1.99 on 2026-11-20
    and QA failed it on build 100 on 11-25, before build 101's mail named it on the QA lane."""
    out = []
    for at_, v, ver, src in sorted(set(x for x in found if x[0] >= (since or "")[:16])):
        out.append({"verdict": VERDICT_WORD.get(v, v), "version": ver, "at": at_[:16], "source": src})
    return out


def lane_verdicts(t, also, lanes, recs, said, issues, qa):
    """{lane: (verdict, version, date, source, history)}: each lane's latest word after the fix arrived there — its report mails
    (lane-bound), the release thread's replies (the QA lane), QA's ticket comments placed by `verdict_lane` — else the
    verdict the lane's state recorded, else untested. On daily and prod a recorded verdict counts only from a report
    mail: the per-lane lists took every QA comment after their own arrival, and a comment proves its lane only by its
    words or panel, which the train reads from the comment itself above."""
    found = {lane: list(r["found"]) for lane, r in recs.items()}
    since = min((r.get("first_at") or "" for r in recs.values()), default="")
    qa_lane = dict(lanes).get("qa")
    for k in [t, *also] if t else []:
        words = comment_lanes(issues.get(k))
        for at_, v, ver, src in TL.comment_verdicts(issues.get(k), qa, since):
            lane = verdict_lane(lanes, recs, words.get(at_))
            if lane:
                found[lane].append((at_, v, ver, src))
    if qa_lane in recs:
        for at_, k, v, ver, who, url in said or ():
            if k in ([t, *also] if t else [next(iter(recs.values()))["id"]]) and at_ >= (recs[qa_lane].get("last_at") or "")[:16]:
                found[qa_lane].append((at_, v, ver, f"release thread by {who}"))
    out = {}
    for lane, r in recs.items():
        history = history_of(found[lane] + list(r.get("heard") or []), since)
        mine = sorted(x for x in found[lane] if x[0] >= (r.get("last_at") or "")[:16])
        if mine:
            out[lane] = (VERDICT_WORD.get(mine[-1][1], mine[-1][1]), mine[-1][2], mine[-1][0][:10], mine[-1][3], history)
            continue
        sv = r.get("state_verdict")
        if sv and lane != qa_lane and not re.match(r"QA (summary )?report", str(sv[3] or "")):
            sv = None                                   # a QA comment the lane's list took after its own arrival: not proof of the lane
        if sv and not any(h["verdict"] == sv[0] and h["at"][:10] == (sv[2] or "") for h in history):
            history = sorted(history + [{"verdict": sv[0], "version": sv[1], "at": sv[2], "source": sv[3]}], key=lambda h: h["at"] or "")
        out[lane] = (*sv, history) if sv else ("untested", None, None, None, history)
    return out


# ── the train ────────────────────────────────────────────────────────────────────────────────────────

def incident_on(key, cell, incidents):
    """The open customer incident that names the key and was raised after the fix arrived on the lane, or None."""
    for i in incidents or []:
        text = f"{i.get('summary') or ''} {' '.join(i.get('labels') or [])}"
        raised = (i.get("created") or i.get("updated") or "")[:10]
        if key and key in B.keys_in(text) and (not cell.get("since") or raised >= cell["since"]):
            return i.get("key")
    return None


def row_of(rid, lanes, per_lane, said, issues, incidents, sprint, soon, qa, names=None):
    """One row of the train from its records on each lane."""
    recs = {lane: per_lane[lane][0][rid] for _, lane in lanes if rid in per_lane[lane][0]}
    first = next(iter(recs.values()))
    t = first["ticket"]
    qa_lane = dict(lanes).get("qa")
    verdicts = lane_verdicts(t, first["also"], lanes, recs, said, issues, qa)
    f = ((issues.get(t) if t else None) or {}).get("fields") or {}
    title = f.get("summary") or next((r["log"][0] for r in recs.values() if r["log"]), None) or next((r["focus"] for r in recs.values() if r["focus"]), "")
    layers = sorted({l for r in recs.values() for l in r["layers"]})
    pre = TL.PREFIX_RX.match(title or "")
    cells, arrived = {}, []
    for role, lane in lanes:
        r = recs.get(lane)
        if not r:
            continue
        v, ver, date, src, history = verdicts[lane]
        cells[lane] = {"arrived": r["label"], "since": (r["first_at"] or "")[:10] or None, "verdict": v, "version": ver, "source": src, "at": date,
                       "history": history}                   # the fields above are the latest word, as every reader takes them
        if role in ("prod", "cn") and v != "fail":
            inc = incident_on(t, cells[lane], incidents)
            if inc:
                raised = next((i.get("created") or i.get("updated") for i in incidents if i.get("key") == inc), "") or ""
                cells[lane].update(verdict="incident", source=f"incident {inc}", at=raised[:10] or None,
                                   history=history + [{"verdict": "incident", "version": None, "at": raised[:16] or None, "source": f"incident {inc}"}])
        if role in ROLE_RANK:
            arrived.append(role)
    position = max(arrived, key=ROLE_RANK.get, default="dev")
    for role, lane in lanes:                                  # a lane with no record below the position: its list began later
        if lane not in cells and 0 < ROLE_RANK.get(role, 0) < ROLE_RANK[position]:
            cells[lane] = {"arrived": None, "since": None, "verdict": "n/a", "version": None, "source": "no record: the lane's list began later", "at": None, "history": []}
    qa_cell = cells.get(qa_lane) if qa_lane else None
    judged = qa_cell if qa_cell and qa_cell.get("arrived") else cells.get(dict(lanes).get(position))
    pr = {"ticket": t, "verdict": (judged or {}).get("verdict") or "untested", "verdict_version": (judged or {}).get("version")}
    builds_after = recs[qa_lane]["builds_after"] if qa_lane in recs else 0
    priority, why = TL.priority(pr, f, sprint, builds_after, soon)
    regression = None
    if qa_cell and qa_cell.get("verdict") == "pass":
        for role, lane in lanes:
            c = cells.get(lane)
            if role != "qa" and c and c.get("verdict") in ("fail", "incident"):
                regression = {"lane": lane, "arrived": c["arrived"], "passed_on": qa_lane, "passed_build": qa_cell["arrived"]}
                priority, why = "P1", f"regression on {shown(lane)} {c['arrived']}, passed {shown(qa_lane)} on {qa_cell['arrived']}"
                break
    how = next((r["focus"] for r in recs.values() if r["focus"]), None) or (TL.acceptance(issues.get(t)) if t else None) or "steps unknown"
    change = next((r["log"][0] for r in recs.values() if r.get("log")), None)
    assignee = J.name_of(f.get("assignee")) if f.get("assignee") else None
    return {"id": rid, "key": t, "also": first["also"], "url": TL.JIRA_URL + t if t else None, "title": title,
            "layer": "+".join(layers) or (pre.group(1) if pre else "—"), "owner": (names or {}).get(assignee, assignee) if assignee else None,
            "status": (f.get("status") or {}).get("name") if t else None, "priority": priority, "priority_reason": why,
            "how_to_verify": how, "change": change, "auto": TL.auto_of(f"{title} {how}", bool(t)), "cells": cells, "position": position,
            "regression": bool(regression), "regression_on": regression, "flag": None if t else "no ticket",
            "qa_only": bool(first.get("qa_only"))}


def collect(line, cfg, states, mails, reports, said, issues, incidents, at, sprint=frozenset(), soon=False, regions=None,
            qa=None, lane_read=None, before=None, tested=None, names=None, gaps=(), rulings=()):
    """The train of one line. Pure: every source is given. states/mails/reports: {lane: …}; said: the release threads'
    verdicts; issues: {key: the ticket as `ela jira read --json` gives it}; incidents: the open incident rows, None
    when not read; lane_read/before: the newest saved lane reads for the versions row; rulings: the owner's rulings on
    your-call rows (fixes.read_rulings). Each row carries QA's word, its report line and its impact (fixes.enrich)."""
    lanes = line_lanes(line, cfg, regions)
    qa = qa if qa is not None else TL.qa_people()[0]
    per_lane = {lane: lane_rows(lane, (states or {}).get(lane), (mails or {}).get(lane), (reports or {}).get(lane) or [], issues)
                for role, lane in lanes}
    qa_lane = dict(lanes).get("qa")
    gone = qa_only_rows(qa_lane, per_lane, (reports or {}).get(qa_lane) or [], issues) if qa_lane in per_lane else []
    ids = []
    for _, lane in lanes:
        ids += [rid for rid in per_lane[lane][0] if rid not in ids]
    withdrawn = sorted({w for _, lane in lanes for w in per_lane[lane][2]} | set(gone))
    rows = [row_of(rid, lanes, per_lane, said, issues, incidents, sprint, soon, qa, names) for rid in ids if rid not in withdrawn]
    rows.sort(key=lambda r: (not r["regression"], r["priority"], ROLE_RANK[r["position"]], r["id"]))
    shown_lanes = [{"role": r, "lane": l, "shown": shown(l)} for r, l in lanes]
    FX.enrich(rows, shown_lanes, issues, (reports or {}).get(qa_lane) or [], qa, incidents, rulings, TL.P.key_verdicts)
    missing = report_parity({lane: (reports or {}).get(lane) for _, lane in lanes}, rows, withdrawn)
    gaps = list(gaps) + ([parity_gap(missing)] if missing else [])
    return {"line": str(line), "at": at.isoformat(timespec="minutes"), "lanes": shown_lanes,
            "builds": {lane: per_lane[lane][1] for _, lane in lanes}, "rows": rows, "withdrawn": withdrawn,
            "versions": versions_row(lanes, lane_read or [], before, tested or {}), "counts": counts(rows, lanes), "gaps": gaps, "report_keys_missing": missing,
            "sources": {"states": sorted(l for l in (states or {}) if (states[l] or {}).get("rows")), "mails": sorted(l for l in (mails or {}) if mails[l]),
                        "reports": sorted(l for l in (reports or {}) if reports[l]), "thread_replies": len(said or ()),
                        "incidents": incidents is not None, "lane_read": bool(lane_read)}}


def report_parity(reports, rows, withdrawn=()):
    """The keys the window's QA report mails give a verdict (pass, fail, N/A — the report reader's own lines, so a bug
    QA filed under "new issues" or a test-case id is not one) that the train has no row for, as a row's key or an
    `also`, in a project the train's rows come from; sorted, a withdrawn row counting as present. On 2026-11-24 QA reported MH-4097 on a re-sent build the
    train never read."""
    named = {k for rs in (reports or {}).values() for r in rs or [] for k in B.keys_in(r.get("text") or "")
             if any(v in ("pass", "fail", "n-a") for v, _ in TL.P.key_verdicts(r.get("text") or "", k))}
    have = {k for r in rows for k in [r.get("key"), *(r.get("also") or [])] if k} | set(withdrawn)
    projects = {k.split("-")[0] for k in have}            # QA's case ids (CON-14, SW-10) share the key's shape, not a project
    return sorted({k for k in named - have if k.split("-")[0] in projects}, key=lambda k: (k.split("-")[0], int(k.split("-")[1]) if k.split("-")[1].isdigit() else 0))


def parity_gap(missing):
    """The page's line for report keys with no row; None when every key has one."""
    if not missing:
        return None
    return f"{len(missing)} key{'s' if len(missing) != 1 else ''} with a verdict in the window's QA report mails and no row in the train: " + ", ".join(missing)


def counts(rows, lanes):
    """Per lane: arrived, and the verdict counts; for the QA lane also `open` (no pass yet) and the P1 among them."""
    out = {}
    for role, lane in lanes:
        cells = [r["cells"][lane] for r in rows if r["cells"].get(lane, {}).get("arrived")]
        c = {"arrived": len(cells), **{v: sum(x["verdict"] == v for x in cells) for v in VERDICTS}}
        if role == "qa":
            open_ = [r for r in rows if r["cells"].get(lane, {}).get("arrived") and r["cells"][lane]["verdict"] not in ("pass", "n/a")]
            c["open"], c["p1"] = len(open_), sum(r["priority"] == "P1" for r in open_)
        out[lane] = c
    return out


def versions_row(lanes, rows, before, tested):
    """The lanes' versions for the app's two deliverables, cell by cell the lanes page's way (the brief's matrix cell)."""
    if not rows:
        return []
    out = []
    for role, lane in lanes:
        cells = {}
        for svc in RC.TRAIN_SERVICES:
            try:
                cells[svc] = B.matrix_cell(svc, lane, rows, before, tested, {})["text"]
            except (KeyError, TypeError, ValueError):
                cells[svc] = "—"
        out.append({"role": role, "lane": lane, "shown": shown(lane), "cells": cells})
    return out


# ── views ────────────────────────────────────────────────────────────────────────────────────────────

def qa_view(res):
    """The QA lane's test list as the train sees it: {row id: verdict} for the rows whose QA cell has no pass yet. A
    row named by QA only is left out: the test list reads release mails, so it never held one."""
    qa_lane = next((l["lane"] for l in res["lanes"] if l["role"] == "qa"), None)
    return {r["id"]: r["cells"][qa_lane]["verdict"] for r in res["rows"] if qa_lane and not r.get("qa_only")
            and r["cells"].get(qa_lane, {}).get("arrived") and r["cells"][qa_lane]["verdict"] not in ("pass", "n/a")}


def parity(res, state):
    """The train's QA view against a test-list state's open rows: {missing, extra, differ: {id: (list, train)}}."""
    mine = qa_view(res)
    theirs = {rid: VERDICT_WORD.get(r.get("verdict") or "untested", r.get("verdict") or "untested") for rid, r in ((state or {}).get("rows") or {}).items()}
    return {"missing": sorted(set(theirs) - set(mine)), "extra": sorted(set(mine) - set(theirs)),
            "differ": {k: (theirs[k], mine[k]) for k in sorted(set(mine) & set(theirs)) if mine[k] != theirs[k]},
            "list_rows": len(theirs), "train_rows": len(mine)}


def equal(p):
    return not (p["missing"] or p["extra"] or p["differ"])


def parity_lines(p, qa_lane):
    L = [f"parity · {shown(qa_lane)}: test list {p['list_rows']} open rows, train {p['train_rows']}"]
    L += [f"  missing from the train: {k}" for k in p["missing"]]
    L += [f"  extra in the train: {k}" for k in p["extra"]]
    L += [f"  verdict differs: {k} list {a} · train {b}" for k, (a, b) in p["differ"].items()]
    L.append("  equal" if equal(p) else "  not equal")
    return L


# ── the page ─────────────────────────────────────────────────────────────────────────────────────────

def cell_text(c):
    if not c or not c.get("arrived"):
        return "n/a" if c and c.get("verdict") == "n/a" else "—"
    if c["verdict"] == "incident":
        return "⚠ incident"
    return f"{MARK.get(c['verdict'], c['verdict'])} {c['arrived']}"


def counts_line(res):
    parts = []
    for ln in res["lanes"]:
        c = res["counts"].get(ln["lane"]) or {}
        if ln["role"] == "qa":
            parts.append(f"QA {c.get('open', 0)} open · {c.get('p1', 0)} P1")
        elif ln["role"] == "daily":
            parts.append(f"daily {c.get('arrived', 0)} arrived, {c.get('fail', 0)} fail")
        else:
            parts.append(f"{'prod' if ln['role'] == 'prod' else ln['shown']} {c.get('arrived', 0)} arrived, {c.get('incident', 0)} incident"
                         + (f", {c['fail']} fail" if c.get("fail") else ""))
    return " · ".join(parts)


def row_line(r, lanes):
    p = ("↩ " if r["regression"] else "") + r["priority"]
    ticket = ("◇ " if r.get("qa_only") else "") + (TL.link({"ticket": r["key"], "url": r["url"], "also": r["also"]}) if r["key"] else "no ticket")
    cells = " | ".join(cell_text(r["cells"].get(l)) for l in lanes)
    return f"| {p} | {ticket} | {TL.short(r['title'])} | {TL.page_name(r['owner']) or '—'} | {cells} | {r['position']} |"


def render_block(res, rows_open=ROWS_OPEN):
    """The line's block: the counts line, the versions row, the rows table folded after `rows_open`, the no-ticket
    fold. Phase 2 places this block in lanes.md per line; the page wraps it."""
    lanes = [l["lane"] for l in res["lanes"]]
    L = [f"*{counts_line(res)}*", ""]
    if res.get("versions"):
        L += RC.train_lines(res["versions"]) + [""]
    head = ["| P | ticket | title | owner | " + " | ".join(l["shown"] for l in res["lanes"]) + " | position |", "|---" * (5 + len(lanes)) + "|"]
    keyed = [row_line(r, lanes) for r in res["rows"] if r["key"]]
    L += RC.folded_rows(head, keyed, rows_open) if keyed else ["*No ticketed row rides this line yet.*"]
    nt = [r for r in res["rows"] if not r["key"]]
    if nt:
        L += ["", f"> [!note]- No ticket · {len(nt)}"] + [f"> - {TL.short(r['title'], 90)} — " + " · ".join(f"{shown(l)} {cell_text(r['cells'].get(l))}" for l in lanes if r["cells"].get(l))
                                                           + f" · {r['position']}" for r in nt]
    return L


def render_page(res, rows_open=ROWS_OPEN, budget=BUDGET):
    at = res.get("at") or ""
    qa_lane = next((l for l in res["lanes"] if l["role"] == "qa"), None)
    path = " → ".join(l["shown"] for l in res["lanes"] if l["role"] in ROLES) + "".join(f" · {l['shown']}" for l in res["lanes"] if l["role"] == "cn")
    L = [f"# {title_of(res['line'])}", "", f"*{at[:10]} {at[11:16]} · line {res['line']} · {path} · {len(res['rows'])} rows*",
         f"*{B.F.read_at_line(res.get('read_at'))}*", ""]
    L += render_block(res, rows_open)
    legend = ["", "*✓ pass · ❌ fail · `·` arrived, untested · — not arrived · ⚠ incident · n/a no record (the lane's list began later) · "
              "↩ regression: failed after a pass on QA, P1 · ◇ named by QA only: a QA report judged it, no release mail named it · "
              "position: the furthest lane the fix reached.*"]
    links = [f"[[lanes/test-list-{qa_lane['lane']}|Test list · {qa_lane['shown']}]]"] if qa_lane else []
    links.append("[[lanes|The lanes]]")
    legend.append("*" + " · ".join(links) + f". Generated by `ela train --line {res['line']} --page`.*")
    gaps = res.get("gaps") or []
    if gaps:
        legend += ["", "*Not read: " + "; ".join(g[:160] for g in gaps) + ".*"]
    page = "\n".join(L + legend) + "\n"
    if rows_open > ROWS_MIN and RC.open_units(page) > budget:
        return render_page(res, rows_open - 1, budget)
    return page


# ── main ─────────────────────────────────────────────────────────────────────────────────────────────

def plain_gaps(errs):
    """The prefetch's errors as lines for the page, never a raw record. The keys that could not be read are named
    when there are one or two; from three up they are counted by project, since an unreadable ticket has no title to
    write beside its key and each already stands on its own row of the table."""
    unread = [m.group(1) for m in (re.match(r"jira read (\S+):", g) for g in errs) if m]
    rest = [re.sub(r"\{.*$", "", g).strip(" :") for g in errs if not re.match(r"jira read \S+:", g)]
    by = {}
    for k in unread:
        by[k.split("-")[0]] = by.get(k.split("-")[0], 0) + 1
    which = ", ".join(unread) if len(unread) < 3 else ", ".join(f"{n} in {p}" for p, n in by.items()) + ", each on its row above"
    return ([f"{len(unread)} ticket{'s' if len(unread) != 1 else ''} not readable (another project, or no permission): {which}"] if unread else []) + rest


def train_path(s, line):
    return os.path.join(TL.reports_root(s), "train", f"{line}.json")


def read_train(s, line):
    """The written train of a line, or None: the file phase 2's readers (testlist, promote, recent) import."""
    try:
        return json.load(open(train_path(s, line), encoding="utf-8"))
    except (OSError, ValueError):
        return None


def answer_main(argv):
    """`train.py answer impact:<KEY> A|B [--why TEXT]`: his letter on a your-call row, kept with its kind (fixes.answer).
    The row is looked up in the written trains. Exit 2 for a letter or an ask no written train holds."""
    ap = argparse.ArgumentParser(prog="ela train answer", description="rule on a your-call row: A agrees with ela's leaning, B rules the other way")
    ap.add_argument("id", help="the ask's id, impact:<KEY>")
    ap.add_argument("letter", help="A or B")
    ap.add_argument("--why", help="the cause, kept with the ruling as the precedent's reason")
    a = ap.parse_args(argv)
    s = TL.site()
    reports = TL.reports_root(s)
    for train in trains_on_disk(s):
        try:
            rec = FX.answer(reports, a.id, a.letter, train, a.why)
        except KeyError:
            continue
        except ValueError:
            print(f"letter {a.letter!r}: A or B", file=sys.stderr)
            sys.exit(EX_USAGE)
        print(f"{a.id}: ruled {rec['ruled']} ({rec['kind']})" + ("" if rec["cause"] else "; no cause given, kept as waiting for one"))
        return
    print(f"{a.id}: no written train holds this your-call row", file=sys.stderr)
    sys.exit(EX_USAGE)


def trains_on_disk(s):
    """Every written train, [train]."""
    d = os.path.join(TL.reports_root(s), "train")
    out = []
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if f.endswith(".json"):
            t = read_train(s, f[:-5])
            if t:
                out.append(t)
    return out


def main():
    rest = sys.argv[3:] if sys.argv[1:2] == ["--env-file"] else sys.argv[1:]   # `ela` puts its env file first
    if rest[:1] == ["answer"]:
        return answer_main(rest[1:])
    ap = argparse.ArgumentParser(description="the train: one object per release line, one row per fix with a cell per lane")
    ap.add_argument("--env-file", help="ela's env file")
    ap.add_argument("--line", required=True, help="the release line (2.1)")
    ap.add_argument("--days", type=int, default=21, help="how far back to read the release mails (default 21)")
    ap.add_argument("--json", action="store_true", help="the train instead of the page")
    ap.add_argument("--write", action="store_true", help="keep the train as <reports>/train/<line>.json")
    ap.add_argument("--page", action="store_true", help="also write <reports>/lanes/train-<line>.md")
    ap.add_argument("--parity", action="store_true", help="compare the QA view with the lane's test-list state; exit 1 when they differ")
    a = ap.parse_args()
    s = TL.site()
    env = ["--env-file", a.env_file] if a.env_file else []
    lines = R.rmap("lines") or {}
    line = str(a.line)
    if line not in lines or not (lines[line].get("lanes") or {}).get("qa"):
        print(f"unknown release line {a.line!r} or no lanes for it; known: {', '.join(k for k, v in lines.items() if v.get('lanes'))}", file=sys.stderr)
        sys.exit(EX_USAGE)
    cfg, regions = lines[line], R.rmap("regions") or {}
    lanes = line_lanes(line, cfg, regions)
    at, gaps = now(), []
    try:
        by_lane = TL.release_mails(env, a.days)
    except (B.LaneError, TL.subprocess.TimeoutExpired, ValueError) as x:
        print(f"release mails not read: {str(x)[:200]}", file=sys.stderr)
        sys.exit(EX_REMOTE)
    try:
        reports = TL.report_mails(env, a.days)
    except (B.LaneError, TL.subprocess.TimeoutExpired, ValueError) as x:
        reports = {}
        gaps.append(f"QA report mails: {str(x)[:200]}")
    mails = {lane: (by_lane.get(lane) or {}).get("mails") or [] for _, lane in lanes}
    states = {lane: TL.load_state(TL.state_path(s, lane), lane) for _, lane in lanes}
    keys = {k for lane in mails for b in mails[lane] for l in b["log"] + b["focus"] for k in l["keys"]}
    for st in states.values():
        keys |= {k for part in ("rows", "left") for r in (st.get(part) or {}).values() for k in [r.get("ticket"), *(r.get("also") or [])] if k}
    projects = {k.split("-")[0] for k in keys}                # QA's case ids (CON-14) share the key's shape, not a project
    keys |= {k for r in reports.get(dict(lanes)["qa"]) or [] for k in B.keys_in(r.get("text") or "") if k.split("-")[0] in projects}
    cache, errs = {}, []
    TL.prefetch(env, sorted(keys), cache, errs)
    gaps += plain_gaps(errs)
    errs = []
    msgs = B.slack_rows(env, B.QA_RELEASE, (at - datetime.timedelta(days=7)).date().isoformat(), errs)
    gaps += [f"{g['source']}: {str(g['error']).split('{')[0].strip()}" for g in errs]
    said = TL.thread_verdicts(msgs, TL.qa_people()[0])
    try:
        incidents = B.lane_incidents(a.env_file, 100, at)["rows"]
    except (B.LaneError, ValueError, KeyError) as x:
        incidents = None
        gaps.append(f"incidents: {str(x).split('{')[0].strip() or 'not read'}")
    runner = os.path.join(s.get("runtime") or os.path.join(s.get("projects", ""), ".ela"), "runner")
    reads = B.lane_reads(runner)
    rows = reads[-1][2] if reads else []
    before = reads[-2][2] if len(reads) > 1 else None
    try:
        tested = json.load(open(os.path.join(runner, "qa-tested.json"), encoding="utf-8"))
    except (OSError, ValueError):
        tested = {}
    res = collect(line, cfg, states, mails, {l: reports.get(l) or [] for _, l in lanes}, said, cache, incidents, at,
                  TL.sprint_keys(s), TL.departs_soon(s, at), regions, lane_read=rows, before=before, tested=tested, gaps=gaps,
                  rulings=FX.read_rulings(TL.reports_root(s)))
    res["read_at"] = B.facts_read_at()
    if a.parity:
        qa_lane = dict(lanes)["qa"]
        p = parity(res, states[qa_lane])
        print("\n".join(parity_lines(p, qa_lane)))
        sys.exit(0 if equal(p) else EX_PARITY)
    if a.write:
        path = train_path(s, line)
        TL.save(path, json.dumps(res, ensure_ascii=False, indent=1))
        res["written"] = path
    if a.page:
        page = os.path.join(TL.reports_root(s), "lanes", f"train-{line}.md")
        TL.save(page, render_page(res))
        res["page"] = page
    if a.json:
        print(json.dumps(res, ensure_ascii=False))
    elif a.write or a.page:
        print(f"train {line}: {len(res['rows'])} rows · {counts_line(res)}" + "".join(f" → {res[k]}" for k in ("written", "page") if k in res))
    else:
        print(render_page(res), end="")


if __name__ == "__main__":
    main()
