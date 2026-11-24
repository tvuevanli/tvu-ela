#!/usr/bin/env python3
"""What a stream actually carries — the PID table read off the wire, not off the code.

A field can exist in a profile, be sent in an API call, and still never reach the output: the
copier's HLS branch drops every PID option it was given. Only the stream settles it, so this
reads the stream. ffprobe is the sense; this adds what makes it usable on live MediaHub output:
an HLS media playlist rolls its window in seconds, so a segment named in one call is a 404 in
the next — `probe` resolves and fetches in one pass.
"""
import argparse, array, json, math, os, re, shutil, subprocess, sys, tempfile, urllib.parse, urllib.request

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


def scheme_of(target):
    return target.split("://", 1)[0].lower() if "://" in target else "file"


def capability(container, target, probed_a_segment):
    """What this target kind can answer — decided up front, so a gap is stated and not inferred.

    Protocol and container each remove something. A live pull has no duration and cannot be
    seeked; a container that is not an MPEG-TS multiplex has no PID table and no service tags,
    however it was transported. Saying which of the two removed a field is the whole point:
    "no PIDs" on RTMP is the container's nature, on SRT it would be a finding.
    """
    scheme = scheme_of(target)
    live = scheme in ("srt", "udp", "rtp", "rist", "rtmp", "rtmps", "rtmpt", "rtmpe", "rtsp", "srtp")
    ts = "mpegts" in (container or "")
    caps, why = {}, {}
    caps["pids"] = ts
    if not ts:
        why["pids"] = (f"{container or scheme} is not an MPEG-TS multiplex — PMT, PCR and per-stream "
                       f"PIDs exist only there (FLV over RTMP, bare ES over RTP/RTSP, MP4 over HTTP)")
    caps["service_tags"] = ts
    if not ts:
        why["service_tags"] = "service_name / service_provider live in the TS SDT; this container has none"
    caps["duration"] = not live and not probed_a_segment
    if live:
        why["duration"] = "a live pull has no end to measure"
    elif probed_a_segment:
        why["duration"] = "one HLS segment was read, so duration is the segment's, not the stream's"
    caps["seekable"] = not live
    if live:
        why["seekable"] = "not seekable; every figure is from the sampled window only"
    caps["true_bitrate"] = not live
    if live:
        why["true_bitrate"] = "bitrate over a live window is an estimate, not the stream's rate"
    return caps, why


def gop_analysis(target, seconds, timeout):
    """Keyframe spacing and observed rate — the encoding profile sets a GOP, this measures it."""
    cmd = [need("ffprobe"), "-v", "error"]
    if is_network(target):
        cmd += ["-rw_timeout", str(int(seconds * 1_000_000))]
    cmd += ["-select_streams", "v:0", "-show_entries", "packet=pts_time,flags,size",
            "-read_intervals", f"%+{seconds:g}", "-of", "json", target]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    if p.returncode != 0:
        return None
    pkts = json.loads(p.stdout).get("packets", [])
    if not pkts:
        return None
    keys, total = [], 0
    for i, k in enumerate(pkts):
        total += int(k.get("size") or 0)
        if "K" in (k.get("flags") or ""):
            keys.append(i)
    gaps = [b - a for a, b in zip(keys, keys[1:])]
    times = [float(k["pts_time"]) for k in pkts if k.get("pts_time") not in (None, "N/A")]
    span = (max(times) - min(times)) if len(times) > 1 else 0
    return {"packets": len(pkts), "keyframes": len(keys),
            "gop_frames": (sum(gaps) // len(gaps)) if gaps else None,
            "gop_seconds": round(span / len(gaps), 2) if gaps and span else None,
            "video_kbps": round(total * 8 / span / 1000) if span else None,
            "window_seconds": round(span, 2)}


def row_of(s):
    """One stream, normalised. Everything ffprobe gave is kept under `raw` for --full."""
    t = s.get("codec_type")
    tags = s.get("tags") or {}
    r = {"pid": pid_of(s), "index": s.get("index"), "type": t, "codec": s.get("codec_name"),
         "profile": s.get("profile"), "bitrate": s.get("bit_rate"),
         "language": tags.get("language"), "title": tags.get("title"), "raw": s}
    if t == "video":
        r["detail"] = f"{s.get('width')}x{s.get('height')} {s.get('r_frame_rate')}"
        r["level"] = s.get("level")
        r["pix_fmt"] = s.get("pix_fmt")
        fo = s.get("field_order")
        r["scan"] = "progressive" if fo in (None, "progressive", "unknown") else f"interlaced ({fo})"
        ct = s.get("color_transfer")
        r["hdr"] = {"smpte2084": "HDR10 (PQ)", "arib-std-b67": "HLG"}.get(ct) or None
        r["color"] = " ".join(x for x in (s.get("color_space"), ct, s.get("color_primaries"),
                                          s.get("color_range")) if x and x != "unknown") or None
    elif t == "audio":
        r["detail"] = f"{s.get('sample_rate')}Hz {s.get('channels')}ch"
        r["layout"] = s.get("channel_layout")
        r["sample_fmt"] = s.get("sample_fmt")
    else:
        r["detail"] = ""
    return r


def read(target, which="last", host=None, seconds=8, timeout=45, frames=False):
    """Anything readable in, one normalised record out. Keeps what it actually probed."""
    tmp = None
    segment = False
    if re.search(r"\.m3u8(\?|$)", target):
        seg_url, blob = resolve_hls(target, which)
        tmp = tempfile.NamedTemporaryFile(suffix=".ts", delete=False)
        tmp.write(blob); tmp.close()
        probed, source, segment = tmp.name, seg_url, True
    else:
        probed = source = as_caller(target, host)
    try:
        d = ffprobe_json(probed, seconds, timeout)
        gop = gop_analysis(probed, seconds, timeout) if frames else None
    finally:
        if tmp:
            os.unlink(tmp.name)
    progs = []
    for p in d.get("programs", []):
        tags = p.get("tags") or {}
        progs.append({"program_id": p.get("program_id"), "pmt_pid": p.get("pmt_pid"),
                      "pcr_pid": p.get("pcr_pid"), "nb_streams": p.get("nb_streams"),
                      "service_name": tags.get("service_name"),
                      "service_provider": tags.get("service_provider"), "tags": tags})
    streams = [row_of(s) for s in d.get("streams", [])]
    fmt = d.get("format") or {}
    container = fmt.get("format_name", "")
    caps, why = capability(container, target, segment)
    return {"target": target, "probed": source, "container": container,
            "protocol": scheme_of(target), "segment": segment,
            "has_pids": bool(progs) or any(r["pid"] is not None for r in streams),
            "programs": progs, "streams": streams, "gop": gop,
            "format": {k: fmt.get(k) for k in ("format_name", "duration", "size", "bit_rate",
                                               "probe_score", "start_time")},
            "caps": caps, "unavailable": why}


def render(rec, full=False):
    print(f"# {rec['target']}")
    if rec["probed"] != rec["target"]:
        print(f"  segment: {rec['probed']}")
    print(f"  container: {rec['container'] or '?'}   via: {rec['protocol']}")
    print()
    for p in rec["programs"]:
        print(f"program {p['program_id']}   PMT PID = {p['pmt_pid']}   PCR PID = {p['pcr_pid']}"
              f"   streams = {p['nb_streams']}")
        if p["service_name"] or p["service_provider"]:
            print(f"  service: {p['service_name'] or '—'}   provider: {p['service_provider'] or '—'}")
    if rec["programs"]:
        print()
    elif not rec["has_pids"]:
        print(f"no PID table — {rec['unavailable'].get('pids', 'not an MPEG-TS multiplex')}.")
        print()
    print(f"{'PID':<7}{'hex':<8}{'type':<7}{'codec':<8}{'lang':<6}{'detail'}")
    print(f"{'─'*6:<7}{'─'*6:<8}{'─'*6:<7}{'─'*7:<8}{'─'*5:<6}{'─'*34}")
    for s in rec["streams"]:
        pid = s["pid"]
        extra = s["detail"]
        for k in ("profile", "scan", "hdr", "layout"):
            v = s.get(k)
            if v and not (k == "scan" and v == "progressive"):
                extra += f"  {v}"
        print(f"{pid if pid is not None else '—':<7}{hex(pid) if pid is not None else '—':<8}"
              f"{s['type'] or '?':<7}{s['codec'] or '?':<8}{s['language'] or '—':<6}{extra}")
    if not rec["streams"]:
        print("(no streams)")
    if rec.get("gop"):
        g = rec["gop"]
        print(f"\nvideo over {g['window_seconds']}s: {g['keyframes']} keyframes in {g['packets']} packets"
              f"   GOP ≈ {g['gop_frames']} frames / {g['gop_seconds']}s   ≈ {g['video_kbps']} kbps")
    if full:
        print("\n--- format ---")
        for k, v in rec["format"].items():
            if v is not None:
                print(f"  {k:<14}{v}")
        for s in rec["streams"]:
            print(f"\n--- stream #{s['index']} pid {s['pid']} ({s['type']}) ---")
            for k, v in sorted(s["raw"].items()):
                if k != "disposition" and v not in (None, "", "unknown"):
                    print(f"  {k:<22}{v}")
    if rec["unavailable"]:
        print("\nnot available for this target:")
        for k, v in rec["unavailable"].items():
            print(f"  {k:<14}{v}")


def cmd_probe(a):
    rec = read(a.target, a.segment, a.host, a.seconds, a.timeout, a.frames)
    if a.json:
        print(json.dumps(rec, ensure_ascii=False, indent=2)); return
    render(rec, a.full)


def cmd_diff(a):
    x = read(a.a, a.segment, a.host, a.seconds, a.timeout)
    y = read(a.b, a.segment, a.host, a.seconds, a.timeout)
    for r in (x, y):
        r.pop("streams_raw", None)
    if a.json:
        print(json.dumps({"a": x, "b": y}, ensure_ascii=False, indent=2)); return
    print(f"A  {x['target']}\nB  {y['target']}\n")
    px = x["programs"][0] if x["programs"] else {}
    py = y["programs"][0] if y["programs"] else {}
    rows = [("container", x.get("container"), y.get("container")),
            ("PMT PID", px.get("pmt_pid"), py.get("pmt_pid")),
            ("PCR PID", px.get("pcr_pid"), py.get("pcr_pid")),
            ("service", px.get("service_name"), py.get("service_name")),
            ("provider", px.get("service_provider"), py.get("service_provider"))]
    # Paired within kind, not by position: two outputs of the same source can order their
    # streams differently, and comparing a video against an audio produces noise, not a finding.
    def by_kind(rec):
        out = {}
        for r in rec["streams"]:
            out.setdefault(r["type"] or "?", []).append(r)
        return out
    ka, kb = by_kind(x), by_kind(y)
    for kind in ("video", "audio", "data", "subtitle", "?"):
        la, lb = ka.get(kind, []), kb.get(kind, [])
        for i in range(max(len(la), len(lb))):
            sa = la[i] if i < len(la) else {}
            sb = lb[i] if i < len(lb) else {}
            label = f"{kind} {i}" if max(len(la), len(lb)) > 1 else kind
            rows.append((f"{label} PID", sa.get("pid"), sb.get("pid")))
            rows.append((f"{label} codec", sa.get("codec"), sb.get("codec")))
            rows.append((f"{label} detail", sa.get("detail"), sb.get("detail")))
            if kind == "video":
                rows.append((f"{label} scan", sa.get("scan"), sb.get("scan")))
            if kind == "audio":
                rows.append((f"{label} lang", sa.get("language"), sb.get("language")))
    if getattr(a, "only_diffs", False):
        rows = [r for r in rows if r[1] != r[2]]
    print(f"{'':<18}{'A':<24}{'B':<24}")
    for name, va, vb in rows:
        if va is None and vb is None:
            continue
        mark = "" if va == vb else "   ← differs"
        print(f"{name:<18}{str(va if va is not None else '—'):<24}"
              f"{str(vb if vb is not None else '—'):<24}{mark}")


# --- audio: which channel carries the sound, slice by slice -----------------------------------------------------
# An audio remapping (swap L/R, both the same, mute) is proved by the output, not by the API answer: on 2026-11-24 every
# remap call answered OK while it was being applied on another environment. A capture is decoded to 16-bit stereo PCM
# and cut into slices; each slice gives RMS per channel, the RMS of L−R, their correlation and a silence verdict per
# channel. Which channel is loud is the fact; whether that is the remap asked for is read against the source's layout.
RATE = 48000
SILENT_DB = -60.0       # below this a channel is silent (a muted output reads -99, the floor)
SAME_DB = -60.0         # L−R below this, with both channels sounding, is one signal on both
FLOOR_DB = -99.0


def db(sum_sq, n):
    """dBFS of a sum of squares over n 16-bit samples, floored at -99."""
    return FLOOR_DB if not n or sum_sq <= 0 else max(FLOOR_DB, 10 * math.log10(sum_sq / n / 32768.0 ** 2))


def pcm_of(target, seconds=None, track=0, host=None, timeout=60):
    """Interleaved stereo s16le samples. A .pcm / .s16 / .raw file is read as is (48 kHz stereo s16le); anything else
    is decoded by ffmpeg — a .ts file, or a live srt:// udp:// URL for --seconds."""
    if re.search(r"\.(pcm|s16|raw)$", target, re.I) and not is_network(target):
        raw = open(target, "rb").read()
    else:
        src = as_caller(target, host) if is_network(target) else target
        cmd = [need("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", src]
        if seconds:
            cmd += ["-t", str(seconds)]
        cmd += ["-map", f"0:a:{track}", "-f", "s16le", "-ac", "2", "-ar", str(RATE), "-"]
        print(f"decoding {src}" + (f" for {seconds:g}s" if seconds else ""), file=sys.stderr)
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=timeout + (seconds or 0))
        except subprocess.TimeoutExpired:
            print(f"ffmpeg timed out on {src}", file=sys.stderr); sys.exit(EX_REMOTE)
        if p.returncode != 0 and not p.stdout:
            print(f"ffmpeg failed: {p.stderr.decode('utf-8', 'replace').strip()[:400]}", file=sys.stderr); sys.exit(EX_REMOTE)
        raw = p.stdout
    a = array.array("h")
    a.frombytes(raw[:len(raw) // 4 * 4])
    if sys.byteorder == "big":
        a.byteswap()
    return a


def loud(l_db, r_db, d_db):
    """One slice's verdict: silent · L=R · L · R · both."""
    ls, rs = l_db < SILENT_DB, r_db < SILENT_DB
    if ls and rs:
        return "silent"
    if not ls and not rs and d_db < SAME_DB:
        return "L=R"
    if rs:
        return "L"
    if ls:
        return "R"
    return "both"


def audio_slices(a, slice_s=0.2, rate=RATE):
    """Interleaved stereo samples → per-slice rows and a summary over the whole capture."""
    per = max(1, int(rate * slice_s))
    n = len(a) // 2
    rows, tl, tr, td, tlr = [], 0, 0, 0, 0
    for i in range(n // per):
        sl = sr = sd = slr = 0
        for j in range(2 * i * per, 2 * (i + 1) * per, 2):
            l, r = a[j], a[j + 1]
            sl += l * l; sr += r * r; slr += l * r
            d = l - r; sd += d * d
        tl += sl; tr += sr; td += sd; tlr += slr
        corr = slr / math.sqrt(sl * sr) if sl and sr else None
        L, R, D = db(sl, per), db(sr, per), db(sd, per)
        rows.append({"t": round(i * slice_s, 3), "L_db": round(L, 1), "R_db": round(R, 1), "LmR_db": round(D, 1),
                     "corr": None if corr is None else round(corr, 3),
                     "L_silent": L < SILENT_DB, "R_silent": R < SILENT_DB, "loud": loud(L, R, D)})
    k = len(rows) * per
    counts = {}
    for r in rows:
        counts[r["loud"]] = counts.get(r["loud"], 0) + 1
    L, R, D = db(tl, k), db(tr, k), db(td, k)
    summary = {"seconds": round(n / rate, 2), "slices": len(rows), "slice_s": slice_s,
               "L_db": round(L, 1), "R_db": round(R, 1), "LmR_db": round(D, 1),
               "corr": round(tlr / math.sqrt(tl * tr), 3) if tl and tr else None,
               "L_silent": L < SILENT_DB, "R_silent": R < SILENT_DB, "loud": counts}
    return rows, summary


def cmd_audio(a):
    pcm = pcm_of(a.target, a.seconds, a.track, a.host, a.timeout)
    rows, summ = audio_slices(pcm, a.slice)
    if not rows:
        print("no audio decoded (no audio track, or the capture is shorter than one slice)", file=sys.stderr); sys.exit(EX_REMOTE)
    if a.json:
        print(json.dumps({"target": a.target, "summary": summ, "slices": rows}, ensure_ascii=False)); return
    print(f"# {a.target}  audio track {a.track}  {summ['seconds']}s in {summ['slices']} slices of {a.slice:g}s")
    if a.verbose:
        print(f"{'t':>6} {'L dB':>7} {'R dB':>7} {'L-R dB':>7} {'corr':>6}  loud")
        for r in rows:
            c = "" if r["corr"] is None else f"{r['corr']:.2f}"
            print(f"{r['t']:6.1f} {r['L_db']:7.1f} {r['R_db']:7.1f} {r['LmR_db']:7.1f} {c:>6}  {r['loud']}")
    sil = lambda x: "silent" if x else "sounding"
    print(f"L {summ['L_db']:.1f} dB ({sil(summ['L_silent'])}) · R {summ['R_db']:.1f} dB ({sil(summ['R_silent'])}) · "
          f"L−R {summ['LmR_db']:.1f} dB · corr {summ['corr'] if summ['corr'] is not None else '-'}")
    print("slices by loud channel: " + " · ".join(f"{k} {v}" for k, v in sorted(summ["loud"].items(), key=lambda kv: -kv[1])))


def main():
    ap = argparse.ArgumentParser(
        description="What a stream actually carries: PMT/PCR/PID and codec, and which channel sounds, read off the wire.",
        epilog="Quote the target: an SRT or UDP URL's `&` parameters are shell separators otherwise, "
               "and the URL is silently truncated. The line printed before each read shows what arrived.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe", help="one stream — HLS playlist, .ts file, srt:// udp:// rtp:// rtmp://")
    p.add_argument("target")
    p.add_argument("--host", help="box ip to pull from when the URL is a listener/bind address (srt)")
    p.add_argument("--seconds", type=float, default=8, help="how much of a live feed to look at (default 8)")
    p.add_argument("--timeout", type=float, default=45, help="give up after this many seconds (default 45)")
    p.add_argument("--full", action="store_true", help="every field ffprobe returned, grouped")
    p.add_argument("--frames", action="store_true", help="also read packets: GOP length and observed bitrate")
    p.add_argument("--segment", choices=["first", "last", "newest"], default="last",
                   help="which HLS segment to read (default: one back from newest — complete, still in window)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("diff", help="two streams, field by field")
    p.add_argument("a"); p.add_argument("b")
    p.add_argument("--host", help="box ip for a listener/bind address (applies to both)")
    p.add_argument("--seconds", type=float, default=8)
    p.add_argument("--timeout", type=float, default=45)
    p.add_argument("--segment", choices=["first", "last", "newest"], default="last")
    p.add_argument("--only-diffs", action="store_true", dest="only_diffs",
                   help="print only the rows that differ — that list is the gap")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("audio", help="which channel carries the sound, per slice: RMS L/R, L−R, correlation, silence")
    p.add_argument("target", help=".ts file, .pcm/.s16 (48 kHz stereo s16le), or a live srt:// udp:// URL")
    p.add_argument("--seconds", type=float, help="how much to decode (a live URL needs it; default: the whole file)")
    p.add_argument("--slice", type=float, default=0.2, help="slice length in seconds (default 0.2)")
    p.add_argument("--track", type=int, default=0, help="which audio track (default 0)")
    p.add_argument("--host", help="box ip for a listener/bind address (srt)")
    p.add_argument("--timeout", type=float, default=60)
    p.add_argument("-v", "--verbose", action="store_true", help="one line per slice")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.cmd == "audio" and is_network(a.target) and not a.seconds:
        ap.error("a live URL needs --seconds")
    {"probe": cmd_probe, "diff": cmd_diff, "audio": cmd_audio}[a.cmd](a)


if __name__ == "__main__":
    main()
