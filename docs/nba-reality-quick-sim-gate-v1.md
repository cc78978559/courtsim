# NBA reality and formal quick-sim gate v1

CourtSim freezes three NBA seasons (2022-23 through 2024-25) from source-pinned
SportsDataverse hoopR team box-score Parquet files. The compact tracked reality artifact contains
30-team, 82-game standings and all 15 completed playoff series per season. NBA Cup championship
games that do not count in league standings are excluded explicitly by game ID.

Rebuild the tracked reality and comparison range locally after installing the optional data tools:

```powershell
.\tools.cmd bootstrap-data
.\tools.cmd nba-reality-build `
  experiments/nba-data/hoopr-team-box-reality-2022-25.json `
  experiments/sources/nba-2022-25-standings-playoffs.json `
  experiments/sources/nba-2022-25-quick-sim-reference.json `
  --cache .cache/nba-data/hoopr-team-box-multiseason
```

The formal gate verifies both frozen artifact hashes before reading simulation results. A candidate
must be a complete 30-team batch of at least 30 seasons, use the `formal-nba-reality-` batch ID
prefix, and use a master seed outside the recorded calibration/development seed set. It then
requires all six aggregate quick-sim metrics to remain inside the observed three-season ranges
plus frozen, metric-specific guardbands. The guardbands prevent a three-season accident—such as
all three champions being No. 1 seeds—from becoming an exact simulation requirement.

```powershell
.\tools.cmd nba-quick-sim-formal-gate `
  work/quick-sim/formal-checkpoint.json `
  experiments/gates/nba-2022-25-quick-sim-formal-gate-v1.json `
  --output work/quick-sim/formal-gate-report.json
```

Freezing the gate is not a passing result. A promotion claim requires a separately generated,
complete checkpoint on an eligible unseen master seed and a gate report with `passed: true`.
