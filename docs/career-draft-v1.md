# Career, draft, and retirement v1

CourtSim `0.8.0` adds a deterministic offseason state machine above the season,
playoff, roster, contract, and free-agency layers. It advances immutable player
snapshots instead of mutating game profiles in place.

## Career state

`CareerPlayer` combines the current `PlayerProfile` snapshot with age, professional
experience, development traits, field-level potential, injury burden, draft history,
and one of four exclusive states: prospect, active, free agent, or retired.

Potential uses the same 20 fields as `AbilityRatings`; there is no simulation-wide
overall rating. Current ability cannot exceed its field-level potential.

## Development and decline

`advance_careers` consumes exactly one `PlayerSeasonSummary` for every active or
free-agent player. Each ability is advanced independently from:

- the player's age relative to the configured peak window;
- growth rate or decline resistance;
- games and seconds played;
- injury days and accumulated injury burden;
- a bounded, ability-addressed annual variation.

Athletic-proxy skills such as rim finishing, point-of-attack defense, steals, and
offensive rebounding decline earlier. Shooting, playmaking, decisions, awareness,
post creation, and screen setting decline later.

Every random value is addressed by season, player, and purpose. Adding or removing
another player cannot perturb an existing player's development or retirement result.

## Retirement

Retirement is derived from age, playing time, injury burden, roster status, and
decline resistance. Players below the configured minimum retirement age cannot
retire; players reaching the maximum age must retire.

Retired players are removed atomically from rosters, free agency, and active
contracts while their career record remains available with `RETIRED` status.

## Draft

Draft v1 consumes explicit, contiguous `DraftPickAsset` and `DraftPlan` ledgers.
Pick assets preserve both original and current ownership. The resolver verifies
pick ownership, round bounds, prospect availability, uniqueness, roster capacity,
salary cap, and rookie contract terms.

A selected prospect becomes active, receives canonical draft history, joins the
pick owner's roster, and receives the configured rookie contract.

Lottery generation, pick protections, scouting uncertainty, and AI selection are
deferred. Explicit plans keep the first version deterministic and auditable.

## Offseason order

`advance_offseason` fixes the transition order:

1. develop and decline eligible players;
2. resolve retirement and remove retired obligations;
3. advance contract years and move expirations into free agency;
4. synchronize career ownership states;
5. execute the draft and rookie contracts;
6. apply the ordered free-agent/waiver market plan;
7. validate and freeze the next-season state.

## Serialization and audit

Offseason schema v1 stores the initial player and management state, summaries,
rules, draft assets and selections, market actions, development changes,
retirements, expirations, and final state.

The strict decoder rejects unknown or missing keys and replays the complete
offseason. Final players, rosters, contracts, free agents, draft facts, rating
changes, and retirement decisions must all derive from their input ledgers.

The frozen defaults are
[`governance/career-draft-v1.json`](../governance/career-draft-v1.json).

## Validation evidence

- deterministic player-addressed growth and decline tests;
- injury-sensitive decline and forced-retirement boundary tests;
- draft ownership, uniqueness, roster, and rookie-contract tests;
- complete retirement, expiration, draft, and market ordering tests;
- strict JSON round trip, tamper rejection, and replay audit tests.
