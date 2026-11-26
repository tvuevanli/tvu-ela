#!/usr/bin/env python3
"""The QA report reader, offline: a key takes the verdict of a line about it, never of a line that cites it. Each
line keeps the shape of a line in QA's 2.1 report mails (QA CN3 builds 75-100, CN Prod2): the same filing and
recalling words, brackets and verdict position, the prose replaced. On those lines the reader gave seven bugs a
verdict that was a test case's or another ticket's (MH-3938 3970 3981 4028 4032 4053 4069)."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "promote"))
import promote as P  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


def verdicts(text, key):
    return [v for v, _ in P.key_verdicts(text, key)]


# cited: a bug filed or recalled on a line whose verdict is a test case's
CITED = {
    "MH-3938": "FAIL, 已提单 MH-3938 (Medium).",
    "MH-4053": "B-08 first target fails over to the next; the failed target is retried each time, 已提 MH-4053 Pass",
    "MH-4069": "Video Format 480x272 differs from the real 1080i59.94, decoder value, 同已知问题 MH-4069\nPass",
    "MH-3970": "> RTMP(S) *Pass* source and preview fine; MA bitrate missing（MH-3970, any protocol）.",
    "MH-3981": ">    - *black frame detection*: *Pass* - detects and triggers; only *the mail is not sent（MH-3981）*.",
    "MH-4032": "*2. headlessr 1.0.0.97build97（MH-4032 CN RWS domain）- TVU device source PASS (account / preview left):*",
}
for k, text in CITED.items():
    check(f"{k} cited on another thing's line takes no verdict", verdicts(text, k) == [])

# MH-4028: in brackets beside MH-3984's PASS, and inside PQ's earlier "Fail（MH-4028）） Pass"
L4028 = ("*MH-3984* PASS* [11-16 ~ 11-17] first round 52 / 61（output 阻塞 MH-4028 in UR Caller\n"
         "> PQ（on v2.1.93 Fail（MH-4028）） Pass\n"
         "> *MH-3984* TESTING 52 / 61 run; output 阻塞 MH-4028 fixed in UR Caller v2.1.94")
check("MH-4028 takes neither MH-3984's PASS nor PQ's earlier Fail", verdicts(L4028, "MH-4028") == [])
check("MH-3984 keeps its own PASS on the same line", verdicts(L4028, "MH-3984")[:1] == ["pass"])

# a wrapped line closing the bracket the key sits in
check("a key closing a wrapped bracket takes no verdict",
      verdicts("MH-4005）; profile resolution is preset only, out-of-range case N/A 2 Pass + 1 Fail", "MH-4005") == [])

# still read: the key's own result line, a shared verdict for keys the line leads with, the verdict on the next line
check("own result line", verdicts("*MH-3872* PASS a shared YouTube source read by a second account returns 0x0", "MH-3872") == ["pass"])
check("own line with a case id first", verdicts("TC5 MH-3887: port 70000 returns 8000400 Url Format Error Pass", "MH-3887") == ["pass"])
SHARED = "*MH-3961* PASS WebRenderer and mixer in different pools（filed during MH-1860）: self-hosted destination live in 19s"
check("a bracket after the key does not cite it", verdicts(SHARED, "MH-3961") == ["pass"])
check("...while the bracketed key takes none", verdicts(SHARED, "MH-1860") == [])
LEAD = "*MH-3897 / MH-3899 / MH-3900 / MH-3901* PASS [11-9] start and end time in the past are refused"
check("keys the line leads with share its verdict", all(verdicts(LEAD, k) == ["pass"] for k in ("MH-3897", "MH-3899", "MH-3901")))
check("a key mid-line does not share another key's verdict",
      verdicts("*MH-3984* PASS* first round 52 / 61, MH-4029 followed separately", "MH-4029") == [])
check("the verdict on the next line behind an arrow",
      verdicts("*Test Result:* 1. MH-3827 -->PASS, button size stable, closed. 2. MH-3841\n-->PASS, transcode output fine, closed.", "MH-3841") == ["pass"])
check("a section still lists a bracketed key", verdicts("Reopened issues\n(MH-4023)", "MH-4023") == ["fail"])

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nall ok")
