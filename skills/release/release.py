#!/usr/bin/env python3
"""Release facts, read first-hand — userservice (GM bundles, env versions), Jenkins (builds), the map.
L1: subcommands, --json, stdlib only. No store, no scheduler: every answer is the source's current state.

  bundles  [line]                       GM bundles for a line prefix (default mh2.1@), newest first
  bundle   <name|id>                    a bundle's bill of materials (serviceTagList)
  envs     [service]                    versions per environment tag from userservice (prod host); --qa for the tvutest host
  builds   <job|service> [--limit N]    Jenkins builds: number, version, result, branch, sha, time
  drift    [line]                       GM service names in the newest bundle vs map/services.yaml gm_names
  login                                 tvutest login → prints the QA SID to put in .env as TVUTEST_SID

Config: site.json `services` (userservice, userservice-test, jenkins urls) · <records>/map/release.yaml (service ids,
job → service) · .env USERSERVICE_ADMIN_SID
(pasted from a browser cookie — expires; HTTP 402 "no login" means paste a fresh one), TVUTEST_ACCOUNT/
TVUTEST_PASSWORD (login flow), TVUTEST_SID (cached login).
Exit codes: 0 ok · 2 usage · 3 not found · 4 auth (SID expired) · 5 remote error.
"""
import argparse, hashlib, json, os, re, signal, sys, urllib.error, urllib.parse, urllib.request

EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE = 2, 3, 4, 5
SITE = os.path.expanduser("~/.claude/ela/site.json")

def _release_map():
    """<records>/map/release.yaml — which userservice service ids publish which versions, and Jenkins job → service.
    World facts live in the knowledge base, not here; site.json `map` points at the directory."""
    path = os.path.join(site().get("map", ""), "release.yaml")
    try:
        text = open(path).read()
    except OSError:
        print(f"no {path} — the release map lives in the knowledge base (map/release.yaml); see /ela:release", file=sys.stderr); sys.exit(EX_USAGE)
    out, section = {}, None
    for line in text.splitlines():
        line = re.sub(r"\s+#.*$", "", line.rstrip())
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([a-z_]+):\s*$", line)
        if m:
            section = out.setdefault(m.group(1), {}); continue
        m = re.match(r"^  ([^:#\s]+):\s*(.+?)\s*$", line)
        if m and section is not None:
            v = m.group(2)
            try:
                v = json.loads(v)
            except ValueError:
                pass
            section[m.group(1)] = [tuple(x) for x in v] if isinstance(v, list) else v
    return out


_MAP = None
def rmap(key):
    global _MAP
    if _MAP is None:
        _MAP = _release_map()
    return _MAP.get(key) or {}


def env_value(key, env_file=None):
    v = os.environ.get(key)
    if v:
        return v
    for path in filter(None, [env_file, os.environ.get("ELA_ENV_FILE")]):
        try:
            for line in open(path):
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].rstrip("\n")
        except OSError:
            continue
    return None


def site():
    try:
        return json.load(open(SITE))
    except Exception:
        return {}


def http(url, payload=None, cookie=None, timeout=20):
    headers = {"Accept": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=json.dumps(payload).encode() if payload is not None else None, headers=headers, method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw.strip().startswith((b"{", b"[")) else raw.decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw[:300]
    except Exception as e:
        return 0, str(e)[:200]


def _service_url(name):
    url = (site().get("services", {}).get(name) or {}).get("url")
    if not url:
        print(f"site.json services.{name}.url is not set — run /ela:setup", file=sys.stderr); sys.exit(EX_USAGE)
    return url.rstrip("/")


class US:
    def __init__(self, env_file, qa=False):
        s = site().get("services", {})
        self.qa = qa
        self.host = _service_url("userservice-test" if qa else "userservice")
        self.env_file = env_file
        self.sid = env_value("TVUTEST_SID" if qa else "USERSERVICE_ADMIN_SID", env_file)
        if qa and not self.sid:
            self.sid = tvutest_login(env_file, self.host)

    def call(self, path, payload=None):
        if not self.sid:
            print("no userservice SID — paste USERSERVICE_ADMIN_SID from a browser cookie into the env file (or `login` for tvutest)", file=sys.stderr); sys.exit(EX_AUTH)
        st, body = http(self.host + path, payload, cookie=f"SID={self.sid}")
        if self.qa and (st in (401, 402, 403) or (isinstance(body, str) and "no login" in body)):
            # a tvutest SID lives two hours; log in again once and retry rather than asking a human
            self.sid = tvutest_login(self.env_file, self.host)
            st, body = http(self.host + path, payload, cookie=f"SID={self.sid}")
        if st in (401, 402, 403) or (isinstance(body, str) and "no login" in body):
            which = "TVUTEST_SID (run `release login`)" if self.qa else "USERSERVICE_ADMIN_SID (paste a fresh SID from the browser)"
            print(f"userservice {self.host}: session rejected (HTTP {st}) — refresh {which}", file=sys.stderr); sys.exit(EX_AUTH)
        if st != 200:
            print(f"userservice {path}: HTTP {st} {str(body)[:200]}", file=sys.stderr); sys.exit(EX_REMOTE)
        return body


def tvutest_login(env_file, host):
    acc, pw = env_value("TVUTEST_ACCOUNT", env_file), env_value("TVUTEST_PASSWORD", env_file)
    if not acc or not pw:
        print("no TVUTEST_ACCOUNT / TVUTEST_PASSWORD in the env file", file=sys.stderr); sys.exit(EX_AUTH)
    st, body = http(host + "/userAuth/token/getToken", {"email": acc, "password": hashlib.sha512(pw.encode()).hexdigest(), "expireTime": 7200})
    result = (body or {}).get("result") if isinstance(body, dict) else {}
    sid = (result or {}).get("token") or (result or {}).get("sid") or (body or {}).get("sid") if isinstance(body, dict) else None
    if not sid:
        print(f"tvutest login failed: HTTP {st} {str(body)[:200]}", file=sys.stderr); sys.exit(EX_AUTH)
    return str(sid).strip()


# ── bundles ──────────────────────────────────────────────────────────────────

def when(v):
    """epoch ms | epoch s | iso → 'YYYY-MM-DD HH:MM'."""
    import datetime
    try:
        n = float(v)
        if n > 1e12: n /= 1000
        return datetime.datetime.fromtimestamp(n).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(v or "")[:16]


def bundle_list(us, line, limit=50):
    body = us.call("/userGroup/user-group/tagBundle/page",
                   {"bundleName": line, "operator": "", "createStartTime": "", "createEndTime": "", "pageNum": 1, "pageSize": limit})
    return ((body or {}).get("result") or {}).get("list") or []


def bundle_detail(us, bundle_id):
    body = us.call(f"/userGroup/user-group/tagBundle/getDetail?bundleId={urllib.parse.quote(str(bundle_id))}")
    return (body or {}).get("result") or {}


def cmd_bundles(a):
    us = US(a.env_file, a.qa)
    rows = bundle_list(us, a.line, a.limit)
    rows.sort(key=lambda x: str(x.get("createTime") or ""), reverse=True)
    if a.json:
        print(json.dumps({"line": a.line, "count": len(rows), "bundles": rows}, ensure_ascii=False)); return
    if not rows:
        print(f"no bundles for {a.line!r}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    for b in rows:
        print(f"{str(b.get('bundleName')):<32} {str(b.get('bundleId')):<22} {when(b.get('createTime')):<17} {b.get('operator') or ''}")


def resolve_bundle(us, ref):
    if re.fullmatch(r"\d{15,20}", ref):
        return ref, ref
    line = ref.split("@")[0] + "@" if "@" in ref else ref
    rows = bundle_list(us, line, 50)
    hit = next((b for b in rows if str(b.get("bundleName")) == ref), None)
    if not hit:
        names = ", ".join(str(b.get("bundleName")) for b in rows[:8])
        print(f"bundle {ref!r} not found; nearest: {names}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    return str(hit["bundleId"]), str(hit["bundleName"])


def cmd_bundle(a):
    us = US(a.env_file, a.qa)
    bid, name = resolve_bundle(us, a.ref)
    detail = bundle_detail(us, bid)
    items = detail.get("serviceTagList") or []
    if a.json or a.raw:
        print(json.dumps({"bundle": name, "bundleId": bid, "detail": detail} if a.raw else
                         {"bundle": name, "bundleId": bid, "count": len(items), "services": items}, ensure_ascii=False)); return
    print(f"# bundle {name}  id {bid}  {len(items)} service(s)")
    if items:
        keys = [k for k in ("serviceName", "tagName", "version", "tag", "type", "serviceId") if k in items[0]]
        print("  " + "  ".join(f"{k:<28}" if k == "serviceName" else f"{k:<20}" for k in keys))
        for it in sorted(items, key=lambda x: str(x.get("serviceName") or "")):
            print("  " + "  ".join(f"{str(it.get(k)):<28}" if k == "serviceName" else f"{str(it.get(k)):<20}" for k in keys))
        extra = sorted(set(items[0].keys()) - set(keys))
        if extra:
            print(f"  (other fields: {', '.join(extra)} — use --raw)")


# ── env versions ──────────────────────────────────────────────────────────────

def cmd_envs(a):
    us = US(a.env_file, a.qa)
    want = (a.service or "").lower()
    out = []
    for svc_id, slugs in rmap("qa_service_ids" if a.qa else "service_ids").items():
        if want and not any(want in slug for slug, _ in slugs):
            continue
        body = us.call(f"/userGroup/user-group/tag/getTagVersionList?serviceId={svc_id}")
        r = body.get("result") if isinstance(body, dict) else None
        entries = r if isinstance(r, list) else (body.get("data") if isinstance(body, dict) and isinstance(body.get("data"), list) else (r or {}).get("list") or [])
        for slug, field in slugs:
            if want and want not in slug:
                continue
            for e in entries:
                out.append({"service": slug, "tag": e.get("tagName"), "version": " ".join(str(e.get(field) or "").split()), "updated": when(e.get("updateTime") or e.get("createTime"))})
    if a.json:
        print(json.dumps({"host": us.host, "rows": out}, ensure_ascii=False)); return
    if not out:
        print(f"no env versions for {a.service!r}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    cur = None
    for r in sorted(out, key=lambda x: (x["service"], str(x["tag"]))):
        if r["service"] != cur:
            cur = r["service"]; print(f"# {cur}")
        print(f"  {str(r['tag']):<28} {str(r['version']):<28} {str(r['updated'] or '')[:19]}")


# ── jenkins ───────────────────────────────────────────────────────────────────

def cmd_builds(a):
    base = _service_url("jenkins")
    JOBS = rmap("jobs")
    job = a.job
    if job not in JOBS:
        by_service = {v: k for k, v in JOBS.items()}
        job = by_service.get(job) or next((k for k in JOBS if a.job.lower() in k), None)
        if not job:
            print(f"unknown job or service {a.job!r}; jobs: {', '.join(JOBS)}", file=sys.stderr); sys.exit(EX_USAGE)
    tree = f"builds[number,displayName,result,timestamp,url,actions[lastBuiltRevision[branch[name,SHA1]]]]{{0,{a.limit}}}"
    st, body = http(f"{base}/job/{urllib.parse.quote(job, safe='')}/api/json?tree={urllib.parse.quote(tree, safe='[],:{}')}", timeout=30)
    if st != 200 or not isinstance(body, dict):
        print(f"jenkins {job}: HTTP {st} {str(body)[:200]}", file=sys.stderr); sys.exit(EX_REMOTE)
    rows = []
    for b in body.get("builds") or []:
        rev = next((x.get("lastBuiltRevision") for x in b.get("actions") or [] if isinstance(x, dict) and x.get("lastBuiltRevision")), {}) or {}
        br = (rev.get("branch") or [{}])[0]
        m = re.search(r"v?(\d+\.\d+\.\d+(?:\.\d+)?)\s*build\s*(\d+)", b.get("displayName") or "")
        rows.append({"job": job, "service": JOBS[job], "number": b.get("number"), "display": b.get("displayName"), "version": m.group(1) if m else None,
                     "result": b.get("result"), "branch": (br.get("name") or "").replace("refs/remotes/origin/", ""), "sha": (br.get("SHA1") or "")[:12],
                     "time": __import__("datetime").datetime.fromtimestamp((b.get("timestamp") or 0) / 1000).strftime("%Y-%m-%d %H:%M"), "url": b.get("url")})
    if a.json:
        print(json.dumps({"job": job, "service": JOBS[job], "builds": rows}, ensure_ascii=False)); return
    print(f"# {job}  ({JOBS[job]})")
    for r in rows:
        print(f"  #{r['number']:<5} {str(r['version']):<12} {str(r['result']):<9} {r['branch']:<20} {r['sha']:<12} {r['time']}")


# ── drift: bundle vs services.yaml ────────────────────────────────────────────

def cmd_drift(a):
    us = US(a.env_file, a.qa)
    rows = bundle_list(us, a.line, 50)
    rows.sort(key=lambda x: str(x.get("createTime") or ""), reverse=True)
    if not rows:
        print(f"no bundles for {a.line!r}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    b = rows[0]; items = bundle_detail(us, str(b["bundleId"])).get("serviceTagList") or []
    in_bundle = {str(it.get("serviceName") or "").strip() for it in items} - {""}
    mapdir = site().get("map", "")
    known = set()
    try:
        lines = open(os.path.join(mapdir, "services.yaml")).read().splitlines()
    except OSError:
        print(f"no {os.path.join(mapdir, 'services.yaml')} — site.json `map` must point at the knowledge base's map/", file=sys.stderr); sys.exit(EX_USAGE)
    for line in lines:
        m = re.match(r"^    gm_names: (.+)$", line)
        if m:
            try: known |= set(json.loads(m.group(1)))
            except ValueError: pass
    only_bundle, only_map = sorted(in_bundle - known), sorted(known - in_bundle)
    if a.json:
        print(json.dumps({"bundle": b.get("bundleName"), "in_bundle": sorted(in_bundle), "only_in_bundle": only_bundle, "only_in_services_yaml": only_map}, ensure_ascii=False)); return
    print(f"# {b.get('bundleName')}  {len(in_bundle)} services in bundle · {len(known)} GM names in services.yaml")
    print("in the bundle, not in services.yaml:"); [print("  " + x) for x in only_bundle] or print("  —")
    print("in services.yaml, not in this bundle:"); [print("  " + x) for x in only_map] or print("  —")


def cmd_login(a):
    host = _service_url("userservice-test")
    sid = tvutest_login(a.env_file, host)
    print(json.dumps({"TVUTEST_SID": sid}) if a.json else f"TVUTEST_SID={sid}\n(put it in the env file; it expires in 2h)")


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description="Release facts, first-hand.")
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("bundles"); p.add_argument("line", nargs="?", default="mh2.1@"); p.add_argument("--limit", type=int, default=50); p.add_argument("--qa", action="store_true"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("bundle"); p.add_argument("ref", help="bundle name (mh2.1@daily-wed-s1-d31) or id"); p.add_argument("--qa", action="store_true"); p.add_argument("--json", action="store_true"); p.add_argument("--raw", action="store_true")
    p = sub.add_parser("envs"); p.add_argument("service", nargs="?"); p.add_argument("--qa", action="store_true"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("builds"); p.add_argument("job"); p.add_argument("--limit", type=int, default=15); p.add_argument("--json", action="store_true")
    p = sub.add_parser("drift"); p.add_argument("line", nargs="?", default="mh2.1@"); p.add_argument("--qa", action="store_true"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("login"); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    {"bundles": cmd_bundles, "bundle": cmd_bundle, "envs": cmd_envs, "builds": cmd_builds, "drift": cmd_drift, "login": cmd_login}[a.cmd](a)


if __name__ == "__main__":
    main()
