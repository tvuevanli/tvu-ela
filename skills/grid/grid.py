#!/usr/bin/env python3
"""Grid source capability — read-only. L1: subcommands, --json, meaningful exit codes, stdlib only.

From a Grid source's name, sender PID (16 hex), source id (32 hex = PID + resource) or MediaHub object id (19 digits),
read the chain end to end and label every line checked · inferred · not checked:

  sender     the Command Center device record: name, type, status, version, last report      (tvucc-device getDevice)
  encoders   the sender's configured encoders: mode, SDI card, issp output, bitrate           (GCS getXmlFile type=x)
  routes     the receivers GCS pairs the source to, each one's own status, and whether its
             livePeerId is this source                                                       (GCS getPairRBySourceId)
  mediahub   the graphs holding the object (Object Service), when an object id is the input
  breaks     the first link that is down, by the rule in breaks()

Reads only these, all open by design (no credential): GCS `/gcsApi/getDeviceId`, `/gcsApi/getPairRBySourceId`,
`/gcsApi/getXmlFile?type=x` and tvucc-device `/device/getDevice`. NEVER `getXmlFile?type=r` (it records the caller's IP
as the receiver's address, XmlFileServiceImpl.getXmlR) nor any `/noLogin/*` route: those are writes.

What it cannot see is printed as not checked: the sender's input signal (only the sender's own logs show it), the
receiver's internal Grid state (LinuxR GridPeerEntity, on the box or through CC), GCS's logged-in Relay views (user-auth
service "Grid Server"; the owner's account is refused there), and the MediaHub decoder process (`ela graph <id> -d`).

Hosts: site.json services `gcs` / `gcs-cn` and `cc-device` / `cc-device-cn`.
Exit codes: 0 ok · 2 usage · 3 not found · 5 remote error.
"""
import argparse, datetime, json, os, re, signal, subprocess, sys, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

EX_USAGE, EX_NOTFOUND, EX_REMOTE = 2, 3, 5
HERE = os.path.dirname(os.path.realpath(__file__))
STATUS = {"0": "offline", "1": "online", "2": "live", "3": "off-air"}
RESOURCE = {1: "pack", 2: "sdi", 3: "mediahub"}          # tvu-media-hub Constants.java:163-165 (grid_pack/sdi/mediahub)
STALE_H = 30 * 24                                         # a paired receiver silent this long is a leftover pair, not a route


def services():
    try:
        return json.load(open(os.path.expanduser("~/.claude/ela/site.json"))).get("services") or {}
    except (OSError, ValueError):
        return {}


def base(name, region):
    key = name + ("-cn" if region == "cn" else "")
    url = ((services().get(key) or {}).get("url") or "").rstrip("/")
    if not url:
        print(f"site.json services.{key}.url is not set — /ela:setup", file=sys.stderr); sys.exit(EX_USAGE)
    return url


def get(url, want_json=True):
    req = urllib.request.Request(url, headers={"Accept": "application/json, application/xml"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        print(f"{url.split('?')[0]}: HTTP {e.code}", file=sys.stderr); sys.exit(EX_REMOTE)
    except urllib.error.URLError as e:
        print(f"{url.split('?')[0]}: {e.reason}", file=sys.stderr); sys.exit(EX_REMOTE)
    if not want_json:
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        print(f"{url.split('?')[0]}: not JSON: {raw[:160]!r}", file=sys.stderr); sys.exit(EX_REMOTE)


class Grid:
    def __init__(self, region):
        self.region = region
        self.gcs = base("gcs", region)
        self.cc = base("cc-device", region)

    def device_id(self, name):
        d = get(f"{self.gcs}/gcsApi/getDeviceId?" + urllib.parse.urlencode({"deviceName": name}))
        r = d.get("result") if isinstance(d, dict) else None
        return r.lower() if isinstance(r, str) and re.fullmatch(r"[0-9a-fA-F]{16}", r) else None

    def pairs(self, source_id):
        d = get(f"{self.gcs}/gcsApi/getPairRBySourceId?peerid={source_id}")
        return d if isinstance(d, list) else []

    def encoders(self, pid):
        raw = get(f"{self.gcs}/gcsApi/getXmlFile?type=x&peerId={pid}", want_json=False)
        try:
            root = ET.fromstring(raw.strip().encode())
        except ET.ParseError:
            return None
        out = []
        for i, c in enumerate(root.iter("Command"), 1):
            a = c.attrib
            m = re.search(r"(\d+)$", a.get("Name") or "")   # encoderN feeds resource N (LAMCA: one Command, encoder2 → …0002)
            out.append({"resource": int(m.group(1)) if m else i, "name": a.get("Name"), "enabled": a.get("Enabled") == "true", "mode": a.get("Mode"),
                        "sdi_card": a.get("DeckLinkCardNumber"), "output": a.get("OutputAddress"),
                        "bitrate_kbps": a.get("Bitrate"), "audio": a.get("AudioEncoder")})
        return out

    def device(self, pid):
        d = get(f"{self.cc}/device/getDevice?peerId={pid}")
        r = d.get("result") if isinstance(d, dict) else None
        if not r:
            return None
        ts = r.get("timeStamp")
        seen = None
        if ts and str(ts).isdigit():
            seen = datetime.datetime.fromtimestamp(int(ts) / 1000, datetime.timezone.utc)
        return {"pid": r.get("peerId"), "name": r.get("name"), "type": r.get("type"), "status": STATUS.get(str(r.get("status")), str(r.get("status"))),
                "version": r.get("version"), "ip": r.get("ip"), "live_peer": (r.get("livePeerId") or "").lower() or None,
                "grid_live_peer": (r.get("gridLivePeerId") or "").lower() or None,
                "last_report": seen.strftime("%Y-%m-%dT%H:%M:%SZ") if seen else None,
                "age_h": round((datetime.datetime.now(datetime.timezone.utc) - seen).total_seconds() / 3600, 1) if seen else None}


def from_object(oid, env_file):
    """object id → (source id, object name, graphs) through the Object Service; None when it holds no [X] tangible."""
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "object"))
    import object as objsvc
    svc = objsvc.OS_(env_file)
    r = svc.object(oid)
    if not r:
        print(f"object {oid}: not found in the Object Service", file=sys.stderr); sys.exit(EX_NOTFOUND)
    o = objsvc.summarise_object(r)
    xs = [t for t in o["tangibles"] if (t["type"] or "").upper() == "X"]
    if not xs:
        print(f"object {oid} ({o['name']}) holds no Grid [X] tangible: not a Grid source", file=sys.stderr); sys.exit(EX_NOTFOUND)
    decoders = [t["tangible_id"] for t in o["tangibles"] if (t["type"] or "").upper() == "SHM" and "grid_decoder" in (t["name"] or "")]
    return xs[0]["tangible_id"].lower(), o["name"], xs[0]["name"], o["graphs"], decoders


def decoder(pid, env_file):
    """One MediaHub grid_decoder process through graph.py (UR): status and what it receives. None when UR has no record."""
    argv = ["python3", os.path.join(os.path.dirname(HERE), "graph", "graph.py")] + (["--env-file", env_file] if env_file else []) + ["process", pid, "--json"]
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=120).stdout
        d = json.loads(out)
    except (subprocess.TimeoutExpired, ValueError):
        return None
    v = d.get("video") or {}
    return {"process": pid, "status": d.get("status"), "env": d.get("env"), "graph": d.get("graph_id"), "image": d.get("image"),
            "video": f"{v.get('codec')} {v.get('format')} {round((v.get('bitrate') or 0) / 1000)} kbps" if v else None,
            "dropped": v.get("droppedFrames"), "error_rate_60s": d.get("error_rate_60s")}


def resolve(g, ident, env_file):
    """→ dict(pid, sources [32 hex], how, object fields)."""
    out = {"input": ident, "object": None}
    if re.fullmatch(r"\d{19}", ident):
        sid, oname, xname, graphs, decoders = from_object(ident, env_file)
        out.update(pid=sid[:16], sources=[sid], how=f"object {ident} → [X] {sid}",
                   object={"id": ident, "name": oname, "x_name": xname, "graphs": graphs, "decoders": decoders})
    elif re.fullmatch(r"[0-9a-fA-F]{32}", ident):
        out.update(pid=ident[:16].lower(), sources=[ident.lower()], how="source id")
    elif re.fullmatch(r"[0-9a-fA-F]{16}", ident):
        out.update(pid=ident.lower(), sources=None, how="sender PID")
    else:
        pid = g.device_id(ident)
        if not pid:
            print(f"GCS knows no device named exactly {ident!r} ({g.region}); try the PID, the object id, or the sender's "
                  f"device name rather than the MediaHub source name", file=sys.stderr); sys.exit(EX_NOTFOUND)
        out.update(pid=pid, sources=None, how=f"GCS name {ident!r} → {pid}")
    return out


def breaks(r):
    """The first link that is down, in chain order, with its label. A rule over facts, not a diagnosis."""
    s = r["sender"]
    if not s:
        return ("sender", "checked", "Command Center has no device with this PID")
    if s["status"] == "offline":
        return ("sender", "checked", f"the sender is offline (last report {s['last_report']}, {s['age_h']} h ago)")
    if r["encoders"] is not None:
        used = {x["resource"] for x in r["encoders"] if x["enabled"]}
        wanted = [int(sid[16:], 16) for sid in r["sources"]]
        off = [w for w in wanted if w not in used]
        if off and len(off) == len(wanted):
            return ("encoder", "inferred", f"no enabled encoder for resource {', '.join(map(str, off))} in the sender's GCS config "
                                           f"(resource N = encoderN, inferred)")
    decs = r.get("decoders") or []
    if decs:                                       # a MediaHub source: its receiver is the grid_decoder, not a GCS pair
        bad = [d for d in decs if not d or d["status"] != "running"]
        if len(bad) == len(decs):
            return ("decoder", "checked", "no MediaHub grid_decoder holding this object is running")
        worse = [d for d in decs if d and d["status"] == "running" and ((d["error_rate_60s"] or 0) > 0 or (d["dropped"] or 0) > 0)]
        if worse:
            return ("decoder", "checked", f"decoder {worse[0]['process']} runs but loses data (error rate 60 s {worse[0]['error_rate_60s']}, "
                                          f"dropped {worse[0]['dropped']})")
        return (None, "checked", "sender online and the MediaHub decoder receiving cleanly; the input signal is not checked")
    routes = [x for src in r["routes"] for x in src["receivers"] if not x["stale"]]
    if not routes:                                 # MediaHub pulls without a live GCS pair (HEKAYAT1 MAIN, 2026-11-23), so not proof
        return ("route", "inferred", "GCS pairs this source to no current receiver"
                + (" (only leftover pairs to long-silent receivers)" if any(src["receivers"] for src in r["routes"]) else "")
                + "; a MediaHub decoder pulls without a pair, so give the object id to check that side")
    if not any(x["live_on_source"] for x in routes):
        return ("receiver", "checked", "no paired receiver is live on this source now")
    return (None, "checked", "sender online and at least one paired receiver live on it; the input signal is not checked")


def cmd_source(a):
    g = Grid(a.region)
    r = resolve(g, a.id, a.env_file)
    r["region"] = a.region
    r["sender"] = g.device(r["pid"])
    r["encoders"] = g.encoders(r["pid"])
    if r["sources"] is None:                       # a PID or a name: every enabled encoder is a source
        enc = [x["resource"] for x in (r["encoders"] or []) if x["enabled"]] or [1, 2, 3]
        r["sources"] = [r["pid"] + f"{n:016x}" for n in enc]
    r["routes"] = []
    for sid in r["sources"]:
        recv = {}
        for p in g.pairs(sid):
            rid = (p.get("device_id") or "").lower()
            if rid in recv:                        # GCS can hold several pair rows for one receiver
                recv[rid]["pair_ids"].append(p.get("pair_id")); continue
            d = g.device(rid) if rid else None
            live = bool(d and sid in ((d.get("live_peer") or ""), (d.get("grid_live_peer") or "")))
            stale = bool(d and d["status"] == "offline" and (d["age_h"] or 0) > STALE_H)
            recv[rid] = {"receiver": rid, "pair_ids": [p.get("pair_id")], "auto": str(p.get("is_auto")) == "1", "device": d,
                         "live_on_source": live, "stale": stale}
        recv = list(recv.values())
        r["routes"].append({"source": sid, "kind": RESOURCE.get(int(sid[16:], 16), "?"), "receivers": recv})
    r["decoders"] = [decoder(p, a.env_file) for p in ((r["object"] or {}).get("decoders") or [])]
    link, label, why = breaks(r)
    r["breaks"] = {"link": link, "label": label, "why": why}
    r["not_checked"] = ["the sender's input signal (format, presence): only the sender's own logs show it",
                        "the receiver's internal Grid state (LinuxR GridPeerEntity): on the box or through CC",
                        "the Relay path and the receivers pulling now: GCS's logged-in views (service 'Grid Server'; refused to the owner's account)",
                        "the MediaHub decoder's own log: `ela logs loki --pid <process>`"]
    if a.json:
        print(json.dumps(r, ensure_ascii=False)); return
    show(r)


def dev_line(d):
    if not d:
        return "unknown to Command Center"
    return (f"{d['name']}  type {d['type']}  {d['status']}  v{d['version']}  last report {d['last_report']} ({d['age_h']} h ago)"
            + (f"  live on {d['live_peer']}" if d.get("live_peer") else ""))


def show(r):
    o = r["object"]
    head = f"# Grid source {r['input']}  ({r['how']}; {r['region']})"
    print(head)
    if o:
        print(f"object     {o['id']}  {o['name']}  [X] {o['x_name']}")
    rnote = "; a type-R sender's status is its own receiver mode, not its Grid sending (inferred)" if (r["sender"] or {}).get("type") == "R" else ""
    print(f"sender     {r['pid']}  {dev_line(r['sender'])}   [checked: CC device record{rnote}]")
    if r["encoders"] is None:
        print("encoders   GCS returned no config for this PID   [checked]")
    for x in r["encoders"] or []:
        mark = "" if x["enabled"] else "  (disabled)"
        card = f"  SDI card {x['sdi_card']}" if "DeckLink" in (x["mode"] or "") else ""
        print(f"encoder {x['resource']}  {x['name']}  {x['mode']}{card}  → {x['output']}  {x['bitrate_kbps']} kbps{mark}   [checked: GCS config; feeds resource {x['resource']}, inferred from the name]")
    for src in r["routes"]:
        print(f"route      {src['source']}  ({src['kind']})  → {len(src['receivers'])} paired receiver(s)   [checked: GCS pairs]")
        for x in src["receivers"]:
            live = "LIVE ON THIS SOURCE" if x["live_on_source"] else "not on this source"
            tags = ("  (auto pair)" if x["auto"] else "") + ("  STALE PAIR (receiver silent > 30 days)" if x["stale"] else "")
            print(f"  ↳ {x['receiver']}  {dev_line(x['device'])}  · {live}{tags}  pair {','.join(map(str, x['pair_ids']))}")
    if o and o["graphs"]:
        print(f"mediahub   graphs {', '.join(o['graphs'])}   [checked: Object Service]")
    for d in r.get("decoders") or []:
        if d:
            print(f"  ↳ grid_decoder {d['process']}  {d['status']}  {d['env']}  graph {d['graph']}  {d['video'] or 'no video stats'}"
                  f"  dropped {d['dropped']}  error-rate-60s {d['error_rate_60s']}  {(d['image'] or '').rsplit('/', 1)[-1]}   [checked: UR process]")
    if not o:
        print("mediahub   not checked (give the object id to see the graphs holding it)")
    b = r["breaks"]
    print(f"breaks     {('at ' + b['link']) if b['link'] else 'no break found in what was read'}: {b['why']}   [{b['label']}]")
    for n in r["not_checked"]:
        print(f"not checked  {n}")


def main():
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "configserver"))
    import redact; redact.guard_output()
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description="Grid source, end to end, read-only: sender · encoders · GCS routes · receivers · where it breaks.")
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("source", help="a Grid source by name, sender PID (16 hex), source id (32 hex) or object id (19 digits)")
    p.add_argument("id"); p.add_argument("--region", choices=("com", "cn"), default="com"); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    {"source": cmd_source}[a.cmd](a)


if __name__ == "__main__":
    main()
