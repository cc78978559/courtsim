# v6 30-season long holdout runbook

The frozen design is `experiments/gates/postseason-schedule-v6-long-holdout-v1.json`.
It requires 30 paired aggregate and full-engine seasons under batch id
`long-holdout-v6-strength035-v1` and master seed `20261210`. Interim checkpoint inspection is
for process health only; do not change the sample size, inputs, thresholds, or stopping time.

## Full-engine run or exact resume

```powershell
.\tools.cmd nba-quick-sim-run `
  work/nba-2024-25-team-shot-profiles-calibrated.json `
  experiments/sources/nba-2024-25-team-strength-035-v1.json `
  work/quick-sim/long-holdout-v6-strength035-v1.json `
  --manifest work/quick-sim/long-holdout-v6-strength035-v1.manifest.json `
  --schema data/model_schema_demo_v1_12.json `
  --parameters work/pace-dev-short11-parameters.json `
  --lineup examples/calibration_lineup_v1.json `
  --batch-id long-holdout-v6-strength035-v1 `
  --master-seed 20261210 --seasons 30 --maximum-new-seasons 30 --workers 3 `
  --executor-version nba-quick-sim-executor-v6
```

The checkpoint is written after every completed three-season worker wave. If the process stops,
run the exact command again; the manifest and checkpoint hashes reject configuration drift.

Health-only progress check after the first checkpoint exists:

```powershell
.\tools.cmd nba-quick-sim-status `
  work/quick-sim/long-holdout-v6-strength035-v1.json
```

## Paired aggregate batch

```powershell
.\tools.cmd nba-aggregate-quick-sim-run `
  work/quick-sim/long-holdout-v6-strength035-v1-aggregate.json `
  --manifest work/quick-sim/long-holdout-v6-strength035-v1-aggregate.manifest.json `
  --aggregate-parameters `
  experiments/sources/nba-aggregate-quick-sim-parameters-full-season-v2.json `
  --strength experiments/sources/nba-2024-25-team-strength-035-v1.json `
  --batch-id long-holdout-v6-strength035-v1 `
  --master-seed 20261210 --seasons 30 --maximum-new-seasons 30
```

## Final evaluation only after 30 + 30 seasons

```powershell
.\tools.cmd nba-quick-sim-formal-gate `
  work/quick-sim/long-holdout-v6-strength035-v1.json `
  experiments/gates/nba-full-engine-strength035-reality-long-v1.json `
  work/quick-sim/long-holdout-v6-strength035-v1.manifest.json `
  --output work/quick-sim/long-holdout-v6-strength035-v1-reality-gate.json
```

```powershell
.\tools.cmd nba-quick-sim-consistency `
  work/quick-sim/long-holdout-v6-strength035-v1-aggregate.json `
  work/quick-sim/long-holdout-v6-strength035-v1.json `
  work/quick-sim/long-holdout-v6-strength035-v1-consistency.json `
  --gate experiments/gates/quick-sim-engine-consistency-strength035-long-v1.json `
  --aggregate-manifest `
  work/quick-sim/long-holdout-v6-strength035-v1-aggregate.manifest.json `
  --full-manifest work/quick-sim/long-holdout-v6-strength035-v1.manifest.json
```

Promotion requires both reports to have `passed: true`. A failure remains evidence; do not edit a
frozen gate after reading the result.
