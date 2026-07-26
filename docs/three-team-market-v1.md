# Automatic three-team market v1

Status: local release candidate, 2026-07-26.

## Candidate discovery

The market visits every stable three-team combination and enumerates both cyclic player-route
orientations plus hub-and-spoke packages. A hub sends distinct players to both other teams and
receives one player from each. Hub identities rotate in stable round-robin order, preventing the
candidate ceiling from concentrating discovery on the lexically first team.

Cyclic and hub families each receive 32 evaluations inside a shared 64-evaluation ceiling per
trio. Candidate generation is deterministic and lazy, so identical league state and manager
profiles produce the same bounded offers, evaluations, and decision ledger.

Each candidate is evaluated by the native atomic three-team engine. It must satisfy roster,
contract, cap, salary-matching, pick-ownership, and Stepien rules before all three white-box
managers independently decide whether to approve it.

## Pick compensation

When a base offer is rejected, the market identifies the participant with the lowest rational
gain and routes available future picks from the participant with the highest gain. Negotiation
can escalate from a one-pick counteroffer to a two-pick counteroffer, stopping early when a round
is accepted or the family budget is exhausted. Each round retains its immediate parent trade
identifier and exposes negotiation round 0, 1, or 2 in the league audit.

## Selection and unified clearing

Only unanimously approved candidates above the combined rational-gain floor can enter a plan.
Candidates are ranked by gain with a stable offer signature as the tie-breaker. A team can occur
in at most one selected three-team offer.

During the preseason Shadow stage, the league adapter generates bilateral and three-team plans
from the same initial state. It executes the plan with the higher combined rational gain; an
exact tie preserves the bilateral plan. The audit records both markets and the clearing choice.
Incumbent mode remains unchanged, and automatic activation remains disabled.

## Current boundary

Version 1 searches player cycles, two-in/two-out hub packages, and up to two compensation picks.
Salary-driven package construction, three-plus-round bargaining, conditional conversions, and
learned opponent models remain later work.
