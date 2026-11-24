# 0024 — An improvement waits for his word only when carrying it out writes live

Status: accepted, 2026-11-24. Supersedes one clause of ADR 0023, "Who decides follows who would notice"; the rest of
0023 stands.

## Context

ADR 0023 sent every fix a colleague would see to an ask on today.md, a change to how mediahub-bot answers among them.
The charter's confirm exists for writes to a live system: a Slack post, a message sent, a Jira write. A change to how a
bot composes its answers is a change to ela's own definitions, made and tested in ela's repositories like any other;
the bot's next answer is still the bot's, under the same rules. Asking the owner about such changes spends one of his
three daily ask slots on a decision the charter already gives to ela. Asked on 2026-11-24, the owner left the line to
ela.

## Decision

- **`who: owner` only when carrying the fix out would send or post something, or write to Jira**, by ela or in the
  owner's name. Such an item starts `open` and takes an ordinary ask slot on today.md with A go · B drop it, as before.
- **Everything else is `who: ela`**, a change to how mediahub-bot or the ela bot answers included: it starts `go`, ela
  builds it under the target repository's rules and reports the outcome in the evening's Improve lines.
- The verb's vocabulary, store and states are unchanged; the evening session that proposes items applies this rule.

## The gate (CLAUDE.md §Gate)

- Problem and evidence: under 0023, a bot's answer format would compete with a mention or a drafted Jira write for an
  ask slot, though it writes nothing live.
- Strongest alternative: keep 0023's line, so the owner sees every change a colleague could notice before it ships.
  Rejected: the evening Improve lines already report each change and its outcome, and a change he dislikes is reversed
  like any other commit; a live write cannot be.
- Conflict with a recorded decision: ADR 0023's clause, superseded here. The charter's confirm before a live write is
  kept whole.
- Verdict: narrow it. Rejected option: ela carrying out a fix that posts, sends or writes to Jira without his letter.
