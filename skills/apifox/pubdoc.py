"""The public API documentation customers code against — an Apidog doc site behind TVU userservice SSO — read
into the same OpenAPI-like dict apifox.py builds from Apifox. Read-only, stdlib only; imported by apifox.py.

Mechanism. The site is a Remix app. The root page embeds the whole sidebar (folders, endpoints, docs) as a
turbo-stream inside `streamController.enqueue("…")`; `/api-<id>.data` returns one endpoint as a turbo-stream
array whose resourceData has the Apifox client shape (parameters by place, requestBody, responses) plus the
data-schema definitions it refers to. Turbo-stream: a flat de-duplicated array, a dict `{"_<k>": v}` gives key
and value as indices; inside a list or dict a negative int is null and any other int an index; a value stored
at an index is literal, numbers included.

Reading is lazy, because the site has no bulk export ela can parse with the stdlib and each endpoint page is a
few hundred KB: `tags` and `list` need only the catalog (one page); `read` fetches the endpoints it prints;
`export`, `schema` and `diff` fetch their scope. The catalog and each endpoint are cached a day.

Access. The SID of the owner's test account `li`: session.json `tvu-com-test`, obtained by `ela login tvu --as
test`. Never his own account (`el`) or an admin SID; no login is made here, because the token endpoint is
itself one the docs describe. Only the doc host is fetched; redirects are never followed (a 302 to signIn is a
refused session, and following it would carry the cookie off-host). The SID is sent as a Cookie, never printed.
"""
import concurrent.futures, json, os, re, sys, time, urllib.error, urllib.request

HOST = "document.tvunetworks.com"
BASE = f"https://{HOST}"
APIDOG_PROJECT = "483063"
SESSION_FILE = os.path.expanduser("~/.claude/ela/session.json")
SESSION_KEY = "tvu-com-test"             # the test account `li`; the owner's own sign-in is never used here
CACHE = os.path.expanduser("~/.claude/ela/apifox/public")
DAY = 86400
WORKERS = 6
EX_NOTFOUND, EX_AUTH, EX_REMOTE = 3, 4, 5


def die(msg, code):
    print(f"public doc: {msg}", file=sys.stderr); sys.exit(code)


def is_public(ref, docs):
    """A ref names the public doc: a name under apis.yaml `docs:` whose apidog id is this site's, or a URL on it."""
    if HOST in (ref or ""):
        return True
    entry = docs.get(ref or "")
    return bool(entry) and entry.get("apidog") == APIDOG_PROJECT


def sid():
    try:
        s = json.load(open(SESSION_FILE)).get(SESSION_KEY) or {}
    except (OSError, ValueError):
        s = {}
    v = s.get("sid") or (s.get("cookies") or {}).get("SID")
    if not v:
        die(f"no {SESSION_KEY} session (the test account) — run: ela login tvu --as test", EX_AUTH)
    return v


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def get(path, cookie):
    url = BASE + path
    if urllib.request.urlparse(url).hostname != HOST:
        die(f"refusing a non-doc host in {path!r}", EX_REMOTE)
    req = urllib.request.Request(url, headers={"Cookie": f"SID={cookie}", "User-Agent": "ela (python-urllib)"})
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308, 401, 403):
            die(f"the {SESSION_KEY} session was refused (HTTP {e.code}) — run: ela login tvu --as test", EX_AUTH)
        if e.code == 404:
            die(f"not found — {path}", EX_NOTFOUND)
        die(f"HTTP {e.code} on {path}", EX_REMOTE)
    except (urllib.error.URLError, TimeoutError) as e:
        die(f"unreachable ({e})", EX_REMOTE)


# ── turbo-stream ──────────────────────────────────────────────────────────────

def _js_string(html, i):
    """The body of the JS string literal opening at html[i], still escaped."""
    j, n = i + 1, len(html)
    while j < n:
        c = html[j]
        if c == "\\":
            j += 2; continue
        if c == '"':
            return html[i + 1:j]
        j += 1
    die("an unterminated payload string in the page", EX_REMOTE)


def html_stream(html):
    """The largest enqueue payload of a page, as the flat array. JSON's string escapes are a superset of what
    the page uses, so the literal parses as a JSON string."""
    marker, found, at = "streamController.enqueue(", [], 0
    while True:
        k = html.find(marker, at)
        if k < 0:
            break
        s = _js_string(html, k + len(marker)); found.append(s); at = k + len(marker) + len(s) + 2
    if not found:
        die("no turbo-stream payload in the page; the site's shape may have changed", EX_REMOTE)
    return json.loads(json.loads('"' + max(found, key=len) + '"'))


def resolve(arr):
    n, memo, busy = len(arr), {}, set()
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 20000))

    def r(i):
        if isinstance(i, bool) or not isinstance(i, int):
            return i
        if i < 0:
            return None
        if i >= n:
            return i
        if i in memo:
            return memo[i]
        if i in busy:
            return None
        busy.add(i)
        v = arr[i]
        if isinstance(v, list):   # an int stored at an index is a number; ints inside lists and dicts are references
            out = [r(x) for x in v]
        elif isinstance(v, dict):
            out = {r(int(k[1:])): r(x) for k, x in v.items()}
        else:
            out = v
        busy.discard(i); memo[i] = out
        return out
    return r(0)


def docs_state(tree):
    if isinstance(tree, dict):
        for holder in ((tree.get("root") or {}).get("data"), (tree.get("loaderData") or {}).get("root")):
            if isinstance(holder, dict) and isinstance(holder.get("docsDataState"), dict):
                return holder["docsDataState"]
    die("no docsDataState in the payload; the site's shape may have changed", EX_REMOTE)


# ── cache ─────────────────────────────────────────────────────────────────────

def _cached(name, refresh):
    p = os.path.join(CACHE, name)
    if not refresh and os.path.isfile(p) and time.time() - os.path.getmtime(p) < DAY:
        try:
            return json.load(open(p))
        except ValueError:
            return None
    return None


def _store(name, obj):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name)
    json.dump(obj, open(p + ".tmp", "w"), ensure_ascii=False); os.replace(p + ".tmp", p)


def catalog(refresh=False):
    """[{kind: endpoint|doc|folder, id, name, folder: [..], method, path, status}] from the root page."""
    c = _cached("catalog.json", refresh)
    if c is not None:
        return c, False
    st = docs_state(resolve(html_stream(get("/", sid()).decode("utf-8", "replace"))))
    tree = (st.get("sidebarTree") or {}).get("sidebarTreeList")
    if not isinstance(tree, list) or not tree:
        die("the sidebar is empty or missing; the site's shape may have changed", EX_REMOTE)
    out = []

    def walk(nodes, trail):
        for x in nodes or []:
            if not isinstance(x, dict):
                continue
            t, name = x.get("type"), x.get("name") or ""
            if t == "apiDetail":
                out.append({"kind": "endpoint", "id": str(x.get("id")), "name": name, "folder": trail,
                            "method": (x.get("method") or "").lower(), "path": x.get("path") or "", "status": x.get("status") or ""})
            elif t == "doc":
                out.append({"kind": "doc", "id": str(x.get("id")), "name": name, "folder": trail})
            elif x.get("children") is not None or t == "apiDetailFolder":
                out.append({"kind": "folder", "id": str(x.get("id")), "name": name, "folder": trail})
                walk(x.get("children"), trail + [name])
    walk(tree, [])
    if not any(e["kind"] == "endpoint" for e in out):
        die("the sidebar holds no endpoints; the site's shape may have changed", EX_REMOTE)
    _store("catalog.json", out)
    return out, True


KEEP = ("id", "name", "method", "path", "operationId", "description", "status", "tags", "parameters", "requestBody",
        "responses", "updatedAt")


def endpoint(eid, cookie, refresh=False):
    """One endpoint in the client shape, with the definitions it refers to: {"op": {...}, "defs": {id: schema}}."""
    c = _cached(f"api-{eid}.json", refresh)
    if c is not None:
        return c
    st = docs_state(resolve(json.loads(get(f"/api-{eid}.data", cookie))))
    rd = st.get("resourceData") or {}
    data = rd.get("data") or {}
    if str(data.get("id")) != str(eid) or not data.get("method"):
        die(f"api-{eid}: the page did not carry that endpoint; the site's shape may have changed", EX_REMOTE)
    out = {"op": {k: data.get(k) for k in KEEP}, "defs": (rd.get("extraData") or {}).get("dataSchemaDefinitions") or {}}
    _store(f"api-{eid}.json", out)
    return out


def load(to_openapi, hydrate=lambda e: False, refresh=False):
    """The doc as apifox.py's dict. Endpoints for which hydrate(entry) is true carry their full definition; the
    rest carry only what the catalog says (method, path, name, folder) and are marked x-ela-detail false."""
    cat, fresh = catalog(refresh)
    eps = [e for e in cat if e["kind"] == "endpoint"]
    want = [e for e in eps if hydrate(e)]
    full, todo = {}, []
    if want:
        todo = [e for e in want if refresh or _cached(f"api-{e['id']}.json", False) is None]
        cookie = sid() if todo else None
        if len(todo) > 3:
            print(f"public doc: reading {len(todo)} endpoint pages ({len(want) - len(todo)} cached)…", file=sys.stderr)
        with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
            for e, got in zip(want, pool.map(lambda e: endpoint(e["id"], cookie, refresh), want)):
                full[e["id"]] = got
    details, folder_of, defs = [], {}, {}
    for e in eps:
        folder_of[e["id"]] = "/".join(e["folder"])
        if e["id"] in full:
            op = dict(full[e["id"]]["op"]); op["tags"] = [t for t in op.get("tags") or [] if isinstance(t, str)]
            details.append(op); defs.update(full[e["id"]]["defs"])
        else:
            details.append({"id": e["id"], "name": e["name"], "method": e["method"], "path": e["path"], "x-ela-stub": True})
    schemas = [{"id": k, "name": (v or {}).get("name") or (v or {}).get("title") or k, "jsonSchema": v} for k, v in defs.items()]
    d = to_openapi("public API doc", APIDOG_PROJECT, details, folder_of, schemas)
    done = {(op["method"].lower(), _norm_path(op["path"])) for op in details if not op.get("x-ela-stub")}
    slug = {(e["method"], _norm_path(e["path"])): f"api-{e['id']}" for e in eps}
    for path, item in d["paths"].items():
        for m, op in item.items():
            op["x-ela-detail"], op["x-ela-slug"] = (m, path) in done, slug.get((m, path))
    d["x-ela-source"] = f"public doc ({SESSION_KEY} session)"
    d["x-ela-catalog"] = cat
    d["x-ela-fetched"] = fresh or bool(todo)
    return d


def _norm_path(p):
    p = re.sub(r"^[a-z]+://[^/]+", "", p or "")
    return p if p.startswith("/") else "/" + p
