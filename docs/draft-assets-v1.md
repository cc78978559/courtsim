# Persistent draft assets v1

Status: local release candidate, 2026-07-26.

## Asset identity

Every future pick has a stable positive asset ID, draft year, round, original team, current
owner, top-N protection threshold, and remaining protection deferrals. Trading changes only
the current owner. The original-team identity, draft year, round, and asset ID remain stable.

`DraftAssetLedger` stores future picks, one-way swap rights, and the next unused asset ID. It
rejects duplicate native picks, duplicate asset IDs, duplicate swap IDs, unknown league teams,
and non-canonical ordering. The JSON contract is strict and hash-governed.

## Annual lifecycle

The league adapter maintains a rolling three-draft horizon. At the end of a season:

1. original teams receive slots in reverse standings order;
2. due picks are ordered by round and original-team slot;
3. a traded top-N-protected pick in the protected range stays with its original team;
4. when deferrals remain, the obligation moves onto the next year's native pick;
5. an unprotected or untriggered pick conveys to its current owner;
6. eligible swap rights exchange owners only when the controller receives the better slot;
7. settled picks and expired swap rights leave the future ledger.

The resulting current `DraftPickAsset` values flow through the existing white-box draft and
canonical offseason pipeline. The next league state retains only unsettled future assets.

## Trade integration

Future picks implement the same stable trade identifier used by current picks. The canonical
trade engine, bilateral manager approval, counteroffer generator, and conflict-locking market
therefore accept future assets without weakening ownership checks. Preseason Shadow markets
now receive the persisted future ledger and may include picks in approved packages.

## Current boundary

Version 1 supports top-N protection with bounded annual deferral and one-way better-slot swaps.
It does not yet support lottery drawings, second-round conditional ranges, multi-outcome
conversion, pick freezes, Stepien-rule legality, cash, trade exceptions, or multi-team trades.
