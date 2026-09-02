---
name: probe
description: Deep, read-only investigation of a MediaHub bug — from a ticket or symptom to the implicated service, its code and the root cause with file:line, then drafted comments for the reporter and the owner. Reads Jira, the graph (UR), the service table and the code first-hand; clones missing code; never edits anything. Use for "deep check", "查一下根因", "看代码找原因", "why does copier …", "MH-xxxx 到底怎么回事", or when routing alone is not enough.
user-invocable: true
---

# /ela:probe <ticket | symptom> — a bug in, a root cause with file:line out

Self-contained. Argument: a Jira key or URL, a graph or process id, or a described symptom. Read-only
throughout: code is read, never changed; Jira and Slack are read, and every proposed comment is a
draft until Evan says post.

## Invariants
- **Code before people.** The 2026-09-02 MH-3568 investigation found the cause in `addScteStream`
  defaulting to 1 only because it read the copier code instead of asking. Route only after the code
  has been read, or when the code cannot be reached — and say which.
- **Attribution by image, never by node name.** A graph node's `metadata.name` is a slot label and
  misleads (`input_srt_decoder_*` is not the SRT ingress). The image is the codebase fingerprint; the
  service table maps image → process types → owners → repos.
- **The checkout may lie about production.** Compare the image tag the graph reports with the
  checkout's branch/tag before trusting a line number; say when they differ.
- **Every claim carries a path.** file:line for code, key for Jira, permalink for Slack, the
  `graph.py` line for runtime facts. A claim without a path is a hypothesis and is labelled one.
- **Analyst for the reading, session for the judgment.** Code reading goes to the read-only analyst
  agent with specific questions; the synthesis, the product reading and the drafts stay here.

## 0 — bind
Read `~/.claude/ela/site.json` → `env`, `map`, `records`, `map_sources.team_roster`.
```bash
JIRA="python3 ${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py --env-file <env>"
GRAPH="python3 ${CLAUDE_PLUGIN_ROOT}/skills/graph/graph.py --env-file <env>"
MAP="python3 ${CLAUDE_PLUGIN_ROOT}/skills/map/map.py"
```

## 1 — facts, in this order
1. **The report.** `$JIRA read <key> --deep`: reporter's evidence verbatim — ids, versions, env,
   what was ruled out. If the ticket names a graph, process or object id, or the reporter pasted a
   graph JSON, that is the anchor.
2. **The runtime.** `$GRAPH resolve <id>`: env, phase, nodes with type · process · image · box.
   `$GRAPH process <pid>` on the suspect node: status, error rates, container, shm. Write down the
   image tags — they pin the version under investigation.
3. **The implicated service.** `$MAP find <image|process type|service word>` → owners and repos with
   local paths. No repo → `$MAP probe media/<name> media/imatrix/prj/<name>` and, if it answers,
   `$MAP clone <path>` (GitLab, LAN, placed by the mds layout rule). If nothing answers, the service
   goes to the routing step as "code not reachable" and the absent list gets an entry.
4. **The version.** `git -C <path> log -1 --format='%h %ad'` and tags vs the image tag from step 2.

## 2 — read the code
Spawn the read-only analyst with the repo paths and **specific questions**, not "look for the bug":
which function decides the behaviour the reporter saw; what its inputs and defaults are; where the
default is set (config file, plugin xml, compile-time); what upstream would have to provide for the
other branch; what changed recently in that area (`git log -S`). Ask for file:line per answer and
the exact snippet. Read the answers against the report: does the code path explain every observed
fact? Anything unexplained is a second question, not a footnote.

## 3 — conclude
Write, in this shape:
- **Root cause** — one sentence, then the mechanism as a chain (`source → … → symptom`), each hop with
  its file:line or `graph.py` fact.
- **Why it is designed that way** — read the intent before calling it a bug (the gate's rule on
  fences). Name the trade-off the default encodes.
- **What is affected** — who else sees this; is the reporter a special case or the first to notice.
- **Options** — the fix the reporter needs now, the product fix, the "real" fix; cost of each; which
  needs a product decision and from whom.
- **Owner and check** — name and the exact discriminating check, via `/ela:route` when the layer is
  not obvious.

## 4 — record and draft
- Record: `records/<date>-probe-<key>.md` in the knowledge base with the conclusion and its
  paths — Evan says "记下来". The agentic-observability `investigation-*.md` files are the format
  precedent.
- Drafts, each ≤ 8 lines, each a separate confirm: one for the reporter/product (what happens and
  what they can do now, no code), one for the owner (the mechanism, file:line, the question to
  decide). `$JIRA comment <key> --text …` shows the dry-run; `--apply` only after Evan's word.

## 5 — what this skill does not do
Change code, run builds, start or stop processes, post anywhere, or clone from GitHub when the LAN
GitLab has the repo (`map.py` clones GitLab-first; GitHub mirrors are read-only reference).
