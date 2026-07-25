# Changelog

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
