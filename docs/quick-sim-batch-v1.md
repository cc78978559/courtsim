# CourtSim quick simulation batch v1

`quick-sim-batch-v1` coordinates deterministic, resumable multi-season quick-simulation
studies. A batch fixes its identity, master seed, season count, and team count. Each season
receives an address-derived seed and a stable season identifier, so interrupted and one-shot
execution produce the same result.

Every completed season stores a canonical summary and SHA-256 digest. The checkpoint also
stores a batch digest over the immutable specification and ordered season-summary hashes.
Loading rejects unknown JSON fields, type coercion, gaps, altered summaries, mismatched team
counts, and incorrect completion flags.

Observed season summaries can build a versioned `quick-sim-comparison-v1` reference. Each
metric interval is the observed minimum and maximum; source label, exact game build, roster
date, team count, and season count remain mandatory. This supplies the reproducible collection
path for real NBA 2K observations without inventing target values.
