#!/usr/bin/env python3
"""The evidence chain behind a ticket's Fixed In value, and the value that chain supports — draft only; no Jira write.
L1: subcommands, --json, stdlib only. Every source is read now: the ticket, the commits naming its key, the Jenkins
builds carrying those commits, the lanes running those builds, and QA's own words about the key.

  draft <KEY> [<KEY>…] [--jql '<JQL>'] [--since YYYY-MM-DD] [--evidence] [--author A] [--path P] [--thread URL]
  declared <KEY> [<KEY>…]          what the developers' comments declare was built — Jira, the roster and the published
                                   map only, so it runs on any site; every entry is unverified by construction
  compare-helm <KEY>… [--jql …]    test only: ela's declared reading against Helm's grader on the same tickets
        ticket  summary, status, labels, the current Fixed In (map/release.yaml fixed_in.field)
        commits `git log --all --grep=<KEY>` and remote branches named for the key, in every checkout of a repository
                map/release.yaml `repos` names — the checkout the survey cache locates; a missing one is a gap.
                A commit that never named its key is found only through a hint the caller supplies — `--author`
                (with --since as the window), `--path`, `--thread` (a Slack permalink in the message) — and is
                labelled by the hint it came from; the judgment that such a commit is the fix stays with the caller
        builds  the first Jenkins build of the repository's job (map/release.yaml `jobs`) whose sha is the commit or
                descends from it in that checkout. Jenkins keeps a window; builds older than it come from Helm's build
                ledger when site.json names one (`builds_ledger`: captured first-hand by Helm's scheduler, stamped
                `synced_at`, read-only here) and are reported as such. A build whose sha is not in the checkout cannot be
                judged, so the carrying build is the earliest *verifiable* one and the untestable range is named
        lanes   qa-*, daily-*, stage and prod-N lanes whose own Jenkins build (the +BUILD of the lane's version) has a
                commit of the key as an ancestor; version order is not containment across branches. A build outside
                the fetched window, or a prod read without a session, is a gap, never a guess
        evidence QA verdicts over the key's Jira comments, mail and Slack since --since (default 30 days), one line each —
                only with --evidence: the mail and Slack sweep is the slow part (minutes) and a close rarely needs it
        draft   `<slug>@<version>` per service, beside the current value: same · differs · empty

--jql runs the same for every key the query returns. Nothing is written here: the owner confirms a draft and the
jira capability writes it (`jira.py fixed-in <KEY> --add '<entries>' --apply`, append-only). Checkouts are read as they are on disk; `ela sync <repo>` brings one up to date.
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


# ── hints: commits that never named their key ────────────────────────────────

def hinted_commits(path, a):
    """Candidate commits from the caller's hints, each labelled by the hint: --author (within --since), --path
    (within --since), --thread (the permalink in the message, fixed-string). Deduplicated by sha."""
    rows = []
    fmt = ("--format=%H%x09%ad%x09%s", "--date=short")
    if a.author or a.path:
        argv = ["log", "--all", f"--since={a.since}", "-n", "200", *fmt]
        via = []
        if a.author:
            argv.append(f"--author={a.author}"); via.append(f"author {a.author}")
        if a.path:
            argv += ["--", a.path]; via.append(f"path {a.path}")
        rc, out, _ = P.git(path, *argv)
        for r in parse_log(out) if rc == 0 else []:
            rows.append(dict(r, via=" ".join(via)))
    if a.thread:
        rc, out, _ = P.git(path, "log", "--all", "-F", f"--grep={a.thread}", *fmt)
        for r in parse_log(out) if rc == 0 else []:
            if r["sha"] not in {x["sha"] for x in rows}:
                rows.append(dict(r, via="thread"))
    return rows


# ── builds ────────────────────────────────────────────────────────────────────

def ledger_builds(job):
    """Helm's build ledger for a job (site.json `builds_ledger`, a sqlite file opened read-only): rows in the shape
    `release builds --json` gives, plus ledger=True, and the newest `synced_at`. (None, None) when the site names no
    ledger; ([], reason) when it cannot be read. The ledger is a first-hand capture stamped at capture time, kept
    because Jenkins forgets; inside Jenkins' own window Jenkins wins."""
    path = R.site().get("builds_ledger")
    if not path:
        return None, None
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{os.path.expanduser(path)}?mode=ro", uri=True)
        rows = con.execute("select number, version, branch, sha, result, timestamp, synced_at from builds where job=? order by number", (job,)).fetchall()
    except sqlite3.Error as e:
        return [], f"ledger unreadable: {e}"
    out, latest = [], ""
    for n, ver, br, sha, res, ts, syn in rows:
        pv = R.parse_version(ver or "")
        out.append({"job": job, "number": n, "version": R.vlabel(pv).split("+")[0] if pv else None,
                    "build": pv[4] if pv and pv[4] else n, "result": res, "branch": br or "", "sha": (sha or "")[:12],
                    "sha_full": sha or "", "time": datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "",
                    "ledger": True})
        latest = max(latest, syn or "")
    return out, latest


def job_builds(a, job, builds_cache, rec):
    """Jenkins' last 80 builds of a job, extended backwards from the ledger; cached per run. (builds, error)."""
    if job in builds_cache:
        return builds_cache[job]
    P.say(f"jenkins {job}")
    ok, bd, berr = P.l1("release", "builds", job, "--limit", "80", env_file=a.env_file, timeout=60)
    jb = (bd or {}).get("builds") if ok else None
    lb, stamp = ledger_builds(job)
    if lb:
        have = {b.get("number") for b in (jb or [])}
        merged = list(jb or []) + [b for b in lb if b["number"] not in have]
        note = f"ledger: builds older than Jenkins' window from Helm's ledger, captured {stamp}" if jb is not None \
            else f"ledger: Jenkins {job} unreadable ({(berr or '')[:80]}); all builds from Helm's ledger, captured {stamp}"
        builds_cache[job] = (merged, note)
    elif lb == [] and stamp:
        builds_cache[job] = (jb, "") if jb is not None else (None, berr)
        rec["gaps"].append(f"{job}: {stamp}")
    else:
        builds_cache[job] = (jb, "") if jb is not None else (None, berr)
    return builds_cache[job]


def commit_exists(path, sha):
    return P.git(path, "cat-file", "-e", f"{sha}^{{commit}}")[0] == 0


def untestable_before(path, builds, number):
    """Build numbers below `number` whose sha the checkout does not hold — they cannot be judged, so `number` is the
    earliest *verifiable* carrier, not necessarily the earliest. Capped so a long ledger stays cheap."""
    earlier = sorted((b for b in builds if b.get("number") is not None and b["number"] < number and b.get("sha_full")),
                     key=lambda b: -b["number"])[:150]
    return sorted(b["number"] for b in earlier if not commit_exists(path, b["sha_full"]))


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


def lanes_running(rows, builds, shas, is_ancestor):
    """Lanes whose own Jenkins build — the +BUILD of the lane's version — has a commit of the key as an ancestor.
    Version order is not containment: release.yaml trains build one job from several branches, so a higher number
    can come from a branch that never merged the fix. A lane whose build is outside the fetched builds, or whose
    number names a build of another version, is returned unjudged."""
    by_number = {b["number"]: b for b in builds if b.get("number") is not None and b.get("sha_full")}
    out, unjudged = [], []
    for r in rows:
        pv = R.parse_version(r.get("version"))
        if not r.get("lane") or not pv:
            continue
        b = by_number.get(pv[4])
        bpv = build_parsed(b) if b else None
        if not bpv or bpv[:4] != pv[:4]:
            unjudged.append(r["lane"]); continue
        s = next((s for s in shas if s == b["sha_full"] or is_ancestor(s, b["sha_full"])), None)
        if s:
            out.append({"lane": r["lane"], "version": R.vlabel(pv), "build": b["number"], "carries": s[:8]})
    return out, unjudged


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
    rec["declared"] = declared_from_comments(rec["comments"], f.get("summary") or "", P.load_roster())
    for e in P.parse_fixed_in(rec["current"]):
        if e["docker"]:
            rec["gaps"].append(f"{e['slug']}@{e['version']}: {DOCKER_GAP}")
    jobs = {v: k for k, v in (R.rmap("jobs") or {}).items()}          # service → job
    carriers, found = {}, {}                                          # found: slug → (key shas, builds, is_anc)
    for slug, rel in (R.rmap("repos") or {}).items():
        path = checkout_of(rel, repos_cache or [])
        if not path:
            rec["gaps"].append(f"{slug}: no checkout of {rel} in the survey cache (ela clone {rel})"); continue
        rows, err = commits_for(key, path)
        if err:
            rec["gaps"].append(f"{slug}: {err}"); continue
        for h in hinted_commits(path, a) if (a.author or a.path or a.thread) else []:
            if h["sha"] not in {r["sha"] for r in rows}:
                rows.append(h)
        if not rows:
            continue
        for c in rows:
            rec["commits"].append(dict(c, service=slug, repo=rel))
        job = jobs.get(slug)
        if not job:
            rec["gaps"].append(f"{slug}: service unmapped — no Jenkins job in map/release.yaml jobs; ask its owner for the build"); continue
        builds, note = job_builds(a, job, builds_cache, rec)
        if builds is None:
            rec["gaps"].append(f"{slug}: Jenkins {job} unreadable: {(note or '')[:120]}"); continue
        if note and note not in rec["gaps"]:
            rec["gaps"].append(note)
        is_anc = lambda s, b, p=path: P.git(p, "merge-base", "--is-ancestor", s, b)[0] == 0
        for c in rows:
            b = carrying_build(c["sha"], builds, is_anc)
            if not b:
                rec["gaps"].append(f"{slug}: {c['sha'][:8]} is in no build of {job}'s last {len(builds)} (not built yet, or older than the window)"); continue
            rec["builds"].append({"service": slug, "sha": c["sha"], "job": job, "number": b["number"],
                                  "version": R.vlabel(build_parsed(b)) if build_parsed(b) else b.get("version"), "result": b.get("result"),
                                  "ledger": bool(b.get("ledger"))})
            missing = untestable_before(path, builds, b["number"])
            if missing:
                rec["gaps"].append(f"{slug}: #{b['number']} is the earliest verifiable carrier of {c['sha'][:8]}; "
                                   f"#{missing[0]}–#{missing[-1]} ({len(missing)} builds) untestable — sha not in the checkout")
            carriers.setdefault(slug, []).append(b)
        found[slug] = ([c["sha"] for c in rows], builds, is_anc)
    for slug, bs in carriers.items():
        rec["draft"] += draft_values(slug, bs)
        shas, builds, is_anc = found[slug]
        for host in ("qa", "prod"):
            rows, gap = lane_rows(a.env_file, slug, host)
            if gap:
                if gap not in rec["gaps"]:
                    rec["gaps"].append(gap)
                continue
            running, unjudged = lanes_running(rows, builds, shas, is_anc)
            for x in running:
                rec["lanes"].append(dict(x, service=slug, host=host))
            if unjudged:
                rec["gaps"].append(f"{slug} on {host}: {', '.join(sorted(set(unjudged)))} run a build outside Jenkins' last {len(builds)} — not compared")
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


# ── declared: what the comments say was built (never what was verified) ───────
# The reading rules below were carried over from Helm's evidence engine (app/ops/scripts/evidence_engine.py,
# 2026-10-19) so that one implementation answers "what did the developer declare", and Helm's can retire on
# parity (`compare-helm`). The lexical tables — named-service tokens, summary prefixes, the one unique version
# series — are reading rules, not knowledge about the product; the service identities they resolve to are the
# slugs of map/release.yaml and the images of map/services.yaml, both published.

VERSION_RX = re.compile(r"(?:v?\d+\.\d+[\.\d]*(?:\+\d+|build\d+)?|build\s*\d+|@\d+[\.\d]*)", re.I)
BARE_BUILD_RX = re.compile(r"^build\s*(\d+)$", re.I)
EXPLICIT_RX = re.compile(r"(?<![A-Za-z0-9._/@-])([a-z][a-z0-9]*(?:-[a-z0-9]+)+)@"
                         r"(v?\d+(?:\.\d+){1,3}(?:\+\d+)?|build\s*\d+|[a-z0-9][a-z0-9._-]*:v?\d[a-z0-9._+-]*)", re.I)
COMMIT_SUBJECT_RX = re.compile(r"(?:commit|提交)\s*[:：].*|(?:fix|feat|chore|refactor|perf|docs|test|build|ci)\([^)]*\)\s*[:：].*", re.I)
NO_VERSION_RX = re.compile(r"(?:配置已修改|配置.*?已生效|已修改配置|已生效|(?:环境配置|配置问题).*?(?:已修复|修复|已解决|解决)"
                           r"|config\s+(?:changed|updated|applied|effective|deployed)|dns\s+(?:changed|updated|propagat)"
                           r"|infra\s+(?:fix|change|update).*?(?:applied|deployed|done))", re.I)
QA_REFUTE_RX = re.compile(r"(?:see\s+again|still\s+(?:repro|fail|broken|present|see|occur|happen)|still\b|reproduc(?:ed|ible|es)"
                          r"|fail(?:ed|s)\b|依然存在|仍然|还是|重现|复现|未解决|没解决|不行)", re.I)
VERDICT_LINE_RX = re.compile(r"(?:验证结果|验证结论|测试结果|复测结果|回归结果)\s*[:：]")
VERDICT_NEG_RX = re.compile(r"❌|未修复|未完全修复|未能修复|未通过|不通过|验证失败|验证不通过")
VERDICT_POS_RX = re.compile(r"✅|✓|验证通过|已修复|已实现|通过|pass(?:ed)?\b", re.I)
BARE_NEG_VERDICT_RX = re.compile(r"(?:未修复|未完全修复|未能修复|未通过|不通过|验证失败)\s*[：:（(]?\s*❌|❌\s*(?:未修复|未完全修复|未能修复|未通过|不通过|验证失败)")
QA_PASS_LOOSE_RX = re.compile(r"验证通过|已修复\s*[✅✓]|已修复.*(?:通过|验证|无问题)|pass(?:ed)?\b|verified\b", re.I)
DOCKER_IMAGE_RX = re.compile(r"([A-Za-z0-9][A-Za-z0-9._/\-]*[A-Za-z0-9]):(v?\d(?:[A-Za-z0-9._+\-]*[A-Za-z0-9])?)")
NAMED_SERVICES = [  # (token in lower-cased prose, slug); None marks a token too ambiguous to resolve alone
    ("unified-media-frontend", "unified-media-frontend"), ("unified-media-backend", "unified-media-backend"),
    ("mediahub-frontend", "mediahub-frontend"), ("mediahub-backend", "mediahub-backend"),
    ("mx-service-front", "unified-media-frontend"), ("mediahub-front-docker", "mediahub-frontend"),
    ("[media hub] frontend", "mediahub-frontend"), ("[media hub front]", "mediahub-frontend"), ("media hub front", "mediahub-frontend"),
    ("mediahub frontend", "mediahub-frontend"), ("mh frontend", "mediahub-frontend"), ("mh-frontend", "mediahub-frontend"), ("前端", None),
    ("[media hub] backend", "mediahub-backend"), ("media hub back", "mediahub-backend"), ("mediahub backend", "mediahub-backend"),
    ("mh backend", "mediahub-backend"), ("mh-backend", "mediahub-backend"),
    ("unified-streaming", "unified-streaming"), ("ur-streaming", "unified-streaming"), ("ur streaming", "unified-streaming"),
    ("ur-caller", "unified-streaming"), ("ur caller", "unified-streaming"), ("[ur caller]", "unified-streaming"),
    ("unified media service", None), ("unified media backend", "unified-media-backend"), ("unified media frontend", "unified-media-frontend"),
    ("j2n", "j2n"), ("headlessr", "headlessr"), ("ur portal", "ur-portal"), ("ur-portal", "ur-portal"),
]
SUMMARY_PREFIXES = [("ur caller", "unified-streaming"), ("[ur caller]", "unified-streaming"), ("ur-caller", "unified-streaming")]
SERIES_SLUGS = {"2.2": "mediahub-frontend"}          # the one MAJOR.MINOR series only one service uses
MH_CONTINUATION = {"frontend": "mediahub-frontend", "backend": "mediahub-backend"}
MH_QUALIFIERS = ("[media hub]", "media hub", "mediahub")
PAIR_WINDOW, QUALIFIER_WINDOW = 120, 80
DEV_AREAS = {"app", "ui", "ur", "media"}   # the layers that build; the owner's own closing comments are not declarations


def normalize_token(raw):
    v = str(raw or "").strip()
    while v[:1] in ("@", "v", "V"):
        v = v[1:]
    return re.sub(r"[^0-9A-Za-z]+$", "", v)


def is_bare_line(version):
    """A bare MAJOR.MINOR is a release line, never a service version."""
    m = (version or "").strip()
    if not m or re.search(r"\+\d+|build\d+", m, re.I) or re.match(r"(?:build\s*\d+|@\d)", m, re.I):
        return False
    return len(m.lstrip("vV").split(".")) < 3


def qa_verdict(body):
    """'refute' | 'pass' | None: the explicit verdict a QA comment declares. A structured verdict line (验证结果：…)
    is read in a 30-character window, negative beating positive; a bare negative beside ❌ is a refutation."""
    body, positive = body or "", False
    for m in VERDICT_LINE_RX.finditer(body):
        window = body[m.end():m.end() + 30]
        if VERDICT_NEG_RX.search(window):
            return "refute"
        if VERDICT_POS_RX.search(window):
            positive = True
    if positive:
        return "pass"
    return "refute" if BARE_NEG_VERDICT_RX.search(body) else None


def qa_refutes(body):
    """A QA comment refutes the fix when its explicit verdict is negative, or — with no verdict line and no pass
    wording — when a re-failure token appears. A passing comment that mentions "still" is not a refutation."""
    v = qa_verdict(body)
    if v:
        return v == "refute"
    return not QA_PASS_LOOSE_RX.search(body) and bool(QA_REFUTE_RX.search(body))


def mask_commit_subjects(body):
    out = body
    for m in COMMIT_SUBJECT_RX.finditer(body):
        out = out[:m.start()] + " " * (m.end() - m.start()) + out[m.end():]
    return out


def _binds(ch):
    return ch.isalnum() or ch in "-_@/."


_IMAGES = None
def image_index():
    """image base name → [{slug, gm_name, process_type}] from the published map/services.yaml `images:` block."""
    global _IMAGES
    if _IMAGES is not None:
        return _IMAGES
    idx, cur, raw = {}, None, []
    try:
        lines = open(os.path.join(R.site().get("map", ""), "services.yaml"), encoding="utf-8").read().splitlines()
    except OSError:
        _IMAGES = {}; return _IMAGES
    inside = False
    for ln in lines:
        if not ln.startswith(" "):
            inside = ln.startswith("images:"); cur = None; continue
        if not inside:
            continue
        m = re.match(r"^  ([A-Za-z0-9][A-Za-z0-9._/-]*):\s*$", ln)
        if m:
            cur = {"image": m.group(1).lower(), "slugs": [], "gm_names": [], "process_types": []}
            raw.append(cur)
            continue
        m = re.match(r"^    (slugs|gm_names|process_types):\s*(\[.*\])\s*$", ln)
        if m and cur is not None:
            try:
                cur[m.group(1)] = [str(x) for x in json.loads(m.group(2))]
            except ValueError:
                pass
    for e in raw:                       # one record per slug: the lists are parallel, position i describes slug i
        recs = [{"slug": sl, "gm_name": e["gm_names"][i] if i < len(e["gm_names"]) else "",
                 "process_type": e["process_types"][i] if i < len(e["process_types"]) else ""} for i, sl in enumerate(e["slugs"])]
        for key in ("/".join(e["image"].split("/")[i:]) for i in range(e["image"].count("/") + 1)):
            idx.setdefault(key, []).extend(r for r in recs if r["slug"] not in {x["slug"] for x in idx.get(key, [])})
    _IMAGES = idx
    return idx


def known_slugs():
    out = {s for _, s in named_services() if s} | set(SERIES_SLUGS.values())
    al = (R.rmap("fixed_in") or {}).get("slug_aliases") or {}
    out |= set(al) | set(al.values()) | set((R.rmap("repos") or {}).keys()) | set((R.rmap("jobs") or {}).values())
    for bucket in image_index().values():
        out |= {e["slug"] for e in bucket}
    return out


def resolve_explicit(body):
    al = (R.rmap("fixed_in") or {}).get("slug_aliases") or {}
    known, order, ver = known_slugs(), [], {}
    for m in EXPLICIT_RX.finditer(body):
        slug = al.get(m.group(1).lower(), m.group(1).lower())
        if slug not in known:
            continue
        raw = m.group(2)
        if slug not in ver:
            order.append(slug)
        ver[slug] = raw if ":" in raw else normalize_token(raw)
    return [(s, ver[s]) for s in order]


def resolve_docker(body, context=""):
    """`image:tag` citations → (mds slug, image:tag); a shared image narrowed by what the ticket names, else all of them."""
    idx, ctx, out, seen = image_index(), (context or "").lower(), [], set()
    for m in DOCKER_IMAGE_RX.finditer(body or ""):
        path, tag = m.group(1).lower(), m.group(2)
        parts = [p for p in path.split("/") if p]
        hit = next((idx[k] for k in ("/".join(parts[i:]) for i in range(len(parts))) if idx.get(k)), None)
        if not hit:
            continue
        cands = list(hit)
        if len(cands) > 1 and ctx:
            narrowed = [e for e in cands if any(t and t.lower() in ctx for t in (e["process_type"], e["gm_name"]))]
            if len(narrowed) == 1:
                cands = narrowed
        name = parts[-1] if parts else path
        for e in cands:
            if e["slug"] not in seen:
                seen.add(e["slug"]); out.append((e["slug"], f"{name}:{tag}"))
    return out


_NAMED = None
def named_services():
    """The hand table above plus what the published release map derives first-hand: every Jenkins job name and every
    repository basename names the service it builds (media-hub-v4 and tvu-media-hub → mediahub-backend). Longer tokens
    first, so a job name is matched before a word inside it."""
    global _NAMED
    if _NAMED is None:
        extra = []
        for job, slug in (R.rmap("jobs") or {}).items():
            extra.append((job.lower(), slug))
        for slug, rel in (R.rmap("repos") or {}).items():
            base = str(rel).rstrip("/").split("/")[-1].lower()
            if base and len(base) > 4:
                extra.append((base, slug))
        seen = {t for t, _ in NAMED_SERVICES}
        _NAMED = NAMED_SERVICES + [(t, sl) for t, sl in extra if t not in seen]
        _NAMED.sort(key=lambda x: -len(x[0]))
    return _NAMED


def resolve_named_multi(body):
    b = body.lower()
    vers = [(m.start(), m.end(), m.group()) for m in VERSION_RX.finditer(b)]
    svc, covered = [], set()
    for token, slug in named_services():
        start = 0
        while True:
            pos = b.find(token, start)
            if pos == -1:
                break
            if pos not in covered and not any(s0 <= pos < s1 for s0, s1, _ in svc):
                covered.add(pos); svc.append((pos, pos + len(token), slug))
            start = pos + 1
    quals = [b.find(t) for t in MH_QUALIFIERS if t in b]
    if quals:
        for kw, kslug in MH_CONTINUATION.items():
            start = 0
            while True:
                pos = b.find(kw, start)
                if pos == -1:
                    break
                inside = any(s <= pos < e for s, e, _ in svc)
                qualified = any(0 <= pos - q <= QUALIFIER_WINDOW for q in quals)
                if qualified and not inside and pos not in covered:
                    pre = b[pos - 1] if pos else " "; post = b[pos + len(kw)] if pos + len(kw) < len(b) else " "
                    if not _binds(pre) and not _binds(post):
                        covered.add(pos); svc.append((pos, pos + len(kw), kslug))
                start = pos + 1
    if not svc:
        return []
    svc.sort()
    claimed, pairs = set(), []
    for s0, s1, slug in svc:
        if slug is None:
            continue
        best = None
        for v0, v1, vs in vers:
            if v0 in claimed or v0 < s1 or v0 > s1 + PAIR_WINDOW:
                continue
            if best is None or v0 - s1 < best[0] - s1:
                best = (v0, vs)
        if best is None:
            continue
        claimed.add(best[0]); pv = best[1]
        if not re.search(r"(?:\+\d+|build\d+)$", pv, re.I):
            vend = best[0] + len(pv)
            for n0, n1, ns in vers:
                if n0 <= best[0] or n0 in claimed:
                    continue
                bm = BARE_BUILD_RX.match(ns.strip())
                if bm is None:
                    break
                if re.fullmatch(r"[\s()]*", b[vend:n0]):
                    claimed.add(n0); pv = pv + "+" + bm.group(1)
                break
        pairs.append((slug, pv))
    seen, out = set(), []
    for slug, v in pairs:
        if slug not in seen:
            seen.add(slug); out.append((slug, v))
    return out


def resolve_named_one(body):
    b = body.lower()
    for token, slug in named_services():
        if token in b:
            return slug
    return None


def resolve_pairs(body, versions, summary):
    """One developer comment → the (slug, version) pairs it declares, and the rule that read them."""
    explicit = resolve_explicit(body)
    if explicit:
        return explicit, "explicit token"
    body = mask_commit_subjects(body)
    multi = resolve_named_multi(body)
    if multi:
        return [(s, normalize_token(v)) for s, v in multi], "named service" + (" (multi)" if len(multi) > 1 else "")
    distinct = {normalize_token(v) for v in versions} - {""}
    last = normalize_token(versions[-1]) if versions else ""
    slug, via, pair = resolve_named_one(body), "named service", last
    if slug is None:
        s = summary.lower()
        slug = next((sl for t, sl in SUMMARY_PREFIXES if t in s), None); via = "summary prefix"
    if slug is None:
        bl = body.lower()
        slug = next((sl for t, sl in SUMMARY_PREFIXES if t in bl), None); via = "feature tag"
    if slug is None:
        for v in versions:
            parts = normalize_token(v).split(".")
            if len(parts) >= 2 and SERIES_SLUGS.get(f"{parts[0]}.{parts[1]}"):
                slug, pair, via = SERIES_SLUGS[f"{parts[0]}.{parts[1]}"], normalize_token(v), "version series"
                break
    if not slug or not pair:
        return [], ""
    if len(distinct) != 1 and pair == last:
        return [], ""            # several versions, nothing positional: refuse rather than pick
    return [(slug, pair)], via


def declared_from_comments(comments, summary, roster):
    """What the developers' comments declare, as the latest full version per service, with the bare release-line
    tokens kept apart and docker citations resolved through the image index. Never verified: a declaration says
    where a fix was built, not that QA passed it (map/release.yaml fixed_in.dev_declared_is_not_verified)."""
    cits, qa_refute, unknown = [], [], []
    for idx, c in enumerate(comments):
        who = c.get("author") if isinstance(c.get("author"), str) else (c.get("author") or {}).get("displayName") or ""
        body = P.adf_text(c.get("body")).strip() if not isinstance(c.get("body"), str) else c.get("body")
        area = P.person_area(roster, who) or ""
        versions = VERSION_RX.findall(body)
        when = (c.get("created") or "")[:10]
        if area == "qa":
            if qa_refutes(body):
                qa_refute.append(idx)
            continue
        if not versions and not DOCKER_IMAGE_RX.search(body):
            continue
        if area in DEV_AREAS:
            cits.append((idx, {"author": who, "when": when, "body": body, "versions": versions}))
        elif who:
            unknown.append({"author": who, "when": when, "area": area or "not in roster"})
    suppressed = {i for i, _ in cits if any(r > i for r in qa_refute)}
    order, ver, meta, bare, docker = [], {}, {}, [], []
    context = (summary or "") + " " + " ".join(c["body"] for _, c in cits)
    for idx, cit in cits:
        if idx in suppressed:
            continue
        if NO_VERSION_RX.search(cit["body"]) and cit["versions"] and all(is_bare_line(v) for v in cit["versions"]):
            continue
        for slug, image_tag in resolve_docker(cit["body"], context):
            if (slug, image_tag) not in docker:
                docker.append((slug, image_tag)); meta[slug] = (cit["author"], cit["when"], "docker image")
        pairs, via = resolve_pairs(cit["body"], cit["versions"], summary or "")
        for slug, version in pairs:
            if is_bare_line(version):
                bare.append((slug, version)); continue
            if slug not in ver:
                order.append(slug)
            ver[slug] = version; meta[slug] = (cit["author"], cit["when"], via)
    bare = [(s, v) for s, v in bare if s not in ver]
    rows = [{"service": s, "version": ver[s], "value": f"{s}@{ver[s]}", "author": meta[s][0], "date": meta[s][1], "via": meta[s][2], "verified": False} for s in order]
    rows += [{"service": s, "version": t, "value": f"{s}@{t}", "author": meta[s][0], "date": meta[s][1], "via": "docker image", "verified": False} for s, t in docker]
    return {"declared": rows, "bare_release_lines": [f"{s}@{v}" for s, v in bare], "suppressed_by_qa_refutation": len(suppressed),
            "versions_from_unknown_authors": unknown, "developer_comments_read": len(cits)}


def cmd_declared(a):
    """`declared <KEY>…`: the Jira read, the roster and the published map only — no checkout, no Jenkins — so it runs
    on any site, the remote included. Draft only; nothing is written."""
    keys = [k.upper() for k in a.keys]
    bad = [k for k in keys if not KEY_SHAPE.match(k)]
    if not keys or bad:
        print("declared needs ticket keys", file=sys.stderr); sys.exit(EX_USAGE)
    roster, recs, code = P.load_roster(), [], 0
    for k in keys:
        d, err = read_ticket(a.env_file, k)
        if not d:
            recs.append({"key": k, "error": "not in Jira" if err == EX_NOTFOUND else "Jira unreadable"}); code = code or err; continue
        f = d.get("fields") or {}
        fid = (R.rmap("fixed_in") or {}).get("field") or "customfield_11252"
        raw = f.get(fid)
        rec = {"key": k, "summary": f.get("summary"), "status": (f.get("status") or {}).get("name"),
               "current": P.adf_text(raw).strip() if raw else ""}
        rec.update(declared_from_comments(d.get("comments") or [], f.get("summary") or "", roster))
        recs.append(rec)
    if a.json:
        print(json.dumps({"keys": recs}, ensure_ascii=False))
    else:
        for r in recs:
            if r.get("error"):
                print(f"## {r['key']}  ! {r['error']}"); continue
            print(f"## {r['key']}  [{r['status'] or '?'}]  {(r['summary'] or '')[:90]}")
            print(f"   current   {r['current'] or '—'}")
            for x in r["declared"]:
                print(f"   declared  {x['value']:<44} {x['author']} {x['date']}  via {x['via']}  (unverified)")
            if r["bare_release_lines"]:
                print(f"   ! release-line tokens, not versions: {', '.join(r['bare_release_lines'])}")
            if r["suppressed_by_qa_refutation"]:
                print(f"   ! {r['suppressed_by_qa_refutation']} declaration(s) post-dated by a QA re-failure, left out")
            for u in r["versions_from_unknown_authors"]:
                print(f"   ! a version in a comment by {u['author']} ({u['area']}) on {u['when']} — not read as a declaration")
            print()
    if code:
        sys.exit(code)


# ── compare-helm: Helm's grader as the oracle (test only; never a runtime dependency) ──

HELM_GRADER = r'''
import sys, json
from pathlib import Path
ROOT = Path(sys.argv[1])
for p in (ROOT / "app" / "ops" / "scripts", ROOT / "app" / "ops", ROOT / "app", ROOT):
    sys.path.insert(0, str(p))
import evidence_engine as E
issues = json.load(open(sys.argv[2]))
out = {}
for iss in issues:
    f = iss["fields"]; f["comment"] = {"comments": iss.get("comments") or []}
    g = E.grade_issue({"key": iss["key"], "fields": f})
    dev = []
    for idx, c in enumerate(f["comment"]["comments"]):
        author = (c.get("author") or {}).get("displayName", ""); canon = E.canonical_author(c)
        body = E.extract_text(c.get("body", {})); versions = E.VERSION_RE.findall(body)
        if E.author_in(author, canon, E.DEV_NAMES) and versions:
            dev.append((idx, {"author": author, "body": body, "versions": versions}))
    refuted = E.qa_refutation_indices(f["comment"]["comments"])
    suppressed = {i for i, _ in dev if any(r > i for r in refuted)}
    pairs, vias, bare = E.union_declared_pairs(dev, f.get("summary") or "", suppressed)
    out[iss["key"]] = {"grade": g.grade, "signal": g.signal, "pairs": [f"{s}@{v}" for s, v in pairs], "bare": [f"{s}@{v}" for s, v in bare]}
json.dump(out, open(sys.argv[3], "w"), ensure_ascii=False, default=str)
'''


def cmd_compare_helm(a):
    """`compare-helm <KEY>… [--jql …]`: ela's `declared` against Helm's `union_declared_pairs` on the same ticket JSON; every
    difference listed. Zero unexplained differences is the retirement condition for Helm's copy (ADR 0005)."""
    keys = [k.upper() for k in a.keys]
    if a.jql:
        ok, d, err = P.l1("jira", "jql", a.jql, "--limit", "100", env_file=a.env_file, timeout=120)
        if not ok:
            print(f"jql failed: {err}", file=sys.stderr); sys.exit(EX_REMOTE)
        keys += [i["key"] for i in d.get("issues") or [] if i.get("key") and i["key"] not in keys]
    if not keys:
        print("compare-helm needs ticket keys or --jql", file=sys.stderr); sys.exit(EX_USAGE)
    helm = os.path.join(R.site().get("projects") or "", "helm")
    if not os.path.isfile(os.path.join(helm, "app", "ops", "scripts", "evidence_engine.py")):
        print(f"no Helm checkout at {helm}", file=sys.stderr); sys.exit(EX_USAGE)
    roster, issues, mine = P.load_roster(), [], {}
    cached = {i["key"]: i for i in json.load(open(a.issues))} if a.issues else {}
    for k in keys:
        d, err = (cached.get(k), None) if a.issues else read_ticket(a.env_file, k)
        if not d:
            continue
        issues.append(d)
        f = d.get("fields") or {}
        mine[k] = declared_from_comments(d.get("comments") or [], f.get("summary") or "", roster)
    work = os.path.join(R.site().get("runtime") or "/tmp", "compare-helm"); os.makedirs(work, exist_ok=True)
    inp, outp, script = os.path.join(work, "issues.json"), os.path.join(work, "helm.json"), os.path.join(work, "helm_grader.py")
    json.dump(issues, open(inp, "w"), ensure_ascii=False); open(script, "w").write(HELM_GRADER)
    rc, out, err = P.run(["bash", "-lc", f"cd {helm} && set -a && . config/.env 2>/dev/null; set +a; python3 {script} {helm} {inp} {outp}"], 600)
    if rc != 0 or not os.path.isfile(outp):
        print(f"helm grader failed: {(err or out).strip()[-400:]}", file=sys.stderr); sys.exit(EX_REMOTE)
    helm_out, agree, differ = json.load(open(outp)), 0, []
    for k, m in mine.items():
        h = helm_out.get(k) or {}
        ela_pairs = sorted(x["value"] for x in m["declared"] if x["via"] != "docker image")
        helm_pairs = sorted(h.get("pairs") or [])
        if ela_pairs == helm_pairs:
            agree += 1
        else:
            differ.append({"key": k, "ela": ela_pairs, "helm": helm_pairs, "helm_grade": h.get("grade"), "ela_bare": m["bare_release_lines"], "helm_bare": h.get("bare")})
    res = {"compared": len(mine), "agree": agree, "differ": differ}
    if a.json:
        print(json.dumps(res, ensure_ascii=False)); return
    print(f"compared {len(mine)}  agree {agree}  differ {len(differ)}")
    for d in differ:
        print(f"  {d['key']:<8} ela {d['ela'] or '—'}   helm {d['helm'] or '—'}  (helm grade {d['helm_grade']})")


# ── output ────────────────────────────────────────────────────────────────────

def print_text(recs):
    for r in recs:
        print(f"## {r['key']}  [{r['status'] or '?'}]  {(r['summary'] or '')[:90]}")
        print(f"   current   {r['current'] or '—'}")
        print(f"   draft     {'; '.join(d['value'] for d in r['draft']) or '—'}   ({r['compare'] or 'unread'})")
        for c in r["commits"]:
            via = f"  [branch {', '.join(c['branches'])}]" if c.get("branches") else ""
            hint = f"  [via {c['via']}]" if c.get("via") not in (None, "message", "branch") else ""
            print(f"   commit    {c['service']:<24} {c['sha'][:8]} {c['date']} {c['subject'][:80]}{via}{hint}")
        for x in (r.get("declared") or {}).get("declared") or []:
            print(f"   declared  {x['value']:<44} {x['author']} {x['date']}  via {x['via']}  (unverified)")
        for b in r["builds"]:
            print(f"   build     {b['service']:<24} {b['job']} #{b['number']} {b['version']} {b['result'] or ''}  ← {b['sha'][:8]}{'  (ledger)' if b.get('ledger') else ''}")
        for x in r["lanes"]:
            print(f"   lane      {x['service']:<24} {x['lane']:<12} {x['version']}  ({x['host']})  ← {x['carries']}")
        ev = r.get("evidence")
        if ev:
            print(f"   evidence  {ev['verdict']} since {ev['since']} — {len(ev['items'])} item(s)")
            for i in ev["items"]:
                print(f"             {i['source']:<5} {i['date']} {i['verdict']:<14} {i['line'][:110]}")
        for g in r["gaps"]:
            print(f"   ! {g}")
        print()


def group_of(r):
    """One of four groups a clean-up batch sorts into: derivable (a build was found) · declared (only a developer's
    comment names a version) · unmapped (the service has no job or checkout in the release map) · none."""
    if r.get("exit"):
        return "unreadable"
    if r.get("draft"):
        return "derivable"
    if (r.get("declared") or {}).get("declared"):
        return "declared"
    if any("unmapped" in g or "no checkout" in g for g in r.get("gaps") or []):
        return "unmapped"
    return "none"


def print_groups(recs):
    groups = {}
    for r in recs:
        groups.setdefault(group_of(r), []).append(r)
    order = ["derivable", "declared", "unmapped", "none", "unreadable"]
    print("## groups")
    for g in order:
        rows = groups.get(g) or []
        if not rows:
            continue
        print(f"   {g:<10} {len(rows):>3}  " + ", ".join(r["key"] for r in rows))
    print("   derivable → `jira close` with the draft; declared → verify the declared build by ancestry first, or write it as declared;")
    print("   unmapped → ask the service's owner for the build; none → the comment names what closed it, the field stays")


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
    if a.evidence:
        attach_evidence(a, recs)
    else:
        for r in recs:
            r.pop("comments", None)
    if a.json:
        print(json.dumps({"keys": [dict({f: r.get(f) for f in ("key", "summary", "status", "labels", "current", "compare", "draft",
                                                               "commits", "builds", "lanes", "evidence", "gaps", "declared")}, group=group_of(r)) for r in recs]}, ensure_ascii=False))
    else:
        print_text(recs)
        if a.group or len(recs) > 1:
            print_groups(recs)
    codes = {r.get("exit") for r in recs}
    if EX_REMOTE in codes:
        sys.exit(EX_REMOTE)
    if EX_NOTFOUND in codes:
        sys.exit(EX_NOTFOUND)


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    verbs = ("draft", "declared", "compare-helm")
    i = 3 if len(sys.argv) > 1 and sys.argv[1] == "--env-file" else 1      # where the subcommand sits
    if len(sys.argv) > i and sys.argv[i] == "draft" and len(sys.argv) > i + 1 and sys.argv[i + 1] in verbs[1:]:
        del sys.argv[i]                        # `ela fixed-in declared …` arrives as `draft declared …`: the named verb wins
    elif len(sys.argv) > i and sys.argv[i] not in verbs + ("-h", "--help"):
        sys.argv.insert(i, "draft")            # `ela fixed-in MH-1` is the draft
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("draft", help="the Fixed In a ticket's evidence supports, beside the current value — draft only; no Jira write")
    p.add_argument("keys", nargs="*", help="ticket keys (MH-3568)")
    p.add_argument("--jql", help="also every key this query returns (up to 300)")
    p.add_argument("--since", help="window start for --evidence and for --author/--path, YYYY-MM-DD (default 30 days ago)")
    p.add_argument("--evidence", action="store_true", help="also sweep QA mail and Slack for verdicts (slow: minutes)")
    p.add_argument("--author", help="hint: also take this author's commits since --since as candidates")
    p.add_argument("--path", help="hint: also take commits touching this path since --since as candidates")
    p.add_argument("--thread", help="hint: also take commits whose message carries this Slack permalink")
    p.add_argument("--group", action="store_true", help="end with the four groups a batch sorts into (always on for more than one key)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("declared", help="what the developers' comments declare was built (unverified) — no checkout, no Jenkins")
    p.add_argument("keys", nargs="*"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("compare-helm", help="test only: ela's declared reading vs Helm's grader on the same tickets")
    p.add_argument("keys", nargs="*"); p.add_argument("--jql"); p.add_argument("--issues", help="a saved issues.json from an earlier run instead of reading Jira again")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if getattr(a, "since", None) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.since):
        print("--since takes YYYY-MM-DD", file=sys.stderr); sys.exit(EX_USAGE)
    {"draft": cmd_draft, "declared": cmd_declared, "compare-helm": cmd_compare_helm}[a.cmd](a)


if __name__ == "__main__":
    main()
