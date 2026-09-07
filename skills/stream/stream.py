#!/usr/bin/env python3
"""What a stream actually carries — the PID table read off the wire, not off the code.

A field can exist in a profile, be sent in an API call, and still never reach the output: the
copier's HLS branch drops every PID option it was given. Only the stream settles it, so this
reads the stream. ffprobe is the sense; this adds what makes it usable on live MediaHub output:
an HLS media playlist rolls its window in seconds, so a segment named in one call is a 404 in
the next — `probe` resolves and fetches in one pass.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, urllib.parse, urllib.request

EX_OK, EX_USAGE, EX_MISSING, EX_REMOTE = 0, 2, 3, 5
UA = "ela-stream/1.0"


def need(binary):
    if not shutil.which(binary):
        print(f"{binary} not found — install ffmpeg", file=sys.stderr); sys.exit(EX_MISSING)
    return binary


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def resolve_hls(url, which="last"):
    """A playlist in, one segment's bytes out — resolved and fetched back to back.

    The live window is typically 5 segments of 2s. Anything that resolves in one call and
    downloads in another races the window and gets a 404, so the two happen here together.
    Returns (segment_url, bytes). A master playlist is followed one level to a media playlist.
    """
    print(f"resolving playlist {url}", file=sys.stderr)
    body = fetch(url).decode("utf-8", "replace")
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    if any(l.startswith("#EXT-X-STREAM-INF") for l in lines):          # master → first variant
        variants = [l for l in lines if not l.startswith("#")]
        if not variants:
            print("master playlist with no variant", file=sys.stderr); sys.exit(EX_REMOTE)
        return resolve_hls(urllib.parse.urljoin(url, variants[0]), which)
    segs = [l for l in lines if not l.startswith("#")]
    if not segs:
        print("no segments in playlist (stream may be stopped)", file=sys.stderr); sys.exit(EX_REMOTE)
    # not the newest: it may still be being written. One back is complete and still inside the window.
    pick = segs[-2] if which == "last" and len(segs) > 1 else (segs[0] if which == "first" else segs[-1])
    seg_url = urllib.parse.urljoin(url, pick)
    return seg_url, fetch(seg_url)


# Only an MPEG-TS multiplex has PIDs. RTMP carries FLV and RTSP usually carries bare elementary
# streams over RTP: both are legitimate targets here, and neither has a PID table to show.
TS_SCHEMES = ("srt://", "udp://", "rtp://", "rist://")
NO_PID_SCHEMES = ("rtmp://", "rtmps://", "rtmpt://", "rtmpe://", "rtsp://")


def is_network(target):
    return "://" in target and not target.startswith("file://")


def as_caller(url, host=None):
    """A listener URL is where the sender binds, not somewhere a puller can connect.

    The copier publishes `srt://0.0.0.0:PORT?mode=listener`; pulling from it means connecting to
    the box's address as a caller. Rewrites the bind address to `host` and drops `mode=listener`.
    """
    u = urllib.parse.urlsplit(url)
    if not u.scheme.startswith("srt"):
        return url
    q = urllib.parse.parse_qs(u.query, keep_blank_values=True)
    listener = q.get("mode", [""])[0] == "listener"
    bind = u.hostname in ("0.0.0.0", "::", "127.0.0.1", "localhost")
    if not (listener or bind):
        return url
    if not host:
        print(f"{url}\n  is a listener/bind address — nothing to connect to.\n"
              f"  Pass --host <box ip> to pull from it as a caller.", file=sys.stderr)
        sys.exit(EX_USAGE)
    q.pop("mode", None)
    netloc = f"{host}:{u.port}" if u.port else host
    return urllib.parse.urlunsplit((u.scheme, netloc, u.path,
                                    urllib.parse.urlencode(q, doseq=True), u.fragment))


def announce(target, seconds):
    """The URL that arrived, before the silent wait — and a truncated one is visible here.

    Every SRT and UDP URL carries `&` query parameters, which an unquoted shell argument splits:
    the command is backgrounded and the tool probes a URL shorter than the one that was typed.
    Nothing downstream can detect that, so the received target is always printed.
    """
    if is_network(target):
        print(f"probing {target}  (live pull, up to {seconds:g}s)", file=sys.stderr)
    else:
        print(f"reading {target}", file=sys.stderr)


def ffprobe_json(path_or_url, seconds=8, timeout=45):
    """Bounded on purpose: a live pull feed never ends, so say how much of it to look at."""
    announce(path_or_url, seconds)
    cmd = [need("ffprobe"), "-v", "error"]
    if is_network(path_or_url):
        # microseconds; without these a dead endpoint blocks until the subprocess timeout
        cmd += ["-rw_timeout", str(int(seconds * 1_000_000)),
                "-analyzeduration", str(int(seconds * 1_000_000)),
                "-probesize", "10000000"]
    cmd += ["-show_programs", "-show_streams", "-show_format", "-of", "json", path_or_url]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"ffprobe timed out after {timeout}s on {path_or_url}\n"
              f"  A listener with no sender, or a pull URL nothing is publishing to, looks like this.",
              file=sys.stderr)
        sys.exit(EX_REMOTE)
    if p.returncode != 0:
        print(f"ffprobe failed: {p.stderr.strip()[:400]}", file=sys.stderr); sys.exit(EX_REMOTE)
    return json.loads(p.stdout)


def pid_of(stream):
    """A TS stream's id is its PID; ffprobe prints it hex for mpegts, int elsewhere."""
    i = stream.get("id")
    if i is None:
        return None
    try:
        return int(i, 16) if isinstance(i, str) else int(i)
    except ValueError:
        return None


def read(target, which="last", host=None, seconds=8, timeout=45):
    """Anything readable in, one normalised record out. Keeps what it actually probed."""
    tmp = None
    if re.search(r"\.m3u8(\?|$)", target):
        seg_url, blob = resolve_hls(target, which)
        tmp = tempfile.NamedTemporaryFile(suffix=".ts", delete=False)
        tmp.write(blob); tmp.close()
        probed, source = tmp.name, seg_url
    else:
        probed = source = as_caller(target, host)
    try:
        d = ffprobe_json(probed, seconds, timeout)
    finally:
        if tmp:
            os.unlink(tmp.name)
    progs = []
    for p in d.get("programs", []):
        progs.append({"program_id": p.get("program_id"), "pmt_pid": p.get("pmt_pid"),
                      "pcr_pid": p.get("pcr_pid")})
    streams = []
    for s in d.get("streams", []):
        row = {"pid": pid_of(s), "type": s.get("codec_type"), "codec": s.get("codec_name"),
               "profile": s.get("profile")}
        if s.get("codec_type") == "video":
            row["detail"] = f"{s.get('width')}x{s.get('height')} {s.get('r_frame_rate')}"
        elif s.get("codec_type") == "audio":
            row["detail"] = f"{s.get('sample_rate')}Hz {s.get('channels')}ch"
        else:
            row["detail"] = ""
        streams.append(row)
    container = (d.get("format") or {}).get("format_name", "")
    return {"target": target, "probed": source, "container": container,
            "has_pids": bool(progs) or any(r["pid"] is not None for r in streams),
            "programs": progs, "streams": streams}


def render(rec):
    print(f"# {rec['target']}")
    if rec["probed"] != rec["target"]:
        print(f"  segment: {rec['probed']}")
    print()
    if rec.get("container"):
        print(f"  container: {rec['container']}")
        print()
    for p in rec["programs"]:
        print(f"program {p['program_id']}   PMT PID = {p['pmt_pid']}   PCR PID = {p['pcr_pid']}")
    if rec["programs"]:
        print()
    elif not rec.get("has_pids"):
        print("no PID table — this container is not an MPEG-TS multiplex "
              "(FLV over RTMP, or bare elementary streams over RTP/RTSP).")
        print("PMT, PCR and per-stream PIDs exist only in MPEG-TS: HLS segments, .ts, SRT, UDP, RTP-TS.")
        print()
    print(f"{'PID':<7}{'hex':<8}{'type':<8}{'codec':<8}{'detail'}")
    print(f"{'─'*6:<7}{'─'*6:<8}{'─'*7:<8}{'─'*7:<8}{'─'*24}")
    for s in rec["streams"]:
        pid = s["pid"]
        print(f"{pid if pid is not None else '?':<7}{hex(pid) if pid is not None else '?':<8}"
              f"{s['type'] or '?':<8}{s['codec'] or '?':<8}{s['detail']}")
    if not rec["streams"]:
        print("(no streams)")


def cmd_probe(a):
    rec = read(a.target, a.segment, a.host, a.seconds, a.timeout)
    print(json.dumps(rec, ensure_ascii=False, indent=2) if a.json else "", end="")
    if not a.json:
        render(rec)


def cmd_diff(a):
    x = read(a.a, a.segment, a.host, a.seconds, a.timeout)
    y = read(a.b, a.segment, a.host, a.seconds, a.timeout)
    if a.json:
        print(json.dumps({"a": x, "b": y}, ensure_ascii=False, indent=2)); return
    print(f"A  {x['target']}\nB  {y['target']}\n")
    px = x["programs"][0] if x["programs"] else {}
    py = y["programs"][0] if y["programs"] else {}
    rows = [("PMT PID", px.get("pmt_pid"), py.get("pmt_pid")),
            ("PCR PID", px.get("pcr_pid"), py.get("pcr_pid"))]
    for i in range(max(len(x["streams"]), len(y["streams"]))):
        sa = x["streams"][i] if i < len(x["streams"]) else {}
        sb = y["streams"][i] if i < len(y["streams"]) else {}
        rows.append((f"#{i} {sa.get('type') or sb.get('type') or '?'} PID", sa.get("pid"), sb.get("pid")))
        rows.append((f"#{i} codec", sa.get("codec"), sb.get("codec")))
    print(f"{'':<18}{'A':<12}{'B':<12}")
    for name, va, vb in rows:
        mark = "" if va == vb else "   ← differs"
        print(f"{name:<18}{str(va):<12}{str(vb):<12}{mark}")


def main():
    ap = argparse.ArgumentParser(
        description="What a stream actually carries: PMT/PCR/PID and codec, read off the wire.",
        epilog="Quote the target: an SRT or UDP URL's `&` parameters are shell separators otherwise, "
               "and the URL is silently truncated. The line printed before each read shows what arrived.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe", help="one stream — HLS playlist, .ts file, srt:// udp:// rtp:// rtmp://")
    p.add_argument("target")
    p.add_argument("--host", help="box ip to pull from when the URL is a listener/bind address (srt)")
    p.add_argument("--seconds", type=float, default=8, help="how much of a live feed to look at (default 8)")
    p.add_argument("--timeout", type=float, default=45, help="give up after this many seconds (default 45)")
    p.add_argument("--segment", choices=["first", "last", "newest"], default="last",
                   help="which HLS segment to read (default: one back from newest — complete, still in window)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("diff", help="two streams, field by field")
    p.add_argument("a"); p.add_argument("b")
    p.add_argument("--host", help="box ip for a listener/bind address (applies to both)")
    p.add_argument("--seconds", type=float, default=8)
    p.add_argument("--timeout", type=float, default=45)
    p.add_argument("--segment", choices=["first", "last", "newest"], default="last")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    {"probe": cmd_probe, "diff": cmd_diff}[a.cmd](a)


if __name__ == "__main__":
    main()
