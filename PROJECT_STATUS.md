# CourtSim project status

Status date: 2026-07-25

CourtSim is a local-first, no-UI basketball game simulator. It uses a layered
conditional-probability model, deterministic state machines, and an event-sourced
statistics ledger rather than continuous court physics.

## Current versions

- Latest mechanics: schema `demo-v1.12`, parameters `demo-1.4.0`.
- Frozen realism baseline: `demo-1.4.0`.
- Latest completed mechanic: formal late-game intentional fouls, including non-bonus
  inbound continuation and explicit clock cost.

The latest mechanics are now the formal baseline after a complete independent
100-game event audit, realism scoring, manifest verification, and regression-gate
promotion.

## Implemented

- Deterministic action segment, possession, quarter, and regulation-game runtimes.
- Three same-level offensive plans: ball screen, isolation, and off-ball action.
- Player-aware probabilities driven by 20 abilities and 17 editable tendency values.
- Defensive coverage, matchup interaction, shooting, blocks, turnovers, assists,
  rebounds, shooting fouls, free throws, non-shooting fouls, team bonus, late-game
  tempo, and intentional-foul execution.
- Canonical JSONL event ledgers, replay, SHA-256 manifests, and statistics attribution.
- Parallel deterministic batches, resumable experiment matrices, paired-seed
  counterfactuals, multi-seed robustness checks, and realism/regression gates.
- Read-only artifact inventory, hash-verified archive planning, independent archive
  verification and restore, and draft retention-policy regression checks.

## Validation

- Ruff formatting and lint: passed.
- mypy strict: passed.
- pytest: 266 passed; one Windows symlink test skipped when link privileges are absent.
- Coverage: 86%, with a required minimum of 85%.
- Runtime dependencies: Python standard library only.
- Frozen `demo-1.4.0` audit: 10 core realism targets, 3 free-throw targets, and
  37 regression gates passed.
- Linux and Windows run the same quality gate in GitHub Actions.

Run the complete local gate with:

```powershell
.\tools.ps1 check
```

## Known gaps

- Substitutions, rotations, fatigue, injuries, and lineup scheduling.
- Overtime and several special-rule branches, including offensive and technical fouls.
- Broader offensive vocabulary and stronger player-level usage calibration.
- Multi-team and player-level real-data calibration beyond the current selected targets.
- Season schedule, roster management, transactions, development, and fantasy-manager
  gameplay.

## Repository boundary

Generated `work/` artifacts, virtual environments, caches, coverage databases,
downloaded wheel files, and machine-specific governance reports are intentionally
excluded from Git. Reproducible policies, experiment definitions, source code, tests,
and human-readable progress documentation are versioned.
