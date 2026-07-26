# CourtSim NBA franchise v1

`nba-franchise-v1` composes one deterministic 30-team franchise year from the
canonical regular season through the next opening-day state. It runs all 1,230
regular-season games, the play-in and playoffs, combines regular- and postseason
career workload, resolves the NBA lottery and draft assets, executes the complete
offseason, and rebuilds legal rosters, lineups, benches, and rotation plans.

The returned state advances the management year and completed-season counter once.
It contains the updated career players, contracts, rosters, future-pick ledger, and
game teams required to call the same operation for the following year. When no
prospect class is supplied, the loop generates one addressed 30-player class for
the upcoming draft.

This first composition layer rebuilds the manager's base rotation while preserving
each team's existing offense, defense, and tempo strategy. Persistent manager
learning and opponent-specific opening rotations are not yet wired into the
franchise state. The transaction is composable in memory; disk checkpoints and
resume are intentionally deferred.
