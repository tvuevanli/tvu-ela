#!/usr/bin/env python3
"""Lane runtime facts: which config profiles a lane's service really runs, proven by what it did, read each pass.

  runtime.py [--env-file F] refresh [--lane L]... [--json]     instances and decisive keys per lane and service
  runtime.py prove <graph id> [--json]                          bind one graph to the lane, the UR Caller instance
                                                                that created it and the gateway that bridged it
  runtime.py show [--lane L] [--json]                           the store as last read
  runtime.py initconfig --lane L --file F                       keep a browser-read initConfig (non-secret keys)

Why: on 2026-11-09 a promotion read daily-wed's UR Caller config from `mx_service_wed` alone and concluded two wrong
things (`mediaBox.viaGateway` false, the HTML/YouTube mediabox whitelist missing). The service runs a chain of
profiles, and only runtime evidence says which. Nothing here is recorded by hand:

- **The services.** Every repo of the promotion that is a config-server client: its `bootstrap.properties`
  `spring.cloud.config.name` names the applications (disk is the fact). Its log index is the profiles'
  `elk.config.indexName`.
- **The lane's own profile.** The profile whose `elk.config.env` equals the lane's gateway token (release.yaml
  `gateway_versions`), else the one named `<prefix>_<token>`.
- **The instances.** The java-log over the last hours, grouped by `env` and host: an instance logging the lane
  profile's env proves that profile is the **last** layer (it wins `elk.config.env`).
- **The rest of the chain.** `prove <graph>`: the graph's `traceId` annotation → the java-log of that trace → the
  UR Caller instance (env, host) that created it; the graph's processes → the mqtt-gateway's `bridge OK target=<process id>`
  lines → the gateway instance. A profile that is not the lane's own and whose `mqtt.gatewayBoxPath` names that
  gateway's flavour (`-test` ↔ `mqtt_gateway_test1`) is an earlier layer; the proof records each step.
- **Decisive keys.** For each lane and service the keys whose value differs between the lane profile read alone
  and the proven chain — exactly where a one-profile read goes wrong — and the keys the chain sets over `default`.
- **initConfig.** The MediaHub backend's runtime `dynamicMap` as the browser received it (`ela browser env` hands it
  here), keys and non-secret values only, each with the lane the version panel proved.

Store: `<runtime>/facts/runtime/` — `lanes.json` (refresh), `proofs.json` (one per lane and service, newest kept),
`initconfig-<lane>.json`. Exit codes: 0 ok · 2 usage · 3 nothing proven · 5 a source unreadable.
"""
import argparse, datetime, glob, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
SITE = os.path.expanduser("~/.claude/ela/site.json")
EX_USAGE, EX_NONE, EX_SOURCE = 2, 3, 5
DEFAULT = "default"
LOG_HOURS = 6


def site():
    try:
        return json.load(open(SITE))
    except (OSError, ValueError):
        return {}


def store(*parts):
    root = os.environ.get("ELA_FACTS_RUNTIME") or site().get("runtime") or os.path.expanduser("~/.ela")
    d = os.path.join(root, "facts", "runtime")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, *parts) if parts else d


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path, default=None):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def l1(cap, *args, env_file=None, timeout=180):
    argv = ["python3", os.path.join(SKILLS, cap, f"{cap}.py")]
    if env_file:
        argv += ["--env-file", env_file]
    argv += list(args) + ["--json"]
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    if p.returncode != 0 or not p.stdout.strip():
        return None, (p.stderr or p.stdout).strip()[-300:]
    try:
        return json.loads(p.stdout), ""
    except ValueError:
        return None, "not json"


# ── which services, which profiles ────────────────────────────────────────────

def gateway_tokens():
    """lane → token, from release.yaml gateway_versions (the lanes the gateway answers for)."""
    sys.path.insert(0, os.path.join(SKILLS, "release"))
    import release as R  # noqa: E402
    gv = R.rmap("gateway_versions")
    out = {}
    for spec in gv.values():
        for lane, w in (spec.get("lanes") or {}).items():
            out.setdefault(lane, w.get("token"))
    return out


def config_apps(repo_dir):
    """The config applications a checkout reads at boot, from its own bootstrap file(s)."""
    names = []
    for f in glob.glob(os.path.join(repo_dir, "src/main/resources/bootstrap*.properties")) + \
            glob.glob(os.path.join(repo_dir, "src/main/resources/bootstrap*.yml")):
        for line in open(f, errors="replace"):
            m = re.match(r"\s*spring\.cloud\.config\.name\s*[=:]\s*(\S+)", line) or re.match(r"\s*name:\s*(\S+,\S+)", line)
            if m:
                names += [n.strip() for n in m.group(1).split(",") if n.strip()]
    return list(dict.fromkeys(names))


SERVICE_REPOS = {"ur-caller": "web/mx-service", "mediahub-backend": "web/tvu-media-hub"}


def repo_dir(repo):
    code = site().get("code") or ""
    for alias_dir in glob.glob(os.path.join(code, "*", repo.split("/", 1)[-1])):
        if os.path.isdir(os.path.join(alias_dir, ".git")):
            return alias_dir
    return None


def profile_envs(app, env_file):
    """profile → {env, index} from `elk.config.env` / `elk.config.indexName` (one read for all profiles)."""
    got, err = l1("configserver", "get", app, "all", "--key", "elk.config", env_file=env_file)
    if got is None:
        return None, err
    out = {}
    for prof, rows in (got.get("profiles") or {}).items():
        for r in rows:
            if r.get("key") == "elk.config.env":
                out.setdefault(prof, {})["env"] = r.get("value")
            elif r.get("key") == "elk.config.indexName":
                out.setdefault(prof, {})["index"] = r.get("value")
    return out, ""


def lane_profile(envs, token, app):
    if not token:
        return None
    exact = [p for p, v in envs.items() if v.get("env") == token and p != DEFAULT]
    if len(exact) == 1:
        return exact[0]
    named = [p for p in envs if p.endswith("_" + token)]
    return named[0] if len(named) == 1 else (exact[0] if exact else None)


def items(app, profile, env_file):
    got, err = l1("configserver", "get", app, profile, env_file=env_file)
    if got is None:
        return {}
    rows = got.get("items")
    if rows is None:
        rows = [r for v in (got.get("profiles") or {}).values() for r in v]
    return {r["key"]: r.get("value") for r in rows if r.get("status", 1) == 1}


def layered(app, chain, env_file, cache):
    merged = {}
    for p in chain:
        if (app, p) not in cache:
            cache[(app, p)] = items(app, p, env_file)
        for k, v in cache[(app, p)].items():
            merged[k] = {"value": v, "layer": p}
    return merged


# ── instances from the java-log ───────────────────────────────────────────────

def instances(index, env_file, hours=LOG_HOURS):
    t = datetime.datetime.now(datetime.timezone.utc)
    frm = (t - datetime.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    got, err = l1("logs", "java", "--app", index, "--from", frm, "--to", t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "--limit", "1000", env_file=env_file, timeout=240)
    if got is None:
        return None, err
    by = {}
    for r in got.get("lines") or []:
        e = by.setdefault(r.get("env"), {"lines": 0, "hosts": set(), "last": ""})
        e["lines"] += 1
        e["hosts"].add(r.get("host"))
        e["last"] = max(e["last"], r.get("time") or "")
    return {k: {"lines": v["lines"], "hosts": sorted(h for h in v["hosts"] if h), "last": v["last"][:16]}
            for k, v in by.items()}, ""


# ── refresh ───────────────────────────────────────────────────────────────────

def refresh(env_file, lanes=None):
    tokens = gateway_tokens()
    want = lanes or followed_lanes()
    out = {"read_at": now_iso(), "hours": LOG_HOURS, "lanes": {}, "gaps": []}
    proofs = read_json(store("proofs.json"), {}) or {}
    cache = {}
    for svc, repo in SERVICE_REPOS.items():
        d = repo_dir(repo)
        apps = config_apps(d) if d else []
        if not apps:
            out["gaps"].append(f"{svc}: no checkout or no bootstrap config name for {repo}")
            continue
        app = apps[-1]                       # the service's own application; the earlier names are shared ones
        envs, err = profile_envs(app, env_file)
        if envs is None:
            out["gaps"].append(f"{svc}: config server unreadable ({err})")
            continue
        index = next((v.get("index") for v in envs.values() if v.get("index")), svc)
        inst, err = instances(index, env_file)
        if inst is None:
            out["gaps"].append(f"{svc}: java-log unreadable ({err})")
            inst = {}
        for lane in want:
            token = tokens.get(lane)
            lp = lane_profile(envs, token, app)
            row = {"service": svc, "app": app, "config_names": apps, "log_index": index, "token": token,
                   "lane_profile": lp, "lane_env": (envs.get(lp) or {}).get("env") if lp else None}
            seen = inst.get(row["lane_env"]) if row["lane_env"] else None
            row["instance"] = seen
            proof = proofs.get(f"{lane}|{svc}")
            if proof and proof.get("chain"):
                row["chain"], row["chain_status"] = proof["chain"], "proven"
                row["chain_proof"] = {k: proof.get(k) for k in ("graph", "at", "steps")}
            elif lp and seen:
                row["chain"], row["chain_status"] = [DEFAULT, lp], "last layer proven, earlier layers unproven"
            elif lp:
                row["chain"], row["chain_status"] = [DEFAULT, lp], "unproven: no instance logs the lane profile's env"
            else:
                row["chain"], row["chain_status"] = [DEFAULT], "no lane profile"
            if lp:
                alone = layered(app, [DEFAULT, lp], env_file, cache)
                chained = layered(app, row["chain"], env_file, cache)
                diff = sorted(k for k in set(alone) | set(chained)
                              if (alone.get(k) or {}).get("value") != (chained.get(k) or {}).get("value"))
                row["differs_from_single_profile"] = [
                    {"key": k, "single": (alone.get(k) or {}).get("value"), "chain": (chained.get(k) or {}).get("value"),
                     "layer": (chained.get(k) or {}).get("layer")} for k in diff]
                row["set_over_default"] = sorted(k for k, v in chained.items() if v["layer"] != DEFAULT)
                row["effective"] = {k: v for k, v in chained.items() if v["layer"] != DEFAULT}
            out["lanes"].setdefault(lane, {})[svc] = row
    out["initconfig"] = initconfigs()
    write_json(store("lanes.json"), out)
    return out


def initconfigs():
    init = {}
    for f in glob.glob(store("initconfig-*.json")):
        j = read_json(f, {})
        if j.get("lane"):
            init[j["lane"]] = j
    return init


def followed_lanes():
    sys.path.insert(0, os.path.join(SKILLS, "release"))
    import release as R  # noqa: E402
    lanes = []
    for spec in R.rmap("lines").values():
        for role, ln in (spec.get("lanes") or {}).items():
            if role in ("daily", "prod") and ln not in lanes:
                lanes.append(ln)
    return lanes


# ── prove one graph ───────────────────────────────────────────────────────────

def walk(o, want, out):
    if isinstance(o, dict):
        for k, v in o.items():
            if k in want and not isinstance(v, (dict, list)):
                out.setdefault(k, []).append(v)
            walk(v, want, out)
    elif isinstance(o, list):
        for v in o:
            walk(v, want, out)
    return out


def prove(graph_id, env_file):
    steps = []
    raw, err = l1("graph", "graph", graph_id, "--raw", env_file=env_file, timeout=120)
    if raw is None:
        return {"graph": graph_id, "error": f"graph unreadable: {err}", "steps": steps}
    ann = (raw.get("metadata") or {}).get("annotations") or {}
    found = walk(raw, {"isMediaBox", "env", "environment"}, {})
    nodes = (raw.get("spec") or {}).get("nodes") or []
    mediabox = sum(1 for n in nodes if ((n.get("spec") or {}).get("options") or {}).get("isMediaBox"))
    genv = (found.get("env") or found.get("environment") or [None])[0]
    created = (raw.get("metadata") or {}).get("creationTimestamp") or ann.get("createTime")
    steps.append({"step": "graph", "env": genv, "createBy": ann.get("createBy"), "appName": ann.get("appName"),
                  "mediabox_nodes": mediabox, "nodes": len(nodes), "created": created})
    trace = ann.get("traceId")
    caller = None
    if trace:
        day = (created or now_iso())[:10]
        got, err = l1("logs", "java", "--trace", trace, "--date", day, "--days", "2", "--limit", "200",
                      env_file=env_file, timeout=180)
        hits = {}
        for r in (got or {}).get("lines") or []:
            k = (r.get("app"), r.get("env"))
            h = hits.setdefault(k, {"lines": 0, "hosts": set()})
            h["lines"] += 1
            h["hosts"].add(r.get("host"))
        callers = [(a, e, v) for (a, e), v in hits.items() if a == "ur-caller"]
        if callers:
            a, e, v = max(callers, key=lambda x: x[2]["lines"])
            caller = {"app": a, "env": e, "hosts": sorted(x for x in v["hosts"] if x), "lines": v["lines"]}
        steps.append({"step": "trace", "trace": trace, "ur_caller": caller,
                      "others": sorted(f"{a}[{e}]" for (a, e) in hits if a != "ur-caller"),
                      "error": err if got is None else None})
    det, err = l1("graph", "graph", graph_id, "-d", env_file=env_file, timeout=240)
    res = (det or {}).get("results") or []
    res = res[0] if isinstance(res, list) and res else (res if isinstance(res, dict) else {})
    if res:
        genv = genv or res.get("env")
        created = created or res.get("created_at")
        steps[0].update({"env": genv, "created": created, "email": res.get("email"), "phase": res.get("phase")})
    boxes = sorted({n.get("process_id") for n in res.get("nodes") or [] if n.get("process_id")})   # bridge target=<process id>
    gateway = None
    if boxes and created:
        t0 = datetime.datetime.strptime(created[:19], "%Y-%m-%dT%H:%M:%S")
        frm, to = (t0 - datetime.timedelta(minutes=1)), (t0 + datetime.timedelta(minutes=12))
        envs, pids = {}, set(boxes)
        # --grep filters on the client after the line limit, so read the window once and match every process here
        got, _ = l1("logs", "java", "--app", "mqtt-gateway", "--from", frm.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "--to", to.strftime("%Y-%m-%dT%H:%M:%SZ"), "--grep", "bridge", "--limit", "5000",
                    env_file=env_file, timeout=300)
        for r in (got or {}).get("lines") or []:
            m = re.search(r"target=([0-9a-f]{32})", r.get("message") or "")
            if m and m.group(1) in pids:
                envs[r.get("env")] = envs.get(r.get("env"), 0) + 1
        if envs:
            gateway = {"env": max(envs, key=envs.get), "bridge_lines": envs}
    steps.append({"step": "gateway", "processes": boxes, "gateway": gateway,
                  "note": None if boxes else "no process ids in the graph detail"})
    return {"graph": graph_id, "at": now_iso(), "graph_env": genv, "caller": caller, "gateway": gateway,
            "mediabox_nodes": mediabox, "steps": steps}


def chain_from_proof(p, env_file):
    """lane and chain from a proof: the lane whose profile env the caller logged; earlier layers by the gateway."""
    if not p.get("caller"):
        return None, None, "no UR Caller line for the graph's trace"
    app = config_apps(repo_dir(SERVICE_REPOS["ur-caller"]) or "")[-1:] or ["mx-service"]
    app = app[0]
    envs, err = profile_envs(app, env_file)
    if envs is None:
        return None, None, f"config server unreadable ({err})"
    tokens = gateway_tokens()
    lane = next((ln for ln, tok in tokens.items() if lane_profile(envs, tok, app) and
                 envs[lane_profile(envs, tok, app)].get("env") == p["caller"]["env"]), None)
    last = next((pr for pr, v in envs.items() if v.get("env") == p["caller"]["env"] and pr != DEFAULT), None)
    if not last:
        return None, None, f"no profile sets elk.config.env={p['caller']['env']}"
    chain = [DEFAULT]
    gw = (p.get("gateway") or {}).get("env") or ""
    flavour = "test" if "test" in gw else ("prod" if "prod" in gw else None)
    lane_items = items(app, last, env_file)
    if flavour and "mqtt.gatewayBoxPath" not in lane_items:
        def_items = items(app, DEFAULT, env_file)
        default_flavour = "test" if "test" in str(def_items.get("mqtt.gatewayBoxPath", "")) else "prod"
        if flavour != default_flavour:
            cands = [pr for pr in envs if pr not in (DEFAULT, last)
                     and flavour in str(items(app, pr, env_file).get("mqtt.gatewayBoxPath", ""))]
            if len(cands) == 1:
                chain.append(cands[0])
            elif cands:
                return lane, None, f"gateway {gw} fits several profiles: {', '.join(cands)}"
    chain.append(last)
    return lane, chain, ""


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_refresh(a):
    out = refresh(a.env_file, a.lane)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print_lanes(out, a.lane)
    sys.exit(EX_SOURCE if out["gaps"] and not out["lanes"] else 0)


def cmd_show(a):
    out = read_json(store("lanes.json"))
    if not out:
        print("no runtime facts yet — run: ela facts runtime refresh", file=sys.stderr)
        sys.exit(EX_NONE)
    out["initconfig"] = initconfigs()
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print_lanes(out, a.lane)


def print_lanes(out, only=None):
    print(f"runtime facts read {out['read_at']} (java-log {out['hours']}h)")
    for lane, svcs in out["lanes"].items():
        if only and lane not in only:
            continue
        print(f"── {lane}")
        for svc, r in svcs.items():
            inst = r.get("instance")
            seen = f"instance {r['lane_env']} on {', '.join(inst['hosts'])} ({inst['lines']} lines)" if inst else "no instance seen"
            print(f"  {svc}: chain {' → '.join(r['chain'])} ({r['chain_status']}) · {seen}")
            for d in r.get("differs_from_single_profile") or []:
                print(f"    ≠ {d['key']}: {r['lane_profile']} alone = {str(d['single'])[:50]} · chain = {str(d['chain'])[:50]} ({d['layer']})")
        ic = out.get("initconfig", {}).get(lane)
        if ic:
            print(f"  initConfig ({ic.get('read_at')}, panel lane {ic.get('panel_lane')}): " +
                  ", ".join(f"{k}={v}" for k, v in sorted(ic.get("keys", {}).items())
                            if not re.match(r"^<\w+>$", str(v)))[:600])
    for g in out.get("gaps") or []:
        print(f"  gap: {g}")


def cmd_prove(a):
    p = prove(a.graph, a.env_file)
    lane, chain, why = chain_from_proof(p, a.env_file) if not p.get("error") else (None, None, p["error"])
    p.update({"lane": lane, "chain": chain, "why_not": why or None})
    if lane and chain:
        proofs = read_json(store("proofs.json"), {}) or {}
        proofs[f"{lane}|ur-caller"] = p
        write_json(store("proofs.json"), proofs)
    if a.json:
        print(json.dumps(p, ensure_ascii=False, indent=1))
    else:
        c = p.get("caller") or {}
        g = p.get("gateway") or {}
        print(f"graph {a.graph}: env {p.get('graph_env')} · {p.get('mediabox_nodes')} mediabox node(s)")
        print(f"  created by ur-caller[{c.get('env')}] on {', '.join(c.get('hosts') or []) or '?'}"
              if c else "  creator: no UR Caller line for its trace")
        print(f"  bridged by {g.get('env')} ({sum((g.get('bridge_lines') or {}).values())} bridge lines)" if g
              else "  gateway: no bridge line for its processes")
        print(f"  lane {lane or '?'} · chain {' → '.join(chain) if chain else 'unproven'}" + (f" — {why}" if why else ""))
    sys.exit(0 if chain else EX_NONE)


SAFE_STR = re.compile(r"^(/[\w./-]*|[A-Za-z][\w-]{0,40})$")      # a path or one word: no host, no address


def cmd_initconfig(a):
    """Keep a browser-read initConfig: booleans, numbers, path-like and short word values; anything else as a shape."""
    raw = read_json(a.file, {}) or {}
    res = raw.get("initConfig") or raw.get("result") or raw
    keys = {}
    for k, v in (res.items() if isinstance(res, dict) else []):
        if isinstance(v, (bool, int, float)) or v is None:
            keys[k] = v
        elif isinstance(v, str) and re.search(r"(?i)token|secret|key|pass|sign", k):
            keys[k] = f"<{type(v).__name__}>"
        elif isinstance(v, str) and SAFE_STR.match(v):
            keys[k] = v
        elif isinstance(v, str) and re.match(r"^(https?://|wss?://)?[\w.-]+\.[a-z]{2,}(:\d+)?(/[\w./-]*)?$", v):
            path = re.sub(r"^(https?://|wss?://)?[\w.-]+(:\d+)?", "", v)
            keys[k] = f"<host>{path}"                 # the flavour (-test, -wed) lives in the path and the key, not the host
        else:
            keys[k] = f"<{type(v).__name__}>"
    rec = {"lane": a.lane, "panel_lane": raw.get("panel_lane") or a.lane, "read_at": raw.get("read_at") or now_iso(),
           "keys": keys, "missing_means": "a key absent here is absent at runtime; the frontend's own default applies"}
    write_json(store(f"initconfig-{a.lane}.json"), rec)
    print(json.dumps(rec, ensure_ascii=False, indent=1) if a.json else f"kept {len(keys)} initConfig key(s) for {a.lane}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("refresh", help="per lane and service: lane profile, instance seen, chain, decisive keys")
    p.add_argument("--lane", action="append"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("show", help="the store as last read"); p.add_argument("--lane", action="append"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("prove", help="bind a graph to its lane, its UR Caller instance and its gateway; record the chain")
    p.add_argument("graph"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("initconfig", help="keep a browser-read initConfig for a lane (non-secret keys only)")
    p.add_argument("--lane", required=True); p.add_argument("--file", required=True); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    a.env_file = a.env_file or os.environ.get("ELA_ENV_FILE") or site().get("env")
    {"refresh": cmd_refresh, "show": cmd_show, "prove": cmd_prove, "initconfig": cmd_initconfig}[a.cmd](a)


if __name__ == "__main__":
    main()
