#!/usr/bin/env python3
"""configserver redacts a credential embedded inside a printable value — a query or fragment parameter, a header or
JSON pair, user:pass@ in a URL, a Bearer/Basic token, a JWT, an AWS or AppSync key — in place, in every record field
and so in every subcommand and output mode. Synthetic values only, built at run time so this file carries no
credential-shaped literal of its own (the content guard reads it). Pure functions; nothing is read or written."""
import json, os, random, string, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "configserver"))
import configserver as C  # noqa: E402 — the module under test

failures = []


def check(ok, label):
    print(("ok   " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


rnd = random.Random(7)
low = lambda n: "".join(rnd.choice(string.ascii_lowercase + string.digits) for _ in range(n))  # noqa: E731
mix = lambda n: "".join(rnd.choice(string.ascii_letters + string.digits) for _ in range(n))  # noqa: E731
APPSYNC = "da" + "2-" + low(26)
AWS = "AK" + "IA" + "".join(rnd.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567") for _ in range(16))
JWT = "ey" + "J" + mix(20) + "." + mix(30) + "." + mix(25)
TOK = mix(24)
HOST = "https://abc.example.invalid/graphql"

cases = [
    ("query x-api-key", f"{HOST}?x-api-key={APPSYNC}", APPSYNC),
    ("query api_key among others", f"{HOST}?region=us&api_key={TOK}&v=2", TOK),
    ("query key", f"{HOST}?key={TOK}", TOK),
    ("fragment access_token", f"{HOST}#access_token={TOK}", TOK),
    ("query sig", f"{HOST}?sig={TOK}", TOK),
    ("query signature", f"{HOST}?signature={TOK}", TOK),
    ("query password", f"{HOST}?password={TOK}", TOK),
    ("query secret", f"{HOST}?secret={TOK}", TOK),
    ("query access_key", f"{HOST}?access_key={TOK}", TOK),
    ("user:pass@ in a URL", f"https://svc:{TOK}@abc.example.invalid/x", TOK),
    ("Bearer token", f"Authorization: Bearer {TOK}", TOK),
    ("Basic token", f"Basic {TOK}", TOK),
    ("JWT shape", f"{HOST}?t={JWT}", JWT),
    ("AWS access key", f"aws {AWS}", AWS),
    ("bare AppSync key", f"{HOST} {APPSYNC}", APPSYNC),
    ("header map JSON", json.dumps({"url": HOST, "headers": {"x-api-key": APPSYNC}}), APPSYNC),
    ("properties pair", f"apiKey={TOK}", TOK),
]
for label, value, secret in cases:
    out = C.shown("zuul.routes.audiomixergraphql.urls", value)
    check(secret not in str(out), f"{label}: the credential is gone")
for label, value, secret in cases[:2]:
    out = C.shown("zuul.routes.audiomixergraphql.urls", value)
    check(out.startswith(HOST) and C.RED in out, f"{label}: the rest of the URL still reads, the key marked")

check(C.shown("zuul.routes.a.url", f"{HOST}?region=us") == f"{HOST}?region=us", "a plain URL prints as is")
check(C.shown("ob.enabled", "true") == "true", "a plain value prints as is")
check(C.shown("db.password", "x" * 5).startswith("<redacted:"), "a credential key name still withholds the whole value")

# every field of a record, so get / effective / search / history in text and --json alike
rec = {"key": "zuul.routes.audiomixergraphql.urls", "value": f"{HOST}?x-api-key={APPSYNC}",
       "pendingValue": f"{HOST}?x-api-key={APPSYNC}", "remark": f"rotated {HOST}?key={TOK}",
       "extra": f"{HOST}?token={TOK}", "id": 1, "status": 1}
safe = json.dumps(C.safe_item(rec))
check(APPSYNC not in safe and TOK not in safe, "safe_item leaves no embedded credential in any field")
check(C.safe_item(rec)["id"] == 1, "non-string fields pass through")

# the other read senses wrap their whole output: a print of a remote payload is scrubbed, a ticket key is kept
import subprocess  # noqa: E402
prog = ("import sys; sys.path.insert(0, sys.argv[1]); import redact; redact.guard_output(); "
        "print(sys.argv[2]); print(sys.argv[2], file=sys.stderr)")
payload = json.dumps({"key": "MH-1860", "url": f"{HOST}?x-api-key={APPSYNC}", "Authorization": f"Bearer {TOK}"})
r = subprocess.run([sys.executable, "-c", prog, os.path.join(ROOT, "skills", "configserver"), payload],
                   capture_output=True, text=True)
check(r.returncode == 0 and APPSYNC not in r.stdout + r.stderr and TOK not in r.stdout + r.stderr,
      "guard_output scrubs every print, stdout and stderr")
check('"key": "MH-1860"' in r.stdout, "guard_output keeps a JSON ticket key")
for sense in ("logs/logs", "graph/graph", "release/release", "object/object", "browser/browser", "sentry/sentry",
              "apifox/apifox"):
    src = open(os.path.join(ROOT, "skills", sense + ".py")).read()
    check("redact.guard_output()" in src.split("\ndef main():\n", 1)[-1][:400], f"{sense} guards its output")

sys.exit(1 if failures else 0)
