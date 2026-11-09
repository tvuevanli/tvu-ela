#!/usr/bin/env python3
"""Lane runtime facts offline: a profile chain layers later-wins with each shadowed value kept; a graph proven to be
created by ur-caller[wed] and bridged by the test gateway yields default → mx_service_test → mx_service_wed; a
prod-gateway graph adds no earlier layer; a gateway that fits two profiles is refused, never guessed.
Fixtures from the 2026-11-09 daily-wed → prod-3 promotion, where reading mx_service_wed alone was wrong."""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["ELA_FACTS_RUNTIME"] = tempfile.mkdtemp(prefix="ela-runtime-")
sys.path.insert(0, os.path.join(ROOT, "skills", "facts"))
sys.path.insert(0, os.path.join(ROOT, "skills", "configserver"))
import runtime as RT  # noqa: E402
import configserver as C  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

# ── configserver: the chain ────────────────────────────────────────────────────────────────────────
check("a+b is default, a, b", C.profile_chain("mx_service_wed+mx_service_test") == ["default", "mx_service_wed", "mx_service_test"])
check("default is never repeated", C.profile_chain("default,mx_service_prod3") == ["default", "mx_service_prod3"])
rows = {"default": [{"key": "mediaBox.viaGateway", "value": "false", "status": 1}],
        "mx_service_test": [{"key": "mediaBox.viaGateway", "value": "true", "status": 1}, {"key": "elk.config.env", "value": "test", "status": 1}],
        "mx_service_wed": [{"key": "elk.config.env", "value": "wed", "status": 1}]}
m = C.layer_chain(rows, ["default", "mx_service_test", "mx_service_wed"])
check("the later profile wins", m["elk.config.env"]["value"] == "wed" and m["elk.config.env"]["_layer"] == "mx_service_wed")
check("a shadowed value is kept with its layer", m["elk.config.env"]["_shadowed"] == [{"layer": "mx_service_test", "value": "test"}])
check("a key only an earlier lane profile sets survives", m["mediaBox.viaGateway"]["value"] == "true")

# ── runtime: a proof becomes a chain ───────────────────────────────────────────────────────────────
ENVS = {"default": {"env": "prod"}, "mx_service_wed": {"env": "wed"}, "mx_service_test": {"env": "test"},
        "mx_service_prod3": {"env": "prod3"}, "mx_service_mon": {"env": "mon"}}
ITEMS = {"default": {"mqtt.gatewayBoxPath": "/mqtt-gateway"}, "mx_service_wed": {"elk.config.env": "wed"},
         "mx_service_test": {"mqtt.gatewayBoxPath": "/mqtt-gateway-test"}, "mx_service_prod3": {}, "mx_service_mon": {}}
RT.profile_envs = lambda app, env_file: (ENVS, "")
RT.items = lambda app, prof, env_file: ITEMS.get(prof, {})
RT.gateway_tokens = lambda: {"daily-wed": "wed", "prod-3": "prod3", "daily-mon": "mon"}
RT.config_apps = lambda d: ["command-center-plus", "mx-service"]
RT.repo_dir = lambda r: "/x"

lane, chain, why = RT.chain_from_proof({"caller": {"env": "wed"}, "gateway": {"env": "mqtt_gateway_test1"}}, None)
check("ur-caller[wed] over the test gateway is daily-wed", lane == "daily-wed")
check("its chain is default → mx_service_test → mx_service_wed", chain == ["default", "mx_service_test", "mx_service_wed"])
lane, chain, why = RT.chain_from_proof({"caller": {"env": "prod3"}, "gateway": {"env": "mqtt_gateway_prod1"}}, None)
check("a prod-gateway graph on prod-3 adds no earlier layer", lane == "prod-3" and chain == ["default", "mx_service_prod3"])
lane, chain, why = RT.chain_from_proof({"caller": None}, None)
check("no creator line, no chain", chain is None and "no UR Caller" in why)
ITEMS["mx_service_mon"] = {"mqtt.gatewayBoxPath": "/mqtt-gateway-test"}
lane, chain, why = RT.chain_from_proof({"caller": {"env": "wed"}, "gateway": {"env": "mqtt_gateway_test1"}}, None)
check("a gateway that fits two profiles is refused, not guessed", chain is None and "several profiles" in why)
check("the lane profile is the one whose elk.config.env is the token", RT.lane_profile(ENVS, "prod3", "mx-service") == "mx_service_prod3")

# ── initConfig: only non-secret shapes are kept ───────────────────────────────────────────────────
import json  # noqa: E402
f = os.path.join(os.environ["ELA_FACTS_RUNTIME"], "ic.json")
json.dump({"result": {"htmlBaseOnMqtt": False, "mqttGatewayPath": "/mqtt-gateway-test", "mqttToken": "abc", "gatewayUrl": "https://h.example/x"}}, open(f, "w"))
class A: lane = "daily-wed"; file = f; json = False
RT.cmd_initconfig(A())
kept = RT.read_json(RT.store("initconfig-daily-wed.json"))["keys"]
check("a boolean and a path are kept", kept["htmlBaseOnMqtt"] is False and kept["mqttGatewayPath"] == "/mqtt-gateway-test")
check("a token-named key keeps its shape only; a URL keeps its path, never its host", kept["mqttToken"] == "<str>" and kept["gatewayUrl"] == "<host>/x")

if failures:
    print(f"runtime chain: {len(failures)} failure(s)"); sys.exit(1)
print("runtime chain: all offline checks passed")
