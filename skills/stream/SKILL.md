---
name: stream
description: What a stream actually carries, read off the wire — the MPEG-TS PID table (PMT, PCR, per-stream PID), codec, resolution and sample rate of an HLS output, a .ts segment, an SRT or UDP endpoint; and the field-by-field difference between two streams. Use when a question turns on what a MediaHub output really contains rather than what it was configured to contain — "PID 生效了吗", "输出是什么编码", "这两条流差在哪", verifying a copier change, or checking a customer's report of an output against the profile that produced it.
user-invocable: true
---

# /ela:stream — a URL in, the PID table out

Self-contained. Read-only: it downloads and probes, and writes nothing anywhere.

## Why it exists
A field can be set in an encoding profile, be delivered in the copier's `CreateInstance` call, and
still never reach the output — the copier's HLS branch drops every PID option it is handed. Code
says what should happen; only the stream says what did. Any claim about a MediaHub output's PIDs
that has not been read off the wire is a hypothesis.

## 0 — bind
```bash
STREAM="python3 ${CLAUDE_PLUGIN_ROOT}/skills/stream/stream.py"
```
Needs `ffprobe` on PATH. No credentials: the outputs this reads are the ones a viewer can reach.

```bash
$STREAM probe <target>       # PMT · PCR · PID table · codec
$STREAM diff  <a> <b>        # the two, field by field
```
Both take `--json`, `--segment first|last|newest` (which HLS segment), `--host` (below),
`--seconds` (how much of a live feed to look at, default 8) and `--timeout` (default 45).

## What a target can be, and what it can answer

| target | pulled how | PID table |
|---|---|---|
| `*.m3u8` | playlist resolved, one segment fetched | **yes** — segments are MPEG-TS |
| `*.ts` file | read | **yes** |
| `srt://` `udp://` `rtp://` `rist://` | live pull, bounded by `--seconds` | **yes** |
| `rtmp://` `rtmps://` | live pull | **no** — FLV has no programs and no stream ids |
| `rtsp://` | live pull | **no** — bare elementary streams over RTP |

PMT, PCR and per-stream PIDs exist **only in an MPEG-TS multiplex**. On a container that has none
the table prints the codecs and says so rather than showing blanks — "no PIDs" there is the
container's nature, never a finding about configuration.

Out of reach entirely, and named so a gap is not mistaken for a fault: **NDI** (needs the vendor SDK;
no NDI demuxer in a stock build) and **ISSP** (TVU's own transport). A graph output of either kind
cannot be verified this way — read the process's command line instead.

## Depth

| | costs | gives |
|---|---|---|
| default | one header read | programs, service/provider, PID table, codec, language, scan, HDR |
| `--full` | same read | every field ffprobe returned, per stream, grouped |
| `--frames` | a second read over `--seconds` | keyframe spacing (measured GOP) and observed video bitrate |

Every figure maps to something an encoding profile sets — resolution, frame rate, profile/level,
GOP, bitrate, audio codec/rate/channels/language, PIDs, service name — so a profile can be checked
against what it actually produced, field by field. `diff` does that between two outputs.

## What `diff` is for

Two streams and the list of what is not the same between them. The uses it was built from, all
questions that otherwise take a day of reading:

- **Same profile, two outputs.** One encoding profile drives an HLS graph and an SRT graph; the diff
  says which output honours it. This is how a "we support PIDs" claim is tested per output type.
- **Before and after a change.** Probe an output, keep the JSON, probe it again after the fix — the
  diff is the acceptance test, and it names any field the change moved that nobody asked it to.
- **Target against reality.** Build a reference locally with the values a customer asked for, then
  diff it against what the pipeline produces. With `--only-diffs` that output *is* the gap list.
- **Source against output.** A complaint that a pipeline changed something is answered by diffing
  what went in against what came out, rather than by arguing about what it should have done.

Streams are paired **within kind** — video with video, audio 0 with audio 0 — never by position: two
outputs of one source may order their streams differently, and a video compared against an audio is
noise, not a finding. A row present on one side only shows as `—`, which is itself the answer when
one output dropped a track.

**What a target cannot answer is printed, with the reason**, under `not available for this target`.
Protocol and container each remove different things: a live pull has no duration, cannot be seeked
and gives a windowed bitrate estimate; a non-TS container has no PIDs and no service tags however it
was transported.

## Invariants
- **A live HLS window is seconds wide.** A media playlist typically lists 5 × 2s segments, so
  resolving a segment in one call and fetching it in the next races the window and 404s. `probe`
  resolves and downloads in one pass — never hand-assemble the two steps.
- **Default is one back from newest**, not newest: the newest segment may still be being written.
  `--segment newest` overrides when the stream has stopped and the window is frozen.
- **A TS stream's `id` is its PID.** ffprobe prints it hex for mpegts; the table shows both, because
  the profile and the app speak decimal and the muxer options speak hex.
- **PCR PID is not a setting.** The muxer binds it to the video stream's PID (`mpegtsenc.c`
  `select_pcr_streams`). Reading PCR ≠ video PID on a TVU output means something is wrong, not that
  someone configured it.
- **What is probed is named.** For a playlist the output prints the segment it actually read, so a
  claim can be re-checked against the same bytes.
- **Quote the target.** Every SRT and UDP URL carries `&` query parameters, which an unquoted shell
  argument splits: the command is backgrounded and a URL shorter than the one typed is probed. It
  usually still connects, so the result looks right and is not. Each read prints the target it
  received to stderr before it waits — that line is where a truncation shows.
- **A listener address is not a pull address.** The copier publishes
  `srt://0.0.0.0:PORT?mode=listener` — where the sender binds, not somewhere to connect. `probe`
  refuses it and asks for `--host <box ip>`, then connects as a caller. The box ip comes from
  `/ela:graph`, never from the URL.
- **A live feed never ends, so the look is bounded.** `--seconds` caps both the analysis window and
  the read timeout; a listener with no sender fails in seconds instead of hanging. A short window
  costs detail — resolution may come back `0x0` — so raise it when the answer needs more than PIDs.
- **One segment is not the stream.** PIDs are assigned per segment muxer; a change that lands in one
  segment lands in all. Confirm across two segments before calling a fix verified.

## Where it fits
`/ela:feasible` uses it as the last of the five checkpoints — the runtime evidence without which a
"supported / not supported" verdict stays a reading of the code. `/ela:probe` uses it when a bug
report is about what an output contains.
