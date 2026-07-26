# CourtSim NBA manager draft offseason v1

`nba-draft-offseason-v1` turns the settled 30-team first round into an executed white-box
manager draft. Every team must have a manager profile, and every manager receives an
independent scouting estimate for every available prospect.

Managers rank only eligible players using the existing auditable rational and bounded-style
contributions. True potential remains hidden. The final pick owner controls the selection,
including traded, protected, and swapped picks.

The explicit active entry point executes all 30 selections atomically through the canonical
draft engine. It enforces unique selections, roster and payroll limits, creates rookie
contracts, activates drafted prospects, and records draft year, round, and final slot on each
career.
