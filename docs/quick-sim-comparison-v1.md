# CourtSim quick simulation comparison v1

`quick-sim-comparison-v1` compares multi-season CourtSim output with a versioned external quick
simulation reference.

The canonical metrics are team win-rate standard deviation, possessions per team, offensive
rating, team point-differential standard deviation, playoff upset rate, and mean champion seed.
Regular-season values come from canonical game and possession ledgers; postseason values come
from the validated playoff bracket.

References must name the exact game version, roster date, source, team count, and observed
season count. Each metric supplies an observed minimum and maximum. Reports average CourtSim
seasons and retain every metric's observed value, target interval, and pass status.

The repository includes an NBA 2K reference template with null target values. Templates are
valid documentation artifacts but are rejected for scoring. Real exported 2K observations must
replace those values before any comparison can claim a result.
