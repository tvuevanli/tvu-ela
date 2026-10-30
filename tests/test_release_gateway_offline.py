#!/usr/bin/env python3
"""The gateway reader, offline: recorded orchestration answers per lane parse into versions; a 503, a 404, a body no
version family fits and a host site.json lacks are each UNDETERMINED with the reason, never "not deployed"."""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "release"))
import release as R  # noqa: E402

REC = json.load(open(os.path.join(ROOT, "tests", "fixtures", "gateway-orchestration.json")))
HOSTS = {"gateway": "https://gw.invalid", "gateway-test": "https://gw-test.invalid", "gateway-qa": "https://gw-qa.invalid/"}
R.site = lambda: {"services": {k: {"url": v} for k, v in HOSTS.items()}}
lane = lambda key, tok: {"site_service": key, "token": tok}
R._MAP = {"gateway_versions": {"orchestration": {"path": "/orchestration-{token}/base/version", "lanes": {
    "daily-wed": lane("gateway-test", "wed"), "daily-mon": lane("gateway-test", "mon"), "prod-3": lane("gateway", "prod3"),
    "prod-4": lane("gateway", "prod4"), "prod-1": lane("gateway", "prod1"), "daily-stage": lane("gateway", "wed"),
    "qa-2": lane("gateway-qa", "qa2"), "prod-2-china": lane("gateway-china", "prod2")}}}}
asked = []

def get(url):
    asked.append(url)
    key = next(k for k, v in HOSTS.items() if url.startswith(v.rstrip("/") + "/"))
    tok = url.split("/orchestration-")[1].split("/")[0]
    return tuple(REC[key].get(tok, [404, ""]))

rows = {r["lane"]: r for r in R.gateway_versions(get=get)}
v = lambda ln: R.vlabel(R.parse_version(rows[ln]["version"])) if rows[ln]["version"] else None
checks = [
    ("daily-wed reads 4.0.206 build 79", v("daily-wed") == "4.0.206+79" and rows["daily-wed"]["status"] == "read"),
    ("a patch version keeps its fourth digit", v("daily-mon") == "4.0.172.1+65"),
    ("prod-3 reads 4.0.205 build 78", v("prod-3") == "4.0.205+78"),
    ("the underscore-dated build still parses", v("prod-4") == "4.0.73+109"),
    ("a 404 is undetermined, no route", rows["prod-1"]["status"] == "undetermined" and "no route" in rows["prod-1"]["why"]),
    ("a 503 is undetermined, route without instance", rows["daily-stage"]["status"] == "undetermined" and "503" in rows["daily-stage"]["why"]),
    ("a catch-all body is undetermined", rows["qa-2"]["status"] == "undetermined" and "default" in rows["qa-2"]["why"]),
    ("a host site.json lacks is undetermined, never called", rows["prod-2-china"]["why"] == "site.json services.gateway-china.url is not set"
        and not any("china" in u for u in asked)),
    ("every row names its source", all(r["source"] == "gateway" for r in rows.values())),
    ("the path is the map's, with the token", "https://gw.invalid/orchestration-prod3/base/version" in asked
        and "https://gw-qa.invalid/orchestration-qa2/base/version" in asked),
    ("one lane only when asked", [r["lane"] for r in R.gateway_versions(lane="prod-3", get=get)] == ["prod-3"]),
]
fail = 0
for name, ok in checks:
    print(("ok   " if ok else "FAIL ") + name); fail += not ok
sys.exit(1 if fail else 0)
