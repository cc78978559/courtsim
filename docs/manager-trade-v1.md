# White-box manager trades v1

Status: local release candidate, 2026-07-26.

## Inheritance from MythicMons

CourtSim reuses the domain-independent architecture proven in the MythicMons sports market:

- compare utility before and after an offer;
- evaluate both participants independently;
- reject illegal assets before preferences are scored;
- keep personality inside a bounded reasonable-choice band;
- require explicit evidence before policy authority can be promoted.

It does not reuse Pokémon family, type coverage, rarity, battle-role, or market-value weights.
Basketball value is rebuilt from current ability, field-level potential, upside, age, injury
burden, salary efficiency, roster balance, cap flexibility, and draft-pick round.

## Canonical trade engine

`trades.py` defines one bilateral offer containing sorted player IDs and draft selection
numbers sent by each team. A legal trade:

1. references two known and distinct teams;
2. contains assets owned by the sending team;
3. leaves both rosters within configured bounds;
4. leaves both payrolls under the hard salary cap;
5. satisfies configured incoming-salary matching above the threshold;
6. moves each player's existing contract with the player;
7. changes draft-pick ownership without changing original ownership.

The engine computes the complete final state before returning it. Illegal offers raise before
any state is exposed, so there is no partial player, contract, or pick movement. `audit_trade`
replays the offer from the initial state and verifies exact equality.

## Bilateral manager approval

`evaluate_trade_shadow` creates an independent `accept` versus `reject` decision for each
manager. The accept candidate exposes rational contributions for player assets, draft assets,
roster balance, and cap flexibility. Star preference and continuity are bounded style signals.

A trade is approved only when:

- the canonical engine finds no hard rejection;
- both managers select `accept`;
- both accept candidates meet the minimum rational-gain gate.

The returned result contains both full decision traces and an immutable two-record ledger.
The function has `SHADOW` authority and never calls `apply_trade`.

## Current boundary

This version supplies the transaction and approval foundation. It does not yet generate offers,
negotiate counters, model pick protections or swaps, trade picks from future season ledgers, or
insert approved offers into the multi-season league adapter. Those are the next integration
layer and require paired evidence before any authority beyond Shadow.
