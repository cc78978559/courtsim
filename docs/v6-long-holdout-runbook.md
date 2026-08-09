# v6 30-season long holdout runbook

Status: completed and promoted on 2026-08-02. Both frozen gates passed. The tracked compact
receipt is `experiments/promotion/nba-quick-sim-executor-v6.json`; the large checkpoints and gate
reports remain local under `work/quick-sim`.

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

The completed local report hashes are:

- full checkpoint: `c026de6f4c1d706ee3836a3daede6f1676926cd620fb4f1cc9322efb790f01d6`;
- full manifest: `302a5ae35c0fa17acbccb0b4a486b4aa77d3490b16c6811c7ef3922cf951d63a`;
- aggregate checkpoint: `f612605a709c84c11e27319eea01fe64dc576efebac23ac226d6a37f2bcf6048`;
- aggregate manifest: `75641737d85781d35d603af22ab1518d62570d61d68ac2fa5d714de24c82c1e6`;
- reality-gate report: `3baca5696cbf0d927979d6f82e9ce27aec7d6a9d749fec18620eb936ae744ae6`;
- consistency report: `4f51f1f95cfec82388f46c38a3167d618e30a78117121f30cc202d5f954bb288`.

If the large local artifacts are unavailable on another machine, rerun the exact commands above.
If a partial checkpoint and its manifest were transferred together, the full-engine command
resumes the verified prefix without replaying completed seasons.
