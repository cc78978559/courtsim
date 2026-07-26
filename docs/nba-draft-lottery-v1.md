# CourtSim NBA draft lottery v1

`nba-draft-lottery-v1` replaces the four-team experiment lottery when a complete NBA season
enters the offseason. Fourteen non-playoff teams participate, the first four selections are
drawn without replacement, and the published 14.0% through 0.5% odds sum to exactly 10,000
basis points.

The remaining lottery teams retain their incoming order. Sixteen playoff teams follow,
grouped by elimination round and ordered worst-to-best by regular-season standing inside each
group. The Finals loser selects 29th and the champion 30th.

The result contains both the complete draw ledger and the derived 30-team order. A convenience
entry point derives the lottery/playoff partitions directly from canonical season standings
and the validated NBA postseason bracket.
