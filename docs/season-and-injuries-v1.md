# Season and injuries v1

CourtSim `0.4.0` adds an opt-in deterministic layer above the canonical game runtime. It
does not change the frozen `demo-v1.12 / demo-1.4.0` possession probability baseline.

## Schedule contract

`SeasonSchedule` contains a unique ordered team list and games ordered by `(day, game_id)`.
Game identifiers are unique, teams cannot play themselves, and every game must reference
teams declared by the schedule.

The runtime processes games chronologically because fatigue and availability are persistent.
Each game's simulation seed is derived from the season master seed and stable `game_id`.

## Cross-game state

Every rostered player has canonical season state:

- team and player identity;
- bounded fatigue carried from the prior game;
- the first day on which the player is available again.

Before a team's game, each complete rest day removes
`daily_fatigue_recovery` fatigue points. Consecutive-day games have no off-day recovery.
The game runtime accepts the resulting complete initial-fatigue map and records its normal
possession snapshots and final-fatigue ledger.

## Injury and availability contract

After a completed game, every player with recorded playing time receives a deterministic
injury roll addressed by master seed, `injury-v1`, game ID, player ID, and draw purpose.
The injury roll cannot consume or shift any game random value.

An injury records the team, player, source game, injury day, and return day. Until the return
day the player is removed from the game roster, active lineup, and every scheduled rotation
stint. Remaining available players fill open lineup positions in roster order. A team with
fewer than five available players forfeits; if both teams are short, the canonical result is
a scoreless tie with the home team recorded as the first forfeiting side.

Default frozen configuration:

- injury probability: 35 basis points per player appearance;
- days out: 1 through 7;
- off-day fatigue recovery: 2,500 points;
- forfeit score: 1.

## Results and audit

`SeasonResult` contains the exact schedule, ordered game records, unavailable-player lists,
nested canonical game results, standings, injuries, and final player states. Standings derive
only from game records and sort by wins, losses, point differential, points scored, then team
ID. Ties are explicit.

The strict schema-v1 JSON codec rejects unknown or missing keys and revalidates nested game
results, standings, injuries, and player state. `audit_season` reports scheduled/completed
games, forfeits, injuries, missed player-games, and standings win/loss balance.

The machine-readable frozen configuration is
[`governance/season-injury-v1.json`](../governance/season-injury-v1.json).

## Validation evidence

- focused Phase 4 schedule, fatigue, injury, forfeit, standings, audit, and serialization tests;
- deterministic reruns with immutable input teams;
- injury-on/off comparison proving the first game's canonical event stream is unchanged;
- full Ruff, strict mypy, pytest, coverage, Ubuntu CI, and Windows CI gates.
