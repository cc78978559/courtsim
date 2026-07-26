# CourtSim NBA quick-simulation executor v4

`nba-quick-sim-executor-v4` adds validated opponent-specific team variants to the
canonical 30-team quick simulator. A directed variant may change lineup, rotation,
offensive play-family bias, defensive coverage bias, and tempo, but must retain the
base team identity and exact roster.

The resolver selects variants independently for the home and away team in all 1,230
regular-season games and throughout play-in and playoff execution. Missing variants
fall back to the base team. The returned execution records the number of supplied
directed variants.
