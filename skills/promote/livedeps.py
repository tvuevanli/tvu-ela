#!/usr/bin/env python3
"""The services a promotion's code calls, read live on the target lane: which instance answers, at which build, and
what that build lacks.

  livedeps.py <report.json> [--json]        from a saved promote report (its lanes, delta, tickets)

Why: on 2026-11-09 four dependency facts surfaced only when the owner pushed: every deployed audio-mixer predated the
gateway leg the mediabox mixer needs (master since 10-13, every instance built 10-08 or earlier); the audio-mixer route
is version-controlled across prod1–5, A/B/C and test instances, so one lane's profile is not where to set its key;
the overlay service's collaborator secret was empty; orchestration differed per lane. None of it needs a guess:

1. **Edges** — the dependency map (`<published>/map/dependencies.yaml`, deps.py's artefact): each Feign client of a
   repo in the range, with its endpoints and, for a fixed-URL client, the config key that holds the URL.
2. **The URL on the target lane** — that key's effective value along the lane's proven profile chain (the fact
   store's runtime source; `configserver effective <app> <chain>`).
3. **The route** — the API gateway's own config (`tvu-zuul` / `default`, `zuul.routes.<r>.path`): a route with
   `metadata.versionControl` picks the instance by the user's version tag; its `urls` name every instance.
4. **Each instance's build** — `GET <instance>/base/version`, read now.
5. **What the build lacks** — the callee's checkout (`services.<name>.repo` in the map): commits on its mainline after
   the instance's build date; one that names a release ticket is high, the rest are listed for the reader.
6. **Which features** — the release tickets whose range commits touch the client file.
Eureka-routed edges (no fixed URL) are lane-local and listed with "version not readable from here".
"""
import argparse, datetime, glob, json, os, re, subprocess, sys, urllib.request

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
for d in ("release", "facts", "map"):
    sys.path.insert(0, os.path.join(SKILLS, d))
KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,5}-\d{2,6}\b")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
APP_OF = {"web/mx-service": "ur-caller", "web/tvu-media-hub": "mediahub-backend"}


def site():
    try:
        return json.load(open(os.path.expanduser("~/.claude/ela/site.json")))
    except (OSError, ValueError):
        return {}


def run(argv, timeout=120):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


UNREAD = {}   # source -> why it could not be read this pass; every row that needed it says so


def l1(cap, *args, timeout=120, absent_ok=False):
    """A sibling L1's --json. Exit 3 with absent_ok is "nothing there" ({}); any other failure is recorded in UNREAD
    and returns None, so a refused session never reads as "no dependencies"."""
    env = site().get("env")
    rc, out, err = run(["python3", os.path.join(SKILLS, cap, f"{cap}.py")] + (["--env-file", env] if env else []) + list(args) + ["--json"], timeout)
    if rc == 3 and absent_ok:
        return {}
    try:
        if rc == 0:
            return json.loads(out)
    except ValueError:
        err = "not json"
    UNREAD.setdefault(cap, (err or out).strip().splitlines()[-1][:160] if (err or out).strip() else f"exit {rc}")
    return None


def dep_map():
    import deps as D  # noqa: E402 — the map's own reader
    return D.load(os.path.join(site().get("map") or "", "dependencies.yaml"))


def http_version(url):
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/base/version", timeout=10) as r:
            body = r.read(300).decode("utf-8", "replace").strip()
            return r.status, body
    except Exception as e:  # noqa: BLE001 — an instance that does not answer is a finding, not a crash
        return getattr(e, "code", 0) or 0, str(e)[:80]


def zuul_routes():
    got = l1("configserver", "get", "tvu-zuul", "default", "--key", "zuul.routes.", "-v", timeout=180)
    if got is None:
        return None
    rows = (got or {}).get("items") or [r for v in ((got or {}).get("profiles") or {}).values() for r in v]
    routes = {}
    for r in rows:
        m = re.match(r"zuul\.routes\.([^.]+)\.(path|urls|metadata|url)$", r.get("key") or "")
        if m:
            routes.setdefault(m.group(1), {})[m.group(2)] = r.get("value")
    return routes


def route_for(url, routes):
    seg = re.sub(r"^https?://[^/]+", "", url or "").strip("/").split("/")[0]
    for name, r in routes.items():
        if str(r.get("path") or "").strip("/").split("/")[0] == seg:
            return name, r
    return None, None


def instances(route):
    try:
        meta = json.loads(route.get("metadata") or "{}")
    except ValueError:
        meta = {}
    vc = str(meta.get("versionControl") or "") in ("1", "true", "True")
    out = {}
    if vc:
        try:
            for name, v in (json.loads(route.get("urls") or "{}") or {}).items():
                if isinstance(v, dict) and str(v.get("url", "")).startswith("http"):
                    out[name] = v["url"]
        except ValueError:
            pass
    return vc, out


def checkout(repo):
    code = site().get("code") or ""
    base = (repo or "").split("/")[-1]
    for p in glob.glob(os.path.join(code, "*", base)):
        if os.path.isdir(os.path.join(p, ".git")):
            return p
    return None


def newer_commits(path, since_date, keys):
    rc, ref, _ = run(["git", "-C", path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
    ref = ref.strip() or "origin/master"
    rc, log, _ = run(["git", "-C", path, "log", "--no-merges", f"--since={since_date} 23:59", "--format=%h%x09%ad%x09%s", "--date=short", ref])
    commits = [dict(zip(("sha", "date", "subject"), l.split("\t", 2))) for l in log.splitlines() if l.strip()]
    for c in commits:
        c["release_keys"] = sorted(set(KEY_RE.findall(c["subject"])) & keys)
    return ref, commits


def effective(app, chain, key):
    got = l1("configserver", "effective", app, "+".join(p for p in chain if p != "default") or "default", "--key", key, absent_ok=True)
    if got is None:
        return None, "unread"
    for it in got.get("items") or []:
        if it.get("key") == key:
            return it.get("value"), it.get("layer")
    return None, None


def collect(report):
    to = report.get("to")
    keys = {t["key"] for t in (report.get("tickets") or {}).get("tickets") or [] if t.get("exists")}
    m = dep_map()
    edges, services = m.get("edges") or {}, m.get("services") or {}
    UNREAD.clear()
    rt = (l1("facts", "runtime", "show", "--lane", to) or {}).get("lanes", {}).get(to, {})
    routes = None
    out = []
    for s in (report.get("delta") or {}).get("services") or []:
        repo = s.get("repo")
        path = checkout(repo)
        row = rt.get(APP_OF.get(repo, ""), {})
        chain = row.get("chain") or ["default"]
        app = row.get("app")
        for e in (edges.get(repo) or {}).get("feign") or []:
            pin = e.get("pinned_url") or ""
            feats = []
            if path and e.get("file") and (s.get("to_build") or {}).get("sha") and (s.get("from_build") or {}).get("sha"):
                rc, log, _ = run(["git", "-C", path, "log", "--format=%s", f"{s['to_build']['sha']}..{s['from_build']['sha']}", "--", e["file"]])
                feats = sorted(set(KEY_RE.findall(log)) & keys)
            dep = {"caller": s["service"], "to": e.get("to"), "client": e.get("client"), "features": feats,
                   "endpoints": [f"{x.get('http')} {x.get('path')}" for x in e.get("endpoints") or []][:6]}
            km = re.match(r"\$\{([^:}]+)(?::([^}]*))?\}", pin)
            if not km:
                dep["routing"] = "eureka (lane-local); version not readable from here"
                if feats:
                    out.append(dep)
                continue
            key, code_default = km.group(1), km.group(2)
            if not app:
                dep.update({"key": key, "unread": f"no runtime row for {s['service']} on {to}; its profile chain is unknown"})
                out.append(dep)
                continue
            val, layer = effective(app, chain, key)
            dep.update({"key": key, "url_layer": layer, "chain": chain, "chain_status": row.get("chain_status")})
            if layer == "unread":
                dep["unread"] = f"config server: {UNREAD.get('configserver')}"
                out.append(dep)
                continue
            if not val:
                dep["code_default"] = code_default
                dep["routing"] = f"{key} not set on {to}'s chain; the code default applies" + (f": {code_default}" if code_default else " (none: the client has no URL)")
                if not code_default:
                    out.append(dep)
                    continue
                val = code_default
            if routes is None:
                routes = zuul_routes()
            if routes is None:
                dep["unread"] = f"zuul routes: {UNREAD.get('configserver')}"
                out.append(dep)
                continue
            rname, route = route_for(val, routes)
            vc, inst = instances(route) if route else (False, {})
            dep["route"] = rname
            dep["version_controlled"] = vc
            targets = inst if vc else {"(the route)": val}
            repo_c = checkout((services.get(e.get("to")) or {}).get("repo"))
            dep["instances"] = []
            for name, url in sorted(targets.items()):
                st, body = http_version(url)
                ver = body if st == 200 else None
                d = DATE_RE.search(ver or "")
                inst_row = {"instance": name, "status": st, "version": ver, "build_date": d.group(1) if d else None}
                if repo_c and inst_row["build_date"]:
                    ref, newer = newer_commits(repo_c, inst_row["build_date"], keys)
                    inst_row.update({"mainline": ref, "newer_commits": len(newer), "newest": newer[:4],
                                     "missing_release_keys": sorted({k for c in newer for k in c["release_keys"]})})
                dep["instances"].append(inst_row)
            dep["routing"] = (f"route {rname} is version-controlled: the user's version tag picks one of {len(inst)} instance(s); "
                              f"a key set in one lane's profile reaches only that lane's instance") if vc else f"route {rname or '?'}"
            out.append(dep)
    return out


def findings(deps, to):
    f = [("medium", f"{src} unread this pass: {why}") for src, why in sorted(UNREAD.items())]
    for d in deps:
        if d.get("unread"):
            f.append(("medium", f"{d['caller']} → {d['to']} ({d.get('key')}): unread — {d['unread']}"
                                + (f" (features calling it: {', '.join(d['features'])})" if d.get("features") else "")))
            continue
        if "code_default" in d:
            dflt = d["code_default"] or ""
            f.append(("high" if (not dflt or re.search(r"-dev\b|dev\.|-test\b|test\.", dflt)) else "medium",
                      f"{d['caller']} → {d['to']}: {d['key']} not set on {to}'s chain; the code default applies: "
                      + (dflt or "none, the client has no URL")))
        for i in d.get("instances") or []:
            if i.get("missing_release_keys"):
                f.append(("high", f"{d['to']} {i['instance']} ({i['version']}) lacks commits for {', '.join(i['missing_release_keys'])} "
                                  f"that {d['caller']} calls through {d.get('client')}"))
            elif i.get("newer_commits"):
                f.append(("medium" if d.get("features") else "note",
                          f"{d['to']} {i['instance']} built {i['build_date']}: {i['newer_commits']} commit(s) on {i['mainline']} since — "
                          + "; ".join(f"{c['sha']} {c['subject'][:50]}" for c in i["newest"][:3])
                          + (f" (features in this release calling it: {', '.join(d['features'])})" if d.get("features") else "")))
            if i.get("status") != 200:
                f.append(("medium", f"{d['to']} {i['instance']}: /base/version answered {i['status']} — unread, not undeployed"))
        if d.get("version_controlled"):
            f.append(("note", f"{d['to']}: {d['routing']}"))
    return f


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = json.load(open(a.report))
    deps = collect(r)
    if a.json:
        print(json.dumps({"deps": deps, "findings": findings(deps, r.get("to"))}, ensure_ascii=False, indent=1)); return
    fs = findings(deps, r.get("to"))
    print(f"live dependencies on {r.get('to')}: {len(deps)} edge(s) read, {len(fs)} finding(s)"
          + (f"; unread: {', '.join(UNREAD)}" if UNREAD else ""))
    for sev, what in fs:
        print(f"[{sev}] {what}")


if __name__ == "__main__":
    main()
