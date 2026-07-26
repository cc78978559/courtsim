# Changelog

## [0.13.0] - 2026-07-26

- Add deterministic annual prospect classes with reserved stable player identities.
- Generate field-level current abilities, potential ceilings, archetypes, ages, size classes,
  and development traits from isolated semantic random addresses.
- Preserve preloaded complete classes, reject ambiguous partial classes, and detect ID collisions.
- Inject identical annual classes into incumbent/Shadow league experiments and retain their
  complete audit payload.

## [0.12.0] - 2026-07-26

- Add a strict, deterministic league-state payload for manager experiments.
- Connect real regular seasons and sampled playoff brackets to the paired experiment runner.
- Derive career summaries and execute growth, retirement, contracts, draft, and free agency.
- Apply incumbent and white-box Shadow offseason policies with common random numbers.
- Emit complete season/playoff/offseason audit payloads and normalized manager outcomes.

## [0.11.0] - 2026-07-26

- Add resumable incumbent/Shadow manager experiment orchestration across independent sources.
- Carry isolated arm state through exact multi-season horizons from one shared initial state.
- Persist source/arm/season cells with request, state, and execution digests.
- Reuse only verified completed cells after interruption and reject conflicting plans.
- Recompute manager evidence from stored outcomes and bind plans, cells, reports, and manifests.

## [0.10.0] - 2026-07-26

- Add exact-address paired incumbent/Shadow manager outcomes across multiple seasons.
- Add source-isolated evidence gates for utility, win rate, loss frequency, and worst-source
  safety.
- Prevent sample-count-only promotion and repeated-seed pseudo-replication.
- Add evidence digests and a strict JSON manager policy release registry.
- Add evidence-required activation, explicit rejection, retirement, and safety rollback.

## [0.9.0] - 2026-07-26

- Add a generic white-box manager decision contract with hard rejections, rational scoring,
  a reasonable-choice band, and bounded personality contributions.
- Add validated manager profiles, deterministic candidate ordering, incumbent comparisons,
  and immutable decision ledgers.
- Add non-executing draft and free-agency Shadow policies that emit canonical `DraftPlan`
  and `MarketPlan` values for replay through the existing rule engines.
- Enforce roster and salary-cap legality before manager style can influence a choice.

## [0.8.0] - 2026-07-26

- Add immutable player career state with field-level potential and no global overall rating.
- Add player-addressed annual ability growth, age decline, injury burden, and retirement.
- Add explicit draft-pick ownership, ordered selections, roster insertion, and rookie contracts.
- Add a canonical offseason pipeline for retirement, expirations, draft, and free agency.
- Add strict offseason JSON, full replay audits, and frozen career/draft governance.

## [0.7.0] - 2026-07-26

- Add a deterministic four-team playoff bracket with 1/3/5/7-game series.
- Enforce canonical seed pairings, game addresses, and configurable home-court patterns.
- Derive series winners, advancement, finals, and champion from the game ledger.
- Add strict playoff JSON, bracket replay audits, and frozen playoff governance.

## [0.6.0] - 2026-07-25

- Add canonical multi-year player contracts with salary and term limits.
- Add team payroll and salary-cap validation tied to roster ownership.
- Add deterministic contract-year advancement and expiration into free agency.
- Add ordered, atomic waiver and free-agent signing plans.
- Add strict management JSON, payroll/action audits, and frozen contract governance.

## [0.5.0] - 2026-07-25

- Add league-wide unique player ownership and configurable roster-size contracts.
- Add deterministic effective-day player transfers with complete preflight validation.
- Preserve fatigue, injury, and return state when a player changes teams.
- Rebuild source lineups and rotations while adding acquired players to destination roster order.
- Add season schema v2 transfer ledgers and initial/final roster snapshots with v1 read support.

## [0.4.0] - 2026-07-25

- Add immutable, validated multi-team schedules with stable game identifiers.
- Carry bounded fatigue between games and apply deterministic off-day recovery.
- Add isolated deterministic injury rolls, availability, return dates, and injury-safe rotations.
- Derive canonical forfeits, standings, season audits, and strict season JSON artifacts.

## [0.3.0] - 2026-07-25

- Add full-roster identity and active-lineup contracts.
- Add deterministic clock-addressed rotation schedules and canonical substitution events.
- Derive player seconds from possession lineups and serialize the complete ledger with game schema
  v2 while retaining v1 decoding.
- Add versioned, bounded fatigue load, bench recovery, explicit ability feedback, and rotation
  audits.

## [0.2.0] - 2026-07-25

- Add opt-in deterministic overtime with explicit completion and safety-limit reasons.
- Add roster-order foul-out replacement and explicit no-legal-lineup termination.
- Add canonical offensive-foul and technical-foul events with schema-v5 compatibility.
- Add the versioned `nba-v1` period, overtime, and final-two-minute team-foul rules.

All notable user-visible changes are recorded here. CourtSim follows Semantic Versioning
for the Python engine; model structure and parameter versions are tracked separately.

## [0.1.0] - 2026-07-25

### Added

- Deterministic action, possession, regulation-game, batch, replay, and audit runtimes.
- Player-aware probability model through `demo-v1.12 / demo-1.4.0`.
- Event-sourced statistics, SHA-256 manifests, experiment matrices, realism targets,
  regression gates, and artifact-governance tooling.
- Linux and Windows CI with formatting, lint, strict typing, tests, and coverage.

### Fixed

- Preserved audited file hashes across Windows checkouts.
- Restored Python 3.11 compatibility for runtime generic constructions.
- Updated default model audit and benchmark commands to use the frozen model.
