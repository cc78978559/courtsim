# NBA manager policy promotion v1

This document freezes the WIP-only promotion design for the thirty-team front-office policy.
It does not activate a policy, modify the release registry, create a tag, or authorize a release.

## Causal design

Each source is one independent focal-team pairing. The control arm gives all thirty teams
`nba-front-office-reality-baseline-v1`; the treatment arm changes only the focal team to
`nba-front-office-whitebox-v1`. Both arms start from the same source-pinned franchise state and
master seed. The focal team retains its policy for five consecutive seasons. The other twenty-nine
teams provide league-realism and negotiation-externality audits, but are not treated as independent
effect observations.

The formal study is frozen at thirty sources, seeds `20270401` through `20270430`, five seasons and
two arms: 300 complete-engine seasons. The development-only range is `20270301` through `20270308`
for eight three-season sources. Development evidence can never produce a candidate receipt.

The baseline uses only observable scouting, current ability, age, roster need, contracts and the
shared legal ledgers. It cannot read hidden potential. Draft weights are 55/30/15 for scouted
potential/current ability/need. Free-agency weights are 45/25/20/10 for ability/age projection/need/
contract value. Its neutral trade evaluator shares canonical bilateral, three-team v2, CapLedger,
Bird-rights, obligation/freeze and atomic settlement validation with the candidate.

## Frozen inputs and storage boundary

`nba-manager-source-sync` caches keyless ESPN athlete and historical contract responses locally.
Raw payloads remain under `.cache/`. The compact, normalized formal source is frozen at
`experiments/inputs/nba-manager-state-source-2025.json`; it records explicit source/fallback
provenance for every age, salary, contract term and Bird-rights value. `nba-manager-state-build`
requires at least 95% source age coverage and 90% reality-minute-weighted source salary coverage
before marking a state formally eligible.

The state checkpoint, cell states and progress data live in ignored
`work/manager-promotion/`. Every source/arm/season cell is gzip-compressed and contains only state,
compact management audit and metrics. No possession log is retained. Plan, initial state, cells,
progress, report and manifest are SHA-256 bound; resume verifies the complete prefix without replay.
Scheduling options such as worker count and maximum newly executed sources do not enter the semantic
configuration hash.

The study rejects a state-build receipt unless its exact schema, source coverage, serialized state
hash and checkpoint receipt all match the loaded checkpoint. The plan also pins the Git commit and
a content hash of every executable `courtsim` Python source file, so a receipt cannot be relabelled
with a later commit.

## Commands

Reconstruct the frozen initial state on any machine. The receipt stores only the checkpoint file
name, so its SHA-256 is independent of the checkout directory and operating system:

```powershell
courtsim nba-manager-state-build `
  experiments/inputs/nba-player-targets-2024-25.json `
  experiments/inputs/nba-manager-state-source-2025.json `
  experiments/inputs/nba-2024-25-team-shot-profiles-calibrated.json `
  experiments/sources/nba-2024-25-team-strength-035-v1.json `
  work/manager-promotion/initial-franchise.json.gz `
  work/manager-promotion/initial-franchise-receipt.json
```

Run or resume the frozen formal study. Omit `--development`, `--sources`, `--seasons` and
`--seed-start`; the CLI then enforces the formal 30 x 5 identity:

```powershell
courtsim nba-manager-study-run `
  work/manager-promotion/initial-franchise.json.gz `
  work/manager-promotion/initial-franchise-receipt.json `
  <shot-profiles> <macro-reference> experiments/sources/nba-manager-profiles-v1.json `
  work/manager-promotion/formal-v1 `
  --player-targets experiments/inputs/nba-player-targets-2024-25.json `
  --state-build-source experiments/inputs/nba-manager-state-source-2025.json `
  --protocol experiments/promotion/nba-manager-policy-v1-protocol.json `
  --workers 4 --maximum-new-sources 2
courtsim nba-manager-study-status work/manager-promotion/formal-v1
courtsim nba-manager-study-verify work/manager-promotion/formal-v1/report.json
```

During the formal holdout, inspect only status/manifest health. Do not change code, inputs, weights
or thresholds, and do not reread the same holdout after lowering a failed threshold.

## Gate and governance

The evaluator uses season weights 0.10/0.15/0.20/0.25/0.30 and utility weights 35/15/20/15/10/5
percent for win rate, postseason progress, player assets, seven-year draft assets, cap health and
core continuity. It computes the confidence interval over thirty source-level paired effects.
Negotiation efficiency, average rounds, positive-gain executions, no-counter terminations,
round-limit exhaustion and stale rejections are reported separately and cannot improve utility.

Any illegal transaction, unplayable roster, broken state chain, configuration drift, unauthorized
execution or failed v7 macro gate is a hard failure. The numerical thresholds are serialized into
the plan and evidence report. Completion emits `candidate-pass` or `candidate-fail`; both remain
Shadow.

Macro reality is evaluated on the complete control and treatment season batches, not on individual
seasons. This preserves the semantics of metrics such as mean champion seed and playoff upset rate.
The compact audit additionally records home win rate, injury incidence and the calendar span,
game-day, league-off-day, daily-volume, back-to-back, rest and consecutive-game distributions.

Only after clean-checkout tests, strict mypy, 85% coverage, Ubuntu CI, Windows CI and wheel smoke
all pass may `nba-manager-study-receipt` write
`experiments/promotion/nba-manager-policy-v1-candidate.json`. The receipt must say
`wip-not-promoted`, `active_registry_modified: false` and `release_created: false`. PR #45, v7
candidate evidence and the v6 release registry remain unchanged.

Every `--ci` value must be `NAME=passed@COMMIT@RUN_URL`; the commit must match the frozen study and
the URL must identify a successful run in the canonical `cc78978559/courtsim` repository. The six
governance proof names map to the existing Ubuntu/Windows/package jobs and, where relevant, their
successful named steps. The same run URL may support several proofs without duplicating the
workflow. All six proof names must be supplied exactly once.

PR #46 is stacked on PR #45. Merge #45 with a merge commit to preserve ancestry. If #45 is squash-
or rebase-merged, rebase the two #46 commits onto the resulting `main` before retargeting #46.
