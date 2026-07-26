# CourtSim manager league adapter v1

Status: local release candidate, 2026-07-26.

## Purpose

`manager-league-adapter-v1` is the production domain adapter for
`manager-experiment-v1`. It turns one experiment season request into a real CourtSim regular
season, playoff bracket, career transition, contract year, draft, and free-agent period, then
returns the next complete league state and normalized manager outcomes.

## Canonical state

The adapter state contains:

- validated `contract-v1 / free-agency-v1` management state;
- every active, free-agent, prospect, and retired career player;
- full immutable player profiles, potential, development traits, age, draft history, injury
  burden, and career status.

State JSON is strict and deterministic. Management snapshots reuse the existing audited
management serializer. Every experiment arm carries its own returned state into the following
season.

Before each season, `manager-rotation-v1` converts every roster and manager profile into
starters, a normal rotation group, emergency depth and an official clock-addressed plan. These
plans are used by both the regular-season and playoff game samplers.

Persisted `manager-learning-v1` opponent memories also compile into matchup-specific tactics.
Defensive strength shifts ball-screen, isolation, and off-ball play-family logits; observed
shot profile and offensive strength shift base, drop, switch, and blitz coverage logits; pace
and defensive strength produce a bounded tempo counter. Tactical influence scales linearly
from one through eight observed games, then remains capped. The same matchup teams are resolved
for regular-season and postseason games, and the audit records every bias, confidence, tempo
delta, and effective tempo. An unseen opponent retains the exact neutral strategy.

When the state has no waiting prospects, `prospect-generation-v1` adds an identical addressed
class to both policy arms for the following draft. A supplied complete class is preserved.

## Season and playoff execution

Version 1 requires exactly four teams. It creates a deterministic round-robin schedule and runs
`season-v1` with the configured game rules, injuries, fatigue, trace mode, and model parameters.
The top four standings become the `playoff-v1` seeds.

Playoff games use the full game sampler and configured best-of pattern. If the game engine
reaches its configured overtime safety limit still tied, the adapter adds one deterministic
derived-seed safety point so the bracket always has a legal winner. The resulting playoff
ledger remains replayable by `playoff-v1`.

Incumbent and Shadow arms derive regular-season, playoff, career, and offseason random streams
without the arm label. Therefore identical states consume common random numbers; policy
differences, not unrelated randomness, create divergence.

## Offseason execution

The adapter derives player season summaries from audited playing-time and injury ledgers. It
then previews career transitions, retirements, contract expirations and roster capacity before
constructing reverse-standings draft assets.

- Incumbent draft policy selects current ability, then potential, with stable player identity
  as the final tie-break.
- Shadow draft policy uses `manager-ai-v1` white-box recommendations.
- Incumbent free agency performs only signings required to restore a playable roster.
- Shadow free agency uses the white-box market policy, followed by the same safety restoration
  if a roster has fewer than five players.

The selected plans are executed once through the canonical `advance_offseason` pipeline. The
audit payload includes the complete season, playoff and offseason ledgers plus Shadow decision
records.

## Outcome mapping

The adapter returns normalized:

- regular-season win rate;
- playoff progress (`0.5` participant, `0.75` finalist, `1.0` champion);
- post-offseason roster asset value from current abilities and potential;
- post-offseason salary-cap flexibility.

These values feed `manager-evidence-v1`; they are not simulation-level overall ratings.

## Known limits

- The default compact adapter path supports four teams; persisted NBA alignment activates the
  complete 30-team schedule and play-in bracket.
- Opponent models learn season aggregates rather than series-by-series outcomes.
- Owner objectives and human promotion remain outside the adapter.
