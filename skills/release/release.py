#!/usr/bin/env python3
"""Release facts, read first-hand — userservice on both hosts (GM bundles, lane versions), Jenkins (builds), the map.
L1: subcommands, --json, stdlib only. No store, no scheduler: every answer is the source's current state.

  bundles  [line] [--host qa|prod]        GM bundles for a line prefix (default mh2.1@), newest first
  bundle   <name|id> [--host qa|prod]     a bundle's bill of materials (serviceTagList)
  bundle-diff <A> <B> [--host-a|--host-b] services added, removed and changed from A to B; A and B are a name, an id
                                          or a prefix (newest match wins, the rule printed); Slack searches suggested
  envs     [service] [--host qa|prod]     versions per lane; tag names mapped to lanes by <elak>/map/release.yaml hosts
  builds   <job|service> [--limit N]      Jenkins builds: number, version, result, branch, sha, time
  pin      <line> <bundle> [--apply]      the line's official prod bundle in <elak>/blueprint/releases.yaml; dry run
                                          shows the change, --apply writes the entry and commits that file alone (ADR 0012)
  pins     [--json]                       the official bundle per line, as pinned
  drift    [line] [--bundles N] [--host]  GM service names shipped in the newest N bundles vs map/services.yaml gm_names
  login    [qa|tvu] [--force]             qa: tvutest account login → SID (2h), printed for the env file.
                                          tvu: a one-time HTTPS page under ela.tvunetworks.com collects the browser's
                                          SID after Google SSO (a paste field is the fallback); stored in
                                          ~/.claude/ela/session.json (mode 600) with obtained_at; the first refusal
                                          records rejected_at so the session's real lifetime is measured.
  login tvu --keepalive                   one validation call to user-auth, which renews the session's idle TTL; never
                                          logs in, never retries. 0 renewed · 4 refused (recorded) or already refused ·
                                          5 network. A systemd user timer runs it every 30 min (skills/release/keepalive/).

Hosts. qa = site.json services.userservice-test, account login (TVUTEST_ACCOUNT / TVUTEST_PASSWORD), QA bundles and
qa-* lanes. prod = site.json services.userservice, the person's TVU SSO session — `ela login tvu` (elak `blueprint/decisions/2026-09-04-prod-gm-read-through-a-person-login.md`): daily-*, stage and prod-N lanes and their bundles.
A prod read without a live session exits 4 and names the command; nothing is guessed and no cache is read instead.
Config: <elak>/map/release.yaml (service ids per host, tag→lane maps, Jenkins job → service, release lines).
Exit codes: 0 ok · 2 usage · 3 not found · 4 auth · 5 remote error.
"""
import argparse, datetime, hashlib, json, os, re, signal, ssl, subprocess, sys, urllib.error, urllib.parse, urllib.request
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer

EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE = 2, 3, 4, 5
SITE = os.path.expanduser("~/.claude/ela/site.json")
SESSION_FILE = os.path.expanduser("~/.claude/ela/session.json")
TLS_DIR = os.path.expanduser("~/.claude/ela/tls")
LOGIN_HOST = "ela.tvunetworks.com"
USER_AUTH_DEFAULT = "https://cc-ms.tvunetworks.com/userAuth"   # the userAuthUrl UAS's initData returns; .env TVU_USER_AUTH_BASE overrides
SESSION_REFUSED = "0x80060005"                                  # user-auth: "Session is not correct or expired"


def _login_port():
    """The port `login tvu` serves its collection page on. 8443 unless the site says otherwise.

    A site fact, not a constant: the port has to be free on the machine ela runs on, and on a shared
    box it is not ours to assume. The remote site publishes a container on 8443, so a hardcoded port
    made `login tvu` unrunnable there with no way to say so in configuration — the one thing site.json
    exists to carry. `$ELA_LOGIN_PORT` is the one-off override; site.json `login_port` is the durable one.
    A malformed or out-of-range value falls back to the default rather than failing at bind time.
    """
    for raw in (os.environ.get("ELA_LOGIN_PORT"), site().get("login_port")):
        try:
            n = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= 65535:
            return n
    return 8443


# ── the release map (a YAML subset: nested maps by indentation, inline JSON, lists of maps) ──────────

def _yaml_subset(text):
    """Parse the subset of YAML that <elak>/map/release.yaml is written in: two-space nested maps, `key: value`
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
    """<elak>/map/release.yaml — world facts about the version system; site.json `map` points at the directory."""
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


# ela creates bundles and writes nothing else to userservice: no delete, update or bind. The reads POST too
# (/tagBundle/page), so the guard is by path, never by method.
WRITE_PATHS = {"/userGroup/user-group/tagBundle/create"}
WRITE_RX = re.compile(r"delete|remove|update|edit|modify|save|batch|bind|apply|switch|create", re.I)


def write_refused(path, kind):
    """Why a userservice call may not go out, or None: a write path outside the allowlist, or a create off prod."""
    bare = path.split("?", 1)[0]
    if WRITE_RX.search(bare) and bare not in WRITE_PATHS:
        return f"{bare} is a write ela does not make (the only write is {', '.join(sorted(WRITE_PATHS))})"
    if bare in WRITE_PATHS and kind != "prod":
        return f"{bare} is made on the prod host only (daily, rc and official bundles live there)"
    return None


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
        why = write_refused(path, self.kind)
        if why:
            print(f"userservice: refused: {why}", file=sys.stderr); sys.exit(EX_USAGE)
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


def keepalive_tvu(env_file, json_out=False):
    """One validation call so user-auth renews the session's idle TTL. Never logs in, never retries.

    user-auth holds the session in Redis for `sessionInterval` and renews it whenever a validation finds less than
    `left.expire.time` left (UserAuthServiceImpl getUserFromSession); both are 7200 in Config Server, so each call
    renews to two hours. The SID goes in the form body, never the URL, so it stays out of access logs; only the
    email and the errorCode are printed. A refusal is recorded like any other reader's; a network failure is not.
    """
    def out(code, state, msg, **kw):
        print(json.dumps({"tvu": state, **kw}) if json_out else msg, file=sys.stdout if code == 0 else sys.stderr)
        sys.exit(code)

    s = _load_sessions().get("tvu") or {}
    if not s.get("sid"):
        out(EX_AUTH, "missing", "tvu session missing — run: ela login tvu")
    if s.get("rejected_at"):
        out(EX_AUTH, "refused", f"tvu session refused at {s['rejected_at']} — run: ela login tvu", rejected_at=s["rejected_at"])
    base = (env_value("TVU_USER_AUTH_BASE", env_file) or USER_AUTH_DEFAULT).rstrip("/")
    req = urllib.request.Request(base + "/main/GetInfoJSON", data=urllib.parse.urlencode({"session": s["sid"]}).encode(),
                                 headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            st, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        st, raw = e.code, e.read()
    except Exception as e:
        out(EX_REMOTE, "network", f"tvu keepalive: network failure ({type(e).__name__}) — not recorded as a refusal")
    try:
        body = json.loads(raw)
    except ValueError:
        body = None
    code = str(body.get("errorCode") or "") if isinstance(body, dict) else ""
    if code == SESSION_REFUSED:
        _mark_rejected("tvu")
        out(EX_AUTH, "refused", f"tvu session refused ({code}) — run: ela login tvu", errorCode=code)
    if st != 200 or code != "0x0":
        out(EX_REMOTE, "remote", f"tvu keepalive: HTTP {st} errorCode {code or '?'} — not recorded as a refusal", errorCode=code or None)
    email = ((body.get("user") or {}).get("email")) or "?"
    out(0, "renewed", f"tvu session renewed ({email}, {code})", email=email, errorCode=code)


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
    port = _login_port()
    url = f"https://{LOGIN_HOST}:{port}/"
    state = {"sid": None, "source": None, "note": "", "cookies": {}}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body, code=200):
            data = _PAGE.format(body=body).encode()
            self.send_response(code); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def _accept(self, sid, source, cookies=None):
            if _validate_sid(host_url, sid):
                state["sid"], state["source"], state["cookies"] = sid, source, cookies or {}
                self._send('<p class="ok">✓ TVU session stored in ~/.claude/ela/session.json. You can close this tab.</p>'); return True
            return False

        def do_GET(self):
            c = SimpleCookie(self.headers.get("Cookie") or "")
            sid = c["SID"].value.strip() if "SID" in c else None
            # The browser sends every .tvunetworks.com cookie, among them the per-service tag cookies
            # (mediahubNN, …) login-service sets from the user's group; the gateway routes on them, so a
            # browser test that replays SID alone lands on the gateway default instead of the account's lane.
            if sid and self._accept(sid, "browser", {k: m.value for k, m in c.items()}):
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
        srv = HTTPServer(("127.0.0.1", port), H)
    except OSError as e:
        print(f"cannot listen on 127.0.0.1:{port}: {e} — set `login_port` in ~/.claude/ela/site.json "
              f"(or $ELA_LOGIN_PORT) to a free port", file=sys.stderr); sys.exit(EX_REMOTE)
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
                        "cookies": state["cookies"], "lifetimes_s": cur.get("lifetimes_s") or []}
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


def resolve_bundle(us, ref, missing_ok=False):
    if re.fullmatch(r"\d{15,20}", ref):
        return ref, ref
    line = ref.split("@")[0] + "@" if "@" in ref else ref
    rows = bundle_list(us, line, 50)
    hit = next((b for b in rows if str(b.get("bundleName")) == ref), None)
    if not hit:                                        # a release named by its number ("2.1.15" for "MediaHub 2.1.15"), when only one bundle carries it
        whole = [b for b in rows if re.search(r"(?<![\w.])" + re.escape(ref) + r"(?![\w.])", str(b.get("bundleName")))]
        if len(whole) == 1:
            hit = whole[0]
            print(f"bundle {ref!r} on {us.kind}: the one name carrying it → {hit.get('bundleName')}", file=sys.stderr)
    if not hit and missing_ok:
        return None
    if not hit:
        names = ", ".join(str(b.get("bundleName")) for b in rows[:8])
        print(f"bundle {ref!r} not found on {us.kind}; nearest: {names}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    return str(hit["bundleId"]), str(hit["bundleName"])


# ── the official bundle per line: a ruled fact, pinned in elak (ADR 0012) ─────────────────────────────

PINS_REL = os.path.join("blueprint", "releases.yaml")


def pins_path():
    """elak's file where elak is checked out, else the published copy; the first that exists."""
    s = site()
    for root in (s.get("elak"), s.get("published")):
        if root and os.path.isfile(os.path.join(root, PINS_REL)):
            return os.path.join(root, PINS_REL)
    return os.path.join(s.get("elak") or "", PINS_REL)


def read_pins(path=None):
    """{line: {official, id, set, by}}; {} when nothing is pinned."""
    try:
        return (_yaml_subset(open(path or pins_path()).read()) or {}).get("lines") or {}
    except OSError:
        return {}


def render_pins(lines):
    out = ["# The official prod bundle per release line, set on the owner's word with `ela release pin` (ela ADR 0012).",
           "# GM records no deployment; this is the ruling. Readers: ela matrix, ela changes, Helm (from the published copy).",
           "lines:"]
    for line in sorted(lines):
        out.append(f"  {json.dumps(line)}: {json.dumps(lines[line], ensure_ascii=False)}")
    return "\n".join(out) + "\n"


def cmd_pin(a):
    us = US(a.env_file, "prod")
    bid, name = resolve_bundle(us, a.bundle)
    elak = site().get("elak")
    if not elak or not os.path.isdir(os.path.join(elak, ".git")):
        print("pin writes elak, which is not checked out on this machine", file=sys.stderr); sys.exit(EX_USAGE)
    path = os.path.join(elak, PINS_REL)
    lines = read_pins(path) if os.path.isfile(path) else {}
    was = lines.get(a.line)
    entry = {"official": name, "id": bid, "set": datetime.date.today().isoformat(), "by": "owner"}
    if was and was.get("id") == bid:
        print(f"{a.line}: already pinned to {name}"); return
    print(f"{a.line}: {(was or {}).get('official') or 'no pin'} → {name} ({bid})")
    if not a.apply:
        print("dry run; --apply writes blueprint/releases.yaml and commits it alone"); return
    lines[a.line] = entry
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(render_pins(lines))
    msg = f"Pin {a.line}'s official prod bundle to {name}\n\nSet on the owner's apply (ela ADR 0012)."
    for cmd in (["git", "-C", elak, "add", "--", PINS_REL], ["git", "-C", elak, "commit", "-q", "-m", msg, "--", PINS_REL]):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            print(f"elak: {' '.join(cmd[3:5])} failed: {(r.stderr or r.stdout).strip()[-200:]}", file=sys.stderr); sys.exit(EX_REMOTE)
    print(f"pinned and committed in elak: {PINS_REL}; `ela publish pins` carries it to the published directory")


def cmd_pins(a):
    lines = read_pins()
    if a.json:
        print(json.dumps({"path": pins_path(), "lines": lines}, ensure_ascii=False)); return
    for line, e in sorted(lines.items()):
        print(f"{line:<6} {e.get('official')}  (set {e.get('set')} by {e.get('by')})")
    if not lines:
        print(f"no line pinned ({pins_path()})")


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


# ── bundle-diff: two named bundles ────────────────────────────────────────────

def _bundle_prefix(ref):
    """The loose form `2.0 rc-s5` (or `mh2.0 rc-s5`) → `mh2.0@rc-s5`; anything else is returned as typed."""
    m = re.fullmatch(r"\s*(?:mh)?(\d+(?:\.\d+)+)\s+(\S.*?)\s*", ref)
    return f"mh{m.group(1)}@{m.group(2)}" if m else ref.strip()


def resolve_bundle_loose(us, ref):
    """(a) an exact name or id through resolve_bundle; (b) otherwise the newest bundle whose name starts with the
    normalised prefix. Returns (id, name, rule); prints the rule that matched to stderr so --json stays clean."""
    hit = resolve_bundle(us, ref, missing_ok=True)
    if hit:
        rule = "id" if re.fullmatch(r"\d{15,20}", ref) else "exact name"
        print(f"{ref!r} on {us.kind}: {rule} → {hit[1]}", file=sys.stderr)
        return hit[0], hit[1], rule
    prefix = _bundle_prefix(ref)
    rows = [b for b in bundle_list(us, prefix, 50) if str(b.get("bundleName") or "").startswith(prefix)]
    rows.sort(key=lambda x: str(x.get("createTime") or ""), reverse=True)
    if not rows:
        line = prefix.split("@")[0] + "@" if "@" in prefix else prefix
        near = bundle_list(us, line, 50)
        near.sort(key=lambda x: str(x.get("createTime") or ""), reverse=True)
        names = ", ".join(str(b.get("bundleName")) for b in near[:8])
        print(f"bundle {ref!r} not found on {us.kind} (as name or prefix {prefix!r}); nearest: {names}", file=sys.stderr); sys.exit(EX_NOTFOUND)
    b = rows[0]
    more = f", newest of {len(rows)}" if len(rows) > 1 else ""
    print(f"{ref!r} on {us.kind}: prefix {prefix!r}{more} → {b.get('bundleName')}", file=sys.stderr)
    return str(b["bundleId"]), str(b["bundleName"]), "prefix"


def bundle_map(us, bundle_id):
    """gm name → version. The same two lines as promote.py's bundle_map, repeated because promote imports this module."""
    items = bundle_detail(us, bundle_id).get("serviceTagList") or []
    return {str(i.get("serviceName") or "").strip(): str(i.get("tagName") or i.get("version") or "").strip() for i in items}


def _gm_slugs():
    """gm name → slug, from the service rows of services.yaml in the map site.json names (the published copy).
    A missing file yields {} — the search suggestion then falls back to the gm name."""
    out = {}
    try:
        text = open(os.path.join(site().get("map", ""), "services.yaml"), encoding="utf-8").read()
    except OSError:
        return out
    for line in text.splitlines():
        m = re.match(r"^      - (\{.*\})\s*$", line)
        if not m:
            continue
        try: row = json.loads(m.group(1))
        except ValueError: continue
        if row.get("gm_name") and row.get("slug"):
            out.setdefault(str(row["gm_name"]).strip(), str(row["slug"]).strip())
    return out


def cmd_bundle_diff(a):
    sides = {}
    for key, ref, host in (("a", a.a, a.host_a), ("b", a.b, a.host_b)):
        us = US(a.env_file, host)
        bid, name, rule = resolve_bundle_loose(us, ref)
        sides[key] = {"name": name, "id": bid, "host": host, "rule": rule, "map": bundle_map(us, bid)}
    ma, mb = sides["a"]["map"], sides["b"]["map"]
    added = [{"service": s, "version": mb[s]} for s in sorted(set(mb) - set(ma))]
    removed = [{"service": s, "version": ma[s]} for s in sorted(set(ma) - set(mb))]
    changed = [{"service": s, "from": ma[s], "to": mb[s]} for s in sorted(set(ma) & set(mb)) if ma[s] != mb[s]]
    slugs = _gm_slugs()
    since = next((when(b.get("createTime"))[:10] for b in bundle_list(US(a.env_file, a.host_a), sides["a"]["name"], 50)
                  if str(b.get("bundleName")) == sides["a"]["name"]), "") or "<date of A>"
    searches = [f"ela slack history '#prj_dev_mediahub' --since {since} --threads --json — look for: "
                f"{slugs.get(r['service'], r['service'])} {r.get('to') or r.get('version')}" for r in changed + added]
    if a.json:
        print(json.dumps({k: {f: sides[k][f] for f in ("name", "id", "host")} for k in ("a", "b")} |
                         {"added": added, "removed": removed, "changed": changed, "searches": searches}, ensure_ascii=False)); return
    print(f"# {sides['a']['name']} [{a.host_a}] → {sides['b']['name']} [{a.host_b}] — "
          f"{len(added)} added · {len(removed)} removed · {len(changed)} changed · {len(ma)}→{len(mb)} service(s)")
    print("added:"); [print(f"  {r['service']:<40} {r['version']}") for r in added] or print("  —")
    print("removed:"); [print(f"  {r['service']:<40} {r['version']}") for r in removed] or print("  —")
    print("changed:"); [print(f"  {r['service']:<40} {r['from']} → {r['to']}") for r in changed] or print("  —")
    if searches:
        print("why — suggested searches (printed, not run):"); [print("  " + s) for s in searches]


# ── create: a new bundle from a base, one service at a time ─────────────────

def official_bundle(us, line):
    """Prod's bundle for a line ("2.1"): the owner's pin (ADR 0012), else the newest "MediaHub <line>.N". An rc bundle
    is a special-purpose bundle, not prod's lane (owner's ruling, 2026-10-27), so it is never the answer."""
    pin = read_pins().get(line) or {}
    rows = [x for x in bundle_list(us, f"MediaHub {line}", 50) if re.match(r"^MediaHub " + re.escape(line) + r"\.\d+", str(x.get("bundleName") or ""))]
    return next((x for x in rows if pin and str(x.get("bundleId")) == str(pin.get("id"))), None) or \
        max(rows, key=lambda x: str(x.get("createTime") or ""), default=None)


def name_rules(line):
    """The closed set of bundle names the owner uses for a line (map release.yaml bundle_names; Helm's bundle
    management note): (class, regex). Temporary and unpublished bundles have no form yet and are refused."""
    ln = re.escape(line.rstrip("@"))
    return [("daily", re.compile(rf"^{ln}@daily-[a-z]+-s\d+-d\d+$")), ("daily", re.compile(rf"^{ln}@stage-s\d+-d\d+$")),
            ("prod", re.compile(rf"^{ln}@(?:rc|beta|ga)-s\d+-d\d+$")),
            ("official", re.compile(r"^MediaHub \d+\.\d+\.\d+(?: \([^()]+\))?$")), ("official", re.compile(r"^MediaHub \d+\.\d+ rc\d+$"))]


def name_class(name, line):
    return next((c for c, rx in name_rules(line) if rx.match(name)), None)


def next_name(base):
    """The base's successor: d45 → d46, MediaHub 2.1.15 → 2.1.16 (its qualifier dropped), MediaHub 2.0 rc11 → rc12."""
    m = re.match(r"^(.*-d)(\d+)$", base)
    if m:
        return f"{m.group(1)}{int(m.group(2)) + 1}"
    m = re.match(r"^MediaHub (\d+\.\d+)\.(\d+)", base)
    if m:
        return f"MediaHub {m.group(1)}.{int(m.group(2)) + 1}"
    m = re.match(r"^MediaHub (\d+\.\d+) rc(\d+)$", base)
    return f"MediaHub {m.group(1)} rc{int(m.group(2)) + 1}" if m else None


def match_tag(tags, want):
    """The one tag of a service whose name is `want`, else the one carrying it as a whole token; (tag, nearest)."""
    exact = [t for t in tags if str(t.get("tagName") or "").strip() == want]
    if len(exact) == 1:
        return exact[0], []
    token = [t for t in tags if re.search(r"(?<![\w.])" + re.escape(want) + r"(?![\w.])", str(t.get("tagName") or ""))]
    if len(token) == 1 and not exact:
        return token[0], []
    if exact or token:                                     # more than one: the candidates are the answer
        return None, [str(t.get("tagName")) for t in exact or token]
    pw = parse_version(want)

    def gap(n):
        pn = parse_version(n)
        if not pw or not pn or pn[:2] != pw[:2]:
            return (1, 0, 0, n)
        return (0, abs(pn[2] - pw[2]), abs(pn[3] - pw[3]) + abs(pn[4] - pw[4]), n)
    return None, sorted({str(t.get("tagName")) for t in tags}, key=gap)[:6]


DESC_MAX = 255                     # GM refuses a longer description (errorCode 80952002)


def describe(changed, added, removed, room=DESC_MAX):
    """The bundle's description from its own diff: what this upgrade changed, so it cannot be carried over wrong. Within
    `room` characters: in full when it fits, else services moving between the same two versions grouped ("13 Docker
    decoders 1.0.72 → 1.0.76"), else counts only."""
    full = [f"{r['service']} {r['from']} → {r['to']}" for r in changed] + [f"add {r['service']} {r['version']}" for r in added] + \
           [f"drop {r['service']}" for r in removed]
    text = "; ".join(full) or "no change from the base"
    if len(text) <= room:
        return text
    groups = {}
    for r in changed:
        groups.setdefault((r["from"], r["to"]), []).append(r["service"])

    def kind(names):
        last = {n.split()[-1].lower() for n in names}
        first = {n.split()[0] for n in names}
        return f"{len(names)} {first.pop() + ' ' if len(first) == 1 else ''}{last.pop() + 's' if len(last) == 1 else 'services'}"
    grouped = [f"{names[0] if len(names) == 1 else kind(names)} {f} → {t}" for (f, t), names in sorted(groups.items(), key=lambda kv: -len(kv[1]))] + \
              [f"add {r['service']} {r['version']}" for r in added] + [f"drop {r['service']}" for r in removed]
    text = "; ".join(grouped)
    if len(text) <= room:
        return text
    counts = [f"{len(changed)} changed" if changed else "", f"{len(added)} added" if added else "", f"{len(removed)} dropped" if removed else ""]
    return ", ".join(c for c in counts if c)[:room]


def bundle_created(body):
    """(new bundle id, None) from create's answer, or (None, why): GM answers HTTP 200 with errorCode 0x0 and the id as
    result on success, and HTTP 200 with another errorCode and errorInfo when it refuses."""
    if isinstance(body, dict) and str(body.get("errorCode")) == "0x0" and body.get("result"):
        return str(body["result"]), None
    if isinstance(body, dict):
        return None, f"{body.get('errorCode')}: {body.get('errorInfo') or 'no reason given'}"
    return None, f"unreadable answer: {str(body)[:200]}"


def order_warnings(rows, cls, neighbours):
    """Versions run QA ≥ daily ≥ prod. For each service of the new bundle, the lane above it and below it: a version
    under the lane above or over the lane below is a warning (a rollback or a special bundle can be meant). A pair that
    does not parse, or sits in another series (M.m), is undetermined, never an inversion."""
    out, undetermined = [], 0
    above, below = {"daily": ("qa", "prod"), "prod": ("daily", None), "official": ("daily", None)}.get(cls, (None, None))
    for svc, v in sorted(rows.items()):
        pv = parse_version(v)
        for role, want in ((above, "≤"), (below, "≥")):
            if not role or svc not in (neighbours.get(role) or {}):
                continue
            ov = neighbours[role][svc]
            po = parse_version(ov)
            if not pv or not po or pv[:2] != po[:2]:
                undetermined += v != ov                    # equal strings need no order
                continue
            if (want == "≤" and pv > po) or (want == "≥" and pv < po):
                out.append({"service": svc, "version": v, "lane": role, "lane_version": ov,
                            "says": f"{svc} {v} is {'above' if want == '≤' else 'below'} {role} {ov}"})
    return out, undetermined


def neighbour_maps(env_file, line, cls):
    """{role: {gm name: version}} for the lanes either side of a bundle class: QA's newest bundle (qa host), daily's
    newest on the line's daily token, prod's pinned official (else the newest MediaHub <line>.N)."""
    cfg = (rmap("lines") or {}).get(line.replace("mh", "").rstrip("@")) or {}
    toks, out = cfg.get("bundle_lanes") or {}, {}
    want = {"daily": ("qa", "prod"), "prod": ("daily",), "official": ("daily",)}.get(cls, ())
    for role in want:
        try:
            if role == "prod":
                us = US(env_file, "prod")
                b = official_bundle(us, line.replace("mh", "").rstrip("@"))
            else:
                us = US(env_file, "qa" if role == "qa" else "prod")
                pre = line + toks.get(role, role)
                rows = [x for x in bundle_list(us, pre, 50) if str(x.get("bundleName") or "").startswith(pre)]
                b = max(rows, key=lambda x: str(x.get("createTime") or ""), default=None)
            out[role] = {"bundle": b.get("bundleName"), "map": bundle_map(us, b["bundleId"])} if b else None
        except SystemExit:
            out[role] = None
    return out


def cmd_create(a):
    """A new bundle on prod from a base: the base's services and tags, each --set resolved to exactly one tag of
    that service, each --drop removed. Dry run by default: the diff, the description it writes and the lane order.
    --apply posts it, then reads it back by name and checks every service and tag."""
    us = US(a.env_file, "prod")
    bid, base, _ = resolve_bundle_loose(us, a.base)
    line = base.split("@")[0] + "@" if "@" in base else "mh" + (re.search(r"(\d+\.\d+)", base) or [None, ""])[1] + "@"
    name = a.name or next_name(base)
    cls = name_class(name or "", line)
    if not cls:
        print(f"create: {name!r} is not a bundle name the owner uses (daily-<day>-sN-dM, stage-sN-dM, rc|beta|ga-sN-dM, "
              "MediaHub M.m.N, MediaHub M.m rcN); temporary bundles have no name form yet", file=sys.stderr); sys.exit(EX_USAGE)
    if any(str(b.get("bundleName")) == name for b in bundle_list(us, name, 50)):
        print(f"create: {name!r} already exists on prod; ela never replaces a bundle", file=sys.stderr); sys.exit(EX_USAGE)
    rows = {str(i.get("serviceName") or "").strip(): i for i in bundle_detail(us, bid).get("serviceTagList") or []}
    by_slug = {v: k for k, v in _gm_slugs().items()}
    want = {k: {"serviceId": r.get("serviceId"), "tagId": r.get("tagId"), "tagName": r.get("tagName")} for k, r in rows.items()}
    services = None
    for d in a.drop or []:
        gm = by_slug.get(d, d)
        if gm not in want:
            print(f"create: --drop {d}: not in {base}", file=sys.stderr); sys.exit(EX_NOTFOUND)
        del want[gm]
    for s_ in a.set or []:
        svc, _, ver = s_.partition("=")
        gm = by_slug.get(svc.strip(), svc.strip())
        sid = (rows.get(gm) or {}).get("serviceId")
        if not sid:                                        # a service the base does not carry: from the service list
            services = services or ((us.call("/userGroup/user-group/service/list?showInternalFlag=true") or {}).get("result") or [])
            hit = [x for x in services if str(x.get("serviceName") or "").strip().lower() == gm.lower()]
            if len(hit) != 1:
                print(f"create: --set {svc}: {'no' if not hit else len(hit)} GM service named {gm!r}", file=sys.stderr); sys.exit(EX_NOTFOUND)
            gm, sid = str(hit[0]["serviceName"]).strip(), hit[0]["serviceId"]
        tags = (us.call(f"/userGroup/user-group/tag/getTagVersionList?serviceId={urllib.parse.quote(str(sid))}") or {}).get("result") or []
        tag, near = match_tag(tags, ver.strip())
        if not tag:
            print(f"create: --set {svc}={ver}: not exactly one tag of {gm}; nearest: {', '.join(near) or '—'}", file=sys.stderr); sys.exit(EX_NOTFOUND)
        want[gm] = {"serviceId": sid, "tagId": tag.get("id"), "tagName": str(tag.get("tagName"))}
    old = {k: str(r.get("tagName") or "") for k, r in rows.items()}
    new = {k: str(v["tagName"] or "") for k, v in want.items()}
    changed = [{"service": k, "from": old[k], "to": new[k]} for k in sorted(set(old) & set(new)) if old[k] != new[k]]
    added = [{"service": k, "version": new[k]} for k in sorted(set(new) - set(old))]
    removed = [{"service": k, "version": old[k]} for k in sorted(set(old) - set(new))]
    note = (a.note or "").strip()
    if len(note) > DESC_MAX - 10:
        print(f"create: --note is {len(note)} characters; GM keeps {DESC_MAX} for the whole description", file=sys.stderr); sys.exit(EX_USAGE)
    desc = (note + " — " + describe(changed, added, removed, DESC_MAX - len(note) - 3)) if note else describe(changed, added, removed)
    nb = neighbour_maps(a.env_file, line, cls)
    warns, undetermined = order_warnings(new, cls, {r: (v or {}).get("map") or {} for r, v in nb.items()})
    payload = {"bundleName": name, "description": desc,
               "serviceTagList": [{"serviceId": v["serviceId"], "tagId": v["tagId"]} for _, v in sorted(want.items())]}
    res = {"name": name, "class": cls, "base": base, "services": len(want), "description": desc, "added": added, "removed": removed,
           "changed": changed, "order": warns, "undetermined": undetermined,
           "neighbours": {r: (v or {}).get("bundle") for r, v in nb.items()}, "applied": False}
    if a.apply:
        new_id, why = bundle_created(us.call("/userGroup/user-group/tagBundle/create", payload))
        if why:                                             # GM refused with HTTP 200: say so, never read back an absence
            print(f"create: GM refused {name}: {why}", file=sys.stderr); sys.exit(EX_REMOTE)
        detail = bundle_detail(us, new_id)
        got = {(str(i.get("serviceId")), str(i.get("tagId"))) for i in (detail.get("serviceTagList") or [])}
        meant = {(str(x["serviceId"]), str(x["tagId"])) for x in payload["serviceTagList"]}
        res.update(applied=True, id=new_id, verified=got == meant and str(detail.get("bundleName") or name) == name,
                   missing=len(meant - got), extra=len(got - meant))
    if a.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        print(f"# {'created' if a.apply else 'dry run'}: {name} ({cls}) from {base} — {len(want)} service(s)")
        print(f"description: {desc}")
        for r in changed:
            print(f"  changed  {r['service']:<40} {r['from']} → {r['to']}")
        for r in added:
            print(f"  added    {r['service']:<40} {r['version']}")
        for r in removed:
            print(f"  dropped  {r['service']:<40} {r['version']}")
        groups = {}
        for w in warns:                                     # one line per version pair: eleven decoders share one tag
            groups.setdefault((w["version"], w["lane"], w["lane_version"], "above" if "above" in w["says"] else "below"), []).append(w["service"])
        for (v, lane, lv, side), svcs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            who = svcs[0] if len(svcs) == 1 else f"{len(svcs)} services ({', '.join(svcs[:3])}{', …' if len(svcs) > 3 else ''})"
            print(f"  ! order  {who} {v} is {side} {lane} {lv}")
        if warns:
            print("           versions run QA ≥ daily ≥ prod; if this is meant (a rollback, a special bundle), say why in --note")
        print(f"  lanes compared: " + ", ".join(f"{r} {b or 'not read'}" for r, b in res["neighbours"].items())
              + (f" · {undetermined} pair(s) undetermined (another series or no version)" if undetermined else ""))
        if a.apply:
            print(f"  read back: id {res['id']} · " + ("every service and tag as meant" if res["verified"] else
                  f"DIFFERS: {res['missing']} missing, {res['extra']} extra"))
        else:
            print("  nothing was created; add --apply on the owner's word")
    if a.apply and not res["verified"]:
        sys.exit(EX_REMOTE)


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
    if a.keepalive:
        if a.target != "tvu":
            print("--keepalive applies to the tvu session only: ela login tvu --keepalive", file=sys.stderr); sys.exit(EX_USAGE)
        keepalive_tvu(a.env_file, json_out=a.json)
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
    p = sub.add_parser("bundle-diff", help="docker services added, removed and changed between two bundles")
    p.add_argument("a", help="bundle A: exact name, id, or a prefix (mh2.0@rc-s5, or '2.0 rc-s5') — the newest match wins")
    p.add_argument("b", help="bundle B, resolved the same way")
    for side in ("a", "b"): p.add_argument(f"--host-{side}", choices=("qa", "prod"), default="qa", help=f"host bundle {side.upper()} is read from (default qa)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("envs"); p.add_argument("service", nargs="?"); host_arg(p); p.add_argument("--json", action="store_true")
    p = sub.add_parser("create", help="a new bundle on prod from a base bundle, services changed one by one; dry run unless --apply; never deletes")
    p.add_argument("name", nargs="?", help="the new bundle's name; default the base's next (d45 → d46, MediaHub 2.1.15 → 2.1.16)")
    p.add_argument("--from", dest="base", required=True, help="the base bundle: name, id or prefix")
    p.add_argument("--set", action="append", help="'<GM name or slug>=<tag name or version>', repeatable; must match exactly one tag")
    p.add_argument("--drop", action="append", help="a service the new bundle leaves out (GM name or slug), repeatable")
    p.add_argument("--note", help="why this bundle exists; written before the change list in its description")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("pin", help="pin a line's official prod bundle in elak; dry run unless --apply (ADR 0012)"); p.add_argument("line"); p.add_argument("bundle", help="name (MediaHub 2.1.15), number (2.1.15) or id"); p.add_argument("--apply", action="store_true")
    p = sub.add_parser("pins", help="the official bundle per line, as pinned"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("builds"); p.add_argument("job"); p.add_argument("--limit", type=int, default=15); p.add_argument("--json", action="store_true")
    p = sub.add_parser("drift"); p.add_argument("line", nargs="?", default="mh2.1@"); p.add_argument("--bundles", type=int, default=5, help="newest N bundles to union (default 5)"); host_arg(p); p.add_argument("--json", action="store_true")
    p = sub.add_parser("login"); p.add_argument("target", nargs="?", choices=("qa", "tvu"), default="qa"); p.add_argument("--force", action="store_true"); p.add_argument("--no-browser", action="store_true"); p.add_argument("--timeout", type=int, default=300); p.add_argument("--json", action="store_true")
    p.add_argument("--keepalive", action="store_true", help="tvu: one validation call that renews the session's idle TTL; never logs in, never retries")
    a = ap.parse_args()
    {"bundles": cmd_bundles, "bundle": cmd_bundle, "bundle-diff": cmd_bundle_diff, "envs": cmd_envs, "builds": cmd_builds, "drift": cmd_drift, "login": cmd_login, "pin": cmd_pin, "pins": cmd_pins,
     "create": cmd_create}[a.cmd](a)


if __name__ == "__main__":
    main()
