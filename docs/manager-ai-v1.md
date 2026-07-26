# White-box manager AI v1

Status: local release candidate, 2026-07-26.

## Purpose

`manager-ai-v1` introduces explainable basketball general-manager recommendations without
granting the policy authority to mutate league state. It borrows the proven decision boundary
from MythicMons while replacing every domain-specific signal with CourtSim career, roster,
contract, and player-profile data.

## Decision contract

Every candidate is evaluated in this order:

1. Hard rejections remove illegal choices, including unavailable players, full rosters, and
   salary-cap violations.
2. Rational contributions measure current ability, potential, remaining upside, roster fit,
   age-curve value, and salary efficiency.
3. The reasonable-choice band removes candidates materially behind the rational leader.
4. Manager style may alter only candidates inside that band and is clamped to a configured
   contribution limit.
5. Final ties use rational score and then stable candidate identity.

This makes manager personality visible without allowing personality to override legality or a
large competence difference.

## Manager profile

Each manager has bounded integer ratings for win-now pressure, patience, risk tolerance,
development, star preference, depth preference, continuity, and cap discipline. The first
policy version uses the traits only as small semantic adjustments. Learning and profile
evolution remain future work.

## Shadow policies

`generate_draft_shadow` produces a complete `DraftPlan`. It processes owned picks in canonical
selection order, removes drafted prospects from the available pool, and updates provisional
roster/payroll capacity between picks.

`generate_market_shadow` considers a pass option and legal free agents, recommends at most one
signing per team, and prevents a player from being recommended to multiple teams. Salary and
term are explicit inputs.

Both functions return:

- the proposed canonical plan;
- the full candidate traces;
- incumbent agreement when an incumbent plan was supplied;
- an immutable manager decision ledger;
- an explicit `SHADOW` authority marker.

The caller may replay a proposed plan through `apply_draft` or `apply_market_plan`. Generation
itself never executes it.

## Promotion boundary

`SHADOW` is the only supported operational default. `ASSIST` and `ACTIVE` are reserved authority
labels, not automatic promotion rules. A later phase must add matched-seed, multi-season
counterfactual evaluation and explicit safety/quality gates before either mode controls a live
offseason.

## Known limits

- Player value is a transparent rating composite rather than calibrated wins or contract value.
- Roster fit currently uses size-class scarcity, not rotations or tactical role demand.
- Free agency supports one proposed signing per team and fixed offered terms.
- Trades, waivers, draft lottery/protections, scouting uncertainty, negotiation, and owner
  objectives are outside v1.
- Decision-ledger persistence and release-registry rollback remain future work.
