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
$STREAM probe <m3u8 | file.ts | srt://… | udp://…>   # PMT · PCR · PID table · codec
$STREAM diff  <a> <b>                                 # the two, field by field
```
Both take `--json`. `--segment first|last|newest` picks which HLS segment to read.

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
- **One segment is not the stream.** PIDs are assigned per segment muxer; a change that lands in one
  segment lands in all. Confirm across two segments before calling a fix verified.

## Where it fits
`/ela:feasible` uses it as the last of the five checkpoints — the runtime evidence without which a
"supported / not supported" verdict stays a reading of the code. `/ela:probe` uses it when a bug
report is about what an output contains.
