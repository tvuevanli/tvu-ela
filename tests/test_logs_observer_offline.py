#!/usr/bin/env python3
"""logs offline: Observer status rows parse (a row or its detail may arrive as a JSON string), runs of one code fold,
a format descriptor reads as one line, and a metric series reports zeros and missing steps. A stub request answers in
place of Observer and the graph lookup is bypassed with --graph/--type. No network, no credential."""
import datetime, io, json, os, sys, types
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "logs"))
import logs as L  # noqa: E402

failures = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


T0 = 1795544977000
fmt = {"programs": [{"video": {"width": 1920, "height": 1080, "fps": 59.94, "interlaced": 0, "bitDepth": 8, "codec": "N/A"},
                     "audio": {"tracks": [{"channels": 8, "sampleRate": 48000}]}, "data": {"num": 0}}]}
rows = [json.dumps({"code": "0x80001010", "timestamp": T0, "detail": json.dumps({"nodeId": "p1"})}),
        {"code": "0x83310100", "timestamp": T0 + 5000, "detail": fmt, "level": "info"},
        {"code": "0x8240001a", "timestamp": T0 + 21000, "detail": "shm has no data", "level": "error"},
        {"code": "0x8240001a", "timestamp": T0 + 42000, "detail": "shm has no data", "level": "error"}]
evs = [L.parse_event(r) for r in rows]
check("a string row parses, its detail too", evs[0]["code"] == "0x80001010" and evs[0]["detail"] == {"nodeId": "p1"})
check("a UR lifecycle code is named", L.describe(evs[0]).startswith("dispatched"))
check("a format descriptor reads as one line", L.describe(evs[1]) == "format: video 1920x1080p59.94 8-bit uncompressed; audio 1 track(s) × 8ch 48000Hz")
c = L.collapse(evs)
check("a repeated alert folds into one row", len(c) == 3 and c[-1]["n"] == 2 and c[-1]["last"] == L.from_ms(T0 + 42000))

s = datetime.datetime(2026, 11, 25, 5, 0, tzinfo=L.UTC); e = s + datetime.timedelta(minutes=10)
pts = [{"ts": L.ms(s) + i * 60000, "value": v} for i, v in enumerate([59.94, 0, 59.94, 59.94, 59.94])]
x = L.summarize_series("video.fps", pts, 60, s, e)
check("a series counts zeros and expected steps", x["n"] == 5 and x["zeros"] == 1 and x["expected"] == 10 and x["last"] == 59.94)
check("numbers print short", L.num(1989660672) == "1.99G" and L.num(59.94) == "59.94")
check("other audio tracks are hidden by default", not L.shown_key("audio.tracks[1].bitRate", False) and L.shown_key("audio.tracks[0].bitRate", False))

sent = []
def stub(a, route, body):
    sent.append((route, body))
    if route == "queryMetricsHistoryData":
        return {"code": 0, "data": [{"key": "video.fps", "valueList": [{"ts": L.ms(s), "value": 0}]}]}
    return {"code": 0, "data": [{"key": "/ur/MediaHub/G1/p1", "data": rows}]}
L.observer_post = stub
L.now = lambda: e
a = types.SimpleNamespace(pid="p1", graph="G1", type="sdi_copier", at=None, window=None, frm=None, to=None, since="10m",
                          kind=["frame"], step=60, all_keys=False, json=False, verbose=False, width=240, env_file=None)
out = io.StringIO()
with redirect_stdout(out):
    L.cmd_metrics(a)
check("metrics asks docker_<node type>", sent[-1][1]["dockerType"] == "docker_sdi_copier" and sent[-1][1]["metrics"] == "frame")
check("a zero fps point is flagged", "1 zero point(s)" in out.getvalue() and "9 of 10 steps missing" in out.getvalue())
a.since = "7h"
try:
    with redirect_stdout(io.StringIO()):
        L.cmd_metrics(a)
    check("a metrics read over 6 hours is refused", False)
except SystemExit as ex:
    check("a metrics read over 6 hours is refused", ex.code == L.EX_USAGE)
a.since = "6h"; out = io.StringIO()
with redirect_stdout(out):
    L.cmd_status(a)
check("status reads the process key and folds", sent[-1][1]["prefixes"] == ["/ur/MediaHub/G1/p1"] and "×2 until" in out.getvalue())
sys.exit(1 if failures else 0)
