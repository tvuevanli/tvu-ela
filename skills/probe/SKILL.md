---
name: probe
description: Read-only MediaHub code investigation — a bug to root cause with file:line, or `probe how <mechanism>`. Use for "deep check", "查一下根因", "看代码找原因", "why does copier …", "MH-xxxx 到底怎么回事", "这个字段哪来的", "命令行参数什么意思", "上报的数据是什么", "前后端模型", "谁调用谁", "这段逻辑在哪", "how does X work in the code", or when routing is not enough.
user-invocable: true
---

# /ela:probe <ticket | symptom> | /ela:probe how <mechanism> — a bug in, a root cause with file:line out

Self-contained. Argument: a Jira key or URL, a graph or process id, or a described symptom. Read-only
throughout: code is read, never changed; Jira and Slack are read, and every proposed comment is a
draft until Evan says post.

The `how` form takes a mechanism named in the owner's words (a command line, a reported field, a
status model, "who calls whom") and no ticket. It runs §0–§3 as written, skips the drafted comments
of §4, and ends with (a) the mechanism chain — each hop with file:line at the commit read, values and
defaults where the code fixes them, and what the chain does NOT assert — and (b) a `knowledge/` draft
written to `<runtime>/drafts/<slug>.md` in elak's house style (front matter `verified`, `source` =
repo@sha file:line only, no session or transcript cited, no names), for the owner to admit with
"记下来" (knowledge/README's one-year test).

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
Read `~/.claude/ela/site.json` → `env`, `map`, `elak`, `published`.
```bash
JIRA="python3 ${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py --env-file <env>"
GRAPH="python3 ${CLAUDE_PLUGIN_ROOT}/skills/graph/graph.py --env-file <env>"
MAP="python3 ${CLAUDE_PLUGIN_ROOT}/skills/map/map.py"
TEAM="python3 ${CLAUDE_PLUGIN_ROOT}/skills/team/team.py --env-file <env>"   # or: ela who … · ela team areas
```
The owner §3 names is read at that moment, never recalled: the area from
`<published>/knowledge/products/mediahub/team/layer-classification.md`, the person from `$TEAM who
<name|email|Uxxx|accountId>` (exit 3 = not in the roster — say so, never compose a name) or `$TEAM
areas` for who to ask first; both read `<published>`, falling back to elak's private source on the
office machine. `<map>/services.yaml` still gives image → owners → repos.

## 1 — facts, in this order
1. **The report.** `$JIRA read <key> --deep`: reporter's evidence verbatim — ids, versions, env,
   what was ruled out. If the ticket names a graph, process or object id, or the reporter pasted a
   graph JSON, that is the anchor.
2. **The runtime.** `$GRAPH resolve <id>`: env, phase, nodes with type · process · image · box.
   `$GRAPH process <pid>` on the suspect node: status, error rates, container, shm. Write down the
   image tags — they pin the version under investigation. For the `how` form this hop is optional:
   run it when the owner names an id; otherwise say "not read at runtime" in the output.
3. **The implicated service.** `$MAP find <image|process type|service word>` → owners and repos with
   local paths. No repo → `$MAP probe media/<name> media/imatrix/prj/<name>` and, if it answers,
   `$MAP clone <path>` (GitLab, LAN, placed at `<code>/<alias>/<remote path>`). If nothing answers, the service
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
- Record what the probe **established**, not that it ran — drafted here, written on Evan's word: the conclusion and its paths go where the
  knowledge base's placement test sends them (elak `blueprint/principles.md` P1) — a platform
  finding to `knowledge/platform/<component>/`, an ela finding to `blueprint/`. A dated file of "what
  the probe did" is a diary and is not kept; the agentic-observability `investigation-*.md` files are
  a format precedent for the write-up, not a licence to keep the run.
- Drafts, each ≤ 8 lines, each a separate confirm: one for the reporter/product (what happens and
  what they can do now, no code), one for the owner (the mechanism, file:line, the question to
  decide). `$JIRA comment <key> --text …` shows the dry-run; `--apply` only after Evan's word.

## 5 — what this skill does not do
Change code, run builds, start or stop processes, post anywhere, or clone from GitHub when the LAN
GitLab has the repo (`map.py` clones GitLab-first; GitHub mirrors are read-only reference).
`probe how` does not price findings (that is arch) and does not decide support (that is feasible).
