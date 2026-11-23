#!/usr/bin/env python3
"""Release facts, read first-hand — userservice on its three hosts (GM bundles, lane versions), Jenkins (builds), the map.
L1: subcommands, --json, stdlib only. No store, no scheduler: every answer is the source's current state.

  bundles  [line] [--host prod|cn]        GM bundles for a line prefix (default mh2.1@), newest first; without --host
                                          every host, each row with its host and read time; --raw: one host as it answers
  bundle   <name|id> [--host prod|cn]     a bundle's bill of materials (serviceTagList)
  bundle-diff <A> <B> [--host-a|--host-b] services added, removed and changed from A to B; A and B are a name, an id
                                          or a prefix (newest match wins, the rule printed); Slack searches suggested
  envs     [service] [--host prod|cn]     versions per lane; tag names mapped to lanes by <elak>/map/release.yaml hosts
                                          (the China host's by regions.china.userservice); without --host every host;
                                          --raw: one host's service list, or a service's tag records, as it answers
  sync-dev [daily|prod|bundle …] [--ahead]  dev's docker images (each service's default tag on dev) against the
                                          sources, matched by service name and image: same, on dev under another tag,
                                          or refused (no dev tag carries it); ▲ where dev runs above every source.
                                          Read-only; the write waits on vault ela/2026-11-23-plan-release-sync-dev.md
  gateway  [service] [--lane L]           versions userservice does not publish (orchestration), per lane, read through
                                          the API gateway named in <elak>/map/release.yaml gateway_versions; no login.
                                          A lane that does not answer or parse is UNDETERMINED, never "not deployed"
  builds   <job|service> [--limit N]      Jenkins builds: number, version, result, branch, sha, time
  pin      <line> <bundle> [--apply]      the line's official prod bundle in <elak>/blueprint/releases.yaml; dry run
                                          shows the change, --apply writes the entry and commits that file alone (ADR 0012)
  pins     [--json]                       the official bundle per line, as pinned
  drift    [line] [--bundles N] [--host]  GM service names shipped in the newest N bundles vs map/services.yaml gm_names
  changes  [lane] [--check FILE] [--tickets]  what a lane's newest build changed, by service and what for, from its
                                          record; --tickets: each ticket under its service, key, title, status, assignee
  reconcile <lane> [--build N] [--batch [--apply]]  the build's tickets against Jira: a Fixed In covering this build's
                                          version of each service, the release label, the status and assignee the
                                          release thread announced; a fold is an open question. Read-only; the reading
                                          is kept beside the record. --batch: the appends and labels, dry run first
  login    [qa|tvu|cn] [--force]          qa: tvutest account login → SID (2h), printed for the env file.
                                          cn: the China host's account login, proved and kept in session.json (2h); never shown.
                                          tvu: a one-time HTTPS page under ela.tvunetworks.com collects the browser's
                                          SID after Google SSO (a paste field is the fallback); stored in
                                          ~/.claude/ela/session.json (mode 600) with obtained_at; the first refusal
                                          records rejected_at so the session's real lifetime is measured.
  login tvu --host dev                    the owner's own session on dev (MH dev + UR dev2), same browser sign-in on
                                          Chrome under a profile of ela's own, stored as session.json `tvu-dev`; never
                                          touches `tvu-com`. Read it with --host dev on bundle and bundle-diff.
  login tvu --keepalive                   one validation call to user-auth, which renews the session's idle TTL; never
                                          logs in, never retries. 0 renewed · 4 refused (recorded) or already refused ·
                                          5 network. A systemd user timer runs it every 30 min (skills/release/keepalive/).

Hosts. qa = site.json services.userservice-test, account login (TVUTEST_ACCOUNT / TVUTEST_PASSWORD), QA bundles and
qa-* lanes. prod = site.json services.userservice, the person's TVU SSO session — `ela login tvu` (elak `blueprint/decisions/2026-09-04-prod-gm-read-through-a-person-login.md`): daily-*, stage and prod-N lanes and their bundles.
A prod read without a live session exits 4 and names the command; nothing is guessed and no cache is read instead.
cn = site.json services.userservice-cn, account login (TVU_CN_ACCOUNT / TVU_CN_PASSWORD, or a session in TVU_CN_SID):
the China region's bundles and lanes (prod-N-china). Its names mean a lane only where the map's
regions.china.userservice says so; anything else is shown as read, marked unmapped. While the site lacks those names,
a read of every host answers for .com and says once what to add; --host cn exits 2 with the same line.
dev = site.json services.userservice-dev (MH dev + UR dev2), the owner's own session on dev — `ela login tvu --host dev`,
session.json `tvu-dev`, apart from prod's `tvu-com`. Read with --host dev on bundle, bundle-diff and drift, never in an every-host
read; nothing is written there.
Config: <elak>/map/release.yaml (service ids per host, tag→lane maps, Jenkins job → service, release lines).
Exit codes: 0 ok · 2 usage · 3 not found · 4 auth · 5 remote error.
"""
import argparse, contextlib, datetime, glob, hashlib, io, json, os, re, shutil, signal, ssl, subprocess, sys, urllib.error, urllib.parse, urllib.request
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
    if host_kind == "cn":                                   # the China host has its own map and names China lanes only
        lane = _tag_lane(cn_map(), tagname)
        return lane if lane_region(lane) else None
    return _tag_lane((rmap("hosts") or {}).get(host_kind) or {}, tagname)


def _tag_lane(h, tagname):
    t = str(tagname or "").strip()
    if h.get("match") == "endswith":
        for suffix, lane in sorted((h.get("tag_suffix_to_lane") or {}).items(), key=lambda kv: -len(kv[0])):
            if t.endswith(suffix):
                return lane
        return None
    return (h.get("tag_to_lane") or {}).get(t)


# ── the China region's host ──────────────────────────────────────────────────────────────────────────
# A third userservice, beside qa and prod: the China region's bundles and version records live on it and nowhere else.
# Its address is site.json services.userservice-cn.url, its login the env file's TVU_CN_ACCOUNT / TVU_CN_PASSWORD (or a
# session in TVU_CN_SID). Its names are not the .com names: a tag or a bundle name read from it means a lane only where
# the release map's regions.china.userservice says so, and only a China lane (prod-N-china); anything else is shown as
# read and marked unmapped. "Prod2" exists on both hosts and is two environments, so nothing read here is ever looked
# up in hosts.prod, and its facts are kept in files of their own.
HOSTS = ("prod", "cn")
# dev (MH dev + UR dev2) is read on its own and never in an "every host" read: it is no release lane, and its session
# is the owner's sign-in on dev, kept under session.json `tvu-dev` beside prod's `tvu-com` and never mixed with it.
DEV_SERVICE = "userservice-dev"
READ_HOSTS = HOSTS + ("dev",)
# The QA host is not read: since 2026-11-04 it admits no developer account, and a QA lane's versions and bundle come
# from QA's report mails and the release channel instead (SKILL.md, "Two hosts, two sessions"). Asking for it is
# answered with this note and no network call, so no caller spends a login and a retry on a standing refusal.
QA_NOT_READ = ("the QA host is not read: a QA lane's versions come from QA's report mails and the release channel "
               "(the QA environment admits no developer account since 2026-11-04)")
CN_SERVICE = "userservice-cn"
CN_KEYS = ("TVU_CN_ACCOUNT", "TVU_CN_PASSWORD")
CN_SID = "TVU_CN_SID"
DEFAULT_LINE = "mh2.1@"


def cn_map():
    """The China host's naming, as data: release.yaml regions.china.userservice ({} while the map has none)."""
    m = ((rmap("regions") or {}).get("china") or {}).get("userservice")
    return m if isinstance(m, dict) else {}


def _env_file(env_file=None):
    return env_file or os.environ.get("ELA_ENV_FILE") or site_env()


def cn_missing(env_file=None):
    """The names the site still lacks for the China host, [] when it is configured."""
    out = []
    entry = (site().get("services") or {}).get(CN_SERVICE)
    if not (entry.get("url") if isinstance(entry, dict) else entry):
        out.append(f"site.json services.{CN_SERVICE}.url")
    f = _env_file(env_file)
    if not env_value(CN_SID, f) and not all(env_value(k, f) for k in CN_KEYS):
        out.append(f"{' / '.join(CN_KEYS)} in the env file")
    return out


def cn_note(missing):
    return "China host not configured: add " + " and ".join(missing)


def cn_unmapped_note():
    return ("China lanes not mapped: the release map's regions.china.userservice.service_ids is empty; "
            "`ela release envs --host cn --raw` lists the services as the host names them")


def cn_bundle_lane(name):
    """(lane, line) the release map gives a bundle name read from the China host, (None, None) when no rule names it:
    regions.china.userservice.bundles is a list of {match: <regex>, lane: <a China lane>, line: <M.m>}, first hit wins."""
    for rule in cn_map().get("bundles") or []:
        if not isinstance(rule, dict) or not rule.get("match") or not lane_region(rule.get("lane")):
            continue
        try:
            if re.search(str(rule["match"]), str(name or "")):
                return rule["lane"], (str(rule["line"]) if rule.get("line") is not None else None)
        except re.error:
            continue
    return None, None


def lane_shown(lane):
    """The name the team uses for a region lane (prod-2-china → CN Prod2), from the map; the lane itself otherwise."""
    for reg in (rmap("regions") or {}).values():
        meta = ((reg or {}).get("lanes") or {}).get(lane)
        if isinstance(meta, dict) and meta.get("shown"):
            return meta["shown"]
    return lane


def cn_bundle(b):
    """A bundle row read from the China host with what the map says of its name: lane, shown, line, mapped."""
    lane, line = cn_bundle_lane(b.get("bundleName"))
    return dict(b, lane=lane, shown=lane_shown(lane) if lane else None, line=line, mapped=bool(lane))


def default_line(host):
    """The bundle query a host is asked when none is typed: the morning's line on .com; on the China host the map's
    regions.china.userservice.bundle_line, else nothing, which lists the newest of everything."""
    return str(cn_map().get("bundle_line") or "") if host == "cn" else DEFAULT_LINE


# A prod lane carries its region: the .com lanes are prod-N, the China region's are prod-N-china (never "-cn": qa-cn3 is
# the .com QA-AWS3). Two environments share the ProdN tag (the .com Prod2 and CN Prod2, MH-3752); the .com userservice
# publishes only its own, so the region is read from the words that already say CN: a release mail's environment
# ("CN Prod2") or a bundle's qualifier ("(CN Prod2)").
PROD_WORDS_RX = re.compile(r"(cn|china)?-?prod-?(\d+)(-china\b)?")


def prod_lane(words):
    """Environment words → a prod lane with its region: Prod3 → prod-3, CN Prod2 · prod-2-china → prod-2-china; None
    otherwise."""
    m = PROD_WORDS_RX.search(re.sub(r"\s+", "", str(words or "")).lower())
    return f"prod-{m.group(2)}{'-china' if m.group(1) or m.group(3) else ''}" if m else None


def lane_region(lane):
    """'china' for a China-region lane (prod-2-china), '' for a .com one."""
    return "china" if str(lane or "").endswith("-china") else ""


def bundle_lane(name):
    """The lane an official bundle's qualifier names: MediaHub 2.1.13 (CN Prod2) → prod-2-china; None when it names none."""
    m = re.search(r"\(([^()]+)\)\s*$", str(name or ""))
    return prod_lane(m.group(1)) if m else None


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


sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "facts"))
try:
    import facts as F  # noqa: E402 — the fact store: lane versions, the gateway, Jenkins builds and bundles once per pass
except ImportError:
    F = None


def _safe(name):
    return re.sub(r"[^A-Za-z0-9._@-]+", "_", str(name))


def _store_fresh():
    return bool(F) and not F.forced_fresh()


def http(url, payload=None, cookie=None, timeout=20):
    if F:
        F.trace("release", url.split("?")[0])
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
    entry = site().get("services", {}).get(name)
    url = entry.get("url") if isinstance(entry, dict) else entry
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


# One name per deployment: the owner's own sign-in is `tvu-<deployment>` (com: .com daily and prod; cn; dev), a test
# account is `tvu-<deployment>-test` (com: product tests on prod; qa: the QA lines, which take test accounts only).
# The old names still read: on load each old key is the same object as its new one, and on save only new names stay,
# so a verb that still says `tvu` or `cn` keeps working while the file holds one name per sign-in. `tvu` is kept for
# good as the short name of `tvu-com` (the owner's word, 2026-11-23): .com is the sign-in meant when none is named,
# and `ela login tvu` stays the command for it.
_LOADED = {}                                              # each new name's object as the last load returned it
SESSION_NAMES = {"tvu": "tvu-com", "cn": "tvu-cn", "dev": "tvu-dev", "tvu-test": "tvu-com-test", "qa": "tvu-qa-test"}


def _load_sessions():
    try:
        d = json.load(open(SESSION_FILE))
    except Exception:
        return {}
    for old, new in SESSION_NAMES.items():                 # a writer outside ela (Helm's SID mirror) may still use
        a, b = d.get(old), d.get(new)                       # the old name: the later sign-in of the two wins
        if isinstance(a, dict) and (not isinstance(b, dict) or str(a.get("obtained_at") or "") > str(b.get("obtained_at") or "")):
            d[new] = a
        if new in d:
            d[old] = d[new]
        _LOADED[new] = d.get(new)
    return d


def _save_sessions(d):
    """Only new names are written. Of an old name and its new one, the one a verb changed since the load wins: the
    two are one object at load, so whichever no longer is that object is the fresh write (a write under the new name
    is never undone by the stale alias, and a write under an old name still lands)."""
    d = dict(d)
    for old, new in SESSION_NAMES.items():
        if old in d:
            a, b = d.pop(old), d.get(new)
            loaded = _LOADED.get(new)
            if b is None or (a is not b and b is loaded):     # only the old name was written to
                d[new] = a
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


LOGIN_CMD = {"tvu-com": "ela login tvu", "tvu-dev": "ela login tvu --host dev", "tvu-com-test": "ela login tvu --as test",
             "tvu": "ela login tvu", "dev": "ela login tvu --host dev", "tvu-test": "ela login tvu --as test"}


def _need_login(kind, why):
    print(f"{kind} session {why} — run: {LOGIN_CMD.get(kind, 'ela login ' + kind)}", file=sys.stderr); sys.exit(EX_AUTH)


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
    """userservice on one host. qa and cn: account login, renewed by the script. prod: the person's session or nothing."""
    def __init__(self, env_file, host="prod"):
        self.kind = host if host in READ_HOSTS + ("qa",) else "prod"
        self.env_file = env_file
        if self.kind == "qa":
            print(QA_NOT_READ, file=sys.stderr); sys.exit(EX_USAGE)
        if self.kind == "cn":
            missing = cn_missing(env_file)
            if missing:
                print(cn_note(missing), file=sys.stderr); sys.exit(EX_USAGE)
            self.env_file = env_file = _env_file(env_file)
            self.host = _service_url(CN_SERVICE)
            self.sid = env_value(CN_SID, env_file) or account_login(env_file, self.host, CN_KEYS, "China")
        else:                                              # prod and dev: the owner's browser session, each its own
            self.session = "tvu-com" if self.kind == "prod" else "tvu-dev"
            self.host = _service_url("userservice" if self.kind == "prod" else DEV_SERVICE)
            s = _load_sessions().get(self.session) or {}
            self.sid = s.get("sid") if not s.get("rejected_at") else None
            if not self.sid:
                _need_login(self.session, "missing" if not s.get("sid") else f"refused at {s.get('rejected_at')}")

    def call(self, path, payload=None):
        why = write_refused(path, self.kind)
        if why:
            print(f"userservice: refused: {why}", file=sys.stderr); sys.exit(EX_USAGE)
        st, body = http(self.host + path, payload, cookie=f"SID={self.sid}")
        if _auth_failed(st, body):
            if self.kind in ("prod", "dev"):
                _mark_rejected(self.session); _need_login(self.session, f"refused (HTTP {st})")
            keys, what = CN_KEYS, "China"
            self.sid = account_login(self.env_file, self.host, keys, what)   # an account SID lives two hours; log in again once
            st, body = http(self.host + path, payload, cookie=f"SID={self.sid}")
            if _auth_failed(st, body):
                print(f"userservice {self.kind}: login rejected (HTTP {st}) — check {' / '.join(keys)}", file=sys.stderr); sys.exit(EX_AUTH)
        if st != 200:
            print(f"userservice {path}: HTTP {st} {str(body)[:200]}", file=sys.stderr); sys.exit(EX_REMOTE)
        return body


class LazyUS:
    """A userservice handle that logs in only when a call is made, so a read the store answers costs no login."""
    def __init__(self, env_file, host="prod"):
        self.kind = host if host in READ_HOSTS + ("qa",) else "prod"
        self.env_file, self._us = env_file, None

    def call(self, path, payload=None):
        if self._us is None:
            self._us = US(self.env_file, self.kind)
        return self._us.call(path, payload)


QA_KEYS = ("TVUTEST_ACCOUNT", "TVUTEST_PASSWORD")


def account_login(env_file, host, keys=QA_KEYS, what="tvutest"):
    """An account login on a userservice host (qa, cn): the env file's account and password → a two-hour SID."""
    acc, pw = env_value(keys[0], env_file), env_value(keys[1], env_file)
    if not acc or not pw:
        print(f"no {' / '.join(keys)} in the env file", file=sys.stderr); sys.exit(EX_AUTH)
    st, body = http(host + "/userAuth/token/getToken", {"email": acc, "password": hashlib.sha512(pw.encode()).hexdigest(), "expireTime": 7200})
    result = (body or {}).get("result") if isinstance(body, dict) else {}
    sid = (result or {}).get("token") or (result or {}).get("sid") or (body or {}).get("sid") if isinstance(body, dict) else None
    if not sid:
        print(f"{what} login failed: HTTP {st} {str(body)[:200]}", file=sys.stderr); sys.exit(EX_AUTH)
    return str(sid).strip()


# A userservice's answer to an account it does not admit ("This account hasn't been activated"). The QA environment
# answers the tvutest account so since 2026-11-04: an access policy, not a broken account (SKILL.md, two hosts).
NOT_ADMITTED = "0x80060018"


def _refresh_read(read):
    """(rows, gap) of one host read for `ela facts refresh`. The gap is the exit code; a login the host refused as not
    admitted is said in it, so a reader of the gap can tell that standing state from a fault. The read's own last
    words still reach stderr."""
    said = io.StringIO()
    try:
        with contextlib.redirect_stderr(said):
            return read(), None
    except SystemExit as e:
        gap = f"exit {e.code}"
        if e.code == EX_AUTH and NOT_ADMITTED in said.getvalue():
            gap += f", account not admitted ({NOT_ADMITTED})"
        return None, gap
    finally:
        sys.stderr.write(said.getvalue())


def tvutest_login(env_file, host):
    return account_login(env_file, host, QA_KEYS, "tvutest")


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


CHROME_WIN = "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"


CHROME_STATE_WIN = "/mnt/c/Users/{user}/AppData/Local/Google/Chrome/User Data/Local State"


def _chrome_profile_for(account):
    """The owner's own Chrome profile signed in to `account` (Windows Chrome's Local State), or None. His browsers
    (2026-11-23): Edge, the default, for everyday daily and prod; Chrome with one profile for the test account and one
    for evanli kept apart from Edge, where dev is signed in."""
    if not account:
        return None
    for path in glob.glob(CHROME_STATE_WIN.format(user="*")):
        try:
            cache = (json.load(open(path, encoding="utf-8")).get("profile") or {}).get("info_cache") or {}
        except (OSError, ValueError):
            continue
        for directory, info in cache.items():
            if str(info.get("user_name") or "").lower() == account.lower():
                return directory
    return None


def _chrome_argv(url, profile=None, account=None):
    """Google Chrome on the Windows side of WSL, else a Linux Chrome. With `account`, the owner's own Chrome profile
    signed in to it, when there is one; else `profile` names a profile directory of ela's own, so a second account
    signs in without the owner's cookies (his everyday browser holds his prod session)."""
    if os.path.isfile(CHROME_WIN):
        argv = [CHROME_WIN]
        own = _chrome_profile_for(account)
        if own:
            return argv + [f"--profile-directory={own}", "--new-window", url]
        if profile:
            r = subprocess.run(["/mnt/c/WINDOWS/system32/cmd.exe", "/c", "echo", "%LOCALAPPDATA%"], cwd="/mnt/c", capture_output=True, text=True)
            base = r.stdout.strip()
            if base and "%" not in base:
                argv.append(f"--user-data-dir={base}\\ela\\chrome-{profile}")
        return argv + ["--new-window", url]
    for name in ("google-chrome", "google-chrome-stable"):
        exe = shutil.which(name)
        if exe:
            extra = [f"--user-data-dir={os.path.expanduser(f'~/.claude/ela/chrome-{profile}')}"] if profile else []
            return [exe, *extra, "--new-window", url]
    return None


def _open_browser(url, browser=None, profile=None, account=None):
    if browser == "chrome":
        argv = _chrome_argv(url, profile, account)
        if not argv:
            print("Google Chrome not found (Windows side or Linux)", file=sys.stderr); return False
        subprocess.Popen(argv, cwd="/mnt/c" if argv[0] == CHROME_WIN else None, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
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


def login_tvu(env_file, force=False, timeout=300, json_out=False, open_browser=True, key="tvu", browser=None):
    """key: the session.json entry — `tvu` is the owner's own on .com (daily, prod); `tvu-dev` the owner's own on dev,
    proven by a bundle row on dev's userservice; `tvu-test` the second account product tests act as (ela browser
    --as test). dev and test open Chrome on a profile of ela's own: the SID cookie is one name on .tvunetworks.com,
    so a dev sign-in in the everyday profile would replace the prod one."""
    host_url = _service_url(DEV_SERVICE if key == "tvu-dev" else "userservice")
    owner = (env_value("TVU_ACCOUNT", env_file) or "").lower()
    sessions = _load_sessions(); cur = sessions.get(key) or {}
    test = key == "tvu-test"
    valid = (lambda sid: _sid_email(env_file, sid) != "?") if test else (lambda sid: _validate_sid(host_url, sid))
    if cur.get("sid") and not cur.get("rejected_at") and not force and valid(cur["sid"]):
        msg = {"tvu": "valid", "obtained_at": cur.get("obtained_at"), "source": cur.get("source")}
        print(json.dumps(msg) if json_out else f"{key} session still valid (obtained {cur.get('obtained_at')}, {cur.get('source')}); --force to replace"); return
    crt, tls_key = _ensure_cert()
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
            # The owner's check reads a bundle row, which an ordinary account may not read; a test account is proven
            # by the user-auth service naming whose session it is, and must not be the owner's own session.
            if test:
                who = _sid_email(env_file, sid)
                if who.lower() == owner:
                    self._send(f'<p class="bad">This browser is signed in as the owner ({who}), not the test account. '
                               f'Sign out of userservice here, sign in as the test account, then reload.</p>', 409); return True
                ok = who != "?"
            else:
                ok = _validate_sid(host_url, sid)
            if ok:
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

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(crt, tls_key)
    try:
        srv = HTTPServer(("127.0.0.1", port), H)
    except OSError as e:
        print(f"cannot listen on 127.0.0.1:{port}: {e} — set `login_port` in ~/.claude/ela/site.json "
              f"(or $ELA_LOGIN_PORT) to a free port", file=sys.stderr); sys.exit(EX_REMOTE)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True); srv.timeout = 1
    # the test account signs in in his Chrome profile of that account, dev in his Chrome profile of his own account
    account = env_value("TVU_TEST_ACCOUNT", env_file) if key in ("tvu-test", "tvu-com-test") else owner if key == "tvu-dev" else None
    opened = _open_browser(url, browser, {"tvu-test": "test", "tvu-com-test": "test", "tvu-dev": "dev"}.get(key), account) if open_browser else False
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
    # whose session: the user-auth service of the host it came from (dev's lives under its userservice)
    email = _sid_email(env_file, state["sid"], (host_url + "/userAuth") if key == "tvu-dev" else None)
    sessions = _load_sessions()                             # re-read: another reader may have marked a session meanwhile
    for old in [o_ for o_, n_ in SESSION_NAMES.items() if key in (o_, n_)]:
        sessions.pop(old, None)                             # the alias holds the old object; on save it would win
    sessions[key] = {**{k: v for k, v in cur.items() if k not in ("sid", "obtained_at", "rejected_at", "source", "cookies", "lifetimes_s", "account")},
                     "sid": state["sid"], "obtained_at": _now(), "rejected_at": None, "source": state["source"],
                     "cookies": state["cookies"], "lifetimes_s": cur.get("lifetimes_s") or [], "account": email}
    _save_sessions(sessions)
    msg = {key: "stored", "obtained_at": sessions[key]["obtained_at"], "source": state["source"], "account": email}
    print(json.dumps(msg) if json_out else f"{key} session stored for {email} ({state['source']}, {msg['obtained_at']})")


def _sid_email(env_file, sid, base=None):
    """Whose session a SID is: the user-auth service's GetInfoJSON, the call keepalive makes. '?' when it cannot say."""
    base = (base or env_value("TVU_USER_AUTH_BASE", env_file) or USER_AUTH_DEFAULT).rstrip("/")
    req = urllib.request.Request(base + "/main/GetInfoJSON", data=urllib.parse.urlencode({"session": sid}).encode(),
                                 headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = json.loads(r.read())
        return ((body.get("user") or {}).get("email")) or "?"
    except Exception:
        return "?"


# ── bundles ──────────────────────────────────────────────────────────────────

def when(v):
    """epoch ms | epoch s | iso → 'YYYY-MM-DD HH:MM'."""
    try:
        n = float(v)
        if n > 1e12: n /= 1000
        return datetime.datetime.fromtimestamp(n).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(v or "")[:16]


def _bundles_path(kind, line):
    return os.path.join(F.store_dir("builds", "bundles", kind), f"{_safe(line) or '_all'}.json")


def stored_bundles(kind, line, limit):
    """The store's bundle list for a host and line name while fresh and at least as deep as `limit`, or its fresh gap
    (the host refused at the last read); else None."""
    if not _store_fresh():
        return None
    doc = F.read_json(_bundles_path(kind, line))
    if not doc:
        return None
    gap = doc.get("gap")
    if gap and F.fresh(gap.get("at")) and str(gap.get("at")) >= str(doc.get("at") or ""):
        return {"gap": gap, "at": doc.get("at"), "bundles": doc.get("bundles")}
    if F.fresh(doc.get("at")) and (doc.get("limit", 0) >= limit or len(doc.get("bundles") or []) < doc.get("limit", 0)):
        return doc
    return None


def bundle_list(us, line, limit=50, fresh=False):
    doc = None if fresh else stored_bundles(us.kind, line, limit)
    if doc is not None:
        if doc.get("gap"):
            g = doc["gap"]
            print(f"userservice {us.kind}: {g.get('why')} (facts {str(g.get('at'))[:16]}; last good read {str(doc.get('at') or 'none')[:16]}; --fresh retries)", file=sys.stderr)
            sys.exit(int(g.get("exit") or EX_REMOTE))
        F.served("release", doc["at"], f"bundles {us.kind} {line}")
        return list(doc["bundles"])[:limit]
    try:
        body = us.call("/userGroup/user-group/tagBundle/page",
                       {"bundleName": line, "operator": "", "createStartTime": "", "createEndTime": "", "pageNum": 1, "pageSize": limit})
    except SystemExit as e:
        if F:
            prev = F.read_json(_bundles_path(us.kind, line), {}) or {}
            prev["gap"] = {"at": F.now_iso(), "exit": e.code if isinstance(e.code, int) else EX_REMOTE, "why": f"read failed (exit {e.code})"}
            F.write_json(_bundles_path(us.kind, line), prev)
        raise
    rows = ((body or {}).get("result") or {}).get("list") or []
    if F:
        F.write_json(_bundles_path(us.kind, line), {"at": F.now_iso(), "host": us.kind, "line": line, "limit": limit, "bundles": rows})
    return rows


def refresh_bundles(env_file, host, line, limit):
    """`ela facts refresh`: one list per host and line, written through; (rows, gap)."""
    return _refresh_read(lambda: bundle_list(LazyUS(env_file, host), line, limit, fresh=True))


def bundle_detail(us, bundle_id, fresh=False):
    # a China bundle's detail is kept under its own host: an id is unique on one userservice, not across two
    where = (us.kind, "detail") if us.kind in ("cn", "dev") else ("detail",)
    path = os.path.join(F.store_dir("builds", "bundles", *where), f"{_safe(bundle_id)}.json") if F else None
    doc = F.read_json(path) if path else None
    if doc and not fresh and _store_fresh() and F.fresh(doc.get("at")):
        F.served("release", doc["at"], f"bundle {bundle_id}")
        return doc["bundle"]
    body = us.call(f"/userGroup/user-group/tagBundle/getDetail?bundleId={urllib.parse.quote(str(bundle_id))}")
    out = (body or {}).get("result") or {}
    if path and out:
        F.write_json(path, {"at": F.now_iso(), "host": us.kind, "bundle": out})
    return out


def read_hosts(env_file, read, hosts=HOSTS):
    """One read per host, each on its own: `read(host)` → (rows, read_at). A host that does not answer leaves the
    others whole and becomes a gap with its own last words; the China host while the site lacks its names is a note,
    never a gap. ([{host, rows, read_at}], [{host, exit, why}], [note])."""
    got, gaps, notes = [], [], []
    for host in hosts:
        if host == "cn" and cn_missing(env_file):
            notes.append(cn_note(cn_missing(env_file))); continue
        said = io.StringIO()
        try:
            with contextlib.redirect_stderr(said):
                rows, at = read(host)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else EX_REMOTE
            last = next((l.strip() for l in reversed(said.getvalue().splitlines()) if l.strip()), "") or f"exit {code}"
            if host == "cn" and last == cn_unmapped_note():
                notes.append(last)
            else:
                gaps.append({"host": host, "exit": code, "why": last})
            continue
        sys.stderr.write(said.getvalue())
        got.append({"host": host, "rows": rows, "read_at": at})
    return got, gaps, notes


def _stamp(at):
    """A read time as the reader's clock shows it: 'YYYY-MM-DD HH:MM' local, from an ISO stamp with Z or an offset."""
    try:
        t = datetime.datetime.fromisoformat(str(at).replace("Z", "+00:00"))
        return (t.astimezone() if t.tzinfo else t).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(at or "")[:16]


def _hosts_exit(got, gaps, what):
    """Say each note and gap once on stderr; exit only when no host answered (prod's code first) or none had a row."""
    if not got:
        code = next((g["exit"] for g in gaps if g["host"] == "prod"), None) or next((g["exit"] for g in gaps), EX_USAGE)
        sys.exit(code)
    if not any(h["rows"] for h in got):
        print(f"no {what} on {', '.join(h['host'] for h in got)}", file=sys.stderr); sys.exit(EX_NOTFOUND)


def _say_hosts(gaps, notes):
    for g in gaps:
        print(f"not read: {g['host']} — {g['why']}; the other hosts' rows are whole", file=sys.stderr)
    for n in notes:
        print(n, file=sys.stderr)


def _bundle_rows(env_file, host, line, limit, fresh):
    """(rows newest first, read_at) for one host; the China host's rows carry what the map says of their names."""
    line = default_line(host) if line is None else line
    rows = bundle_list(LazyUS(env_file, host), line, limit, fresh=fresh)
    rows.sort(key=lambda x: str(x.get("createTime") or ""), reverse=True)
    doc = None if fresh else stored_bundles(host, line, limit)
    return ([cn_bundle(b) for b in rows] if host == "cn" else rows), (doc or {}).get("at") or _now()


def _bundle_line(b, host):
    tail = ""
    if host == "cn":
        tail = f"  {b['shown']} ({b['lane']})" if b.get("mapped") else "  unmapped"
    return f"{str(b.get('bundleName')):<32} {str(b.get('bundleId')):<22} {when(b.get('createTime')):<17} {b.get('operator') or ''}{tail}"


def cmd_bundles(a):
    if a.raw:
        if not a.host:
            print("--raw shows one host's answer as it is: name it with --host", file=sys.stderr); sys.exit(EX_USAGE)
        line = default_line(a.host) if a.line is None else a.line
        rows = bundle_list(US(a.env_file, a.host), line, a.limit, fresh=True)   # the host now, no mapping, written through
        if a.json:
            print(json.dumps({"host": a.host, "query": line, "raw": True, "count": len(rows), "bundles": rows, "read_at": _now()}, ensure_ascii=False)); return
        print(f"# {a.host} · query {line!r} · {len(rows)} bundle(s) as the host answers, names quoted as read · {_stamp(_now())}")
        for b in rows:
            rest = {k: v for k, v in b.items() if k not in ("bundleName", "bundleId", "createTime") and v not in (None, "")}
            print(f"{json.dumps(b.get('bundleName'), ensure_ascii=False):<36} {str(b.get('bundleId')):<22} {when(b.get('createTime')):<17} "
                  + json.dumps(rest, ensure_ascii=False))
        return
    if a.host:
        line = default_line(a.host) if a.line is None else a.line
        rows, at = _bundle_rows(a.env_file, a.host, line, a.limit, a.fresh)
        if a.json:
            print(json.dumps({"host": a.host, "line": line, "count": len(rows), "bundles": rows, "read_at": at}, ensure_ascii=False)); return
        if not rows:
            print(f"no bundles for {line!r} on {a.host}", file=sys.stderr); sys.exit(EX_NOTFOUND)
        for b in rows:
            print(_bundle_line(b, a.host))
        return
    # no host named: every host, each row saying where it was read and when
    got, gaps, notes = read_hosts(a.env_file, lambda h: _bundle_rows(a.env_file, h, a.line, a.limit, a.fresh))
    rows = [dict(b, host=h["host"], read_at=h["read_at"]) for h in got for b in h["rows"]]
    _say_hosts(gaps, notes)
    if a.json:
        print(json.dumps({"host": "all", "line": a.line if a.line is not None else DEFAULT_LINE, "count": len(rows), "bundles": rows,
                          "hosts": [{"host": h["host"], "read_at": h["read_at"], "count": len(h["rows"]),
                                     "query": default_line(h["host"]) if a.line is None else a.line} for h in got],
                          "gaps": gaps, "notes": notes}, ensure_ascii=False))
        if not got:
            _hosts_exit(got, gaps, "bundles")
        return
    _hosts_exit(got, gaps, "bundles")
    for h in got:
        print(f"# {h['host']} — {len(h['rows'])} bundle(s), read {_stamp(h['read_at'])}")
        for b in h["rows"]:
            print(_bundle_line(b, h["host"]))


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
    out = ["# A hold on prod's bundle per release line, set on the owner's word with `ela release pin` (ela ADR 0013).",
           "# Without one, prod follows the newest official bundle; a line here is held on an older one, with why.",
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
    if not is_official(name, a.line):
        print(f"pin: {name!r} is not an official {a.line} bundle", file=sys.stderr); sys.exit(EX_USAGE)
    newest = official_bundle(us, a.line)
    if newest and str(newest.get("bundleId")) == bid and not was:
        print(f"{a.line}: {name} is already the newest official, which prod follows without a pin; nothing to hold"); return
    entry = {"official": name, "id": bid, "set": datetime.date.today().isoformat(), "by": "owner", "why": a.why}
    if was and was.get("id") == bid:
        print(f"{a.line}: already pinned to {name}"); return
    print(f"{a.line}: {(was or {}).get('official') or 'no pin'} → {name} ({bid})")
    if not a.apply:
        print("dry run; --apply writes blueprint/releases.yaml and commits it alone"); return
    lines[a.line] = entry
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(render_pins(lines))
    msg = f"Hold {a.line}'s prod bundle on {name}\n\n{a.why}\n\nSet on the owner's apply (ela ADR 0013)."
    for cmd in (["git", "-C", elak, "add", "--", PINS_REL], ["git", "-C", elak, "commit", "-q", "-m", msg, "--", PINS_REL]):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            print(f"elak: {' '.join(cmd[3:5])} failed: {(r.stderr or r.stdout).strip()[-200:]}", file=sys.stderr); sys.exit(EX_REMOTE)
    print(f"pinned and committed in elak: {PINS_REL}; `ela publish pins` carries it to the published directory")


def cmd_unpin(a):
    """Lift a line's hold: prod follows the newest official bundle again. Dry run unless --apply, which removes the one
    entry and commits blueprint/releases.yaml alone (ADR 0012's write, ADR 0013's meaning)."""
    elak = site().get("elak")
    path = os.path.join(elak or "", PINS_REL)
    lines = read_pins(path) if os.path.isfile(path) else {}
    if a.line not in lines:
        print(f"{a.line}: no hold; prod follows the newest official"); return
    print(f"{a.line}: hold on {lines[a.line].get('official')} lifted → prod follows the newest official")
    if not a.apply:
        print("dry run; --apply removes the entry and commits blueprint/releases.yaml alone"); return
    del lines[a.line]
    open(path, "w").write(render_pins(lines))
    msg = f"Lift the hold on {a.line}'s prod bundle\n\nProd follows the newest official again (ela ADR 0013)."
    for cmd in (["git", "-C", elak, "add", "--", PINS_REL], ["git", "-C", elak, "commit", "-q", "-m", msg, "--", PINS_REL]):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            print(f"elak: {' '.join(cmd[3:5])} failed: {(r.stderr or r.stdout).strip()[-200:]}", file=sys.stderr); sys.exit(EX_REMOTE)
    print(f"lifted and committed in elak: {PINS_REL}; `ela publish pins` carries it")


def cmd_pins(a):
    lines = read_pins()
    if a.json:
        print(json.dumps({"path": pins_path(), "lines": lines}, ensure_ascii=False)); return
    for line, e in sorted(lines.items()):
        print(f"{line:<6} held on {e.get('official')}  (set {e.get('set')} by {e.get('by')}: {e.get('why') or 'no reason recorded'})")
    if not lines:
        print(f"no line held; prod follows the newest official bundle ({pins_path()})")


def cmd_bundle(a):
    us = US(a.env_file, a.host)
    bid, name = resolve_bundle(us, a.ref)
    detail = bundle_detail(us, bid)
    items = detail.get("serviceTagList") or []
    if a.json or a.raw:
        print(json.dumps({"host": a.host, "bundle": name, "bundleId": bid, "detail": detail} if a.raw else
                         {"host": a.host, "bundle": name, "bundleId": bid, "count": len(items), "services": items}, ensure_ascii=False)); return
    lane = cn_bundle_lane(name)[0] if a.host == "cn" else None
    print(f"# bundle {name}  id {bid}  {len(items)} service(s)  [{a.host}"
          + (f" · {lane_shown(lane)} ({lane})" if lane else " · unmapped" if a.host == "cn" else "") + "]")
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
    rows = [x for x in bundle_list(us, f"MediaHub {line}", 50) if is_official(str(x.get("bundleName") or ""), line)]
    return next((x for x in rows if pin and str(x.get("bundleId")) == str(pin.get("id"))), None) or \
        max(rows, key=lambda x: str(x.get("createTime") or ""), default=None)


def name_rules(line):
    """The closed set of bundle names the owner uses for a line ("mh2.1@" or "2.1"; map release.yaml bundle_names;
    Helm's bundle management note): (class, regex). Official names end where the form ends, so a side bundle ("MediaHub
    2.1.10 Docker Only", "MediaHub 1.5.3 SE", "MediaHub 2.0 rc8 pre") is never official. Temporary and unpublished
    bundles have no form yet and are refused."""
    ver = re.sub(r"^mh|@$", "", line)
    ln, mm = re.escape(f"mh{ver}"), re.escape(ver)
    return [("daily", re.compile(rf"^{ln}@daily-[a-z]+-s\d+-d\d+$")), ("daily", re.compile(rf"^{ln}@stage-s\d+-d\d+$")),
            ("prod", re.compile(rf"^{ln}@(?:rc|beta|ga)-s\d+-d\d+$")),
            ("official", re.compile(rf"^MediaHub {mm}\.\d+(?: \([^()]+\))?$")), ("official", re.compile(rf"^MediaHub {mm} rc\d+$"))]


def is_official(name, line, region=""):
    """Whether a bundle name is an official release of the line ("2.1") for a region's prod lane, by the one closed
    grammar. MediaHub 2.1.13 (CN Prod2) is the China region's: never the .com prod lane's official, nor its pin."""
    return name_class(name, line) == "official" and lane_region(bundle_lane(name)) == region


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
    want = {"daily": ("prod",), "prod": ("daily",), "official": ("daily",)}.get(cls, ())   # QA's bundle: not read
    for role in want:
        try:
            if role == "prod":
                us = US(env_file, "prod")
                b = official_bundle(us, line.replace("mh", "").rstrip("@"))
            else:
                us = US(env_file, "prod")
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

def _envs_path(kind):
    return os.path.join(F.store_dir("lanes"), f"envs-{kind}.json")


def stored_envs(kind):
    """The store's lane read for a host: {at, rows} or {gap} while fresh; None when there is none or it is stale."""
    if not _store_fresh():
        return None
    doc = F.read_json(_envs_path(kind))
    if not doc:
        return None
    gap = doc.get("gap")
    if gap and F.fresh(gap.get("at")) and str(gap.get("at")) >= str(doc.get("at") or ""):
        return {"gap": gap, "rows": doc.get("rows"), "at": doc.get("at")}
    if doc.get("at") and F.fresh(doc["at"]):
        return {"at": doc["at"], "rows": doc.get("rows") or []}
    return None


def lane_versions(us, want=None, fresh=False):
    """Every (service, tag, lane, version, updated) row a host publishes for the mapped service ids. Served from the
    store while its read of the host is fresh (a recorded gap exits as the live read did); a live read writes through."""
    if us.kind == "cn" and not host_service_ids("cn"):       # nothing to ask for yet: a state of the map, never a recorded gap
        if not cn_missing(us.env_file):
            print(cn_unmapped_note(), file=sys.stderr); sys.exit(EX_USAGE)
        print(cn_note(cn_missing(us.env_file)), file=sys.stderr); sys.exit(EX_USAGE)
    doc = None if fresh else stored_envs(us.kind)
    if doc is not None:
        if doc.get("gap"):
            g = doc["gap"]
            print(f"userservice {us.kind}: {g.get('why')} (facts {str(g.get('at'))[:16]}; last good read {str(doc.get('at') or 'none')[:16]}; --fresh retries)", file=sys.stderr)
            sys.exit(int(g.get("exit") or EX_REMOTE))
        F.served("release", doc["at"], f"envs {us.kind}")
        return [r for r in doc["rows"] if not want or want in r.get("service", "")]
    try:
        out = _lane_versions_live(us, want)
    except SystemExit as e:
        if F and not want:
            prev = F.read_json(_envs_path(us.kind), {}) or {}
            prev["gap"] = {"at": F.now_iso(), "exit": e.code if isinstance(e.code, int) else EX_REMOTE, "why": f"read failed (exit {e.code})"}
            F.write_json(_envs_path(us.kind), prev)
        raise
    if F and not want:
        F.write_json(_envs_path(us.kind), {"at": F.now_iso(), "host": us.kind, "rows": out})
    return out


def refresh_envs(env_file, host):
    """`ela facts refresh`: one read of a host's lanes, written through; (rows, gap)."""
    return _refresh_read(lambda: lane_versions(LazyUS(env_file, host), fresh=True))


def host_service_ids(kind):
    """service id → [[slug, version field], …] for a host: each host publishes under its own ids, the China host's
    from the map's regions.china.userservice.service_ids."""
    if kind == "cn":
        return cn_map().get("service_ids") or {}
    return rmap("service_ids" if kind == "prod" else "qa_service_ids")


def _entries(body):
    r = body.get("result") if isinstance(body, dict) else None
    return r if isinstance(r, list) else (body.get("data") if isinstance(body, dict) and isinstance(body.get("data"), list) else (r or {}).get("list") or [])


def raw_envs(us, want=None):
    """A host's own words, nothing mapped: its service list (name, id), or with `want` (an id, or part of a name) the
    tag records of each service it matches. The first read of a host whose ids and tag names are not in the map yet."""
    services = _entries(us.call("/userGroup/user-group/service/list?showInternalFlag=true"))
    if not want:
        return {"services": [{"serviceName": x.get("serviceName"), "serviceId": x.get("serviceId")} for x in services]}
    hit = [x for x in services if str(x.get("serviceId")) == want or want.lower() in str(x.get("serviceName") or "").lower()]
    out = []
    for x in hit:
        tags = _entries(us.call(f"/userGroup/user-group/tag/getTagVersionList?serviceId={urllib.parse.quote(str(x.get('serviceId')))}"))
        out.append({"serviceName": x.get("serviceName"), "serviceId": x.get("serviceId"), "tags": tags})
    return {"services": out}


def _lane_versions_live(us, want=None):
    ids = host_service_ids(us.kind)
    out = []
    for svc_id, slugs in ids.items():
        slugs = [tuple(x) for x in slugs]
        if want and not any(want in slug for slug, _ in slugs):
            continue
        entries = _entries(us.call(f"/userGroup/user-group/tag/getTagVersionList?serviceId={svc_id}"))
        for slug, field in slugs:
            if want and want not in slug:
                continue
            for e in entries:
                out.append({"service": slug, "tag": e.get("tagName"), "lane": lane_of(us.kind, e.get("tagName")),
                            "version": " ".join(str(e.get(field) or "").split()), "updated": when(e.get("updateTime") or e.get("createTime"))})
    return out


def gateway_versions(want=None, lane=None, get=None, fresh=False):
    """Every (service, lane, token, version) the map's gateway_versions names, read live from the service through the
    API gateway: GET <site.json services.<site_service>.url><path with the lane's token>. A lane whose host is not in
    site.json, that does not answer 200, or whose body no version family parses is UNDETERMINED with the reason —
    never "not deployed": a gateway answers 503 for a route it knows with no instance behind it, and 404 for none.
    Served from the store while its read is fresh; a whole live read (no `get` injected) writes through."""
    path = os.path.join(F.store_dir("lanes"), "gateway.json") if F else None
    doc = F.read_json(path) if path else None
    if doc and not fresh and get is None and _store_fresh() and F.fresh(doc.get("at")):
        F.served("release", doc["at"], "gateway")
        return [r for r in doc["rows"] if (not want or want in r["service"]) and (not lane or r["lane"] == lane)]
    live = get is None
    get = get or (lambda url: http(url, timeout=10))
    services = site().get("services") or {}
    out = []
    for svc, cfg in (rmap("gateway_versions") or {}).items():
        if want and want not in svc:
            continue
        for ln, where in sorted((cfg.get("lanes") or {}).items()):
            if lane and ln != lane:
                continue
            key, token = where.get("site_service"), where.get("token")
            row = {"service": svc, "lane": ln, "token": token, "site_service": key, "source": "gateway", "version": None}
            base = (services.get(key) or {}).get("url")
            if not base:
                out.append(dict(row, status="undetermined", why=f"site.json services.{key}.url is not set")); continue
            st, body = get(base.rstrip("/") + str(cfg.get("path") or "").replace("{token}", str(token)))
            raw = " ".join(body.split()) if st == 200 and isinstance(body, str) else ""
            if not raw or parse_version(raw) is None:
                why = f"HTTP {st}" + (f": {str(body)[:80]!r}" if st == 200 else {503: " (route known, no instance)", 404: " (no route)", 0: f" ({body})"}.get(st, ""))
                out.append(dict(row, status="undetermined", why=why)); continue
            out.append(dict(row, status="read", version=raw))
    if path and live and not want and not lane:
        F.write_json(path, {"at": F.now_iso(), "rows": out})
    return out


def refresh_gateway():
    try:
        return gateway_versions(fresh=True), None
    except SystemExit as e:
        return None, f"exit {e.code}"


# ── dev against daily and prod: docker images, read-only ────────────────────────────────────────────
# Dev's GM names its tags as slots ("backup", "default", "Production5"), not versions, and the image is in
# backendVersion; a service's isDefault tag is what an account without a dev bundle runs (read first-hand 2026-11-23:
# Docker Rtmp Decoder's default "backup" carries playeroftvu:1.0.48). So dev is matched by service name and by image,
# never by tag name or id. Nothing is written: the plan for a write is vault ela/2026-11-23-plan-release-sync-dev.md.

def _image(ref):
    """'host/ns/repo:tag' → (repo path, tag); a value without a colon is a bare tag of an unknown repo."""
    ref = str(ref or "").strip()
    repo, _, tag = ref.rpartition(":") if ":" in ref.split("/")[-1] else (ref, "", "")
    return (repo, tag) if tag else ("", ref)


def _image_order(tag):
    """A docker tag's numbers in order ('8.13.6build164-ubuntu' → (8, 13, 6, 164)); () when it has none."""
    return tuple(int(n) for n in re.findall(r"\d+", str(tag or "")))


def image_cmp(a, b):
    """-1, 0, 1 for two image refs of one repo; None when they are not comparable (another repo, or no numbers)."""
    (ra, ta), (rb, tb) = _image(a), _image(b)
    if ra and rb and ra != rb:
        return None
    if ta == tb:
        return 0
    oa, ob = _image_order(ta), _image_order(tb)
    if not oa or not ob or oa == ob:
        return None
    return (oa > ob) - (oa < ob)


def sync_source(us, ref, line):
    """(bundle id, name, how) for a source: `prod` (the line's official, pinned or newest), `daily` (the newest daily
    or stage bundle of the line), or a bundle name, prefix or id."""
    if ref == "prod":
        b = official_bundle(us, line)
        if not b:
            print(f"sync-dev: no official MediaHub {line} bundle on {us.kind}", file=sys.stderr); sys.exit(EX_NOTFOUND)
        return str(b["bundleId"]), str(b["bundleName"]), "prod official"
    if ref == "daily":
        rows = [b for b in bundle_list(us, f"mh{line}@", 50) if name_class(str(b.get("bundleName") or ""), f"mh{line}@") == "daily"]
        if not rows:
            print(f"sync-dev: no daily bundle of mh{line}@ on {us.kind}", file=sys.stderr); sys.exit(EX_NOTFOUND)
        b = max(rows, key=lambda x: str(x.get("createTime") or ""))
        return str(b["bundleId"]), str(b["bundleName"]), "newest daily"
    bid, name, rule = resolve_bundle_loose(us, ref)
    return bid, name, rule


def sync_dev(env_file, sources, line, host="prod"):
    """Dev's docker images against one or more source bundles. The first source is the target a sync would take;
    `ahead` is a dev image above every source's image of the same repo."""
    src_us, dev = US(env_file, host), US(env_file, "dev")
    srcs = []
    for ref in sources:
        bid, name, how = sync_source(src_us, ref, line)
        rows = [i for i in bundle_detail(src_us, bid).get("serviceTagList") or [] if str(i.get("serviceName") or "").startswith("Docker")]
        srcs.append({"ref": ref, "name": name, "id": bid, "how": how,
                     "images": {str(i["serviceName"]).strip(): str(i.get("backendVersion") or i.get("defaultBackendVersion") or "") for i in rows}})
    dev_ids = {str(x.get("serviceName") or "").strip().lower(): x.get("serviceId") for x in _entries(dev.call("/userGroup/user-group/service/list?showInternalFlag=true"))}
    out = []
    for svc in sorted(set().union(*(s["images"] for s in srcs))):
        want = srcs[0]["images"].get(svc)
        row = {"service": svc, "sources": {s["ref"]: s["images"].get(svc) for s in srcs}, "target": want}
        sid = dev_ids.get(svc.lower())
        if not sid:
            out.append({**row, "state": "service not on dev", "dev": None}); continue
        tags = _entries(dev.call(f"/userGroup/user-group/tag/getTagVersionList?serviceId={urllib.parse.quote(str(sid))}"))
        default = next((t for t in tags if str(t.get("isDefault")) == "1"), None)
        now = str((default or {}).get("backendVersion") or "") or None
        row["dev"] = {"tag": (default or {}).get("tagName"), "image": now, "tags": len(tags)}
        carrying = [str(t.get("tagName")) for t in tags if want and str(t.get("backendVersion") or "") == want]
        if not want:
            state = "not in target"
        elif now == want:
            state = "same"
        elif carrying:
            state = f"on dev as tag {carrying[0]}" + (f" (+{len(carrying) - 1})" if len(carrying) > 1 else "")
        else:
            state = "refused: no dev tag carries this image"
        cmps = [image_cmp(now, s["images"].get(svc)) for s in srcs if s["images"].get(svc)]
        row["ahead"] = bool(now) and bool(cmps) and all(c == 1 for c in cmps)
        row["by"] = None                                    # the audit of dev writes does not exist yet: by hand in GM
        out.append({**row, "state": state})
    return srcs, out


def cmd_sync_dev(a):
    srcs, rows = sync_dev(a.env_file, a.sources or ["daily", "prod"], a.line, a.host)
    rows_shown = [r for r in rows if r.get("ahead")] if a.ahead else rows
    refused = [r for r in rows if str(r["state"]).startswith("refused")]
    if a.json:
        print(json.dumps({"dry_run": True, "sources": [{k: s[k] for k in ("ref", "name", "id", "how")} for s in srcs],
                          "rows": rows_shown, "refused": len(refused), "ahead": sum(1 for r in rows if r.get("ahead")),
                          "dev_basis": "each service's default tag on dev (what an account without a dev bundle runs)"}, ensure_ascii=False)); return
    print(f"# dry run: dev's docker images against {', '.join(f'{s['name']} ({s['how']})' for s in srcs)}; "
          f"target {srcs[0]['name']}; dev = each service's default tag; nothing is written")
    tag = lambda v: _image(v)[1] if v else "—"
    for r in rows_shown:
        d = r.get("dev") or {}
        others = "  ".join(f"{k}={tag(v)}" for k, v in list(r["sources"].items())[1:])
        print(f"  {r['service']:<40} dev {tag(d.get('image')):<26} ({str(d.get('tag') or '—')[:14]:<14}) → {tag(r['target']):<26} "
              f"{r['state']}{'  ▲ dev ahead' if r.get('ahead') else ''}{'  ' + others if others else ''}")
    same = sum(1 for r in rows if r["state"] == "same")
    print(f"{len(rows)} service(s): {same} same · {sum(1 for r in rows if str(r['state']).startswith('on dev'))} on dev under another tag · "
          f"{len(refused)} refused (image not on dev) · {sum(1 for r in rows if r.get('ahead'))} dev ahead of every source")


def cmd_gateway(a):
    want = (a.service or "").lower()
    if want and not any(want in s for s in rmap("gateway_versions")):
        print(f"{a.service!r} is not in map/release.yaml gateway_versions ({', '.join(rmap('gateway_versions')) or 'none'})", file=sys.stderr); sys.exit(EX_NOTFOUND)
    out = gateway_versions(want, a.lane, fresh=a.fresh)
    if a.json:
        doc = (F.read_json(os.path.join(F.store_dir("lanes"), "gateway.json")) or {}) if F and not a.fresh else {}
        print(json.dumps({"source": "gateway", "rows": out, "read_at": doc.get("at") or _now()}, ensure_ascii=False)); return
    cur = None
    for r in out:
        if r["service"] != cur:
            cur = r["service"]; print(f"# {cur}  [gateway]")
        v = vlabel(parse_version(r["version"])) if r["status"] == "read" else f"UNDETERMINED — {r['why']}"
        print(f"  {r['lane']:<13} {r['site_service']:<14} {str(r['token']):<8} {v:<16} {r['version'] or ''}")


def _env_rows(env_file, host, want, fresh):
    """(rows, read_at) for one host; a China row says its region, and a tag the map does not name stays, unmapped."""
    rows = lane_versions(LazyUS(env_file, host), want, fresh=fresh)
    doc = None if fresh else stored_envs(host)
    if host == "cn":
        rows = [dict(r, region="china", mapped=bool(r.get("lane"))) for r in rows]
    return rows, (doc or {}).get("at") or _now()


def _env_line(r, host):
    lane = r["lane"] or ("unmapped" if host == "cn" else "?")
    return f"  {str(lane):<13} {str(r['tag']):<22} {str(r['version']):<40} {str(r['updated'] or '')[:19]}"


def cmd_envs(a):
    want = (a.service or "").lower()
    if a.raw:
        if not a.host:
            print("--raw shows one host's answer as it is: name it with --host", file=sys.stderr); sys.exit(EX_USAGE)
        got = raw_envs(US(a.env_file, a.host), a.service)
        if a.json:
            print(json.dumps({"host": a.host, "raw": True, "read_at": _now(), **got}, ensure_ascii=False)); return
        print(f"# {a.host} · {len(got['services'])} service(s) as the host answers, names quoted as read · {_stamp(_now())}")
        for x in got["services"]:
            print(f"{json.dumps(x.get('serviceName'), ensure_ascii=False):<44} {x.get('serviceId')}")
            for t in x.get("tags") or []:
                rest = {k: v for k, v in t.items() if k in ("backendVersion", "frontendVersion") and v}
                print(f"  {json.dumps(t.get('tagName'), ensure_ascii=False):<30} {json.dumps(rest, ensure_ascii=False)}")
        return
    if a.host:
        out, at = _env_rows(a.env_file, a.host, want, a.fresh)
        if a.json:
            print(json.dumps({"host": a.host, "rows": out, "read_at": at}, ensure_ascii=False)); return
        if not out:
            print(f"no env versions for {a.service!r} on {a.host}", file=sys.stderr); sys.exit(EX_NOTFOUND)
        cur = None
        for r in sorted(out, key=lambda x: (x["service"], str(x["lane"] or "~"), str(x["tag"]))):
            if r["service"] != cur:
                cur = r["service"]; print(f"# {cur}  [{a.host}]")
            print(_env_line(r, a.host))
        return
    # no host named: every host, each row saying where it was read and when
    got, gaps, notes = read_hosts(a.env_file, lambda h: _env_rows(a.env_file, h, want, a.fresh))
    rows = [dict(r, host=h["host"], read_at=h["read_at"]) for h in got for r in h["rows"]]
    _say_hosts(gaps, notes)
    if a.json:
        print(json.dumps({"host": "all", "rows": rows, "hosts": [{"host": h["host"], "read_at": h["read_at"], "count": len(h["rows"])} for h in got],
                          "gaps": gaps, "notes": notes}, ensure_ascii=False))
        if not got:
            _hosts_exit(got, gaps, "env versions")
        return
    _hosts_exit(got, gaps, f"env versions for {a.service!r}" if a.service else "env versions")
    for h in got:
        cur = None
        for r in sorted(h["rows"], key=lambda x: (x["service"], str(x["lane"] or "~"), str(x["tag"]))):
            if r["service"] != cur:
                cur = r["service"]; print(f"# {cur}  [{h['host']} · read {_stamp(h['read_at'])}]")
            print(_env_line(r, h["host"]))


# ── jenkins ───────────────────────────────────────────────────────────────────

def job_of(name):
    """A Jenkins job by its name, its service slug, or a substring; None when unknown."""
    JOBS = rmap("jobs")
    if name in JOBS:
        return name
    by_service = {v: k for k, v in JOBS.items()}
    return by_service.get(name) or next((k for k in JOBS if name.lower() in k), None)


def _builds_path(job):
    return os.path.join(F.store_dir("builds"), f"{_safe(job)}.json")


def stored_builds(job, limit):
    if not _store_fresh():
        return None
    doc = F.read_json(_builds_path(job))
    if doc and F.fresh(doc.get("at")) and (doc.get("limit", 0) >= limit or len(doc.get("builds") or []) < doc.get("limit", 0)):
        return doc
    return None


def builds_rows(job, limit=15, fresh=False):
    """A job's newest builds: number, version, build, result, branch, sha (12), sha_full, time, url. Served from the
    store while fresh and deep enough; a live read writes through. Raises SystemExit(5) when Jenkins does not answer."""
    doc = None if fresh else stored_builds(job, limit)
    if doc is not None:
        F.served("release", doc["at"], f"builds {job}")
        return list(doc["builds"])[:limit]
    JOBS = rmap("jobs")
    base = _service_url("jenkins")
    tree = f"builds[number,displayName,result,timestamp,url,actions[lastBuiltRevision[branch[name,SHA1]]]]{{0,{limit}}}"
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
    if F:
        F.write_json(_builds_path(job), {"at": F.now_iso(), "job": job, "service": JOBS[job], "limit": limit, "builds": rows})
    return rows


def refresh_builds(job, limit):
    """`ela facts refresh`: one Jenkins read per job, written through; (rows, gap)."""
    try:
        return builds_rows(job, limit, fresh=True), None
    except SystemExit as e:
        return None, f"exit {e.code}"


def cmd_builds(a):
    JOBS = rmap("jobs")
    job = job_of(a.job)
    if not job:
        print(f"unknown job or service {a.job!r}; jobs: {', '.join(JOBS)}", file=sys.stderr); sys.exit(EX_USAGE)
    rows = builds_rows(job, a.limit, fresh=a.fresh)
    if a.json:
        doc = None if a.fresh else stored_builds(job, a.limit)
        print(json.dumps({"job": job, "service": JOBS[job], "builds": rows, "read_at": (doc or {}).get("at") or _now()}, ensure_ascii=False)); return
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
    if a.host == "dev" and (a.target != "tvu" or a.as_ or a.keepalive):
        print("--host dev is the owner's own sign-in on dev, nothing else: ela login tvu --host dev", file=sys.stderr); sys.exit(EX_USAGE)
    if a.keepalive:
        if a.target != "tvu":
            print("--keepalive applies to the tvu session only: ela login tvu --keepalive", file=sys.stderr); sys.exit(EX_USAGE)
        keepalive_tvu(a.env_file, json_out=a.json)
    if a.target == "tvu":
        key = "tvu-test" if a.as_ == "test" else "tvu-dev" if a.host == "dev" else "tvu"
        login_tvu(a.env_file, force=a.force, timeout=a.timeout, json_out=a.json, open_browser=not a.no_browser,
                  key=key, browser=a.browser or ("chrome" if key != "tvu" else None)); return
    if a.target == "cn":                                    # proves the address and the account; the session id is never shown
        missing = cn_missing(a.env_file)
        if missing:
            print(cn_note(missing), file=sys.stderr); sys.exit(EX_USAGE)
        f = _env_file(a.env_file)
        sid = account_login(f, _service_url(CN_SERVICE), CN_KEYS, "China")
        # kept beside the tvu session (mode 600) for a reader that holds no account: the runner copies it into
        # mediahub-bot's session file, as it does the tvu one; an account session lives two hours
        d = _load_sessions()
        d["cn"] = {"sid": sid, "obtained_at": _now(), "expires_h": 2}
        _save_sessions(d)
        print(json.dumps({"cn": "obtained", "expires_h": 2, "shown": False}) if a.json
              else "China session obtained (2h); the read verbs log in by themselves: ela release bundles --host cn --raw"); return
    host = _service_url("userservice-test")
    sid = tvutest_login(a.env_file, host)
    # the session id is a credential: shown only to a person at a terminal, never into a pipe or a session's shell
    # (the audit of 2026-11-13). Nothing needs it copied: Client logs in by itself when TVUTEST_SID is absent.
    if sys.stdout.isatty() and not a.json:
        print(f"TVUTEST_SID={sid}\n(put it in the env file; it expires in 2h)"); return
    print(json.dumps({"tvutest": "obtained", "expires_h": 2, "shown": False}) if a.json
          else "QA session obtained (2h); its id is shown only in a terminal, and the read verbs log in by themselves")


# ── a build a lane took: one line per service and what for ───────────────────────────────────────────
# When a lane's versions move, the morning session writes one record per build, once:
# <reports>/releases/<line>/<date>-build-<n>-to-<lane>.json. The service lines are its judgment (the tickets and
# commits the build carries, grouped: "FloSports public API: six endpoints", never six titles); everything else reads
# the record: today.md's Releases fact, the release note in the vault, `ela release changes <lane>`. Reason: the
# review of the vault's first day on layout 5 (<runtime>/drafts/2026-11-12-vault-two-day-review-brief.md, change 2).
BUILD_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})-build-([\w.]+)-to-([a-z0-9-]+)\.json$")
BUILD_LINES, BUILD_WORDS = 4, 15
KEY_IN = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")


def lane_slug(name):
    return re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")


def build_name(rec):
    """The record's file stem, also its release note's: `<date>-build-<n>-to-<lane as the team names it>`."""
    return f"{rec['date']}-build-{rec['build']}-to-{lane_slug(rec.get('lane_name') or rec['lane'])}"


def build_check(rec, name=None):
    """Problems with a build record, [] when it is whole: who it is (line, lane, build, date), at least one service,
    each with from, to and a purpose of at most BUILD_WORDS words, whole (no ellipsis), its ticket keys in `keys`
    rather than in the words."""
    out = [f"missing {k}" for k in ("line", "lane", "build", "date") if not rec.get(k)]
    svcs = rec.get("services") or []
    if not svcs:
        out.append("no service")
    for i, v in enumerate(svcs):
        what = " ".join(str(v.get("for") or "").split())
        who = v.get("service") or f"service {i + 1}"
        out += [f"{who}: missing {k}" for k in ("service", "to", "for") if not v.get(k)]
        if len(what.split()) > BUILD_WORDS:
            out.append(f"{who}: what for is {len(what.split())} words, at most {BUILD_WORDS}")
        if "…" in what or "..." in what:
            out.append(f"{who}: what for is cut; write it whole")
        if KEY_IN.search(what):
            out.append(f"{who}: a ticket key in the words; put it in keys")
    if name and not out and name != build_name(rec) + ".json":
        out.append(f"named {name}, expected {build_name(rec)}.json")
    return out


def build_records(reports):
    """Every whole build record under <reports>/releases/, newest first → [rec with `name`]; a broken one is skipped."""
    root = os.path.join(reports or "", "releases")
    out = []
    for line in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        d = os.path.join(root, line)
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if not BUILD_FILE.match(f):
                continue
            try:
                rec = json.load(open(os.path.join(d, f), encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(rec, dict) and not build_check(rec):
                out.append(dict(rec, name=f[:-5]))
    return sorted(out, key=lambda r: (r.get("at") or r["date"], r["name"]), reverse=True)


def build_lines(rec, cap=BUILD_LINES):
    """One line per changed service, at most `cap`: `<service> <old> → <new>: <what for>` and its ticket keys after
    it, bare (the page's linker links them); a last line counts what did not fit."""
    out = []
    svcs = rec.get("services") or []
    shown = svcs if len(svcs) <= cap else svcs[:cap - 1]
    for v in shown:
        move = f"{v['from']} → {v['to']}" if v.get("from") else f"→ {v['to']}"
        keys = " ".join(v.get("keys") or [])
        out.append(f"{v['service']} {move}: {' '.join(str(v['for']).split())}" + (f" ({keys})" if keys else ""))
    if len(shown) < len(svcs):
        out.append(f"{len(svcs) - len(shown)} more services in the release note")
    return out


def build_title(rec):
    return f"MediaHub {rec['line']} build {rec['build']} → {rec.get('lane_name') or rec['lane']} · what changed"


TITLE_CHARS = 90


def ticket_title(summary, n=TITLE_CHARS):
    """A Jira summary as pages show it: whole up to about n characters, a longer one cut at a word boundary."""
    t = " ".join(str(summary or "").split()).replace("|", "/")
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0].rstrip(" ,;:-") + " …"


def ticket_facts(issue):
    """{summary, status, assignee} of a Jira issue as read or as the fact store keeps it; None for no issue."""
    if not issue:
        return None
    f = issue.get("fields") or issue
    who = f.get("assignee")
    rep = f.get("reporter")
    return {"summary": f.get("summary") or "", "status": ((f.get("status") or {}).get("name") if isinstance(f.get("status"), dict) else f.get("status")) or "",
            "assignee": (who or {}).get("displayName") if isinstance(who, dict) else who,
            "reporter": (rep or {}).get("displayName") if isinstance(rep, dict) else rep}


def facts_tickets(runtime, keys):
    """{key: ticket_facts} from the fact store (<runtime>/facts/jira/issues/<KEY>.json); a key it lacks is left out."""
    out = {}
    for k in keys:
        try:
            out[k] = ticket_facts(json.load(open(os.path.join(runtime or "", "facts", "jira", "issues", f"{k}.json"), encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def ticket_line(key, t, who=True):
    """One ticket in words, never a bare key: `KEY <summary> · <status>[ · <assignee>]`; the key alone is linked by the
    page's linker. A ticket the fact store lacks says so."""
    if not t:
        return f"{key} (not in the fact store)"
    return f"{key} {ticket_title(t.get('summary'))} · {t.get('status') or '?'}" + (f" · {t['assignee']}" if who and t.get("assignee") else "")


def service_move(v):
    return f"{v['from']} → {v['to']}" if v.get("from") else f"→ {v['to']}"


def job_number(runtime, job, version):
    """The Jenkins number of a job's newest successful build of `version`, from the fact store's builds
    (<runtime>/facts/builds/<job>.json); None when the store does not hold it."""
    try:
        rows = json.load(open(os.path.join(runtime or "", "facts", "builds", f"{job}.json"), encoding="utf-8")).get("builds") or []
    except (OSError, ValueError, AttributeError):
        return None
    want = str(version or "").lstrip("v")
    hits = [r["number"] for r in rows if str(r.get("version") or "").lstrip("v") == want and r.get("result") == "SUCCESS" and r.get("number")]
    return max(hits) if hits else None


def helm_compare(rec, runtime, helm):
    """{service: Helm's compare view from the job's build of `from` to its build of `to`}; a service whose job or
    either build number is unknown has none. `helm` is the site's Helm URL (site.json helm_local_url)."""
    if not helm:
        return {}
    jobs = {slug: job for job, slug in (rmap("jobs") or {}).items()}
    out = {}
    for v in rec.get("services") or []:
        job = jobs.get(reconcile_mod().slug_of(v.get("service")) or "")
        a, b = (job_number(runtime, job, v.get("from")), job_number(runtime, job, v.get("to"))) if job and v.get("from") else (None, None)
        if a and b and a != b:
            out[v["service"]] = f"{helm.rstrip('/')}/builds/compare?from={job}-{a}&to={job}-{b}"
    return out


def build_note(rec, reading=None, tickets=None, compare=None):
    """The release note's body: the title, where it came from, then per service its section — the version move and
    what for, then one line per ticket it carries (key, title, status, assignee) — then the record's notes and the
    Jira gaps `ela release reconcile` last read (nothing when there is none). `tickets`: {key: ticket_facts};
    `compare`: {service: Helm's compare link}, put at the end of the service's line. Keys
    are left bare for the vault's linker; a key never stands alone."""
    tickets = tickets or {}
    L = [f"# {build_title(rec)}", ""]
    L.append(f"*{rec.get('lane_name') or rec['lane']}, {rec['date']}." + (f" Source: {rec['source']}." if rec.get("source") else "") + "*")
    for v in rec["services"]:
        link = (compare or {}).get(v["service"])
        L += ["", f"## {v['service']}", "", f"{service_move(v)} · {' '.join(str(v['for']).split())}" + (f" · [compare]({link})" if link else "")]
        keys = v.get("keys") or []
        if keys:
            L += [""] + [f"- {ticket_line(k, tickets.get(k))}" for k in keys]
    if rec.get("notes"):
        L += ["", "## Notes", "", " ".join(str(rec["notes"]).split())]
    gaps = reconcile_mod().gaps_table(reading) if reading else ""
    if gaps:
        L += ["", gaps.rstrip("\n")]
    return "\n".join(L) + "\n"


def reconcile_mod():
    sys.modules.setdefault("release", sys.modules[__name__])   # run as a script, the module reconcile imports is this one
    import reconcile                                           # noqa: E402 — a build against Jira and its release thread
    return reconcile


def lane_builds(reports, lane, builds=None):
    """The lane's build records, newest first; `builds` narrows to those numbers."""
    want = lane_slug(lane or "")
    recs = [r for r in build_records(reports) if not want or want in (lane_slug(r["lane"]), lane_slug(r.get("lane_name")))]
    return [r for r in recs if str(r["build"]) in {str(b) for b in builds}] if builds else recs


def cmd_reconcile(a):
    """A lane's build against Jira: what each ticket it carries lacks (Fixed In, the label, the status and assignee the
    release thread announced), and the folds that are open questions. Read-only; the reading is kept beside the record
    for the release note. `--batch` runs the Fixed In appends and labels through the jira verbs, dry run unless --apply."""
    RC = reconcile_mod()
    s = site()
    reports = s.get("reports") or os.path.join(s.get("projects", ""), "reports")
    recs = lane_builds(reports, a.lane, a.build)
    if not a.build:
        recs = recs[:1]
    if not recs:
        print(f"no build record for {a.lane}" + (f" build {', '.join(a.build)}" if a.build else "") + " under <reports>/releases/", file=sys.stderr)
        sys.exit(EX_NOTFOUND)
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    a.env_file = a.env_file or s.get("env")                    # jira and slack read their tokens from the site's env file
    results = []
    for rec in sorted(recs, key=lambda r: (r["date"], r["name"])):
        msgs = RC.read_thread(rec, a.env_file)
        reading = RC.thread_reading(msgs, RC.record_keys(rec)) if msgs is not None else None
        keys = RC.record_keys(rec) + [f["key"] for f in (reading or {}).get("folds") or []]
        res = dict(RC.reconcile(rec, RC.read_issues(keys, a.env_file), reading), at=now)
        results.append(res)
        if not a.no_save:
            p = RC.reading_path(reports, res)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p + ".tmp", "w", encoding="utf-8") as fh:
                fh.write(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
            os.replace(p + ".tmp", p)
    raised = []
    if not a.no_save:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "vault"))
        import questions as Q                                  # noqa: E402 — ADR 0016's records

        def write(path, text):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + ".tmp", "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(path + ".tmp", path)
        state = Q.load(reports)
        raised = RC.raise_questions(state, results, RC.saved_readings(reports, a.lane), datetime.date.today(), now,
                                    drafts_dir=os.path.join(reports, "ela", "drafts"), write=write)
        if raised:
            Q.save(reports, state, write)
    if a.batch and a.apply and os.environ.get("ELA_NO_APPLY"):
        print("reconcile: an unattended session dry-runs the batch; --apply is the owner's word", file=sys.stderr); sys.exit(EX_USAGE)
    if a.batch:
        os.environ.setdefault("ELA_ACTION", f"reconcile {a.lane} build " + ",".join(str(r.get("build")) for r in results))
        ran = RC.run_batch(results, apply=a.apply, env_file=a.env_file)
        if a.json:
            print(json.dumps([{"key": k, "rc": rc, "out": t} for k, rc, t in ran], ensure_ascii=False)); return
        if not ran:
            print("nothing to write: every ticket has its Fixed In and label"); return
        print(("APPLIED" if a.apply else "DRY RUN") + f" — {RC.ask_text(results) or ''} Append-only; status, assignee and folds are not in the batch.")
        for k, rc, t in ran:
            print("\n".join("  " + l for l in t.splitlines()) if rc == 0 else f"  {k}: failed: {t[:200]}")
        if not a.apply:
            print("pass --apply to write")
        else:
            print(f"undo: `ela dry undo {RC.batch_id(results)}` (a dry run until --apply; one write: …#N)")
        sys.exit(0 if all(rc == 0 for _, rc, _ in ran) else EX_REMOTE)
    if a.json:
        cmd = f"ela release reconcile {a.lane} " + " ".join(f"--build {r['build']}" for r in results) + " --batch"
        print(json.dumps({"results": results, "ask": RC.ask_text(results), "command": cmd if RC.ask_text(results) else None,
                          "options": RC.ask_options("N", cmd) if RC.ask_text(results) else None, "raised": raised},
                         ensure_ascii=False)); return
    for res in results:
        print(f"{res.get('lane_name') or res['lane']} build {res['build']} ({res['line']}, {res['date']}): "
              f"{len(res['rows'])} ticket{'s' if len(res['rows']) != 1 else ''} with a gap, {len(res['ok'])} in order")
        for r in res["rows"]:
            print(f"  {r['key']}  {r['status'] or '?'} · {r['assignee'] or 'unassigned'} · {(r['agent'] or 'no agent named') + ('' if r.get('asked', True) else ', not asked')}")
            for m in r["misses"]:
                print(f"    {m['what']}" + (f" → {m['entry']}" if m.get("entry") else ""))
        for q in res["questions"]:
            print(f"  open question to {q.get('holder') or 'its holder'}: {q['text']}")
        for g in res["gaps"]:
            print(f"  not judged: {g}")
    ask = RC.ask_text(results)
    if ask:
        print(f"ask: {ask} (`ela release reconcile {a.lane} " + " ".join(f"--build {r['build']}" for r in results) + " --batch`)")
    if raised:
        print(f"raised {len(raised)} open question{'s' if len(raised) != 1 else ''} ({', '.join(raised)})")


def cmd_changes(a):
    """What a lane's newest build changed, by service and purpose, from its record; `--check FILE` validates a record
    before the morning session leaves it."""
    if a.check:
        try:
            rec = json.load(open(a.check, encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"cannot read {a.check}: {e}", file=sys.stderr); sys.exit(EX_USAGE)
        probs = build_check(rec, os.path.basename(a.check))
        print("\n".join(probs) if probs else f"ok: {build_name(rec)}")
        sys.exit(1 if probs else 0)
    s = site()
    reports = s.get("reports") or os.path.join(s.get("projects", ""), "reports")
    want = lane_slug(a.lane or "")
    recs = [r for r in build_records(reports) if not want or want in (lane_slug(r["lane"]), lane_slug(r.get("lane_name")))]
    if a.json:
        print(json.dumps(recs[:1] if a.lane else recs, ensure_ascii=False)); return
    if not recs:
        print(f"no build record for {a.lane or 'any lane'} under <reports>/releases/"); sys.exit(1)
    for r in recs[:1] if a.lane else recs:
        print(f"{r.get('lane_name') or r['lane']} took build {r['build']} ({r['line']}, {r['date']}):")
        if not a.tickets:
            print("\n".join("  " + l for l in build_lines(r)))
            continue
        facts = facts_tickets(s.get("runtime"), [k for v in r["services"] for k in v.get("keys") or []])
        for v in r["services"]:                            # per service its move and purpose, then one line per ticket
            print(f"  {v['service']} {service_move(v)}: {' '.join(str(v['for']).split())}")
            print("\n".join(f"    {ticket_line(k, facts.get(k))}" for k in v.get("keys") or []))


def cmd_line(a):
    """The line page (line.py), printed: what the vault writes as releases/<line>/<line>.md."""
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    import line as LP                                          # noqa: E402
    s = site()
    reports = s.get("reports") or os.path.join(s.get("projects", ""), "reports")
    d = LP.gather(a.line, reports, s.get("runtime"))
    if a.json:
        print(json.dumps(dict(d, builds=[{"build": b["rec"]["build"], "date": b["rec"]["date"], "qa": b["qa"]} for b in d["builds"]]),
                         ensure_ascii=False, indent=1, default=str)); return
    print(LP.render(d), end="")


def main():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "configserver"))
    import redact; redact.guard_output()  # a credential inside a remote payload never reaches the terminal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description="Release facts, first-hand.")
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    HOST_HELP = ("prod (the person's TVU session; ela login tvu), cn (the China region's host, account login) "
                 "or dev (MH dev + UR dev2; the person's dev session, ela login tvu --host dev)")
    def host_arg(p): p.add_argument("--host", choices=READ_HOSTS, default="prod", help=HOST_HELP + "; the QA host is not read")
    def hosts_arg(p): p.add_argument("--host", choices=HOSTS, help=HOST_HELP + "; without it every host is read and each row says which")
    RAW_HELP = "one host's answer as it is, names quoted as read, nothing mapped; needs --host (the first read of the China host)"
    p = sub.add_parser("bundles"); p.add_argument("line", nargs="?", help=f"a name prefix; default {DEFAULT_LINE} (.com) and the map's regions.china.userservice.bundle_line (cn)"); p.add_argument("--limit", type=int, default=50); hosts_arg(p); p.add_argument("--fresh", action="store_true", help="read the host now instead of the store"); p.add_argument("--raw", action="store_true", help=RAW_HELP); p.add_argument("--json", action="store_true")
    p = sub.add_parser("bundle"); p.add_argument("ref", help="bundle name (mh2.1@daily-wed-s1-d33) or id"); host_arg(p); p.add_argument("--json", action="store_true"); p.add_argument("--raw", action="store_true")
    p = sub.add_parser("bundle-diff", help="docker services added, removed and changed between two bundles")
    p.add_argument("a", help="bundle A: exact name, id, or a prefix (mh2.0@rc-s5, or '2.0 rc-s5') — the newest match wins")
    p.add_argument("b", help="bundle B, resolved the same way")
    for side in ("a", "b"): p.add_argument(f"--host-{side}", choices=READ_HOSTS, default="prod", help=f"host bundle {side.upper()} is read from (default prod)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("envs"); p.add_argument("service", nargs="?"); hosts_arg(p); p.add_argument("--fresh", action="store_true", help="read the host now instead of the store"); p.add_argument("--raw", action="store_true", help=RAW_HELP + ": its service list, or with a service its tag records"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("gateway", help="versions userservice does not publish (orchestration), read per lane through the API gateways; no login")
    p.add_argument("service", nargs="?"); p.add_argument("--lane", help="one lane (daily-wed, prod-3)"); p.add_argument("--fresh", action="store_true", help="read the gateways now instead of the store"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("create", help="a new bundle on prod from a base bundle, services changed one by one; dry run unless --apply; never deletes")
    p.add_argument("name", nargs="?", help="the new bundle's name; default the base's next (d45 → d46, MediaHub 2.1.15 → 2.1.16)")
    p.add_argument("--from", dest="base", required=True, help="the base bundle: name, id or prefix")
    p.add_argument("--set", action="append", help="'<GM name or slug>=<tag name or version>', repeatable; must match exactly one tag")
    p.add_argument("--drop", action="append", help="a service the new bundle leaves out (GM name or slug), repeatable")
    p.add_argument("--note", help="why this bundle exists; written before the change list in its description")
    p.add_argument("--apply", action="store_true"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("pin", help="hold a line's prod bundle on an older official, with why; dry run unless --apply (ADR 0013)"); p.add_argument("line"); p.add_argument("bundle", help="name (MediaHub 2.1.15), number (2.1.15) or id"); p.add_argument("--why", required=True, help="why prod stays on this bundle"); p.add_argument("--apply", action="store_true")
    p = sub.add_parser("unpin", help="lift a line's hold: prod follows the newest official again; dry run unless --apply"); p.add_argument("line"); p.add_argument("--apply", action="store_true")
    p = sub.add_parser("pins", help="the official bundle per line, as pinned"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("builds"); p.add_argument("job"); p.add_argument("--limit", type=int, default=15); p.add_argument("--fresh", action="store_true", help="read Jenkins now instead of the store"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("drift"); p.add_argument("line", nargs="?", default=DEFAULT_LINE); p.add_argument("--bundles", type=int, default=5, help="newest N bundles to union (default 5)"); host_arg(p); p.add_argument("--json", action="store_true")
    p = sub.add_parser("changes", help="what a lane's newest build changed, one line per service and what for, from its record")
    p.add_argument("lane", nargs="?", help="qa-cn3 or QA-AWS3; every record when omitted"); p.add_argument("--check", metavar="FILE", help="validate a build record")
    p.add_argument("--tickets", action="store_true", help="one line per ticket under each service: key, title, status, assignee (the fact store)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("reconcile", help="a lane's build against Jira: Fixed In, the release label, the status and assignee the thread announced; read-only, --batch writes the appends on --apply")
    p.add_argument("lane", help="qa-cn3 or QA-AWS3"); p.add_argument("--build", action="append", help="a build number, repeatable; default the newest")
    p.add_argument("--batch", action="store_true", help="the Fixed In appends and labels through the jira verbs; dry run unless --apply")
    p.add_argument("--apply", action="store_true"); p.add_argument("--no-save", action="store_true", help="keep no reading and raise no question")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("sync-dev", help="dev's docker images against daily and prod (or named bundles): the dry run of a sync and what dev runs ahead; read-only")
    p.add_argument("sources", nargs="*", help="daily | prod | a bundle name, prefix or id; the first is the target; default: daily prod")
    p.add_argument("--line", default="2.1", help="release line for daily and prod (default 2.1)"); p.add_argument("--host", choices=HOSTS, default="prod", help="host the sources are read from")
    p.add_argument("--ahead", action="store_true", help="only the services where dev runs above every source"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("line", help="one release line as one page: lanes, next promotion, docker differences, builds, history (local files only)")
    p.add_argument("line"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("login"); p.add_argument("target", nargs="?", choices=("qa", "tvu", "cn"), default="tvu"); p.add_argument("--force", action="store_true"); p.add_argument("--no-browser", action="store_true"); p.add_argument("--timeout", type=int, default=300); p.add_argument("--json", action="store_true")
    p.add_argument("--keepalive", action="store_true", help="tvu: one validation call that renews the session's idle TTL; never logs in, never retries")
    p.add_argument("--as", dest="as_", choices=("test",), help="tvu: sign in the second account product tests act as (session `tvu-test`, ela browser --as test); opens Chrome on ela's own profile")
    p.add_argument("--browser", choices=("chrome",), help="open the sign-in page in Google Chrome instead of the default browser")
    p.add_argument("--host", choices=("prod", "dev"), default="prod", help="tvu: dev signs the owner in on dev (session `tvu-dev`, kept apart from prod's `tvu-com`); opens Chrome on ela's own profile")
    a = ap.parse_args()
    # An unattended session (ELA_NO_APPLY) reads and dry-runs: a bundle create, a pin or a reconcile batch writes to GM
    # or commits to elak, and runs on the owner's word through the runner's `apply N`, never from a session.
    if getattr(a, "apply", False) and os.environ.get("ELA_NO_APPLY"):
        print(f"refused: {a.cmd} --apply inside an unattended session (ELA_NO_APPLY); the dry run is the answer, the owner's word applies it",
              file=sys.stderr)
        sys.exit(2)
    {"bundles": cmd_bundles, "bundle": cmd_bundle, "bundle-diff": cmd_bundle_diff, "envs": cmd_envs, "gateway": cmd_gateway, "builds": cmd_builds, "drift": cmd_drift, "login": cmd_login, "pin": cmd_pin, "unpin": cmd_unpin, "pins": cmd_pins,
     "create": cmd_create, "sync-dev": cmd_sync_dev, "changes": cmd_changes, "reconcile": cmd_reconcile, "line": cmd_line}[a.cmd](a)


if __name__ == "__main__":
    main()
