---
name: verify
description: Verify a ticket in the product in a real browser on a named lane, read-only, the version panel as proof; a report for the owner, a short Jira comment on confirm. Use for "auto-test MH-xxxx", "在浏览器里验一下这票".
user-invocable: true
---

# /ela:verify <KEY> [--lane prod-3 | prod-8 | qa-cn3 …] — a ticket checked in the product, with proof

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

`ela browser env` with no lane first: exit 4 means the cookies are stale or missing — stop and ask the owner
for `ela login tvu --force` (after a bundle switch the cookies change). Nothing else in this skill runs on
an unproven session.

## 1 — the lane and the proof

- The lane is the owner's word, else the ticket's `release:` label through `map/release.yaml` (`lanes:` per
  line), else the lane the panel names. State which.
- `$BROWSER env --lane <lane> --json`: every panel section recorded; the ticket's services (from its Fixed
  In, its labels' line, or the layer its prefix names) must read `match`; `differs` on one of them → abort
  with the two values shown; `differs` on another service → noted in the report. The owner decides the
  services the gate covers only when the ticket names none.
- The ancestry check: the lane's build sha (release map, `ela builds`) descends from the fix commits
  (`$FIXEDIN <KEY>`); without it the run tests a build that may not carry the fix, and the report says so.

## 2 — the cases

From three sources, each case naming its source: the ticket's description (the asked behaviour), its
comments (what the developer said they built, what QA failed), and the file at the lane's build sha — the
selectors and the expectations come from that file, never from the ticket's own commits, because later
tickets change the control (MH-2570's dropdowns became date-time pickers under MH-3046). A case whose
control no longer exists is reported `changed`, not failed.

Write the cases as one script in `<runtime>/browser/cases/<KEY>.js`:

```js
module.exports = async ({ p, panel, url, shots }) => {
  // read values and texts; screenshot each case into `shots`; return [{id, action, observed, result}]
};
```

`$BROWSER run <runtime>/browser/cases/<KEY>.js --json`. Scope selectors to the dialog or page the case is
about (the product keeps several hidden `.el-dialog` elements). A case that must write (save, start) is its
own confirm and its own cleanup, named in the dry run before it runs.

## 3 — the verdict

One of: `pass` (every asked behaviour observed), `fail` (an asked behaviour not observed, with the step and
the screenshot), `changed` (the asked control or rule was replaced by a later ticket — name it; whether the
new behaviour is intended is the product owner's question, not this skill's), `unproven` (the gate failed;
nothing else is reported). The verdict names what it rejects: a pass says which step would have failed it.

## 4 — the two outputs

1. **The report for the owner**, and for nobody else: an HTML page written to `<reports>/verify/<KEY>-<date>.html`
   (his private reading surface, `/ela:reports` conventions) and published as a private artifact. It is never
   linked from the ticket, a Slack thread or any shared place: the page is his reading, the comment below is
   the record (decided 2026-10-21 on MH-2570). Verdict strip with lane, frontend and backend builds; the
   ticket; the goals with sources; the environment proof (panel text, the map comparison, the ancestry line);
   results with one screenshot per case; the technique.
2. **The comment for the ticket**, `$JIRA comment <KEY> --from-file …` as a dry run, in the Markdown subset
   the atom renders (bold, bullets, numbered lists, code): above the fold the verdict in bold, the lane and
   the two builds on one line, what changed, the person addressed first as a real `@mention`, in English;
   after a `---` line the method, the environment, the cases T1..Tn with PASS / FAIL / CHANGED / N/A, and
   the build ancestry. About 1,500 characters, no link to the report. The owner's word posts it; it never
   changes the status — a close is `/ela:revisit`.

## What this skill does not do

- Test on an unproven session, or on a lane whose build does not carry the fix, and say it did.
- Press Save, start a stream, or change the account, without a confirm for that step and its cleanup.
- Keep selectors or expectations as knowledge: they belong to the file at the build, read each time.
- Replace QA: the report says what a browser observed on one lane; QA's verdict on the ticket is theirs.
