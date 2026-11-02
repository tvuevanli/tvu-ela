#!/usr/bin/env python3
"""graph.py's environment model, offline: China is a second edge with environments in the path (cn → cn2 → /prod2 on
the CN host), the default probe ends with cn2, UR_ENV_ORDER still replaces it, and `envs` lists it all without a request."""
import json, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "graph"))
import graph as G  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

CN, QA = "https://cn.example", "https://qa.example"
os.environ.update({"UR_ACCESS_KEY": "offline", "UR_CN_HOST": CN, "UR_QA_HOST": QA})
os.environ.pop("UR_ENV_ORDER", None); os.environ.pop("ELA_ENV_FILE", None); os.environ.pop("UR_BASE_HOST", None)
ur = G.UR(None, warm=False)

check("cn is an alias of cn2", G.normalise("cn") == "cn2" and G.normalise("china") == "cn2" and G.normalise("CN") == "cn2")
check("cn2 stays cn2", G.normalise("cn2") == "cn2")
check("cn2 routes to the CN host under /prod2, /any kept",
      ur.route("cn2", G.graph_path("01X")) == (CN, "/prod2/j2n/api/v1-beta1/graphs/01X/any"))
check("cn2 keeps v2 and Pilot under /prod2 too",
      ur.route("cn2", G.J2N2 + "/graphs")[1] == "/prod2/j2n/api/v2/graphs" and ur.route("cn2", G.PILOT + "/boxes")[1] == "/prod2/pilot/api/v1/boxes")
check("the .com edge carries the env name itself", ur.route("prod3", G.PILOT + "/boxes") == ("https://ur.tvunetworks.com", "/prod3/pilot/api/v1/boxes"))
check("qa2 is the QA host with the env in the path", ur.route("qa2", G.PILOT + "/boxes") == (QA, "/qa2/pilot/api/v1/boxes"))
check("the default probe is the .com edge first, cn2 last", ur.order == ["prod3", "prod2", "test2", "cn2"])
check("no QA env is probed by default", not any(G.QA_ENV.fullmatch(e) for e in ur.order))
check("the root of the CN host is not an env", "cn" not in ur.edges and all(seg for _, seg, _ in ur.edges.values()))

os.environ["UR_ENV_ORDER"] = "test2,prod3"
check("UR_ENV_ORDER replaces the whole order", G.UR(None, warm=False).order == ["test2", "prod3"])
del os.environ["UR_ENV_ORDER"]

script = os.path.join(ROOT, "skills", "graph", "graph.py")
def run(*args):
    return subprocess.run([sys.executable, script, *args], capture_output=True, text=True, env=os.environ)
r = run("envs")
check("envs exits 0 and names the order ending in cn2", r.returncode == 0 and "prod3" in r.stdout and r.stdout.index("test2") < r.stdout.index("cn2"))
check("envs shows cn2 as CN Prod2 under /prod2 on the CN host", f"{CN}/prod2/" in r.stdout and "CN Prod2" in r.stdout)
check("envs lists the aliases", "cn → cn2" in r.stdout and "china → cn2" in r.stdout and "p<N> → prod<N>" in r.stdout)
check("envs names QA as named-only", "qa<N>" in r.stdout and "never probed" in r.stdout and QA in r.stdout)
check("envs makes no request", "ur " not in r.stderr and "401" not in r.stderr)
r2 = run("graph", "envs")
check("`graph envs` is the envs listing, not a graph lookup", r2.returncode == 0 and r2.stdout == r.stdout)
j = json.loads(run("envs", "--json").stdout)
check("envs --json carries order, edges and aliases",
      j["order"][-1] == "cn2" and j["edges"]["cn2"] == {"host": CN, "path": "prod2", "label": "CN Prod2"} and j["aliases"]["cn"] == "cn2")

if failures:
    print(f"{len(failures)} failing"); sys.exit(1)
print("graph envs offline: all checks pass")
