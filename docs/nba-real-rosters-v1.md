# NBA real rosters v1

The formal quick-sim runner accepts `--player-rosters` with a source-pinned
`nba-player-target-v1` artifact. When present, it replaces the synthetic five-template roster
replication with real NBA player IDs, names, 2024-25 team membership, target-shaped usage and
shot profiles, and a deterministic ten-player rotation whose stint allocation totals 240 minutes.

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
does not by itself certify player-level usage, efficiency, shot structure, or minutes. Those remain
separate full-trace `nba-player-audit`, `nba-player-evaluate`, and multi-seed evaluation gates; a
real roster cannot be described as player-calibrated until those reports pass.
