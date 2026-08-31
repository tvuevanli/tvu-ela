---
name: task
description: Run one piece of implementation work Evan owns end to end — read the ticket first-hand, locate the repo in the map, create an isolated worktree with a write tier, delegate to the area's own agent stack (headless session in the counterpart's repo) or implement under the repo's own rules, verify artefacts and evidence, record the ledger. Use for "do MH-xxxx", "implement this", "改 app 代码", "按 mediahub-agent 的规矩做", or any request to change code in a repo Evan does not own.
user-invocable: true
---

# /ela:task <KEY | --source "…"> <repo> [--lane <branch>] — implement under the owner's rules, from here

Self-contained. Arguments: a Jira key **or** a source (a Slack permalink, or a verbal one-liner —
a ticket is not required to start; see §0), the target repo's directory name as it appears in the
map, optional base lane override.

## Invariants
- **Read first-hand.** The ticket is read with `/ela:jira`; the repo is located from the map. No
  step relies on a counterpart's description of either.
- **One task, one worktree, one child session.** Never edit a base clone. Pathspec commits only.
- **Delegate by governance, never by convenience.** A team-stack repo is implemented by *their*
  stack — ela supplies task, worktree and permission envelope, and verifies. ela does not "just do
  it" because it would be faster.
- **Permission is the tier.** The child session can only do what its `--allowedTools` list permits.
  `git push` is never in that list below `branch-only`. This is the enforcement; no prose is.
- **Confirmations come to Evan.** When the child needs a decision (proposal approval, contract
  `confirmed`, a scope question), it stops and prints it; ela relays to Evan and resumes the same
  session. ela never answers on Evan's behalf.
- **No outward writes from inside.** Slack posts, Jira comments, pushes: the child is told not to;
  the allowlist makes sure. (Exception: hooks the counterpart's own repo runs, e.g. KB index
  regeneration — those are their rules on their files.)
- **Evidence over report.** "Tests pass" is verified against the target's own standard (see §4).

## 0 — site + source
Read `~/.claude/ela/site.json` (`projects`, `map`, `env`, `runtime` — default `~/ela-runtime`).
The task id is `<key-lower>` when a Jira key is given, else a short kebab slug from the source.

**With a Jira key:**
`python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py" --env-file <env> read <KEY> --deep > <runtime>/<id>/ticket.md`
→ note type, status, parent, subtasks, linked tickets, the layer token in the title (`[App]` `[UI]` …).
**Route up before going down:** if the ticket plainly crosses layers/areas and has neither subtasks
nor a plan in `<records>/breakdowns/`, stop and point to `/ela:breakdown <KEY>` — implementing one
slice of an unsplit requirement is how scope drifts.

**Without a ticket** (`--source`): a ticket is not a precondition — counterparts accept a recorded
source of type `jira / slack / verbal` (mediahub-agent `CLAUDE.md` §OpenSpec: verbal = one-line
description + date, never empty). A Slack permalink → dump the thread with the slack capability to
`<runtime>/<id>/source.md`; a verbal one-liner → write it there with today's date. The delegation
prompt's first line then cites `Source: slack <permalink>` or `Source: verbal — "<one-liner>"
(recorded YYYY-MM-DD)` instead of a Jira url. If the work later grows other people's lanes, create
the ticket then (`jira.py create`, confirm-gated) — coordination is what tickets are for.

Either way the dump file is handed to the child by path: `--agent X` limits the child to X's
`tools:` frontmatter (mediahub-agent's agents have no Skill tool), so the child **cannot read Jira
itself**. A verbatim dump by path is not paraphrase — it satisfies their "paths, not retelling" rule.

## 1 — locate
Read `<map>/host.yaml`; find `repos[name == <repo>]`. Missing → run `/ela:map` first, do not
guess. Take: `path` (base clone), `area`, `governance`, `stack` (team-stack only), `federate`,
`owner`, and the area's lane for this repo (from the counterpart's registry when it has one —
`mediahub-agent/workspace.json`; else the repo's default branch). `--lane` overrides.

## 2 — worktree + tier
Where the worktree lives is decided by governance — **the counterpart's convention wins**:

| governance | worktree path | why |
|---|---|---|
| team-stack | `<area root>/<repo>-<key-lower>` e.g. `~/projects/mh-app/media-hub-front-mh-2191` | mediahub-agent's own convention (`<service>-<suffix>` in the workspace root): its `resolve-workspace.cjs` lists only worktrees under that root, its `feign-contract-guard` matches the `<service>-` prefix, and CodeAgent accepts only paths that script reports |
| repo-local / bare | `<runtime>/<key-lower>/<repo>` (site `runtime`, default `~/ela-runtime`) | nobody there constrains location; keep ela's own place |

```bash
git -C <path> fetch origin --prune        # also before any read-only analysis: base clones lag origin
git -C <path> worktree add -b evan/<key-lower> "$WT" origin/<lane>
```
The base clone is never `--add-dir`ed to the child, so it is structurally unwritable from there —
isolation by permission scope, not by instruction. Remove the worktree at close so the counterpart's
root does not accumulate task dirs.

Tier for the repo (from `ela-knowledge/decisions/` or the area's registry; default **draft-only**):

| tier | child may | never |
|---|---|---|
| `draft-only` | edit, run tests, commit in `$WT` | push |
| `branch-only` | + `git push -u origin evan/*` | shared lanes, MRs |
| `mr-gated` | + open an MR naming the human owner | merge |

Record `{key, repo, worktree, branch, base_ref, tier, owner, governance}` to
`<records>/ledger/<key-lower>.json` with `status: prepared` **before** delegating.

## 3 — delegate by governance

### team-stack (e.g. `mh-app` → `mediahub-agent`)
The child session starts **in the counterpart's repo**, so their `CLAUDE.md`, agents, skills and
hooks load; the worktree is attached with `--add-dir`.

```bash
SID=$(uuidgen)
cat > "$WT/../prompt.txt" <<PROMPT
Task: <KEY or slug> — <title>. Source: <Jira url | slack <permalink> | verbal — "<one-liner>" (recorded YYYY-MM-DD)>.
Verbatim source dump (read it first): <runtime>/<id>/ticket.md (or source.md)
Target worktree (the ONLY place code may change): $WT   (branch evan/<key>, from origin/<lane>; it is a git worktree of the base checkout — run node scripts/resolve-workspace.cjs and you will see it listed with its owner)
Follow this repo's own workflow end to end for this repo — every gate, artefact and write-back your
rules require (change directory, contract if any, KB, QA report, go-live checklist). Work on the
worktree path above, not on the base checkout.
Do not git push. Do not post to Slack or write to Jira. When you need a human decision, print a line
starting with QUESTION: and stop.
When done, print DONE: followed by the list of artefacts you created (absolute paths) and the exact
test command + result line.
PROMPT
cd <stack> && \
JIRA_ENV_FILE=<env> SLACK_ENV_FILE=<env> OUTLINE_ENV_FILE=<env> \
claude -p --session-id "$SID" --agent <their router, e.g. CodeAgent> \
  --add-dir "$WT" --output-format stream-json \
  --allowedTools "<preset for tier>" \
  < "$WT/../prompt.txt"
```
**The prompt goes in on stdin.** `--allowedTools` is variadic and will swallow a trailing positional
prompt as a tool name (observed: "Input must be provided either through stdin or as a prompt
argument"). Never put the prompt after `--allowedTools`.
```
Permission envelope = `--allowedTools` **plus** `--disallowedTools` (deny wins). Prefix patterns must
match the real command shape — `Bash(git log*)` does **not** match `git -C <path> log`, so git is
granted broadly and pushes are denied explicitly:

- `draft-only`:
  `--allowedTools "Read,Grep,Glob,Edit,Write,MultiEdit,Agent,Bash(git *),Bash(node *),Bash(npm *),Bash(npx *),Bash(mvn *),Bash(python3 *),Bash(ls*),Bash(cat*),Bash(find*),Bash(grep*),Bash(rg*),Bash(wc*),Bash(head*),Bash(sed -n*)"`
  `--disallowedTools "Bash(git push*),Bash(git -C * push*),Bash(git remote add*),Bash(git remote set-url*)"`
- `branch-only`: same, but the disallow list drops `push` and the prompt states the only branch is `evan/<key>`
  (a pattern cannot express "push only this branch"; §4 verifies no other ref moved).
- read-only analysis (no worktree, e.g. their `jira-analyst`): drop `Edit,Write,MultiEdit`; keep the git deny list.
Never `--dangerously-skip-permissions`.

**Loop:** stream the output. On `QUESTION:` → show Evan verbatim, take his answer, then
`echo "<answer>" | claude -p --resume "$SID" --agent <router> --add-dir "$WT" --allowedTools "<same>"`.
On `DONE:` → §4. If the child cannot proceed headless (interactive-only step), print the **handoff
block** — worktree, branch, tier, owner, `cd <stack> && claude` + `/add-dir $WT` — and stop.

### repo-local / bare
Same mechanism, different start directory: the child starts **in the worktree**, so the repo's own
`CLAUDE.md` / `.claude/settings.json` / `AGENTS.md` load. No `--agent` (or ela's implementer once
one exists). Same prompt shape, same presets, same loop. For `bare`, the prompt adds ela's defaults:
match existing style, tests beside the change, conventional commit citing the key.

### read-only
Refuse at §1 with the reason.

## 4 — verify (ela does this itself; never from the child's DONE line alone)
- **Isolation:** `git -C <path> status --porcelain` is unchanged from before; all commits are in
  `$WT` on `evan/<key>` (`git -C $WT log origin/<lane>..HEAD`).
- **No push:** `git ls-remote --heads origin evan/<key>` is empty unless tier allows.
- **Artefacts by governance:** team-stack → the artefacts their workflow names exist (for
  `mediahub-agent`: `openspec/changes/<change>/{proposal.md,tasks.md}` plus `contract.md` when
  inter-service, `qa-report.md`, `go-live-checklist.md`; `node scripts/kb-index.cjs --check` exits 0).
  repo-local → whatever `federate` files require (spec pairing, comment tags…).
- **Evidence by the target's standard:** frontend → the jest `Tests:` summary line; Java → a fresh
  `target/surefire-reports/` with `Tests run > 0`; .NET → `dotnet test` summary. `BUILD SUCCESS`,
  `npm run build` and lint are **not** evidence. Missing → status `unverified`, say so plainly.

## 5 — ledger
Update `<records>/ledger/<key-lower>.json`: `status` (`done` | `unverified` | `blocked`),
`session_id`, `commits[]`, `artefacts[]`, `evidence{command,result}`, `questions[]` (asked/answered),
`finished`. Commit it in the records repo.

## 6 — deliver per tier
- `draft-only`: show `git -C $WT diff origin/<lane>` summary and the artefact list; **stop** — push or
  MR is Evan's call, done by Evan.
- `branch-only`: pushed `evan/<key>`; report the branch.
- `mr-gated`: pushed + MR URL naming `owner`.
Then `git -C <path> worktree remove "$WT"` only when Evan says the task is closed.
