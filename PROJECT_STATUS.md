# CourtSim project status

Status date: 2026-07-25

CourtSim is a local-first, no-UI basketball game simulator. It uses a layered
conditional-probability model, deterministic state machines, and an event-sourced
statistics ledger rather than continuous court physics.

## Current versions

- Engine release candidate: `0.3.0`.
- Latest mechanics: schema `demo-v1.12`, parameters `demo-1.4.0`.
- Frozen realism baseline: `demo-1.4.0`.
- Game rules: `nba-v1`.
- Rotation and fatigue state: `rotation-v1 / fatigue-v1`.

The latest mechanics are now the formal baseline after a complete independent
100-game event audit, realism scoring, manifest verification, and regression-gate
promotion.

## Implemented

- Deterministic action segment, possession, regulation, and overtime runtimes.
- Three same-level offensive plans: ball screen, isolation, and off-ball action.
- Player-aware probabilities driven by 20 abilities and 17 editable tendency values.
- Defensive coverage, matchup interaction, shooting, blocks, turnovers, assists,
  rebounds, shooting fouls, free throws, non-shooting fouls, team bonus, late-game
  tempo, and intentional-foul execution.
- Full-roster identity, deterministic clock-addressed rotations, foul-out and scheduled
  substitution resolution, possession-level active lineups, and derived player seconds.
- Bounded active-load fatigue, bench recovery, explicit ability feedback, fatigue snapshots,
  and rotation/fatigue audits.
- Canonical JSONL event ledgers, replay, SHA-256 manifests, and statistics attribution.
- Parallel deterministic batches, resumable experiment matrices, paired-seed
  counterfactuals, multi-seed robustness checks, and realism/regression gates.
- Read-only artifact inventory, hash-verified archive planning, independent archive
  verification and restore, and draft retention-policy regression checks.

## Validation

- Ruff formatting and lint: passed.
- mypy strict: passed.
- pytest: 290 passed; one Windows symlink test skipped when link privileges are absent.
- Coverage: 85%, meeting the required minimum of 85%.
- Runtime dependencies: Python standard library only.
- Frozen `demo-1.4.0` audit: 10 core realism targets, 3 free-throw targets, and
  37 regression gates passed.
- Linux and Windows run the same quality gate in GitHub Actions.

Run the complete local gate with:

```powershell
.\tools.ps1 check
```

## Known gaps

- Injuries and availability across games.
- Broader offensive vocabulary and stronger player-level usage calibration.
- Multi-team and player-level real-data calibration beyond the current selected targets.
- Season schedule, roster management, transactions, development, and fantasy-manager
  gameplay.

## Repository boundary

Generated `work/` artifacts, virtual environments, caches, coverage databases,
downloaded wheel files, and machine-specific governance reports are intentionally
excluded from Git. Reproducible policies, experiment definitions, source code, tests,
and human-readable progress documentation are versioned.
