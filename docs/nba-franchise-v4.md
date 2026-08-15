# CourtSim NBA franchise v4

`nba-franchise-v4` makes roster transactions and the independent salary-cap ledger
part of every composed thirty-team franchise season.

Before the schedule begins, expired trade exceptions are removed and both the
bilateral and native three-team markets run their deterministic white-box searches.
The engine compares the total rational gain of each conflict-free plan and clears
exactly one market family. This preserves the one-trade-per-team season boundary
while retaining complete evaluations and manager decision ledgers for both markets.

Trade legality is evaluated with the same Bird-rights, apron, salary-matching, and
trade-exception ledger used by canonical execution. The winning plan atomically
updates management rosters, contracts, future draft picks, and the cap ledger.
Rotations and game teams are then rebuilt from the traded roster before any regular
season or postseason game is sampled.

The final cap ledger is stored in franchise state, included in canonical checkpoint
hashes, restored on resume, and advanced by season-based trade-exception expiry.
The multi-season runner therefore resumes management, pick, learning, and cap state
as one deterministic franchise prefix.
