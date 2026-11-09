#!/usr/bin/env python3
"""J2N's resource-scheduling scores, read first-hand through the J2N config UI's own proxy. L1: subcommands, --json,
stdlib only, read-only. A sense: it reports what a box is charged per app instance (Cpu, QsvRender3D, QsvVideo …) in
each J2N environment; whether a score explains a placement or a capacity complaint is the calling skill's judgment.

  envs                                  the UI's environments (name, category, production mark) and the owner's access
                                        to each (read / write); a GET of the env list and of the owner's permissions
  scores <env> [--subtype S] [--labels k=v,…] [--diff <env>]
                                        the score rows of one environment, one row per label set; --subtype and
                                        --labels narrow them (a label key by its full name, its short form
                                        `encoder/resolution`, or its last segment `resolution`); --diff <env> compares
                                        two environments the way the UI's compare view does: rows present in only one,
                                        and rows whose values differ

The UI is a separate store from Config Server (`ela configserver`): keyed by environment and label set, no
application or profile. The J2N environment names (prod3, prod8, test2 …) are J2N's; which MediaHub lane each backs is
assumed by name (prod3 ↔ prod-3), not verified.

Host, TLS and credential. The host is site.json `services.j2n-config-ui.url`; it is named in no tracked file. TLS
verifies against the pinned leaf certificate ~/.claude/ela/certs/j2n-config-ui.pem (the C# team's private CA issued
it; partial-chain verification, the host name checked) and its SHA-256 beside it (`.sha256`); any other certificate
refuses the connection (exit 5). Verification is never disabled. The bearer token is the owner's, from the UI's own
sign-in with TVU_ACCOUNT / TVU_PASSWORD in the site env file, cached at <runtime>/j2n-config-ui.token (mode 600) and
renewed when the UI answers 401. Neither the token nor the credentials are ever printed.

Read-only by construction. The owner's account can WRITE on qa and qa2 in this UI; this script cannot. Every request
passes one gate: GET on a closed list of paths (the env list, the owner's permissions, one environment's scores), and
POST on the sign-in path only. Any other method or path is refused before a connection is made (exit 2).
Output passes through the shared redaction (skills/configserver/redact.py).

Source quirks, verified 2026-11-09 against the live UI:
  - the direct score service (each environment's scoreApiServer in the UI's config) answers 401 to the UI's token;
    the UI's proxy (`/ui/api/proxy/j2n/api/v1/<env>/config/scores/all`) is the path that works.
  - qa and qa2 answer 404 through the proxy: their scores sit on a separate score server the proxy does not reach.
  - a scores GET sometimes answers 500 "Version conflict (WriteStateAsync) … readonlyscoresettings/<env>": the
    service's own cache write racing; the read is retried twice, then reported (exit 5).
  - which row wins when several match one instance is decided in the j2n-config service; not read here.
Exit codes: 0 ok · 2 usage or a refused request · 3 not found (unknown env, 404, no row matches) · 4 auth ·
5 remote error or a certificate that is not the pin.
"""
import argparse, hashlib, http.client, json, os, re, signal, ssl, stat, sys, time, urllib.parse

EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE = 2, 3, 4, 5
SITE = os.path.expanduser("~/.claude/ela/site.json")
CERT = os.path.expanduser("~/.claude/ela/certs/j2n-config-ui.pem")
SERVICE = "j2n-config-ui"
TOKEN_NAME = "j2n-config-ui.token"
SUBTYPE = "app.tvunetworks.com/subtype"

# The gate. Nothing else is ever sent: no save, apply, delete, export, audit or admin path.
ENV_RX = r"[a-z][a-z0-9-]{0,31}"
ALLOWED = {
    "GET": [re.compile(r"/ui/api/config"), re.compile(r"/ui/api/permissions/me"),
            re.compile(rf"/ui/api/proxy/j2n/api/v1/{ENV_RX}/config/scores/all")],
    "POST": [re.compile(r"/ui/api/auth/login")],
}


class Refused(Exception):
    """A request outside the gate."""


class Fail(Exception):
    def __init__(self, msg, code):
        super().__init__(msg); self.code = code


def gate(method, path):
    """Raise Refused unless (method, path) is on the closed list. Pure; called before any connection."""
    if not any(rx.fullmatch(path) for rx in ALLOWED.get(method, [])):
        raise Refused(f"refused: {method} {path} is not on the read-only list")


def transient(status, raw):
    """The score service's intermittent 500 on a read: its read-only grain's state write lost a version race."""
    return status == 500 and b"Version conflict" in (raw or b"")


def pin_ok(der, expected_hex):
    """The peer certificate (DER bytes) is the pinned one."""
    want = re.sub(r"[^0-9a-f]", "", (expected_hex or "").lower())
    return bool(want) and hashlib.sha256(der).hexdigest() == want


# ── site, credentials, token ────────────────────────────────────────────────────────────────────────

def site():
    try:
        return json.load(open(SITE))
    except (OSError, ValueError):
        return {}


def base_url(s):
    url = ((s.get("services") or {}).get(SERVICE) or {}).get("url")
    if not url:
        raise Fail(f"no services.{SERVICE}.url in site.json — the J2N config UI's address belongs there (/ela:setup)",
                   EX_USAGE)
    return url.rstrip("/")


def runtime_dir(s):
    return s.get("runtime") or (os.path.join(s["projects"], ".ela") if s.get("projects") else
                                os.path.expanduser("~/.ela"))


def env_value(key, env_file=None):
    v = os.environ.get(key)
    if v:
        return v
    for path in filter(None, [env_file, os.environ.get("ELA_ENV_FILE")]):
        try:
            for line in open(path):
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return None


def read_token(path):
    try:
        return open(path).read().strip() or None
    except OSError:
        return None


def write_token(path, tok):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(tok + "\n")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


# ── transport ───────────────────────────────────────────────────────────────────────────────────────

def tls_context():
    if not os.path.isfile(CERT):
        raise Fail(f"no pinned certificate at {CERT} (and its .sha256) — pin the leaf once, never disable "
                   "verification", EX_REMOTE)
    ctx = ssl.create_default_context(cafile=CERT)
    ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    return ctx


class UI:
    def __init__(self, env_file, s=None):
        self.site = s if s is not None else site()
        self.base = urllib.parse.urlsplit(base_url(self.site))
        self.env_file = env_file
        self.token_path = os.path.join(runtime_dir(self.site), TOKEN_NAME)
        self.token = read_token(self.token_path)
        self.ctx = None
        try:
            self.fingerprint = open(CERT[:-4] + ".sha256").read().split()[0]
        except (OSError, IndexError):
            self.fingerprint = None

    def _send(self, method, path, body=None, auth=True):
        gate(method, path)
        if self.ctx is None:
            self.ctx = tls_context()
        if not self.fingerprint:
            raise Fail(f"no fingerprint beside the pinned certificate ({CERT[:-4]}.sha256)", EX_REMOTE)
        conn = http.client.HTTPSConnection(self.base.hostname, self.base.port or 443, context=self.ctx, timeout=30)
        try:
            try:
                conn.connect()
            except ssl.SSLError as e:
                raise Fail(f"TLS refused: the J2N config UI's certificate does not verify against the pin ({e.reason})",
                           EX_REMOTE)
            except OSError as e:
                raise Fail(f"the J2N config UI does not answer: {e}", EX_REMOTE)
            if not pin_ok(conn.sock.getpeercert(binary_form=True), self.fingerprint):
                raise Fail("TLS refused: the J2N config UI presented a certificate whose SHA-256 is not the pin",
                           EX_REMOTE)
            headers = {"Accept": "application/json"}
            if auth and self.token:
                headers["Authorization"] = "Bearer " + self.token
            data = None
            if body is not None:
                data = json.dumps(body).encode(); headers["Content-Type"] = "application/json"
            conn.request(method, path, body=data, headers=headers)
            r = conn.getresponse()
            return r.status, r.read()
        finally:
            conn.close()

    def login(self):
        email, pw = env_value("TVU_ACCOUNT", self.env_file), env_value("TVU_PASSWORD", self.env_file)
        if not (email and pw):
            raise Fail("no TVU_ACCOUNT / TVU_PASSWORD in the site env file — `ela secret TVU_PASSWORD`", EX_AUTH)
        st, raw = self._send("POST", "/ui/api/auth/login", {"email": email, "password": pw}, auth=False)
        try:
            tok = json.loads(raw).get("token")
        except ValueError:
            tok = None
        if st != 200 or not tok:
            raise Fail(f"the J2N config UI refused the sign-in (HTTP {st}) — check TVU_ACCOUNT / TVU_PASSWORD "
                       "(`ela secret TVU_PASSWORD`)", EX_AUTH)
        self.token = tok
        write_token(self.token_path, tok)

    def get(self, path, auth=True):
        """GET a path on the list, as JSON; sign in once when the token is missing or refused."""
        if auth and not self.token:
            self.login()
        st, raw = self._send("GET", path, auth=auth)
        if st == 401 and auth:
            self.login()
            st, raw = self._send("GET", path, auth=auth)
        for _ in range(2):                       # the score service's own cache write races on a read; a GET is safe
            if not transient(st, raw):
                break
            time.sleep(0.5)
            st, raw = self._send("GET", path, auth=auth)
        if st in (401, 403):
            raise Fail(f"the J2N config UI refused the owner's token (HTTP {st}) on {path}", EX_AUTH)
        if st == 404:
            raise Fail(f"HTTP 404 on {path}", EX_NOTFOUND)
        if st != 200:
            raise Fail(f"HTTP {st} on {path}: {raw[:200].decode('utf-8', 'replace')}", EX_REMOTE)
        try:
            return json.loads(raw)
        except ValueError:
            raise Fail(f"not JSON from {path}", EX_REMOTE)

    def config(self):
        return self.get("/ui/api/config", auth=False)

    def access(self):
        return (self.get("/ui/api/permissions/me") or {}).get("access") or {}

    def scores(self, env):
        if not re.fullmatch(ENV_RX, env):
            raise Fail(f"not an environment name: {env!r}", EX_USAGE)
        try:
            return self.get(f"/ui/api/proxy/j2n/api/v1/{env}/config/scores/all")
        except Fail as e:
            if e.code == EX_NOTFOUND:
                raise Fail(f"{env}: the proxy answers 404 — its scores sit on a score server the proxy does not reach "
                           "(qa and qa2 do, 2026-11-09)", EX_NOTFOUND)
            raise


# ── pure: environments, rows, filters, diff (tests/test_j2n_offline.py) ─────────────────────────────

def envs_table(cfg, access):
    prod = set(cfg.get("productionEnvironments") or [])
    return [{"env": e.get("value"), "label": e.get("label"), "category": e.get("category"),
             "production": e.get("value") in prod, "access": access.get(e.get("value"), "none")}
            for e in cfg.get("environments") or []]   # the servers' addresses are not carried out


def short_key(k):
    """`encoder.app.tvunetworks.com/resolution` → `encoder/resolution`; `app.tvunetworks.com/subtype` → `subtype`;
    a key without a slash is itself."""
    if "/" not in k:
        return k
    prefix, name = k.split("/", 1)
    return name if prefix.startswith("app.") else f"{prefix.split('.')[0]}/{name}"


def parse_labels(spec):
    out = []
    for part in filter(None, (p.strip() for p in (spec or "").split(","))):
        if "=" not in part:
            raise Fail(f"--labels wants k=v pairs, got {part!r}", EX_USAGE)
        k, v = part.split("=", 1)
        out.append((k.strip(), v.strip()))
    return out


def key_matches(full, want):
    return want in (full, short_key(full), full.rsplit("/", 1)[-1])


def row_matches(row, subtype=None, labels=()):
    lab = row.get("labels") or {}
    if subtype and lab.get(SUBTYPE) != subtype:
        return False
    return all(any(key_matches(k, wk) and str(v).lower() == wv.lower() for k, v in lab.items()) for wk, wv in labels)


def row_key(row):
    return tuple(sorted((row.get("labels") or {}).items()))


def other_labels(row):
    return {short_key(k): v for k, v in sorted((row.get("labels") or {}).items()) if k != SUBTYPE}


def fmt_score(score):
    return " · ".join(f"{k} {v}" for k, v in sorted((score or {}).items())) or "(empty)"


def fmt_labels(row):
    return ", ".join(f"{k}={v}" for k, v in other_labels(row).items()) or "(base)"


def sort_rows(rows):
    return sorted(rows, key=lambda r: ((r.get("labels") or {}).get(SUBTYPE, ""), len(r.get("labels") or {}),
                                       row_key(r)))


def diff(rows_a, rows_b):
    a = {row_key(r): r for r in rows_a}
    b = {row_key(r): r for r in rows_b}
    only_a = sort_rows([a[k] for k in a if k not in b])
    only_b = sort_rows([b[k] for k in b if k not in a])
    differ = [{"labels": a[k].get("labels"), "a": a[k].get("score"), "b": b[k].get("score")}
              for k in a if k in b and a[k].get("score") != b[k].get("score")]
    differ.sort(key=lambda d: ((d["labels"] or {}).get(SUBTYPE, ""), len(d["labels"] or {}), sorted(d["labels"].items())))
    return {"only_a": only_a, "only_b": only_b, "differ": differ, "same": sum(1 for k in a if k in b) - len(differ)}


def render_rows(env, total, rows):
    out = [f"{env}: {total} rows" + (f", {len(rows)} shown" if len(rows) != total else "")]
    w = max([len((r.get("labels") or {}).get(SUBTYPE, "")) for r in rows] + [7])
    lw = max([len(fmt_labels(r)) for r in rows] + [6])
    for r in sort_rows(rows):
        out.append(f"  {(r.get('labels') or {}).get(SUBTYPE, '?'):<{w}}  {fmt_labels(r):<{lw}}  {fmt_score(r.get('score'))}")
    return "\n".join(out)


def render_diff(ea, eb, d):
    out = [f"{ea} ↔ {eb}: {d['same']} rows equal · {len(d['differ'])} differ · {len(d['only_a'])} only in {ea} · "
           f"{len(d['only_b'])} only in {eb}"]
    if d["differ"]:
        out.append(f"\ndiffer ({ea} → {eb})")
        for x in d["differ"]:
            row = {"labels": x["labels"]}
            out.append(f"  {x['labels'].get(SUBTYPE, '?')}  {fmt_labels(row)}  {fmt_score(x['a'])} → {fmt_score(x['b'])}")
    for side, env in (("only_a", ea), ("only_b", eb)):
        if d[side]:
            out.append(f"\nonly in {env}")
            for r in d[side]:
                out.append(f"  {(r.get('labels') or {}).get(SUBTYPE, '?')}  {fmt_labels(r)}  {fmt_score(r.get('score'))}")
    if not (d["differ"] or d["only_a"] or d["only_b"]):
        out.append("identical")
    return "\n".join(out)


# ── commands ────────────────────────────────────────────────────────────────────────────────────────

def known_envs(ui):
    return [e.get("value") for e in ui.config().get("environments") or []]


def check_env(env, known):
    if env not in known:
        raise Fail(f"unknown environment {env!r}; the UI has: {', '.join(known)}", EX_NOTFOUND)


def cmd_envs(a, ui):
    rows = envs_table(ui.config(), ui.access())
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1)); return
    print(f"{'env':<9} {'category':<12} {'prod':<5} access")
    for r in rows:
        warn = "  ← the owner can change scores here; this sense never does" if r["access"] == "write" else ""
        print(f"{r['env']:<9} {r['category'] or '':<12} {'yes' if r['production'] else '':<5} {r['access']}{warn}")


def cmd_scores(a, ui):
    labels = parse_labels(a.labels)
    known = known_envs(ui)
    check_env(a.env, known)
    rows_a = ui.scores(a.env)
    pick = lambda rows: [r for r in rows if row_matches(r, a.subtype, labels)]  # noqa: E731
    if a.diff:
        check_env(a.diff, known)
        rows_b = ui.scores(a.diff)
        d = diff(pick(rows_a), pick(rows_b))
        if a.json:
            print(json.dumps({"a": a.env, "b": a.diff, **d}, ensure_ascii=False, indent=1)); return
        print(render_diff(a.env, a.diff, d)); return
    shown = pick(rows_a)
    if a.json:
        print(json.dumps({"env": a.env, "rows": len(rows_a), "shown": sort_rows(shown)}, ensure_ascii=False, indent=1))
    else:
        print(render_rows(a.env, len(rows_a), shown))
    if not shown:
        what = " ".join(filter(None, [a.subtype and f"subtype={a.subtype}", a.labels]))
        print(f"no row in {a.env} matches {what}", file=sys.stderr); sys.exit(EX_NOTFOUND)


def main():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "configserver"))
    import redact; redact.guard_output()  # a credential inside a remote payload never reaches the terminal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description="J2N scheduling scores through the J2N config UI, read-only.",
                                 epilog="Exit codes: 0 ok · 2 usage/refused · 3 not found · 4 auth · 5 remote/TLS.")
    ap.add_argument("--env-file", help="the site env file (TVU_ACCOUNT, TVU_PASSWORD)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("envs", help="environments and the owner's access to each")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("scores", help="one environment's score rows, filtered, or two compared")
    p.add_argument("env")
    p.add_argument("--subtype", help="app subtype, exact (encoder, headlessr_decoder …)")
    p.add_argument("--labels", help="k=v[,k=v…]; a key by full name, short form or last segment")
    p.add_argument("--diff", metavar="ENV", help="compare with another environment")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        ui = UI(a.env_file)
        {"envs": cmd_envs, "scores": cmd_scores}[a.cmd](a, ui)
    except Refused as e:
        print(str(e), file=sys.stderr); sys.exit(EX_USAGE)
    except Fail as e:
        print(str(e), file=sys.stderr); sys.exit(e.code)


if __name__ == "__main__":
    main()
