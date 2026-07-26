# CourtSim NBA quick simulation executor v2

`nba-quick-sim-executor-v2` extends the complete 30-team path with postseason state
continuity. The final regular-season player states are preserved as the exact postseason
initial snapshot. Fatigue recovers according to elapsed calendar days, and unresolved
regular-season injuries continue to suppress availability until their return day.

Every played postseason game can create deterministic addressed injuries using the same
season injury rules. Those injuries affect later play-in and playoff games. The execution
retains ordered game-state records containing day, bracket address, score, unavailable
players, and any forfeit, plus the initial/final player-state snapshots and postseason injury
ledger.

Default spacing is two rest days before the postseason, one between games, and two between
rounds. All values are configurable non-negative integers. A team unable to field five
players loses by deterministic forfeit, keeping elimination games decisive and auditable.
