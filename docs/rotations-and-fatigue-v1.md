# Rotations and fatigue v1

Status: implemented as the opt-in `rotation-v1 / fatigue-v1` game-state layer.

This layer sits above the frozen `demo-v1.12 / demo-1.4.0` probability model. Rotation and fatigue
configuration therefore cannot silently change the promoted probability artifacts.

## Full roster

`GameTeam` keeps an active five, active profiles, bench profiles, and a stable substitution order.
All identities across both complete rosters must be disjoint. Five-player inputs remain valid and
behave as they did in v0.2.

## Rotation schedule

A `RotationPlan` is an ordered tuple of clock-addressed `RotationStint` values. At each dead-ball
boundary, the runtime resolves the current target lineup, removes ineligible players through the
same legal replacement path used by foul-outs, and records each actual player exchange.

Schedule addresses are `(period, start_clock_seconds)`. Stints are sorted by period and descending
clock. A target becomes active when the game clock reaches or passes its start clock.

## Canonical ledger

Every schema-v2 `GamePossessionRecord` stores the offense and defense lineups. When fatigue is
enabled it also stores both active-five fatigue snapshots. `SubstitutionRecord` stores team,
period, clock, reason, outgoing player, and incoming player.

`PlayerPlayingTime` is derived only from possession durations and the two recorded lineups. It is
validated against the ledger during replay and decoding. Game schema v2 writers include the new
fields; readers continue to accept schema v1 games.

## Fatigue

Fatigue is an integer in `0..maximum_fatigue`. Active players add
`active_load_per_second * elapsed_seconds`; bench players recover
`bench_recovery_per_second * elapsed_seconds`. The update consumes no random slot and is independent
of trace mode, worker count, or iteration order.

The bounded ability penalty applies only to:

- perimeter creation and ball security;
- rim, midrange, three-point, and free-throw execution;
- point-of-attack defense and rim protection;
- offensive and defensive rebounding;
- offensive decision-making and defensive awareness.

Profiles and tendencies are never mutated. Zero load produces the exact v0.2 possession-event
stream. Audit output reports scheduled and foul-out substitutions, players used, total player
seconds, and maximum final fatigue.

## Validation evidence

The Phase 3 gate covers deterministic single games and batches, scheduled and foul-out legality,
schema-v1 compatibility, schema-v2 replay, player-seconds reconstruction, bounded recovery, zero
load compatibility, and a paired player-aware three-point counterfactual.

On the 2026-07-25 local Windows check, a 200-game synthetic 30-second batch ran at approximately
`709.93 games/s` with rotations only and `689.35 games/s` with default fatigue enabled. This small
runtime probe is evidence of bounded overhead, not a full-game production throughput claim.
