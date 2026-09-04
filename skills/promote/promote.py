#!/usr/bin/env python3
"""Promotion assessment, read first-hand and cross-checked — the facts a person needs before moving a release
line from one lane to another. L1: subcommands, --json, stdlib only; every source is read now, nothing is
cached, and every source is checked against another one (a commit against its ticket, a ticket against its
Fixed In, a Fixed In against the build that carries it, a claim against QA's own words).

  lanes    <line> <from> <to> [--scope app|all]   both lanes' versions per service; other lanes ahead of `to`
  delta    <line> <from> <to> [--scope]          builds between the lanes → commit range per service → keys, kinds, hygiene
  tickets  <line> <from> <to> [--scope]          every key the delta names ∪ every ticket whose Fixed In names a delta build; reconciled
  evidence <line> <from> <to> [--scope] [--since YYYY-MM-DD]   QA verdicts per key from Jira comments, mail and Slack
  bundles  <line> <from> <to>                    the two lanes' newest bundles, docker service by docker service
  report   <line> <from> <to> [--purpose regular|prod-staging|demo] [--scope] [--out DIR]   all of it, ranked and capped

<line> is a key of map/release.yaml lines ("2.1"); <from>/<to> are lane roles (qa · daily · prod) or lane names
(qa-cn3 · daily-wed · prod-3). QA lanes are read on the qa host (account login); daily/stage/prod lanes and their
bundles on the prod host with the person's TVU session (`ela login tvu`) — a missing session is a finding, never
a cached number. Judgement is not here: the skill ranks and words; this script collects and reconciles.
Exit codes: 0 ok · 2 usage · 3 a lane is unreadable · 5 remote error.
"""
import argparse, datetime, email.utils, json, os, re, signal, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SKILLS, "release"))
import release as R  # noqa: E402  — the release map, the userservice hosts, Jenkins

EX_USAGE, EX_LANE, EX_REMOTE = 2, 3, 5
KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,5}-\d{2,6}\b")
ISO = "%Y-%m-%dT%H:%M:%SZ"


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime(ISO)


def run(argv, timeout=180):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except OSError as e:
        return 127, "", str(e)


def l1(cap, *args, env_file=None, timeout=180):
    """Call a sibling L1 with --json; return (ok, parsed or None, stderr)."""
    argv = ["python3", os.path.join(SKILLS, cap, f"{cap}.py")]
    if env_file and cap not in ("map",):
        argv += ["--env-file", env_file]
    argv += list(args) + ["--json"]
    rc, out, err = run(argv, timeout)
    if rc != 0 or not out.strip():
        return False, None, (err or out).strip()[:300]
    try:
        return True, json.loads(out), ""
    except ValueError:
        return False, None, "not json"


# ── versions ──────────────────────────────────────────────────────────────────

parse_version, vlabel = R.parse_version, R.vlabel


def cmp_versions(slug, a, b):
    """-1 a<b · 0 · 1 a>b, honouring patch_only slugs (order on M.m.p only)."""
    if a is None or b is None:
        return None
    po = set((R.rmap("version_rules").get("semver_build") or {}).get("patch_only") or [])
    ka, kb = (a[:3], b[:3]) if slug in po else (a, b)
    return (ka > kb) - (ka < kb)


# ── lanes ─────────────────────────────────────────────────────────────────────

def line_cfg(line):
    cfg = (R.rmap("lines") or {}).get(str(line))
    if not cfg:
        print(f"unknown release line {line!r}; known: {', '.join(R.rmap('lines') or {})}", file=sys.stderr); sys.exit(EX_USAGE)
    return cfg


def lane_name(cfg, role_or_lane):
    lanes = cfg.get("lanes") or {}
    if role_or_lane in lanes:
        return lanes[role_or_lane]
    return role_or_lane


def lane_host(lane):
    classes = (R.rmap("hosts") or {}).get("lane_classes") or {}
    if lane in (classes.get("qa") or []):
        return "qa"
    if lane in (classes.get("daily") or []) or lane in (classes.get("prod") or []):
        return "prod"
    return "prod" if lane.startswith(("daily-", "prod-", "stage")) else "qa"


def scope_slugs(scope):
    if scope == "app":
        return list((R.rmap("version_rules").get("app_layer") or {}).get("slugs") or [])
    seen = []
    for sec in ("service_ids", "qa_service_ids"):
        for pairs in (R.rmap(sec) or {}).values():
            for slug, _ in (tuple(x) for x in pairs):
                if slug not in seen:
                    seen.append(slug)
    return seen


def read_host(env_file, host, gaps):
    """All lane rows a host publishes; None (and a gap) when the host is unreadable."""
    try:
        us = R.US(env_file, host)
    except SystemExit as e:
        gaps.append({"kind": "host_unreadable", "host": host, "detail": "no session — run: ela login tvu" if host == "prod" else "qa login failed", "exit": e.code}); return None
    try:
        return R.lane_versions(us)
    except SystemExit as e:
        gaps.append({"kind": "host_unreadable", "host": host, "detail": f"read failed (exit {e.code})", "exit": e.code}); return None


def collect_lanes(a, gaps):
    cfg = line_cfg(a.line)
    f_lane, t_lane = lane_name(cfg, a.src), lane_name(cfg, a.dst)
    hosts = {}
    for h in {lane_host(f_lane), lane_host(t_lane)}:
        hosts[h] = read_host(a.env_file, h, gaps)
    slugs = scope_slugs(a.scope)
    by = {}                                  # slug → lane → row
    for h, rows in hosts.items():
        for r in rows or []:
            if r["service"] in slugs and r.get("lane"):
                by.setdefault(r["service"], {})[r["lane"]] = dict(r, host=h, parsed=parse_version(r["version"]))
    lane_for_slug = cfg.get("lane_for_slug") or {}
    out = []
    for slug in slugs:
        lanes = by.get(slug, {})
        tl = lane_for_slug.get(slug, t_lane) if a.dst in ("daily",) else t_lane
        fr, to = lanes.get(f_lane), lanes.get(tl)
        rel = None
        if fr and to:
            c = cmp_versions(slug, fr["parsed"], to["parsed"])
            rel = {1: "from_ahead", 0: "same", -1: "to_ahead", None: "unparsed"}[c]
        ahead = []
        relevant = set((cfg.get("lanes") or {}).values()) | set(lane_for_slug.values())
        if to and to["parsed"]:
            for ln, row in lanes.items():
                if ln in relevant and ln not in (tl, f_lane) and row["parsed"] and cmp_versions(slug, row["parsed"], to["parsed"]) == 1:
                    ahead.append({"lane": ln, "version": row["version"]})
        out.append({"service": slug, "from_lane": f_lane, "to_lane": tl,
                    "from": fr and {"version": fr["version"], "parsed": fr["parsed"], "tag": fr["tag"], "host": fr["host"]},
                    "to": to and {"version": to["version"], "parsed": to["parsed"], "tag": to["tag"], "host": to["host"]},
                    "relation": rel, "other_lanes_ahead_of_to": ahead,
                    "unreadable": [h for h in (lane_host(f_lane), lane_host(tl)) if hosts.get(h) is None]})
    return {"line": a.line, "from": f_lane, "to": t_lane, "services": out, "hosts_read": {h: (rows is not None) for h, rows in hosts.items()}}


def cmd_lanes(a):
    gaps = []
    res = collect_lanes(a, gaps); res["gaps"] = gaps
    if a.json:
        print(json.dumps(res, ensure_ascii=False)); return
    print(f"# {a.line}: {res['from']} → {res['to']}   read: " + ", ".join(f"{h} {'ok' if ok else 'UNREADABLE'}" for h, ok in res["hosts_read"].items()))
    for s in res["services"]:
        f = (s["from"] or {}).get("version", "—"); t = (s["to"] or {}).get("version", "—")
        extra = ("  ← " + ", ".join(f"{x['lane']} ahead ({x['version'].split(' 20')[0]})" for x in s["other_lanes_ahead_of_to"])) if s["other_lanes_ahead_of_to"] else ""
        print(f"  {s['service']:<24} {str(f).split(' 20')[0]:<26} → {str(t).split(' 20')[0]:<26} {s['relation'] or '?'}{extra}")
    for g in gaps:
        print(f"  ! {g['kind']}: {g.get('host', '')} {g['detail']}")
    if gaps:
        sys.exit(EX_LANE)


# ── delta: builds → commits ───────────────────────────────────────────────────

def jenkins_builds(job, limit=80):
    base = R._service_url("jenkins")
    tree = f"builds[number,displayName,result,timestamp,url,actions[lastBuiltRevision[branch[name,SHA1]]]]{{0,{limit}}}"
    st, body = R.http(f"{base}/job/{R.urllib.parse.quote(job, safe='')}/api/json?tree={R.urllib.parse.quote(tree, safe='[],:{}')}", timeout=30)
    if st != 200 or not isinstance(body, dict):
        return None
    rows = []
    for b in body.get("builds") or []:
        rev = next((x.get("lastBuiltRevision") for x in b.get("actions") or [] if isinstance(x, dict) and x.get("lastBuiltRevision")), {}) or {}
        br = (rev.get("branch") or [{}])[0]
        pv = parse_version(b.get("displayName") or "")
        rows.append({"number": b.get("number"), "display": b.get("displayName"), "version": vlabel(pv).split("+")[0] if pv else None,
                     "build": pv[4] if pv else None, "result": b.get("result"),
                     "branch": (br.get("name") or "").replace("refs/remotes/origin/", ""), "sha": br.get("SHA1") or "",
                     "time": datetime.datetime.fromtimestamp((b.get("timestamp") or 0) / 1000).strftime("%Y-%m-%d %H:%M"), "url": b.get("url")})
    return rows


def match_build(rows, parsed):
    """The Jenkins build that published this lane version: same build number and same M.m.SUB[.PATCH] label."""
    if not parsed:
        return None, "unparsed"
    label = vlabel(parsed).split("+")[0]
    exact = [r for r in rows if r.get("build") == parsed[4] and r.get("version") == label]
    if exact:
        return exact[0], "exact"
    by_num = [r for r in rows if r.get("build") == parsed[4]]
    if by_num:
        return by_num[0], "build_number_only — label differs: " + str(by_num[0].get("version"))
    by_label = [r for r in rows if r.get("version") == label]
    if by_label and parsed[4] == 0:
        return by_label[0], "label_only"
    return None, "not_in_jenkins_window"


def repo_path(repo):
    code = R.site().get("code") or ""
    dn = R.site().get("dir_names") or {}
    for cand in (dn.get(repo), repo):
        if cand and os.path.isdir(os.path.join(code, cand, ".git")):
            return os.path.join(code, cand)
    return None


def git(path, *args, timeout=60):
    rc, out, err = run(["git", "-C", path, *args], timeout)
    return rc, out, err


def kind_of(subject):
    m = re.match(r"^\s*(revert\b|[a-zA-Z]+)(?:\([^)]*\))?!?:", subject.strip(), re.I)
    return (m.group(1).lower() if m else "other")


def collect_delta(a, lanes, gaps):
    jobs = {v: k for k, v in (R.rmap("jobs") or {}).items()}      # service → job
    repos = R.rmap("repos") or {}
    out = []
    for s in lanes["services"]:
        slug = s["service"]
        rec = {"service": slug, "job": jobs.get(slug), "repo": repos.get(slug), "from": s["from"] and s["from"]["version"], "to": s["to"] and s["to"]["version"],
               "relation": s["relation"], "commits": [], "hygiene": [], "builds_between": [], "newer_builds_on_neither_lane": []}
        out.append(rec)
        if not s["from"] or not s["to"] or s["relation"] in ("same", None):
            rec["note"] = "no delta" if s["relation"] == "same" else "a lane is unreadable or unparsed"; continue
        if not rec["job"]:
            rec["note"] = "no Jenkins job in map/release.yaml jobs"; continue
        rows = jenkins_builds(rec["job"])
        if rows is None:
            gaps.append({"kind": "jenkins_unreadable", "job": rec["job"]}); rec["note"] = "jenkins unreadable"; continue
        fb, fhow = match_build(rows, s["from"]["parsed"]); tb, thow = match_build(rows, s["to"]["parsed"])
        rec["from_build"] = fb and {k: fb[k] for k in ("number", "version", "build", "branch", "sha", "time")}; rec["from_match"] = fhow
        rec["to_build"] = tb and {k: tb[k] for k in ("number", "version", "build", "branch", "sha", "time")}; rec["to_match"] = thow
        lo, hi = (s["to"]["parsed"], s["from"]["parsed"]) if s["relation"] == "from_ahead" else (s["from"]["parsed"], s["to"]["parsed"])
        lo_b, hi_b = (tb, fb) if s["relation"] == "from_ahead" else (fb, tb)
        if lo_b and hi_b:
            between = [r for r in rows if r.get("build") is not None and lo_b["build"] < r["build"] <= hi_b["build"]]
            between.sort(key=lambda r: r["build"])
            rec["builds_between"] = [{k: r[k] for k in ("number", "version", "build", "branch", "sha", "time", "result")} for r in between]
            # hygiene inside the range
            seen_ver = {}
            last = None
            branches = set()
            for r in between:
                pv = parse_version((r.get("version") or "") + f"+{r['build']}")
                if r.get("version"):
                    seen_ver.setdefault(r["version"], set()).add(r["sha"][:12])
                if last and pv and last[0] and cmp_versions(slug, pv[:4] + (0,), last[0][:4] + (0,)) == -1:
                    rec["hygiene"].append({"kind": "version_label_not_monotonic", "detail": f"build {r['build']} is {r['version']} after build {last[1]} was {last[0] and vlabel(last[0]).split('+')[0]}"})
                last = (pv, r["build"])
                if r.get("branch"):
                    branches.add(r["branch"])
                if r.get("result") not in (None, "SUCCESS"):
                    rec["hygiene"].append({"kind": "build_not_success", "detail": f"build {r['build']} {r['result']}"})
            for v, shas in seen_ver.items():
                if len(shas) > 1:
                    rec["hygiene"].append({"kind": "one_label_two_shas", "detail": f"{v} built from {', '.join(sorted(shas))}"})
            nums = [r["build"] for r in between]
            if nums:
                missing = sorted(set(range(lo_b["build"] + 1, hi_b["build"] + 1)) - set(nums))
                if missing:
                    rec["hygiene"].append({"kind": "missing_build_numbers", "detail": ", ".join(str(x) for x in missing[:8])})
            for br in branches:
                if not re.match(r"^(release|master$|main$|hotfix)", br):
                    rec["hygiene"].append({"kind": "built_from_non_release_branch", "detail": br})
            if "build_number_only" in (fhow + thow):
                rec["hygiene"].append({"kind": "lane_label_differs_from_jenkins", "detail": f"from: {fhow}; to: {thow}"})
        newer = [r for r in rows if r.get("build") and hi_b and r["build"] > hi_b["build"] and r.get("result") == "SUCCESS"]
        rec["newer_builds_on_neither_lane"] = [{k: r[k] for k in ("number", "version", "build", "branch", "sha", "time")} for r in newer[:5]]
        # commits
        path = repo_path(rec["repo"]) if rec["repo"] else None
        if not path:
            rec["note"] = f"repo not on disk: {rec['repo']} (ela clone)"; gaps.append({"kind": "repo_missing", "service": slug, "repo": rec["repo"]}); continue
        git(path, "fetch", "--quiet", "--all", timeout=90)
        if not (lo_b and hi_b):
            rec["note"] = f"cannot place both lane versions on Jenkins builds (from: {fhow}; to: {thow})"; continue
        for tag, sha in (("from", lo_b["sha"]), ("to", hi_b["sha"])):
            rc, _, _ = git(path, "cat-file", "-e", f"{sha}^{{commit}}")
            if rc != 0:
                rec["hygiene"].append({"kind": "sha_not_in_checkout", "detail": f"{tag} {sha[:12]} — checkout behind Jenkins or a rewritten branch"})
        rc, log, err = git(path, "log", "--no-merges", "--date=short", "--pretty=%H%x1f%ad%x1f%an%x1f%s%x1f%b%x1e", f"{lo_b['sha']}..{hi_b['sha']}")
        if rc != 0:
            rec["note"] = "git log failed: " + err.strip()[:120]; continue
        for recd in log.split("\x1e"):
            recd = recd.strip("\n")
            if not recd.strip():
                continue
            h, d, au, subj, body = (recd.split("\x1f") + [""] * 5)[:5]
            ks, kb = sorted(set(KEY_RE.findall(subj))), sorted(set(KEY_RE.findall(body)) - set(KEY_RE.findall(subj)))
            owner = ks if ks else kb          # the commit's own ticket(s): the subject's key, else the body's when the subject has none
            refs = [k for k in kb if k not in owner]
            rec["commits"].append({"sha": h[:8], "date": d, "author": au, "subject": subj, "kind": kind_of(subj),
                                   "keys": sorted(set(ks) | set(kb)), "keys_in_subject": ks, "keys_only_in_body": kb,
                                   "owner_keys": owner, "ref_keys": refs,
                                   "body_excerpt": re.sub(r"\s+", " ", body)[:240]})
        rc, stat, _ = git(path, "diff", "--shortstat", f"{lo_b['sha']}..{hi_b['sha']}")
        rec["shortstat"] = stat.strip()
        rec["direction"] = "to lane is behind from lane — promotion moves it forward" if s["relation"] == "from_ahead" else "TO LANE IS AHEAD — promotion would move it backwards"
    return {"line": a.line, "from": lanes["from"], "to": lanes["to"], "services": out}


def cmd_delta(a):
    gaps = []
    lanes = collect_lanes(a, gaps)
    res = collect_delta(a, lanes, gaps); res["gaps"] = gaps
    if a.json:
        print(json.dumps(res, ensure_ascii=False)); return
    print(f"# {a.line}: {res['from']} → {res['to']}")
    for s in res["services"]:
        print(f"\n## {s['service']}  {str(s['from'] or '—').split(' 20')[0]} → {str(s['to'] or '—').split(' 20')[0]}   {s.get('direction') or s.get('note') or ''}")
        if s.get("builds_between"):
            print("   builds: " + " · ".join(f"#{b['number']} {b['version']}+{b['build']} {b['branch']}" for b in s["builds_between"]))
        for c in s["commits"]:
            flag = ("" if c["keys_in_subject"] else (" (key only in body)" if c["keys_only_in_body"] else " (no key)")) + (f"  [body also cites {', '.join(c['keys_only_in_body'])}]" if c["keys_in_subject"] and c["keys_only_in_body"] else "")
            print(f"   {c['sha']} {c['date']} {c['kind']:<8} {c['subject'][:90]}{flag}")
        if s.get("shortstat"):
            print(f"   {len(s['commits'])} commit(s); {s['shortstat']}")
        for h in s["hygiene"]:
            print(f"   ! {h['kind']}: {h['detail']}")
        for b in s["newer_builds_on_neither_lane"]:
            print(f"   ~ newer build on neither lane: #{b['number']} {b['version']}+{b['build']} {b['branch']} {b['time']}")
    for g in gaps:
        print(f"! {g}")


# ── tickets ───────────────────────────────────────────────────────────────────

def adf_text(node):
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_text(n) for n in node)
    if isinstance(node, dict):
        t = node.get("type")
        if t == "text":
            return node.get("text", "")
        if t == "mention":
            return "@" + ((node.get("attrs") or {}).get("text", "") or "")
        if t == "inlineCard":
            return (node.get("attrs") or {}).get("url", "")
        if t == "hardBreak":
            return "\n"
        s = adf_text(node.get("content") or [])
        return s + ("\n" if t in ("paragraph", "heading", "listItem", "tableRow", "codeBlock") else "")
    return ""


def parse_fixed_in(text):
    """'slug@ver; slug@ver' → [(slug, ver, parsed)] with legacy aliases resolved."""
    aliases = (R.rmap("fixed_in") or {}).get("slug_aliases") or {}
    out = []
    for part in re.split(r"[;\n]+", text or ""):
        part = part.strip().rstrip(".")
        if "@" not in part:
            continue
        slug, ver = part.split("@", 1)
        slug = aliases.get(slug.strip(), slug.strip()); ver = ver.strip()
        out.append({"slug": slug, "version": ver, "parsed": parse_version(ver.replace("build", "+")) if not slug.startswith("mds-") else None, "docker": slug.startswith("mds-")})
    return out


def jira_read(env_file, key):
    ok, d, err = l1("jira", "read", key, env_file=env_file, timeout=60)
    return d if ok else None


def load_roster():
    path = os.path.join(R.site().get("records") or "", "knowledge", "products", "mediahub", "team", "roster.yaml")
    try:
        d = R._yaml_subset(open(path).read())
    except OSError:
        return []
    return d.get("people") or []


def person_area(roster, display_name):
    n = (display_name or "").strip().lower()
    for p in roster:
        names = {str(p.get("name") or "").lower(), str(p.get("jira_name") or "").lower()}
        if n and n in names:
            return p.get("area") or ""
    return ""


def collect_tickets(a, delta, gaps):
    cfg = line_cfg(a.line)
    label = cfg.get("label")
    keys, refs = {}, {}
    for s in delta["services"]:
        for c in s["commits"]:
            for k in c["owner_keys"]:
                keys.setdefault(k, {"commits": [], "services": set()})
                keys[k]["commits"].append({"service": s["service"], "sha": c["sha"], "kind": c["kind"], "only_in_body": k in c["keys_only_in_body"], "subject": c["subject"][:80]})
                keys[k]["services"].add(s["service"])
            for k in c["ref_keys"]:
                refs.setdefault(k, []).append({"service": s["service"], "sha": c["sha"], "subject": c["subject"][:80], "by": c["owner_keys"]})
    # reverse: tickets whose Fixed In names a build inside the delta, and tickets carrying the line label updated in the window
    versions = set()
    for s in delta["services"]:
        for b in s.get("builds_between") or []:
            if b.get("version"):
                versions.add(b["version"])
    reverse = {}
    fid = (R.rmap("fixed_in") or {}).get("field") or "customfield_11252"
    cf = re.sub(r"\D", "", fid)
    if versions:
        clauses = " OR ".join(f'cf[{cf}] ~ "{v}"' for v in sorted(versions))
        ok, d, err = l1("jira", "jql", f"({clauses}) ORDER BY key", "--limit", "100", env_file=a.env_file, timeout=90)
        if ok:
            for it in d.get("issues") or []:
                reverse[it.get("key")] = "fixed_in_names_a_delta_build"
        else:
            gaps.append({"kind": "jira_reverse_lookup_failed", "detail": err})
    for k in reverse:
        keys.setdefault(k, {"commits": [], "services": set()})
    roster = load_roster()
    out = []
    for k in sorted(keys):
        d = jira_read(a.env_file, k)
        if not d:
            out.append({"key": k, "exists": False, "commits": keys[k]["commits"], "flags": ["key_not_in_jira"]}); continue
        f = d.get("fields") or {}
        st = (f.get("status") or {}).get("name"); asg = (f.get("assignee") or {}).get("displayName"); labels = f.get("labels") or []
        fi_raw = f.get(fid)
        fi_text = adf_text(fi_raw).strip() if fi_raw else ""
        fi = parse_fixed_in(fi_text)
        svcs = sorted(keys[k]["services"])
        flags = []
        if label and label not in labels:
            flags.append("no_release_label")
        commit_kinds = {c["kind"] for c in keys[k]["commits"]}
        code_commits = [c for c in keys[k]["commits"] if c["kind"] not in ("docs", "chore", "test", "style")]
        if not fi_text and code_commits:
            flags.append("no_fixed_in")
        if keys[k]["commits"] and all(c["only_in_body"] for c in keys[k]["commits"]):
            flags.append("key_only_in_commit_bodies")
        if keys[k]["commits"] and not code_commits:
            flags.append("referenced_by_docs_only")
        if k in reverse and not keys[k]["commits"]:
            flags.append("fixed_in_claims_delta_build_but_no_commit_names_it")
        # Fixed In vs carrier: every service with code commits should have a Fixed In entry inside the delta
        fi_by_slug = {e["slug"]: e for e in fi}
        carried = {c["service"] for c in code_commits}
        for svc in sorted(carried):
            e = fi_by_slug.get(svc)
            if not e:
                if fi_text:
                    flags.append(f"fixed_in_missing_service:{svc}")
                continue
            sd = next((x for x in delta["services"] if x["service"] == svc), None)
            if sd and e["parsed"] and sd.get("builds_between"):
                labels_in = {b["version"] for b in sd["builds_between"] if b.get("version")}
                if vlabel(e["parsed"]).split("+")[0] not in labels_in:
                    flags.append(f"fixed_in_outside_delta:{svc}@{e['version']}")
        for e in fi:
            if e["slug"] not in scope_slugs("all") and not e["docker"] and e["slug"] not in ((R.rmap("fixed_in") or {}).get("bundle_tracked_extra_slugs") or []):
                flags.append(f"fixed_in_unknown_slug:{e['slug']}")
        comments = []
        for c in d.get("comments") or []:
            who = c.get("author") if isinstance(c.get("author"), str) else (c.get("author") or {}).get("displayName")
            comments.append({"who": who, "area": person_area(roster, who), "when": (c.get("created") or "")[:10], "text": adf_text(c.get("body")).strip()})
        out.append({"key": k, "exists": True, "summary": f.get("summary"), "status": st, "assignee": asg, "labels": labels, "fixed_in": fi_text, "fixed_in_entries": fi,
                    "services_in_delta": svcs, "commits": keys[k]["commits"], "reverse": reverse.get(k), "flags": flags, "comments": comments,
                    "url": d.get("url")})
    return {"line": a.line, "label": label, "tickets": out, "referenced_only": {k: v for k, v in refs.items() if k not in keys}}


def cmd_tickets(a):
    gaps = []
    lanes = collect_lanes(a, gaps); delta = collect_delta(a, lanes, gaps)
    res = collect_tickets(a, delta, gaps); res["gaps"] = gaps
    if a.json:
        for t in res["tickets"]:
            t.pop("comments", None)
        print(json.dumps(res, ensure_ascii=False)); return
    print(f"# {a.line} tickets in {lanes['from']} → {lanes['to']}  ({len(res['tickets'])})")
    for t in res["tickets"]:
        if not t["exists"]:
            print(f"  {t['key']:<9} NOT IN JIRA  commits: {len(t['commits'])}"); continue
        print(f"  {t['key']:<9} [{str(t['status']):<11}] {str(t['assignee'] or '—'):<14} svc: {','.join(t['services_in_delta']) or '—':<48} FixedIn: {t['fixed_in'] or '—'}")
        if t["flags"]:
            print(f"            ! {'; '.join(t['flags'])}")
    if res.get("referenced_only"):
        print("  referenced in commit bodies only (context, not carried): " + ", ".join(sorted(res["referenced_only"])))
    for g in gaps:
        print(f"! {g}")


# ── evidence ──────────────────────────────────────────────────────────────────

VERDICT = [
    ("pass", re.compile(r"(?i)\bpass(ed)?\b(?!\s*(rate|word))|验证结果[:：]?\s*已修复|已修复\s*✅|验证通过|测试通过|已关单|\bverified\b(?!\s+(on\s+)?(daily|不了))")),
    ("fail", re.compile(r"(?i)\bfail(ed)?\b|未修复|验证结果[:：]?\s*未|退回|reopen")),
    ("n-a", re.compile(r"(?i)\bN/?A\b|无需\s*QA|不在\s*MH\s*端验证|无需验证|not applicable")),
    ("not-scheduled", re.compile(r"未排期|not scheduled|未覆盖|did not cover")),
    ("dev-declared", re.compile(r"(?i)has been fixed|deployed to|implemented and|已修复并|shipped in|released in|本次部署|fixed in build|ready for qa")),
]


def classify(text, area):
    hits = [name for name, rx in VERDICT if rx.search(text or "")]
    if area == "qa":
        for pick in ("fail", "pass", "n-a", "not-scheduled"):
            if pick in hits:
                return pick
        return "qa-comment" if text else "none"
    if "dev-declared" in hits or ("pass" in hits and area in ("app", "ui", "engineering")):
        return "dev-declared"
    return "mention"


def iso_when(v):
    """RFC 2822 (mail), ISO (jira), epoch seconds (slack) → 'YYYY-MM-DDTHH:MM' for ordering; '' when unknown."""
    if v is None:
        return ""
    s = str(v).strip()
    try:
        return datetime.datetime.fromtimestamp(float(s), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M")
    except ValueError:
        pass
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:16].replace(" ", "T")
    try:
        return email.utils.parsedate_to_datetime(s).astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M")
    except Exception:
        return ""


SECTION = re.compile(r"(?i)^\W*(?:\d+\.\s*)?(close[d]? issues?|reopen(?:ed)? issues?|new issues?|closed|reopened|已关闭|重新打开|新增)\b")
KEY_VERDICT = re.compile(r"(?i)\b(PASS(?:ED)?|FAIL(?:ED)?|N/?A|未修复|已修复|未排期|不在\s*MH\s*端验证|无需\s*QA\s*介入)\b")


def key_verdicts(text, key):
    """Verdicts a report gives THIS key: the key's own result line (`*MH-3405* PASS [9-3]`, `MH-3405 FAIL`), or the
    section the key is listed under (close issue → pass, reopened → fail). Never a neighbouring key's line."""
    out, section = [], None
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        m = SECTION.match(ln.strip())
        if m:
            head = m.group(1).lower()
            section = "pass" if head.startswith(("close", "已关闭")) else "fail" if head.startswith(("reopen", "重新")) else "new"
            continue
        if key not in ln:
            continue
        others = set(KEY_RE.findall(ln)) - {key}
        seg = ln
        if others:                                        # keep only the part of the line that belongs to this key
            idx = ln.find(key); seg = ln[idx:]
            cut = min((seg.find(o) for o in others if seg.find(o) > 0), default=len(seg)); seg = seg[:cut]
        v = KEY_VERDICT.search(seg)
        if not v and others:                              # "A / B  N/A" — one verdict for every key on the line
            line_v = {x.lower() for x in KEY_VERDICT.findall(ln)}
            if len(line_v) == 1:
                v = KEY_VERDICT.search(ln)
        if not v and i + 1 < len(lines) and not KEY_RE.search(lines[i + 1]):
            v = KEY_VERDICT.match(lines[i + 1].strip())
        if v:
            w = v.group(1).lower()
            verdict = "pass" if w.startswith("pass") or w == "已修复" else "fail" if w.startswith("fail") or w == "未修复" else "not-scheduled" if w == "未排期" else "n-a"
            out.append((verdict, seg.strip()[:220])); continue
        if section in ("pass", "fail") and re.fullmatch(r"\W*" + re.escape(key) + r"\W*.*", ln.strip()) and len(ln.strip()) < 160:
            out.append((section, f"listed under {'close' if section == 'pass' else 'reopened'} issues: {ln.strip()[:120]}"))
    return out


def collect_evidence(a, tickets, delta, gaps, since=None):
    roster = load_roster()
    qa_people = [p for p in roster if (p.get("area") or "") == "qa"]
    qa_emails = [p.get("email") for p in qa_people if p.get("email")]
    qa_names = {str(p.get("name") or "") for p in qa_people}
    keys = [t["key"] for t in tickets["tickets"] if t.get("exists")]
    if not since:
        dates = [b["time"][:10] for s in delta["services"] for b in (s.get("builds_between") or [])]
        since = min(dates) if dates else (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    ev = {k: [] for k in keys}
    # 1 jira comments
    for t in tickets["tickets"]:
        for c in t.get("comments") or []:
            if c["when"] and c["when"] < since and not c["area"] == "qa":
                continue
            v = classify(c["text"], c["area"])
            if c["area"] == "qa":
                kv = key_verdicts(c["text"], t["key"])
                if kv:
                    v = kv[-1][0]
                elif re.search(r"验证结果[:：]?\s*(已修复|未修复)", c["text"]):
                    v = "pass" if "已修复" in c["text"].split("验证结果", 1)[1][:6] else "fail"
                elif re.search(r"(?i)qa\s*验证结果|验证结果", c["text"]) and not VERDICT[1][1].search(c["text"]) and "依然" not in c["text"]:
                    v = "pass"                                     # a QA result comment with no failure wording
            if v in ("pass", "fail", "n-a", "not-scheduled", "dev-declared", "qa-comment"):
                ev[t["key"]].append({"source": "jira", "who": c["who"], "area": c["area"], "when": iso_when(c["when"]), "verdict": v, "quote": re.sub(r"\s+", " ", c["text"])[:220]})
    # 2 mail: QA people's reports and dev deploy notices since the window start
    q_since = since.replace("-", "/")
    senders = " OR ".join(f"from:{e}" for e in qa_emails) if qa_emails else "subject:(test report)"
    ok, d, err = l1("mail", "search", f"after:{q_since} ({senders} OR subject:(test report MediaHub) OR subject:(Release MediaHub) OR subject:(Release Mediahub) OR subject:(Release UR Caller))", "--limit", "120", "--body", env_file=a.env_file, timeout=420)
    if not ok:
        gaps.append({"kind": "mail_unreadable", "detail": err})
    else:
        for m in d.get("messages") or []:
            body = m.get("body") or ""
            text = (m.get("subject") or "") + "\n" + body
            found = sorted(set(KEY_RE.findall(text)) & set(keys))
            if not found:
                continue
            who = re.sub(r"\s*<.*", "", m.get("from") or "")
            area = person_area(roster, who) or ("qa" if any(e in (m.get("from") or "") for e in qa_emails) else "")
            is_deploy_notice = bool(re.match(r"^\s*(Re:\s*)?\[Release", m.get("subject") or ""))
            for k in found:
                kv = key_verdicts(text, k) if area == "qa" else []
                if kv:
                    verdict, quote = kv[-1]
                else:
                    verdict = "dev-declared" if is_deploy_notice else ("qa-report-mention" if area == "qa" else "mention")
                    quote = next((ln.strip() for ln in text.splitlines() if k in ln), "")[:220]
                ev[k].append({"source": "mail", "who": who, "area": area, "when": iso_when(m.get("date")), "verdict": verdict,
                              "subject": m.get("subject"), "id": m["id"], "quote": quote})
    # 3 slack: the channel since the window start, top-level messages
    ok, d, err = l1("slack", "history", "#prj_dev_mediahub", "--since", since, env_file=a.env_file, timeout=240)
    if not ok:
        gaps.append({"kind": "slack_unreadable", "detail": err})
    else:
        for m in d.get("messages") or []:
            text = m.get("text") or ""
            found = sorted(set(KEY_RE.findall(text)) & set(keys))
            for k in found:
                who = m.get("user_name") or m.get("author") or m.get("user") or ""
                v = classify(text, person_area(roster, who))
                ev[k].append({"source": "slack", "who": who, "when": iso_when(m.get("ts") or m.get("date")), "verdict": v if v in ("pass", "fail", "n-a", "not-scheduled", "dev-declared") else "mention",
                              "permalink": m.get("permalink"), "quote": re.sub(r"\s+", " ", text)[:220]})
    # verdict per key: QA words win; dev words never mean verified
    summary = {}
    for k, items in ev.items():
        qa = [i for i in items if i["verdict"] in ("pass", "fail", "n-a", "not-scheduled") and (i.get("area") == "qa" or i["source"] == "mail" and i.get("area") == "qa")]
        qa.sort(key=lambda i: i.get("when") or "")
        final = qa[-1]["verdict"] if qa else ("dev-declared" if any(i["verdict"] == "dev-declared" for i in items) else "none")
        summary[k] = {"verdict": final, "qa_items": len(qa), "items": items}
    return {"since": since, "keys": summary, "qa_people": sorted(qa_names)}


def cmd_evidence(a):
    gaps = []
    lanes = collect_lanes(a, gaps); delta = collect_delta(a, lanes, gaps); tickets = collect_tickets(a, delta, gaps)
    res = collect_evidence(a, tickets, delta, gaps, a.since); res["gaps"] = gaps
    if a.json:
        print(json.dumps(res, ensure_ascii=False)); return
    print(f"# evidence since {res['since']}  (QA people: {', '.join(res['qa_people'])})")
    for k, s in res["keys"].items():
        print(f"  {k:<9} {s['verdict']:<14} {len(s['items'])} item(s)")
        for i in s["items"][:4]:
            print(f"      {i['source']:<5} {i['verdict']:<14} {str(i.get('when'))[:10]} {str(i.get('who'))[:18]:<18} {i.get('quote','')[:110]}")
    for g in gaps:
        print(f"! {g}")


# ── bundles ───────────────────────────────────────────────────────────────────

def newest_bundle(us, bundle_line, lane_token):
    rows = R.bundle_list(us, bundle_line, 50)
    rows = [b for b in rows if str(b.get("bundleName", "")).startswith(bundle_line + lane_token) and
            (str(b.get("bundleName")) == bundle_line + lane_token or str(b.get("bundleName"))[len(bundle_line + lane_token)] == "-")]
    rows.sort(key=lambda x: str(x.get("createTime") or ""), reverse=True)
    return rows[0] if rows else None


def bundle_map(us, b):
    items = R.bundle_detail(us, str(b["bundleId"])).get("serviceTagList") or []
    return {str(i.get("serviceName") or "").strip(): str(i.get("tagName") or i.get("version") or "").strip() for i in items}


def collect_bundles(a, gaps):
    cfg = line_cfg(a.line)
    bl = cfg.get("bundle_line"); toks = cfg.get("bundle_lanes") or {}
    f_role = a.src if a.src in toks else next((r for r, l in (cfg.get("lanes") or {}).items() if l == a.src), None)
    t_role = a.dst if a.dst in toks else next((r for r, l in (cfg.get("lanes") or {}).items() if l == a.dst), None)
    res = {"line": a.line, "from": None, "to": None, "changed": [], "only_in_from": [], "only_in_to": [], "identical": 0, "comparable_direction": []}
    if not bl or not f_role or not t_role:
        gaps.append({"kind": "bundle_lanes_unknown", "detail": f"line {a.line} has no bundle_lanes for {a.src}/{a.dst}"}); return res
    maps = {}
    for role, key in ((f_role, "from"), (t_role, "to")):
        host = "qa" if role == "qa" else "prod"
        try:
            us = R.US(a.env_file, host)
            b = newest_bundle(us, bl, toks[role])
            if not b:
                gaps.append({"kind": "bundle_missing", "detail": f"no {bl}{toks[role]}* on {host}"}); continue
            res[key] = {"name": b.get("bundleName"), "id": str(b.get("bundleId")), "created": R.when(b.get("createTime")), "host": host}
            maps[key] = bundle_map(us, b)
        except SystemExit as e:
            gaps.append({"kind": "host_unreadable", "host": host, "detail": "no session — run: ela login tvu" if host == "prod" else "qa login failed", "exit": e.code})
    if "from" in maps and "to" in maps:
        fm, tm = maps["from"], maps["to"]
        for name in sorted(set(fm) | set(tm)):
            if name not in tm:
                res["only_in_from"].append({"service": name, "tag": fm[name]}); continue
            if name not in fm:
                res["only_in_to"].append({"service": name, "tag": tm[name]}); continue
            if fm[name] == tm[name]:
                res["identical"] += 1; continue
            pf, pt = parse_version(fm[name]), parse_version(tm[name])
            direction = None
            if pf and pt:
                c = (pf > pt) - (pf < pt); direction = {1: "from_ahead", -1: "to_ahead", 0: "same"}[c]
            res["changed"].append({"service": name, "from": fm[name], "to": tm[name], "direction": direction or "named_tags_not_comparable"})
    return res


def cmd_bundles(a):
    gaps = []
    res = collect_bundles(a, gaps); res["gaps"] = gaps
    if a.json:
        print(json.dumps(res, ensure_ascii=False)); return
    print(f"# {a.line} bundles: {(res['from'] or {}).get('name')} ({(res['from'] or {}).get('host')}) → {(res['to'] or {}).get('name')} ({(res['to'] or {}).get('host')})")
    print(f"  identical {res['identical']} · changed {len(res['changed'])} · only in from {len(res['only_in_from'])} · only in to {len(res['only_in_to'])}")
    for c in res["changed"]:
        print(f"  {c['service']:<44} {c['from']:<22} → {c['to']:<22} {c['direction']}")
    for x in res["only_in_from"]:
        print(f"  + only in from: {x['service']} ({x['tag']})")
    for x in res["only_in_to"]:
        print(f"  - only in to:   {x['service']} ({x['tag']})")
    for g in gaps:
        print(f"! {g}")


# ── report ────────────────────────────────────────────────────────────────────

SEV = {"stop": 0, "high": 1, "medium": 2, "low": 3, "note": 4}


def assess(a, lanes, delta, tickets, evidence, bundles, gaps):
    """Findings, ranked. Purpose sets which reconciliation results are open points rather than notes."""
    purpose = a.purpose
    to_is_prod = lane_host(lanes["to"]) == "prod" and lanes["to"].startswith("prod")
    strict = purpose in ("prod-staging",) or to_is_prod
    F = []
    def add(sev, kind, what, **kw):
        F.append(dict(severity=sev, kind=kind, what=what, **kw))
    for g in gaps:
        if g["kind"] == "host_unreadable":
            add("stop", "lane_unreadable", f"{g['host']} host unreadable — {g['detail']}")
        elif g["kind"] in ("repo_missing", "jenkins_unreadable", "mail_unreadable", "slack_unreadable", "jira_reverse_lookup_failed", "bundle_missing", "bundle_lanes_unknown"):
            add("medium", g["kind"], str(g.get("detail") or g))
    for s in lanes["services"]:
        if s["relation"] == "to_ahead":
            add("high", "to_lane_ahead", f"{s['service']}: {s['to_lane']} runs {s['to']['version'].split(' 20')[0]}, newer than {s['from_lane']} {s['from']['version'].split(' 20')[0]} — promotion would move it backwards")
        for x in s["other_lanes_ahead_of_to"]:
            add("medium" if strict else "low", "other_lane_ahead_of_to", f"{s['service']}: {x['lane']} already runs {x['version'].split(' 20')[0]}, ahead of {s['to_lane']}")
        if s["relation"] == "unparsed":
            add("medium", "version_unparsed", f"{s['service']}: a lane version could not be parsed — undetermined, not compared")
    ev = (evidence or {}).get("keys") or {}
    for t in tickets["tickets"]:
        if not t.get("exists"):
            add("note", "key_not_in_jira", f"{t['key']} is named by {len(t['commits'])} commit(s) but is not a Jira issue"); continue
        v = (ev.get(t["key"]) or {}).get("verdict", "none")
        code = [c for c in t["commits"] if c["kind"] not in ("docs", "chore", "test", "style")]
        multi = len(t["services_in_delta"]) > 1
        if code:
            if v in ("none", "dev-declared", "qa-comment", "mention"):
                sev = "high" if strict else ("medium" if (multi or t.get("status") in ("Done",)) else "low")
                add(sev, "no_qa_verdict", f"{t['key']} [{t['status']}] {t.get('summary','')[:70]} — {len(code)} code commit(s) in {', '.join(t['services_in_delta'])}; evidence: {v}", key=t["key"])
            elif v == "fail":
                add("high", "qa_failed", f"{t['key']} — QA's latest verdict is FAIL", key=t["key"])
            elif v == "not-scheduled":
                add("medium" if strict else "low", "qa_not_scheduled", f"{t['key']} — QA recorded it as not scheduled", key=t["key"])
        for fl in t["flags"]:
            if fl.startswith("fixed_in_outside_delta") or fl.startswith("fixed_in_missing_service") or fl == "no_fixed_in":
                add("medium", "fixed_in_gap", f"{t['key']}: {fl}", key=t["key"])
            elif fl == "fixed_in_claims_delta_build_but_no_commit_names_it":
                add("medium", "fixed_in_unbacked", f"{t['key']}: Fixed In names a build in this delta, but no commit in the range names the key", key=t["key"])
            elif fl == "no_release_label":
                add("low", "no_release_label", f"{t['key']} lacks {tickets['label']}", key=t["key"])
            elif fl == "key_only_in_commit_bodies":
                add("low", "key_only_in_body", f"{t['key']} appears only in commit bodies, never in a subject", key=t["key"])
            elif fl.startswith("fixed_in_unknown_slug"):
                add("low", "fixed_in_unknown_slug", f"{t['key']}: {fl}", key=t["key"])
    for k, uses in sorted((tickets.get("referenced_only") or {}).items()):
        add("note", "referenced_only", f"{k} is cited as context by {len(uses)} commit(s) of {', '.join(sorted({x for u in uses for x in u['by']}))} — not carried by this promotion")
    for s in delta["services"]:
        loose = [c for c in s["commits"] if not c["keys"] and c["kind"] in ("feat", "fix", "perf", "refactor", "revert")]
        if loose:
            add("high" if strict else "medium", "ticketless_code_commits", f"{s['service']}: {len(loose)} {'/'.join(sorted({c['kind'] for c in loose}))} commit(s) with no ticket — " + "; ".join(c["subject"][:60] for c in loose[:4]), service=s["service"])
        for h in s["hygiene"]:
            add("low", "build_hygiene", f"{s['service']}: {h['kind']} — {h['detail']}", service=s["service"])
        for b in s["newer_builds_on_neither_lane"][:2]:
            add("note", "newer_build_pending", f"{s['service']}: build #{b['number']} {b['version']}+{b['build']} ({b['time']}) is on neither lane", service=s["service"])
    if bundles and bundles.get("changed") is not None:
        back = [c for c in bundles["changed"] if c["direction"] == "to_ahead"]
        fwd = [c for c in bundles["changed"] if c["direction"] == "from_ahead"]
        if back:
            add("high" if a.scope == "all" else "medium", "bundle_would_roll_back", "docker services newer on the target lane than on the source: " + ", ".join(f"{c['service']} {c['to']}→{c['from']}" for c in back[:6]))
        if fwd:
            add("note", "bundle_forward", "docker services newer on the source lane: " + ", ".join(f"{c['service']} {c['from']}" for c in fwd[:6]))
        if bundles.get("only_in_from"):
            add("note", "bundle_new_service", "only in the source bundle: " + ", ".join(x["service"] for x in bundles["only_in_from"][:6]))
    F.sort(key=lambda f: SEV[f["severity"]])
    return F


def cmd_report(a):
    gaps = []
    lanes = collect_lanes(a, gaps)
    delta = collect_delta(a, lanes, gaps)
    tickets = collect_tickets(a, delta, gaps)
    evidence = collect_evidence(a, tickets, delta, gaps, a.since)
    bundles = collect_bundles(a, gaps) if a.scope == "all" or a.bundles else None
    findings = assess(a, lanes, delta, tickets, evidence, bundles, gaps)
    for t in tickets["tickets"]:
        t.pop("comments", None)
    res = {"generated_at": now(), "line": a.line, "from": lanes["from"], "to": lanes["to"], "purpose": a.purpose, "scope": a.scope,
           "lanes": lanes, "delta": delta, "tickets": tickets, "evidence": evidence, "bundles": bundles, "findings": findings, "gaps": gaps,
           "counts": {"commits": sum(len(s["commits"]) for s in delta["services"]), "tickets": len(tickets["tickets"]),
                      "findings": {k: sum(1 for f in findings if f["severity"] == k) for k in SEV}}}
    md = render_md(res)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        stem = f"{datetime.date.today().isoformat()}-mh{a.line}-{lanes['from']}-{lanes['to']}"
        json.dump(res, open(os.path.join(a.out, stem + ".json"), "w"), ensure_ascii=False, indent=1)
        open(os.path.join(a.out, stem + ".md"), "w").write(md)
        print(f"written: {os.path.join(a.out, stem)}.{{json,md}}", file=sys.stderr)
    if a.json:
        print(json.dumps(res, ensure_ascii=False)); return
    print(md)
    if any(f["severity"] == "stop" for f in findings):
        sys.exit(EX_LANE)


def render_md(r):
    L = []
    L.append(f"# MH {r['line']}: {r['from']} → {r['to']}  ·  purpose {r['purpose']}  ·  scope {r['scope']}  ·  {r['generated_at']}")
    L.append("")
    L.append("| service | " + r["from"] + " | " + r["to"] + " | relation |")
    L.append("|---|---|---|---|")
    for s in r["lanes"]["services"]:
        f = (s["from"] or {}).get("version", "—").split(" 20")[0]; t = (s["to"] or {}).get("version", "—").split(" 20")[0]
        extra = "; ".join(f"{x['lane']} ahead" for x in s["other_lanes_ahead_of_to"])
        L.append(f"| {s['service']} | {f} | {t} | {s['relation'] or '?'}{(' · ' + extra) if extra else ''} |")
    L.append("")
    c = r["counts"]
    L.append(f"{c['commits']} commit(s) · {c['tickets']} ticket(s) · evidence read since {(r['evidence'] or {}).get('since')} · findings: " + ", ".join(f"{k} {v}" for k, v in c["findings"].items() if v))
    L.append("")
    L.append("## Findings (ranked; first 20)")
    for f in r["findings"][:20]:
        L.append(f"- **{f['severity']}** `{f['kind']}` — {f['what']}")
    if len(r["findings"]) > 20:
        L.append(f"- … {len(r['findings']) - 20} more in the JSON")
    L.append("")
    L.append("## Changes by ticket")
    ev = (r["evidence"] or {}).get("keys") or {}
    for t in r["tickets"]["tickets"]:
        if not t.get("exists"):
            L.append(f"- **{t['key']}** — not in Jira · {len(t['commits'])} commit(s)"); continue
        v = (ev.get(t["key"]) or {}).get("verdict", "none")
        L.append(f"- **{t['key']}** [{t['status']}] {t.get('summary','')[:90]} · {', '.join(t['services_in_delta']) or 'no commit in range'} · QA: **{v}**" + (f" · flags: {', '.join(t['flags'])}" if t["flags"] else ""))
    loose = [(s["service"], c) for s in r["delta"]["services"] for c in s["commits"] if not c["keys"]]
    if loose:
        L.append("")
        L.append("## Commits without a ticket")
        for svc, cm in loose:
            L.append(f"- {svc} `{cm['sha']}` {cm['kind']}: {cm['subject'][:100]}")
    if r.get("bundles") and r["bundles"].get("from"):
        b = r["bundles"]
        L.append("")
        L.append(f"## Bundles: {b['from']['name']} → {b['to']['name'] if b.get('to') else '?'}")
        L.append(f"identical {b['identical']} · changed {len(b['changed'])} · only in source {len(b['only_in_from'])} · only in target {len(b['only_in_to'])}")
        for ch in b["changed"][:30]:
            L.append(f"- {ch['service']}: {ch['from']} → {ch['to']} ({ch['direction']})")
    if r["gaps"]:
        L.append("")
        L.append("## Gaps (what could not be read)")
        for g in r["gaps"]:
            L.append(f"- {g}")
    return "\n".join(L) + "\n"


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description="Promotion assessment, first-hand and cross-checked.")
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    def common(p, scope=True):
        p.add_argument("line"); p.add_argument("src"); p.add_argument("dst")
        if scope:
            p.add_argument("--scope", choices=("app", "all"), default="app")
        p.add_argument("--json", action="store_true")
    common(sub.add_parser("lanes")); common(sub.add_parser("delta")); common(sub.add_parser("tickets"))
    p = sub.add_parser("evidence"); common(p); p.add_argument("--since")
    common(sub.add_parser("bundles"), scope=False)
    p = sub.add_parser("report"); common(p); p.add_argument("--purpose", choices=("regular", "prod-staging", "demo"), default="regular"); p.add_argument("--since"); p.add_argument("--bundles", action="store_true", help="include the bundle diff even with --scope app"); p.add_argument("--out", help="directory for <date>-mh<line>-<from>-<to>.{json,md}")
    a = ap.parse_args()
    {"lanes": cmd_lanes, "delta": cmd_delta, "tickets": cmd_tickets, "evidence": cmd_evidence, "bundles": cmd_bundles, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    main()
