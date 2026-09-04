#!/usr/bin/env python3
"""Release facts, read first-hand — userservice on both hosts (GM bundles, lane versions), Jenkins (builds), the map.
L1: subcommands, --json, stdlib only. No store, no scheduler: every answer is the source's current state.

  bundles  [line] [--host qa|prod]        GM bundles for a line prefix (default mh2.1@), newest first
  bundle   <name|id> [--host qa|prod]     a bundle's bill of materials (serviceTagList)
  envs     [service] [--host qa|prod]     versions per lane; tag names mapped to lanes by <records>/map/release.yaml hosts
  builds   <job|service> [--limit N]      Jenkins builds: number, version, result, branch, sha, time
  drift    [line] [--bundles N] [--host]  GM service names shipped in the newest N bundles vs map/services.yaml gm_names
  login    [qa|tvu] [--force]             qa: tvutest account login → SID (2h), printed for the env file.
                                          tvu: a one-time HTTPS page under ela.tvunetworks.com collects the browser's
                                          SID after Google SSO (a paste field is the fallback); stored in
                                          ~/.claude/ela/session.json (mode 600) with obtained_at; the first refusal
                                          records rejected_at so the session's real lifetime is measured.

Hosts. qa = site.json services.userservice-test, account login (TVUTEST_ACCOUNT / TVUTEST_PASSWORD), QA bundles and
qa-* lanes. prod = site.json services.userservice, the person's TVU SSO session — `ela login tvu` (decision
2026-09-04-prod-gm-is-read-through-a-persons-login-at-the-cli): daily-*, stage and prod-N lanes and their bundles.
A prod read without a live session exits 4 and names the command; nothing is guessed and no cache is read instead.
Config: <records>/map/release.yaml (service ids per host, tag→lane maps, Jenkins job → service, release lines).
Exit codes: 0 ok · 2 usage · 3 not found · 4 auth · 5 remote error.
"""
import argparse, datetime, hashlib, json, os, re, signal, ssl, subprocess, sys, urllib.error, urllib.parse, urllib.request
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer

EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE = 2, 3, 4, 5
SITE = os.path.expanduser("~/.claude/ela/site.json")
SESSION_FILE = os.path.expanduser("~/.claude/ela/session.json")
TLS_DIR = os.path.expanduser("~/.claude/ela/tls")
LOGIN_HOST, LOGIN_PORT = "ela.tvunetworks.com", 8443


# ── the release map (a YAML subset: nested maps by indentation, inline JSON, lists of maps) ──────────

def _yaml_subset(text):
    """Parse the subset of YAML that <records>/map/release.yaml is written in: two-space nested maps, `key: value`
    with the value tried as JSON first, `key:` opening a nested block, `- key: value` lists of maps, `- scalar`
    lists, and an indented line without a key continuing the previous scalar. Comments start at ` #`."""
    lines = []
    for raw in text.splitlines():
        s = re.sub(r"\s+#.*$", "", raw.rstrip())
        if not s.strip() or s.lstrip().startswith("#"):
            continue
        lines.append((len(s) - len(s.lstrip()), s.strip()))
    KV = re.compile(r'^("[^"]*"|\'[^\']*\'|[^\s:\-][^:]*?):(?:\s+(.*))?$')
    pos = [0]

    def scalar(v):
        v = (v or "").strip()
        if v == "":
            return None
        try:
            return json.loads(v)
        except ValueError:
            pass
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            return v[1:-1]
        return v

    def block(indent):
        if pos[0] >= len(lines):
            return None
        return lst(indent) if lines[pos[0]][1].startswith("- ") else mp(indent)

    def mp(indent):
        out, last = {}, None
        while pos[0] < len(lines):
            ind, s = lines[pos[0]]
            if ind < indent:
                break
            m = KV.match(s) if ind == indent else None
            if ind > indent or (not m and not s.startswith("- ")):
                if last is not None and isinstance(out.get(last), str):
                    out[last] = out[last] + " " + s; pos[0] += 1; continue
                break
            if not m:
                break
            key = m.group(1).strip().strip("\"'"); val = m.group(2)
            pos[0] += 1
            if val is None or val.strip() == "":
                out[key] = block(lines[pos[0]][0]) if pos[0] < len(lines) and lines[pos[0]][0] > indent else None
            else:
                out[key] = scalar(val)
            last = key
        return out

    def lst(indent):
        out = []
        while pos[0] < len(lines):
            ind, s = lines[pos[0]]
            if ind != indent or not s.startswith("- "):
                break
            item = s[2:].strip()
            m = KV.match(item)
            pos[0] += 1
            if not m:
                out.append(scalar(item)); continue
            d = {}
            key = m.group(1).strip().strip("\"'"); val = m.group(2)
            if val is None or val.strip() == "":
                d[key] = block(lines[pos[0]][0]) if pos[0] < len(lines) and lines[pos[0]][0] > indent + 2 else None
            else:
                d[key] = scalar(val)
            if pos[0] < len(lines) and lines[pos[0]][0] == indent + 2 and not lines[pos[0]][1].startswith("- "):
                d.update(mp(indent + 2))
            out.append(d)
        return out

    return mp(0)


def _release_map():
    """<records>/map/release.yaml — world facts about the version system; site.json `map` points at the directory."""
    path = os.path.join(site().get("map", ""), "release.yaml")
    try:
        text = open(path).read()
    except OSError:
        print(f"no {path} — the release map lives in the knowledge base (map/release.yaml); see /ela:release", file=sys.stderr); sys.exit(EX_USAGE)
    return _yaml_subset(text)


_MAP = None
def rmap(key):
    global _MAP
    if _MAP is None:
        _MAP = _release_map()
    return _MAP.get(key) or {}


def lane_of(host_kind, tagname):
    """Canonical lane name for a userservice tagName on a host, from release.yaml hosts; None when unmapped."""
    h = (rmap("hosts") or {}).get(host_kind) or {}
    t = str(tagname or "").strip()
    if h.get("match") == "endswith":
        for suffix, lane in sorted((h.get("tag_suffix_to_lane") or {}).items(), key=lambda kv: -len(kv[0])):
            if t.endswith(suffix):
                return lane
        return None
    return (h.get("tag_to_lane") or {}).get(t)


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


def _auth_failed(st, body):
    if st in (401, 402, 403):
        return True
    if isinstance(body, str) and "no login" in body.lower():
        return True
    if isinstance(body, dict):
        code = str(body.get("errorCode") or body.get("code") or "")
        info = str(body.get("errorInfo") or body.get("message") or "").lower()
        if code in ("401", "402", "403") or "login" in info and "no" in info:
            return True
    return False


def parse_version(raw):
    """Any env string family in map/release.yaml version_rules → (M, m, SUB, PATCH, BUILD), or None when no family
    fits (undetermined — never a comparison result). JSON-wrapped values are unwrapped; a hash build counts as 0;
    in the space-less family the counter ends where a YYYY-MM-DD date begins, never read greedily."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s.startswith("{"):
        try:
            v = json.loads(s)
            if isinstance(v, dict) and v:
                s = str(next(iter(v.values())))
        except ValueError:
            return None
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?(.*)$", s)
    if not m:
        return None
    M, mi, sub = int(m.group(1)), int(m.group(2)), int(m.group(3))
    patch = int(m.group(4)) if m.group(4) else 0
    rest = m.group(5) or ""
    build = 0
    b = re.match(r"^\s*build(?:ID:)?\s*(\d+)(-\d{2}-\d{2})?", rest, re.I)
    if b:
        digits = b.group(1)
        if b.group(2):
            digits = digits[:-4] or "0"
        build = int(digits)
    else:
        p = re.match(r"^\+(\w+)", rest)
        if p and p.group(1).isdigit():
            build = int(p.group(1))
    return (M, mi, sub, patch, build)


def vlabel(t):
    if not t:
        return "?"
    M, m, s, p, b = t
    return f"{M}.{m}.{s}" + (f".{p}" if p else "") + (f"+{b}" if b else "")


# ── the person's prod session ────────────────────────────────────────────────

def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_sessions():
    try:
        return json.load(open(SESSION_FILE))
    except Exception:
        return {}


def _save_sessions(d):
    os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
    tmp = SESSION_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(d, fh, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, SESSION_FILE)


def _mark_rejected(kind):
    d = _load_sessions(); s = d.get(kind) or {}
    if s.get("sid") and not s.get("rejected_at"):
        s["rejected_at"] = _now()
        try:
            got = datetime.datetime.strptime(s["obtained_at"], "%Y-%m-%dT%H:%M:%SZ"); rej = datetime.datetime.strptime(s["rejected_at"], "%Y-%m-%dT%H:%M:%SZ")
            s.setdefault("lifetimes_s", []).append(int((rej - got).total_seconds()))
        except Exception:
            pass
        d[kind] = s; _save_sessions(d)


def _need_login(kind, why):
    print(f"{kind} session {why} — run: ela login {kind}", file=sys.stderr); sys.exit(EX_AUTH)


class US:
    """userservice on one host. qa: account login, renewed by the script. prod: the person's session or nothing."""
    def __init__(self, env_file, host="qa"):
        self.kind = "prod" if host == "prod" else "qa"
        self.env_file = env_file
        if self.kind == "prod":
            self.host = _service_url("userservice")
            s = _load_sessions().get("tvu") or {}
            self.sid = s.get("sid") if not s.get("rejected_at") else None
            if not self.sid:
                _need_login("tvu", "missing" if not s.get("sid") else f"refused at {s.get('rejected_at')}")
        else:
            self.host = _service_url("userservice-test")
            self.sid = env_value("TVUTEST_SID", env_file) or tvutest_login(env_file, self.host)

    def call(self, path, payload=None):
        st, body = http(self.host + path, payload, cookie=f"SID={self.sid}")
        if _auth_failed(st, body):
            if self.kind == "prod":
                _mark_rejected("tvu"); _need_login("tvu", f"refused (HTTP {st})")
            self.sid = tvutest_login(self.env_file, self.host)          # a tvutest SID lives two hours; log in again once
            st, body = http(self.host + path, payload, cookie=f"SID={self.sid}")
            if _auth_failed(st, body):
                print(f"userservice {self.host}: login rejected (HTTP {st}) — check TVUTEST_ACCOUNT / TVUTEST_PASSWORD", file=sys.stderr); sys.exit(EX_AUTH)
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


def _validate_sid(host_url, sid):
    """The cheapest prod read: one bundle row. True only on HTTP 200 with a result object."""
    st, body = http(host_url + "/userGroup/user-group/tagBundle/page",
                    {"bundleName": "", "operator": "", "createStartTime": "", "createEndTime": "", "pageNum": 1, "pageSize": 1},
                    cookie=f"SID={sid}", timeout=15)
    return st == 200 and isinstance(body, dict) and body.get("result") is not None and not _auth_failed(st, body)


def _ensure_cert():
    crt, key = os.path.join(TLS_DIR, f"{LOGIN_HOST}.crt"), os.path.join(TLS_DIR, f"{LOGIN_HOST}.key")
    if os.path.isfile(crt) and os.path.isfile(key):
        return crt, key
    os.makedirs(TLS_DIR, exist_ok=True)
    r = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", crt, "-days", "825",
                        "-subj", f"/CN={LOGIN_HOST}", "-addext", f"subjectAltName=DNS:{LOGIN_HOST}"], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"openssl could not create the certificate: {r.stderr.strip()[:300]}", file=sys.stderr); sys.exit(EX_REMOTE)
    os.chmod(key, 0o600)
    return crt, key


def _open_browser(url):
    for argv, cwd in ((["/mnt/c/WINDOWS/system32/cmd.exe", "/c", "start", "", url], "/mnt/c"), (["xdg-open", url], None), (["open", url], None)):
        if os.path.isfile(argv[0]) or argv[0] in ("xdg-open", "open"):
            try:
                subprocess.Popen(argv, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); return True
            except Exception:
                continue
    return False


_PAGE = """<!doctype html><meta charset="utf-8"><title>ela login tvu</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;max-width:640px;margin:48px auto;padding:0 20px;color:#222}}
code{{background:#f2f2f2;padding:2px 6px;border-radius:4px}} .ok{{color:#0a7d2c}} .bad{{color:#b3261e}}
input{{width:100%;padding:8px;font:inherit}} button{{padding:8px 16px;font:inherit}}</style>
<h2>ela · TVU session</h2>{body}"""


def login_tvu(env_file, force=False, timeout=300, json_out=False, open_browser=True):
    host_url = _service_url("userservice")
    sessions = _load_sessions(); cur = sessions.get("tvu") or {}
    if cur.get("sid") and not cur.get("rejected_at") and not force and _validate_sid(host_url, cur["sid"]):
        msg = {"tvu": "valid", "obtained_at": cur.get("obtained_at"), "source": cur.get("source")}
        print(json.dumps(msg) if json_out else f"tvu session still valid (obtained {cur.get('obtained_at')}, {cur.get('source')}); --force to replace"); return
    crt, key = _ensure_cert()
    url = f"https://{LOGIN_HOST}:{LOGIN_PORT}/"
    state = {"sid": None, "source": None, "note": ""}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body, code=200):
            data = _PAGE.format(body=body).encode()
            self.send_response(code); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def _accept(self, sid, source):
            if _validate_sid(host_url, sid):
                state["sid"], state["source"] = sid, source
                self._send('<p class="ok">✓ TVU session stored in ~/.claude/ela/session.json. You can close this tab.</p>'); return True
            return False

        def do_GET(self):
            c = SimpleCookie(self.headers.get("Cookie") or "")
            sid = c["SID"].value.strip() if "SID" in c else None
            if sid and self._accept(sid, "browser"):
                return
            note = '<p class="bad">The browser sent a SID but userservice refused it — sign in again, then reload.</p>' if sid else \
                   '<p>No SID cookie reached this page. Either you are not signed in to userservice yet, or this page is not under the <code>.tvunetworks.com</code> domain in your browser (hosts entry missing).</p>'
            self._send(note + f'<ol><li><a href="{host_url}" target="_blank">Sign in to userservice</a> (Google SSO), then <a href="/">reload this page</a>.</li>'
                       f'<li>If it still does not arrive: DevTools → Application → Cookies → <code>SID</code>, paste it here.</li></ol>'
                       '<form method="post" action="/sid"><input name="sid" placeholder="SID" autocomplete="off"><p><button>Store</button></p></form>'
                       f'<p><small>hosts entry for the automatic path: <code>127.0.0.1 {LOGIN_HOST}</code></small></p>')

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            form = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", "replace"))
            sid = (form.get("sid") or [""])[0].strip()
            if sid and self._accept(sid, "paste"):
                return
            self._send('<p class="bad">userservice refused that SID.</p><p><a href="/">Back</a></p>', 400)

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(crt, key)
    try:
        srv = HTTPServer(("127.0.0.1", LOGIN_PORT), H)
    except OSError as e:
        print(f"cannot listen on 127.0.0.1:{LOGIN_PORT}: {e}", file=sys.stderr); sys.exit(EX_REMOTE)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True); srv.timeout = 1
    opened = _open_browser(url) if open_browser else False
    print(f"waiting for the browser at {url}  ({'opened' if opened else 'open it yourself'}; hosts: 127.0.0.1 {LOGIN_HOST}; up to {timeout}s)", file=sys.stderr)
    if cur.get("lifetimes_s"):
        print(f"previous session lifetimes: {', '.join(str(round(x/3600, 1)) + 'h' for x in cur['lifetimes_s'][-5:])}", file=sys.stderr)
    deadline = datetime.datetime.now() + datetime.timedelta(seconds=timeout)
    while state["sid"] is None and datetime.datetime.now() < deadline:
        try:
            srv.handle_request()
        except ssl.SSLError:
            continue
    srv.server_close()
    if not state["sid"]:
        print("no session collected before the timeout", file=sys.stderr); sys.exit(EX_AUTH)
    sessions["tvu"] = {"sid": state["sid"], "obtained_at": _now(), "rejected_at": None, "source": state["source"],
                        "lifetimes_s": cur.get("lifetimes_s") or []}
    _save_sessions(sessions)
    msg = {"tvu": "stored", "obtained_at": sessions["tvu"]["obtained_at"], "source": state["source"]}
    print(json.dumps(msg) if json_out else f"TVU session stored ({state['source']}, {msg['obtained_at']}) — ela versions --host prod")


# ── bundles ──────────────────────────────────────────────────────────────────

def when(v):
    """epoch ms | epoch s | iso → 'YYYY-MM-DD HH:MM'."""
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
    us = US(a.env_file, a.host)
    rows = bundle_list(us, a.line, a.limit)
    rows.sort(key=lambda x: str(x.get("createTime") or ""), reverse=True)
    if a.json:
        print(json.dumps({"host": a.host, "line": a.line, "count": len(rows), "bundles": rows}, ensure_ascii=False)); return
    if not rows:
        print(f"no bundles for {a.line!r} on {a.host}", file=sys.stderr); sys.exit(EX_NOTFOUND)
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
        print(f"bundle {ref!r} not found on {us.kind}; nearest: {names}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    return str(hit["bundleId"]), str(hit["bundleName"])


def cmd_bundle(a):
    us = US(a.env_file, a.host)
    bid, name = resolve_bundle(us, a.ref)
    detail = bundle_detail(us, bid)
    items = detail.get("serviceTagList") or []
    if a.json or a.raw:
        print(json.dumps({"host": a.host, "bundle": name, "bundleId": bid, "detail": detail} if a.raw else
                         {"host": a.host, "bundle": name, "bundleId": bid, "count": len(items), "services": items}, ensure_ascii=False)); return
    print(f"# bundle {name}  id {bid}  {len(items)} service(s)  [{a.host}]")
    if items:
        keys = [k for k in ("serviceName", "tagName", "version", "tag", "type", "serviceId") if k in items[0]]
        print("  " + "  ".join(f"{k:<28}" if k == "serviceName" else f"{k:<20}" for k in keys))
        for it in sorted(items, key=lambda x: str(x.get("serviceName") or "")):
            print("  " + "  ".join(f"{str(it.get(k)):<28}" if k == "serviceName" else f"{str(it.get(k)):<20}" for k in keys))
        extra = sorted(set(items[0].keys()) - set(keys))
        if extra:
            print(f"  (other fields: {', '.join(extra)} — use --raw)")


# ── env versions ──────────────────────────────────────────────────────────────

def lane_versions(us, want=None):
    """Every (service, tag, lane, version, updated) row a host publishes for the mapped service ids."""
    ids = rmap("service_ids" if us.kind == "prod" else "qa_service_ids")
    out = []
    for svc_id, slugs in ids.items():
        slugs = [tuple(x) for x in slugs]
        if want and not any(want in slug for slug, _ in slugs):
            continue
        body = us.call(f"/userGroup/user-group/tag/getTagVersionList?serviceId={svc_id}")
        r = body.get("result") if isinstance(body, dict) else None
        entries = r if isinstance(r, list) else (body.get("data") if isinstance(body, dict) and isinstance(body.get("data"), list) else (r or {}).get("list") or [])
        for slug, field in slugs:
            if want and want not in slug:
                continue
            for e in entries:
                out.append({"service": slug, "tag": e.get("tagName"), "lane": lane_of(us.kind, e.get("tagName")),
                            "version": " ".join(str(e.get(field) or "").split()), "updated": when(e.get("updateTime") or e.get("createTime"))})
    return out


def cmd_envs(a):
    us = US(a.env_file, a.host)
    out = lane_versions(us, (a.service or "").lower())
    if a.json:
        print(json.dumps({"host": a.host, "rows": out}, ensure_ascii=False)); return
    if not out:
        print(f"no env versions for {a.service!r} on {a.host}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    cur = None
    for r in sorted(out, key=lambda x: (x["service"], str(x["lane"] or "~"), str(x["tag"]))):
        if r["service"] != cur:
            cur = r["service"]; print(f"# {cur}  [{a.host}]")
        print(f"  {str(r['lane'] or '?'):<13} {str(r['tag']):<22} {str(r['version']):<40} {str(r['updated'] or '')[:19]}")


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
        pv = parse_version(b.get("displayName") or "")
        rows.append({"job": job, "service": JOBS[job], "number": b.get("number"), "display": b.get("displayName"), "version": vlabel(pv).split("+")[0] if pv else None,
                     "build": pv[4] if pv else None,
                     "result": b.get("result"), "branch": (br.get("name") or "").replace("refs/remotes/origin/", ""), "sha": (br.get("SHA1") or "")[:12],
                     "sha_full": br.get("SHA1") or "",
                     "time": datetime.datetime.fromtimestamp((b.get("timestamp") or 0) / 1000).strftime("%Y-%m-%d %H:%M"), "url": b.get("url")})
    if a.json:
        print(json.dumps({"job": job, "service": JOBS[job], "builds": rows}, ensure_ascii=False)); return
    print(f"# {job}  ({JOBS[job]})")
    for r in rows:
        print(f"  #{r['number']:<5} {str(r['version']):<12} {str(r['result']):<9} {r['branch']:<20} {r['sha']:<12} {r['time']}")


# ── drift: bundle vs services.yaml ────────────────────────────────────────────

def cmd_drift(a):
    """services.yaml's GM names vs what GM actually ships: the union of the newest N bundles of a line (default 5),
    so a service that left the bundle two weeks ago still counts as GM's. First-hand; the registry itself has no list API we know."""
    us = US(a.env_file, a.host)
    rows = bundle_list(us, a.line, 50)
    rows.sort(key=lambda x: str(x.get("createTime") or ""), reverse=True)
    if not rows:
        print(f"no bundles for {a.line!r} on {a.host}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    rows = rows[:max(1, a.bundles)]
    seen = {}                                      # gm name → [bundle names carrying it, newest first]
    for b in rows:
        items = bundle_detail(us, str(b["bundleId"])).get("serviceTagList") or []
        for it in items:
            name = str(it.get("serviceName") or "").strip()
            if name:
                seen.setdefault(name, []).append(b.get("bundleName"))
    newest = rows[0].get("bundleName")
    in_gm = set(seen)
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
    only_gm = sorted(in_gm - known); only_map = sorted(known - in_gm)
    dropped = sorted(n for n in in_gm & known if newest not in seen[n])   # known, shipped recently, but not in the newest bundle
    if a.json:
        print(json.dumps({"host": a.host, "line": a.line, "bundles": [b.get("bundleName") for b in rows], "in_gm": {n: seen[n] for n in sorted(seen)},
                          "only_in_gm": only_gm, "only_in_services_yaml": only_map, "not_in_newest": dropped}, ensure_ascii=False)); return
    print(f"# {a.line} on {a.host} — {len(rows)} bundle(s), newest {newest}: {len(in_gm)} GM names shipped · {len(known)} in services.yaml")
    print("shipped by GM, not in services.yaml:")
    for x in only_gm: print(f"  {x:<40} in {len(seen[x])}/{len(rows)} bundles, newest {seen[x][0]}")
    if not only_gm: print("  —")
    print("in services.yaml, not shipped in these bundles:"); [print("  " + x) for x in only_map] or print("  —")
    if dropped:
        print(f"known and shipped, but not in {newest}:"); [print(f"  {x:<40} last {seen[x][0]}") for x in dropped]


def cmd_login(a):
    if a.target == "tvu":
        login_tvu(a.env_file, force=a.force, timeout=a.timeout, json_out=a.json, open_browser=not a.no_browser); return
    host = _service_url("userservice-test")
    sid = tvutest_login(a.env_file, host)
    print(json.dumps({"TVUTEST_SID": sid}) if a.json else f"TVUTEST_SID={sid}\n(put it in the env file; it expires in 2h)")


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description="Release facts, first-hand.")
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    def host_arg(p): p.add_argument("--host", choices=("qa", "prod"), default="qa", help="qa (tvutest, account login) or prod (the person's TVU session; ela login tvu)")
    p = sub.add_parser("bundles"); p.add_argument("line", nargs="?", default="mh2.1@"); p.add_argument("--limit", type=int, default=50); host_arg(p); p.add_argument("--json", action="store_true")
    p = sub.add_parser("bundle"); p.add_argument("ref", help="bundle name (mh2.1@daily-wed-s1-d33) or id"); host_arg(p); p.add_argument("--json", action="store_true"); p.add_argument("--raw", action="store_true")
    p = sub.add_parser("envs"); p.add_argument("service", nargs="?"); host_arg(p); p.add_argument("--json", action="store_true")
    p = sub.add_parser("builds"); p.add_argument("job"); p.add_argument("--limit", type=int, default=15); p.add_argument("--json", action="store_true")
    p = sub.add_parser("drift"); p.add_argument("line", nargs="?", default="mh2.1@"); p.add_argument("--bundles", type=int, default=5, help="newest N bundles to union (default 5)"); host_arg(p); p.add_argument("--json", action="store_true")
    p = sub.add_parser("login"); p.add_argument("target", nargs="?", choices=("qa", "tvu"), default="qa"); p.add_argument("--force", action="store_true"); p.add_argument("--no-browser", action="store_true"); p.add_argument("--timeout", type=int, default=300); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    {"bundles": cmd_bundles, "bundle": cmd_bundle, "envs": cmd_envs, "builds": cmd_builds, "drift": cmd_drift, "login": cmd_login}[a.cmd](a)


if __name__ == "__main__":
    main()
