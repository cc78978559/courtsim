# CourtSim NBA franchise artifact v1

`nba-franchise-artifact-v1` is the strict, cross-process checkpoint for a complete
30-team franchise state. It persists league identity, season counters, contract and
management state, career players, draft assets, manager memories, conference
alignment, and every game team's profiles, strategies, substitution order, and
rotation plan.

The state payload uses canonical JSON and carries an embedded SHA-256 digest. Writes
use the repository's flush, fsync, and atomic-replace path. Each write and verified
load returns a receipt containing both the state digest and complete file digest.
Callers may require the expected file digest when resuming.

Unknown keys, unsupported schemas or versions, malformed teams, a changed state
payload, and a mismatched file digest are rejected. An exact restored state can be
passed directly to the next franchise-season execution.
