#!/usr/bin/env python3
"""UR graph capability. L1: subcommands, --json, meaningful exit codes, stdlib only. Reads are first-hand;
the four actions (connect · exec · start · stop) are Evan's hand at the shell — start/stop ask y/N.

What Evan's `ura` does by hand, without setting an environment first: a graph or process id is
probed across environments in a fixed order (MediaHub 2.1 prod first) until one answers.

  graph    <graphId>  [-e X | --all] [-d] [-c]   node table in pipeline order; -d box location/id + image, -c connections
  process  <processId> [--env X]           one process: type, box public/private ip, control port, box id
  box      <boxId>     [--env X]           one box
  graphs   [email|alias] [--env X | --all] graphs owned by an email; no argument = me (site.json `emails`)
  resolve  <id> [--email owner]            detect the id shape and route: graph · process · object → its running graphs (via Object Service tangibles)
  envs                                     the probe order
  connect  <ip|boxId|processId> [--env]    ssh to the box as root            (ura connect)
  exec     <processId> [--env]             docker exec -it -w /var/log <pid> bash on its box   (ura exec)
  start    <processId> --url U --format F --shm S [--name N] [--yes]   start a Sender working process   (ura start)
  stop     <processId> [--yes]             stop a Sender working process    (ura stop)

Environments live in the URL path: https://ur.tvunetworks.com/<env>/j2n/… and …/<env>/pilot/….
Probe order (first answer wins): UR_ENV_ORDER in the env file (comma-separated), else prod3, prod2, test2.
Credentials: UR_ACCESS_KEY (+ UR_BASE_HOST) from $UR_ACCESS_KEY → --env-file → $ELA_ENV_FILE.
Exit codes: 0 ok · 2 usage · 3 not found on any env · 4 auth · 5 remote error.
"""
import argparse, json, os, re, shutil, signal, sys, urllib.error, urllib.parse, urllib.request

EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE = 2, 3, 4, 5
# Probe order — three envs cover everything Evan touches: prod3 (MediaHub 2.1, answers 2.0 too), prod2 (older
# prod), test2 (test). Sequential fallback; a miss costs one round-trip per env. Override with UR_ENV_ORDER.
DEFAULT_ORDER = ["prod3", "prod2", "test2"]
ALIASES = {"p": "prod", "t": "test", "t2": "test2", "t1": "test1"}


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


class UR:
    def __init__(self, env_file):
        self.key = env_value("UR_ACCESS_KEY", env_file)
        if not self.key:
            print("no UR_ACCESS_KEY (env, $ELA_ENV_FILE, or --env-file)", file=sys.stderr); sys.exit(EX_AUTH)
        self.host = (env_value("UR_BASE_HOST", env_file) or "https://ur.tvunetworks.com").rstrip("/")
        order = env_value("UR_ENV_ORDER", env_file)
        self.order = [e.strip() for e in order.split(",") if e.strip()] if order else DEFAULT_ORDER

    def get(self, env, path):
        """→ (status, body_json_or_None). 5xx and 404 with an empty body read as 'not here'."""
        url = f"{self.host}/{env}{path}"
        req = urllib.request.Request(url, headers={"AccessKey": self.key, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw.strip() else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, (json.loads(raw) if raw.strip() else None)
            except ValueError:
                return e.code, None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            print(f"ur {env}: {str(e)[:80]}", file=sys.stderr); return 0, None

    def probe(self, path, env=None, accept=lambda body: body is not None):
        """Try envs in order; return (env, body) for the first 200 whose body passes `accept`."""
        envs = [normalise(env)] if env else self.order
        seen_auth = []
        for e in envs:
            status, body = self.get(e, path)
            if status == 200 and accept(body):
                return e, body
            if status == 401:
                seen_auth.append(e)
        if seen_auth:
            print(f"401 on {', '.join(seen_auth)} — the access key is not valid there", file=sys.stderr)
        return None, None


def env_name(v):
    """Production8 / Test2 (Pilot) and prod8 / test2 (J2N) name the same environment."""
    v = (v or "").strip()
    m = re.fullmatch(r"(?i)production(\d*)", v)
    if m:
        return "prod" + m.group(1)
    return v.lower()


def normalise(env):
    env = env.strip().lower()
    if env in ALIASES:
        return ALIASES[env]
    m = re.fullmatch(r"p(\d+)", env)
    if m:
        return f"prod{m.group(1)}"
    return env.replace("prod-", "prod").replace("test-", "test")


def unwrap(body):
    """J2N wraps in {value: <json or json-string>}."""
    if not isinstance(body, dict):
        return body
    v = body.get("value", body)
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return None
    return v


def detect(id_):
    if re.fullmatch(r"[0-9A-Z]{26}", id_):
        return "graph"
    if re.fullmatch(r"[0-9a-f]{32}", id_):
        return "process"
    if re.fullmatch(r"\d{19}", id_):
        return "object"
    return ""


# ── graph ────────────────────────────────────────────────────────────────────

def parse_graph(v):
    spec = (v or {}).get("spec") or {}
    nodes = []
    for n in spec.get("nodes") or []:
        meta, sp, st = n.get("metadata") or {}, n.get("spec") or {}, n.get("status") or {}
        pi = st.get("processInfo") or {}
        opts = sp.get("options") or {}
        nodes.append({
            "name": meta.get("name", ""), "type": sp.get("type", ""),
            "process_id": pi.get("processId") or "", "box_id": pi.get("boxId") or st.get("evaluatedBoxId") or "",
            "public_ip": pi.get("publicIpv4") or "", "private_ip": pi.get("privateIpv4") or "",
            "image": opts.get("dockerImage") or sp.get("image") or sp.get("version") or "",
            "tangible_id": st.get("tangibleId") or "", "dispatched": bool(st.get("dispatched")),
            "errors": st.get("errors") or [],
        })
    edges = []
    for e in spec.get("edges") or []:
        traffics = (e.get("status") or {}).get("traffics") or []
        kinds = sorted({t.get("localShmType") or t.get("outputShmType") or t.get("shmType") or t.get("type") or "" for t in traffics} - {""})
        edges.append({"from": e.get("from", ""), "to": e.get("to", ""), "shm": kinds})
    idx = {n["name"]: i for i, n in enumerate(nodes)}
    indeg = [0] * len(nodes); adj = [[] for _ in nodes]
    for e in edges:
        if e["from"] in idx and e["to"] in idx:
            adj[idx[e["from"]]].append(idx[e["to"]]); indeg[idx[e["to"]]] += 1
    queue = [i for i, d in enumerate(indeg) if d == 0]; order = []
    while queue:
        i = queue.pop(0); order.append(i)
        for j in adj[i]:
            indeg[j] -= 1
            if indeg[j] == 0:
                queue.append(j)
    order += [i for i in range(len(nodes)) if i not in order]
    meta = (v or {}).get("metadata") or {}
    ann = meta.get("annotations") or {}
    st = (v or {}).get("status") or {}
    return {"graph_id": meta.get("name") or ann.get("app.tvunetworks.com/id") or "",
            "env": env_name(ann.get("app.tvunetworks.com/environment", "")), "app": ann.get("appName", ""),
            "business_type": ann.get("businessType", ""), "business_name": ann.get("businessName", ""),
            "business_id": ann.get("businessId", ""), "object_id": ann.get("objectId", ""),
            "email": ann.get("email", ""), "user_id": ann.get("userId", ""), "root_group": ann.get("rootGroupId", ""),
            "phase": st.get("phase", ""), "created_at": st.get("createdAt", ""), "deleted_at": st.get("deletedAt", ""),
            "errors": st.get("errors") or [], "nodes": [nodes[i] for i in order], "edges": edges}


TTY = sys.stdout.isatty()
def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if TTY else str(text)
BOLD, DIM, CYAN, GREEN = "1", "2", "36", "32"


def enrich_nodes(ur, env, nodes):
    """One Pilot nodeOrigins call per node: control port, box id and the box's cloud placement."""
    for n in nodes:
        n.update({"control_port": 0, "box_type": "", "platform": "", "region": ""})
        if not n["process_id"]:
            continue
        st, body = ur.get(env, f"/pilot/api/v1/nodeOrigins/{n['process_id']}/nodeOrginsByNodeDetails")
        if st != 200 or not isinstance(body, dict):
            continue
        box = body.get("box") if isinstance(body.get("box"), dict) else {}
        n["public_ip"] = n["public_ip"] or _none(body.get("publicIp")) or box.get("publicIpv4") or ""
        n["private_ip"] = n["private_ip"] or _none(body.get("privateIp")) or box.get("privateIpv4") or ""
        n["control_port"] = _none(body.get("mediaBoxControlPort")) or _none(body.get("controlPort")) or 0
        n["box_id"] = _none(body.get("boxId")) or box.get("id") or n["box_id"]
        n["box_type"], n["platform"], n["region"] = box.get("type") or "", box.get("platform") or "", box.get("region") or ""
    return nodes


def box_location(n):
    if n.get("box_type") == "ManagedCloud":
        return " / ".join(x for x in (n.get("platform"), n.get("region")) if x) or "ManagedCloud"
    return n.get("box_type") or ""


def print_graph(a, via, g):
    title = " · ".join(x for x in [g["business_type"], g["business_name"], g["email"]] if x)
    print(_c(BOLD, f"Graph: {g['graph_id'] or a.graph_id}") + f"  env {g['env'] or '?'} (answered via {via})  {g['phase']}  {title}")
    if g["object_id"]:
        print(_c(DIM, f"object {g['object_id']}  business {g['business_id']}  app {g['app']}  created {g['created_at'][:19]}"))
    print()
    cols = [("Node", 5), ("Type", 18), ("Process ID", 32), ("Public IP", 15), ("Private IP", 15), ("Control Port", 12)]
    if a.detail:
        cols += [("Box Location", 20), ("Box ID", 32)]
    print(_c(BOLD, "  " + "  ".join(f"{h:<{w}}" for h, w in cols)))
    print(_c(DIM, "  " + "  ".join("─" * w for _, w in cols)))
    for i, n in enumerate(g["nodes"], 1):
        row = [_c(CYAN, f"{'[' + str(i) + ']':<5}"), _c(BOLD, f"{n['type'][:18]:<18}"), _c(DIM, f"{n['process_id']:<32}"),
               f"{n['public_ip'] or '(none)':<15}", f"{n['private_ip'] or '(none)':<15}", _c(GREEN, f"{n['control_port'] or 'N/A':<12}")]
        if a.detail:
            row += [f"{box_location(n) or '(none)':<20}", _c(DIM, n['box_id'] or '(none)')]
        print("  " + "  ".join(row))
        if a.detail:
            print(_c(DIM, f"  {'':<5}  {'':<18}  {n['image'] or '(no image)'}   {n['name']}"))
    if a.connections and g["edges"]:
        idx = {n["name"]: i for i, n in enumerate(g["nodes"], 1)}
        print(); print(_c(BOLD, "  Connections")); print(_c(DIM, "  " + "─" * 58))
        for e in sorted(g["edges"], key=lambda e: (idx.get(e["from"], 999), idx.get(e["to"], 999))):
            fi, ti = idx.get(e["from"]), idx.get(e["to"])
            ft = g["nodes"][fi - 1]["type"] if fi else e["from"]
            tt = g["nodes"][ti - 1]["type"] if ti else e["to"]
            print(f"  {_c(CYAN, '[' + str(fi or '?') + ']')} {ft:<18} {_c(DIM, '──')} {(','.join(e['shm']) or 'N/A'):<32} {_c(DIM, '──►')} {_c(CYAN, '[' + str(ti or '?') + ']')} {tt}")
    errs = [x for n in g["nodes"] for x in n["errors"]] + g["errors"]
    if errs:
        print(); print("  errors: " + "; ".join(str(x)[:120] for x in errs[:5]))
    print()


def cmd_graph(ur, a):
    path = f"/j2n/api/v1-beta1/graphs/{a.graph_id}"
    if a.all:
        found = []
        for e in ur.order:
            st, body = ur.get(e, path)
            v = unwrap(body) if st == 200 else None
            if v and (v.get("spec") or {}).get("nodes"):
                found.append((e, v))
        results = [(e, parse_graph(v)) for e, v in found]
    else:
        env, body = ur.probe(path, a.env, accept=lambda b: bool(((unwrap(b) or {}).get("spec") or {}).get("nodes")))
        if not env:
            print(f"graph {a.graph_id}: not found on {', '.join([normalise(a.env)] if a.env else ur.order)}", file=sys.stderr); sys.exit(EX_NOTFOUND)
        v = unwrap(body)
        if a.raw:
            print(json.dumps(v, ensure_ascii=False, indent=1)); return
        results = [(env, parse_graph(v))]
    for via, g in results:
        enrich_nodes(ur, via, g["nodes"])
    if a.json:
        print(json.dumps({"graph_id": a.graph_id, "results": [dict(via=e, **g) for e, g in results]}, ensure_ascii=False)); return
    for via, g in results:
        print_graph(a, via, g)


# ── process / box ─────────────────────────────────────────────────────────────

def _none(v):
    return None if v in (None, "None", "") else v


def parse_process(d):
    box = d.get("box") if isinstance(d.get("box"), dict) else {}
    ident = d.get("identity") if isinstance(d.get("identity"), dict) else {}
    video = d.get("video") if isinstance(d.get("video"), dict) else {}
    er = d.get("errorRates") if isinstance(d.get("errorRates"), dict) else {}
    return {"process_id": _none(d.get("nodeId")) or "", "type": _none(d.get("type")) or "",
            "status": _none(d.get("processStatus")) or "", "active": d.get("active"),
            "env": env_name(_none(d.get("env")) or ""), "graph_id": _none(d.get("graphId")) or "",
            "app": _none(d.get("appName")) or "", "owner": ident.get("userEmail") or ident.get("userId") or "",
            "image": _none(d.get("imageVersion")) or "", "box_id": _none(d.get("boxId")) or (box.get("huan") or "").rsplit(":", 1)[-1],
            "public_ip": _none(d.get("publicIp")) or "", "private_ip": _none(d.get("privateIp")) or "",
            "control_port": _none(d.get("mediaBoxControlPort")) or 0, "container": _none(d.get("container")) or "",
            "video": {k: video.get(k) for k in ("codec", "width", "height", "fps") if k in video},
            "error_rate_1s": er.get("errorRate1secPercentage"), "error_rate_8s": er.get("errorRate8secPercentage"),
            "shm": {k: _none(d.get(k)) for k in ("videoShm", "audioShm", "dataShm", "tvuLiveShm") if _none(d.get(k))},
            "created_at": _none(d.get("createdAt")) or "", "deleted": bool(d.get("nodeDelete")) and _none(d.get("graphId")) is None}


def cmd_process(ur, a):
    path = f"/pilot/api/v1/nodeOrigins/{a.process_id}/nodeOrginsByNodeDetails"
    live = lambda b: isinstance(b, dict) and _none(b.get("graphId")) is not None
    via, body = ur.probe(path, a.env, accept=live)
    if not via:
        print(f"process {a.process_id}: no live record on {', '.join([normalise(a.env)] if a.env else ur.order)} "
              "(a deleted process answers with an empty skeleton). A 32-hex id can also be an Object Service tangible — try `ela object <id>` (`/ela:object`).",
              file=sys.stderr); sys.exit(EX_NOTFOUND)
    if a.raw:
        print(json.dumps(body, ensure_ascii=False, indent=1)); return
    p = parse_process(body)
    if a.json:
        print(json.dumps(dict(via=via, **p), ensure_ascii=False)); return
    print(f"# process {a.process_id}  env {p['env'] or '?'} (answered via {via})")
    for k in ("type", "status", "graph_id", "app", "owner", "image", "box_id", "public_ip", "private_ip", "control_port", "container", "created_at"):
        if p.get(k) not in ("", 0, None):
            print(f"{k:<13}{p[k]}")
    if p["video"]:
        print(f"{'video':<13}{p['video']}")
    if p["error_rate_1s"] is not None:
        print(f"{'errors':<13}1s {p['error_rate_1s']}%  8s {p['error_rate_8s']}%")
    if p["shm"]:
        print(f"{'shm':<13}{' '.join(f'{k}={v}' for k, v in p['shm'].items())}")


def cmd_box(ur, a):
    env, body = ur.probe(f"/pilot/api/v1/boxes/{a.box_id}", a.env, accept=lambda b: isinstance(b, dict) and bool(b))
    if not env:
        print(f"box {a.box_id}: not found", file=sys.stderr); sys.exit(EX_NOTFOUND)
    if a.json or a.raw:
        print(json.dumps(dict(env=env, **body), ensure_ascii=False, indent=None if a.json else 1)); return
    print(f"# box {a.box_id}  [{env}]")
    for k, v in body.items():
        if not isinstance(v, (dict, list)):
            print(f"{k:<20}{v}")


# ── graphs by email ───────────────────────────────────────────────────────────

def resolve_email(who, env_file):
    """'me' | 'li' | an alias from site.json `emails` | an address | nothing (→ me)."""
    try:
        emails = json.load(open(os.path.expanduser("~/.claude/ela/site.json"))).get("emails", {})
    except Exception:
        emails = {}
    who = (who or "me").strip()
    if "@" in who:
        return who
    if who in emails:
        return emails[who]
    if who == "me":
        me = env_value("JIRA_EMAIL", env_file)
        if me:
            return me
    print(f"unknown email alias {who!r}; known: {', '.join(emails) or 'none'} (site.json `emails`)", file=sys.stderr); sys.exit(EX_USAGE)


def cmd_graphs(ur, a):
    a.email = resolve_email(a.email, a.env_file)
    envs = ur.order if a.all else ([normalise(a.env)] if a.env else ur.order)
    out, seen = [], set()
    for e in envs:
        rows, page = [], 0
        while True:
            st, body = ur.get(e, f"/j2n/v1beta1/emails/{urllib.parse.quote(a.email)}/graphs?page={page}&limit={a.limit}")
            if st != 200:
                break
            ents = ((body or {}).get("value") or {}).get("entities") or []
            for x in ents:
                meta, ann = x.get("metadata") or {}, (x.get("metadata") or {}).get("annotations") or {}
                gid = meta.get("name") or ann.get("app.tvunetworks.com/id", "")
                if gid in seen:
                    continue
                row = {"graph_id": gid, "env": env_name(ann.get("app.tvunetworks.com/environment", "")), "type": ann.get("businessType", ""),
                       "name": ann.get("businessName", ""), "object_id": ann.get("objectId", ""), "business_id": ann.get("businessId", ""),
                       "phase": ((x.get("status") or {}).get("phase", "")), "created_at": ((x.get("status") or {}).get("createdAt", ""))}
                if a.object and a.object not in (row["object_id"], row["business_id"]):
                    continue
                seen.add(gid); rows.append(row)
            if len(ents) < a.limit or not a.pages or page + 1 >= a.pages:
                break
            page += 1
        if rows:
            out.append({"via": e, "count": len(rows), "graphs": rows})
            if not a.all:
                break
    if a.json:
        print(json.dumps({"email": a.email, "object": a.object, "results": out}, ensure_ascii=False)); return
    if not out:
        print(f"no graphs for {a.email}" + (f" with object {a.object}" if a.object else "") + f" on {', '.join(envs)}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    for r in out:
        print(f"# {a.email}  (answered via {r['via']})  {r['count']} graph(s)")
        for g in r["graphs"]:
            print(f"  {g['graph_id']:<28}{g['env']:<8}{g['type']:<10}{g['phase']:<12}object {g['object_id']:<20} {g['name']}")


# ── resolve ───────────────────────────────────────────────────────────────────

def object_graphs(env_file, oid):
    """Graph ids an active object runs in, read from the Object Service: SHM/RTIL tangibles are named
    <graphId>:<node> and their tangibleId is the process id. Returns {graph_id: [(node, process_id, type)]}."""
    host = (env_value("TVU_OBJECT_SERVICE_HOST", env_file) or "").rstrip("/")
    tok = env_value("TVU_CC_BEARER_TOKEN", env_file)
    if not host or not tok:
        return None
    req = urllib.request.Request(f"{host}/route-object/object-service/base/object/{oid}",
                                 headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read() or b"{}")
    except Exception as e:
        print(f"object service: {str(e)[:80]}", file=sys.stderr); return None
    rec = d.get("result") if isinstance(d, dict) else None
    if not rec:
        return {}
    out = {}
    for t in rec.get("tangibleInfo") or []:
        m = re.match(r"^([0-9A-Z]{26}):(.+)$", t.get("tangibleName") or "")
        if m:
            out.setdefault(m.group(1), []).append((m.group(2), t.get("tangibleId", ""), t.get("tangibleType", "")))
    out["_object"] = {"name": rec.get("objectName"), "type": rec.get("objectType")}
    return out


def cmd_resolve(ur, a):
    kind = detect(a.id)
    if kind == "graph":
        a.graph_id, a.all, a.raw, a.detail, a.connections = a.id, False, False, False, False; return cmd_graph(ur, a)
    if kind == "process":
        a.process_id, a.raw = a.id, False; return cmd_process(ur, a)
    if kind == "object":
        og = object_graphs(a.env_file, a.id)
        graphs = [g for g in (og or {}) if g != "_object"]
        if graphs:
            info = og["_object"]
            print(f"# object {a.id}  {info['name']}  runs in {len(graphs)} graph(s): {', '.join(graphs)}\n", flush=True)
            for g in graphs:
                a.graph_id, a.all, a.raw, a.detail, a.connections = g, False, False, False, False
                try:
                    cmd_graph(ur, a)
                except SystemExit:
                    # a tangible can outlive its graph; say so and go on to the next one
                    print(f"graph {g}: no longer on any env — a stale tangible row on the object\n", flush=True)
            return
        if a.email:
            a.object, a.all, a.pages, a.limit = a.id, False, 5, 50; return cmd_graphs(ur, a)
        why = ("the Object Service has no SHM/RTIL tangible for it — the object is inactive (no running graph), "
               if og == {} or (og and not graphs) else "the Object Service could not be read — ")
        print(f"object {a.id}: {why}so no graph can be derived. With --email <owner>, J2N's graph list is searched instead "
              "(it includes finished graphs).", file=sys.stderr); sys.exit(EX_NOTFOUND)
    print(f"unrecognised id shape: {a.id} (graph = 26 chars A-Z0-9, process = 32 hex, object = 19 digits)", file=sys.stderr); sys.exit(EX_USAGE)


# ── actions (ura's connect · exec · start · stop). A human typing the command is the confirm;
#    an LLM caller must pass --yes, and a Claude session asks Evan first. ─────────────────────

def _ssh_creds(env_file):
    user = env_value("TVU_SSH_USER", env_file) or "operate_sh"
    pw = env_value("TVU_SSH_PASSWORD", env_file)
    if not pw:
        print("no TVU_SSH_PASSWORD in the env file — run /ela:setup", file=sys.stderr); sys.exit(EX_AUTH)
    return user, pw


def _box_ip_for(ur, env_file, ident, env=None):
    """ip | box id | process id → (ip, via)."""
    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ident):
        return ident, "given"
    if not re.fullmatch(r"[0-9a-f]{32}", ident):
        print(f"{ident}: expected an IPv4, a 32-hex box id or a 32-hex process id", file=sys.stderr); sys.exit(EX_USAGE)
    via, body = ur.probe(f"/pilot/api/v1/nodeOrigins/{ident}/nodeOrginsByNodeDetails", env, accept=lambda b: isinstance(b, dict) and _none(b.get("graphId")) is not None)
    if via:
        p = parse_process(body)
        ip = p["public_ip"]
        if not ip:  # the live process record often lacks ips; the graph node carries them
            g_via, g = ur.probe(f"/j2n/api/v1-beta1/graphs/{p['graph_id']}", None, accept=lambda b: bool(((unwrap(b) or {}).get("spec") or {}).get("nodes")))
            if g_via:
                for n in parse_graph(unwrap(g))["nodes"]:
                    if n["process_id"] == ident:
                        ip = n["public_ip"]
        if ip:
            return ip, f"process on {p['env'] or via}"
    via, body = ur.probe(f"/pilot/api/v1/boxes/{ident}", env, accept=lambda b: isinstance(b, dict) and bool(b))
    if via:
        ip = body.get("publicIpv4") or body.get("publicIp") or (body.get("box") or {}).get("publicIpv4") or body.get("ip")
        if ip:
            return ip, f"box on {via}"
    print(f"{ident}: no ip found as process or box", file=sys.stderr); sys.exit(EX_NOTFOUND)


def _ssh(user, pw, ip, remote_cmd):
    """The password travels in the environment, never in an argv: SSHPASS for sshpass -e, and LC_ELA_SUDO
    for the remote sudo — sshd's default AcceptEnv accepts LC_*. If the box rejects it, sudo prompts on the tty."""
    os.environ["LC_ELA_SUDO"] = pw
    base = ["ssh", "-t", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10", "-o", "SendEnv=LC_ELA_SUDO", f"{user}@{ip}", remote_cmd]
    if shutil.which("sshpass"):
        os.environ["SSHPASS"] = pw
        os.execvp("sshpass", ["sshpass", "-e", *base])
    print("sshpass not installed — you will be asked for the password", file=sys.stderr)
    os.execvp("ssh", base)


def _sudo(cmd):
    """Remote: unlock sudo with the password from the environment (silently, if it arrived), then run cmd as root."""
    return f"printf '%s\\n' \"$LC_ELA_SUDO\" | sudo -S -p '' true 2>/dev/null; unset LC_ELA_SUDO; sudo -p 'sudo password: ' {cmd}"


def cmd_connect(ur, a):
    user, pw = _ssh_creds(a.env_file)
    ip, via = _box_ip_for(ur, a.env_file, a.target, a.env)
    print(f"→ ssh {user}@{ip} (root)   [{via}]", file=sys.stderr)
    _ssh(user, pw, ip, _sudo("su -"))


def cmd_exec(ur, a):
    if not re.fullmatch(r"[0-9a-f]{32}", a.process_id):
        print("exec takes a 32-hex process id", file=sys.stderr); sys.exit(EX_USAGE)
    user, pw = _ssh_creds(a.env_file)
    ip, via = _box_ip_for(ur, a.env_file, a.process_id, a.env)
    print(f"→ ssh {user}@{ip} → docker exec -it -w /var/log {a.process_id} bash   [{via}]", file=sys.stderr)
    _ssh(user, pw, ip, _sudo(f"docker exec -it -w /var/log {a.process_id} bash"))


def _control_endpoint(ur, a):
    via, body = ur.probe(f"/pilot/api/v1/nodeOrigins/{a.process_id}/nodeOrginsByNodeDetails", a.env, accept=lambda b: isinstance(b, dict) and _none(b.get("graphId")) is not None)
    if not via:
        print(f"{a.process_id}: no live process record", file=sys.stderr); sys.exit(EX_NOTFOUND)
    p = parse_process(body)
    ip, port = p["public_ip"], p["control_port"]
    if not ip:
        ip, _ = _box_ip_for(ur, a.env_file, a.process_id, a.env)
    if not ip or not port:
        print(f"{a.process_id}: publicIp={ip or '-'} controlPort={port or 0} — the process may not be running", file=sys.stderr); sys.exit(EX_NOTFOUND)
    return ip, port, p


def _post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]
    except Exception as e:
        return 0, str(e)[:200]


def _confirm(a, what):
    if a.yes or sys.stdin.isatty() and input(f"{what}  [y/N] ").strip().lower() == "y":
        return
    print("not confirmed — nothing done", file=sys.stderr); sys.exit(EX_USAGE)


def cmd_start(ur, a):
    ip, port, p = _control_endpoint(ur, a)
    url = f"http://{ip}:{port}/api/output/v2/StartWorkingProcess"
    payload = {"processId": a.process_id, "role": "output",
               "wp": {"params": {"shared_memory_name": a.shm, "output_format": a.format, "output_url": a.url, "name": a.name or a.format, "srt_relay": False}}}
    print(f"process {a.process_id} ({p['type']}, {p['env']})  control {ip}:{port}\n  output {a.format} → {a.url}   shm {a.shm}")
    _confirm(a, f"POST {url}")
    st, body = _post(url, payload)
    print(json.dumps({"status": st, "body": body}, ensure_ascii=False) if a.json else f"HTTP {st}  {json.dumps(body, ensure_ascii=False)[:300] if body else ''}")
    if st != 200:
        sys.exit(EX_REMOTE)


def cmd_stop(ur, a):
    ip, port, p = _control_endpoint(ur, a)
    url = f"http://{ip}:{port}/api/output/v2/StopWorkingProcess"
    print(f"process {a.process_id} ({p['type']}, {p['env']})  control {ip}:{port}")
    _confirm(a, f"POST {url}  (stop the sender working process)")
    st, body = _post(url, {"processId": a.process_id, "role": "output", "wp": {"params": {}}})
    print(json.dumps({"status": st, "body": body}, ensure_ascii=False) if a.json else f"HTTP {st}  {json.dumps(body, ensure_ascii=False)[:300] if body else ''}")
    if st != 200:
        sys.exit(EX_REMOTE)


def cmd_envs(ur, a):
    print(json.dumps({"host": ur.host, "order": ur.order}) if a.json else "\n".join(ur.order))


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description="UR graph capability: read graphs, processes and boxes first-hand; connect/exec/start/stop on Evan's word.")
    ap.add_argument("--env-file", help="file with UR_ACCESS_KEY, UR_BASE_HOST, UR_ENV_ORDER")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, arg in (("graph", "graph_id"), ("process", "process_id"), ("box", "box_id")):
        p = sub.add_parser(name); p.add_argument(arg)
        p.add_argument("-e", "--env", help="prod3 · p3 · prod2 · test2 …; default: probe in order")
        p.add_argument("--json", action="store_true"); p.add_argument("--raw", action="store_true", help="the API body as-is")
        if name == "graph":
            p.add_argument("--all", action="store_true", help="every env that has it, not just the first")
            p.add_argument("-d", "--detail", action="store_true", help="box location, box id and image per node")
            p.add_argument("-c", "--connections", action="store_true", help="the edges as a connections list")
    p = sub.add_parser("graphs"); p.add_argument("email", nargs="?", default="me", help="address, or an alias from site.json emails (me · li …); default me"); p.add_argument("--env"); p.add_argument("--all", action="store_true")
    p.add_argument("--object", help="keep only graphs whose objectId or businessId equals this")
    p.add_argument("--pages", type=int, default=5, help="pages to walk per env"); p.add_argument("--limit", type=int, default=50, help="page size")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("resolve"); p.add_argument("id"); p.add_argument("--env"); p.add_argument("--email", help="owner email, needed for an object id")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("connect", help="ssh to a TVU box as root — by ip, box id or process id (ura connect)")
    p.add_argument("target"); p.add_argument("--env")
    p = sub.add_parser("exec", help="docker exec -it -w /var/log <process> bash on its box (ura exec)")
    p.add_argument("process_id"); p.add_argument("--env")
    p = sub.add_parser("start", help="start a Sender working process (ura start) — asks y/N unless --yes")
    p.add_argument("process_id"); p.add_argument("--url", required=True); p.add_argument("--format", required=True); p.add_argument("--shm", required=True)
    p.add_argument("--name"); p.add_argument("--env"); p.add_argument("--yes", action="store_true"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("stop", help="stop a Sender working process (ura stop) — asks y/N unless --yes")
    p.add_argument("process_id"); p.add_argument("--env"); p.add_argument("--yes", action="store_true"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("envs"); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    ur = UR(a.env_file)
    {"graph": cmd_graph, "process": cmd_process, "box": cmd_box, "graphs": cmd_graphs,
     "resolve": cmd_resolve, "envs": cmd_envs, "connect": cmd_connect, "exec": cmd_exec, "start": cmd_start, "stop": cmd_stop}[a.cmd](ur, a)


if __name__ == "__main__":
    main()
