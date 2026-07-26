# CourtSim NBA franchise runner v1

`nba-franchise-runner-v1` orchestrates a complete franchise across multiple process
invocations. Its run specification fixes the run identity, master seed, and target
number of seasons. Each season seed is addressed by the runner version, run ID, and
absolute completed-season number.

The runner writes an initial state checkpoint and one immutable checkpoint after
every completed season. A manifest is atomically replaced only after the referenced
state file is durable. A crash between those writes may leave an unreferenced file,
but cannot advance the verified prefix.

Resume verifies the specification, initial-state digest, league identity, contract
rules, contiguous completed-season numbers, derived seeds, and every referenced file
and state digest. Already completed seasons are never passed back to the executor.
Callers may bound new work per invocation; calling a completed run is a verified
no-op.
