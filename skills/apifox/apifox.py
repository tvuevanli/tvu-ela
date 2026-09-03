#!/usr/bin/env python3
"""Apifox — the API definitions the teams keep in Apifox, read first-hand through its Open API. Read-only, stdlib only.

  projects                          the projects ela knows by name (<records>/map/apis.yaml) and their cache state
  export  <project> [--refresh]     fetch the project's OpenAPI 3.1 document (cached a day under ~/.claude/ela/apifox/)
  tags    <project>                 the tags (folders) and how many operations each carries
  list    <project> [--tag T] [--grep text]   operations: METHOD path · summary · tag
  read    <project> <ref>           one operation in full: parameters, request body, responses — ref = path, operationId,
                                    "METHOD path", or a summary fragment (unique match required)
  schema  <project> <Name>          one component schema, $refs resolved two levels deep

<project> is a name from apis.yaml (ur, …) or a numeric Apifox project id; an app.apifox.com/project/<id> URL works too.
Credentials: APIFOX_TOKEN (a personal access token) from the env or the env file; sent as a Bearer header with
X-Apifox-Api-Version 2024-03-28. Apifox's edge drops requests without a User-Agent, so one is always sent.
Team pages cannot be listed through the Open API; project ids are read off the UI URL and recorded in apis.yaml.
Exit codes: 0 ok · 2 usage · 3 not found · 4 auth · 5 remote error.
"""
import argparse, json, os, re, signal, sys, time, urllib.error, urllib.request

EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE = 2, 3, 4, 5
SITE = os.path.expanduser("~/.claude/ela/site.json")
CACHE_DIR = os.path.expanduser("~/.claude/ela/apifox")
API = "https://api.apifox.com/v1"
VERSION = "2024-03-28"
METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


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


def known_projects():
    """<records>/map/apis.yaml → {name: {id, note}}. A small YAML subset: `projects:` then `  name: {id: N, note: …}` or `  name: N`."""
    path = os.path.join(site().get("map", ""), "apis.yaml")
    out = {}
    try:
        text = open(path).read()
    except OSError:
        return out
    section = None
    for line in text.splitlines():
        line = re.sub(r"\s+#.*$", "", line.rstrip())
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if re.match(r"^[a-z_]+:\s*$", line):
            section = line.strip(":"); continue
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*(.+)$", line)
        if m and section == "projects":
            v = m.group(2).strip()
            mm = re.match(r"^\{\s*id:\s*(\d+)\s*(?:,\s*note:\s*(.+?)\s*)?\}$", v)
            out[m.group(1)] = {"id": mm.group(1), "note": (mm.group(2) or "").strip("'\"")} if mm else {"id": re.sub(r"\D", "", v), "note": ""}
    return out


def project_id(ref):
    m = re.search(r"apifox\.com/project/(\d+)", ref or "")
    if m:
        return m.group(1)
    if re.fullmatch(r"\d+", ref or ""):
        return ref
    p = known_projects().get(ref)
    if p:
        return p["id"]
    print(f"{ref!r}: not a project id, URL or a name in map/apis.yaml ({', '.join(known_projects()) or 'none recorded'})", file=sys.stderr); sys.exit(EX_USAGE)


def fetch_openapi(pid, env_file):
    tok = env_value("APIFOX_TOKEN", env_file)
    if not tok:
        print("no APIFOX_TOKEN in the env file — run /ela:setup", file=sys.stderr); sys.exit(EX_AUTH)
    body = json.dumps({"scope": {"type": "ALL"}, "options": {"includeApifoxExtensionProperties": False, "addFoldersToTags": True},
                       "oasVersion": "3.1", "exportFormat": "JSON"}).encode()
    req = urllib.request.Request(f"{API}/projects/{pid}/export-openapi?locale=zh-CN", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {tok}", "X-Apifox-Api-Version": VERSION,
                                          "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "ela (python-urllib)"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            print(f"apifox: HTTP {e.code} — the token is invalid or has no access to project {pid}", file=sys.stderr); sys.exit(EX_AUTH)
        if e.code == 404:
            print(f"apifox: project {pid} not found", file=sys.stderr); sys.exit(EX_NOTFOUND)
        print(f"apifox: HTTP {e.code} {e.read()[:200]!r}", file=sys.stderr); sys.exit(EX_REMOTE)
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"apifox: unreachable ({e})", file=sys.stderr); sys.exit(EX_REMOTE)
    try:
        d = json.loads(raw)
    except ValueError:
        print(f"apifox: not an OpenAPI document ({len(raw)} bytes)", file=sys.stderr); sys.exit(EX_REMOTE)
    if "paths" not in d:
        print(f"apifox: unexpected body {json.dumps(d, ensure_ascii=False)[:200]}", file=sys.stderr); sys.exit(EX_REMOTE)
    return d


def load(pid, env_file, refresh=False):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cp = os.path.join(CACHE_DIR, f"{pid}.json")
    if not refresh and os.path.isfile(cp) and time.time() - os.path.getmtime(cp) < 86400:
        return json.load(open(cp)), cp, False
    d = fetch_openapi(pid, env_file)
    json.dump(d, open(cp, "w"), ensure_ascii=False)
    return d, cp, True


def ops(d):
    for path, item in (d.get("paths") or {}).items():
        for m in METHODS:
            if m in item and isinstance(item[m], dict):
                yield m.upper(), path, item[m]


# ── schemas ───────────────────────────────────────────────────────────────────

def deref(d, node, depth=2):
    """Resolve $ref two levels deep; beyond that print the name. Keeps output readable, not exhaustive."""
    if isinstance(node, dict):
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            if depth <= 0:
                return {"$schema": name}
            target = (d.get("components") or {}).get("schemas", {}).get(name)
            return {"$schema": name, **deref(d, target, depth - 1)} if isinstance(target, dict) else {"$schema": name}
        return {k: deref(d, v, depth) for k, v in node.items() if k not in ("x-apifox-orders", "x-apifox-ignore-properties", "x-apifox-folder", "x-apifox-status")}
    if isinstance(node, list):
        return [deref(d, x, depth) for x in node]
    return node


def compact_schema(s, indent=0):
    """A schema as indented lines: name: type (required) — description."""
    lines, pad = [], "  " * indent
    if not isinstance(s, dict):
        return lines
    if s.get("$schema") and indent > 3:
        return [f"{pad}<{s['$schema']}>"]
    t = s.get("type") or ("object" if "properties" in s else "")
    req = set(s.get("required") or [])
    if t == "object" or "properties" in s:
        for k, v in (s.get("properties") or {}).items():
            vt = v.get("type") or ("object" if "properties" in v else ("array" if "items" in v else v.get("$schema", "")))
            if vt == "array":
                it = v.get("items") or {}
                vt = f"array<{it.get('type') or it.get('$schema') or 'object'}>"
            desc = (v.get("description") or v.get("title") or "").replace("\n", " ")[:80]
            enum = f" ∈ {v['enum']}" if v.get("enum") else ""
            lines.append(f"{pad}{k}{'*' if k in req else ''}: {vt}{enum}" + (f"  — {desc}" if desc else ""))
            if "properties" in v or ("items" in v and isinstance(v["items"], dict) and "properties" in v["items"]):
                lines += compact_schema(v if "properties" in v else v["items"], indent + 1)
    elif t == "array":
        lines.append(f"{pad}array<{(s.get('items') or {}).get('type') or (s.get('items') or {}).get('$schema') or 'object'}>")
        lines += compact_schema(s.get("items") or {}, indent + 1)
    else:
        lines.append(f"{pad}{t}" + (f"  — {s.get('description', '')[:80]}" if s.get("description") else ""))
    return lines


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_projects(a):
    kp = known_projects()
    rows = []
    for name, p in kp.items():
        cp = os.path.join(CACHE_DIR, f"{p['id']}.json")
        cached = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(cp))) if os.path.isfile(cp) else ""
        rows.append({"name": name, "id": p["id"], "note": p["note"], "cached": cached})
    if a.json:
        print(json.dumps(rows, ensure_ascii=False)); return
    if not rows:
        print("no projects recorded — add `projects:` entries to <records>/map/apis.yaml (name: {id: N, note: …})"); return
    for r in rows:
        print(f"{r['name']:<12} {r['id']:<10} {('cached ' + r['cached']) if r['cached'] else 'not fetched':<24} {r['note']}")


def cmd_export(a):
    pid = project_id(a.project)
    d, cp, fresh = load(pid, a.env_file, refresh=a.refresh)
    n = sum(1 for _ in ops(d))
    if a.json:
        print(json.dumps({"project": pid, "title": d.get("info", {}).get("title"), "operations": n, "tags": len(d.get("tags") or []), "cache": cp, "fetched_now": fresh})); return
    print(f"{d.get('info', {}).get('title')}  project {pid}  {n} operations · {len(d.get('tags') or [])} tags  → {cp}{' (fetched now)' if fresh else ' (cache)'}")


def cmd_tags(a):
    d, _, _ = load(project_id(a.project), a.env_file)
    counts = {}
    for _, _, op in ops(d):
        for t in op.get("tags") or ["(untagged)"]:
            counts[t] = counts.get(t, 0) + 1
    if a.json:
        print(json.dumps(counts, ensure_ascii=False)); return
    for t, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"{n:>4}  {t}")


def cmd_list(a):
    d, _, _ = load(project_id(a.project), a.env_file)
    q = (a.grep or "").lower()
    rows = []
    for m, path, op in ops(d):
        tags = op.get("tags") or []
        if a.tag and not any(a.tag.lower() == t.lower() or a.tag.lower() in t.lower() for t in tags):
            continue
        hay = " ".join([path, op.get("summary") or "", op.get("operationId") or "", op.get("description") or ""]).lower()
        if q and q not in hay:
            continue
        rows.append({"method": m, "path": path, "summary": op.get("summary") or "", "operationId": op.get("operationId") or "", "tags": tags})
    if a.json:
        print(json.dumps(rows, ensure_ascii=False)); return
    if not rows:
        print("no operations match", file=sys.stderr); sys.exit(EX_NOTFOUND)
    for r in rows:
        print(f"{r['method']:<7} {r['path']:<60} {r['summary'][:50]:<50} {'/'.join(r['tags'][:2])}")


def find_op(d, ref):
    ref_l = ref.strip().lower()
    m = re.match(r"^(get|post|put|patch|delete|head|options)\s+(\S+)$", ref_l)
    hits = []
    for meth, path, op in ops(d):
        if m and meth.lower() == m.group(1) and path.lower() == m.group(2):
            return [(meth, path, op)]
        if path.lower() == ref_l or (op.get("operationId") or "").lower() == ref_l:
            hits.append((meth, path, op))
    if hits:
        return hits
    return [(meth, path, op) for meth, path, op in ops(d) if ref_l in (op.get("summary") or "").lower() or ref_l in path.lower()]


def cmd_read(a):
    d, _, _ = load(project_id(a.project), a.env_file)
    hits = find_op(d, a.ref)
    if not hits:
        print(f"no operation matches {a.ref!r}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    if len(hits) > 1 and not a.all:
        print(f"{len(hits)} operations match — say which (METHOD path):", file=sys.stderr)
        for meth, path, op in hits[:20]:
            print(f"  {meth:<7} {path:<60} {(op.get('summary') or '')[:50]}", file=sys.stderr)
        sys.exit(EX_USAGE)
    out = []
    for meth, path, op in hits:
        params = [{"name": p.get("name"), "in": p.get("in"), "required": bool(p.get("required")), "type": (p.get("schema") or {}).get("type", ""),
                   "description": (p.get("description") or "")[:120]} for p in (op.get("parameters") or []) if isinstance(p, dict)]
        rb = op.get("requestBody") or {}
        body_schema = None
        for ct, media in ((rb.get("content") or {}).items()):
            body_schema = deref(d, media.get("schema") or {}); body_ct = ct; break
        responses = {}
        for code, resp in (op.get("responses") or {}).items():
            sch = None
            for ct, media in ((resp.get("content") or {}).items()):
                sch = deref(d, media.get("schema") or {}); break
            responses[code] = {"description": (resp.get("description") or "")[:100], "schema": sch}
        rec = {"method": meth, "path": path, "summary": op.get("summary") or "", "operationId": op.get("operationId") or "",
               "tags": op.get("tags") or [], "description": (op.get("description") or "")[:600], "parameters": params,
               "requestBody": body_schema, "responses": responses}
        out.append(rec)
        if not a.json:
            print(f"# {meth} {path}\n{rec['summary']}  ·  {'/'.join(rec['tags'])}" + (f"\n{rec['description']}" if rec['description'] else ""))
            if params:
                print("parameters:")
                for p in params:
                    print(f"  {p['name']}{'*' if p['required'] else ''} ({p['in']}, {p['type'] or '?'})" + (f"  — {p['description']}" if p['description'] else ""))
            if body_schema:
                print(f"request body ({body_ct}):"); print("\n".join(compact_schema(body_schema, 1)) or "  (opaque)")
            for code, r in responses.items():
                print(f"response {code}: {r['description']}")
                if r["schema"]:
                    print("\n".join(compact_schema(r["schema"], 1)))
            print()
    if a.json:
        print(json.dumps(out if len(out) > 1 else out[0], ensure_ascii=False))


def cmd_schema(a):
    d, _, _ = load(project_id(a.project), a.env_file)
    schemas = (d.get("components") or {}).get("schemas") or {}
    name = a.name if a.name in schemas else next((k for k in schemas if k.lower() == a.name.lower()), None)
    if not name:
        near = [k for k in schemas if a.name.lower() in k.lower()][:15]
        print(f"no schema {a.name!r}" + (f"; near: {', '.join(near)}" if near else ""), file=sys.stderr); sys.exit(EX_NOTFOUND)
    s = deref(d, schemas[name])
    if a.json:
        print(json.dumps({"name": name, "schema": s}, ensure_ascii=False)); return
    print(f"# {name}"); print("\n".join(compact_schema(s, 1)) or json.dumps(s, ensure_ascii=False)[:800])


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description="Apifox API definitions, read-only.")
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("projects"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("export"); p.add_argument("project"); p.add_argument("--refresh", action="store_true"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("tags"); p.add_argument("project"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("list"); p.add_argument("project"); p.add_argument("--tag"); p.add_argument("--grep"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("read"); p.add_argument("project"); p.add_argument("ref"); p.add_argument("--all", action="store_true", help="print every match instead of asking"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("schema"); p.add_argument("project"); p.add_argument("name"); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    {"projects": cmd_projects, "export": cmd_export, "tags": cmd_tags, "list": cmd_list, "read": cmd_read, "schema": cmd_schema}[a.cmd](a)


if __name__ == "__main__":
    main()
