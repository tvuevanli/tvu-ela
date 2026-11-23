---
name: grid
description: A Grid source end to end, read-only. Use for a disconnected Grid input or a grid_decoder graph.
user-invocable: true
---

# /ela:grid — a Grid source, link by link

A Grid source crosses three owners: the sender (a LinuxR box or a Pack, whose box belongs to the customer and whose
software belongs to the R team), GCS (the web team's Grid Control Server, which pairs sources to receivers), and the
receiver, which is a LinuxR or, for MediaHub, the `grid_decoder` (playeroftvu). `ela grid` reads every link it can
reach, labels each line **checked**, **inferred** or **not checked**, and names the first link that is down.

```
ela grid <object id>          the fullest answer: includes the MediaHub graphs and the decoder process
ela grid <sender name>        exact GCS device name (the sender's, e.g. R_1D85, not the MediaHub source name)
ela grid <16-hex PID>         every enabled encoder of that sender
ela grid <32-hex source id>   PID + resource (…01 pack · …02 SDI · …03 MediaHub)
        --region cn · --json
```

## How to use the answer

- **Quote the labels.** A checked line is a fact read now, from the source named in brackets. An inferred line says
  what it rests on. A not-checked line is a gap to name, never one to fill: the sender's **input signal** (format,
  presence) is visible only in the sender's own logs. HEKAYAT1 on 2026-11-16 broke exactly there, on an RGB SDI feed
  the sender's dcap2 did not handle. When every checked link is up and the stream is still bad, the next stop is the
  sender's owner (the R team for a LinuxR sender), with the PID and the encoder line.
- **A stale pair is not a route.** GCS keeps pairs to receivers silent for years. They are flagged and kept out of
  the verdict. A MediaHub source is pulled by its decoder without needing a live GCS pair.
- **A type-R sender's status** in Command Center is that box's own receiver mode. "live" there means it is
  receiving something itself; it does not mean that Grid is sending.
- **The decoder's own log** is the next hop on the MediaHub side: `ela logs loki --pid <process>`. Its owner and the
  copier's are in `ela find grid`.

## Rules

- Reads only. The script calls four endpoints, all of them open by design. GCS `getXmlFile?type=r` and every
  `/noLogin/*` route are writes (they record the caller as a receiver), and the script never calls them. Do not
  call them by hand either.
- Never connect to the customer's live output to "see" the stream (MH-4049). A stream read goes to `ela stream`
  on a MediaHub-side URL only.
- GCS's logged-in views (Relay links, the receivers pulling right now) need user-auth service "Grid Server", which
  the owner's account does not have. Say so instead of working around it.

The reading behind this is the vault plan `ela/2026-11-23-plan-grid-source.md`. LinuxR's side is in
`<elak>/knowledge/platform/linuxr/`.
