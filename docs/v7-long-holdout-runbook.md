# v7 real-player 30+30 holdout runbook

Status: completed local WIP candidate on 2026-08-15, not promoted and not a release. Development
seeds are listed in `experiments/gates/real-player-v7-long-holdout-v1.json`; the disjoint holdout
master seed is `20270210`. Once either formal run begins, inspect only checkpoint health. Do not
change code, inputs, parameters, thresholds, seed, sample size, worker-independent semantics, or
stopping time.

## Preconditions

From a clean checkout of the candidate freeze commit:

```powershell
.\tools.cmd bootstrap
.\tools.cmd check
.\.venv\Scripts\python.exe -m build
git status --short --branch
```

The old `nba-quick-sim-executor-v6` receipt and release registry remain immutable. v7 is selected
explicitly because the CLI default intentionally remains v6.

## Full-engine real-player batch

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
```

The same command resumes a verified prefix. It writes the team checkpoint, manifest, and compact
player sidecar `work/quick-sim/v7-holdout-real-players.json` as one recoverable evidence set.

## Paired aggregate batch

```powershell
.\tools.cmd nba-aggregate-quick-sim-run `
  work/quick-sim/v7-holdout-aggregate.json `
  --manifest work/quick-sim/v7-holdout-aggregate.manifest.json `
  --aggregate-parameters experiments/parameters/nba-aggregate-quick-sim-parameters-v7-candidate.json `
  --strength experiments/sources/nba-2024-25-team-strength-035-v1.json `
  --batch-id long-holdout-v7-real-players-001 `
  --master-seed 20270210 --seasons 30 --maximum-new-seasons 30
```

## Frozen gates

Run all three only after both batches report 30 complete seasons:

```powershell
.\tools.cmd nba-quick-sim-formal-gate `
  work/quick-sim/v7-holdout-real.json `
  experiments/gates/nba-full-engine-player-reality-v7-long-v1.json `
  work/quick-sim/v7-holdout-real.manifest.json `
  --output work/quick-sim/v7-holdout-real-reality.json

.\tools.cmd nba-player-holdout-gate `
  work/quick-sim/v7-holdout-real-players.json `
  experiments/gates/nba-player-holdout-v7-long-v1.json `
  work/quick-sim/v7-holdout-real-player-gate.json

.\tools.cmd nba-quick-sim-consistency `
  work/quick-sim/v7-holdout-aggregate.json `
  work/quick-sim/v7-holdout-real.json `
  work/quick-sim/v7-holdout-consistency.json `
  --gate experiments/gates/quick-sim-engine-consistency-v7-long-v1.json `
  --aggregate-manifest work/quick-sim/v7-holdout-aggregate.manifest.json `
  --full-manifest work/quick-sim/v7-holdout-real.manifest.json
```

Any non-zero result is a retained failed candidate, not permission to retune against this seed.
Only three passed reports authorize creation of a new v7 candidate receipt. That receipt may state
that v6 is superseded for current simulation semantics, but it must not edit or delete the v6
historical receipt, merge the WIP branch, tag, or create a release.

## Completed result

Both batches completed 30 seasons and all three frozen gates passed. The tracked compact evidence
is `experiments/promotion/nba-quick-sim-executor-v7-candidate.json`. The full engine produced pace
`98.5706`, offensive rating `116.4386`, home win rate `0.5079`, and player MAE values of `3.2084`
minutes, `0.0465` usage, `0.0376` true shooting, and `0.0726` shot structure. Aggregate/full team
rank Spearman was `0.7561` against the frozen `0.75` minimum.

The freeze commit passed a clean CPython 3.12 checkout gate: 694 tests collected, 692 passed, two
environment-specific skips, strict mypy, and 85% coverage. Isolated sdist/wheel construction and a
fresh wheel install smoke also passed. Remote CI run `31888541136` passed Ubuntu, Windows, and
package-smoke jobs for freeze commit `4081f97`. The receipt remains `candidate-pass`: the CLI
default and release registry remain v6, and no merge/tag/release occurred. A separate merge review
is still required.
