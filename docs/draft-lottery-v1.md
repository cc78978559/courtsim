# Draft lottery and Stepien safety v1

Status: local release candidate, 2026-07-26.

## Lottery

The four-team league draws the first two first-round slots without replacement. Reverse
standings establish the candidate order and fixed 40/30/20/10 percent weights. Each draw uses
an isolated semantic random address containing the lottery version, draft year, and slot.

The audit records every candidate and weight, total weight, exact roll, selected team, base
order, and final order. Undrawn teams retain reverse-standings order. Only round one uses the
lottery result; later rounds remain in reverse standings order.

## Stepien approximation

When a trade contains persisted future first-round assets, the canonical legality pass computes
post-trade ownership across every represented future year. A participating team may not end
without any owned first-round pick in consecutive years. The rule counts any owned first,
including another team's asset, and runs before either manager may approve the offer.

This is a conservative version-1 approximation. It does not yet calculate seven-year trade
horizons, conditional-protection worst cases, frozen picks, or every collective-bargaining
exception.

## Multi-player market packages

The deterministic market now generates bounded two-for-one packages in both directions.
Candidate mixing reserves stable capacity for direct swaps, multi-player packages, pick
counteroffers, and player-for-pick offers. Existing roster, salary, Stepien, bilateral approval,
positive-surplus, team-lock, and asset-lock rules apply unchanged.
