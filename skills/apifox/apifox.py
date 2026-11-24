#!/usr/bin/env python3
"""Apifox — the API definitions the teams keep in Apifox, read first-hand. Read-only, stdlib only.

  projects                          the projects ela knows by name (<elak>/map/apis.yaml) and their cache state
  projects --team <id>|all [--grep text]   every project a team holds (team ids from apis.yaml `teams:`)
  export  <project> [--refresh]     fetch the project's API document (cached a day under ~/.claude/ela/apifox/)
  tags    <project>                 the tags (folders) and how many operations each carries
  list    <project> [--tag T] [--grep text]   operations: METHOD path · summary · tag
  read    <project> <ref>           one operation in full: parameters, request body, responses — ref = path, operationId,
                                    "METHOD path", or a summary fragment (unique match required)
  schema  <project> <Name>          one component schema, $refs resolved two levels deep
  diff    <a> <b> [--tag T] [--tag-b T]   two contracts compared: operations on one side only, the same name at
                                    another path, parameter and body-field mismatches of matched operations

<project> may also be the public API doc customers read (`public`, apis.yaml `docs:`, or its URL): pubdoc.py.

<project> is a name from apis.yaml (ur, …) or a numeric Apifox project id; an app.apifox.com/project/<id> URL works too.
Two read paths, same output. First the Open API export (OpenAPI 3.1), which needs maintainer rights on the project;
on 403 the member read: the web client's API (/api/v1 api-details, api-tree-list, data-schemas) with the same token,
converted to the export's shape, folder paths as tags. The member read is undocumented; a body that does not match
the expected shape exits 5 with the body, never an empty result. The cache records which path produced it.
Credentials: APIFOX_TOKEN (a personal access token) from the env or the env file, sent as a Bearer header.
Apifox's edge drops requests without a User-Agent, so one is always sent.
Exit codes: 0 ok · 2 usage · 3 not found · 4 auth · 5 remote error.
"""
import argparse, json, os, re, signal, sys, time, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import pubdoc

EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE = 2, 3, 4, 5
SITE = os.path.expanduser("~/.claude/ela/site.json")
CACHE_DIR = os.path.expanduser("~/.claude/ela/apifox")
API = "https://api.apifox.com/v1"
VERSION = "2024-03-28"
WEB_API = "https://api.apifox.com/api/v1"   # the web client's API: what a project member can read without maintainer rights
WEB_CLIENT_VERSION = "2.7.2"
CONTEXT = ""   # set once export was refused, so a member-read failure names both attempts
METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


def site_env():
    """The site's env file, site.json `env`: read only when neither --env-file nor an env-file variable names one."""
    try:
        return os.path.expanduser(json.load(open(os.path.expanduser("~/.claude/ela/site.json"))).get("env") or "") or None
    except (OSError, ValueError, AttributeError):
        return None


def env_value(key, env_file=None):
    v = os.environ.get(key)
    if v:
        return v
    for path in [p for p in (env_file, os.environ.get("ELA_ENV_FILE")) if p] or filter(None, [site_env()]):
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
    """<elak>/map/apis.yaml → {name: {id, note}}. A small YAML subset: `projects:` then `  name: {id: N, note: …}` or `  name: N`."""
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


def known_teams():
    """<elak>/map/apis.yaml `teams:` → [{id, note}], entries written `  - {id: N, note: …}`."""
    path = os.path.join(site().get("map", ""), "apis.yaml")
    try:
        text = open(path).read()
    except OSError:
        return []
    out, section = [], None
    for line in text.splitlines():
        line = re.sub(r"\s+#.*$", "", line.rstrip())
        if re.match(r"^[a-z_]+:\s*$", line):
            section = line.strip(":"); continue
        m = re.match(r"^  - \{\s*id:\s*(\d+)\s*(?:,\s*note:\s*(.+?)\s*)?\}$", line)
        if m and section == "teams":
            out.append({"id": m.group(1), "note": (m.group(2) or "").strip("'\"")})
    return out


def known_docs():
    """<elak>/map/apis.yaml `docs:` → {name: {apidog, note}}: published doc sites, entries `  name: {apidog: N, note: …}`."""
    path = os.path.join(site().get("map", ""), "apis.yaml")
    try:
        text = open(path).read()
    except OSError:
        return {}
    out, section = {}, None
    for line in text.splitlines():
        line = re.sub(r"\s+#.*$", "", line.rstrip())
        if re.match(r"^[a-z_]+:\s*$", line):
            section = line.strip(":"); continue
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*\{\s*apidog:\s*(\d+)\s*(?:,\s*note:\s*(.+?)\s*)?\}$", line)
        if m and section == "docs":
            out[m.group(1)] = {"apidog": m.group(2), "note": (m.group(3) or "").strip("'\"")}
    return out


def document(ref, env_file, hydrate=lambda e: False, refresh=False):
    """(dict, cache, fetched_now, project label) for an Apifox project or the public doc; the commands below read
    either the same way. For the public doc `hydrate(entry)` picks the endpoints read in full (pubdoc.load)."""
    if pubdoc.is_public(ref, known_docs()):
        d = pubdoc.load(to_openapi, hydrate=hydrate, refresh=refresh)
        return d, pubdoc.CACHE, d.get("x-ela-fetched"), "public"
    pid = project_id(ref)
    d, cp, fresh = load(pid, env_file, refresh=refresh)
    return d, cp, fresh, pid


EVERY = lambda e: True


class Refused(Exception):
    """An HTTP 401/403 from Apifox, kept so load() can decide whether the other read path applies."""
    def __init__(self, code, why):
        super().__init__(f"HTTP {code}: {why or 'no detail'}")
        self.code, self.why = code, why


def token(env_file):
    tok = env_value("APIFOX_TOKEN", env_file)
    if not tok:
        print("no APIFOX_TOKEN in the env file — run /ela:setup", file=sys.stderr); sys.exit(EX_AUTH)
    return tok


def http_json(url, headers, data=None, timeout=120):
    """One request → parsed JSON. 401/403 raise Refused; 404 exits 3; anything else unexpected exits 5."""
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                 headers={"Accept": "application/json", "User-Agent": "ela (python-urllib)", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        body = e.read()
        if e.code in (401, 403):
            try:
                why = json.loads(body.decode()).get("errorMessage") or ""
            except Exception:
                why = ""
            raise Refused(e.code, why)
        if e.code == 404:
            print(f"apifox: {CONTEXT}not found — {url.split('?')[0]}", file=sys.stderr); sys.exit(EX_NOTFOUND)
        print(f"apifox: {CONTEXT}HTTP {e.code} {body[:200]!r}", file=sys.stderr); sys.exit(EX_REMOTE)
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"apifox: {CONTEXT}unreachable ({e})", file=sys.stderr); sys.exit(EX_REMOTE)
    try:
        return json.loads(raw)
    except ValueError:
        print(f"apifox: {CONTEXT}not JSON ({len(raw)} bytes) from {url.split('?')[0]}", file=sys.stderr); sys.exit(EX_REMOTE)


def fetch_openapi(pid, tok):
    """The Open API export. Needs maintainer rights on the project; a member gets 403."""
    body = json.dumps({"scope": {"type": "ALL"}, "options": {"includeApifoxExtensionProperties": False, "addFoldersToTags": True},
                       "oasVersion": "3.1", "exportFormat": "JSON"}).encode()
    d = http_json(f"{API}/projects/{pid}/export-openapi?locale=zh-CN", data=body,
                  headers={"Authorization": f"Bearer {tok}", "X-Apifox-Api-Version": VERSION, "Content-Type": "application/json"})
    if not isinstance(d, dict) or "paths" not in d:
        print(f"apifox: export returned an unexpected body {json.dumps(d, ensure_ascii=False)[:300]}", file=sys.stderr); sys.exit(EX_REMOTE)
    return d


# ── member read: the web client's API ─────────────────────────────────────────
# Undocumented and owned by Apifox: every shape is checked, and a body that does not match exits 5 with the body
# rather than yielding an empty or partial document.

def web_get(pid, tok, path):
    d = http_json(f"{WEB_API}{path}?locale=zh-CN", timeout=120,
                  headers={"Authorization": f"Bearer {tok}", "X-Project-Id": str(pid), "X-Client-Version": WEB_CLIENT_VERSION})
    if not (isinstance(d, dict) and d.get("success") is True and "data" in d):
        print(f"apifox: {CONTEXT}{path}: unexpected body {json.dumps(d, ensure_ascii=False)[:300]}", file=sys.stderr); sys.exit(EX_REMOTE)
    return d["data"]


def shape_error(what, sample):
    print(f"apifox: {CONTEXT}{what}; the client API's shape may have changed: {json.dumps(sample, ensure_ascii=False)[:300]}", file=sys.stderr)
    sys.exit(EX_REMOTE)


def fetch_member(pid, tok):
    """The same content through the web client's API, converted to the OpenAPI-like dict the export yields."""
    info = web_get(pid, tok, f"/projects/{pid}")
    details = web_get(pid, tok, "/api-details")
    tree = web_get(pid, tok, "/api-tree-list")
    schemas = web_get(pid, tok, f"/projects/{pid}/data-schemas")
    for what, v in (("api-details", details), ("api-tree-list", tree), ("data-schemas", schemas)):
        if not isinstance(v, list):
            shape_error(f"{what} is not a list", v)
    if not details:
        shape_error("api-details returned no operations", details)
    bad = next((x for x in details if not (isinstance(x, dict) and x.get("method") and x.get("path"))), None)
    if bad is not None:
        shape_error("an operation without method/path", bad)

    # folder path per operation id, as export's addFoldersToTags names it ("pilot/Node")
    folder_of = {}
    def walk(nodes, trail):
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            key = str(n.get("key") or "")
            if key.startswith("apiDetailFolder."):
                walk(n.get("children"), trail + [n.get("name") or ""])
            elif key.startswith("apiDetail."):
                folder_of[key.split(".", 1)[1]] = "/".join(trail)
    walk(tree, [])
    return to_openapi(info.get("name") if isinstance(info, dict) else None, pid, details, folder_of, schemas)


def to_openapi(title, pid, details, folder_of, schemas):
    """Operations in the Apifox/Apidog client shape (api-details: method, path, parameters by place, requestBody,
    responses) → the OpenAPI-like dict the export yields. Shared by the member read and the public doc, whose
    pages carry the same shape. `folder_of` maps an operation id to its folder path; `schemas` is a list of
    {id, name, jsonSchema}."""
    # component schemas: web refs are "#/definitions/<schema id>" or "#/components/schemas/<name>"; both end up by name
    names, comps = {}, {}
    for s in schemas:
        if not (isinstance(s, dict) and "id" in s and "jsonSchema" in s):
            shape_error("a data schema without id/jsonSchema", s)
        name = s.get("name") or str(s["id"])
        if name in comps:
            name = f"{name}.{s['id']}"
        names[str(s["id"])] = name
        comps[name] = s["jsonSchema"]

    def fix_refs(node):
        if isinstance(node, dict):
            out = {k: fix_refs(v) for k, v in node.items()}
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/definitions/"):
                sid = ref.rsplit("/", 1)[-1]
                out["$ref"] = f"#/components/schemas/{names.get(sid, sid)}"
            return out
        if isinstance(node, list):
            return [fix_refs(x) for x in node]
        return node

    def body_of(rb):
        t = rb.get("type") or "none"
        if t == "none":
            return None
        fields = [f for f in rb.get("parameters") or [] if isinstance(f, dict) and f.get("name")]
        if fields:   # form bodies carry their fields as parameters
            schema = {"type": "object", "properties": {f["name"]: {"type": f.get("type") or "string", "description": f.get("description") or ""} for f in fields},
                      "required": [f["name"] for f in fields if f.get("required")]}
        else:
            schema = rb.get("jsonSchema") or {"type": "string"}
            if schema.get("type") == "object" and not (schema.get("properties") or schema.get("$ref") or schema.get("additionalProperties")):
                return None   # the editor's empty default, not a declared body
        return {"required": bool(rb.get("required")), "content": {rb.get("mediaType") or t: {"schema": schema}}}

    paths, dropped = {}, 0
    for x in details:
        path = re.sub(r"^[a-z]+://[^/]+", "", x["path"])   # as export does: a full URL keeps its path only
        path = path if path.startswith("/") else "/" + path
        method = x["method"].lower()
        if method in paths.get(path, {}):
            dropped += 1; continue
        params = []
        for where in ("path", "query", "header", "cookie"):
            for p in (x.get("parameters") or {}).get(where) or []:
                if isinstance(p, dict) and p.get("name"):
                    params.append({"name": p["name"], "in": where, "required": bool(p.get("required")), "description": p.get("description") or "",
                                   "example": p.get("example"), "schema": p.get("schema") or {"type": p.get("type") or "string"}})
        responses = {}
        for r in x.get("responses") or []:
            if not isinstance(r, dict):
                continue
            ct = r.get("mediaType") or ("application/json" if r.get("contentType") == "json" else r.get("contentType") or "application/json")
            responses[str(r.get("code"))] = {"description": r.get("description") or r.get("name") or "",
                                             "content": {ct: {"schema": r.get("jsonSchema") or {}}}}
        folder = folder_of.get(str(x.get("id")), "")
        tags = ([folder] if folder else []) + [t for t in x.get("tags") or [] if t != folder]
        op = {"summary": x.get("name") or "", "operationId": x.get("operationId") or "", "description": x.get("description") or "",
              "tags": tags, "parameters": params, "responses": responses}
        rb = body_of(x.get("requestBody") or {})
        if rb:
            op["requestBody"] = rb
        paths.setdefault(path, {})[method] = fix_refs(op)
    tag_names = sorted({t for item in paths.values() for op in item.values() for t in op["tags"]})
    return {"openapi": "3.1.0", "info": {"title": title or f"project {pid}"}, "tags": [{"name": t} for t in tag_names], "paths": paths,
            "components": {"schemas": fix_refs(comps)}, "x-ela-dropped-duplicates": dropped}


def load(pid, env_file, refresh=False):
    """cache → export → (on 403) member read. The cache records which path produced it (x-ela-source)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cp = os.path.join(CACHE_DIR, f"{pid}.json")
    if not refresh and os.path.isfile(cp) and time.time() - os.path.getmtime(cp) < 86400:
        return json.load(open(cp)), cp, False
    tok = token(env_file)
    try:
        d, source = fetch_openapi(pid, tok), "export"
    except Refused as e:
        if e.code == 401:
            print(f"apifox: export on project {pid}: {e} — the token is invalid or expired; run /ela:setup", file=sys.stderr); sys.exit(EX_AUTH)
        global CONTEXT
        CONTEXT = f"export refused ({e}); member read: "
        try:
            d, source = fetch_member(pid, tok), "member read"
        except Refused as w:
            hint = "the token is invalid or expired; run /ela:setup" if w.code == 401 else "the account cannot see this project as a member either"
            print(f"apifox: project {pid} unreadable — export: {e}; member read: {w} — {hint}", file=sys.stderr); sys.exit(EX_AUTH)
    d["x-ela-source"] = source
    print(f"apifox: project {pid} read by {source}", file=sys.stderr)
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

def cmd_team_projects(a):
    teams = known_teams()
    ids = [t["id"] for t in teams] if a.team == "all" else [a.team]
    if not ids:
        print("no teams recorded — add `teams:` entries to <elak>/map/apis.yaml (- {id: N, note: …})", file=sys.stderr); sys.exit(EX_USAGE)
    tok = token(a.env_file)
    named = {p["id"]: n for n, p in known_projects().items()}
    q = (a.grep or "").lower()
    rows = []
    for tid in ids:
        try:
            d = http_json(f"{API}/teams/{tid}/projects?locale=zh-CN", timeout=60, headers={"Authorization": f"Bearer {tok}", "X-Apifox-Api-Version": VERSION})
        except Refused as e:
            print(f"apifox: team {tid}: {e} — the token is invalid or the account is not in this team", file=sys.stderr); sys.exit(EX_AUTH)
        if not (isinstance(d, dict) and d.get("success") is True and isinstance(d.get("data"), list)):
            print(f"apifox: team {tid}: unexpected body {json.dumps(d, ensure_ascii=False)[:300]}", file=sys.stderr); sys.exit(EX_REMOTE)
        for p in d["data"]:
            if not (isinstance(p, dict) and "id" in p):
                print(f"apifox: team {tid}: unexpected project entry {json.dumps(p, ensure_ascii=False)[:200]}", file=sys.stderr); sys.exit(EX_REMOTE)
            if q and q not in (p.get("name") or "").lower() and q not in str(p["id"]):
                continue
            rows.append({"team": str(tid), "id": str(p["id"]), "name": p.get("name") or "", "known_as": named.get(str(p["id"]), "")})
    if a.json:
        print(json.dumps(rows, ensure_ascii=False)); return
    if not rows:
        print("no projects match", file=sys.stderr); sys.exit(EX_NOTFOUND)
    for r in rows:
        print(f"{r['team']:<9} {r['id']:<10} {r['name']}" + (f"  (apis.yaml: {r['known_as']})" if r["known_as"] else ""))


def cmd_projects(a):
    if a.team:
        return cmd_team_projects(a)
    kp = known_projects()
    rows = []
    for name, p in kp.items():
        cp = os.path.join(CACHE_DIR, f"{p['id']}.json")
        cached = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(cp))) if os.path.isfile(cp) else ""
        rows.append({"name": name, "id": p["id"], "note": p["note"], "cached": cached})
    for name, p in known_docs().items():
        cp = os.path.join(pubdoc.CACHE, "catalog.json")
        cached = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(cp))) if os.path.isfile(cp) else ""
        rows.append({"name": name, "id": f"apidog {p['apidog']}", "note": p["note"], "cached": cached})
    if a.json:
        print(json.dumps(rows, ensure_ascii=False)); return
    if not rows:
        print("no projects recorded — add `projects:` entries to <elak>/map/apis.yaml (name: {id: N, note: …})"); return
    for r in rows:
        print(f"{r['name']:<12} {r['id']:<10} {('cached ' + r['cached']) if r['cached'] else 'not fetched':<24} {r['note']}")


def cmd_export(a):
    d, cp, fresh, pid = document(a.project, a.env_file, EVERY, refresh=a.refresh)
    n = sum(1 for _ in ops(d))
    if a.json:
        print(json.dumps({"project": pid, "title": d.get("info", {}).get("title"), "operations": n, "tags": len(d.get("tags") or []), "cache": cp,
                          "fetched_now": fresh, "source": d.get("x-ela-source", "export")})); return
    print(f"{d.get('info', {}).get('title')}  project {pid}  {n} operations · {len(d.get('tags') or [])} tags  → {cp}"
          f" ({d.get('x-ela-source', 'export')}, {'fetched now' if fresh else 'cache'})")


def cmd_tags(a):
    d = document(a.project, a.env_file)[0]
    counts = {}
    for _, _, op in ops(d):
        for t in op.get("tags") or ["(untagged)"]:
            counts[t] = counts.get(t, 0) + 1
    if a.json:
        print(json.dumps(counts, ensure_ascii=False)); return
    for t, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"{n:>4}  {t}")


def cmd_list(a):
    d = document(a.project, a.env_file)[0]
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
    slug = re.search(r"(api-\d+)$", ref_l)
    if slug:   # a public-doc page, api-<id> or its URL
        hit = [(meth, path, op) for meth, path, op in ops(d) if op.get("x-ela-slug") == slug.group(1)]
        if hit:
            return hit
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
    d = document(a.project, a.env_file)[0]
    hits = find_op(d, a.ref)
    if hits and (len(hits) == 1 or a.all) and not all(op.get("x-ela-detail", True) for _, _, op in hits):
        # the public doc lists from its catalog; the matched endpoints are now read in full
        slugs = {op.get("x-ela-slug") for _, _, op in hits}
        d = document(a.project, a.env_file, lambda e: f"api-{e['id']}" in slugs)[0]
        keys = {(m, p) for m, p, _ in hits}
        hits = [(m, p, op) for m, p, op in ops(d) if (m, p) in keys]
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
               **({"doc": f"{pubdoc.BASE}/{op['x-ela-slug']}"} if op.get("x-ela-slug") else {}),
               "tags": op.get("tags") or [], "description": (op.get("description") or "")[:600], "parameters": params,
               "requestBody": body_schema, "responses": responses}
        out.append(rec)
        if not a.json:
            print(f"# {meth} {path}\n{rec['summary']}  ·  {'/'.join(rec['tags'])}" + (f"  ·  {rec['doc']}" if rec.get("doc") else "")
                  + (f"\n{rec['description']}" if rec['description'] else ""))
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
    d = document(a.project, a.env_file, EVERY)[0]
    schemas = (d.get("components") or {}).get("schemas") or {}
    name = a.name if a.name in schemas else next((k for k in schemas if k.lower() == a.name.lower()), None)
    if not name:
        near = [k for k in schemas if a.name.lower() in k.lower()][:15]
        print(f"no schema {a.name!r}" + (f"; near: {', '.join(near)}" if near else ""), file=sys.stderr); sys.exit(EX_NOTFOUND)
    s = deref(d, schemas[name])
    if a.json:
        print(json.dumps({"name": name, "schema": s}, ensure_ascii=False)); return
    print(f"# {name}"); print("\n".join(compact_schema(s, 1)) or json.dumps(s, ensure_ascii=False)[:800])


# ── diff ──────────────────────────────────────────────────────────────────────
# Two contracts of one API — typically what customers read (public) and what a team declares (an Apifox
# project) — compared operation by operation. Paths match exactly first; then by segment-aligned suffix, since
# one side often carries a gateway prefix (/mediahub/api/v2/… against /api/v2/…). A suffix that fits several
# operations is not guessed: both stay unmatched. Auth and transport headers are not compared.

QUIET_HEADERS = {"sid", "authorization", "content-type", "accept", "x-access-token"}


def _segs(path):
    return [("{}" if re.fullmatch(r"\{[^}]*\}", x) else x.lower()) for x in path.strip("/").split("/") if x]


def _scoped(d, tag):
    t = (tag or "").lower()
    return [(m, p, op) for m, p, op in ops(d) if not t or any(t == x.lower() or x.lower().startswith(t + "/") for x in op.get("tags") or [])]


def _params(op):
    out = {}
    for x in op.get("parameters") or []:
        if isinstance(x, dict) and x.get("name") and not (x.get("in") == "header" and x["name"].lower() in QUIET_HEADERS):
            out[(x.get("in"), x["name"])] = {"required": bool(x.get("required")), "type": (x.get("schema") or {}).get("type") or ""}
    return out


def _body(d, op):
    for media in ((op.get("requestBody") or {}).get("content") or {}).values():
        s = deref(d, media.get("schema") or {}, 1)
        if s.get("type") == "array" and isinstance(s.get("items"), dict):
            s = deref(d, s["items"], 1)
        return {k: {"type": (v or {}).get("type") or (v or {}).get("$schema") or "", "required": k in (s.get("required") or [])}
                for k, v in (s.get("properties") or {}).items()}
    return None


def compare_ops(da, a_op, db, b_op):
    """The differences of one matched pair, as lines (empty when they agree)."""
    out = []
    pa, pb = _params(a_op), _params(b_op)
    for k in sorted(set(pa) | set(pb)):
        where, name = k
        if k not in pb:
            out.append(f"param {name} ({where}): only in A"); continue
        if k not in pa:
            out.append(f"param {name} ({where}): only in B"); continue
        if pa[k]["required"] != pb[k]["required"]:
            out.append(f"param {name} ({where}): required A {'yes' if pa[k]['required'] else 'no'}, B {'yes' if pb[k]['required'] else 'no'}")
        if pa[k]["type"] and pb[k]["type"] and pa[k]["type"] != pb[k]["type"]:
            out.append(f"param {name} ({where}): type A {pa[k]['type']}, B {pb[k]['type']}")
    ba, bb = _body(da, a_op), _body(db, b_op)
    if (ba is None) != (bb is None):
        out.append(f"request body: only in {'A' if ba is not None else 'B'}")
    elif ba is not None:
        only_a, only_b = sorted(set(ba) - set(bb)), sorted(set(bb) - set(ba))
        if only_a:
            out.append(f"body fields only in A: {', '.join(only_a)}")
        if only_b:
            out.append(f"body fields only in B: {', '.join(only_b)}")
        for k in sorted(set(ba) & set(bb)):
            if ba[k]["required"] != bb[k]["required"]:
                out.append(f"body field {k}: required A {'yes' if ba[k]['required'] else 'no'}, B {'yes' if bb[k]['required'] else 'no'}")
            if ba[k]["type"] and bb[k]["type"] and ba[k]["type"] != bb[k]["type"]:
                out.append(f"body field {k}: type A {ba[k]['type']}, B {bb[k]['type']}")
    return out


def match_ops(A, B):
    """(pairs [(a, b, how)], only_a, only_b). a/b are (METHOD, path, op)."""
    bkey = {}
    for x in B:
        bkey.setdefault((x[0], tuple(_segs(x[1]))), []).append(x)
    pairs, rest_a, used = [], [], set()
    for x in A:
        hit = [y for y in bkey.get((x[0], tuple(_segs(x[1]))), []) if id(y) not in used]
        if len(hit) == 1:
            pairs.append((x, hit[0], "exact")); used.add(id(hit[0]))
        else:
            rest_a.append(x)
    rest_b = [y for y in B if id(y) not in used]
    def fits(x, y):
        sa, sb = _segs(x[1]), _segs(y[1]); n = min(len(sa), len(sb))
        return x[0] == y[0] and n >= 2 and sa[-n:] == sb[-n:]
    cand = {id(x): [y for y in rest_b if fits(x, y)] for x in rest_a}
    claims = {}
    for x in rest_a:
        for y in cand[id(x)]:
            claims[id(y)] = claims.get(id(y), 0) + 1
    still_a = []
    for x in rest_a:      # a suffix pair only when each side has exactly one candidate
        c = cand[id(x)]
        if len(c) == 1 and claims[id(c[0])] == 1:
            pairs.append((x, c[0], "suffix")); rest_b.remove(c[0])
        else:
            still_a.append(x)
    return pairs, still_a, rest_b


def cmd_diff(a):
    tag_a, tag_b = a.tag, a.tag_b if a.tag_b is not None else None
    hyd = (lambda e: not tag_a or "/".join(e["folder"]).lower() == tag_a.lower() or "/".join(e["folder"]).lower().startswith(tag_a.lower() + "/"))
    da, _, _, la = document(a.a, a.env_file, hyd)
    hyd_b = (lambda e: not tag_b or "/".join(e["folder"]).lower() == tag_b.lower() or "/".join(e["folder"]).lower().startswith(tag_b.lower() + "/"))
    db, _, _, lb = document(a.b, a.env_file, hyd_b)
    A, B = _scoped(da, tag_a), _scoped(db, tag_b)
    if not A:
        print(f"A ({a.a}) has no operations under tag {tag_a!r}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    pairs, only_a, only_b = match_ops(A, B)
    diffs = [(x, y, how, compare_ops(da, x[2], db, y[2])) for x, y, how in pairs]
    # B's operations outside every folder A also has (feign, admin … on an internal project) are counted, not listed
    leaves = {t.rsplit("/", 1)[-1].lower() for _, _, o in A for t in o.get("tags") or []}
    shared = lambda o: tag_b is not None or any(t.rsplit("/", 1)[-1].lower() in leaves for t in o.get("tags") or [])
    elsewhere = {}
    for _, _, o in only_b:
        if not shared(o):
            k = "/".join(o.get("tags") or []) or "(untagged)"; elsewhere[k] = elsewhere.get(k, 0) + 1
    # an operation under the same name on both sides but at different paths: drift worth its own line
    name = lambda o: (o.get("operationId") or o.get("summary") or "").strip().lower()
    nb = {}
    for y in only_b:
        if name(y[2]):
            nb.setdefault(name(y[2]), []).append(y)
    renamed = [(x, nb[name(x[2])][0]) for x in only_a if len(nb.get(name(x[2]), [])) == 1]
    title = lambda d, l: f"{(d.get('info') or {}).get('title')} ({l})"
    rec = {"A": {"source": title(da, la), "tag": tag_a, "operations": len(A)}, "B": {"source": title(db, lb), "tag": tag_b, "operations": len(B)},
           "matched": len(pairs), "matched_by_suffix": sum(1 for p in pairs if p[2] == "suffix"),
           "only_in_A": [{"method": m, "path": p, "summary": o.get("summary") or "", "doc": o.get("x-ela-slug")} for m, p, o in only_a],
           "only_in_B": [{"method": m, "path": p, "summary": o.get("summary") or "", "tag": "/".join(o.get("tags") or [])} for m, p, o in only_b
                         if shared(o)],
           "only_in_B_elsewhere": elsewhere,
           "same_name_other_path": [{"name": x[2].get("summary") or "", "A": f"{x[0]} {x[1]}", "B": f"{y[0]} {y[1]}"} for x, y in renamed],
           "mismatched": [{"A": f"{x[0]} {x[1]}", "B": f"{y[0]} {y[1]}", "how": how, "summary": x[2].get("summary") or "", "differences": dd}
                          for x, y, how, dd in diffs if dd]}
    if a.json:
        print(json.dumps(rec, ensure_ascii=False)); return
    print(f"A  {rec['A']['source']}" + (f" · tag {tag_a}" if tag_a else "") + f" · {len(A)} operations")
    print(f"B  {rec['B']['source']}" + (f" · tag {tag_b}" if tag_b else "") + f" · {len(B)} operations")
    print(f"matched {len(pairs)} ({rec['matched_by_suffix']} by path suffix) · only in A {len(only_a)} · only in B {len(only_b)} · "
          f"differing {len(rec['mismatched'])}")
    if only_a:
        print(f"\n## only in A ({len(only_a)})")
        for r in rec["only_in_A"]:
            print(f"  {r['method']:<7} {r['path']:<58} {r['summary'][:40]}")
    if rec["only_in_B"]:
        print(f"\n## only in B, in folders A also has ({len(rec['only_in_B'])})")
        for r in rec["only_in_B"]:
            print(f"  {r['method']:<7} {r['path']:<58} {r['summary'][:40]}  [{r['tag']}]")
    if elsewhere:
        print(f"\n## only in B, folders A does not have ({sum(elsewhere.values())}): "
              + " · ".join(f"{k} {n}" for k, n in sorted(elsewhere.items(), key=lambda x: -x[1])))
    if renamed:
        print(f"\n## same name, different path ({len(renamed)})")
        for r in rec["same_name_other_path"]:
            print(f"  {r['name'][:40]}: A {r['A']}  ·  B {r['B']}")
    if rec["mismatched"]:
        print(f"\n## matched, differing ({len(rec['mismatched'])})")
        for r in rec["mismatched"]:
            print(f"  {r['A']}" + (f"  ↔  {r['B']}" if r["how"] == "suffix" else "") + f"  · {r['summary'][:40]}")
            for line in r["differences"]:
                print(f"      {line}")


def main():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "configserver"))
    import redact; redact.guard_output()  # a credential inside a remote payload never reaches the terminal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description="Apifox API definitions, read-only.")
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("projects"); p.add_argument("--team", help="a team id from apis.yaml `teams:`, or all"); p.add_argument("--grep"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("export"); p.add_argument("project"); p.add_argument("--refresh", action="store_true"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("tags"); p.add_argument("project"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("list"); p.add_argument("project"); p.add_argument("--tag"); p.add_argument("--grep"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("read"); p.add_argument("project"); p.add_argument("ref"); p.add_argument("--all", action="store_true", help="print every match instead of asking"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("schema"); p.add_argument("project"); p.add_argument("name"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("diff", help="two contracts compared: operations in one only, parameter and body mismatches")
    p.add_argument("a"); p.add_argument("b"); p.add_argument("--tag", help="A's folder (e.g. 'MediaHub API'), its subfolders included")
    p.add_argument("--tag-b", help="B's folder; default all of B"); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    {"projects": cmd_projects, "export": cmd_export, "tags": cmd_tags, "list": cmd_list, "read": cmd_read, "schema": cmd_schema, "diff": cmd_diff}[a.cmd](a)


if __name__ == "__main__":
    main()
