#!/usr/bin/env python3
"""j2n offline: the read-only gate (GET on a closed list, POST on the sign-in only, refused before any connection), the
certificate pin, label short forms and filters, the compare view, the env table carrying no address, a 401 renewing
the token once, and the score service's version-conflict 500 retried. Synthetic fixtures (tests/fixtures/j2n); no
network, no site file, no credential."""
import io, json, os, sys, tempfile
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "j2n")
sys.path.insert(0, os.path.join(ROOT, "skills", "j2n"))
import j2n as J  # noqa: E402

failures = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


def fx(name):
    return json.load(open(os.path.join(FIX, name)))


def refused(method, path):
    try:
        J.gate(method, path)
        return False
    except J.Refused:
        return True


# ── the gate ────────────────────────────────────────────────────────────────────────────────────────
check("GET scores of an env passes", not refused("GET", "/ui/api/proxy/j2n/api/v1/prod3/config/scores/all"))
check("GET env list passes", not refused("GET", "/ui/api/config"))
check("GET own permissions passes", not refused("GET", "/ui/api/permissions/me"))
check("POST sign-in passes", not refused("POST", "/ui/api/auth/login"))
for m, p in [("POST", "/ui/api/proxy/j2n/api/v1/qa/config/scores/all"),
             ("PUT", "/ui/api/proxy/j2n/api/v1/qa/config/scores"),
             ("DELETE", "/ui/api/proxy/j2n/api/v1/qa/config/scores/all"),
             ("GET", "/ui/api/proxy/j2n/api/v1/qa/config/scores"),
             ("GET", "/ui/api/proxy/j2n/api/v1/../admin/config/scores/all"),
             ("GET", "/ui/api/proxy/j2n/api/v1/prod3/config/scores/all?x=1"),
             ("GET", "/ui/api/permissions"), ("GET", "/ui/api/audit"), ("GET", "/ui/api/export"),
             ("POST", "/ui/api/auth/logout"), ("GET", "/ui/api/auth/login")]:
    check(f"refused: {m} {p}", refused(m, p))

ui = J.UI(None, {"services": {"j2n-config-ui": {"url": "https://ui.example.invalid:1"}}, "runtime": tempfile.mkdtemp()})
ui.tls_called = False
orig_ctx = J.tls_context
J.tls_context = lambda: (_ for _ in ()).throw(AssertionError("connected"))
try:
    ui._send("PUT", "/ui/api/proxy/j2n/api/v1/qa/config/scores/all")
    check("a write is refused before any connection", False)
except J.Refused:
    check("a write is refused before any connection", True)
except AssertionError:
    check("a write is refused before any connection", False)
J.tls_context = orig_ctx

# ── the pin ─────────────────────────────────────────────────────────────────────────────────────────
import hashlib  # noqa: E402
der = b"synthetic-der-bytes"
fp = hashlib.sha256(der).hexdigest()
check("the pinned fingerprint matches", J.pin_ok(der, fp))
check("a fingerprint with colons and upper case matches", J.pin_ok(der, ":".join(fp[i:i + 2] for i in range(0, 64, 2)).upper()))
check("another certificate does not", not J.pin_ok(b"other", fp))
check("no fingerprint never matches", not J.pin_ok(der, ""))

# ── labels and filters ──────────────────────────────────────────────────────────────────────────────
check("short form of a prefixed key", J.short_key("encoder.app.tvunetworks.com/resolution") == "encoder/resolution")
check("short form of the subtype key", J.short_key("app.tvunetworks.com/subtype") == "subtype")
check("a bare key is itself", J.short_key("version") == "version")
a, b = fx("scores-prod3.json"), fx("scores-test2.json")
enc = [r for r in a if J.row_matches(r, "encoder")]
check("--subtype encoder keeps the three encoder rows", len(enc) == 3)
for spec in ("resolution=UHD", "encoder/resolution=uhd", "encoder.app.tvunetworks.com/resolution=UHD"):
    m = [r for r in a if J.row_matches(r, "encoder", J.parse_labels(spec))]
    check(f"--labels {spec} finds encoder UHD 1600", len(m) == 1 and m[0]["score"] == {"Cpu": 1600})
m = [r for r in a if J.row_matches(r, None, J.parse_labels("resolution=UHD,strategy=SpecifiedPoolOnly"))]
check("two labels must both hold", len(m) == 1 and m[0]["labels"]["app.tvunetworks.com/subtype"] == "headlessr_decoder")
try:
    J.parse_labels("resolution")
    check("a pair without = is a usage error", False)
except J.Fail as e:
    check("a pair without = is a usage error", e.code == J.EX_USAGE)
txt = J.render_rows("prod3", len(a), enc)
check("the table says total and shown", txt.startswith("prod3: 6 rows, 3 shown"))
check("the table shows the UHD row", "encoder/resolution=UHD" in txt and "Cpu 1600" in txt)
check("a multi-resource score reads in one cell", "Cpu 150 · QsvRender3D 12 · QsvVideo 5" in txt)

# ── the compare view ────────────────────────────────────────────────────────────────────────────────
d = J.diff(a, b)
check("rows only in prod3", [r["labels"]["app.tvunetworks.com/subtype"] for r in d["only_a"]] == ["MeshAdapterSender"])
check("rows only in test2", [r["labels"]["app.tvunetworks.com/subtype"] for r in d["only_b"]] == ["youtube_decoder"])
check("three rows differ", len(d["differ"]) == 3 and d["same"] == 2)
uhd = [x for x in d["differ"] if "encoder.app.tvunetworks.com/resolution" in x["labels"]][0]
check("encoder UHD differs 1600 → 500", uhd["a"] == {"Cpu": 1600} and uhd["b"] == {"Cpu": 500})
txt = J.render_diff("prod3", "test2", d)
check("the diff headline counts", txt.startswith("prod3 ↔ test2: 2 rows equal · 3 differ · 1 only in prod3 · 1 only in test2"))
check("identical sides say so", J.render_diff("x", "y", J.diff(a, a)).endswith("identical"))

# ── envs: no address leaves ─────────────────────────────────────────────────────────────────────────
rows = J.envs_table(fx("config.json"), fx("permissions-me.json")["access"])
check("envs carry name, category, production, access", rows[2] == {"env": "qa", "label": "qa", "category": "qa",
                                                                    "production": False, "access": "write"})
check("no server address in the env table", "example.invalid" not in json.dumps(rows))

# ── transport behaviour, faked: a 401 renews once; a version-conflict 500 is retried ────────────────
class Fake(J.UI):
    def __init__(self, replies):
        super().__init__(None, {"services": {"j2n-config-ui": {"url": "https://ui.example.invalid:1"}},
                                "runtime": tempfile.mkdtemp()})
        self.replies, self.sent, self.token = list(replies), [], "old"

    def _send(self, method, path, body=None, auth=True):
        J.gate(method, path)
        self.sent.append((method, path, self.token if auth else None))
        return self.replies.pop(0)

    def login(self):
        self.sent.append(("POST", "/ui/api/auth/login", None))
        self.token = "new"


J.time.sleep = lambda s: None
f = Fake([(401, b'{"error":"Unauthorized"}'), (200, json.dumps(a).encode())])
check("a 401 signs in once and retries with the new token", f.scores("prod3") == a and
      [s[0] for s in f.sent] == ["GET", "POST", "GET"] and f.sent[-1][2] == "new")
f = Fake([(401, b""), (401, b"")])
try:
    f.scores("prod3"); check("a second 401 is exit 4", False)
except J.Fail as e:
    check("a second 401 is exit 4", e.code == J.EX_AUTH)
conflict = (500, b'{"error":{"message":"Version conflict (WriteStateAsync): GrainId=readonlyscoresettings/prod3"}}')
f = Fake([conflict, (200, json.dumps(b).encode())])
check("a version-conflict 500 is retried", f.scores("prod3") == b and len(f.sent) == 2)
f = Fake([conflict, conflict, conflict])
try:
    f.scores("prod3"); check("three conflicts are exit 5", False)
except J.Fail as e:
    check("three conflicts are exit 5", e.code == J.EX_REMOTE and len(f.sent) == 3)
f = Fake([(500, b'{"error":"boom"}')])
try:
    f.scores("prod3"); check("another 500 is not retried", False)
except J.Fail as e:
    check("another 500 is not retried", e.code == J.EX_REMOTE and len(f.sent) == 1)
f = Fake([(404, b"")])
try:
    f.scores("qa"); check("a 404 is exit 3 naming the proxy", False)
except J.Fail as e:
    check("a 404 is exit 3 naming the proxy", e.code == J.EX_NOTFOUND and "proxy" in str(e))
try:
    Fake([]).scores("../x"); check("an env name outside the shape is a usage error", False)
except J.Fail as e:
    check("an env name outside the shape is a usage error", e.code == J.EX_USAGE)

# ── the token file ──────────────────────────────────────────────────────────────────────────────────
p = os.path.join(tempfile.mkdtemp(), "sub", "t.token")
J.write_token(p, "synthetic")
check("the token is written mode 600", oct(os.stat(p).st_mode & 0o777) == "0o600" and J.read_token(p) == "synthetic")

if failures:
    print(f"j2n offline: {len(failures)} failed"); sys.exit(1)
print("j2n offline: all passed")
