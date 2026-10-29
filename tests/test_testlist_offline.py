#!/usr/bin/env python3
"""The test list offline: a release mail's Test Focus and Change Log into behaviours, the owner of a two-ticket fix,
auto, priority, and the version a QA comment names."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "testlist"))
import testlist as TL  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

BODY = """Hi All:

Test Focus

   1. *MH-3833 / MH-3834* Change the Stream URL of an active YouTube source
   from Quick Edit; it switches without stopping the task.
   2. *MH-3831* Volume slider for YouTube sources in Quick Edit; it is
   disabled until the source task is running.
   3. Admin group setting changes push a permissionChange that the frontend
   now applies.

Change Log

   1. UR Caller: switch the URL of a running YouTube source — MH-3833
   <https://www.google.com/url?q=https://tvunetworks.atlassian.net/browse/MH-3833&source=gmail>
   2. UR Caller: setAudioDelay rejects an empty offset
   3. MediaHub Backend: permissionChange push payload includes groupId again
   4. MediaHub Frontend: YouTube source volume slider — MH-3831; edit Stream
   URL of an active YouTube source — MH-3834; CI and unit test fixes

Other Service Dependencies

   - none
"""
b = TL.parse_build_mail({"subject": "[Release Mediahub QA-AWS3] For 2.1 Release build 78", "body": BODY, "id": "x",
                         "date": "Wed, 28 Oct 2026 03:23:26 -0700"})
check("the build number comes from the subject", b["build"] == "78")
check("three Test Focus items", len(b["focus"]) == 3)
check("a Google redirect link is not a key", b["log"][0]["keys"] == ["MH-3833"])
check("a change-log line splits on ';' and a CI chore is dropped", [l["keys"] for l in b["log"]][3:] == [["MH-3831"], ["MH-3834"]])
check("the layer comes from the component", [l["layer"] for l in b["log"]][:3] == ["UR", "UR", "App"])
beh = TL.behaviours(b)
keys = [x["keys"] for x in beh]
check("two keys in one focus item are one behaviour", ["MH-3833", "MH-3834"] in keys)
check("a keyless focus item joins the keyless change-log line it shares a word with",
      any(not x["keys"] and x["focus"] and "permissionChange" in x["log"][0]["text"] for x in beh))
check("a keyless change-log line with no focus item is its own no-ticket behaviour",
      any(not x["keys"] and not x["focus"] and "setAudioDelay" in x["log"][0]["text"] for x in beh))
check("MH-3834's change-log line joins the MH-3833 behaviour", len(beh) == 4)

issues = {"MH-3833": {"fields": {"issuelinks": []}},
          "MH-3834": {"fields": {"parent": {"key": "MH-3833"}}}}
check("the parent owns a two-ticket fix", TL.owner_of(["MH-3834", "MH-3833"], issues) == "MH-3833")
check("with no relation the first named owns it", TL.owner_of(["MH-1", "MH-2"], {}) == "MH-1")

check("a field in a dialog is auto", TL.auto_of("Volume slider in the Quick Edit dialog is disabled", True))
check("a stream is never auto", not TL.auto_of("the sender outputUrl in the list shows issp", True))
check("a no-ticket row is never auto", not TL.auto_of("a page shows a list", False))

row = {"ticket": "MH-1", "verdict": "untested"}
check("a customer label is P1", TL.priority(row, {"labels": ["customer-issue"]}, set(), 0)[0] == "P1")
check("a failed row is a P1 re-test", TL.priority(dict(row, verdict="fail", verdict_version="2.1.36"), {}, set(), 0)
      == ("P1", "re-test: failed on 2.1.36"))
check("riding the next train ranks nothing", TL.priority(row, {}, set(), 0)[0] == "P3")
check("a customer's bracket is P1", TL.priority(row, {"summary": "[NDTV] audio-only HLS"}, set(), 0) == ("P1", "customer incident (NDTV)"))
check("a layer prefix is not a customer", TL.priority(row, {"summary": "[App] a field"}, set(), 0)[0] == "P3")
check("a hotfix label is P1", TL.priority(row, {"labels": ["hotfix-2.1"]}, set(), 0) == ("P1", "hotfix"))
check("a train within a working day lifts an untested row", TL.priority(row, {}, set(), 0, True)[0] == "P2")
check("the sprint is P2", TL.priority(row, {}, {"MH-1"}, 0)[0] == "P2")
check("High is P2", TL.priority(row, {"priority": {"name": "High"}}, set(), 0)[0] == "P2")
check("two builds old moves up one", TL.priority(row, {}, set(), 2) == ("P2", "the rest, 2 builds old"))

v = lambda t: TL.QA_VERSION_RX.search(t)  # noqa: E731
check("an address is not a version", v("on 10.12.64.45 it fails") is None)
check("a version with its build", v("Frontend: v2.2.117 build172 pass").groups()[:2] == ("2.2.117", "172"))
check("a bare build", v("passed on build 75").group(3) == "75")

check("every lane name the release mails use", [TL.env_lane(x) for x in ("QA-AWS3", "QA-AWS2", "Stage", "Prod3", "CN Prod2", "Daily WED")]
      == ["qa-cn3", "qa-cn2", "daily-stage", "prod-3", "prod-2", "daily-wed"])
check("a prod release is keyed by its day, labelled by its version",
      TL.build_key("[Release MediaHub Prod3] MH 2.1 Release build 2.1.74 (Daily WED → Prod 3)", "2026-10-26T11:07:10+08:00", False) == ("20261026", "2.1.74"))
check("a QA build named only by a version falls back to its day", TL.build_key("[Release Mediahub QA-AWS2] build 2.0.10", "2026-10-15T10:00", True) == ("20261015", "2.0.10"))
up = TL.parse_build_mail({"subject": "[Release MediaHub CN Prod2] CN2 upgrade to the Global Prod3 version (MH 2.1, MH-3752)", "body": "Hi\n",
                          "id": "y", "date": "Wed, 21 Oct 2026 13:23:42 +0800"}, qa=False)
check("a mail with no Test Focus and no Change Log is one row per key in its subject", [l["keys"] for l in up["log"]] == [["MH-3752"]])
pr = TL.sections("*Change Log* (Prod 3 v2.1.68 → v2.1.74)\n\n*Fixes*\n\n   1. DR auto-recovery honours the cooldown MH-3721\n")
check("a bold section heading with a note in brackets is a section", "MH-3721" in pr.get("Change Log", ""))
import datetime  # noqa: E402
th = "https://x.slack.com/archives/C0C16LK4KT9/p1793180233748809"
check("a reply's permalink names its thread", TL.reply_link(th, "1793190000.123456")
      == "https://x.slack.com/archives/C0C16LK4KT9/p1793190000123456?thread_ts=1793180233.748809&cid=C0C16LK4KT9")
msgs = [{"permalink": th, "replies": [{"ts": "1793190000.1", "user": "QA Person", "text": "MH-3833 pass on 2.1.78\nnt-1a2b3c4d fail on build 78"},
                                      {"ts": "1793190001.1", "user": "Dev One", "text": "MH-3831 pass on 2.2.123"}]}]
got = TL.thread_verdicts(msgs, {"qa person": "QA Person"})
check("a QA member's thread reply is a verdict, a developer's is not",
      [(k, v, ver) for _, k, v, ver, _, _ in got] == [("MH-3833", "pass", "2.1.78"), ("nt-1a2b3c4d", "fail", "build 78")])
fri = datetime.datetime(2026, 10, 26, 9, 0).astimezone()   # a Monday
TL.B.is_working_day = lambda d, doc=None: d.weekday() < 5
check("the last evening run before a Monday is Friday 19:00", TL.last_evening(fri).strftime("%a %H:%M") == "Fri 19:00")
row = lambda k: {"id": k, "ticket": k, "url": "u", "also": [], "title": k, "priority": "P3", "how_to_verify": "", "auto": False, "reason": "r"}  # noqa: E731
plan = [row("MH-1"), row("MH-2"), row("MH-3")]
left = TL.apply_guidance(plan, ["ela: drop MH-2", "ela: MH-3 first", "ela: something else"], {"rows": []})
check("his lines drop and reorder; an unknown line is returned", [p["id"] for p in plan] == ["MH-3", "MH-1"] and left == ["something else"])
check("a bot or helm is never an ask", all(TL.BOT_RX.search(n) for n in ("andyBot", "helm", "Summer Slack Bot")) and not TL.BOT_RX.search("Robin Wu"))
sys.exit(1 if failures else 0)
