# CourtSim NBA quick simulation executor v3

`nba-quick-sim-executor-v3` adds the career-statistics bridge required by the multi-season
franchise loop. Every play-in and playoff game now contributes team games, player appearances,
and player seconds alongside fatigue, availability, injuries, and forfeits.

The summary builder combines those postseason values with the canonical regular-season game
ledger. It produces one `PlayerSeasonSummary` per active or free-agent career, including total
games available, games played, seconds, and injury days.

Career development, decline, injury burden, and retirement can therefore consume the true
full-season workload rather than treating the end of the regular season as the end of a
player's year.
