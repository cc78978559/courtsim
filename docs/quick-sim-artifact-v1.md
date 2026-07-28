# CourtSim quick simulation artifact v1

`quick-sim-artifact-v1` turns the deterministic batch protocol into a crash-resilient local
workflow. It writes an atomic checkpoint after every completed season. If execution stops,
the next run verifies and resumes the contiguous prefix without executing completed seasons
again.

Each receipt records the absolute artifact path, number of seasons before and after the run,
completion state, logical batch digest, and physical file SHA-256. Batch identity must match
an existing checkpoint exactly. The protocol assumes one writer per checkpoint.

A complete checkpoint can be exported as an observed `quick-sim-comparison-v1` reference.
The reference uses canonical JSON and returns its own file-hash receipt. Partial batches are
rejected so an interrupted data collection cannot be presented as a completed benchmark.
