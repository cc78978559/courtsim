# CourtSim project status

Status date: 2026-07-26

CourtSim is a local-first, no-UI basketball game simulator. It uses a layered
conditional-probability model, deterministic state machines, and an event-sourced
statistics ledger rather than continuous court physics.

## Current versions

- Engine release candidate: `0.37.0`.
- Latest mechanics: schema `demo-v1.12`, parameters `demo-1.4.0`.
- Frozen realism baseline: `demo-1.4.0`.
- Game rules: `nba-v1`.
- Rotation and fatigue state: `rotation-v1 / fatigue-v1`.
- Season and injury state: `season-v1 / injury-v1`.
- Roster transaction state: `roster-v1`; season result schema `2`.
- Contract and free-agency state: `contract-v1 / free-agency-v1`.
- Playoff state: `playoff-v1`; playoff result schema `1`.
- Career, draft, and retirement state: `career-v1 / draft-v1 / retirement-v1`;
  offseason schema `1`.
- White-box manager policy and decision ledger: `manager-ai-v1`; default authority
  `shadow`.
- Unified manager stage authority and execution receipts: `manager-authority-v1`.
- Annual white-box manager strategy objectives: `manager-objective-v1`.
- Manager counterfactual evidence and release registry:
  `manager-evidence-v1 / manager-release-registry-v1`.
- Resumable paired manager experiment orchestration: `manager-experiment-v1`.
- Real season/playoff/offseason experiment adapter: `manager-league-adapter-v1`.
- Annual deterministic draft classes: `prospect-generation-v1`.
- White-box manager lineups and playing time: `manager-rotation-v1`.
- Atomic bilateral trades and white-box approval: `trade-v1 / manager-trade-v1`.
- Deterministic offer generation and conflict-free clearing: `trade-market-v1`.
- Persistent future picks, protections, and swap rights: `draft-asset-v1`.
- Weighted first-round lottery and Stepien safety: `draft-lottery-v1`.
- Native routed three-team transactions: `three-team-trade-v1`.
- Automatic cyclic/hub three-team discovery and unified clearing: `three-team-market-v1`.
- Team-specific hidden-potential scouting: `scouting-v1`.
- Bird rights, aprons, salary tiers, and trade exceptions: `cap-mechanics-v1`.
- Thirty-team schedule, play-in, and full bracket: `nba-league-v1`.
- Cross-season opponent modeling: `manager-learning-v1`.

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
- Deterministic multi-team schedules, cross-game fatigue recovery, player availability,
  injuries and return dates, forfeits, standings, season audits, and strict season JSON.
- League-wide roster ownership, size bounds, scheduled player transfers, state continuity,
  legal post-transfer lineups/rotations, and initial/final roster ledgers.
- Multi-year contracts, salary bounds and team caps, deterministic expirations, free-agent
  pools, ordered sign/waive plans, and auditable management JSON.
- Deterministic four-team playoff seeding, best-of series, home-court patterns, bracket
  advancement, championship resolution, strict JSON, and replay audits.
- Immutable career state, field-level potential, player-addressed annual growth and decline,
  injury burden, retirement, explicit draft-pick ownership, rookie contracts, and a canonical
  retirement/expiration/draft/free-agency offseason pipeline.
- Auditable white-box manager profiles and deterministic draft/free-agency Shadow policies
  with hard legality gates, bounded personality, incumbent comparison, and decision ledgers.
- Exact paired, multi-season manager evidence with independent-source protection, explicit
  performance/safety gates, evidence digests, activation, rejection, and rollback.
- Resumable incumbent/Shadow experiment cells with isolated multi-season state continuity,
  request/execution digests, derived evidence reports, and hash-verified manifests.
- Strict league-state serialization and a real four-team adapter spanning schedules, games,
  playoffs, careers, retirement, contracts, draft, free agency, and manager outcome metrics.
- Address-stable annual prospects with archetypes, 20 current abilities, field-level potential,
  age, size, and complete development traits shared across paired policy arms.
- Auditable manager starters, rotation groups, emergency depth, clock-addressed stints, and
  official young-player playing time feeding the career loop.
- Atomic player/contract/draft-pick trades with ownership, roster, cap, salary-matching, and
  replay gates, plus independent bilateral manager approval in Shadow mode.
- Deterministic direct/counteroffer generation, positive-surplus ranking, asset locking, and
  preseason Shadow-market execution inside real multi-season manager experiments.
- Bounded three-round bilateral negotiation trees with parent offers, additional-pick final
  counters, repeated white-box approval, and explicit accepted/round-limit/no-counter outcomes.
- Stable future-pick ownership across seasons, top-N protection and deferral, one-way
  better-slot swaps, and standings-addressed annual settlement into the draft.
- Addressed weighted lottery draws, round-specific order settlement, consecutive-future-first
  trade safety, and bounded two-for-one white-box trade packages.
- Native three-team player/pick routing with simultaneous legality, atomic contract and asset
  movement, replay audit, and unanimous three-manager Shadow approval.
- Deterministic cyclic three-team discovery, bounded future-pick compensation, positive-surplus
  selection, team locking, and gain-based clearing against the bilateral market.
- Round-robin hub-team packages and two-round, two-pick compensation chains with stable parent
  identifiers and fixed per-family search budgets.
- Salary-aware hub candidate ordering based on aggregate net player-salary imbalance, with
  stable low-imbalance tie-breaking and explicit audit values.
- Field-level prospect uncertainty with team-specific reports, exposure-driven confidence,
  hidden true potential, and direct integration into Shadow draft decisions.
- Non-Bird, Early Bird, and Full Bird over-cap signing paths, first/second aprons, three salary
  matching tiers, and immutable expiring trade-exception ledgers.
- A deterministic 30-team schedule containing exactly 1,230 games and 82 games per team,
  conference play-in resolution, and a validated 16-team/15-series postseason path.
- Division-aware NBA series allocation with four games against every division opponent,
  6/4 four-game/three-game same-conference opponents, two games against every opposite-
  conference opponent, 41 balanced home games, and conflict-free deterministic game days.
- Games-weighted opponent memories across seasons and bounded matchup contributions that
  directly alter the existing white-box rotation selector.
- Evidence-scaled opponent tactics that change offensive play-family selection, defensive
  coverage selection, and tempo in both regular-season and postseason games, with explicit
  matchup audit values and bounded behavior for sparse samples.
- Event-ledger opponent observations using possession-normalized offense/defense, clock-
  normalized pace, and actual three-point/rim shot zones, closing the automatic multi-season
  feedback path into matchup tactics.
- Canonical Shadow/Assist/Active authority semantics across draft, free agency, trade, rotation,
  and tactics, including authorization enforcement and per-stage execution receipts.
- Outcome-responsive matchup tactics that keep opponent style direction separate from bounded
  intensity feedback derived from historical matchup net efficiency.
- Annual contend, develop, rebuild, cap-relief, and balanced objectives derived from roster,
  payroll, and draft-asset context, producing one bounded effective profile shared by draft,
  free agency, trade, and rotation decisions.
- League-state schema 4 persistence for Bird rights, trade exceptions, manager opponent memory,
  and optional 30-team conference/division alignment, with deterministic schema 1/2/3 migration.
- Roster-safe per-game team resolution and opponent-specific white-box rotations throughout
  regular-season games and playoff series, with base behavior for unseen opponents.
- Regular-season fatigue and injury state carried into the postseason, calendar-based recovery
  between games and rounds, new playoff injuries affecting later games, deterministic forfeits,
  and postseason playing time/injury burden feeding annual career development.
- Canonical free-agency, bilateral-trade, and three-team-trade entry points governed by the
  persisted cap ledger, including Bird-rights signings, tiered matching, atomic exception
  creation/consumption, replay verification, and scaled aprons for custom leagues.
- Canonical JSONL event ledgers, replay, SHA-256 manifests, and statistics attribution.
- Parallel deterministic batches, resumable experiment matrices, paired-seed
  counterfactuals, multi-seed robustness checks, and realism/regression gates.
- Read-only artifact inventory, hash-verified archive planning, independent archive
  verification and restore, and draft retention-policy regression checks.

## Validation

- Ruff formatting and lint: passed.
- mypy strict: passed.
- pytest: 458 passed; one Windows symlink test skipped when link privileges are absent.
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

- Broader offensive vocabulary and stronger player-level usage calibration.
- Multi-team and player-level real-data calibration beyond the current selected targets.
- Full NBA lottery odds and advanced conditional-pick rules, seven-year Stepien edge cases,
  four-plus-round and contract-dependent negotiation, causal tactical experiments,
  human-approved promotion beyond Shadow mode, and fantasy-manager gameplay.

## Repository boundary

Generated `work/` artifacts, virtual environments, caches, coverage databases,
downloaded wheel files, and machine-specific governance reports are intentionally
excluded from Git. Reproducible policies, experiment definitions, source code, tests,
and human-readable progress documentation are versioned.
