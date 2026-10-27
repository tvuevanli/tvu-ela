#!/usr/bin/env python3
"""The changes facts, offline: release and QA mail parsed, the release thread's builds, lane moves against a snapshot."""
import datetime, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "brief"))
import brief as B  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

MAIL = {"id": "1", "thread": "t", "from": "qa", "date": "d", "subject": "[Release Mediahub QA-AWS3] For 2.1 Release build 76",
        "body": "Service add\n   - UR Caller Backend (mx-service) (release2.1) : v2.1.75 => v2.1.76\n   (deployed to QA-AWS3)\n"
                "   - MediaHub Frontend (release2.1) : v2.2.119 => v2.2.120 (deployed to\n   QA-AWS3)\n"}
r = B.parse_release_mail(MAIL)
check("a release mail's moves: service, branch, from, to, where",
      [(m["service"], m["branch"], m["from"], m["to"], m["env"]) for m in r["moves"]]
      == [("UR Caller Backend (mx-service)", "release2.1", "2.1.75", "2.1.76", "QA-AWS3"), ("MediaHub Frontend", "release2.1", "2.2.119", "2.2.120", "QA-AWS3")]
      and r["env"] == "Mediahub QA-AWS3")
tag = B.parse_release_mail({"id": "2", "thread": "u", "from": "x", "date": "d", "subject": "[Release] <Docker Html Render Uncompresseddecoder>",
                            "body": "Default Version Tag Update\n From:0.0.24\n To:0.0.25\n"})
check("a default-tag mail is one move", [(m["service"], m["from"], m["to"]) for m in tag["moves"]] == [("Docker Html Render Uncompresseddecoder", "0.0.24", "0.0.25")])

QA = {"id": "3", "from": "qa", "date": "d", "subject": "Daily Test Report for TVU MediaHub AWS CN3 on 10-26",
      "body": "Please review the test report (build v2.1.33 build264 / MediaHub Frontend v2.2.119).\n*4 Pass* · Closed *3* · *New 2*\n"
              "Test Environment\nTVU MediaHub (ENV: aws-cn3-env) Beta\nBackend: v2.1.33 build264 2026-10-22\n"
              "*MH-3767* PASS works\n*MH-3750* FAIL port still occupied\n8 cases: 7 Pass / 1 Fail\n"}
q = B.parse_qa_mail(QA)
check("a QA report: env, build, counts from its summary, not a case table",
      (q["env"], q["build"], q["pass"], q["fail"], q["closed"], q["new"]) == ("aws-cn3-env", "v2.1.33 build264", 4, None, 3, 2))
check("and the failing cases", q["failing"] == ["MH-3750: port still occupied"] and q["mediahub"])

THREAD = [f"{B.BUILD_RESULT} {B.DEPLOYED} QA-AWS3\n:white_check_mark: ur-caller v2.1.76 · 102s · <https://j/job/ur-caller/366/>",
          f"QA3 {B.RELEASE_DONE}\n• ur-caller v2.1.76 (#366) ← A\n   - MH-3802 no multiProgram\n   - nightly fixes\n"
          "• mediahub-front-docker v2.2.120 (#175) ← B\n   - MH-3821 both sources filtered"]
t = {r["job"]: r for r in B.parse_release_thread(THREAD)}
check("the release thread: each build, where it went, the tickets it carries",
      t["ur-caller"]["number"] == 366 and t["ur-caller"]["env"] == "QA-AWS3" and [i["keys"] for i in t["ur-caller"]["items"]] == [["MH-3802"], []]
      and t["mediahub-front-docker"]["service"] == "mediahub-frontend" and t["mediahub-front-docker"]["items"][0]["keys"] == ["MH-3821"])

now = datetime.datetime(2026, 10, 27, 8, 0).astimezone()
win = B.window_of(24, now)
prev = [{"host": "qa", "lane": "qa-cn3", "service": "mediahub-frontend", "version": "v2.2.119 build174 2026-10-26 06:54:05"},
        {"host": "qa", "lane": "qa-cn3", "service": "mediahub-backend", "version": "v2.1.34 build265 2026-10-26 09:44:53"}]
rows = [dict(prev[0], version="v2.2.121 build176 2026-10-26 10:18:25"), prev[1],
        {"host": "prod", "lane": "prod-3", "service": "unified-media-frontend", "version": "v3.0.36.1build1942026-10-26 08:08:34"}]
mv = B.lane_moves(prev, rows, win)
check("a lane move against the snapshot: from, to, build", [(m["lane"], m["from"], m["to"], m["build"]) for m in mv]
      == [("qa-cn3", "2.2.119 build 174", "2.2.121 build 176", 176)])
first = B.lane_moves(None, rows, win)
check("with no snapshot, the builds dated in the window, a patch marked", {m["lane"] for m in first} == {"qa-cn3", "prod-3"}
      and all(m["from"] is None for m in first) and any(m["patch"] for m in first if m["lane"] == "prod-3"))
check("a service outside the scope is left out of the thread", not B.parse_release_thread([f"{B.RELEASE_DONE}\n• mx-media v1.0.1 (#9) ← C\n   - x"]))
check("a mail outside the scope is not a release of the page", not B.IN_SCOPE_MAIL.search("[Release Drive AWSQA] Cloud Drive BE Build v2.1.153")
      and B.IN_SCOPE_MAIL.search("[Release prod3] Orchestration Service of version 4.0.205"))
check("UR Caller is labelled as the mails name it", B.LABEL["unified-streaming"].startswith("UR Caller"))

import json, subprocess, tempfile, types  # noqa: E402
REPORT = ("Please review.\n*4 Pass*\nTest Environment\nTVU MediaHub (ENV: aws-cn3-env) Beta\nFrontend: v2.2.119 build174 2026-10-26 06:54:05\n"
          "Backend: v2.1.33 build264 2026-10-22 09:42:12\nUnified Resources Caller (ENV: AWSCN3) Beta\nBackend: v2.1.75 build365 2026-10-22\n"
          "Billing Service\nFrontend: v1.0.252 build59\n")
tv = B.tested_versions(REPORT)
check("a QA report's environment block: the versions it ran on, per lane and service, another product's block left out",
      [(r["lane"], r["service"], r["version"][:16]) for r in tv] == [("qa-cn3", "mediahub-frontend", "v2.2.119 build17"),
                                                                     ("qa-cn3", "mediahub-backend", "v2.1.33 build264"), ("qa-cn3", "unified-streaming", "v2.1.75 build365")])
check("a release mail's environment is a lane", (B.mail_lane("MediaHub Prod3"), B.mail_lane("prod3"), B.mail_lane("Mediahub QA-AWS3"),
                                                 B.mail_lane("MediaHub Daily WED"), B.mail_lane("Drive Test")) == ("prod-3", "prod-3", "qa-cn3", "daily-wed", None))
with tempfile.TemporaryDirectory() as d:
    qa = [{"tested": tv, "at": "2026-10-26T18:39:00+08:00", "verdict": "pass", "subject": "Daily Test Report CN3"}]
    kept = B.keep_tested(d, qa, now)
    kept = B.keep_tested(d, [], now)
    check("tested versions are kept across mornings", B.newest_tested(kept, "qa-cn3", "mediahub-frontend")["version"].startswith("v2.2.119"))
    out = {"versions": [{"lane": "qa-cn3", "service": "mediahub-frontend", "to": "2.2.121 build 176", "built": "2026-10-26 19:18"}],
           "builds": [{"service": "unified-media-frontend", "label": "unified-media-frontend", "version": "3.0.36.1", "number": 194,
                       "branch": "prod3_patch", "patch": True, "deployed_to": ["daily-wed", "prod-3"], "commits": ["abc"], "url": "u", "time": "t"}],
           "code": {"repos": [{"repo": "web/media-hub-front", "tickets": [], "untracked": [
               {"sha": "s1", "subject": "fix: drag handle", "lanes": ["qa-cn3"], "at": "a"},
               {"sha": "s2", "subject": "docs: readme", "lanes": ["qa-cn3"], "at": "a"}]}]},
           "releases": []}
    rows = [{"host": "qa", "lane": "qa-cn3", "service": "mediahub-frontend", "version": "v2.2.121 build176 2026-10-26 10:18:25"},
            {"host": "qa", "lane": "qa-cn3", "service": "mediahub-backend", "version": "v2.1.33 build264 2026-10-22 09:42:12"}]
    real = B.subprocess
    B.subprocess = types.SimpleNamespace(run=lambda *a, **k: types.SimpleNamespace(returncode=1, stdout=""), TimeoutExpired=subprocess.TimeoutExpired)
    errs = []
    try:
        F = B.findings_of(out, rows, kept, [], errs)
    finally:
        B.subprocess = real
    kinds = sorted((f["kind"], f.get("service")) for f in F)
    check("a QA lane running a build newer than its last report is untested, and moved after the run",
          ("untested_build_on_lane", "mediahub-frontend") in kinds and ("version_moved_after_qa_run", "mediahub-frontend") in kinds
          and ("untested_build_on_lane", "mediahub-backend") not in kinds)
    check("a patch build on prod with no ticket is a prod fix without a ticket", ("prod_fix_without_ticket", "unified-media-frontend") in kinds)
    check("an unticketed fix on the QA lane is counted once per repo and lane, docs left out",
          [f["what"][:2] for f in F if f["kind"] == "unticketed_change_on_a_prod_path"] == ["1 "])
    check("what was not computed or not read is named", any(e["source"] == "constraints" for e in errs) and any("customer_ask_unanswered" in e["error"] for e in errs))

mrows = [{"service": "mediahub-frontend", "lane": "qa-cn3", "version": "v2.2.121 build176 2026-10-26"},
         {"service": "mediahub-backend", "lane": "qa-cn3", "version": "v2.1.33 build264 2026-10-22"},
         {"service": "unified-media-frontend", "lane": "prod-3", "version": "v3.0.36.1build1942026-10-26"}]
mprev = [{"service": "mediahub-frontend", "lane": "qa-cn3", "version": "v2.2.118 build173 2026-10-23"}]
mtested = {"a": {"lane": "qa-cn3", "service": "mediahub-backend", "version": "v2.1.33 build264", "at": "2026-10-26T18:39:00+08:00", "verdict": "pass"}}
c = B.matrix_cell("mediahub-frontend", "qa-cn3", mrows, mprev, mtested, {})
check("a cell that moved shows ▲ and the old version, and ○ when no report names it", c["text"] == "▲ 2.2.121+176 (was 2.2.118+173) ○")
check("a cell QA passed shows ✓ and the report's date", B.matrix_cell("mediahub-backend", "qa-cn3", mrows, mprev, mtested, {})["text"] == "2.1.33+264 ✓ 10-26")
pc = B.matrix_cell("unified-media-frontend", "prod-3", mrows, None, {}, {("unified-media-frontend", "prod-3"): "over"})["text"]
check("a patch build is marked, and a pin over is ⛔", pc.startswith("3.0.36.") and pc.endswith("+194 patch ○ ⛔"))
md = B.render_matrix({"lanes": ["prod-3", "QA-AWS3"], "rows": [{"row": "media bundle", "cells": [{"text": "x"}, {"text": "y"}]}],
                      "same": ["Orchestration 4.0.205"], "gate": {"stop": 1, "high": 2, "report": "/r/2026-10-27-mh2.1-daily-wed-prod-3.json"}})
check("the table renders lanes as columns, the rows that agree as one line, and the gate", md.startswith("| | prod-3 | QA-AWS3 |")
      and "1 more the same on every lane: Orchestration 4.0.205" in md and "1 stop · 2 high" in md)
q2 = B.parse_qa_mail({"id": "4", "from": "qa", "date": "d", "subject": "Daily Test Report for TVU MediaHub on aws-cn3-env on 2026/10/26",
                      "body": "*Test Result:*\n   *1. new issue:*\n       MH-3821\n<https://j/browse/MH-3821>\nIn list view   Medium\n"
                              "   *2. reopened issue:*\n   *3. close issue:*\n       MH-3639\n<https://j/browse/MH-3639>\n       MH-3675\n-----\nBest\n"})
check("the listed-issues shape: new, reopened and closed by key, counted", (q2["new"], q2["closed"], q2["reopened"], q2["new_keys"], q2["closed_keys"])
      == (1, 2, 0, ["MH-3821"], ["MH-3639", "MH-3675"]) and q2["verdict"] == "pass")
orch = [{"host": "mail", "service": "orchestration", "lane": "prod-3", "version": "4.0.205"}]
check("a lane with no release mail for a mail-only service says so, not a bare dash",
      B.matrix_cell("orchestration", "qa-cn3", orch, None, {}, {})["text"] == "no release mail")
req = [{"host": "mail", "service": "orchestration", "lane": "prod-3", "version": "4.0.205", "state": "requested"}]
check("a version known only from a request mail reads as requested", B.matrix_cell("orchestration", "prod-3", req, None, {}, {})["text"] == "4.0.205 requested")
msg = lambda body: {"body": body}
check("a release runs once a reply says so, and a later hold takes it back",
      B.release_state([msg("please deploy"), msg("Deployed to prod3.")]) == "confirmed"
      and B.release_state([msg("please deploy"), msg("Deployed."), msg("Please hold until I confirm")]) == "requested"
      and B.release_state([msg("please deploy")]) == "requested")
check("a prod release bundle is found by its name", bool(B.RELEASE_NAME("2.1").match("MediaHub 2.1.14 (Build Version Emission)"))
      and not B.RELEASE_NAME("2.1").match("MediaHub 2.0 rc11"))
bc = B.bundle_cell({"bundleName": "MediaHub 2.1.15", "createTime": 1792992135152}, "by name", "2026-10-20 09:45", True)
check("a prod bundle reads as unconfirmed, and stale only when the lane moved after it",
      bc["text"].startswith("MediaHub 2.1.15 (2026-10-2") and bc["text"].endswith("unconfirmed") and not bc["stale"]
      and B.bundle_cell({"bundleName": "mh2.1@rc-s2-d8", "createTime": 1758600000000}, "token", "2026-10-26 08:08", True)["stale"])
check("findings carry the morning's rank; a QA build outside the candidate is the lanes table only",
      B.finding_rank({"kind": "constraint_over"}, set()) == 2
      and B.finding_rank({"kind": "untested_build_on_lane", "lane": "qa-cn3", "service": "mediahub-frontend"}, set()) is None
      and B.finding_rank({"kind": "untested_build_on_lane", "lane": "qa-cn3", "service": "mediahub-frontend"}, {"mediahub-frontend"}) == 7
      and B.finding_rank({"kind": "untested_build_on_lane", "lane": "prod-3", "service": "x"}, set()) == 5)
check("a candidate cell awaiting the owner reads as a question with its options",
      B.candidate_cell({"awaiting": "owner", "options": ["2.2.118", "2.2.118 patch"], "why": "x"})["text"] == "? (2 options)"
      and B.candidate_cell({"version": "2.1.34"})["text"] == "2.1.34" and B.candidate_cell("2.1.34")["text"] == "2.1.34")
named = [{"bundleName": "MediaHub 2.1.15", "bundleId": "15", "createTime": 1792992135152},
         {"bundleName": "MediaHub 2.1.14 (Build Version Emission)", "bundleId": "14", "createTime": 1792142586769},
         {"bundleName": "mh2.1@rc-s2-d8", "bundleId": "8", "createTime": 1792999999999}]
pf = B.pin_findings(named, None)
check("with no pin, the newest release-named bundle is offered as the pin command",
      len(pf) == 1 and pf[0]["kind"] == "release_newer_than_pin" and pf[0]["options"] == ['ela release pin 2.1 "MediaHub 2.1.15"'])
check("a pin on an older release is a decision; a pin on the newest is quiet",
      len(B.pin_findings(named, {"official": "MediaHub 2.1.14", "id": "14"})) == 1 and B.pin_findings(named, {"official": "MediaHub 2.1.15", "id": "15"}) == [])
diff = {"changed": [{"service": "Docker Html Render Uncompresseddecoder", "from": "0.0.22", "to": "0.0.24"},
                    {"service": "MediaHub Backend", "from": "2.1.33", "to": "2.1.34"}], "added": [{"service": "Docker Srt Copier", "version": "1.0.9"}]}
dr = B.docker_rows(diff, "qa-cn3", {"bundleName": "mh2.1@qa-q26", "createTime": 1792142586769, "operator": "qa"}, {"Docker Srt Copier": "mds-srt-copier"})
check("a bundle diff gives one row per docker service moved or added, by slug where the map has one",
      [(r["service"], r["from"], r["version"]) for r in dr] == [("Docker Html Render Uncompresseddecoder", "0.0.22", "0.0.24"), ("mds-srt-copier", None, "1.0.9")]
      and dr[0]["source"] == "bundle mh2.1@qa-q26")
with tempfile.TemporaryDirectory() as d:
    lp = os.path.join(d, "releases", "docker-versions.jsonl")
    check("the ledger takes a row once per service, version and source", B.append_ledger(lp, dr) == 2 and B.append_ledger(lp, dr) == 0
          and len(open(lp).read().splitlines()) == 2)
al = {"mds-html-decoder": "mds-html-decoder", "docker html render uncompresseddecoder": "mds-html-decoder"}
m1 = {"id": "m1", "from": "Q A <qa@x>", "date": "Mon, 26 Oct 2026 18:55:00 +0800",
      "subject": "Summary Test report for [AI output] Release docker.example.com/tvurtc/output:v1.0.18 - 20261026",
      "body": "Covers MH-3802.\nBox images (box): copier / tvu_live_transmit 1.0.23, playeroftvu 1.0.75, agoraencoder 8.13.8build243-ubuntu\n\nEnd"}
dm = B.docker_from_mail(m1, al)
check("a mail's image subject is a version that claims the mail's tickets; the box line lists versions without claims",
      [(r["service"], r["version"], [c["key"] for c in r["claims"]]) for r in dm] ==
      [("output", "1.0.18", ["MH-3802"]), ("copier", "1.0.23", []), ("tvu_live_transmit", "1.0.23", []), ("playeroftvu", "1.0.75", []),
       ("agoraencoder", "8.13.8build243-ubuntu", [])])
m2 = {"id": "m2", "from": "web", "date": "Mon, 26 Oct 2026 09:13:10 +0000", "subject": "[Release] <Docker Html Render Uncompresseddecoder>",
      "body": "Default Version Tag Update\n From:0.0.24\n To:0.0.25\n"}
check("a default-tag mail is the new version, by the map's slug", [(r["service"], r["version"]) for r in B.docker_from_mail(m2, al)] == [("mds-html-decoder", "0.0.25")])
rows = [dict(B.docker_from_mail(m2, al)[0], claims=[{"key": "MH-3790", "via": "jira", "ref": "comment 282857"}]), dm[0]]
df = B.docker_findings(rows, {"MH-3790", "MH-3802"})
check("a version naming a ticket with empty Fixed In drafts the entry for a mapped slug, cites the comment, and ranks with prod fixes",
      df[0]["options"] == ["ela jira fixed-in MH-3790 --add 'mds-html-decoder@0.0.25'"] and df[0]["evidence"] == ["MH-3790 comment 282857"] and df[0]["rank"] == 5
      and df[1]["options"] == [] and "no slug for output" in df[1]["what"])
check("a ticket whose Fixed In is set is not a finding", B.docker_findings(rows, set()) == [])
sys.exit(1 if failures else 0)
