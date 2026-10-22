---
name: verify
description: Verify a ticket in the product in a real browser on a named lane, read-only, the version panel as proof; a report for the owner, a short Jira comment on confirm. Use for "auto-test MH-xxxx", "在浏览器里验一下这票".
user-invocable: true
---

# /ela:verify <KEY> [--lane prod-3 | prod-8 | qa-cn3 …] — a ticket checked in the product, with proof

Replies to the owner follow the working preferences' language line; the English of this file is not the
language of the answer.

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

Two hosts, two sessions. The gateway (test, daily and prod lanes) is opened on the owner's own login,
wherever his account's bundle puts it; the QA deployment (`qa-*` lanes, its own domain) is opened on ela's
own session with the QA test account (`ela browser login --host qa`), never his. `ela browser env` picks
the host from the lane prefix. A fix often reaches a QA lane days before any gateway lane, so the lane
question is answered from the fix, never from where an account happens to be.

- `$FIXEDIN <KEY> --json` first: `lanes` are the lanes whose build descends from the fix commits (ancestry).
  Only QA lanes carry it → the run is on the QA deployment with ela's own session, and the report says so.
  The fix on a daily or prod lane the owner's account is not on → say which, and that he switches the
  account's bundle and runs `ela login tvu --force` before the gate.
- `$BROWSER env --key <KEY> [--lane <lane>] --shots <run>/shots --json` is the gate: exit 4 = unproven (cookies:
  `ela login tvu --force`, or the fix's lanes unread because the lane's build fell outside the fetched Jenkins
  window — rerun, never read as absent), exit 3 = a service differs from the release map, exit 6 = the panel's lane
  does not carry the fix. `--shots` keeps `version-panel.png`, the panel as read, for the record. Services the
  panel does not list but the session reaches through the gateway (the scheduler, `tvu-aioc-service`) are read on
  the same browser run and appear in `compare` as `recorded`: the account's lane by construction, nothing in the map to
  match, so they prove the build under test and never fail the gate (MH-2519, 2026-10-21: prod-3's scheduler was
  seven weeks behind its master, and only that read showed it).
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
its kind (`black` for a behaviour, `guard` for a behaviour the ticket says is unchanged and the run keeps as a regression
check, `timed` for one the clock decides, `provenance` / `precondition` for a check on the build):

1. **The description** — the asked behaviour, in the reporter's terms.
2. **The comments** — what the developer said they built, what QA failed, what product added later.
3. **The fix commits** (`$FIXEDIN <KEY>`) — the scope: which files and controls changed, for the provenance
   check and the selectors; a behaviour the diff adds that no requirement names becomes a question for the
   product owner, never an expectation.
4. **Every later commit on the same files, up to the lane's build sha** (`git log <fix>..<build sha> -- <files>`)
   — each one is read for whether it supersedes a goal; a superseding ticket is named on the goal, and the
   selectors and expectations are taken from the file at the build sha, never from the ticket's commits.

The plan is then shown to the owner as a dry run — a table of goals with kind, source, expected result and
the later ticket whose rule now governs, when there is one — and he confirms or edits it before a browser
opens. A goal whose rule a later ticket rewrote is judged by that ticket's rule (§3); a goal whose control is
gone is kept in the table as `n/a` with the ticket that removed it.

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
about (the product keeps several hidden `.el-dialog` elements). Two mechanics the QA runs taught (MH-3722,
2026-10-22): the destination panel keeps a personal tag filter across sessions and it hides an untagged test
object, so a case clears that filter first (the tag popover's search box) and restores it at the end; and on
the QA deployment the test account and its group are shared, so another person may edit the object between
runs — the evidence for one goal's steps comes from one run, and the record says so.

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

A case that writes is named in the dry run with its cleanup as its own row. On the gateway (test, daily,
prod) every such case is its own confirm: it runs on the owner's account and a schedule routes a real
source. On the QA deployment, where the session is ela's own test account, the **fixture** is ela's to
build and remove without a word — a Partyline destination, HLS sources on the public bipbop stream, named
`ela-verify <KEY> …` so nothing else is ever touched — and only **starting** a task (routing, going live)
waits for the owner's approval, given once per run for the exact calls the dry phase printed. A fixture
script has phases (dry · setup · start · observe · cleanup) and leaves its ids in the run's `state.json`,
so cleanup is a command, not a memory (2026-10-22, MH-3416 on qa-cn3).

## 3 — the verdict

One of: `pass` (every asked behaviour observed), `fail` (an asked behaviour not observed, with the step and
the screenshot), `blocked` (the gate passed but a precondition the account lacks — a live destination, a
routed source — stopped a case; the provenance checks still count and the report says what was missing and
what would unblock it), `unproven` (the gate failed; nothing else is reported). **The newest ticket on the same
control governs**: an older ticket's goal is judged pass or fail by the later ticket's rule, and that ticket
is named on the goal; there is no `changed` verdict and no hand-back to the product owner (2026-10-21,
MH-2602 under MH-3046). A goal is `n/a` only when the control itself no longer exists. The verdict names what
it rejects: a pass says which step would have failed it. A `guard` goal the fixture could not observe is `blocked` in
its row and named as not covered, but does not decide the verdict: the ticket is judged on what it asked (MH-3365,
2026-10-22, an HLS source whose receiving side reports no PID table).

## 4 — the two outputs

1. **The QA record, rendered, not written** — the run leaves `<runtime>/browser/runs/<KEY>-<date>/` holding
   `ticket.json`, `plan.json` (the confirmed goals, each with `kind`), `env.json` (`ela browser env --json`),
   `cases.json` (`ela browser run --json`), `ancestry.json`, `technique.json` and `shots/` (the gate's `version-panel.png` among them);
   `ela verify --key <KEY> --run <dir> --pdf <dir>/<KEY>-verify-<date>.pdf` renders the page under
   `<reports>/verify/<KEY>-<date>/` for the owner (publishable as a private artifact) and prints the PDF for the
   ticket. **The readable part comes first**: the verdict, the environment in one plain sentence, and one row
   per requirement check — what the ticket asks (the goal from the plan) and what was seen, in a reader's
   sentence. For that, every case result carries `seen` (one plain sentence, no ids, no json, no request paths)
   beside `observed` (the raw text, kept whole); setup and cleanup steps (`T0`, `C1`, kinds setup/cleanup) never
   sit in that table. Everything technical — the run log with every step's raw observation, the panel text, the
   service table, the ancestry, selectors, the method, the screenshots — is the appendix, collapsed on screen and
   printed after a page break (the PDF opens it). A reader of page one should need nothing else to know whether
   the ticket is OK; a second reader opens the appendix to repeat or audit the run.
   The record is written for colleagues: facts only, no account of how the run went, nothing linking to
   claude.ai. The ticket gets the PDF, one file, because Jira previews it inline where an HTML is shown as
   source and loose screenshots duplicate the record.
2. **The ticket gets the comment and the attachment**: `$JIRA attach <KEY> <pdf>` and `$JIRA comment <KEY>
   --from-file …`, both dry runs first, one confirm. **The comment is the short version and stands on its
   own**. In English, in the Markdown subset, no mention by default (a leading mention reads as that person
   having tested). The first sentence names who verified and how: `Verified on prod-3 by an automated browser
   run on my own session — closing as Done.`; a colleague who should know is named in plain words at the end
   of that line (`<first name>, FYI.`), never as a mention unless the owner asks. The lane is named in that first
   sentence and nowhere else above the fold; the builds are not. Then at most four plain lines: what was seen,
   in the reader's words, not the selector's, grouped by behaviour rather than one line per case; what was not
   covered; and `Full record attached: <file>.pdf` (no "screenshots inside", no second mention of the file).
   After the `---` line, collapsed and only there: lane with its ENV name, frontend and backend builds, the
   commit ancestry in one line, and the cases as `T1 PASS` lines — the one place the cases repeat. Nothing above
   the fold is repeated below it in the same words. About 600 characters above the fold, no link. The comment never
   changes the status by itself — a close is the `jira close` bundle, where this comment is the bundle's comment.

## What this skill does not do

- Test on an unproven session, or on a lane whose build does not carry the fix, and say it did.
- Judge a scheduled behaviour by the browser's clock, or wait for midnight when a faked clock answers the case.
- Press Save, start a stream, schedule a route, or change the account, without a confirm for that step and its cleanup.
- Keep selectors or expectations as knowledge: they belong to the file at the build, read each time.
- Replace QA: the report says what a browser observed on one lane; QA's verdict on the ticket is theirs.
