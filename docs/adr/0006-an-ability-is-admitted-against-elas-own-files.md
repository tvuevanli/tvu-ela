# 0006 — An ability is admitted against ela's own files

**Decision.** Adding, changing or removing an ability is a one-way ask, and its four Gate checks are
answered against named files in this repository, not in the abstract. The five questions below are
the admission test for an ability, as `<elak>/knowledge/README.md` is the admission test for
knowledge:

1. **Scenario** — which row of `docs/capabilities.md` it serves. A new row states why the existing
   rows do not cover it; an ability that serves no row is not built.
2. **Layer** — script, skill, verb, MCP tool, or several (`docs/architecture.md`, L1–L3). A
   capability is a script first; a skill exists only where a session needs judgment or invariants,
   and a skill over an ability needing neither is documentation pretending to be capability.
   Judgment is never pushed down into a sense: a sense reports what a source says, a skill decides.
3. **Workflow** — where it is invoked in `docs/manual.md` §一 and §六, and what it displaces there.
   An ability with no place in the day is not reached on the day it is needed. `tests/run.sh` checks
   that the name appears; the author checks that the flow still reads.
4. **Phase and the cost of proof** — the phase it belongs to in `ROADMAP.md`, and how much further it
   pushes that phase's exit test. It enters `docs/manual.md` §五 unproven, so its output goes to the
   owner alone until it meets its test (elak principle P7). Adding an ability while a phase is
   unproven trades proof for surface; that trade is stated, not assumed.
5. **Duplication** — the judgment it would hold that another ability already holds. A shared *input*
   step belongs to one ability and is called by the others; a duplicated *verdict* is refused
   (ADR 0005 is the same rule on Helm's side).

A modification answers 1, 3 and 5; a removal answers 3 and 4. The verdict names the option ela would
reject.

**Reason.** The Gate already listed "adding a capability" as one-way, but its four checks could be
answered from judgment alone, so the register, the layers, the manual and the roadmap were kept true
after the fact rather than consulted before it. Two failures follow from that. An ability whose
scenario is never named duplicates one that exists, and two abilities deciding the same thing drift
into two answers with one owner. An ability with no place in the day is built, documented and not
reached, while the phase it was taken from stays unproven — the count of abilities grows and the
count of proofs does not. Binding the checks to files makes both visible before the work, and makes
the reviewer's job possible: the same five answers are what the owner reads to accept or reject.
