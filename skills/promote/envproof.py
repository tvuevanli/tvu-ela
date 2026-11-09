#!/usr/bin/env python3
"""The environment proof, as a gate on test evidence: a test counts for a lane only when the lane is proven.

  envproof.py text <file|-> --lane L [--versions JSON] [--json]   a version-panel block (a QA comment's 验证环境,
                                                                   a pasted panel): which lane, which versions
  envproof.py graph <graph id> --lane L [--json]                  a graph: the UR Caller instance that created it

The verify skill's rule, reused (its parser, `browser.parse_panel`, and the fact store's `runtime prove`): the API
gateway routes by the account, so a test "on Wed" proves Wed only when the version panel names Wed's ENV, or when
the graph the test made was created by Wed's UR Caller (its trace in the java-log) — on 2026-11-09 a volume test
"on Wed" ran through prod-3's UR Caller (graph env prod3). Verdicts:

  proven        the evidence names the claimed lane
  same-build    another lane, every version it lists equal to the claimed lane's: build evidence, said as
                "on <lane> at <build>", never as "on <claimed lane>"
  other-lane    another lane at other versions: does not count for the claimed lane
  unproven      no panel ENV, no graph creator: does not count

Exit codes: 0 proven or same-build · 3 other-lane · 4 unproven · 2 usage.
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.dirname(HERE)
for d in ("browser", "facts", "release"):
    sys.path.insert(0, os.path.join(SKILLS, d))

EX_USAGE, EX_OTHER, EX_UNPROVEN = 2, 3, 4
COUNTS = ("proven", "same-build")


def panel(text):
    """Panel text → {lane, lanes, host, versions: {slug: version}} or None when it names no ENV that maps to a lane.
    QA ENV names (aws-cn3-env) and gateway ENV names (Production3) live on different hosts; both are tried."""
    import browser as B  # noqa: E402
    best = None
    for host in ("qa", "prod"):
        try:
            r = B.parse_panel(text or "", host)
        except SystemExit:
            continue
        if r.get("lanes"):
            lane = max(r["lanes"], key=r["lanes"].get)
            vers = {s["slug"]: s["version"] for sec in r["sections"] for s in sec["services"]}
            cand = {"lane": lane, "lanes": r["lanes"], "host": host, "versions": vers,
                    "envs": sorted({sec["env"] for sec in r["sections"] if sec.get("env")})}
            if not best or sum(r["lanes"].values()) > sum(best["lanes"].values()):
                best = cand
    return best


def same_version(a, b):
    import release as R  # noqa: E402
    pa, pb = R.parse_version(str(a or "")), R.parse_version(str(b or ""))
    if pa and pb:
        return pa == pb
    return str(a or "").strip() == str(b or "").strip()


def judge(claim_lane, proof, lane_versions=None):
    """proof = panel() or graph() result. lane_versions = {slug: version} the claimed lane runs."""
    if not proof or not proof.get("lane"):
        return {"verdict": "unproven", "counts": False, "why": (proof or {}).get("why") or "no ENV or graph creator names a lane"}
    if proof["lane"] == claim_lane:
        return {"verdict": "proven", "counts": True, "lane": claim_lane, "why": f"the evidence names {claim_lane}"}
    vers = proof.get("versions") or {}
    shared = [s for s in vers if s in (lane_versions or {})]
    if shared and all(same_version(vers[s], lane_versions[s]) for s in shared):
        return {"verdict": "same-build", "counts": True, "lane": proof["lane"],
                "why": f"observed on {proof['lane']} at the versions {claim_lane} runs ({', '.join(sorted(shared))}); "
                       f"build evidence, not {claim_lane} evidence"}
    diff = [f"{s} {vers[s]} vs {lane_versions[s]}" for s in shared if not same_version(vers[s], lane_versions[s])]
    return {"verdict": "other-lane", "counts": False, "lane": proof["lane"],
            "why": f"observed on {proof['lane']}" + (f"; differs: {'; '.join(diff)}" if diff else
                                                     "; no version in common with the claimed lane to compare")}


def graph(graph_id, env_file):
    import runtime as RT  # noqa: E402
    p = RT.prove(graph_id, env_file)
    if p.get("error"):
        return {"lane": None, "why": p["error"], "graph": graph_id}
    lane, chain, why = RT.chain_from_proof(p, env_file)
    c = p.get("caller") or {}
    return {"lane": lane, "graph": graph_id, "graph_env": p.get("graph_env"), "creator": f"ur-caller[{c.get('env')}]" if c else None,
            "chain": chain, "why": why or None, "versions": {}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("text", help="a version-panel block: which lane, which versions")
    p.add_argument("file"); p.add_argument("--lane", required=True); p.add_argument("--versions", help='{"slug": "version"} the lane runs')
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("graph", help="a graph: the UR Caller instance that created it")
    p.add_argument("graph"); p.add_argument("--lane", required=True); p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    env_file = a.env_file or os.environ.get("ELA_ENV_FILE")
    if a.cmd == "text":
        text = sys.stdin.read() if a.file == "-" else open(a.file).read()
        proof = panel(text)
        verdict = judge(a.lane, proof, json.loads(a.versions) if a.versions else None)
    else:
        if not env_file:
            try:
                env_file = json.load(open(os.path.expanduser("~/.claude/ela/site.json"))).get("env")
            except (OSError, ValueError):
                pass
        proof = graph(a.graph, env_file)
        verdict = judge(a.lane, proof)
    out = {"claim_lane": a.lane, "proof": proof, **verdict}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(f"{verdict['verdict']}: {verdict['why']}")
    sys.exit(0 if verdict["counts"] else (EX_UNPROVEN if verdict["verdict"] == "unproven" else EX_OTHER))


if __name__ == "__main__":
    main()
