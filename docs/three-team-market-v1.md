# Automatic three-team market v1

Status: local release candidate, 2026-07-26.

## Candidate discovery

The market visits every stable three-team combination and enumerates both cyclic player-route
orientations. Candidate generation is deterministic and bounded per trio, so identical league
state and manager profiles produce the same offers, evaluations, and decision ledger.

Each candidate is evaluated by the native atomic three-team engine. It must satisfy roster,
contract, cap, salary-matching, pick-ownership, and Stepien rules before all three white-box
managers independently decide whether to approve it.

## Pick compensation

When a cycle is rejected, the market may build one bounded compensation candidate. It identifies
the participant with the lowest rational gain and routes an available future pick from the
participant with the highest gain. The compensated proposal retains a parent trade identifier,
making the counteroffer chain inspectable.

## Selection and unified clearing

Only unanimously approved candidates above the combined rational-gain floor can enter a plan.
Candidates are ranked by gain with a stable offer signature as the tie-breaker. A team can occur
in at most one selected three-team offer.

During the preseason Shadow stage, the league adapter generates bilateral and three-team plans
from the same initial state. It executes the plan with the higher combined rational gain; an
exact tie preserves the bilateral plan. The audit records both markets and the clearing choice.
Incumbent mode remains unchanged, and automatic activation remains disabled.

## Current boundary

Version 1 searches player cycles plus single-pick compensation. Hub-team packages, multiple
compensation assets, multi-round negotiation, conditional conversions, and learned opponent
models remain later work.
