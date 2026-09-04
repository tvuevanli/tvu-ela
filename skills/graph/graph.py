#!/usr/bin/env python3
"""UR graph capability. L1: subcommands, --json, meaningful exit codes, stdlib only. Reads are first-hand;
the four actions (connect · exec · start · stop) are Evan's hand at the shell — start/stop ask y/N.

What Evan's `ura` does by hand, without setting an environment first: a graph or process id is
probed across environments in a fixed order (MediaHub 2.1 prod first) until one answers.

  graph    <graphId>  [-e X | --all] [-d] [-c]   node table in pipeline order with each node's state; stopped
                                           graphs read too (J2N /any). -d adds box location/id, the live process
                                           status, the image actually running and the node's encoding profile; -c connections
  process  <processId> [--env X] [-d]      one process: type, box ips, control port, video/audio statistic, error
                                           rates, local shms. A stopped process falls through to the graph it ran in
  box      <boxId>     [--env X]           one box: placement, state, capacity and load, versions, connection times
  graphs   [email|alias|name] [--env X | --all] [--any | --deleted]  graphs owned by an address (any, as given), a site
                                           alias, or a roster name; no argument = me. --any/--deleted include stopped ones
  resolve  <id> [-d] [--limit N]           detect the id shape and route: graph · process · object → every graph the
                                           object ever ran in, stopped ones included, then the current (or last) one in full
  envs                                     the probe order
  connect  <ip|boxId|processId> [--env]    ssh to the box as root            (ura connect)
  exec     <processId> [--env]             docker exec -it -w /var/log <pid> bash on its box   (ura exec)
  start    <processId> --url U --format F --shm S [--name N] [--yes]   start a Sender working process   (ura start)
  stop     <processId> [--yes]             stop a Sender working process    (ura stop)

A stopped graph is not gone: J2N keeps it, and the routes that return it are `graphs/{id}/any`, `query_mode=any`
(v2 lists) and v2's object/process routes. Everything here reads those, so an Inactive object still has a history.

Environments live in the URL path: https://ur.tvunetworks.com/<env>/j2n/… and …/<env>/pilot/….
J2N v2 (`/j2n/api/v2`) is not on every environment — prod3 and test2 answer it today, prod2 does not.
Probe order (first answer wins): UR_ENV_ORDER in the env file (comma-separated), else prod3, prod2, test2.
Credentials: UR_ACCESS_KEY (+ UR_BASE_HOST) from $UR_ACCESS_KEY → --env-file → $ELA_ENV_FILE.
Exit codes: 0 ok (a stopped process/graph answered from history counts as ok) · 2 usage · 3 not found on any env
· 4 auth · 5 remote error.
"""
import argparse, datetime, http.client, json, os, queue, re, shutil, signal, sys, threading, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE = 2, 3, 4, 5
# Probe order — three envs cover everything Evan touches: prod3 (MediaHub 2.1, answers 2.0 too), prod2 (older
# prod), test2 (test). Sequential fallback; a miss costs one round-trip per env. Override with UR_ENV_ORDER.
DEFAULT_ORDER = ["prod3", "prod2", "test2"]
ALIASES = {"p": "prod", "t": "test", "t2": "test2", "t1": "test1"}
# J2N publishes every graph route twice, as /v1beta1/… and /api/v1-beta1/… — one family here, the /api one.
J2N, J2N2, PILOT = "/j2n/api/v1-beta1", "/j2n/api/v2", "/pilot/api/v1"
J2N_NEUTRAL = "/j2n/v1beta1"      # the neutral family; the only route that exists there alone is emails/…/graphs


def graph_path(gid):
    """`/any` answers whether the graph is live or already stopped. The plain route returns an empty envelope
    for a deleted graph — which is why a finished job used to read as 'not found on any env'."""
    return f"{J2N}/graphs/{gid}/any"


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
    """One host, many environments in the path. Connecting costs ~3 s (TLS to the UR edge), a request on an open
    connection ~0.5–1 s — so connections are kept alive, pooled, and a few are warmed in the background at start."""
    WARM = 4

    def __init__(self, env_file, warm=True):
        self.key = env_value("UR_ACCESS_KEY", env_file)
        if not self.key:
            print("no UR_ACCESS_KEY (env, $ELA_ENV_FILE, or --env-file)", file=sys.stderr); sys.exit(EX_AUTH)
        self.host = (env_value("UR_BASE_HOST", env_file) or "https://ur.tvunetworks.com").rstrip("/")
        order = env_value("UR_ENV_ORDER", env_file)
        self.order = [e.strip() for e in order.split(",") if e.strip()] if order else DEFAULT_ORDER
        u = urllib.parse.urlparse(self.host)
        self.netloc, self.https = u.netloc, (u.scheme == "https")
        self.pool = queue.LifoQueue()
        if warm:
            for _ in range(self.WARM):
                threading.Thread(target=lambda: self.pool.put(self._connect()), daemon=True).start()

    def _connect(self):
        cls = http.client.HTTPSConnection if self.https else http.client.HTTPConnection
        c = cls(self.netloc, timeout=30)
        try:
            c.connect()
        except OSError:
            pass                                   # surfaces as an error on first use
        return c

    def _take(self):
        try:
            return self.pool.get(timeout=0.05)
        except queue.Empty:
            return self._connect()

    def get(self, env, path):
        """→ (status, body_json_or_None). 5xx and 404 with an empty body read as 'not here'."""
        target = f"/{env}{path}"
        headers = {"AccessKey": self.key, "Accept": "application/json", "Connection": "keep-alive"}
        for attempt in range(2):
            c = self._take()
            try:
                c.request("GET", target, headers=headers)
                r = c.getresponse(); raw = r.read()
                self.pool.put(c)
                try:
                    return r.status, (json.loads(raw) if raw.strip() else None)
                except ValueError:
                    return r.status, None
            except (http.client.HTTPException, OSError) as e:
                c.close()
                if attempt == 1:
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


def _ts(v):
    """UR writes 0001-01-01T00:00:00Z for 'never' — read it as empty."""
    v = (v or "").strip()
    return "" if not v or v.startswith("0001-01-01") else v


def _age(start, end=None):
    """Elapsed time as a human span: start → end (or now). Empty when either end is unreadable."""
    try:
        t0 = datetime.datetime.fromisoformat(_ts(start).replace("Z", "+00:00"))
        t1 = (datetime.datetime.fromisoformat(_ts(end).replace("Z", "+00:00")) if _ts(end)
              else datetime.datetime.now(datetime.timezone.utc))
    except ValueError:
        return ""
    n = int((t1 - t0).total_seconds())
    if n < 0:
        return ""
    d, r = divmod(n, 86400); h, r = divmod(r, 3600); m, sec = divmod(r, 60)
    return f"{d}d{h}h" if d else f"{h}h{m}m" if h else f"{m}m{sec}s" if m else f"{sec}s"


def _ip(v):
    """A process record's publicIp/privateIp is null in practice, but Pilot types it as an object of per-shm
    addresses — take an address out of it rather than letting a dict reach the output."""
    if isinstance(v, dict):
        for k in ("videoShmAddress", "localShmAddress", "audioShmAddress", "transmitShmAddress",
                  "dataShmAddress", "tvuLiveShmAddress"):
            a = v.get(k)
            if a:
                return str(a).split(":")[0]
        return ""
    return "" if v in (None, "None", "") else str(v)


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
        opts, prm = sp.get("options") or {}, sp.get("params") or {}
        nodes.append({
            # what J2N got as far as: pending → created (a process id exists) → dispatched (it is running)
            "state": ("err" if st.get("errors") else "dispatched" if st.get("dispatched")
                      else "created" if st.get("created") else "pending"),
            # an encoder/copier/switcher names its encoding profile by id only; resolved in enrich_profiles
            "profile_id": opts.get("profileId") or prm.get("profileId") or "",
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
            "phase": st.get("phase", ""), "created_at": st.get("createdAt", ""), "deleted_at": _ts(st.get("deletedAt")),
            "errors": st.get("errors") or [], "nodes": [nodes[i] for i in order], "edges": edges}


TTY = sys.stdout.isatty()
def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if TTY else str(text)
BOLD, DIM, CYAN, GREEN, YELLOW, RED = "1", "2", "36", "32", "33", "31"
STATE_COLOUR = {"dispatched": GREEN, "created": CYAN, "pending": YELLOW, "err": RED}


def enrich_nodes(ur, env, nodes):
    """One Pilot nodeOrigins call per node — in parallel over the warmed connections: control port, box id, the box's cloud placement."""
    def one(n):
        n.update({"control_port": 0, "box_type": "", "platform": "", "region": "",
                  "process_status": "", "active": None, "image_running": ""})
        if not n["process_id"]:
            return
        st, body = ur.get(env, f"{PILOT}/nodeOrigins/{n['process_id']}/nodeOrginsByNodeDetails")
        if st != 200 or not isinstance(body, dict):
            return
        box = body.get("box") if isinstance(body.get("box"), dict) else {}
        # the same response carries the live truth about the process — status, activity, the image actually running
        n["process_status"] = _none(body.get("processStatus")) or ""
        n["active"] = body.get("active")
        n["image_running"] = _none(body.get("imageVersion")) or ""
        n["public_ip"] = n["public_ip"] or _ip(body.get("publicIp")) or box.get("publicIpv4") or ""
        n["private_ip"] = n["private_ip"] or _ip(body.get("privateIp")) or box.get("privateIpv4") or ""
        n["control_port"] = _none(body.get("mediaBoxControlPort")) or _none(body.get("controlPort")) or 0
        n["box_id"] = _none(body.get("boxId")) or box.get("id") or n["box_id"]
        n["box_type"], n["platform"], n["region"] = box.get("type") or "", box.get("platform") or "", box.get("region") or ""
    with ThreadPoolExecutor(max_workers=min(UR.WARM + 2, max(1, len(nodes)))) as ex:
        list(ex.map(one, nodes))
    return nodes


def enrich_profiles(ur, env, nodes):
    """profileId → the encoding profile behind it, one Pilot call per distinct id (in parallel, cached by id).
    A graph node carries the id only; the tier it names — video, audio, stream — is what the encoder was told
    to produce, and single-tier covers the MediaHub profiles (multi-tier is tried for the assembled ones)."""
    ids = sorted({n.get("profile_id") for n in nodes if n.get("profile_id")})
    found = {}

    def one(pid):
        for kind in ("single-tier", "multi-tier"):
            st, b = ur.get(env, f"{PILOT}/ep/{kind}-encoding-profiles/{pid}/details")
            if st == 200 and isinstance(b, dict) and b.get("id"):
                found[pid] = b
                return

    if ids:
        with ThreadPoolExecutor(max_workers=min(UR.WARM + 2, len(ids))) as ex:
            list(ex.map(one, ids))
    for n in nodes:
        n["profile"] = found.get(n.get("profile_id")) or None
    return nodes


def profile_line(p):
    """One line for an encoding profile: name · video · audio — the numbers an encoding complaint turns on."""
    tier = p.get("encodingTier") or {}
    v = tier.get("videoProfile") or {}
    auds = [a for a in (tier.get("audioProfiles") or [tier.get("audioProfile")]) if isinstance(a, dict)]
    name = p.get("name") or p.get("id") or ""
    if not v:                                     # a multi-tier profile: its tiers, not one encoding
        tiers = p.get("streamProfiles") or p.get("tiers") or p.get("encodingTiers") or []
        return f"{name} · {len(tiers)} tier(s)" if tiers else name
    fps = v.get("frameRate")
    vid = [x for x in (v.get("codec"), v.get("resolution"), v.get("bitrate"),
                       f"{fps:g}fps" if isinstance(fps, (int, float)) else "",
                       f"gop{v['gop']}" if v.get("gop") else "",
                       "cbr" if v.get("cbr") else "vbr",
                       f"{v.get('profile')}@{v.get('level')}" if v.get("profile") else "") if x]
    a = auds[0] if auds else {}
    aud = [x for x in (a.get("codec"), a.get("bitrate"),
                       f"{int(a['sampleRate']) // 1000}kHz" if a.get("sampleRate") else "") if x]
    more = f" (+{len(auds) - 1} audio)" if len(auds) > 1 else ""
    return f"{name} · " + " ".join(vid) + (f" · audio {' '.join(aud)}{more}" if aud else "")


def box_location(n):
    if n.get("box_type") == "ManagedCloud":
        return " / ".join(x for x in (n.get("platform"), n.get("region")) if x) or "ManagedCloud"
    return n.get("box_type") or ""


def print_graph(a, via, g):
    title = " · ".join(x for x in [g["business_type"], g["business_name"], g["email"]] if x)
    print(_c(BOLD, f"Graph: {g['graph_id'] or a.graph_id}") + f"  env {g['env'] or '?'} (answered via {via})  {g['phase']}  {title}")
    if g["object_id"]:
        age = f"  ({_age(g['created_at'], g['deleted_at'])} old)" if g["created_at"] and not g["deleted_at"] else ""
        print(_c(DIM, f"object {g['object_id']}  business {g['business_id']}  app {g['app']}  created {g['created_at'][:19]}{age}"))
    if g["deleted_at"]:
        lived = _age(g["created_at"], g["deleted_at"])
        print(_c(YELLOW, f"STOPPED  deleted {g['deleted_at'][:19]}" + (f"  (ran {lived})" if lived else "")
                         + "  — read from /any; the nodes below are the last known placement, not live"))
    print()
    cols = [("Node", 5), ("Type", 18), ("State", 10), ("Process ID", 32), ("Public IP", 15), ("Private IP", 15)]
    if a.detail:
        cols += [("Control Port", 12), ("Box Location", 20), ("Box ID", 32)]
    print(_c(BOLD, "  " + "  ".join(f"{h:<{w}}" for h, w in cols)))
    print(_c(DIM, "  " + "  ".join("─" * w for _, w in cols)))
    for i, n in enumerate(g["nodes"], 1):
        state = n.get("state") or ""
        row = [_c(CYAN, f"{'[' + str(i) + ']':<5}"), _c(BOLD, f"{n['type'][:18]:<18}"),
               _c(DIM if g["deleted_at"] else STATE_COLOUR.get(state, DIM), f"{state:<10}"), _c(DIM, f"{n['process_id']:<32}"),
               f"{n['public_ip'] or '(none)':<15}", f"{n['private_ip'] or '(none)':<15}"]
        if a.detail:
            row += [_c(GREEN, f"{n.get('control_port') or 'N/A':<12}"), f"{box_location(n) or '(none)':<20}", _c(DIM, n['box_id'] or '(none)')]
        print(("  " + "  ".join(row)).rstrip())
        if a.detail:
            pad = f"  {'':<5}  {'':<18}  "
            live = " · ".join(x for x in [n.get("process_status") or "",
                                          "active" if n.get("active") else ("inactive" if n.get("active") is False else "")] if x)
            print(_c(DIM, pad) + (_c(GREEN, live) + "  " if live else "") + _c(DIM, f"{n['image'] or '(no image)'}   {n['name']}"))
            run = n.get("image_running") or ""
            if run and run != n["image"]:         # declared (J2N) vs running (Pilot) — a deploy/promotion smell
                print(_c(DIM, pad) + _c(YELLOW, f"running {run}  ≠ declared above"))
            if n.get("profile"):
                print(_c(DIM, f"{pad}profile {profile_line(n['profile'])}"))
            elif n.get("profile_id"):
                print(_c(DIM, f"{pad}profile {n['profile_id']} (not readable on {via})"))
    if a.connections and g["edges"]:
        idx = {n["name"]: i for i, n in enumerate(g["nodes"], 1)}
        print(); print(_c(BOLD, "  Connections")); print(_c(DIM, "  " + "─" * 58))
        for e in sorted(g["edges"], key=lambda e: (idx.get(e["from"], 999), idx.get(e["to"], 999))):
            fi, ti = idx.get(e["from"]), idx.get(e["to"])
            ft = g["nodes"][fi - 1]["type"] if fi else e["from"]
            tt = g["nodes"][ti - 1]["type"] if ti else e["to"]
            print(f"  {_c(CYAN, '[' + str(fi or '?') + ']')} {ft:<18} {_c(DIM, '──')} {(','.join(e['shm']) or 'N/A'):<32} {_c(DIM, '──►')} {_c(CYAN, '[' + str(ti or '?') + ']')} {tt}")
    errs = ([(f"[{i}] {n['type'][:16]}", x) for i, n in enumerate(g["nodes"], 1) for x in n["errors"]]
            + [("graph", x) for x in g["errors"]])
    if errs:
        print(); print(_c(BOLD, "  Errors")); print(_c(DIM, "  " + "─" * 58))
        for who, x in errs[:12]:
            print(f"  {_c(RED, f'{who:<22}')} {str(x)[:150]}")
        if len(errs) > 12:
            print(_c(DIM, f"  … {len(errs) - 12} more"))
    print()


def cmd_graph(ur, a):
    path = graph_path(a.graph_id)
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
    if a.detail or a.json:                        # the default table needs no Pilot call — progressive disclosure
        for via, g in results:
            enrich_nodes(ur, via, g["nodes"])
            enrich_profiles(ur, via, g["nodes"])
    if a.json:
        print(json.dumps({"graph_id": a.graph_id, "results": [dict(via=e, **g) for e, g in results]}, ensure_ascii=False)); return
    for via, g in results:
        print_graph(a, via, g)


# ── process / box ─────────────────────────────────────────────────────────────

def _none(v):
    return None if v in (None, "None", "") else v


VIDEO_KEYS = ("codec", "codecName", "width", "height", "fps", "realTimeFps", "bitrate", "realTimeBitrate",
              "outputFrames", "totalFrames", "droppedFrames", "format", "videoFormat", "interlace",
              "compressionStructure", "compressionProfile", "jitter1sec", "withClosedCaption")
AUDIO_KEYS = ("codec", "codecName", "bitrate", "sampleRate", "channelCount", "channels", "droppedFrames", "streamIndex")


def parse_process(d):
    box = d.get("box") if isinstance(d.get("box"), dict) else {}
    ident = d.get("identity") if isinstance(d.get("identity"), dict) else {}
    video = d.get("video") if isinstance(d.get("video"), dict) else {}
    # live Pilot returns `audios` (a list); the published contract says `audio` (one object) — take either
    auds = [x for x in (d.get("audios") if isinstance(d.get("audios"), list) else [d.get("audio")]) if isinstance(x, dict)]
    er = d.get("errorRates") if isinstance(d.get("errorRates"), dict) else {}
    shms = [x for x in (d.get("localShmList") or []) if isinstance(x, dict)]
    return {"process_id": _none(d.get("nodeId")) or "", "type": _none(d.get("type")) or "",
            "status": _none(d.get("processStatus")) or "", "active": d.get("active"),
            "env": env_name(_none(d.get("env")) or ""),
            # Pilot names a node's graph "<graphId>:<nodeName>" — J2N only knows the bare graph id
            "graph_id": (_none(d.get("graphId")) or "").split(":", 1)[0], "node": (_none(d.get("graphId")) or "").partition(":")[2],
            "app": _none(d.get("appName")) or "", "owner": ident.get("userEmail") or ident.get("userId") or "",
            "image": _none(d.get("imageVersion")) or "", "box_id": _none(d.get("boxId")) or (box.get("huan") or "").rsplit(":", 1)[-1],
            # the process row's own ip fields are usually null; the box block in the same record carries them
            "public_ip": _ip(d.get("publicIp")) or box.get("publicIpv4") or "", "private_ip": _ip(d.get("privateIp")) or box.get("privateIpv4") or "",
            "control_port": _none(d.get("mediaBoxControlPort")) or _none(d.get("controlPort")) or 0,
            "container": _none(d.get("container")) or "",
            "video": {k: video.get(k) for k in VIDEO_KEYS if video.get(k) not in (None, "")},
            "audio": [{k: a.get(k) for k in AUDIO_KEYS if a.get(k) not in (None, "")} for a in auds],
            "error_rate_1s": er.get("errorRate1secPercentage"), "error_rate_8s": er.get("errorRate8secPercentage"),
            "error_rate_60s": er.get("errorRate60secPercentage"), "late_1s": d.get("packetLatePercentage1sec"),
            "shm": {k: _none(d.get(k)) for k in ("videoShm", "audioShm", "dataShm", "tvuLiveShm", "transmitShm") if _none(d.get(k))},
            "local_shms": [{"id": x.get("localShmId", ""), "name": x.get("localShmName", ""), "type": x.get("localShmType"),
                            "depth": x.get("depth"), "box_id": x.get("boxId", "")} for x in shms],
            "url": _none(d.get("url")) or _none(d.get("listenUrl")) or "", "cross_zone_url": _none(d.get("crossZoneOutputUrl")) or "",
            "created_at": _none(d.get("createdAt")) or "", "deleted_at": _ts(d.get("deletedAt")),
            "deleted": bool(d.get("nodeDelete")) and _none(d.get("graphId")) is None}


def _rate(br):
    """Pilot reports a bitrate in bit/s for some process types and in kbit/s for others (a decoder says
    7584174, an encoder 8144) — the magnitude is the only thing that tells them apart, so label the unit."""
    if not isinstance(br, (int, float)) or br <= 0:
        return ""
    return f"{br / 1e6:.2f} Mb/s" if br > 100000 else f"{br:g} kb/s"


def fmt_video(v):
    """The video statistic as one line — configured shape first, then what is actually coming through."""
    br = v.get("bitrate") or v.get("realTimeBitrate")
    fps = v.get("fps") or v.get("realTimeFps")
    frames = v.get("outputFrames") if v.get("outputFrames") is not None else v.get("totalFrames")
    parts = [v.get("codec") or v.get("codecName") or "",
             f"{v['width']}x{v['height']}" if v.get("width") else "",
             f"{fps:.4g}fps" if isinstance(fps, (int, float)) else "",
             _rate(br),
             "interlaced" if v.get("interlace") else "",
             v.get("compressionStructure") or "",
             f"frames {frames}" if frames is not None else "",
             f"dropped {v['droppedFrames']}" if v.get("droppedFrames") is not None else "",
             f"jitter {v['jitter1sec']}ms" if v.get("jitter1sec") is not None else "",
             "cc" if v.get("withClosedCaption") else ""]
    return "  ".join(x for x in parts if x)


def fmt_audio(a):
    br, sr = a.get("bitrate"), a.get("sampleRate")
    parts = [a.get("codec") or a.get("codecName") or "", _rate(br),
             f"{int(sr) // 1000}kHz" if isinstance(sr, (int, float)) and sr else "",
             f"{a.get('channelCount') or a.get('channels')}ch" if (a.get("channelCount") or a.get("channels")) else "",
             f"dropped {a['droppedFrames']}" if a.get("droppedFrames") is not None else ""]
    return "  ".join(x for x in parts if x)


def process_gone(ur, a):
    """Pilot has no live record — the process has stopped. J2N v2 still knows which graph it belonged to and
    when that graph ended, so the answer is that graph, not 'not found'. Exit 0 when the history was found."""
    q = f"?page=0&limit=3&query_mode=any&sorting={urllib.parse.quote('CreatedAt DESC')}"
    via, body = ur.probe(f"{J2N2}/processes/{a.process_id}/graphs{q}", a.env,
                         accept=lambda b: bool((unwrap(b) or {}).get("entities")))
    rows = [v2_row(e) for e in ((unwrap(body) or {}).get("entities") or [])] if via else []
    if a.json:
        print(json.dumps({"process_id": a.process_id, "live": False, "via": via, "graphs": rows}, ensure_ascii=False))
        sys.exit(0 if rows else EX_NOTFOUND)
    if not rows:
        print(f"process {a.process_id}: no live record on {', '.join([normalise(a.env)] if a.env else ur.order)} and no "
              "graph in J2N v2 either (v2 is not on every environment — try -e prod3). A 32-hex id can also be an "
              "Object Service tangible — try `ela object <id>` (`/ela:object`).", file=sys.stderr); sys.exit(EX_NOTFOUND)
    r = rows[0]
    ended = (f"stopped {r['deleted_at'][:19].replace('T', ' ')} (ran {_age(r['created_at'], r['deleted_at'])})"
             if r["deleted_at"] else "the graph is still live — the process itself is not")
    print(_c(BOLD, f"# process {a.process_id}") + f"  stopped — no live record on {', '.join(ur.order) if not a.env else normalise(a.env)}")
    print(_c(DIM, f"  it ran in graph {r['graph_id']}  ({r['type']} · {r['name']})  {ended}\n"))
    a.graph_id, a.all, a.raw, a.detail, a.connections = r["graph_id"], False, False, getattr(a, "detail", False), False
    cmd_graph(ur, a)


def cmd_process(ur, a):
    path = f"{PILOT}/nodeOrigins/{a.process_id}/nodeOrginsByNodeDetails"
    live = lambda b: isinstance(b, dict) and _none(b.get("graphId")) is not None
    via, body = ur.probe(path, a.env, accept=live)
    if not via:
        return process_gone(ur, a)
    if a.raw:
        print(json.dumps(body, ensure_ascii=False, indent=1)); return
    p = parse_process(body)
    if a.json:
        print(json.dumps(dict(via=via, **p), ensure_ascii=False)); return
    print(f"# process {a.process_id}  env {p['env'] or '?'} (answered via {via})")
    for k in ("type", "status", "graph_id", "node", "app", "owner", "image", "box_id", "public_ip", "private_ip",
              "control_port", "container", "url", "cross_zone_url", "created_at"):
        if p.get(k) not in ("", 0, None):
            print(f"{k:<13}{p[k]}")
    if p["created_at"]:
        print(f"{'uptime':<13}{_age(p['created_at']) or '-'}" + (f"   (deleted {p['deleted_at'][:19]})" if p["deleted_at"] else ""))
    if p.get("active") is not None:
        print(f"{'active':<13}{str(bool(p['active'])).lower()}")
    if p["video"]:
        print(f"{'video':<13}{fmt_video(p['video'])}")
    for i, aud in enumerate(p["audio"]):
        print(f"{('audio' if i == 0 else ''):<13}{fmt_audio(aud)}")
    rates = [f"1s {p['error_rate_1s']}%", f"8s {p['error_rate_8s']}%", f"60s {p['error_rate_60s']}%"]
    if p["error_rate_1s"] is not None:
        late = f"   late 1s {p['late_1s']}%" if p.get("late_1s") is not None else ""
        print(f"{'errors':<13}{'  '.join(r for r in rates if 'None' not in r)}{late}")
    if p["shm"]:
        print(f"{'shm':<13}{' '.join(f'{k}={v}' for k, v in p['shm'].items())}")
    if p["local_shms"]:
        depths = ", ".join(f"{x['name'] or x['id'][:8]} depth {x['depth']}" for x in p["local_shms"][:6])
        print(f"{'localshm':<13}{len(p['local_shms'])}  {depths}")


BOX_STATUS = {0: "InActive", 1: "Active"}
BOX_ACTIVE = {0: "Pending", 1: "Active", 2: "Deactive"}
BOX_INSTANCE = {0: "Creating", 1: "Starting", 2: "Running", 3: "Stopping", 4: "Stopped", 5: "Destroyed"}


def print_box(env, b):
    """A box record is mostly nested — capacity, load, versions and the connection times are the whole point,
    so they are laid out by hand instead of printing whatever happens to be a scalar."""
    def line(k, v):
        if v not in ("", None):
            print(f"{k:<15}{v}")

    def cap(name, d, unit="GB"):
        if isinstance(d, dict) and d:
            size = d.get("cores") if "cores" in d else d.get("gbSize")
            idle = d.get("idle")
            line(name, f"{size}{'' if 'cores' in d else ' ' + unit}"
                       + (f" cores" if "cores" in d else "")
                       + (f"   {idle:.0f}% idle   {100 - idle:.0f}% used" if isinstance(idle, (int, float)) else ""))

    print(f"# box {b.get('id') or ''}  [{env}]" + ("   DELETED" if b.get("deleted") else ""))
    line("name", b.get("name") or b.get("hostname") or "")
    where = [b.get("type"), b.get("platform"), b.get("region")]
    if b.get("availableZone") and b.get("availableZone") != b.get("region"):
        where.append(b.get("availableZone"))
    line("type", " · ".join(x for x in where if x))
    line("cloud id", b.get("cloudBoxId"))
    line("public ip", b.get("publicIpv4")); line("private ip", b.get("privateIpv4"))
    line("state", " · ".join([BOX_STATUS.get(b.get("status"), str(b.get("status"))),
                              BOX_ACTIVE.get(b.get("activeStatus"), str(b.get("activeStatus"))),
                              BOX_INSTANCE.get(b.get("instanceStatus"), str(b.get("instanceStatus")))]))
    line("pool", b.get("poolId")); line("env", b.get("boxConnectedEnv"))
    print()
    cap("cpu", b.get("cpu")); cap("mem", b.get("mem")); cap("disk", b.get("disk")); cap("shm", b.get("shm"))
    ld = b.get("load") or {}
    if ld:
        line("load", f"{ld.get('loadAvg1Min')} / {ld.get('loadAvg5Min')} / {ld.get('loadAvg15Min')}   (1m/5m/15m)")
    print()
    hb = _ts(b.get("heartbeatAt"))
    line("created", (_ts(b.get("createdAt")) or "")[:19])
    line("connected", (_ts(b.get("connectedAt")) or "")[:19] + (f"   up {_age(b.get('connectedAt'))}" if _ts(b.get("connectedAt")) else ""))
    line("heartbeat", (hb or "")[:19] + (f"   {_age(hb)} ago" if hb else ""))
    line("disconnected", (_ts(b.get("lastDisconnectTime")) or "never")[:19])
    ver = b.get("version") or {}
    if ver:
        known = {k: v for k, v in ver.items() if k != "processVersions" and v and v != "Unknown"}
        line("versions", "  ".join(f"{k.replace('Version', '')}={v}" for k, v in known.items()) or "(all Unknown)")
        pv = ver.get("processVersions") or {}
        if pv:
            line("processes", "  ".join(f"{k}={v}" for k, v in list(pv.items())[:8]))
    ports = [f"nginx {b.get('nginxHttpPort')}" if b.get("nginxHttpPort") else "", f"rtmp {b.get('rtmpServerPort')}" if b.get("rtmpServerPort") else "",
             f"{len(b.get('externalPortMappings') or [])} mappings" if b.get("externalPortMappings") else ""]
    line("ports", "  ".join(x for x in ports if x))
    sw = b.get("softwareInfo") or {}
    if sw:
        line("software", " · ".join(str(x) for x in (sw.get("distribution"), sw.get("kernel"), sw.get("dockerVersion")) if x))
    if b.get("daemonSet"):
        line("daemons", ", ".join(b["daemonSet"]))


def cmd_box(ur, a):
    env, body = ur.probe(f"{PILOT}/boxes/{a.box_id}", a.env, accept=lambda b: isinstance(b, dict) and bool(b))
    if not env:
        print(f"box {a.box_id}: not found", file=sys.stderr); sys.exit(EX_NOTFOUND)
    if a.json or a.raw:
        print(json.dumps(dict(env=env, **body), ensure_ascii=False, indent=None if a.json else 1)); return
    print_box(env, body)


# ── graphs by email ───────────────────────────────────────────────────────────

def resolve_email(who, env_file):
    """'me' | 'li' | an alias from site.json `emails` | an address | nothing (→ me)."""
    try:
        emails = json.load(open(os.path.expanduser("~/.claude/ela/site.json"))).get("emails", {})
    except Exception:
        emails = {}
    who = (who or "me").strip()
    if "@" in who:
        return who                      # a full address is input as given — UR users are mostly not on the roster
    if who in emails:
        return emails[who]
    if who == "me":
        me = env_value("JIRA_EMAIL", env_file)
        if me:
            return me
    # a name → the roster (skills/team), never a composed address
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "team"))
        import team
        _, people = team.read_roster()
        hits = team.find(people, who)
    except SystemExit:
        hits = []
    if len(hits) == 1:
        return hits[0]["email"]
    if len(hits) > 1:
        print(f"{who!r} matches several people: {', '.join(p['name'] + ' <' + p['email'] + '>' for p in hits)} — say which", file=sys.stderr); sys.exit(EX_USAGE)
    print(f"{who!r} is neither an address, a site alias ({', '.join(emails) or 'none'}) nor a roster name — pass the full address, or add the person to the roster", file=sys.stderr); sys.exit(EX_USAGE)


def cmd_graphs(ur, a):
    a.email = resolve_email(a.email, a.env_file)
    envs = ur.order if a.all else ([normalise(a.env)] if a.env else ur.order)
    out, seen = [], set()
    mode = "any" if getattr(a, "any", False) else ("deleted" if getattr(a, "deleted", False) else "")
    for e in envs:
        rows, page = [], 0
        while True:
            if mode:      # v2's options route filters by email server-side and is the only one that honours query_mode
                st, body = ur.get(e, f"{J2N2}/options/graphs?email={urllib.parse.quote(a.email)}&page={page}"
                                     f"&limit={a.limit}&query_mode={mode}&sorting={urllib.parse.quote('CreatedAt DESC')}")
                ents = (unwrap(body) or {}).get("entities") or [] if st == 200 else []
                new = [v2_row(x) for x in ents]
            else:
                st, body = ur.get(e, f"{J2N_NEUTRAL}/emails/{urllib.parse.quote(a.email)}/graphs?page={page}&limit={a.limit}")
                ents = ((body or {}).get("value") or {}).get("entities") or [] if st == 200 else []
                new = []
                for x in ents:
                    meta, ann = x.get("metadata") or {}, (x.get("metadata") or {}).get("annotations") or {}
                    stt = x.get("status") or {}
                    new.append({"graph_id": meta.get("name") or ann.get("app.tvunetworks.com/id", ""),
                                "env": env_name(ann.get("app.tvunetworks.com/environment", "")), "type": ann.get("businessType", ""),
                                "name": ann.get("businessName", ""), "object_id": ann.get("objectId", ""),
                                "business_id": ann.get("businessId", ""), "email": a.email, "phase": stt.get("phase", ""),
                                "created_at": _ts(stt.get("createdAt")), "deleted_at": _ts(stt.get("deletedAt")),
                                "processes": len((x.get("spec") or {}).get("nodes") or [])})
            if st != 200:
                break
            for row in new:
                if not row["graph_id"] or row["graph_id"] in seen:
                    continue
                if a.object and a.object not in (row["object_id"], row["business_id"]):
                    continue
                seen.add(row["graph_id"]); rows.append(row)
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
        print(f"# {a.email}  (answered via {r['via']})  {r['count']} graph(s)"
              + (f"  [{'stopped graphs included' if mode == 'any' else 'stopped graphs only'}]" if mode else ""))
        for g in r["graphs"]:
            end = (f"  stopped {g['deleted_at'][:19].replace('T', ' ')}" if g.get("deleted_at") else "")
            print(f"  {g['graph_id']:<28}{g['env']:<8}{g['type']:<10}{g['phase']:<12}object {g['object_id']:<20} {g['name']}{_c(DIM, end)}")


def v2_row(e):
    """A J2N v2 graph record → the row `graphs` and the object history print. v2 is flat where v1beta1 nests
    (no metadata/spec/status envelope) and it is the only family that can return stopped graphs by owner."""
    ann = e.get("annotations") or {}
    return {"graph_id": e.get("id") or ann.get("app.tvunetworks.com/id", ""),
            "env": env_name(ann.get("app.tvunetworks.com/environment", "")),
            "type": ann.get("businessType", ""), "name": ann.get("businessName", ""),
            "object_id": ann.get("objectId", ""), "business_id": ann.get("businessId", ""),
            "email": e.get("email", ""), "phase": e.get("phase", ""),
            "created_at": _ts(e.get("createdAt")), "deleted_at": _ts(e.get("deletedAt")),
            "processes": len(e.get("processes") or {})}


def object_graph_history(ur, oid, env=None, limit=10):
    """Every graph an object ever ran in, stopped ones included, newest first — J2N v2's object route with
    query_mode=any. This is the answer for an object the app shows as Inactive: the Object Service has no
    tangible left to follow, but J2N still holds the graphs and when each of them ended.
    v2 answers where it is deployed (prod3 and test2 today; prod2 has no v2 and 404s)."""
    q = f"?page=0&limit={limit}&query_mode=any&sorting={urllib.parse.quote('CreatedAt DESC')}"
    via, body = ur.probe(f"{J2N2}/objects/{oid}/graphs{q}", env, accept=lambda b: bool((unwrap(b) or {}).get("entities")))
    if not via:
        return None, [], 0
    v = unwrap(body) or {}
    rows = [v2_row(e) for e in (v.get("entities") or [])]
    return via, rows, v.get("count") or len(rows)


def print_history(oid, via, rows, total):
    live = [r for r in rows if not r["deleted_at"]]
    name = next((r["name"] for r in rows if r["name"]), "")
    print(_c(BOLD, f"# object {oid}") + (f"  {name}" if name else ""))
    print(f"  {total} graph(s) known to J2N on {via} — {len(live)} live, {total - len(live)} stopped"
          + (f" (newest {len(rows)} listed)" if total > len(rows) else "") + "\n")
    for r in rows:
        when = f"created {r['created_at'][:19].replace('T', ' ')}"
        end = (f"  stopped {r['deleted_at'][11:19]} (ran {_age(r['created_at'], r['deleted_at'])})"
               if r["deleted_at"] else _c(GREEN, "  live"))
        print(f"  {r['graph_id']:<28}{r['env'] or '?':<7}{r['type']:<9}{r['phase']:<12}"
              f"{r['processes'] or '-':>2} proc  {when}{end}")
    print()


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
        a.graph_id, a.all, a.raw, a.connections = a.id, False, False, False
        a.detail = getattr(a, "detail", False); return cmd_graph(ur, a)
    if kind == "process":
        a.process_id, a.raw = a.id, False; return cmd_process(ur, a)
    if kind == "object":
        via, hist, total = object_graph_history(ur, a.id, a.env, getattr(a, "limit", 10) or 10)
        if hist:
            live = [r for r in hist if not r["deleted_at"]]
            chosen = live or hist[:1]                 # what is running, else the last graph that ran
            if a.json:
                out = {"object": a.id, "via": via, "name": next((r["name"] for r in hist if r["name"]), ""),
                       "type": next((r["type"] for r in hist if r["type"]), ""), "count": total,
                       "history": hist, "graphs": [], "stale": []}
                for r in chosen:
                    env, body = ur.probe(graph_path(r["graph_id"]), a.env,
                                         accept=lambda b: bool(((unwrap(b) or {}).get("spec") or {}).get("nodes")))
                    if env:
                        parsed = parse_graph(unwrap(body))
                        enrich_nodes(ur, env, parsed["nodes"]); enrich_profiles(ur, env, parsed["nodes"])
                        out["graphs"].append(dict(via=env, **parsed))
                    else:
                        out["stale"].append(r["graph_id"])
                print(json.dumps(out, ensure_ascii=False)); return
            print_history(a.id, via, hist, total)
            for r in chosen:
                a.graph_id, a.all, a.raw, a.detail, a.connections = r["graph_id"], False, False, getattr(a, "detail", False), False
                try:
                    cmd_graph(ur, a)
                except SystemExit:
                    print(f"graph {r['graph_id']}: J2N lists it but will not return it — read the row above\n", flush=True)
            if len(hist) > len(chosen):
                print(_c(DIM, f"  earlier graphs: ela graph <id> — they are readable in full, stopped or not"))
            return
        og = object_graphs(a.env_file, a.id)
        graphs = [g for g in (og or {}) if g != "_object"]
        if graphs:
            info = og["_object"]
            if a.json:
                # one JSON document for the whole object — a caller (Helm's seam) parses stdout as a single value
                out = {"object": a.id, "name": info.get("name"), "type": info.get("type"), "graphs": [], "stale": []}
                for g in graphs:
                    env, body = ur.probe(graph_path(g), a.env, accept=lambda b: bool(((unwrap(b) or {}).get("spec") or {}).get("nodes")))
                    if env:
                        parsed = parse_graph(unwrap(body)); enrich_nodes(ur, env, parsed["nodes"])
                        out["graphs"].append(dict(via=env, **parsed))
                    else:
                        out["stale"].append(g)
                print(json.dumps(out, ensure_ascii=False)); return
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
        why = ("J2N v2 knows no graph carrying it and the Object Service has no SHM/RTIL tangible for it "
               if og == {} or (og and not graphs) else "the Object Service could not be read — ")
        print(f"object {a.id}: {why}on {', '.join([normalise(a.env)] if a.env else ur.order)}. "
              "v2 (the route that returns stopped graphs) is not on every environment — try -e prod3, or "
              "--email <owner> to search J2N's list by owner.", file=sys.stderr); sys.exit(EX_NOTFOUND)
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
    via, body = ur.probe(f"{PILOT}/nodeOrigins/{ident}/nodeOrginsByNodeDetails", env, accept=lambda b: isinstance(b, dict) and _none(b.get("graphId")) is not None)
    if via:
        p = parse_process(body)
        ip = p["public_ip"]
        if not ip:  # the live process record often lacks ips; the graph node carries them
            g_via, g = ur.probe(graph_path(p["graph_id"]), None, accept=lambda b: bool(((unwrap(b) or {}).get("spec") or {}).get("nodes")))
            if g_via:
                for n in parse_graph(unwrap(g))["nodes"]:
                    if n["process_id"] == ident:
                        ip = n["public_ip"]
        if ip:
            return ip, f"process on {p['env'] or via}"
    via, body = ur.probe(f"{PILOT}/boxes/{ident}", env, accept=lambda b: isinstance(b, dict) and bool(b))
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
    words = [w for w in a.target if w.lower() not in ("process", "box", "ip")]   # ura habit: `connect process <id>`
    if len(words) != 1:
        print("connect takes one target: an ip, a box id or a process id", file=sys.stderr); sys.exit(EX_USAGE)
    a.target = words[0]
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
    via, body = ur.probe(f"{PILOT}/nodeOrigins/{a.process_id}/nodeOrginsByNodeDetails", a.env, accept=lambda b: isinstance(b, dict) and _none(b.get("graphId")) is not None)
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
        if name == "process":                     # a stopped process falls through to the graph it ran in
            p.add_argument("-d", "--detail", action="store_true", help="per node, when the graph is printed")
        p.add_argument("-e", "--env", help="prod3 · p3 · prod2 · test2 …; default: probe in order")
        p.add_argument("--json", action="store_true"); p.add_argument("--raw", action="store_true", help="the API body as-is")
        if name == "graph":
            p.add_argument("--all", action="store_true", help="every env that has it, not just the first")
            p.add_argument("-d", "--detail", action="store_true", help="control port, box location, box id and image per node (one Pilot call per node)")
            p.add_argument("-c", "--connections", action="store_true", help="the edges as a connections list")
    p = sub.add_parser("graphs"); p.add_argument("email", nargs="?", default="me", help="a full address (any UR user, as given), an alias from site.json emails (me · li …), or a roster name (robin); default me"); p.add_argument("-e", "--env"); p.add_argument("--all", action="store_true")
    p.add_argument("--object", help="keep only graphs whose objectId or businessId equals this")
    p.add_argument("--any", action="store_true", help="stopped graphs too (J2N v2, newest first)")
    p.add_argument("--deleted", action="store_true", help="only stopped graphs (J2N v2, newest first)")
    p.add_argument("--pages", type=int, default=5, help="pages to walk per env"); p.add_argument("--limit", type=int, default=50, help="page size")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("resolve"); p.add_argument("id"); p.add_argument("-e", "--env"); p.add_argument("--email", help="owner email, fallback for an object id")
    p.add_argument("-d", "--detail", action="store_true", help="per node: control port, box, live status, encoding profile")
    p.add_argument("--limit", type=int, default=10, help="graphs to list for an object id (its history, newest first)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("connect", help="ssh to a TVU box as root — by ip, box id or process id (ura connect; `connect process <id>` works too)")
    p.add_argument("target", nargs="+"); p.add_argument("-e", "--env")
    p = sub.add_parser("exec", help="docker exec -it -w /var/log <process> bash on its box (ura exec)")
    p.add_argument("process_id"); p.add_argument("-e", "--env")
    p = sub.add_parser("start", help="start a Sender working process (ura start) — asks y/N unless --yes")
    p.add_argument("process_id"); p.add_argument("--url", required=True); p.add_argument("--format", required=True); p.add_argument("--shm", required=True)
    p.add_argument("--name"); p.add_argument("-e", "--env"); p.add_argument("--yes", action="store_true"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("stop", help="stop a Sender working process (ura stop) — asks y/N unless --yes")
    p.add_argument("process_id"); p.add_argument("-e", "--env"); p.add_argument("--yes", action="store_true"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("envs"); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    ur = UR(a.env_file)
    {"graph": cmd_graph, "process": cmd_process, "box": cmd_box, "graphs": cmd_graphs,
     "resolve": cmd_resolve, "envs": cmd_envs, "connect": cmd_connect, "exec": cmd_exec, "start": cmd_start, "stop": cmd_stop}[a.cmd](ur, a)


if __name__ == "__main__":
    main()
