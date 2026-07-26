# CourtSim NBA franchise v3

`nba-franchise-v3` closes the postseason feedback loop for persistent manager
learning. Every regular-season, play-in, and playoff game contributes two directed
opponent observations. Each observation carries score, possession, three-point, and
rim-attempt totals derived from the canonical game result.

The season update aggregates these ledgers by manager and opponent before converting
them into bounded white-box ratings. Existing memories and the new complete-season
sample are games-weighted. The directed sample count is exact: 2,460 observations
from the regular season plus twice the number of played postseason games.

The updated memories remain part of the next franchise state and drive the following
season's 870 opponent-specific rotation and tactical variants. Disk persistence and
cross-process resume remain outside this version.
