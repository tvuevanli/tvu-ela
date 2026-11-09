#!/usr/bin/env python3
"""promote livedeps, offline: a fixed-URL Feign edge resolved along the target lane's chain, the gateway route's
version-controlled instances read for /base/version, an instance older than a release commit flagged high, a key
absent from the chain falling to the code default (a dev URL on prod is high), and a refused config server named
as unread on every edge that needed it, never an empty result."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "promote"))
import livedeps as L  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

REPORT = {"to": "prod-3", "tickets": {"tickets": [{"key": "MH-3900", "exists": True}]},
          "delta": {"services": [{"service": "unified-streaming", "repo": "web/mx-service",
                                  "from_build": {"sha": "bbb"}, "to_build": {"sha": "aaa"}}]}}
MAP = {"services": {"audio-mx": {"repo": "web/audio-mixer"}},
       "edges": {"web/mx-service": {"feign": [
           {"to": "audio-mx", "client": "AudioMxClient", "file": "src/AudioMx.java", "pinned_url": "${audioMxUrl:https://gw.example/audio-mixer-dev}"},
           {"to": "tvucc-user", "client": "UserClient", "file": "src/User.java"}]}}}
ROUTES = {"audio-mixer": {"path": "/audio-mixer/**", "metadata": '{"versionControl": "1"}',
                          "urls": '{"prod1": {"url": "http://a1"}, "prod3": {"url": "http://a3"}}'}}
STATE = {"cs": "ok", "value": "https://gw.example/audio-mixer"}

def fake_l1(cap, *args, timeout=120, absent_ok=False):
    if cap == "facts":
        return {"lanes": {"prod-3": {"ur-caller": {"app": "mx-service", "chain": ["default", "mx_service_prod3"], "chain_status": "proven"}}}}
    if STATE["cs"] == "refused":
        L.UNREAD.setdefault(cap, "tvu session refused")
        return None
    if args[0] == "effective":
        return {"items": [{"key": "audioMxUrl", "value": STATE["value"], "layer": "mx_service_prod3"}]} if STATE["value"] else {}
    return {"items": [{"key": f"zuul.routes.audio-mixer.{k}", "value": v} for k, v in ROUTES["audio-mixer"].items()]}

def fake_run(argv, timeout=120):
    if "log" in argv and "--format=%s" in argv and "src/AudioMx.java" in argv:
        return 0, "MH-3900 audio mixer leg\n", ""
    if "log" in argv and "--format=%s" in argv:
        return 0, "", ""
    if "symbolic-ref" in argv:
        return 0, "origin/master\n", ""
    if "log" in argv:
        return 0, "c0ffee1\t2026-10-13\tMH-3900 gateway leg for mediabox mixer\nc0ffee2\t2026-10-20\trefactor\n", ""
    return 1, "", ""

L.l1, L.run = fake_l1, fake_run
L.dep_map = lambda: MAP
L.checkout = lambda repo: "/x/" + repo if repo else None
L.http_version = lambda url: (200, "audio-mixer 1.4.2 2026-10-08") if url.endswith("a3") else (502, "bad gateway")

deps = L.collect(REPORT)
fs = L.findings(deps, "prod-3")
d = deps[0]
check("the feature touching the client is named", d["features"] == ["MH-3900"])
check("the URL is read along the lane's chain, its layer kept", d["url_layer"] == "mx_service_prod3" and d["chain"] == ["default", "mx_service_prod3"])
check("a version-controlled route lists every instance", d["version_controlled"] and [i["instance"] for i in d["instances"]] == ["prod1", "prod3"])
check("an instance built before a release commit is high", any(s == "high" and "prod3" in w and "MH-3900" in w for s, w in fs))
check("an instance that does not answer is unread, not undeployed", any("prod1" in w and "unread, not undeployed" in w for s, w in fs))
check("a eureka edge with no feature is left out", all(x["to"] != "tvucc-user" for x in deps))

STATE["value"] = None
deps = L.collect(REPORT); fs = L.findings(deps, "prod-3")
check("a key absent from the chain falls to the code default", deps[0]["code_default"] == "https://gw.example/audio-mixer-dev")
check("a dev default on prod is high", any(s == "high" and "code default applies" in w for s, w in fs))

STATE["cs"] = "refused"
deps = L.collect(REPORT); fs = L.findings(deps, "prod-3")
check("a refused config server is unread on the edge", deps and "refused" in deps[0].get("unread", ""))
check("the unread source heads the findings", fs and fs[0][0] == "medium" and fs[0][1].startswith("configserver unread"))

print("promote livedeps: " + ("all offline checks passed" if not failures else f"{len(failures)} failed"))
sys.exit(1 if failures else 0)
