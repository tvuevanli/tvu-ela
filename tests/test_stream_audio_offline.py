#!/usr/bin/env python3
"""stream audio offline: synthetic 48 kHz stereo PCM for the four remap cases (default, swapped, both the same, muted),
cut into slices and read back as which channel sounds."""
import array, json, math, os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "stream"))
import stream as S  # noqa: E402

failures = []
def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

RATE = 48000
def tone(n, f, amp=8000, phase=0):
    return [int(amp * math.sin(2 * math.pi * f * (i + phase) / RATE)) for i in range(n)]

def stereo(left, right):
    a = array.array("h")
    for l, r in zip(left, right):
        a.append(l); a.append(r)
    return a

HALF = RATE // 2                       # 0.5 s each: the source's left speaker, then its right
zero = [0] * HALF
src_l, src_r = tone(HALF, 440), tone(HALF, 660)
cases = {
    "default": stereo(src_l + zero, zero + src_r),      # left plays first, then right
    "swapped": stereo(zero + src_r, src_l + zero),      # the same programme with the channels exchanged
    "same":    stereo(src_l + src_r, src_l + src_r),    # both channels carry one signal
    "muted":   stereo(zero + zero, zero + zero),
}
res = {k: S.audio_slices(v, 0.25) for k, v in cases.items()}
loud = {k: [r["loud"] for r in rows] for k, (rows, _) in res.items()}

check("default: L sounds, then R", loud["default"] == ["L", "L", "R", "R"])
check("swapped: R sounds, then L — the reverse of the default", loud["swapped"] == ["R", "R", "L", "L"])
check("both the same: every slice L=R, L−R at the floor, correlation 1",
      loud["same"] == ["L=R"] * 4 and res["same"][1]["LmR_db"] == S.FLOOR_DB and res["same"][1]["corr"] == 1.0)
check("muted: every slice silent, both channels silent overall",
      loud["muted"] == ["silent"] * 4 and res["muted"][1]["L_silent"] and res["muted"][1]["R_silent"])
r0 = res["default"][0][0]
check("a silent channel in a sounding slice: per-channel verdicts and no correlation",
      not r0["L_silent"] and r0["R_silent"] and r0["corr"] is None and r0["R_db"] == S.FLOOR_DB)
check("a full-scale-ish sine reads its RMS in dBFS (8000/32768 peak → about -15.3 dB)", abs(r0["L_db"] - (-15.3)) < 0.2)
summ = res["default"][1]
check("the summary counts slices by loud channel and the seconds read",
      summ["loud"] == {"L": 2, "R": 2} and summ["seconds"] == 1.0 and summ["slices"] == 4)
check("stereo music with both channels different reads both",
      S.loud(-20.0, -22.0, -25.0) == "both" and S.loud(-20.0, -20.0, -80.0) == "L=R")

# the CLI on a .pcm fixture: no ffmpeg needed
with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as f:
    f.write(cases["swapped"].tobytes())
try:
    p = subprocess.run([sys.executable, os.path.join(ROOT, "skills", "stream", "stream.py"), "audio", f.name, "--slice", "0.5", "--json"],
                       capture_output=True, text=True)
    d = json.loads(p.stdout) if p.returncode == 0 else {}
    check("audio --json on a .pcm file: R then L", [r["loud"] for r in d.get("slices", [])] == ["R", "L"])
    p = subprocess.run([sys.executable, os.path.join(ROOT, "skills", "stream", "stream.py"), "audio", "srt://box.example:1"],
                       capture_output=True, text=True)
    check("a live URL without --seconds is a usage error", p.returncode == 2)
finally:
    os.unlink(f.name)

print("stream audio: all offline checks passed" if not failures else f"stream audio: {len(failures)} check(s) failed")
sys.exit(1 if failures else 0)
