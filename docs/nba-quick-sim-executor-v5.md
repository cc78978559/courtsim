# CourtSim NBA quick-simulation executor v5

`nba-quick-sim-executor-v5` emits a compact manager-learning ledger for every play-in
and playoff game. The ledger stores two directed observations per game and preserves
scores, possessions, shot attempts, three-point attempts, and rim attempts without
requiring full trace retention.

Forfeits still create score and game-count observations while naturally carrying zero
event totals. The complete postseason learning ledger is returned alongside fatigue,
injury, availability, playing-time, and team-game continuity.
