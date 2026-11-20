#!/usr/bin/env python3
"""docker offline: the images a mail subject names (full paths, `& name:ver`, a dated suffix, replies skipped), QA's
conclusion from a wrapped bold sentence, the signal (a negative word wins; item marks speak when no word does), the
report's tickets with their blocking column, a lane's cell, the change log, the mail labels, one image's rows and the
page's head. No network."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "docker"))
import docker as D  # noqa: E402
FIX = os.path.join(ROOT, "tests", "fixtures", "docker")
def fixture(name):          # report bodies in Chinese live in files: the content guard reads a quoted CJK sentence as speech
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

# ── images_in, on subjects as QA and the developers write them ─────────────────────────────────────
check("full path after a product build",
      D.images_in("Summary Test Report for tvu_live_transmit 8.2.0build23 & docker.tvunetworks.com/tvurtc/tvu_live_transmit:1.0.25 release-20261105")
      == [("tvu_live_transmit", "1.0.25")])
check("a bare name:version after & shares the first path's registry",
      D.images_in("Summary test report for docker.tvunetworks.com/tvurtc/shm_agora:1.0.6 & audio_card_capture:1.0.6 - 11/3")
      == [("shm_agora", "1.0.6"), ("audio_card_capture", "1.0.6")])
check("a dated suffix is not part of the version",
      D.images_in("Summary Test Report for [AI output] Release docker.tvunetworks.com/tvurtc/output:v1.0.19-20261103")
      == [("output", "v1.0.19")])
check("a build suffix with a word stays",
      D.images_in("Summary test report for docker.tvunetworks.com/tvursys/agoraencoder:12.13.9build256-ubuntu & agoradecoder:12.11.3build113-ubuntu - 10/28")
      == [("agoraencoder", "12.13.9build256-ubuntu"), ("agoradecoder", "12.11.3build113-ubuntu")])
check("the cn registry counts", D.images_in("[encoder for mediabox ]docker.tvunetworks.cn/tvurtc/tvu264_all:1.0.58") == [("tvu264_all", "1.0.58")])
check("no registry path, no image", D.images_in("Daily Test Report on 11-3 & copier:1.0.88") == [])
check("a reply is skipped", bool(D.REPLY_RX.match("Re: Summary test report for docker.tvunetworks.com/tvurtc/copier:1.0.88")))
check("a forward is skipped", bool(D.REPLY_RX.match("Fwd: [AI receiver2] Release docker.tvunetworks.com/tvurtc/receiver2:v1.0.11")))
check("a first mail is not a reply", not D.REPLY_RX.match("Summary test report for docker.tvunetworks.com/tvurtc/copier:1.0.88"))

# ── conclusion ─────────────────────────────────────────────────────────────────────────────────────
check("a bold sentence wrapped across lines is joined",
      D.conclusion(fixture("wrapped.txt")) == fixture("wrapped-conclusion.txt").strip())
check("with no bold, the marker's next line", D.conclusion("Conclusion:\nAll six features pass on 1.0.23, recommend release\n")
      == "All six features pass on 1.0.23, recommend release")
check("with no marker, the first line with a release word", D.conclusion(fixture("no-marker.txt")) == fixture("no-marker.txt").split("\n")[1])

# ── signal ─────────────────────────────────────────────────────────────────────────────────────────
check("a positive word", D.signal("结论：*建议发布*", "建议发布") == ("positive", "建议发布"))
check("a negative word wins over a positive one", D.signal(fixture("both-words.txt"), "建议发布")[0] == "negative")
check("the negative word is named", D.signal(fixture("both-words.txt"), "")[1] == "放行卡点")
MARKS_OK = fixture("marks-pass.txt")
check("item marks all pass read as positive", D.signal(MARKS_OK, "") == ("positive", "3 items marked PASS/通过, none FAIL"))
check("one FAIL mark reads as negative", D.signal(MARKS_OK + "4. 断流恢复 *FAIL*\n", "") == ("negative", "1 item marked FAIL"))
check("FAIL in an expected-behaviour sentence is not a mark", D.signal("expected: the API returns FAIL on a bad port\n*PASS*\n*PASS*", "")[0] == "positive")
check("one mark alone says nothing", D.signal("*PASS*", "") == ("unclear", None))

# ── ticket_rows ────────────────────────────────────────────────────────────────────────────────────
ROWS = ("| key | summary | priority | blocking |\n"
        "MH-3913 SRT passphrase written in plain text High 否\n"
        "MH-3786 MEDIA-SEQUENCE resets after restart Highest 是\n"
        "see also MH-3697, fixed in this version\n"
        "MH-3913 again in the notes\n")
rows = {r["key"]: r["blocking"] for r in D.ticket_rows(ROWS)}
check("blocking 否 reads no", rows.get("MH-3913") == "no")
check("blocking 是 reads yes", rows.get("MH-3786") == "yes")
check("a key with no row has no blocking", "MH-3697" in rows and rows["MH-3697"] is None)
check("each key once", [r["key"] for r in D.ticket_rows(ROWS)].count("MH-3913") == 1)

# ── lane_cell ──────────────────────────────────────────────────────────────────────────────────────
def lane(tags, image="tvu_live_transmit"):
    return {"images": {image: [("LiveTransmit" + str(i), t) for i, t in enumerate(tags)]}, "error": None}
check("one version tag: at it", D.lane_cell(lane(["1.0.23"]), "tvu_live_transmit") ==
      {"gm": ["LiveTransmit0"], "have": ["1.0.23"], "versions": ["1.0.23"], "state": "at"})
check("a GM named tag beside a version: the version is compared, the named tag's service is left out of the command",
      D.lane_cell(lane(["1.0.60", "Production2"]), "tvu_live_transmit")["versions"] == ["1.0.60"]
      and D.lane_cell(lane(["1.0.60", "Production2"]), "tvu_live_transmit")["gm"] == ["LiveTransmit0"])
check("two versions: mixed", D.lane_cell(lane(["1.0.24", "1.0.26"]), "tvu_live_transmit")["state"] == "mixed")
check("only a GM named tag cannot be compared", D.lane_cell(lane(["Production2"]), "tvu_live_transmit")["state"] == "named")
check("an image not in the bundle is absent", D.lane_cell(lane(["1.0.25"]), "copier") == {"state": "absent"})
check("an unread lane says why", D.lane_cell({"images": None, "error": "not readable"}, "copier") == {"state": "unread", "why": "not readable"})

# ── change logs, labels, links ─────────────────────────────────────────────────────────────────────
REL = ("tvu_live_transmit latest version release for integration\ntest.\n\n*The change logs*(from build 5):\n\n"
       "   - *Retry* (MH-4047): a failed report is retried up to 3 times\n   (backoff 1s / 2s / 4s).\n"
       "   - Size the SRT input's receive buffer.\n\n*Note*: set net.core.rmem_max.\n\ndocker run -itd --name x\n")
check("the change log: its items on one line, the mail's bold and line breaks undone, the note and the command left out",
      D.change_log(REL) == "Retry (MH-4047): a failed report is retried up to 3 times (backoff 1s / 2s / 4s).; Size the SRT input's receive buffer.")
check("a change log that runs on is cut at a word with an ellipsis",
      len(D.change_log("*The change logs*:\n1. " + "word " * 100 + "\n")) <= D.CHANGES_MAX + 2 and D.change_log("*The change logs*:\n1. " + "word " * 100).endswith("…"))
check("no change log: None", D.change_log("Hi team, a release.\n") is None)
m = {"id": "m1", "thread": "t1", "from": "Soffee Shu <s@x>", "at": "2026-11-18 20:01"}
check("a QA mail: a clean label and its Gmail thread",
      D.mail_link("QA summary", "tvu_live_transmit", "1.0.28", m) == "[QA summary · tvu_live_transmit 1.0.28 · Soffee Shu · 11-18](https://mail.google.com/mail/u/0/#all/t1)")
check("a release mail names no person", D.mail_label("Release mail", "mixer", "1.0.36", dict(m, at="2026-11-19 10:00")) == "Release mail · mixer 1.0.36 · 11-19")

# ── one image: a row per version, the target, the head line, the fold ───────────────────────────────
import datetime  # noqa: E402
OK = "1. Conclusion\n*Recommend release: every case passes, no regression introduced by this version.*\n"
def mail(i, at, body="", subject="s"):
    return {"id": i, "thread": "t" + i, "from": "QA One <q@x>", "at": at, "subject": subject, "body": body}
VS = {"1.0.25": {"release": mail("r25", "2026-10-20 10:00", REL), "summary": [mail("s25", "2026-10-22 10:00", OK)], "daily": []},
      "1.0.26": {"release": mail("r26", "2026-11-01 10:00", REL), "summary": [mail("s26", "2026-11-02 10:00", OK)], "daily": []},
      "1.0.27": {"release": mail("r27", "2026-11-17 10:00", REL), "summary": [], "daily": [mail("d27", "2026-11-18 10:00")]}}
LANES = [{"line": "2.1", "role": "daily", "lane": "daily-wed", "name": "Wednesday", "bundle": {"name": "mh2.1@daily-wed-s2-d57"},
          "images": {"tvu_live_transmit": [("Docker Mpegts Receiver", "1.0.24")]}, "error": None},
         {"line": "2.1", "role": "prod", "lane": "prod-3", "name": "Prod 3", "bundle": {"name": "MediaHub 2.1.20"},
          "images": {"tvu_live_transmit": [("Docker Mpegts Receiver", "1.0.25")]}, "error": None}]
c = D.image_record("tvu_live_transmit", VS, LANES, {}, [], datetime.date(2026, 11, 20), changes={"1.0.24": "changes not read"})
check("a row per version from the oldest a lane runs to the newest, newest first, the lanes marked",
      [r["version"] for r in c["rows"]] == ["1.0.27", "1.0.26", "1.0.25", "1.0.24"] and c["rows"][3]["lanes"] == ["Wednesday"]
      and c["rows"][2]["lanes"] == ["Prod 3"] and c["rows"][3]["verdict"] == "before the mail window")
check("each row: its changes, QA's verdict, its mails", c["rows"][1]["verdict"] == "ready" and c["rows"][0]["verdict"] == "under test"
      and c["rows"][1]["changes"].startswith("Retry (MH-4047)") and len(c["rows"][1]["mails"]) == 2)
check("the target is the newest ready version; both lanes are behind it", c["target"] == "1.0.26" and c["can_move"]
      and c["behind"] == ["daily-wed"] and c["prod_behind"] == ["prod-3"])
check("ready more than 14 days ago and not moved is flagged with its date", c["stale"] == "11-02")
check("a daily lane gets the bundle command; prod moves with its promotion", [x["lane"] for x in c["commands"]] == ["daily-wed"]
      and '--set "Docker Mpegts Receiver=1.0.26"' in c["commands"][0]["command"])
res = {"at": "2026-11-20T11:00:00+08:00", "days": 21, "lines": ["2.1"], "candidates": [c], "gaps": [],
       "lanes": [{"name": "Wednesday", "bundle": {"name": "b", "at": "2026-11-20 10:03"}}]}
page = D.render(res, page=True)
head = page.split("## Waiting")[0]
check("the head: one line, image and target bold, the lanes by MediaHub name, the QA date, the flag, the mail",
      "- **tvu_live_transmit** · Wednesday 1.0.24 / Prod 3 1.0.25 → **1.0.26** · QA ready 11-02 · ready since 11-02, not moved · "
      "[QA summary · tvu_live_transmit 1.0.26 · QA One · 11-02](https://mail.google.com/mail/u/0/#all/ts26)" in head
      and head.count("**") == 4)
check("the page: titled by its lines, its old names kept as aliases, every image folded, the commands folded",
      "# Media docker services · 2.1" in page and 'aliases: ["mds", "docker", "Docker candidates"]' in page
      and "> [!note]- tvu_live_transmit · Wednesday 1.0.24 · Prod 3 1.0.25 · newest 1.0.27" in page
      and "## Commands" in page and "> [!note]- 1 bundle command" in page and "QA-AWS" not in page)
c2 = D.image_record("copier", {"1.0.91": {"release": mail("r91", "2026-11-19 10:00", REL), "summary": [], "daily": []}},
                    [dict(LANES[0], images={"copier": [("Copier", "1.0.90")]})], {}, [], datetime.date(2026, 11, 20))
check("a newer version with no report waits, its reason one clause", not c2["can_move"] and c2["waiting"] == "1.0.91 released 11-19, no QA report yet")
check("no setting: the newest followed line", isinstance(D.docker_lines(), list) and D.docker_lines())

if failures:
    print(f"{len(failures)} failed"); sys.exit(1)
print("docker offline: all passed")
