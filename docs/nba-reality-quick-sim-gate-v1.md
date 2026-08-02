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

Run or resume the pinned model locally. Every completed season is committed atomically to the
checkpoint; the adjacent manifest binds the checkpoint to model, parameter, lineup, shot-profile,
team-strength and clock hashes. Team strength is a white-box additive ability offset derived from
2024-25 point differential, not a hidden fitted policy.
The same source file explicitly assigns the 15 Eastern and 15 Western teams; alphabetical profile
order is never used as a conference shortcut.
The calibrated shot-profile file and explicitly frozen formal result bundles are narrow tracked
exceptions under `work/`; ordinary run outputs and checkpoints remain ignored.

```powershell
.\tools.cmd nba-quick-sim-run `
  work/nba-2024-25-team-shot-profiles-calibrated.json `
  experiments/sources/nba-2024-25-team-strength-v1.json `
  work/quick-sim/formal-nba-reality-v1.json `
  --batch-id formal-nba-reality-v1 --master-seed 20260902 --seasons 30 `
  --maximum-new-seasons 4 --workers 4
```

```powershell
.\tools.cmd nba-quick-sim-formal-gate `
  work/quick-sim/formal-checkpoint.json `
  experiments/gates/nba-2022-25-quick-sim-formal-gate-v1.json `
  work/quick-sim/formal-checkpoint.manifest.json `
  --output work/quick-sim/formal-gate-report.json
```

Freezing the gate is not a passing result. A promotion claim requires a separately generated,
complete checkpoint on an eligible unseen master seed and a gate report with `passed: true`.

The separate aggregate execution path, its strict feature boundary, and its first 30-season
five-of-six gate result are documented in
[`nba-aggregate-quick-sim-v1.md`](nba-aggregate-quick-sim-v1.md).
