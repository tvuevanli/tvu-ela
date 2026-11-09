#!/usr/bin/env python3
"""TVU Config Server, read first-hand — the runtime configuration a service's decision depends on.
L1: subcommands, --json, stdlib only, read-only. A sense: it reports what the config server holds; whether a value
explains a failure is the calling skill's judgment.

  apps [--grep text]                        application names the person's account can see
  profiles <app>                            an application's profiles (environments)
  get <app> <profile|all> [--key text]… [--sort time|key] [--all-status]
                                            stored items: key, value, id, status, updateTime (newest first by default)
  effective <app> <profile> [--key text]…   what a client asking for (app, profile) receives: the profile's items over
                                            the app's `default`, profile wins per key; each value marked with its layer,
                                            (default) or (<profile>); enabled items only, like the server's own query
  search <text>                             items whose key or value contains the text, across every application
  history <app> <profile> <key>             the last versions of one item (the server keeps five), the current marked

Values are redacted, always: a key whose name carries a credential word (password, secret, token, cert, keystore,
clientId, …) or whose last segment ends in `key`,
a `{cipher}` value, or a value shaped like a credential (the backend's ApiKeyDetector rules, a URI with user:pass@,
a JWT, a long base64 or hex blob) prints as `<redacted: N chars, …>`. A credential embedded in an otherwise printable
value — a query or fragment parameter (key, api-key, x-api-key, token, secret, password, sig, signature, access_key),
a header or JSON pair under such a name, user:pass@ in a URL, a Bearer/Basic token, a JWT, an AWS or AppSync key — is
cut out in place as `<redacted>`, in every field of every record, so in every subcommand. `--json` redacts
identically. There is no flag to turn it off; a redacted value is read by the person in the web UI. False positives
are accepted.

Source quirks, verified 2026-09-30 against webteam/config-server-backend and the live server:
  - an expired or foreign SID answers HTTP 200 with errorCode -1 and the login URL as errorInfo; that is a refused
    session (exit 4), never data. Success is errorCode 0, an integer.
  - /op/profile/get answers HTTP 500 (errorCode 2002, a NullPointerException) when searchKey is absent; the script
    always sends it, empty when unused.
  - valueType is 0 string / 1 boolean, not a secrecy marker (model/ConfigPropertiesVersion.java:39).
  - the service-to-service paths (/config/{app}/{profile}, /api/get/…) are IP-whitelisted and refuse this machine;
    they are not called.
  - the layering in `effective` is Spring Cloud Config's documented composition, applied here to the stored items; it
    is not read back from the server.

Host and credential. CONFIGSERVER_BASE (default the config-server API under configservice.tvunetworks.com), and the
person's TVU session from `ela login tvu` (~/.claude/ela/session.json) as the SID cookie; a refusal is recorded on the
session like release.py records it and exits 4 naming the command. ELA_TVU_SID overrides the stored session for one
run (a refusal is then not recorded). Five GET paths are called — /op/application/getAll, /op/profile/get,
/op/key/get, /op/key/getApplication, /op/key/version; the server's write, cipher and plaintext-search endpoints are
not named in this script.
Exit codes: 0 ok · 2 usage · 3 nothing found (what was searched is printed) · 4 auth · 5 remote error.
"""
import argparse, datetime, json, os, re, signal, sys, urllib.error, urllib.parse, urllib.request

SKILLS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(SKILLS, "release"))
import release as R  # noqa: E402  — the person's TVU session: reader, refusal record, the login hint
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from redact import _B, _DETECTOR, RED, scrub  # noqa: E402,F401 — embedded credentials cut out in place

EX_USAGE, EX_NOTFOUND, EX_AUTH, EX_REMOTE = 2, 3, 4, 5
BASE_DEFAULT = "https://configservice.tvunetworks.com/config-server"
UTC = datetime.timezone.utc
DEFAULT_PROFILE = "default"


def die(msg, code):
    print(msg, file=sys.stderr); sys.exit(code)


# ── redaction ────────────────────────────────────────────────────────────────

# Credential words, matched inside each dot-separated segment of the key with `-` and `_` removed, so `api-key`,
# `api_key` and `apiKey` all read `apikey`. Substring on purpose: `renewToken` is redacted with `accessToken`.
KEY_WORDS = ("password", "passwd", "pwd", "secret", "token", "credential", "private", "accesskey", "apikey",
             "signature", "signkey", "cert", "jks", "keystore", "clientid")
# A key whose last segment *ends* in `key` names a key (`admin.key`, `appKey`, `authKey`); read live 2026-09-30, two
# such values carried credentials that no word above caught. The last segment only: `ob.subkey.*` are code lists.
KEY_SUFFIX = "key"

# The backend's own detector (util/ApiKeyDetector.java) and the in-place cut live in redact.py beside this file, shared
# with the other read senses; a value whose shape survives the cut is withheld whole.
VALUE_SHAPES = [(re.compile(f"(?<!{_B}){p}(?!{_B})"), "credential pattern") for p in _DETECTOR] + [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"[a-z][a-z0-9+.-]*://[^\s:\"',;{}/?#@]+:[^\s@\"',;{}/?#]+@", re.I), "URI with credentials"),
    (re.compile(r"AccountKey=|\"type\"\s*:\s*\"service_account\"|hooks\.slack\.com/services/"), "credential pattern"),
    (re.compile(r"(?:password|passwd|pwd|secret|token|accesskey|apikey)[\"']?\s*[=:]\s*[\"']?(?!<redacted>)"
                r"[^\s\"',;&}]{3,}", re.I),
     "credential assignment"),
    (re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{32,}(?![0-9A-Fa-f])"), "hex blob"),
    # upper, lower and digit all present: random base64 of this length always is; a word or a lowercase path is not
    (re.compile(r"(?<![A-Za-z0-9+/_-])(?=[A-Za-z0-9+/_-]*\d)(?=[A-Za-z0-9+/_-]*[a-z])(?=[A-Za-z0-9+/_-]*[A-Z])"
                r"[A-Za-z0-9+/_-]{32,}={0,2}"), "base64 blob"),
]


def key_is_secret(key):
    segs = re.sub(r"[-_]", "", str(key or "").lower()).split(".")
    return any(w in seg for seg in segs for w in KEY_WORDS) or segs[-1].endswith(KEY_SUFFIX)


def secret_reason(key, value):
    """Why a value is withheld, or None when it may be printed."""
    if key_is_secret(key):
        return "key name"
    v = str(value or "").strip()
    if v.lower().startswith("{cipher}"):
        return "{cipher}"
    for rx, why in VALUE_SHAPES:
        if rx.search(v):
            return why
    return None


def shape_of(value):
    v = str(value).strip()
    try:
        j = json.loads(v)
        if isinstance(j, (dict, list)):
            return "JSON"
    except ValueError:
        pass
    if "://" in v:
        return "URL"
    if "\n" in v:
        return "multi-line"
    return None


def shown(key, value):
    """The printable form of a value: the value with embedded credentials cut out, or — when the key names a
    credential, or something credential-shaped survives the cut — a label that says only its length and shape."""
    if value is None:
        return None
    why = "key name" if key_is_secret(key) else secret_reason("", scrub(value))
    if not why:
        return scrub(value)
    tags = [f"{len(str(value))} chars"] + [t for t in (shape_of(value),) if t] + [why]
    return f"<redacted: {', '.join(tags)}>"


def safe_item(it, key=None):
    """A reply record with every value-bearing field redacted; the only form a record leaves this script in."""
    k = key or it.get("key")
    out = {}
    for f, v in it.items():
        if f in ("value", "pendingValue"):
            out[f] = shown(k, v)
        elif f in ("remark", "pendingRemark") and v:
            out[f] = shown("", v)
        else:
            out[f] = scrub(v)
    return out


# ── transport ────────────────────────────────────────────────────────────────

class CS:
    """The config server's operator API, under the person's TVU session."""
    def __init__(self, env_file):
        self.base = (R.env_value("CONFIGSERVER_BASE", env_file) or BASE_DEFAULT).rstrip("/")
        self.override = os.environ.get("ELA_TVU_SID")
        if self.override:
            self.sid = self.override
            return
        s = R._load_sessions().get("tvu") or {}
        self.sid = s.get("sid") if not s.get("rejected_at") else None
        if not self.sid:
            R._need_login("tvu", "missing" if not s.get("sid") else f"refused at {s.get('rejected_at')}")

    def refused(self, why):
        if not self.override:
            R._mark_rejected("tvu")
        R._need_login("tvu", why)

    def call(self, path, params=None):
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers={"Accept": "application/json", "Cookie": f"SID={self.sid}"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                st, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            st, raw = e.code, e.read()
        except Exception as e:
            die(f"config server {path}: {str(e)[:200]}", EX_REMOTE)
        try:
            body = json.loads(raw)
        except ValueError:
            body = raw.decode("utf-8", "replace")[:300]
        if st in (401, 403):
            self.refused(f"refused by the config server (HTTP {st})")
        if not isinstance(body, dict):
            die(f"config server {path}: HTTP {st} {str(body)[:200]}", EX_REMOTE)
        if str(body.get("errorCode")) == "-1":
            self.refused("refused by the config server (errorCode -1, a login redirect)")
        if st != 200 or str(body.get("errorCode")) != "0":
            die(f"config server {path}: HTTP {st} errorCode {body.get('errorCode')} {str(body.get('errorInfo'))[:200]}",
                EX_REMOTE)
        return body.get("result")

    def items(self, app, profile, search="", label="master"):
        return self.call("/op/key/get", {"application": app, "profile": profile, "label": label,
                                         "searchKey": search or ""}) or []

    def profiles(self, app):
        return self.call("/op/profile/get", {"application": app, "searchKey": ""}) or []


# ── output ───────────────────────────────────────────────────────────────────

def when(v):
    try:
        return datetime.datetime.fromtimestamp(int(v) / 1000, UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    except (TypeError, ValueError):
        return "?"


def emit_json(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def key_filter(items, keys):
    """Items whose key contains every --key text (case-insensitive); an exact key match, when there is one, alone."""
    if not keys:
        return items
    ks = [k.lower() for k in keys]
    hit = [i for i in items if all(k in str(i.get("key", "")).lower() for k in ks)]
    exact = [i for i in hit if len(ks) == 1 and str(i.get("key", "")).lower() == ks[0]]
    return exact or hit


def one_line(v, width):
    s = "" if v is None else str(v).replace("\n", " ⏎ ")
    return s if width <= 0 or len(s) <= width else s[:width] + f" … ({len(s)} chars; -v for all)"


def need_app(cs, app):
    names = cs.call("/op/application/getAll", {"searchKey": app}) or []
    if app not in names:
        near = [n for n in names if app.lower() in n.lower()][:10]
        die(f"no application {app!r} visible to this account" + (f" — near: {', '.join(near)}" if near else ""),
            EX_NOTFOUND)


def need_profile(cs, app, profile):
    profs = cs.profiles(app)
    if profile not in profs:
        die(f"{app} has no profile {profile!r} — its profiles: {', '.join(profs) or '(none)'}", EX_NOTFOUND)
    return profs


# ── commands ─────────────────────────────────────────────────────────────────

def cmd_apps(a):
    names = CS(a.env_file).call("/op/application/getAll", {"searchKey": a.grep or ""}) or []
    if a.grep:
        names = [n for n in names if a.grep.lower() in n.lower()]
    names = sorted(names)
    if not names:
        die(f"no application matches {a.grep!r}", EX_NOTFOUND)
    if a.json:
        return emit_json({"grep": a.grep, "applications": names})
    print(f"{len(names)} application(s)" + (f" matching {a.grep!r}" if a.grep else ""))
    for n in names:
        print(f"  {n}")


def cmd_profiles(a):
    cs = CS(a.env_file)
    profs = cs.profiles(a.app)
    if not profs:
        need_app(cs, a.app)
        die(f"{a.app} has no profiles", EX_NOTFOUND)
    if a.json:
        return emit_json({"application": a.app, "profiles": profs})
    print(f"{a.app}: {len(profs)} profile(s) — a running service's profile is the `env` of its java-log lines")
    for p in profs:
        print(f"  {p}")


def print_items(rows, a, layer=False):
    for it in rows:
        mark = "" if it.get("status") == 1 else "  [disabled]"
        pend = "  [pending change]" if it.get("pendingStatus") not in (None, 0) or it.get("pendingValue") else ""
        lay = f"({it['_layer']})  " if layer else ""
        print(f"{it.get('key')} = {one_line(it.get('value'), 0 if a.verbose else a.width)}")
        print(f"      {lay}id {it.get('id')} · v{it.get('version')} · updated {when(it.get('updateTime'))}"
              f"{mark}{pend}" + (f" · remark {one_line(it.get('remark'), 120)}" if it.get("remark") else ""))


def cmd_get(a):
    cs = CS(a.env_file)
    profs = cs.profiles(a.app) if a.profile == "all" else [a.profile]
    if a.profile == "all" and not profs:
        need_app(cs, a.app)
    search = a.key[0] if a.key and len(a.key) == 1 else ""
    out = []
    for p in profs:
        rows = key_filter(cs.items(a.app, p, search), a.key)
        if not a.all_status:
            rows = [r for r in rows if r.get("status") == 1]
        rows = [safe_item(r) for r in rows]
        if a.sort == "key":
            rows.sort(key=lambda r: str(r.get("key")))
        out.append((p, rows))
    total = sum(len(r) for _, r in out)
    searched = f"{a.app} / {a.profile}" + (f" key ~ {' & '.join(a.key)}" if a.key else "")
    if not total:
        if a.profile != "all":
            need_profile(cs, a.app, a.profile)
        die(f"no items — searched {searched}" + ("" if a.all_status else " (enabled only; --all-status for disabled)"),
            EX_NOTFOUND)
    if a.json:
        return emit_json({"application": a.app, "searched": searched, "profiles": {p: r for p, r in out}})
    for p, rows in out:
        if not rows and a.profile == "all":
            continue
        print(f"── {a.app} / {p} · {len(rows)} item(s)")
        print_items(rows, a)


def profile_chain(spec):
    """`a+b` or `a,b` → [default, a, b]: the order a service lists its active profiles, the later one winning per key
    (Spring's rule for `spring.profiles.active=a,b`). `default` is always the base and never repeated."""
    chain = [p.strip() for p in re.split(r"[+,]", spec or "") if p.strip() and p.strip() != DEFAULT_PROFILE]
    return [DEFAULT_PROFILE] + list(dict.fromkeys(chain))


def layer_chain(rows_by_layer, chain):
    """Merge per-layer rows along the chain. Each key keeps the winning row, the layer it came from and every
    earlier layer's value it shadows — a key set in two lane profiles is where a one-profile read goes wrong."""
    merged = {}
    for p in chain:
        for r in rows_by_layer.get(p, []):
            k = r["key"]
            prev = merged.get(k)
            shadowed = (prev["_shadowed"] + [{"layer": prev["_layer"], "value": prev.get("value")}]) if prev else []
            merged[k] = {**safe_item(r), "_layer": p, "_shadowed": shadowed}
    return merged


def cmd_effective(a):
    cs = CS(a.env_file)
    search = a.key[0] if a.key and len(a.key) == 1 else ""
    layers = profile_chain("+".join([a.profile] + (a.chain or [])))
    got = {p: [r for r in key_filter(cs.items(a.app, p, search), a.key) if r.get("status") == 1] for p in layers}
    merged = layer_chain(got, layers)
    rows = sorted(merged.values(), key=lambda r: str(r.get("key")))
    chain_word = " over ".join(reversed(layers))
    searched = f"{a.app} / {chain_word}" + (f", key ~ {' & '.join(a.key)}" if a.key else "")
    if not rows:
        for p in layers[1:]:
            need_profile(cs, a.app, p)
        die(f"no enabled items — searched {searched}. Absent here, the code's own default applies", EX_NOTFOUND)
    per_layer = {p: sum(1 for r in rows if r["_layer"] == p) for p in layers}
    overrides = sorted(r["key"] for r in rows if r["_shadowed"])
    lane_conflicts = sorted(r["key"] for r in rows
                            if any(s["layer"] != DEFAULT_PROFILE for s in r["_shadowed"]) and r["_layer"] != DEFAULT_PROFILE)
    summary = {"keys": len(rows), "per_layer": per_layer, "from_profile": len(rows) - per_layer[DEFAULT_PROFILE],
               "from_default": per_layer[DEFAULT_PROFILE], "profile_overrides_default": len(overrides),
               "set_in_two_profiles": len(lane_conflicts)}
    if a.json:
        return emit_json({"application": a.app, "profile": a.profile, "chain": layers, "searched": searched,
                          "precedence": "later profile wins (Spring's rule for a comma-separated active list); "
                                        "the chain itself is the caller's claim, proven by runtime evidence",
                          "summary": summary, "overridden_keys": overrides, "set_in_two_profiles": lane_conflicts,
                          "items": [{**{k: v for k, v in r.items() if k not in ("_layer", "_shadowed")},
                                     "layer": r["_layer"], "shadows": r["_shadowed"]} for r in rows]})
    if len(layers) == 1:
        print(f"{a.app} / {DEFAULT_PROFILE} · {len(rows)} key(s), all from ({DEFAULT_PROFILE})")
    else:
        counts = ", ".join(f"{per_layer[p]} from ({p})" for p in reversed(layers))
        print(f"{a.app} / {chain_word} · {len(rows)} key(s): {counts}; {len(overrides)} key(s) override an earlier layer"
              + (f"; {len(lane_conflicts)} set in two lane profiles" if lane_conflicts else ""))
    for r in rows:
        over = ""
        if r["_shadowed"]:
            over = "  overrides " + ", ".join(f"({s['layer']}) = {one_line(s.get('value'), 40)}" for s in r["_shadowed"])
        print(f"({r['_layer']}) {r['key']} = {one_line(r.get('value'), 0 if a.verbose else a.width)}")
        print(f"      id {r.get('id')} · v{r.get('version')} · updated {when(r.get('updateTime'))}{over}")


def cmd_search(a):
    rows = CS(a.env_file).call("/op/key/getApplication", {"searchKey": a.text, "label": "master"}) or []
    rows = [safe_item(r) for r in rows]
    rows.sort(key=lambda r: (str(r.get("application")), str(r.get("profile")), str(r.get("key"))))
    if not rows:
        die(f"no item whose key or value contains {a.text!r}, in any application", EX_NOTFOUND)
    if a.json:
        return emit_json({"text": a.text, "items": rows})
    shown_rows = rows[:a.limit]
    print(f"{len(rows)} item(s) whose key or value contains {a.text!r}"
          + (f" (first {a.limit}; --limit)" if len(rows) > a.limit else ""))
    for r in shown_rows:
        off = "" if r.get("status") == 1 else "  [disabled]"
        print(f"{r.get('application')} / {r.get('profile')}  {r.get('key')} = "
              f"{one_line(r.get('value'), 0 if a.verbose else a.width)}{off}")


def cmd_history(a):
    cs = CS(a.env_file)
    rows = [r for r in cs.items(a.app, a.profile, a.key) if r.get("key") == a.key]
    if not rows:
        need_profile(cs, a.app, a.profile)
        die(f"no item {a.key!r} in {a.app} / {a.profile}", EX_NOTFOUND)
    it = rows[0]
    vers = cs.call("/op/key/version", {"id": it["id"]}) or []
    vers = [safe_item(v, key=a.key) for v in vers]
    if a.json:
        return emit_json({"application": a.app, "profile": a.profile, "key": a.key, "id": it["id"],
                          "item": safe_item(it), "versions": vers})
    print(f"{a.app} / {a.profile}  {a.key}  id {it['id']} · {len(vers)} version(s), newest first as the server orders them")
    if not vers:
        print("  (no version history returned — an invisible item's history is shown to admins only)")
    for v in vers:
        cur = "  ◀ current" if v.get("current") else ""
        rb = "  (rollback)" if v.get("isRollback") else ""
        print(f"  v{v.get('version')}  {when(v.get('createTime'))}  by {v.get('operator') or '?'}{cur}{rb}")
        print(f"      {one_line(v.get('value'), 0 if a.verbose else a.width)}")


def main():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    ap = argparse.ArgumentParser(description="TVU Config Server, first-hand and read-only; values redacted, always.")
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("-v", "--verbose", action="store_true", help="whole values, not cut at --width")
        p.add_argument("--width", type=int, default=200, help="characters of a value shown without -v")
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("apps", help="application names"); p.add_argument("--grep"); common(p)
    p = sub.add_parser("profiles", help="an application's profiles"); p.add_argument("app"); common(p)
    p = sub.add_parser("get", help="stored items of one profile, or of all")
    p.add_argument("app"); p.add_argument("profile", help="a profile name, or `all`")
    p.add_argument("--key", action="append", help="keep keys containing this text (repeatable; all must match)")
    p.add_argument("--sort", choices=("time", "key"), default="time")
    p.add_argument("--all-status", action="store_true", help="include disabled items"); common(p)
    p = sub.add_parser("effective", help="a profile chain over default, per key, each value marked with its layer")
    p.add_argument("app"); p.add_argument("profile", help="one profile, or a chain in the service's own order: mx_service_wed+mx_service_test (the later wins)")
    p.add_argument("--chain", action="append", help="another profile after PROFILE in the chain (repeatable), same as a+b")
    p.add_argument("--key", action="append", help="keep keys containing this text (repeatable; all must match)")
    common(p)
    p = sub.add_parser("search", help="items whose key or value contains a text, across applications")
    p.add_argument("text"); p.add_argument("--limit", type=int, default=200); common(p)
    p = sub.add_parser("history", help="the last versions of one item")
    p.add_argument("app"); p.add_argument("profile"); p.add_argument("key"); common(p)
    a = ap.parse_args()
    {"apps": cmd_apps, "profiles": cmd_profiles, "get": cmd_get, "effective": cmd_effective,
     "search": cmd_search, "history": cmd_history}[a.cmd](a)


if __name__ == "__main__":
    main()
