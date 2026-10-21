# 0007 — No phase plan in ela; the two-week window lives in elak

**Decision.** ela keeps no plan beyond what each ability must prove. `ROADMAP.md` records what exists,
the exit test each part must pass, and what is not built on purpose; it no longer orders work into
phases. The only plan is the two-week window in elak
(`blueprint/plans/2026-10-21-the-assistant-as-a-whole.md` §6), rewritten against disk every two
weeks and never appended. Question 4 of ADR 0006's admission test ("the phase it belongs to") is
read as: the exit test the ability pushes, and whether it is inside the current window.

**Why.** The owner's work changes week to week; a phase plan written in September was wrong by
October on every row that reached beyond the next fortnight, and keeping it true cost more than it
guided. What stays true are rules, decisions and evidence (elak), and the exit test of each ability
(this repository). Decided by the owner on 2026-10-21 in the standing plan.

**Rejected.** Keeping the phase table and editing it on every change (a plan that is always stale or
always being rewritten); deleting `ROADMAP.md` (the exit tests and the deliberate omissions are
durable and belong here).

**Supersedes.** The phase ordering in `ROADMAP.md`; nothing else in ADRs 0001–0006.
