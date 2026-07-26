# Playoffs v1

CourtSim `0.7.0` adds a deterministic four-team playoff resolver above the game and season
layers. It consumes completed game scores and does not introduce a new random stream.

## Bracket contract

Exactly four unique teams are seeded contiguously from one through four. The semifinals are
fixed as seed 1 versus 4 and seed 2 versus 3. Their winners advance to the championship
series; the better original seed retains higher-seed status in the final.

Playoff v1 intentionally fixes the field at four teams. Larger fields and play-in games are
deferred so that bracket-slot semantics can be versioned explicitly later.

## Series and home court

`PlayoffConfig` supports best-of-1, 3, 5, or 7 series. A boolean tuple contains one entry for
every possible game: `true` means the higher seed hosts. The frozen best-of-7 default is
`H, H, L, L, H, L, H`.

Every `PlayoffGame` records round, series, game number, home and away team IDs, and the final
score. Ties are illegal. Games must appear in bracket order, match the configured home-court
pattern, and stop immediately when one team reaches the required wins.

## Derived facts

`resolve_playoffs` derives all three series, higher/lower-seed win totals, advancing teams,
and champion from the ordered game ledger. It rejects incomplete series and any game after
the championship is decided.

`audit_playoffs` independently replays the ledger and reports teams, completed series, games,
sweeps, series that reached the maximum game, and champion.

## Serialization

Playoff schema v1 stores the exact config, seeds, ordered games, and champion. The strict
decoder rejects unknown or missing keys, resolves the bracket again, and verifies that the
stored champion is derived rather than asserted independently.

The frozen configuration is
[`governance/playoffs-v1.json`](../governance/playoffs-v1.json).

## Validation evidence

- focused config, seeding, home-court, advancement, incomplete/extra-game, audit, and JSON tests;
- Ruff formatting and lint checks;
- full Python 3.11 strict typing;
- 324 passing tests with one Windows symlink test skipped;
- 85% coverage, meeting the project quality gate.
