---
name: verify
description: Verify a ticket in the product in a real browser on a named lane, read-only, the version panel as proof; a report for the owner, a short Jira comment on confirm. Use for "auto-test MH-xxxx", "在浏览器里验一下这票".
user-invocable: true
---

# /ela:verify <KEY> [--lane prod-3 | prod-8 | qa-cn3 …] — a ticket checked in the product, with proof

Replies to the owner follow the working preferences (Chinese in conversation unless he asks otherwise); the
English of this file is not the language of the answer.

Self-contained. Read-only over the product: the browser session is the owner's own, and a case never presses
Save. Jira writes are dry-run until the owner's word. The browser is `ela browser` (a sense); the verdict,
the cases and the report are this skill's.

## The rule this skill exists for

**A browser result counts only with the environment proven in one browser run.** The gateway routes each
product service by per-user tag cookies, so a session that lands on the gateway's default lane renders a
real page and proves nothing about the lane the ticket is for: on 2026-10-21 a run was reported as prod-3
while the frontend served was prod-8's, and the version panel had shown no ENV. The proof is the version
panel — hover the MediaHub logo — read before any case, every service's ENV and build recorded whole, and
the services the ticket touches matched against the release map for the lane. Missing ENV or a mismatch on
one of the ticket's services aborts the run; a mismatch elsewhere is recorded, not fatal.

## 0 — bind

Read `~/.claude/ela/site.json` → `env`, `map`, `runtime`, `mediahub_url`.

```bash
JIRA="python3 ${CLAUDE_PLUGIN_ROOT}/skills/jira/jira.py --env-file <env>"
BROWSER="python3 ${CLAUDE_PLUGIN_ROOT}/skills/browser/browser.py --env-file <env>"
FIXEDIN="python3 ${CLAUDE_PLUGIN_ROOT}/skills/fixedin/fixedin.py --env-file <env>"
```

Nothing in this skill runs on an unproven session or on a lane whose build does not carry the fix (§1).

## 1 — the fix, the lane and the proof

The owner's account sits on a daily or a prod lane; he does not test on QA lanes. A fix often reaches a QA
lane days before any lane he can open, so the lane question is answered from the fix, never from where the
account happens to be.

- `$FIXEDIN <KEY> --json` first: `lanes` are the lanes whose build descends from the fix commits (ancestry).
  None of them daily or prod → stop: the ticket is not testable on his lanes yet; say which QA lane carries it
  and leave the ticket to QA. The fix on a daily or prod lane the account is not on → say which, and that he
  switches the account's bundle and runs `ela login tvu --force` before the gate.
- `$BROWSER env --key <KEY> [--lane <lane>] --json` is the gate: exit 4 = unproven (cookies: `ela login tvu
  --force`), exit 3 = a service differs from the release map, exit 6 = the panel's lane does not carry the fix.
  The lane is the owner's word, else the one the panel names; state which. Every panel section is recorded;
  the ticket's services (its Fixed In, its labels' line, or the layer its prefix names) must read `match`;
  `differs` on another service is noted in the report. The record keeps the browser clock (zone and time)
  with the panel, because a scheduled behaviour is judged against it.

## 2 — the plan, shown before anything runs

A ticket's description is rarely the whole requirement, and its own commits are rarely the whole truth of
the build under test. On MH-2570 the description was two lines; two of the four goals lived in comments
(the cross-day marker, the developer's plan) and two in the fix commits; a later ticket, MH-3046, had
rewritten the same file, so one goal's behaviour had changed and one had nothing left to test. A plan from
the description alone tests too little; a plan from the ticket's own commits tests what no longer exists.

**Expectations come from the requirement, never from the code.** A test whose expected result is read off
the diff passes a wrong fix with it. So every case's expected result comes from the description, the
comments (what product or QA asked for), or the owner's word. The code is used for three things only, none
of them an expectation: *provenance* — the lane's build descends from the fix commits (`ancestry`) and the
file at that build still carries the change, which proves the thing under test is the thing claimed;
*preconditions* — the config key the behaviour depends on holds what it needs on this lane
(`ela configserver`); and *mechanics* — the selectors and the controls come from the file at the build. A
behaviour the diff adds that no requirement names is listed as "undocumented, for the product owner", not
as an expectation. The default plan is the tech lead's acceptance of the ticket's claim: the black-box cases
the requirement asks for, plus the provenance and precondition checks; not QA's regression matrix, which
stays QA's and the report says so. `--kind black` runs the cases alone; `--kind qa` adds the regression
cases the ticket's QA section lists, when the owner wants them.

So the plan is built in four reads, each goal carrying its source (where its expectation came from) and
its kind (`black` for a behaviour, `timed` for one the clock decides, `provenance` / `precondition` for a check on the build):

1. **The description** — the asked behaviour, in the reporter's terms.
2. **The comments** — what the developer said they built, what QA failed, what product added later.
3. **The fix commits** (`$FIXEDIN <KEY>`) — the scope: which files and controls changed, for the provenance
   check and the selectors; a behaviour the diff adds that no requirement names becomes a question for the
   product owner, never an expectation.
4. **Every later commit on the same files, up to the lane's build sha** (`git log <fix>..<build sha> -- <files>`)
   — each one is read for whether it supersedes a goal; a superseding ticket is named on the goal, and the
   selectors and expectations are taken from the file at the build sha, never from the ticket's commits.

The plan is then shown to the owner as a dry run — a table of goals with kind, source, expected result and
any superseding ticket — and he confirms or edits it before a browser opens. A goal the current build no
longer has is kept in the table, so the report can say `changed` or `n/a` with the superseding ticket, which
is the product owner's question and never this skill's `fail`.

When the ticket has no QA-verification section, the skill offers, after the run, to draft one from the
confirmed plan into the ticket (the shape `skills/jira/SKILL.md` describes); it is written only on the
owner's word, like every other Jira write.

Write the confirmed cases as one script in `<runtime>/browser/cases/<KEY>.js`:

```js
module.exports = async ({ p, panel, url, shots, phase, state, fakeTime }) => {
  // read values and texts; screenshot each case into `shots`; return [{id, action, observed, result}]
};
```

`$BROWSER run <runtime>/browser/cases/<KEY>.js --json`. Scope selectors to the dialog or page the case is
about (the product keeps several hidden `.el-dialog` elements).

**Behaviour that depends on the clock** (a scheduled route, a cross-day marker, "starts up to one minute
early", MH-2601 and its children) gets a fourth kind, `timed`, and three rules:
- The expectation carries a window, not an instant (`starts in [T-60s, T]`), and the evidence is the
  server's timestamp on the record the page shows, never the browser's clock. The plan row says how long the
  run waits.
- A form or display case fakes the browser clock (`await fakeTime("2026-10-21T23:58:00+08:00")`) instead of
  waiting for midnight; the run records the faked time and the report says the server's clock was real.
- An execution case is two runs over one state file: `--phase create --state <run>/state.json` makes the
  schedule and leaves its id and time in the state; `--phase observe` runs after the scheduled time and
  reads the record back. `--timeout` raises the run's limit when a wait is inside one run.

A case that writes (save, start, schedule) is named in the dry run with its cleanup (cancel, delete) as its
own row, is its own confirm, and runs on prod only with a confirm for that case: on prod a schedule
routes a real source. Read-only cases need no such word.

## 3 — the verdict

One of: `pass` (every asked behaviour observed), `fail` (an asked behaviour not observed, with the step and
the screenshot), `changed` (the asked control or rule was replaced by a later ticket — name it; whether the
new behaviour is intended is the product owner's question, not this skill's), `unproven` (the gate failed;
nothing else is reported). The verdict names what it rejects: a pass says which step would have failed it.

## 4 — the two outputs

1. **The QA record, rendered, not written** — the run leaves `<runtime>/browser/runs/<KEY>-<date>/` holding
   `ticket.json`, `plan.json` (the confirmed goals, each with `kind`), `env.json` (`ela browser env --json`),
   `cases.json` (`ela browser run --json`), `ancestry.json`, `technique.json` and `shots/`;
   `ela verify --key <KEY> --run <dir> --single <runtime>/browser/runs/<KEY>-<date>/<KEY>-verify-<date>.html`
   renders two copies from the same data: the page under `<reports>/verify/<KEY>-<date>/` for the owner's
   reading (publishable as a private artifact), and one self-contained HTML with the screenshots embedded for
   the ticket. The record is written for colleagues: the verdict strip with lane and the two builds, the
   ticket, the goals with kind and source, the environment proof (the panel, the map comparison, the
   ancestry), the results with one screenshot per case, the technique — facts only, no account of how the run
   went. Nothing in it links to claude.ai.
2. **The ticket gets the comment and the attachment**: `$JIRA comment <KEY> --from-file …` and
   `$JIRA attach <KEY> <single.html>`, both dry runs first, one confirm. **The comment is the short version and
   stands on its own**: a reader who never opens the attachment can tell whether the ticket is OK, and a reader
   who wants the panel, the screenshots, the ancestry and the method opens the attachment. In English, in the
   Markdown subset, about 600 characters: the verdict in bold with one clause of meaning (`**PASS** — the asked
   behaviour is observed on prod-3`); the environment line (lane, frontend and backend builds, "matches the
   release map" or what differs); every case as one line — `T1 PASS — opening the dialog sets end = start + 60
   min (16:00 → 17:00)` — `CHANGED` and `N/A` lines naming the superseding ticket; what was not covered (QA's
   regression matrix, a write step not run); and `Full record attached: <file>.html`. Nothing else: no fold, no
   service table, no link. The comment never changes the status — a close is `/ela:revisit`.
   (The attachment supersedes the 2026-10-21 rule that the report is never on the ticket: that rule was about a
   claude.ai link; an attachment lives with the ticket under its own permissions.)

## What this skill does not do

- Test on an unproven session, or on a lane whose build does not carry the fix, and say it did.
- Judge a scheduled behaviour by the browser's clock, or wait for midnight when a faked clock answers the case.
- Press Save, start a stream, schedule a route, or change the account, without a confirm for that step and its cleanup.
- Keep selectors or expectations as knowledge: they belong to the file at the build, read each time.
- Replace QA: the report says what a browser observed on one lane; QA's verdict on the ticket is theirs.
