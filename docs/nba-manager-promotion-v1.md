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
Raw payloads and their manifest remain under `.cache/`; they are not Git inputs. The compact source
records explicit source/fallback provenance for every age, salary, contract term and Bird-rights
value. `nba-manager-state-build` requires at least 95% source age coverage and 90% reality-minute-
weighted source salary coverage before marking a state formally eligible.

The state checkpoint, cell states and progress data live in ignored
`work/manager-promotion/`. Every source/arm/season cell is gzip-compressed and contains only state,
compact management audit and metrics. No possession log is retained. Plan, initial state, cells,
progress, report and manifest are SHA-256 bound; resume verifies the complete prefix without replay.
Scheduling options such as worker count and maximum newly executed sources do not enter the semantic
configuration hash.

## Commands

Build the local source and initial state:

```powershell
courtsim nba-manager-source-sync <player-targets> <identity-crosswalk> `
  work/manager-promotion/management-source.json --cache .cache/nba-manager-source
courtsim nba-manager-state-build <player-targets> `
  work/manager-promotion/management-source.json <shot-profiles> <team-strength> `
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
  work/manager-promotion/formal-v1 --workers 4 --maximum-new-sources 2
courtsim nba-manager-study-status work/manager-promotion/formal-v1
courtsim nba-manager-study-verify work/manager-promotion/formal-v1/report.json
```

During the formal holdout, inspect only status/manifest health. Do not change code, inputs, weights
or thresholds, and do not reread the same holdout after lowering a failed threshold.

## Gate and governance

The evaluator uses season weights 0.10/0.15/0.20/0.25/0.30 and utility weights 35/15/20/15/10/5
percent for win rate, postseason progress, player assets, seven-year draft assets, cap health and
core continuity. It computes the confidence interval over thirty source-level paired effects.
Negotiation efficiency is reported separately and cannot improve utility.

Any illegal transaction, unplayable roster, broken state chain, configuration drift, unauthorized
execution or failed v7 macro gate is a hard failure. The numerical thresholds are serialized into
the plan and evidence report. Completion emits `candidate-pass` or `candidate-fail`; both remain
Shadow.

Only after clean-checkout tests, strict mypy, 85% coverage, Ubuntu CI, Windows CI and wheel smoke
all pass may `nba-manager-study-receipt` write
`experiments/promotion/nba-manager-policy-v1-candidate.json`. The receipt must say
`wip-not-promoted`, `active_registry_modified: false` and `release_created: false`. PR #45, v7
candidate evidence and the v6 release registry remain unchanged.
