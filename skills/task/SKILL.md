---
name: task
description: Run one piece of implementation work Evan owns end to end — read the ticket first-hand, locate the repo in the map, create an isolated worktree with a write tier, delegate to the area's own agent stack (headless session in the counterpart's repo) or implement under the repo's own rules, verify artefacts and evidence, record the ledger. Use for "do MH-xxxx", "implement this", "改 app 代码", "按 mediahub-agent 的规矩做", or any request to change code in a repo Evan does not own.
user-invocable: true
---

# /ela:task <KEY> <repo> [--lane <branch>] — implement under the owner's rules, from here

Self-contained. Arguments: a Jira key, the target repo's directory name as it appears in the map,
optional base lane override.

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

## 0 — site + ticket
Read `~/.claude/ela/site.json` (`projects`, `map`, `env`, `runtime` — default `~/ela-runtime`).
`python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/jiraread.py" --env-file <env> <KEY> --deep` → note
type, status, parent, subtasks, linked tickets, the layer token in the title (`[App]` `[UI]` …).

## 1 — locate
Read `<map>/host.yaml`; find `repos[name == <repo>]`. Missing → run `/ela:map` first, do not
guess. Take: `path` (base clone), `area`, `governance`, `stack` (team-stack only), `federate`,
`owner`, and the area's lane for this repo (from the counterpart's registry when it has one —
`mediahub-agent/workspace.json`; else the repo's default branch). `--lane` overrides.

## 2 — worktree + tier
```bash
WT=<runtime>/<key-lower>/<repo>          # last path segment == repo dir name (their guards match on it)
git -C <path> fetch origin --prune
git -C <path> worktree add -b evan/<key-lower> "$WT" origin/<lane>
```
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
cd <stack> && \
JIRA_ENV_FILE=<env> SLACK_ENV_FILE=<env> OUTLINE_ENV_FILE=<env> \
claude -p --session-id "$SID" --agent <their router, e.g. CodeAgent> \
  --add-dir "$WT" --output-format stream-json \
  --allowedTools "<preset for tier>" \
  "$(cat <<PROMPT
Task: <KEY> — <title>. Jira: <url>.
Target worktree (the ONLY place code may change): $WT   (branch evan/<key>, from origin/<lane>)
Follow this repo's own workflow end to end for this repo — every gate, artefact and write-back your
rules require (change directory, contract if any, KB, QA report, go-live checklist). Work on the
worktree path above, not on the base checkout.
Do not git push. Do not post to Slack or write to Jira. When you need a human decision, print a line
starting with QUESTION: and stop.
When done, print DONE: followed by the list of artefacts you created (absolute paths) and the exact
test command + result line.
PROMPT
)"
```
Allowlist presets (`--allowedTools`):
- `draft-only`: `Read,Grep,Glob,Edit,Write,MultiEdit,Agent,Bash(node *),Bash(npm *),Bash(npx *),Bash(mvn *),Bash(python3 *),Bash(git status*),Bash(git diff*),Bash(git log*),Bash(git add *),Bash(git commit *),Bash(git worktree list*),Bash(git show*),Bash(git branch*),Bash(ls*),Bash(cat*),Bash(find*),Bash(grep*),Bash(rg*)`
- `branch-only`: the above + `Bash(git push -u origin evan/*)`
Never `--dangerously-skip-permissions`.

**Loop:** stream the output. On `QUESTION:` → show Evan verbatim, take his answer, then
`claude -p --resume "$SID" --agent <router> --add-dir "$WT" --allowedTools "<same>" "<answer>"`.
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
