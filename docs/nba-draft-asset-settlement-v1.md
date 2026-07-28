# CourtSim NBA draft asset settlement v1

`nba-draft-asset-settlement-v1` applies the complete NBA lottery result to persistent future
pick assets. First-round protections and swap rights use the final post-lottery slot, while
later rounds retain the pre-lottery worst-to-best order.

Ownership changes never alter a pick's original-team identity. A protected traded pick returns
to its original team for the current draft and rolls the obligation according to its existing
deferral terms. Swap controllers receive the better final slot only when they still own their
native pick.

The operation returns the NBA lottery ledger together with the atomic draft-asset settlement,
including protected, rolled, and exercised-swap identifiers.
