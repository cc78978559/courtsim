# Native three-team trades v1

Status: local release candidate, 2026-07-26.

## Routed offer

A three-team offer names exactly three ordered teams and contains explicit player and pick
routes. Every route has one source and one destination inside the participant set. Every team
must send and receive at least one asset, and an asset may appear in only one route.

This is not implemented as three sequential bilateral trades. The legality pass computes all
post-trade rosters, payrolls, salary matching, contract destinations, pick ownership, and
Stepien first-round continuity from the same initial state.

## Atomic execution and audit

If any route references an unowned asset, any roster leaves its bounds, any payroll or matching
rule fails, or any participant violates Stepien safety, execution raises before returning a
state. A legal offer updates all three rosters, player contracts, and pick owners together.

The audit replays the complete routed offer from its initial management and pick states and
requires exact equality with both final states.

## White-box approval

The generic per-team trade evaluator is shared with bilateral trades. Each manager independently
compares incoming and outgoing player value, pick value, roster balance, cap flexibility, and
bounded personality signals against rejection. A three-team Shadow result is approved only
when all three managers accept and meet the rational-gain floor. All three traces enter one
contiguous decision ledger.

## Current boundary

Version 1 exposes canonical execution and Shadow approval for supplied offers. Automatic
three-team offer discovery, hub-team compensation search, multi-round counteroffers, conditional
asset conversion, and integration into the preseason clearing market remain later work.
