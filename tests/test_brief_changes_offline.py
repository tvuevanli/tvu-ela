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
check("a prod release bundle is found by its name", B.R.is_official("MediaHub 2.1.14 (Build Version Emission)", "2.1")
      and not B.R.is_official("MediaHub 2.0 rc11", "2.1") and not B.R.is_official("MediaHub 2.1.10 Docker Only", "2.1"))
bc = B.bundle_cell({"bundleName": "MediaHub 2.1.15", "createTime": 1792992135152}, "official", "2026-10-20 09:45", True)
check("a held prod bundle reads as pinned, and stale only when the lane moved after it",
      bc["text"].startswith("MediaHub 2.1.15 (2026-10-2") and bc["text"].endswith("pinned") and not bc["stale"]
      and not B.bundle_cell({"bundleName": "MediaHub 2.1.15", "createTime": 1792992135152}, "by name", "", False)["text"].endswith("pinned")
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
check("with no pin, prod follows the newest official and nothing is asked", B.pin_findings(named, None) == [])
pf = B.pin_findings(named, {"official": "MediaHub 2.1.14", "id": "14", "why": "the HTML input waits for QA"})
check("a hold on an older official is his decision again while a newer one exists, offered as unpin",
      len(pf) == 1 and pf[0]["options"] == ["ela release unpin 2.1"] and "the HTML input waits for QA" in pf[0]["what"]
      and B.pin_findings(named, {"official": "MediaHub 2.1.15", "id": "15"}) == [])
YAML = ('images:\n'
        '  webemulator:\n    slugs: ["mds-html-decoder"]\n    aliases: ["HTML render", "html_render"]\n    services:\n'
        '      - {"slug": "mds-html-decoder", "gm_name": "Docker Html Render Uncompresseddecoder", "process_type": "html_render_decoder"}\n'
        '  tvu_live_transmit:\n    slugs: ["mds-mpegts-receiver", "mds-mpegts-transmitter"]\n    aliases: ["live_transmit"]\n    services:\n'
        '      - {"slug": "mds-mpegts-receiver", "gm_name": "Docker Mpegts Receiver"}\n'
        '      - {"slug": "mds-mpegts-transmitter", "gm_name": "Docker Mpegts Transmitter", "aliases": ["MPEG-TS transmitter"]}\n'
        '  playeroftvu:\n    slugs: ["mds-srt-decoder", "mds-udp-decoder"]\n    services:\n'
        '      - {"slug": "mds-srt-decoder", "gm_name": "Docker Srt Decoder"}\n      - {"slug": "mds-udp-decoder", "gm_name": "Docker Udp Decoder"}\n')
with tempfile.TemporaryDirectory() as d:
    open(os.path.join(d, "services.yaml"), "w").write(YAML)
    site = os.path.join(d, "site.json"); json.dump({"map": d}, open(site, "w"))
    saved, B.SITE = B.SITE, site
    try:
        al = B.service_aliases()
    finally:
        B.SITE = saved
check("an image's name and aliases reach all its services; a service's names reach that one; _ - and space are equal",
      al["live-transmit"] == {"image": "tvu_live_transmit", "slugs": ["mds-mpegts-receiver", "mds-mpegts-transmitter"]}
      and al[B.norm("MPEG-TS transmitter")] == {"image": "tvu_live_transmit", "slugs": ["mds-mpegts-transmitter"]}
      and al[B.norm("html render")]["slugs"] == ["mds-html-decoder"] and B.norm("live transmit") == B.norm("live_transmit"))
diff = {"changed": [{"service": "Docker Html Render Uncompresseddecoder", "from": "0.0.22", "to": "0.0.24"},
                    {"service": "MediaHub Backend", "from": "2.1.33", "to": "2.1.34"}], "added": [{"service": "Docker Audio Splitter", "version": "default Production2"}]}
dr = B.docker_rows(diff, "qa-cn3", {"bundleName": "mh2.1@qa-q26", "createTime": 1792142586769, "operator": "qa"}, al, "2.1")
check("a bundle diff gives one row per docker service, by slug and image; a named GM tag is kept but not comparable",
      [(r["service"], r["image"], r["from"], r["version"], r["comparable"]) for r in dr]
      == [("mds-html-decoder", "webemulator", "0.0.22", "0.0.24", True), ("Docker Audio Splitter", None, None, "default Production2", False)])
with tempfile.TemporaryDirectory() as d:
    lp = os.path.join(d, "releases", "docker-versions.jsonl")
    check("the ledger takes a row once per service, version and source", B.append_ledger(lp, dr) == 2 and B.append_ledger(lp, dr) == 0)
m1 = {"id": "m1", "from": "Q A <qa@x>", "date": "Mon, 26 Oct 2026 18:55:00 +0800",
      "subject": "Summary Test report for [AI output] Release docker.example.com/tvurtc/webemulator:v0.0.25 - 20261026",
      "body": "Covers MH-3802 and AC-3.\nBox images (box): copier / tvu_live_transmit 1.0.23, decoder 1.0.75, agoraencoder 8.13.8build243-ubuntu\n\nEnd"}
dm = B.docker_from_mail(m1, al)
check("a subject's image path is matched on its last segment, its trailing date is not a version, MH keys are its claims",
      (dm[0]["image"], dm[0]["version"], [c["key"] for c in dm[0]["claims"]]) == ("webemulator", "0.0.25", ["MH-3802"]))
check("the box line: one version for 'copier / tvu_live_transmit' is the last name's; a bare decoder is playeroftvu",
      [(r["seen"], r["image"], r["version"]) for r in dm[1:]] == [("tvu_live_transmit", "tvu_live_transmit", "1.0.23"),
                                                                ("decoder", "playeroftvu", "1.0.75"), ("agoraencoder", None, "8.13.8build243-ubuntu")])
amb = B.docker_entry("decoder", "1.0.75", al, "decoder 1.0.75, youtuberender 0.0.38")
check("a bare decoder beside another decoder image is unresolved", amb.get("unresolved") and not amb["mapped"])
qa = B.docker_from_mail({"id": "m3", "from": "Dev <d@x>", "date": "Tue, 27 Oct 2026 10:00:00 +0800",
                         "subject": "[QA release] MPEG-TS transmitter 1.0.24 for test", "body": "Fixes MH-3790."}, al)
check("a [QA release] subject is a version for test, claiming the mail's keys",
      [(r["service"], r["version"], r["lane_or_bundle"], [c["key"] for c in r["claims"]]) for r in qa] == [("mds-mpegts-transmitter", "1.0.24", "QA release (for test)", ["MH-3790"])])
img = dict(dm[1], claims=[{"key": "MH-3790", "via": "jira", "ref": "comment 282857"}])
df = B.docker_findings([img, qa[0], dr[1] | {"claims": [{"key": "MH-1", "via": "mail", "ref": "x"}]}], {"MH-3790": None, "MH-1": None})
check("an image of several services drafts nothing until the service is known, and says so",
      df[0]["options"] == [] and "carries 2 services" in df[0]["what"] and df[0]["evidence"] == ["MH-3790 comment 282857"] and df[0]["rank"] == 5)
check("a service named alone drafts the team's form for that service",
      df[1]["options"] == ["ela jira fixed-in MH-3790 --add 'mds-mpegts-transmitter@tvu_live_transmit:1.0.24'"])
check("an unmapped name or a named tag drafts nothing, and says why", df[2]["options"] == [] and "no entry is drafted" in df[2]["what"])
check("a bundle's version is drafted only for a ticket whose release label is the bundle's line",
      B.docker_findings([dict(dr[0], claims=[{"key": "MH-9", "via": "jira", "ref": "c"}])], {"MH-9": "2.0"}) == []
      and len(B.docker_findings([dict(dr[0], claims=[{"key": "MH-9", "via": "jira", "ref": "c"}])], {"MH-9": "2.1"})) == 1)
check("a ticket whose Fixed In is set is not a finding", B.docker_findings([img], {}) == [])
rep_ = {"lanes": {"from": "qa-cn3", "to": "daily-wed"},
        "delta": {"services": [{"service": "mediahub-frontend", "from": "v2.2.121 build176", "to": "v2.2.118 build170", "relation": "from_ahead",
                                "commits": [{"sha": "aaaa1111", "subject": "fix(MH-1): a", "kind": "fix", "keys": ["MH-1"], "keys_in_subject": ["MH-1"]},
                                            {"sha": "bbbb2222", "subject": "fix: b", "kind": "fix", "keys": [], "keys_in_subject": []},
                                            {"sha": "cccc3333", "subject": "feat(MH-2): c", "kind": "feat", "keys": ["MH-2"], "keys_in_subject": ["MH-2"]}]},
                               {"service": "mediahub-backend", "from": "v2.1.34", "to": "v2.1.34", "relation": "same", "commits": []}]},
        "tickets": {"tickets": [{"key": "MH-1", "exists": True, "summary": "One", "status": "Review", "url": "u1"},
                                {"key": "MH-2", "exists": True, "summary": "Two", "status": "Done", "url": "u2"}]},
        "evidence": {"keys": {"MH-1": {"verdict": "pass"}}}}
dl = "\n".join(B.differences(rep_, lambda l: B.LANE_SHOWN.get(l, l)))
check("a pair opens with one verdict line", "**QA-AWS3 carries 2 tickets daily-wed does not; 1 verified, 1 untested, 1 unfiled fix.**" in dl)
check("each service lists its tickets with QA's verdict and state, by slug", "**mediahub-frontend** 2.2.118+170 → 2.2.121+176" in dl
      and "- [MH-1](u1) One — QA pass · Review" in dl and "- [MH-2](u2) Two — ○ no QA verdict · Done" in dl)
check("behaviour commits without a ticket are counted, folded", "> [!note]- 1 behaviour commit without a ticket" in dl and "> - `bbbb2222` fix: b" in dl)
rep2 = json.loads(json.dumps(rep_))
rep2["delta"]["services"][0]["service"] = "unified-streaming"
rep2["delta"]["services"][0]["commits"] += [{"sha": "dddd4444", "subject": "docs: d [arc-review]", "kind": "docs", "keys": []},
                                             {"sha": "eeee5555", "subject": "docs: e", "kind": "docs", "keys": []},
                                             {"sha": "ffff6666", "subject": "test: f", "kind": "test", "keys": []}]
rep2["evidence"]["keys"]["MH-2"] = {"verdict": "dev-declared"}
rep2["evidence"]["keys"]["MH-1"] = {"verdict": "pass", "items": [{"verdict": "pass", "when": "2026-10-26T10:00"}]}
d2 = "\n".join(B.differences(rep2, lambda l: B.LANE_SHOWN.get(l, l), [{"service": "unified-streaming", "lane": "prod-3", "says": "HTML input stays off prod 3"}]))
check("docs and tests are one closing line, not unfiled fixes", "2 docs and 1 test commits, no behaviour." in d2 or "2 docs commits and 1 test commit, no behaviour." in d2)
check("a developer's Fixed In is not a QA verdict; a real one carries its date", "○ no QA verdict · Fixed In by developer" in d2 and "QA pass (10-26)" in d2)
check("a ticket under a standing pin shows the lock and the constraint's word", "🔒 held off prod-3: HTML input stays off prod 3" in d2)
check("a service is named as the matrix names it", "**UR Caller (unified-streaming)**" in d2)
mx = {"lanes": ["prod-3", "daily-wed", "QA-AWS3"], "rows": [
    {"row": "mediahub-backend", "service": "mediahub-backend", "cells": [{"version": "2.1.34+265"}, {"version": "2.1.32+263"}, {"version": "2.1.34+265"}]},
    {"row": "x", "service": "x", "cells": [{"version": "3.0.36.1+194"}, {"version": "2.9.1"}, {"version": "3.0.38+195"}]}]}
inv, und = B.out_of_order(mx)
check("a lane below the one after it is out of order; two series are undetermined", inv == ["mediahub-backend: daily-wed 2.1.32+263 is below prod-3 2.1.34+265"] and und == 2)
check("a mail's service words are the slug", B.mail_slug("UR Caller Backend (mx-service)") == "unified-streaming" and B.mail_slug("MediaHub Frontend") == "mediahub-frontend")
check("a service the same on both lanes is not listed", "mediahub-backend" not in dl)
with tempfile.TemporaryDirectory() as t:
    os.makedirs(os.path.join(t, "runner"))
    json.dump({"date": "2026-10-26", "versions": [], "bundles": [], "releases": [], "code": {"repos": []},
               "builds": [{"service": "mediahub-frontend", "version": "2.2.119", "build": 174, "branch": "release2.1", "result": "SUCCESS",
                           "time": "2026-10-26 14:53", "deployed_to": [], "commits": []},
                          {"service": "mediahub-frontend", "version": "2.2.120", "build": 175, "branch": "release2.1", "result": "SUCCESS",
                           "time": "2026-10-26 17:44", "deployed_to": ["qa-cn3"], "commits": []},
                          {"service": "unified-media-frontend", "version": "3.0.36.1", "build": 194, "branch": "prod3_patch", "result": "SUCCESS",
                           "time": "2026-10-26 16:08", "deployed_to": ["prod-3"], "commits": []}]},
              open(os.path.join(t, "runner", "2026-10-26-changes.json"), "w"))
    mv = "\n".join(B.movements(t, t, {}, datetime.date(2026, 10, 26), lambda l: B.LANE_SHOWN.get(l, l)))
check("a release-branch build without a lane is on the QA lane, and each from chains to the last to",
      "| QA-AWS3 | mediahub-frontend | — → 2.2.119 build 174 |" in mv and "| QA-AWS3 | mediahub-frontend | 2.2.119 build 174 → 2.2.120 build 175 |" in mv)
check("a patch build sits on its base", "| prod-3 | unified-media-frontend | 3.0.36 → 3.0.36.1 build 194 |" in mv)
pg = "### 1. x\n- [ ] apply 1 — post it\n\n## Backlog\n| MH-1 | apply 4 |\n- [x] apply 2 — done\n"
check("a page names an apply N only with its action and its box", B.page_check(pg, [{"n": 1}, {"n": 2}]) == ([4], [4])
      and B.page_check("- [ ] apply 1 — x\n", [{"n": 1}]) == ([], []))
sys.exit(1 if failures else 0)
