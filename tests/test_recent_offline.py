#!/usr/bin/env python3
"""ela recent, offline: the line from the label, where a fix stands against the lane versions, QA's word from the test
lists on disk, the lanes a ticket names, what moved, the label ela would infer, and the page within its budget."""
import datetime, json, os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "recent"))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import recent as RC  # noqa: E402
import vault as V  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

RC.R._MAP = {"lines": {"2.1": {"label": "release:mh-2.1", "lanes": {"qa": "qa-cn3", "daily": "daily-wed", "prod": "prod-3"}},
                       "2.0": {"label": "release:mh-2.0", "lanes": {"qa": "qa-cn2", "daily": "daily-stage", "prod": "prod-8"}},
                       "2.2": {"label": "release:mh-2.2", "note": "label only — no lanes confirmed yet"},
                       "1.5": {"label": "release:mh-1.5", "lanes": {"qa": "qa-cn1", "daily": "daily-fri", "prod": "prod-2"}}},
             "version_rules": {"semver_build": {"patch_only": []}},
             "fixed_in": {"slug_aliases": {"mh-backend": "mediahub-backend"}}}
CFG = RC.lines_cfg()
TZ = datetime.timezone(datetime.timedelta(hours=8))
NOW = datetime.datetime(2026, 11, 2, 14, 5, tzinfo=TZ)


def row(service, lane, version, host="prod"):
    return {"service": service, "lane": lane, "version": version, "host": host}


ROWS = [row("mediahub-backend", "qa-cn3", "v2.1.37 build269 2026-10-30 10:00:00", "qa"), row("mediahub-frontend", "qa-cn3", "v2.2.124 build179 2026-10-30", "qa"),
        row("mediahub-backend", "daily-wed", "v2.1.36 build267 2026-10-29"), row("mediahub-frontend", "daily-wed", "v2.2.123 build178 2026-10-29"),
        row("mediahub-backend", "prod-3", "v2.1.32 build263 2026-10-26"), row("mediahub-frontend", "prod-3", "v2.2.116 build171 2026-10-26"),
        row("mediahub-backend", "prod-2-china", "v2.1.26 build256 2026-10-20"),
        row("mediahub-backend", "qa-cn2", "v2.0.40 build300 2026-10-20", "qa"), row("mediahub-backend", "daily-stage", "v2.0.39 build299"), row("mediahub-backend", "prod-8", "v2.0.38 build298"),
        row("orchestration", "prod-3", "4.0.205+78", "mail")]
BEFORE = [row("mediahub-backend", "daily-wed", "v2.1.32 build263 2026-10-26"), row("mediahub-backend", "qa-cn3", "v2.1.35 build266", "qa"),
          row("mediahub-backend", "prod-3", "v2.1.32 build263 2026-10-26")]
TESTLISTS = {"qa-cn3": [{"id": "MH-1", "ticket": "MH-1", "also": ["MH-9"], "verdict": "pass", "verdict_version": "build 80", "verdict_date": "2026-10-31"},
                        {"id": "MH-2", "ticket": "MH-2", "also": [], "verdict": "untested", "verdict_version": None, "verdict_date": None}]}


def issue(key, summary, labels=(), fixed=None, status="Review", created="2026-10-20T09:00:00.000+0800", updated="2026-11-01T10:00:00.000+0800",
          events=(), description=None, itype="Bug", due=None):
    hist = [{"created": at, "author": {"displayName": "Dev Person"}, "items": [{"field": f, "fromString": a, "toString": b}]} for at, f, a, b in events]
    return {"key": key, "fields": {"summary": summary, "labels": list(labels), RC.J.FIXED_IN_FIELD: fixed, "status": {"name": status},
                                   "assignee": {"displayName": "Dev Person"}, "issuetype": {"name": itype}, "priority": {"name": "High"},
                                   "created": created, "updated": updated, "duedate": due, "description": description},
            "changelog": {"histories": hist}}


ISSUES = [
    issue("MH-1", "Player freezes on prod-3 after reconnect", ["release:mh-2.1"], "mediahub-backend@2.1.36+267",
          events=[("2026-11-01T10:00:00.000+0800", "status", "In Progress", "Review"), ("2026-10-20T10:00:00.000+0800", "status", "Backlog", "In Progress")]),
    issue("MH-2", "Art page input replays", ["release:mh-2.1"], "mh-backend@2.1.37+269", created="2026-10-30T09:00:00.000+0800", updated="2026-10-30T09:00:00.000+0800"),
    issue("MH-3", "HTML status over MQTT", [], "mediahub-frontend@2.2.120+175", events=[("2026-11-02T08:00:00.000+0800", "Fixed In", None, "mediahub-frontend@2.2.120+175")]),
    issue("MH-4", "Cross-region prompt", [], None, status="Backlog", updated="2026-10-31T08:00:00.000+0800"),
    issue("MH-5", "Upload fails on AWS CN2 env", ["release:mh-2.0"], None, status="In Progress", events=[("2026-10-29T08:00:00.000+0800", "assignee", None, "Dev Person")]),
    issue("MH-6", "AI Sender MPEG-TS option", ["release:mh-2.1"], "mds-ai-sender@output:1.0.18", status="Done"),
    issue("MH-7", "Region hotfix", ["release:mh-2.1"], "mediahub-backend@2.1.30+260", status="Done", events=[("2026-10-28T08:00:00.000+0800", "priority", "Medium", "High")]),
    issue("MH-8", "Something on 2.2", ["release:mh-2.2"], None, status="Backlog"),
    issue("MH-10", "Two labels", ["release:mh-2.1", "release:mh-2.0"], None),
] + [issue(f"MH-{100 + i}", f"Filler ticket number {i} with a long summary about a behaviour of the player and its outputs", ["release:mh-2.1"],
           f"mediahub-backend@2.1.{30 + i % 8}+{260 + i % 8}", updated=f"2026-10-{27 + i % 5:02d}T10:00:00.000+0800") for i in range(130)]

res = RC.collect(ISSUES, CFG, ROWS, BEFORE, {}, TESTLISTS, NOW, 7, "https://jira.example", {"Dev Person": "Dev Roster"})
by = {t["key"]: t for ln in res["lines"] for t in ln["tickets"]}
no = {t["key"]: t for t in res["no_line"]}
check("the line comes from the label; two labels or none is no line", by["MH-1"]["line"] == "2.1" and by["MH-5"]["line"] == "2.0" and by["MH-8"]["line"] == "2.2"
      and {"MH-3", "MH-4", "MH-10"} <= set(no) and "MH-10" not in by)
check("the sections run 2.1, 2.0, 2.2, then a line with tickets; an empty other line is left out", [l["line"] for l in res["lines"]] == ["2.1", "2.0", "2.2"])
check("the counts name every line and no line", res["counts"] == {"2.1": 134, "2.0": 1, "2.2": 1, "no line": 3} and res["count"] == 139)
check("a fix carried by daily and QA but not prod stands at daily", by["MH-1"]["stands"]["text"] == "daily-wed" and by["MH-1"]["stands"]["role"] == "daily")
check("an alias resolves, and a fix only QA carries names the QA build", by["MH-2"]["stands"]["text"] == "qa-cn3 (build 269)")
check("a fix on prod with the China lane behind says so", by["MH-7"]["stands"]["text"] == "prod-3 · CN behind")
check("no Fixed In is dev; a docker image no lane row judges is declared", by["MH-5"]["stands"]["text"] == "dev" and by["MH-6"]["stands"]["text"] == "declared")
check("QA said comes from the lane test list, also-keys included", by["MH-1"]["qa"] == {"verdict": "pass", "version": "build 80", "date": "2026-10-31", "lane": "qa-cn3"}
      and RC.qa_said("MH-9", TESTLISTS)["verdict"] == "pass" and by["MH-2"]["qa"] is None)
check("a Jira name is written the roster's way", by["MH-1"]["assignee"] == "Dev Roster")
check("seen on reads the lanes the ticket names", by["MH-1"]["seen_on"] == ["prod-3"] and by["MH-5"]["seen_on"] == ["qa-cn2"]
      and RC.lane_words("fails on CN Prod2 and Prod 3, not on daily-wed or Stage") == ["prod-2-china", "prod-3", "daily-wed", "daily-stage"])
check("last change is the newest move in the window, or created, or updated",
      by["MH-1"]["last"] == "Review 11-01" and by["MH-2"]["last"] == "created 10-30" and no["MH-3"]["last"] == "Fixed In 11-02"
      and no["MH-4"]["last"] == "updated 10-31" and by["MH-5"]["last"] == "assigned 10-29" and by["MH-7"]["last"] == "High 10-28")
check("a move before the window is not an event", len(by["MH-1"]["events"]) == 1)
check("the label ela would infer comes from the Fixed In series on a line's lanes, and says why none can be",
      no["MH-3"]["infer"]["label"] == "release:mh-2.1" and "2.2.120+175 is in the 2.1 series on" in no["MH-3"]["infer"]["from"]
      and no["MH-4"]["infer"] == {"label": None, "line": None, "from": "no Fixed In"})
lanes = {x["lane"]: x for x in res["lines"][0]["by_lane"]}
check("by lane: the fix that reached daily in the window arrived there, the QA-only fix is under test, the prod bug is reported from prod",
      "MH-1" in lanes["daily-wed"]["arrived"] and "MH-1" not in lanes["prod-3"]["arrived"] and "MH-2" in lanes["qa-cn3"]["under_test"]
      and "MH-1" not in lanes["qa-cn3"]["under_test"] and lanes["prod-3"]["reported"] == ["MH-1"]
      and "MH-7" not in lanes["prod-3"]["arrived"] and "MH-7" not in lanes["prod-3"]["under_test"])
check("the test list's 'untested' is no verdict", RC.qa_said("MH-2", TESTLISTS) is None)
noold = RC.collect(ISSUES[:3], CFG, ROWS, None, {}, TESTLISTS, NOW, 7)
check("with no older lane read nothing is claimed to have arrived", all(x["arrived"] == [] for x in noold["lines"][0]["by_lane"]))
check("the train carries the lanes page's cells for both deliverables", [x["lane"] for x in res["lines"][0]["train"]] == ["qa-cn3", "daily-wed", "prod-3"]
      and res["lines"][0]["train"][1]["cells"]["mediahub-backend"].startswith("▲ 2.1.36+267 (was 2.1.32+263)") and res["lines"][2]["train"] == [])

page = RC.render_page(res)
check("the page is the dashboard: title, the refresh box, the sections in order, No line last",
      page.startswith("# Recent · 7 days\n") and "\n- [ ] refresh recent (last 14:05;" in page
      and page.index("## 2.1") < page.index("## 2.0") < page.index("## 2.2") < page.index("## No line"))
check("a line with no lanes says so", "*label only — no lanes confirmed yet*" in page)
check("the table folds after N rows and the By lane lists are folded", "> [!note]- " in page and " more\n> | ticket |" in page and "> [!note]- By lane\n> **qa-cn3 (QA-AWS3)** — arrived:" in page)
check("the seven columns", "| ticket | type · status · assignee | P / due | seen on | fix stands at | QA said | last change |" in page)
check("a row reads as designed", "| MH-1 · Player freezes on prod-3 after reconnect | Bug · Review · Dev Roster | High | prod-3 | daily-wed | pass on build 80 | Review 11-01 |" in page)
check("no line names the label ela would infer and writes nothing", "| release:mh-2.1 |" in page and "No label is written" in page and "apply " not in page)
check("the page fits the vault's budget outside its folds", RC.open_units(page) <= 1200
      and V.reading_gate(V.Note("recent.md", RC.TITLE, page, {"type": "recent"})) == [])
check("the vault's units and the page's agree", RC.units("word " * 10 + "[a](https://x/y) 参数") == V.reading_units("word " * 10 + "[a](https://x/y) 参数"))
with tempfile.TemporaryDirectory() as t:
    os.makedirs(f"{t}/recent"); os.makedirs(f"{t}/lanes")
    json.dump({"at": "2026-10-30T09:00", "count": 1}, open(f"{t}/recent/2026-10-30.json", "w"))
    json.dump(res, open(f"{t}/recent/2026-11-02.json", "w"))
    json.dump({"lane": "qa-cn3", "rows": {r["id"]: r for r in TESTLISTS["qa-cn3"]}}, open(f"{t}/lanes/test-list-qa-cn3.json", "w"))
    p, d = RC.newest_result(t)
    check("the newest result on disk is the one the vault renders", p.endswith("2026-11-02.json") and d["count"] == 139)
    check("the test lists are read from the lanes folder", RC.read_testlists(t) == {"qa-cn3": TESTLISTS["qa-cn3"]})
    check("no result, no page", RC.newest_result(f"{t}/none") == (None, None))
check("a timestamp with its offset", RC.mmdd("2026-11-01T23:30:00.000-0800") in ("11-01", "11-02") and RC.parse_at("junk") is None)
print(f"{len(failures)} failures" if failures else "recent: all offline checks passed")
sys.exit(1 if failures else 0)
