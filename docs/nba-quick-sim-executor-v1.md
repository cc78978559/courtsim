# CourtSim NBA quick simulation executor v1

`nba-quick-sim-executor-v1` is the first direct 30-team executor for the quick-simulation
batch protocol. It runs the canonical 1,230-game season schedule through CourtSim's existing
possession and season state machines, derives conference seeds, samples both play-in
tournaments, and resolves all 15 best-of-seven playoff series.

The executor requires 30 ordered teams, league-unique player identifiers, an exact conference
alignment, and overtime-enabled games. Regular-season simulation uses aggregate-only tracing
by default. Conference ties are ordered by wins plus half-ties, point differential, then team
identifier. Postseason games deterministically retry a complete game when the configured
overtime limit still ends tied.

The returned execution retains the canonical season, both play-in ledgers, the validated NBA
postseason ledger, and the six-metric quick-simulation summary. The executor is callable with
the `(season_id, seed)` contract used by resumable batches and atomic checkpoints.

This first executor version starts postseason games from base team state. Carrying
regular-season fatigue, unresolved injuries, and new playoff injuries into this 30-team path
is explicitly deferred; the governance file marks both continuity flags false.
