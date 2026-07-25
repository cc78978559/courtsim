# Changelog

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
