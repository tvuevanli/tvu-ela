# 0005 — Helm is an interface over ela

**Decision.** Helm adds no new judgment logic. Its pages, bot, scheduler and API call ela through
`clients/ela.py`. Each existing Helm skill that duplicates an ela skill carries a retirement condition
(ela's parity harness passing on the same input) and is removed when it is met. Helm reads shared
knowledge from the published directory, never from elak and not from a copy of its own.

**Reason.** Two implementations of one judgment diverge and double the maintenance for one person.
Helm's strengths — its tests, its deployment, its Slack and web surfaces — are interface strengths;
its knowledge and reasoning copies are the cost of a transition that is now over.
