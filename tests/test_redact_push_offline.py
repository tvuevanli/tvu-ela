#!/usr/bin/env python3
"""redact cuts a stream key carried as a bare URL path segment: the last segment of an rtmp(s) push URL after its
application, an srt:// path or streamid, the segment after a known http(s) push path (its media extension kept), and
YouTube's HLS ingest cid. What is not a key reads as is: an rtmp URL with only its application, a playback URL outside
the push paths, a file path, a ticket key. Synthetic values built at run time; nothing is read or written."""
import os, random, string, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "configserver"))
import redact as R  # noqa: E402

failures = []


def check(ok, label):
    print(("ok   " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


rnd = random.Random(11)
k = lambda n: "".join(rnd.choice(string.ascii_lowercase + string.digits) for _ in range(n))  # noqa: E731
KEY = "-".join(k(4) for _ in range(4))
H = "ingest.example.invalid"

cut = [
    ("rtmp app/key", f"rtmp://{H}/live2/{KEY}", f"rtmp://{H}/live2/{R.RED}"),
    ("rtmps with port", f"rtmps://{H}:443/rtmp/{KEY}", f"rtmps://{H}:443/rtmp/{R.RED}"),
    ("rtmp nested app", f"rtmp://{H}/app/inst/{KEY}", f"rtmp://{H}/app/inst/{R.RED}"),
    ("rtmp key with a query", f"rtmp://{H}/live/{KEY}?vhost=x", f"rtmp://{H}/live/{R.RED}?vhost=x"),
    ("rtmp inside JSON", f'{{"url": "rtmp://{H}/live/{KEY}"}}', f'{{"url": "rtmp://{H}/live/{R.RED}"}}'),
    ("srt path", f"srt://{H}:9000/{KEY}", f"srt://{H}:9000/{R.RED}"),
    ("srt streamid", f"srt://{H}:9000?streamid={KEY}&latency=200", f"srt://{H}:9000?streamid={R.RED}&latency=200"),
    ("https /live/ push", f"https://{H}/live/{KEY}", f"https://{H}/live/{R.RED}"),
    ("https /live/ with extension", f"https://{H}/hls/live/{KEY}.m3u8", f"https://{H}/hls/live/{R.RED}.m3u8"),
    ("http /push/", f"http://{H}:8080/push/{KEY}/index.m3u8", f"http://{H}:8080/push/{R.RED}/index.m3u8"),
    ("YouTube HLS cid", f"https://a.upload.youtube.com/http_upload_hls?cid={KEY}&copy=0&file=",
     f"https://a.upload.youtube.com/http_upload_hls?cid={R.RED}&copy=0&file="),
]
for label, value, want in cut:
    out = R.scrub(value)
    check(KEY not in out, f"{label}: the key is gone")
    check(out == want, f"{label}: the rest reads as before")
    check(R.scrub(out) == out, f"{label}: scrubbing twice changes nothing")

kept = [
    ("rtmp with only its application", f"rtmp://{H}/live"),
    ("playback outside a push path", f"https://{H}/vod/{KEY[:4]}/index.m3u8"),
    ("a file path with live in it", f"/var/log/live/{KEY[:4]}.log"),
    ("a ticket key", "MH-1860"),
    ("an srt URL without path", f"srt://{H}:9000?latency=200"),
]
for label, value in kept:
    check(R.scrub(value) == value, f"{label}: prints as is")

user = f"rtmp://pub:{k(12)}@{H}/live/{KEY}"
out = R.scrub(user)
check(KEY not in out and "pub:" not in out, "rtmp with user:pass@ and a key: both cut")

sys.exit(1 if failures else 0)
