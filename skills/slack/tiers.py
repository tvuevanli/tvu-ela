"""The information tier of every notice ela or the runner may send the owner: one table, read by each notifier
before it decides to message him. A module, not a capability: the notifiers keep their own verdicts and ask this
table which tier a kind of notice is in.

  I1 interrupt  his own action is needed within hours and only he can take it: a direct message now
  I2 decision   needs his word but can wait for his next look: a vault page; Slack at most reminds, once a day
  I3 fact       nothing is asked of him: no message; the fact store has it and the reports read it there
  I4 record     nobody needs it: a log line and the tally

The owner's rule (2026-11-26): whether something reaches him is decided by its information tier, as Jira writes
are by theirs; a day's facts go to the team daily report and his own report, through the fact store. The scheduled
reports are deliveries, not notices, and are not in this table. A kind not in the table is a programming error
(KeyError, caught by the offline tests), never a guess. An incident is I1 whatever any later rule says (FLOOR).
"""

I1, I2, I3, I4 = "I1", "I2", "I3", "I4"
WHERE = {I1: "a direct message now", I2: "a vault page; one Slack reminder a day at most",
         I3: "no message: the fact store and the reports", I4: "a log line and the tally"}

TIERS = {
    ("mention", "incident"): (I1, "a prod failure addressed to him: sent at once, also outside his DM hours (ADR 0021)"),
    ("mention", "ask"): (I1, "a question or request put to him, unanswered through the wait, inside his DM hours (ADR 0021)"),
    ("mention", "ask-held"): (I2, "the same ask falling due outside his DM hours: an ask on today.md, no message"),
    ("mention", "notice"): (I4, "a cc, a bot's announcement, a broadcast: recorded and tallied, never raised"),
    ("mention", "not-needed"): (I4, "ela's reading that he is only copied: closed, no card (2026-11-25)"),
    ("watch", "topic"): (I2, "a board-watch decision that is his: ela/watch.md, one reminder a day when a topic is new"),
    ("watch", "act"): (I3, "what the board watch wrote: ela/dry/did.md and the fact store, no message"),
    ("runner", "failure"): (I1, "a pass that failed: a direct message, held outside his DM hours (decision 2026-10-26)"),
    ("runner", "page-check"): (I3, "a morning page held back by its check: the facts page stands in and says so"),
}
FLOOR = {("mention", "incident"): I1}


def tier(source, kind):
    """The tier of one kind of notice; KeyError for a kind nobody placed."""
    t = TIERS[(source, kind)][0]
    return FLOOR.get((source, kind)) or t


def messages_now(source, kind):
    """Whether this kind of notice may be a direct message to him now (I1)."""
    return tier(source, kind) == I1
