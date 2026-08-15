# NBA aggregate quick-sim v1

## Purpose and boundary

`nba-aggregate-quick-sim-v1` is the fast season-distribution path. It simulates the complete
30-team, 82-game schedule, real conferences and divisions, both play-in tournaments and all 15
best-of-seven playoff series. It produces the same `QuickSimSeasonSummary` contract as the full
possession engine, but it does not produce player statistics, possession traces, injuries,
rotations or manager-learning evidence. Those remain full-engine responsibilities.

The aggregate executor does not read the formal reality reference or gate. Its base pace,
offensive rating and team-score standard deviation come from the frozen promoted 100-game
full-engine audit. Team strength comes from the independently frozen 2024-25 point-differential
ledger. The home advantage and pace standard deviation are explicit design constants and must be
covered by sensitivity studies before promotion.

## Reproducible run

```powershell
.\tools.cmd nba-aggregate-quick-sim-run `
  work/quick-sim/formal-nba-aggregate-v1.json `
  --batch-id formal-nba-aggregate-v1 `
  --master-seed 20260906 `
  --seasons 30

.\tools.cmd nba-quick-sim-formal-gate `
  work/quick-sim/formal-nba-aggregate-v1.json `
  experiments/gates/nba-2022-25-aggregate-quick-sim-formal-gate-v1.json `
  work/quick-sim/formal-nba-aggregate-v1.manifest.json `
  --output work/quick-sim/formal-nba-aggregate-v1-gate.json
```

The frozen 30-season run completed in roughly four seconds on the development machine. Input,
batch, seed and reality-integrity eligibility all passed. Five of six realism metrics passed. Pace
failed at `96.7030` possessions per team against the guarded minimum `97.8058`; the gate therefore
correctly returned failure. No parameter was changed after seeing this result.
The checkpoint, run manifest and failed gate report are intentionally tracked as a reproducible
formal result bundle under `work/quick-sim/`.

## Promotion requirements

Aggregate quick-sim is currently a candidate tool, not a replacement for the full engine. Before
promotion it requires paired seeds against completed full-engine seasons, sensitivity analysis for
the two explicit design constants, and a new holdout master seed after any pace correction. A pace
correction belongs in the promoted full-engine model or in a separately justified parameter
revision; it must not be copied from the gate threshold.
