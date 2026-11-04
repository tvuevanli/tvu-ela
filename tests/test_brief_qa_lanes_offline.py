#!/usr/bin/env python3
"""The QA lanes when the qa host does not admit ela, offline: the release thread's build summary, QA's report block as
lane rows, the release as a built row until a report names it, the merge with a host read and with a carried read, the
cells and the source lines, and the finding when a read and QA's newest report disagree."""
import datetime, json, os, subprocess, sys, tempfile, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "brief"))
import brief as B  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

B.R._MAP = {"lines": {"2.1": {"lanes": {"qa": "qa-cn3", "daily": "daily-wed", "prod": "prod-3"}, "decided": "yes"}},
            "hosts": {"qa": {"match": "exact", "tag_to_lane": {"aws-cn3-env": "qa-cn3", "AWSCN3": "qa-cn3"}},
                      "lane_classes": {"qa": ["qa-cn1", "qa-cn2", "qa-cn3"], "daily": ["daily-wed"], "prod": ["prod-3"]}},
            "jobs": {"media-hub-v4": "mediahub-backend", "mediahub-front-docker": "mediahub-frontend", "ur-caller": "unified-streaming",
                     "mx-media": "unified-media-backend", "mx-service-front-docker": "unified-media-frontend"}, "regions": {}}

# the bot's reply in the day's release thread, by role (the markers are the bot's Chinese words, escaped)
SUMMARY = ("\u672c\u6b21\u6784\u5efa 3 \u4e2a\uff08\u5168\u90e8 QA-AWS3\uff09\uff1aur-caller v2.1.81 · media-hub-v4 v2.1.39 "
           "· mediahub-front-docker v2.2.126")
DONE = ("[\u4eca\u65e5\u53d1\u7248] \u4eca\u65e5 QA3 \u53d1\u7248\u5b8c\u6210\n"
        "• ur-caller v2.1.81 (#371)\n   - MH-3862 destination description\n"
        "• media-hub-v4 v2.1.39 (#271)\n   - project history by projectId\n"
        "• mediahub-front-docker v2.2.126 (#181)\n   - MH-3848 schedule dialog\n")
rows = {r["job"]: r for r in B.parse_release_thread([SUMMARY])}
check("the summary reply names each job's version and the lane it went to",
      [(r["service"], r["to"], r["number"], r["env"]) for r in rows.values()]
      == [("unified-streaming", "2.1.81", None, "QA-AWS3"), ("mediahub-backend", "2.1.39", None, "QA-AWS3"), ("mediahub-frontend", "2.2.126", None, "QA-AWS3")])
rows = {r["job"]: r for r in B.parse_release_thread([DONE, SUMMARY])}
check("the release-done bullets give the build numbers, the summary the lane; the tickets stay",
      (rows["media-hub-v4"]["number"], rows["media-hub-v4"]["env"], rows["mediahub-front-docker"]["items"][0]["keys"]) == (271, "QA-AWS3", ["MH-3848"]))
check("the thread's lane words reach ela's lane name", B.mail_lane("QA-AWS3") == "qa-cn3" and B.mail_lane("QA3") == "qa-cn3")

# QA's report: its environment block, kept across days, as reported rows
BLOCK = ("Please review the test report.\n*2 Pass* · Closed *0* · *New 1*\n"
         "Test Environment\nTVU MediaHub (ENV: aws-cn3-env) Beta\nFrontend: v2.2.126 build181 2026-11-02 09:39:47\n"
         "Backend: v2.1.39 build271 2026-11-02 09:39:26\nUnified Media Service (ENV: AWSCN3)\nFrontend: v3.0.40 build197 2026-10-30 09:45:44\n"
         "Backend: v1.0.287 build91 2026-10-30 10:13:09\nUnified Resources Caller (ENV: AWSCN3)\nBackend: v2.1.81 build371 2026-11-02 09:39:24\n"
         "Test Result\n*MH-3848* PASS\n")
q = B.parse_qa_mail({"id": "r1", "from": "qa lead", "date": "Tue, 03 Nov 2026 19:07:07 +0800",
                     "subject": "Daily Test Report for [Release Mediahub QA-AWS3] For 2.1 Release build 79 on 11-3", "body": BLOCK})
check("the block names five services on the QA lane", sorted(r["service"] for r in q["tested"])
      == ["mediahub-backend", "mediahub-frontend", "unified-media-backend", "unified-media-frontend", "unified-streaming"]
      and all(r["lane"] == "qa-cn3" for r in q["tested"]))
with tempfile.TemporaryDirectory() as d:
    tested = B.keep_tested(d, [q], datetime.datetime(2026, 11, 4, 8, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8))))
rep = B.reported_rows(tested, {"qa-cn3"})
be = next(r for r in rep if r["service"] == "mediahub-backend")
check("a reported row is the lane as QA's report says it ran, dated by the report",
      len(rep) == 5 and be["host"] == "mail" and be["state"] == "reported" and be["version"].startswith("v2.1.39 build271")
      and be["at"] == "2026-11-03T19:07:07+08:00" and B.vkey(be["version"]) == ((2, 1, 39, 0), 271))

# the release: the mail and the thread as built rows; a report names the version and wins; a newer build stands as built
MAIL = B.parse_release_mail({"id": "m1", "thread": "t1", "from": "release owner", "date": "Mon, 02 Nov 2026 17:46:36 +0800",
                             "subject": "[Release Mediahub QA-AWS3] For 2.1 Release build 81",
                             "body": "Service add\n   - UR Caller Backend (mx-service) (release2.1) : v2.1.80 => v2.1.81 (deployed to QA-AWS3)\n"
                                     "   - MediaHub Backend (release2.1) : v2.1.38 => v2.1.39 (deployed to QA-AWS3)\n"
                                     "   - MediaHub Admin Frontend (master) : v1.0.38 => v1.0.39\n"})
THREAD = {"subject": "2026-11-02_Release", "from": "bot", "date": "2026-11-02 17:36", "env": "slack", "moves": B.parse_release_thread([DONE, SUMMARY]),
          "text": DONE, "link": "x", "replies": 3}
built = {r["service"]: r for r in B.built_rows([MAIL, THREAD], {"qa-cn3"})}
check("a built row carries the thread's build number and says its source; a service outside the app is not one",
      built["mediahub-backend"]["version"] == "v2.1.39 build271" and built["mediahub-backend"]["source"] == "release thread"
      and built["mediahub-backend"]["state"] == "built" and "mediahub-admin-frontend" not in built and set(built) == {"mediahub-backend", "mediahub-frontend", "unified-streaming"})
mail_only = {r["service"]: r for r in B.built_rows([MAIL], {"qa-cn3"})}
check("the mail alone gives the version without a build, dated by the mail",
      mail_only["unified-streaming"]["version"] == "v2.1.81" and mail_only["unified-streaming"]["at"] == "2026-11-02T17:46:36+08:00"
      and mail_only["unified-streaming"]["source"] == "release mail")
rows = {r["service"]: r for r in B.qa_mail_rows(tested, [MAIL, THREAD], {"qa-cn3"})}
check("a report naming the built version outranks the release row", rows["mediahub-backend"]["state"] == "reported" and len(rows) == 5)
LATER = dict(THREAD, date="2026-11-04 17:40", moves=B.parse_release_thread(["• media-hub-v4 v2.1.40 (#272)\n", SUMMARY.replace("v2.1.39", "v2.1.40")]))
rows = {r["service"]: r for r in B.qa_mail_rows(tested, [MAIL, THREAD, LATER], {"qa-cn3"})}
check("a build newer than the newest report stands as built, no report",
      rows["mediahub-backend"]["state"] == "built" and rows["mediahub-backend"]["version"] == "v2.1.40 build272" and rows["unified-streaming"]["state"] == "reported")

# the merge: a host read now; a carried read older than the report; a carried read newer than it; the base's own mail rows
NOW = datetime.datetime(2026, 11, 4, 8, 10, 45, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
def live_row(service, lane, version, host="qa", **kw):
    return {"service": service, "tag": "", "lane": lane, "version": version, "updated": "", "host": host, **kw}
base = [live_row("mediahub-backend", "qa-cn3", "v2.1.37 build269 2026-10-29 09:44:16", read_at="2026-10-30T08:13:10+08:00"),
        live_row("unified-media-backend", "qa-cn3", "v1.0.286 build90 2026-10-19 06:48:59", read_at="2026-10-30T08:13:10+08:00"),
        live_row("mediahub-backend", "prod-3", "v2.1.36 build267 2026-10-27 09:46:52", host="prod", read_at="2026-11-03T08:10:52+08:00"),
        {"host": "mail", "lane": "daily-wed", "tag": None, "service": "orchestration", "version": "4.0.207", "updated": "Mon, 02 Nov 2026 14:59:31 +0800", "state": "requested"}]
mail = B.qa_mail_rows(tested, [MAIL, THREAD], {"qa-cn3"})
live = [live_row("mediahub-backend", "qa-cn3", "v2.1.39 build271 2026-11-02 09:39:26"), live_row("mediahub-backend", "prod-3", "v2.1.36 build267 2026-10-27 09:46:52", host="prod")]
got = B.merge_lane_rows(live, {"qa": True, "prod": True}, base, mail, NOW)
qa_be = [r for r in got if r["service"] == "mediahub-backend" and r["lane"] == "qa-cn3"]
check("a host read now is the row, dated by the read; the report's row for it is dropped",
      len(qa_be) == 1 and qa_be[0]["host"] == "qa" and qa_be[0]["read_at"] == NOW.isoformat(timespec="seconds") and "state" not in qa_be[0])
check("a service the host does not publish today is still the report's", any(r["service"] == "unified-streaming" and r["state"] == "reported" for r in got))
got = B.merge_lane_rows([live_row("mediahub-backend", "prod-3", "v2.1.36 build267 2026-10-27 09:46:52", host="prod")], {"prod": True}, base, mail, NOW)
qa_be = [r for r in got if r["service"] == "mediahub-backend" and r["lane"] == "qa-cn3"]
check("the qa host unread: the report of 11-03 replaces the read of 10-30",
      len(qa_be) == 1 and qa_be[0]["host"] == "mail" and qa_be[0]["state"] == "reported" and B.vkey(qa_be[0]["version"]) == ((2, 1, 39, 0), 271))
umb = next(r for r in got if r["service"] == "unified-media-backend" and r["lane"] == "qa-cn3")
check("the report names the UMS backend too, so that row is not carried either", umb["state"] == "reported" and B.vkey(umb["version"]) == ((1, 0, 287, 0), 91))
check("the base's Orchestration request stands", any(r["service"] == "orchestration" and r["state"] == "requested" for r in got))
newer = [dict(r, read_at="2026-11-04T07:00:00+08:00") for r in base[:2]]
got = B.merge_lane_rows([], {}, newer + base[2:], mail, NOW)
qa_be = next(r for r in got if r["service"] == "mediahub-backend" and r["lane"] == "qa-cn3")
check("a read later than the report is carried over it, marked carried with its read time",
      qa_be["host"] == "qa" and qa_be["state"] == "carried" and B.row_source(qa_be) == "last read 11-04 07:00")
pr = next(r for r in got if r["lane"] == "prod-3")
check("a prod row the session could not read is carried the same way", pr["state"] == "carried" and B.row_source(pr) == "last read 11-03 08:10")
old = [dict(r) for r in base[:2]]
for r in old:
    r.pop("read_at")
got = B.merge_lane_rows([], {}, old, [], NOW)
check("a carried row of unknown time says so and yields to any mail row",
      B.row_source(next(r for r in got if r["service"] == "mediahub-backend")) == "carried from an earlier read, its time unknown"
      and B.merge_lane_rows([], {}, old, mail, NOW)[0]["host"] == "mail")

# the moves and the cells
prev_rows = base[:3]
merged = B.merge_lane_rows([live_row("mediahub-backend", "prod-3", "v2.1.36 build267 2026-10-27 09:46:52", host="prod")], {"prod": True}, base, mail, NOW)
mv = [m for m in B.lane_moves(prev_rows, merged, None) if m["lane"] == "qa-cn3"]
check("the carried read to the report is a lane move, saying it is by mail",
      any(m["service"] == "mediahub-backend" and m["from"] == "2.1.37 build 269" and m["to"] == "2.1.39 build 271" and m["state"] == "reported" for m in mv))
cell = B.matrix_cell("mediahub-backend", "qa-cn3", merged, prev_rows, tested, {})
check("a reported cell is the version, QA's mark, and the report's date",
      cell["text"] == "▲ 2.1.39+271 (was 2.1.37+269) ✓ · QA report 11-03" and cell["source"] == "QA report" and cell["moved"])
built_cell = B.matrix_cell("mediahub-backend", "qa-cn3", [rows["mediahub-backend"]], None, tested, {})
check("a built cell says no report names it", built_cell["text"] == "2.1.40+272 built, no report" and built_cell["source"] == "release thread")
carried = B.matrix_cell("mediahub-backend", "qa-cn3", B.merge_lane_rows([], {}, newer, [], NOW), None, tested, {})
check("a carried cell says when the lane was last read", carried["text"].endswith("· last read 11-04 07:00") and carried["source"] == "last read 11-04 07:00")
req = B.matrix_cell("orchestration", "daily-wed", merged, None, tested, {})
check("a request is still a request", req["text"] == "4.0.207 requested")
check("the lane's source line names the report and its time",
      B.lane_sources(merged, ["qa-cn3", "prod-3"]) == ["QA-AWS3 as QA reported 11-03 19:07; lane not read"])
mixed = [r for r in merged if not (r["service"] == "unified-media-frontend" and r.get("state") == "reported")]
mixed.append(dict(rows["mediahub-backend"], service="unified-media-frontend"))
check("two sources on one lane are both named, by service",
      B.lane_sources(mixed, ["qa-cn3"]) == ["QA-AWS3: mediahub-backend, mediahub-frontend, unified-media-backend, UR Caller (unified-streaming) as QA reported 11-03 19:07; "
                                           "unified-media-frontend as built 11-04 17:40 (release thread), no QA report; lane not read"])
check("a lane read now has no source line", B.lane_sources(B.merge_lane_rows(live, {"qa": True, "prod": True}, [], [], NOW)) == [])

# saved reads: a row the file read live is dated by the file
with tempfile.TemporaryDirectory() as d:
    json.dump({"date": "2026-11-03", "at": "2026-11-03T08:10:52+08:00", "read": {"prod": True}, "rows": base[:3]}, open(os.path.join(d, "versions-2026-11-03.json"), "w"))
    reads = B.lane_reads(d)
    r = {x["lane"]: x for x in reads[-1][2]}
    check("the prod row is dated by its file, the carried qa row keeps its own", r["prod-3"]["read_at"] == "2026-11-03T08:10:52+08:00" and r["qa-cn3"]["read_at"] == "2026-10-30T08:13:10+08:00")
    def down(cmd, timeout=None):
        raise B.LaneError("qa login failed")
    real = B.run_json
    B.run_json = down
    live_rows, read, errs = B.read_lanes_live([], merged)
    B.run_json = real
    check("a live read with no host answering carries the merged base, the report's rows included",
          not read and any(r["state"] == "reported" for r in live_rows) and all(r.get("state") for r in live_rows if r["host"] != "mail"))

# the finding: both readable today, and the read is behind QA's newest report
real = B.subprocess
B.subprocess = types.SimpleNamespace(run=lambda *a, **k: types.SimpleNamespace(returncode=1, stdout=""), TimeoutExpired=subprocess.TimeoutExpired)
try:
    out = {"versions": [], "builds": [], "code": {"repos": []}, "releases": []}
    F = B.findings_of(out, [live_row("mediahub-backend", "qa-cn3", "v2.1.37 build269 2026-10-29 09:44:16", read_at=NOW.isoformat())], tested, [], [])
    dis = [f for f in F if f["kind"] == "lane_disagrees_with_qa_report"]
    check("a read behind the newest report is a finding with the report as evidence",
          len(dis) == 1 and "2.1.37 build 269" in dis[0]["what"] and "2.1.39 build 271" in dis[0]["what"] and dis[0]["rank"] == 6
          and dis[0]["evidence"][0].startswith("mail: Daily Test Report"))
    F = B.findings_of(out, [live_row("mediahub-backend", "qa-cn3", "v2.1.40 build272 2026-11-04 09:40:00", read_at=NOW.isoformat())], tested, [], [])
    check("a read ahead of the report is the untested build, not a disagreement",
          [f["kind"] for f in F if f.get("service")] == ["untested_build_on_lane"])
    F = B.findings_of(out, [rows["mediahub-backend"]], tested, [], [])
    check("a built row is said to be sent, not to run", F[0]["kind"] == "untested_build_on_lane" and F[0]["what"].startswith("qa-cn3 was sent (release thread) mediahub-backend 2.1.40 build 272"))
    F = B.findings_of(out, [r for r in merged if r["lane"] == "qa-cn3"], tested, [], [])
    check("the reported rows raise nothing", not [f for f in F if f.get("service")])
finally:
    B.subprocess = real

sys.exit(1 if failures else 0)
