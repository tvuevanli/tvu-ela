#!/usr/bin/env python3
"""jira.py find, offline: the source ticket's vocabulary is its identifiers and endpoints (never its ids, hex,
versions or templated pieces), the keys it names exclude its own, and a caller's word outranks one source term."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "jira"))
import jira as J  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

# MH-3954's first and third comments, as read from Jira (2026-11-12), the box address removed
SOURCE = """结论(qa2,Object 1529119349384810496 / Pack-8CFC,box <box>)
两个 destination graph(SRT Listener 62299 / 62300)由 UrCaller 通过 J2N 同步接口 在约 2 秒内先后提交,同一 object 下起了两个 `headlessr_decoder`:
  - `51df0eba…`:graph 01M6R593KH(62299),10:08:16 创建,之后 preview graph 和 SDI graph 复用了它。
  - 10:08:15.786 `Lease not acquired, held by another owner`,资源 `tangible-claim:1529119349384810496:headlessr_decoder`,owner 形如 `sync:{graphId}:{guid}`。
J2N 的 object 锁(UR-512 tangible claim)的"等待并重试"只在异步接口 `POST /api/v2.0/graph-submissions` 实现。
  - MediaHub / UrCaller 创建 graph 改走 `graph-submissions` 异步接口,由 J2N 对 object id 加锁并串行化。
补充：qa2 的 MH-3934 <https://tvunetworks.atlassian.net/browse/MH-3934>（同一个源先后路由两个 destination）与本单 MH-3954 同一原因。
Slack 源链接： 查看原消息 <https://tvunetworks.slack.com/archives/C06553EE44X/p1793962203105579>
J2N 侧不改：只有 `/api/v2.0/graph-submissions` 异步接口会串行化。"""

terms = J.context_terms(SOURCE)
check("graph-submissions is a source term, and the most frequent", terms[:1] == ["graph-submissions"])
check("headlessr_decoder is a source term", "headlessr_decoder" in terms)
check("no object id", not any("1529119349384810496" in t for t in terms))
check("no templated piece of sync:{graphId}:{guid}", not any(x in t for t in terms for x in ("graphid", "guid", "{")))
check("no version", not any("v2.0" in t or t == "v2" for t in terms))
check("no hex-bearing name (Pack-8CFC)", "pack-8cfc" not in terms)
check("no issue key", not any(t.upper().startswith(("MH-", "UR-")) for t in terms))
check("a permalink ending in an id names nothing", "archives" not in terms and "browse" not in terms)
check("a templated tail falls back to its literal", J.context_terms("GET /api/v2/graphs/{graphId}") == ["graphs"])
check("short words are dropped", J.context_terms("see a-b and x_y") == [])

check("named keys: MH-3934 and UR-512, not its own",
      J.mentioned_keys(SOURCE, "MH-3954") == ["UR-512", "MH-3934"])

def row(key, summary, assignee=None):
    return {"key": key, "fields": {"summary": summary, "status": {"name": "Backlog"},
                                   "assignee": {"displayName": assignee or "x", "accountId": assignee or "x"}}}

hits = {"MH-2564": {"issue": row("MH-2564", "Integrate Graph Submissions API", "me"), "phrases": ["async"], "terms": []},
        "UR-541": {"issue": row("UR-541", "graph-submissions stale stage"), "phrases": [], "terms": ["graph-submissions"]},
        "UR-512": {"issue": row("UR-512", "tangible claim"), "phrases": [], "terms": ["graph-submissions"]}}
ranked = J.rank_found(hits, ["UR-512"], owner="me", project="MH")
keys = [r["key"] for r in ranked]
check("a caller's word outranks one source term", keys.index("MH-2564") < keys.index("UR-541"))
check("named by the source adds: UR-512 above UR-541", keys.index("UR-512") < keys.index("UR-541"))
by = {r["key"]: r for r in ranked}
check("score: word 3 + yours 1 + project 1", by["MH-2564"]["score"] == 5)
check("score: term 1 + named 2", by["UR-512"]["score"] == 3)
check("every row carries why", all(r["why"] for r in ranked) and "named by the source" in by["UR-512"]["why"])

br = J.bridged_terms(SOURCE, ["异步", "async"], terms)
check("bridge: the source writes 异步 beside graph-submissions", br.get("graph-submissions") == ["异步"])
check("bridge: a term never beside a caller's word is not bridged", "headlessr_decoder" not in br)

# MH-2564 carries none of the caller's words; the bridged term and its summary lift it over a bilingual noise hit
hits = {"MH-2564": {"issue": row("MH-2564", "Integrate Graph Submissions API", "me"), "phrases": [],
                    "terms": ["graph-submissions"]},
        "CH-1": {"issue": row("CH-1", "慢接口优化"), "phrases": ["异步", "async"], "terms": []}}
by = {r["key"]: r for r in J.rank_found(hits, [], owner="me", project="MH", bridges=br)}
check("bridged term ×3 + summary 2 + yours 1 + project 1", by["MH-2564"]["score"] == 7)
check("outranks a hit on both caller's words alone", by["MH-2564"]["score"] > by["CH-1"]["score"])
check("why names the bridge and the summary",
      any("≈异步" in w for w in by["MH-2564"]["why"]) and any(w.startswith("summary carries") for w in by["MH-2564"]["why"]))

print("jira find: all offline checks passed" if not failures else f"jira find: {len(failures)} failed")
sys.exit(1 if failures else 0)
