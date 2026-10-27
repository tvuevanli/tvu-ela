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
sys.exit(1 if failures else 0)
