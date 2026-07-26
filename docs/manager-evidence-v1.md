# Manager policy evidence v1

Status: local release candidate, 2026-07-26.

## Purpose

`manager-evidence-v1` decides whether a white-box manager policy has enough paired,
multi-season evidence to be considered for activation. It does not run seasons and it never
activates a policy automatically.

## Evidence address

Every observation contains an incumbent outcome and a Shadow outcome with the exact same:

- source identifier;
- master seed;
- season year;
- team identifier.

Duplicate addresses are rejected. One source must retain one master seed across its seasons,
and different sources must use different master seeds. This prevents relabeling repeated output
as independent evidence.

## Outcome metrics

All metrics are normalized to `0..1`:

- regular-season win rate;
- playoff progress;
- roster asset value;
- salary-cap flexibility.

The governed default utility weights are `0.45 / 0.20 / 0.25 / 0.10`. The evaluator also
reports every metric delta independently so a positive composite cannot hide a material
win-rate regression.

## Activation recommendation

The default gate requires:

- at least 30 independent sources;
- at least two distinct seasons per source;
- mean utility improvement of at least `0.005`;
- mean win-rate delta of at least `-0.002`;
- loss rate no greater than `0.45`;
- worst per-source mean utility delta of at least `-0.04`.

Passing sample-count gates alone is insufficient. An evidence result receives a canonical
SHA-256 digest over the policy version, weights, thresholds, and sorted paired observations.

## Release registry

Policies move through `CANDIDATE`, `ACTIVE`, `REJECTED`, and `RETIRED`. Activation requires a
passing evidence result for the exact registered policy version. Activating a candidate retires
the previous active policy. Rollback may restore a retired release without new evidence because
rollback is a safety response.

The registry has strict JSON round-trip support. It maintains exactly one active pointer and
rejects duplicate versions, invalid parents, invalid transitions, and unknown statuses.

## Remaining boundary

Human approval remains outside the registry. A passing result means “eligible for review,” not
“automatically deploy.” CourtSim still needs a season-level experiment runner that generates
the governed outcome records from complete incumbent/Shadow league simulations.
