# NBA real rosters v1

The formal quick-sim runner accepts `--player-rosters` with a source-pinned
`nba-player-target-v1` artifact. When present, it replaces the synthetic five-template roster
replication with real NBA player IDs, names, 2024-25 team membership, target-shaped usage and
shot profiles, and a deterministic per-game active rotation selected from up to fifteen players.
Appearance probability and minutes are derived from observed games played and MPG, with low-sample
values shrunk toward league means. Players 11-15 can appear at low frequency or replace unavailable
rotation players instead of being permanently excluded.

The ESPN team-ID crosswalk is explicit in `nba_real_rosters.py`; names are never used as an
identity fallback. The clean-checkout-safe frozen input is
`experiments/inputs/nba-player-targets-2024-25.json`, SHA-256
`433e59f47be18ef03d05d75780eb3297f4bf5a969adce1ccd11b5c3a8c279f19`. It contains 451 eligible
players and yields 11-23 players per team. Rebuild it from the source-pinned local data workflow in
`nba-player-data-v1.md`. The processed target set is committed for reproducibility; raw upstream
Parquet files remain local and untracked.

Run the real-roster holdout with:

```powershell
.\tools.cmd nba-quick-sim-run `
  experiments/inputs/nba-2024-25-team-shot-profiles-calibrated.json `
  experiments/sources/nba-2024-25-team-strength-035-v1.json `
  work/quick-sim/v7-holdout-real.json `
  --manifest work/quick-sim/v7-holdout-real.manifest.json `
  --schema data/model_schema_demo_v1_12.json `
  --parameters experiments/parameters/pace-dev-short11-parameters.json `
  --player-rosters experiments/inputs/nba-player-targets-2024-25.json `
  --batch-id long-holdout-v7-real-players-001 `
  --master-seed 20270210 --seasons 30 --maximum-new-seasons 30 `
  --workers 3 --executor-version nba-quick-sim-executor-v7

.\tools.cmd nba-quick-sim-formal-gate `
  work/quick-sim/v7-holdout-real.json `
  experiments/gates/nba-full-engine-player-reality-v7-long-v1.json `
  work/quick-sim/v7-holdout-real.manifest.json `
  --output work/quick-sim/v7-holdout-real-reality.json

.\tools.cmd nba-player-holdout-gate `
  work/quick-sim/v7-holdout-real-players.json `
  experiments/gates/nba-player-holdout-v7-long-v1.json `
  work/quick-sim/v7-holdout-real-player-gate.json
```

The formal gate binds the real roster input and evaluates league-level multi-season reality. It
does not by itself certify player-level usage, efficiency, shot structure, or minutes. Real-roster
execution now uses `PLAYER_AGGREGATES`, which retains season totals without possession logs. Convert
the runner writes a compact, hash-chained `-players.json` holdout sidecar. The
`nba-player-holdout-gate` command exits 17 when minutes MAE, usage MAE, TS MAE, mean three-zone
structure MAE, or zero-minute coverage exceeds its frozen limit. Promotion requires all 30 frozen
seasons and the macro, player, and paired-engine gates to pass.
