#!/usr/bin/env python3
"""The evidence chain behind a ticket's Fixed In value, and the value that chain supports — draft only; no Jira write.
L1: subcommands, --json, stdlib only. Every source is read now: the ticket, the commits naming its key, the Jenkins
builds carrying those commits, the lanes running those builds, and QA's own words about the key.

  draft <KEY> [<KEY>…] [--jql '<JQL>'] [--since YYYY-MM-DD]
        ticket  summary, status, labels, the current Fixed In (map/release.yaml fixed_in.field)
        commits `git log --all --grep=<KEY>` and remote branches named for the key, in every checkout of a repository
                map/release.yaml `repos` names — the checkout the survey cache locates; a missing one is a gap
        builds  the first Jenkins build of the repository's job (map/release.yaml `jobs`) whose sha is the commit or
                descends from it in that checkout
        lanes   qa-*, daily-*, stage and prod-N lanes running a version at or above the carrying build (version_rules);
                a prod read without a session is a gap, never a guess
        evidence QA verdicts over the key's Jira comments, mail and Slack since --since (default 30 days), one line each
        draft   `<slug>@<version>` per service, beside the current value: same · differs · empty

--jql runs the same for every key the query returns. Nothing is written anywhere: the Fixed In field is set by a
person, from this draft, in Jira. Checkouts are read as they are on disk; `ela sync <repo>` brings one up to date.
Exit codes: 0 ok · 2 usage · 3 a key is not in Jira · 5 remote error.
"""
import argparse, datetime, json, os, re, signal, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SKILLS, "release"))
sys.path.insert(0, os.path.join(SKILLS, "promote"))
import promote as P  # noqa: E402 — Fixed In grammar, QA-evidence reading, version comparison
R = P.R              # the release module promote already loaded: the release map, parse_version, vlabel

EX_USAGE, EX_NOTFOUND, EX_REMOTE = 2, 3, 5
KEY_SHAPE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
CACHE = os.path.expanduser("~/.claude/ela/map/host.json")
DOCKER_GAP = "docker: no job map — value cannot be derived"


def key_rx(key):
    """The key as a whole token: MH-123 does not match inside MH-1234."""
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(key) + r"(?!\d)", re.I)


# ── commits ───────────────────────────────────────────────────────────────────

def parse_log(out):
    """`%H%x09%ad%x09%s` lines → [{sha, date, subject}], first occurrence of a sha kept."""
    rows, seen = [], set()
    for ln in (out or "").splitlines():
        parts = ln.split("\t", 2)
        if len(parts) < 3 or not re.fullmatch(r"[0-9a-f]{40}", parts[0]) or parts[0] in seen:
            continue
        seen.add(parts[0])
        rows.append({"sha": parts[0], "date": parts[1], "subject": parts[2]})
    return rows


def checkout_of(rel, repos_cache):
    """The survey cache's checkout for a release.yaml `repos` value (<alias>/<remote path>); None when absent."""
    code = R.site().get("code") or ""
    target = os.path.join(code, (R.site().get("dir_names") or {}).get(rel, rel))
    for r in repos_cache:
        if r.get("path") == target or (r.get("place") == target and r.get("in_place")):
            return r["path"]
    return None


def survey_repos():
    try:
        return json.load(open(CACHE)).get("repos") or []
    except (OSError, ValueError):
        return None


def commits_for(key, path):
    """Commits whose message names the key, and the tips of remote branches named for it."""
    rc, out, err = P.git(path, "log", "--all", f"--grep={key}", "--format=%H%x09%ad%x09%s", "--date=short")
    if rc != 0:
        return None, "git log failed: " + err.strip()[:120]
    rows = parse_log(out)
    if rows:                       # --grep is a substring match; keep the commits that name this key as a token
        rc, bodies, _ = P.git(path, "log", "--no-walk", "--format=%H%x1f%B%x1e", *[r["sha"] for r in rows])
        named = {b.split("\x1f", 1)[0].strip() for b in bodies.split("\x1e") if "\x1f" in b and key_rx(key).search(b.split("\x1f", 1)[1])}
        rows = [r for r in rows if r["sha"] in named] if rc == 0 else rows
    for r in rows:
        r["via"] = "message"
    rc, out, _ = P.git(path, "branch", "-r", "--list", f"*{key.lower()}*")
    for br in (b.strip() for b in out.splitlines() if b.strip() and "->" not in b):
        if not key_rx(key).search(br):
            continue
        rc, tip, _ = P.git(path, "log", "-1", "--format=%H%x09%ad%x09%s", "--date=short", br)
        for t in parse_log(tip):
            hit = next((r for r in rows if r["sha"] == t["sha"]), None)
            if hit:
                hit.setdefault("branches", []).append(br)
            else:
                rows.append(dict(t, via="branch", branches=[br]))
    return rows, None


# ── builds ────────────────────────────────────────────────────────────────────

def build_parsed(b):
    return R.parse_version(f"{b['version']}+{b['build']}") if b.get("version") and b.get("build") is not None else None


def carrying_build(sha, builds, is_ancestor):
    """The earliest build whose sha is the commit or descends from it; a successful build is preferred."""
    ordered = sorted((b for b in builds if b.get("sha_full") and b.get("number") is not None), key=lambda b: b["number"])
    for want_success in (True, False):
        for b in ordered:
            if want_success and b.get("result") != "SUCCESS":
                continue
            if b["sha_full"] == sha or is_ancestor(sha, b["sha_full"]):
                return b
    return None


def draft_values(slug, carriers):
    """Carrying builds of one service → Fixed In entries: the highest build per M.m series (release.yaml
    fixed_in.same_slug_twice), written in the canonical M.m.p+BUILD form."""
    best = {}
    for b in carriers:
        pv = build_parsed(b)
        if not pv:
            continue
        series = pv[:2]
        if series not in best or pv > best[series]:
            best[series] = pv
    return [{"service": slug, "value": f"{slug}@{R.vlabel(pv)}"} for _, pv in sorted(best.items())]


def compare(current_text, drafts):
    """same · differs · empty — the current app-layer entries against the draft; docker entries are not derivable."""
    if not (current_text or "").strip():
        return "empty"
    cur = set()
    for e in P.parse_fixed_in(current_text):
        if not e["docker"]:
            cur.add(f"{e['slug']}@{R.vlabel(e['parsed']) if e['parsed'] else e['version']}")
    return "same" if cur == {d["value"] for d in drafts} else "differs"


# ── lanes ─────────────────────────────────────────────────────────────────────

_ENVS = {}
def lane_rows(env_file, slug, host):
    """(rows, gap) of `release.py envs <slug> --host <host>`; exit 4 is a named gap, never a guess."""
    if (slug, host) not in _ENVS:
        rc, out, err = P.run(["python3", os.path.join(SKILLS, "release", "release.py"), "--env-file", env_file or "",
                              "envs", slug, "--host", host, "--json"], 120)
        if rc == 0:
            try:
                _ENVS[(slug, host)] = ([r for r in json.loads(out).get("rows") or [] if r.get("service") == slug], None)
            except ValueError:
                _ENVS[(slug, host)] = ([], f"{host} lanes: output not json")
        elif rc == 3:
            _ENVS[(slug, host)] = ([], None)
        elif rc == 4:
            _ENVS[(slug, host)] = ([], f"{host} lanes unread — no session (ela login {'tvu' if host == 'prod' else 'qa'})")
        else:
            _ENVS[(slug, host)] = ([], f"{host} lanes unread (exit {rc}): {(err or out).strip()[:120]}")
    return _ENVS[(slug, host)]


def lanes_running(slug, rows, carrier_pv):
    """Lanes whose version is at or above the carrying build, compared only inside one M.m series."""
    out, other = [], []
    for r in rows:
        pv = R.parse_version(r.get("version"))
        if not r.get("lane") or not pv:
            continue
        if pv[:2] != carrier_pv[:2]:
            other.append(r["lane"]); continue
        if P.cmp_versions(slug, pv, carrier_pv) >= 0:
            out.append({"lane": r["lane"], "version": R.vlabel(pv)})
    return out, other


# ── the chain for one key ─────────────────────────────────────────────────────

def read_ticket(env_file, key):
    rc, out, err = P.run(["python3", os.path.join(SKILLS, "jira", "jira.py"), "--env-file", env_file or "",
                          "read", key, "--json", "--deep"], 60)
    if rc == 0:
        try:
            return json.loads(out), None
        except ValueError:
            return None, EX_REMOTE
    return None, EX_NOTFOUND if re.search(r"HTTP 404|does not exist", err or "") else EX_REMOTE


def chain(a, key, repos_cache, builds_cache):
    fid = (R.rmap("fixed_in") or {}).get("field") or "customfield_11252"
    rec = {"key": key, "summary": None, "status": None, "labels": [], "current": "", "compare": None,
           "draft": [], "commits": [], "builds": [], "lanes": [], "evidence": None, "gaps": [], "comments": []}
    d, code = read_ticket(a.env_file, key)
    if not d:
        rec["gaps"].append("not in Jira" if code == EX_NOTFOUND else "Jira unreadable"); rec["exit"] = code
        return rec
    f = d.get("fields") or {}
    raw = f.get(fid)
    rec.update(summary=f.get("summary"), status=(f.get("status") or {}).get("name"), labels=f.get("labels") or [],
               current=(P.adf_text(raw).strip() if raw else ""), url=d.get("url"))
    rec["comments"] = d.get("comments") or []
    for e in P.parse_fixed_in(rec["current"]):
        if e["docker"]:
            rec["gaps"].append(f"{e['slug']}@{e['version']}: {DOCKER_GAP}")
    jobs = {v: k for k, v in (R.rmap("jobs") or {}).items()}          # service → job
    carriers = {}
    for slug, rel in (R.rmap("repos") or {}).items():
        path = checkout_of(rel, repos_cache or [])
        if not path:
            rec["gaps"].append(f"{slug}: no checkout of {rel} in the survey cache (ela clone {rel})"); continue
        rows, err = commits_for(key, path)
        if err:
            rec["gaps"].append(f"{slug}: {err}"); continue
        if not rows:
            continue
        for c in rows:
            rec["commits"].append(dict(c, service=slug, repo=rel))
        job = jobs.get(slug)
        if not job:
            rec["gaps"].append(f"{slug}: no Jenkins job in map/release.yaml jobs"); continue
        if job not in builds_cache:
            P.say(f"jenkins {job}")
            ok, bd, berr = P.l1("release", "builds", job, "--limit", "80", env_file=a.env_file, timeout=60)
            builds_cache[job] = ((bd or {}).get("builds"), "") if ok else (None, berr)
        builds, berr = builds_cache[job]
        if builds is None:
            rec["gaps"].append(f"{slug}: Jenkins {job} unreadable: {berr[:120]}"); continue
        is_anc = lambda s, b, p=path: P.git(p, "merge-base", "--is-ancestor", s, b)[0] == 0
        for c in rows:
            b = carrying_build(c["sha"], builds, is_anc)
            if not b:
                rec["gaps"].append(f"{slug}: {c['sha'][:8]} is in no build of {job}'s last {len(builds)} (not built yet, or older than the window)"); continue
            rec["builds"].append({"service": slug, "sha": c["sha"], "job": job, "number": b["number"],
                                  "version": R.vlabel(build_parsed(b)) if build_parsed(b) else b.get("version"), "result": b.get("result")})
            carriers.setdefault(slug, []).append(b)
    for slug, bs in carriers.items():
        vals = draft_values(slug, bs)
        rec["draft"] += vals
        for v in vals:
            pv = R.parse_version(v["value"].split("@", 1)[1])
            for host in ("qa", "prod"):
                rows, gap = lane_rows(a.env_file, slug, host)
                if gap:
                    if gap not in rec["gaps"]:
                        rec["gaps"].append(gap)
                    continue
                running, other = lanes_running(slug, rows, pv)
                for x in running:
                    rec["lanes"].append(dict(x, service=slug, host=host, carries=v["value"]))
                if other:
                    rec["gaps"].append(f"{slug} on {host}: {', '.join(sorted(set(other)))} run another M.m series — not compared")
    rec["compare"] = compare(rec["current"], rec["draft"])
    return rec


def attach_evidence(a, recs):
    """Promote's QA-evidence reading, once for every key, over its comments, mail and Slack."""
    roster = P.load_roster()
    tickets = {"tickets": []}
    for r in recs:
        if r.get("exit"):
            continue
        cs = []
        for c in r.pop("comments", []):
            who = c.get("author") if isinstance(c.get("author"), str) else (c.get("author") or {}).get("displayName")
            cs.append({"who": who, "area": P.person_area(roster, who), "when": (c.get("created") or "")[:10], "text": P.adf_text(c.get("body")).strip()})
        tickets["tickets"].append({"key": r["key"], "exists": True, "comments": cs})
    for r in recs:
        r.pop("comments", None)
    if not tickets["tickets"]:
        return
    gaps = []
    ev = P.collect_evidence(a, tickets, {"services": []}, gaps, a.since)
    for r in recs:
        k = (ev.get("keys") or {}).get(r["key"])
        if k is None:
            continue
        items = sorted(k["items"], key=lambda i: i.get("when") or "")
        r["evidence"] = {"verdict": k["verdict"], "since": ev.get("since"),
                         "items": [{"source": i["source"], "date": (i.get("when") or "")[:10], "verdict": i["verdict"],
                                    "line": (i.get("quote") or "").splitlines()[0][:140] if i.get("quote") else ""} for i in items]}
        for g in gaps:
            r["gaps"].append(f"evidence: {g['kind']}")


# ── output ────────────────────────────────────────────────────────────────────

def print_text(recs):
    for r in recs:
        print(f"## {r['key']}  [{r['status'] or '?'}]  {(r['summary'] or '')[:90]}")
        print(f"   current   {r['current'] or '—'}")
        print(f"   draft     {'; '.join(d['value'] for d in r['draft']) or '—'}   ({r['compare'] or 'unread'})")
        for c in r["commits"]:
            via = f"  [branch {', '.join(c['branches'])}]" if c.get("branches") else ""
            print(f"   commit    {c['service']:<24} {c['sha'][:8]} {c['date']} {c['subject'][:80]}{via}")
        for b in r["builds"]:
            print(f"   build     {b['service']:<24} {b['job']} #{b['number']} {b['version']} {b['result'] or ''}  ← {b['sha'][:8]}")
        for x in r["lanes"]:
            print(f"   lane      {x['service']:<24} {x['lane']:<12} {x['version']}  ({x['host']})")
        ev = r.get("evidence")
        if ev:
            print(f"   evidence  {ev['verdict']} since {ev['since']} — {len(ev['items'])} item(s)")
            for i in ev["items"]:
                print(f"             {i['source']:<5} {i['date']} {i['verdict']:<14} {i['line'][:110]}")
        for g in r["gaps"]:
            print(f"   ! {g}")
        print()


def cmd_draft(a):
    keys = [k.upper() for k in a.keys]
    if a.jql:
        ok, d, err = P.l1("jira", "jql", a.jql, "--limit", "300", env_file=a.env_file, timeout=120)
        if not ok:
            print(f"jql failed: {err}", file=sys.stderr); sys.exit(EX_REMOTE)
        keys += [i["key"] for i in d.get("issues") or [] if i.get("key") and i["key"] not in keys]
    bad = [k for k in keys if not KEY_SHAPE.match(k)]
    if not keys or bad:
        print(f"draft needs a ticket key or --jql{'; not a key: ' + ', '.join(bad) if bad else ''}", file=sys.stderr); sys.exit(EX_USAGE)
    if not a.since:
        a.since = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    repos_cache = survey_repos()
    recs, builds_cache = [], {}
    for k in keys:
        P.say(f"{k}: ticket, commits, builds, lanes")
        r = chain(a, k, repos_cache, builds_cache)
        if repos_cache is None:
            r["gaps"].append(f"no survey cache at {CACHE} — run: ela survey")
        recs.append(r)
    attach_evidence(a, recs)
    if a.json:
        print(json.dumps({"keys": [{f: r.get(f) for f in ("key", "summary", "status", "labels", "current", "compare", "draft",
                                                          "commits", "builds", "lanes", "evidence", "gaps")} for r in recs]}, ensure_ascii=False))
    else:
        print_text(recs)
    codes = {r.get("exit") for r in recs}
    if EX_REMOTE in codes:
        sys.exit(EX_REMOTE)
    if EX_NOTFOUND in codes:
        sys.exit(EX_NOTFOUND)


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("draft", help="the Fixed In a ticket's evidence supports, beside the current value — draft only; no Jira write")
    p.add_argument("keys", nargs="*", help="ticket keys (MH-3568)")
    p.add_argument("--jql", help="also every key this query returns (up to 300)")
    p.add_argument("--since", help="evidence window start, YYYY-MM-DD (default 30 days ago)")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.since and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.since):
        print("--since takes YYYY-MM-DD", file=sys.stderr); sys.exit(EX_USAGE)
    {"draft": cmd_draft}[a.cmd](a)


if __name__ == "__main__":
    main()
