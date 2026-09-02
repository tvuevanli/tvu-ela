#!/usr/bin/env python3
"""Object Service capability — read-only. L1: subcommands, --json, meaningful exit codes, stdlib only.

The TVU Object Service (/route-object/object-service — not objectd, a different service). An object
(19 digits) holds one or more tangibles (32 hex); both are readable.

  get     <id>            object or tangible, decided by the id shape, falling through to the other on a miss

Only `get` exists: the service exposes GET /base/object/<id> and GET /base/tangible/<id>. A batch endpoint
and a keyword search were documented in an earlier skill but answer 404 (verified 2026-09-02).
An active object's SHM/RTIL tangibles are named <graphId>:<node> and their tangibleId is the process id —
that is how an object resolves to its running graphs (see graph.py resolve).

Credentials: TVU_OBJECT_SERVICE_HOST and TVU_CC_BEARER_TOKEN from the environment → --env-file → $ELA_ENV_FILE.
Exit codes: 0 ok · 2 usage · 3 not found · 4 auth · 5 remote error.
"""
import argparse, json, os, re, signal, sys, urllib.error, urllib.request

EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE = 2, 3, 4, 5
TYPES = {"1": "Source", "2": "Destination"}


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


class OS_:
    def __init__(self, env_file):
        self.host = (env_value("TVU_OBJECT_SERVICE_HOST", env_file) or "").rstrip("/")
        self.tok = env_value("TVU_CC_BEARER_TOKEN", env_file)
        if not self.host or not self.tok:
            print("need TVU_OBJECT_SERVICE_HOST and TVU_CC_BEARER_TOKEN (env, $ELA_ENV_FILE, or --env-file)", file=sys.stderr); sys.exit(EX_AUTH)
        self.base = self.host + "/route-object/object-service/base"

    def call(self, url, payload=None):
        req = urllib.request.Request(url, data=json.dumps(payload).encode() if payload is not None else None,
                                     headers={"Authorization": f"Bearer {self.tok}", "Accept": "application/json",
                                              **({"Content-Type": "application/json"} if payload is not None else {})})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw.strip() else None)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                print(f"object service: HTTP {e.code} — token rejected; run /ela:setup", file=sys.stderr); sys.exit(EX_AUTH)
            raw = e.read().decode("utf-8", "replace")[:300]
            if e.code == 404:
                return 404, None
            print(f"object service: HTTP {e.code} {raw}", file=sys.stderr); sys.exit(EX_REMOTE)
        except urllib.error.URLError as e:
            print(f"object service: {e}", file=sys.stderr); sys.exit(EX_REMOTE)

    def object(self, oid):
        st, d = self.call(f"{self.base}/object/{oid}")
        r = (d or {}).get("result") if isinstance(d, dict) else None
        return r if r else None

    def tangible(self, tid):
        st, d = self.call(f"{self.base}/tangible/{tid}")
        return d if isinstance(d, dict) and d.get("tangibleId") else None


def shape(id_):
    if re.fullmatch(r"\d{19}", id_):
        return "object"
    if re.fullmatch(r"[0-9a-f]{16,32}", id_):
        return "tangible"
    return ""


def summarise_object(r):
    owner = r.get("owner") if isinstance(r.get("owner"), dict) else {}
    return {"object_id": r.get("objectId"), "name": r.get("objectName"), "type": TYPES.get(str(r.get("objectType")), str(r.get("objectType"))),
            "origin": r.get("origin"), "owner_users": owner.get("users") or [], "owner_groups": owner.get("groups") or [],
            "created": r.get("createTimestamp"), "updated": r.get("updateTimestamp"), "deleted": r.get("deleteFlag"),
            "tangibles": [{"tangible_id": t.get("tangibleId"), "name": t.get("tangibleName"), "type": t.get("tangibleType"),
                           "extra": _extra(t.get("extraInfo"))} for t in r.get("tangibleInfo") or []],
            # an active object's SHM/RTIL tangibles are named <graphId>:<node>; their tangibleId is the process id
            "graphs": sorted({(t.get("tangibleName") or "").split(":")[0] for t in r.get("tangibleInfo") or []
                              if re.match(r"^[0-9A-Z]{26}:", t.get("tangibleName") or "")})}


def _extra(x):
    if isinstance(x, str):
        try:
            return json.loads(x)
        except ValueError:
            return x
    return x


def print_object(o):
    print(f"# object {o['object_id']}  {o['type']}  {o['name']}")
    if o.get("origin"):
        print(f"origin       {o['origin']}")
    if o["owner_users"]:
        print(f"owner users  {', '.join(o['owner_users'])}")
    for t in o["tangibles"]:
        url = (t["extra"] or {}).get("url") if isinstance(t["extra"], dict) else ""
        print(f"  [{t['type']}] {t['tangible_id']}  {t['name']}" + (f"  {url}" if url else ""))
    if o["graphs"]:
        print(f"graphs       {', '.join(o['graphs'])}   (running; tangibleId of an SHM/RTIL row is its process id)")


def cmd_get(svc, a):
    kind = shape(a.id)
    if not kind:
        print(f"unrecognised id: {a.id} (object = 19 digits, tangible = 16–32 hex)", file=sys.stderr); sys.exit(EX_USAGE)
    order = ["object", "tangible"] if kind == "object" else ["tangible", "object"]
    for k in order:
        r = svc.object(a.id) if k == "object" else svc.tangible(a.id)
        if r:
            if a.raw:
                print(json.dumps(r, ensure_ascii=False, indent=1)); return
            if k == "object":
                o = summarise_object(r)
                print(json.dumps(dict(answered_by="object", **o), ensure_ascii=False)) if a.json else print_object(o)
            else:
                t = {"tangible_id": r.get("tangibleId"), "name": r.get("tangibleName"), "type": r.get("tangibleType"),
                     "object_id": r.get("objectId"), "object_name": r.get("objectName"),
                     "object_type": TYPES.get(str(r.get("objectType")), str(r.get("objectType"))), "extra": _extra(r.get("extraInfo"))}
                if a.json:
                    print(json.dumps(dict(answered_by="tangible", **t), ensure_ascii=False))
                else:
                    print(f"# tangible {t['tangible_id']}  [{t['type']}]  {t['name']}")
                    if t["object_id"]:
                        print(f"object       {t['object_id']}  {t['object_type']}  {t['object_name']}")
                    else:
                        print("object       (the tangible endpoint carries no objectId; find the object by name or from the graph)")
                    if t["extra"]:
                        print(f"extra        {json.dumps(t['extra'], ensure_ascii=False)[:400]}")
            return
    print(f"{a.id}: not found as object nor tangible", file=sys.stderr); sys.exit(EX_NOTFOUND)


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description="TVU Object Service — read-only.")
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("get"); p.add_argument("id"); p.add_argument("--json", action="store_true"); p.add_argument("--raw", action="store_true")
    a = ap.parse_args()
    svc = OS_(a.env_file)
    {"get": cmd_get}[a.cmd](svc, a)


if __name__ == "__main__":
    main()
