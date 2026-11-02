#!/usr/bin/env python3
"""ela train, offline: the line's lanes with the aligned China lane, rows joined across lanes from the state files
and a new release mail, verdicts per lane, the position, a regression, an incident, the parity check against the QA
test list, and the page within its budget."""
import datetime, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "train"))
sys.path.insert(0, os.path.join(ROOT, "skills", "vault"))
import train as TR  # noqa: E402
import vault as V  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

CFG = {"label": "release:mh-2.1", "lanes": {"qa": "qa-cn3", "daily": "daily-wed", "prod": "prod-3"}}
REGIONS = {"china": {"aligns_with": "prod-3", "lanes": {"prod-2-china": {"shown": "CN Prod2", "line": "2.1"}, "prod-1-china": {"retiring": True}}}}
TZ = datetime.timezone(datetime.timedelta(hours=8))
NOW = datetime.datetime(2026, 11, 2, 14, 5, tzinfo=TZ)
QA = {"qa person": "QA Person"}


def srow(rid, ticket, build, at, verdict="untested", also=(), focus=None, log=()):
    return {"id": rid, "ticket": ticket, "also": list(also), "focus": focus, "log": list(log), "layers": ["App"], "first_build": build,
            "first_at": at, "builds": [build], "last_build": build, "last_at": at, "verdict": verdict, "verdict_version": "build 76" if verdict == "fail" else None,
            "verdict_date": "2026-10-27" if verdict == "fail" else None}


NT = TR.TL.nt_id("UR Caller: a null guard")
STATES = {
    "qa-cn3": {"lane": "qa-cn3", "lane_build": "79", "seed_after": "74",
               "builds": {"75": {"at": "2026-10-22T17:57:00+08:00", "label": "75"}, "76": {"at": "2026-10-26T17:52:00+08:00", "label": "76"},
                          "79": {"at": "2026-10-29T17:53:00+08:00", "label": "79"}},
               "rows": {"MH-1": srow("MH-1", "MH-1", "75", "2026-10-22T17:57:00+08:00", "fail", also=["MH-9"], focus="MH-1 the dialog shows the field"),
                        "MH-2": srow("MH-2", "MH-2", "79", "2026-10-29T17:53:00+08:00"),
                        NT: srow(NT, None, "79", "2026-10-29T17:53:00+08:00", log=["UR Caller: a null guard"])},
               "left": {"MH-3": dict(srow("MH-3", "MH-3", "75", "2026-10-22T17:57:00+08:00"), why="pass on build 75 (2026-10-23, QA report)", left_at="2026-10-23T10:00"),
                        "MH-4": dict(srow("MH-4", "MH-4", "76", "2026-10-26T17:52:00+08:00"), why="pass on build 76 (2026-10-28, QA report)", left_at="2026-10-28T10:00"),
                        "MH-7": dict(srow("MH-7", "MH-7", "76", "2026-10-26T17:52:00+08:00"), why="withdrawn: Won't Do", left_at="2026-10-28T10:00")}},
    "daily-wed": {"lane": "daily-wed", "builds": {"20261030": {"at": "2026-10-30T10:48:00+08:00", "label": "2.1.78"}},
                  "rows": {"MH-3": srow("MH-3", "MH-3", "20261030", "2026-10-30T10:48:00+08:00"),
                           "MH-4": srow("MH-4", "MH-4", "20261030", "2026-10-30T10:48:00+08:00")}, "left": {}},
    "prod-3": {"lane": "prod-3", "builds": {"20261026": {"at": "2026-10-26T11:07:00+08:00", "label": "2.1.74"}},
               "rows": {"MH-5": srow("MH-5", "MH-5", "20261026", "2026-10-26T11:07:00+08:00"), "MH-3": srow("MH-3", "MH-3", "20261026", "2026-10-26T11:07:00+08:00")}, "left": {}},
    "prod-2-china": {"lane": "prod-2-china", "builds": {}, "rows": {}, "left": {}},
}
MAILS = {"qa-cn3": [{"build": "80", "label": "80", "at": "2026-10-30T17:53:00+08:00", "id": "m80", "subject": "[Release Mediahub QA-AWS3] For 2.1 Release build 80",
                     "focus": [{"text": "MH-6 Encoding profile bitrate limit raised in the settings page", "keys": ["MH-6"]}],
                     "log": [{"text": "MediaHub Backend: bitrate limit — MH-6", "keys": ["MH-6"], "layer": "App"},
                             {"text": "UR Caller: a null guard", "keys": [], "layer": "UR"}]},
                    {"build": "74", "label": "74", "at": "2026-10-20T17:53:00+08:00", "id": "m74", "subject": "old", "focus": [], "log": [{"text": "old thing MH-99", "keys": ["MH-99"], "layer": None}]}]}
REPORTS = {"qa-cn3": [{"at": "2026-10-31T10:00", "build": "80", "summary": True, "subject": "Summary Test Report [Release Mediahub QA-AWS3] build 80",
                       "text": "Summary Test Report\nMH-2 pass\n"}],
           "daily-wed": [], "prod-3": [], "prod-2-china": []}


def comment(who, text, at):
    return {"author": {"displayName": who}, "body": text, "created": at}


ISSUES = {"MH-1": {"fields": {"summary": "The dialog shows the wrong field", "assignee": {"displayName": "Dev Person"}, "status": {"name": "Review"}, "priority": {"name": "High"}}, "comments": []},
          "MH-2": {"fields": {"summary": "Art page input replays", "status": {"name": "Review"}}, "comments": []},
          "MH-3": {"fields": {"summary": "Player freezes after reconnect", "status": {"name": "Done"}},
                   "comments": [comment("QA Person", "fail on 2.1.78 — freezes again on daily", "2026-10-31T09:00:00.000+0800")]},
          "MH-4": {"fields": {"summary": "Upload fails on large files", "status": {"name": "Done"}}, "comments": []},
          "MH-5": {"fields": {"summary": "YouTube source volume", "status": {"name": "Done"}}, "comments": []},
          "MH-6": {"fields": {"summary": "Encoding Profile bitrate upper limit", "status": {"name": "Review"}, "labels": ["customer-issue"]}, "comments": []},
          "MH-7": {"fields": {"summary": "withdrawn thing", "status": {"name": "Done"}, "resolution": {"name": "Won't Do"}}, "comments": []}}
INCIDENTS = [{"key": "MH-500", "summary": "[Customer] playback stops, caused by MH-5 on prod-3", "created": "2026-10-28T08:00:00.000+0800"},
             {"key": "MH-501", "summary": "old incident MH-3", "created": "2026-10-01T08:00:00.000+0800"}]
LANE_READ = [{"service": "mediahub-backend", "lane": "qa-cn3", "version": "v2.1.37 build269 2026-10-30", "host": "qa"},
             {"service": "mediahub-backend", "lane": "daily-wed", "version": "v2.1.36 build267 2026-10-29", "host": "prod"},
             {"service": "mediahub-backend", "lane": "prod-3", "version": "v2.1.32 build263 2026-10-26", "host": "prod"},
             {"service": "mediahub-backend", "lane": "prod-2-china", "version": "v2.1.26 build256 2026-10-20", "host": "prod"}]

check("the line's lanes: qa, daily, prod, then the aligned China lane; a retiring one is left out",
      TR.line_lanes("2.1", CFG, REGIONS) == [("qa", "qa-cn3"), ("daily", "daily-wed"), ("prod", "prod-3"), ("cn", "prod-2-china")])
check("a left row's why reads back as a verdict", TR.left_verdict("pass on build 75 (2026-10-23, QA report)") == ("pass", "build 75", "2026-10-23", "QA report")
      and TR.left_verdict("withdrawn: Won't Do") is None)

READS = [("2026-10-29", "0000", [{"service": "mediahub-frontend", "lane": "qa-cn3", "version": "v2.2.123 build178 2026-10-29", "host": "qa"}]),
         ("2026-10-30", "0000", LANE_READ + [{"service": "mediahub-frontend", "lane": "qa-cn3", "version": "v2.2.123 build178 2026-10-29", "host": "qa"},
                                             {"service": "mediahub-frontend", "lane": "daily-wed", "version": "v2.2.123 build178 2026-10-29", "host": "prod"}])]
res = TR.collect("2.1", CFG, STATES, MAILS, REPORTS, [], ISSUES, INCIDENTS, NOW, sprint={"MH-2"}, regions=REGIONS, qa=QA, lane_read=LANE_READ, reads=READS)
by = {r["id"]: r for r in res["rows"]}
check("one row per fix across the lanes; a withdrawn ticket rides nowhere", set(by) == {"MH-1", "MH-2", "MH-3", "MH-4", "MH-5", "MH-6", NT} and res["withdrawn"] == ["MH-7"])
check("a new QA build from the mails adds its rows; a build at or under seed_after does not", "MH-6" in by and "MH-99" not in by and res["builds"]["qa-cn3"] == ["75", "76", "79", "80"])
check("a no-ticket row named again by a later build keeps its first build", by[NT]["cells"]["qa-cn3"]["arrived"] == "79")
c1 = by["MH-1"]["cells"]
check("the QA cell carries the state's fail with its build; no other lane has it", c1["qa-cn3"]["verdict"] == "fail" and c1["qa-cn3"]["arrived"] == "75"
      and c1["qa-cn3"]["since"] == "2026-10-22" and "daily-wed" not in c1 and by["MH-1"]["position"] == "qa")
check("a re-test after a fail is P1 by the test list's rule", by["MH-1"]["priority"] == "P1" and by["MH-1"]["priority_reason"].startswith("re-test"))
check("the QA report after the row's build gives the verdict", by["MH-2"]["cells"]["qa-cn3"]["verdict"] == "pass" and by["MH-2"]["cells"]["qa-cn3"]["source"] == "QA report")
check("a QA summary report on a later build closes a no-ticket row as n/a", by[NT]["cells"]["qa-cn3"]["verdict"] == "n/a")
c3 = by["MH-3"]["cells"]
check("a fix on prod with a pass on QA: three cells, position prod", c3["qa-cn3"]["verdict"] == "pass" and c3["qa-cn3"]["arrived"] == "75"
      and c3["daily-wed"]["arrived"] == "2.1.78" and c3["prod-3"]["arrived"] == "2.1.74" and by["MH-3"]["position"] == "prod")
check("a QA fail comment after the daily arrival is the daily verdict, and a regression at P1 naming both lanes",
      c3["daily-wed"]["verdict"] == "fail" and by["MH-3"]["regression"] and by["MH-3"]["priority"] == "P1"
      and by["MH-3"]["priority_reason"] == "regression on daily-wed 2.1.78, passed qa-cn3 on 75")
check("an old incident does not count against a later arrival", c3["prod-3"]["verdict"] == "untested")
c5 = by["MH-5"]["cells"]
check("an incident naming the key after the prod arrival is the prod verdict; lanes below with no record are n/a",
      c5["prod-3"]["verdict"] == "incident" and c5["prod-3"]["source"] == "incident MH-500" and c5["qa-cn3"]["verdict"] == "n/a" and c5["daily-wed"]["verdict"] == "n/a"
      and not by["MH-5"]["regression"] and by["MH-5"]["position"] == "prod")
recs = {"qa-cn3": {"label": "78", "first_at": "2026-10-28T18:00:00+08:00"}, "daily-wed": {"label": "2.1.78", "first_at": "2026-10-30T10:48:00+08:00"}}
L = TR.line_lanes("2.1", CFG, REGIONS)
check("a comment naming a service version both lanes ran goes to QA, the lane QA tests; the lane it names in words wins",
      TR.verdict_lane("2026-10-29T20:00", "2.2.123 build 178", L, recs, ["78"], READS) == "qa-cn3"
      and TR.verdict_lane("2026-10-30T20:00", "2.2.123 build 178", L, recs, ["78"], READS) == "qa-cn3"
      and TR.verdict_lane("2026-10-30T20:00", "2.2.123 build 178", L, recs, ["78"], READS, ["daily-wed"]) == "daily-wed"
      and TR.verdict_lane("2026-10-30T20:00", "2.2.123 build 178", L, recs, ["78"], READS, ["prod-3"]) == "qa-cn3")
check("the lanes a comment names, keyed by its time", TR.comment_lanes({"comments": [comment("QA Person", "still fails on daily-wed and Prod 3", "2026-10-31T09:00:00.000+0800")]})
      == {"2026-10-31T09:00+08:00": ["prod-3", "daily-wed"]})
check("the prefetch's errors reach the page as named keys, never a record",
      TR.plain_gaps(["jira read MEDIAHF-254: {'query': '--env-file /x/.env read', 'exit': 1}", "jira read TVUCCM-4: {'exit': 1}", "QA report mails: {'stderr': 'x'}"])
      == ["2 tickets not readable (another project, or no permission): MEDIAHF-254, TVUCCM-4", "QA report mails"])
check("a comment naming the daily release's label goes to daily; a QA build number to QA; else the furthest lane reached",
      TR.verdict_lane("2026-10-31T09:00", "2.1.78", L, recs, ["78"]) == "daily-wed" and TR.verdict_lane("2026-10-31T09:00", "build 78", L, recs, ["78"]) == "qa-cn3"
      and TR.verdict_lane("2026-10-31T09:00", "1.0.11", L, recs, ["78"]) == "qa-cn3" and TR.verdict_lane("2026-10-31T09:00", "1.0.11", L, {"daily-wed": recs["daily-wed"]}, ["78"]) == "daily-wed")
daily_state = dict(STATES, **{"daily-wed": dict(STATES["daily-wed"], rows={"MH-4": dict(srow("MH-4", "MH-4", "20261030", "2026-10-30T10:48:00+08:00", "fail"),
                                                                                        verdict_version="build 76", verdict_date="2026-10-27", verdict_source=None)})})
with_state = TR.collect("2.1", CFG, daily_state, MAILS, REPORTS, [], ISSUES, INCIDENTS, NOW, regions=REGIONS, qa=QA)
check("a lane's recorded comment that belongs to another lane by the rule is not that lane's verdict (no false regression)",
      {r["id"]: r for r in with_state["rows"]}["MH-4"]["cells"]["daily-wed"]["verdict"] == "untested" and not {r["id"]: r for r in with_state["rows"]}["MH-4"]["regression"])
check("a pass on QA then untested on daily is no regression", by["MH-4"]["cells"]["daily-wed"]["verdict"] == "untested" and not by["MH-4"]["regression"])
check("the customer label is P1, the dialog row is auto, the owner is named", by["MH-6"]["priority"] == "P1" and by["MH-1"]["auto"] and by["MH-1"]["owner"] == "Dev Person")
check("the China lane is a cell, never a position", "prod-2-china" in [l["lane"] for l in res["lanes"]] and all(r["position"] != "cn" for r in res["rows"]))
check("the counts per lane", res["counts"]["qa-cn3"]["open"] == 2 and res["counts"]["qa-cn3"]["p1"] == 2 and res["counts"]["daily-wed"] == {"arrived": 2, "pass": 0, "fail": 1, "untested": 1, "incident": 0, "n/a": 0}
      and res["counts"]["prod-3"]["incident"] == 1)
check("regressions first, then priority", [r["id"] for r in res["rows"]][:3] == ["MH-3", "MH-1", "MH-6"])
check("the versions row comes from the lane read, cell by cell", [v["lane"] for v in res["versions"]] == ["qa-cn3", "daily-wed", "prod-3", "prod-2-china"]
      and res["versions"][0]["cells"]["mediahub-backend"].startswith("2.1.37+269"))

view = TR.qa_view(res)
check("the QA view is the rows with no pass on QA", view == {"MH-1": "fail", "MH-6": "untested"})
p = TR.parity(res, STATES["qa-cn3"])
check("parity names what the list has that the train lacks, and the reverse", p["missing"] == ["MH-2", NT] and p["extra"] == ["MH-6"] and p["differ"] == {} and not TR.equal(p))
same = {"rows": {"MH-1": {"verdict": "fail"}, "MH-6": {"verdict": "untested"}}}
check("equal lists are equal", TR.equal(TR.parity(res, same)) and TR.parity_lines(TR.parity(res, same), "qa-cn3")[-1] == "  equal")
check("a verdict that differs is named", TR.parity(res, {"rows": {"MH-1": {"verdict": "untested"}, "MH-6": {"verdict": "untested"}}})["differ"] == {"MH-1": ("untested", "fail")})

page = TR.render_page(res)
check("the page: title, the date line, the counts line", page.startswith("# Train · 2.1\n\n*2026-11-02 14:05 · line 2.1 · qa-cn3 → daily-wed → prod-3 · CN Prod2 · 7 rows*\n")
      and "*QA 2 open · 2 P1 · daily 2 arrived, 1 fail · prod 2 arrived, 1 incident · CN Prod2 0 arrived, 0 incident*" in page)
check("the versions row and the table head", "| | qa-cn3 (QA-AWS3) | daily-wed | prod-3 | prod-2-china (CN Prod2) |" in page
      and "| P | ticket | title | owner | qa-cn3 | daily-wed | prod-3 | prod-2-china | position |" in page)
check("a regression row reads as designed", "| ↩ P1 | [MH-3](https://tvunetworks.atlassian.net/browse/MH-3) | Player freezes after reconnect | — | ✓ 75 | ❌ 2.1.78 | · 2.1.74 | — | prod |" in page)
check("an incident row and n/a cells", "| n/a | n/a | ⚠ incident | — | prod |" in page)
check("a fail row with also-keys", "| P1 | [MH-1](https://tvunetworks.atlassian.net/browse/MH-1) / [MH-9](https://tvunetworks.atlassian.net/browse/MH-9) | The dialog shows the wrong field | Dev Person | ❌ 75 | — | — | — | qa |" in page)
check("no-ticket rows fold apart", "> [!note]- No ticket · 1\n> - UR Caller: a null guard — QA-AWS3 n/a 79 · qa" in page)
check("the footer links the test list and the lanes", "[[lanes/test-list-qa-cn3|Test list · QA-AWS3]] · [[lanes|The lanes]]" in page)
check("the page fits the vault's budget and its type", TR.RC.open_units(page) <= 1200
      and V.reading_gate(V.Note("lanes/train-2.1.md", "Train · 2.1", page, {"type": "train"})) == [])
big = dict(res, rows=res["rows"] + [dict(by["MH-2"], id=f"MH-{100 + i}", key=f"MH-{100 + i}", url=f"https://x/MH-{100 + i}") for i in range(30)])
bp = TR.render_page(big)
check("the table folds after eight rows", "\n> [!note]- 28 more\n" in bp and bp.count("\n| P1 |") + bp.count("\n| ↩ P1 |") + bp.count("\n| P2 |") + bp.count("\n| P3 |") == 8)
check("the block is a function of its own for the lanes page", TR.render_block(res)[0].startswith("*QA 2 open"))
none = TR.collect("2.1", CFG, {}, {}, {}, [], {}, None, NOW, regions=REGIONS, qa=QA)
check("with nothing read the train is empty and says what it had", none["rows"] == [] and none["sources"]["incidents"] is False and "No ticketed row" in TR.render_page(none))
print(f"{len(failures)} failures" if failures else "train: all offline checks passed")
sys.exit(1 if failures else 0)
