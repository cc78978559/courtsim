# Roster transactions v1

CourtSim `0.5.0` adds deterministic in-season player transfers above `season-v1`. The
feature does not modify the frozen possession probability model.

## League roster contract

Every player ID has exactly one team owner. `RosterRules` freezes a default minimum of five
and maximum of fifteen players per team. Initial teams, transfer plans, and player profiles
remain immutable; the runtime creates new team values as transactions are applied.

`RosterSnapshot` stores a team ID and its canonical roster order. A managed season records
both initial and final snapshots, making ownership changes independently auditable.

## Transfer plan

Each `PlayerTransfer` records:

- a unique non-negative transaction ID;
- a positive effective day;
- the player ID;
- distinct source and destination team IDs.

`TransferPlan` is ordered by `(effective_day, transaction_id)`. Before the first game is
sampled, the complete plan is replayed against temporary rosters. Unknown teams, missing
source ownership, destination overflow, source underflow, duplicate IDs, invalid order, and
transactions after the final scheduled day are rejected during this preflight.

Valid transfers are then applied immediately before the first scheduled game on or after
their effective day. Transfer execution does not consume randomness.

## Player-state continuity

The player's fatigue and unavailable-until day move from the source state key to the
destination state key. Historical injuries retain the team and game where they occurred,
while later availability is evaluated under the new owner. Per-player last-game dates ensure
off-day recovery follows the player rather than adopting the destination team's history.

## Lineup and rotation rebuilding

When an active player leaves, the source lineup is filled in existing roster order. Every
rotation stint is rebuilt by removing the transferred player and filling the open place from
the remaining roster. The acquired profile is appended to the destination roster and bench;
it does not silently enter the active lineup or an existing rotation.

## Season schema v2

Season JSON schema v2 adds:

- applied transfer records;
- initial roster snapshots;
- final roster snapshots;
- the `roster-v1` marker and the exact roster-size rules used.

The decoder continues to accept schema v1 and supplies empty legacy roster ledgers. Schema-v2
validation replays ownership through the schedule, verifies unavailable players and injuries
against game-day ownership, and requires final player states to match final rosters.

`audit_season` additionally reports transfers applied and final rostered players. The frozen
machine-readable configuration is
[`governance/roster-transactions-v1.json`](../governance/roster-transactions-v1.json).

## Validation evidence

- focused ownership, size, ordering, preflight, lineup, rotation, state, schema, and audit tests;
- schema-v1 compatibility read and schema-v2 strict round trip;
- immutable input-team and transfer-plan checks;
- full Ruff, strict mypy, pytest, coverage, Ubuntu CI, and Windows CI gates.
