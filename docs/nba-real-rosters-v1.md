# NBA real rosters v1

The formal quick-sim runner accepts `--player-rosters` with a source-pinned
`nba-player-target-v1` artifact. When present, it replaces the synthetic five-template roster
replication with real NBA player IDs, names, 2024-25 team membership, target-shaped usage and
shot profiles, and a deterministic per-game active rotation selected from up to fifteen players.
Appearance probability and minutes are derived from observed games played and MPG, with low-sample
values shrunk toward league means. Players 11-15 can appear at low frequency or replace unavailable
rotation players instead of being permanently excluded.

The ESPN team-ID crosswalk is explicit in `nba_real_rosters.py`; names are never used as an
identity fallback. The current local frozen input is `work/nba-player-targets-2024-25.json`, SHA-256
`433e59f47be18ef03d05d75780eb3297f4bf5a969adce1ccd11b5c3a8c279f19`. It contains 451 eligible
players and yields 11-23 players per team. Rebuild it from the source-pinned local data workflow in
`nba-player-data-v1.md`; do not commit raw upstream Parquet files.

Run the real-roster holdout with:

```powershell
.\tools.cmd nba-quick-sim-run `
  experiments/inputs/nba-2024-25-team-shot-profiles-calibrated.json `
  experiments/sources/nba-2024-25-team-strength-035-v1.json `
  work/quick-sim/real-player-v1.json `
  --player-rosters work/nba-player-targets-2024-25.json `
  --batch-id long-holdout-real-players-v1-001 `
  --master-seed <unseen-seed> --seasons 30 --workers 4

.\tools.cmd nba-quick-sim-formal-gate `
  work/quick-sim/real-player-v1.json `
  experiments/gates/nba-full-engine-player-reality-long-v1.json `
  work/quick-sim/real-player-v1.manifest.json
```

The formal gate binds the real roster input and evaluates league-level multi-season reality. It
does not by itself certify player-level usage, efficiency, shot structure, or minutes. Real-roster
execution now uses `PLAYER_AGGREGATES`, which retains season totals without possession logs. Convert
those aggregates with `audit_nba_player_aggregates`, evaluate them with `nba-player-evaluate`, then
run `nba-player-formal-gate`; the command exits 16 when minutes MAE, usage MAE, TS MAE, mean
three-zone structure MAE, or zero-minute coverage exceeds its frozen limit. Promotion still
requires this gate to pass across holdout seeds.
