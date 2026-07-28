# Deterministic trade market v1

Status: local release candidate, 2026-07-26.

## Purpose

`trade-market-v1` turns the single-offer trade and manager-approval contracts into a bounded
league market. It follows the MythicMons market-flow pattern while retaining CourtSim's own
basketball valuation and transaction rules.

## Candidate flow

For every ordered pair of teams, the market generates stable candidates from:

1. one-player-for-one-player direct offers;
2. a direct offer plus one currently owned draft pick from either side;
3. one player for one currently owned draft pick;
4. bounded two-for-one player packages.

Each non-direct candidate records a parent direct-offer ID. Generation is bounded per team
pair and never uses random sampling, so input state fully determines candidate identity.

Candidates form explicit negotiation trees. A direct offer is round one, the existing
player/pick alternatives are round two, and a legal round-two offer rejected by exactly one
manager may receive round-three pick compensation from the other team. Both managers then
re-evaluate the complete package. Round-three generation is capped globally, and every
negotiation terminates as accepted, round-limit, or no-counter.

Every candidate is sent through canonical trade legality and two independent white-box manager
decisions. Approved candidates are ranked by combined rational gain and then stable offer
identity. A positive combined-gain floor prevents zero-surplus roster churn.

## Clearing

The clearing pass locks both participating teams and every included player and pick. Version 1
permits at most one selected trade per team, eliminating stale simultaneous valuations and
preventing one asset from entering multiple offers. Selected offers form a canonical
`TradeMarketPlan` and replay sequentially through `apply_trade`; every transition receives its
own replay audit.

Generation remains `SHADOW`. The production manager experiment adapter applies its selected
plan only inside the Shadow experiment arm before the season begins. Incumbent state remains
unchanged, and the audit payload records candidate summaries, approvals, selected offers,
negotiation IDs and rounds, terminal summaries, execution audits, and the manager decision
ledger.

## Current boundary

The adapter supplies the persisted three-year pick inventory defined by `draft-asset-v1`.
Future-year picks, top-N protections, one-way swaps, multi-player packages, three-round
negotiation, and trade exceptions are therefore live inputs. Deadlines, contract-dependent
packages, and conditional multi-outcome conversion remain future versioned work.
