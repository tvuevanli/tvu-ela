#!/usr/bin/env python3
"""docker offline: the images a mail subject names (full paths, `& name:ver`, a dated suffix, replies skipped), QA's
conclusion from a wrapped bold sentence, the signal (a negative word wins; item marks speak when no word does), the
report's tickets with their blocking column, and a lane's cell against a version. No network."""
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
VERSIONS = {"1.0.23": {"summary": [{"id": "a"}]}, "1.0.24": {"summary": []}, "1.0.25": {"summary": [{"id": "b"}]}}
def lane(tags):
    return {"images": {"tvu_live_transmit": [("LiveTransmit" + str(i), t) for i, t in enumerate(tags)]}, "error": None}
behind = D.lane_cell(lane(["1.0.23"]), "tvu_live_transmit", "1.0.25", VERSIONS)
check("an older tag is behind", behind["state"] == "behind")
check("behind names the skipped version and whether QA reported it", behind["skips"] == [{"version": "1.0.24", "reported": False}])
check("behind carries the GM names for the bundle command", behind["gm"] == ["LiveTransmit0"])
check("a newer tag is ahead", D.lane_cell(lane(["1.0.26"]), "tvu_live_transmit", "1.0.25", VERSIONS)["state"] == "ahead")
check("the same version with a v is at", D.lane_cell(lane(["v1.0.25"]), "tvu_live_transmit", "1.0.25", VERSIONS)["state"] == "at")
check("services on either side differ", D.lane_cell(lane(["1.0.24", "1.0.26"]), "tvu_live_transmit", "1.0.25", VERSIONS)["state"] == "mixed")
check("a GM named tag cannot be compared", D.lane_cell(lane(["Production2"]), "tvu_live_transmit", "1.0.25", VERSIONS)["state"] == "named")
check("an image not in the bundle is absent", D.lane_cell(lane(["1.0.25"]), "copier", "1.0.88", VERSIONS) == {"state": "absent"})
check("an unread lane says why", D.lane_cell({"images": None, "error": "not readable"}, "copier", "1.0.88", VERSIONS)
      == {"state": "unread", "why": "not readable"})

if failures:
    print(f"{len(failures)} failed"); sys.exit(1)
print("docker offline: all passed")
